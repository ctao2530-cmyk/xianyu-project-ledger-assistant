from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import stat

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import func, select

from backend.app.config import get_settings
from backend.app.database import Database
from backend.app.ledger import LedgerService, RevisionConflict
from backend.app.models import (
    BusinessCustomer,
    Conversation,
    CustomerChannelIdentity,
    LedgerMutationRequest,
    LedgerState,
    Message,
)
from backend.app.services.customer_intake import CustomerIntakeError, CustomerIntakeService
from backend.app.services.event_hub import EventHub


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


def strip_customer_intake_columns(path: Path) -> None:
    """Recreate the real pre-0036 shape despite 0001's live-metadata bootstrap."""

    with sqlite3.connect(path) as connection:
        for column in ("notes", "next_action", "price_amount", "price_type", "current_need"):
            connection.execute(f"ALTER TABLE business_customers DROP COLUMN {column}")


def build_service(tmp_path: Path) -> tuple[Database, LedgerService, CustomerIntakeService]:
    database = Database(f"sqlite:///{tmp_path / 'customer-intake.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    return database, ledger, CustomerIntakeService(database, ledger, EventHub())


def add_conversation(
    database: Database,
    *,
    suffix: str,
    customer_name: str,
    channel: str = "xianyu",
    content: str = "客户希望先确认需求范围",
) -> int:
    with database.session() as session:
        conversation = Conversation(
            channel=channel,
            external_id=f"intake-conversation-{suffix}",
            customer_id=f"intake-customer-{suffix}",
            customer_name=customer_name,
            last_message_at=datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc),
        )
        session.add(conversation)
        session.flush()
        session.add(
            Message(
                channel=channel,
                platform_message_id=f"intake-message-{suffix}",
                external_id=f"intake-message-{suffix}",
                conversation_id=conversation.id,
                sender_id=conversation.customer_id,
                sender_name=customer_name,
                direction="inbound",
                message_type="text",
                content=content,
                status="new",
                received_at=conversation.last_message_at,
            )
        )
        session.commit()
        return conversation.id


def test_candidates_are_read_only_hide_linked_relationships_and_do_not_merge_names(
    tmp_path: Path,
) -> None:
    database, _ledger, service = build_service(tmp_path)
    available_id = add_conversation(
        database, suffix="available", customer_name="同名客户"
    )
    linked_id = add_conversation(database, suffix="linked", customer_name="已绑定客户")
    with database.session() as session:
        session.add_all(
            (
                BusinessCustomer(id="existing-same-name", name="同名客户"),
                BusinessCustomer(id="existing-linked", name="已绑定客户"),
            )
        )
        linked = session.get(Conversation, linked_id)
        assert linked is not None
        session.add(
            CustomerChannelIdentity(
                id="identity-linked",
                customer_id="existing-linked",
                channel=linked.channel,
                external_customer_id=linked.customer_id,
                conversation_id=linked.id,
                display_name=linked.customer_name,
            )
        )
        session.commit()
        revision_before = session.get(LedgerState, 1).revision
        requests_before = session.scalar(
            select(func.count()).select_from(LedgerMutationRequest)
        )

    first = service.candidates()
    second = service.candidates()
    assert first == second
    assert [row["conversation_id"] for row in first["candidates"]] == [available_id]
    assert first["candidates"][0]["same_name_exists"] is True
    assert first["candidates"][0]["last_text_preview"] == "客户希望先确认需求范围"
    with database.session() as session:
        assert session.get(LedgerState, 1).revision == revision_before
        assert session.scalar(
            select(func.count()).select_from(LedgerMutationRequest)
        ) == requests_before


