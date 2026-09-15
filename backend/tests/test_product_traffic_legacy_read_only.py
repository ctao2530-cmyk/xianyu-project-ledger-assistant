from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from backend.app.adapters.base import ItemInfo
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.ledger import LedgerService
from backend.app.models import (
    BusinessExpense,
    Item,
    ProductDailySnapshot,
    ProductMonitor,
    ProductTrafficBatch,
    ProductTrafficBatchEvent,
    ProductTrafficBatchItem,
    ProductTrafficCheckpoint,
    ProductTrafficCheckpointJob,
    ProductTrafficCheckpointJobItem,
)
from backend.app.product_api import product_router
from backend.app.services.event_hub import EventHub
from backend.app.services.product_intelligence import (
    ProductIntelligenceService,
    ProductTrafficConflict,
)


LEGACY_ERROR = "历史 72h 曝光批次为只读记录，不能再修改、启动或重排"


class CountingAdapter:
    def __init__(self) -> None:
        self.own_user_id = "seller"
        self.calls: list[str] = []

    async def fetch_item(self, item_id: str) -> ItemInfo:
        self.calls.append(item_id)
        return ItemInfo(
            external_id=item_id,
            title="72h 历史商品",
            price="¥100",
            description="只读夹具",
            seller_id="seller",
            raw={
                "title": "72h 历史商品",
                "browseCnt": 99,
                "itemStatusStr": "在售",
                "trackParams": {"sellerId": "seller"},
            },
        )


def build_service(
    tmp_path: Path,
) -> tuple[Database, CountingAdapter, ProductIntelligenceService]:
    database_url = f"sqlite:///{tmp_path / 'legacy-read-only.db'}"
    database = Database(database_url)
    database.create_all()
    adapter = CountingAdapter()
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        xianyu_cookie=SecretStr("unb=seller; _m_h5_tk=token_suffix"),
        product_collection_request_delay_seconds=0,
        product_collection_check_interval_seconds=60,
    )
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    service = ProductIntelligenceService(
        database,
        adapter,
        settings,
        EventHub(),
        ledger=ledger,
    )
    return database, adapter, service


def seed_owned_item(database: Database, *, external_id: str) -> int:
    raw = {
        "title": "72h 历史商品",
        "browseCnt": 20,
        "itemStatusStr": "在售",
        "trackParams": {"sellerId": "seller"},
    }
    with database.session() as session:
        item = Item(
            external_id=external_id,
            title="72h 历史商品",
            price="¥100",
            description="只读夹具",
            raw_json=json.dumps(raw, ensure_ascii=False),
        )
        session.add(item)
        session.flush()
        session.add(
            ProductMonitor(
                item_id=item.id,
                source="manual",
                enabled=True,
                ownership_status="owned",
                ownership_source="test_seed",
            )
        )
        session.commit()
        return item.id


