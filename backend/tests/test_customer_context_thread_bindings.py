from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app.customer_context_api import customer_context_router
from backend.app.customer_context_mcp import bridge, get_bound_conversation_context
from backend.app.database import Database
from backend.app.models import (
    Conversation,
    CustomerContextThreadBinding,
    Message,
)
from backend.app.services.customer_context_gateway import CustomerContextGatewayError
from backend.tests.test_customer_context_gateway import upgrade
from backend.tests.test_customer_context_oauth import identity, oauth_config
from backend.tests.test_customer_context_reader import seed
from backend.tests.test_customer_context_tunnel import (
    bind_customer,
    mcp_context,
    tunnel_config,
)


def add_second_conversation(database: Database) -> int:
    with database.session() as session:
        conversation = Conversation(
            channel="xianyu",
            external_id="parallel-conversation",
            customer_id="parallel-customer",
            customer_name="并行客户",
        )
        session.add(conversation)
        session.flush()
        for index in range(1, 4):
            session.add(
                Message(
                    channel="xianyu",
                    platform_message_id=f"parallel-{index}",
                    external_id=f"parallel-{index}",
                    conversation_id=conversation.id,
                    sender_id="parallel-customer",
                    sender_name="并行客户",
                    direction="inbound",
                    message_type="text",
                    content=f"并行客户消息 {index}",
                    status="new",
                )
            )
        session.commit()
        return conversation.id


def create_binding(gateway, conversation_id: int, request_id: str, auth_mode: str):
    state = gateway.conversation_access_state(conversation_id)
    return gateway.create_thread_binding(
        conversation_id=conversation_id,
        request_id=request_id,
        expected_conversation_revision=state["revision"],
        auth_mode=auth_mode,
        allow_text=True,
        allow_images=False,
        allow_artifacts=False,
        allow_new_messages=True,
        expires_in_seconds=3600,
        authorization_note="仅允许一个 ChatGPT 对话读取该客户文字",
    )


def test_two_tunnel_thread_keys_read_two_customers_without_crossing(
    tmp_path: Path,
) -> None:
    database, reader, _legacy_grant, first_conversation_id = seed(tmp_path)
    second_conversation_id = add_second_conversation(database)
    bind_customer(
        reader.gateway,
        first_conversation_id,
        request_id="legacy-tunnel-before-multithread",
    )
    first = create_binding(
        reader.gateway,
        first_conversation_id,
        "thread-bind-first-0001",
        "tunnel_binding",
    )
    second = create_binding(
        reader.gateway,
        second_conversation_id,
        "thread-bind-second-0001",
        "tunnel_binding",
    )

    assert first["context_key"] != second["context_key"]
    assert len([row for row in reader.gateway.list_thread_bindings() if row["active"]]) == 2
    with pytest.raises(CustomerContextGatewayError):
        reader.gateway.resolve_active_tunnel_binding()
    with database.session() as session:
        rows = list(session.scalars(select(CustomerContextThreadBinding)))
        assert len(rows) == 2
        serialized = " ".join(row.context_key_hash for row in rows)
        assert first["context_key"] not in serialized
        assert second["context_key"] not in serialized
        assert hashlib.sha256(first["context_key"].encode()).hexdigest() in serialized

    bridge.bind(reader, reader.gateway, oauth_config(), None, tunnel_config())
    try:
        async def read_both():
            return await asyncio.gather(
                get_bound_conversation_context(
                    mcp_context(), context_key=first["context_key"]
                ),
                get_bound_conversation_context(
                    mcp_context(), context_key=second["context_key"]
                ),
            )

        first_result, second_result = asyncio.run(read_both())
        assert first_result.isError is False
        assert second_result.isError is False
        assert first_result.structuredContent["conversation_id"] == first_conversation_id
        assert second_result.structuredContent["conversation_id"] == second_conversation_id
        assert all(
            "并行客户消息" not in row["content"]
            for row in first_result.structuredContent["messages"]
        )
        assert [row["content"] for row in second_result.structuredContent["messages"]] == [
            "并行客户消息 1",
            "并行客户消息 2",
            "并行客户消息 3",
        ]

        unkeyed = asyncio.run(get_bound_conversation_context(mcp_context()))
        assert unkeyed.isError is True
        assert "必须提供 context_key" in unkeyed.content[0].text

        invalid = asyncio.run(
            get_bound_conversation_context(
                mcp_context(), context_key="ctx_" + "x" * 43
            )
        )
        assert invalid.isError is True

        replacement = create_binding(
            reader.gateway,
            first_conversation_id,
            "thread-bind-first-0002",
            "tunnel_binding",
        )
        stale = asyncio.run(
            get_bound_conversation_context(
                mcp_context(), context_key=first["context_key"]
            )
        )
        still_active = asyncio.run(
            get_bound_conversation_context(
                mcp_context(), context_key=second["context_key"]
            )
        )
        refreshed = asyncio.run(
            get_bound_conversation_context(
                mcp_context(), context_key=replacement["context_key"]
            )
        )
        assert stale.isError is True
        assert still_active.isError is False
        assert refreshed.isError is False
    finally:
        bridge.bind(reader, reader.gateway)


