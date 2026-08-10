from __future__ import annotations

import importlib.util
import subprocess
import stat
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "configure_xianyu.py"
SPEC = importlib.util.spec_from_file_location("root_configure_xianyu", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
configure_xianyu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configure_xianyu)

OPEN_VERIFICATION_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "open_xianyu_verification.py"
)
OPEN_VERIFICATION_SPEC = importlib.util.spec_from_file_location(
    "root_open_xianyu_verification", OPEN_VERIFICATION_SCRIPT_PATH
)
assert OPEN_VERIFICATION_SPEC is not None and OPEN_VERIFICATION_SPEC.loader is not None
open_xianyu_verification = importlib.util.module_from_spec(OPEN_VERIFICATION_SPEC)
OPEN_VERIFICATION_SPEC.loader.exec_module(open_xianyu_verification)


def valid_cookie(*, expiry_ms: int) -> str:
    return (
        "unb=seller; cookie2=session; "
        f"_m_h5_tk=fresh_{expiry_ms}; _m_h5_tk_enc=encrypted; foo=bar"
    )


def test_validate_cookie_accepts_fresh_complete_cookie() -> None:
    now_ms = int(time.time() * 1000)
    summary = configure_xianyu.validate_cookie(
        valid_cookie(expiry_ms=now_ms + 3_600_000),
        now_ms=now_ms,
    )

    assert summary["field_count"] == 5
    assert summary["expiry_ms"] == now_ms + 3_600_000


def test_validate_cookie_rejects_expired_or_incomplete_cookie() -> None:
    now_ms = int(time.time() * 1000)
    with pytest.raises(ValueError, match="已过期"):
        configure_xianyu.validate_cookie(
            valid_cookie(expiry_ms=now_ms - 1),
            now_ms=now_ms,
        )
    with pytest.raises(ValueError, match="缺少必要字段"):
        configure_xianyu.validate_cookie(
            f"unb=seller; _m_h5_tk=fresh_{now_ms + 3_600_000}",
            now_ms=now_ms,
        )


def test_update_env_is_atomic_private_and_preserves_other_secrets(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DEEPSEEK_API_KEY=keep-secret\nXIANYU_COOKIE=old-cookie\n",
        encoding="utf-8",
    )
    lines, _values = configure_xianyu.parse_env(env_path)
    cookie = valid_cookie(expiry_ms=int(time.time() * 1000) + 3_600_000)

    configure_xianyu.update_env(
        env_path,
        lines,
        cookie=cookie,
        session_cache_mode="enable",
    )

    _updated_lines, values = configure_xianyu.parse_env(env_path)
    assert values["DEEPSEEK_API_KEY"] == "keep-secret"
    assert values["XIANYU_COOKIE"] == cookie
    assert (
        values["XIANYU_SESSION_CACHE_PATH"]
        == configure_xianyu.DEFAULT_SESSION_CACHE_PATH
    )
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".env.xianyu-*")) == []


def test_read_goofish_cookie_store_decrypts_private_machine_bound_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_ms = int(time.time() * 1000)
    cookie_path = tmp_path / "cookies.json"
    payload = {
        "unb": "seller",
        "cookie2": "session",
        "_m_h5_tk": f"fresh_{now_ms + 3_600_000}",
        "_m_h5_tk_enc": "encrypted",
        "foo": "bar",
    }
    key = configure_xianyu._goofish_machine_key(
        hostname="test-host", username="test-user"
    )
    cookie_path.write_bytes(Fernet(key).encrypt(__import__("json").dumps(payload).encode()))
    cookie_path.chmod(0o600)
    monkeypatch.setattr(
        configure_xianyu,
        "_goofish_machine_key",
        lambda: key,
    )

    raw = configure_xianyu.read_goofish_cookie_store(cookie_path)
    summary = configure_xianyu.validate_cookie(raw, now_ms=now_ms)

    assert summary["field_count"] == len(payload)
    assert summary["expiry_ms"] == now_ms + 3_600_000


def test_read_goofish_cookie_store_rejects_broad_permissions(
    tmp_path: Path,
) -> None:
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_bytes(b"not-a-cookie")
    cookie_path.chmod(0o644)

    with pytest.raises(ValueError, match="权限过宽"):
        configure_xianyu.read_goofish_cookie_store(cookie_path)


def test_open_verification_uses_private_file_not_process_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verification_url = "https://passport.taobao.com/punish?one_time=secret"
    observed: dict[str, object] = {}

    def fake_run(args, **kwargs):
        observed["args"] = args
        observed["script"] = kwargs["input"]
        temporary_path = Path(args[-1])
        observed["mode"] = stat.S_IMODE(temporary_path.stat().st_mode)
        observed["url"] = temporary_path.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="opened\n", stderr="")

    monkeypatch.setattr(open_xianyu_verification.subprocess, "run", fake_run)

    open_xianyu_verification.open_in_existing_edge(verification_url)

    assert verification_url not in " ".join(observed["args"])
    assert verification_url not in str(observed["script"])
    assert observed["mode"] == 0o600
    assert observed["url"] == verification_url
    assert not Path(observed["args"][-1]).exists()