def seed_planned_legacy_batch(
    database: Database,
    service: ProductIntelligenceService,
    *,
    external_id: str,
    fixed: datetime,
) -> str:
    view = service.create_legacy_planned_traffic_batch_for_test(
        request_id="legacy-read-only-create",
        item_external_ids=[external_id],
        planned_at=fixed,
        actual_cost=5.9,
        plan_slot_id=None,
        note="原始历史事实",
        checkpoint_collection_mode="auto",
    )
    with database.session() as session:
        batch = session.get(ProductTrafficBatch, view.id)
        batch_item = session.scalar(
            select(ProductTrafficBatchItem).where(
                ProductTrafficBatchItem.batch_id == view.id
            )
        )
        assert batch is not None and batch_item is not None
        batch.created_at = fixed
        batch.updated_at = fixed
        session.add(
            ProductTrafficCheckpoint(
                id="legacy-read-only-checkpoint",
                batch_id=view.id,
                item_id=batch_item.item_id,
                checkpoint="h1",
                browse_count=25,
                collect_count=1,
                want_count=1,
                inquiry_count=1,
                recorded_at=fixed + timedelta(hours=1),
                source="manual",
                note="既有检查点",
            )
        )
        job = ProductTrafficCheckpointJob(
            id="legacy-read-only-job",
            batch_id=view.id,
            checkpoint="h6",
            scheduled_for=fixed + timedelta(hours=6),
            status="partial",
            attempt_count=1,
            collected_count=0,
            total_count=1,
            last_error_code="historical_partial",
            last_error_detail="历史任务保持不变",
            created_at=fixed,
            updated_at=fixed,
        )
        session.add(job)
        session.flush()
        session.add(
            ProductTrafficCheckpointJobItem(
                job_id=job.id,
                item_id=batch_item.item_id,
                status="pending",
                created_at=fixed,
                updated_at=fixed,
            )
        )
        session.add(
            ProductTrafficBatchEvent(
                id="legacy-read-only-event",
                batch_id=view.id,
                request_id="legacy-read-only-existing-event",
                event_type="historical_seed",
                payload_hash="0" * 64,
                summary_json='{"facts_preserved":true}',
                result_json='{"status":"planned"}',
                created_at=fixed,
            )
        )
        session.add(
            BusinessExpense(
                id=f"expense-traffic-{view.id}",
                name="72h 历史费用",
                category="traffic",
                amount=5.9,
                paid_at=fixed.isoformat(),
                notes="原始历史费用",
            )
        )
        session.commit()
    return view.id


def seed_observing_legacy_batch(
    database: Database,
    service: ProductIntelligenceService,
    *,
    external_id: str,
    fixed: datetime,
) -> str:
    view = service.create_legacy_planned_traffic_batch_for_test(
        request_id="legacy-observing-create",
        item_external_ids=[external_id],
        planned_at=fixed,
        actual_cost=5.9,
        plan_slot_id=None,
        note="观察中历史事实",
        checkpoint_collection_mode="auto",
    )
    with database.session() as session:
        batch = session.get(ProductTrafficBatch, view.id)
        batch_item = session.scalar(
            select(ProductTrafficBatchItem).where(
                ProductTrafficBatchItem.batch_id == view.id
            )
        )
        assert batch is not None and batch_item is not None
        batch.status = "observing"
        batch.started_at = fixed
        batch.baseline_prepared_at = fixed
        batch.created_at = fixed + timedelta(minutes=1)
        batch.updated_at = fixed
        batch_item.baseline_browse_count = 20
        batch_item.baseline_captured_at = fixed
        batch_item.baseline_source = "manual"
        job = ProductTrafficCheckpointJob(
            id="legacy-observing-job",
            batch_id=view.id,
            checkpoint="h1",
            scheduled_for=fixed + timedelta(hours=1),
            status="partial",
            attempt_count=1,
            collected_count=0,
            total_count=1,
            last_error_code="historical_partial",
            last_error_detail="历史任务保持不变",
            created_at=fixed,
            updated_at=fixed,
        )
        session.add(job)
        session.flush()
        session.add(
            ProductTrafficCheckpointJobItem(
                job_id=job.id,
                item_id=batch_item.item_id,
                status="pending",
                created_at=fixed,
                updated_at=fixed,
            )
        )
        session.commit()
    return view.id


