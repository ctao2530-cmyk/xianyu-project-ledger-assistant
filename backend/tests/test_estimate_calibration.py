from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from backend.app.database import Database
from backend.app.codex_verification_schemas import ProjectOutcomeFreezeInput
from backend.app.ledger import LedgerService, default_snapshot
from backend.app.models import (
    BusinessProject,
    BusinessTask,
    CodexAcceptancePoint,
    EstimateCalibrationDecision,
    EstimateCalibrationMutationRequest,
    EstimateCalibrationRun,
    EstimateCalibrationSample,
    EstimateCalibrationSuggestion,
    ProjectOutcomeFreeze,
    ProjectTimeEntry,
)
from backend.app.prediction.calibration_repository import (
    CalibrationRequestConflict,
    CalibrationRevisionConflict,
)
from backend.app.prediction.calibration_schemas import CalibrationDecisionRequest
from backend.app.prediction.calibration_service import EstimateCalibrationService
from backend.app.prediction_api import prediction_router
from backend.app.services.event_hub import EventHub
from backend.app.services.project_outcomes import ProjectOutcomeService
from backend.app.services.project_progress import ProjectProgressService
from backend.app.services.project_sample_formation import ProjectSampleFormationService


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def build_calibration(
    tmp_path: Path,
    *,
    project_count: int = 5,
    freeze_results: bool = True,
) -> tuple[Database, EstimateCalibrationService]:
    database = Database(f"sqlite:///{tmp_path / 'calibration.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    snapshot = default_snapshot()
    snapshot["projects"] = []
    snapshot["tasks"] = []
    for index in range(project_count):
        project_id = f"calibration-project-{index + 1}"
        task_id = f"calibration-task-{index + 1}"
        estimated = float(10 + index)
        snapshot["projects"].append(
            {
                "id": project_id,
                "name": f"Calibration {index + 1}",
                "projectKind": "personal",
                "progress": 100,
                "status": "completed",
                "estimatedHours": estimated,
                "startDate": "2026-07-01",
                "dueDate": "2026-07-20",
            }
        )
        snapshot["tasks"].append(
            {
                "id": task_id,
                "projectId": project_id,
                "title": f"Task {index + 1}",
                "status": "done",
                "estimatedHours": estimated,
                "actualHours": 0,
            }
        )
    ledger.save(snapshot, 0)
    with database.session() as session:
        for index in range(project_count):
            project_id = f"calibration-project-{index + 1}"
            task_id = f"calibration-task-{index + 1}"
            completed_at = NOW - timedelta(days=project_count - index + 2)
            point = CodexAcceptancePoint(
                id=f"calibration-point-{index + 1}",
                project_id=project_id,
                task_id=task_id,
                point_key="AC-1",
                title="Verified delivery",
                status="verified",
                verified_at=completed_at,
                created_at=completed_at,
                updated_at=completed_at,
            )
            actual = float(8 + index * 2)
            entry = ProjectTimeEntry(
                id=f"calibration-time-{index + 1}",
                project_id=project_id,
                task_id=task_id,
                category="development",
                source="manual",
                hours=actual,
                note="verified actual",
                occurred_at=completed_at,
                created_at=completed_at,
            )
            session.add_all([point, entry])
        session.commit()
    outcomes = ProjectOutcomeService()
    progress = ProjectProgressService()
    sample_formation = ProjectSampleFormationService(
        database,
        ledger,
        EventHub(),
        outcomes=outcomes,
        progress=progress,
    )
    revision, _ = ledger.get()
    if freeze_results:
        for index in range(project_count):
            sample_formation.freeze(
                f"calibration-project-{index + 1}",
                ProjectOutcomeFreezeInput(
                    request_id=f"calibration-freeze-request-{index + 1:04d}",
                    expected_revision=revision,
                    confirmed_scope_complete=True,
                    confirmed_time_complete=True,
                    confirmation_note="人工确认验收范围和工时记录完整",
                ),
            )
    return database, EstimateCalibrationService(
        database,
        outcomes=outcomes,
        progress=progress,
        sample_formation=sample_formation,
    )


def test_zero_sample_state_is_truthful_and_read_only(tmp_path: Path) -> None:
    database, service = build_calibration(tmp_path, project_count=0)
    summary = service.summary(cutoff_at=NOW)
    assert summary.record_status == "live"
    assert summary.sample_count == 0
    assert summary.sufficiency == "insufficient"
    assert summary.metrics.mae_hours is None
    assert summary.metrics.overrun_rate is None
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(EstimateCalibrationRun)) == 0
        assert session.scalar(select(func.count()).select_from(EstimateCalibrationSample)) == 0


