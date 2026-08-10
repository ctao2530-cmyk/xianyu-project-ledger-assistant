from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.database import Database
from backend.app.ledger_api import ledger_router
from backend.app.models import Conversation


def test_operations_summary_returns_highest_priority_pending_conversation(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'operations.db'}")
    database.create_all()
    now = datetime.now(timezone.utc)
    with database.session() as session:
        low_unread = Conversation(
            channel="xianyu",
            external_id="conversation-low",
            customer_id="customer-low",
            customer_name="低优先级",
            unread_count=1,
            last_message_at=now,
        )
        high_unread = Conversation(
            channel="xianyu",
            external_id="conversation-high",
            customer_id="customer-high",
            customer_name="高优先级",
            unread_count=3,
            last_message_at=now - timedelta(hours=1),
        )
        read = Conversation(
            channel="xianyu",
            external_id="conversation-read",
            customer_id="customer-read",
            customer_name="已读会话",
            unread_count=0,
            last_message_at=now + timedelta(minutes=1),
        )
        session.add_all([low_unread, high_unread, read])
        session.commit()
        expected_id = high_unread.id

    app = FastAPI()
    app.include_router(ledger_router)
    app.state.runtime = SimpleNamespace(database=database)
    response = TestClient(app).get("/api/operations/summary")

    assert response.status_code == 200
    assert response.json() == {
        "unread": 4,
        "pending_replies": 2,
        "first_pending_conversation_id": expected_id,
        "open_leads": 0,
        "quoted_leads": 0,
        "converted_leads": 0,
    }
