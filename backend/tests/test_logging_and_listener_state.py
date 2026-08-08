from __future__ import annotations

import logging

from sqlalchemy import select

from backend.app.database import Database
from backend.app.logging_config import configure_logging
from backend.app.models import ListenerStatusLog
from backend.app.services.listener_state import ListenerStateTracker
from backend.app.services.status import RuntimeStatus


def test_rotating_file_log_redacts_secrets(tmp_path) -> None:
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    log_file = tmp_path / "backend.log"
    try:
        configure_logging(
            "INFO",
            secrets=("complete-secret-value",),
            file_path=str(log_file),
            max_bytes=100_000,
            backup_count=2,
        )
        logging.getLogger("test.logging").warning(
            "cookie=complete-secret-value token=temporary-token"
        )
        for handler in root.handlers:
            handler.flush()
        content = log_file.read_text(encoding="utf-8")
        assert "complete-secret-value" not in content
        assert "temporary-token" not in content
        assert content.count("[REDACTED]") >= 2
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = old_handlers
        root.setLevel(old_level)


def test_listener_state_tracker_persists_only_transitions(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'listener-logs.db'}")
    database.create_all()
    status = RuntimeStatus()
    tracker = ListenerStateTracker(database, status)

    tracker.record("connecting", "正在连接")
    tracker.record("connecting", "正在连接")
    tracker.record(
        "reconnecting",
        "连接中断（TimeoutError），5 秒后重试",
        error_type="TimeoutError",
    )
    tracker.record("connected")

    with database.session() as session:
        rows = list(
            session.scalars(
                select(ListenerStatusLog).order_by(ListenerStatusLog.id)
            )
        )
    assert [row.status for row in rows] == [
        "connecting",
        "reconnecting",
        "connected",
    ]
    assert rows[1].error_type == "TimeoutError"
    assert status.listener == "connected"
    assert status.listener_detail is None
