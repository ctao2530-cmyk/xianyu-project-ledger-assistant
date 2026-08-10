from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from statistics import median
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, distinct, func, or_, select
from sqlalchemy.exc import IntegrityError

from ..adapters.base import (
    AdapterAccessVerificationError,
    AdapterDisconnectedError,
    AdapterError,
    ItemInfo,
    LoginExpiredError,
)
from ..config import Settings
from ..database import Database
from ..ledger import LedgerService
from ..models import (
    BusinessExpense,
    BusinessProject,
    Conversation,
    Item,
    Message,
    PaymentNode,
    ProductActionLog,
    ProductCollectionAttempt,
    ProductCollectionAttemptItem,
    ProductCollectionRun,
    ProductDailySnapshot,
    ProductLaunchPlan,
    ProductMarketKeywordPlan,
    ProductMarketReminderLog,
    ProductMarketSample,
    ProductMarketSampleResult,
    ProductModificationExperiment,
    ProductMonitor,
    ProductOperatingPlan,
    ProductOperatingPlanSlot,
    ProductStrategyRecommendation,
    ProductTrafficBatch,
    ProductTrafficBatchItem,
    ProductTrafficCheckpoint,
    ProductTrafficReminderLog,
    ProjectSettlementIssueRecord,
    utcnow,
)
from ..product_schemas import (
    DemandOpportunityView,
    ProductExposureAnalyticsView,
    ProductActionView,
    ProductCollectionAttemptItemView,
    ProductCollectionAttemptView,
    ProductCollectionRunView,
    ProductCollectionStatusView,
    ProductIntelligenceView,
    ProductLaunchPlanView,
    ProductLaunchRecommendationView,
    ProductMarketKeywordCandidateView,
    ProductMarketBenchmarkView,
    ProductMarketReferenceView,
    ProductMarketReminderView,
    ProductMarketSampleResultView,
    ProductMarketSampleView,
    ProductMarketStabilityView,
    ProductModificationExperimentView,
    ProductModificationSuggestionView,
    ProductOperatingPlanSlotView,
    ProductOperatingPlanView,
    ProductPlanProductView,
    ProductPortfolioSummary,
    ProductRecommendationView,
    ProductSnapshotView,
    ProductTrafficBatchItemView,
    ProductTrafficBatchView,
    ProductTrafficCheckpointMetricsView,
    ProductTrafficSummaryView,
    ProductTrafficTimeBucketView,
    ProductView,
    ProductWindowMetricsView,
    PublishTimingView,
    PublishWindowView,
)
from .event_hub import EventHub
from .notifier import MacOSNotifier


logger = logging.getLogger(__name__)


class ProductCollectionUnavailable(RuntimeError):
    pass


class ProductAlreadyCollected(RuntimeError):
    pass


class ProductReferenceInvalid(RuntimeError):
    pass


class ProductRecordNotFound(RuntimeError):
    pass


class ProductOwnershipRestricted(RuntimeError):
    pass


class ProductItemUnavailable(AdapterError):
    pass


class ProductTrafficConflict(RuntimeError):
    pass


class ProductMarketConflict(RuntimeError):
    pass


DEMAND_THEMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("网站与网页开发", ("网站", "网页", "官网", "前端", "wordpress", "h5")),
    ("小程序开发", ("小程序", "微信小程序", "抖音小程序")),
    ("修改、修复与二开", ("修改", "修复", "bug", "二开", "二次开发", "改一下")),
    ("数据库与接口", ("数据库", "mysql", "sql", "接口", "api", "后端")),
    ("自动化与脚本", ("自动化", "脚本", "爬虫", "机器人", "批量")),
    ("设计与原型", ("ui", "设计", "原型", "figma", "界面")),
    ("部署与上线", ("部署", "服务器", "域名", "上线", "发布")),
)

WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
TERMINATED_PROJECT_ISSUE_TYPES = ("project_cancelled", "cooperation_terminated")
RULES_VERSION = "v2.2"
CHECKPOINT_HOURS = {"h1": 1, "h6": 6, "h24": 24, "h72": 72}
CHECKPOINT_ORDER = tuple(CHECKPOINT_HOURS)
MODIFICATION_ACTIONS = {"title", "cover", "description", "price", "republish"}
MARKET_RULES_VERSION = "market-v2"
TECHNICAL_MARKET_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("网站与网页开发", "网站功能修改"),
    ("小程序开发", "小程序功能开发"),
    ("修改、修复与二开", "程序功能修改"),
    ("数据库与接口", "数据库接口开发"),
    ("自动化与脚本", "Python自动化脚本"),
    ("设计与原型", "UI页面设计实现"),
    ("部署与上线", "项目部署上线"),
)

# Only generic capability and delivery terms are extracted from public search
# titles. The service never copies a complete competing title into a suggestion.
MARKET_TITLE_TERMS: tuple[str, ...] = (
    "网站",
    "网页",
    "官网",
    "前端",
    "后端",
    "全栈",
    "小程序",
    "微信小程序",
    "uni-app",
    "vue",
    "react",
    "typescript",
    "javascript",
    "python",
    "java",
    "spring boot",
    "django",
    "flask",
    "mysql",
    "sql",
    "excel",
    "vba",
    "数据库",
    "接口",
    "api",
    "数据处理",
    "数据分析",
    "可视化",
    "自动化",
    "脚本",
    "爬虫",
    "机器人",
    "修复",
    "bug",
    "二开",
    "修改",
    "功能",
    "开发",
    "设计",
    "ui",
    "原型",
    "figma",
    "部署",
    "上线",
    "服务器",
    "域名",
    "响应式",
    "源码",
    "定制",
    "远程",
    "交付",
    "验收",
    "售后",
)


def _json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _as_count(value) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return max(0, int(value))
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0
    multiplier = 10_000 if "万" in text else 1
    match = re.search(r"\d+(?:\.\d+)?", text)
    return max(0, int(float(match.group()) * multiplier)) if match else 0


def _as_money(value) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return round(float(value), 2)
    text = str(value or "").strip().replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return round(float(match.group()), 2) if match else None


def _external_id(reference: str) -> str:
    value = reference.strip()
    if not value:
        raise ProductReferenceInvalid("请输入闲鱼商品 ID 或商品链接")
    parsed = urlparse(value if "://" in value else f"https://local.invalid/?itemId={value}")
    queries = parse_qs(parsed.query)
    candidate = (
        queries.get("itemId", [None])[0]
        or queries.get("item_id", [None])[0]
        or queries.get("id", [None])[0]
    )
    if candidate is None:
        match = re.search(r"(?:itemId|item_id|id)[=/]([A-Za-z0-9_-]{5,128})", value)
        candidate = match.group(1) if match else (value if "://" not in value else None)
    candidate = str(candidate or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,128}", candidate):
        raise ProductReferenceInvalid("没有识别到有效的闲鱼商品 ID")
    return candidate


def _seller_id(raw: dict) -> str:
    track_params = raw.get("trackParams")
    if isinstance(track_params, dict):
        value = str(track_params.get("sellerId") or "").strip()
        if value:
            return value
    for key in ("sellerDO", "seller", "user"):
        value = raw.get(key)
        if not isinstance(value, dict):
            continue
        seller = str(
            value.get("sellerId") or value.get("userId") or value.get("id") or ""
        ).strip()
        if seller:
            return seller
    return ""


