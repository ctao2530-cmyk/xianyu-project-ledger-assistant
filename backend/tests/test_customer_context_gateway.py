from __future__ import annotations

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import sqlite3
import threading

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.customer_context_api import customer_context_router
from backend.app.database import Database
from backend.app.models import (
    Conversation,
    CustomerContextAccessAudit,
    CustomerContextGrant,
    CustomerContextMutationRequest,
    GlobalAgentMessage,
    GlobalAgentRun,
    GlobalAgentThread,
    utcnow,
)
from backend.app.services.customer_context_gateway import (
    CustomerContextGateway,
    CustomerContextGatewayError,
)


ROOT = Path(__file__).resolve().parents[2]


def upgrade(path: Path, revision: str) -> None:
    previous = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = f"sqlite:///{path}"
        get_settings.cache_clear()
        command.upgrade(Config(str(ROOT / "alembic.ini")), revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def build_gateway(tmp_path: Path) -> tuple[Database, CustomerContextGateway, int, str]:
    database = Database(f"sqlite:///{tmp_path / 'gateway.db'}")
    database.create_all()
    with database.session() as session:
        conversation = Conversation(
            channel="xianyu",
            external_id="conversation-authorized",
            customer_id="platform-customer-1",
            customer_name="测试客户",
        )
        session.add(conversation)
        session.flush()
        thread = GlobalAgentThread(
            id="agent-thread-authorized",
            title="授权测试",
            profile_id=None,
            provider="codex_cli",
            model="gpt-test",
            reasoning_effort="medium",
            context_scope="customer_conversation",
            conversation_id=conversation.id,
            customer_id=None,
            status="active",
            revision=1,
        )
        session.add(thread)
        session.commit()
        return database, CustomerContextGateway(database), conversation.id, thread.id


def create_grant(
    gateway: CustomerContextGateway,
    thread_id: str,
    *,
    request_id: str = "grant-request-0001",
    expected_revision: int = 1,
    audience: str = "openai_chatgpt",
    allow_artifacts: bool = True,
) -> dict:
    return gateway.create_grant(
        thread_id=thread_id,
        request_id=request_id,
        expected_revision=expected_revision,
        provider_scope="openai",
        audience=audience,
        allow_text=True,
        allow_images=True,
        allow_artifacts=allow_artifacts,
        allow_new_messages=True,
        expires_in_seconds=3600,
        authorization_note="用户明确授权绑定会话的原始文字和已归档原图",
    )


def test_grant_is_thread_bound_short_lived_and_token_is_stored_only_as_hash(
    tmp_path: Path,
) -> None:
    database, gateway, conversation_id, thread_id = build_gateway(tmp_path)

    created = create_grant(gateway, thread_id)
    repeated = create_grant(gateway, thread_id)

    assert created["conversation_id"] == conversation_id
    assert created["thread_revision"] == 2
    assert created["allow_text"] is True
    assert created["allow_images"] is True
    assert created["allow_artifacts"] is True
    assert created["allow_new_messages"] is True
    assert created["audience"] == "openai_chatgpt"
    assert created["capability_token"]
    assert repeated["idempotent"] is True
    assert repeated["capability_token"] is None
    latest = gateway.latest_grant(thread_id)
    assert latest is not None
    assert "capability_token" not in latest
    with database.session() as session:
        row = session.get(CustomerContextGrant, created["id"])
        assert row is not None
        assert row.token_hash == hashlib.sha256(
            created["capability_token"].encode("utf-8")
        ).hexdigest()
        assert created["capability_token"] not in row.authorization_note
        assert session.scalar(select(func.count(CustomerContextMutationRequest.request_id))) == 1


def test_request_id_reuse_revision_conflict_and_unbound_thread_fail_closed(
    tmp_path: Path,
) -> None:
    _database, gateway, _conversation_id, thread_id = build_gateway(tmp_path)
    create_grant(gateway, thread_id)

    with pytest.raises(CustomerContextGatewayError, match="请求编号") as reused:
        create_grant(
            gateway,
            thread_id,
            request_id="grant-request-0001",
            audience="openai_api",
        )
    assert reused.value.code == "request_id_reused"
    with pytest.raises(CustomerContextGatewayError) as stale:
        create_grant(
            gateway,
            thread_id,
            request_id="grant-request-0002",
            expected_revision=1,
        )
    assert stale.value.code == "thread_revision_conflict"


def test_capability_authorizes_exact_audience_and_audit_precedes_completion(
    tmp_path: Path,
) -> None:
    database, gateway, conversation_id, thread_id = build_gateway(tmp_path)
    grant = create_grant(gateway, thread_id)
    token = grant["capability_token"]

    authorized = gateway.authorize_access(
        request_id="access-nonce-0001",
        capability_token=token,
        provider="openai",
        audience="openai_chatgpt",
        target_model="gpt-test",
        tool_name="customer_context_text",
        scopes=["text"],
    )
    with database.session() as session:
        row = session.scalar(
            select(CustomerContextAccessAudit).where(
                CustomerContextAccessAudit.request_id == "access-nonce-0001"
            )
        )
        assert row is not None
        assert row.status == "authorized"
        assert row.conversation_id == conversation_id
        assert row.completed_at is None
        assert row.request_hash

    source_hash = "a" * 64
    completed = gateway.complete_access(
        authorized["request_id"],
        summary_version=3,
        watermark_before=100,
        watermark_after=103,
        text_message_count=3,
        image_count=0,
        byte_count=0,
        source_hash=source_hash,
        duration_ms=12,
    )
    assert completed["status"] == "completed"
    assert completed["source_hash"] == source_hash
    assert completed["summary_version"] == 3

    with pytest.raises(CustomerContextGatewayError) as replayed:
        gateway.authorize_access(
            request_id="access-nonce-0001",
            capability_token=token,
            provider="openai",
            audience="openai_chatgpt",
            target_model="gpt-test",
            tool_name="customer_context_text",
            scopes=["text"],
        )
    assert replayed.value.code == "access_request_replayed"


def test_wrong_audience_expired_binding_and_revocation_deny_without_content(
    tmp_path: Path,
) -> None:
    database, gateway, _conversation_id, thread_id = build_gateway(tmp_path)
    grant = create_grant(gateway, thread_id)
    token = grant["capability_token"]

    with pytest.raises(CustomerContextGatewayError) as wrong_audience:
        gateway.authorize_access(
            request_id="access-nonce-wrong-audience",
            capability_token=token,
            provider="openai",
            audience="codex_cli",
            target_model="gpt-test",
            tool_name="customer_context_text",
            scopes=["text"],
        )
    assert wrong_audience.value.code == "audience_not_allowed"

    with database.session() as session:
        row = session.get(CustomerContextGrant, grant["id"])
        assert row is not None
        row.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    with pytest.raises(CustomerContextGatewayError) as expired:
        gateway.authorize_access(
            request_id="access-nonce-expired",
            capability_token=token,
            provider="openai",
            audience="openai_chatgpt",
            target_model="gpt-test",
            tool_name="customer_context_image_manifest",
            scopes=["images"],
        )
    assert expired.value.code == "grant_expired"

    with database.session() as session:
        row = session.get(CustomerContextGrant, grant["id"])
        assert row is not None
        row.expires_at = utcnow() + timedelta(hours=1)
        session.commit()
    revoked = gateway.revoke_grant(
        grant["id"],
        request_id="grant-revoke-0001",
        expected_revision=2,
        reason="用户停止本次外部读取",
    )
    assert revoked["status"] == "revoked"
    with pytest.raises(CustomerContextGatewayError) as denied:
        gateway.authorize_access(
            request_id="access-nonce-revoked",
            capability_token=token,
            provider="openai",
            audience="openai_chatgpt",
            target_model="gpt-test",
            tool_name="customer_context_text",
            scopes=["text"],
        )
    assert denied.value.code == "grant_revoked"


def test_thread_rebinding_invalidates_existing_grant(tmp_path: Path) -> None:
    database, gateway, _conversation_id, thread_id = build_gateway(tmp_path)
    grant = create_grant(gateway, thread_id)
    with database.session() as session:
        replacement = Conversation(
            channel="xianyu",
            external_id="replacement-conversation",
            customer_id="platform-customer-2",
            customer_name="另一位客户",
        )
        session.add(replacement)
        session.flush()
        thread = session.get(GlobalAgentThread, thread_id)
        assert thread is not None
        thread.conversation_id = replacement.id
        thread.revision += 1
        session.commit()

    with pytest.raises(CustomerContextGatewayError) as changed:
        gateway.authorize_access(
            request_id="access-nonce-rebound",
            capability_token=grant["capability_token"],
            provider="openai",
            audience="openai_chatgpt",
            target_model="gpt-test",
            tool_name="customer_context_text",
            scopes=["text"],
        )
    assert changed.value.code == "binding_changed"


def test_concurrent_nonce_replay_yields_one_receipt_and_one_domain_error(
    tmp_path: Path,
) -> None:
    database, gateway, _conversation_id, thread_id = build_gateway(tmp_path)
    grant = create_grant(gateway, thread_id)
    barrier = threading.Barrier(2)

    def synchronize_access_audits(session: Session, _context, _instances) -> None:
        if any(
            isinstance(row, CustomerContextAccessAudit)
            and row.request_id == "access-nonce-concurrent"
            for row in session.new
        ):
            barrier.wait(timeout=5)

    event.listen(Session, "before_flush", synchronize_access_audits)
    try:
        def authorize() -> str:
            try:
                gateway.authorize_access(
                    request_id="access-nonce-concurrent",
                    capability_token=grant["capability_token"],
                    provider="openai",
                    audience="openai_chatgpt",
                    target_model="gpt-test",
                    tool_name="customer_context_text",
                    scopes=["text"],
                )
                return "authorized"
            except CustomerContextGatewayError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = sorted(executor.map(lambda _value: authorize(), range(2)))
    finally:
        event.remove(Session, "before_flush", synchronize_access_audits)

    assert outcomes == ["access_request_replayed", "authorized"]
    with database.session() as session:
        assert session.scalar(
            select(func.count(CustomerContextAccessAudit.id)).where(
                CustomerContextAccessAudit.request_id == "access-nonce-concurrent"
            )
        ) == 1


def test_get_views_do_not_write_and_audits_never_contain_customer_content(
    tmp_path: Path,
) -> None:
    database, gateway, _conversation_id, thread_id = build_gateway(tmp_path)
    grant = create_grant(gateway, thread_id)
    with database.session() as session:
        before = session.scalar(select(func.count(CustomerContextMutationRequest.request_id)))
    gateway.latest_grant(thread_id)
    assert gateway.access_audits(thread_id) == []
    with database.session() as session:
        after = session.scalar(select(func.count(CustomerContextMutationRequest.request_id)))
        stored = session.get(CustomerContextGrant, grant["id"])
        assert stored is not None
        assert "客户消息" not in stored.consent_text_hash
    assert before == after == 1


def test_direct_conversation_grant_never_creates_agent_messages_or_runs(
    tmp_path: Path,
) -> None:
    database, gateway, conversation_id, small_agent_thread_id = build_gateway(tmp_path)

    initial = gateway.conversation_access_state(conversation_id)
    assert initial == {
        "conversation_id": conversation_id,
        "revision": 0,
        "latest_grant": None,
    }
    with database.session() as session:
        assert session.get(
            GlobalAgentThread, f"external-context-access-{conversation_id}"
        ) is None
        assert session.scalar(select(func.count(GlobalAgentMessage.id))) == 0
        assert session.scalar(select(func.count(GlobalAgentRun.id))) == 0

    created = gateway.create_conversation_grant(
        conversation_id=conversation_id,
        request_id="direct-grant-request-0001",
        expected_revision=0,
        provider_scope="openai",
        audience="openai_chatgpt",
        allow_text=True,
        allow_images=False,
        allow_artifacts=False,
        allow_new_messages=True,
        expires_in_seconds=900,
        authorization_note="ChatGPT 按需读取当前客户会话文字",
    )
    repeated = gateway.create_conversation_grant(
        conversation_id=conversation_id,
        request_id="direct-grant-request-0001",
        expected_revision=0,
        provider_scope="openai",
        audience="openai_chatgpt",
        allow_text=True,
        allow_images=False,
        allow_artifacts=False,
        allow_new_messages=True,
        expires_in_seconds=900,
        authorization_note="ChatGPT 按需读取当前客户会话文字",
    )

    assert created["thread_id"] == f"external-context-access-{conversation_id}"
    assert created["thread_revision"] == 1
    assert created["capability_token"]
    assert repeated["idempotent"] is True
    assert repeated["capability_token"] is None
    with database.session() as session:
        anchor = session.get(GlobalAgentThread, created["thread_id"])
        small_agent_thread = session.get(GlobalAgentThread, small_agent_thread_id)
        assert anchor is not None
        assert anchor.status == "external_context_access"
        assert anchor.provider == "openai"
        assert anchor.model == "mcp-read-only"
        assert small_agent_thread is not None
        assert small_agent_thread.revision == 1
        assert session.scalar(select(func.count(GlobalAgentMessage.id))) == 0
        assert session.scalar(select(func.count(GlobalAgentRun.id))) == 0

    authorized = gateway.authorize_access(
        request_id="direct-access-nonce-0001",
        capability_token=created["capability_token"],
        provider="openai",
        audience="openai_chatgpt",
        target_model="gpt-test",
        tool_name="customer_context_text",
        scopes=["text"],
    )
    assert authorized["conversation_id"] == conversation_id


def test_direct_conversation_grant_revision_replace_and_revoke_fail_closed(
    tmp_path: Path,
) -> None:
    _database, gateway, conversation_id, _small_agent_thread_id = build_gateway(tmp_path)
    first = gateway.create_conversation_grant(
        conversation_id=conversation_id,
        request_id="direct-grant-replace-0001",
        expected_revision=0,
        audience="openai_chatgpt",
        allow_text=True,
        allow_images=False,
        allow_artifacts=False,
        expires_in_seconds=900,
        authorization_note="首次按需读取授权",
    )

    with pytest.raises(CustomerContextGatewayError) as stale:
        gateway.create_conversation_grant(
            conversation_id=conversation_id,
            request_id="direct-grant-replace-stale",
            expected_revision=0,
            audience="openai_chatgpt",
            allow_text=True,
            allow_images=False,
            allow_artifacts=False,
            expires_in_seconds=900,
            authorization_note="过期 revision 不得覆盖",
        )
    assert stale.value.code == "conversation_revision_conflict"

    replacement = gateway.create_conversation_grant(
        conversation_id=conversation_id,
        request_id="direct-grant-replace-0002",
        expected_revision=1,
        audience="openai_chatgpt",
        allow_text=True,
        allow_images=True,
        allow_artifacts=True,
        expires_in_seconds=900,
        authorization_note="替换授权并独立允许原图与成果",
    )
    assert replacement["thread_revision"] == 2
    with pytest.raises(CustomerContextGatewayError) as old_token:
        gateway.authorize_access(
            request_id="direct-old-token-denied",
            capability_token=first["capability_token"],
            provider="openai",
            audience="openai_chatgpt",
            target_model="gpt-test",
            tool_name="customer_context_text",
            scopes=["text"],
        )
    assert old_token.value.code == "grant_revoked"

    revoked = gateway.revoke_grant(
        replacement["id"],
        request_id="direct-grant-revoke-0001",
        expected_revision=2,
        reason="用户结束 ChatGPT 网页读取",
    )
    assert revoked["status"] == "revoked"
    assert revoked["thread_revision"] == 3
    with pytest.raises(CustomerContextGatewayError) as revoked_token:
        gateway.resolve_active_capability(replacement["capability_token"])
    assert revoked_token.value.code == "grant_expired"


def test_artifact_scope_requires_explicit_grant(tmp_path: Path) -> None:
    _database, gateway, _conversation_id, thread_id = build_gateway(tmp_path)
    grant = create_grant(gateway, thread_id, allow_artifacts=False)
    with pytest.raises(CustomerContextGatewayError) as denied:
        gateway.authorize_access(
            request_id="access-artifact-denied",
            capability_token=grant["capability_token"],
            provider="openai",
            audience="openai_chatgpt",
            target_model="gpt-test",
            tool_name="customer_requirement_artifact",
            scopes=["artifact"],
        )
    assert denied.value.code == "artifact_not_authorized"


def test_startup_migration_is_idempotent_and_rejects_partial_schema(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'migration.db'}")
    database.create_all()
    database.create_all()
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE customer_context_access_audits")
        connection.exec_driver_sql("DROP TABLE customer_context_mutation_requests")

    with pytest.raises(RuntimeError, match="customer context gateway schema is incomplete"):
        Database(f"sqlite:///{tmp_path / 'migration.db'}").create_all()


def test_0039_to_0040_and_full_chain_keep_sqlite_integrity(tmp_path: Path) -> None:
    incremental_path = tmp_path / "context-incremental.db"
    upgrade(incremental_path, "20260828_0039")
    upgrade(incremental_path, "20260901_0040")
    with sqlite3.connect(incremental_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260901_0040",)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "customer_context_grants",
            "customer_context_access_audits",
            "customer_context_mutation_requests",
        } <= tables
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []

    full_chain_path = tmp_path / "context-full-chain.db"
    upgrade(full_chain_path, "head")
    with sqlite3.connect(full_chain_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260908_0046",)
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []


def test_customer_context_api_creates_reads_revokes_and_never_replays_token(
    tmp_path: Path,
) -> None:
    _database, gateway, conversation_id, thread_id = build_gateway(tmp_path)
    app = FastAPI()
    app.state.runtime = type("Runtime", (), {"customer_context_gateway": gateway})()
    app.include_router(customer_context_router)
    client = TestClient(app, base_url="http://127.0.0.1:8877")
    payload = {
        "request_id": "api-context-grant-0001",
        "thread_id": thread_id,
        "expected_revision": 1,
        "provider_scope": "openai",
        "audience": "openai_chatgpt",
        "allow_text": True,
        "allow_images": True,
        "allow_artifacts": True,
        "allow_new_messages": True,
        "expires_in_seconds": 3600,
        "authorization_note": "仅按需发送当前绑定会话给 OpenAI",
        "confirmed": True,
    }

    created = client.post("/api/customer-context/grants", json=payload)
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["conversation_id"] == conversation_id
    assert created_body["capability_token"]
    assert created_body["thread_revision"] == 2

    repeated = client.post("/api/customer-context/grants", json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["idempotent"] is True
    assert repeated.json()["capability_token"] is None

    latest = client.get(f"/api/customer-context/threads/{thread_id}/grant")
    assert latest.status_code == 200
    assert latest.json()["id"] == created_body["id"]
    assert latest.json()["capability_token"] is None

    revoked = client.post(
        f"/api/customer-context/grants/{created_body['id']}/revoke",
        json={
            "request_id": "api-context-revoke-0001",
            "expected_revision": created_body["thread_revision"],
            "reason": "本次外部读取已经结束",
            "confirmed": True,
        },
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["thread_revision"] == 3


def test_customer_context_api_creates_direct_grant_without_small_agent_thread(
    tmp_path: Path,
) -> None:
    database, gateway, conversation_id, small_agent_thread_id = build_gateway(tmp_path)
    app = FastAPI()
    app.state.runtime = type("Runtime", (), {"customer_context_gateway": gateway})()
    app.include_router(customer_context_router)
    client = TestClient(app, base_url="http://127.0.0.1:8877")

    access = client.get(
        f"/api/customer-context/conversations/{conversation_id}/access"
    )
    assert access.status_code == 200
    assert access.json() == {
        "conversation_id": conversation_id,
        "revision": 0,
        "latest_grant": None,
    }
    with database.session() as session:
        assert session.get(
            GlobalAgentThread, f"external-context-access-{conversation_id}"
        ) is None

    created = client.post(
        "/api/customer-context/conversation-grants",
        json={
            "request_id": "api-direct-grant-0001",
            "conversation_id": conversation_id,
            "expected_revision": 0,
            "provider_scope": "openai",
            "audience": "openai_chatgpt",
            "allow_text": True,
            "allow_images": False,
            "allow_artifacts": False,
            "allow_new_messages": True,
            "expires_in_seconds": 900,
            "authorization_note": "ChatGPT 独立按需读取客户会话文字",
            "confirmed": True,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["conversation_id"] == conversation_id
    assert body["thread_id"] == f"external-context-access-{conversation_id}"
    assert body["capability_token"]
    with database.session() as session:
        small_agent_thread = session.get(GlobalAgentThread, small_agent_thread_id)
        assert small_agent_thread is not None
        assert small_agent_thread.revision == 1
        assert session.scalar(select(func.count(GlobalAgentMessage.id))) == 0
        assert session.scalar(select(func.count(GlobalAgentRun.id))) == 0


def test_customer_context_api_rejects_deepseek_unbound_and_stale_revision(
    tmp_path: Path,
) -> None:
    database, gateway, _conversation_id, thread_id = build_gateway(tmp_path)
    app = FastAPI()
    app.state.runtime = type("Runtime", (), {"customer_context_gateway": gateway})()
    app.include_router(customer_context_router)
    client = TestClient(app, base_url="http://127.0.0.1:8877")
    base_payload = {
        "request_id": "api-context-deny-0001",
        "thread_id": thread_id,
        "expected_revision": 1,
        "provider_scope": "openai",
        "audience": "openai_chatgpt",
        "allow_text": True,
        "allow_images": False,
        "allow_artifacts": False,
        "allow_new_messages": True,
        "expires_in_seconds": 3600,
        "authorization_note": "只授权当前绑定会话文字",
        "confirmed": True,
    }
    deepseek = client.post(
        "/api/customer-context/grants",
        json={**base_payload, "provider_scope": "deepseek"},
    )
    assert deepseek.status_code == 422
    assert "capability_token" not in deepseek.text

    stale = client.post(
        "/api/customer-context/grants",
        json={**base_payload, "expected_revision": 9},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "thread_revision_conflict"

    with database.session() as session:
        thread = session.get(GlobalAgentThread, thread_id)
        assert thread is not None
        thread.context_scope = "none"
        thread.conversation_id = None
        session.commit()
    unbound = client.post(
        "/api/customer-context/grants",
        json={**base_payload, "request_id": "api-context-deny-0002"},
    )
    assert unbound.status_code == 422
    assert unbound.json()["detail"]["code"] == "conversation_not_bound"
