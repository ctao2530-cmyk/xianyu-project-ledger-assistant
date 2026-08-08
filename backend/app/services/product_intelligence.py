from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, distinct, func, or_, select
from sqlalchemy.exc import IntegrityError

from ..adapters.base import (
    AdapterDisconnectedError,
    AdapterError,
    ItemInfo,
    LoginExpiredError,
)
from ..config import Settings
from ..database import Database
from ..models import (
    BusinessExpense,
    BusinessProject,
    Conversation,
    Item,
    Message,
    PaymentNode,
    ProductActionLog,
    ProductCollectionRun,
    ProductDailySnapshot,
    ProductMonitor,
    ProductStrategyRecommendation,
    utcnow,
)
from ..product_schemas import (
    DemandOpportunityView,
    ProductActionView,
    ProductCollectionRunView,
    ProductCollectionStatusView,
    ProductIntelligenceView,
    ProductPortfolioSummary,
    ProductRecommendationView,
    ProductSnapshotView,
    ProductView,
    PublishTimingView,
    PublishWindowView,
)
from .event_hub import EventHub


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
    ) -> None:
        self.database = database
        self.adapter = adapter
        self.settings = settings
        self.event_hub = event_hub
        self.timezone = ZoneInfo(settings.product_collection_timezone)
        self._task: asyncio.Task | None = None
        self._collection_lock = asyncio.Lock()

    def _now(self) -> datetime:
        return datetime.now(self.timezone)

    def _day_key(self, value: datetime | None = None) -> str:
        current = value or self._now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc).astimezone(self.timezone)
        else:
            current = current.astimezone(self.timezone)
        return current.date().isoformat()

    async def start(self) -> None:
        self.bootstrap_cached_state()
        if self.settings.product_collection_enabled and self._task is None:
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
        return ProductDailySnapshot(
            item_id=item.id,
            snapshot_date=snapshot_date,
            source=source,
            title=str(raw.get("title") or item.title or "未知商品"),
            price=price,
            status=str(status_value),
            published_at=str(raw.get("gmtCreate") or raw.get("GMT_CREATE_DATE_KEY") or ""),
            browse_count=_as_count(raw.get("browseCnt")),
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
        fresh = self._snapshot_from_raw(
            item,
            raw,
            snapshot_date,
            source=source,
            metrics=metrics,
        )
        existing = session.scalar(
            select(ProductDailySnapshot).where(
                ProductDailySnapshot.item_id == item.id,
                ProductDailySnapshot.snapshot_date == snapshot_date,
            )
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

            collected = 0
            failed = 0
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
                    continue
                try:
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
                            if monitor.source == "manual":
                                monitor.enabled = True
                            monitor.last_collection_status = "success"
                            self._upsert_snapshot(
                                session,
                                item,
                                info.raw,
                                run_date,
                                source="remote_daily",
                            )
                        elif ownership_status == "excluded":
                            monitor.enabled = False
                            monitor.last_collection_status = "excluded"
                        else:
                            monitor.enabled = False
                            monitor.last_collection_status = "pending"
                        session.commit()
                    collected += 1
                except LoginExpiredError as exc:
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
                run.detail = (
                    f"已读取 {collected} 个商品，失败 {failed} 个；没有执行修改、发布或投流"
                    if monitor_item_ids
                    else "暂无启用监测的商品"
                )
                if failure_notes:
                    run.detail += f"（{failure_notes[0]}）"
                run.finished_at = utcnow()
                self._refresh_recommendations(session)
                session.commit()
                result = self._run_view(run)
            self.event_hub.publish_nowait(
                {
                    "type": "product_intelligence_updated",
                    "run_date": run_date,
                    "status": result.status,
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

    def _strategy(
        self,
        current: ProductDailySnapshot,
        previous: ProductDailySnapshot | None,
        *,
        active_projects: int,
        capacity: int,
        history_count: int,
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
        confidence = (
            "high"
            if history_count >= 7 and current.inquiry_count >= 5
            else "medium"
            if history_count >= 2
            else "low"
        )
        evidence = [
            f"累计浏览 {current.browse_count}，想要 {current.want_count}，收藏 {current.collect_count}",
            f"关联 {current.inquiry_count} 个咨询，形成 {current.converted_project_count} 个项目",
        ]
        if browse_delta is not None:
            evidence.insert(0, f"较上次采集新增 {browse_delta} 次浏览")
        if current.revenue_total or current.profit_total:
            evidence.append(
                f"关联收入 ¥{current.revenue_total:,.0f}，实际利润 ¥{current.profit_total:,.0f}"
            )

        if active_projects >= capacity and current.converted_project_count > 0:
            return {
                "strategy_code": "capacity_guard",
                "priority_score": 96,
                "attention": "high",
                "posture": "delivery_guard",
                "title": "先保护交付能力，暂缓新增流量",
                "summary": f"当前进行中项目已达到 {active_projects}/{capacity}，继续放大咨询可能挤压交付质量。",
                "evidence": evidence + [f"进行中项目 {active_projects} 个，容量上限 {capacity} 个"],
                "actions": ["保持商品在线但暂停新增推广", "优先完成当前项目并检查回款", "释放交付容量后再重新评估"],
                "confidence": confidence,
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
                "summary": "这件商品已经产生真实项目和正利润，适合在人工确认后进行小范围曝光实验。",
                "evidence": evidence,
                "actions": ["先记录当前数据作为实验基线", "人工设置可承受的小预算并观察 48–72 小时", "对比新增咨询、成交和利润，不只看浏览量"],
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
            and browse_delta <= max(2, round(previous.browse_count * 0.01))
            and current.inquiry_count == previous.inquiry_count
        ):
            return {
                "strategy_code": "low_exposure",
                "priority_score": 70,
                "attention": "medium",
                "posture": "visibility_risk",
                "title": "流量与咨询停滞，适合安排一次人工优化",
                "summary": "连续采集间隔内浏览和咨询几乎没有增长，可以优先检查标题、首图、类目和价格带。",
                "evidence": evidence,
                "actions": ["一次只调整一个关键变量", "优先从标题关键词或首图中选择一项修改", "记录修改动作并观察 7 天"],
                "confidence": confidence,
            }
        if previous is None:
            return {
                "strategy_code": "baseline",
                "priority_score": 35,
                "attention": "low",
                "posture": "observing",
                "title": "已建立经营基线，继续观察趋势",
                "summary": "目前只有一个数据点，系统不会用单次累计值做过度判断。",
                "evidence": evidence,
                "actions": ["保持商品稳定一个完整采集周期", "不要同时修改标题、价格和描述", "积累至少 2 个快照后查看变化"],
                "confidence": "low",
            }
        return {
            "strategy_code": "healthy",
            "priority_score": 28,
            "attention": "low",
            "posture": "stable",
            "title": "当前表现稳定，暂不需要频繁修改",
            "summary": "没有发现明显的流量停滞、咨询断层或成交问题，保持稳定更有利于观察。",
            "evidence": evidence,
            "actions": ["继续按日观察", "有明显变化时再调整", "避免为了刷新而频繁修改商品"],
            "confidence": confidence,
        }

    def _refresh_recommendations(self, session) -> None:
        active_projects = int(
            session.scalar(
                select(func.count(BusinessProject.id)).where(
                    BusinessProject.status.in_(("pending", "in_progress", "overdue"))
                )
            )
            or 0
        )
        capacity = self.settings.product_delivery_capacity
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
            result = self._strategy(
                current,
                previous,
                active_projects=active_projects,
                capacity=capacity,
                history_count=len(history),
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
        timestamps = session.scalars(
            select(Message.received_at).where(
                Message.direction == "inbound",
                Message.received_at >= cutoff,
            )
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
                f"过去 90 天咨询最集中在{best.weekday} {best.time_range}；"
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
        inquiries = current.inquiry_count if current else 0
        converted = current.converted_project_count if current else 0
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
            history=[
                ProductSnapshotView(
                    date=snapshot.snapshot_date,
                    source=snapshot.source,
                    browse_count=snapshot.browse_count,
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
            active_projects = int(
                session.scalar(
                    select(func.count(BusinessProject.id)).where(
                        BusinessProject.status.in_(("pending", "in_progress", "overdue"))
                    )
                )
                or 0
            )
            inactive_statuses = {"sold", "off", "已卖出", "已下架", "deleted"}
            active_products = sum(
                1
                for product in products
                if product.monitoring_enabled and product.status.lower() not in inactive_statuses
            )
            collection = ProductCollectionStatusView(
                configured=self.settings.xianyu_configured,
                schedule=(
                    f"每天 {self.settings.product_collection_hour:02d}:"
                    f"{self.settings.product_collection_minute:02d}（北京时间），"
                    "每个北京时间自然日最多一次"
                ),
                timezone=self.settings.product_collection_timezone,
                can_collect_today=(
                    self.settings.product_collection_enabled
                    and self.settings.xianyu_configured
                    and not has_run_today
                ),
                next_collection_at=self._next_collection_at(has_run_today),
                last_run=self._run_view(last_run) if last_run else None,
                safety_note="只读取商品指标并生成建议，不会修改、发布、下架商品或产生推广费用。",
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
        return ProductIntelligenceView(
            collection=collection,
            summary=summary,
            products=products,
            candidates=candidates,
            recommendations=recommendations,
            publish_timing=publish_timing,
            demand_opportunities=demand_opportunities,
        )
