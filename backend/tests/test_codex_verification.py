from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from backend.app.codex_sync_schemas import CodexEventInput
from backend.app.codex_verification_api import codex_verification_router
from backend.app.codex_verification_schemas import (
    AcceptanceDecisionInput,
    ManualTimeEntryInput,
    TimeAdjustmentInput,
    TestExecutionInput,
)
from backend.app.database import Database
from backend.app.ledger import LedgerService, default_snapshot
from backend.app.models import (
    BusinessProject,
    BusinessTask,
    CodexAcceptanceEvidence,
    CodexAcceptancePoint,
    CodexAcceptanceStatusHistory,
    CodexRun,
    ProjectTimeEntry,
)
from backend.app.services.codex_sync import CodexSyncService
from backend.app.services.codex_verification import CodexVerificationError, CodexVerificationService
from backend.app.services.event_hub import EventHub


NOW = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)


def build_fixture(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'verification.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    snapshot = default_snapshot()
    snapshot["projects"] = [
        {
            "id": "project-1", "name": "Verification", "projectKind": "personal",
            "progress": 73, "status": "in_progress", "estimatedHours": 10,
        }
    ]
    snapshot["tasks"] = [
        {
            "id": "task-1", "projectId": "project-1", "title": "Weighted task",
            "status": "todo", "estimatedHours": 8, "actualHours": 0,
        },
        {
            "id": "task-2", "projectId": "project-1", "title": "Small task",
            "status": "todo", "estimatedHours": 2, "actualHours": 0,
        },
    ]
    ledger.save(snapshot, 0)
    with database.session() as session:
        first = session.get(BusinessTask, "task-1")
        second = session.get(BusinessTask, "task-2")
        first.task_key = "DEV-001"
        first.acceptance_points_json = '[{"point_key":"AC-1","title":"Automated","verification_type":"automated_test"}]'
        first.test_commands_json = '["python -m pytest -q"]'
        second.task_key = "DEV-002"
        session.add_all(
            [
                CodexAcceptancePoint(
                    id="point-1", project_id="project-1", task_id="task-1",
                    point_key="AC-1", title="Automated", verification_type="automated_test",
                ),
                CodexAcceptancePoint(
                    id="point-2", project_id="project-1", task_id="task-2",
                    point_key="AC-2", title="Manual", verification_type="manual_check",
                ),
            ]
        )
        session.commit()
    hub = EventHub()
    verification = CodexVerificationService(database, ledger, hub)
    sync = CodexSyncService(database, hub, verification)
    return database, ledger, verification, sync


def test_progress_is_weighted_and_waiver_is_explicit(tmp_path: Path) -> None:
    database, ledger, service, _sync = build_fixture(tmp_path)
    initial = service.view("project-1")
    assert initial.progress.verified_delivery.percent == 0
    assert initial.legacy_progress is None

    verified = service.decide(
        "point-1",
        AcceptanceDecisionInput(
            request_id="verify-point-0001", expected_revision=initial.revision,
            status="verified", reason="人工检查通过",
        ),
    )
    assert verified.progress.verified_delivery.percent == 80
    assert verified.progress.implemented.percent == 80
    assert verified.progress_source == "verified"

    waived = service.decide(
        "point-2",
        AcceptanceDecisionInput(
            request_id="waive-point-0002", expected_revision=verified.revision,
            status="waived", reason="客户明确取消该范围", waived_counts=False,
        ),
    )
    assert waived.progress.verified_delivery.percent == 80
    assert waived.progress.waived_count == 1
    assert waived.progress.waived_counted == 0
    with database.session() as session:
        project = session.get(BusinessProject, "project-1")
        assert project.progress == 80
    revision, snapshot = ledger.get()
    assert revision == waived.revision
    assert snapshot["projects"][0]["progress"] == 80


def test_event_claim_and_test_create_audited_evidence_but_not_verified_progress(tmp_path: Path) -> None:
    database, _ledger, service, sync = build_fixture(tmp_path)
    complete = CodexEventInput(
        request_id="event-request-001", event_id="event-complete-001",
        project_id="project-1", source="mcp", external_session_id="session-1",
        event_type="task_complete", task_key="DEV-001", occurred_at=NOW,
        payload={"summary": "implemented"},
    )
    sync.ingest(complete)
    after_claim = service.view("project-1")
    point = next(row for row in after_claim.points if row.id == "point-1")
    assert point.status == "implemented"
    assert after_claim.progress.verified_delivery.percent == 0

    test = complete.model_copy(
        update={
            "request_id": "event-request-002", "event_id": "event-test-002",
            "event_type": "test_reported", "occurred_at": NOW + timedelta(minutes=1),
            "payload": {"command": "python -m pytest -q", "exit_code": 0, "summary": "12 passed"},
        }
    )
    sync.ingest(test)
    replay = sync.ingest(test)
    assert replay.idempotent is True
    after_test = service.view("project-1")
    point = next(row for row in after_test.points if row.id == "point-1")
    assert point.status == "test_passed"
    assert after_test.progress.implemented.percent == 80
    assert after_test.progress.verified_delivery.percent == 0
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(CodexAcceptanceEvidence)) == 1
        assert session.scalar(select(func.count()).select_from(CodexAcceptanceStatusHistory)) == 2


