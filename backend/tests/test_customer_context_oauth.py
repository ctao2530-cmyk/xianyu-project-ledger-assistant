from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import httpx
import pytest
from sqlalchemy import select

from backend.app.config import Settings
from backend.app.customer_context_mcp import (
    bridge,
    get_bound_conversation_context,
    mcp,
)
from backend.app.database import Database
from backend.app.models import CustomerContextOAuthBinding
from backend.app.services.customer_context_gateway import (
    CustomerContextGatewayError,
)
from backend.app.services.customer_context_oauth import (
    CustomerContextOAuthConfig,
    CustomerContextOAuthError,
    CustomerContextOAuthIdentity,
    CustomerContextOAuthVerifier,
)
from backend.tests.test_customer_context_gateway import build_gateway, upgrade
from backend.tests.test_customer_context_reader import seed


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def jwk(private_key: rsa.RSAPrivateKey, kid: str) -> dict:
    public = private_key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": b64(public.n.to_bytes((public.n.bit_length() + 7) // 8, "big")),
        "e": b64(public.e.to_bytes((public.e.bit_length() + 7) // 8, "big")),
    }


def jwt_token(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str = "key-1",
    issuer: str = "https://issuer.example",
    audience: str = "https://xunying.example/mcp/customer-context",
    subject: str = "operator-subject",
    client_id: str = "chatgpt-client",
    scope: str = "customer-context.read",
    issued_at: int | None = None,
    expires_at: int | None = None,
    not_before: int | None = None,
) -> str:
    now = int(time.time())
    issued = issued_at if issued_at is not None else now
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "azp": client_id,
        "scope": scope,
        "iat": issued,
        "nbf": not_before if not_before is not None else issued,
        "exp": expires_at if expires_at is not None else now + 3600,
    }
    encoded = (
        b64(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + b64(json.dumps(claims, separators=(",", ":")).encode())
    )
    signature = private_key.sign(
        encoded.encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
    )
    return encoded + "." + b64(signature)


def oauth_config(**changes) -> CustomerContextOAuthConfig:
    values = {
        "enabled": True,
        "issuer_url": "https://issuer.example",
        "audience": "https://xunying.example/mcp/customer-context",
        "resource_server_url": "https://xunying.example/mcp/customer-context",
        "required_scope": "customer-context.read",
        "allowed_subjects": ("operator-subject",),
        "allowed_client_ids": ("chatgpt-client",),
        "jwks_cache_seconds": 300,
        "clock_skew_seconds": 60,
    }
    values.update(changes)
    return CustomerContextOAuthConfig(**values)


def test_auth0_issuer_trailing_slash_is_preserved_in_resource_metadata() -> None:
    config = CustomerContextOAuthConfig.from_settings(
        Settings(
            customer_context_oauth_enabled=True,
            customer_context_oauth_issuer_url="https://tenant.example/",
            customer_context_oauth_audience=(
                "https://xunying.example/mcp/customer-context"
            ),
            customer_context_oauth_resource_server_url=(
                "https://xunying.example/mcp/customer-context"
            ),
            customer_context_oauth_allowed_subjects="operator-subject",
        )
    )
    assert config.issuer_url == "https://tenant.example/"
    assert config.protected_resource_metadata()["authorization_servers"] == [
        "https://tenant.example/"
    ]


def test_private_tunnel_accepts_loopback_http_resource_metadata_url() -> None:
    config = CustomerContextOAuthConfig.from_settings(
        Settings(
            customer_context_oauth_enabled=True,
            customer_context_oauth_issuer_url="https://tenant.example/",
            customer_context_oauth_audience=(
                "https://xunying.example/mcp/customer-context"
            ),
            customer_context_oauth_resource_server_url=(
                "http://127.0.0.1:8877/mcp/customer-context"
            ),
            customer_context_oauth_allowed_subjects="operator-subject",
        )
    )
    assert config.resource_metadata_url == (
        "http://127.0.0.1:8877/.well-known/"
        "oauth-protected-resource/mcp/customer-context"
    )
    assert config.protected_resource_metadata()["resource"] == (
        "https://xunying.example/mcp/customer-context"
    )


def test_private_tunnel_rejects_non_loopback_http_resource_url() -> None:
    with pytest.raises(CustomerContextOAuthError) as exc_info:
        CustomerContextOAuthConfig.from_settings(
            Settings(
                customer_context_oauth_enabled=True,
                customer_context_oauth_issuer_url="https://tenant.example/",
                customer_context_oauth_audience=(
                    "https://xunying.example/mcp/customer-context"
                ),
                customer_context_oauth_resource_server_url=(
                    "http://xunying.example/mcp/customer-context"
                ),
                customer_context_oauth_allowed_subjects="operator-subject",
            )
        )
    assert exc_info.value.code == "oauth_configuration_invalid"


def verifier_for(
    private_key: rsa.RSAPrivateKey,
    *,
    metadata_s256: bool = True,
    config: CustomerContextOAuthConfig | None = None,
) -> CustomerContextOAuthVerifier:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": "https://issuer.example",
                    "authorization_endpoint": "https://issuer.example/authorize",
                    "token_endpoint": "https://issuer.example/oauth/token",
                    "jwks_uri": "https://issuer.example/.well-known/jwks.json",
                    "code_challenge_methods_supported": (
                        ["S256"] if metadata_s256 else ["plain"]
                    ),
                },
            )
        return httpx.Response(200, json={"keys": [jwk(private_key, "key-1")]})

    return CustomerContextOAuthVerifier(
        config or oauth_config(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_rs256_verifier_enforces_identity_audience_scope_and_time() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = verifier_for(private_key)
    identity = await verifier.verify_access_token(jwt_token(private_key))
    assert identity.subject == "operator-subject"
    assert identity.client_id == "chatgpt-client"
    assert identity.scopes == ("customer-context.read",)

    cases = [
        (jwt_token(private_key, issuer="https://wrong.example"), "oauth_issuer_invalid"),
        (jwt_token(private_key, audience="wrong"), "oauth_audience_invalid"),
        (jwt_token(private_key, subject="other"), "oauth_subject_not_allowed"),
        (jwt_token(private_key, client_id="other"), "oauth_client_not_allowed"),
        (jwt_token(private_key, scope="other"), "oauth_scope_insufficient"),
        (
            jwt_token(private_key, expires_at=int(time.time()) - 120),
            "oauth_token_expired",
        ),
        (
            jwt_token(private_key, not_before=int(time.time()) + 120),
            "oauth_token_expired",
        ),
    ]
    for token, code in cases:
        with pytest.raises(CustomerContextOAuthError) as error:
            await verifier.verify_access_token(token)
        assert error.value.code == code
    await verifier.close()


@pytest.mark.asyncio
async def test_verifier_rejects_metadata_without_pkce_s256() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = verifier_for(private_key, metadata_s256=False)
    with pytest.raises(CustomerContextOAuthError) as error:
        await verifier.verify_access_token(jwt_token(private_key))
    assert error.value.code == "oauth_metadata_invalid"
    await verifier.close()


@pytest.mark.asyncio
async def test_verifier_refreshes_jwks_once_for_a_rotated_kid() -> None:
    first = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rotated = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    calls = {"jwks": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": "https://issuer.example",
                    "authorization_endpoint": "https://issuer.example/authorize",
                    "token_endpoint": "https://issuer.example/oauth/token",
                    "jwks_uri": "https://issuer.example/.well-known/jwks.json",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        calls["jwks"] += 1
        keys = [jwk(first, "key-1")]
        if calls["jwks"] > 1:
            keys = [jwk(rotated, "key-2")]
        return httpx.Response(200, json={"keys": keys})

    verifier = CustomerContextOAuthVerifier(
        oauth_config(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await verifier.verify_access_token(jwt_token(first, kid="key-1"))
    result = await verifier.verify_access_token(jwt_token(rotated, kid="key-2"))
    assert result.subject == "operator-subject"
    assert calls["jwks"] == 2


def direct_grant(tmp_path: Path):
    database, gateway, conversation_id, _thread_id = build_gateway(tmp_path)
    grant = gateway.create_conversation_grant(
        conversation_id=conversation_id,
        request_id="oauth-direct-grant",
        expected_revision=0,
        allow_text=True,
        allow_images=True,
        allow_artifacts=True,
        allow_new_messages=True,
        expires_in_seconds=3600,
        authorization_note="用户明确授权 ChatGPT 读取当前客户会话",
        audience="openai_chatgpt",
    )
    return database, gateway, grant


def identity(now: datetime | None = None) -> CustomerContextOAuthIdentity:
    current = now or datetime.now(timezone.utc)
    return CustomerContextOAuthIdentity(
        issuer="https://issuer.example",
        subject="operator-subject",
        client_id="chatgpt-client",
        audience="https://xunying.example/mcp/customer-context",
        scopes=("customer-context.read",),
        issued_at=current,
        expires_at=current + timedelta(hours=1),
    )


def test_oauth_token_binds_once_to_prior_manual_grant_and_stores_only_hashes(
    tmp_path: Path,
) -> None:
    database, gateway, grant = direct_grant(tmp_path)
    raw_token = "header.payload.signature"
    resolved = gateway.resolve_or_bind_oauth_capability(raw_token, identity())
    assert resolved["id"] == grant["id"]

    with database.session() as session:
        binding = session.scalar(select(CustomerContextOAuthBinding))
        assert binding is not None
        assert binding.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
        serialized = " ".join(
            [binding.token_hash, binding.subject_hash, binding.client_id_hash]
        )
        assert raw_token not in serialized
        assert "operator-subject" not in serialized
        assert "chatgpt-client" not in serialized

    state = gateway.conversation_access_state(grant["conversation_id"])
    newer = gateway.create_conversation_grant(
        conversation_id=grant["conversation_id"],
        request_id="oauth-newer-grant",
        expected_revision=state["revision"],
        allow_text=True,
        allow_images=False,
        allow_artifacts=True,
        allow_new_messages=True,
        expires_in_seconds=3600,
        authorization_note="更新授权",
        audience="openai_chatgpt",
    )
    assert newer["id"] != grant["id"]
    with pytest.raises(CustomerContextGatewayError) as stale:
        gateway.resolve_or_bind_oauth_capability(raw_token, identity())
    assert stale.value.code in {"grant_expired", "binding_changed"}


def context_with_token(token: str | None = None):
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return SimpleNamespace(
        request_context=SimpleNamespace(request=SimpleNamespace(headers=headers))
    )


@pytest.mark.asyncio
async def test_mcp_discovery_is_anonymous_and_tools_publish_oauth_challenge(
    tmp_path: Path,
) -> None:
    _database, reader, _grant, _conversation_id = seed(tmp_path)
    config = oauth_config()
    bridge.bind(reader, reader.gateway, config, None)
    try:
        tools = await mcp.list_tools()
        for tool in tools:
            assert tool.annotations.readOnlyHint is (tool.name not in {'xunying_confirm_bound_context_batch', 'xunying_preview_requirement_blueprint', 'xunying_confirm_requirement_blueprint'})
            assert tool.securitySchemes[0]["type"] == "oauth2"
            assert tool.meta["securitySchemes"] == tool.securitySchemes
        denied = await get_bound_conversation_context(context_with_token())
        assert denied.isError is True
        challenge = denied.meta["mcp/www_authenticate"][0]
        assert "oauth-protected-resource/mcp/customer-context" in challenge
    finally:
        bridge.bind(reader, reader.gateway)


@pytest.mark.asyncio
async def test_verified_oauth_token_reads_only_its_manually_bound_conversation(
    tmp_path: Path,
) -> None:
    _database, reader, _legacy_grant, conversation_id = seed(tmp_path)
    access = reader.gateway.conversation_access_state(conversation_id)
    reader.gateway.create_conversation_grant(
        conversation_id=conversation_id,
        request_id="oauth-mcp-direct-grant",
        expected_revision=access["revision"],
        allow_text=True,
        allow_images=False,
        allow_artifacts=True,
        allow_new_messages=True,
        expires_in_seconds=3600,
        authorization_note="用户明确授权 ChatGPT 读取当前客户会话文字",
        audience="openai_chatgpt",
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt_token(private_key)
    config = oauth_config()
    verifier = verifier_for(private_key, config=config)
    bridge.bind(reader, reader.gateway, config, verifier)
    try:
        called = await get_bound_conversation_context(context_with_token(token))
        assert called.isError is False
        assert called.structuredContent["conversation_id"] == conversation_id
        assert len(called.structuredContent["messages"]) == 200
    finally:
        bridge.bind(reader, reader.gateway)


def test_0041_to_0042_startup_idempotency_and_partial_rejection(tmp_path: Path) -> None:
    path = tmp_path / "oauth-upgrade.db"
    upgrade(path, "20260901_0041")
    upgrade(path, "20260902_0042")
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260902_0042",)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []

    database = Database(f"sqlite:///{path}")
    database.create_all()
    database.create_all()

    partial = tmp_path / "oauth-partial.db"
    prior = Database(f"sqlite:///{partial}")
    prior.create_all()
    with prior.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE customer_context_oauth_bindings")
        connection.exec_driver_sql(
            "CREATE TABLE customer_context_oauth_bindings (id VARCHAR(128) PRIMARY KEY)"
        )
    with pytest.raises(RuntimeError, match="OAuth schema is incomplete"):
        prior.create_all()
