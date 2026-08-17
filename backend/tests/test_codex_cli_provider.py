from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from backend.app.ai import AIInput, AIProviderError, CodexCliProvider
from backend.app.config import Settings


VALID_RESULT = {
    "direct": "可以，请把具体需求、截止时间和参考资料发来，我先确认工作范围。",
    "friendly": "您好，可以先说下想实现的功能，并附上截止时间和参考案例，我帮您看看。",
    "conversion": "您把需求文档、期望时间和参考资料发我，确认范围后我们再继续沟通。",
    "risk_level": "low",
    "risk_reasons": [],
    "needs_human_confirmation": True,
}


def make_fake_codex(
    tmp_path: Path,
    outputs: list[str],
    *,
    logged_in: bool = True,
    delay: float = 0,
) -> tuple[Path, Path]:
    script = tmp_path / "fake-codex"
    counter = tmp_path / "counter.txt"
    # /usr/bin/env avoids an invalid shebang when the unified project path
    # contains spaces (the production Codex executable is unaffected).
    source = f"""#!/usr/bin/env python3
import pathlib
import sys
import time

args = sys.argv[1:]
if args == ["exec", "--help"]:
    print("--output-schema --output-last-message --ephemeral --sandbox --model --config")
    raise SystemExit(0)
if args == ["login", "status"]:
    print({('"Logged in using ChatGPT"' if logged_in else '"Not logged in"')})
    raise SystemExit({0 if logged_in else 1})
if args and args[0] == "exec":
    sys.stdin.read()
    time.sleep({delay!r})
    counter = pathlib.Path({str(counter)!r})
    value = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(value + 1))
    outputs = {outputs!r}
    content = outputs[min(value, len(outputs) - 1)]
    target = pathlib.Path(args[args.index("--output-last-message") + 1])
    target.write_text(content, encoding="utf-8")
    print(content)
    raise SystemExit(0)
raise SystemExit(2)
"""
    script.write_text(source, encoding="utf-8")
    script.chmod(0o755)
    return script, counter


def sample_input(message: str = "能做一个网页吗？") -> AIInput:
    return AIInput(
        customer_message=message,
        product={"title": "网页制作", "price": "未提供", "description": "企业网站开发"},
        recent_messages=[],
        seller_rules=["任何发送都要人工确认"],
        current_time="2026-08-03T12:00:00+08:00",
    )


@pytest.mark.asyncio
async def test_codex_provider_uses_login_and_retries_invalid_json_once(tmp_path: Path) -> None:
    script, counter = make_fake_codex(
        tmp_path,
        ["这不是 JSON", json.dumps(VALID_RESULT, ensure_ascii=False)],
    )
    settings = Settings(_env_file=None, codex_command=str(script))
    provider = CodexCliProvider(settings)

    health = await provider.healthcheck(validate_execution=False)
    result = await provider.generate(sample_input(), task_key="task-1")

    assert health.installed is True
    assert health.logged_in is True
    assert result.direct == VALID_RESULT["direct"]
    assert counter.read_text() == "2"


@pytest.mark.asyncio
async def test_codex_provider_detects_login_failure(tmp_path: Path) -> None:
    script, _counter = make_fake_codex(tmp_path, ["{}"], logged_in=False)
    provider = CodexCliProvider(Settings(_env_file=None, codex_command=str(script)))

    health = await provider.healthcheck(validate_execution=False)

    assert health.status == "login_required"
    assert health.logged_in is False
    assert health.repair_command == "codex login"


@pytest.mark.asyncio
async def test_codex_provider_timeout_is_bounded(tmp_path: Path) -> None:
    script, _counter = make_fake_codex(
        tmp_path,
        [json.dumps(VALID_RESULT, ensure_ascii=False)],
        delay=1,
    )
    settings = Settings(_env_file=None, codex_command=str(script))
    settings.codex_timeout_seconds = 0.05
    provider = CodexCliProvider(settings)
    await provider.healthcheck(validate_execution=False)

    with pytest.raises(AIProviderError) as raised:
        await provider.generate(sample_input(), task_key="task-timeout")

    assert raised.value.code == "codex_timeout"


@pytest.mark.asyncio
async def test_deterministic_sensitive_topic_forces_high_risk(tmp_path: Path) -> None:
    script, _counter = make_fake_codex(
        tmp_path,
        [json.dumps(VALID_RESULT, ensure_ascii=False)],
    )
    provider = CodexCliProvider(Settings(_env_file=None, codex_command=str(script)))
    await provider.healthcheck(validate_execution=False)

    result = await provider.generate(sample_input("可以改价到 500 元吗？"), task_key="risk")

    assert result.risk_level == "high"
    assert "报价需确认" in result.risk_reasons


@pytest.mark.asyncio
async def test_codex_exec_uses_supported_isolation_flags(tmp_path: Path) -> None:
    script, _counter = make_fake_codex(
        tmp_path,
        [json.dumps(VALID_RESULT, ensure_ascii=False)],
    )
    provider = CodexCliProvider(
        Settings(
            _env_file=None,
            codex_command=str(script),
            codex_ignore_user_config=True,
            codex_ignore_rules=True,
        )
    )
    await provider.healthcheck(validate_execution=False)
    workdir = tmp_path / "work"
    workdir.mkdir()

    args = provider._command_args(
        workdir,
        tmp_path / "schema.json",
        tmp_path / "output.json",
    )

    assert "--ignore-user-config" in args
    assert "--ignore-rules" in args
    assert args[-1] == "-"


def test_codex_workspace_plan_uses_repository_only_permission_profile(
    tmp_path: Path,
) -> None:
    provider = CodexCliProvider(Settings(_env_file=None, codex_command="codex"))
    provider._command_path = "codex"
    repository = tmp_path / "customer repository"
    repository.mkdir()

    args = provider._command_args(
        repository,
        tmp_path / "schema.json",
        tmp_path / "output.json",
        repository_scope=repository,
    )

    config_values = [
        args[index + 1]
        for index, value in enumerate(args)
        if value == "--config"
    ]
    assert "--sandbox" not in args
    assert "--ignore-user-config" in args
    assert "--ignore-rules" in args
    assert "--strict-config" in args
    assert 'default_permissions="repository_planning"' in config_values
    assert (
        'permissions.repository_planning.filesystem={'
        '":root"="deny",'
        '":minimal"="read",'
        '":workspace_roots"={"."="read"}'
        "}"
    ) in config_values
    assert (
        "permissions.repository_planning.workspace_roots="
        f"{{{json.dumps(str(repository))}=true}}"
    ) in config_values
    assert (
        "permissions.repository_planning.network={enabled=false}" in config_values
    )


def test_codex_provider_reports_network_failure_without_exposing_stderr() -> None:
    provider = CodexCliProvider(Settings(_env_file=None, codex_command="codex"))

    error = provider._classify_failure(
        "stream disconnected before completion: Connection refused (os error 61)"
    )

    assert error.code == "codex_network_unavailable"
    assert error.retryable is True
    assert "网络或本机代理" in error.safe_message
    assert "os error" not in error.safe_message
