from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.database import Database
from backend.app.agents.tools import BusinessPredictionTool
from backend.app.ledger import LedgerService, default_snapshot
from backend.app.models import (
    BusinessTask,
    CodexAcceptancePoint,
    Conversation,
    CustomerChannelIdentity,
    Message,
    PredictionEvaluationRecord,
    PredictionResultRecord,
    PredictionRun,
    ProjectTimeEntry,
)
from backend.app.prediction.repository import PredictionEvaluationConflict
from backend.app.prediction.service import PredictionService
from backend.app.prediction_api import prediction_router
from backend.app.services.business_analysis import BusinessAnalysisService
from backend.app.services.business_analysis_reasoning import (
    BusinessAnalysisReasoningService,
)


NOW = datetime(2026, 8, 16, 8, 0, tzinfo=timezone.utc)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_service(tmp_path: Path) -> tuple[Database, LedgerService, PredictionService]:
    database = Database(f"sqlite:///{tmp_path / 'prediction.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    return database, ledger, PredictionService(database, ledger)


def test_empty_prediction_degrades_without_inventing_history(tmp_path: Path) -> None:
    _, ledger, service = build_service(tmp_path)

    result = service.preview(now=NOW)
    workload = next(row for row in result.results if row.target == "workload_14d")
    cashflow = next(row for row in result.results if row.target == "cashflow_30d")

    assert workload.prediction_value == 0
    assert workload.risk_level == "normal"
    assert workload.data_sufficiency == "low"
    assert cashflow.prediction_value == 0
    assert cashflow.lower_bound is None
    assert cashflow.upper_bound is None
    assert cashflow.data_sufficiency == "low"
    assert "概率" not in workload.summary
    assert ledger.get()[0] == 0


def test_workload_and_delay_rules_use_real_hours_and_boundary_labels(tmp_path: Path) -> None:
    _, ledger, service = build_service(tmp_path)
    snapshot = default_snapshot()
    snapshot["settings"]["defaultDailyAvailableHours"] = 8
    snapshot["projects"] = [
        {
            "id": "project-risk",
            "name": "风险项目",
            "customerId": "",
            "projectKind": "personal",
            "totalAmount": 0,
            "startDate": "2026-07-01",
            "dueDate": "2026-08-15",
            "progress": 10,
            "status": "pending",
            "type": "个人开发",
            "estimatedHours": 112,
            "accent": "purple",
        }
    ]
    snapshot["tasks"] = [
        {
            "id": "task-risk",
            "projectId": "project-risk",
            "title": "待完成任务",
            "status": "todo",
            "startDate": "2026-07-01",
            "dueDate": "2026-08-15",
            "estimatedHours": 112,
            "actualHours": 0,
        }
    ]
    ledger.save(snapshot, 0)

    result = service.preview(now=NOW)
    workload = next(row for row in result.results if row.target == "workload_14d")
    delay = next(row for row in result.results if row.target == "project_delay_risk")

    assert workload.prediction_value == 100
    assert workload.risk_level == "high"
    assert workload.data_sufficiency == "high"
    assert delay.score is not None and delay.score >= 70
    assert delay.risk_level == "high"
    assert any(driver.code == "capacity_gap" for driver in delay.drivers)
    assert any(driver.code == "schedule_progress_gap" for driver in delay.drivers)
    assert "概率" not in delay.summary


def test_terminal_settlement_projects_do_not_drive_workload_or_delay(tmp_path: Path) -> None:
    _, ledger, service = build_service(tmp_path)
    snapshot = default_snapshot()
    snapshot["projects"] = [
        {
            "id": "project-terminated",
            "name": "已终止项目",
            "customerId": "customer-terminated",
            "projectKind": "client",
            "totalAmount": 1000,
            "startDate": "2026-08-01",
            "dueDate": "2026-08-16",
            "progress": 0,
            "status": "pending",
            "type": "定制开发",
            "estimatedHours": 40,
            "accent": "blue",
        }
    ]
    snapshot["customers"] = [
        {
            "id": "customer-terminated",
            "name": "终止合作客户",
            "source": "xianyu",
            "phone": "",
            "followUpStatus": "inactive",
            "lastContactAt": "2026-08-15T08:00:00+00:00",
            "level": "C",
            "tags": [],
        }
    ]
    snapshot["settlementIssues"] = [
        {
            "id": "issue-terminal",
            "projectId": "project-terminated",
            "customerId": "customer-terminated",
            "type": "cooperation_terminated",
            "reason": "合作已终止",
            "occurredAt": "2026-08-15T08:00:00+00:00",
            "receivableImpact": 1000,
            "refundAmount": 0,
            "requestId": "issue-terminal-request",
            "createdAt": "2026-08-15T08:00:00+00:00",
        }
    ]
    ledger.save(snapshot, 0)

    result = service.preview(now=NOW)
    workload = next(row for row in result.results if row.target == "workload_14d")
    delay_rows = [row for row in result.results if row.target == "project_delay_risk"]

    assert workload.prediction_value == 0
    assert delay_rows == []


def test_cashflow_enables_moving_average_only_after_three_complete_months(
    tmp_path: Path,
) -> None:
    _, ledger, service = build_service(tmp_path)
    snapshot = default_snapshot()
    snapshot["projects"] = [
        {
            "id": "project-cash",
            "name": "现金流项目",
            "customerId": "customer-cash",
            "projectKind": "client",
            "totalAmount": 5000,
            "startDate": "2026-05-01",
            "dueDate": "2026-09-01",
            "progress": 50,
            "status": "in_progress",
            "type": "定制开发",
            "estimatedHours": 40,
            "accent": "blue",
        }
    ]
    snapshot["customers"] = [
        {
            "id": "customer-cash",
            "name": "现金流客户",
            "source": "xianyu",
            "phone": "",
            "followUpStatus": "won",
            "lastContactAt": "2026-08-10T10:00:00+08:00",
            "level": "A",
        }
    ]
    snapshot["payments"] = [
        {
            "id": f"paid-{month}",
            "projectId": "project-cash",
            "customerId": "customer-cash",
            "amount": amount,
            "type": "milestone",
            "status": "confirmed",
            "paidAt": f"2026-{month:02d}-10T10:00:00+08:00",
            "dueAt": f"2026-{month:02d}-10",
        }
        for month, amount in [(5, 1000), (6, 900), (7, 800)]
    ] + [
        {
            "id": "pending-next",
            "projectId": "project-cash",
            "customerId": "customer-cash",
            "amount": 500,
            "type": "final",
            "status": "pending",
            "paidAt": "",
            "dueAt": "2026-08-25",
        }
    ]
    ledger.save(snapshot, 0)

    cashflow = next(
        row for row in service.preview(now=NOW).results if row.target == "cashflow_30d"
    )
    baseline = next(fact for fact in cashflow.facts if fact.key == "baseline_estimate")

    assert baseline.value == 900
    assert cashflow.prediction_value == 1400
    assert cashflow.data_sufficiency == "medium"
    assert cashflow.lower_bound is None
    assert cashflow.upper_bound is None


def test_customer_priority_uses_linked_message_metadata_not_message_content(
    tmp_path: Path,
) -> None:
    database, ledger, service = build_service(tmp_path)
    snapshot = default_snapshot()
    snapshot["customers"] = [
        {
            "id": "customer-priority",
            "name": "待跟进客户",
            "source": "xianyu",
            "phone": "",
            "followUpStatus": "contacted",
            "lastContactAt": "2026-08-16T14:00:00+08:00",
            "level": "A",
        }
    ]
    ledger.save(snapshot, 0)
    with database.session() as session:
        conversation = Conversation(
            external_id="conversation-priority",
            customer_id="channel-customer",
            customer_name="渠道客户",
            unread_count=2,
            last_message_at=NOW - timedelta(hours=1),
        )
        session.add(conversation)
        session.flush()
        session.add(
            CustomerChannelIdentity(
                id="identity-priority",
                customer_id="customer-priority",
                channel="xianyu",
                external_customer_id="channel-customer",
                conversation_id=conversation.id,
                display_name="渠道客户",
            )
        )
        session.add(
            Message(
                external_id="message-priority",
                platform_message_id="message-priority",
                conversation_id=conversation.id,
                sender_id="channel-customer",
                sender_name="渠道客户",
                direction="inbound",
                content="这段正文不能进入预测快照",
                status="history",
                received_at=NOW - timedelta(hours=1),
            )
        )
        session.commit()

    priority = next(
        row
        for row in service.preview(now=NOW).results
        if row.target == "customer_followup_priority"
    )

    assert priority.score is not None and priority.score >= 75
    assert priority.risk_level == "urgent"
    assert priority.data_sufficiency == "medium"
    assert any(driver.code == "waiting_for_us" for driver in priority.drivers)
    serialized = priority.model_dump_json()
    assert "这段正文不能进入预测快照" not in serialized


def test_prediction_persistence_and_evaluation_are_idempotent(tmp_path: Path) -> None:
    database, _, service = build_service(tmp_path)

    created = service.run(request_id="prediction-run-request-0001", now=NOW)
    replay = service.run(request_id="prediction-run-request-0001", now=NOW)
    assert created.id == replay.id
    assert created.record_status == "completed"
    assert created.results[0].run_id == created.id

    result = created.results[0]
    evaluated = service.evaluate(
        result.id,
        request_id="prediction-evaluation-request-0001",
        actual_value=12.5,
        evaluation_method="manual",
        evaluated_at=NOW + timedelta(days=14),
        note="隔离测试",
    )
    repeated = service.evaluate(
        result.id,
        request_id="prediction-evaluation-request-0001",
        actual_value=12.5,
        evaluation_method="manual",
        evaluated_at=NOW + timedelta(days=14),
        note="隔离测试",
    )
    assert evaluated.actual_value == repeated.actual_value == 12.5
    with pytest.raises(PredictionEvaluationConflict):
        service.evaluate(
            result.id,
            request_id="prediction-evaluation-request-0001",
            actual_value=99,
            evaluation_method="manual",
            evaluated_at=NOW + timedelta(days=14),
            note="隔离测试",
        )

    with database.session() as session:
        assert session.scalar(select(func.count(PredictionRun.id))) == 1
        assert session.scalar(select(func.count(PredictionResultRecord.id))) == len(
            created.results
        )
        assert session.scalar(select(func.count(PredictionEvaluationRecord.id))) == 1


def test_new_prediction_run_idempotently_evaluates_mature_delay_from_verified_outcome(
    tmp_path: Path,
) -> None:
    database, ledger, service = build_service(tmp_path)
    snapshot = default_snapshot()
    snapshot["projects"] = [
        {
            "id": "project-delay-evaluation",
            "name": "延期评估项目",
            "projectKind": "personal",
            "startDate": "2026-08-01",
            "dueDate": "2026-08-16",
            "progress": 0,
            "status": "in_progress",
            "estimatedHours": 8,
        }
    ]
    snapshot["tasks"] = [
        {
            "id": "task-delay-evaluation",
            "projectId": "project-delay-evaluation",
            "title": "延期评估任务",
            "status": "todo",
            "estimatedHours": 8,
            "actualHours": 0,
        }
    ]
    ledger.save(snapshot, 0)
    first = service.run(request_id="prediction-delay-run-0001", now=NOW)
    result = next(row for row in first.results if row.target == "project_delay_risk")
    assert any(fact.key == "planned_due_date" for fact in result.facts)

    # Keep the synthetic evaluation cutoff after the database row timestamps
    # created by the test process; otherwise the outcome is correctly treated
    # as not yet available at the artificial cutoff.
    completed_at = max(
        NOW + timedelta(days=3),
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=1),
    )
    with database.session() as session:
        task = session.get(BusinessTask, "task-delay-evaluation")
        session.add_all(
            [
                CodexAcceptancePoint(
                    id="point-delay-evaluation",
                    project_id="project-delay-evaluation",
                    task_id=task.id,
                    point_key="AC-1",
                    title="完成并验收",
                    status="verified",
                    verified_at=completed_at,
                    created_at=completed_at,
                    updated_at=completed_at,
                ),
                ProjectTimeEntry(
                    id="time-delay-evaluation",
                    project_id="project-delay-evaluation",
                    task_id=task.id,
                    category="development",
                    source="manual",
                    hours=9,
                    note="验收后的真实工时",
                    occurred_at=completed_at,
                    created_at=completed_at,
                ),
            ]
        )
        session.commit()

    service.run(request_id="prediction-delay-run-0002", now=completed_at)
    repeated = service.evaluate_matured_project_delays(now=completed_at)
    assert repeated == 0
    with database.session() as session:
        evaluation = session.scalar(
            select(PredictionEvaluationRecord).where(
                PredictionEvaluationRecord.result_id == result.id
            )
        )
        assert evaluation is not None
        assert evaluation.evaluation_method == "ledger_actual"
        assert evaluation.actual_value_json == "true"