def test_missing_task_key_never_changes_acceptance(tmp_path: Path) -> None:
    database, _ledger, service, sync = build_fixture(tmp_path)
    sync.ingest(
        CodexEventInput(
            request_id="event-request-003", event_id="event-general-003",
            project_id="project-1", source="mcp", external_session_id="session-1",
            event_type="task_complete", task_key=None, occurred_at=NOW, payload={},
        )
    )
    assert all(point.status == "pending" for point in service.view("project-1").points)
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(CodexAcceptanceStatusHistory)) == 0


def test_time_is_append_only_and_legacy_snapshot_cannot_overwrite_it(tmp_path: Path) -> None:
    database, ledger, service, _sync = build_fixture(tmp_path)
    initial = service.view("project-1")
    added = service.add_time(
        "project-1",
        ManualTimeEntryInput(
            request_id="manual-time-0001", expected_revision=initial.revision,
            task_id="task-1", category="testing", hours=2.5, note="人工回归测试",
        ),
    )
    original = added.time.entries[0]
    adjusted = service.adjust_time(
        original.id,
        TimeAdjustmentInput(
            request_id="adjust-time-0002", expected_revision=added.revision,
            hours_delta=-0.5, reason="扣除休息时间",
        ),
    )
    assert adjusted.time.total_hours == 2.0
    assert len(adjusted.time.entries) == 2
    with pytest.raises(CodexVerificationError, match="小于 0"):
        service.adjust_time(
            original.id,
            TimeAdjustmentInput(
                request_id="adjust-time-0003", expected_revision=adjusted.revision,
                hours_delta=-3, reason="错误修正",
            ),
        )

    revision, snapshot = ledger.get()
    snapshot["tasks"][0]["actualHours"] = 999
    snapshot["projects"][0]["progress"] = 100
    snapshot["tasks"] = [row for row in snapshot["tasks"] if row["id"] != "task-1"]
    ledger.save(snapshot, revision)
    _revision, protected = ledger.get()
    protected_task = next(row for row in protected["tasks"] if row["id"] == "task-1")
    assert protected_task["actualHours"] == 2.0
    assert protected["projects"][0]["progress"] == 0
    with database.session() as session:
        assert session.get(BusinessTask, "task-1").actual_hours == 2.0
        assert session.scalar(select(func.count()).select_from(ProjectTimeEntry)) == 2


def test_run_time_counts_only_explicit_active_intervals(tmp_path: Path) -> None:
    database, ledger, service, _sync = build_fixture(tmp_path)
    with database.session() as session:
        run = CodexRun(
            id="run-1", project_id="project-1", source="app_server",
            external_session_id="run-1", runtime_type="app_server",
            task_key="DEV-001", status="running", started_at=NOW, last_event_at=NOW,
        )
        session.add(run)
        service.open_active_interval(session, run, started_at=NOW)
        session.commit()
    with database.session() as session:
        run = session.get(CodexRun, "run-1")
        service.close_active_interval(
            session, run, stop_reason="waiting_approval", ended_at=NOW + timedelta(hours=1)
        )
        session.commit()
    # The two-hour approval wait is not represented by an interval.
    with database.session() as session:
        run = session.get(CodexRun, "run-1")
        service.open_active_interval(session, run, started_at=NOW + timedelta(hours=3))
        session.commit()
    with database.session() as session:
        run = session.get(CodexRun, "run-1")
        service.close_active_interval(
            session, run, stop_reason="completed", ended_at=NOW + timedelta(hours=3, minutes=30)
        )
        session.commit()
    view = service.view("project-1")
    assert view.time.codex_hours == 1.5
    _revision, snapshot = ledger.get()
    assert next(row for row in snapshot["tasks"] if row["id"] == "task-1")["actualHours"] == 1.5