def as_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def stored_state(database: Database, batch_id: str) -> dict:
    with database.session() as session:
        batch = session.get(ProductTrafficBatch, batch_id)
        assert batch is not None
        items = session.scalars(
            select(ProductTrafficBatchItem)
            .where(ProductTrafficBatchItem.batch_id == batch_id)
            .order_by(ProductTrafficBatchItem.id)
        ).all()
        item_ids = [row.item_id for row in items]
        checkpoints = session.scalars(
            select(ProductTrafficCheckpoint)
            .where(ProductTrafficCheckpoint.batch_id == batch_id)
            .order_by(ProductTrafficCheckpoint.id)
        ).all()
        jobs = session.scalars(
            select(ProductTrafficCheckpointJob)
            .where(ProductTrafficCheckpointJob.batch_id == batch_id)
            .order_by(ProductTrafficCheckpointJob.id)
        ).all()
        job_ids = [row.id for row in jobs]
        job_items = (
            session.scalars(
                select(ProductTrafficCheckpointJobItem)
                .where(ProductTrafficCheckpointJobItem.job_id.in_(job_ids))
                .order_by(ProductTrafficCheckpointJobItem.id)
            ).all()
            if job_ids
            else []
        )
        events = session.scalars(
            select(ProductTrafficBatchEvent)
            .where(ProductTrafficBatchEvent.batch_id == batch_id)
            .order_by(ProductTrafficBatchEvent.id)
        ).all()
        monitors = (
            session.scalars(
                select(ProductMonitor)
                .where(ProductMonitor.item_id.in_(item_ids))
                .order_by(ProductMonitor.id)
            ).all()
            if item_ids
            else []
        )
        snapshots = (
            session.scalars(
                select(ProductDailySnapshot)
                .where(ProductDailySnapshot.item_id.in_(item_ids))
                .order_by(ProductDailySnapshot.id)
            ).all()
            if item_ids
            else []
        )
        expense = session.get(BusinessExpense, f"expense-traffic-{batch_id}")
        return {
            "batch": (
                batch.status,
                as_iso(batch.started_at),
                as_iso(batch.completed_at),
                as_iso(batch.baseline_prepared_at),
                batch.recording_mode,
                batch.attribution_status,
                as_iso(batch.invalidated_at),
                batch.invalidation_reason,
                batch.checkpoint_collection_mode,
                batch.observation_window_hours,
                batch.actual_cost,
                batch.total_exposure,
                batch.note,
                as_iso(batch.created_at),
                as_iso(batch.updated_at),
            ),
            "items": [
                (
                    row.id,
                    row.item_id,
                    row.position,
                    row.baseline_browse_count,
                    row.baseline_collect_count,
                    row.baseline_want_count,
                    row.baseline_inquiry_count,
                    as_iso(row.baseline_captured_at),
                    row.baseline_source,
                )
                for row in items
            ],
            "checkpoints": [
                (
                    row.id,
                    row.item_id,
                    row.checkpoint,
                    row.browse_count,
                    row.collect_count,
                    row.want_count,
                    row.inquiry_count,
                    as_iso(row.recorded_at),
                    row.source,
                    row.note,
                )
                for row in checkpoints
            ],
            "jobs": [
                (
                    row.id,
                    row.checkpoint,
                    as_iso(row.scheduled_for),
                    row.status,
                    row.attempt_count,
                    row.collected_count,
                    row.total_count,
                    as_iso(row.started_at),
                    as_iso(row.captured_at),
                    as_iso(row.completed_at),
                    as_iso(row.last_attempt_at),
                    row.capture_delay_minutes,
                    row.last_error_code,
                    row.last_error_detail,
                    as_iso(row.updated_at),
                )
                for row in jobs
            ],
            "job_items": [
                (
                    row.id,
                    row.job_id,
                    row.item_id,
                    row.status,
                    as_iso(row.captured_at),
                    row.error_code,
                    row.error_detail,
                    as_iso(row.updated_at),
                )
                for row in job_items
            ],
            "events": [
                (
                    row.id,
                    row.request_id,
                    row.event_type,
                    row.payload_hash,
                    row.summary_json,
                    row.result_json,
                    as_iso(row.created_at),
                )
                for row in events
            ],
            "expense": (
                None
                if expense is None
                else (
                    expense.id,
                    expense.name,
                    expense.category,
                    expense.amount,
                    expense.paid_at,
                    expense.notes,
                )
            ),
            "monitors": [
                (
                    row.id,
                    row.enabled,
                    row.ownership_status,
                    as_iso(row.last_attempt_at),
                    row.last_collection_status,
                    row.last_error_code,
                    row.last_error_detail,
                    as_iso(row.updated_at),
                )
                for row in monitors
            ],
            "snapshots": [
                (row.id, row.snapshot_date, row.source, as_iso(row.captured_at))
                for row in snapshots
            ],
        }