def test_oauth_thread_key_claims_one_identity_and_allows_same_user_parallel_keys(
    tmp_path: Path,
) -> None:
    database, reader, _legacy_grant, first_conversation_id = seed(tmp_path)
    second_conversation_id = add_second_conversation(database)
    first = create_binding(
        reader.gateway,
        first_conversation_id,
        "oauth-thread-first-0001",
        "oauth",
    )
    second = create_binding(
        reader.gateway,
        second_conversation_id,
        "oauth-thread-second-0001",
        "oauth",
    )
    operator = identity()
    first_grant = reader.gateway.resolve_active_thread_binding(
        first["context_key"], auth_mode="oauth", identity=operator
    )
    second_grant = reader.gateway.resolve_active_thread_binding(
        second["context_key"], auth_mode="oauth", identity=operator
    )
    assert first_grant["conversation_id"] == first_conversation_id
    assert second_grant["conversation_id"] == second_conversation_id

    other_user = type(operator)(
        issuer=operator.issuer,
        subject="another-operator",
        client_id=operator.client_id,
        audience=operator.audience,
        scopes=operator.scopes,
        issued_at=operator.issued_at,
        expires_at=operator.expires_at,
    )
    with pytest.raises(CustomerContextGatewayError) as denied:
        reader.gateway.resolve_active_thread_binding(
            first["context_key"], auth_mode="oauth", identity=other_user
        )
    assert denied.value.code == "context_key_owner_mismatch"
    with database.session() as session:
        rows = list(session.scalars(select(CustomerContextThreadBinding)))
        assert all(row.owner_subject_hash for row in rows)
        assert all("operator" not in (row.owner_subject_hash or "") for row in rows)


def test_thread_binding_api_returns_key_once_and_lists_only_safe_hints(
    tmp_path: Path,
) -> None:
    _database, reader, _legacy_grant, conversation_id = seed(tmp_path)
    app = FastAPI()
    app.state.runtime = type(
        "Runtime", (), {"customer_context_gateway": reader.gateway}
    )()
    app.state.customer_context_tunnel_config = tunnel_config()
    app.include_router(customer_context_router)
    client = TestClient(app, base_url="http://127.0.0.1:8877")

    created = client.post(
        "/api/customer-context/thread-bindings",
        json={
            "request_id": "thread-api-bind-0001",
            "conversation_id": conversation_id,
            "expected_conversation_revision": 0,
            "allow_text": True,
            "allow_images": False,
            "allow_artifacts": False,
            "allow_new_messages": True,
            "expires_in_seconds": 900,
            "authorization_note": "为一个 ChatGPT 对话创建客户读取密钥",
            "confirmed": True,
        },
    )
    assert created.status_code == 200
    raw_key = created.json()["context_key"]
    assert raw_key.startswith("ctx_")

    repeated = client.post(
        "/api/customer-context/thread-bindings",
        json={
            "request_id": "thread-api-bind-0001",
            "conversation_id": conversation_id,
            "expected_conversation_revision": 0,
            "allow_text": True,
            "allow_images": False,
            "allow_artifacts": False,
            "allow_new_messages": True,
            "expires_in_seconds": 900,
            "authorization_note": "为一个 ChatGPT 对话创建客户读取密钥",
            "confirmed": True,
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["context_key"] is None
    assert repeated.json()["idempotent"] is True

    listed = client.get("/api/customer-context/thread-bindings")
    assert listed.status_code == 200
    assert listed.json()["auth_mode"] == "tunnel_binding"
    assert listed.json()["bindings"][0]["context_key_hint"].startswith("…")
    assert '"context_key":' not in listed.text
    assert raw_key not in listed.text
    assert "capability_token" not in listed.text


def test_0043_to_0044_startup_idempotency_and_partial_rejection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "thread-binding-upgrade.db"
    upgrade(path, "20260902_0043")
    upgrade(path, "20260903_0044")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260903_0044",
        )
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []

    database = Database(f"sqlite:///{path}")
    database.create_all()
    database.create_all()

    partial = tmp_path / "thread-binding-partial.db"
    upgrade(partial, "20260902_0043")
    with sqlite3.connect(partial) as connection:
        connection.execute(
            "CREATE TABLE customer_context_thread_bindings ("
            "id VARCHAR(128) PRIMARY KEY, "
            "context_key_hash VARCHAR(64) NOT NULL UNIQUE, "
            "context_key_hint VARCHAR(16) NOT NULL, "
            "grant_id VARCHAR(128) NOT NULL UNIQUE, "
            "auth_mode VARCHAR(32) NOT NULL, "
            "owner_issuer VARCHAR(512), "
            "owner_subject_hash VARCHAR(64), "
            "owner_client_id_hash VARCHAR(64), "
            "status VARCHAR(32) NOT NULL, "
            "revision INTEGER NOT NULL, "
            "expires_at DATETIME NOT NULL, "
            "revoked_at DATETIME, "
            "last_used_at DATETIME, "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        )
    broken = Database(f"sqlite:///{partial}")
    with pytest.raises(
        RuntimeError,
        match="thread binding schema is incomplete: grant foreign key missing",
    ):
        broken.create_all()
