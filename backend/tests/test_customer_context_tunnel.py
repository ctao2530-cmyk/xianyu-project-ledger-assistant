from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from starlette.responses import Response

from backend.app.customer_context_api import customer_context_router
from backend.app.customer_context_mcp import (
    CustomerContextOAuthDiscoveryMiddleware,
    bridge,
    customer_context_mcp_app,
    get_bound_conversation_context,
    list_bound_archived_images,
    mcp,
)
from backend.app.database import Database
from backend.app.models import (
    CustomerContextAccessAudit,
    CustomerContextTunnelBinding,
)
from backend.app.services.customer_context_gateway import CustomerContextGatewayError
from backend.app.services.customer_context_tunnel import CustomerContextTunnelConfig
from backend.tests.test_customer_context_gateway import upgrade
from backend.tests.test_customer_context_oauth import oauth_config
from backend.tests.test_customer_context_reader import seed


SECRET = "tunnel-test-secret-0123456789abcdef0123456789"


def bind_customer(gateway, conversation_id: int, *, request_id: str = "tunnel-bind-0001"):
    access = gateway.conversation_access_state(conversation_id)
    state = gateway.tunnel_binding_state()
    return gateway.replace_tunnel_binding(
        conversation_id=conversation_id,
        request_id=request_id,
        expected_binding_revision=state["revision"],
        expected_conversation_revision=access["revision"],
        allow_text=True,
        allow_images=False,
        allow_artifacts=False,
        allow_new_messages=True,
        expires_in_seconds=3600,
        authorization_note="仅允许 ChatGPT Tunnel 按需读取该客户会话文字",
    )


def tunnel_config() -> CustomerContextTunnelConfig:
    return CustomerContextTunnelConfig(
        mode="tunnel_binding",
        shared_secret=SECRET,
    )


def mcp_headers(secret: str = SECRET) -> dict[str, str]:
    return {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "x-xunying-tunnel-key": secret,
    }


def mcp_context(secret: str = SECRET):
    return SimpleNamespace(
        request_context=SimpleNamespace(
            request=SimpleNamespace(headers=mcp_headers(secret))
        )
    )


def test_tunnel_binding_is_unique_idempotent_and_revocable(tmp_path: Path) -> None:
    database, reader, _legacy_grant, conversation_id = seed(tmp_path)
    gateway = reader.gateway

    created = bind_customer(gateway, conversation_id)
    assert created["active"] is True
    assert created["revision"] == 1
    assert created["grant"]["conversation_id"] == conversation_id
    assert "capability_token" not in created

    repeated = gateway.replace_tunnel_binding(
        conversation_id=conversation_id,
        request_id="tunnel-bind-0001",
        expected_binding_revision=0,
        expected_conversation_revision=0,
        allow_text=True,
        allow_images=False,
        allow_artifacts=False,
        allow_new_messages=True,
        expires_in_seconds=3600,
        authorization_note="仅允许 ChatGPT Tunnel 按需读取该客户会话文字",
    )
    assert repeated["idempotent"] is True
    assert repeated["grant"]["id"] == created["grant"]["id"]
    assert gateway.resolve_active_tunnel_binding()["id"] == created["grant"]["id"]

    revoked = gateway.revoke_tunnel_binding(
        request_id="tunnel-revoke-0001",
        expected_binding_revision=created["revision"],
        reason="用户停止本次 ChatGPT 读取",
    )
    assert revoked["active"] is False
    assert revoked["revision"] == 2
    with pytest.raises(CustomerContextGatewayError):
        gateway.resolve_active_tunnel_binding()
    with database.session() as session:
        assert session.scalar(select(func.count(CustomerContextTunnelBinding.slot))) == 1


