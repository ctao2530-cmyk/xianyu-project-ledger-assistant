from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models import (
    ProductTrafficBatch,
    ProductTrafficBatchItem,
    ProductTrafficCheckpoint,
    ProductTrafficCheckpointJob,
)
from backend.app.services.product_traffic_domain import (
    ACTUAL_CHECKPOINT_ORDER,
    LEGACY_CHECKPOINT_ORDER,
    ProductTrafficAccounting,
    ProductTrafficAttribution,
    ProductTrafficConflict,
    ProductTrafficLifecycle,
    ProductTrafficProtocol,
)


def traffic_batch(window: int) -> ProductTrafficBatch:
    return ProductTrafficBatch(
        id=f"traffic-domain-{window}",
        request_id=f"traffic-domain-{window}",
        status="observing",
        planned_at=datetime(2026, 8, 30, 4, 5, tzinfo=timezone.utc),
        started_at=datetime(2026, 8, 30, 4, 5, tzinfo=timezone.utc),
        actual_cost=5.9,
        observation_window_hours=window,
    )


def test_protocol_keeps_new_48h_and_legacy_72h_sequences_immutable() -> None:
    current = traffic_batch(48)
    legacy = traffic_batch(72)

    assert ProductTrafficProtocol.observation_window_hours(current) == 48
    assert ProductTrafficProtocol.checkpoint_order(current) == ACTUAL_CHECKPOINT_ORDER
    assert ProductTrafficProtocol.terminal_checkpoint(current) == "h48"
    assert ProductTrafficProtocol.observation_window_hours(legacy) == 72
    assert ProductTrafficProtocol.checkpoint_order(legacy) == LEGACY_CHECKPOINT_ORDER
    assert ProductTrafficProtocol.terminal_checkpoint(legacy) == "h72"


def test_attribution_metrics_remain_descriptive_and_guard_zero_denominators() -> None:
    assert ProductTrafficAttribution.conversion(2, 20) == 10
    assert ProductTrafficAttribution.conversion(2, 0) is None
    assert ProductTrafficAttribution.unit_cost(5.9, 10) == 0.59
    assert ProductTrafficAttribution.unit_cost(5.9, 0) is None


def test_attribution_domain_owns_mixed_windows_lateness_and_consistency() -> None:
    assert ProductTrafficAttribution.overlap_window_hours(48, 48) == 48
    assert ProductTrafficAttribution.overlap_window_hours(48, 72) == 72
    job = ProductTrafficCheckpointJob(
        id="domain-late-job",
        batch_id="domain-late-batch",
        checkpoint="h1",
        scheduled_for=datetime(2026, 8, 30, 5, 0, tzinfo=timezone.utc),
        capture_delay_minutes=31,
    )
    assert ProductTrafficAttribution.checkpoint_capture_is_late(job, "h1") is True
    job.capture_delay_minutes = 30
    assert ProductTrafficAttribution.checkpoint_capture_is_late(job, "h1") is False

    item = ProductTrafficBatchItem(
        batch_id="domain-series",
        item_id=1,
        position=0,
        baseline_browse_count=10,
    )
    decreasing = ProductTrafficCheckpoint(
        id="domain-series-h1",
        batch_id=item.batch_id,
        item_id=item.item_id,
        checkpoint="h1",
        browse_count=9,
        recorded_at=datetime(2026, 8, 30, 5, 0, tzinfo=timezone.utc),
    )
    assert ProductTrafficAttribution.checkpoint_series_is_inconsistent(
        [item],
        {item.item_id: [decreasing]},
        {"h1": 0},
    ) is True
    decreasing.browse_count = 11
    assert ProductTrafficAttribution.checkpoint_series_is_inconsistent(
        [item],
        {item.item_id: [decreasing]},
        {"h1": 0},
    ) is False