def test_test_command_parser_rejects_shell_and_delivery_actions() -> None:
    assert CodexVerificationService._test_argv("python -m pytest -q") == [
        "python", "-m", "pytest", "-q"
    ]
    for command in (
        "pytest -q && git push",
        "pytest -q | tee result.txt",
        "git commit -am test",
        "npm install",
        "wrangler deploy",
        "rm -rf build",
        "python -c 'import os; os.remove(\"README.md\")'",
    ):
        with pytest.raises(CodexVerificationError):
            CodexVerificationService._test_argv(command)


def test_loopback_verification_api_and_revision_conflict(tmp_path: Path) -> None:
    _database, _ledger, service, _sync = build_fixture(tmp_path)
    app = FastAPI()
    app.include_router(codex_verification_router)
    app.state.runtime = SimpleNamespace(
        codex_verification=service,
        sample_formation=service.sample_formation,
    )
    client = TestClient(app)

    current = client.get("/api/projects/project-1/verification")
    assert current.status_code == 200
    body = current.json()
    assert body["progress"]["verified_delivery"]["percent"] == 0
    assert body["revision"] == 1
    assert body["sample_readiness"]["status"] == "needs_verification"

    accepted = client.post(
        "/api/acceptance-points/point-1/decision",
        json={
            "request_id": "api-verify-point-0001",
            "expected_revision": body["revision"],
            "status": "verified",
            "reason": "API 人工核验通过",
            "waived_counts": False,
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["progress"]["verified_delivery"]["percent"] == 80

    stale = client.post(
        "/api/projects/project-1/time-entries",
        json={
            "request_id": "api-stale-time-0002",
            "expected_revision": body["revision"],
            "task_id": "task-1",
            "category": "testing",
            "hours": 1,
            "note": "旧页面写入",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"


@pytest.mark.asyncio
async def test_confirmed_test_runs_only_in_managed_worktree(tmp_path: Path) -> None:
    database, ledger, _service, _sync = build_fixture(tmp_path)
    managed_root = tmp_path / "managed"
    worktree = managed_root / "project-1" / "run-1"
    worktree.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    )
    (worktree / "README.md").write_text("fixture\n", encoding="utf-8")
    with database.session() as session:
        task = session.get(BusinessTask, "task-1")
        task.test_commands_json = '["test -s README.md"]'
        session.add(
            CodexRun(
                id="run-test", project_id="project-1", source="app_server",
                external_session_id="run-test", runtime_type="app_server",
                task_key="DEV-001", worktree_path=str(worktree), status="paused",
                started_at=NOW, last_event_at=NOW,
            )
        )
        session.commit()
    service = CodexVerificationService(
        database,
        ledger,
        EventHub(),
        managed_worktree_root=managed_root,
    )
    current = service.view("project-1")
    result = await service.run_test(
        "project-1",
        TestExecutionInput(
            request_id="run-confirmed-test-0001",
            expected_revision=current.revision,
            point_id="point-1",
            command="test -s README.md",
            timeout_seconds=5,
            confirmed=True,
        ),
    )
    assert next(point for point in result.points if point.id == "point-1").status == "test_passed"
    assert result.progress.verified_delivery.percent == 0

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".git").mkdir()
    with database.session() as session:
        session.get(CodexRun, "run-test").worktree_path = str(outside)
        session.commit()
    with pytest.raises(CodexVerificationError, match="托管 Worktree 根目录"):
        await service.run_test(
            "project-1",
            TestExecutionInput(
                request_id="run-confirmed-test-0002",
                expected_revision=result.revision,
                point_id="point-1",
                command="test -s README.md",
                timeout_seconds=5,
                confirmed=True,
            ),
        )
