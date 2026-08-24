from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.config import Settings
from backend.app.database import Database
from backend.app.models import (
    BusinessCustomer,
    BusinessExpense,
    BusinessProject,
    Conversation,
    Item,
    Message,
    PaymentNode,
    ProductMonitor,
    ProductOperatingPlan,
    ProductOperatingPlanSlot,
    ProductTrafficBatch,
    ProductTrafficBatchItem,
    ProductTrafficBudgetDecision,
    ProductTrafficCheckpoint,
    ProductTrafficCommercialAttribution,
    ProductTrafficExperiment,
    ProductTrafficExperimentCell,
    ProductTrafficScaleCohort,
    ProductTrafficScaleCohortBatch,
)
from backend.app.services.traffic_growth import (
    STAGE_BATCHES_PER_WEEK,
    TrafficGrowthConflict,
    TrafficGrowthService,
)
from backend.app.services.event_hub import EventHub
from backend.app.services.product_intelligence import ProductIntelligenceService
from backend.app.traffic_growth_schemas import (
    TrafficBudgetDecisionView,
    TrafficGrowthMetricsView,
)
from backend.app.traffic_growth_api import traffic_growth_router


NOW = datetime(2026, 8, 17, 8, 20, tzinfo=timezone.utc)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GROWTH_TABLES = {
    "product_traffic_experiments",
    "product_traffic_experiment_cells",
    "product_traffic_scale_cohorts",
    "product_traffic_scale_cohort_batches",
    "product_traffic_commercial_attributions",
    "product_traffic_budget_decisions",
    "product_traffic_growth_requests",
}


def build_service(tmp_path: Path) -> tuple[Database, TrafficGrowthService, Item]:
    path = tmp_path / "traffic-growth.db"
    database = Database(f"sqlite:///{path}")
    database.create_all()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{path}",
        product_collection_timezone="Asia/Shanghai",
        product_traffic_cooldown_hours=72,
        product_delivery_capacity=4,
    )
    service = TrafficGrowthService(database, settings)
    service._now = lambda: NOW
    with database.session() as session:
        item = Item(
            external_id="hero-listing-001",
            title="高潜技术实现服务",
            updated_at=NOW,
        )
        session.add(item)
        session.flush()
        session.add(
            ProductMonitor(
                item_id=item.id,
                enabled=True,
                ownership_status="owned",
                ownership_source="test",
            )
        )
        session.commit()
        session.refresh(item)
        session.expunge(item)
    return database, service, item


def create_experiment(service: TrafficGrowthService):
    return service.create_experiment(
        request_id="growth-create-0001",
        item_external_id="hero-listing-001",
        target_windows=["12", "16", "20"],
        baseline_weekly_budget=24,
        hard_weekly_cap=48,
    )


def seed_clean_batch(
    database: Database,
    *,
    item_id: int,
    batch_id: str,
    started_at: datetime,
    browse_delta: int,
    inquiry_delta: int,
) -> None:
    with database.session() as session:
        batch = ProductTrafficBatch(
            id=batch_id,
            request_id=f"request-{batch_id}",
            status="closed",
            planned_at=started_at,
            started_at=started_at,
            completed_at=started_at + timedelta(hours=1),
            baseline_prepared_at=started_at - timedelta(minutes=5),
            recording_mode="standard",
            attribution_status="clean",
            actual_cost=5.9,
            created_at=started_at,
            updated_at=started_at,
        )
        session.add(batch)
        session.flush()
        session.add(
            ProductTrafficBatchItem(
                batch_id=batch.id,
                item_id=item_id,
                position=0,
                baseline_browse_count=100,
                baseline_collect_count=3,
                baseline_want_count=4,
                baseline_inquiry_count=2,
                baseline_captured_at=started_at - timedelta(minutes=5),
                baseline_source="manual",
            )
        )
        session.add(
            ProductTrafficCheckpoint(
                id=f"checkpoint-{batch_id}",
                batch_id=batch.id,
                item_id=item_id,
                checkpoint="h72",
                browse_count=100 + browse_delta,
                collect_count=3,
                want_count=4,
                inquiry_count=2 + inquiry_delta,
                recorded_at=started_at + timedelta(hours=72),
                source="manual",
            )
        )
        session.commit()


