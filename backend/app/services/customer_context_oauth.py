from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
from typing import Any
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import httpx

from ..config import Settings


class CustomerContextOAuthError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _csv(value: str) -> tuple[str, ...]:
    return tuple(sorted({part.strip() for part in value.split(",") if part.strip()}))


def _canonical_https_url(
    value: str,
    *,
    field: str,
    preserve_trailing_slash: bool = False,
    allow_loopback_http: bool = False,
) -> str:
    stripped = value.strip()
    normalized = stripped if preserve_trailing_slash else stripped.rstrip("/")
    parsed = urlparse(normalized)
    loopback_http = (
        allow_loopback_http
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    )
    if (
        (parsed.scheme != "https" and not loopback_http)
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        requirement = (
            "HTTPS URL（本地回环地址可使用 HTTP）"
            if allow_loopback_http
            else "HTTPS URL"
        )
        raise CustomerContextOAuthError(
            "oauth_configuration_invalid",
            f"{field} 必须是无查询参数和片段的{requirement}",
        )
    return normalized


@dataclass(frozen=True, slots=True)
class CustomerContextOAuthConfig:
    enabled: bool
    issuer_url: str = ""
    audience: str = ""
    resource_server_url: str = ""
    jwks_url: str = ""
    required_scope: str = "customer-context.read"
    allowed_subjects: tuple[str, ...] = ()
    allowed_client_ids: tuple[str, ...] = ()
    jwks_cache_seconds: int = 300
    clock_skew_seconds: int = 60

    @classmethod
    def from_settings(cls, settings: Settings) -> "CustomerContextOAuthConfig":
        if not settings.customer_context_oauth_enabled:
            return cls(enabled=False)
        missing: list[str] = []
        required_values = {
            "CUSTOMER_CONTEXT_OAUTH_ISSUER_URL": settings.customer_context_oauth_issuer_url,
            "CUSTOMER_CONTEXT_OAUTH_AUDIENCE": settings.customer_context_oauth_audience,
            "CUSTOMER_CONTEXT_OAUTH_RESOURCE_SERVER_URL": (
                settings.customer_context_oauth_resource_server_url
            ),
            "CUSTOMER_CONTEXT_OAUTH_ALLOWED_SUBJECTS": (
                settings.customer_context_oauth_allowed_subjects
            ),
        }
        for name, value in required_values.items():
            if not value.strip():
                missing.append(name)
        if missing:
            raise CustomerContextOAuthError(
                "oauth_configuration_incomplete",
                "客户上下文 OAuth 配置缺少：" + ", ".join(missing),
            )
        scope = settings.customer_context_oauth_required_scope.strip()
        if not scope or any(char.isspace() for char in scope):
            raise CustomerContextOAuthError(
                "oauth_configuration_invalid",
                "CUSTOMER_CONTEXT_OAUTH_REQUIRED_SCOPE 必须是单个非空 scope",
            )
        return cls(
            enabled=True,
            issuer_url=_canonical_https_url(
                settings.customer_context_oauth_issuer_url,
                field="CUSTOMER_CONTEXT_OAUTH_ISSUER_URL",
                preserve_trailing_slash=True,
            ),
            audience=settings.customer_context_oauth_audience.strip(),
            resource_server_url=_canonical_https_url(
                settings.customer_context_oauth_resource_server_url,
                field="CUSTOMER_CONTEXT_OAUTH_RESOURCE_SERVER_URL",
                allow_loopback_http=True,
            ),
            jwks_url=(
                _canonical_https_url(
                    settings.customer_context_oauth_jwks_url,
                    field="CUSTOMER_CONTEXT_OAUTH_JWKS_URL",
                )
                if settings.customer_context_oauth_jwks_url.strip()
                else ""
            ),
            required_scope=scope,
            allowed_subjects=_csv(settings.customer_context_oauth_allowed_subjects),
            allowed_client_ids=_csv(settings.customer_context_oauth_allowed_client_ids),
            jwks_cache_seconds=settings.customer_context_oauth_jwks_cache_seconds,
            clock_skew_seconds=settings.customer_context_oauth_clock_skew_seconds,
        )

    @property
    def resource_metadata_url(self) -> str:
        if not self.enabled:
            return ""
        parsed = urlparse(self.resource_server_url)
        resource_path = parsed.path.rstrip("/")
        return (
            f"{parsed.scheme}://{parsed.netloc}"
            f"/.well-known/oauth-protected-resource{resource_path}"
        )

    def protected_resource_metadata(self) -> dict[str, Any]:
        if not self.enabled:
            raise CustomerContextOAuthError(
                "oauth_not_configured", "客户上下文 OAuth 尚未配置"
            )
        return {
            # The metadata document is fetched through the local tunnel route,
            # while the OAuth resource identifier must match the Auth0 API
            # audience advertised to remote clients.
            "resource": self.audience,
            "authorization_servers": [self.issuer_url],
            "scopes_supported": [self.required_scope],
            "resource_name": "循营客户上下文",
        }

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.enabled,
            "issuer_url": self.issuer_url if self.enabled else "",
            "resource_server_url": self.resource_server_url if self.enabled else "",
            "resource_metadata_url": self.resource_metadata_url,
            "required_scope": self.required_scope,
            "allowed_subject_count": len(self.allowed_subjects),
            "allowed_client_id_count": len(self.allowed_client_ids),
        }


