from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select

from ..config import Settings
from ..database import Database
from ..models import (
    AIGenerationTask,
    AutomationState,
    Draft,
    Message,
    OperationLog,
    utcnow,
)
from ..rate_limit import SlidingWindowRateLimiter
from .actions import ActionConflictError, HumanActions, MessageNotFoundError
from .notifier import MacOSNotifier
from .risk import detect_risks
from .status import RuntimeStatus


ENABLE_CONFIRMATION = "我确认开启无人值守自动回复"


class AutomationUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class AutomationSnapshot:
    feature_enabled: bool
    enabled: bool
    enabled_until: datetime | None
    remaining_seconds: int
    disabled_reason: str | None
    consecutive_failures: int
    daily_sent: int
    daily_limit: int
    max_duration_minutes: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _local_day_start_utc() -> datetime:
    local_now = datetime.now().astimezone()
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=local_now.tzinfo)
    return local_start.astimezone(timezone.utc)


class AutoReplyService:
    """Fail-closed gate between completed AI drafts and channel senders."""

    def __init__(
        self,
        database: Database,
        actions: HumanActions,
        notifier: MacOSNotifier,
        settings: Settings,
        runtime_status: RuntimeStatus,
        send_limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        self.database = database
        self.actions = actions
        self.notifier = notifier
        self.settings = settings
        self.runtime_status = runtime_status
        self.send_limiter = send_limiter
        self._lock = asyncio.Lock()

    def _load_state(self, session) -> AutomationState:
        state = session.get(AutomationState, 1)
        if state is None:
            state = AutomationState(
                id=1,
                enabled=False,
                disabled_reason="默认关闭，等待用户手动开启",
            )
            session.add(state)
            session.flush()
        return state

    def snapshot(self) -> AutomationSnapshot:
        now = utcnow()
        with self.database.session() as session:
            state = self._load_state(session)
            enabled_until = _as_utc(state.enabled_until)
            if state.enabled and (enabled_until is None or enabled_until <= now):
                state.enabled = False
                state.disabled_reason = "授权时间已结束"
                session.add(
                    OperationLog(
                        action="auto_reply_disabled",
                        detail="无人值守授权时间已结束",
                    )
                )
                session.commit()
            daily_sent = session.scalar(
                select(func.count())
                .select_from(OperationLog)
                .where(
                    OperationLog.action == "auto_reply_sent",
                    OperationLog.created_at >= _local_day_start_utc(),
                )
            ) or 0
            if state.enabled and daily_sent >= self.settings.auto_reply_daily_limit:
                state.enabled = False
                state.enabled_until = None
                state.disabled_reason = "已达到今日自动回复上限"
                session.add(
                    OperationLog(
                        action="auto_reply_disabled",
                        detail="已达到今日自动回复上限",
                    )
                )
                session.commit()
            enabled_until = _as_utc(state.enabled_until)
            enabled = bool(
                self.settings.auto_reply_feature_enabled
                and state.enabled
                and enabled_until is not None
                and enabled_until > now
                and daily_sent < self.settings.auto_reply_daily_limit
            )
            remaining = max(0, int((enabled_until - now).total_seconds())) if enabled else 0
            snapshot = AutomationSnapshot(
                feature_enabled=self.settings.auto_reply_feature_enabled,
                enabled=enabled,
                enabled_until=enabled_until if enabled else None,
                remaining_seconds=remaining,
                disabled_reason=None if enabled else state.disabled_reason,
                consecutive_failures=state.consecutive_failures,
                daily_sent=daily_sent,
                daily_limit=self.settings.auto_reply_daily_limit,
                max_duration_minutes=self.settings.auto_reply_max_minutes,
            )
            session.commit()
            return snapshot

    async def enable(self, duration_minutes: int | None = None) -> AutomationSnapshot:
        if not self.settings.auto_reply_feature_enabled:
            raise AutomationUnavailableError("无人值守功能已被环境配置禁用")
        if self.snapshot().daily_sent >= self.settings.auto_reply_daily_limit:
            raise AutomationUnavailableError("今日自动回复数量已达到安全上限")
        requested = duration_minutes or self.settings.auto_reply_default_minutes
        duration = min(requested, self.settings.auto_reply_max_minutes)
        now = utcnow()
        with self.database.session() as session:
            state = self._load_state(session)
            state.enabled = True
            state.enabled_at = now
            state.enabled_until = now + timedelta(minutes=duration)
            state.disabled_reason = None
            state.consecutive_failures = 0
            session.add(
                OperationLog(
                    action="auto_reply_enabled",
                    detail=f"用户开启无人值守自动回复，有效 {duration} 分钟",
                )
            )
            session.commit()
        await self.notifier.notify(
            "鱼答：无人值守已开启",
            f"仅低风险消息可自动回复，将在 {duration} 分钟后自动关闭。",
            "报价、退款、交付时间等仍需人工处理",
        )
        return self.snapshot()

    async def disable(self, reason: str = "用户手动关闭") -> AutomationSnapshot:
        with self.database.session() as session:
            state = self._load_state(session)
            state.enabled = False
            state.enabled_until = None
            state.disabled_reason = reason
            session.add(
                OperationLog(action="auto_reply_disabled", detail=reason)
            )
            session.commit()
        await self.notifier.notify(
            "鱼答：无人值守已关闭",
            reason,
            "后续消息只生成草稿，不会自动发送",
        )
        return self.snapshot()

    async def handle_completed(self, message_id: int) -> str:
        """Return a safe outcome label consumed by desktop events."""
        if not self.snapshot().enabled:
            return "disabled"

        eligibility = self._eligibility(message_id)
        if eligibility != "eligible":
            return eligibility

        if self.settings.auto_reply_debounce_seconds:
            await asyncio.sleep(self.settings.auto_reply_debounce_seconds)

        async with self._lock:
            if not self.snapshot().enabled:
                return "disabled"
            eligibility = self._eligibility(message_id)
            if eligibility != "eligible":
                return eligibility

            try:
                channel = self.actions.channel_for_message(message_id)
            except MessageNotFoundError:
                return "stale"
            if self.send_limiter and not await self.send_limiter.allow(
                f"{channel}_send"
            ):
                with self.database.session() as session:
                    self._log_skip(session, message_id, "已达到全局每分钟发送上限")
                return "rate_limited"

            with self.database.session() as session:
                message = session.get(Message, message_id)
                draft = session.scalar(
                    select(Draft).where(
                        Draft.message_id == message_id,
                        Draft.style == "简洁直接",
                    )
                )
                reply = draft.content.strip() if draft else ""
                customer_name = message.conversation.customer_name if message else "闲鱼客户"

            try:
                await self.actions.auto_send(message_id, reply)
            except (ActionConflictError, MessageNotFoundError):
                return "stale"
            except Exception as exc:
                disabled = self._record_failure(message_id, type(exc).__name__)
                if disabled:
                    await self.notifier.notify(
                        "鱼答：无人值守已自动关闭",
                        "连续发送失败达到安全阈值，请检查闲鱼登录和连接状态。",
                        "不会继续自动发送",
                    )
                return "failed"

            with self.database.session() as session:
                state = self._load_state(session)
                state.consecutive_failures = 0
                state.last_auto_reply_at = utcnow()
                session.commit()
            await self.notifier.notify(
                "鱼答已自动回复",
                "低风险回复已通过无人值守模式发送。",
                customer_name,
            )
            return "sent"

    def _eligibility(self, message_id: int) -> str:
        if self.runtime_status.listener != "connected":
            return "listener_unavailable"
        snapshot = self.snapshot()
        if not snapshot.enabled:
            return "disabled"
        if snapshot.daily_sent >= snapshot.daily_limit:
            return "daily_limit"

        with self.database.session() as session:
            message = session.get(Message, message_id)
            if (
                not message
                or message.direction != "inbound"
                or message.message_type != "text"
                or message.status != "drafted"
            ):
                return "stale"
            if message.channel != "xianyu":
                self._log_skip(
                    session,
                    message.id,
                    "当前渠道发送器仍为 Mock，仅允许人工确认",
                )
                return "channel_requires_human_confirmation"

            latest_inbound_id = session.scalar(
                select(Message.id)
                .where(
                    Message.conversation_id == message.conversation_id,
                    Message.direction == "inbound",
                )
                .order_by(Message.received_at.desc(), Message.id.desc())
                .limit(1)
            )
            if latest_inbound_id != message.id:
                self._log_skip(session, message.id, "新消息已到达，旧草稿不自动发送")
                return "stale"

            task = session.scalar(
                select(AIGenerationTask)
                .where(
                    AIGenerationTask.message_id == message.id,
                    AIGenerationTask.status == "completed",
                )
                .order_by(AIGenerationTask.id.desc())
                .limit(1)
            )
            reasons: list[str] = []
            if task:
                try:
                    parsed = json.loads(task.risk_reasons_json)
                    reasons = parsed if isinstance(parsed, list) else []
                except json.JSONDecodeError:
                    reasons = ["风险信息无法解析"]
            if not task or task.risk_level != "low" or reasons:
                self._log_skip(session, message.id, "AI 风险等级不允许自动回复")
                return "blocked_risk"

            draft = session.scalar(
                select(Draft).where(
                    Draft.message_id == message.id,
                    Draft.style == "简洁直接",
                )
            )
            reply = draft.content.strip() if draft else ""
            if not 20 <= len(reply) <= 100 or detect_risks(reply):
                self._log_skip(session, message.id, "草稿触发本地风险规则")
                return "blocked_risk"

            source_flags = detect_risks(message.content)
            if source_flags:
                self._log_skip(session, message.id, "客户消息涉及需人工确认内容")
                return "blocked_risk"

            last_sent = session.scalar(
                select(OperationLog.created_at)
                .join(Message, OperationLog.message_id == Message.id)
                .where(
                    OperationLog.action == "auto_reply_sent",
                    Message.conversation_id == message.conversation_id,
                )
                .order_by(OperationLog.created_at.desc())
                .limit(1)
            )
            last_sent_utc = _as_utc(last_sent)
            if last_sent_utc and (
                utcnow() - last_sent_utc
            ).total_seconds() < self.settings.auto_reply_conversation_cooldown_seconds:
                self._log_skip(session, message.id, "同一会话仍在自动回复冷却期")
                return "cooldown"
        return "eligible"

    @staticmethod
    def _log_skip(session, message_id: int, detail: str) -> None:
        already_logged = session.scalar(
            select(OperationLog.id)
            .where(
                OperationLog.message_id == message_id,
                OperationLog.action == "auto_reply_skipped",
                OperationLog.detail == detail,
            )
            .limit(1)
        )
        if already_logged is None:
            session.add(
                OperationLog(
                    message_id=message_id,
                    action="auto_reply_skipped",
                    detail=detail,
                )
            )
            session.commit()

    def _record_failure(self, message_id: int, error_name: str) -> bool:
        with self.database.session() as session:
            state = self._load_state(session)
            state.consecutive_failures += 1
            disabled = state.consecutive_failures >= self.settings.auto_reply_max_failures
            if disabled:
                state.enabled = False
                state.enabled_until = None
                state.disabled_reason = "连续发送失败，已自动熔断"
            session.add(
                OperationLog(
                    message_id=message_id,
                    action="auto_reply_failed",
                    detail=f"自动发送失败：{error_name}",
                )
            )
            session.commit()
            return disabled