def bind_matrix_batch(
    database: Database,
    service: TrafficGrowthService,
    *,
    experiment_id: str,
    bucket: str,
    phase: str,
    suffix: str,
    browse_delta: int,
    inquiry_delta: int,
) -> None:
    with database.session() as session:
        cell = session.scalar(
            select(ProductTrafficExperimentCell)
            .where(
                ProductTrafficExperimentCell.experiment_id == experiment_id,
                ProductTrafficExperimentCell.phase == phase,
                ProductTrafficExperimentCell.window_bucket == bucket,
                ProductTrafficExperimentCell.batch_id.is_(None),
            )
            .order_by(ProductTrafficExperimentCell.repeat_index)
            .limit(1)
        )
        assert cell is not None and cell.scheduled_for is not None
        cell_id = cell.id
        started_at = service._utc(cell.scheduled_for)
        item_id = session.get(ProductTrafficExperiment, experiment_id).item_id
    batch_id = f"batch-{phase}-{bucket}-{suffix}"
    seed_clean_batch(
        database,
        item_id=item_id,
        batch_id=batch_id,
        started_at=started_at,
        browse_delta=browse_delta,
        inquiry_delta=inquiry_delta,
    )
    service.bind_experiment_batch(
        experiment_id,
        cell_id,
        request_id=f"bind-{phase}-{bucket}-{suffix}",
        batch_id=batch_id,
    )


def complete_winning_matrix(
    database: Database,
    service: TrafficGrowthService,
    experiment_id: str,
):
    for bucket, browse, inquiries in (
        ("12", 40, 1),
        ("16", 50, 2),
        ("20", 30, 0),
    ):
        for repeat in (1, 2):
            bind_matrix_batch(
                database,
                service,
                experiment_id=experiment_id,
                bucket=bucket,
                phase="exploration",
                suffix=str(repeat),
                browse_delta=browse,
                inquiry_delta=inquiries,
            )
    view = service.experiment(experiment_id)
    assert view.valid_exploration_batches == 6
    assert view.provisional_winner == "16"
    view = service.advance_experiment(
        experiment_id,
        request_id="growth-advance-0001",
        expected_updated_at=view.updated_at,
    )
    for bucket, browse, inquiries in (("16", 55, 2), ("12", 42, 1)):
        bind_matrix_batch(
            database,
            service,
            experiment_id=experiment_id,
            bucket=bucket,
            phase="confirmation",
            suffix="1",
            browse_delta=browse,
            inquiry_delta=inquiries,
        )
    view = service.experiment(experiment_id)
    assert view.valid_confirmation_batches == 2
    assert view.confirmed_winner == "16"
    return view


def test_clean_time_matrix_is_balanced_and_keeps_hero_72_hours_apart(tmp_path: Path) -> None:
    _, service, _ = build_service(tmp_path)
    preview = service.preview_experiment(
        item_external_id="hero-listing-001",
        target_windows=["12", "16", "20"],
        baseline_weekly_budget=24,
        hard_weekly_cap=48,
    )

    assert len(preview.schedule) == 6
    assert {bucket: sum(row.window_bucket == bucket for row in preview.schedule) for bucket in ("12", "16", "20")} == {
        "12": 2,
        "16": 2,
        "20": 2,
    }
    schedule = [row.scheduled_for for row in preview.schedule]
    assert all(value is not None for value in schedule)
    assert all(
        right - left >= timedelta(hours=72)
        for left, right in zip(schedule, schedule[1:])
    )
    assert preview.expected_batch_count == 8
    assert preview.estimated_cost == pytest.approx(47.2)


def test_0025_migration_upgrades_existing_schema_and_keeps_integrity(tmp_path: Path) -> None:
    database_path = tmp_path / "growth-migration.db"
    Database(f"sqlite:///{database_path}").create_all()
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        for table in (
            "product_traffic_growth_requests",
            "product_traffic_budget_decisions",
            "product_traffic_commercial_attributions",
            "product_traffic_scale_cohort_batches",
            "product_traffic_scale_cohorts",
            "product_traffic_experiment_cells",
            "product_traffic_experiments",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute(
            "CREATE TABLE alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO alembic_version(version_num) VALUES ('20260817_0024')"
        )

    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path}"
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
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert version == ("20260820_0036",)
    assert GROWTH_TABLES.issubset(tables)
    assert integrity == ("ok",)
    assert violations == []


def test_growth_upgrade_backup_is_private_integral_and_hashed(tmp_path: Path) -> None:
    database_path = tmp_path / "growth-backup.db"
    database = Database(f"sqlite:///{database_path}")
    database.create_all()
    with database.engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        for table in GROWTH_TABLES:
            connection.exec_driver_sql(f"DROP TABLE {table}")
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    database._backup_before_product_traffic_growth_upgrade()
    backups = list(
        (tmp_path / "backups").glob("*-before-product-traffic-growth-*.db")
    )
    assert len(backups) == 1
    backup = backups[0]
    assert backup.stat().st_mode & 0o777 == 0o600
    assert len(hashlib.sha256(backup.read_bytes()).hexdigest()) == 64
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_growth_upgrade_refuses_partial_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "growth-partial.db"
    database = Database(f"sqlite:///{database_path}")
    database.create_all()
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE product_traffic_growth_requests")

    with pytest.raises(RuntimeError, match="schema is partial"):
        database._backup_before_product_traffic_growth_upgrade()


