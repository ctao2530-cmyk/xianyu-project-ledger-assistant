from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy import select

from backend.app.database import Database
from backend.app.ledger_api import ledger_router
from backend.app.models import Conversation, Message, MessageAttachment
from backend.app.services.requirement_exchange import RequirementExchangeError, RequirementExchangeService
from backend.app.services.requirement_materials import RequirementMaterialsService


def image_bytes(
    color: tuple[int, int, int] = (108, 76, 232),
    *,
    image_format: str = "PNG",
    include_exif: bool = False,
) -> bytes:
    image = Image.new("RGB", (80, 54), color)
    output = BytesIO()
    options = {}
    if include_exif:
        exif = Image.Exif()
        exif[0x010E] = "private note"
        exif[0x013B] = "customer name"
        options["exif"] = exif
    image.save(output, format=image_format, **options)
    return output.getvalue()


def build_service(tmp_path: Path) -> tuple[Database, RequirementMaterialsService, int, int, int]:
    database = Database(f"sqlite:///{tmp_path / 'data' / 'materials.db'}")
    database.create_all()
    with database.session() as session:
        first = Conversation(
            channel="xianyu",
            external_id="materials-conversation",
            customer_id="external-customer",
            customer_name="测试客户 13800138000",
        )
        second = Conversation(
            channel="xianyu",
            external_id="other-conversation",
            customer_id="other-customer",
            customer_name="其他客户",
        )
        session.add_all([first, second])
        session.flush()
        rows = [
            Message(
                channel="xianyu",
                platform_message_id="materials-text",
                external_id="materials-text",
                conversation_id=first.id,
                sender_id="external-customer",
                sender_name="客户",
                direction="inbound",
                message_type="text",
                content="需要一个订单后台，邮箱 demo@example.com",
                status="new",
                received_at=datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc),
            ),
            Message(
                channel="xianyu",
                platform_message_id="materials-placeholder",
                external_id="materials-placeholder",
                conversation_id=first.id,
                sender_id="external-customer",
                sender_name="客户",
                direction="inbound",
                message_type="text",
                content="[图片]",
                status="new",
                received_at=datetime(2026, 8, 14, 1, 1, tzinfo=timezone.utc),
            ),
            Message(
                channel="xianyu",
                platform_message_id="materials-image",
                external_id="materials-image",
                conversation_id=first.id,
                sender_id="external-customer",
                sender_name="客户",
                direction="inbound",
                message_type="image",
                content="界面参考",
                status="new",
                received_at=datetime(2026, 8, 14, 1, 2, tzinfo=timezone.utc),
            ),
        ]
        session.add_all(rows)
        session.commit()
        return (
            database,
            RequirementMaterialsService(
                database,
                RequirementExchangeService(database),
                tmp_path,
            ),
            first.id,
            second.id,
            rows[1].id,
        )


def test_empty_conversation_exports_complete_text_only_package(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'data' / 'empty-materials.db'}")
    database.create_all()
    with database.session() as session:
        conversation = Conversation(
            channel="xianyu",
            external_id="empty-materials-conversation",
            customer_id="empty-customer",
            customer_name="空会话",
        )
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id
    service = RequirementMaterialsService(
        database,
        RequirementExchangeService(database),
        tmp_path,
    )

    preview = service.preview(conversation_id)
    result = service.create_package(
        conversation_id,
        attachment_ids=[],
        allow_incomplete=False,
    )

    assert preview["text_message_count"] == 0
    assert preview["image_candidate_count"] == 0
    assert preview["missing_image_count"] == 0
    assert preview["package_complete"] is True
    assert result["package_complete"] is True
    assert Path(result["readme_path"]).is_file()
    assert Path(result["package_root"], "images").is_dir()
    assert not Path(result["package_root"], "contact-sheet-01.png").exists()


