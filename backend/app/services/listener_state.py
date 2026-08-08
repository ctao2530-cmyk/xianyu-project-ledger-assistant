from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete

from ..database import Database
from ..models import ListenerStatusLog, utcnow
from .status import RuntimeStatus


logger = logging.getLogger(__name__)


class ListenerStateTracker:
    """Update live state and persist only sanitized state transitions."""

    def __init__(
        self,
        database: Database,
        runtime_status: RuntimeStatus,
        *,
        retention_days: int = 30,
    ) -> None:
        self.database = database
        self.runtime_status = runtime_status
        self.retention_days = retention_days

    def record(
        self,
        status: str,
        detail: str | None = None,
        *,
        error_type: str | None = None,
        force: bool = False,
    ) -> None:
        changed = (
            self.runtime_status.listener != status
            or self.runtime_status.listener_detail != detail
        )
        self.runtime_status.listener = status
        self.runtime_status.listener_detail = detail
        if not changed and not force:
            return

        log = logger.warning if error_type else logger.info
        log(
            "闲鱼监听状态：%s detail=%s error_type=%s",
            status,
            detail or "-",
            error_type or "-",
        )
        cutoff = utcnow() - timedelta(days=self.retention_days)
        with self.database.session() as session:
            session.add(
                ListenerStatusLog(
                    status=status,
                    detail=detail,
                    error_type=error_type,
                )
            )
            session.execute(
                delete(ListenerStatusLog).where(
                    ListenerStatusLog.created_at < cutoff
                )
            )
            session.commit()