@pytest.mark.parametrize("claimed_status", ["implemented", "test_passed"])
def test_legacy_progress_and_codex_claims_never_form_samples_without_freeze(
    tmp_path: Path,
    claimed_status: str,
) -> None:
    database, service = build_calibration(
        tmp_path,
        project_count=1,
        freeze_results=False,
    )
    with database.session() as session:
        point = session.get(CodexAcceptancePoint, "calibration-point-1")
        point.status = claimed_status
        point.verified_at = None
        session.commit()
    summary = service.summary(cutoff_at=NOW + timedelta(days=1))
    assert summary.sample_count == 0
    assert summary.candidates[0].eligible is False
    assert summary.candidates[0].freeze_id is None
    assert summary.candidates[0].exclusion_code in {
        "verification_incomplete",
        "verified_progress_incomplete",
    }


def test_stale_freeze_is_excluded_until_append_only_refreeze(tmp_path: Path) -> None:
    database, service = build_calibration(tmp_path, project_count=1)
    with database.session() as session:
        session.add(
            ProjectTimeEntry(
                id="calibration-stale-time",
                project_id="calibration-project-1",
                task_id="calibration-task-1",
                category="fixing",
                source="manual_adjustment",
                hours=1,
                note="冻结后补记工时",
                occurred_at=NOW,
                created_at=NOW,
            )
        )
        session.commit()
    summary = service.summary(cutoff_at=NOW + timedelta(days=1))
    assert summary.sample_count == 0
    assert summary.candidates[0].exclusion_code == "stale_freeze"
    assert summary.candidates[0].freeze_stale is True


def test_five_verified_results_create_immutable_samples_and_actionable_suggestions(
    tmp_path: Path,
) -> None:
    database, service = build_calibration(tmp_path)
    cutoff = NOW + timedelta(days=1)
    created = service.run(request_id="calibration-run-request-0001", cutoff_at=cutoff)
    replay = service.run(request_id="calibration-run-request-0001", cutoff_at=cutoff)

    assert created.run_id == replay.run_id
    assert created.sample_count == 5
    assert created.sufficiency == "actionable"
    assert created.metrics.mae_hours is not None
    assert created.metrics.multiplier_median is not None
    assert created.metrics.interval_coverage is None
    quote = service.quote_assist("calibration-project-1")
    assert quote.status == "pending"
    assert quote.suggestion_id
    assert quote.original_estimated_hours == 10
    assert quote.suggested_hours is not None
    assert quote.lower_hours <= quote.suggested_hours <= quote.upper_hours
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(EstimateCalibrationRun)) == 1
        assert session.scalar(select(func.count()).select_from(EstimateCalibrationSample)) == 5
        assert session.scalar(select(func.count()).select_from(EstimateCalibrationSuggestion)) == 5
        assert session.scalar(select(func.count()).select_from(EstimateCalibrationMutationRequest)) == 1


def test_cutoff_excludes_future_finalization_and_prevents_leakage(tmp_path: Path) -> None:
    database, service = build_calibration(tmp_path)
    with database.session() as session:
        freeze = session.scalar(
            select(ProjectOutcomeFreeze).where(
                ProjectOutcomeFreeze.project_id == "calibration-project-5"
            )
        )
        outcome = json.loads(freeze.outcome_json)
        future = NOW + timedelta(days=2)
        outcome["available_at"] = NOW.isoformat()
        outcome["finalized_at"] = future.isoformat()
        freeze.outcome_json = json.dumps(outcome)
        freeze.frozen_at = future
        session.commit()
    cutoff = NOW + timedelta(days=1)
    summary = service._live_summary(cutoff)  # noqa: SLF001 - explicit causal-boundary test
    assert summary.sample_count < 5
    future = [row for row in summary.candidates if row.exclusion_code == "future_finalized"]
    assert future
    assert all(not row.eligible for row in future)