def test_create_is_idempotent_and_rejects_request_id_payload_reuse(tmp_path: Path) -> None:
    _, service, _ = build_service(tmp_path)
    first = create_experiment(service)
    replay = create_experiment(service)
    assert replay.id == first.id
    with pytest.raises(TrafficGrowthConflict, match="request_id"):
        service.create_experiment(
            request_id="growth-create-0001",
            item_external_id="hero-listing-001",
            target_windows=["10", "16", "20"],
            baseline_weekly_budget=24,
            hard_weekly_cap=48,
        )


def test_growth_api_exposes_preview_create_and_conflict_contract(tmp_path: Path) -> None:
    _, service, _ = build_service(tmp_path)
    app = FastAPI()
    app.state.runtime = SimpleNamespace(traffic_growth=service)
    app.include_router(traffic_growth_router)
    client = TestClient(app)

    preview = client.post(
        "/api/products/traffic-experiments/preview",
        json={
            "item_external_id": "hero-listing-001",
            "target_windows": ["12", "16", "20"],
            "baseline_weekly_budget": 24,
            "hard_weekly_cap": 48,
        },
    )
    assert preview.status_code == 200
    assert preview.json()["expected_batch_count"] == 8

    created = client.post(
        "/api/products/traffic-experiments",
        json={
            "request_id": "growth-api-create-0001",
            "item_external_id": "hero-listing-001",
            "target_windows": ["12", "16", "20"],
            "baseline_weekly_budget": 24,
            "hard_weekly_cap": 48,
        },
    )
    assert created.status_code == 200
    experiment_id = created.json()["id"]
    overview = client.get("/api/products/traffic-growth")
    assert overview.status_code == 200
    assert overview.json()["active_experiment"]["id"] == experiment_id

    duplicate = client.post(
        "/api/products/traffic-experiments/preview",
        json={
            "item_external_id": "hero-listing-001",
            "target_windows": ["12", "16", "20"],
            "baseline_weekly_budget": 24,
            "hard_weekly_cap": 48,
        },
    )
    assert duplicate.status_code == 409
    assert "已经存在" in duplicate.json()["detail"]


def test_operating_plan_context_uses_next_pending_cell_without_creating_batch(tmp_path: Path) -> None:
    database, service, _ = build_service(tmp_path)
    experiment = create_experiment(service)
    with database.session() as session:
        before = len(session.scalars(select(ProductTrafficBatch)).all())
        context = service.operating_plan_context(session, now=NOW)
        after = len(session.scalars(select(ProductTrafficBatch)).all())

    assert context is not None
    assert context["mode"] == "time_test"
    assert context["hero_external_id"] == "hero-listing-001"
    assert context["weekly_budget"] == 24
    assert len(context["slots"]) == 1
    slot = next(iter(context["slots"].values()))
    next_cell = min(
        (value for value in experiment.cells if value.status == "pending"),
        key=lambda value: value.scheduled_for,
    )
    assert slot["cell_id"] == next_cell.id
    assert before == after == 0


def test_plan_batch_creation_atomically_binds_the_experiment_cell(tmp_path: Path) -> None:
    database, growth, hero = build_service(tmp_path)
    product_service = ProductIntelligenceService(
        database,
        object(),
        growth.settings,
        EventHub(),
    )
    product_service._now = lambda: NOW
    product_service.traffic_growth = growth
    experiment = create_experiment(growth)
    cell = min(
        (value for value in experiment.cells if value.status == "pending"),
        key=lambda value: value.scheduled_for,
    )
    with database.session() as session:
        companions = []
        for index in range(2):
            companion = Item(
                external_id=f"atomic-companion-{index}",
                title=f"陪跑商品 {index}",
                updated_at=NOW,
            )
            session.add(companion)
            session.flush()
            session.add(
                ProductMonitor(
                    item_id=companion.id,
                    enabled=True,
                    ownership_status="owned",
                    ownership_source="test",
                )
            )
            companions.append(companion.external_id)
        plan = ProductOperatingPlan(
            id="plan-atomic-bind",
            plan_start_date="2026-08-17",
            version=1,
            status="current",
            input_signature="atomic-bind",
            weekly_budget=24,
            generated_at=NOW,
        )
        slot = ProductOperatingPlanSlot(
            id="slot-atomic-bind",
            plan_id=plan.id,
            slot_date="2026-08-18",
            scheduled_time="12:00",
            action_type="traffic",
            item_ids_json="[]",
            planned_cost=5.9,
            status="planned",
            is_new_spend=True,
            rotation_summary_json=(
                '{"experiment_managed":true,"experiment_id":"'
                + experiment.id
                + '","cell_id":"'
                + cell.id
                + '","mode":"time_test"}'
            ),
        )
        session.add_all([plan, slot])
        session.commit()

    batch = product_service.create_traffic_batch(
        request_id="create-atomic-bind",
        item_external_ids=[hero.external_id, *companions],
        planned_at=cell.scheduled_for,
        actual_cost=5.9,
        plan_slot_id="slot-atomic-bind",
        note="",
    )
    with database.session() as session:
        bound = session.get(ProductTrafficExperimentCell, cell.id)
        assert bound.batch_id == batch.id
        assert bound.status == "bound"
        assert session.get(ProductOperatingPlanSlot, "slot-atomic-bind").status == "scheduled"
        model = session.get(ProductTrafficBatch, batch.id)
        model.baseline_prepared_at = NOW - timedelta(minutes=5)
        model.updated_at = NOW - timedelta(minutes=1)
        items = session.scalars(
            select(ProductTrafficBatchItem).where(
                ProductTrafficBatchItem.batch_id == batch.id
            )
        ).all()
        for item in items:
            item.baseline_source = "manual"
            item.baseline_captured_at = NOW - timedelta(minutes=5)
        session.commit()
        expected_updated_at = model.updated_at

    started = product_service.start_traffic_batch(
        batch.id,
        request_id="start-atomic-bind",
        expected_updated_at=expected_updated_at,
        expected_baseline_captured_at=NOW - timedelta(minutes=5),
    )
    assert started.started_at == NOW.replace(second=0, microsecond=0)
    with database.session() as session:
        actual = session.scalar(
            select(ProductTrafficExperimentCell).where(
                ProductTrafficExperimentCell.batch_id == batch.id
            )
        )
        assert actual is not None
        assert actual.window_bucket == "16"
        assert actual.actual_bucket == "16"
        if cell.window_bucket != "16":
            original = session.get(ProductTrafficExperimentCell, cell.id)
            assert original.batch_id is None
            assert original.status == "pending"


