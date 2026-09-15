from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Mapping

from ..config import Settings


class CustomerContextTunnelError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CustomerContextTunnelConfig:
    """Local transport authentication for the private ChatGPT tunnel."""

    mode: str
    shared_secret: str = ""
    header_name: str = "x-xunying-tunnel-key"

    @classmethod
    def from_settings(cls, settings: Settings) -> "CustomerContextTunnelConfig":
        mode = settings.customer_context_mcp_auth_mode.strip().lower()
        if mode not in {"oauth", "tunnel_binding"}:
            raise CustomerContextTunnelError(
                "tunnel_configuration_invalid",
                "CUSTOMER_CONTEXT_MCP_AUTH_MODE 只允许 oauth 或 tunnel_binding",
            )
        secret = settings.customer_context_tunnel_secret.get_secret_value().strip()
        if mode == "tunnel_binding" and len(secret) < 32:
            raise CustomerContextTunnelError(
                "tunnel_configuration_incomplete",
                "Tunnel 传输密钥缺失或长度不足",
            )
        return cls(mode=mode, shared_secret=secret)

    @property
    def enabled(self) -> bool:
        return self.mode == "tunnel_binding"

    def verify(self, headers: Mapping[str, str]) -> None:
        supplied = str(headers.get(self.header_name, ""))
        if (
            not self.enabled
            or not supplied
            or not secrets.compare_digest(supplied, self.shared_secret)
        ):
            raise CustomerContextTunnelError(
                "tunnel_transport_unauthorized",
                "Tunnel 传输认证失败",
            )

    def status(self) -> dict[str, object]:
        return {
            "auth_mode": self.mode,
            "configured": self.enabled and len(self.shared_secret) >= 32,
            "header_name": "X-Xunying-Tunnel-Key",
        }