def test_preview_detects_text_placeholders_orders_images_and_deduplicates(tmp_path: Path) -> None:
    database, service, conversation_id, _other_id, placeholder_message_id = build_service(tmp_path)
    before = service.preview(conversation_id)

    assert before["text_message_count"] == 1
    assert before["image_candidate_count"] == 2
    assert before["missing_image_count"] == 2
    assert [candidate["label"] for candidate in before["image_candidates"]] == ["M0002", "M0003"]
    assert before["redaction_count"] == 2

    first = service.add_attachment(
        conversation_id,
        data=image_bytes(),
        content_type="image/png",
        original_name="reference.png",
        message_id=placeholder_message_id,
    )
    duplicate = service.add_attachment(
        conversation_id,
        data=image_bytes(),
        content_type="image/png",
        original_name="same-image.png",
        message_id=placeholder_message_id,
    )
    after = service.preview(conversation_id)

    assert duplicate["id"] == first["id"]
    assert duplicate["duplicate"] is True
    assert after["captured_image_count"] == 1
    assert after["missing_image_count"] == 1
    with database.session() as session:
        assert len(list(session.scalars(select(MessageAttachment)))) == 1

    second_message_id = before["image_candidates"][1]["message_id"]
    second_reference = service.add_attachment(
        conversation_id,
        data=image_bytes(),
        content_type="image/png",
        original_name=r"C:\private\same-reference.png",
        message_id=second_message_id,
    )
    completed = service.preview(conversation_id)
    first_path, _first_mime, _first_name = service.attachment_file(conversation_id, first["id"])
    second_path, _second_mime, second_name = service.attachment_file(
        conversation_id,
        second_reference["id"],
    )

    assert second_reference["id"] != first["id"]
    assert second_reference["duplicate"] is False
    assert second_name == "same-reference.png"
    assert first_path == second_path
    assert completed["missing_image_count"] == 0
    assert completed["captured_image_count"] == 2
    assert completed["total_bytes"] == first["file_size"]
    service.delete_attachment(conversation_id, first["id"])
    assert second_path.is_file()
    assert service.attachment_file(conversation_id, second_reference["id"])[0] == second_path


def test_package_requires_review_marks_missing_and_strips_exif(tmp_path: Path) -> None:
    _database, service, conversation_id, _other_id, placeholder_message_id = build_service(tmp_path)
    attachment = service.add_attachment(
        conversation_id,
        data=image_bytes(image_format="JPEG", include_exif=True),
        content_type="image/jpeg",
        original_name="customer-private.jpg",
        message_id=placeholder_message_id,
    )
    stored_path, _mime, _name = service.attachment_file(conversation_id, attachment["id"])
    with Image.open(stored_path) as normalized:
        assert dict(normalized.getexif()) == {}

    with pytest.raises(RequirementExchangeError) as unreviewed:
        service.create_package(
            conversation_id,
            attachment_ids=[attachment["id"]],
            allow_incomplete=True,
        )
    assert unreviewed.value.code == "privacy_review_required"

    service.update_privacy(conversation_id, attachment["id"], "reviewed")
    with pytest.raises(RequirementExchangeError) as incomplete:
        service.create_package(
            conversation_id,
            attachment_ids=[attachment["id"]],
            allow_incomplete=False,
        )
    assert incomplete.value.code == "incomplete_package"

    result = service.create_package(
        conversation_id,
        attachment_ids=[attachment["id"]],
        allow_incomplete=True,
    )
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    readme = Path(result["readme_path"]).read_text(encoding="utf-8")

    assert result["package_complete"] is False
    assert result["missing_image_count"] == 1
    assert manifest["missing_message_numbers"] == [3]
    assert manifest["attachments"][0]["message_number"] == 2
    assert "conversation_id" not in manifest
    assert "attachment_id" not in manifest["attachments"][0]
    assert "明确标记为不完整" in readme
    assert "对话和图片" in result["codex_prompt"]
    assert "不执行" in result["codex_prompt"]
    assert Path(result["package_root"], "contact-sheet-01.png").is_file()


@pytest.mark.parametrize(
    ("payload", "content_type", "expected_code"),
    [
        (b"not-an-image", "image/png", "attachment_corrupt"),
        (image_bytes(), "image/jpeg", "attachment_mime_mismatch"),
        (image_bytes(), "application/octet-stream", "attachment_type_invalid"),
    ],
)
def test_image_validation_rejects_corrupt_or_spoofed_files(
    tmp_path: Path,
    payload: bytes,
    content_type: str,
    expected_code: str,
) -> None:
    _database, service, conversation_id, _other_id, placeholder_message_id = build_service(tmp_path)
    with pytest.raises(RequirementExchangeError) as exc_info:
        service.add_attachment(
            conversation_id,
            data=payload,
            content_type=content_type,
            original_name="reference.png",
            message_id=placeholder_message_id,
        )
    assert exc_info.value.code == expected_code


def test_limits_cross_conversation_and_path_traversal_are_enforced(tmp_path: Path) -> None:
    database, service, conversation_id, other_id, placeholder_message_id = build_service(tmp_path)
    attachment = service.add_attachment(
        conversation_id,
        data=image_bytes(),
        content_type="image/png",
        original_name="reference.png",
        message_id=placeholder_message_id,
    )
    with pytest.raises(RequirementExchangeError) as cross_conversation:
        service.attachment_file(other_id, attachment["id"])
    assert cross_conversation.value.code == "attachment_not_found"

    service.MAX_IMAGE_BYTES = 10
    with pytest.raises(RequirementExchangeError) as too_large:
        service.add_attachment(
            conversation_id,
            data=b"x" * 11,
            content_type="image/png",
            original_name="large.png",
        )
    assert too_large.value.code == "attachment_too_large"

    with database.session() as session:
        row = session.get(MessageAttachment, attachment["id"])
        assert row is not None
        row.storage_path = "../outside-private.png"
        session.commit()
    with pytest.raises(RequirementExchangeError) as traversal:
        service.attachment_file(conversation_id, attachment["id"])
    assert traversal.value.code == "attachment_not_found"