class ProductIntelligenceService:
    """Daily, read-only product monitoring plus deterministic local advice."""

    def __init__(
        self,
        database: Database,
        adapter,
        settings: Settings,
        event_hub: EventHub,
        notifier: MacOSNotifier | None = None,
        ledger: LedgerService | None = None,
    ) -> None:
        self.database = database
        self.adapter = adapter
        self.settings = settings
        self.event_hub = event_hub
        self.notifier = notifier
        self.ledger = ledger
        self.timezone = ZoneInfo(settings.product_collection_timezone)
        self._task: asyncio.Task | None = None
        self._collection_lock = asyncio.Lock()

    @staticmethod
    def _active_project_count(session) -> int:
        return int(
            session.scalar(
                select(func.count(BusinessProject.id)).where(
                    BusinessProject.status.in_(("pending", "in_progress", "overdue")),
                    ~BusinessProject.id.in_(
                        select(ProjectSettlementIssueRecord.project_id).where(
                            ProjectSettlementIssueRecord.issue_type.in_(
                                TERMINATED_PROJECT_ISSUE_TYPES
                            )
                        )
                    ),
                )
            )
            or 0
        )

    def _now(self) -> datetime:
        return datetime.now(self.timezone)

    def _day_key(self, value: datetime | None = None) -> str:
        current = value or self._now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc).astimezone(self.timezone)
        else:
            current = current.astimezone(self.timezone)
        return current.date().isoformat()

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    def _local(self, value: datetime | None) -> datetime | None:
        normalized = self._utc(value)
        return normalized.astimezone(self.timezone) if normalized else None

    def _traffic_time_bucket(self, value: datetime | None) -> tuple[str, str]:
        local_value = self._local(value) or self._now()
        start_hour = (local_value.hour // 2) * 2
        end_hour = start_hour + 1
        return (
            f"{start_hour:02d}",
            f"{start_hour:02d}:00–{end_hour:02d}:59",
        )

    @staticmethod
    def _traffic_conversion(inquiries: int, browses: int) -> float | None:
        if browses <= 0:
            return None
        return round(inquiries / browses * 100, 2)

    @staticmethod
    def _traffic_unit_cost(cost: float, increment: int) -> float | None:
        if increment <= 0:
            return None
        return round(cost / increment, 2)

    def _week_bounds(self, value: datetime | None = None) -> tuple[datetime, datetime]:
        current = (value or self._now()).astimezone(self.timezone)
        start = datetime.combine(
            current.date() - timedelta(days=current.weekday()),
            time.min,
            tzinfo=self.timezone,
        )
        return start, start + timedelta(days=7)

    @staticmethod
    def _json_list(raw: str | None) -> list:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    async def start(self) -> None:
        self.bootstrap_cached_state()
        if self._task is None:
            self._task = asyncio.create_task(
                self._scheduler_loop(), name="daily-product-intelligence"
            )

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                await self._dispatch_due_traffic_reminders()
                await self._dispatch_due_market_reminder()
                if self._scheduled_collection_due():
                    await self.collect_today(trigger="scheduled")
            except ProductCollectionUnavailable:
                # Missing credentials are a visible configuration state, not a
                # failed remote run. Do not write a run or retry aggressively.
                pass
            except ProductAlreadyCollected:
                pass
            except Exception:
                logger.exception("每日商品经营数据采集失败")
            await asyncio.sleep(self.settings.product_collection_check_interval_seconds)

    async def _dispatch_due_traffic_reminders(self) -> None:
        """Send one local reminder per planned batch/checkpoint.

        This never calls Xianyu. One-hour and later observations remain manual.
        """

        now = utcnow()
        pending: list[tuple[str, str, datetime, str]] = []
        with self.database.session() as session:
            batches = session.scalars(
                select(ProductTrafficBatch)
                .where(ProductTrafficBatch.status.in_(("planned", "running", "observing")))
                .order_by(ProductTrafficBatch.planned_at)
                .limit(50)
            ).all()
            for batch in batches:
                reminder_specs: list[tuple[str, datetime, str]] = []
                planned_at = self._utc(batch.planned_at)
                started_at = self._utc(batch.started_at)
                if batch.status == "planned" and planned_at:
                    reminder_at = planned_at - timedelta(
                        minutes=self.settings.product_traffic_reminder_minutes
                    )
                    if reminder_at <= now <= planned_at + timedelta(hours=6):
                        reminder_specs.append(
                            (
                                "preflight",
                                reminder_at,
                                "曝光批次即将开始，请在闲鱼人工选择商品并确认费用",
                            )
                        )
                if started_at and batch.status in {"running", "observing"}:
                    completed = set(
                        session.scalars(
                            select(distinct(ProductTrafficCheckpoint.checkpoint)).where(
                                ProductTrafficCheckpoint.batch_id == batch.id
                            )
                        ).all()
                    )
                    for checkpoint, hours in CHECKPOINT_HOURS.items():
                        if checkpoint in completed:
                            continue
                        due_at = started_at + timedelta(hours=hours)
                        if due_at <= now <= due_at + timedelta(days=7):
                            reminder_specs.append(
                                (
                                    checkpoint,
                                    due_at,
                                    f"曝光批次到了 +{hours}h 检查点，请手工记录浏览与咨询变化",
                                )
                            )
                            break
                for reminder_type, scheduled_for, message in reminder_specs:
                    existing = session.scalar(
                        select(ProductTrafficReminderLog.id).where(
                            ProductTrafficReminderLog.batch_id == batch.id,
                            ProductTrafficReminderLog.reminder_type == reminder_type,
                        )
                    )
                    if existing:
                        continue
                    session.add(
                        ProductTrafficReminderLog(
                            id=f"traffic-reminder-{uuid4()}",
                            batch_id=batch.id,
                            reminder_type=reminder_type,
                            scheduled_for=scheduled_for,
                            sent_at=now,
                        )
                    )
                    pending.append((batch.id, reminder_type, scheduled_for, message))
            if pending:
                session.commit()

        for batch_id, reminder_type, _scheduled_for, message in pending:
            self.event_hub.publish_nowait(
                {
                    "type": "product_traffic_reminder",
                    "batch_id": batch_id,
                    "reminder_type": reminder_type,
                }
            )
            if self.notifier:
                await self.notifier.notify(
                    "闲鱼经营计划提醒",
                    message,
                    "只提醒，不会自动购买曝光",
                )

    def _market_scheduled_for(self, value: datetime | None = None) -> datetime:
        current = (value or self._now()).astimezone(self.timezone)
        return datetime.combine(
            current.date(),
            time(
                hour=self.settings.product_market_reminder_hour,
                minute=self.settings.product_market_reminder_minute,
            ),
            tzinfo=self.timezone,
        )

    async def _dispatch_due_market_reminder(self) -> None:
        """Notify once when today's user-assisted Edge sample is still missing."""

        now_local = self._now()
        scheduled_local = self._market_scheduled_for(now_local)
        if now_local < scheduled_local:
            return
        today = self._day_key(now_local)
        should_notify = False
        with self.database.session() as session:
            sample_exists = session.scalar(
                select(ProductMarketSample.id).where(
                    ProductMarketSample.sample_date == today
                )
            )
            reminder = session.scalar(
                select(ProductMarketReminderLog).where(
                    ProductMarketReminderLog.reminder_date == today
                )
            )
            if sample_exists:
                if reminder and reminder.status != "completed":
                    reminder.status = "completed"
                    reminder.snoozed_until = None
                    session.commit()
                return
            if reminder and reminder.status in {"sent", "skipped", "completed"}:
                return
            if reminder and reminder.status == "snoozed":
                snoozed_until = self._local(reminder.snoozed_until)
                if snoozed_until and now_local < snoozed_until:
                    return
                reminder.status = "sent"
                reminder.sent_at = now_local.astimezone(timezone.utc)
                reminder.snoozed_until = None
                should_notify = True
            elif reminder is None:
                session.add(
                    ProductMarketReminderLog(
                        id=f"market-reminder-{uuid4()}",
                        reminder_date=today,
                        status="sent",
                        scheduled_for=scheduled_local.astimezone(timezone.utc),
                        sent_at=now_local.astimezone(timezone.utc),
                    )
                )
                should_notify = True
            if should_notify:
                session.commit()

        if not should_notify:
            return
        self.event_hub.publish_nowait(
            {"type": "product_market_reminder_updated", "date": today, "status": "sent"}
        )
        if self.notifier:
            await self.notifier.notify(
                "闲鱼市场参考待更新",
                "今天还没有导入关键词搜索参考；可用现有 Edge 搜索后回到助手导入",
                "只提醒，不会自动打开网站或采集",
            )

    def _scheduled_collection_due(self) -> bool:
        if not self.settings.product_collection_enabled:
            return False
        if not self.settings.xianyu_configured:
            return False
        now = self._now()
        scheduled = datetime.combine(
            now.date(),
            time(
                hour=self.settings.product_collection_hour,
                minute=self.settings.product_collection_minute,
            ),
            tzinfo=self.timezone,
        )
        if now < scheduled:
            return False
        with self.database.session() as session:
            return session.scalar(
                select(ProductCollectionRun.id).where(
                    ProductCollectionRun.run_date == now.date().isoformat()
                )
            ) is None

    def _next_collection_at(self, has_run_today: bool) -> datetime:
        now = self._now()
        scheduled = datetime.combine(
            now.date(),
            time(
                hour=self.settings.product_collection_hour,
                minute=self.settings.product_collection_minute,
            ),
            tzinfo=self.timezone,
        )
        if has_run_today or now >= scheduled:
            scheduled += timedelta(days=1)
        return scheduled

    def _ownership(self, raw: dict, seller_id: str | None = None) -> tuple[str, str]:
        own_user_id = str(getattr(self.adapter, "own_user_id", "") or "").strip()
        item_seller_id = str(seller_id or _seller_id(raw) or "").strip()
        if not own_user_id:
            return "pending", "account_unavailable"
        if not item_seller_id:
            return "pending", "seller_unavailable"
        if item_seller_id == own_user_id:
            return "owned", "seller_match"
        return "excluded", "seller_mismatch"

    @staticmethod
    def _safe_collection_error(exc: Exception) -> tuple[str, str]:
        if isinstance(exc, AdapterAccessVerificationError):
            return (
                "access_verification",
                "闲鱼接口触发访问验证，本批次已停止后续请求；商品不一定下架。请在现有 Edge 中人工完成验证，再更新本机 .env 的 XIANYU_COOKIE 并重启服务；不要在聊天或日志中发送 Cookie。恢复后请先手动采集单件商品。",
            )
        if isinstance(exc, ProductItemUnavailable):
            return (
                "item_unavailable",
                "商品详情不可读取，可能已下架、失效或当前账号无权访问。",
            )
        if isinstance(exc, LoginExpiredError):
            return "auth_expired", "闲鱼登录已失效，请重新连接后等待下一次采集。"
        if isinstance(exc, AdapterDisconnectedError):
            return "connection_lost", "闲鱼连接已断开，请恢复连接后等待下一次采集。"
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return "request_timeout", "商品详情请求超时，本日不会自动重复采集。"
        if isinstance(exc, AdapterError):
            return "adapter_error", "闲鱼商品接口返回异常，本日不会自动重复采集。"
        return "unknown_error", "商品采集发生未知异常，请查看本机服务状态。"

    @staticmethod
    def _set_monitor_failure(monitor: ProductMonitor, exc: Exception) -> None:
        code, detail = ProductIntelligenceService._safe_collection_error(exc)
        monitor.last_attempt_at = utcnow()
        monitor.last_collection_status = "failed"
        monitor.last_error_code = code
        monitor.last_error_detail = detail

    @staticmethod
    def _set_monitor_skipped_after_access_verification(
        monitor: ProductMonitor,
    ) -> None:
        """Record that no remote request was made after the batch fuse opened."""

        monitor.last_collection_status = "skipped"
        monitor.last_error_code = "access_verification_batch_stopped"
        monitor.last_error_detail = (
            "本批次已有商品触发闲鱼访问验证。为保护账号，本商品未继续请求；"
            "请先在现有 Edge 中完成人工验证，恢复后从单件采集开始。"
        )

    def _backfill_legacy_collection_diagnostics(
        self,
        session,
        monitors: dict[int, ProductMonitor],
    ) -> None:
        """Recover safe item-level state from the last aggregate-only run.

        Older versions only stored a run total. A snapshot proves success. When
        the aggregate run covered the complete monitor roster, a missing
        snapshot safely identifies one of the failed item-detail reads without
        making a second remote request.
        """

        last_run = session.scalar(
            select(ProductCollectionRun)
            .where(ProductCollectionRun.status != "running")
            .order_by(ProductCollectionRun.run_date.desc())
            .limit(1)
        )
        if last_run is None:
            return
        complete_roster = last_run.monitored_count == len(monitors)
        attempted_at = last_run.finished_at or last_run.started_at
        for monitor in monitors.values():
            if monitor.last_attempt_at is not None or monitor.last_collection_status != "waiting":
                continue
            snapshot = session.scalar(
                select(ProductDailySnapshot).where(
                    ProductDailySnapshot.item_id == monitor.item_id,
                    ProductDailySnapshot.snapshot_date == last_run.run_date,
                    ProductDailySnapshot.source == "remote_daily",
                )
            )
            if snapshot is not None:
                monitor.last_attempt_at = snapshot.captured_at
                monitor.last_collection_status = "success"
                monitor.last_error_code = None
                monitor.last_error_detail = None
            elif complete_roster and last_run.failed_count > 0:
                monitor.last_attempt_at = attempted_at
                monitor.last_collection_status = "failed"
                monitor.last_error_code = "item_unavailable"
                monitor.last_error_detail = (
                    "商品详情不可读取，可能已下架、失效或当前账号无权访问。"
                )

    def bootstrap_cached_state(self) -> None:
        """Classify known conversation items without making a network request."""
        with self.database.session() as session:
            items = session.scalars(select(Item).order_by(Item.id)).all()
            monitors = {
                monitor.item_id: monitor
                for monitor in session.scalars(select(ProductMonitor)).all()
            }
            for item in items:
                raw = _json_dict(item.raw_json)
                ownership_status, ownership_source = self._ownership(raw)
                monitor = monitors.get(item.id)
                if monitor is None:
                    monitor = ProductMonitor(
                        item_id=item.id,
                        source="conversation",
                        enabled=ownership_status == "owned",
                        ownership_status=ownership_status,
                        ownership_source=f"cached_{ownership_source}",
                    )
                    session.add(monitor)
                    monitors[item.id] = monitor
                else:
                    previous_status = monitor.ownership_status
                    if ownership_status != "pending" or previous_status == "pending":
                        monitor.ownership_status = ownership_status
                        monitor.ownership_source = f"cached_{ownership_source}"
                    if monitor.ownership_status != "owned":
                        monitor.enabled = False
            session.flush()
            for item in items:
                monitor = monitors[item.id]
                exists = session.scalar(
                    select(ProductDailySnapshot.id)
                    .where(ProductDailySnapshot.item_id == item.id)
                    .limit(1)
                )
                raw = _json_dict(item.raw_json)
                if exists is None and raw and monitor.ownership_status == "owned":
                    snapshot_date = self._day_key(item.updated_at)
                    metrics = self._business_metrics(session, item.id)
                    session.add(
                        self._snapshot_from_raw(
                            item,
                            raw,
                            snapshot_date,
                            source="cached_baseline",
                            metrics=metrics,
                            collection_views_excluded=0,
                        )
                    )
            session.flush()
            self._backfill_legacy_collection_diagnostics(session, monitors)
            self._refresh_recommendations(session)
            session.commit()

    def _business_metrics(self, session, item_id: int) -> dict[str, float | int]:
        conversation_ids = list(
            session.scalars(
                select(Conversation.id).where(Conversation.item_id == item_id)
            ).all()
        )
        if not conversation_ids:
            return {
                "inquiry_count": 0,
                "inbound_message_count": 0,
                "converted_project_count": 0,
                "revenue_total": 0.0,
                "profit_total": 0.0,
            }
        inquiry_count = int(
            session.scalar(
                select(func.count(distinct(Message.conversation_id))).where(
                    Message.conversation_id.in_(conversation_ids),
                    Message.direction == "inbound",
                )
            )
            or 0
        )
        inbound_count = int(
            session.scalar(
                select(func.count(Message.id)).where(
                    Message.conversation_id.in_(conversation_ids),
                    Message.direction == "inbound",
                )
            )
            or 0
        )
        project_ids = list(
            session.scalars(
                select(BusinessProject.id).where(
                    BusinessProject.conversation_id.in_(conversation_ids)
                )
            ).all()
        )
        converted = len(set(project_ids))
        revenue = 0.0
        expenses = 0.0
        if project_ids:
            revenue = float(
                session.scalar(
                    select(func.coalesce(func.sum(PaymentNode.amount), 0)).where(
                        PaymentNode.project_id.in_(project_ids),
                        PaymentNode.status == "confirmed",
                    )
                )
                or 0
            )
            expenses = float(
                session.scalar(
                    select(func.coalesce(func.sum(BusinessExpense.amount), 0)).where(
                        BusinessExpense.project_id.in_(project_ids)
                    )
                )
                or 0
            )
        return {
            "inquiry_count": inquiry_count,
            "inbound_message_count": inbound_count,
            "converted_project_count": converted,
            "revenue_total": round(revenue, 2),
            "profit_total": round(revenue - expenses, 2),
        }

    def _snapshot_from_raw(
        self,
        item: Item,
        raw: dict,
        snapshot_date: str,
        *,
        source: str,
        metrics: dict[str, float | int],
        collection_views_excluded: int,
    ) -> ProductDailySnapshot:
        price = _as_money(
            raw.get("soldPrice")
            or raw.get("promotionPriceDO", {}).get("price")
            if isinstance(raw.get("promotionPriceDO"), dict)
            else raw.get("soldPrice")
        )
        if price is None:
            price = _as_money(raw.get("defaultPrice") or item.price)
        status_value = raw.get("itemStatusStr") or raw.get("itemStatus") or "unknown"
        raw_browse_count = _as_count(raw.get("browseCnt"))
        return ProductDailySnapshot(
            item_id=item.id,
            snapshot_date=snapshot_date,
            source=source,
            title=str(raw.get("title") or item.title or "未知商品"),
            price=price,
            status=str(status_value),
            published_at=str(raw.get("gmtCreate") or raw.get("GMT_CREATE_DATE_KEY") or ""),
            raw_browse_count=raw_browse_count,
            collection_views_excluded=collection_views_excluded,
            browse_count=max(0, raw_browse_count - collection_views_excluded),
            collect_count=_as_count(raw.get("collectCnt") or raw.get("favorCnt")),
            want_count=_as_count(raw.get("wantCnt") or raw.get("interactFavorCnt")),
            sold_count=_as_count(raw.get("soldCnt")),
            inquiry_count=int(metrics["inquiry_count"]),
            inbound_message_count=int(metrics["inbound_message_count"]),
            converted_project_count=int(metrics["converted_project_count"]),
            revenue_total=float(metrics["revenue_total"]),
            profit_total=float(metrics["profit_total"]),
        )

    def _upsert_snapshot(
        self,
        session,
        item: Item,
        raw: dict,
        snapshot_date: str,
        *,
        source: str,
    ) -> ProductDailySnapshot:
        metrics = self._business_metrics(session, item.id)
        existing = session.scalar(
            select(ProductDailySnapshot).where(
                ProductDailySnapshot.item_id == item.id,
                ProductDailySnapshot.snapshot_date == snapshot_date,
            )
        )
        if existing is not None:
            prior_exclusions = existing.collection_views_excluded
        else:
            prior_exclusions = int(
                session.scalar(
                    select(ProductDailySnapshot.collection_views_excluded)
                    .where(
                        ProductDailySnapshot.item_id == item.id,
                        ProductDailySnapshot.snapshot_date < snapshot_date,
                    )
                    .order_by(
                        ProductDailySnapshot.snapshot_date.desc(),
                        ProductDailySnapshot.id.desc(),
                    )
                    .limit(1)
                )
                or 0
            )
        exclusions = prior_exclusions + (
            1 if source in {"remote_daily", "remote_manual"} else 0
        )
        fresh = self._snapshot_from_raw(
            item,
            raw,
            snapshot_date,
            source=source,
            metrics=metrics,
            collection_views_excluded=exclusions,
        )
        if existing is None:
            session.add(fresh)
            session.flush()
            return fresh
        for field in (
            "source",
            "title",
            "price",
            "status",
            "published_at",
            "raw_browse_count",
            "collection_views_excluded",
            "browse_count",
            "collect_count",
            "want_count",
            "sold_count",
            "inquiry_count",
            "inbound_message_count",
            "converted_project_count",
            "revenue_total",
            "profit_total",
        ):
            setattr(existing, field, getattr(fresh, field))
        existing.captured_at = utcnow()
        session.flush()
        return existing

    async def _collect_monitor(
        self,
        *,
        monitor_id: int,
        item_id: int,
        external_id: str,
        snapshot_date: str,
        source: str,
        enable_owned: bool = False,
    ) -> str:
        """Read one listing and atomically refresh its safe local state."""

        info: ItemInfo | None = await self.adapter.fetch_item(external_id)
        if info is None:
            raise ProductItemUnavailable("商品详情为空")
        with self.database.session() as session:
            item = session.get(Item, item_id)
            monitor = session.get(ProductMonitor, monitor_id)
            if item is None:
                raise ProductRecordNotFound("商品记录不存在")
            if monitor is None:
                raise ProductRecordNotFound("商品监测记录不存在")
            item.title = info.title
            item.price = info.price
            item.description = info.description
            item.raw_json = json.dumps(info.raw, ensure_ascii=False)[:100_000]
            ownership_status, ownership_source = self._ownership(
                info.raw, info.seller_id
            )
            if (
                ownership_status == "pending"
                and monitor.ownership_status == "owned"
            ):
                ownership_status = "owned"
                ownership_source = monitor.ownership_source
            monitor.ownership_status = ownership_status
            monitor.ownership_source = f"remote_{ownership_source}"
            monitor.last_attempt_at = utcnow()
            monitor.last_error_code = None
            monitor.last_error_detail = None
            if ownership_status == "owned":
                if monitor.source == "manual" or enable_owned:
                    monitor.enabled = True
                monitor.last_collection_status = "success"
                self._upsert_snapshot(
                    session,
                    item,
                    info.raw,
                    snapshot_date,
                    source=source,
                )
            elif ownership_status == "excluded":
                monitor.enabled = False
                monitor.last_collection_status = "excluded"
            else:
                monitor.enabled = False
                monitor.last_collection_status = "pending"
            session.commit()
        return ownership_status

    def _start_collection_attempt(
        self,
        *,
        run_date: str,
        trigger: str,
        item_ids: list[int],
        requested_item_id: int | None = None,
        daily_run_id: str | None = None,
        started_at: datetime | None = None,
    ) -> str:
        attempt_id = f"product-attempt-{uuid4()}"
        with self.database.session() as session:
            session.add(
                ProductCollectionAttempt(
                    id=attempt_id,
                    run_date=run_date,
                    daily_run_id=daily_run_id,
                    trigger=trigger,
                    requested_item_id=requested_item_id,
                    status="running",
                    monitored_count=len(item_ids),
                    detail="只读采集进行中",
                    started_at=started_at or utcnow(),
                )
            )
            for item_id in item_ids:
                session.add(
                    ProductCollectionAttemptItem(
                        id=f"product-attempt-item-{uuid4()}",
                        attempt_id=attempt_id,
                        item_id=item_id,
                        status="pending",
                        detail="等待采集",
                    )
                )
            session.commit()
        return attempt_id

    def _mark_collection_attempt_item(
        self,
        attempt_id: str,
        item_id: int,
        *,
        status: str,
        detail: str,
        error_code: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        with self.database.session() as session:
            row = session.scalar(
                select(ProductCollectionAttemptItem).where(
                    ProductCollectionAttemptItem.attempt_id == attempt_id,
                    ProductCollectionAttemptItem.item_id == item_id,
                )
            )
            if row is None:
                return
            row.status = status
            row.error_code = error_code
            row.detail = detail[:500]
            row.finished_at = finished_at or utcnow()
            session.commit()

    def _mark_collection_attempt_skipped(
        self,
        attempt_id: str,
        item_ids: list[int],
        *,
        error_code: str,
        detail: str,
    ) -> None:
        if not item_ids:
            return
        finished_at = utcnow()
        with self.database.session() as session:
            rows = session.scalars(
                select(ProductCollectionAttemptItem).where(
                    ProductCollectionAttemptItem.attempt_id == attempt_id,
                    ProductCollectionAttemptItem.item_id.in_(item_ids),
                    ProductCollectionAttemptItem.status == "pending",
                )
            ).all()
            for row in rows:
                row.status = "skipped"
                row.error_code = error_code
                row.detail = detail[:500]
                row.finished_at = finished_at
            session.commit()

    def _finish_collection_attempt(
        self,
        attempt_id: str,
        *,
        detail: str,
        finished_at: datetime | None = None,
    ) -> None:
        with self.database.session() as session:
            attempt = session.get(ProductCollectionAttempt, attempt_id)
            if attempt is None:
                return
            statuses = list(
                session.scalars(
                    select(ProductCollectionAttemptItem.status).where(
                        ProductCollectionAttemptItem.attempt_id == attempt_id
                    )
                )
            )
            collected = sum(value == "success" for value in statuses)
            failed = sum(value == "failed" for value in statuses)
            skipped = sum(value == "skipped" for value in statuses)
            attempt.collected_count = collected
            attempt.failed_count = failed
            attempt.skipped_count = skipped
            attempt.status = (
                "partial"
                if collected and (failed or skipped)
                else "failed"
                if failed or skipped
                else "success"
            )
            attempt.detail = detail[:500]
            attempt.finished_at = finished_at or utcnow()
            session.commit()

    def _attempt_view(
        self,
        session,
        attempt: ProductCollectionAttempt,
    ) -> ProductCollectionAttemptView:
        rows = session.execute(
            select(ProductCollectionAttemptItem, Item)
            .join(Item, Item.id == ProductCollectionAttemptItem.item_id)
            .where(ProductCollectionAttemptItem.attempt_id == attempt.id)
            .order_by(ProductCollectionAttemptItem.item_id)
        ).all()
        requested = (
            session.get(Item, attempt.requested_item_id)
            if attempt.requested_item_id is not None
            else None
        )
        return ProductCollectionAttemptView(
            id=attempt.id,
            run_date=attempt.run_date,
            daily_run_id=attempt.daily_run_id,
            trigger=attempt.trigger,
            requested_external_id=requested.external_id if requested else None,
            requested_title=requested.title if requested else None,
            status=attempt.status,
            monitored_count=attempt.monitored_count,
            collected_count=attempt.collected_count,
            failed_count=attempt.failed_count,
            skipped_count=attempt.skipped_count,
            detail=attempt.detail,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            items=[
                ProductCollectionAttemptItemView(
                    external_id=item.external_id,
                    title=item.title,
                    status=row.status,
                    error_code=row.error_code,
                    detail=row.detail,
                    finished_at=row.finished_at,
                )
                for row, item in rows
            ],
        )

    async def collect_today(self, *, trigger: str) -> ProductCollectionRunView:
        async with self._collection_lock:
            if not self.settings.product_collection_enabled:
                raise ProductCollectionUnavailable("商品每日采集已关闭")
            if not self.settings.xianyu_configured:
                raise ProductCollectionUnavailable(
                    "请先在设置中心配置有效的闲鱼 Cookie，系统不会读取或展示 Cookie 内容"
                )
            run_date = self._day_key()
            self.bootstrap_cached_state()
            with self.database.session() as session:
                existing = session.scalar(
                    select(ProductCollectionRun).where(
                        ProductCollectionRun.run_date == run_date
                    )
                )
                if existing is not None:
                    raise ProductAlreadyCollected("今天已经执行过一次商品采集，明天再继续")
                monitors = session.scalars(
                    select(ProductMonitor)
                    .where(
                        or_(
                            and_(
                                ProductMonitor.ownership_status == "owned",
                                ProductMonitor.enabled.is_(True),
                            ),
                            and_(
                                ProductMonitor.ownership_status == "pending",
                                ProductMonitor.source == "manual",
                            ),
                        )
                    )
                    .order_by(ProductMonitor.id)
                    .limit(self.settings.product_collection_max_items)
                ).all()
                run = ProductCollectionRun(
                    id=f"product-run-{uuid4()}",
                    run_date=run_date,
                    trigger=trigger,
                    status="running",
                    monitored_count=len(monitors),
                    detail="每日一次只读采集进行中",
                )
                session.add(run)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    raise ProductAlreadyCollected(
                        "今天已经执行过一次商品采集，明天再继续"
                    ) from None
                monitor_item_ids = [(monitor.id, monitor.item_id) for monitor in monitors]

            attempt_id = self._start_collection_attempt(
                run_date=run_date,
                trigger=trigger,
                item_ids=[item_id for _, item_id in monitor_item_ids],
                daily_run_id=run.id,
                started_at=run.started_at,
            )

            collected = 0
            failed = 0
            skipped = 0
            failure_notes: list[str] = []
            for index, (monitor_id, item_id) in enumerate(monitor_item_ids):
                with self.database.session() as session:
                    item = session.get(Item, item_id)
                    external_id = item.external_id if item else ""
                if not external_id:
                    failed += 1
                    missing_error = ProductRecordNotFound("商品记录不存在")
                    with self.database.session() as session:
                        monitor = session.get(ProductMonitor, monitor_id)
                        if monitor:
                            self._set_monitor_failure(monitor, missing_error)
                            session.commit()
                    self._mark_collection_attempt_item(
                        attempt_id,
                        item_id,
                        status="failed",
                        error_code="record_missing",
                        detail="商品记录不存在，未发起平台请求",
                    )
                    continue
                try:
                    ownership_status = await self._collect_monitor(
                        monitor_id=monitor_id,
                        item_id=item_id,
                        external_id=external_id,
                        snapshot_date=run_date,
                        source="remote_daily",
                    )
                    collected += 1
                    self._mark_collection_attempt_item(
                        attempt_id,
                        item_id,
                        status="success",
                        detail=(
                            "只读采集成功"
                            if ownership_status == "owned"
                            else "只读校验完成，商品已移出本人商品统计"
                            if ownership_status == "excluded"
                            else "只读校验完成，商品归属仍待确认"
                        ),
                    )
                except LoginExpiredError as exc:
                    code, detail = self._safe_collection_error(exc)
                    with self.database.session() as session:
                        current = session.get(ProductMonitor, monitor_id)
                        if current:
                            self._set_monitor_failure(current, exc)
                        remaining_ids = [row[0] for row in monitor_item_ids[index + 1 :]]
                        if remaining_ids:
                            remaining = session.scalars(
                                select(ProductMonitor).where(
                                    ProductMonitor.id.in_(remaining_ids)
                                )
                            ).all()
                            for monitor in remaining:
                                monitor.last_collection_status = "skipped"
                                monitor.last_error_code = "auth_expired"
                                monitor.last_error_detail = (
                                    "因闲鱼登录失效，本日剩余商品未继续采集。"
                                )
                        session.commit()
                    failed += len(monitor_item_ids) - index
                    failure_notes.append("闲鱼登录已失效，已停止今日剩余采集")
                    self._mark_collection_attempt_item(
                        attempt_id,
                        item_id,
                        status="failed",
                        error_code=code,
                        detail=detail,
                    )
                    self._mark_collection_attempt_skipped(
                        attempt_id,
                        [row[1] for row in monitor_item_ids[index + 1 :]],
                        error_code="auth_expired_batch_stopped",
                        detail="因闲鱼登录失效，本次剩余商品未继续请求",
                    )
                    break
                except AdapterAccessVerificationError as exc:
                    remaining_ids = [row[0] for row in monitor_item_ids[index + 1 :]]
                    with self.database.session() as session:
                        current = session.get(ProductMonitor, monitor_id)
                        if current:
                            self._set_monitor_failure(current, exc)
                        if remaining_ids:
                            remaining = session.scalars(
                                select(ProductMonitor).where(
                                    ProductMonitor.id.in_(remaining_ids)
                                )
                            ).all()
                            for monitor in remaining:
                                self._set_monitor_skipped_after_access_verification(
                                    monitor
                                )
                        session.commit()
                    failed += 1
                    skipped += len(remaining_ids)
                    failure_notes.insert(
                        0,
                        "闲鱼触发访问验证，已立即停止本日剩余采集"
                    )
                    logger.warning(
                        "商品每日采集触发访问验证，已熔断剩余请求 item=%s skipped=%s",
                        external_id,
                        skipped,
                    )
                    code, detail = self._safe_collection_error(exc)
                    self._mark_collection_attempt_item(
                        attempt_id,
                        item_id,
                        status="failed",
                        error_code=code,
                        detail=detail,
                    )
                    self._mark_collection_attempt_skipped(
                        attempt_id,
                        [row[1] for row in monitor_item_ids[index + 1 :]],
                        error_code="access_verification_batch_stopped",
                        detail="为保护账号，本次剩余商品未继续请求",
                    )
                    break
                except Exception as exc:
                    failed += 1
                    code, detail = self._safe_collection_error(exc)
                    failure_notes.append(detail)
                    with self.database.session() as session:
                        monitor = session.get(ProductMonitor, monitor_id)
                        if monitor:
                            self._set_monitor_failure(monitor, exc)
                            session.commit()
                    self._mark_collection_attempt_item(
                        attempt_id,
                        item_id,
                        status="failed",
                        error_code=code,
                        detail=detail,
                    )
                    logger.warning(
                        "商品每日采集单项失败 item=%s error=%s code=%s",
                        external_id,
                        type(exc).__name__,
                        code,
                    )
                if (
                    index < len(monitor_item_ids) - 1
                    and self.settings.product_collection_request_delay_seconds > 0
                ):
                    await asyncio.sleep(
                        self.settings.product_collection_request_delay_seconds
                    )

            with self.database.session() as session:
                run = session.scalar(
                    select(ProductCollectionRun).where(
                        ProductCollectionRun.run_date == run_date
                    )
                )
                assert run is not None
                run.collected_count = collected
                run.failed_count = failed
                run.status = (
                    "success" if failed == 0 else "partial" if collected else "failed"
                )
                if not monitor_item_ids:
                    run.detail = "暂无启用监测的商品"
                elif skipped:
                    run.detail = (
                        f"已读取 {collected} 个商品，{failed} 个触发访问验证，"
                        f"{skipped} 个为保护账号而跳过；没有执行修改、发布或投流"
                    )
                else:
                    run.detail = (
                        f"已读取 {collected} 个商品，{failed} 个未取得当日数据；"
                        "没有执行修改、发布或投流"
                    )
                if failure_notes:
                    run.detail += f"（{failure_notes[0]}）"
                run.finished_at = utcnow()
                self._refresh_recommendations(session)
                session.commit()
                result = self._run_view(run)
            self._finish_collection_attempt(
                attempt_id,
                detail=result.detail,
                finished_at=result.finished_at,
            )
            self.event_hub.publish_nowait(
                {
                    "type": "product_intelligence_updated",
                    "run_date": run_date,
                    "status": result.status,
                }
            )
            return result

    async def collect_manual(
        self,
        external_id: str | None = None,
    ) -> ProductCollectionRunView:
        """Run an explicit read-only refresh without consuming the daily run.

        Manual refreshes update the same per-item Beijing-day snapshot, so
        repeated explicit reads never create duplicate trend points.
        """

        async with self._collection_lock:
            if not self.settings.product_collection_enabled:
                raise ProductCollectionUnavailable("商品采集已关闭")
            if not self.settings.xianyu_configured:
                raise ProductCollectionUnavailable(
                    "请先在设置中心配置有效的闲鱼 Cookie，系统不会读取或展示 Cookie 内容"
                )
            self.bootstrap_cached_state()
            run_date = self._day_key()
            started_at = utcnow()
            requested_external_id = _external_id(external_id) if external_id else None
            with self.database.session() as session:
                if requested_external_id:
                    item = session.scalar(
                        select(Item).where(Item.external_id == requested_external_id)
                    )
                    if item is None:
                        raise ProductRecordNotFound("商品不存在，请先添加到商品管理")
                    monitor = session.scalar(
                        select(ProductMonitor).where(ProductMonitor.item_id == item.id)
                    )
                    if monitor is None:
                        raise ProductRecordNotFound("商品尚未加入监测")
                    if monitor.ownership_status == "excluded":
                        raise ProductOwnershipRestricted(
                            "该商品已确认属于其他卖家，不能执行采集"
                        )
                    targets = [(monitor.id, monitor.item_id, item.external_id)]
                else:
                    monitors = session.scalars(
                        select(ProductMonitor)
                        .where(
                            ProductMonitor.ownership_status == "owned",
                            ProductMonitor.enabled.is_(True),
                        )
                        .order_by(ProductMonitor.id)
                        .limit(self.settings.product_collection_max_items)
                    ).all()
                    targets = [
                        (monitor.id, monitor.item_id, monitor.item.external_id)
                        for monitor in monitors
                    ]

            attempt_id = self._start_collection_attempt(
                run_date=run_date,
                trigger="manual_single" if requested_external_id else "manual_all",
                item_ids=[item_id for _, item_id, _ in targets],
                requested_item_id=targets[0][1] if requested_external_id and targets else None,
                started_at=started_at,
            )

            collected = 0
            failed = 0
            skipped = 0
            failure_notes: list[str] = []
            for index, (monitor_id, item_id, item_external_id) in enumerate(targets):
                try:
                    ownership_status = await self._collect_monitor(
                        monitor_id=monitor_id,
                        item_id=item_id,
                        external_id=item_external_id,
                        snapshot_date=run_date,
                        source="remote_manual",
                        enable_owned=bool(requested_external_id),
                    )
                    collected += 1
                    self._mark_collection_attempt_item(
                        attempt_id,
                        item_id,
                        status="success",
                        detail=(
                            "指定商品只读采集成功"
                            if requested_external_id and ownership_status == "owned"
                            else "只读采集成功"
                            if ownership_status == "owned"
                            else "只读校验完成，商品已移出本人商品统计"
                            if ownership_status == "excluded"
                            else "只读校验完成，商品归属仍待确认"
                        ),
                    )
                except LoginExpiredError as exc:
                    code, safe_detail = self._safe_collection_error(exc)
                    with self.database.session() as session:
                        monitor = session.get(ProductMonitor, monitor_id)
                        if monitor:
                            self._set_monitor_failure(monitor, exc)
                            session.commit()
                    failed += len(targets) - index
                    failure_notes.append("闲鱼登录已失效，已停止本次手动采集")
                    self._mark_collection_attempt_item(
                        attempt_id,
                        item_id,
                        status="failed",
                        error_code=code,
                        detail=safe_detail,
                    )
                    self._mark_collection_attempt_skipped(
                        attempt_id,
                        [row[1] for row in targets[index + 1 :]],
                        error_code="auth_expired_batch_stopped",
                        detail="因闲鱼登录失效，本次剩余商品未继续请求",
                    )
                    break
                except AdapterAccessVerificationError as exc:
                    remaining_ids = [row[0] for row in targets[index + 1 :]]
                    with self.database.session() as session:
                        monitor = session.get(ProductMonitor, monitor_id)
                        if monitor:
                            self._set_monitor_failure(monitor, exc)
                        if remaining_ids:
                            remaining = session.scalars(
                                select(ProductMonitor).where(
                                    ProductMonitor.id.in_(remaining_ids)
                                )
                            ).all()
                            for remaining_monitor in remaining:
                                self._set_monitor_skipped_after_access_verification(
                                    remaining_monitor
                                )
                        session.commit()
                    failed += 1
                    skipped += len(remaining_ids)
                    failure_notes.insert(
                        0,
                        "闲鱼触发访问验证，已立即停止本次剩余手动采集"
                    )
                    logger.warning(
                        "商品手动采集触发访问验证，已熔断剩余请求 item=%s skipped=%s",
                        item_external_id,
                        skipped,
                    )
                    code, safe_detail = self._safe_collection_error(exc)
                    self._mark_collection_attempt_item(
                        attempt_id,
                        item_id,
                        status="failed",
                        error_code=code,
                        detail=safe_detail,
                    )
                    self._mark_collection_attempt_skipped(
                        attempt_id,
                        [row[1] for row in targets[index + 1 :]],
                        error_code="access_verification_batch_stopped",
                        detail="为保护账号，本次剩余商品未继续请求",
                    )
                    break
                except Exception as exc:
                    failed += 1
                    code, detail = self._safe_collection_error(exc)
                    failure_notes.append(detail)
                    with self.database.session() as session:
                        monitor = session.get(ProductMonitor, monitor_id)
                        if monitor:
                            self._set_monitor_failure(monitor, exc)
                            session.commit()
                    self._mark_collection_attempt_item(
                        attempt_id,
                        item_id,
                        status="failed",
                        error_code=code,
                        detail=detail,
                    )
                    logger.warning(
                        "商品手动采集单项失败 item=%s error=%s code=%s",
                        item_external_id,
                        type(exc).__name__,
                        code,
                    )
                if (
                    index < len(targets) - 1
                    and self.settings.product_collection_request_delay_seconds > 0
                ):
                    await asyncio.sleep(
                        self.settings.product_collection_request_delay_seconds
                    )

            with self.database.session() as session:
                self._refresh_recommendations(session)
                session.commit()
            status = "success" if failed == 0 else "partial" if collected else "failed"
            if not targets:
                detail = "当前没有启用监测的本人商品"
            elif requested_external_id:
                detail = (
                    "指定商品手动采集完成，已更新今天的数据点"
                    if not failed
                    else "指定商品本次未取得数据"
                )
            else:
                if skipped:
                    detail = (
                        f"手动采集已停止：已读取 {collected} 个商品，"
                        f"{failed} 个触发访问验证，{skipped} 个为保护账号而跳过；"
                        "今天每个商品仍只保留一个趋势点"
                    )
                else:
                    detail = (
                        f"手动采集完成：已读取 {collected} 个商品，"
                        f"{failed} 个未取得数据；今天每个商品仍只保留一个趋势点"
                    )
            if failure_notes:
                detail += f"（{failure_notes[0]}）"
            finished_at = utcnow()
            self._finish_collection_attempt(
                attempt_id,
                detail=detail,
                finished_at=finished_at,
            )
            result = ProductCollectionRunView(
                id=attempt_id,
                run_date=run_date,
                trigger="manual_single" if requested_external_id else "manual_all",
                status=status,
                monitored_count=len(targets),
                collected_count=collected,
                failed_count=failed,
                detail=detail,
                started_at=started_at,
                finished_at=finished_at,
            )
            self.event_hub.publish_nowait(
                {
                    "type": "product_intelligence_updated",
                    "run_date": run_date,
                    "status": result.status,
                    "source": result.trigger,
                }
            )
            return result

    def register(self, reference: str) -> ProductView:
        external_id = _external_id(reference)
        with self.database.session() as session:
            item = session.scalar(
                select(Item).where(Item.external_id == external_id)
            )
            if item is None:
                item = Item(
                    external_id=external_id,
                    title=f"待首次采集商品 · {external_id[-6:]}",
                    raw_json=None,
                )
                session.add(item)
                session.flush()
            monitor = session.scalar(
                select(ProductMonitor).where(ProductMonitor.item_id == item.id)
            )
            if monitor is None:
                monitor = ProductMonitor(
                    item_id=item.id,
                    source="manual",
                    enabled=False,
                    ownership_status="pending",
                    ownership_source="manual_pending",
                )
                session.add(monitor)
            else:
                monitor.source = "manual"
                if monitor.ownership_status == "owned":
                    monitor.enabled = True
            session.commit()
        self.event_hub.publish_nowait(
            {"type": "product_monitor_updated", "item_id": external_id}
        )
        return self.product(external_id)

    def update_monitor(self, external_id: str, enabled: bool) -> ProductView:
        with self.database.session() as session:
            item = session.scalar(select(Item).where(Item.external_id == external_id))
            if item is None:
                raise ProductRecordNotFound("商品不存在")
            monitor = session.scalar(
                select(ProductMonitor).where(ProductMonitor.item_id == item.id)
            )
            if monitor is None:
                monitor = ProductMonitor(
                    item_id=item.id,
                    source="manual",
                    enabled=False,
                    ownership_status="pending",
                    ownership_source="manual_pending",
                )
                session.add(monitor)
            else:
                if enabled and monitor.ownership_status != "owned":
                    label = (
                        "该商品卖家与当前闲鱼账号不一致，不能恢复监测"
                        if monitor.ownership_status == "excluded"
                        else "该商品尚未完成卖家验证，请等待下一次每日采集"
                    )
                    raise ProductOwnershipRestricted(label)
                monitor.enabled = enabled
            session.commit()
        self.event_hub.publish_nowait(
            {"type": "product_monitor_updated", "item_id": external_id}
        )
        return self.product(external_id)

    def create_action(
        self,
        external_id: str,
        *,
        action_type: str,
        status: str,
        note: str,
        cost: float,
        recommendation_id: str | None,
        observation_days: int,
    ) -> ProductActionView:
        with self.database.session() as session:
            item = session.scalar(select(Item).where(Item.external_id == external_id))
            if item is None:
                raise ProductRecordNotFound("商品不存在")
            recommendation = None
            if recommendation_id:
                recommendation = session.get(
                    ProductStrategyRecommendation, recommendation_id
                )
                if recommendation is None or recommendation.item_id != item.id:
                    raise ProductRecordNotFound("经营建议不存在")
            happened_at = utcnow()
            action = ProductActionLog(
                id=f"product-action-{uuid4()}",
                item_id=item.id,
                recommendation_id=recommendation.id if recommendation else None,
                action_type=action_type,
                status=status,
                note=note.strip(),
                cost=round(cost, 2),
                happened_at=happened_at,
                observation_until=(
                    happened_at + timedelta(days=observation_days)
                    if status != "cancelled"
                    else None
                ),
            )
            session.add(action)
            if recommendation:
                recommendation.status = (
                    "completed" if action_type == "hold" else "in_progress"
                )
            session.commit()
            result = self._action_view(action)
        self.event_hub.publish_nowait(
            {
                "type": "product_action_recorded",
                "item_id": external_id,
                "action_type": action_type,
            }
        )
        return result

    def update_recommendation(self, recommendation_id: str, status: str) -> None:
        with self.database.session() as session:
            recommendation = session.get(
                ProductStrategyRecommendation, recommendation_id
            )
            if recommendation is None:
                raise ProductRecordNotFound("经营建议不存在")
            recommendation.status = status
            session.commit()
        self.event_hub.publish_nowait(
            {
                "type": "product_recommendation_updated",
                "recommendation_id": recommendation_id,
                "status": status,
            }
        )

    def _window_metrics(
        self,
        history_desc: list[ProductDailySnapshot],
        days: int,
    ) -> ProductWindowMetricsView:
        if not history_desc:
            return ProductWindowMetricsView(
                days=days,
                observation_days=0,
                snapshot_count=0,
                browse_delta=None,
                inquiry_delta=None,
                want_delta=None,
                daily_browse=None,
            )
        current = history_desc[0]
        try:
            current_day = datetime.fromisoformat(current.snapshot_date).date()
        except ValueError:
            current_day = self._now().date()
        candidates: list[tuple[int, ProductDailySnapshot]] = []
        for snapshot in history_desc:
            try:
                snapshot_day = datetime.fromisoformat(snapshot.snapshot_date).date()
            except ValueError:
                continue
            difference = max(0, (current_day - snapshot_day).days)
            if difference <= days:
                candidates.append((difference, snapshot))
        if len(candidates) < 2:
            return ProductWindowMetricsView(
                days=days,
                observation_days=0,
                snapshot_count=len(candidates),
                browse_delta=None,
                inquiry_delta=None,
                want_delta=None,
                daily_browse=None,
            )
        observation_days, oldest = max(candidates, key=lambda row: row[0])
        observation_days = max(1, observation_days)
        browse_delta = max(0, current.browse_count - oldest.browse_count)
        return ProductWindowMetricsView(
            days=days,
            observation_days=observation_days,
            snapshot_count=len(candidates),
            browse_delta=browse_delta,
            inquiry_delta=max(0, current.inquiry_count - oldest.inquiry_count),
            want_delta=max(0, current.want_count - oldest.want_count),
            daily_browse=round(browse_delta / observation_days, 1),
        )

    def _product_signal_state(
        self,
        session,
        monitor: ProductMonitor,
        history_desc: list[ProductDailySnapshot],
    ) -> dict:
        current = history_desc[0] if history_desc else None
        freshness_days: int | None = None
        if current:
            try:
                freshness_days = max(
                    0,
                    (self._now().date() - datetime.fromisoformat(current.snapshot_date).date()).days,
                )
            except ValueError:
                freshness_days = None
        gaps: list[str] = []
        if not history_desc:
            gaps.append("尚无经营快照")
        elif len(history_desc) < 3:
            gaps.append("少于 3 个快照日")
        if freshness_days is None or freshness_days > 2:
            gaps.append("最近数据不够新鲜")
        if monitor.last_collection_status == "failed":
            gaps.append("最近一次采集失败")

        quality = "low"
        if len(history_desc) >= 7 and freshness_days is not None and freshness_days <= 1:
            quality = "high"
        elif len(history_desc) >= 3 and freshness_days is not None and freshness_days <= 2:
            quality = "medium"

        batch_rows = session.execute(
            select(ProductTrafficBatch.planned_at, ProductTrafficBatch.started_at)
            .join(
                ProductTrafficBatchItem,
                ProductTrafficBatchItem.batch_id == ProductTrafficBatch.id,
            )
            .where(
                ProductTrafficBatchItem.item_id == monitor.item_id,
                ProductTrafficBatch.status.not_in(("cancelled", "skipped")),
            )
        ).all()
        batch_started = max(
            (
                self._utc(started_at or planned_at)
                for planned_at, started_at in batch_rows
                if started_at or planned_at
            ),
            default=None,
        )
        cooldown_until = (
            batch_started + timedelta(hours=self.settings.product_traffic_cooldown_hours)
            if batch_started
            else None
        )
        modification_until = session.scalar(
            select(func.max(ProductActionLog.observation_until)).where(
                ProductActionLog.item_id == monitor.item_id,
                ProductActionLog.action_type.in_(MODIFICATION_ACTIONS),
                ProductActionLog.status == "completed",
            )
        )
        modification_until = self._utc(modification_until)
        return {
            "snapshot_count": len(history_desc),
            "freshness_days": freshness_days,
            "data_quality": quality,
            "data_gaps": gaps,
            "traffic_cooldown_until": cooldown_until,
            "modification_observation_until": modification_until,
            "recent_windows": [
                self._window_metrics(history_desc, window) for window in (1, 7, 28)
            ],
        }

    @staticmethod
    def _analysis_stage(effective_batch_count: int) -> str:
        if effective_batch_count >= 30:
            return "explore_exploit"
        if effective_batch_count >= 6:
            return "controlled_learning"
        return "baseline_learning"

    def _effective_batch_count(self, session) -> int:
        batch_ids = session.scalars(
            select(distinct(ProductTrafficCheckpoint.batch_id)).where(
                ProductTrafficCheckpoint.checkpoint.in_(("h24", "h72"))
            )
        ).all()
        return sum(
            1
            for batch_id in batch_ids
            if (
                batch := session.get(ProductTrafficBatch, batch_id)
            ) is not None
            and self._traffic_batch_view(session, batch).analysis_eligible
        )

    def _week_traffic_totals(
        self,
        session,
        value: datetime | None = None,
    ) -> tuple[float, float]:
        start, end = self._week_bounds(value)
        batches = session.scalars(
            select(ProductTrafficBatch).where(
                ProductTrafficBatch.planned_at >= start.astimezone(timezone.utc),
                ProductTrafficBatch.planned_at < end.astimezone(timezone.utc),
                ProductTrafficBatch.status != "cancelled",
            )
        ).all()
        spent = round(
            sum(
                batch.actual_cost
                for batch in batches
                if batch.status in {"running", "observing", "closed"}
            ),
            2,
        )
        planned = round(
            sum(batch.actual_cost for batch in batches if batch.status == "planned"),
            2,
        )
        return spent, planned

    def _traffic_effect_for_item(self, session, item_id: int) -> dict:
        history = session.scalars(
            select(ProductDailySnapshot)
            .where(ProductDailySnapshot.item_id == item_id)
            .order_by(ProductDailySnapshot.snapshot_date.desc())
            .limit(30)
        ).all()
        natural_window = self._window_metrics(list(history), 28)
        natural_daily_browse = natural_window.daily_browse or 0
        rows = session.execute(
            select(ProductTrafficBatchItem, ProductTrafficCheckpoint)
            .join(
                ProductTrafficCheckpoint,
                and_(
                    ProductTrafficCheckpoint.batch_id == ProductTrafficBatchItem.batch_id,
                    ProductTrafficCheckpoint.item_id == ProductTrafficBatchItem.item_id,
                ),
            )
            .where(
                ProductTrafficBatchItem.item_id == item_id,
                ProductTrafficCheckpoint.checkpoint.in_(("h24", "h72")),
            )
            .order_by(ProductTrafficCheckpoint.recorded_at.desc())
        ).all()
        by_batch: dict[str, tuple[ProductTrafficBatchItem, ProductTrafficCheckpoint]] = {}
        for batch_item, checkpoint in rows:
            by_batch.setdefault(batch_item.batch_id, (batch_item, checkpoint))
        browse_lifts = []
        incremental_browse_lifts = []
        for batch_item, checkpoint in by_batch.values():
            browse_lift = max(
                0, checkpoint.browse_count - batch_item.baseline_browse_count
            )
            browse_lifts.append(browse_lift)
            hours = CHECKPOINT_HOURS.get(checkpoint.checkpoint, 24)
            natural_expected = natural_daily_browse * hours / 24
            incremental_browse_lifts.append(max(0, browse_lift - natural_expected))
        inquiry_lifts = [
            max(0, checkpoint.inquiry_count - batch_item.baseline_inquiry_count)
            for batch_item, checkpoint in by_batch.values()
        ]
        count = len(by_batch)
        current = history[0] if history else None
        project_probability = (
            (current.converted_project_count + 1) / (current.inquiry_count + 2)
            if current
            else 0.5
        )
        profit_per_project = (
            current.profit_total / current.converted_project_count
            if current and current.converted_project_count > 0 and current.profit_total > 0
            else 0
        )
        expected_inquiries = (sum(inquiry_lifts) + 1) / (count + 2)
        return {
            "batch_count": count,
            "average_browse_lift": round(sum(browse_lifts) / count, 1) if count else 0,
            "average_incremental_browse": (
                round(sum(incremental_browse_lifts) / count, 1) if count else 0
            ),
            "average_inquiry_lift": round(sum(inquiry_lifts) / count, 2) if count else 0,
            # Beta(1, 1) smoothing prevents one early success from dominating.
            "smoothed_inquiry_probability": round(
                (sum(1 for value in inquiry_lifts if value > 0) + 1) / (count + 2),
                3,
            ),
            "expected_contribution": round(
                expected_inquiries * project_probability * profit_per_project,
                2,
            ),
        }

    def _candidate_pool(self, session) -> list[dict]:
        monitors = session.scalars(
            select(ProductMonitor)
            .where(
                ProductMonitor.enabled.is_(True),
                ProductMonitor.ownership_status == "owned",
            )
            .order_by(ProductMonitor.id)
        ).all()
        candidates: list[dict] = []
        for monitor in monitors:
            history = session.scalars(
                select(ProductDailySnapshot)
                .where(ProductDailySnapshot.item_id == monitor.item_id)
                .order_by(ProductDailySnapshot.snapshot_date.desc())
                .limit(30)
            ).all()
            signal = self._product_signal_state(session, monitor, list(history))
            current = history[0] if history else None
            browse = current.browse_count if current else 0
            inquiries = current.inquiry_count if current else 0
            converted = current.converted_project_count if current else 0
            profit = current.profit_total if current else 0
            inquiry_rate = inquiries / browse * 100 if browse else None
            effect = self._traffic_effect_for_item(session, monitor.item_id)

            role = "探索位"
            reason = "样本不足，用小批次积累真实基线"
            score = 20
            eligible = True
            if converted > 0 and profit > 0:
                role = "已验证"
                reason = "已有真实项目与正利润"
                score = 80 + min(15, converted * 5)
            elif inquiries > 0:
                role = "潜力位"
                reason = "已有真实咨询，继续验证转化"
                score = 58 + min(15, inquiries * 3)
            if browse >= 80 and (inquiry_rate or 0) < 1:
                role = "先优化"
                reason = "浏览较高但咨询率偏低，不宜继续放大无效流量"
                score = 12
                eligible = False
            if signal["data_quality"] == "medium":
                score += 5
            elif signal["data_quality"] == "high":
                score += 10
            if effect["batch_count"]:
                score += min(
                    20,
                    int(effect["average_inquiry_lift"] * 8)
                    + int(effect["smoothed_inquiry_probability"] * 8),
                )
                reason += f"；历史批次平均新增咨询 {effect['average_inquiry_lift']:.1f}"
            if "最近一次采集失败" in signal["data_gaps"] or "最近数据不够新鲜" in signal["data_gaps"]:
                eligible = False
                role = "数据待恢复"
                reason = "最近数据不可靠，先恢复采集"
                score = 4
            candidates.append(
                {
                    "monitor": monitor,
                    "item": monitor.item,
                    "signal": signal,
                    "current": current,
                    "role": role,
                    "reason": reason,
                    "score": max(0, min(100, score)),
                    "eligible": eligible,
                    "effect": effect,
                }
            )
        return candidates

    def _plan_input_signature(self, session, candidates: list[dict]) -> str:
        payload = {
            "date": self._day_key(),
            "rules_version": RULES_VERSION,
            "active_projects": self._active_project_count(session),
            "capacity": self.settings.product_delivery_capacity,
            "weekly_budget": self.settings.product_traffic_weekly_budget,
            "products": [
                {
                    "id": candidate["item"].external_id,
                    "enabled": candidate["monitor"].enabled,
                    "collection": candidate["monitor"].last_collection_status,
                    "quality": candidate["signal"]["data_quality"],
                    "cooldown": str(candidate["signal"]["traffic_cooldown_until"] or ""),
                    "observation": str(
                        candidate["signal"]["modification_observation_until"] or ""
                    ),
                    "snapshot": (
                        [
                            candidate["current"].snapshot_date,
                            candidate["current"].browse_count,
                            candidate["current"].inquiry_count,
                            candidate["current"].converted_project_count,
                            candidate["current"].profit_total,
                        ]
                        if candidate["current"]
                        else None
                    ),
                    "effects": candidate["effect"],
                }
                for candidate in candidates
            ],
            "batches": [
                [
                    batch.id,
                    batch.status,
                    str(batch.planned_at),
                    str(batch.started_at or ""),
                    batch.actual_cost,
                    batch.total_exposure,
                ]
                for batch in session.scalars(
                    select(ProductTrafficBatch)
                    .order_by(ProductTrafficBatch.created_at.desc())
                    .limit(50)
                ).all()
            ],
            "checkpoints": [
                [
                    checkpoint.batch_id,
                    checkpoint.item_id,
                    checkpoint.checkpoint,
                    checkpoint.browse_count,
                    checkpoint.collect_count,
                    checkpoint.want_count,
                    checkpoint.inquiry_count,
                    str(checkpoint.recorded_at),
                ]
                for checkpoint in session.scalars(
                    select(ProductTrafficCheckpoint)
                    .order_by(ProductTrafficCheckpoint.recorded_at.desc())
                    .limit(200)
                ).all()
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _ensure_operating_plan(
        self,
        session,
        *,
        force: bool = False,
    ) -> ProductOperatingPlan:
        candidates = self._candidate_pool(session)
        signature = self._plan_input_signature(session, candidates)
        today = self._now().date()
        today_key = today.isoformat()
        latest = session.scalar(
            select(ProductOperatingPlan)
            .where(ProductOperatingPlan.status == "current")
            .order_by(ProductOperatingPlan.generated_at.desc())
            .limit(1)
        )
        if (
            latest
            and latest.plan_start_date == today_key
            and latest.input_signature == signature
            and not force
        ):
            return latest

        previous_slots: dict[str, ProductOperatingPlanSlot] = {}
        if latest:
            previous_slots = {
                slot.slot_date: slot
                for slot in session.scalars(
                    select(ProductOperatingPlanSlot).where(
                        ProductOperatingPlanSlot.plan_id == latest.id
                    )
                ).all()
            }
        version = (
            int(
                session.scalar(
                    select(func.max(ProductOperatingPlan.version)).where(
                        ProductOperatingPlan.plan_start_date == today_key
                    )
                )
                or 0
            )
            + 1
        )
        if latest:
            latest.status = "superseded"

        effective_batch_count = self._effective_batch_count(session)
        analysis_stage = self._analysis_stage(effective_batch_count)
        quality_counts = defaultdict(int)
        for candidate in candidates:
            quality_counts[candidate["signal"]["data_quality"]] += 1
        portfolio_quality = "low"
        if quality_counts["high"] >= max(2, len(candidates) // 2) and effective_batch_count >= 10:
            portfolio_quality = "high"
        elif quality_counts["medium"] + quality_counts["high"] >= max(2, len(candidates) // 3) or effective_batch_count >= 6:
            portfolio_quality = "medium"

        timing = self._publish_timing(session)
        exposure_timing = self._exposure_analytics(session)
        scheduled_time = "20:00"
        timing_source = "默认晚间经营窗口"
        if exposure_timing.best_time_bucket:
            scheduled_time = exposure_timing.best_time_bucket.split("–", 1)[0]
            timing_source = (
                f"近 {exposure_timing.window_days} 天成熟曝光批次的优先窗口"
            )
        elif timing.windows:
            scheduled_time = timing.windows[0].time_range.split("–", 1)[0]
            timing_source = "近 90 天首次咨询高峰"
        scheduled_hour, scheduled_minute = [int(value) for value in scheduled_time.split(":")]
        today_scheduled = datetime.combine(
            today,
            time(scheduled_hour, scheduled_minute),
            tzinfo=self.timezone,
        )
        first_traffic_offset = 0 if self._now() < today_scheduled else 1
        traffic_offsets = set(range(first_traffic_offset, 7, 2))
        active_projects = self._active_project_count(session)
        capacity_guard = active_projects >= self.settings.product_delivery_capacity
        batch_cost = round(self.settings.product_traffic_batch_cost, 2)
        usage: defaultdict[str, int] = defaultdict(int)
        future_cooldowns: dict[str, datetime] = {}
        planned_by_week: defaultdict[str, float] = defaultdict(float)
        changed_slots = 0
        new_slots: list[dict] = []
        eligible_external_ids = {
            candidate["item"].external_id
            for candidate in candidates
            if candidate["eligible"]
        }

        for offset in range(7):
            slot_day = today + timedelta(days=offset)
            slot_key = slot_day.isoformat()
            slot_local = datetime.combine(
                slot_day,
                time(scheduled_hour, scheduled_minute),
                tzinfo=self.timezone,
            )
            previous = previous_slots.get(slot_key)
            keep_previous = bool(
                previous
                and not capacity_guard
                and (previous.locked or offset <= 1)
                and set(self._json_list(previous.item_ids_json)).issubset(
                    eligible_external_ids
                )
            )
            if keep_previous:
                item_ids = [str(value) for value in self._json_list(previous.item_ids_json)]
                for external_id in item_ids:
                    usage[external_id] += 1
                    if previous.action_type == "traffic":
                        future_cooldowns[external_id] = slot_local + timedelta(
                            hours=self.settings.product_traffic_cooldown_hours
                        )
                new_slots.append(
                    {
                        "date": slot_key,
                        "scheduled_time": previous.scheduled_time,
                        "action_type": previous.action_type,
                        "item_ids": item_ids,
                        "planned_cost": previous.planned_cost,
                        "reason": previous.reason,
                        "change_reason": "近 24 小时计划已锁定，保持不变",
                        "evidence": [
                            f"规则版本 {RULES_VERSION}",
                            *[
                                str(value)
                                for value in self._json_list(previous.evidence_json)
                                if not str(value).startswith("规则版本")
                                and not str(value).startswith("投放时段依据")
                            ],
                            "投放时段依据：近 24 小时计划锁定，沿用上一版时段",
                        ],
                        "warnings": self._json_list(previous.warnings_json),
                        "confidence": previous.confidence,
                        "locked": True,
                        "status": previous.status,
                    }
                )
                continue

            action_type = "observe"
            selected: list[dict] = []
            planned_cost = 0.0
            warnings: list[str] = []
            evidence = [
                f"规则版本 {RULES_VERSION}",
                f"交付负载 {active_projects}/{self.settings.product_delivery_capacity}",
                f"有效曝光批次 {effective_batch_count} 个",
                f"投放时段依据：{timing_source}",
            ]
            reason = "观察自然流量，不在没有证据时频繁调整"

            if capacity_guard:
                action_type = "delivery_guard"
                reason = "交付容量已满，本地规则暂停全部商品的新增曝光建议"
                warnings.append("容量保护优先于商品分数")
            elif offset in traffic_offsets:
                week_start = slot_day - timedelta(days=slot_day.weekday())
                week_key = week_start.isoformat()
                spent, already_planned = self._week_traffic_totals(session, slot_local)
                available_budget = (
                    self.settings.product_traffic_weekly_budget
                    - spent
                    - already_planned
                    - planned_by_week[week_key]
                )
                available = []
                for candidate in candidates:
                    if not candidate["eligible"]:
                        continue
                    external_id = candidate["item"].external_id
                    cooldown = candidate["signal"]["traffic_cooldown_until"]
                    observation = candidate["signal"]["modification_observation_until"]
                    if cooldown and cooldown > slot_local.astimezone(timezone.utc):
                        continue
                    if observation and observation > slot_local.astimezone(timezone.utc):
                        continue
                    if future_cooldowns.get(external_id, datetime.min.replace(tzinfo=timezone.utc)) > slot_local.astimezone(timezone.utc):
                        continue
                    available.append(candidate)
                available.sort(
                    key=lambda candidate: (
                        usage[candidate["item"].external_id],
                        -candidate["score"],
                        candidate["item"].external_id,
                    )
                )
                if analysis_stage == "explore_exploit" and len(available) >= 3:
                    exploit_count = max(
                        2, self.settings.product_traffic_batch_max_items - 1
                    )
                    exploit = sorted(
                        available,
                        key=lambda candidate: (
                            -candidate["score"],
                            usage[candidate["item"].external_id],
                        ),
                    )[:exploit_count]
                    exploration = next(
                        (
                            candidate
                            for candidate in sorted(
                                available,
                                key=lambda value: (
                                    value["effect"]["batch_count"],
                                    usage[value["item"].external_id],
                                ),
                            )
                            if candidate not in exploit
                        ),
                        None,
                    )
                    selected = exploit + ([exploration] if exploration else [])
                else:
                    selected = available[: self.settings.product_traffic_batch_max_items]
                minimum = min(
                    self.settings.product_traffic_batch_min_items,
                    len(eligible_external_ids),
                )
                if available_budget + 1e-9 < batch_cost:
                    action_type = "rest"
                    selected = []
                    reason = "本周计划预算已用完，保留自然流量观察日"
                    warnings.append(
                        f"周上限 ¥{self.settings.product_traffic_weekly_budget:.0f}，不会建议超额批次"
                    )
                elif len(selected) < max(1, minimum):
                    action_type = "measure"
                    selected = []
                    reason = "可用商品不足，优先等待 72 小时冷却或数据恢复"
                    warnings.append("同一商品不会为了凑批次而重复投放")
                else:
                    action_type = "traffic"
                    planned_cost = batch_cost
                    planned_by_week[week_key] += batch_cost
                    reason = (
                        f"建议人工选择 {len(selected)} 件商品组成一个批次；"
                        f"批次总费用按约 ¥{batch_cost:g} 记录"
                    )
                    warnings.extend(
                        [
                            "套餐总曝光不平均分摊到单件商品",
                            "1 小时完成曝光后仍继续观察 +24h 与 +72h 浏览、咨询",
                        ]
                    )
                    if analysis_stage != "baseline_learning":
                        expected_value = round(
                            sum(
                                candidate["effect"]["expected_contribution"]
                                for candidate in selected
                            )
                            - batch_cost,
                            2,
                        )
                        evidence.append(
                            "按历史咨询、项目概率与贡献利润平滑估算，"
                            f"本批期望贡献净值约 {expected_value:,.2f} 元"
                        )
                        observed_count = sum(
                            candidate["effect"]["batch_count"] for candidate in selected
                        )
                        if expected_value < 0 and observed_count >= len(selected) * 2:
                            action_type = "measure"
                            planned_cost = 0
                            planned_by_week[week_key] -= batch_cost
                            reason = "历史平滑估算仍为负，暂停新增曝光并复盘商品组合"
                            warnings.append("不会为了维持投放频率而忽略负向结果")
                    if action_type == "traffic":
                        for candidate in selected:
                            external_id = candidate["item"].external_id
                            usage[external_id] += 1
                            future_cooldowns[external_id] = slot_local.astimezone(
                                timezone.utc
                            ) + timedelta(hours=self.settings.product_traffic_cooldown_hours)
            else:
                active_observations = [
                    candidate
                    for candidate in candidates
                    if (
                        candidate["signal"]["traffic_cooldown_until"]
                        and candidate["signal"]["traffic_cooldown_until"]
                        > slot_local.astimezone(timezone.utc)
                    )
                ]
                optimization = [
                    candidate for candidate in candidates if candidate["role"] == "先优化"
                ]
                if active_observations:
                    action_type = "measure"
                    selected = active_observations[:3]
                    reason = "曝光后的长尾观察日，补齐检查点，不安排重叠批次"
                elif optimization:
                    action_type = "optimize"
                    selected = optimization[:2]
                    reason = "先优化高浏览低咨询商品的表达，再考虑曝光"

            item_ids = [candidate["item"].external_id for candidate in selected]
            change_reason = "首次建立滚动计划"
            if previous:
                previous_ids = [str(value) for value in self._json_list(previous.item_ids_json)]
                if previous.action_type == action_type and previous_ids == item_ids:
                    change_reason = "新数据未改变结论，未来安排保持稳定"
                else:
                    changed_slots += 1
                    change_reason = "根据新快照、预算、交付容量或 72 小时冷却重新安排"
            new_slots.append(
                {
                    "date": slot_key,
                    "scheduled_time": scheduled_time,
                    "action_type": action_type,
                    "item_ids": item_ids,
                    "planned_cost": planned_cost,
                    "reason": reason,
                    "change_reason": change_reason,
                    "evidence": evidence,
                    "warnings": warnings,
                    "confidence": portfolio_quality,
                    "locked": offset <= 1,
                    "status": "planned",
                }
            )

        if latest:
            change_summary = (
                f"已生成第 {version} 版；今明两天保持稳定，未来计划调整 {changed_slots} 天。"
                if changed_slots
                else f"已生成第 {version} 版；新数据未改变主要安排。"
            )
        else:
            change_summary = "首次建立滚动 7 天计划；默认隔天安排一批并轮换商品。"
        if force:
            change_summary = "你已手动重新评估。" + change_summary

        plan = ProductOperatingPlan(
            id=f"product-plan-{uuid4()}",
            plan_start_date=today_key,
            version=version,
            status="current",
            input_signature=signature,
            weekly_budget=round(self.settings.product_traffic_weekly_budget, 2),
            change_summary=change_summary,
            data_quality=portfolio_quality,
            rules_version=RULES_VERSION,
            generated_at=utcnow(),
        )
        session.add(plan)
        session.flush()
        for slot_data in new_slots:
            session.add(
                ProductOperatingPlanSlot(
                    id=f"product-plan-slot-{uuid4()}",
                    plan_id=plan.id,
                    slot_date=slot_data["date"],
                    scheduled_time=slot_data["scheduled_time"],
                    action_type=slot_data["action_type"],
                    item_ids_json=json.dumps(slot_data["item_ids"], ensure_ascii=False),
                    planned_cost=slot_data["planned_cost"],
                    reason=slot_data["reason"],
                    change_reason=slot_data["change_reason"],
                    evidence_json=json.dumps(slot_data["evidence"], ensure_ascii=False),
                    warnings_json=json.dumps(slot_data["warnings"], ensure_ascii=False),
                    confidence=slot_data["confidence"],
                    locked=slot_data["locked"],
                    status=slot_data["status"],
                )
            )
        session.flush()
        return plan

    def _operating_plan_view(
        self,
        session,
        plan: ProductOperatingPlan,
        candidates: list[dict] | None = None,
    ) -> ProductOperatingPlanView:
        candidates = candidates or self._candidate_pool(session)
        candidate_by_external_id = {
            candidate["item"].external_id: candidate for candidate in candidates
        }
        batches = session.scalars(
            select(ProductTrafficBatch).where(ProductTrafficBatch.plan_slot_id.is_not(None))
        ).all()
        batch_by_slot = {batch.plan_slot_id: batch.id for batch in batches}
        slots = session.scalars(
            select(ProductOperatingPlanSlot)
            .where(ProductOperatingPlanSlot.plan_id == plan.id)
            .order_by(ProductOperatingPlanSlot.slot_date)
        ).all()
        # When a new plan version carries a locked day forward, its existing
        # batch still points to the previous slot. Match it safely by Beijing
        # day and overlapping product ids so the current plan does not create a
        # duplicate batch or count the same budget twice.
        all_active_batches = session.scalars(
            select(ProductTrafficBatch).where(ProductTrafficBatch.status != "cancelled")
        ).all()
        batch_product_ids: dict[str, set[str]] = {}
        for batch in all_active_batches:
            batch_product_ids[batch.id] = set(
                session.scalars(
                    select(Item.external_id)
                    .join(ProductTrafficBatchItem, ProductTrafficBatchItem.item_id == Item.id)
                    .where(ProductTrafficBatchItem.batch_id == batch.id)
                ).all()
            )
        for slot in slots:
            if slot.id in batch_by_slot:
                continue
            slot_ids = {str(value) for value in self._json_list(slot.item_ids_json)}
            for batch in all_active_batches:
                local_planned = self._local(batch.planned_at)
                if (
                    local_planned
                    and local_planned.date().isoformat() == slot.slot_date
                    and slot_ids
                    and slot_ids & batch_product_ids.get(batch.id, set())
                ):
                    batch_by_slot[slot.id] = batch.id
                    break
        slot_views: list[ProductOperatingPlanSlotView] = []
        for slot in slots:
            products: list[ProductPlanProductView] = []
            for external_id in self._json_list(slot.item_ids_json):
                candidate = candidate_by_external_id.get(str(external_id))
                if candidate:
                    products.append(
                        ProductPlanProductView(
                            external_id=candidate["item"].external_id,
                            title=candidate["item"].title,
                            role=candidate["role"],
                            score=candidate["score"],
                            data_quality=candidate["signal"]["data_quality"],
                            reason=candidate["reason"],
                        )
                    )
            try:
                slot_day = datetime.fromisoformat(slot.slot_date).date()
                weekday = WEEKDAY_LABELS[slot_day.weekday()]
            except ValueError:
                weekday = ""
            slot_views.append(
                ProductOperatingPlanSlotView(
                    id=slot.id,
                    date=slot.slot_date,
                    weekday=weekday,
                    scheduled_time=slot.scheduled_time,
                    action_type=slot.action_type,
                    products=products,
                    planned_cost=round(slot.planned_cost, 2),
                    reason=slot.reason,
                    change_reason=slot.change_reason,
                    evidence=[str(value) for value in self._json_list(slot.evidence_json)],
                    warnings=[str(value) for value in self._json_list(slot.warnings_json)],
                    confidence=slot.confidence,
                    locked=slot.locked,
                    status=slot.status,
                    batch_id=batch_by_slot.get(slot.id),
                )
            )
        spent, already_planned = self._week_traffic_totals(session)
        this_week_start = self._now().date() - timedelta(days=self._now().weekday())
        this_week_end = this_week_start + timedelta(days=7)
        unmaterialized = round(
            sum(
                slot.planned_cost
                for slot in slots
                if this_week_start <= datetime.fromisoformat(slot.slot_date).date() < this_week_end
                and slot.id not in batch_by_slot
            ),
            2,
        )
        planned_total = round(already_planned + unmaterialized, 2)
        effective_batch_count = self._effective_batch_count(session)
        return ProductOperatingPlanView(
            id=plan.id,
            version=plan.version,
            start_date=plan.plan_start_date,
            end_date=(datetime.fromisoformat(plan.plan_start_date).date() + timedelta(days=6)).isoformat(),
            generated_at=plan.generated_at,
            weekly_budget=round(plan.weekly_budget, 2),
            spent_this_week=spent,
            planned_this_week=planned_total,
            remaining_this_week=max(0, round(plan.weekly_budget - spent - planned_total, 2)),
            cadence="默认隔天一批；同一商品至少间隔 72 小时",
            change_summary=plan.change_summary,
            data_quality=plan.data_quality,
            rules_version=plan.rules_version,
            analysis_stage=self._analysis_stage(effective_batch_count),
            effective_batch_count=effective_batch_count,
            slots=slot_views,
        )

    def _traffic_batch_view(self, session, batch: ProductTrafficBatch) -> ProductTrafficBatchView:
        batch_items = session.scalars(
            select(ProductTrafficBatchItem)
            .where(ProductTrafficBatchItem.batch_id == batch.id)
            .order_by(ProductTrafficBatchItem.position)
        ).all()
        checkpoints = session.scalars(
            select(ProductTrafficCheckpoint)
            .where(ProductTrafficCheckpoint.batch_id == batch.id)
            .order_by(ProductTrafficCheckpoint.recorded_at)
        ).all()
        checkpoint_rank = {name: index for index, name in enumerate(CHECKPOINT_ORDER)}
        by_item: defaultdict[int, list[ProductTrafficCheckpoint]] = defaultdict(list)
        by_checkpoint: defaultdict[str, dict[int, ProductTrafficCheckpoint]] = defaultdict(dict)
        for checkpoint in checkpoints:
            by_item[checkpoint.item_id].append(checkpoint)
            by_checkpoint[checkpoint.checkpoint][checkpoint.item_id] = checkpoint

        completed_checkpoints = [
            checkpoint
            for checkpoint in CHECKPOINT_ORDER
            if batch_items
            and len(by_checkpoint.get(checkpoint, {})) >= len(batch_items)
        ]
        checkpoint_metrics: list[ProductTrafficCheckpointMetricsView] = []
        baseline_by_item = {value.item_id: value for value in batch_items}
        for checkpoint_name in completed_checkpoints:
            checkpoint_values = by_checkpoint[checkpoint_name]
            browse_delta = collect_delta = want_delta = inquiry_delta = 0
            for item_id, checkpoint in checkpoint_values.items():
                baseline = baseline_by_item[item_id]
                browse_delta += max(0, checkpoint.browse_count - baseline.baseline_browse_count)
                collect_delta += max(0, checkpoint.collect_count - baseline.baseline_collect_count)
                want_delta += max(0, checkpoint.want_count - baseline.baseline_want_count)
                inquiry_delta += max(0, checkpoint.inquiry_count - baseline.baseline_inquiry_count)
            checkpoint_metrics.append(
                ProductTrafficCheckpointMetricsView(
                    checkpoint=checkpoint_name,
                    hours=CHECKPOINT_HOURS[checkpoint_name],
                    browse_delta=browse_delta,
                    collect_delta=collect_delta,
                    want_delta=want_delta,
                    inquiry_delta=inquiry_delta,
                    inquiry_conversion_rate=self._traffic_conversion(
                        inquiry_delta,
                        browse_delta,
                    ),
                    average_browse_delta=round(browse_delta, 1),
                    average_inquiry_delta=round(inquiry_delta, 2),
                )
            )

        item_views: list[ProductTrafficBatchItemView] = []
        for batch_item in batch_items:
            item_checkpoints = by_item[batch_item.item_id]
            latest = (
                max(
                    item_checkpoints,
                    key=lambda value: checkpoint_rank.get(value.checkpoint, -1),
                )
                if item_checkpoints
                else None
            )
            browse = latest.browse_count if latest else batch_item.baseline_browse_count
            collect = latest.collect_count if latest else batch_item.baseline_collect_count
            want = latest.want_count if latest else batch_item.baseline_want_count
            inquiry = latest.inquiry_count if latest else batch_item.baseline_inquiry_count
            item_views.append(
                ProductTrafficBatchItemView(
                    external_id=batch_item.item.external_id,
                    title=batch_item.item.title,
                    baseline_browse_count=batch_item.baseline_browse_count,
                    baseline_collect_count=batch_item.baseline_collect_count,
                    baseline_want_count=batch_item.baseline_want_count,
                    baseline_inquiry_count=batch_item.baseline_inquiry_count,
                    baseline_captured_at=batch_item.baseline_captured_at,
                    latest_checkpoint=latest.checkpoint if latest else None,
                    latest_browse_count=browse,
                    latest_collect_count=collect,
                    latest_want_count=want,
                    latest_inquiry_count=inquiry,
                    browse_delta=max(0, browse - batch_item.baseline_browse_count),
                    collect_delta=max(0, collect - batch_item.baseline_collect_count),
                    want_delta=max(0, want - batch_item.baseline_want_count),
                    inquiry_delta=max(0, inquiry - batch_item.baseline_inquiry_count),
                )
            )
        due_checkpoint = None
        due_at = None
        started_at = self._utc(batch.started_at)
        if started_at and batch.status in {"running", "observing"}:
            due_checkpoint = next(
                (
                    checkpoint
                    for checkpoint in CHECKPOINT_ORDER
                    if checkpoint not in completed_checkpoints
                ),
                None,
            )
            if due_checkpoint:
                due_at = started_at + timedelta(hours=CHECKPOINT_HOURS[due_checkpoint])

        overlap_warning = None
        attribution_overlap = False
        anchor_at = started_at or self._utc(batch.planned_at)
        if anchor_at and batch_items:
            other_rows = session.execute(
                select(
                    ProductTrafficBatch.started_at,
                    ProductTrafficBatchItem.item_id,
                )
                .join(
                    ProductTrafficBatchItem,
                    ProductTrafficBatchItem.batch_id == ProductTrafficBatch.id,
                )
                .where(
                    ProductTrafficBatch.id != batch.id,
                    ProductTrafficBatch.started_at.is_not(None),
                    ProductTrafficBatch.status.in_(("running", "observing", "closed")),
                    ProductTrafficBatchItem.item_id.in_(
                        [item.item_id for item in batch_items]
                    ),
                )
            ).all()
            overlapping_items = {
                item_id
                for other_started_at, item_id in other_rows
                if self._utc(other_started_at)
                and abs((self._utc(other_started_at) - anchor_at).total_seconds())
                < self.settings.product_traffic_cooldown_hours * 3600
            }
            if overlapping_items:
                attribution_overlap = True
                overlap_warning = (
                    f"有 {len(overlapping_items)} 件商品与其他批次间隔不足 "
                    f"{self.settings.product_traffic_cooldown_hours} 小时，结果可能重叠"
                )

        observation_checkpoint = completed_checkpoints[-1] if completed_checkpoints else None
        latest_metric = checkpoint_metrics[-1] if checkpoint_metrics else None
        browse_delta = latest_metric.browse_delta if latest_metric else 0
        collect_delta = latest_metric.collect_delta if latest_metric else 0
        want_delta = latest_metric.want_delta if latest_metric else 0
        inquiry_delta = latest_metric.inquiry_delta if latest_metric else 0
        observation_hours = CHECKPOINT_HOURS.get(observation_checkpoint or "", 0)
        baseline_missing = bool(started_at) and any(
            value.baseline_captured_at is None for value in batch_items
        )
        baseline_stale = bool(started_at) and any(
            value.baseline_captured_at is not None
            and (
                started_at - (self._utc(value.baseline_captured_at) or started_at)
            ).total_seconds()
            > 24 * 3600
            for value in batch_items
        )
        inconsistent = False
        for batch_item in batch_items:
            previous = (
                batch_item.baseline_browse_count,
                batch_item.baseline_collect_count,
                batch_item.baseline_want_count,
                batch_item.baseline_inquiry_count,
            )
            for checkpoint in sorted(
                by_item[batch_item.item_id],
                key=lambda value: checkpoint_rank.get(value.checkpoint, -1),
            ):
                current = (
                    checkpoint.browse_count,
                    checkpoint.collect_count,
                    checkpoint.want_count,
                    checkpoint.inquiry_count,
                )
                if any(current_value < previous_value for current_value, previous_value in zip(current, previous)):
                    inconsistent = True
                    break
                previous = current
            if inconsistent:
                break

        if batch.status == "planned":
            data_quality = "planned"
        elif baseline_missing:
            data_quality = "missing_baseline"
        elif inconsistent:
            data_quality = "inconsistent"
        elif attribution_overlap:
            data_quality = "confounded"
        elif baseline_stale:
            data_quality = "stale_baseline"
        elif observation_checkpoint in {"h24", "h72"}:
            data_quality = "mature"
        elif observation_checkpoint:
            data_quality = "early"
        else:
            data_quality = "baseline"
        analysis_eligible = data_quality == "mature"
        time_bucket, _time_range = self._traffic_time_bucket(
            batch.started_at or batch.planned_at
        )
        return ProductTrafficBatchView(
            id=batch.id,
            plan_slot_id=batch.plan_slot_id,
            status=batch.status,
            planned_at=batch.planned_at,
            started_at=batch.started_at,
            completed_at=batch.completed_at,
            actual_cost=round(batch.actual_cost, 2),
            total_exposure=batch.total_exposure,
            note=batch.note,
            products=item_views,
            completed_checkpoints=completed_checkpoints,
            due_checkpoint=due_checkpoint,
            due_at=due_at,
            overlap_warning=overlap_warning,
            browse_delta=browse_delta,
            collect_delta=collect_delta,
            want_delta=want_delta,
            inquiry_delta=inquiry_delta,
            inquiry_conversion_rate=self._traffic_conversion(
                inquiry_delta,
                browse_delta,
            ),
            cost_per_browse=self._traffic_unit_cost(batch.actual_cost, browse_delta),
            cost_per_inquiry=self._traffic_unit_cost(batch.actual_cost, inquiry_delta),
            observation_checkpoint=observation_checkpoint,
            observation_hours=observation_hours,
            time_bucket=time_bucket,
            data_quality=data_quality,
            analysis_eligible=analysis_eligible,
            checkpoint_metrics=checkpoint_metrics,
            created_at=batch.created_at,
        )

    def _recent_traffic_batches(
        self,
        session,
        *,
        limit: int = 12,
    ) -> list[ProductTrafficBatchView]:
        batches = session.scalars(
            select(ProductTrafficBatch)
            .order_by(ProductTrafficBatch.planned_at.desc())
            .limit(limit)
        ).all()
        return [self._traffic_batch_view(session, batch) for batch in batches]

    def _exposure_analytics(
        self,
        session,
        *,
        window_days: int = 90,
    ) -> ProductExposureAnalyticsView:
        cutoff = utcnow() - timedelta(days=window_days)
        batches = session.scalars(
            select(ProductTrafficBatch)
            .where(
                ProductTrafficBatch.started_at.is_not(None),
                ProductTrafficBatch.started_at >= cutoff,
                ProductTrafficBatch.status.in_(("running", "observing", "closed")),
            )
            .order_by(ProductTrafficBatch.started_at.desc())
            .limit(120)
        ).all()
        views = [self._traffic_batch_view(session, batch) for batch in batches]
        mature = [
            batch
            for batch in views
            if batch.observation_checkpoint in {"h24", "h72"}
        ]
        eligible = [batch for batch in mature if batch.analysis_eligible]
        total_spent = round(sum(batch.actual_cost for batch in views), 2)
        observed_cost = round(sum(batch.actual_cost for batch in eligible), 2)
        browse_delta = sum(batch.browse_delta for batch in eligible)
        collect_delta = sum(batch.collect_delta for batch in eligible)
        want_delta = sum(batch.want_delta for batch in eligible)
        inquiry_delta = sum(batch.inquiry_delta for batch in eligible)
        eligible_count = len(eligible)

        checkpoint_groups: defaultdict[
            str,
            list[ProductTrafficCheckpointMetricsView],
        ] = defaultdict(list)
        for batch in views:
            if batch.data_quality in {
                "missing_baseline",
                "stale_baseline",
                "inconsistent",
                "confounded",
            }:
                continue
            for checkpoint in batch.checkpoint_metrics:
                checkpoint_groups[checkpoint.checkpoint].append(checkpoint)
        checkpoint_views: list[ProductTrafficCheckpointMetricsView] = []
        for checkpoint_name in CHECKPOINT_ORDER:
            values = checkpoint_groups.get(checkpoint_name, [])
            if not values:
                continue
            checkpoint_browse = sum(value.browse_delta for value in values)
            checkpoint_collect = sum(value.collect_delta for value in values)
            checkpoint_want = sum(value.want_delta for value in values)
            checkpoint_inquiry = sum(value.inquiry_delta for value in values)
            count = len(values)
            checkpoint_views.append(
                ProductTrafficCheckpointMetricsView(
                    checkpoint=checkpoint_name,
                    hours=CHECKPOINT_HOURS[checkpoint_name],
                    batch_count=count,
                    browse_delta=checkpoint_browse,
                    collect_delta=checkpoint_collect,
                    want_delta=checkpoint_want,
                    inquiry_delta=checkpoint_inquiry,
                    inquiry_conversion_rate=self._traffic_conversion(
                        checkpoint_inquiry,
                        checkpoint_browse,
                    ),
                    average_browse_delta=round(checkpoint_browse / count, 1),
                    average_inquiry_delta=round(checkpoint_inquiry / count, 2),
                )
            )

        grouped: defaultdict[str, list[ProductTrafficBatchView]] = defaultdict(list)
        for batch in eligible:
            grouped[batch.time_bucket].append(batch)
        time_bucket_rows: list[tuple[ProductTrafficTimeBucketView, float]] = []
        global_average_browse = browse_delta / eligible_count if eligible_count else 0
        global_average_inquiry = inquiry_delta / eligible_count if eligible_count else 0
        for bucket, bucket_batches in grouped.items():
            count = len(bucket_batches)
            bucket_cost = round(sum(batch.actual_cost for batch in bucket_batches), 2)
            bucket_browse = sum(batch.browse_delta for batch in bucket_batches)
            bucket_inquiry = sum(batch.inquiry_delta for batch in bucket_batches)
            start_hour = int(bucket)
            time_range = f"{start_hour:02d}:00–{start_hour + 1:02d}:59"
            confidence = "high" if count >= 6 else "medium" if count >= 3 else "low"
            # Two prior-equivalent batches shrink one lucky result toward the
            # portfolio mean before ranking different Beijing-time windows.
            smoothed_inquiry = (
                bucket_inquiry + global_average_inquiry * 2
            ) / (count + 2)
            smoothed_browse = (
                bucket_browse + global_average_browse * 2
            ) / (count + 2)
            conversion = self._traffic_conversion(bucket_inquiry, bucket_browse)
            average_cost = bucket_cost / count if count else 0
            score = (
                smoothed_inquiry / max(average_cost, 0.01) * 1000
                + (conversion or 0) * 2
                + smoothed_browse / max(average_cost, 0.01)
            )
            time_bucket_rows.append(
                (
                    ProductTrafficTimeBucketView(
                        bucket=bucket,
                        time_range=time_range,
                        batch_count=count,
                        total_cost=bucket_cost,
                        browse_delta=bucket_browse,
                        inquiry_delta=bucket_inquiry,
                        average_browse_delta=round(bucket_browse / count, 1),
                        average_inquiry_delta=round(bucket_inquiry / count, 2),
                        inquiry_conversion_rate=conversion,
                        cost_per_browse=self._traffic_unit_cost(
                            bucket_cost,
                            bucket_browse,
                        ),
                        cost_per_inquiry=self._traffic_unit_cost(
                            bucket_cost,
                            bucket_inquiry,
                        ),
                        confidence=confidence,
                        recommended=False,
                    ),
                    score,
                )
            )
        comparable = [value for value in time_bucket_rows if value[0].batch_count >= 2]
        best_bucket = max(comparable, key=lambda value: value[1])[0] if comparable else None
        time_buckets = sorted(
            [
                row.model_copy(update={"recommended": row.bucket == best_bucket.bucket})
                if best_bucket
                else row
                for row, _score in time_bucket_rows
            ],
            key=lambda value: (
                not value.recommended,
                -value.average_inquiry_delta,
                -value.average_browse_delta,
                value.bucket,
            ),
        )

        confidence = (
            "high"
            if eligible_count >= 12
            else "medium"
            if eligible_count >= 6
            else "low"
        )
        if eligible_count == 0:
            summary = (
                "尚无可比较的 +24h 或 +72h 批次。先补齐长尾检查点，"
                "系统不会用 1 小时套餐结束时的数据冒充最终效果。"
            )
        elif eligible_count < 2:
            summary = (
                f"当前只有 {eligible_count} 个可比较成熟批次，样本不足以比较投放时段；"
                "继续按同一口径记录后再调整投入。"
            )
        elif best_bucket is None:
            summary = (
                f"已有 {eligible_count} 个成熟批次，但每个时段都只出现一次。"
                "同一北京时间窗口至少重复 2 批后，才给出优先时段。"
            )
        else:
            summary = (
                f"当前 {best_bucket.time_range} 的平滑后表现相对更好；"
                f"该窗口已有 {best_bucket.batch_count} 批，仍应结合单位咨询成本和交付容量逐批验证。"
            )
        excluded_count = max(0, len(mature) - eligible_count)
        if excluded_count:
            summary += f" 另有 {excluded_count} 批因基线过旧、数据倒退或投放重叠未进入时段结论。"
        return ProductExposureAnalyticsView(
            window_days=window_days,
            total_spent=total_spent,
            observed_cost=observed_cost,
            eligible_batch_count=eligible_count,
            excluded_batch_count=excluded_count,
            browse_delta=browse_delta,
            collect_delta=collect_delta,
            want_delta=want_delta,
            inquiry_delta=inquiry_delta,
            average_browse_delta=(
                round(browse_delta / eligible_count, 1) if eligible_count else 0
            ),
            average_inquiry_delta=(
                round(inquiry_delta / eligible_count, 2) if eligible_count else 0
            ),
            inquiry_conversion_rate=self._traffic_conversion(
                inquiry_delta,
                browse_delta,
            ),
            cost_per_browse=self._traffic_unit_cost(observed_cost, browse_delta),
            cost_per_inquiry=self._traffic_unit_cost(observed_cost, inquiry_delta),
            confidence=confidence,
            best_time_bucket=best_bucket.time_range if best_bucket else None,
            summary=summary,
            checkpoints=checkpoint_views,
            time_buckets=time_buckets,
        )

    def _traffic_summary(
        self,
        session,
        batches: list[ProductTrafficBatchView] | None = None,
    ) -> ProductTrafficSummaryView:
        batches = batches if batches is not None else self._recent_traffic_batches(session)
        effective = self._effective_batch_count(session)
        stage = self._analysis_stage(effective)
        now = utcnow()
        due_count = sum(
            1
            for batch in batches
            if batch.due_at and self._utc(batch.due_at) <= now
        )
        spent, _planned = self._week_traffic_totals(session)
        if effective == 0:
            summary = "尚无包含 +24h 或 +72h 检查点的有效批次，当前计划只做探索和基线积累。"
        elif effective < 6:
            summary = f"已有 {effective} 个有效批次；达到 6 个后再启用自然基线与对照判断，避免过早下结论。"
        elif effective < 30:
            summary = "已进入对照学习阶段：结合自然窗口、批次长尾和贝叶斯平滑评估商品。"
        else:
            summary = "已进入探索与利用阶段：在已验证、潜力和新商品之间动态分配批次位置。"
        return ProductTrafficSummaryView(
            batch_count=int(
                session.scalar(select(func.count(ProductTrafficBatch.id))) or 0
            ),
            effective_batch_count=effective,
            active_batch_count=int(
                session.scalar(
                    select(func.count(ProductTrafficBatch.id)).where(
                        ProductTrafficBatch.status.in_(("planned", "running", "observing"))
                    )
                )
                or 0
            ),
            due_checkpoint_count=due_count,
            spent_this_week=spent,
            analysis_stage=stage,
            analysis_summary=summary,
        )

    def _sync_traffic_expense_in_session(
        self,
        session,
        batch: ProductTrafficBatch,
    ) -> tuple[int | None, bool]:
        if self.ledger is None or batch.started_at is None:
            return None, False
        product_count = int(
            session.scalar(
                select(func.count(ProductTrafficBatchItem.id)).where(
                    ProductTrafficBatchItem.batch_id == batch.id
                )
            )
            or 0
        )
        paid_at = self._local(batch.started_at)
        revision, changed = self.ledger.upsert_system_expense_in_session(
            session,
            expense_id=f"expense-traffic-{batch.id}",
            name=f"闲鱼曝光批次 · {product_count} 件商品",
            category="traffic",
            amount=batch.actual_cost,
            paid_at=(paid_at or self._now()).isoformat(),
            notes="商品经营自动记账；一笔费用对应整个多商品曝光批次。",
        )
        return revision, changed

    def create_traffic_batch(
        self,
        *,
        request_id: str,
        item_external_ids: list[str],
        planned_at: datetime,
        actual_cost: float,
        plan_slot_id: str | None,
        note: str,
    ) -> ProductTrafficBatchView:
        unique_ids = list(dict.fromkeys(item_external_ids))
        if len(unique_ids) != len(item_external_ids):
            raise ProductTrafficConflict("同一商品不能在一个曝光批次中重复选择")
        if len(unique_ids) > self.settings.product_traffic_batch_max_items:
            raise ProductTrafficConflict(
                f"一个批次最多选择 {self.settings.product_traffic_batch_max_items} 件商品"
            )
        with self.database.session() as session:
            existing = session.scalar(
                select(ProductTrafficBatch).where(
                    ProductTrafficBatch.request_id == request_id
                )
            )
            if existing:
                return self._traffic_batch_view(session, existing)
            monitors = session.scalars(
                select(ProductMonitor)
                .join(Item, Item.id == ProductMonitor.item_id)
                .where(Item.external_id.in_(unique_ids))
            ).all()
            by_external_id = {monitor.item.external_id: monitor for monitor in monitors}
            missing = [external_id for external_id in unique_ids if external_id not in by_external_id]
            if missing:
                raise ProductRecordNotFound("有商品不存在或尚未加入监测")
            restricted = [
                external_id
                for external_id, monitor in by_external_id.items()
                if monitor.ownership_status != "owned" or not monitor.enabled
            ]
            if restricted:
                raise ProductOwnershipRestricted("只能选择已确认属于本人且启用监测的商品")
            slot = None
            if plan_slot_id:
                slot = session.get(ProductOperatingPlanSlot, plan_slot_id)
                if slot is None:
                    raise ProductRecordNotFound("经营计划日期不存在")
                linked = session.scalar(
                    select(ProductTrafficBatch.id).where(
                        ProductTrafficBatch.plan_slot_id == plan_slot_id,
                        ProductTrafficBatch.status != "cancelled",
                    )
                )
                if linked:
                    raise ProductTrafficConflict("这个计划日期已经建立曝光批次")
            batch = ProductTrafficBatch(
                id=f"traffic-batch-{uuid4()}",
                request_id=request_id,
                plan_slot_id=plan_slot_id,
                status="planned",
                planned_at=self._utc(planned_at),
                actual_cost=round(actual_cost, 2),
                note=note.strip(),
                created_at=utcnow(),
            )
            session.add(batch)
            session.flush()
            for index, external_id in enumerate(unique_ids):
                monitor = by_external_id[external_id]
                snapshot = session.scalar(
                    select(ProductDailySnapshot)
                    .where(ProductDailySnapshot.item_id == monitor.item_id)
                    .order_by(ProductDailySnapshot.snapshot_date.desc())
                    .limit(1)
                )
                session.add(
                    ProductTrafficBatchItem(
                        batch_id=batch.id,
                        item_id=monitor.item_id,
                        position=index,
                        baseline_browse_count=snapshot.browse_count if snapshot else 0,
                        baseline_collect_count=snapshot.collect_count if snapshot else 0,
                        baseline_want_count=snapshot.want_count if snapshot else 0,
                        baseline_inquiry_count=snapshot.inquiry_count if snapshot else 0,
                        baseline_captured_at=snapshot.captured_at if snapshot else None,
                    )
                )
            if slot:
                slot.status = "scheduled"
            session.commit()
            result = self._traffic_batch_view(session, batch)
        self.event_hub.publish_nowait(
            {"type": "product_traffic_batch_updated", "batch_id": result.id}
        )
        return result

    def start_traffic_batch(self, batch_id: str) -> ProductTrafficBatchView:
        ledger_revision = None
        ledger_changed = False
        with self.database.session() as session:
            batch = session.get(ProductTrafficBatch, batch_id)
            if batch is None:
                raise ProductRecordNotFound("曝光批次不存在")
            if batch.status == "cancelled":
                raise ProductTrafficConflict("已取消的批次不能开始")
            if batch.status == "planned":
                batch.started_at = utcnow()
                batch.status = "running"
                batch_items = session.scalars(
                    select(ProductTrafficBatchItem).where(
                        ProductTrafficBatchItem.batch_id == batch.id
                    )
                ).all()
                for batch_item in batch_items:
                    snapshot = session.scalar(
                        select(ProductDailySnapshot)
                        .where(ProductDailySnapshot.item_id == batch_item.item_id)
                        .order_by(ProductDailySnapshot.snapshot_date.desc())
                        .limit(1)
                    )
                    if snapshot:
                        batch_item.baseline_browse_count = snapshot.browse_count
                        batch_item.baseline_collect_count = snapshot.collect_count
                        batch_item.baseline_want_count = snapshot.want_count
                        batch_item.baseline_inquiry_count = snapshot.inquiry_count
                        batch_item.baseline_captured_at = snapshot.captured_at
            ledger_revision, ledger_changed = self._sync_traffic_expense_in_session(
                session,
                batch,
            )
            session.commit()
            result = self._traffic_batch_view(session, batch)
        self.event_hub.publish_nowait(
            {"type": "product_traffic_batch_updated", "batch_id": batch_id}
        )
        if ledger_changed:
            self.event_hub.publish_nowait(
                {
                    "type": "ledger_updated",
                    "revision": ledger_revision,
                    "source": "product_traffic",
                }
            )
        return result

    def complete_traffic_batch(
        self,
        batch_id: str,
        *,
        completed_at: datetime,
        actual_cost: float,
        total_exposure: int | None,
        note: str,
    ) -> ProductTrafficBatchView:
        ledger_revision = None
        ledger_changed = False
        with self.database.session() as session:
            batch = session.get(ProductTrafficBatch, batch_id)
            if batch is None:
                raise ProductRecordNotFound("曝光批次不存在")
            if batch.status == "planned":
                raise ProductTrafficConflict("请先点击“开始批次”记录 T0 基线")
            if batch.status == "cancelled":
                raise ProductTrafficConflict("已取消的批次不能记录完成")
            batch.completed_at = self._utc(completed_at)
            batch.actual_cost = round(actual_cost, 2)
            batch.total_exposure = total_exposure
            if note.strip():
                batch.note = note.strip()
            if batch.status != "closed":
                batch.status = "observing"
            ledger_revision, ledger_changed = self._sync_traffic_expense_in_session(
                session,
                batch,
            )
            session.commit()
            result = self._traffic_batch_view(session, batch)
        self.event_hub.publish_nowait(
            {"type": "product_traffic_batch_updated", "batch_id": batch_id}
        )
        if ledger_changed:
            self.event_hub.publish_nowait(
                {
                    "type": "ledger_updated",
                    "revision": ledger_revision,
                    "source": "product_traffic",
                }
            )
        return result

    def record_traffic_checkpoint(
        self,
        batch_id: str,
        *,
        checkpoint: str,
        recorded_at: datetime,
        items: list[dict],
        note: str,
    ) -> ProductTrafficBatchView:
        if checkpoint not in CHECKPOINT_HOURS:
            raise ProductTrafficConflict("不支持的观察检查点")
        with self.database.session() as session:
            batch = session.get(ProductTrafficBatch, batch_id)
            if batch is None:
                raise ProductRecordNotFound("曝光批次不存在")
            if batch.status not in {"running", "observing", "closed"}:
                raise ProductTrafficConflict("批次尚未开始，不能记录观察数据")
            batch_items = session.scalars(
                select(ProductTrafficBatchItem).where(
                    ProductTrafficBatchItem.batch_id == batch.id
                )
            ).all()
            by_external_id = {
                batch_item.item.external_id: batch_item for batch_item in batch_items
            }
            submitted = {str(value["external_id"]) for value in items}
            if submitted != set(by_external_id):
                raise ProductTrafficConflict("每个检查点需要填写该批次的全部商品")
            recorded = self._utc(recorded_at) or utcnow()
            for value in items:
                batch_item = by_external_id[str(value["external_id"])]
                submitted_counts = (
                    int(value["browse_count"]),
                    int(value.get("collect_count", 0)),
                    int(value.get("want_count", 0)),
                    int(value.get("inquiry_count", 0)),
                )
                baseline_counts = (
                    batch_item.baseline_browse_count,
                    batch_item.baseline_collect_count,
                    batch_item.baseline_want_count,
                    batch_item.baseline_inquiry_count,
                )
                if any(
                    submitted < baseline
                    for submitted, baseline in zip(submitted_counts, baseline_counts)
                ):
                    raise ProductTrafficConflict(
                        f"{batch_item.item.title} 的累计值不能低于 T0 基线"
                    )
                other_checkpoints = session.scalars(
                    select(ProductTrafficCheckpoint).where(
                        ProductTrafficCheckpoint.batch_id == batch.id,
                        ProductTrafficCheckpoint.item_id == batch_item.item_id,
                        ProductTrafficCheckpoint.checkpoint != checkpoint,
                    )
                ).all()
                submitted_rank = CHECKPOINT_ORDER.index(checkpoint)
                for other in other_checkpoints:
                    other_rank = CHECKPOINT_ORDER.index(other.checkpoint)
                    other_counts = (
                        other.browse_count,
                        other.collect_count,
                        other.want_count,
                        other.inquiry_count,
                    )
                    if other_rank < submitted_rank and any(
                        submitted < previous
                        for submitted, previous in zip(submitted_counts, other_counts)
                    ):
                        raise ProductTrafficConflict(
                            f"{batch_item.item.title} 的累计值不能低于更早检查点"
                        )
                    if other_rank > submitted_rank and any(
                        submitted > later
                        for submitted, later in zip(submitted_counts, other_counts)
                    ):
                        raise ProductTrafficConflict(
                            f"{batch_item.item.title} 的累计值不能高于后续检查点"
                        )
                existing = session.scalar(
                    select(ProductTrafficCheckpoint).where(
                        ProductTrafficCheckpoint.batch_id == batch.id,
                        ProductTrafficCheckpoint.item_id == batch_item.item_id,
                        ProductTrafficCheckpoint.checkpoint == checkpoint,
                    )
                )
                if existing is None:
                    existing = ProductTrafficCheckpoint(
                        id=f"traffic-checkpoint-{uuid4()}",
                        batch_id=batch.id,
                        item_id=batch_item.item_id,
                        checkpoint=checkpoint,
                    )
                    session.add(existing)
                existing.browse_count = submitted_counts[0]
                existing.collect_count = submitted_counts[1]
                existing.want_count = submitted_counts[2]
                existing.inquiry_count = submitted_counts[3]
                existing.recorded_at = recorded
                existing.source = "manual"
                existing.note = note.strip()
            if checkpoint == "h72":
                batch.status = "closed"
            elif batch.status == "running":
                batch.status = "observing"
            session.commit()
            result = self._traffic_batch_view(session, batch)
        self.event_hub.publish_nowait(
            {
                "type": "product_traffic_checkpoint_recorded",
                "batch_id": batch_id,
                "checkpoint": checkpoint,
            }
        )
        return result

    def cancel_traffic_batch(self, batch_id: str) -> ProductTrafficBatchView:
        with self.database.session() as session:
            batch = session.get(ProductTrafficBatch, batch_id)
            if batch is None:
                raise ProductRecordNotFound("曝光批次不存在")
            if batch.status in {"running", "observing", "closed"}:
                raise ProductTrafficConflict("已经开始的批次不能取消，可继续补齐观察数据")
            batch.status = "cancelled"
            if batch.plan_slot_id:
                slot = session.get(ProductOperatingPlanSlot, batch.plan_slot_id)
                if slot:
                    slot.status = "planned"
            session.commit()
            result = self._traffic_batch_view(session, batch)
        self.event_hub.publish_nowait(
            {"type": "product_traffic_batch_updated", "batch_id": batch_id}
        )
        return result

    def update_plan_slot_lock(
        self,
        slot_id: str,
        locked: bool,
    ) -> ProductOperatingPlanView:
        with self.database.session() as session:
            slot = session.get(ProductOperatingPlanSlot, slot_id)
            if slot is None:
                raise ProductRecordNotFound("经营计划日期不存在")
            try:
                slot_day = datetime.fromisoformat(slot.slot_date).date()
            except ValueError:
                slot_day = self._now().date()
            if not locked and slot_day <= self._now().date() + timedelta(days=1):
                raise ProductTrafficConflict("今天和未来 24 小时的计划保持稳定，不能解锁")
            slot.locked = locked
            session.commit()
            plan = session.get(ProductOperatingPlan, slot.plan_id)
            if plan is None:
                raise ProductRecordNotFound("经营计划不存在")
            result = self._operating_plan_view(session, plan)
        self.event_hub.publish_nowait(
            {"type": "product_operating_plan_updated", "slot_id": slot_id}
        )
        return result

    def refresh_operating_plan(self) -> ProductOperatingPlanView:
        with self.database.session() as session:
            plan = self._ensure_operating_plan(session, force=True)
            session.commit()
            result = self._operating_plan_view(session, plan)
        self.event_hub.publish_nowait(
            {"type": "product_operating_plan_updated", "plan_id": result.id}
        )
        return result

    def _strategy(
        self,
        current: ProductDailySnapshot,
        previous: ProductDailySnapshot | None,
        *,
        active_projects: int,
        capacity: int,
        history_count: int,
        observation_days: int = 0,
        daily_browse: float | None = None,
        inquiry_delta: int | None = None,
        data_quality: str = "low",
        data_gaps: list[str] | None = None,
        traffic_cooldown_until: datetime | None = None,
        modification_observation_until: datetime | None = None,
        effective_batch_count: int = 0,
    ) -> dict:
        browse_delta = (
            max(0, current.browse_count - previous.browse_count)
            if previous is not None
            else None
        )
        inquiry_rate = (
            current.inquiry_count / current.browse_count * 100
            if current.browse_count > 0
            else None
        )
        deal_rate = (
            current.converted_project_count / current.inquiry_count * 100
            if current.inquiry_count > 0
            else None
        )
        confidence = "low"
        if data_quality == "high" and effective_batch_count >= 10:
            confidence = "high"
        elif data_quality in {"medium", "high"} or effective_batch_count >= 6:
            confidence = "medium"
        evidence = [
            f"经营浏览 {current.browse_count}，想要 {current.want_count}，收藏 {current.collect_count}",
            f"关联 {current.inquiry_count} 个咨询，形成 {current.converted_project_count} 个项目",
        ]
        if browse_delta is not None:
            interval = f"，折合日均 {daily_browse:.1f}" if daily_browse is not None else ""
            evidence.insert(
                0,
                f"最近 {max(1, observation_days)} 天新增 {browse_delta} 次浏览{interval}",
            )
        if current.revenue_total or current.profit_total:
            evidence.append(
                f"关联收入 ¥{current.revenue_total:,.0f}，实际利润 ¥{current.profit_total:,.0f}"
            )

        gaps = list(data_gaps or [])
        if gaps:
            evidence.append("数据缺口：" + "、".join(gaps[:3]))

        now = utcnow()
        if active_projects >= capacity:
            return {
                "strategy_code": "capacity_guard",
                "priority_score": 96,
                "attention": "high",
                "posture": "delivery_guard",
                "title": "先保护交付能力，暂缓新增流量",
                "summary": f"当前进行中项目已达到 {active_projects}/{capacity}。容量保护作用于全部商品，不再只限制已经成交过的商品。",
                "evidence": evidence + [f"进行中项目 {active_projects} 个，容量上限 {capacity} 个"],
                "actions": ["保持商品在线但暂停新增推广", "优先完成当前项目并检查回款", "释放交付容量后再重新评估"],
                "confidence": confidence,
            }
        if modification_observation_until and modification_observation_until > now:
            remaining = max(1, math.ceil((modification_observation_until - now).total_seconds() / 86_400))
            return {
                "strategy_code": "change_observation",
                "priority_score": 76,
                "attention": "medium",
                "posture": "measurement_guard",
                "title": "商品刚完成修改，先保持变量稳定",
                "summary": f"当前仍在修改后的观察期内，约剩 {remaining} 天；此时叠加曝光会让结果难以归因。",
                "evidence": evidence,
                "actions": ["保持标题、首图、价格和描述不变", "按日观察自然浏览与咨询", "观察期结束后再进入曝光批次"],
                "confidence": confidence,
            }
        if traffic_cooldown_until and traffic_cooldown_until > now:
            remaining_hours = max(1, math.ceil((traffic_cooldown_until - now).total_seconds() / 3600))
            return {
                "strategy_code": "traffic_cooldown",
                "priority_score": 72,
                "attention": "medium",
                "posture": "long_tail_observation",
                "title": "曝光长尾仍在观察，暂不重复投放",
                "summary": f"距上次批次不足 {self.settings.product_traffic_cooldown_hours} 小时，约剩 {remaining_hours} 小时冷却。1 小时内完成曝光不代表效果已经结束。",
                "evidence": evidence,
                "actions": ["记录 +24h 与 +72h 浏览和咨询", "把后续自然浏览纳入同一批次", "冷却结束前不重复选择该商品"],
                "confidence": confidence,
            }
        if "最近一次采集失败" in gaps or "最近数据不够新鲜" in gaps:
            return {
                "strategy_code": "data_quality_guard",
                "priority_score": 68,
                "attention": "medium",
                "posture": "data_guard",
                "title": "先补齐可靠数据，再决定是否投放",
                "summary": "采集失败或数据过旧时，规则不会把累计值误当成近期增长。",
                "evidence": evidence,
                "actions": ["等待下一次北京时间采集", "如需要可手工核对当前浏览和咨询", "数据恢复后重新生成 7 天计划"],
                "confidence": "low",
            }
        if (
            current.converted_project_count >= 1
            and current.profit_total > 0
            and (deal_rate or 0) >= 15
        ):
            return {
                "strategy_code": "scale_candidate",
                "priority_score": 88,
                "attention": "high",
                "posture": "scale_ready",
                "title": "具备成交和利润验证，可做小预算测试",
                "summary": "这件商品已经产生真实项目和正利润，可进入多商品小批次，但仍按批次总费用计算，不虚构单品曝光分摊。",
                "evidence": evidence,
                "actions": ["与 2–4 件商品组成约 ¥5.9 的人工批次", "记录 T0、+1h、+24h、+72h", "对比新增咨询、成交和利润，不只看套餐曝光量"],
                "confidence": confidence,
            }
        if current.inquiry_count >= 3 and current.converted_project_count == 0:
            return {
                "strategy_code": "inquiry_no_deal",
                "priority_score": 84,
                "attention": "high",
                "posture": "conversion_blocked",
                "title": "咨询存在但未成交，先优化信任与报价",
                "summary": "需求信号已经出现，问题更可能在服务边界、案例、回复或报价，而不是曝光不足。",
                "evidence": evidence,
                "actions": ["整理客户反复询问的问题并补进描述", "补充交付物、验收方式与案例", "复盘首次回复和未成交原因后再考虑投流"],
                "confidence": confidence,
            }
        if current.browse_count >= 80 and (inquiry_rate or 0) < 1:
            return {
                "strategy_code": "views_no_inquiry",
                "priority_score": 78,
                "attention": "medium",
                "posture": "message_fit_gap",
                "title": "浏览没有转成咨询，优先改商品表达",
                "summary": "入口已有流量，但咨询率偏低；继续加曝光会放大无效流量。",
                "evidence": evidence + [f"浏览到咨询约 {(inquiry_rate or 0):.1f}%"],
                "actions": ["人工检查首图与标题是否准确表达服务", "重写描述前两行，先说明能解决的问题", "修改后至少观察一个完整采集周期"],
                "confidence": confidence,
            }
        if (
            previous is not None
            and browse_delta is not None
            and daily_browse is not None
            and daily_browse <= 2
            and (inquiry_delta or 0) == 0
            and observation_days >= 1
        ):
            return {
                "strategy_code": "low_exposure",
                "priority_score": 70,
                "attention": "medium",
                "posture": "visibility_risk",
                "title": "流量与咨询停滞，适合安排一次人工优化",
                "summary": f"按真实 {observation_days} 天间隔归一化后，浏览和咨询仍接近停滞；先确认商品表达，再决定是否进入探索批次。",
                "evidence": evidence,
                "actions": ["一次只调整一个关键变量", "优先从标题关键词或首图中选择一项修改", "记录修改动作并观察 7 天"],
                "confidence": confidence,
            }
        if previous is None or history_count < 2:
            return {
                "strategy_code": "baseline",
                "priority_score": 35,
                "attention": "low",
                "posture": "observing",
                "title": "已建立经营基线，继续观察趋势",
                "summary": "目前只有一个数据点，系统不会用单次累计值做过度判断。",
                "evidence": evidence,
                "actions": ["保持商品稳定一个完整采集周期", "不要同时修改标题、价格和描述", "如需测试，只作为多商品批次中的探索位"],
                "confidence": "low",
            }
        return {
            "strategy_code": "healthy",
            "priority_score": 28,
            "attention": "low",
            "posture": "stable",
            "title": "当前表现稳定，暂不需要频繁修改",
            "summary": "没有发现明显的流量停滞、咨询断层或成交问题。规则会继续结合 24h、7d、28d 窗口和批次记录观察。",
            "evidence": evidence,
            "actions": ["继续按日观察", "有明显变化时再调整", "避免为了刷新而频繁修改商品"],
            "confidence": confidence,
        }

    def _refresh_recommendations(self, session) -> None:
        active_projects = self._active_project_count(session)
        capacity = self.settings.product_delivery_capacity
        effective_batch_count = int(
            session.scalar(
                select(func.count(distinct(ProductTrafficCheckpoint.batch_id))).where(
                    ProductTrafficCheckpoint.checkpoint.in_(("h24", "h72"))
                )
            )
            or 0
        )
        monitors = session.scalars(
            select(ProductMonitor).where(
                ProductMonitor.enabled.is_(True),
                ProductMonitor.ownership_status == "owned",
            )
        ).all()
        today = self._day_key()
        for monitor in monitors:
            history = session.scalars(
                select(ProductDailySnapshot)
                .where(ProductDailySnapshot.item_id == monitor.item_id)
                .order_by(ProductDailySnapshot.snapshot_date.desc())
                .limit(30)
            ).all()
            if not history:
                continue
            current = history[0]
            previous = history[1] if len(history) > 1 else None
            signal = self._product_signal_state(session, monitor, list(history))
            window_7d = signal["recent_windows"][1]
            result = self._strategy(
                current,
                previous,
                active_projects=active_projects,
                capacity=capacity,
                history_count=len(history),
                observation_days=window_7d.observation_days,
                daily_browse=window_7d.daily_browse,
                inquiry_delta=window_7d.inquiry_delta,
                data_quality=signal["data_quality"],
                data_gaps=signal["data_gaps"],
                traffic_cooldown_until=signal["traffic_cooldown_until"],
                modification_observation_until=signal[
                    "modification_observation_until"
                ],
                effective_batch_count=effective_batch_count,
            )
            existing = session.scalar(
                select(ProductStrategyRecommendation).where(
                    ProductStrategyRecommendation.item_id == monitor.item_id,
                    ProductStrategyRecommendation.recommendation_date == today,
                )
            )
            if existing is None:
                existing = ProductStrategyRecommendation(
                    id=f"product-rec-{uuid4()}",
                    item_id=monitor.item_id,
                    snapshot_id=current.id,
                    recommendation_date=today,
                    strategy_code=result["strategy_code"],
                    priority_score=result["priority_score"],
                    attention=result["attention"],
                    posture=result["posture"],
                    title=result["title"],
                    summary=result["summary"],
                    evidence_json=json.dumps(result["evidence"], ensure_ascii=False),
                    actions_json=json.dumps(result["actions"], ensure_ascii=False),
                    confidence=result["confidence"],
                    status="active",
                )
                session.add(existing)
            else:
                existing.snapshot_id = current.id
                existing.strategy_code = result["strategy_code"]
                existing.priority_score = result["priority_score"]
                existing.attention = result["attention"]
                existing.posture = result["posture"]
                existing.title = result["title"]
                existing.summary = result["summary"]
                existing.evidence_json = json.dumps(result["evidence"], ensure_ascii=False)
                existing.actions_json = json.dumps(result["actions"], ensure_ascii=False)
                existing.confidence = result["confidence"]

    def _publish_timing(self, session) -> PublishTimingView:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        # Count the first inbound message of each conversation. Repeated
        # follow-ups from one customer must not make a time window look better.
        timestamps = session.scalars(
            select(func.min(Message.received_at))
            .where(
                Message.direction == "inbound",
                Message.received_at >= cutoff,
            )
            .group_by(Message.conversation_id)
        ).all()
        buckets: dict[tuple[int, int], int] = defaultdict(int)
        for received_at in timestamps:
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
            local = received_at.astimezone(self.timezone)
            buckets[(local.weekday(), (local.hour // 2) * 2)] += 1
        sample_size = len(timestamps)
        windows = []
        for (weekday, start_hour), count in sorted(
            buckets.items(), key=lambda row: row[1], reverse=True
        )[:3]:
            windows.append(
                PublishWindowView(
                    weekday=WEEKDAY_LABELS[weekday],
                    time_range=f"{start_hour:02d}:00–{(start_hour + 2) % 24:02d}:00",
                    inquiry_count=count,
                    share=round(count / sample_size * 100, 1) if sample_size else 0,
                )
            )
        confidence = "high" if sample_size >= 50 else "medium" if sample_size >= 10 else "low"
        if not windows:
            summary = "尚无足够咨询时间数据，系统不会提供通用模板时段。"
        else:
            best = windows[0]
            summary = (
                f"过去 90 天首次咨询最集中在{best.weekday} {best.time_range}；"
                "建议发布后预留时间及时人工回复。"
            )
            if confidence == "low":
                summary += " 当前样本较少，仅作为观察提示。"
        return PublishTimingView(
            sample_size=sample_size,
            confidence=confidence,
            summary=summary,
            windows=windows,
        )

    def _demand_opportunities(self, session) -> list[DemandOpportunityView]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        rows = session.execute(
            select(Message.content, Message.conversation_id).where(
                Message.direction == "inbound",
                Message.received_at >= cutoff,
            )
        ).all()
        converted_conversations = set(
            session.scalars(
                select(BusinessProject.conversation_id).where(
                    BusinessProject.conversation_id.is_not(None)
                )
            ).all()
        )
        counts: dict[str, dict] = {
            theme: {"messages": 0, "conversations": set()}
            for theme, _keywords in DEMAND_THEMES
        }
        for content, conversation_id in rows:
            normalized = str(content or "").lower()
            for theme, keywords in DEMAND_THEMES:
                if any(keyword in normalized for keyword in keywords):
                    counts[theme]["messages"] += 1
                    counts[theme]["conversations"].add(conversation_id)
        opportunities: list[DemandOpportunityView] = []
        for theme, data in counts.items():
            conversation_ids = data["conversations"]
            if not conversation_ids:
                continue
            converted = len(conversation_ids & converted_conversations)
            if len(conversation_ids) >= 3 and converted == 0:
                posture = "供给缺口"
                suggestion = "存在重复需求但尚未形成项目，先整理服务范围、案例和验收边界。"
            elif converted:
                posture = "已验证"
                suggestion = "需求已经产生真实项目，可整理为更标准、边界更清晰的商品版本。"
            else:
                posture = "继续观察"
                suggestion = "当前需求信号较少，继续积累数据，不急于新增商品。"
            opportunities.append(
                DemandOpportunityView(
                    theme=theme,
                    message_count=data["messages"],
                    conversation_count=len(conversation_ids),
                    converted_project_count=converted,
                    posture=posture,
                    suggestion=suggestion,
                )
            )
        return sorted(
            opportunities,
            key=lambda value: (
                value.conversation_count,
                value.message_count,
                value.converted_project_count,
            ),
            reverse=True,
        )[:5]

    @staticmethod
    def _normalize_market_keyword(value: str) -> str:
        keyword = re.sub(r"\s+", " ", str(value or "").strip())
        if len(keyword) < 2 or len(keyword) > 80:
            raise ProductMarketConflict("关键词需要保持在 2–80 个字符")
        return keyword

    def _market_keyword_candidates(
        self, session
    ) -> list[ProductMarketKeywordCandidateView]:
        opportunities = {
            opportunity.theme: opportunity
            for opportunity in self._demand_opportunities(session)
        }
        owned_titles = [
            str(title or "").lower()
            for title in session.scalars(
                select(Item.title)
                .join(ProductMonitor, ProductMonitor.item_id == Item.id)
                .where(
                    ProductMonitor.enabled.is_(True),
                    ProductMonitor.ownership_status == "owned",
                )
            ).all()
        ]
        theme_tokens = {theme: keywords for theme, keywords in DEMAND_THEMES}
        active_projects = self._active_project_count(session)
        capacity_available = max(
            0, self.settings.product_delivery_capacity - active_projects
        )
        candidates: list[ProductMarketKeywordCandidateView] = []
        for theme, keyword in TECHNICAL_MARKET_KEYWORDS:
            opportunity = opportunities.get(theme)
            message_count = opportunity.message_count if opportunity else 0
            conversation_count = opportunity.conversation_count if opportunity else 0
            converted_count = (
                opportunity.converted_project_count if opportunity else 0
            )
            tokens = theme_tokens.get(theme, ())
            matching_products = sum(
                1 for title in owned_titles if any(token in title for token in tokens)
            )
            sample_days = int(
                session.scalar(
                    select(func.count(distinct(ProductMarketSample.sample_date))).where(
                        ProductMarketSample.keyword == keyword
                    )
                )
                or 0
            )
            score = (
                conversation_count * 12
                + message_count * 2
                + converted_count * 6
                + (24 if matching_products == 0 else max(0, 8 - matching_products * 2))
                + min(5, sample_days) * 3
                + (6 if capacity_available > 0 else -12)
            )
            if conversation_count >= 3 and sample_days >= 3:
                confidence = "high"
            elif conversation_count >= 2 or converted_count > 0 or sample_days > 0:
                confidence = "medium"
            else:
                confidence = "low"
            if conversation_count and matching_products == 0:
                reason = "真实咨询出现且本人商品尚未覆盖"
            elif converted_count:
                reason = "已有真实项目转化，适合验证标准化供给"
            elif sample_days:
                reason = "已有市场参考历史，可继续积累多日稳定度"
            else:
                reason = "技术实现类候选，需通过今天的真实搜索验证"
            evidence = [
                f"近 90 天相关咨询 {conversation_count} 个会话 / {message_count} 条消息",
                f"当前本人商品覆盖 {matching_products} 个",
                f"历史市场参考 {sample_days} 天",
                f"当前可用交付容量 {capacity_available} 个项目",
            ]
            candidates.append(
                ProductMarketKeywordCandidateView(
                    keyword=keyword,
                    theme=theme,
                    score=max(0, min(100, score)),
                    reason=reason,
                    evidence=evidence,
                    confidence=confidence,
                )
            )
        return sorted(
            candidates, key=lambda value: (-value.score, value.keyword)
        )[:3]

    def _ensure_market_keyword_plan(self, session) -> ProductMarketKeywordPlan:
        today = self._day_key()
        existing = session.scalar(
            select(ProductMarketKeywordPlan).where(
                ProductMarketKeywordPlan.plan_date == today
            )
        )
        if existing:
            return existing
        candidates = self._market_keyword_candidates(session)
        selected = candidates[0].keyword if candidates else "技术实现服务"
        evidence = [
            "候选词由真实咨询、本人商品覆盖、历史参考稳定度和交付容量共同排序",
            "候选仅是假设，不代表闲鱼官方热度或全站排名",
        ]
        plan = ProductMarketKeywordPlan(
            id=f"market-keyword-plan-{uuid4()}",
            plan_date=today,
            mode="recommended",
            selected_keyword=selected,
            custom_keyword="",
            recommended_candidates_json=json.dumps(
                [candidate.model_dump() for candidate in candidates],
                ensure_ascii=False,
            ),
            evidence_json=json.dumps(evidence, ensure_ascii=False),
            rules_version=MARKET_RULES_VERSION,
            save_as_common=False,
        )
        session.add(plan)
        session.flush()
        return plan

    def _market_sample_view(
        self, session, sample: ProductMarketSample
    ) -> ProductMarketSampleView:
        results = session.scalars(
            select(ProductMarketSampleResult)
            .where(ProductMarketSampleResult.sample_id == sample.id)
            .order_by(ProductMarketSampleResult.position)
        ).all()
        return ProductMarketSampleView(
            id=sample.id,
            keyword=sample.keyword,
            sample_date=sample.sample_date,
            source=sample.source,
            captured_at=sample.captured_at,
            result_count=sample.result_count,
            note=sample.note,
            results=[
                ProductMarketSampleResultView(
                    position=result.position,
                    title=result.title,
                    price=result.price,
                    tags=[str(tag) for tag in self._json_list(result.tags_json)],
                )
                for result in results
            ],
        )

    @staticmethod
    def _market_title_key(value: str) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())

    @staticmethod
    def _market_term_present(value: str, term: str) -> bool:
        normalized = str(value or "").lower()
        clean_term = term.lower()
        if re.search(r"[a-z0-9]", clean_term):
            return bool(
                re.search(
                    rf"(?<![a-z0-9]){re.escape(clean_term)}(?![a-z0-9])",
                    normalized,
                )
            )
        return clean_term in normalized

    @classmethod
    def _market_terms(cls, value: str) -> list[str]:
        return [
            term
            for term in MARKET_TITLE_TERMS
            if cls._market_term_present(value, term)
        ]

    @staticmethod
    def _market_percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        position = (len(ordered) - 1) * fraction
        lower_index = math.floor(position)
        upper_index = math.ceil(position)
        if lower_index == upper_index:
            return round(float(ordered[lower_index]), 2)
        weight = position - lower_index
        return round(
            float(ordered[lower_index] * (1 - weight) + ordered[upper_index] * weight),
            2,
        )

    @staticmethod
    def _market_price_label(value: float | None) -> str:
        if value is None:
            return "—"
        return f"¥{value:,.0f}" if float(value).is_integer() else f"¥{value:,.2f}"

    def _market_theme_for_text(self, value: str) -> str | None:
        normalized = str(value or "").lower()
        for theme, keyword in TECHNICAL_MARKET_KEYWORDS:
            if normalized == keyword.lower():
                return theme
        ranked: list[tuple[int, int, str]] = []
        for index, (theme, tokens) in enumerate(DEMAND_THEMES):
            score = sum(
                1 for token in tokens if self._market_term_present(normalized, token)
            )
            if score:
                ranked.append((score, -index, theme))
        return max(ranked)[2] if ranked else None

    def _market_benchmark(
        self, session, keyword: str
    ) -> ProductMarketBenchmarkView:
        if not keyword:
            return ProductMarketBenchmarkView(
                keyword="",
                sample_days=0,
                high_visibility_result_count=0,
                priced_result_count=0,
                repeated_result_count=0,
                median_price=None,
                price_low=None,
                price_high=None,
                common_title_terms=[],
                common_tags=[],
                median_title_length=None,
                confidence="low",
                evidence=["尚未选择关键词，无法建立市场基准"],
            )
        cutoff = (self._now().date() - timedelta(days=29)).isoformat()
        sample_days = int(
            session.scalar(
                select(func.count(distinct(ProductMarketSample.sample_date))).where(
                    ProductMarketSample.keyword == keyword,
                    ProductMarketSample.sample_date >= cutoff,
                )
            )
            or 0
        )
        rows = session.execute(
            select(
                ProductMarketSample.sample_date,
                ProductMarketSampleResult.position,
                ProductMarketSampleResult.title,
                ProductMarketSampleResult.price,
                ProductMarketSampleResult.tags_json,
            )
            .join(
                ProductMarketSample,
                ProductMarketSample.id == ProductMarketSampleResult.sample_id,
            )
            .where(
                ProductMarketSample.keyword == keyword,
                ProductMarketSample.sample_date >= cutoff,
                ProductMarketSampleResult.position <= 10,
            )
            .order_by(
                ProductMarketSample.sample_date.desc(),
                ProductMarketSampleResult.position,
            )
        ).all()
        prices: list[float] = []
        title_lengths: list[int] = []
        title_days: dict[str, set[str]] = defaultdict(set)
        term_counts: Counter[str] = Counter()
        tag_counts: Counter[str] = Counter()
        tag_labels: dict[str, str] = {}
        for sample_date, _position, title, price, tags_json in rows:
            title_text = str(title or "").strip()
            title_key = self._market_title_key(title_text)
            if title_key:
                title_days[title_key].add(str(sample_date))
            if title_text:
                title_lengths.append(len(title_text))
            for term in set(self._market_terms(title_text)):
                term_counts[term] += 1
            if price is not None and 0 < float(price) <= 1_000_000:
                prices.append(float(price))
            for raw_tag in self._json_list(tags_json):
                label = str(raw_tag or "").strip()
                key = label.casefold()
                if not key:
                    continue
                tag_counts[key] += 1
                tag_labels.setdefault(key, label)

        high_visibility_count = len(rows)
        repeated_count = sum(1 for days in title_days.values() if len(days) >= 2)
        minimum_term_count = 2 if high_visibility_count >= 2 else 1
        common_title_terms = [
            term
            for term, count in sorted(
                term_counts.items(),
                key=lambda row: (-row[1], MARKET_TITLE_TERMS.index(row[0])),
            )
            if count >= minimum_term_count
        ][:6]
        common_tags = [
            tag_labels[key]
            for key, _count in sorted(
                tag_counts.items(), key=lambda row: (-row[1], row[0])
            )[:5]
        ]
        median_price = round(float(median(prices)), 2) if prices else None
        price_low = self._market_percentile(prices, 0.25)
        price_high = self._market_percentile(prices, 0.75)
        median_title_length = (
            int(round(float(median(title_lengths)))) if title_lengths else None
        )
        if (
            sample_days >= 3
            and high_visibility_count >= 6
            and (repeated_count > 0 or len(common_title_terms) >= 2)
        ):
            confidence = "high"
        elif (sample_days >= 2 and high_visibility_count >= 3) or high_visibility_count >= 8:
            confidence = "medium"
        else:
            confidence = "low"

        evidence: list[str] = []
        if high_visibility_count:
            evidence.append(
                f"近 30 天 {sample_days} 个样本日，共提取 {high_visibility_count} 条前 10 位公开结果"
            )
            evidence.append(
                f"其中 {repeated_count} 个标题结构在至少两个样本日重复出现"
            )
        elif sample_days:
            evidence.append(
                f"近 30 天已有 {sample_days} 个样本日，但没有可用的前 10 位公开结果"
            )
        else:
            evidence.append("近 30 天尚无该关键词的人工导入市场样本")
        if prices:
            evidence.append(
                "公开标价中位数 "
                f"{self._market_price_label(median_price)}，中间区间 "
                f"{self._market_price_label(price_low)}–{self._market_price_label(price_high)}；"
                "公开标价不等于最终成交价"
            )
        if common_title_terms:
            evidence.append(
                f"高位参考中反复出现的通用能力词：{'、'.join(common_title_terms[:5])}"
            )
        if common_tags:
            evidence.append(f"常见公开标签：{'、'.join(common_tags)}")
        return ProductMarketBenchmarkView(
            keyword=keyword,
            sample_days=sample_days,
            high_visibility_result_count=high_visibility_count,
            priced_result_count=len(prices),
            repeated_result_count=repeated_count,
            median_price=median_price,
            price_low=price_low,
            price_high=price_high,
            common_title_terms=common_title_terms,
            common_tags=common_tags,
            median_title_length=median_title_length,
            confidence=confidence,
            evidence=evidence,
        )

    def _market_benchmarks(self, session) -> list[ProductMarketBenchmarkView]:
        cutoff = (self._now().date() - timedelta(days=29)).isoformat()
        keywords = session.scalars(
            select(distinct(ProductMarketSample.keyword)).where(
                ProductMarketSample.sample_date >= cutoff
            )
        ).all()
        return [self._market_benchmark(session, str(keyword)) for keyword in keywords]

    def _matching_market_benchmark(
        self,
        title: str,
        benchmarks: list[ProductMarketBenchmarkView],
    ) -> ProductMarketBenchmarkView | None:
        title_theme = self._market_theme_for_text(title)
        title_terms = set(self._market_terms(title))
        ranked: list[tuple[int, int, int, ProductMarketBenchmarkView]] = []
        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        for benchmark in benchmarks:
            if benchmark.high_visibility_result_count <= 0:
                continue
            benchmark_theme = self._market_theme_for_text(benchmark.keyword)
            benchmark_terms = set(self._market_terms(benchmark.keyword))
            overlap = len(title_terms & (benchmark_terms | set(benchmark.common_title_terms)))
            if title_theme:
                if benchmark_theme != title_theme:
                    continue
                match_score = 100 + overlap * 5
            else:
                if overlap == 0:
                    continue
                match_score = overlap * 10
            ranked.append(
                (
                    match_score,
                    confidence_rank.get(benchmark.confidence, 0),
                    benchmark.sample_days * 100 + benchmark.high_visibility_result_count,
                    benchmark,
                )
            )
        return max(ranked, key=lambda row: row[:3])[3] if ranked else None

    def _market_stability(
        self, session, keyword: str
    ) -> ProductMarketStabilityView:
        if not keyword:
            return ProductMarketStabilityView(
                keyword="",
                sample_days=0,
                visible_days=0,
                average_best_position=None,
                status="insufficient",
                label="等待选择关键词",
            )
        cutoff = (self._now().date() - timedelta(days=29)).isoformat()
        samples = session.scalars(
            select(ProductMarketSample)
            .where(
                ProductMarketSample.keyword == keyword,
                ProductMarketSample.sample_date >= cutoff,
            )
            .order_by(ProductMarketSample.sample_date.desc())
        ).all()
        best_positions: list[int] = []
        for sample in samples:
            position = session.scalar(
                select(func.min(ProductMarketSampleResult.position)).where(
                    ProductMarketSampleResult.sample_id == sample.id
                )
            )
            if position is not None:
                best_positions.append(int(position))
        sample_days = len(samples)
        visible_days = len(best_positions)
        average_position = (
            round(sum(best_positions) / visible_days, 1)
            if visible_days
            else None
        )
        if sample_days >= 3 and visible_days >= 3 and (average_position or 999) <= 10:
            status = "stable"
            label = "连续多日高可见参考"
        elif sample_days >= 2:
            status = "emerging"
            label = "正在形成多日参考"
        else:
            status = "insufficient"
            label = "需要连续多日验证"
        return ProductMarketStabilityView(
            keyword=keyword,
            sample_days=sample_days,
            visible_days=visible_days,
            average_best_position=average_position,
            status=status,
            label=label,
        )

    def _market_reference_view(
        self, session, plan: ProductMarketKeywordPlan
    ) -> ProductMarketReferenceView:
        today = self._day_key()
        current_sample = session.scalar(
            select(ProductMarketSample).where(
                ProductMarketSample.keyword == plan.selected_keyword,
                ProductMarketSample.sample_date == today,
            )
        )
        recent_samples = session.scalars(
            select(ProductMarketSample)
            .where(ProductMarketSample.keyword == plan.selected_keyword)
            .order_by(ProductMarketSample.sample_date.desc())
            .limit(7)
        ).all()
        reminder = session.scalar(
            select(ProductMarketReminderLog).where(
                ProductMarketReminderLog.reminder_date == today
            )
        )
        scheduled = self._market_scheduled_for()
        if current_sample:
            reminder_status = "completed"
        elif reminder:
            reminder_status = reminder.status
        else:
            reminder_status = "pending"
        due = (
            not current_sample
            and reminder_status not in {"skipped", "completed"}
            and self._now() >= scheduled
        )
        common_keywords = []
        for value in session.scalars(
            select(ProductMarketKeywordPlan.custom_keyword)
            .where(
                ProductMarketKeywordPlan.save_as_common.is_(True),
                ProductMarketKeywordPlan.custom_keyword != "",
            )
            .order_by(ProductMarketKeywordPlan.updated_at.desc())
            .limit(20)
        ).all():
            if value not in common_keywords:
                common_keywords.append(value)
        raw_candidates = self._json_list(plan.recommended_candidates_json)
        candidates = [
            ProductMarketKeywordCandidateView.model_validate(candidate)
            for candidate in raw_candidates
            if isinstance(candidate, dict)
        ]
        return ProductMarketReferenceView(
            date=today,
            mode=plan.mode,
            selected_keyword=plan.selected_keyword,
            custom_keyword=plan.custom_keyword,
            recommendations=candidates,
            common_keywords=common_keywords[:8],
            current_sample=(
                self._market_sample_view(session, current_sample)
                if current_sample
                else None
            ),
            recent_samples=[
                self._market_sample_view(session, sample) for sample in recent_samples
            ],
            stability=self._market_stability(session, plan.selected_keyword),
            benchmark=self._market_benchmark(session, plan.selected_keyword),
            reminder=ProductMarketReminderView(
                date=today,
                status=reminder_status,
                scheduled_for=scheduled,
                due=due,
                snoozed_until=reminder.snoozed_until if reminder else None,
            ),
            update_completed=bool(current_sample),
            last_updated_at=current_sample.captured_at if current_sample else None,
            rules_version=MARKET_RULES_VERSION,
            safety_note=(
                "仅保存关键词、标题、价格、标签、搜索位置和采集时间；"
                "不保存 Cookie、卖家身份、平台敏感 ID、原始页面或 HTML。"
            ),
        )

    def market_reference(self) -> ProductMarketReferenceView:
        with self.database.session() as session:
            plan = self._ensure_market_keyword_plan(session)
            session.commit()
            return self._market_reference_view(session, plan)

    def update_market_keyword(
        self, *, mode: str, keyword: str, save_as_common: bool
    ) -> ProductMarketReferenceView:
        normalized = self._normalize_market_keyword(keyword)
        with self.database.session() as session:
            plan = self._ensure_market_keyword_plan(session)
            candidates = {
                candidate.get("keyword")
                for candidate in self._json_list(plan.recommended_candidates_json)
                if isinstance(candidate, dict)
            }
            if mode == "recommended" and normalized not in candidates:
                raise ProductMarketConflict("请选择今天系统给出的候选关键词")
            plan.mode = mode
            plan.selected_keyword = normalized
            plan.custom_keyword = normalized if mode == "custom" else ""
            plan.save_as_common = bool(save_as_common and mode == "custom")
            session.commit()
            result = self._market_reference_view(session, plan)
        self.event_hub.publish_nowait(
            {
                "type": "product_market_reference_updated",
                "date": result.date,
                "mode": result.mode,
            }
        )
        return result

    def import_market_reference(
        self,
        *,
        keyword: str,
        captured_at: datetime,
        results: list[dict],
        note: str,
    ) -> ProductMarketReferenceView:
        normalized = self._normalize_market_keyword(keyword)
        captured_local = (
            captured_at.replace(tzinfo=self.timezone)
            if captured_at.tzinfo is None
            else captured_at.astimezone(self.timezone)
        )
        if captured_local.date() != self._now().date():
            raise ProductMarketConflict("只能导入今天在现有 Edge 中取得的搜索参考")
        if captured_local > self._now() + timedelta(minutes=5):
            raise ProductMarketConflict("采集时间不能晚于当前北京时间")
        with self.database.session() as session:
            plan = self._ensure_market_keyword_plan(session)
            if normalized != plan.selected_keyword:
                raise ProductMarketConflict("导入关键词与今天选中的关键词不一致")
            today = self._day_key(captured_local)
            sample = session.scalar(
                select(ProductMarketSample).where(
                    ProductMarketSample.keyword == normalized,
                    ProductMarketSample.sample_date == today,
                )
            )
            if sample is None:
                sample = ProductMarketSample(
                    id=f"market-sample-{uuid4()}",
                    keyword=normalized,
                    sample_date=today,
                    source="edge_codex",
                    captured_at=captured_local.astimezone(timezone.utc),
                    result_count=len(results),
                    note=note.strip(),
                )
                session.add(sample)
                session.flush()
            else:
                sample.captured_at = captured_local.astimezone(timezone.utc)
                sample.result_count = len(results)
                sample.note = note.strip()
                session.execute(
                    delete(ProductMarketSampleResult).where(
                        ProductMarketSampleResult.sample_id == sample.id
                    )
                )
            for result in sorted(results, key=lambda value: int(value["position"])):
                tags = []
                for tag in result.get("tags", []):
                    clean = str(tag).strip()
                    if clean and clean not in tags:
                        tags.append(clean)
                session.add(
                    ProductMarketSampleResult(
                        sample_id=sample.id,
                        position=int(result["position"]),
                        title=str(result["title"]).strip(),
                        price=(
                            round(float(result["price"]), 2)
                            if result.get("price") is not None
                            else None
                        ),
                        tags_json=json.dumps(tags, ensure_ascii=False),
                    )
                )
            reminder = session.scalar(
                select(ProductMarketReminderLog).where(
                    ProductMarketReminderLog.reminder_date == today
                )
            )
            if reminder is None:
                reminder = ProductMarketReminderLog(
                    id=f"market-reminder-{uuid4()}",
                    reminder_date=today,
                    status="completed",
                    scheduled_for=self._market_scheduled_for(
                        captured_local
                    ).astimezone(timezone.utc),
                )
                session.add(reminder)
            else:
                reminder.status = "completed"
                reminder.snoozed_until = None
            session.commit()
            result_view = self._market_reference_view(session, plan)
        self.event_hub.publish_nowait(
            {
                "type": "product_market_reference_updated",
                "date": result_view.date,
                "keyword": normalized,
                "status": "completed",
            }
        )
        return result_view

    def snooze_market_reminder(self, hours: int) -> ProductMarketReferenceView:
        now = self._now()
        today = self._day_key(now)
        with self.database.session() as session:
            plan = self._ensure_market_keyword_plan(session)
            sample = session.scalar(
                select(ProductMarketSample.id).where(
                    ProductMarketSample.sample_date == today,
                    ProductMarketSample.keyword == plan.selected_keyword,
                )
            )
            if sample:
                raise ProductMarketConflict("今天的市场参考已经更新")
            reminder = session.scalar(
                select(ProductMarketReminderLog).where(
                    ProductMarketReminderLog.reminder_date == today
                )
            )
            if reminder is None:
                reminder = ProductMarketReminderLog(
                    id=f"market-reminder-{uuid4()}",
                    reminder_date=today,
                    scheduled_for=self._market_scheduled_for(now).astimezone(timezone.utc),
                )
                session.add(reminder)
            reminder.status = "snoozed"
            reminder.snoozed_until = (now + timedelta(hours=hours)).astimezone(
                timezone.utc
            )
            session.commit()
            result = self._market_reference_view(session, plan)
        self.event_hub.publish_nowait(
            {
                "type": "product_market_reminder_updated",
                "date": today,
                "status": "snoozed",
            }
        )
        return result

    def skip_market_reminder(self) -> ProductMarketReferenceView:
        now = self._now()
        today = self._day_key(now)
        with self.database.session() as session:
            plan = self._ensure_market_keyword_plan(session)
            reminder = session.scalar(
                select(ProductMarketReminderLog).where(
                    ProductMarketReminderLog.reminder_date == today
                )
            )
            if reminder is None:
                reminder = ProductMarketReminderLog(
                    id=f"market-reminder-{uuid4()}",
                    reminder_date=today,
                    scheduled_for=self._market_scheduled_for(now).astimezone(timezone.utc),
                )
                session.add(reminder)
            reminder.status = "skipped"
            reminder.snoozed_until = None
            session.commit()
            result = self._market_reference_view(session, plan)
        self.event_hub.publish_nowait(
            {
                "type": "product_market_reminder_updated",
                "date": today,
                "status": "skipped",
            }
        )
        return result

    def _launch_recommendation(
        self, session, market: ProductMarketReferenceView
    ) -> ProductLaunchRecommendationView:
        candidate = next(
            (
                value
                for value in market.recommendations
                if value.keyword == market.selected_keyword
            ),
            market.recommendations[0] if market.recommendations else None,
        )
        theme = candidate.theme if candidate else "技术实现服务"
        opportunities = {
            value.theme: value for value in self._demand_opportunities(session)
        }
        demand = opportunities.get(theme)
        demand_conversations = demand.conversation_count if demand else 0
        tokens = dict(DEMAND_THEMES).get(theme, ())
        matching_product_count = sum(
            1
            for title in session.scalars(
                select(Item.title)
                .join(ProductMonitor, ProductMonitor.item_id == Item.id)
                .where(
                    ProductMonitor.enabled.is_(True),
                    ProductMonitor.ownership_status == "owned",
                )
            ).all()
            if any(token in str(title or "").lower() for token in tokens)
        )
        active_projects = self._active_project_count(session)
        capacity_available = max(
            0, self.settings.product_delivery_capacity - active_projects
        )
        timing = self._publish_timing(session)
        window = (
            f"{timing.windows[0].weekday} {timing.windows[0].time_range}"
            if timing.windows
            else "需要更多咨询时段样本"
        )
        benchmark = market.benchmark
        validation_required = not (
            market.stability.status == "stable"
            and benchmark.sample_days >= 3
            and benchmark.high_visibility_result_count >= 3
        )
        if matching_product_count > 0:
            recommended_action = "modify_existing"
        elif (
            demand_conversations > 0
            and capacity_available > 0
            and not validation_required
        ):
            recommended_action = "launch"
        else:
            recommended_action = "observe"
        if (
            recommended_action == "launch"
            and demand_conversations >= 3
            and benchmark.confidence == "high"
        ):
            confidence = "high"
        elif (
            demand_conversations > 0
            or matching_product_count > 0
            or benchmark.high_visibility_result_count > 0
        ):
            confidence = "medium"
        else:
            confidence = "low"

        common_terms = benchmark.common_title_terms[:3]
        title_term_text = "、".join(common_terms) if common_terms else market.selected_keyword
        suggested_product_type = f"{theme} · 交付边界清晰的技术服务"
        title_direction = (
            f"围绕“{market.selected_keyword}”组织标题，突出{title_term_text}，"
            "并写清交付物与验收范围；不要照搬其他商品完整标题"
        )
        if benchmark.median_price is not None:
            price_reference = (
                f"公开标价中位数 {self._market_price_label(benchmark.median_price)}，"
                f"中间区间 {self._market_price_label(benchmark.price_low)}–"
                f"{self._market_price_label(benchmark.price_high)}；仅用于校准展示方式"
            )
        else:
            price_reference = "暂无足够公开标价；最终金额仍按工时、风险和交付范围报价"
        common_signal = common_terms or benchmark.common_tags[:3]
        market_differentiation = (
            f"高位参考普遍强调{'、'.join(common_signal)}；你的商品应进一步明确周期、"
            "交付物、验收标准和不包含范围"
            if common_signal
            else "先积累多日高可见参考，再确定差异化；当前不要凭单日结果改写商品"
        )
        rationale = [
            (
                f"近 90 天出现 {demand_conversations} 个相关咨询会话"
                if demand_conversations
                else "尚无足够真实咨询，需要先验证需求"
            ),
            (
                "本人商品尚未覆盖这一方向"
                if matching_product_count == 0
                else f"已有 {matching_product_count} 个相关商品，先检查是否应修改而非重复上新"
            ),
            (
                f"当前仍可承接约 {capacity_available} 个项目"
                if capacity_available > 0
                else "当前交付容量已满，不建议立即扩大供给"
            ),
            (
                f"近 30 天已有 {benchmark.sample_days} 个样本日、"
                f"{benchmark.high_visibility_result_count} 条高可见公开结果"
                if benchmark.high_visibility_result_count
                else "尚无可用于上新决策的高可见市场参考"
            ),
        ]
        if recommended_action == "launch":
            rationale.append("需求、供给缺口、交付容量和多日市场证据同时满足，可建立人工上新方案")
        elif recommended_action == "modify_existing":
            rationale.append("已有同类本人商品，优先做单变量修改实验，避免重复上新分散流量")
        elif capacity_available <= 0:
            rationale.append("先完成当前交付，再重新评估上新时间")
        elif validation_required:
            rationale.append("市场证据尚未形成多日稳定基准，继续观察而不强行上新")
        else:
            rationale.append("需求信号仍不足，继续积累真实咨询再决定")
        evidence = list(candidate.evidence if candidate else [])
        evidence.extend(benchmark.evidence)
        evidence.append(timing.summary)
        return ProductLaunchRecommendationView(
            keyword=market.selected_keyword,
            theme=theme,
            title=f"{market.selected_keyword}｜明确交付物与验收边界",
            recommended_window=window,
            demand_conversations=demand_conversations,
            matching_product_count=matching_product_count,
            capacity_available=capacity_available,
            confidence=confidence,
            market_validation_required=validation_required,
            ready=recommended_action == "launch",
            recommended_action=recommended_action,
            suggested_product_type=suggested_product_type,
            title_direction=title_direction,
            price_reference=price_reference,
            market_differentiation=market_differentiation,
            timing_basis=timing.summary,
            benchmark=benchmark,
            rationale=rationale,
            evidence=evidence,
        )

    def _launch_plan_view(self, plan: ProductLaunchPlan) -> ProductLaunchPlanView:
        return ProductLaunchPlanView(
            id=plan.id,
            keyword=plan.keyword,
            theme=plan.theme,
            title=plan.title,
            recommended_window=plan.recommended_window,
            rationale=[str(value) for value in self._json_list(plan.rationale_json)],
            evidence=[str(value) for value in self._json_list(plan.evidence_json)],
            confidence=plan.confidence,
            status=plan.status,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )

    def create_launch_plan(
        self, *, keyword: str, title: str | None
    ) -> ProductLaunchPlanView:
        normalized = self._normalize_market_keyword(keyword)
        with self.database.session() as session:
            keyword_plan = self._ensure_market_keyword_plan(session)
            market = self._market_reference_view(session, keyword_plan)
            recommendation = self._launch_recommendation(session, market)
            if normalized != recommendation.keyword:
                raise ProductMarketConflict("请先把该关键词设为今天的验证关键词")
            existing = session.scalar(
                select(ProductLaunchPlan).where(
                    ProductLaunchPlan.keyword == normalized,
                    ProductLaunchPlan.status.in_(("proposed", "planned")),
                )
            )
            if existing:
                raise ProductMarketConflict("该关键词已经有一个进行中的上新方案")
            plan = ProductLaunchPlan(
                id=f"product-launch-{uuid4()}",
                keyword=normalized,
                theme=recommendation.theme,
                title=(str(title or "").strip() or recommendation.title),
                recommended_window=recommendation.recommended_window,
                rationale_json=json.dumps(recommendation.rationale, ensure_ascii=False),
                evidence_json=json.dumps(recommendation.evidence, ensure_ascii=False),
                confidence=recommendation.confidence,
                status="planned",
            )
            session.add(plan)
            session.commit()
            result = self._launch_plan_view(plan)
        self.event_hub.publish_nowait(
            {"type": "product_launch_plan_updated", "plan_id": result.id}
        )
        return result

    def update_launch_plan(self, plan_id: str, status: str) -> ProductLaunchPlanView:
        with self.database.session() as session:
            plan = session.get(ProductLaunchPlan, plan_id)
            if plan is None:
                raise ProductRecordNotFound("上新方案不存在")
            plan.status = status
            session.commit()
            result = self._launch_plan_view(plan)
        self.event_hub.publish_nowait(
            {"type": "product_launch_plan_updated", "plan_id": plan_id}
        )
        return result

    def _experiment_view(
        self, experiment: ProductModificationExperiment
    ) -> ProductModificationExperimentView:
        now = self._now().astimezone(timezone.utc)
        observation_until = self._utc(experiment.observation_until) or now
        return ProductModificationExperimentView(
            id=experiment.id,
            item_external_id=experiment.item.external_id,
            item_title=experiment.item.title,
            variable=experiment.variable,
            before_value=experiment.before_value,
            after_value=experiment.after_value,
            baseline=_json_dict(experiment.baseline_json),
            started_at=experiment.started_at,
            observation_until=experiment.observation_until,
            status=experiment.status,
            result=_json_dict(experiment.result_json),
            decision=experiment.decision,
            evidence=[str(value) for value in self._json_list(experiment.evidence_json)],
            can_evaluate=experiment.status == "observing" and now >= observation_until,
        )

    def _modification_suggestions(
        self, session
    ) -> list[ProductModificationSuggestionView]:
        monitors = session.scalars(
            select(ProductMonitor)
            .where(
                ProductMonitor.enabled.is_(True),
                ProductMonitor.ownership_status == "owned",
            )
            .order_by(ProductMonitor.id)
        ).all()
        suggestions: list[ProductModificationSuggestionView] = []
        benchmarks = self._market_benchmarks(session)
        now = self._now().astimezone(timezone.utc)
        for monitor in monitors:
            history = session.scalars(
                select(ProductDailySnapshot)
                .where(ProductDailySnapshot.item_id == monitor.item_id)
                .order_by(ProductDailySnapshot.snapshot_date.desc())
                .limit(30)
            ).all()
            current = history[0] if history else None
            signal = self._product_signal_state(session, monitor, list(history))
            active = session.scalar(
                select(ProductModificationExperiment).where(
                    ProductModificationExperiment.item_id == monitor.item_id,
                    ProductModificationExperiment.status == "observing",
                )
            )
            blocked_reason = None
            if active:
                blocked_reason = "已有单变量实验正在观察"
            elif (
                signal["traffic_cooldown_until"]
                and signal["traffic_cooldown_until"] > now
            ):
                blocked_reason = "曝光长尾观察中，暂不混入商品修改"
            elif not current or signal["data_quality"] == "low":
                blocked_reason = "先补齐至少 3 个可比较快照日"
            variable: str | None = None
            reason = "当前数据不足，暂不建议修改"
            suggested_change = "继续积累可比较快照，暂不改变商品表达"
            benchmark = self._matching_market_benchmark(
                current.title if current else monitor.item.title,
                benchmarks,
            )
            evidence_sources = ["内部表现"]
            market_evidence: list[str] = []
            market_gap: str | None = None
            reference_price_range: str | None = None
            confidence_basis = [
                f"本人商品共有 {signal['snapshot_count']} 个快照日，数据质量 {signal['data_quality']}"
            ]
            if benchmark:
                evidence_sources.append("高可见市场参考")
                market_evidence = [
                    f"匹配关键词：{benchmark.keyword}",
                    *benchmark.evidence[:3],
                ]
                confidence_basis.append(
                    f"市场参考 {benchmark.sample_days} 个样本日，置信度 {benchmark.confidence}"
                )
                if (
                    benchmark.price_low is not None
                    and benchmark.price_high is not None
                ):
                    reference_price_range = (
                        f"{self._market_price_label(benchmark.price_low)}–"
                        f"{self._market_price_label(benchmark.price_high)}"
                    )
            else:
                confidence_basis.append("未找到与该商品主题匹配的近 30 天市场样本")

            confidence = signal["data_quality"]
            if benchmark and signal["data_quality"] != "low":
                confidence = (
                    "high"
                    if signal["data_quality"] == "high"
                    and benchmark.confidence == "high"
                    else "medium"
                )
            if current:
                inquiry_rate = (
                    current.inquiry_count / current.browse_count * 100
                    if current.browse_count
                    else 0
                )
                current_price = (
                    float(current.price)
                    if current.price is not None
                    else _as_money(monitor.item.price)
                )
                missing_title_terms = (
                    [
                        term
                        for term in benchmark.common_title_terms
                        if not self._market_term_present(current.title, term)
                    ][:3]
                    if benchmark
                    else []
                )
                missing_description_terms = (
                    [
                        term
                        for term in benchmark.common_title_terms
                        if not self._market_term_present(
                            str(monitor.item.description or ""), term
                        )
                    ][:3]
                    if benchmark
                    else []
                )
                price_outlier = False
                price_direction = ""
                if (
                    benchmark
                    and benchmark.confidence != "low"
                    and benchmark.priced_result_count >= 3
                    and current_price is not None
                    and benchmark.price_low is not None
                    and benchmark.price_high is not None
                ):
                    if current_price < benchmark.price_low * 0.8:
                        price_outlier = True
                        price_direction = "明显低于"
                    elif current_price > benchmark.price_high * 1.2:
                        price_outlier = True
                        price_direction = "明显高于"
                if price_outlier:
                    market_gap = (
                        f"当前展示价 {self._market_price_label(current_price)}{price_direction}"
                        f"匹配市场中间区间 {reference_price_range}"
                    )
                elif missing_title_terms:
                    market_gap = (
                        f"当前标题未覆盖高位参考中反复出现的通用词："
                        f"{'、'.join(missing_title_terms)}"
                    )
                elif benchmark:
                    market_gap = "当前标题与匹配市场的通用能力词基本一致，差异化应转向交付边界"

                if current.browse_count < 30:
                    variable = "cover"
                    reason = "内部浏览基线偏低，先单独验证首图吸引力"
                    suggested_change = (
                        "只更换首图，突出最终交付物或修改前后对比；标题、描述和价格保持不变"
                    )
                elif current.inquiry_count >= 3 and current.converted_project_count == 0:
                    if price_outlier:
                        variable = "price"
                        reason = "有咨询无成交，且当前展示价明显偏离匹配市场区间"
                        suggested_change = (
                            f"单独测试展示价或起步价说明，参考 {reference_price_range}；"
                            "同时明确最终金额仍按需求范围与工时确认"
                        )
                    else:
                        variable = "description"
                        reason = "已有咨询但尚未成交，价格暂无明确偏离证据"
                        suggested_change = (
                            "先补充服务范围、报价组成、不包含内容与验收方式，价格保持不变"
                        )
                elif current.browse_count >= 80 and inquiry_rate < 1:
                    variable = "description"
                    reason = "内部浏览存在但咨询率偏低，优先验证详情是否说清价值"
                    if missing_description_terms:
                        suggested_change = (
                            f"在描述中补充{'、'.join(missing_description_terms)}对应的技术范围、"
                            "交付物和验收标准；其他变量保持不变"
                        )
                    else:
                        suggested_change = (
                            "把工作范围、交付物、周期、验收标准和不包含内容改成可扫描清单"
                        )
                elif (
                    benchmark
                    and benchmark.confidence in {"medium", "high"}
                    and missing_title_terms
                ):
                    variable = "title"
                    reason = "内部基线可比较，且标题与匹配市场的稳定能力词存在缺口"
                    suggested_change = (
                        f"只调整标题，测试加入{'、'.join(missing_title_terms)}中的 1–2 个通用词；"
                        "不要复制其他商品完整标题"
                    )
                else:
                    variable = "title"
                    reason = "内部基线可比较，暂未发现价格或描述的明确异常"
                    suggested_change = (
                        "只测试一个更明确的标题定位，保留原价格、首图和描述作为对照"
                    )
            suggestions.append(
                ProductModificationSuggestionView(
                    external_id=monitor.item.external_id,
                    title=current.title if current else monitor.item.title,
                    variable=variable,
                    reason=reason,
                    suggested_change=suggested_change,
                    confidence=confidence,
                    blocked_reason=blocked_reason,
                    benchmark_keyword=benchmark.keyword if benchmark else None,
                    market_evidence=market_evidence,
                    market_gap=market_gap,
                    reference_price_range=reference_price_range,
                    confidence_basis=confidence_basis,
                    evidence_sources=evidence_sources,
                )
            )
        return suggestions

    def create_modification_experiment(
        self,
        external_id: str,
        *,
        variable: str,
        before_value: str,
        after_value: str,
        observation_days: int,
    ) -> ProductModificationExperimentView:
        before_clean = before_value.strip()
        after_clean = after_value.strip()
        if before_clean == after_clean:
            raise ProductMarketConflict("修改前后内容不能相同")
        with self.database.session() as session:
            item = session.scalar(select(Item).where(Item.external_id == external_id))
            if item is None:
                raise ProductRecordNotFound("商品不存在")
            monitor = session.scalar(
                select(ProductMonitor).where(ProductMonitor.item_id == item.id)
            )
            if monitor is None or monitor.ownership_status != "owned":
                raise ProductOwnershipRestricted("只有已确认属于你的商品可以建立修改实验")
            existing = session.scalar(
                select(ProductModificationExperiment).where(
                    ProductModificationExperiment.item_id == item.id,
                    ProductModificationExperiment.status == "observing",
                )
            )
            if existing:
                raise ProductMarketConflict("该商品已有一个修改实验正在观察")
            history = session.scalars(
                select(ProductDailySnapshot)
                .where(ProductDailySnapshot.item_id == item.id)
                .order_by(ProductDailySnapshot.snapshot_date.desc())
                .limit(30)
            ).all()
            signal = self._product_signal_state(session, monitor, list(history))
            now = self._now().astimezone(timezone.utc)
            if (
                signal["traffic_cooldown_until"]
                and signal["traffic_cooldown_until"] > now
            ):
                raise ProductMarketConflict("商品仍在曝光长尾观察期，暂不开始修改实验")
            current = history[0] if history else None
            baseline = {
                "snapshot_date": current.snapshot_date if current else None,
                "browse_count": current.browse_count if current else 0,
                "collect_count": current.collect_count if current else 0,
                "want_count": current.want_count if current else 0,
                "inquiry_count": current.inquiry_count if current else 0,
                "converted_project_count": current.converted_project_count if current else 0,
            }
            observation_until = now + timedelta(days=observation_days)
            experiment = ProductModificationExperiment(
                id=f"product-modification-{uuid4()}",
                item_id=item.id,
                variable=variable,
                before_value=before_clean,
                after_value=after_clean,
                baseline_json=json.dumps(baseline, ensure_ascii=False),
                started_at=now,
                observation_until=observation_until,
                status="observing",
                decision="pending",
                evidence_json=json.dumps(
                    [
                        "仅改变一个变量，其他标题、首图、描述和价格保持不变",
                        f"预计观察 {observation_days} 天，再结合浏览与咨询变化判断",
                    ],
                    ensure_ascii=False,
                ),
            )
            session.add(experiment)
            session.add(
                ProductActionLog(
                    id=f"product-action-{uuid4()}",
                    item_id=item.id,
                    action_type=variable,
                    status="completed",
                    note=f"单变量实验：{before_clean} → {after_clean}",
                    happened_at=now,
                    observation_until=observation_until,
                )
            )
            session.commit()
            result = self._experiment_view(experiment)
        self.event_hub.publish_nowait(
            {
                "type": "product_modification_updated",
                "experiment_id": result.id,
                "item_id": external_id,
            }
        )
        return result

    def update_modification_experiment(
        self, experiment_id: str, *, decision: str, note: str
    ) -> ProductModificationExperimentView:
        with self.database.session() as session:
            experiment = session.get(ProductModificationExperiment, experiment_id)
            if experiment is None:
                raise ProductRecordNotFound("修改实验不存在")
            if experiment.status != "observing":
                raise ProductMarketConflict("该实验已经结束")
            now = self._now().astimezone(timezone.utc)
            observation_until = self._utc(experiment.observation_until) or now
            if decision == "keep" and now < observation_until:
                raise ProductMarketConflict("观察期尚未结束；如需立即撤回请选择回退")
            baseline = _json_dict(experiment.baseline_json)
            current = session.scalar(
                select(ProductDailySnapshot)
                .where(ProductDailySnapshot.item_id == experiment.item_id)
                .order_by(ProductDailySnapshot.snapshot_date.desc())
                .limit(1)
            )
            result = {
                "snapshot_date": current.snapshot_date if current else None,
                "browse_delta": max(
                    0,
                    (current.browse_count if current else 0)
                    - int(baseline.get("browse_count") or 0),
                ),
                "inquiry_delta": max(
                    0,
                    (current.inquiry_count if current else 0)
                    - int(baseline.get("inquiry_count") or 0),
                ),
                "want_delta": max(
                    0,
                    (current.want_count if current else 0)
                    - int(baseline.get("want_count") or 0),
                ),
                "note": note.strip(),
            }
            evidence = [str(value) for value in self._json_list(experiment.evidence_json)]
            if note.strip():
                evidence.append(note.strip())
            experiment.result_json = json.dumps(result, ensure_ascii=False)
            experiment.decision = decision
            experiment.evidence_json = json.dumps(evidence, ensure_ascii=False)
            if decision == "continue":
                experiment.observation_until = max(now, observation_until) + timedelta(
                    days=3
                )
            else:
                experiment.status = "completed"
            session.commit()
            view = self._experiment_view(experiment)
        self.event_hub.publish_nowait(
            {
                "type": "product_modification_updated",
                "experiment_id": experiment_id,
                "decision": decision,
            }
        )
        return view

    def _recommendation_view(
        self, recommendation: ProductStrategyRecommendation, item: Item
    ) -> ProductRecommendationView:
        return ProductRecommendationView(
            id=recommendation.id,
            item_external_id=item.external_id,
            item_title=item.title,
            recommendation_date=recommendation.recommendation_date,
            strategy_code=recommendation.strategy_code,
            priority_score=recommendation.priority_score,
            attention=recommendation.attention,
            posture=recommendation.posture,
            title=recommendation.title,
            summary=recommendation.summary,
            evidence=list(json.loads(recommendation.evidence_json or "[]")),
            actions=list(json.loads(recommendation.actions_json or "[]")),
            confidence=recommendation.confidence,
            status=recommendation.status,
        )

    @staticmethod
    def _action_view(action: ProductActionLog) -> ProductActionView:
        return ProductActionView(
            id=action.id,
            action_type=action.action_type,
            status=action.status,
            note=action.note,
            cost=action.cost,
            happened_at=action.happened_at,
            observation_until=action.observation_until,
        )

    @staticmethod
    def _run_view(run: ProductCollectionRun) -> ProductCollectionRunView:
        return ProductCollectionRunView(
            id=run.id,
            run_date=run.run_date,
            trigger=run.trigger,
            status=run.status,
            monitored_count=run.monitored_count,
            collected_count=run.collected_count,
            failed_count=run.failed_count,
            detail=run.detail,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )

    def _product_view(self, session, item: Item, monitor: ProductMonitor) -> ProductView:
        history_desc = session.scalars(
            select(ProductDailySnapshot)
            .where(ProductDailySnapshot.item_id == item.id)
            .order_by(ProductDailySnapshot.snapshot_date.desc())
            .limit(30)
        ).all()
        current = history_desc[0] if history_desc else None
        previous = history_desc[1] if len(history_desc) > 1 else None
        recommendation = session.scalar(
            select(ProductStrategyRecommendation)
            .where(ProductStrategyRecommendation.item_id == item.id)
            .order_by(ProductStrategyRecommendation.recommendation_date.desc())
            .limit(1)
        )
        actions = session.scalars(
            select(ProductActionLog)
            .where(ProductActionLog.item_id == item.id)
            .order_by(ProductActionLog.happened_at.desc())
            .limit(10)
        ).all()
        browse = current.browse_count if current else 0
        raw_browse = current.raw_browse_count if current else 0
        excluded_collection_views = (
            current.collection_views_excluded if current else 0
        )
        inquiries = current.inquiry_count if current else 0
        converted = current.converted_project_count if current else 0
        signal = self._product_signal_state(session, monitor, list(history_desc))
        return ProductView(
            external_id=item.external_id,
            title=current.title if current else item.title,
            price=current.price if current else _as_money(item.price),
            status=current.status if current else "waiting",
            monitoring_enabled=monitor.enabled,
            monitor_source=monitor.source,
            ownership_status=monitor.ownership_status,
            ownership_source=monitor.ownership_source,
            last_attempt_at=monitor.last_attempt_at,
            last_collection_status=monitor.last_collection_status,
            last_error_code=monitor.last_error_code,
            last_error_detail=monitor.last_error_detail,
            last_collected_at=current.captured_at if current else None,
            browse_count=browse,
            raw_browse_count=raw_browse,
            collection_views_excluded=excluded_collection_views,
            collect_count=current.collect_count if current else 0,
            want_count=current.want_count if current else 0,
            sold_count=current.sold_count if current else 0,
            browse_delta=(
                max(0, current.browse_count - previous.browse_count)
                if current and previous
                else None
            ),
            inquiry_count=inquiries,
            inbound_message_count=current.inbound_message_count if current else 0,
            converted_project_count=converted,
            revenue_total=current.revenue_total if current else 0,
            profit_total=current.profit_total if current else 0,
            inquiry_rate=round(inquiries / browse * 100, 2) if browse else None,
            deal_rate=round(converted / inquiries * 100, 2) if inquiries else None,
            snapshot_count=signal["snapshot_count"],
            freshness_days=signal["freshness_days"],
            data_quality=signal["data_quality"],
            data_gaps=signal["data_gaps"],
            traffic_cooldown_until=signal["traffic_cooldown_until"],
            modification_observation_until=signal[
                "modification_observation_until"
            ],
            recent_windows=signal["recent_windows"],
            history=[
                ProductSnapshotView(
                    date=snapshot.snapshot_date,
                    source=snapshot.source,
                    browse_count=snapshot.browse_count,
                    raw_browse_count=snapshot.raw_browse_count,
                    collection_views_excluded=snapshot.collection_views_excluded,
                    collect_count=snapshot.collect_count,
                    want_count=snapshot.want_count,
                    sold_count=snapshot.sold_count,
                    inquiry_count=snapshot.inquiry_count,
                    converted_project_count=snapshot.converted_project_count,
                    revenue_total=snapshot.revenue_total,
                    profit_total=snapshot.profit_total,
                )
                for snapshot in reversed(history_desc)
            ],
            recommendation=(
                self._recommendation_view(recommendation, item)
                if recommendation
                else None
            ),
            actions=[self._action_view(action) for action in actions],
        )

    def product(self, external_id: str) -> ProductView:
        self.bootstrap_cached_state()
        with self.database.session() as session:
            item = session.scalar(select(Item).where(Item.external_id == external_id))
            if item is None:
                raise ProductRecordNotFound("商品不存在")
            monitor = session.scalar(
                select(ProductMonitor).where(ProductMonitor.item_id == item.id)
            )
            if monitor is None:
                raise ProductRecordNotFound("商品尚未加入监测")
            return self._product_view(session, item, monitor)

    def overview(self) -> ProductIntelligenceView:
        self.bootstrap_cached_state()
        with self.database.session() as session:
            monitors = session.scalars(
                select(ProductMonitor).order_by(ProductMonitor.enabled.desc(), ProductMonitor.id)
            ).all()
            all_products = [
                self._product_view(session, monitor.item, monitor)
                for monitor in monitors
            ]
            products = [
                product for product in all_products if product.ownership_status == "owned"
            ]
            candidates = [
                product for product in all_products if product.ownership_status != "owned"
            ]
            today = self._day_key()
            last_run = session.scalar(
                select(ProductCollectionRun)
                .order_by(ProductCollectionRun.run_date.desc())
                .limit(1)
            )
            attempt_rows = session.scalars(
                select(ProductCollectionAttempt)
                .order_by(
                    func.coalesce(
                        ProductCollectionAttempt.finished_at,
                        ProductCollectionAttempt.started_at,
                    ).desc(),
                    ProductCollectionAttempt.started_at.desc(),
                )
                .limit(40)
            ).all()
            attempt_views = [
                self._attempt_view(session, attempt) for attempt in attempt_rows
            ]
            has_run_today = bool(last_run and last_run.run_date == today)
            recommendations = sorted(
                [
                    product.recommendation
                    for product in products
                    if product.monitoring_enabled
                    and product.recommendation
                    and product.recommendation.status in {"active", "in_progress"}
                ],
                key=lambda value: value.priority_score,
                reverse=True,
            )
            snapshot_days = int(
                session.scalar(
                    select(func.count(distinct(ProductDailySnapshot.snapshot_date)))
                    .join(
                        ProductMonitor,
                        ProductMonitor.item_id == ProductDailySnapshot.item_id,
                    )
                    .where(ProductMonitor.ownership_status == "owned")
                )
                or 0
            )
            active_projects = self._active_project_count(session)
            inactive_statuses = {"sold", "off", "已卖出", "已下架", "deleted"}
            active_products = sum(
                1
                for product in products
                if product.monitoring_enabled and product.status.lower() not in inactive_statuses
            )
            collection = ProductCollectionStatusView(
                configured=self.settings.xianyu_configured,
                schedule=(
                    f"自动采集每天 {self.settings.product_collection_hour:02d}:"
                    f"{self.settings.product_collection_minute:02d}（北京时间）；"
                    "也可手动采集全部或指定商品"
                ),
                timezone=self.settings.product_collection_timezone,
                can_collect_today=(
                    self.settings.product_collection_enabled
                    and self.settings.xianyu_configured
                    and not has_run_today
                ),
                next_collection_at=self._next_collection_at(has_run_today),
                last_run=self._run_view(last_run) if last_run else None,
                latest_attempt=attempt_views[0] if attempt_views else None,
                attempts=attempt_views,
                safety_note="自动采集每天一次；手动采集由你显式触发。两者都只读取指标，不会修改、发布、下架商品或产生推广费用。",
            )
            summary = ProductPortfolioSummary(
                monitored_products=sum(1 for product in products if product.monitoring_enabled),
                active_products=active_products,
                pending_products=sum(
                    1 for product in candidates if product.ownership_status == "pending"
                ),
                excluded_products=sum(
                    1 for product in candidates if product.ownership_status == "excluded"
                ),
                needs_attention=sum(
                    1 for recommendation in recommendations if recommendation.attention in {"high", "medium"}
                ),
                traffic_candidates=sum(
                    1 for recommendation in recommendations if recommendation.strategy_code == "scale_candidate"
                ),
                snapshot_days=snapshot_days,
                active_projects=active_projects,
                delivery_capacity=self.settings.product_delivery_capacity,
            )
            publish_timing = self._publish_timing(session)
            demand_opportunities = self._demand_opportunities(session)
            plan = self._ensure_operating_plan(session)
            market_plan = self._ensure_market_keyword_plan(session)
            session.commit()
            operating_plan = self._operating_plan_view(session, plan)
            traffic_batches = self._recent_traffic_batches(session)
            traffic_summary = self._traffic_summary(session, traffic_batches)
            exposure_analytics = self._exposure_analytics(session)
            market_reference = self._market_reference_view(session, market_plan)
            launch_recommendation = self._launch_recommendation(
                session, market_reference
            )
            launch_plans = [
                self._launch_plan_view(value)
                for value in session.scalars(
                    select(ProductLaunchPlan)
                    .order_by(ProductLaunchPlan.created_at.desc())
                    .limit(20)
                ).all()
            ]
            modification_suggestions = self._modification_suggestions(session)
            modification_experiments = [
                self._experiment_view(value)
                for value in session.scalars(
                    select(ProductModificationExperiment)
                    .order_by(ProductModificationExperiment.created_at.desc())
                    .limit(30)
                ).all()
            ]
        return ProductIntelligenceView(
            collection=collection,
            summary=summary,
            products=products,
            candidates=candidates,
            recommendations=recommendations,
            publish_timing=publish_timing,
            demand_opportunities=demand_opportunities,
            operating_plan=operating_plan,
            traffic_batches=traffic_batches,
            traffic_summary=traffic_summary,
            exposure_analytics=exposure_analytics,
            market_reference=market_reference,
            launch_recommendation=launch_recommendation,
            launch_plans=launch_plans,
            modification_suggestions=modification_suggestions,
            modification_experiments=modification_experiments,
        )
