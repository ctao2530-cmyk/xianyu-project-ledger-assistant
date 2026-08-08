from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy import func, select

from ..ai import AIProvider
from ..database import Database
from ..models import AIGenerationTask, OperationLog
from .status import RuntimeStatus
from .automation import AutoReplyService
from .style_learning import StyleLearningService


def _local_day_start_utc() -> datetime:
    local_now = datetime.now().astimezone()
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=local_now.tzinfo)
    return local_start.astimezone(timezone.utc)


def build_desktop_status_event(
    database: Database,
    runtime_status: RuntimeStatus,
    provider: AIProvider,
    automation: AutoReplyService | None = None,
    style_learning: StyleLearningService | None = None,
) -> dict[str, object]:
    start = _local_day_start_utc()
    with database.session() as session:
        pending = session.scalar(
            select(func.count()).select_from(AIGenerationTask).where(
                AIGenerationTask.status == "pending"
            )
        ) or 0
        running = session.scalar(
            select(func.count()).select_from(AIGenerationTask).where(
                AIGenerationTask.status == "running"
            )
        ) or 0
        today_messages = session.scalar(
            select(func.count()).select_from(OperationLog).where(
                OperationLog.action == "message_received",
                OperationLog.created_at >= start,
            )
        ) or 0
        today_generated = session.scalar(
            select(func.count()).select_from(OperationLog).where(
                OperationLog.action == "ai_task_completed",
                OperationLog.created_at >= start,
            )
        ) or 0

    if provider.status == "connected":
        codex = "running" if running else "ready"
    else:
        codex = "error"
    if running:
        ai_task = "generating"
    elif pending:
        ai_task = "waiting"
    elif today_generated:
        ai_task = "completed"
    else:
        ai_task = "idle"
    automation_state = automation.snapshot() if automation else None
    style = style_learning.snapshot() if style_learning else None
    return {
        "type": "status",
        "listener": runtime_status.listener,
        "listener_detail": runtime_status.listener_detail,
        "codex": codex,
        "codex_detail": provider.detail,
        "ai_task": ai_task,
        "pending_tasks": pending,
        "running_tasks": running,
        "today_messages": today_messages,
        "today_generated": today_generated,
        "auto_reply_enabled": automation_state.enabled if automation_state else False,
        "auto_reply_enabled_until": (
            automation_state.enabled_until.isoformat()
            if automation_state and automation_state.enabled_until
            else None
        ),
        "auto_reply_remaining_seconds": (
            automation_state.remaining_seconds if automation_state else 0
        ),
        "auto_reply_daily_sent": automation_state.daily_sent if automation_state else 0,
        "auto_reply_daily_limit": automation_state.daily_limit if automation_state else 0,
        "style_learning_enabled": style.enabled if style else False,
        "style_sample_count": style.sample_count if style else 0,
        "style_summary": style.summary if style else "",
        "style_traits": list(style.traits) if style else [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