@pytest.mark.asyncio
async def test_production_service_mutations_reject_legacy_and_preserve_all_facts(
    tmp_path: Path,
) -> None:
    database, adapter, service = build_service(tmp_path)
    external_id = "legacy-read-only-item"
    seed_owned_item(database, external_id=external_id)
    fixed = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
    batch_id = seed_planned_legacy_batch(
        database,
        service,
        external_id=external_id,
        fixed=fixed,
    )
    before = stored_state(database, batch_id)

    def rejected(callable_) -> None:
        with pytest.raises(ProductTrafficConflict, match="历史 72h") as caught:
            callable_()
        assert str(caught.value) == LEGACY_ERROR

    rejected(
        lambda: service.replan_traffic_batch(
            batch_id,
            request_id="legacy-replan-rejected",
            expected_updated_at=fixed,
            preview_hash="0" * 64,
        )
    )
    with pytest.raises(ProductTrafficConflict, match="历史 72h") as caught:
        await service.prepare_traffic_baseline(
            batch_id,
            request_id="legacy-baseline-rejected",
            expected_updated_at=fixed,
            mode="remote_refresh",
            items=[],
        )
    assert str(caught.value) == LEGACY_ERROR
    rejected(
        lambda: service.start_traffic_batch(
            batch_id,
            request_id="legacy-start-rejected",
            expected_updated_at=fixed,
            expected_baseline_captured_at=fixed,
        )
    )
    rejected(
        lambda: service.record_actual_overlap_start(
            batch_id,
            request_id="legacy-actual-rejected",
            expected_updated_at=fixed,
            actual_started_at=None,
            confirmed_already_purchased=True,
            items=[],
        )
    )
    rejected(
        lambda: service.complete_traffic_batch(
            batch_id,
            completed_at=fixed + timedelta(hours=1),
            actual_cost=99,
            total_exposure=999,
            note="不应覆盖",
        )
    )
    rejected(
        lambda: service.record_traffic_checkpoint(
            batch_id,
            checkpoint="h6",
            recorded_at=fixed + timedelta(hours=6),
            items=[
                {
                    "external_id": external_id,
                    "browse_count": 999,
                    "collect_count": 9,
                    "want_count": 9,
                    "inquiry_count": 9,
                }
            ],
            note="不应新增",
        )
    )
    rejected(
        lambda: service.update_traffic_checkpoint_collection_mode(
            batch_id,
            request_id="legacy-mode-rejected",
            expected_updated_at=fixed,
            mode="manual",
        )
    )
    with pytest.raises(ProductTrafficConflict, match="历史 72h") as caught:
        await service.retry_traffic_checkpoint_collection(
            batch_id,
            "h6",
            request_id="legacy-retry-rejected",
            expected_updated_at=fixed,
        )
    assert str(caught.value) == LEGACY_ERROR
    rejected(lambda: service.cancel_traffic_batch(batch_id))
    rejected(
        lambda: service.correct_traffic_batch_start_from_created_at(
            batch_id,
            request_id="legacy-correct-rejected",
            expected_created_at=fixed,
            expected_started_at=fixed,
        )
    )
    rejected(
        lambda: service.restore_traffic_batch_exploratory_observation(
            batch_id,
            request_id="legacy-restore-rejected",
            snapshot_date="2026-08-12",
        )
    )

    assert adapter.calls == []
    assert stored_state(database, batch_id) == before