def test_decision_is_revision_guarded_idempotent_and_never_changes_project_estimate(
    tmp_path: Path,
) -> None:
    database, service = build_calibration(tmp_path)
    service.run(
        request_id="calibration-run-request-0002",
        cutoff_at=NOW + timedelta(days=1),
    )
    quote = service.quote_assist("calibration-project-1")
    assert quote.suggestion_id
    request = CalibrationDecisionRequest(
        request_id="calibration-decision-request-0001",
        expected_revision=quote.suggestion_revision,
        action="adopt",
        adopted_hours=12.5,
        note="人工结合范围后采用",
    )
    decided = service.decide("calibration-project-1", quote.suggestion_id, request)
    replay = service.decide("calibration-project-1", quote.suggestion_id, request)
    assert decided.status == replay.status == "adopted"
    assert decided.adopted_hours == 12.5
    assert decided.suggestion_revision == 1
    with pytest.raises(CalibrationRevisionConflict):
        service.decide(
            "calibration-project-1",
            quote.suggestion_id,
            request.model_copy(
                update={
                    "request_id": "calibration-decision-request-0002",
                    "adopted_hours": 13,
                }
            ),
        )
    with pytest.raises(CalibrationRequestConflict):
        service.decide(
            "calibration-project-1",
            quote.suggestion_id,
            request.model_copy(update={"adopted_hours": 13}),
        )
    with database.session() as session:
        project = session.get(BusinessProject, "calibration-project-1")
        assert project.estimated_hours == 10
        assert session.scalar(select(func.count()).select_from(EstimateCalibrationDecision)) == 1


def test_calibration_api_keeps_reads_separate_from_explicit_writes(tmp_path: Path) -> None:
    database, service = build_calibration(tmp_path)
    app = FastAPI()
    app.state.runtime = SimpleNamespace(estimate_calibration=service)
    app.include_router(prediction_router)
    client = TestClient(app)

    live = client.get("/api/predictions/calibration")
    assert live.status_code == 200
    assert live.json()["record_status"] == "live"
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(EstimateCalibrationRun)) == 0
    created = client.post(
        "/api/predictions/calibration/runs",
        json={
            "request_id": "calibration-api-run-0001",
            "cutoff_at": (NOW + timedelta(days=1)).isoformat(),
        },
    )
    assert created.status_code == 201
    quote = client.get(
        "/api/predictions/calibration/projects/calibration-project-1"
    )
    assert quote.status_code == 200
    assert quote.json()["status"] == "pending"


def test_calibration_startup_rejects_partial_schema(tmp_path: Path) -> None:
    complete = Database(f"sqlite:///{tmp_path / 'complete.db'}")
    complete.create_all()
    complete.create_all()

    partial_path = tmp_path / "partial.db"
    with sqlite3.connect(partial_path) as connection:
        connection.execute("CREATE TABLE business_projects (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE prediction_runs (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE prediction_results (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE prediction_evaluations (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE estimate_calibration_runs (id TEXT PRIMARY KEY)")
    partial = Database(f"sqlite:///{partial_path}")
    with pytest.raises(RuntimeError, match="estimate calibration schema is incomplete"):
        partial.create_all()


def test_calibration_alembic_migration_advances_0029_to_0030(tmp_path: Path) -> None:
    database_path = tmp_path / "calibration-migration.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO alembic_version(version_num) VALUES ('20260818_0029')"
        )
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260818_0030"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(database_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
    assert version == ("20260818_0030",)
    assert {
        "estimate_calibration_samples",
        "estimate_calibration_runs",
        "estimate_calibration_suggestions",
        "estimate_calibration_decisions",
        "estimate_calibration_mutation_requests",
    }.issubset(tables)
    assert integrity == ("ok",)