def test_total_and_count_limits_are_enforced_without_partial_writes(tmp_path: Path) -> None:
    _database, service, conversation_id, _other_id, placeholder_message_id = build_service(tmp_path)
    service.MAX_TOTAL_BYTES = 100
    with pytest.raises(RequirementExchangeError) as total_limit:
        service.add_attachment(
            conversation_id,
            data=image_bytes(),
            content_type="image/png",
            original_name="reference.png",
            message_id=placeholder_message_id,
        )
    assert total_limit.value.code == "attachment_total_too_large"
    assert list(service.attachments_root.rglob("*.png")) == []

    service.MAX_TOTAL_BYTES = 40 * 1024 * 1024
    service.MAX_IMAGES = 0
    with pytest.raises(RequirementExchangeError) as count_limit:
        service.add_attachment(
            conversation_id,
            data=image_bytes(color=(40, 130, 210)),
            content_type="image/png",
            original_name="second.png",
        )
    assert count_limit.value.code == "attachment_limit_reached"
    assert list(service.attachments_root.rglob("*.png")) == []


def test_package_filesystem_failure_removes_temporary_output(tmp_path: Path) -> None:
    _database, service, conversation_id, _other_id, _placeholder_message_id = build_service(tmp_path)
    service.exports_root.parent.mkdir(parents=True, exist_ok=True)
    service.exports_root.write_text("blocks directory creation", encoding="utf-8")

    with pytest.raises(RequirementExchangeError) as exc_info:
        service.create_package(conversation_id, attachment_ids=[], allow_incomplete=True)

    assert exc_info.value.code == "package_write_failed"
    assert not list(service.exports_root.parent.glob(".reqexp-*.tmp"))


def test_requirement_material_api_upload_review_export_and_scope(tmp_path: Path) -> None:
    _database, service, conversation_id, other_id, _placeholder_message_id = build_service(tmp_path)
    app = FastAPI()
    app.include_router(ledger_router)
    app.state.runtime = SimpleNamespace(requirement_materials=service)
    client = TestClient(app)

    preview = client.get(f"/api/conversations/{conversation_id}/requirement-export-preview")
    assert preview.status_code == 200
    assert preview.json()["missing_image_count"] == 2

    upload = client.post(
        f"/api/conversations/{conversation_id}/requirement-attachments",
        files={"file": ("reference.png", image_bytes(), "image/png")},
        data={"source": "manual"},
    )
    assert upload.status_code == 201
    attachment_id = upload.json()["id"]

    cross = client.get(
        f"/api/conversations/{other_id}/requirement-attachments/{attachment_id}/content"
    )
    assert cross.status_code == 404

    reviewed = client.patch(
        f"/api/conversations/{conversation_id}/requirement-attachments/{attachment_id}",
        json={"privacy_status": "reviewed"},
    )
    assert reviewed.status_code == 200
    content = client.get(
        f"/api/conversations/{conversation_id}/requirement-attachments/{attachment_id}/content"
    )
    assert content.status_code == 200
    assert content.headers["cache-control"] == "private, no-store, max-age=0"
    package = client.post(
        f"/api/conversations/{conversation_id}/requirement-export-package",
        json={
            "confirmed": True,
            "attachment_ids": [attachment_id],
            "allow_incomplete": True,
        },
    )
    assert package.status_code == 200
    assert Path(package.json()["readme_path"]).is_file()

    missing_confirmation = client.post(
        f"/api/conversations/{conversation_id}/requirement-export-package",
        json={
            "confirmed": False,
            "attachment_ids": [attachment_id],
            "allow_incomplete": True,
        },
    )
    assert missing_confirmation.status_code == 422


def test_requirement_material_api_returns_500_for_database_failure(tmp_path: Path) -> None:
    _database, service, conversation_id, _other_id, _placeholder_message_id = build_service(tmp_path)

    def broken_session():
        raise OperationalError("SELECT conversations", {}, RuntimeError("database offline"))

    service.database.session = broken_session  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(ledger_router)
    app.state.runtime = SimpleNamespace(requirement_materials=service)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        f"/api/conversations/{conversation_id}/requirement-export-preview"
    )

    assert response.status_code == 500