def test_actual_window_results_require_replication_and_stable_confirmation(tmp_path: Path) -> None:
    database, service, _ = build_service(tmp_path)
    experiment = create_experiment(service)
    complete = complete_winning_matrix(database, service, experiment.id)

    assert complete.confirmed_winner == "16"
    winner = next(value for value in complete.time_windows if value.window_bucket == "16")
    runner = next(value for value in complete.time_windows if value.window_bucket == "12")
    assert winner.average_inquiry_delta >= runner.average_inquiry_delta + 0.5
    assert winner.average_browse_delta >= runner.average_browse_delta * 0.7


def test_batch_started_in_another_bucket_is_reassigned_not_mislabeled(tmp_path: Path) -> None:
    database, service, item = build_service(tmp_path)
    experiment = create_experiment(service)
    target = next(
        value
        for value in experiment.cells
        if value.window_bucket == "12" and value.repeat_index == 1
    )
    actual = target.scheduled_for.astimezone(timezone.utc).replace(hour=8)
    # 08:00 UTC is 16:00 Beijing, so the batch belongs in a 16 bucket cell.
    seed_clean_batch(
        database,
        item_id=item.id,
        batch_id="batch-reassigned",
        started_at=actual,
        browse_delta=20,
        inquiry_delta=1,
    )
    result = service.bind_experiment_batch(
        experiment.id,
        target.id,
        request_id="bind-reassigned-0001",
        batch_id="batch-reassigned",
    )

    bound = next(value for value in result.cells if value.batch_id == "batch-reassigned")
    assert bound.window_bucket == "16"
    assert bound.actual_bucket == "16"
    assert target.id != bound.id


def test_attribution_requires_first_inbound_and_exact_conversation_project(tmp_path: Path) -> None:
    database, service, item = build_service(tmp_path)
    experiment = create_experiment(service)
    cell = experiment.cells[0]
    start = cell.scheduled_for.astimezone(timezone.utc)
    seed_clean_batch(
        database,
        item_id=item.id,
        batch_id="batch-attribution",
        started_at=start,
        browse_delta=25,
        inquiry_delta=2,
    )
    service.bind_experiment_batch(
        experiment.id,
        cell.id,
        request_id="bind-attribution-0001",
        batch_id="batch-attribution",
    )
    with database.session() as session:
        customer = BusinessCustomer(id="customer-growth", name="增长客户")
        exact = Conversation(
            external_id="conversation-exact",
            customer_id="external-customer-exact",
            customer_name="精确客户",
            item_id=item.id,
            created_at=start + timedelta(hours=2),
            updated_at=start + timedelta(hours=2),
            last_message_at=start + timedelta(hours=2),
        )
        product_only = Conversation(
            external_id="conversation-product-only",
            customer_id="external-customer-product",
            customer_name="仅商品绑定客户",
            item_id=item.id,
            created_at=start + timedelta(hours=3),
            updated_at=start + timedelta(hours=3),
            last_message_at=start + timedelta(hours=3),
        )
        session.add_all([customer, exact, product_only])
        session.flush()
        session.add_all(
            [
                Message(
                    external_id="message-exact",
                    conversation_id=exact.id,
                    sender_id="buyer-exact",
                    direction="inbound",
                    content="咨询实现",
                    received_at=start + timedelta(hours=2),
                ),
                Message(
                    external_id="message-product-only",
                    conversation_id=product_only.id,
                    sender_id="buyer-product",
                    direction="inbound",
                    content="咨询价格",
                    received_at=start + timedelta(hours=3),
                ),
            ]
        )
        exact_project = BusinessProject(
            id="project-exact",
            name="精确对话项目",
            customer_id=customer.id,
            conversation_id=exact.id,
            item_id=item.id,
            status="in_progress",
            created_at=start + timedelta(hours=4),
        )
        product_project = BusinessProject(
            id="project-product-only",
            name="仅商品来源项目",
            customer_id=customer.id,
            conversation_id=None,
            item_id=item.id,
            status="in_progress",
            created_at=start + timedelta(hours=4),
        )
        session.add_all([exact_project, product_project])
        session.commit()

    refreshed = service.refresh_attributions(
        experiment.id,
        request_id="refresh-attribution-0001",
    )
    assert len(refreshed.attributions) == 2
    exact_candidate = next(
        value for value in refreshed.attributions if value.project_id == "project-exact"
    )
    product_only_candidate = next(
        value
        for value in refreshed.attributions
        if value.conversation_id != exact_candidate.conversation_id
    )
    assert product_only_candidate.project_id is None
    with pytest.raises(TrafficGrowthConflict, match="必须选择"):
        service.decide_attribution(
            product_only_candidate.id,
            request_id="confirm-without-project-0001",
            expected_updated_at=product_only_candidate.updated_at,
            decision="confirm",
            project_id=None,
            reason="",
        )


