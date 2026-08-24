from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, func, select

from ..config import Settings
from ..database import Database
from ..models import (
    BusinessExpense,
    BusinessProject,
    Conversation,
    Item,
    Message,
    PaymentNode,
    ProductMonitor,
    ProductTrafficBatch,
    ProductTrafficBatchItem,
    ProductTrafficBudgetDecision,
    ProductTrafficCommercialAttribution,
    ProductTrafficExperiment,
    ProductTrafficExperimentCell,
    ProductTrafficGrowthRequest,
    ProductTrafficScaleCohort,
    ProductTrafficScaleCohortBatch,
    ProjectSettlementIssueRecord,
    utcnow,
)
from ..traffic_growth_schemas import (
    TrafficBudgetDecisionView,
    TrafficCommercialAttributionView,
    TrafficExperimentCellView,
    TrafficExperimentPreviewView,
    TrafficExperimentView,
    TrafficGrowthMetricsView,
    TrafficGrowthOverviewView,
    TrafficGrowthProductView,
    TrafficScaleCohortView,
    TrafficTimeWindowResultView,
)


GROWTH_RULES_VERSION = "growth-v1"
DEFAULT_WINDOWS = ("12", "16", "20")
STAGE_ORDER = ("T0", "S1", "S2", "S3")
STAGE_WEEKLY_BUDGET = {"T0": 24.0, "S1": 24.0, "S2": 36.0, "S3": 48.0}
STAGE_BATCHES_PER_WEEK = {"T0": 2, "S1": 3, "S2": 5, "S3": 7}


class TrafficGrowthConflict(RuntimeError):
    pass


class TrafficGrowthNotFound(RuntimeError):
    pass