def test_customer_create_is_revision_protected_idempotent_and_binds_exact_conversation(
    tmp_path: Path,
) -> None:
    database, ledger, service = build_service(tmp_path)
    conversation_id = add_conversation(
        database, suffix="create", customer_name="王同学"
    )
    revision, _snapshot = ledger.get()
    payload = {
        "request_id": "customer-create-test-001",
        "expected_revision": revision,
        "conversation_id": conversation_id,
        "name": "王同学",
        "source": "wechat",  # Bound conversation source must win.
        "phone": "",
        "level": "B",
        "current_need": "开发一个商品展示页",
        "price_type": "operator_quote",
        "price_amount": 2600.0,
        "next_action": "人工确认交付范围",
        "notes": "等待客户补充域名信息",
    }
    result = service.create_customer(**payload)
    assert result["revision"] == revision + 1
    assert result["created"] is True
    assert result["idempotent"] is False
    created = next(
        customer
        for customer in result["snapshot"]["customers"]
        if customer["id"] == result["customer_id"]
    )
    assert created["source"] == "xianyu"
    assert created["currentNeed"] == "开发一个商品展示页"
    assert created["priceType"] == "operator_quote"
    assert created["priceAmount"] == 2600.0
    assert created["nextAction"] == "人工确认交付范围"
    assert created["notes"] == "等待客户补充域名信息"

    replay = service.create_customer(**payload)
    assert replay["customer_id"] == result["customer_id"]
    assert replay["revision"] == result["revision"]
    assert replay["idempotent"] is True
    with database.session() as session:
        row = session.get(BusinessCustomer, result["customer_id"])
        identity = session.scalar(
            select(CustomerChannelIdentity).where(
                CustomerChannelIdentity.conversation_id == conversation_id
            )
        )
        assert row is not None and row.current_need == "开发一个商品展示页"
        assert row.price_amount == 2600.0
        assert identity is not None and identity.customer_id == row.id
        assert session.scalar(
            select(func.count()).select_from(LedgerMutationRequest).where(
                LedgerMutationRequest.operation == "customer_create"
            )
        ) == 1

    with pytest.raises(CustomerIntakeError, match="请求编号"):
        service.create_customer(**{**payload, "name": "复用请求编号"})
    with pytest.raises(CustomerIntakeError, match="已经加入客户列表"):
        service.create_customer(
            **{
                **payload,
                "request_id": "customer-create-test-002",
                "expected_revision": result["revision"],
            }
        )
    with pytest.raises(RevisionConflict):
        service.create_customer(
            **{
                **payload,
                "request_id": "customer-create-test-003",
                "conversation_id": None,
                "expected_revision": revision,
            }
        )


def test_customer_create_does_not_guess_or_write_when_relationship_changes(
    tmp_path: Path,
) -> None:
    database, ledger, service = build_service(tmp_path)
    conversation_id = add_conversation(
        database, suffix="race", customer_name="关系变化客户"
    )
    revision, before = ledger.get()
    with database.session() as session:
        session.add(BusinessCustomer(id="customer-existing-race", name="已有客户"))
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None
        session.add(
            CustomerChannelIdentity(
                id="identity-race",
                customer_id="customer-existing-race",
                channel=conversation.channel,
                external_customer_id=conversation.customer_id,
                conversation_id=conversation.id,
                display_name=conversation.customer_name,
            )
        )
        session.commit()

    with pytest.raises(CustomerIntakeError, match="已经加入客户列表"):
        service.create_customer(
            request_id="customer-create-race-001",
            expected_revision=revision,
            conversation_id=conversation_id,
            name="关系变化客户",
            source="xianyu",
            phone="",
            level="C",
            current_need="",
            price_type="",
            price_amount=None,
            next_action="",
            notes="",
        )
    after_revision, after = ledger.get()
    assert after_revision == revision
    assert after == before
    with database.session() as session:
        assert session.get(LedgerMutationRequest, "customer-create-race-001") is None


def test_0035_to_0036_and_startup_migration_are_complete_idempotent_and_private(
    tmp_path: Path,
) -> None:
    alembic_path = tmp_path / "alembic.db"
    upgrade(alembic_path, "20260819_0035")
    strip_customer_intake_columns(alembic_path)
    upgrade(alembic_path, "20260820_0036")
    expected = {"current_need", "price_type", "price_amount", "next_action", "notes"}
    with sqlite3.connect(alembic_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(business_customers)")
        }
        assert expected <= columns
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260820_0036",
        )
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []

    startup_path = tmp_path / "startup.db"
    upgrade(startup_path, "20260819_0035")
    strip_customer_intake_columns(startup_path)
    database = Database(f"sqlite:///{startup_path}")
    database.create_all()
    database.create_all()
    backups = list((tmp_path / "backups").glob("startup-before-customer-intake-*.db"))
    assert len(backups) == 1
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    with sqlite3.connect(startup_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(business_customers)")
        }
        assert expected <= columns
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []


def test_startup_rejects_partial_customer_intake_schema(tmp_path: Path) -> None:
    path = tmp_path / "partial.db"
    upgrade(path, "20260819_0035")
    strip_customer_intake_columns(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "ALTER TABLE business_customers ADD COLUMN current_need TEXT NOT NULL DEFAULT ''"
        )
    with pytest.raises(RuntimeError, match="customer intake schema is incomplete"):
        Database(f"sqlite:///{path}").create_all()