def test_legacy_http_mutations_are_409_while_gets_and_capabilities_remain_read_only(
    tmp_path: Path,
) -> None:
    database, adapter, service = build_service(tmp_path)
    external_id = "legacy-read-only-item"
    seed_owned_item(database, external_id=external_id)
    fixed = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
    planned_id = seed_planned_legacy_batch(
        database,
        service,
        external_id=external_id,
        fixed=fixed,
    )
    observing_id = seed_observing_legacy_batch(
        database,
        service,
        external_id=external_id,
        fixed=fixed + timedelta(days=4),
    )
    before = stored_state(database, planned_id)

    app = FastAPI()
    app.state.runtime = SimpleNamespace(product_intelligence=service)
    app.include_router(product_router)
    client = TestClient(app)
    fixed_text = fixed.isoformat()
    item_payload = {
        "external_id": external_id,
        "browse_count": 30,
        "collect_count": 1,
        "want_count": 1,
        "inquiry_count": 1,
    }
    mutations: list[tuple[str, str, dict | None]] = [
        (
            "POST",
            f"/api/products/traffic-batches/{planned_id}/replan",
            {
                "request_id": "legacy-api-replan",
                "expected_updated_at": fixed_text,
                "preview_hash": "0" * 64,
            },
        ),
        (
            "POST",
            f"/api/products/traffic-batches/{planned_id}/baseline",
            {
                "request_id": "legacy-api-baseline",
                "expected_updated_at": fixed_text,
                "mode": "remote_refresh",
                "items": [],
            },
        ),
        (
            "POST",
            f"/api/products/traffic-batches/{planned_id}/start",
            {
                "request_id": "legacy-api-start",
                "expected_updated_at": fixed_text,
                "expected_baseline_captured_at": fixed_text,
            },
        ),
        (
            "POST",
            f"/api/products/traffic-batches/{planned_id}/actual-start",
            {
                "request_id": "legacy-api-actual",
                "expected_updated_at": fixed_text,
                "actual_started_at": None,
                "confirmed_already_purchased": True,
                "items": [],
            },
        ),
        (
            "POST",
            f"/api/products/traffic-batches/{planned_id}/complete",
            {
                "completed_at": (fixed + timedelta(hours=1)).isoformat(),
                "actual_cost": 99,
                "total_exposure": 999,
                "note": "不应覆盖",
            },
        ),
        (
            "POST",
            f"/api/products/traffic-batches/{planned_id}/checkpoints",
            {
                "checkpoint": "h6",
                "recorded_at": (fixed + timedelta(hours=6)).isoformat(),
                "items": [item_payload],
                "note": "不应新增",
            },
        ),
        (
            "PUT",
            f"/api/products/traffic-batches/{planned_id}/checkpoint-collection-mode",
            {
                "request_id": "legacy-api-mode",
                "expected_updated_at": fixed_text,
                "mode": "manual",
            },
        ),
        (
            "POST",
            f"/api/products/traffic-batches/{planned_id}/checkpoints/h6/retry",
            {
                "request_id": "legacy-api-retry",
                "expected_updated_at": fixed_text,
            },
        ),
        (
            "POST",
            f"/api/products/traffic-batches/{planned_id}/cancel",
            None,
        ),
    ]

    for method, path, payload in mutations:
        response = client.request(method, path, json=payload)
        assert response.status_code == 409, (method, path, response.text)
        assert response.json() == {"detail": LEGACY_ERROR}
        assert stored_state(database, planned_id) == before

    assert adapter.calls == []

    listing = client.get("/api/products/traffic-batches?limit=20")
    assert listing.status_code == 200
    by_id = {row["id"]: row for row in listing.json()["items"]}
    planned = by_id[planned_id]
    observing = by_id[observing_id]
    assert planned["is_legacy_protocol"] is True
    assert planned["observation_window_hours"] == 72
    assert planned["can_prepare_baseline"] is False
    assert planned["can_start"] is False
    assert observing["is_legacy_protocol"] is True
    assert observing["checkpoint_jobs"]
    assert all(job["can_retry_auto"] is False for job in observing["checkpoint_jobs"])
    assert all(
        job["can_complete_manually"] is False
        for job in observing["checkpoint_jobs"]
    )

    start_preview = client.get(
        f"/api/products/traffic-batches/{planned_id}/start-preview"
    )
    assert start_preview.status_code == 200
    assert start_preview.json()["batch"]["is_legacy_protocol"] is True
    assert start_preview.json()["can_start"] is False
