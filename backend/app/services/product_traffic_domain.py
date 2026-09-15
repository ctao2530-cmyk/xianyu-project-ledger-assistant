from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from sqlalchemy import func, select

from ..ledger import LedgerService
from ..models import (
    ProductTrafficBatch,
    ProductTrafficBatchItem,
    ProductTrafficCheckpoint,
    ProductTrafficCheckpointJob,
    ProductTrafficCheckpointJobItem,
)


CHECKPOINT_HOURS = {"h1": 1, "h6": 6, "h24": 24, "h48": 48, "h72": 72}
LEGACY_CHECKPOINT_ORDER = ("h1", "h6", "h24", "h72")
ACTUAL_CHECKPOINT_ORDER = ("h1", "h6", "h24", "h48")
CHECKPOINT_ORDER = tuple(CHECKPOINT_HOURS)
CHECKPOINT_MAX_DELAY_MINUTES = {
    "h1": 30,
    "h6": 60,
    "h24": 180,
    "h48": 360,
    "h72": 360,
}
CHECKPOINT_SHORT_LABELS = {
    "h1": "+1h",
    "h6": "+6h",
    "h24": "+24h",
    "h48": "+48h",
    "h72": "+72h",
}
INVALID_BASELINE_REASONS = {
    "missing_baseline": "缺少投放前 T0",
    "legacy_baseline": "使用不可靠的历史 T0",
    "stale_baseline": "T0 与实际投放间隔超过 30 分钟",
    "invalid_baseline_time": "T0 时间关系异常",
}


class ProductTrafficConflict(RuntimeError):
    """A stable business-rule conflict surfaced by the traffic API facade."""


class ProductTrafficProtocol:
    """Immutable 48h/72h protocol and checkpoint policy.

    The facade owns database transactions; this domain object owns the rules
    that decide which checkpoints a stored batch may use.
    """

    @staticmethod
    def normalize_window_hours(value: int | None) -> int:
        return 48 if int(value or 72) == 48 else 72

    @staticmethod
    def observation_window_hours(batch: ProductTrafficBatch) -> int:
        return ProductTrafficProtocol.normalize_window_hours(
            getattr(batch, "observation_window_hours", 72)
        )

    @classmethod
    def checkpoint_order(cls, batch: ProductTrafficBatch) -> tuple[str, ...]:
        return (
            ACTUAL_CHECKPOINT_ORDER
            if cls.observation_window_hours(batch) == 48
            else LEGACY_CHECKPOINT_ORDER
        )

    @classmethod
    def terminal_checkpoint(cls, batch: ProductTrafficBatch) -> str:
        return cls.checkpoint_order(batch)[-1]

    @classmethod
    def observation_title(
        cls,
        batch: ProductTrafficBatch,
        *,
        localize: Callable[[datetime | None], datetime | None],
    ) -> str:
        anchor = localize(batch.started_at or batch.planned_at)
        window = cls.observation_window_hours(batch)
        if anchor is None:
            return f"{window} 小时投流观察"
        return (
            f"{anchor.month}月{anchor.day}日 {anchor.hour:02d}:{anchor.minute:02d} "
            f"投流后的 {window} 小时观察结论"
        )