def test_attribution_domain_owns_maturity_and_invalid_baseline_eligibility() -> None:
    started_at = datetime(2026, 8, 30, 4, 5, tzinfo=timezone.utc)
    batch = traffic_batch(48)
    batch.status = "closed"
    batch.baseline_prepared_at = started_at
    batch_items = [
        ProductTrafficBatchItem(
            batch_id=batch.id,
            item_id=1,
            position=0,
            baseline_browse_count=10,
            baseline_captured_at=started_at,
            baseline_source="remote_refresh",
        )
    ]
    mature = ProductTrafficAttribution.classify(
        batch,
        batch_items,
        now=started_at,
        baseline_max_age_minutes=30,
        observation_checkpoint="h48",
        terminal_checkpoint="h48",
        observation_window_hours=48,
        checkpoint_capture_late=False,
        attribution_overlap=False,
        inconsistent=False,
        exploratory_available=False,
        invalidation_reason_label="",
    )
    assert mature.data_quality == "mature"
    assert mature.analysis_eligible is True
    assert mature.analysis_tier == "decision_grade"

    batch.status = "invalidated"
    batch.invalidation_reason = "missing_baseline"
    invalidated = ProductTrafficAttribution.classify(
        batch,
        batch_items,
        now=started_at,
        baseline_max_age_minutes=30,
        observation_checkpoint="h48",
        terminal_checkpoint="h48",
        observation_window_hours=48,
        checkpoint_capture_late=False,
        attribution_overlap=False,
        inconsistent=False,
        exploratory_available=False,
        invalidation_reason_label="缺少投放前 T0",
    )
    assert invalidated.data_quality == "invalidated"
    assert invalidated.analysis_eligible is False
    assert invalidated.analysis_tier == "fact_only"


def test_lifecycle_owns_current_protocol_and_actual_purchase_guards() -> None:
    lifecycle = ProductTrafficLifecycle(baseline_max_age_minutes=30)

    lifecycle.require_current_protocol(traffic_batch(48))
    with pytest.raises(ProductTrafficConflict, match="历史 72h"):
        lifecycle.require_current_protocol(traffic_batch(72))
    with pytest.raises(ProductTrafficConflict, match="真实购买"):
        lifecycle.validate_record_now_request(
            item_external_ids=["item-1"],
            confirmed_already_purchased=False,
            plan_slot_id=None,
            checkpoint_collection_mode="auto",
            max_items=5,
        )


def test_every_domain_mutator_rejects_legacy_72h_without_partial_changes() -> None:
    lifecycle = ProductTrafficLifecycle(baseline_max_age_minutes=30)
    now = datetime(2026, 8, 30, 6, 0, tzinfo=timezone.utc)
    job = ProductTrafficCheckpointJob(
        id="legacy-domain-job",
        batch_id="traffic-domain-72",
        checkpoint="h1",
        scheduled_for=now,
        status="scheduled",
    )
    item = ProductTrafficBatchItem(
        batch_id="traffic-domain-72",
        item_id=1,
        position=0,
    )
    calls = [
        lambda batch: lifecycle.mark_overlap(batch, has_overlap=True),
        lambda batch: lifecycle.require_replannable(batch),
        lambda batch: lifecycle.apply_replan(batch, planned_at=now, changed_at=now),
        lambda batch: lifecycle.correct_start_from_created_at(
            batch,
            expected_created_at=batch.created_at,
            expected_started_at=batch.started_at,
            transaction_now=now,
        ),
        lambda batch: lifecycle.require_exploratory_restorable(batch),
        lambda batch: lifecycle.restore_exploratory_baseline(
            batch,
            [item],
            snapshot_by_item={},
            transaction_now=now,
        ),
        lambda batch: lifecycle.restore_invalidated_jobs(
            batch,
            [job],
            transaction_now=now,
        ),
        lambda batch: lifecycle.require_baseline_preparable(batch),
        lambda batch: lifecycle.apply_baseline(
            batch,
            [item],
            values={},
            source="manual",
            captured_at=now,
        ),
        lambda batch: lifecycle.apply_start(
            batch,
            [item],
            expected_updated_at=batch.updated_at,
            expected_baseline_captured_at=now,
            transaction_now=now,
            blocked_reason=None,
            legacy_internal=False,
        ),
        lambda batch: lifecycle.require_actual_overlap_recordable(batch),
        lambda batch: lifecycle.apply_actual_overlap_start(
            batch,
            [item],
            manual_values=None,
            started_at=now,
            transaction_now=now,
        ),
        lambda batch: lifecycle.complete(
            batch,
            completed_at=now,
            actual_cost=6,
            total_exposure=100,
            note="",
        ),
        lambda batch: lifecycle.invalidate(
            batch,
            [job],
            reason="missing_baseline",
            invalidated_at=now,
        ),
        lambda batch: lifecycle.ensure_checkpoint_jobs_in_session(
            object(),
            batch,
            now=now,
        ),
        lambda batch: lifecycle.record_checkpoint_in_session(
            object(),
            batch,
            checkpoint="h1",
            recorded_at=now + timedelta(hours=1),
            items=[],
            note="",
            now=now + timedelta(hours=1),
            datetime_label=str,
        ),
        lambda batch: lifecycle.require_checkpoint_mode_mutable(batch),
        lambda batch: lifecycle.update_checkpoint_collection_mode(
            batch,
            [job],
            mode="manual",
            now=now,
        ),
        lambda batch: lifecycle.cancel(batch),
    ]
    for invoke in calls:
        batch = traffic_batch(72)
        before = (
            batch.status,
            batch.started_at,
            batch.completed_at,
            batch.updated_at,
            batch.recording_mode,
            batch.attribution_status,
        )
        with pytest.raises(ProductTrafficConflict, match="历史 72h"):
            invoke(batch)
        assert (
            batch.status,
            batch.started_at,
            batch.completed_at,
            batch.updated_at,
            batch.recording_mode,
            batch.attribution_status,
        ) == before

    accounting = ProductTrafficAccounting(None)
    with pytest.raises(ProductTrafficConflict, match="历史 72h"):
        accounting.sync_expense_in_session(
            object(),
            traffic_batch(72),
            localize=lambda value: value,
            now=lambda: now,
        )