class TrafficGrowthService:
    """Explainable, manual-only exposure experiment and budget rules."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        product_intelligence=None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.product_intelligence = product_intelligence
        self.local_tz = ZoneInfo(settings.product_collection_timezone)

    def _now(self) -> datetime:
        if self.product_intelligence is not None:
            return self.product_intelligence._now()
        return utcnow()

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _json(value: str, fallback):
        try:
            parsed = json.loads(value or "")
        except (TypeError, ValueError):
            return fallback
        return parsed

    @staticmethod
    def _same_time(left: datetime | None, right: datetime | None) -> bool:
        if left is None or right is None:
            return left is right
        left_utc = TrafficGrowthService._utc(left)
        right_utc = TrafficGrowthService._utc(right)
        return bool(left_utc and right_utc and abs((left_utc - right_utc).total_seconds()) < 0.001)

    def _request_replay(
        self,
        session,
        *,
        request_id: str,
        operation: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        stored = session.get(ProductTrafficGrowthRequest, request_id)
        if stored is None:
            return None
        payload_hash = self._payload_hash(payload)
        if stored.operation != operation or stored.payload_hash != payload_hash:
            raise TrafficGrowthConflict("相同 request_id 已用于不同的增长实验操作")
        return self._json(stored.result_json, {})

    def _store_request(
        self,
        session,
        *,
        request_id: str,
        operation: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        session.add(
            ProductTrafficGrowthRequest(
                request_id=request_id,
                operation=operation,
                payload_hash=self._payload_hash(payload),
                result_json=json.dumps(result, ensure_ascii=False, sort_keys=True),
                created_at=self._now().astimezone(timezone.utc),
            )
        )

    def _owned_item(self, session, external_id: str) -> Item:
        item = session.scalar(
            select(Item)
            .join(ProductMonitor, ProductMonitor.item_id == Item.id)
            .where(
                Item.external_id == external_id,
                ProductMonitor.ownership_status == "owned",
                ProductMonitor.enabled.is_(True),
            )
            .limit(1)
        )
        if item is None:
            raise TrafficGrowthNotFound("只能为当前账号已确认且启用监测的商品建立实验")
        return item

    @staticmethod
    def _project_profit(session, project_id: str) -> float:
        confirmed = float(
            session.scalar(
                select(func.coalesce(func.sum(PaymentNode.amount), 0)).where(
                    PaymentNode.project_id == project_id,
                    PaymentNode.status.in_(("confirmed", "refunded")),
                )
            )
            or 0
        )
        payment_refunds = float(
            session.scalar(
                select(func.coalesce(func.sum(PaymentNode.amount), 0)).where(
                    PaymentNode.project_id == project_id,
                    PaymentNode.status == "refunded",
                )
            )
            or 0
        )
        issue_refunds = float(
            session.scalar(
                select(func.coalesce(func.sum(ProjectSettlementIssueRecord.refund_amount), 0)).where(
                    ProjectSettlementIssueRecord.project_id == project_id
                )
            )
            or 0
        )
        expenses = float(
            session.scalar(
                select(func.coalesce(func.sum(BusinessExpense.amount), 0)).where(
                    BusinessExpense.project_id == project_id
                )
            )
            or 0
        )
        return round(confirmed - payment_refunds - issue_refunds - expenses, 2)

    def _product_view(self, session, item: Item) -> TrafficGrowthProductView:
        projects = session.scalars(
            select(BusinessProject).where(BusinessProject.item_id == item.id)
        ).all()
        return TrafficGrowthProductView(
            external_id=item.external_id,
            title=item.title,
            historical_project_count=len(projects),
            historical_realized_profit=round(
                sum(self._project_profit(session, project.id) for project in projects), 2
            ),
            historical_profit_is_attributed=False,
        )

    def _last_started_for_item(self, session, item_id: int) -> datetime | None:
        return self._utc(
            session.scalar(
                select(func.max(ProductTrafficBatch.started_at))
                .join(
                    ProductTrafficBatchItem,
                    ProductTrafficBatchItem.batch_id == ProductTrafficBatch.id,
                )
                .where(
                    ProductTrafficBatchItem.item_id == item_id,
                    ProductTrafficBatch.status != "cancelled",
                )
            )
        )

    def _next_window_at(self, earliest: datetime, bucket: str) -> datetime:
        local = self._utc(earliest).astimezone(self.local_tz)
        candidate = local.replace(hour=int(bucket), minute=0, second=0, microsecond=0)
        if candidate < local:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    def _schedule_rows(
        self,
        session,
        *,
        item_id: int,
        windows: list[str],
        start_after: datetime | None = None,
        phase: str = "exploration",
    ) -> list[dict[str, Any]]:
        now = self._now().astimezone(timezone.utc)
        last_started = self._last_started_for_item(session, item_id)
        cursor = max(
            [
                value
                for value in (
                    now,
                    self._utc(start_after),
                    last_started + timedelta(hours=self.settings.product_traffic_cooldown_hours)
                    if last_started
                    else None,
                )
                if value is not None
            ]
        )
        order = (
            [windows[2], windows[0], windows[1], windows[1], windows[0], windows[2]]
            if phase == "exploration"
            else windows
        )
        repeats: defaultdict[str, int] = defaultdict(int)
        rows: list[dict[str, Any]] = []
        previous: datetime | None = None
        for bucket in order:
            if previous is not None:
                cursor = max(
                    cursor,
                    previous + timedelta(hours=self.settings.product_traffic_cooldown_hours),
                )
            scheduled_for = self._next_window_at(cursor, bucket)
            repeats[bucket] += 1
            rows.append(
                {
                    "phase": phase,
                    "window_bucket": bucket,
                    "repeat_index": repeats[bucket],
                    "scheduled_for": scheduled_for,
                }
            )
            previous = scheduled_for
        return rows

    @staticmethod
    def _time_range(bucket: str) -> str:
        hour = int(bucket)
        return f"{hour:02d}:00–{hour + 1:02d}:59"

    def preview_experiment(
        self,
        *,
        item_external_id: str,
        target_windows: list[str],
        baseline_weekly_budget: float,
        hard_weekly_cap: float,
    ) -> TrafficExperimentPreviewView:
        with self.database.session() as session:
            item = self._owned_item(session, item_external_id)
            active = session.scalar(
                select(ProductTrafficExperiment.id).where(
                    ProductTrafficExperiment.item_id == item.id,
                    ProductTrafficExperiment.status.in_(("active", "paused")),
                )
            )
            if active:
                raise TrafficGrowthConflict("该商品已经存在进行中的增长实验")
            rows = self._schedule_rows(
                session,
                item_id=item.id,
                windows=target_windows,
            )
            schedule = [
                TrafficExperimentCellView(
                    id=f"preview-{index + 1}",
                    phase=row["phase"],
                    window_bucket=row["window_bucket"],
                    time_range=self._time_range(row["window_bucket"]),
                    repeat_index=row["repeat_index"],
                    status="pending",
                    scheduled_for=row["scheduled_for"],
                    batch_id=None,
                    actual_bucket=None,
                    exclusion_reason=None,
                )
                for index, row in enumerate(rows)
            ]
            product = self._product_view(session, item)
        return TrafficExperimentPreviewView(
            product=product,
            target_windows=target_windows,
            schedule=schedule,
            baseline_weekly_budget=round(baseline_weekly_budget, 2),
            hard_weekly_cap=round(hard_weekly_cap, 2),
            expected_batch_count=8,
            expected_minimum_days=24,
            estimated_cost=round(8 * self.settings.product_traffic_batch_cost, 2),
            warnings=[
                "历史项目利润仅用于选择实验候选，不自动视为曝光收益",
                "时段实验期间同一商品至少间隔 72 小时",
                "实验只生成计划和记录入口，不会购买闲鱼曝光",
            ],
            preserves=["历史曝光批次", "商品经营数据", "项目与回款", "今日已执行计划"],
        )

    def create_experiment(
        self,
        *,
        request_id: str,
        item_external_id: str,
        target_windows: list[str],
        baseline_weekly_budget: float,
        hard_weekly_cap: float,
    ) -> TrafficExperimentView:
        payload = {
            "item_external_id": item_external_id,
            "target_windows": target_windows,
            "baseline_weekly_budget": round(baseline_weekly_budget, 2),
            "hard_weekly_cap": round(hard_weekly_cap, 2),
        }
        with self.database.session() as session:
            replay = self._request_replay(
                session,
                request_id=request_id,
                operation="create_experiment",
                payload=payload,
            )
            if replay:
                experiment_id = str(replay.get("experiment_id") or "")
                if experiment_id:
                    return self.experiment(experiment_id)
            item = self._owned_item(session, item_external_id)
            active = session.scalar(
                select(ProductTrafficExperiment.id).where(
                    ProductTrafficExperiment.item_id == item.id,
                    ProductTrafficExperiment.status.in_(("active", "paused")),
                )
            )
            if active:
                raise TrafficGrowthConflict("该商品已经存在进行中的增长实验")
            now = self._now().astimezone(timezone.utc)
            experiment = ProductTrafficExperiment(
                id=f"traffic-experiment-{uuid4()}",
                request_id=request_id,
                item_id=item.id,
                mode="time_test",
                status="active",
                phase="exploration",
                timezone=str(self.local_tz),
                target_windows_json=json.dumps(target_windows),
                baseline_weekly_budget=round(baseline_weekly_budget, 2),
                current_weekly_budget=round(baseline_weekly_budget, 2),
                hard_weekly_cap=round(hard_weekly_cap, 2),
                base_batch_cost=round(self.settings.product_traffic_batch_cost, 2),
                started_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(experiment)
            session.flush()
            rows = self._schedule_rows(
                session,
                item_id=item.id,
                windows=target_windows,
            )
            for row in rows:
                session.add(
                    ProductTrafficExperimentCell(
                        id=f"traffic-experiment-cell-{uuid4()}",
                        experiment_id=experiment.id,
                        phase=row["phase"],
                        window_bucket=row["window_bucket"],
                        repeat_index=row["repeat_index"],
                        status="pending",
                        scheduled_for=row["scheduled_for"],
                        created_at=now,
                        updated_at=now,
                    )
                )
            self._store_request(
                session,
                request_id=request_id,
                operation="create_experiment",
                payload=payload,
                result={"experiment_id": experiment.id},
            )
            session.commit()
            experiment_id = experiment.id
        return self.experiment(experiment_id)

    def _raw_batch_is_h72_eligible(self, session, batch: ProductTrafficBatch) -> bool:
        if self.product_intelligence is not None:
            view = self.product_intelligence._traffic_batch_view(
                session, batch, include_replan=False
            )
            return bool(view.analysis_eligible and view.observation_checkpoint == "h72")
        item_count = int(
            session.scalar(
                select(func.count(ProductTrafficBatchItem.id)).where(
                    ProductTrafficBatchItem.batch_id == batch.id
                )
            )
            or 0
        )
        from ..models import ProductTrafficCheckpoint

        h72_count = int(
            session.scalar(
                select(func.count(distinct(ProductTrafficCheckpoint.item_id))).where(
                    ProductTrafficCheckpoint.batch_id == batch.id,
                    ProductTrafficCheckpoint.checkpoint == "h72",
                )
            )
            or 0
        )
        baselines = session.scalars(
            select(ProductTrafficBatchItem.baseline_source).where(
                ProductTrafficBatchItem.batch_id == batch.id
            )
        ).all()
        return bool(
            item_count
            and h72_count >= item_count
            and set(baselines).issubset({"remote_refresh", "manual"})
            and batch.status != "invalidated"
            and batch.attribution_status == "clean"
            and batch.recording_mode == "standard"
        )

    def _batch_metrics(self, session, batch: ProductTrafficBatch, item_id: int) -> tuple[int, int]:
        if self.product_intelligence is not None:
            view = self.product_intelligence._traffic_batch_view(
                session, batch, include_replan=False
            )
            external_id = session.scalar(
                select(Item.external_id).where(Item.id == item_id)
            )
            product = next(
                (
                    value
                    for value in view.products
                    if value.external_id == external_id
                ),
                None,
            )
            return (
                int(product.browse_delta if product else 0),
                int(product.inquiry_delta if product else 0),
            )
        from ..models import ProductTrafficCheckpoint

        item = session.scalar(
            select(ProductTrafficBatchItem).where(
                ProductTrafficBatchItem.batch_id == batch.id,
                ProductTrafficBatchItem.item_id == item_id,
            )
        )
        checkpoint = session.scalar(
            select(ProductTrafficCheckpoint).where(
                ProductTrafficCheckpoint.batch_id == batch.id,
                ProductTrafficCheckpoint.item_id == item_id,
                ProductTrafficCheckpoint.checkpoint == "h72",
            )
        )
        if item is None or checkpoint is None:
            return 0, 0
        return (
            max(0, checkpoint.browse_count - item.baseline_browse_count),
            max(0, checkpoint.inquiry_count - item.baseline_inquiry_count),
        )

    def _cell_view(
        self,
        session,
        experiment: ProductTrafficExperiment,
        cell: ProductTrafficExperimentCell,
    ) -> TrafficExperimentCellView:
        status = cell.status
        actual_bucket = cell.actual_bucket
        browse_delta: int | None = None
        inquiry_delta: int | None = None
        eligible = False
        if cell.batch_id:
            batch = session.get(ProductTrafficBatch, cell.batch_id)
            if batch is None or batch.status == "cancelled":
                status = "excluded"
            elif batch.started_at:
                local = self._utc(batch.started_at).astimezone(self.local_tz)
                actual_bucket = f"{(local.hour // 2) * 2:02d}"
                if actual_bucket != cell.window_bucket:
                    status = "misbucketed"
                elif self._raw_batch_is_h72_eligible(session, batch):
                    status = "completed"
                    eligible = True
                    browse_delta, inquiry_delta = self._batch_metrics(
                        session, batch, experiment.item_id
                    )
                elif batch.status == "invalidated" or batch.attribution_status != "clean":
                    status = "excluded"
                else:
                    status = "observing"
            else:
                status = "bound"
        return TrafficExperimentCellView(
            id=cell.id,
            phase=cell.phase,
            window_bucket=cell.window_bucket,
            time_range=self._time_range(cell.window_bucket),
            repeat_index=cell.repeat_index,
            status=status,
            scheduled_for=self._utc(cell.scheduled_for),
            batch_id=cell.batch_id,
            actual_bucket=actual_bucket,
            exclusion_reason=cell.exclusion_reason,
            browse_delta=browse_delta,
            inquiry_delta=inquiry_delta,
            analysis_eligible=eligible,
        )

    def _window_results(
        self,
        cells: list[TrafficExperimentCellView],
        windows: list[str],
    ) -> tuple[list[TrafficTimeWindowResultView], str | None, str | None]:
        grouped: dict[str, list[TrafficExperimentCellView]] = defaultdict(list)
        exploration: dict[str, list[TrafficExperimentCellView]] = defaultdict(list)
        confirmation = []
        for cell in cells:
            if cell.analysis_eligible and cell.status == "completed":
                grouped[cell.window_bucket].append(cell)
                if cell.phase == "exploration":
                    exploration[cell.window_bucket].append(cell)
                elif cell.phase == "confirmation":
                    confirmation.append(cell)

        def ordered(source: dict[str, list[TrafficExperimentCellView]]):
            return sorted(
                windows,
                key=lambda bucket: (
                    -sum(value.inquiry_delta or 0 for value in source.get(bucket, []))
                    / max(1, len(source.get(bucket, []))),
                    -sum(value.browse_delta or 0 for value in source.get(bucket, []))
                    / max(1, len(source.get(bucket, []))),
                    bucket,
                ),
            )

        provisional = None
        exploration_order = ordered(exploration)
        if all(len(exploration.get(bucket, [])) >= 2 for bucket in windows):
            top, runner = exploration_order[:2]
            top_rows = exploration[top]
            runner_rows = exploration[runner]
            top_inquiries = sum(value.inquiry_delta or 0 for value in top_rows)
            top_inquiry_avg = top_inquiries / len(top_rows)
            runner_inquiry_avg = sum(value.inquiry_delta or 0 for value in runner_rows) / len(runner_rows)
            top_browse_avg = sum(value.browse_delta or 0 for value in top_rows) / len(top_rows)
            runner_browse_avg = sum(value.browse_delta or 0 for value in runner_rows) / len(runner_rows)
            if (
                top_inquiries >= 2
                and top_inquiry_avg >= runner_inquiry_avg + 0.5
                and (runner_browse_avg <= 0 or top_browse_avg >= runner_browse_avg * 0.7)
            ):
                provisional = top

        confirmed = None
        if provisional and len(confirmation) >= 2:
            confirmation_windows = {value.window_bucket for value in confirmation}
            if len(confirmation_windows) == 2:
                all_order = ordered(grouped)
                top, runner = all_order[:2]
                top_rows = grouped[top]
                runner_rows = grouped[runner]
                top_inquiries = sum(value.inquiry_delta or 0 for value in top_rows)
                runner_inquiries = sum(value.inquiry_delta or 0 for value in runner_rows)
                top_avg = top_inquiries / max(1, len(top_rows))
                runner_avg = runner_inquiries / max(1, len(runner_rows))
                top_browse = sum(value.browse_delta or 0 for value in top_rows) / max(1, len(top_rows))
                runner_browse = sum(value.browse_delta or 0 for value in runner_rows) / max(1, len(runner_rows))
                if (
                    top == provisional
                    and top_inquiries >= 2
                    and top_avg >= runner_avg + 0.5
                    and (runner_browse <= 0 or top_browse >= runner_browse * 0.7)
                ):
                    confirmed = top

        ranking = ordered(grouped)
        results = []
        for bucket in windows:
            rows = grouped.get(bucket, [])
            count = len(rows)
            browse = sum(value.browse_delta or 0 for value in rows)
            inquiries = sum(value.inquiry_delta or 0 for value in rows)
            results.append(
                TrafficTimeWindowResultView(
                    window_bucket=bucket,
                    time_range=self._time_range(bucket),
                    valid_batch_count=count,
                    browse_delta=browse,
                    inquiry_delta=inquiries,
                    average_browse_delta=round(browse / count, 2) if count else 0,
                    average_inquiry_delta=round(inquiries / count, 2) if count else 0,
                    rank=ranking.index(bucket) + 1 if count else None,
                    provisional_winner=bucket == provisional,
                    confirmed_winner=bucket == confirmed,
                )
            )
        results.sort(key=lambda value: (value.rank is None, value.rank or 99, value.window_bucket))
        return results, provisional, confirmed

    def _cohort_view(self, session, cohort: ProductTrafficScaleCohort) -> TrafficScaleCohortView:
        batches = session.scalars(
            select(ProductTrafficBatch)
            .join(
                ProductTrafficScaleCohortBatch,
                ProductTrafficScaleCohortBatch.batch_id == ProductTrafficBatch.id,
            )
            .where(ProductTrafficScaleCohortBatch.cohort_id == cohort.id)
            .order_by(ProductTrafficBatch.started_at, ProductTrafficBatch.created_at)
        ).all()
        started_values = [self._utc(value.started_at) for value in batches if value.started_at]
        started_at = self._utc(cohort.started_at) or (min(started_values) if started_values else None)
        ended_at = self._utc(cohort.ended_at)
        if started_at and ended_at is None:
            ended_at = started_at + timedelta(days=14)
        tail_ends = self._utc(cohort.tail_ends_at) or (
            ended_at + timedelta(days=7) if ended_at else None
        )
        followup_ends = self._utc(cohort.commercial_followup_ends_at) or (
            ended_at + timedelta(days=14) if ended_at else None
        )
        status = cohort.status
        now = self._now().astimezone(timezone.utc)
        if started_at and status == "planned":
            status = "active"
        if ended_at and now >= ended_at and status == "active":
            status = "observing"
        if followup_ends and now >= followup_ends and status in {"active", "observing"}:
            status = "closed"
        return TrafficScaleCohortView(
            id=cohort.id,
            stage=cohort.stage,
            status=status,
            target_batches_per_week=cohort.target_batches_per_week,
            weekly_budget=cohort.weekly_budget,
            no_other_promotion_confirmed=cohort.no_other_promotion_confirmed,
            listing_unchanged_confirmed=cohort.listing_unchanged_confirmed,
            started_at=started_at,
            ended_at=ended_at,
            tail_ends_at=tail_ends,
            commercial_followup_ends_at=followup_ends,
            batch_ids=[value.id for value in batches],
            batch_count=len(batches),
            actual_cost=round(
                sum(
                    value.actual_cost
                    for value in batches
                    if value.started_at is not None and value.status != "cancelled"
                ),
                2,
            ),
        )

    def _attribution_view(
        self, session, attribution: ProductTrafficCommercialAttribution
    ) -> TrafficCommercialAttributionView:
        project = session.get(BusinessProject, attribution.project_id) if attribution.project_id else None
        return TrafficCommercialAttributionView(
            id=attribution.id,
            scope="cohort" if attribution.cohort_id else "batch",
            cohort_id=attribution.cohort_id,
            batch_id=attribution.batch_id,
            conversation_id=attribution.conversation_id,
            project_id=attribution.project_id,
            project_name=project.name if project else None,
            status=attribution.status,
            source=attribution.source,
            first_inbound_at=self._utc(attribution.first_inbound_at),
            window_start=self._utc(attribution.window_start),
            window_end=self._utc(attribution.window_end),
            confirmed_by_user_at=self._utc(attribution.confirmed_by_user_at),
            realized_profit=(
                self._project_profit(session, project.id)
                if project and attribution.status == "confirmed"
                else 0
            ),
            updated_at=self._utc(attribution.updated_at),
        )

    def _active_project_count(self, session) -> int:
        if self.product_intelligence is not None:
            return self.product_intelligence._active_project_count(session)
        return int(
            session.scalar(
                select(func.count(BusinessProject.id)).where(
                    BusinessProject.status.in_(("pending", "in_progress", "overdue"))
                )
            )
            or 0
        )

    def _metrics(
        self,
        session,
        experiment: ProductTrafficExperiment,
        cells: list[TrafficExperimentCellView],
        cohorts: list[TrafficScaleCohortView],
        attributions: list[TrafficCommercialAttributionView],
        confirmed_winner: str | None,
    ) -> TrafficGrowthMetricsView:
        current_cohort = cohorts[-1] if cohorts else None
        if current_cohort:
            scope_ids = set(current_cohort.batch_ids)
            scoped_attributions = [
                value for value in attributions if value.cohort_id == current_cohort.id
            ]
            actual_cost = current_cohort.actual_cost
            observation_complete = bool(
                current_cohort.commercial_followup_ends_at
                and self._now().astimezone(timezone.utc)
                >= current_cohort.commercial_followup_ends_at
            )
        else:
            scope_ids = {value.batch_id for value in cells if value.batch_id}
            batches = session.scalars(
                select(ProductTrafficBatch).where(ProductTrafficBatch.id.in_(scope_ids))
            ).all() if scope_ids else []
            actual_cost = round(
                sum(
                    value.actual_cost
                    for value in batches
                    if value.started_at is not None and value.status != "cancelled"
                ),
                2,
            )
            scoped_attributions = [value for value in attributions if value.batch_id in scope_ids]
            observation_complete = confirmed_winner is not None
        usable_inquiries = [
            value for value in scoped_attributions if value.status in {"candidate", "confirmed"}
        ]
        paid = {
            value.project_id: value
            for value in scoped_attributions
            if value.status == "confirmed" and value.project_id and value.realized_profit > 0
        }
        realized = round(sum(value.realized_profit for value in paid.values()), 2)
        ratio = round(realized / actual_cost, 2) if actual_cost > 0 else None
        limitations = ["该比值是曝光后关联收益，不等同于平台因果增量"]
        if not observation_complete:
            limitations.append("商业转化观察期尚未结束，当前不能作缩减或暂停结论")
        if not paid:
            limitations.append("尚无完成对话与项目绑定的已回款项目")
        return TrafficGrowthMetricsView(
            actual_cost=round(actual_cost, 2),
            attributed_inquiry_count=len(usable_inquiries),
            paid_project_count=len(paid),
            realized_contribution_profit=realized,
            profit_to_cost_ratio=ratio,
            net_after_traffic=round(realized - actual_cost, 2),
            active_projects=self._active_project_count(session),
            delivery_capacity=self.settings.product_delivery_capacity,
            observation_complete=observation_complete,
            limitations=limitations,
        )

    def _latest_persisted_decision(
        self, session, experiment_id: str
    ) -> ProductTrafficBudgetDecision | None:
        return session.scalar(
            select(ProductTrafficBudgetDecision)
            .where(ProductTrafficBudgetDecision.experiment_id == experiment_id)
            .order_by(ProductTrafficBudgetDecision.decided_at.desc())
            .limit(1)
        )

    def _cohort_decision_ratios(
        self,
        session,
        experiment_id: str,
        *,
        exclude_cohort_id: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return one decision-grade ratio per prior closed cohort.

        Budget decisions are immutable evidence snapshots.  Counting closed
        cohorts alone would incorrectly treat an excellent prior cohort as a
        second below-break-even failure, so pause/efficiency rules read the
        persisted ratio for each cohort explicitly.
        """

        cohorts = session.scalars(
            select(ProductTrafficScaleCohort)
            .where(
                ProductTrafficScaleCohort.experiment_id == experiment_id,
                ProductTrafficScaleCohort.status == "closed",
            )
            .order_by(ProductTrafficScaleCohort.created_at)
        ).all()
        result: list[tuple[str, float]] = []
        for cohort in cohorts:
            if cohort.id == exclude_cohort_id:
                continue
            decision = session.scalar(
                select(ProductTrafficBudgetDecision)
                .where(
                    ProductTrafficBudgetDecision.experiment_id == experiment_id,
                    ProductTrafficBudgetDecision.cohort_id == cohort.id,
                )
                .order_by(ProductTrafficBudgetDecision.decided_at.desc())
                .limit(1)
            )
            if decision is None:
                continue
            metrics = self._json(decision.metrics_json, {})
            ratio = metrics.get("profit_to_cost_ratio")
            if isinstance(ratio, (int, float)):
                result.append((cohort.id, float(ratio)))
        return result

    def _decision(
        self,
        session,
        experiment: ProductTrafficExperiment,
        metrics: TrafficGrowthMetricsView,
        *,
        confirmed_winner: str | None,
        cohorts: list[TrafficScaleCohortView],
        persisted: ProductTrafficBudgetDecision | None = None,
    ) -> TrafficBudgetDecisionView:
        current_stage = cohorts[-1].stage if cohorts else "T0"
        stage_index = STAGE_ORDER.index(current_stage)
        next_stage = STAGE_ORDER[min(stage_index + 1, len(STAGE_ORDER) - 1)]
        previous_stage = STAGE_ORDER[max(0, stage_index - 1)]
        recommendation = "hold"
        to_stage = current_stage
        budget = STAGE_WEEKLY_BUDGET[current_stage]
        evidence = []
        ratio = metrics.profit_to_cost_ratio
        current_cohort_id = cohorts[-1].id if cohorts else None
        prior_ratios = self._cohort_decision_ratios(
            session,
            experiment.id,
            exclude_cohort_id=current_cohort_id,
        )
        prior_ratio = prior_ratios[-1][1] if prior_ratios else None
        efficiency_declined = bool(
            ratio is not None
            and prior_ratio is not None
            and ratio < prior_ratio * 0.7
        )
        if metrics.active_projects >= metrics.delivery_capacity:
            recommendation = "pause"
            budget = 0
            evidence.append("交付负载已满，先暂停新增曝光")
        elif not confirmed_winner and not cohorts:
            evidence.append("时段实验尚未确认稳定优先时段")
        elif not metrics.observation_complete:
            evidence.append("商业转化观察期尚未结束，保持当前预算")
        elif metrics.active_projects >= 3:
            recommendation = "reduce" if stage_index > 0 else "hold"
            to_stage = previous_stage if recommendation == "reduce" else current_stage
            budget = STAGE_WEEKLY_BUDGET[to_stage]
            evidence.append("交付负载达到 3/4，不继续扩大流量")
        elif efficiency_declined:
            evidence.append(
                f"当前阶段归因利润率 {ratio:.2f}，较上一完整阶段 "
                f"{prior_ratio:.2f} 下降超过 30%，暂不继续加码"
            )
        elif (
            ratio is not None
            and ratio >= experiment.profit_ratio_scale_threshold
            and metrics.attributed_inquiry_count >= experiment.min_attributed_inquiries
            and metrics.paid_project_count >= experiment.min_paid_projects
            and metrics.realized_contribution_profit >= experiment.min_realized_profit
        ):
            recommendation = "scale" if stage_index < len(STAGE_ORDER) - 1 else "hold"
            to_stage = next_stage if recommendation == "scale" else current_stage
            budget = min(experiment.hard_weekly_cap, STAGE_WEEKLY_BUDGET[to_stage])
            evidence.append(
                f"归因利润率 {ratio:.2f}，并满足咨询、项目、利润和交付容量门槛"
            )
        elif metrics.observation_complete and ratio is not None and ratio < experiment.profit_ratio_hold_threshold:
            prior_below_break_even = sum(
                1
                for _, value in prior_ratios
                if value < experiment.profit_ratio_break_even
            )
            if ratio < experiment.profit_ratio_break_even and prior_below_break_even >= 1:
                recommendation = "pause"
                budget = 0
                evidence.append("连续两个完整阶段低于盈亏平衡阈值，建议暂停 14 天")
            elif stage_index > 0:
                recommendation = "reduce"
                to_stage = previous_stage
                budget = STAGE_WEEKLY_BUDGET[to_stage]
                evidence.append(f"完整观察后归因利润率 {ratio:.2f} 低于保持阈值 2.0")
            else:
                evidence.append(f"归因利润率 {ratio:.2f} 偏低，维持基础预算继续观察")
        else:
            evidence.append("当前证据不足以加码或缩减，保持预算继续观察")
        if metrics.attributed_inquiry_count < experiment.min_attributed_inquiries:
            evidence.append(
                f"曝光后归因咨询 {metrics.attributed_inquiry_count}/{experiment.min_attributed_inquiries}"
            )
        if metrics.paid_project_count < experiment.min_paid_projects:
            evidence.append(
                f"已回款归因项目 {metrics.paid_project_count}/{experiment.min_paid_projects}"
            )
        now = self._now().astimezone(timezone.utc)
        persisted_matches = bool(
            persisted
            and persisted.recommendation == recommendation
            and persisted.from_stage == current_stage
            and persisted.to_stage == to_stage
            and abs(persisted.recommended_weekly_budget - budget) < 0.001
            and self._json(persisted.metrics_json, {})
            == metrics.model_dump(mode="json")
        )
        visible_persisted = persisted if persisted_matches else None
        return TrafficBudgetDecisionView(
            id=visible_persisted.id if visible_persisted else None,
            recommendation=recommendation,
            status=visible_persisted.status if visible_persisted else "preview",
            from_stage=current_stage,
            to_stage=to_stage,
            current_weekly_budget=round(experiment.current_weekly_budget, 2),
            recommended_weekly_budget=round(budget, 2),
            metrics=metrics,
            evidence=evidence,
            rules_version=GROWTH_RULES_VERSION,
            decided_at=(
                self._utc(visible_persisted.decided_at)
                if visible_persisted
                else now
            ),
            applied_at=(
                self._utc(visible_persisted.applied_at)
                if visible_persisted
                else None
            ),
            can_apply=bool(
                visible_persisted
                and visible_persisted.status == "pending"
                and recommendation in {"scale", "reduce", "pause"}
            ),
        )

    def _experiment_view(self, session, experiment: ProductTrafficExperiment) -> TrafficExperimentView:
        item = session.get(Item, experiment.item_id)
        if item is None:
            raise TrafficGrowthNotFound("实验商品已不存在")
        windows = [str(value).zfill(2) for value in self._json(experiment.target_windows_json, list(DEFAULT_WINDOWS))]
        cell_models = session.scalars(
            select(ProductTrafficExperimentCell)
            .where(ProductTrafficExperimentCell.experiment_id == experiment.id)
            .order_by(ProductTrafficExperimentCell.scheduled_for, ProductTrafficExperimentCell.created_at)
        ).all()
        cells = [self._cell_view(session, experiment, value) for value in cell_models]
        time_windows, provisional, confirmed = self._window_results(cells, windows)
        cohort_models = session.scalars(
            select(ProductTrafficScaleCohort)
            .where(ProductTrafficScaleCohort.experiment_id == experiment.id)
            .order_by(ProductTrafficScaleCohort.created_at)
        ).all()
        cohorts = [self._cohort_view(session, value) for value in cohort_models]
        attribution_models = session.scalars(
            select(ProductTrafficCommercialAttribution)
            .where(ProductTrafficCommercialAttribution.experiment_id == experiment.id)
            .order_by(ProductTrafficCommercialAttribution.first_inbound_at)
        ).all()
        attributions = [self._attribution_view(session, value) for value in attribution_models]
        metrics = self._metrics(
            session,
            experiment,
            cells,
            cohorts,
            attributions,
            confirmed,
        )
        persisted = self._latest_persisted_decision(session, experiment.id)
        decision = self._decision(
            session,
            experiment,
            metrics,
            confirmed_winner=confirmed,
            cohorts=cohorts,
            persisted=persisted,
        )
        pending_cells = [value for value in cells if value.status in {"pending", "bound"}]
        next_cell = pending_cells[0] if pending_cells else None
        warnings = [
            "历史商品利润不计入曝光归因利润",
            "只有实际开始时间所属的两小时窗口参与时段实验",
        ]
        if cohorts:
            warnings.append("扩量队列只作整体收益判断，不恢复重叠批次的单批归因")
        return TrafficExperimentView(
            id=experiment.id,
            mode=experiment.mode,
            status=experiment.status,
            phase=experiment.phase,
            product=self._product_view(session, item),
            target_windows=windows,
            baseline_weekly_budget=round(experiment.baseline_weekly_budget, 2),
            current_weekly_budget=round(experiment.current_weekly_budget, 2),
            hard_weekly_cap=round(experiment.hard_weekly_cap, 2),
            base_batch_cost=round(experiment.base_batch_cost, 2),
            started_at=self._utc(experiment.started_at),
            completed_at=self._utc(experiment.completed_at),
            valid_exploration_batches=sum(
                1 for value in cells if value.phase == "exploration" and value.analysis_eligible
            ),
            valid_confirmation_batches=sum(
                1 for value in cells if value.phase == "confirmation" and value.analysis_eligible
            ),
            provisional_winner=provisional,
            confirmed_winner=confirmed,
            cells=cells,
            time_windows=time_windows,
            cohorts=cohorts,
            attributions=attributions,
            metrics=metrics,
            budget_decision=decision,
            next_cell=next_cell,
            warnings=warnings,
            updated_at=self._utc(experiment.updated_at),
        )

    def overview(self) -> TrafficGrowthOverviewView:
        with self.database.session() as session:
            experiments = session.scalars(
                select(ProductTrafficExperiment).order_by(ProductTrafficExperiment.created_at.desc())
            ).all()
            active_model = next(
                (value for value in experiments if value.status in {"active", "paused"}),
                None,
            )
            active = self._experiment_view(session, active_model) if active_model else None
            historical = [
                self._experiment_view(session, value)
                for value in experiments
                if active_model is None or value.id != active_model.id
            ]
            candidate_items = session.scalars(
                select(Item)
                .join(ProductMonitor, ProductMonitor.item_id == Item.id)
                .where(
                    ProductMonitor.ownership_status == "owned",
                    ProductMonitor.enabled.is_(True),
                )
                .order_by(Item.updated_at.desc())
            ).all()
            candidate_views = [
                self._product_view(session, item) for item in candidate_items
            ]
            candidate = max(
                candidate_views,
                key=lambda value: (
                    value.historical_realized_profit,
                    value.historical_project_count,
                ),
                default=None,
            )
        return TrafficGrowthOverviewView(
            active_experiment=active,
            historical_experiments=historical,
            recommended_candidate=candidate,
            safety_notice="全部实验、时段和预算均为本地建议；系统不会购买曝光或修改闲鱼商品。",
        )

    def operating_plan_context(self, session, *, now: datetime) -> dict[str, Any] | None:
        """Expose only the approved future schedule to the rolling plan.

        This method never creates a traffic batch.  The operating plan keeps
        executed days immutable and uses this context only to replace generic
        alternating-day advice with the next clean matrix cell or an active
        scale cohort's advisory frequency.
        """

        experiment = session.scalar(
            select(ProductTrafficExperiment)
            .where(ProductTrafficExperiment.status == "active")
            .order_by(ProductTrafficExperiment.created_at.desc())
            .limit(1)
        )
        if experiment is None:
            return None
        item = session.get(Item, experiment.item_id)
        if item is None:
            return None
        now_utc = self._utc(now)
        assert now_utc is not None
        local_now = now_utc.astimezone(self.local_tz)
        slots: dict[str, dict[str, Any]] = {}
        if experiment.mode == "time_test":
            cells = session.scalars(
                select(ProductTrafficExperimentCell)
                .where(
                    ProductTrafficExperimentCell.experiment_id == experiment.id,
                    ProductTrafficExperimentCell.status == "pending",
                    ProductTrafficExperimentCell.batch_id.is_(None),
                    ProductTrafficExperimentCell.scheduled_for.is_not(None),
                )
                .order_by(ProductTrafficExperimentCell.scheduled_for)
            ).all()
            if not cells:
                return None
            cell = cells[0]
            scheduled = self._utc(cell.scheduled_for)
            assert scheduled is not None
            local = scheduled.astimezone(self.local_tz)
            slots[local.date().isoformat()] = {
                "scheduled_time": f"{local.hour:02d}:{local.minute:02d}",
                "hero_external_id": item.external_id,
                "experiment_id": experiment.id,
                "cell_id": cell.id,
                "mode": "time_test",
                "phase": cell.phase,
                "window_bucket": cell.window_bucket,
            }
        elif experiment.mode == "scale_cohort":
            cohort = session.scalar(
                select(ProductTrafficScaleCohort)
                .where(
                    ProductTrafficScaleCohort.experiment_id == experiment.id,
                    ProductTrafficScaleCohort.status.in_(("planned", "active")),
                )
                .order_by(ProductTrafficScaleCohort.created_at.desc())
                .limit(1)
            )
            if cohort is None:
                return None
            view = self._experiment_view(session, experiment)
            if not view.confirmed_winner:
                return None
            hour = int(view.confirmed_winner)
            target = max(1, min(7, cohort.target_batches_per_week))
            first_offset = 0 if local_now.hour < hour else 1
            available_offsets = list(range(first_offset, 7))
            if target >= len(available_offsets):
                offsets = available_offsets
            elif target == 1:
                offsets = [available_offsets[0]]
            else:
                last_index = len(available_offsets) - 1
                offsets = sorted(
                    {
                        available_offsets[round(index * last_index / (target - 1))]
                        for index in range(target)
                    }
                )
            for offset in offsets:
                day = local_now.date() + timedelta(days=offset)
                slots[day.isoformat()] = {
                    "scheduled_time": f"{hour:02d}:00",
                    "hero_external_id": item.external_id,
                    "experiment_id": experiment.id,
                    "cohort_id": cohort.id,
                    "mode": "scale_cohort",
                    "stage": cohort.stage,
                }
        if not slots:
            return None
        return {
            "experiment_id": experiment.id,
            "mode": experiment.mode,
            "phase": experiment.phase,
            "hero_external_id": item.external_id,
            "weekly_budget": round(experiment.current_weekly_budget, 2),
            "hard_weekly_cap": round(experiment.hard_weekly_cap, 2),
            "slots": slots,
        }

    def bind_plan_batch_in_session(
        self,
        session,
        *,
        slot,
        batch: ProductTrafficBatch,
    ) -> None:
        """Bind a plan-created batch to its experiment scope atomically.

        The rolling-plan slot already persists the approved experiment/cell or
        cohort identifiers.  Materialising that slot into a traffic batch must
        create the association in the same transaction; otherwise a scale
        cohort's hero listing is still treated as an unsafe overlap during the
        start preview window.
        """

        summary = self._json(slot.rotation_summary_json, {})
        if not summary.get("experiment_managed"):
            return
        experiment_id = str(summary.get("experiment_id") or "")
        if not experiment_id:
            raise TrafficGrowthConflict("增长实验计划缺少实验标识，请重新生成经营计划")
        experiment = session.get(ProductTrafficExperiment, experiment_id)
        if experiment is None or experiment.status != "active":
            raise TrafficGrowthConflict("增长实验已经变化，请重新生成经营计划")
        contains_item = session.scalar(
            select(ProductTrafficBatchItem.id).where(
                ProductTrafficBatchItem.batch_id == batch.id,
                ProductTrafficBatchItem.item_id == experiment.item_id,
            )
        )
        if not contains_item:
            raise TrafficGrowthConflict("计划批次不包含增长实验重点商品")

        now = self._now().astimezone(timezone.utc)
        mode = str(summary.get("mode") or "")
        if mode == "time_test":
            cell_id = str(summary.get("cell_id") or "")
            cell = session.get(ProductTrafficExperimentCell, cell_id)
            if (
                cell is None
                or cell.experiment_id != experiment.id
                or cell.status != "pending"
                or cell.batch_id is not None
            ):
                raise TrafficGrowthConflict("时段实验格已经变化，请重新生成经营计划")
            existing = session.scalar(
                select(ProductTrafficExperimentCell.id).where(
                    ProductTrafficExperimentCell.batch_id == batch.id
                )
            )
            if existing:
                raise TrafficGrowthConflict("该批次已经绑定到其他时段实验格")
            cell.batch_id = batch.id
            cell.status = "bound"
            cell.updated_at = now
        elif mode == "scale_cohort":
            cohort_id = str(summary.get("cohort_id") or "")
            cohort = session.get(ProductTrafficScaleCohort, cohort_id)
            if (
                cohort is None
                or cohort.experiment_id != experiment.id
                or cohort.status not in {"planned", "active"}
            ):
                raise TrafficGrowthConflict("扩量队列已经变化，请重新生成经营计划")
            existing = session.scalar(
                select(ProductTrafficScaleCohortBatch).where(
                    ProductTrafficScaleCohortBatch.batch_id == batch.id
                )
            )
            if existing is not None and existing.cohort_id != cohort.id:
                raise TrafficGrowthConflict("该批次已经属于另一个扩量队列")
            linked_batches = session.scalars(
                select(ProductTrafficBatch)
                .join(
                    ProductTrafficScaleCohortBatch,
                    ProductTrafficScaleCohortBatch.batch_id == ProductTrafficBatch.id,
                )
                .where(ProductTrafficScaleCohortBatch.cohort_id == cohort.id)
            ).all()
            if existing is None and len(linked_batches) >= cohort.target_batches_per_week * 2:
                raise TrafficGrowthConflict("该 14 天扩量队列已达到计划批次数")
            planned_cost = sum(
                value.actual_cost
                for value in linked_batches
                if value.status != "cancelled"
            ) + (batch.actual_cost if existing is None else 0)
            if planned_cost > cohort.weekly_budget * 2 + 0.001:
                raise TrafficGrowthConflict("该 14 天扩量队列将超过两周预算上限")
            if existing is None:
                session.add(
                    ProductTrafficScaleCohortBatch(
                        cohort_id=cohort.id,
                        batch_id=batch.id,
                        created_at=now,
                    )
                )
            batch.recording_mode = "scale_cohort"
            batch.attribution_status = "cohort_overlap"
            batch.updated_at = now
            cohort.updated_at = now
        else:
            raise TrafficGrowthConflict("经营计划中的增长实验模式无效")
        experiment.updated_at = now

    def sync_started_batch_in_session(
        self,
        session,
        *,
        batch: ProductTrafficBatch,
    ) -> None:
        """Apply the authoritative start minute to an existing association."""

        started_at = self._utc(batch.started_at)
        if started_at is None:
            return
        now = self._now().astimezone(timezone.utc)
        cell = session.scalar(
            select(ProductTrafficExperimentCell).where(
                ProductTrafficExperimentCell.batch_id == batch.id
            )
        )
        if cell is not None and cell.phase != "off_matrix":
            experiment = session.get(ProductTrafficExperiment, cell.experiment_id)
            if experiment is None:
                raise TrafficGrowthConflict("曝光批次绑定的时段实验已不存在")
            local = started_at.astimezone(self.local_tz)
            actual_bucket = f"{(local.hour // 2) * 2:02d}"
            target = cell
            if actual_bucket != cell.window_bucket:
                alternative = session.scalar(
                    select(ProductTrafficExperimentCell)
                    .where(
                        ProductTrafficExperimentCell.experiment_id == experiment.id,
                        ProductTrafficExperimentCell.phase == cell.phase,
                        ProductTrafficExperimentCell.window_bucket == actual_bucket,
                        ProductTrafficExperimentCell.batch_id.is_(None),
                    )
                    .order_by(ProductTrafficExperimentCell.repeat_index)
                    .limit(1)
                )
                cell.batch_id = None
                cell.status = "pending"
                cell.actual_bucket = None
                cell.updated_at = now
                # SQLite enforces the unique batch_id constraint row by row;
                # release the original cell before assigning the batch to the
                # actual-time target cell.
                session.flush()
                if alternative is not None:
                    target = alternative
                else:
                    next_repeat = int(
                        session.scalar(
                            select(func.max(ProductTrafficExperimentCell.repeat_index)).where(
                                ProductTrafficExperimentCell.experiment_id == experiment.id,
                                ProductTrafficExperimentCell.phase == "off_matrix",
                                ProductTrafficExperimentCell.window_bucket == actual_bucket,
                            )
                        )
                        or 0
                    ) + 1
                    target = ProductTrafficExperimentCell(
                        id=f"traffic-experiment-cell-{uuid4()}",
                        experiment_id=experiment.id,
                        phase="off_matrix",
                        window_bucket=actual_bucket,
                        repeat_index=next_repeat,
                        status="excluded",
                        batch_id=batch.id,
                        actual_bucket=actual_bucket,
                        exclusion_reason="实际开始时间不属于仍缺少的实验格",
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(target)
            if target.batch_id is None:
                target.batch_id = batch.id
            target.actual_bucket = actual_bucket
            target.status = "bound" if target.phase != "off_matrix" else "excluded"
            target.updated_at = now
            experiment.updated_at = now

        association = session.scalar(
            select(ProductTrafficScaleCohortBatch).where(
                ProductTrafficScaleCohortBatch.batch_id == batch.id
            )
        )
        if association is None:
            return
        cohort = session.get(ProductTrafficScaleCohort, association.cohort_id)
        if cohort is None:
            raise TrafficGrowthConflict("曝光批次绑定的扩量队列已不存在")
        experiment = session.get(ProductTrafficExperiment, cohort.experiment_id)
        if experiment is None:
            raise TrafficGrowthConflict("扩量队列绑定的增长实验已不存在")
        if cohort.started_at is None:
            cohort.started_at = started_at
            cohort.ended_at = started_at + timedelta(days=experiment.cohort_days)
            cohort.tail_ends_at = cohort.ended_at + timedelta(days=experiment.tail_days)
            cohort.commercial_followup_ends_at = cohort.ended_at + timedelta(
                days=experiment.commercial_followup_days
            )
            cohort.status = "active"
        elif cohort.ended_at and started_at >= self._utc(cohort.ended_at):
            raise TrafficGrowthConflict("该批次实际开始时间已超出 14 天扩量窗口")
        batch.recording_mode = "scale_cohort"
        batch.attribution_status = "cohort_overlap"
        batch.updated_at = now
        cohort.updated_at = now
        experiment.updated_at = now

    def experiment(self, experiment_id: str) -> TrafficExperimentView:
        with self.database.session() as session:
            experiment = session.get(ProductTrafficExperiment, experiment_id)
            if experiment is None:
                raise TrafficGrowthNotFound("增长实验不存在")
            return self._experiment_view(session, experiment)

    def bind_experiment_batch(
        self,
        experiment_id: str,
        cell_id: str,
        *,
        request_id: str,
        batch_id: str,
    ) -> TrafficExperimentView:
        payload = {"experiment_id": experiment_id, "cell_id": cell_id, "batch_id": batch_id}
        with self.database.session() as session:
            replay = self._request_replay(
                session,
                request_id=request_id,
                operation="bind_experiment_batch",
                payload=payload,
            )
            if replay:
                return self.experiment(experiment_id)
            experiment = session.get(ProductTrafficExperiment, experiment_id)
            cell = session.get(ProductTrafficExperimentCell, cell_id)
            batch = session.get(ProductTrafficBatch, batch_id)
            if experiment is None or cell is None or cell.experiment_id != experiment_id:
                raise TrafficGrowthNotFound("实验或实验格不存在")
            if batch is None:
                raise TrafficGrowthNotFound("曝光批次不存在")
            contains_item = session.scalar(
                select(ProductTrafficBatchItem.id).where(
                    ProductTrafficBatchItem.batch_id == batch.id,
                    ProductTrafficBatchItem.item_id == experiment.item_id,
                )
            )
            if not contains_item:
                raise TrafficGrowthConflict("该批次不包含实验重点商品")
            already = session.scalar(
                select(ProductTrafficExperimentCell).where(
                    ProductTrafficExperimentCell.batch_id == batch.id
                )
            )
            if already and already.id != cell.id:
                raise TrafficGrowthConflict("该批次已经绑定到另一个实验格")
            target = cell
            if batch.started_at:
                local = self._utc(batch.started_at).astimezone(self.local_tz)
                actual_bucket = f"{(local.hour // 2) * 2:02d}"
                if actual_bucket != cell.window_bucket:
                    alternative = session.scalar(
                        select(ProductTrafficExperimentCell)
                        .where(
                            ProductTrafficExperimentCell.experiment_id == experiment.id,
                            ProductTrafficExperimentCell.phase == cell.phase,
                            ProductTrafficExperimentCell.window_bucket == actual_bucket,
                            ProductTrafficExperimentCell.batch_id.is_(None),
                        )
                        .order_by(ProductTrafficExperimentCell.repeat_index)
                        .limit(1)
                    )
                    if alternative:
                        target = alternative
                    else:
                        next_repeat = int(
                            session.scalar(
                                select(func.max(ProductTrafficExperimentCell.repeat_index)).where(
                                    ProductTrafficExperimentCell.experiment_id == experiment.id,
                                    ProductTrafficExperimentCell.phase == "off_matrix",
                                    ProductTrafficExperimentCell.window_bucket == actual_bucket,
                                )
                            )
                            or 0
                        ) + 1
                        target = ProductTrafficExperimentCell(
                            id=f"traffic-experiment-cell-{uuid4()}",
                            experiment_id=experiment.id,
                            phase="off_matrix",
                            window_bucket=actual_bucket,
                            repeat_index=next_repeat,
                            status="excluded",
                            batch_id=batch.id,
                            actual_bucket=actual_bucket,
                            exclusion_reason="实际时间不属于仍缺少的实验格",
                            created_at=self._now().astimezone(timezone.utc),
                            updated_at=self._now().astimezone(timezone.utc),
                        )
                        session.add(target)
                target.actual_bucket = actual_bucket
            if target.batch_id is None:
                target.batch_id = batch.id
            target.status = "bound" if target.phase != "off_matrix" else "excluded"
            target.updated_at = self._now().astimezone(timezone.utc)
            experiment.updated_at = target.updated_at
            self._store_request(
                session,
                request_id=request_id,
                operation="bind_experiment_batch",
                payload=payload,
                result={"experiment_id": experiment.id, "cell_id": target.id},
            )
            session.commit()
        return self.experiment(experiment_id)

    def advance_experiment(
        self,
        experiment_id: str,
        *,
        request_id: str,
        expected_updated_at: datetime,
    ) -> TrafficExperimentView:
        payload = {
            "experiment_id": experiment_id,
            "expected_updated_at": self._utc(expected_updated_at).isoformat(),
        }
        with self.database.session() as session:
            replay = self._request_replay(
                session,
                request_id=request_id,
                operation="advance_experiment",
                payload=payload,
            )
            if replay:
                return self.experiment(experiment_id)
            experiment = session.get(ProductTrafficExperiment, experiment_id)
            if experiment is None:
                raise TrafficGrowthNotFound("增长实验不存在")
            if not self._same_time(experiment.updated_at, expected_updated_at):
                raise TrafficGrowthConflict("实验数据已经变化，请刷新后重新确认")
            view = self._experiment_view(session, experiment)
            if experiment.phase != "exploration" or not view.provisional_winner:
                raise TrafficGrowthConflict("探索阶段尚未形成可确认的候选时段")
            ranking = [value for value in view.time_windows if value.rank]
            candidates = [value.window_bucket for value in ranking[:2]]
            if len(candidates) != 2:
                raise TrafficGrowthConflict("至少需要两个可比较时段")
            last_schedule = max(
                [value.scheduled_for for value in view.cells if value.scheduled_for],
                default=self._now().astimezone(timezone.utc),
            )
            rows = self._schedule_rows(
                session,
                item_id=experiment.item_id,
                windows=candidates,
                start_after=last_schedule,
                phase="confirmation",
            )
            now = self._now().astimezone(timezone.utc)
            for row in rows:
                session.add(
                    ProductTrafficExperimentCell(
                        id=f"traffic-experiment-cell-{uuid4()}",
                        experiment_id=experiment.id,
                        phase="confirmation",
                        window_bucket=row["window_bucket"],
                        repeat_index=1,
                        status="pending",
                        scheduled_for=row["scheduled_for"],
                        created_at=now,
                        updated_at=now,
                    )
                )
            experiment.phase = "confirmation"
            experiment.updated_at = now
            self._store_request(
                session,
                request_id=request_id,
                operation="advance_experiment",
                payload=payload,
                result={"experiment_id": experiment.id},
            )
            session.commit()
        return self.experiment(experiment_id)

    def create_scale_cohort(
        self,
        experiment_id: str,
        *,
        request_id: str,
        stage: str,
        no_other_promotion_confirmed: bool,
        listing_unchanged_confirmed: bool,
    ) -> TrafficExperimentView:
        payload = {
            "experiment_id": experiment_id,
            "stage": stage,
            "no_other_promotion_confirmed": no_other_promotion_confirmed,
            "listing_unchanged_confirmed": listing_unchanged_confirmed,
        }
        with self.database.session() as session:
            replay = self._request_replay(
                session,
                request_id=request_id,
                operation="create_scale_cohort",
                payload=payload,
            )
            if replay:
                return self.experiment(experiment_id)
            experiment = session.get(ProductTrafficExperiment, experiment_id)
            if experiment is None:
                raise TrafficGrowthNotFound("增长实验不存在")
            view = self._experiment_view(session, experiment)
            if not view.confirmed_winner:
                raise TrafficGrowthConflict("必须先完成时段确认阶段")
            if not no_other_promotion_confirmed or not listing_unchanged_confirmed:
                raise TrafficGrowthConflict("扩量队列必须确认没有其他推广且商品表达保持不变")
            active = session.scalar(
                select(ProductTrafficScaleCohort.id).where(
                    ProductTrafficScaleCohort.experiment_id == experiment.id,
                    ProductTrafficScaleCohort.status.in_(("planned", "active", "observing")),
                )
            )
            if active:
                raise TrafficGrowthConflict("已有尚未完成的扩量队列")
            latest = session.scalar(
                select(ProductTrafficScaleCohort)
                .where(ProductTrafficScaleCohort.experiment_id == experiment.id)
                .order_by(ProductTrafficScaleCohort.created_at.desc())
                .limit(1)
            )
            expected = "S1" if latest is None else STAGE_ORDER[min(STAGE_ORDER.index(latest.stage) + 1, 3)]
            if stage != expected:
                raise TrafficGrowthConflict(f"下一阶段应为 {expected}，不能跳级")
            applied = session.scalar(
                select(ProductTrafficBudgetDecision.id)
                .where(
                    ProductTrafficBudgetDecision.experiment_id == experiment.id,
                    ProductTrafficBudgetDecision.status == "applied",
                    ProductTrafficBudgetDecision.to_stage == stage,
                )
                .order_by(ProductTrafficBudgetDecision.applied_at.desc())
                .limit(1)
            )
            if applied is None:
                raise TrafficGrowthConflict(
                    f"必须先人工应用进入 {stage} 的预算建议，才能建立扩量队列"
                )
            now = self._now().astimezone(timezone.utc)
            cohort = ProductTrafficScaleCohort(
                id=f"traffic-scale-cohort-{uuid4()}",
                request_id=request_id,
                experiment_id=experiment.id,
                stage=stage,
                status="planned",
                target_batches_per_week=STAGE_BATCHES_PER_WEEK[stage],
                weekly_budget=min(experiment.hard_weekly_cap, STAGE_WEEKLY_BUDGET[stage]),
                no_other_promotion_confirmed=True,
                listing_unchanged_confirmed=True,
                created_at=now,
                updated_at=now,
            )
            session.add(cohort)
            experiment.mode = "scale_cohort"
            experiment.phase = "scaling"
            experiment.updated_at = now
            self._store_request(
                session,
                request_id=request_id,
                operation="create_scale_cohort",
                payload=payload,
                result={"experiment_id": experiment.id, "cohort_id": cohort.id},
            )
            session.commit()
        return self.experiment(experiment_id)

    def bind_cohort_batch(
        self,
        experiment_id: str,
        cohort_id: str,
        *,
        request_id: str,
        batch_id: str,
    ) -> TrafficExperimentView:
        payload = {"experiment_id": experiment_id, "cohort_id": cohort_id, "batch_id": batch_id}
        with self.database.session() as session:
            replay = self._request_replay(
                session,
                request_id=request_id,
                operation="bind_cohort_batch",
                payload=payload,
            )
            if replay:
                return self.experiment(experiment_id)
            experiment = session.get(ProductTrafficExperiment, experiment_id)
            cohort = session.get(ProductTrafficScaleCohort, cohort_id)
            batch = session.get(ProductTrafficBatch, batch_id)
            if experiment is None or cohort is None or cohort.experiment_id != experiment_id:
                raise TrafficGrowthNotFound("增长实验或扩量队列不存在")
            if batch is None:
                raise TrafficGrowthNotFound("曝光批次不存在")
            if cohort.status not in {"planned", "active"}:
                raise TrafficGrowthConflict("当前扩量队列不再接受新批次")
            if batch.status in {"cancelled", "invalidated"}:
                raise TrafficGrowthConflict("已取消或无效批次不能加入扩量队列")
            contains_item = session.scalar(
                select(ProductTrafficBatchItem.id).where(
                    ProductTrafficBatchItem.batch_id == batch.id,
                    ProductTrafficBatchItem.item_id == experiment.item_id,
                )
            )
            if not contains_item:
                raise TrafficGrowthConflict("扩量批次必须包含重点商品")
            existing = session.scalar(
                select(ProductTrafficScaleCohortBatch).where(
                    ProductTrafficScaleCohortBatch.batch_id == batch.id
                )
            )
            if existing and existing.cohort_id != cohort.id:
                raise TrafficGrowthConflict("该批次已经属于另一个扩量队列")
            linked_batches = session.scalars(
                select(ProductTrafficBatch)
                .join(
                    ProductTrafficScaleCohortBatch,
                    ProductTrafficScaleCohortBatch.batch_id
                    == ProductTrafficBatch.id,
                )
                .where(ProductTrafficScaleCohortBatch.cohort_id == cohort.id)
            ).all()
            if existing is None and len(linked_batches) >= cohort.target_batches_per_week * 2:
                raise TrafficGrowthConflict("该 14 天扩量队列已达到计划批次数")
            planned_cost = sum(
                value.actual_cost
                for value in linked_batches
                if value.status != "cancelled"
            ) + (batch.actual_cost if existing is None else 0)
            if planned_cost > cohort.weekly_budget * 2 + 0.001:
                raise TrafficGrowthConflict("该 14 天扩量队列将超过两周预算上限")
            now = self._now().astimezone(timezone.utc)
            if existing is None:
                session.add(
                    ProductTrafficScaleCohortBatch(
                        cohort_id=cohort.id,
                        batch_id=batch.id,
                        created_at=now,
                    )
                )
            if batch.started_at and cohort.started_at is None:
                cohort.started_at = self._utc(batch.started_at)
                cohort.ended_at = cohort.started_at + timedelta(days=experiment.cohort_days)
                cohort.tail_ends_at = cohort.ended_at + timedelta(days=experiment.tail_days)
                cohort.commercial_followup_ends_at = cohort.ended_at + timedelta(
                    days=experiment.commercial_followup_days
                )
                cohort.status = "active"
            elif batch.started_at and cohort.ended_at:
                started_at = self._utc(batch.started_at)
                if started_at >= self._utc(cohort.ended_at):
                    raise TrafficGrowthConflict("该批次实际开始时间已超出 14 天扩量窗口")
            batch.recording_mode = "scale_cohort"
            batch.attribution_status = "cohort_overlap"
            batch.updated_at = now
            cohort.updated_at = now
            experiment.updated_at = now
            self._store_request(
                session,
                request_id=request_id,
                operation="bind_cohort_batch",
                payload=payload,
                result={"experiment_id": experiment.id, "cohort_id": cohort.id},
            )
            session.commit()
        return self.experiment(experiment_id)

    def scale_cohort_for_batch(self, session, batch_id: str) -> ProductTrafficScaleCohort | None:
        return session.scalar(
            select(ProductTrafficScaleCohort)
            .join(
                ProductTrafficScaleCohortBatch,
                ProductTrafficScaleCohortBatch.cohort_id == ProductTrafficScaleCohort.id,
            )
            .where(
                ProductTrafficScaleCohortBatch.batch_id == batch_id,
                ProductTrafficScaleCohort.status.in_(("planned", "active")),
                ProductTrafficScaleCohort.no_other_promotion_confirmed.is_(True),
                ProductTrafficScaleCohort.listing_unchanged_confirmed.is_(True),
            )
            .limit(1)
        )

    def scale_cohort_item_id_for_batch(self, session, batch_id: str) -> int | None:
        cohort = self.scale_cohort_for_batch(session, batch_id)
        if cohort is None:
            return None
        return session.scalar(
            select(ProductTrafficExperiment.item_id).where(
                ProductTrafficExperiment.id == cohort.experiment_id
            )
        )

    def _sync_cohort_times(self, session, cohort: ProductTrafficScaleCohort) -> None:
        starts = session.scalars(
            select(ProductTrafficBatch.started_at)
            .join(
                ProductTrafficScaleCohortBatch,
                ProductTrafficScaleCohortBatch.batch_id == ProductTrafficBatch.id,
            )
            .where(
                ProductTrafficScaleCohortBatch.cohort_id == cohort.id,
                ProductTrafficBatch.started_at.is_not(None),
            )
        ).all()
        starts = [self._utc(value) for value in starts if value]
        if starts and cohort.started_at is None:
            experiment = session.get(ProductTrafficExperiment, cohort.experiment_id)
            cohort.started_at = min(starts)
            cohort.ended_at = cohort.started_at + timedelta(days=experiment.cohort_days)
            cohort.tail_ends_at = cohort.ended_at + timedelta(days=experiment.tail_days)
            cohort.commercial_followup_ends_at = cohort.ended_at + timedelta(
                days=experiment.commercial_followup_days
            )
            cohort.status = "active"
        now = self._now().astimezone(timezone.utc)
        if cohort.ended_at and now >= self._utc(cohort.ended_at) and cohort.status == "active":
            cohort.status = "observing"
        if (
            cohort.commercial_followup_ends_at
            and now >= self._utc(cohort.commercial_followup_ends_at)
            and cohort.status in {"active", "observing"}
        ):
            cohort.status = "closed"
        cohort.updated_at = now

    def refresh_attributions(
        self,
        experiment_id: str,
        *,
        request_id: str,
    ) -> TrafficExperimentView:
        payload = {"experiment_id": experiment_id}
        with self.database.session() as session:
            replay = self._request_replay(
                session,
                request_id=request_id,
                operation="refresh_attributions",
                payload=payload,
            )
            if replay:
                return self.experiment(experiment_id)
            experiment = session.get(ProductTrafficExperiment, experiment_id)
            if experiment is None:
                raise TrafficGrowthNotFound("增长实验不存在")
            scopes: list[tuple[str, str | None, str | None, datetime, datetime]] = []
            cells = session.scalars(
                select(ProductTrafficExperimentCell).where(
                    ProductTrafficExperimentCell.experiment_id == experiment.id,
                    ProductTrafficExperimentCell.batch_id.is_not(None),
                )
            ).all()
            for cell in cells:
                batch = session.get(ProductTrafficBatch, cell.batch_id)
                if (
                    batch
                    and batch.started_at
                    and self._raw_batch_is_h72_eligible(session, batch)
                ):
                    start = self._utc(batch.started_at)
                    scopes.append((f"batch:{batch.id}", None, batch.id, start, start + timedelta(hours=72)))
            cohorts = session.scalars(
                select(ProductTrafficScaleCohort).where(
                    ProductTrafficScaleCohort.experiment_id == experiment.id
                )
            ).all()
            for cohort in cohorts:
                self._sync_cohort_times(session, cohort)
                if cohort.started_at and cohort.ended_at:
                    scopes.append(
                        (
                            f"cohort:{cohort.id}",
                            cohort.id,
                            None,
                            self._utc(cohort.started_at),
                            self._utc(cohort.tail_ends_at)
                            if cohort.tail_ends_at
                            else self._utc(cohort.ended_at)
                            + timedelta(days=experiment.tail_days),
                        )
                    )
            created = 0
            for scope_key, cohort_id, batch_id, window_start, window_end in scopes:
                first_inbound = (
                    select(
                        Message.conversation_id.label("conversation_id"),
                        func.min(Message.received_at).label("first_inbound_at"),
                    )
                    .where(Message.direction == "inbound")
                    .group_by(Message.conversation_id)
                    .subquery()
                )
                rows = session.execute(
                    select(
                        Conversation.id,
                        first_inbound.c.first_inbound_at,
                    )
                    .join(first_inbound, first_inbound.c.conversation_id == Conversation.id)
                    .where(
                        Conversation.item_id == experiment.item_id,
                        first_inbound.c.first_inbound_at >= window_start,
                        first_inbound.c.first_inbound_at < window_end,
                    )
                ).all()
                for conversation_id, first_inbound_at in rows:
                    if session.scalar(
                        select(ProductTrafficCommercialAttribution.id).where(
                            ProductTrafficCommercialAttribution.experiment_id
                            == experiment.id,
                            ProductTrafficCommercialAttribution.conversation_id
                            == conversation_id,
                        )
                    ):
                        continue
                    key = f"{scope_key}:conversation:{conversation_id}"
                    if session.scalar(
                        select(ProductTrafficCommercialAttribution.id).where(
                            ProductTrafficCommercialAttribution.attribution_key == key
                        )
                    ):
                        continue
                    project = session.scalar(
                        select(BusinessProject)
                        .where(
                            BusinessProject.conversation_id == conversation_id,
                            (BusinessProject.item_id == experiment.item_id)
                            | (BusinessProject.item_id.is_(None)),
                        )
                        .order_by(BusinessProject.created_at)
                        .limit(1)
                    )
                    session.add(
                        ProductTrafficCommercialAttribution(
                            id=f"traffic-attribution-{uuid4()}",
                            attribution_key=key,
                            experiment_id=experiment.id,
                            cohort_id=cohort_id,
                            batch_id=batch_id,
                            item_id=experiment.item_id,
                            conversation_id=conversation_id,
                            project_id=project.id if project else None,
                            status="candidate",
                            source="automatic",
                            first_inbound_at=self._utc(first_inbound_at),
                            window_start=window_start,
                            window_end=window_end,
                            created_at=self._now().astimezone(timezone.utc),
                            updated_at=self._now().astimezone(timezone.utc),
                        )
                    )
                    created += 1
            experiment.updated_at = self._now().astimezone(timezone.utc)
            self._store_request(
                session,
                request_id=request_id,
                operation="refresh_attributions",
                payload=payload,
                result={"experiment_id": experiment.id, "created": created},
            )
            session.commit()
        return self.experiment(experiment_id)

    def decide_attribution(
        self,
        attribution_id: str,
        *,
        request_id: str,
        expected_updated_at: datetime,
        decision: str,
        project_id: str | None,
        reason: str,
    ) -> TrafficExperimentView:
        payload = {
            "attribution_id": attribution_id,
            "expected_updated_at": self._utc(expected_updated_at).isoformat(),
            "decision": decision,
            "project_id": project_id,
            "reason": reason.strip(),
        }
        with self.database.session() as session:
            replay = self._request_replay(
                session,
                request_id=request_id,
                operation="decide_attribution",
                payload=payload,
            )
            if replay:
                return self.experiment(str(replay.get("experiment_id") or ""))
            attribution = session.get(ProductTrafficCommercialAttribution, attribution_id)
            if attribution is None:
                raise TrafficGrowthNotFound("商业归因候选不存在")
            if not self._same_time(attribution.updated_at, expected_updated_at):
                raise TrafficGrowthConflict("归因候选已经变化，请刷新后重试")
            if decision not in {"confirm", "reject"}:
                raise TrafficGrowthConflict("不支持的归因操作")
            if decision == "confirm" and not (project_id or attribution.project_id):
                raise TrafficGrowthConflict("确认商业归因前必须选择明确绑定该对话的项目")
            if decision == "confirm" and (project_id or attribution.project_id):
                project_id = project_id or attribution.project_id
                project = session.get(BusinessProject, project_id)
                if project is None:
                    raise TrafficGrowthNotFound("项目不存在")
                if project.conversation_id != attribution.conversation_id:
                    raise TrafficGrowthConflict("项目必须明确绑定到该客户对话")
                if project.item_id not in {None, attribution.item_id}:
                    raise TrafficGrowthConflict("项目绑定的来源商品与实验商品不一致")
                if self._utc(project.created_at) < self._utc(attribution.first_inbound_at):
                    raise TrafficGrowthConflict("项目建立时间早于该曝光后的首次咨询，不能归入本次曝光")
                duplicated = session.scalar(
                    select(ProductTrafficCommercialAttribution.id).where(
                        ProductTrafficCommercialAttribution.id != attribution.id,
                        ProductTrafficCommercialAttribution.project_id == project.id,
                        ProductTrafficCommercialAttribution.status == "confirmed",
                    )
                )
                if duplicated:
                    raise TrafficGrowthConflict("该项目已经确认归入另一个曝光范围")
                attribution.project_id = project.id
            now = self._now().astimezone(timezone.utc)
            attribution.status = "confirmed" if decision == "confirm" else "rejected"
            attribution.confirmed_by_user_at = now if decision == "confirm" else None
            attribution.rejection_reason = reason.strip() if decision == "reject" else ""
            attribution.updated_at = now
            experiment = session.get(ProductTrafficExperiment, attribution.experiment_id)
            experiment.updated_at = now
            self._store_request(
                session,
                request_id=request_id,
                operation="decide_attribution",
                payload=payload,
                result={"experiment_id": experiment.id, "attribution_id": attribution.id},
            )
            session.commit()
            experiment_id = experiment.id
        return self.experiment(experiment_id)

    def refresh_budget_decision(
        self,
        experiment_id: str,
        *,
        request_id: str,
    ) -> TrafficExperimentView:
        payload = {"experiment_id": experiment_id}
        with self.database.session() as session:
            replay = self._request_replay(
                session,
                request_id=request_id,
                operation="refresh_budget_decision",
                payload=payload,
            )
            if replay:
                return self.experiment(experiment_id)
            experiment = session.get(ProductTrafficExperiment, experiment_id)
            if experiment is None:
                raise TrafficGrowthNotFound("增长实验不存在")
            cohorts = session.scalars(
                select(ProductTrafficScaleCohort).where(
                    ProductTrafficScaleCohort.experiment_id == experiment.id
                )
            ).all()
            for cohort in cohorts:
                self._sync_cohort_times(session, cohort)
            view = self._experiment_view(session, experiment)
            preview = view.budget_decision
            signature = self._payload_hash(
                {
                    "recommendation": preview.recommendation,
                    "from_stage": preview.from_stage,
                    "to_stage": preview.to_stage,
                    "budget": preview.recommended_weekly_budget,
                    "metrics": preview.metrics.model_dump(mode="json"),
                    "rules_version": GROWTH_RULES_VERSION,
                }
            )
            key = f"{experiment.id}:{signature}"
            decision = session.scalar(
                select(ProductTrafficBudgetDecision).where(
                    ProductTrafficBudgetDecision.decision_key == key
                )
            )
            if decision is None:
                current_cohort = cohorts[-1] if cohorts else None
                now = self._now().astimezone(timezone.utc)
                decision = ProductTrafficBudgetDecision(
                    id=f"traffic-budget-decision-{uuid4()}",
                    decision_key=key,
                    experiment_id=experiment.id,
                    cohort_id=current_cohort.id if current_cohort else None,
                    recommendation=preview.recommendation,
                    status="pending" if preview.recommendation != "hold" else "recorded",
                    from_stage=preview.from_stage,
                    to_stage=preview.to_stage,
                    current_weekly_budget=preview.current_weekly_budget,
                    recommended_weekly_budget=preview.recommended_weekly_budget,
                    metrics_json=preview.metrics.model_dump_json(),
                    evidence_json=json.dumps(preview.evidence, ensure_ascii=False),
                    rules_version=GROWTH_RULES_VERSION,
                    observation_started_at=(
                        current_cohort.started_at if current_cohort else experiment.started_at
                    ),
                    observation_ended_at=(
                        current_cohort.commercial_followup_ends_at if current_cohort else None
                    ),
                    decided_at=now,
                    created_at=now,
                )
                session.add(decision)
            self._store_request(
                session,
                request_id=request_id,
                operation="refresh_budget_decision",
                payload=payload,
                result={"experiment_id": experiment.id, "decision_id": decision.id},
            )
            session.commit()
        return self.experiment(experiment_id)

    def apply_budget_decision(
        self,
        decision_id: str,
        *,
        request_id: str,
        expected_experiment_updated_at: datetime,
    ) -> TrafficExperimentView:
        payload = {
            "decision_id": decision_id,
            "expected_experiment_updated_at": self._utc(expected_experiment_updated_at).isoformat(),
        }
        with self.database.session() as session:
            replay = self._request_replay(
                session,
                request_id=request_id,
                operation="apply_budget_decision",
                payload=payload,
            )
            if replay:
                return self.experiment(str(replay.get("experiment_id") or ""))
            decision = session.get(ProductTrafficBudgetDecision, decision_id)
            if decision is None:
                raise TrafficGrowthNotFound("预算决策不存在")
            experiment = session.get(ProductTrafficExperiment, decision.experiment_id)
            if not self._same_time(experiment.updated_at, expected_experiment_updated_at):
                raise TrafficGrowthConflict("实验数据已经变化，请重新生成预算判断")
            if decision.status != "pending" or decision.recommendation not in {
                "scale",
                "reduce",
                "pause",
            }:
                raise TrafficGrowthConflict("当前预算判断不可应用")
            cohorts = session.scalars(
                select(ProductTrafficScaleCohort).where(
                    ProductTrafficScaleCohort.experiment_id == experiment.id
                )
            ).all()
            for cohort in cohorts:
                self._sync_cohort_times(session, cohort)
            current = self._experiment_view(session, experiment).budget_decision
            if (
                current.id != decision.id
                or not current.can_apply
                or current.recommendation != decision.recommendation
                or current.from_stage != decision.from_stage
                or current.to_stage != decision.to_stage
                or abs(
                    current.recommended_weekly_budget
                    - decision.recommended_weekly_budget
                )
                > 0.001
                or current.metrics.model_dump(mode="json")
                != self._json(decision.metrics_json, {})
            ):
                raise TrafficGrowthConflict(
                    "预算判断的付款、项目、利润或交付证据已经变化，请重新生成"
                )
            now = self._now().astimezone(timezone.utc)
            experiment.current_weekly_budget = min(
                experiment.hard_weekly_cap,
                max(0, decision.recommended_weekly_budget),
            )
            if decision.recommendation == "pause":
                experiment.status = "paused"
            else:
                experiment.status = "active"
                experiment.mode = "scale_cohort" if decision.to_stage != "T0" else "time_test"
                experiment.phase = "scaling" if decision.to_stage != "T0" else "confirmed"
            experiment.updated_at = now
            decision.status = "applied"
            decision.applied_at = now
            self._store_request(
                session,
                request_id=request_id,
                operation="apply_budget_decision",
                payload=payload,
                result={"experiment_id": experiment.id, "decision_id": decision.id},
            )
            session.commit()
            experiment_id = experiment.id
        return self.experiment(experiment_id)