@dataclass(frozen=True, slots=True)
class CustomerContextOAuthIdentity:
    issuer: str
    subject: str
    client_id: str
    audience: str
    scopes: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime


def _decode_segment(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise CustomerContextOAuthError("oauth_token_invalid", "OAuth Token 编码无效") from exc


class CustomerContextOAuthVerifier:
    """Verify external IdP JWTs without storing raw tokens or customer data."""

    def __init__(
        self,
        config: CustomerContextOAuthConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self._owned_client = client is None
        self._jwks: dict[str, Any] | None = None
        self._jwks_loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owned_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10, trust_env=False)
        return self._client

    async def _load_jwks(self, *, force: bool = False) -> dict[str, Any]:
        if (
            not force
            and self._jwks is not None
            and time.monotonic() - self._jwks_loaded_at < self.config.jwks_cache_seconds
        ):
            return self._jwks
        async with self._lock:
            if (
                not force
                and self._jwks is not None
                and time.monotonic() - self._jwks_loaded_at
                < self.config.jwks_cache_seconds
            ):
                return self._jwks
            metadata_url = (
                f"{self.config.issuer_url.rstrip('/')}"
                "/.well-known/openid-configuration"
            )
            try:
                metadata_response = await self._http().get(metadata_url)
                metadata_response.raise_for_status()
                metadata = metadata_response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise CustomerContextOAuthError(
                    "oauth_metadata_unavailable",
                    "OAuth 身份提供方元数据不可用",
                ) from exc
            if metadata.get("issuer", "").rstrip("/") != self.config.issuer_url.rstrip(
                "/"
            ):
                raise CustomerContextOAuthError(
                    "oauth_metadata_invalid", "OAuth issuer 元数据不一致"
                )
            methods = metadata.get("code_challenge_methods_supported") or []
            if "S256" not in methods:
                raise CustomerContextOAuthError(
                    "oauth_metadata_invalid", "OAuth 身份提供方未声明 PKCE S256"
                )
            try:
                _canonical_https_url(
                    str(metadata.get("authorization_endpoint") or ""),
                    field="OIDC authorization_endpoint",
                )
                _canonical_https_url(
                    str(metadata.get("token_endpoint") or ""),
                    field="OIDC token_endpoint",
                )
                discovered_jwks_url = _canonical_https_url(
                    str(metadata.get("jwks_uri") or ""), field="OIDC jwks_uri"
                )
            except CustomerContextOAuthError as exc:
                raise CustomerContextOAuthError(
                    "oauth_metadata_invalid", "OAuth 身份提供方端点不完整或不安全"
                ) from exc
            jwks_url = self.config.jwks_url or discovered_jwks_url
            try:
                response = await self._http().get(jwks_url)
                response.raise_for_status()
                jwks = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise CustomerContextOAuthError(
                    "oauth_jwks_unavailable", "OAuth 签名密钥不可用"
                ) from exc
            if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
                raise CustomerContextOAuthError(
                    "oauth_jwks_invalid", "OAuth 签名密钥结构无效"
                )
            self._jwks = jwks
            self._jwks_loaded_at = time.monotonic()
            return jwks

    @staticmethod
    def _json_segment(value: str) -> dict[str, Any]:
        try:
            decoded = json.loads(_decode_segment(value))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CustomerContextOAuthError(
                "oauth_token_invalid", "OAuth Token JSON 无效"
            ) from exc
        if not isinstance(decoded, dict):
            raise CustomerContextOAuthError(
                "oauth_token_invalid", "OAuth Token 结构无效"
            )
        return decoded

    @staticmethod
    def _rsa_key(jwk: dict[str, Any]) -> rsa.RSAPublicKey:
        if jwk.get("kty") != "RSA" or not jwk.get("n") or not jwk.get("e"):
            raise CustomerContextOAuthError(
                "oauth_jwks_invalid", "OAuth RSA 签名密钥无效"
            )
        modulus = int.from_bytes(_decode_segment(str(jwk["n"])), "big")
        exponent = int.from_bytes(_decode_segment(str(jwk["e"])), "big")
        return rsa.RSAPublicNumbers(exponent, modulus).public_key()

    async def verify_access_token(self, token: str) -> CustomerContextOAuthIdentity:
        if not self.config.enabled:
            raise CustomerContextOAuthError(
                "oauth_not_configured", "客户上下文 OAuth 尚未配置"
            )
        parts = token.split(".")
        if len(parts) != 3 or any(not part for part in parts):
            raise CustomerContextOAuthError("oauth_token_invalid", "OAuth Token 结构无效")
        header = self._json_segment(parts[0])
        claims = self._json_segment(parts[1])
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise CustomerContextOAuthError(
                "oauth_token_algorithm_invalid", "OAuth Token 必须使用 RS256"
            )
        jwks = await self._load_jwks()
        key = next(
            (
                item
                for item in jwks["keys"]
                if isinstance(item, dict) and item.get("kid") == header["kid"]
            ),
            None,
        )
        if key is None:
            jwks = await self._load_jwks(force=True)
            key = next(
                (
                    item
                    for item in jwks["keys"]
                    if isinstance(item, dict) and item.get("kid") == header["kid"]
                ),
                None,
            )
        if key is None:
            raise CustomerContextOAuthError(
                "oauth_signing_key_unknown", "OAuth Token 签名密钥未知"
            )
        try:
            self._rsa_key(key).verify(
                _decode_segment(parts[2]),
                f"{parts[0]}.{parts[1]}".encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature as exc:
            raise CustomerContextOAuthError(
                "oauth_signature_invalid", "OAuth Token 签名无效"
            ) from exc

        issuer = str(claims.get("iss") or "").rstrip("/")
        if issuer != self.config.issuer_url.rstrip("/"):
            raise CustomerContextOAuthError(
                "oauth_issuer_invalid", "OAuth Token issuer 无效"
            )
        audiences = claims.get("aud")
        if isinstance(audiences, str):
            audience_values = {audiences}
        elif isinstance(audiences, list):
            audience_values = {str(value) for value in audiences}
        else:
            audience_values = set()
        if self.config.audience not in audience_values:
            raise CustomerContextOAuthError(
                "oauth_audience_invalid", "OAuth Token audience 无效"
            )
        now = int(time.time())
        skew = self.config.clock_skew_seconds
        try:
            expires_at = int(claims["exp"])
            issued_at = int(claims["iat"])
            not_before = int(claims.get("nbf", issued_at))
        except (KeyError, TypeError, ValueError) as exc:
            raise CustomerContextOAuthError(
                "oauth_time_claim_invalid", "OAuth Token 时间声明不完整"
            ) from exc
        if (
            expires_at <= issued_at
            or expires_at <= now - skew
            or not_before > now + skew
            or issued_at > now + skew
        ):
            raise CustomerContextOAuthError(
                "oauth_token_expired", "OAuth Token 已过期或尚未生效"
            )
        subject = str(claims.get("sub") or "")
        if not subject or subject not in self.config.allowed_subjects:
            raise CustomerContextOAuthError(
                "oauth_subject_not_allowed", "OAuth 账户未获循营授权"
            )
        client_id = str(claims.get("azp") or claims.get("client_id") or "")
        if not client_id:
            raise CustomerContextOAuthError(
                "oauth_client_invalid", "OAuth Token 缺少客户端身份"
            )
        if (
            self.config.allowed_client_ids
            and client_id not in self.config.allowed_client_ids
        ):
            raise CustomerContextOAuthError(
                "oauth_client_not_allowed", "OAuth 客户端未获循营授权"
            )
        scopes: set[str] = set()
        raw_scope = claims.get("scope")
        if isinstance(raw_scope, str):
            scopes.update(part for part in raw_scope.split() if part)
        permissions = claims.get("permissions")
        if isinstance(permissions, list):
            scopes.update(str(value) for value in permissions if value)
        if self.config.required_scope not in scopes:
            raise CustomerContextOAuthError(
                "oauth_scope_insufficient", "OAuth Token 缺少客户上下文读取范围"
            )
        return CustomerContextOAuthIdentity(
            issuer=issuer,
            subject=subject,
            client_id=client_id,
            audience=self.config.audience,
            scopes=tuple(sorted(scopes)),
            issued_at=datetime.fromtimestamp(issued_at, tz=timezone.utc),
            expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
        )
