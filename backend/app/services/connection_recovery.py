from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Literal

import httpx
from pydantic import SecretStr

from ..adapters import (
    AdapterAccessVerificationError,
    AdapterError,
    LoginExpiredError,
    XianyuAdapter,
)
from ..ai import AIModelSelection, AIProvider, DeepSeekProvider, ProviderHealth
from ..config import PROJECT_ROOT, Settings
from ..logging_config import register_runtime_secret
from .listener_supervisor import ListenerSupervisor


ConnectionProvider = Literal["xianyu", "deepseek", "codex_cli"]
ReloadableProvider = Literal["xianyu", "deepseek"]
XianyuProbe = Callable[[Settings], Awaitable[str | None]]
DeepSeekProbe = Callable[[Settings], Awaitable[ProviderHealth]]

REQUIRED_XIANYU_COOKIES = ("_m_h5_tk", "_m_h5_tk_enc", "unb", "cookie2")
DEEPSEEK_SETTING_FIELDS = (
    "deepseek_base_url",
    "deepseek_reply_model",
    "deepseek_lead_model",
    "deepseek_timeout_seconds",
)


class ConnectionRecoveryError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ConnectionRecoveryResult:
    provider: ConnectionProvider
    status: str
    detail: str
    configured: bool
    persisted: bool
    repair_command: str | None = None


def _normalize_cookie(raw: str) -> str:
    value = raw.strip()
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()
    if not value or "\n" in value or "\r" in value:
        raise ConnectionRecoveryError(
            "xianyu_cookie_invalid",
            "Cookie 不能为空或包含多行内容",
        )
    if len(value) > 100_000:
        raise ConnectionRecoveryError(
            "xianyu_cookie_too_long",
            "Cookie 内容过长，请重新复制请求头中的完整 Cookie",
        )
    return value


def _token_expiry_ms(token_value: str) -> int | None:
    suffix = token_value.rsplit("_", 1)[-1]
    if not suffix.isdigit():
        return None
    value = int(suffix)
    return value * 1000 if value < 10_000_000_000 else value


def validate_xianyu_cookie(raw: str, *, now_ms: int | None = None) -> str:
    value = _normalize_cookie(raw)
    parsed = SimpleCookie()
    try:
        parsed.load(value)
    except Exception as exc:
        raise ConnectionRecoveryError(
            "xianyu_cookie_invalid",
            "Cookie 格式无法解析，请重新复制完整请求头",
        ) from exc
    missing = [name for name in REQUIRED_XIANYU_COOKIES if name not in parsed]
    if missing:
        raise ConnectionRecoveryError(
            "xianyu_cookie_incomplete",
            f"Cookie 缺少必要字段：{', '.join(missing)}",
        )
    expiry_ms = _token_expiry_ms(parsed["_m_h5_tk"].value)
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    if expiry_ms is not None and expiry_ms <= current_ms:
        raise ConnectionRecoveryError(
            "xianyu_cookie_expired",
            "Cookie 中的登录令牌已过期，请从刚刚刷新的 Ego Lite 请求重新复制",
            status_code=401,
        )
    return value


def _normalize_api_key(raw: str) -> str:
    value = raw.strip()
    if not value or "\n" in value or "\r" in value:
        raise ConnectionRecoveryError(
            "deepseek_key_invalid",
            "API Key 不能为空或包含多行内容",
        )
    if len(value) < 8 or len(value) > 4096:
        raise ConnectionRecoveryError(
            "deepseek_key_invalid",
            "API Key 长度不正确，请重新复制",
        )
    return value


def update_env_values(path: Path, updates: dict[str, str]) -> None:
    """Atomically update selected local environment values with mode 0600."""
    try:
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise OSError("unsafe env path")
            metadata = path.stat()
            if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
                raise OSError("env owner mismatch")
            lines = path.read_text(encoding="utf-8").splitlines()
        else:
            lines = []

        encoded = {
            key: json.dumps(value, ensure_ascii=False)
            for key, value in updates.items()
        }
        output: list[str] = []
        replaced: set[str] = set()
        for line in lines:
            stripped = line.strip()
            key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
            if key in encoded:
                output.append(f"{key}={encoded[key]}")
                replaced.add(key)
            else:
                output.append(line)

        missing = [key for key in encoded if key not in replaced]
        if missing:
            if output and output[-1].strip():
                output.append("")
            output.append("# Local connection credentials (managed by the recovery center)")
            output.extend(f"{key}={encoded[key]}" for key in missing)

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".env.recovery-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(output).rstrip() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, path)
            os.chmod(path, 0o600)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
    except OSError as exc:
        raise ConnectionRecoveryError(
            "local_config_write_failed",
            "本机配置保存失败，原配置未被静默覆盖",
            status_code=500,
        ) from exc


