from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.ai import AIModelSelection, ProviderHealth
from backend.app.api import router
from backend.app.config import Settings
from backend.app.services.connection_recovery import (
    ConnectionRecoveryError,
    ConnectionRecoveryResult,
    ConnectionRecoveryService,
    update_env_values,
    validate_xianyu_cookie,
)


VALID_COOKIE = (
    "_m_h5_tk=token_9999999999999; _m_h5_tk_enc=enc; "
    "unb=account; cookie2=session"
)


class AdapterStub:
    def __init__(self) -> None:
        self.replaced_cookie = ""

    async def replace_cookie(self, raw_cookie: str) -> None:
        self.replaced_cookie = raw_cookie


class SupervisorStub:
    def __init__(self) -> None:
        self.status = SimpleNamespace(listener="login_required", listener_detail="expired")
        self.pause_count = 0
        self.reconnect_count = 0

    async def pause(self) -> None:
        self.pause_count += 1
        self.status.listener = "paused"

    async def reconnect(self) -> None:
        self.reconnect_count += 1
        self.status.listener = "connected"


class ProviderStub:
    def __init__(self, name: str) -> None:
        self.name = name
        self.health = ProviderHealth(status="checking")
        self.selection = AIModelSelection()

    def configure_model(self, selection: AIModelSelection) -> None:
        self.selection = selection

    async def healthcheck(self, *, validate_execution: bool = True) -> ProviderHealth:
        self.health = ProviderHealth(
            status="connected",
            detail="Codex CLI 已安装并已登录",
            installed=True,
            logged_in=True,
        )
        return self.health


def build_service(
    tmp_path: Path,
    *,
    xianyu_probe=None,
    deepseek_probe=None,
) -> tuple[ConnectionRecoveryService, AdapterStub, SupervisorStub, Settings]:
    env_path = tmp_path / ".env"
    env_path.write_text("UNCHANGED=value\n", encoding="utf-8")
    env_path.chmod(0o600)
    settings = Settings(
        _env_file=None,
        xianyu_cookie=VALID_COOKIE,
        deepseek_api_key="old-key-value",
    )
    adapter = AdapterStub()
    supervisor = SupervisorStub()
    deepseek = ProviderStub("deepseek")
    codex = ProviderStub("codex_cli")
    queue = SimpleNamespace(automatic_provider="codex_cli")
    sales = SimpleNamespace(
        provider=codex,
        model_selections={},
    )
    business = SimpleNamespace(provider_enabled={}, provider_selections={})

    async def default_xianyu_probe(_settings: Settings) -> str:
        return VALID_COOKIE

    async def default_deepseek_probe(_settings: Settings) -> ProviderHealth:
        return ProviderHealth(status="connected", detail="DeepSeek 快速通道已连接")

    service = ConnectionRecoveryService(
        settings,
        adapter,  # type: ignore[arg-type]
        supervisor,  # type: ignore[arg-type]
        deepseek,  # type: ignore[arg-type]
        codex,  # type: ignore[arg-type]
        env_path=env_path,
        xianyu_probe=xianyu_probe or default_xianyu_probe,
        deepseek_probe=deepseek_probe or default_deepseek_probe,
        ai_queue=queue,
        sales_agent=sales,
        business_analysis=business,
        listener_wait_seconds=0,
    )
    return service, adapter, supervisor, settings


def test_validate_xianyu_cookie_rejects_expired_and_missing_fields() -> None:
    with pytest.raises(ConnectionRecoveryError) as expired:
        validate_xianyu_cookie(
            "_m_h5_tk=token_1000; _m_h5_tk_enc=enc; unb=a; cookie2=b",
            now_ms=2_000_000,
        )
    assert expired.value.code == "xianyu_cookie_expired"

    with pytest.raises(ConnectionRecoveryError) as incomplete:
        validate_xianyu_cookie("_m_h5_tk=token_9999999999999; unb=a")
    assert incomplete.value.code == "xianyu_cookie_incomplete"


def test_update_env_values_is_atomic_private_and_preserves_other_lines(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP=1\nDEEPSEEK_API_KEY=old\n", encoding="utf-8")
    env_path.chmod(0o644)

    update_env_values(env_path, {"DEEPSEEK_API_KEY": "new-secret"})

    content = env_path.read_text(encoding="utf-8")
    assert "KEEP=1" in content
    assert 'DEEPSEEK_API_KEY="new-secret"' in content
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_xianyu_recovery_validates_before_persisting_and_reconnects(tmp_path: Path) -> None:
    service, adapter, supervisor, settings = build_service(tmp_path)

    result = await service.recover_xianyu(VALID_COOKIE)

    assert result.status == "connected"
    assert result.persisted is True
    assert adapter.replaced_cookie == VALID_COOKIE
    assert settings.xianyu_cookie.get_secret_value() == VALID_COOKIE
    assert supervisor.pause_count == 1
    assert supervisor.reconnect_count == 1
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert 'XIANYU_COOKIE="' in content
    assert VALID_COOKIE not in result.detail


@pytest.mark.asyncio
async def test_deepseek_failure_does_not_write_candidate_key(tmp_path: Path) -> None:
    async def failed_probe(_settings: Settings) -> ProviderHealth:
        return ProviderHealth(status="error", detail="DeepSeek 鉴权失败")

    service, _adapter, _supervisor, settings = build_service(
        tmp_path,
        deepseek_probe=failed_probe,
    )
    before = (tmp_path / ".env").read_text(encoding="utf-8")

    with pytest.raises(ConnectionRecoveryError) as error:
        await service.recover_deepseek("new-secret-key")

    assert error.value.code == "deepseek_auth_failed"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == before
    assert settings.deepseek_api_key.get_secret_value() == "old-key-value"


@pytest.mark.asyncio
async def test_deepseek_recovery_enables_shared_runtime_without_exposing_key(tmp_path: Path) -> None:
    service, _adapter, _supervisor, settings = build_service(tmp_path)

    result = await service.recover_deepseek("new-secret-key")

    assert result.status == "connected"
    assert result.persisted is True
    assert result.detail == "DeepSeek 快速通道已连接"
    assert "new-secret-key" not in repr(result)
    assert settings.deepseek_api_key.get_secret_value() == "new-secret-key"
    assert service.ai_queue.automatic_provider == "deepseek"
    assert service.sales_agent.provider is service.deepseek
    assert service.business_analysis.provider_enabled["deepseek"] is True


def test_recovery_api_requires_local_desktop_header_and_returns_sanitized_view() -> None:
    class RecoveryStub:
        async def recover_xianyu(self, _cookie: str) -> ConnectionRecoveryResult:
            return ConnectionRecoveryResult(
                provider="xianyu",
                status="connected",
                detail="闲鱼 Cookie 已验证，消息监听已恢复",
                configured=True,
                persisted=True,
            )

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(connection_recovery=RecoveryStub())
    client = TestClient(app)
    payload = {"cookie": VALID_COOKIE}

    denied = client.post("/api/connections/xianyu/recover", json=payload)
    allowed = client.post(
        "/api/connections/xianyu/recover",
        json=payload,
        headers={"X-Yuda-Desktop": "1"},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json() == {
        "provider": "xianyu",
        "status": "connected",
        "detail": "闲鱼 Cookie 已验证，消息监听已恢复",
        "configured": True,
        "persisted": True,
        "repair_command": None,
    }
    assert VALID_COOKIE not in allowed.text