def test_tunnel_transport_rejects_forgery_and_reads_only_active_grant(
    tmp_path: Path,
) -> None:
    database, reader, _legacy_grant, conversation_id = seed(tmp_path)
    bound = bind_customer(reader.gateway, conversation_id)
    bridge.bind(reader, reader.gateway, oauth_config(), None, tunnel_config())
    try:
        middleware = CustomerContextOAuthDiscoveryMiddleware(
            customer_context_mcp_app
        )

        async def pass_request(_request) -> Response:
            return Response(status_code=204)

        async def exercise_transport() -> None:
            missing = SimpleNamespace(method="POST", headers={})
            forged = SimpleNamespace(
                method="POST", headers=mcp_headers("wrong-secret")
            )
            trusted = SimpleNamespace(method="POST", headers=mcp_headers())
            assert (
                await middleware.dispatch(missing, pass_request)
            ).status_code == 401
            assert (
                await middleware.dispatch(forged, pass_request)
            ).status_code == 401
            assert (
                await middleware.dispatch(trusted, pass_request)
            ).status_code == 204

            tools = await mcp.list_tools()
            assert len(tools) == 8
            assert all(
                "securitySchemes"
                not in tool.model_dump(by_alias=True, exclude_none=True)
                for tool in tools
            )

            called = await get_bound_conversation_context(mcp_context())
            assert called.isError is False
            assert called.structuredContent["conversation_id"] == conversation_id

            denied_image = await list_bound_archived_images(mcp_context())
            assert denied_image.isError is True

            reader.gateway.revoke_tunnel_binding(
                request_id="tunnel-revoke-after-read",
                expected_binding_revision=bound["revision"],
                reason="验证撤销立即生效",
            )
            revoked = await get_bound_conversation_context(mcp_context())
            assert revoked.isError is True

        asyncio.run(exercise_transport())
    finally:
        bridge.bind(reader, reader.gateway)

    with database.session() as session:
        statuses = list(
            session.scalars(
                select(CustomerContextAccessAudit.status).order_by(
                    CustomerContextAccessAudit.created_at
                )
            )
        )
        assert "completed" in statuses
        assert "denied" in statuses


def test_tunnel_binding_api_never_returns_a_secret_or_capability(tmp_path: Path) -> None:
    _database, reader, _legacy_grant, conversation_id = seed(tmp_path)
    app = FastAPI()
    app.state.runtime = type(
        "Runtime", (), {"customer_context_gateway": reader.gateway}
    )()
    app.state.customer_context_tunnel_config = tunnel_config()
    app.include_router(customer_context_router)
    client = TestClient(app, base_url="http://127.0.0.1:8877")

    initial = client.get("/api/customer-context/tunnel-binding")
    assert initial.status_code == 200
    assert initial.json()["revision"] == 0

    created = client.post(
        "/api/customer-context/tunnel-binding",
        json={
            "request_id": "tunnel-api-bind-0001",
            "conversation_id": conversation_id,
            "expected_binding_revision": 0,
            "expected_conversation_revision": 0,
            "allow_text": True,
            "allow_images": False,
            "allow_artifacts": False,
            "allow_new_messages": True,
            "expires_in_seconds": 900,
            "authorization_note": "ChatGPT Tunnel 按需读取当前客户会话",
            "confirmed": True,
        },
    )
    assert created.status_code == 200
    serialized = created.text.lower()
    assert "capability_token" not in serialized
    assert SECRET.lower() not in serialized
    assert created.json()["active"] is True


def test_0042_to_0043_startup_idempotency_and_partial_rejection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tunnel-upgrade.db"
    upgrade(path, "20260902_0042")
    upgrade(path, "20260902_0043")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260902_0043",
        )
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []

    database = Database(f"sqlite:///{path}")
    database.create_all()
    database.create_all()

    partial = tmp_path / "tunnel-partial.db"
    upgrade(partial, "20260902_0042")
    with sqlite3.connect(partial) as connection:
        connection.execute(
            "CREATE TABLE customer_context_tunnel_bindings ("
            "slot VARCHAR(64) PRIMARY KEY, "
            "grant_id VARCHAR(128) NOT NULL, "
            "revision INTEGER NOT NULL, "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        )
    broken = Database(f"sqlite:///{partial}")
    with pytest.raises(
        RuntimeError,
        match="tunnel schema is incomplete: grant foreign key missing",
    ):
        broken.create_all()
