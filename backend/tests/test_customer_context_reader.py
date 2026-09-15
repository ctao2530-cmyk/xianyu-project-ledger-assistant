from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest
from sqlalchemy import func, select

from backend.app.database import Database
from backend.app.models import (
    Conversation,
    CustomerContextAccessAudit,
    CustomerImageArchive,
    GlobalAgentRun,
    GlobalAgentMessage,
    GlobalAgentThread,
    Message,
    utcnow,
)
from backend.app.services.customer_context_gateway import (
    CustomerContextGateway,
    CustomerContextGatewayError,
)
from backend.app.services.customer_context_reader import (
    CustomerContextReadError,
    CustomerContextReadService,
)


def seed(tmp_path: Path) -> tuple[
    Database, CustomerContextReadService, dict, int
]:
    database = Database(f"sqlite:///{tmp_path / 'reader.db'}")
    database.create_all()
    gateway = CustomerContextGateway(database)
    with database.session() as session:
        conversation = Conversation(
            channel="xianyu",
            external_id="reader-conversation",
            customer_id="reader-customer",
            customer_name="测试客户",
        )
        session.add(conversation)
        session.flush()
        session.add(
            GlobalAgentThread(
                id="reader-agent-thread",
                title="读取测试",
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
        )
        for index in range(1, 506):
            session.add(
                Message(
                    channel="xianyu",
                    platform_message_id=f"reader-{index}",
                    external_id=f"reader-{index}",
                    conversation_id=conversation.id,
                    sender_id="reader-customer",
                    sender_name="测试客户",
                    direction="inbound" if index % 2 else "outbound",
                    message_type="text",
                    content=f"客户文字 {index}",
                    status="new",
                )
            )
        session.commit()
        conversation_id = conversation.id
    grant = gateway.create_grant(
        thread_id="reader-agent-thread",
        request_id="reader-grant-0001",
        expected_revision=1,
        provider_scope="openai",
        audience="openai_chatgpt",
        allow_text=True,
        allow_images=True,
        allow_artifacts=True,
        allow_new_messages=True,
        expires_in_seconds=3600,
        authorization_note="用户明确授权该绑定会话",
    )
    return (
        database,
        CustomerContextReadService(database, gateway, tmp_path),
        grant,
        conversation_id,
    )


def test_reader_uses_current_sqlite_snapshot_and_releases_only_latest_200(
    tmp_path: Path,
) -> None:
    database, reader, grant, _conversation_id = seed(tmp_path)
    result = reader.read_text(
        request_id="reader-access-text-0001",
        capability_token=grant["capability_token"],
        audience="openai_chatgpt",
        target_model="gpt-test",
    )
    assert result["context_mode"] == "full_initial"
    assert len(result["messages"]) == 200
    assert result["messages"][0]["message_id"] == 306
    assert result["messages"][-1]["message_id"] == 505
    assert result["current_snapshot"] == "sqlite_read_during_this_request"
    assert result["source_hash"] != result["payload_source_hash"]
    with database.session() as session:
        audit = session.scalar(
            select(CustomerContextAccessAudit).where(
                CustomerContextAccessAudit.request_id == "reader-access-text-0001"
            )
        )
        assert audit is not None
        assert audit.status == "completed"
        assert audit.text_message_count == 200
        assert "客户文字" not in audit.request_hash


def test_manifest_and_image_read_return_only_bound_original(tmp_path: Path) -> None:
    database, reader, grant, conversation_id = seed(tmp_path)
    image = Image.new("RGB", (32, 24), (82, 63, 220))
    output = BytesIO()
    image.save(output, format="PNG")
    content = output.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    relative = Path("data/customer-images/2026/09") / f"{digest}.png"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with database.session() as session:
        message = Message(
            channel="xianyu",
            platform_message_id="reader-image-message",
            external_id="reader-image-message",
            conversation_id=conversation_id,
            sender_id="reader-customer",
            sender_name="测试客户",
            direction="inbound",
            message_type="image",
            content="[图片]",
            status="new",
        )
        session.add(message)
        session.flush()
        session.add(
            CustomerImageArchive(
                id="reader-image-archive",
                conversation_id=conversation_id,
                message_id=message.id,
                channel="xianyu",
                platform_message_id=message.platform_message_id,
                media_index=0,
                capture_status="stored",
                capture_source="live",
                mime_type="image/png",
                original_name="customer-upload.png",
                storage_path=relative.as_posix(),
                sha256=digest,
                file_size=len(content),
                width=32,
                height=24,
                integrity_verified=True,
                received_at=utcnow(),
                captured_at=utcnow(),
            )
        )
        session.commit()

    manifest = reader.image_manifest(
        request_id="reader-access-images-0001",
        capability_token=grant["capability_token"],
        audience="openai_chatgpt",
        target_model="gpt-test",
    )
    assert manifest["images"] == [
        {
            "archive_id": "reader-image-archive",
            "message_id": manifest["images"][0]["message_id"],
            "received_at": manifest["images"][0]["received_at"],
            "mime_type": "image/png",
            "file_size": len(content),
            "width": 32,
            "height": 24,
            "sha256": digest,
            "capture_status": "stored",
            "conversation_id": conversation_id,
            "error_code": None,
            "updated_at": manifest["images"][0]["updated_at"],
            "representations": ["original", "compatible"],
        }
    ]
    assert "storage_path" not in manifest["images"][0]
    assert "original_name" not in manifest["images"][0]

    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    model_input = reader.read_image(
        "reader-image-archive",
        request_id="reader-access-image-read-0001",
        capability_token=grant["capability_token"],
        audience="openai_chatgpt",
        target_model="gpt-test",
    )
    assert model_input.content == content
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
    assert "content=" not in repr(model_input)


def test_image_reads_reject_cross_conversation_and_outbound_archives(
    tmp_path: Path,
) -> None:
    database, reader, grant, conversation_id = seed(tmp_path)
    image = Image.new("RGB", (18, 12), (31, 120, 91))
    output = BytesIO()
    image.save(output, format="PNG")
    content = output.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    relative = Path("data/customer-images/2026/09") / f"{digest}.png"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    with database.session() as session:
        other = Conversation(
            channel="xianyu",
            external_id="other-reader-conversation",
            customer_id="other-reader-customer",
            customer_name="其他客户",
        )
        session.add(other)
        session.flush()
        rows = []
        for archive_id, bound_conversation_id, direction in (
            ("cross-conversation-image", other.id, "inbound"),
            ("outbound-bound-image", conversation_id, "outbound"),
        ):
            message = Message(
                channel="xianyu",
                platform_message_id=f"message-{archive_id}",
                external_id=f"message-{archive_id}",
                conversation_id=bound_conversation_id,
                sender_id="sender",
                sender_name="测试",
                direction=direction,
                message_type="image",
                content="[图片]",
                status="new",
            )
            session.add(message)
            session.flush()
            rows.append(
                CustomerImageArchive(
                    id=archive_id,
                    conversation_id=bound_conversation_id,
                    message_id=message.id,
                    channel="xianyu",
                    platform_message_id=message.platform_message_id,
                    media_index=0,
                    capture_status="stored",
                    capture_source="live",
                    mime_type="image/png",
                    original_name="hidden-name.png",
                    storage_path=relative.as_posix(),
                    sha256=digest,
                    file_size=len(content),
                    width=18,
                    height=12,
                    integrity_verified=True,
                    received_at=utcnow(),
                    captured_at=utcnow(),
                )
            )
        session.add_all(rows)
        session.commit()

    manifest = reader.image_manifest(
        request_id="reader-cross-manifest",
        capability_token=grant["capability_token"],
        audience="openai_chatgpt",
        target_model="gpt-test",
    )
    assert manifest["images"] == []

    for archive_id, request_id in (
        ("cross-conversation-image", "reader-cross-read"),
        ("outbound-bound-image", "reader-outbound-read"),
    ):
        with pytest.raises(CustomerContextReadError) as denied:
            reader.read_image(
                archive_id,
                request_id=request_id,
                capability_token=grant["capability_token"],
                audience="openai_chatgpt",
                target_model="gpt-test",
            )
        assert denied.value.code == "image_not_in_grant"


def test_audit_commit_failure_releases_no_customer_content(
    tmp_path: Path, monkeypatch,
) -> None:
    _database, reader, grant, _conversation_id = seed(tmp_path)
    content_read = False

    def fail_authorization(**_kwargs):
        raise CustomerContextGatewayError("audit_unavailable", "审计不可用")

    def observe_content_read(_conversation_id: int):
        nonlocal content_read
        content_read = True
        return None

    monkeypatch.setattr(reader.gateway, "authorize_access", fail_authorization)
    monkeypatch.setattr(reader, "_latest_summary", observe_content_read)
    with pytest.raises(CustomerContextGatewayError) as denied:
        reader.read_text(
            request_id="reader-audit-failure",
            capability_token=grant["capability_token"],
            audience="openai_chatgpt",
            target_model="gpt-test",
        )
    assert denied.value.code == "audit_unavailable"
    assert content_read is False


def test_new_message_ingestion_does_not_trigger_context_access_or_model_run(
    tmp_path: Path,
) -> None:
    database, _reader, _grant, conversation_id = seed(tmp_path)
    with database.session() as session:
        before_audits = session.scalar(select(func.count(CustomerContextAccessAudit.id)))
        before_runs = session.scalar(select(func.count(GlobalAgentRun.id)))
        session.add(
            Message(
                channel="xianyu",
                platform_message_id="new-message-no-auto-analysis",
                external_id="new-message-no-auto-analysis",
                conversation_id=conversation_id,
                sender_id="reader-customer",
                sender_name="测试客户",
                direction="inbound",
                message_type="text",
                content="这是新补充，但不得自动调用模型。",
                status="new",
            )
        )
        session.commit()
    with database.session() as session:
        assert session.scalar(select(func.count(CustomerContextAccessAudit.id))) == before_audits
        assert session.scalar(select(func.count(GlobalAgentRun.id))) == before_runs


def test_legacy_chat_answers_are_not_promoted_to_customer_artifacts(
    tmp_path: Path,
) -> None:
    database, reader, grant, _conversation_id = seed(tmp_path)
    with database.session() as session:
        session.add(
            GlobalAgentMessage(
                id="legacy-artifact-assistant",
                thread_id="reader-agent-thread",
                role="assistant",
                content='{"requirement_analysis":{"summary":"旧聊天临时结果"}}',
                status="completed",
            )
        )
        session.commit()

    with pytest.raises(CustomerContextReadError) as missing:
        reader.customer_artifact(
            "requirement_document",
            request_id="reader-artifact-not-promoted",
            capability_token=grant["capability_token"],
            audience="openai_chatgpt",
            target_model="gpt-test",
        )
    assert missing.value.code == "artifact_not_found"