def test_lifecycle_applies_start_completion_and_cancellation_transitions() -> None:
    lifecycle = ProductTrafficLifecycle(baseline_max_age_minutes=30)
    prepared_at = datetime(2026, 8, 30, 4, 0, tzinfo=timezone.utc)
    batch = ProductTrafficBatch(
        id="traffic-domain-start",
        request_id="traffic-domain-start",
        status="planned",
        planned_at=prepared_at,
        baseline_prepared_at=prepared_at,
        actual_cost=5.9,
        observation_window_hours=48,
        updated_at=prepared_at,
    )
    batch_items = [
        ProductTrafficBatchItem(
            batch_id=batch.id,
            item_id=1,
            position=0,
            baseline_browse_count=10,
            baseline_collect_count=1,
            baseline_want_count=1,
            baseline_inquiry_count=0,
            baseline_captured_at=prepared_at,
            baseline_source="manual",
        )
    ]

    started_at = lifecycle.apply_start(
        batch,
        batch_items,
        expected_updated_at=prepared_at,
        expected_baseline_captured_at=prepared_at,
        transaction_now=datetime(2026, 8, 30, 4, 5, 25, tzinfo=timezone.utc),
        blocked_reason=None,
        legacy_internal=False,
    )
    assert started_at == datetime(2026, 8, 30, 4, 5, tzinfo=timezone.utc)
    assert batch.status == "running"

    lifecycle.complete(
        batch,
        completed_at=datetime(2026, 8, 30, 5, 5, tzinfo=timezone.utc),
        actual_cost=6,
        total_exposure=120,
        note="套餐完成",
    )
    assert batch.status == "observing"
    assert batch.actual_cost == 6

    planned = ProductTrafficBatch(
        id="traffic-domain-cancel",
        request_id="traffic-domain-cancel",
        status="planned",
        planned_at=prepared_at,
        actual_cost=5.9,
        observation_window_hours=48,
    )
    lifecycle.cancel(planned)
    assert planned.status == "cancelled"

    legacy = ProductTrafficBatch(
        id="traffic-domain-cancel-legacy",
        request_id="traffic-domain-cancel-legacy",
        status="planned",
        planned_at=prepared_at,
        actual_cost=5.9,
        observation_window_hours=72,
    )
    with pytest.raises(ProductTrafficConflict, match="历史 72h"):
        lifecycle.cancel(legacy)
    assert legacy.status == "planned"


def test_lifecycle_rejects_stale_t0_before_start() -> None:
    lifecycle = ProductTrafficLifecycle(baseline_max_age_minutes=30)
    prepared_at = datetime(2026, 8, 30, 4, 0, tzinfo=timezone.utc)
    batch = ProductTrafficBatch(
        id="traffic-domain-stale",
        request_id="traffic-domain-stale",
        status="planned",
        planned_at=prepared_at,
        baseline_prepared_at=prepared_at,
        actual_cost=5.9,
        observation_window_hours=48,
        updated_at=prepared_at,
    )
    batch_items = [
        ProductTrafficBatchItem(
            batch_id=batch.id,
            item_id=1,
            position=0,
            baseline_captured_at=prepared_at,
            baseline_source="manual",
        )
    ]

    with pytest.raises(ProductTrafficConflict, match="超过 30 分钟"):
        lifecycle.apply_start(
            batch,
            batch_items,
            expected_updated_at=prepared_at,
            expected_baseline_captured_at=prepared_at,
            transaction_now=datetime(2026, 8, 30, 4, 31, tzinfo=timezone.utc),
            blocked_reason=None,
            legacy_internal=False,
        )