def test_prediction_api_exposes_live_preview_persisted_run_and_entity_reads(
    tmp_path: Path,
) -> None:
    database, ledger, service = build_service(tmp_path)
    snapshot = default_snapshot()
    snapshot["projects"] = [
        {
            "id": "project-api",
            "name": "接口项目",
            "customerId": "",
            "projectKind": "personal",
            "totalAmount": 0,
            "startDate": "2026-08-01",
            "dueDate": "2026-08-20",
            "progress": 25,
            "status": "in_progress",
            "type": "个人开发",
            "estimatedHours": 20,
            "accent": "purple",
        }
    ]
    ledger.save(snapshot, 0)
    app = FastAPI()
    app.state.runtime = SimpleNamespace(predictions=service)
    app.include_router(prediction_router)
    client = TestClient(app)

    live = client.get("/api/predictions")
    assert live.status_code == 200
    assert live.json()["run"]["record_status"] == "live"
    project = client.get("/api/predictions/projects/project-api")
    assert project.status_code == 200
    assert project.json()["target"] == "project_delay_risk"
    missing = client.get("/api/predictions/projects/missing")
    assert missing.status_code == 404
    created = client.post(
        "/api/predictions/runs",
        json={"request_id": "prediction-api-run-0001"},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["record_status"] == "completed"
    result_id = payload["results"][0]["id"]
    evaluated = client.post(
        f"/api/predictions/results/{result_id}/evaluations",
        json={
            "request_id": "prediction-api-evaluation-0001",
            "actual_value": 4.5,
            "evaluation_method": "manual",
            "note": "接口测试",
        },
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["actual_value"] == 4.5
    with database.session() as session:
        assert session.scalar(select(func.count(PredictionRun.id))) == 1


def test_business_analysis_reads_prediction_risks_as_manual_recommendations(
    tmp_path: Path,
) -> None:
    database, ledger, predictions = build_service(tmp_path)
    snapshot = default_snapshot()
    snapshot["settings"]["defaultDailyAvailableHours"] = 8
    snapshot["projects"] = [
        {
            "id": "project-analysis-risk",
            "name": "经营分析风险项目",
            "customerId": "",
            "projectKind": "personal",
            "totalAmount": 0,
            "startDate": "2026-07-01",
            "dueDate": "2026-08-15",
            "progress": 10,
            "status": "pending",
            "type": "个人开发",
            "estimatedHours": 112,
            "accent": "purple",
        }
    ]
    snapshot["tasks"] = [
        {
            "id": "task-analysis-risk",
            "projectId": "project-analysis-risk",
            "title": "风险任务",
            "status": "todo",
            "startDate": "2026-07-01",
            "dueDate": "2026-08-15",
            "estimatedHours": 112,
            "actualHours": 0,
        }
    ]
    ledger.save(snapshot, 0)
    analysis = BusinessAnalysisService(database, ledger, predictions=predictions)

    result = analysis.overview(now=NOW)
    insight_ids = {row.id for row in result.insights}
    recommendations = {row.source_key: row for row in result.recommendations}

    assert result.predictions
    assert result.prediction_snapshot_hash
    assert "predicted-workload-pressure" in insight_ids
    assert "predicted-project-delay-project-analysis-risk" in insight_ids
    assert recommendations["review-future-workload"].execution_mode == "manual"
    assert (
        recommendations["review-project-delay-project-analysis-risk"].entity_id
        == "project-analysis-risk"
    )
    assert all("概率" not in row.title for row in result.insights)


def test_business_analysis_reasoning_receives_redacted_prediction_payload(
    tmp_path: Path,
) -> None:
    database, ledger, predictions = build_service(tmp_path)
    snapshot = default_snapshot()
    snapshot["projects"] = [
        {
            "id": "project-redacted",
            "name": "不应传给模型的项目名称",
            "customerId": "",
            "projectKind": "personal",
            "totalAmount": 0,
            "startDate": "2026-08-01",
            "dueDate": "2026-08-18",
            "progress": 30,
            "status": "in_progress",
            "type": "个人开发",
            "estimatedHours": 20,
            "accent": "blue",
        }
    ]
    ledger.save(snapshot, 0)
    analysis = BusinessAnalysisService(database, ledger, predictions=predictions)

    payload = BusinessAnalysisReasoningService._prompt_payload(
        analysis.overview(now=NOW)
    )
    serialized = str(payload["predictions"])

    assert payload["predictions"]
    assert "entity_label" not in serialized
    assert "不应传给模型的项目名称" not in serialized
    assert "prediction_value" in serialized
    assert "evidence_refs" in serialized


@pytest.mark.asyncio
async def test_user_triggered_business_analysis_persists_prediction_run(
    tmp_path: Path,
) -> None:
    database, ledger, predictions = build_service(tmp_path)
    analysis = BusinessAnalysisService(database, ledger, predictions=predictions)

    result = await analysis.run_analysis(
        request_id="analysis-with-prediction-0001",
        provider="deepseek",
        now=NOW,
    )
    repeated = await analysis.run_analysis(
        request_id="analysis-with-prediction-0001",
        provider="deepseek",
        now=NOW,
    )

    assert result.prediction_run_id is not None
    assert repeated.prediction_run_id == result.prediction_run_id
    assert result.prediction_snapshot_hash
    with database.session() as session:
        assert session.scalar(select(func.count(PredictionRun.id))) == 1


def test_prediction_tool_is_read_only_and_uses_latest_service_result(
    tmp_path: Path,
) -> None:
    _, ledger, predictions = build_service(tmp_path)
    tool = BusinessPredictionTool(predictions)
    revision_before, snapshot_before = ledger.get()

    result = tool.get_business_predictions()
    missing_project = tool.get_project_prediction("missing")
    missing_customer = tool.get_customer_priority("missing")
    revision_after, snapshot_after = ledger.get()

    assert result["run"]["record_status"] == "live"
    assert result["workload"]["target"] == "workload_14d"
    assert missing_project is None
    assert missing_customer is None
    assert revision_after == revision_before
    assert snapshot_after == snapshot_before


def test_prediction_alembic_migration_creates_complete_integral_schema(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "prediction-migration.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO alembic_version(version_num) VALUES ('20260815_0022')"
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
    assert {
        "prediction_runs",
        "prediction_results",
        "prediction_evaluations",
    }.issubset(tables)
    assert integrity == ("ok",)
    assert violations == []


def test_prediction_startup_accepts_complete_schema_and_rejects_partial_schema(
    tmp_path: Path,
) -> None:
    complete_path = tmp_path / "prediction-complete.db"
    complete = Database(f"sqlite:///{complete_path}")
    complete.create_all()
    complete.create_all()

    partial_path = tmp_path / "prediction-partial.db"
    with sqlite3.connect(partial_path) as connection:
        connection.execute("CREATE TABLE ledger_state (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE prediction_runs (id TEXT PRIMARY KEY)")
    partial = Database(f"sqlite:///{partial_path}")
    with pytest.raises(RuntimeError, match="prediction schema is incomplete"):
        partial.create_all()