class ConnectionRecoveryService:
    """Validate candidate credentials before applying them to shared runtime objects."""

    def __init__(
        self,
        settings: Settings,
        adapter: XianyuAdapter,
        listener_supervisor: ListenerSupervisor,
        deepseek: DeepSeekProvider,
        codex: AIProvider,
        *,
        env_path: Path | None = None,
        xianyu_probe: XianyuProbe | None = None,
        deepseek_probe: DeepSeekProbe | None = None,
        ai_queue=None,
        sales_agent=None,
        business_analysis=None,
        listener_wait_seconds: float = 12,
    ) -> None:
        self.settings = settings
        self.adapter = adapter
        self.listener_supervisor = listener_supervisor
        self.deepseek = deepseek
        self.codex = codex
        self.env_path = env_path or PROJECT_ROOT / ".env"
        self._xianyu_probe = xianyu_probe or self._probe_xianyu
        self._deepseek_probe = deepseek_probe or self._probe_deepseek
        self.ai_queue = ai_queue
        self.sales_agent = sales_agent
        self.business_analysis = business_analysis
        self.listener_wait_seconds = max(0, listener_wait_seconds)
        self._lock = asyncio.Lock()

    @staticmethod
    async def _probe_xianyu(settings: Settings) -> str | None:
        candidate = XianyuAdapter(settings)
        try:
            return await candidate.probe_login()
        finally:
            await candidate.close()

    @staticmethod
    async def _probe_deepseek(settings: Settings) -> ProviderHealth:
        candidate = DeepSeekProvider(settings)
        try:
            return await candidate.healthcheck(validate_execution=True)
        finally:
            await candidate.close()

    async def _validated_xianyu_cookie(self, raw_cookie: str) -> str:
        value = validate_xianyu_cookie(raw_cookie)
        candidate_settings = self.settings.model_copy(
            update={
                "xianyu_cookie": SecretStr(value),
                "xianyu_session_cache_path": "",
            }
        )
        try:
            refreshed = await self._xianyu_probe(candidate_settings)
        except LoginExpiredError as exc:
            raise ConnectionRecoveryError(
                "xianyu_login_required",
                "闲鱼登录已失效，请从已重新登录的 Ego Lite 复制最新 Cookie",
                status_code=401,
            ) from exc
        except AdapterAccessVerificationError as exc:
            raise ConnectionRecoveryError(
                "xianyu_verification_required",
                "闲鱼要求在现有 Ego Lite 会话中完成人机验证；自动重连已暂停，完成验证后再手动恢复",
                status_code=409,
            ) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ConnectionRecoveryError(
                "xianyu_connection_failed",
                "暂时无法连接闲鱼，请检查网络后重试",
                status_code=503,
            ) from exc
        except (httpx.HTTPError, AdapterError) as exc:
            raise ConnectionRecoveryError(
                "xianyu_probe_failed",
                "闲鱼登录验证失败，请确认 Cookie 来自当前已登录账号",
                status_code=503,
            ) from exc
        return validate_xianyu_cookie(refreshed or value)

    async def _validated_deepseek(
        self, candidate_settings: Settings
    ) -> ProviderHealth:
        try:
            health = await self._deepseek_probe(candidate_settings)
        except httpx.TimeoutException as exc:
            raise ConnectionRecoveryError(
                "deepseek_timeout",
                "DeepSeek 连接超时，请检查网络后重试",
                status_code=503,
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectionRecoveryError(
                "deepseek_connection_failed",
                "DeepSeek 暂时无法连接，请检查网络后重试",
                status_code=503,
            ) from exc
        if health.status != "connected":
            auth_failed = "鉴权" in (health.detail or "")
            raise ConnectionRecoveryError(
                "deepseek_auth_failed" if auth_failed else "deepseek_probe_failed",
                health.detail or "DeepSeek 连接验证失败",
                status_code=401 if auth_failed else 503,
            )
        return health

    async def _wait_for_listener(self) -> str:
        if self.listener_wait_seconds <= 0:
            return self.listener_supervisor.status.listener
        deadline = asyncio.get_running_loop().time() + self.listener_wait_seconds
        while asyncio.get_running_loop().time() < deadline:
            current = self.listener_supervisor.status.listener
            if current in {"connected", "login_required", "config_required"}:
                return current
            await asyncio.sleep(0.2)
        return self.listener_supervisor.status.listener

    async def _apply_xianyu(self, cookie: str, *, persisted: bool) -> ConnectionRecoveryResult:
        register_runtime_secret(cookie)
        await self.listener_supervisor.pause()
        await self.adapter.replace_cookie(cookie)
        self.settings.xianyu_cookie = SecretStr(cookie)
        await self.listener_supervisor.reconnect()
        listener_status = await self._wait_for_listener()
        if listener_status == "connected":
            detail = "闲鱼 Cookie 已验证，消息监听已恢复"
        elif listener_status == "login_required":
            detail = "Cookie 已保存，但监听仍要求重新登录，请重新复制最新 Cookie"
        else:
            detail = "Cookie 已验证，消息监听正在后台重新建立"
        return ConnectionRecoveryResult(
            provider="xianyu",
            status=listener_status,
            detail=detail,
            configured=True,
            persisted=persisted,
        )

    def _apply_deepseek(
        self,
        candidate_settings: Settings,
        health: ProviderHealth,
        *,
        persisted: bool,
    ) -> ConnectionRecoveryResult:
        key = candidate_settings.deepseek_api_key.get_secret_value()
        register_runtime_secret(key)
        self.settings.deepseek_api_key = SecretStr(key)
        for field in DEEPSEEK_SETTING_FIELDS:
            setattr(self.settings, field, getattr(candidate_settings, field))
        self.deepseek.configure_model(
            AIModelSelection(model=self.settings.deepseek_reply_model)
        )
        self.deepseek.health = health
        if self.ai_queue is not None:
            self.ai_queue.automatic_provider = self.deepseek.name
        if self.sales_agent is not None:
            self.sales_agent.provider = self.deepseek
            self.sales_agent.model_selections[self.deepseek.name] = AIModelSelection(
                model=self.settings.deepseek_lead_model
            )
        if self.business_analysis is not None:
            self.business_analysis.provider_enabled[self.deepseek.name] = True
            self.business_analysis.provider_selections[self.deepseek.name] = AIModelSelection(
                model=(
                    self.settings.business_analysis_model.strip()
                    or self.settings.deepseek_lead_model
                )
            )
        return ConnectionRecoveryResult(
            provider="deepseek",
            status=health.status,
            detail=health.detail or "DeepSeek 快速通道已连接",
            configured=True,
            persisted=persisted,
        )

    async def recover_xianyu(self, raw_cookie: str) -> ConnectionRecoveryResult:
        async with self._lock:
            cookie = await self._validated_xianyu_cookie(raw_cookie)
            update_env_values(self.env_path, {"XIANYU_COOKIE": cookie})
            return await self._apply_xianyu(cookie, persisted=True)

    async def recover_deepseek(self, raw_api_key: str) -> ConnectionRecoveryResult:
        async with self._lock:
            api_key = _normalize_api_key(raw_api_key)
            candidate_settings = self.settings.model_copy(
                update={"deepseek_api_key": SecretStr(api_key)}
            )
            health = await self._validated_deepseek(candidate_settings)
            update_env_values(self.env_path, {"DEEPSEEK_API_KEY": api_key})
            return self._apply_deepseek(
                candidate_settings,
                health,
                persisted=True,
            )

    async def reload(self, provider: ReloadableProvider) -> ConnectionRecoveryResult:
        async with self._lock:
            fresh = Settings(_env_file=self.env_path)
            if provider == "xianyu":
                cookie = await self._validated_xianyu_cookie(
                    fresh.xianyu_cookie.get_secret_value()
                )
                return await self._apply_xianyu(cookie, persisted=False)
            api_key = _normalize_api_key(fresh.deepseek_api_key.get_secret_value())
            candidate_settings = fresh.model_copy(
                update={"deepseek_api_key": SecretStr(api_key)}
            )
            health = await self._validated_deepseek(candidate_settings)
            return self._apply_deepseek(
                candidate_settings,
                health,
                persisted=False,
            )

    async def check_codex(self) -> ConnectionRecoveryResult:
        async with self._lock:
            health = await self.codex.healthcheck(validate_execution=False)
            return ConnectionRecoveryResult(
                provider="codex_cli",
                status=health.status,
                detail=health.detail or "Codex 状态已刷新",
                configured=bool(health.installed and health.logged_in),
                persisted=False,
                repair_command=health.repair_command,
            )


__all__ = [
    "ConnectionRecoveryError",
    "ConnectionRecoveryResult",
    "ConnectionRecoveryService",
    "update_env_values",
    "validate_xianyu_cookie",
]