def test_full_batch_cost_and_confirmed_project_profit_drive_budget_preview(tmp_path: Path) -> None:
    database, service, item = build_service(tmp_path)
    experiment = create_experiment(service)
    complete = complete_winning_matrix(database, service, experiment.id)
    scope_batches = [value.batch_id for value in complete.cells if value.batch_id]
    with database.session() as session:
        customer = BusinessCustomer(id="customer-profit", name="利润客户")
        session.add(customer)
        for index in range(3):
            conversation = Conversation(
                external_id=f"conversation-profit-{index}",
                customer_id=f"external-profit-{index}",
                customer_name=f"利润客户{index}",
                item_id=item.id,
                last_message_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
            session.add(conversation)
            session.flush()
            project_id = f"project-profit-{index}" if index < 2 else None
            if project_id:
                project = BusinessProject(
                    id=project_id,
                    name=f"归因项目{index}",
                    customer_id=customer.id,
                    conversation_id=conversation.id,
                    item_id=item.id,
                    status="in_progress",
                    created_at=NOW,
                )
                session.add(project)
                session.flush()
                session.add(
                    PaymentNode(
                        id=f"payment-profit-{index}",
                        project_id=project_id,
                        customer_id=customer.id,
                        amount=180,
                        status="confirmed",
                        paid_at="2026-08-17",
                    )
                )
                session.add(
                    BusinessExpense(
                        id=f"expense-profit-{index}",
                        project_id=project_id,
                        name="项目成本",
                        amount=20,
                        paid_at="2026-08-17",
                    )
                )
            batch = session.get(ProductTrafficBatch, scope_batches[index])
            session.add(
                ProductTrafficCommercialAttribution(
                    id=f"attribution-profit-{index}",
                    attribution_key=f"manual-profit-{index}",
                    experiment_id=experiment.id,
                    batch_id=batch.id,
                    cohort_id=None,
                    item_id=item.id,
                    conversation_id=conversation.id,
                    project_id=project_id,
                    status="confirmed" if project_id else "candidate",
                    source="test",
                    first_inbound_at=batch.started_at + timedelta(hours=2),
                    window_start=batch.started_at,
                    window_end=batch.started_at + timedelta(hours=72),
                    confirmed_by_user_at=NOW if project_id else None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        session.commit()

    view = service.experiment(experiment.id)
    assert view.metrics.actual_cost == pytest.approx(8 * 5.9)
    assert view.metrics.attributed_inquiry_count == 3
    assert view.metrics.paid_project_count == 2
    assert view.metrics.realized_contribution_profit == pytest.approx(320)
    assert view.metrics.profit_to_cost_ratio == pytest.approx(6.78)
    assert view.budget_decision.recommendation == "scale"
    assert view.budget_decision.to_stage == "S1"


def test_scale_cohort_requires_applied_decision_and_enforces_two_week_cap(tmp_path: Path) -> None:
    database, service, item = build_service(tmp_path)
    experiment = create_experiment(service)
    complete_winning_matrix(database, service, experiment.id)
    with database.session() as session:
        model = session.get(ProductTrafficExperiment, experiment.id)
        model.current_weekly_budget = 24
        decision = ProductTrafficBudgetDecision(
            id="decision-applied-s1",
            decision_key="decision-applied-s1-key",
            experiment_id=experiment.id,
            cohort_id=None,
            recommendation="scale",
            status="applied",
            from_stage="T0",
            to_stage="S1",
            current_weekly_budget=24,
            recommended_weekly_budget=24,
            metrics_json="{}",
            evidence_json="[]",
            decided_at=NOW,
            applied_at=NOW,
            created_at=NOW,
        )
        session.add(decision)
        session.commit()

    result = service.create_scale_cohort(
        experiment.id,
        request_id="create-cohort-s1-0001",
        stage="S1",
        no_other_promotion_confirmed=True,
        listing_unchanged_confirmed=True,
    )
    cohort = result.cohorts[-1]
    assert cohort.target_batches_per_week == STAGE_BATCHES_PER_WEEK["S1"]
    assert cohort.weekly_budget == 24

    for index in range(6):
        batch_id = f"batch-cohort-{index}"
        with database.session() as session:
            started = None if index else NOW
            session.add(
                ProductTrafficBatch(
                    id=batch_id,
                    request_id=f"request-{batch_id}",
                    status="running" if started else "planned",
                    planned_at=NOW + timedelta(days=index * 2),
                    started_at=started,
                    baseline_prepared_at=NOW - timedelta(minutes=5),
                    actual_cost=5.9,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.flush()
            session.add(
                ProductTrafficBatchItem(
                    batch_id=batch_id,
                    item_id=item.id,
                    position=0,
                    baseline_source="manual",
                    baseline_captured_at=NOW - timedelta(minutes=5),
                )
            )
            session.commit()
        service.bind_cohort_batch(
            experiment.id,
            cohort.id,
            request_id=f"bind-cohort-{index:04d}",
            batch_id=batch_id,
        )
    with database.session() as session:
        associations = session.scalars(
            select(ProductTrafficScaleCohortBatch).where(
                ProductTrafficScaleCohortBatch.cohort_id == cohort.id
            )
        ).all()
        assert len(associations) == 6
        bound = session.get(ProductTrafficBatch, "batch-cohort-0")
        assert bound.recording_mode == "scale_cohort"
        assert bound.attribution_status == "cohort_overlap"
    with database.session() as session:
        session.add(
            ProductTrafficBatch(
                id="batch-cohort-over-cap",
                request_id="request-batch-cohort-over-cap",
                status="planned",
                planned_at=NOW + timedelta(days=13),
                baseline_prepared_at=NOW - timedelta(minutes=5),
                actual_cost=5.9,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            ProductTrafficBatchItem(
                batch_id="batch-cohort-over-cap",
                item_id=item.id,
                baseline_source="manual",
                baseline_captured_at=NOW - timedelta(minutes=5),
            )
        )
        session.commit()
    with pytest.raises(TrafficGrowthConflict, match="批次数"):
        service.bind_cohort_batch(
            experiment.id,
            cohort.id,
            request_id="bind-cohort-over-cap",
            batch_id="batch-cohort-over-cap",
        )


def test_scale_cohort_relaxes_only_the_hero_listing_cooldown(tmp_path: Path) -> None:
    database, growth, hero = build_service(tmp_path)
    settings = growth.settings
    product_service = ProductIntelligenceService(
        database,
        object(),
        settings,
        EventHub(),
    )
    product_service._now = lambda: NOW
    product_service.traffic_growth = growth
    with database.session() as session:
        companion = Item(external_id="companion-listing", title="陪跑商品")
        session.add(companion)
        session.flush()
        session.add(
            ProductMonitor(
                item_id=companion.id,
                enabled=True,
                ownership_status="owned",
                ownership_source="test",
            )
        )
        experiment = session.scalar(select(ProductTrafficExperiment))
        if experiment is None:
            session.commit()
            experiment_id = create_experiment(growth).id
            experiment = session.get(ProductTrafficExperiment, experiment_id)
        prior = ProductTrafficBatch(
            id="batch-prior-overlap",
            request_id="request-prior-overlap",
            status="observing",
            planned_at=NOW - timedelta(hours=24),
            started_at=NOW - timedelta(hours=24),
            actual_cost=5.9,
            created_at=NOW - timedelta(hours=24),
            updated_at=NOW - timedelta(hours=24),
        )
        planned = ProductTrafficBatch(
            id="batch-cohort-overlap-check",
            request_id="request-cohort-overlap-check",
            status="planned",
            planned_at=NOW,
            recording_mode="scale_cohort",
            attribution_status="cohort_overlap",
            actual_cost=5.9,
            created_at=NOW,
            updated_at=NOW,
        )
        cohort = ProductTrafficScaleCohort(
            id="cohort-overlap-check",
            request_id="cohort-overlap-check-request",
            experiment_id=experiment.id,
            stage="S1",
            status="planned",
            target_batches_per_week=3,
            weekly_budget=24,
            no_other_promotion_confirmed=True,
            listing_unchanged_confirmed=True,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all([prior, planned, cohort])
        session.flush()
        session.add_all(
            [
                ProductTrafficBatchItem(batch_id=prior.id, item_id=hero.id, position=0),
                ProductTrafficBatchItem(batch_id=prior.id, item_id=companion.id, position=1),
                ProductTrafficBatchItem(batch_id=planned.id, item_id=hero.id, position=0),
                ProductTrafficBatchItem(batch_id=planned.id, item_id=companion.id, position=1),
                ProductTrafficScaleCohortBatch(
                    cohort_id=cohort.id,
                    batch_id=planned.id,
                    created_at=NOW,
                ),
            ]
        )
        session.commit()
        blocked, _, _, _ = product_service._traffic_start_conflict(session, planned)

    assert blocked == {companion.id}


def test_start_preview_allows_only_confirmed_cohort_hero_overlap_without_adapter_calls(
    tmp_path: Path,
) -> None:
    database, growth, hero = build_service(tmp_path)
    experiment = create_experiment(growth)

    class NoAdapterCalls:
        def __getattr__(self, name):
            raise AssertionError(f"start preview must not access adapter: {name}")

    product_service = ProductIntelligenceService(
        database,
        NoAdapterCalls(),
        growth.settings,
        EventHub(),
    )
    product_service._now = lambda: NOW
    product_service.traffic_growth = growth
    growth.product_intelligence = product_service
    with database.session() as session:
        companion = Item(external_id="preview-companion", title="预览陪跑商品")
        session.add(companion)
        session.flush()
        session.add(
            ProductMonitor(
                item_id=companion.id,
                enabled=True,
                ownership_status="owned",
                ownership_source="test",
            )
        )
        prior = ProductTrafficBatch(
            id="preview-prior",
            request_id="preview-prior-request",
            status="observing",
            planned_at=NOW - timedelta(hours=24),
            started_at=NOW - timedelta(hours=24),
            actual_cost=5.9,
            created_at=NOW - timedelta(hours=24),
            updated_at=NOW - timedelta(hours=24),
        )
        planned = ProductTrafficBatch(
            id="preview-cohort-batch",
            request_id="preview-cohort-batch-request",
            status="planned",
            planned_at=NOW,
            baseline_prepared_at=NOW - timedelta(minutes=5),
            recording_mode="scale_cohort",
            attribution_status="cohort_overlap",
            actual_cost=5.9,
            created_at=NOW,
            updated_at=NOW,
        )
        cohort = ProductTrafficScaleCohort(
            id="preview-cohort",
            request_id="preview-cohort-request",
            experiment_id=experiment.id,
            stage="S1",
            status="planned",
            target_batches_per_week=3,
            weekly_budget=24,
            no_other_promotion_confirmed=True,
            listing_unchanged_confirmed=True,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all([prior, planned, cohort])
        session.flush()
        session.add_all(
            [
                ProductTrafficBatchItem(batch_id=prior.id, item_id=hero.id, position=0),
                ProductTrafficBatchItem(
                    batch_id=planned.id,
                    item_id=hero.id,
                    position=0,
                    baseline_source="manual",
                    baseline_captured_at=NOW - timedelta(minutes=5),
                ),
                ProductTrafficScaleCohortBatch(
                    cohort_id=cohort.id,
                    batch_id=planned.id,
                    created_at=NOW,
                ),
            ]
        )
        session.commit()

    clean_preview = product_service.traffic_start_preview("preview-cohort-batch")
    assert clean_preview.can_start is True
    assert clean_preview.can_start_cohort is True
    assert clean_preview.can_start_clean is False

    with database.session() as session:
        prior = session.get(ProductTrafficBatch, "preview-prior")
        planned = session.get(ProductTrafficBatch, "preview-cohort-batch")
        companion = session.scalar(select(Item).where(Item.external_id == "preview-companion"))
        session.add_all(
            [
                ProductTrafficBatchItem(batch_id=prior.id, item_id=companion.id, position=1),
                ProductTrafficBatchItem(
                    batch_id=planned.id,
                    item_id=companion.id,
                    position=1,
                    baseline_source="manual",
                    baseline_captured_at=NOW - timedelta(minutes=5),
                ),
            ]
        )
        session.commit()

    blocked_preview = product_service.traffic_start_preview("preview-cohort-batch")
    assert blocked_preview.can_start is False
    assert blocked_preview.can_start_cohort is False
    assert blocked_preview.earliest_start_at == NOW + timedelta(hours=48)


def test_apply_budget_decision_rejects_recomputed_evidence_drift(
    tmp_path: Path,
) -> None:
    database, service, _ = build_service(tmp_path)
    experiment = create_experiment(service)
    metrics = TrafficGrowthMetricsView(
        actual_cost=24,
        attributed_inquiry_count=3,
        paid_project_count=2,
        realized_contribution_profit=150,
        profit_to_cost_ratio=6.25,
        net_after_traffic=126,
        active_projects=1,
        delivery_capacity=4,
        observation_complete=True,
    )
    with database.session() as session:
        model = session.get(ProductTrafficExperiment, experiment.id)
        decision = ProductTrafficBudgetDecision(
            id="decision-evidence-drift",
            decision_key="decision-evidence-drift-key",
            experiment_id=experiment.id,
            cohort_id=None,
            recommendation="scale",
            status="pending",
            from_stage="T0",
            to_stage="S1",
            current_weekly_budget=24,
            recommended_weekly_budget=24,
            metrics_json=metrics.model_dump_json(),
            evidence_json="[]",
            decided_at=NOW,
            created_at=NOW,
        )
        session.add(decision)
        session.commit()
        expected_updated_at = model.updated_at

    changed_metrics = metrics.model_copy(update={"active_projects": 4})
    changed_preview = TrafficBudgetDecisionView(
        id=None,
        recommendation="pause",
        status="preview",
        from_stage="T0",
        to_stage="T0",
        current_weekly_budget=24,
        recommended_weekly_budget=0,
        metrics=changed_metrics,
        evidence=["交付容量已满"],
        rules_version="growth-v1",
        decided_at=NOW,
        applied_at=None,
        can_apply=False,
    )
    original_view = service._experiment_view
    service._experiment_view = lambda _session, _experiment: SimpleNamespace(
        budget_decision=changed_preview
    )
    try:
        with pytest.raises(TrafficGrowthConflict, match="证据已经变化"):
            service.apply_budget_decision(
                "decision-evidence-drift",
                request_id="apply-evidence-drift",
                expected_experiment_updated_at=expected_updated_at,
            )
    finally:
        service._experiment_view = original_view

    with database.session() as session:
        assert session.get(ProductTrafficBudgetDecision, "decision-evidence-drift").status == "pending"
        assert session.get(ProductTrafficExperiment, experiment.id).current_weekly_budget == 24


def test_pause_requires_two_recorded_below_break_even_cohorts(tmp_path: Path) -> None:
    database, service, _ = build_service(tmp_path)
    experiment = create_experiment(service)
    with database.session() as session:
        model = session.get(ProductTrafficExperiment, experiment.id)
        prior = ProductTrafficScaleCohort(
            id="cohort-prior-low",
            request_id="cohort-prior-low-request",
            experiment_id=experiment.id,
            stage="S1",
            status="closed",
            target_batches_per_week=3,
            weekly_budget=24,
            no_other_promotion_confirmed=True,
            listing_unchanged_confirmed=True,
            started_at=NOW - timedelta(days=40),
            ended_at=NOW - timedelta(days=26),
            tail_ends_at=NOW - timedelta(days=19),
            commercial_followup_ends_at=NOW - timedelta(days=12),
            created_at=NOW - timedelta(days=40),
            updated_at=NOW - timedelta(days=12),
        )
        current = ProductTrafficScaleCohort(
            id="cohort-current-low",
            request_id="cohort-current-low-request",
            experiment_id=experiment.id,
            stage="S2",
            status="closed",
            target_batches_per_week=5,
            weekly_budget=36,
            no_other_promotion_confirmed=True,
            listing_unchanged_confirmed=True,
            started_at=NOW - timedelta(days=28),
            ended_at=NOW - timedelta(days=14),
            tail_ends_at=NOW - timedelta(days=7),
            commercial_followup_ends_at=NOW,
            created_at=NOW - timedelta(days=28),
            updated_at=NOW,
        )
        session.add_all([prior, current])
        session.flush()
        session.add(
            ProductTrafficBudgetDecision(
                id="decision-prior-low",
                decision_key="decision-prior-low-key",
                experiment_id=experiment.id,
                cohort_id=prior.id,
                recommendation="reduce",
                status="applied",
                from_stage="S1",
                to_stage="T0",
                current_weekly_budget=24,
                recommended_weekly_budget=24,
                metrics_json=TrafficGrowthMetricsView(
                    actual_cost=24,
                    attributed_inquiry_count=1,
                    paid_project_count=0,
                    realized_contribution_profit=12,
                    profit_to_cost_ratio=0.5,
                    net_after_traffic=-12,
                    active_projects=0,
                    delivery_capacity=4,
                    observation_complete=True,
                ).model_dump_json(),
                evidence_json="[]",
                decided_at=NOW - timedelta(days=12),
                applied_at=NOW - timedelta(days=12),
                created_at=NOW - timedelta(days=12),
            )
        )
        session.commit()
        metrics = TrafficGrowthMetricsView(
            actual_cost=36,
            attributed_inquiry_count=1,
            paid_project_count=0,
            realized_contribution_profit=18,
            profit_to_cost_ratio=0.5,
            net_after_traffic=-18,
            active_projects=0,
            delivery_capacity=4,
            observation_complete=True,
        )
        decision = service._decision(
            session,
            model,
            metrics,
            confirmed_winner="16",
            cohorts=[service._cohort_view(session, prior), service._cohort_view(session, current)],
        )

    assert decision.recommendation == "pause"
    assert decision.recommended_weekly_budget == 0
    assert any("连续两个" in value for value in decision.evidence)