class ProductTrafficLifecycle:
    """Traffic-batch state machine used inside facade-owned transactions.

    The lifecycle owns protocol guards and model transitions. It deliberately
    does not commit, publish events, call the remote adapter, or maintain plans;
    those orchestration responsibilities stay in ``ProductIntelligenceService``.
    """

    def __init__(self, *, baseline_max_age_minutes: int) -> None:
        self.baseline_max_age_minutes = int(baseline_max_age_minutes)

    @staticmethod
    def utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def minute_utc(cls, value: datetime) -> datetime:
        normalized = cls.utc(value)
        assert normalized is not None
        return normalized.replace(second=0, microsecond=0)

    @classmethod
    def same_timestamp(
        cls,
        left: datetime | None,
        right: datetime | None,
    ) -> bool:
        if left is None or right is None:
            return left is right
        normalized_left = cls.utc(left)
        normalized_right = cls.utc(right)
        assert normalized_left is not None and normalized_right is not None
        return abs((normalized_left - normalized_right).total_seconds()) < 0.001

    @staticmethod
    def validate_checkpoint_collection_mode(mode: str) -> None:
        if mode not in {"auto", "manual"}:
            raise ProductTrafficConflict("不支持的检查点采集方式")

    @staticmethod
    def validate_record_now_request(
        *,
        item_external_ids: list[str],
        confirmed_already_purchased: bool,
        plan_slot_id: str | None,
        checkpoint_collection_mode: str,
        max_items: int,
    ) -> list[str]:
        if not confirmed_already_purchased:
            raise ProductTrafficConflict("请先确认这批曝光已经在闲鱼真实购买")
        if plan_slot_id:
            raise ProductTrafficConflict("新投流记录不再接受经营计划关联")
        ProductTrafficLifecycle.validate_checkpoint_collection_mode(
            checkpoint_collection_mode
        )
        unique_ids = list(dict.fromkeys(item_external_ids))
        if not unique_ids:
            raise ProductTrafficConflict("至少选择一件商品")
        if len(unique_ids) != len(item_external_ids):
            raise ProductTrafficConflict("同一商品不能在一个曝光批次中重复选择")
        if len(unique_ids) > max_items:
            raise ProductTrafficConflict(f"一个批次最多选择 {max_items} 件商品")
        return unique_ids

    @staticmethod
    def new_actual_batch(
        *,
        request_id: str,
        started_at: datetime,
        captured_at: datetime | None,
        transaction_now: datetime,
        actual_cost: float,
        note: str,
        checkpoint_collection_mode: str,
    ) -> ProductTrafficBatch:
        return ProductTrafficBatch(
            id=f"traffic-batch-{uuid4()}",
            request_id=request_id,
            plan_slot_id=None,
            status="running",
            planned_at=started_at,
            started_at=started_at,
            baseline_prepared_at=captured_at,
            recording_mode="actual_now",
            observation_window_hours=48,
            actual_cost=round(actual_cost, 2),
            note=note.strip(),
            checkpoint_collection_mode=checkpoint_collection_mode,
            created_at=started_at,
            updated_at=transaction_now,
        )

    @staticmethod
    def new_actual_batch_item(
        *,
        batch_id: str,
        item_id: int,
        position: int,
        baseline: tuple[int, int, int, int, datetime],
    ) -> ProductTrafficBatchItem:
        return ProductTrafficBatchItem(
            batch_id=batch_id,
            item_id=item_id,
            position=position,
            baseline_browse_count=baseline[0],
            baseline_collect_count=baseline[1],
            baseline_want_count=baseline[2],
            baseline_inquiry_count=baseline[3],
            baseline_captured_at=baseline[4],
            baseline_source="remote_refresh",
        )

    @staticmethod
    def new_missing_actual_batch_item(
        *,
        batch_id: str,
        item_id: int,
        position: int,
    ) -> ProductTrafficBatchItem:
        """Preserve one purchased listing without pretending a partial T0 exists."""

        return ProductTrafficBatchItem(
            batch_id=batch_id,
            item_id=item_id,
            position=position,
            baseline_browse_count=0,
            baseline_collect_count=0,
            baseline_want_count=0,
            baseline_inquiry_count=0,
            baseline_captured_at=None,
            baseline_source="missing",
        )

    @staticmethod
    def mark_overlap(batch: ProductTrafficBatch, *, has_overlap: bool) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if has_overlap:
            batch.recording_mode = "actual_overlap"
            batch.attribution_status = "overlap"

    @staticmethod
    def require_replannable(batch: ProductTrafficBatch) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.status != "planned":
            raise ProductTrafficConflict("只有尚未开始的批次可以重排")

    @staticmethod
    def new_pending_batch_item(
        *,
        batch_id: str,
        item_id: int,
        position: int,
    ) -> ProductTrafficBatchItem:
        return ProductTrafficBatchItem(
            batch_id=batch_id,
            item_id=item_id,
            position=position,
            baseline_browse_count=0,
            baseline_collect_count=0,
            baseline_want_count=0,
            baseline_inquiry_count=0,
            baseline_captured_at=None,
            baseline_source="pending",
        )

    @staticmethod
    def apply_replan(
        batch: ProductTrafficBatch,
        *,
        planned_at: datetime,
        changed_at: datetime,
    ) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        batch.planned_at = planned_at
        batch.baseline_prepared_at = None
        batch.updated_at = changed_at

    def correct_start_from_created_at(
        self,
        batch: ProductTrafficBatch,
        *,
        expected_created_at: datetime,
        expected_started_at: datetime,
        transaction_now: datetime,
    ) -> datetime:
        self.require_current_protocol(batch)
        if batch.started_at is None:
            raise ProductTrafficConflict("未开始批次没有可更正的实际时间")
        if not self.same_timestamp(batch.created_at, expected_created_at):
            raise ProductTrafficConflict("批次建立时间已变化，请停止更正并重新核对")
        if not self.same_timestamp(batch.started_at, expected_started_at):
            raise ProductTrafficConflict("批次实际时间已变化，请停止更正并重新核对")
        target = self.minute_utc(batch.created_at)
        current = self.utc(batch.started_at)
        assert current is not None
        if target > current:
            raise ProductTrafficConflict("建立时间晚于实际投放时间，不能自动倒置历史事实")
        batch.started_at = target
        batch.updated_at = transaction_now
        return target

    @staticmethod
    def require_exploratory_restorable(batch: ProductTrafficBatch) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.status != "invalidated" or batch.started_at is None:
            raise ProductTrafficConflict("只有已真实投放且基线无效的批次可以恢复探索观察")
        if batch.invalidation_reason not in {
            "missing_baseline",
            "legacy_baseline",
            "stale_baseline",
            "invalid_baseline_time",
        }:
            raise ProductTrafficConflict("当前终止原因不支持探索观察恢复")

    def restore_exploratory_baseline(
        self,
        batch: ProductTrafficBatch,
        batch_items: list[ProductTrafficBatchItem],
        *,
        snapshot_by_item: dict[int, object],
        transaction_now: datetime,
    ) -> None:
        self.require_current_protocol(batch)
        if not batch_items or len(snapshot_by_item) != len(batch_items):
            raise ProductTrafficConflict("指定日期没有覆盖整批商品的投放前参考快照")
        reference_times: list[datetime] = []
        for batch_item in batch_items:
            snapshot = snapshot_by_item[batch_item.item_id]
            batch_item.baseline_browse_count = snapshot.browse_count
            batch_item.baseline_collect_count = snapshot.collect_count
            batch_item.baseline_want_count = snapshot.want_count
            batch_item.baseline_inquiry_count = snapshot.inquiry_count
            batch_item.baseline_captured_at = snapshot.captured_at
            batch_item.baseline_source = "daily_exploratory"
            captured_at = self.utc(snapshot.captured_at)
            assert captured_at is not None
            reference_times.append(captured_at)
        batch.baseline_prepared_at = max(reference_times)
        batch.status = "running" if batch.completed_at is None else "observing"
        batch.recording_mode = "exploratory_recovery"
        batch.attribution_status = "exploratory"
        batch.invalidated_at = None
        batch.invalidation_reason = None
        batch.updated_at = transaction_now

    @staticmethod
    def restore_invalidated_jobs(
        batch: ProductTrafficBatch,
        jobs: list[ProductTrafficCheckpointJob],
        *,
        transaction_now: datetime,
    ) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        for job in jobs:
            job.status = "scheduled"
            job.completed_at = None
            job.last_error_code = None
            job.last_error_detail = ""
            job.updated_at = transaction_now

    @staticmethod
    def should_dispatch_due_job(
        job: ProductTrafficCheckpointJob,
        batch: ProductTrafficBatch,
        *,
        now: datetime,
        connection_configured: bool,
    ) -> bool:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.checkpoint_collection_mode == "manual":
            job.status = "waiting_manual"
            job.updated_at = now
            return False
        if job.status == "waiting_connection" and not connection_configured:
            return False
        return True

    @staticmethod
    def mark_job_waiting_connection(
        batch: ProductTrafficBatch,
        job: ProductTrafficCheckpointJob,
        *,
        now: datetime,
    ) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        job.status = "waiting_connection"
        job.last_error_code = "connection_unconfigured"
        job.last_error_detail = "闲鱼商品采集凭证未配置，任务已保留"
        job.updated_at = now

    @staticmethod
    def mark_job_interrupted(
        batch: ProductTrafficBatch,
        job: ProductTrafficCheckpointJob,
        *,
        now: datetime,
    ) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        job.status = "waiting_manual"
        job.last_error_code = "service_restarted"
        job.last_error_detail = (
            "服务在采集中重启；已保留成功商品，请手动补齐或明确恢复补采"
        )
        job.updated_at = now

    @staticmethod
    def apply_legacy_snapshot_baseline(
        batch_item: ProductTrafficBatchItem,
        snapshot,
        *,
        prepared_at: datetime,
    ) -> None:
        batch_item.baseline_browse_count = snapshot.browse_count
        batch_item.baseline_collect_count = snapshot.collect_count
        batch_item.baseline_want_count = snapshot.want_count
        batch_item.baseline_inquiry_count = snapshot.inquiry_count
        batch_item.baseline_captured_at = prepared_at
        batch_item.baseline_source = "legacy_snapshot"

    @staticmethod
    def finish_legacy_baseline(
        batch: ProductTrafficBatch,
        *,
        prepared_at: datetime,
    ) -> None:
        batch.baseline_prepared_at = prepared_at
        batch.updated_at = prepared_at

    @staticmethod
    def begin_automatic_job(
        job: ProductTrafficCheckpointJob,
        batch: ProductTrafficBatch,
        *,
        now: datetime,
    ) -> bool:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.checkpoint_collection_mode != "auto":
            job.status = "waiting_manual"
            return False
        job.status = "collecting"
        job.started_at = job.started_at or now
        job.last_attempt_at = now
        job.attempt_count += 1
        job.last_error_code = None
        job.last_error_detail = ""
        return True

    @staticmethod
    def mark_job_item_error(
        batch: ProductTrafficBatch,
        row: ProductTrafficCheckpointJobItem,
        *,
        code: str,
        detail: str,
        now: datetime,
    ) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        row.status = "failed"
        row.error_code = code[:64]
        row.error_detail = detail[:500]
        row.updated_at = now

    @staticmethod
    def open_access_verification_circuit(
        batch: ProductTrafficBatch,
        job: ProductTrafficCheckpointJob,
        remaining_rows: list[ProductTrafficCheckpointJobItem],
        *,
        code: str,
        detail: str,
        now: datetime,
    ) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        job.status = "circuit_open"
        job.last_error_code = code
        job.last_error_detail = detail
        job.updated_at = now
        for row in remaining_rows:
            row.status = "protection_skipped"
            row.error_code = "access_verification_circuit"
            row.error_detail = "首个访问验证后已停止剩余请求"
            row.updated_at = now

    @staticmethod
    def store_automatic_checkpoint_in_session(
        session,
        *,
        batch: ProductTrafficBatch,
        job: ProductTrafficCheckpointJob,
        batch_item: ProductTrafficBatchItem,
        snapshot,
        captured_at: datetime,
    ) -> ProductTrafficCheckpoint:
        ProductTrafficLifecycle.require_current_protocol(batch)
        counts = (
            snapshot.browse_count,
            snapshot.collect_count,
            snapshot.want_count,
            snapshot.inquiry_count,
        )
        floor = (
            batch_item.baseline_browse_count,
            batch_item.baseline_collect_count,
            batch_item.baseline_want_count,
            batch_item.baseline_inquiry_count,
        )
        prior = session.scalars(
            select(ProductTrafficCheckpoint).where(
                ProductTrafficCheckpoint.batch_id == job.batch_id,
                ProductTrafficCheckpoint.item_id == batch_item.item_id,
                ProductTrafficCheckpoint.checkpoint.in_(
                    CHECKPOINT_ORDER[: CHECKPOINT_ORDER.index(job.checkpoint)]
                ),
            )
        ).all()
        for row in prior:
            floor = tuple(
                max(current, previous)
                for current, previous in zip(
                    floor,
                    (
                        row.browse_count,
                        row.collect_count,
                        row.want_count,
                        row.inquiry_count,
                    ),
                )
            )
        if any(current < previous for current, previous in zip(counts, floor)):
            raise ProductTrafficConflict("采集累计值低于基线或更早检查点")
        checkpoint = session.scalar(
            select(ProductTrafficCheckpoint).where(
                ProductTrafficCheckpoint.batch_id == job.batch_id,
                ProductTrafficCheckpoint.item_id == batch_item.item_id,
                ProductTrafficCheckpoint.checkpoint == job.checkpoint,
            )
        )
        if checkpoint is None:
            checkpoint = ProductTrafficCheckpoint(
                id=f"traffic-checkpoint-{uuid4()}",
                batch_id=job.batch_id,
                item_id=batch_item.item_id,
                checkpoint=job.checkpoint,
            )
            session.add(checkpoint)
        checkpoint.browse_count = counts[0]
        checkpoint.collect_count = counts[1]
        checkpoint.want_count = counts[2]
        checkpoint.inquiry_count = counts[3]
        checkpoint.recorded_at = captured_at
        checkpoint.source = "automatic"
        checkpoint.note = "到点自动只读采集"
        job_item = session.scalar(
            select(ProductTrafficCheckpointJobItem).where(
                ProductTrafficCheckpointJobItem.job_id == job.id,
                ProductTrafficCheckpointJobItem.item_id == batch_item.item_id,
            )
        )
        if job_item is not None:
            job_item.status = "completed"
            job_item.captured_at = captured_at
            job_item.error_code = None
            job_item.error_detail = ""
            job_item.updated_at = captured_at
        return checkpoint

    def finalize_checkpoint_job(
        self,
        job: ProductTrafficCheckpointJob,
        batch: ProductTrafficBatch | None,
        rows: list[ProductTrafficCheckpointJobItem],
        *,
        now: datetime,
    ) -> None:
        if batch is None:
            return
        self.require_current_protocol(batch)
        completed_rows = [row for row in rows if row.status == "completed"]
        job.collected_count = len(completed_rows)
        job.total_count = len(rows)
        captured = [
            value
            for row in completed_rows
            if (value := self.utc(row.captured_at)) is not None
        ]
        job.captured_at = max(captured) if captured else None
        if len(completed_rows) == len(rows) and rows:
            job.status = "completed"
            job.completed_at = now
            scheduled_for = self.utc(job.scheduled_for)
            assert scheduled_for is not None
            job.capture_delay_minutes = max(
                0,
                int((now - scheduled_for).total_seconds() // 60),
            )
            job.last_error_code = None
            job.last_error_detail = ""
            if batch is not None:
                batch.status = (
                    "closed"
                    if job.checkpoint == ProductTrafficProtocol.terminal_checkpoint(batch)
                    else "observing"
                )
                batch.updated_at = now
        elif job.status != "circuit_open":
            job.status = "partial" if completed_rows else "waiting_manual"
            job.last_error_code = job.last_error_code or "partial_collection"
            job.last_error_detail = (
                f"已采集 {len(completed_rows)}/{len(rows)} 件；不会自动重试"
            )
        job.updated_at = now

    @staticmethod
    def prepare_checkpoint_retry(
        job: ProductTrafficCheckpointJob,
        rows: list[ProductTrafficCheckpointJobItem],
        batch: ProductTrafficBatch,
        *,
        checkpoint: str,
        now: datetime,
    ) -> bool:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if checkpoint not in ProductTrafficProtocol.checkpoint_order(batch):
            raise ProductTrafficConflict("该批次协议不包含这个观察检查点")
        if batch.status not in {"running", "observing"}:
            raise ProductTrafficConflict("该批次不再允许补采")
        if batch.checkpoint_collection_mode != "auto":
            raise ProductTrafficConflict("请先切换到自动采集方式")
        if job.status == "completed":
            return False
        if not rows:
            raise ProductTrafficConflict("没有需要补采的商品")
        for row in rows:
            row.status = "pending"
            row.error_code = None
            row.error_detail = ""
            row.updated_at = now
        job.status = "scheduled"
        job.last_error_code = None
        job.last_error_detail = ""
        job.updated_at = now
        batch.updated_at = now
        return True

    @staticmethod
    def require_current_protocol(batch: ProductTrafficBatch) -> None:
        if ProductTrafficProtocol.observation_window_hours(batch) != 48:
            raise ProductTrafficConflict(
                "历史 72h 曝光批次为只读记录，不能再修改、启动或重排"
            )

    @classmethod
    def require_revision(
        cls,
        batch: ProductTrafficBatch,
        expected_updated_at: datetime,
    ) -> None:
        if not cls.same_timestamp(batch.updated_at, expected_updated_at):
            raise ProductTrafficConflict("批次已在其他页面更新，请刷新后重试")

    @staticmethod
    def require_baseline_preparable(batch: ProductTrafficBatch) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.status != "planned":
            raise ProductTrafficConflict("已经开始或取消的批次不能重新准备 T0")

    @staticmethod
    def require_startable(
        batch: ProductTrafficBatch,
        *,
        legacy_internal: bool,
    ) -> bool:
        if not legacy_internal:
            ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.status == "cancelled":
            raise ProductTrafficConflict("已取消的批次不能开始")
        if batch.status != "planned":
            if legacy_internal:
                return False
            raise ProductTrafficConflict("批次已经开始；请刷新页面查看实际开始时间")
        return True

    @staticmethod
    def apply_baseline(
        batch: ProductTrafficBatch,
        batch_items: list[ProductTrafficBatchItem],
        *,
        values: dict[int, tuple[int, int, int, int, datetime]],
        source: str,
        captured_at: datetime,
    ) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        for batch_item in batch_items:
            row = values[batch_item.item_id]
            (
                batch_item.baseline_browse_count,
                batch_item.baseline_collect_count,
                batch_item.baseline_want_count,
                batch_item.baseline_inquiry_count,
            ) = row[:4]
            batch_item.baseline_captured_at = row[4]
            batch_item.baseline_source = source
        batch.baseline_prepared_at = captured_at
        batch.updated_at = captured_at

    def apply_start(
        self,
        batch: ProductTrafficBatch,
        batch_items: list[ProductTrafficBatchItem],
        *,
        expected_updated_at: datetime,
        expected_baseline_captured_at: datetime,
        transaction_now: datetime,
        blocked_reason: str | None,
        legacy_internal: bool,
    ) -> datetime:
        self.require_startable(batch, legacy_internal=legacy_internal)
        self.require_revision(batch, expected_updated_at)
        if blocked_reason:
            raise ProductTrafficConflict(blocked_reason)
        prepared_at = self.utc(batch.baseline_prepared_at)
        expected_prepared = self.utc(expected_baseline_captured_at)
        if prepared_at is None or not self.same_timestamp(prepared_at, expected_prepared):
            raise ProductTrafficConflict("T0 已变化，请刷新开始预览后重试")
        normalized_now = self.utc(transaction_now)
        assert normalized_now is not None
        if prepared_at + timedelta(minutes=self.baseline_max_age_minutes) < normalized_now:
            raise ProductTrafficConflict("T0 已超过 30 分钟，请重新刷新或填写")
        allowed_sources = (
            {"remote_refresh", "manual", "legacy_snapshot"}
            if legacy_internal
            else {"remote_refresh", "manual"}
        )
        if not batch_items or any(
            item.baseline_captured_at is None
            or item.baseline_source not in allowed_sources
            for item in batch_items
        ):
            raise ProductTrafficConflict("整批 T0 尚未准备完成")
        started_at = self.minute_utc(normalized_now)
        batch.started_at = started_at
        batch.status = "running"
        batch.updated_at = normalized_now
        return started_at

    @staticmethod
    def require_actual_overlap_recordable(batch: ProductTrafficBatch) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.status != "planned":
            raise ProductTrafficConflict("只有尚未开始的批次可以补记实际投放")

    @staticmethod
    def validate_actual_overlap_request(
        *,
        confirmed_already_purchased: bool,
        actual_started_at: datetime | None,
    ) -> None:
        if not confirmed_already_purchased:
            raise ProductTrafficConflict("请先确认这笔曝光已经在闲鱼真实购买")
        if actual_started_at is not None:
            raise ProductTrafficConflict(
                "实际投放时间改为确认时由系统记录，请刷新页面后重新确认"
            )

    @staticmethod
    def apply_actual_overlap_start(
        batch: ProductTrafficBatch,
        batch_items: list[ProductTrafficBatchItem],
        *,
        manual_values: dict[int, tuple[int, int, int, int]] | None,
        started_at: datetime,
        transaction_now: datetime,
    ) -> str:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if manual_values:
            for batch_item in batch_items:
                (
                    batch_item.baseline_browse_count,
                    batch_item.baseline_collect_count,
                    batch_item.baseline_want_count,
                    batch_item.baseline_inquiry_count,
                ) = manual_values[batch_item.item_id]
                batch_item.baseline_captured_at = started_at
                batch_item.baseline_source = "manual"
            batch.baseline_prepared_at = started_at
            baseline_source = "manual"
        else:
            for batch_item in batch_items:
                batch_item.baseline_browse_count = 0
                batch_item.baseline_collect_count = 0
                batch_item.baseline_want_count = 0
                batch_item.baseline_inquiry_count = 0
                batch_item.baseline_captured_at = None
                batch_item.baseline_source = "missing"
            batch.baseline_prepared_at = None
            baseline_source = "missing"
        batch.started_at = started_at
        batch.status = "running"
        batch.recording_mode = "actual_overlap"
        batch.attribution_status = "overlap"
        batch.updated_at = transaction_now
        return baseline_source

    @staticmethod
    def complete(
        batch: ProductTrafficBatch,
        *,
        completed_at: datetime,
        actual_cost: float,
        total_exposure: int | None,
        note: str,
        allow_legacy_fixture: bool = False,
    ) -> None:
        if not allow_legacy_fixture:
            ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.status == "invalidated":
            raise ProductTrafficConflict(
                "该批次已因基线无效终止观察，不能再记录套餐完成"
            )
        if batch.status == "planned":
            raise ProductTrafficConflict("请先点击“开始批次”记录 T0 基线")
        if batch.status == "cancelled":
            raise ProductTrafficConflict("已取消的批次不能记录完成")
        batch.completed_at = completed_at
        batch.actual_cost = round(actual_cost, 2)
        batch.total_exposure = total_exposure
        if note.strip():
            batch.note = note.strip()
        if batch.status != "closed":
            batch.status = "observing"

    def baseline_invalidation_reason(
        self,
        batch: ProductTrafficBatch,
        batch_items: list[ProductTrafficBatchItem],
    ) -> str | None:
        if (
            batch.started_at is None
            or batch.status not in {"running", "observing", "closed"}
            or not batch_items
        ):
            return None
        if batch.attribution_status == "exploratory":
            return None
        if any(
            item.baseline_captured_at is None
            or item.baseline_source in {"missing", "pending"}
            for item in batch_items
        ):
            return "missing_baseline"
        if any(item.baseline_source == "legacy_snapshot" for item in batch_items):
            return "legacy_baseline"
        started_at = self.minute_utc(batch.started_at)
        captured_minutes = [
            self.minute_utc(item.baseline_captured_at)
            for item in batch_items
            if item.baseline_captured_at is not None
        ]
        if len(captured_minutes) != len(batch_items):
            return "missing_baseline"
        if any(captured_at > started_at for captured_at in captured_minutes):
            return "invalid_baseline_time"
        oldest_age = max(
            int((started_at - captured_at).total_seconds() // 60)
            for captured_at in captured_minutes
        )
        if oldest_age > self.baseline_max_age_minutes:
            return "stale_baseline"
        return None

    @staticmethod
    def invalidate(
        batch: ProductTrafficBatch,
        jobs: list[ProductTrafficCheckpointJob],
        *,
        reason: str,
        invalidated_at: datetime,
    ) -> bool:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.status == "invalidated":
            return False
        batch.status = "invalidated"
        batch.invalidated_at = invalidated_at
        batch.invalidation_reason = reason
        batch.updated_at = invalidated_at
        for job in jobs:
            job.status = "missed"
            job.last_error_code = "baseline_invalidated"
            job.last_error_detail = "基线无效，检查点任务已停止"
            job.completed_at = invalidated_at
            job.updated_at = invalidated_at
        return True

    @staticmethod
    def ensure_checkpoint_jobs_in_session(
        session,
        batch: ProductTrafficBatch,
        *,
        now: datetime,
        allow_legacy_fixture: bool = False,
    ) -> list[ProductTrafficCheckpointJob]:
        if not allow_legacy_fixture:
            ProductTrafficLifecycle.require_current_protocol(batch)
        started_at = ProductTrafficLifecycle.utc(batch.started_at)
        if started_at is None or batch.status in {"planned", "cancelled", "invalidated"}:
            return []
        batch_items = session.scalars(
            select(ProductTrafficBatchItem)
            .where(ProductTrafficBatchItem.batch_id == batch.id)
            .order_by(ProductTrafficBatchItem.position)
        ).all()
        existing = {
            row.checkpoint: row
            for row in session.scalars(
                select(ProductTrafficCheckpointJob).where(
                    ProductTrafficCheckpointJob.batch_id == batch.id
                )
            ).all()
        }
        jobs: list[ProductTrafficCheckpointJob] = []
        for checkpoint in ProductTrafficProtocol.checkpoint_order(batch):
            job = existing.get(checkpoint)
            if job is None:
                job = ProductTrafficCheckpointJob(
                    id=f"traffic-checkpoint-job-{uuid4()}",
                    batch_id=batch.id,
                    checkpoint=checkpoint,
                    scheduled_for=started_at + timedelta(hours=CHECKPOINT_HOURS[checkpoint]),
                    status="scheduled",
                    total_count=len(batch_items),
                    created_at=now,
                    updated_at=now,
                )
                session.add(job)
                session.flush()
                for batch_item in batch_items:
                    session.add(
                        ProductTrafficCheckpointJobItem(
                            job_id=job.id,
                            item_id=batch_item.item_id,
                            status="pending",
                            created_at=now,
                            updated_at=now,
                        )
                    )
            jobs.append(job)
        return jobs

    @staticmethod
    def _validate_checkpoint_counts(
        batch_item: ProductTrafficBatchItem,
        *,
        checkpoint: str,
        checkpoint_order: tuple[str, ...],
        submitted_counts: tuple[int, int, int, int],
        other_checkpoints: list[ProductTrafficCheckpoint],
    ) -> None:
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
        submitted_rank = checkpoint_order.index(checkpoint)
        for other in other_checkpoints:
            if other.checkpoint not in checkpoint_order:
                continue
            other_rank = checkpoint_order.index(other.checkpoint)
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

    def record_checkpoint_in_session(
        self,
        session,
        batch: ProductTrafficBatch,
        *,
        checkpoint: str,
        recorded_at: datetime | None,
        items: list[dict],
        note: str,
        now: datetime,
        datetime_label: Callable[[datetime], str],
        allow_legacy_fixture: bool = False,
    ) -> datetime:
        if not allow_legacy_fixture:
            self.require_current_protocol(batch)
        if checkpoint not in CHECKPOINT_HOURS:
            raise ProductTrafficConflict("不支持的观察检查点")
        checkpoint_order = ProductTrafficProtocol.checkpoint_order(batch)
        if checkpoint not in checkpoint_order:
            raise ProductTrafficConflict("该批次协议不包含这个观察检查点")
        if batch.status == "invalidated":
            raise ProductTrafficConflict(
                "该批次已因基线无效终止观察，不能新增或修改检查点"
            )
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
        recorded = self.utc(recorded_at) or self.utc(now)
        started_at = self.utc(batch.started_at)
        if started_at is None:
            raise ProductTrafficConflict("批次缺少实际开始时间，不能记录检查点")
        assert recorded is not None
        due_at = started_at + timedelta(hours=CHECKPOINT_HOURS[checkpoint])
        if recorded < due_at:
            raise ProductTrafficConflict(
                f"{checkpoint.upper()} 尚未到记录时间；最早可在北京时间 "
                f"{datetime_label(due_at)} 保存"
            )
        normalized_now = self.utc(now)
        assert normalized_now is not None
        if recorded > normalized_now + timedelta(minutes=5):
            raise ProductTrafficConflict("检查点记录时间不能晚于当前北京时间")
        for value in items:
            batch_item = by_external_id[str(value["external_id"])]
            submitted_counts = (
                int(value["browse_count"]),
                int(value.get("collect_count", 0)),
                int(value.get("want_count", 0)),
                int(value.get("inquiry_count", 0)),
            )
            other_checkpoints = session.scalars(
                select(ProductTrafficCheckpoint).where(
                    ProductTrafficCheckpoint.batch_id == batch.id,
                    ProductTrafficCheckpoint.item_id == batch_item.item_id,
                    ProductTrafficCheckpoint.checkpoint != checkpoint,
                )
            ).all()
            self._validate_checkpoint_counts(
                batch_item,
                checkpoint=checkpoint,
                checkpoint_order=checkpoint_order,
                submitted_counts=submitted_counts,
                other_checkpoints=other_checkpoints,
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
        job = session.scalar(
            select(ProductTrafficCheckpointJob).where(
                ProductTrafficCheckpointJob.batch_id == batch.id,
                ProductTrafficCheckpointJob.checkpoint == checkpoint,
            )
        )
        if job is not None:
            job_rows = session.scalars(
                select(ProductTrafficCheckpointJobItem).where(
                    ProductTrafficCheckpointJobItem.job_id == job.id
                )
            ).all()
            for row in job_rows:
                row.status = "completed"
                row.captured_at = recorded
                row.error_code = None
                row.error_detail = ""
                row.updated_at = recorded
            job.status = "completed"
            job.collected_count = len(job_rows)
            job.total_count = len(job_rows)
            job.captured_at = recorded
            job.completed_at = recorded
            scheduled_for = self.utc(job.scheduled_for)
            assert scheduled_for is not None
            job.capture_delay_minutes = max(
                0,
                int((recorded - scheduled_for).total_seconds() // 60),
            )
            job.last_error_code = None
            job.last_error_detail = ""
            job.updated_at = recorded
        if checkpoint == ProductTrafficProtocol.terminal_checkpoint(batch):
            batch.status = "closed"
        elif batch.status == "running":
            batch.status = "observing"
        return recorded

    @staticmethod
    def update_checkpoint_collection_mode(
        batch: ProductTrafficBatch,
        jobs: list[ProductTrafficCheckpointJob],
        *,
        mode: str,
        now: datetime,
    ) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        ProductTrafficLifecycle.validate_checkpoint_collection_mode(mode)
        if batch.status in {"cancelled", "invalidated", "closed"}:
            raise ProductTrafficConflict("该批次已结束，不能修改采集方式")
        batch.checkpoint_collection_mode = mode
        batch.updated_at = now
        for job in jobs:
            if job.status == "completed":
                continue
            scheduled_for = ProductTrafficLifecycle.utc(job.scheduled_for)
            assert scheduled_for is not None
            if mode == "manual" and scheduled_for <= now:
                job.status = "waiting_manual"
            elif mode == "auto" and job.status == "waiting_manual" and job.attempt_count == 0:
                job.status = "scheduled"
            job.updated_at = now

    @staticmethod
    def require_checkpoint_mode_mutable(batch: ProductTrafficBatch) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.status in {"cancelled", "invalidated", "closed"}:
            raise ProductTrafficConflict("该批次已结束，不能修改采集方式")

    @staticmethod
    def cancel(batch: ProductTrafficBatch) -> None:
        ProductTrafficLifecycle.require_current_protocol(batch)
        if batch.status == "invalidated":
            raise ProductTrafficConflict(
                "该批次已因基线无效终止观察，必须保留终止状态和真实投放事实"
            )
        if batch.status in {"running", "observing", "closed"}:
            raise ProductTrafficConflict("已经开始的批次不能取消，可继续补齐观察数据")
        batch.status = "cancelled"


@dataclass(frozen=True, slots=True)
class ProductTrafficAttributionDecision:
    reliable_baseline: bool
    baseline_expires_at: datetime | None
    baseline_age_minutes: int | None
    baseline_status: str
    baseline_status_label: str
    baseline_quality: str
    baseline_quality_label: str
    baseline_quality_detail: str
    data_quality: str
    analysis_eligible: bool
    analysis_tier: str
    analysis_tier_label: str
    analysis_confidence: str


class ProductTrafficAttribution:
    """Pure operating metrics; these never imply platform causality."""

    @staticmethod
    def conversion(inquiries: int, browses: int) -> float | None:
        if browses <= 0:
            return None
        return round(inquiries / browses * 100, 2)

    @staticmethod
    def unit_cost(cost: float, increment: int) -> float | None:
        if increment <= 0:
            return None
        return round(cost / increment, 2)

    @staticmethod
    def overlap_window_hours(target_window: int, source_window: int | None) -> int:
        """Use the longer protocol whenever 48h and 72h histories interact."""

        return max(
            ProductTrafficProtocol.normalize_window_hours(target_window),
            ProductTrafficProtocol.normalize_window_hours(source_window),
        )

    @staticmethod
    def checkpoint_capture_is_late(
        job: ProductTrafficCheckpointJob | None,
        checkpoint: str | None,
    ) -> bool:
        return bool(
            job
            and checkpoint
            and job.capture_delay_minutes is not None
            and job.capture_delay_minutes
            > CHECKPOINT_MAX_DELAY_MINUTES.get(checkpoint, 0)
        )

    @staticmethod
    def checkpoint_series_is_inconsistent(
        batch_items: list[ProductTrafficBatchItem],
        checkpoints_by_item: dict[int, list[ProductTrafficCheckpoint]],
        checkpoint_rank: dict[str, int],
    ) -> bool:
        for batch_item in batch_items:
            previous = (
                batch_item.baseline_browse_count,
                batch_item.baseline_collect_count,
                batch_item.baseline_want_count,
                batch_item.baseline_inquiry_count,
            )
            for checkpoint in sorted(
                checkpoints_by_item.get(batch_item.item_id, []),
                key=lambda value: checkpoint_rank.get(value.checkpoint, -1),
            ):
                current = (
                    checkpoint.browse_count,
                    checkpoint.collect_count,
                    checkpoint.want_count,
                    checkpoint.inquiry_count,
                )
                if any(
                    current_value is not None
                    and previous_value is not None
                    and current_value < previous_value
                    for current_value, previous_value in zip(current, previous)
                ):
                    return True
                previous = tuple(
                    current_value if current_value is not None else previous_value
                    for current_value, previous_value in zip(current, previous)
                )
        return False

    @staticmethod
    def classify(
        batch: ProductTrafficBatch,
        batch_items: list[ProductTrafficBatchItem],
        *,
        now: datetime,
        baseline_max_age_minutes: int,
        observation_checkpoint: str | None,
        terminal_checkpoint: str,
        observation_window_hours: int,
        checkpoint_capture_late: bool,
        attribution_overlap: bool,
        inconsistent: bool,
        exploratory_available: bool,
        invalidation_reason_label: str,
    ) -> ProductTrafficAttributionDecision:
        """Return one auditable eligibility decision without database writes."""

        started_at = ProductTrafficLifecycle.utc(batch.started_at)
        is_invalidated = batch.status == "invalidated"
        baseline_missing = bool(started_at) and any(
            value.baseline_captured_at is None for value in batch_items
        )
        baseline_ages = [
            max(
                0,
                int(
                    (
                        started_at
                        - (
                            ProductTrafficLifecycle.utc(value.baseline_captured_at)
                            or started_at
                        )
                    ).total_seconds()
                    // 60
                ),
            )
            for value in batch_items
            if started_at and value.baseline_captured_at is not None
        ]
        baseline_age_minutes = max(baseline_ages) if baseline_ages else None
        prepared_at = ProductTrafficLifecycle.utc(batch.baseline_prepared_at)
        baseline_expires_at = (
            prepared_at + timedelta(minutes=baseline_max_age_minutes)
            if prepared_at
            else None
        )
        baseline_sources = {value.baseline_source for value in batch_items}
        exploratory_baseline = bool(
            batch.attribution_status == "exploratory"
            or "daily_exploratory" in baseline_sources
        )
        baseline_complete = bool(batch_items) and all(
            value.baseline_captured_at is not None
            and value.baseline_source
            in {"remote_refresh", "manual", "legacy_snapshot", "daily_exploratory"}
            for value in batch_items
        )
        reliable_baseline = bool(batch_items) and not is_invalidated and all(
            value.baseline_captured_at is not None
            and value.baseline_source in {"remote_refresh", "manual"}
            for value in batch_items
        )
        baseline_fresh_now = bool(
            prepared_at
            and baseline_complete
            and baseline_expires_at
            and ProductTrafficLifecycle.utc(now) <= baseline_expires_at
        )
        if is_invalidated:
            baseline_status = "invalidated"
            baseline_status_label = "基线无效 · 已终止观察"
        elif batch.status != "planned":
            baseline_status = (
                "exploratory"
                if exploratory_baseline
                else "legacy"
                if "legacy_snapshot" in baseline_sources
                else "used"
            )
            baseline_status_label = (
                "早间参考基线 · 探索观察"
                if baseline_status == "exploratory"
                else "历史基线"
                if baseline_status == "legacy"
                else "已用于实际投放"
            )
        elif not baseline_complete or prepared_at is None:
            baseline_status = "pending"
            baseline_status_label = "待准备 T0"
        elif not baseline_fresh_now:
            baseline_status = "expired"
            baseline_status_label = "T0 已过期"
        else:
            baseline_status = "ready"
            baseline_status_label = "T0 已就绪"
        legacy_baseline = "legacy_snapshot" in baseline_sources
        baseline_stale = legacy_baseline or (
            bool(started_at)
            and bool(
                baseline_age_minutes is not None
                and baseline_age_minutes > baseline_max_age_minutes
            )
        )
        if is_invalidated:
            baseline_quality = "invalidated"
            baseline_quality_label = "基线无效 · 已终止观察"
            baseline_quality_detail = (
                f"{invalidation_reason_label}；真实费用、投放时间、商品组合和已有记录均保留，"
                "但不会再产生检查点提醒或经营结论"
            )
        elif exploratory_baseline:
            baseline_quality = "exploratory"
            baseline_quality_label = "早间参考基线 · 低置信"
            baseline_quality_detail = (
                f"参考快照距实际投放约 {baseline_age_minutes or 0} 分钟；"
                "允许继续采集和生成方向性观察，但自然增长不能解释为曝光贡献，"
                "且永久排除预算、时段、复投和商品优先级结论"
            )
        elif batch.status == "planned":
            baseline_quality = baseline_status
            baseline_quality_label = baseline_status_label
            baseline_quality_detail = (
                "T0 已准备，可在 30 分钟内完成人工投放并开始计时"
                if baseline_status == "ready"
                else "T0 已超过 30 分钟，需要重新刷新或重新填写"
                if baseline_status == "expired"
                else "先刷新整批 T0；远程失败时可人工填写全部商品"
            )
        elif baseline_missing:
            baseline_quality = "missing"
            baseline_quality_label = "缺少 T0"
            baseline_quality_detail = "没有可审计的投放前快照，不能进入经营结论"
        elif baseline_stale:
            baseline_quality = "weak"
            baseline_quality_label = "历史 T0" if legacy_baseline else "T0 偏旧"
            baseline_quality_detail = (
                "该批次沿用 v2.4 之前的历史快照，数据继续保留，"
                "但不能进入成熟结论或获得商品复投资格"
                if legacy_baseline
                else (
                    f"T0 距实际投放约 {baseline_age_minutes} 分钟，超过 "
                    f"{baseline_max_age_minutes} 分钟门槛；"
                    "数据继续保留，但不进入成熟结论"
                )
            )
        else:
            baseline_quality = "fresh"
            baseline_quality_label = "T0 新鲜"
            baseline_quality_detail = (
                f"T0 距实际投放约 {baseline_age_minutes or 0} 分钟，"
                "可继续完成长尾观察"
            )

        if is_invalidated:
            data_quality = "invalidated"
        elif batch.status == "planned":
            data_quality = "planned"
        elif exploratory_baseline:
            data_quality = "exploratory_baseline"
        elif batch.attribution_status in {"overlap", "cohort_overlap"}:
            data_quality = "confounded"
        elif baseline_missing:
            data_quality = "missing_baseline"
        elif inconsistent:
            data_quality = "inconsistent"
        elif checkpoint_capture_late:
            data_quality = "late_capture"
        elif attribution_overlap:
            data_quality = "confounded"
        elif baseline_stale:
            data_quality = "stale_baseline"
        elif observation_checkpoint in (
            {"h24", "h72"}
            if observation_window_hours == 72
            else {terminal_checkpoint}
        ):
            data_quality = "mature"
        elif observation_checkpoint:
            data_quality = "early"
        else:
            data_quality = "baseline"
        analysis_eligible = data_quality == "mature" and not is_invalidated
        analysis_tier = (
            "decision_grade"
            if analysis_eligible
            else "exploratory"
            if exploratory_available
            else "fact_only"
        )
        analysis_tier_label = {
            "decision_grade": "决策级分析",
            "exploratory": "探索性分析",
            "fact_only": "事实记录",
        }[analysis_tier]
        analysis_confidence = (
            "high"
            if analysis_eligible and observation_checkpoint == terminal_checkpoint
            else "medium"
            if analysis_eligible
            else "low"
        )
        return ProductTrafficAttributionDecision(
            reliable_baseline=reliable_baseline,
            baseline_expires_at=baseline_expires_at,
            baseline_age_minutes=baseline_age_minutes,
            baseline_status=baseline_status,
            baseline_status_label=baseline_status_label,
            baseline_quality=baseline_quality,
            baseline_quality_label=baseline_quality_label,
            baseline_quality_detail=baseline_quality_detail,
            data_quality=data_quality,
            analysis_eligible=analysis_eligible,
            analysis_tier=analysis_tier,
            analysis_tier_label=analysis_tier_label,
            analysis_confidence=analysis_confidence,
        )


class ProductTrafficAccounting:
    """Canonical one-expense-per-batch ledger adapter."""

    def __init__(self, ledger: LedgerService | None) -> None:
        self.ledger = ledger

    def sync_expense_in_session(
        self,
        session,
        batch: ProductTrafficBatch,
        *,
        localize: Callable[[datetime | None], datetime | None],
        now: Callable[[], datetime],
        allow_legacy_fixture: bool = False,
    ) -> tuple[int | None, bool]:
        if not allow_legacy_fixture:
            ProductTrafficLifecycle.require_current_protocol(batch)
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
        paid_at = localize(batch.started_at)
        return self.ledger.upsert_system_expense_in_session(
            session,
            expense_id=f"expense-traffic-{batch.id}",
            name=f"闲鱼曝光批次 · {product_count} 件商品",
            category="traffic",
            amount=batch.actual_cost,
            paid_at=(paid_at or now()).isoformat(),
            notes="商品经营自动记账；一笔费用对应整个多商品曝光批次。",
        )
