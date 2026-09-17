from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import func, select

from backend.app.business_analysis_repository import (
    BusinessAnalysisRepositoryError,
    RecommendationRequestConflict,
    RecommendationVersionConflict,
)
from backend.app.database import Database
from backend.app.ledger import LedgerService, default_snapshot
from backend.app.models import (
    BusinessAnalysisRecommendationEvent,
    BusinessAnalysisRecommendationRecord,
    Item,
    ProductDailySnapshot,
    ProductModificationExperiment,
    ProductMonitor,
)
from backend.app.services.business_analysis import BusinessAnalysisService
from backend.app.services.business_recommendations import (
    BusinessRecommendationService,
    BusinessRecommendationServiceError,
)


FIXED_NOW = datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_services(
    tmp_path: Path,
) -> tuple[Database, LedgerService, BusinessAnalysisService, BusinessRecommendationService]:
    database = Database(f"sqlite:///{tmp_path / 'recommendation-feedback.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    analysis = BusinessAnalysisService(database, ledger)
    return database, ledger, analysis, BusinessRecommendationService(database, analysis)


async def create_analysis(
    analysis: BusinessAnalysisService,
    *,
    request_id: str,
) -> str:
    result = await analysis.run_analysis(
        request_id=request_id,
        provider="deepseek",
        now=FIXED_NOW,
    )
    return result.recommendations[0].id


@pytest.mark.asyncio
async def test_stale_recommendation_cannot_be_accepted_but_can_be_ignored(
    tmp_path: Path,
) -> None:
    _, ledger, analysis, feedback = build_services(tmp_path)
    recommendation_id = await create_analysis(
        analysis,
        request_id="stale-analysis-request",
    )
    revision, snapshot = ledger.get()
    snapshot["expenses"].append(
        {
            "id": "stale-change-expense",
            "name": "事实变化",
            "category": "software",
            "amount": 12,
            "paidAt": "2026-08-11T13:00:00+08:00",
        }
    )
    ledger.save(snapshot, revision)

    with pytest.raises(BusinessRecommendationServiceError) as stale:
        feedback.update(
            recommendation_id,
            status="accepted",
            expected_version=1,
            request_id="stale-accept-request",
            note="",
            now=FIXED_NOW,
        )
    assert stale.value.code == "recommendation_stale"

    ignored = feedback.update(
        recommendation_id,
        status="ignored",
        expected_version=1,
        request_id="stale-ignore-request",
        note="事实已变化",
        now=FIXED_NOW,
    )
    assert ignored.status == "ignored"
    assert ignored.stale is True
    assert ignored.can_accept is False


@pytest.mark.asyncio
async def test_lifecycle_freezes_server_metrics_and_derives_review_due(
    tmp_path: Path,
) -> None:
    _, _, analysis, feedback = build_services(tmp_path)
    recommendation_id = await create_analysis(
        analysis,
        request_id="lifecycle-analysis-request",
    )
    accepted = feedback.update(
        recommendation_id,
        status="accepted",
        expected_version=1,
        request_id="lifecycle-accept-request",
        note="准备人工执行",
        now=FIXED_NOW,
    )
    assert accepted.status == "accepted"
    assert accepted.baseline_metrics is not None
    assert accepted.baseline_metrics.source_snapshot_hash
    assert accepted.accepted_at == FIXED_NOW

    started = feedback.start(
        recommendation_id,
        expected_version=2,
        request_id="lifecycle-start-request",
        now=FIXED_NOW,
    )
    assert started.status == "observing"
    assert started.observe_until is not None
    assert started.can_complete is False

    before_due_time = started.observe_until - timedelta(hours=1)
    after_due_time = started.observe_until + timedelta(hours=1)
    before_due = feedback.queue(now=before_due_time)
    assert before_due.counts.observing == 1
    assert before_due.counts.review_due == 0
    due = feedback.queue(now=after_due_time)
    assert due.counts.review_due == 1
    assert due.items[0].lifecycle_status == "review_due"
    assert due.items[0].can_complete is True

    with pytest.raises(BusinessRecommendationServiceError) as early:
        feedback.complete(
            recommendation_id,
            expected_version=3,
            request_id="lifecycle-complete-early",
            outcome="positive",
            actual_cost=None,
            actual_hours=None,
            user_conclusion="",
            now=before_due_time,
        )
    assert early.value.code == "recommendation_observation_not_due"

    completed = feedback.complete(
        recommendation_id,
        expected_version=3,
        request_id="lifecycle-complete-request",
        outcome="inconclusive",
        actual_cost=6.5,
        actual_hours=2,
        user_conclusion="样本仍不足，暂不沉淀为经营规则",
        now=after_due_time,
    )
    assert completed.status == "completed"
    assert completed.lifecycle_status == "completed"
    assert completed.outcome == "inconclusive"
    assert completed.result_metrics is not None
    assert completed.actual_cost == 6.5
    assert completed.actual_hours == 2


@pytest.mark.asyncio
async def test_request_id_replays_original_result_and_rejects_new_payload(
    tmp_path: Path,
) -> None:
    _, _, analysis, feedback = build_services(tmp_path)
    recommendation_id = await create_analysis(
        analysis,
        request_id="idempotency-analysis-request",
    )
    first = feedback.update(
        recommendation_id,
        status="accepted",
        expected_version=1,
        request_id="idempotency-feedback-request",
        note="同一业务意图",
        now=FIXED_NOW,
    )
    repeated = feedback.update(
        recommendation_id,
        status="accepted",
        expected_version=1,
        request_id="idempotency-feedback-request",
        note="同一业务意图",
        now=FIXED_NOW + timedelta(days=1),
    )
    assert repeated.version == first.version == 2
    assert repeated.accepted_at == first.accepted_at

    with pytest.raises(RecommendationRequestConflict):
        feedback.update(
            recommendation_id,
            status="accepted",
            expected_version=1,
            request_id="idempotency-feedback-request",
            note="不同负载",
            now=FIXED_NOW,
        )

    with pytest.raises(RecommendationVersionConflict):
        feedback.update(
            recommendation_id,
            status="ignored",
            expected_version=1,
            request_id="idempotency-version-conflict",
            note="",
            now=FIXED_NOW,
        )


@pytest.mark.asyncio
async def test_status_and_event_roll_back_atomically(tmp_path: Path) -> None:
    database, _, analysis, feedback = build_services(tmp_path)
    recommendation_id = await create_analysis(
        analysis,
        request_id="atomic-analysis-request",
    )
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_recommendation_event "
            "BEFORE INSERT ON business_analysis_recommendation_events "
            "BEGIN SELECT RAISE(ABORT, 'forced event failure'); END"
        )

    with pytest.raises(BusinessAnalysisRepositoryError):
        feedback.update(
            recommendation_id,
            status="accepted",
            expected_version=1,
            request_id="atomic-feedback-request",
            note="",
            now=FIXED_NOW,
        )

    with database.session() as session:
        row = session.get(BusinessAnalysisRecommendationRecord, recommendation_id)
        assert row is not None
        assert row.status == "pending"
        assert row.version == 1
        assert session.scalar(select(func.count(BusinessAnalysisRecommendationEvent.id))) == 0


@pytest.mark.asyncio
async def test_product_experiment_is_linked_without_creating_a_second_experiment(
    tmp_path: Path,
) -> None:
    database, _, analysis, feedback = build_services(tmp_path)
    with database.session() as session:
        item = Item(external_id="owned-product-feedback", title="本人商品")
        session.add(item)
        session.flush()
        item_id = item.id
        session.add(
            ProductMonitor(
                item_id=item_id,
                enabled=True,
                ownership_status="owned",
                ownership_source="seller_match",
            )
        )
        session.add(
            ProductDailySnapshot(
                item_id=item_id,
                snapshot_date="2026-08-11",
                source="test",
                title="本人商品",
                status="在售",
                raw_browse_count=100,
                browse_count=100,
                inquiry_count=0,
                want_count=3,
                captured_at=FIXED_NOW,
            )
        )
        session.commit()

    result = await analysis.run_analysis(
        request_id="product-link-analysis-request",
        provider="deepseek",
        now=FIXED_NOW,
    )
    recommendation = next(row for row in result.recommendations if row.domain == "products")
    accepted = feedback.update(
        recommendation.id,
        status="accepted",
        expected_version=1,
        request_id="product-link-accept-request",
        note="",
        now=FIXED_NOW,
    )
    assert accepted.baseline_metrics is not None

    experiment_id = "product-modification-feedback-test"
    with database.session() as session:
        session.add(
            ProductModificationExperiment(
                id=experiment_id,
                item_id=item_id,
                variable="title",
                before_value="旧标题",
                after_value="新标题",
                baseline_json=json.dumps(
                    {
                        "browse_count": 100,
                        "inquiry_count": 0,
                        "want_count": 3,
                        "converted_project_count": 0,
                    }
                ),
                started_at=FIXED_NOW,
                observation_until=FIXED_NOW + timedelta(days=7),
                status="observing",
                result_json="{}",
                decision="pending",
                evidence_json="[]",
            )
        )
        session.commit()

    started = feedback.start(
        recommendation.id,
        expected_version=2,
        request_id="product-link-start-request",
        execution_ref_type="product_modification_experiment",
        execution_ref_id=experiment_id,
        now=FIXED_NOW,
    )
    assert started.execution_ref_id == experiment_id
    assert started.baseline_metrics is not None
    assert started.baseline_metrics.values[0].key == "product_experiment.browse_count"

    with database.session() as session:
        experiment = session.get(ProductModificationExperiment, experiment_id)
        assert experiment is not None
        experiment.status = "completed"
        experiment.decision = "keep"
        experiment.result_json = json.dumps(
            {"browse_delta": 24, "inquiry_delta": 2, "want_delta": 1}
        )
        session.commit()

    with pytest.raises(BusinessRecommendationServiceError) as mismatch:
        feedback.complete(
            recommendation.id,
            expected_version=3,
            request_id="product-link-wrong-outcome",
            outcome="negative",
            actual_cost=0,
            actual_hours=1,
            user_conclusion="",
            now=FIXED_NOW + timedelta(days=1),
        )
    assert mismatch.value.code == "recommendation_outcome_conflict"

    completed = feedback.complete(
        recommendation.id,
        expected_version=3,
        request_id="product-link-complete-request",
        outcome="positive",
        actual_cost=0,
        actual_hours=1,
        user_conclusion="商品实验已选择保留",
        now=FIXED_NOW + timedelta(days=1),
    )
    assert completed.outcome == "positive"
    assert completed.result_metrics is not None
    browse = next(
        row
        for row in completed.result_metrics.values
        if row.key == "product_experiment.browse_count"
    )
    assert browse.value == 124
    with database.session() as session:
        assert session.scalar(select(func.count(ProductModificationExperiment.id))) == 1


def test_migration_handles_metadata_created_event_table_before_0016(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "recommendation-feedback-migration.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path}"
    Database(f"sqlite:///{database_path}").create_all()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO alembic_version(version_num) VALUES ('20260811_0015')"
        )

    # Local startup may create new metadata before Alembic records revision
    # 0016. This must remain additive and idempotent.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    with sqlite3.connect(database_path) as connection:
        version = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(business_analysis_recommendations)"
            )
        }
        event_table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='business_analysis_recommendation_events'"
        ).fetchone()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert version == ("20260908_0046",)
    assert {
        "target_scope",
        "accepted_at",
        "observe_until",
        "baseline_metrics_json",
        "result_metrics_json",
        "outcome",
        "actual_cost",
        "actual_hours",
        "execution_ref_type",
        "execution_ref_id",
    } <= columns
    assert event_table == ("business_analysis_recommendation_events",)
    assert violations == []
