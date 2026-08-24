from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import func, select

from backend.app.codex_verification_schemas import (
    ManualAcceptancePointItem,
    ManualAcceptancePointsInput,
    ProjectOutcomeFreezeInput,
    RetireAcceptancePointInput,
)
from backend.app.database import Database
from backend.app.ledger import LedgerService, RevisionConflict, default_snapshot
from backend.app.models import (
    CodexAcceptancePoint,
    CodexAcceptanceStatusHistory,
    CodexDevelopmentPlan,
    ProjectOutcomeFreeze,
    ProjectOutcomeFreezeMutationRequest,
    ProjectSettlementIssueRecord,
    ProjectTimeEntry,
    RequirementCase,
    RequirementDocumentVersion,
)
from backend.app.services.event_hub import EventHub
from backend.app.services.project_sample_formation import (
    ProjectSampleFormationError,
    ProjectSampleFormationService,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def build_service(
    tmp_path: Path,
    *,
    estimated_hours: float = 8,
) -> tuple[Database, LedgerService, ProjectSampleFormationService, int]:
    database = Database(f"sqlite:///{tmp_path / 'sample-formation.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    snapshot = default_snapshot()
    snapshot["customers"] = [
        {
            "id": "sample-customer",
            "name": "样本客户",
            "source": "other",
            "phone": "",
            "followUpStatus": "contacted",
            "lastContactAt": "",
            "level": "C",
            "tags": [],
        }
    ]
    snapshot["projects"] = [
        {
            "id": "sample-project",
            "name": "历史交付项目",
            "customerId": "sample-customer",
            "projectKind": "client",
            "status": "completed",
            "progress": 100,
            "estimatedHours": estimated_hours,
            "startDate": "2026-08-01",
            "dueDate": "2026-08-10",
        }
    ]
    snapshot["tasks"] = [
        {
            "id": "sample-task",
            "projectId": "sample-project",
            "title": "真实交付任务",
            "status": "done",
            "estimatedHours": estimated_hours,
            "actualHours": 0,
        }
    ]
    revision, _ = ledger.save(snapshot, 0)
    return database, ledger, ProjectSampleFormationService(database, ledger, EventHub()), revision


def manual_scope(revision: int, *, request_id: str = "manual-scope-request-0001") -> ManualAcceptancePointsInput:
    return ManualAcceptancePointsInput(
        request_id=request_id,
        expected_revision=revision,
        reason="按历史交付资料人工建立验收范围",
        points=[
            ManualAcceptancePointItem(
                task_id="sample-task",
                point_key="HIST-AC-001",
                title="用户确认核心交付可用",
                verification_type="manual_test",
            )
        ],
    )


def make_ready(
    database: Database,
    service: ProjectSampleFormationService,
    revision: int,
) -> int:
    revision = service.create_manual_points("sample-project", manual_scope(revision))
    with database.session() as session:
        point = session.scalar(
            select(CodexAcceptancePoint).where(
                CodexAcceptancePoint.project_id == "sample-project",
                CodexAcceptancePoint.active.is_(True),
            )
        )
        point.status = "verified"
        point.verified_at = NOW
        point.updated_at = NOW
        session.add(
            ProjectTimeEntry(
                id="sample-time-entry",
                project_id="sample-project",
                task_id="sample-task",
                category="development",
                source="manual",
                hours=9,
                note="人工确认的完整项目工时",
                occurred_at=NOW,
                created_at=NOW,
            )
        )
        session.commit()
    return revision


def freeze_input(revision: int, request_id: str) -> ProjectOutcomeFreezeInput:
    return ProjectOutcomeFreezeInput(
        request_id=request_id,
        expected_revision=revision,
        confirmed_scope_complete=True,
        confirmed_time_complete=True,
        confirmation_note="已逐项核验范围、证据与工时完整性",
    )


def test_manual_scope_is_task_bound_idempotent_revision_guarded_and_retirable(
    tmp_path: Path,
) -> None:
    database, _, service, revision = build_service(tmp_path)
    created_revision = service.create_manual_points("sample-project", manual_scope(revision))
    assert service.create_manual_points("sample-project", manual_scope(revision)) == created_revision
    with database.session() as session:
        point = session.scalar(select(CodexAcceptancePoint))
        assert point.source == "manual_historical"
        assert point.task_id == "sample-task"
        assert point.active is True
        assert session.scalar(select(func.count()).select_from(CodexAcceptancePoint)) == 1

    with pytest.raises(ProjectSampleFormationError, match="请求编号已用于不同"):
        service.create_manual_points(
            "sample-project",
            manual_scope(revision).model_copy(
                update={
                    "reason": "改变请求内容",
                }
            ),
        )
    with pytest.raises(RevisionConflict):
        service.create_manual_points(
            "sample-project",
            manual_scope(created_revision, request_id="manual-scope-request-0002").model_copy(
                update={"expected_revision": revision}
            ),
        )
    with pytest.raises(ProjectSampleFormationError, match="有效任务"):
        service.create_manual_points(
            "sample-project",
            ManualAcceptancePointsInput(
                request_id="manual-scope-request-0003",
                expected_revision=created_revision,
                reason="尝试绑定其他项目任务",
                points=[
                    ManualAcceptancePointItem(
                        task_id="missing-task",
                        point_key="HIST-AC-002",
                        title="错误任务验收点",
                        verification_type="manual_test",
                    )
                ],
            ),
        )

    retired_revision = service.retire_manual_point(
        point.id,
        RetireAcceptancePointInput(
            request_id="retire-manual-point-0001",
            expected_revision=created_revision,
            reason="误建验收范围，保留审计后退役",
        ),
    )
    assert service.retire_manual_point(
        point.id,
        RetireAcceptancePointInput(
            request_id="retire-manual-point-0001",
            expected_revision=created_revision,
            reason="误建验收范围，保留审计后退役",
        ),
    ) == retired_revision
    with database.session() as session:
        retired = session.get(CodexAcceptancePoint, point.id)
        assert retired.active is False
        assert retired.status == "waived"
        assert retired.retired_at is not None
        assert session.scalar(select(func.count()).select_from(CodexAcceptanceStatusHistory)) == 2
    with pytest.raises(ProjectSampleFormationError, match="不能复用"):
        service.create_manual_points(
            "sample-project",
            manual_scope(retired_revision, request_id="manual-scope-request-0004"),
        )


def test_confirmed_codex_plan_prevents_manual_historical_scope_bypass(tmp_path: Path) -> None:
    database, _, service, revision = build_service(tmp_path)
    with database.session() as session:
        case = RequirementCase(
            id="sample-case",
            customer_id="sample-customer",
            title="确认计划需求",
            status="approved",
            current_version=1,
            project_id="sample-project",
        )
        session.add(case)
        session.flush()
        version = RequirementDocumentVersion(
            case_id=case.id,
            version=1,
            title="确认计划需求",
            readiness="approved",
            change_summary="确认范围",
            structured_json="{}",
            content_markdown="# 需求",
            model="manual",
        )
        session.add(version)
        session.flush()
        session.add(
            CodexDevelopmentPlan(
                id="sample-confirmed-plan",
                requirement_case_id=case.id,
                requirement_version_id=version.id,
                project_id="sample-project",
                version=1,
                status="confirmed",
                raw_structured_json="{}",
                structured_json="{}",
                estimate_low_hours=6,
                estimate_expected_hours=8,
                estimate_high_hours=10,
            )
        )
        session.commit()
    with pytest.raises(ProjectSampleFormationError, match="已有确认 Codex 计划"):
        service.create_manual_points("sample-project", manual_scope(revision))


@pytest.mark.parametrize(
    ("mode", "blocker"),
    [
        ("no_scope", "acceptance_scope_missing"),
        ("pending", "verification_incomplete"),
        ("waived", "waiver_present"),
        ("zero_estimate", "estimate_missing"),
        ("zero_actual", "actual_hours_missing"),
        ("terminal", "terminal_project"),
    ],
)
def test_freeze_rejects_incomplete_or_ineligible_project_facts(
    tmp_path: Path,
    mode: str,
    blocker: str,
) -> None:
    database, _, service, revision = build_service(
        tmp_path,
        estimated_hours=0 if mode == "zero_estimate" else 8,
    )
    if mode != "no_scope":
        revision = service.create_manual_points("sample-project", manual_scope(revision))
        with database.session() as session:
            point = session.scalar(select(CodexAcceptancePoint))
            if mode == "waived":
                point.status = "waived"
                point.waived_counts = True
            elif mode not in {"pending"}:
                point.status = "verified"
                point.verified_at = NOW
                point.updated_at = NOW
            if mode not in {"zero_actual", "pending", "waived"}:
                session.add(
                    ProjectTimeEntry(
                        id=f"time-{mode}",
                        project_id="sample-project",
                        task_id="sample-task",
                        category="development",
                        source="manual",
                        hours=3,
                        note="真实工时",
                        occurred_at=NOW,
                        created_at=NOW,
                    )
                )
            if mode == "terminal":
                session.add(
                    ProjectSettlementIssueRecord(
                        id="terminal-issue",
                        project_id="sample-project",
                        customer_id="sample-customer",
                        issue_type="cooperation_terminated",
                        reason="合作终止",
                        request_id="terminal-issue-request",
                    )
                )
            session.commit()
    readiness = service.readiness("sample-project")
    assert blocker in {row.code for row in readiness.blockers}
    assert readiness.can_freeze is False
    with pytest.raises(ProjectSampleFormationError, match="尚未满足结果冻结条件"):
        service.freeze(
            "sample-project",
            freeze_input(revision, f"freeze-blocked-{mode}-request"),
        )


def test_freeze_is_immutable_idempotent_stale_aware_and_append_only(tmp_path: Path) -> None:
    database, _, service, revision = build_service(tmp_path)
    revision = make_ready(database, service, revision)
    first_request = freeze_input(revision, "freeze-ready-request-0001")
    first = service.freeze("sample-project", first_request)
    replay = service.freeze("sample-project", first_request)
    same_facts = service.freeze(
        "sample-project",
        freeze_input(revision, "freeze-ready-request-0002"),
    )
    assert replay.id == same_facts.id == first.id
    assert first.version == 1
    assert first.is_stale is False
    assert service.readiness("sample-project").calibration_eligible is True

    with database.session() as session:
        session.add(
            ProjectTimeEntry(
                id="sample-time-adjustment",
                project_id="sample-project",
                task_id="sample-task",
                category="fixing",
                source="manual_adjustment",
                hours=1,
                adjustment_of_id="sample-time-entry",
                note="补记返工工时",
                occurred_at=NOW,
                created_at=NOW,
            )
        )
        session.commit()
    stale = service.readiness("sample-project")
    assert stale.status == "stale"
    assert stale.calibration_eligible is False
    assert stale.latest_freeze and stale.latest_freeze.is_stale is True

    second = service.freeze(
        "sample-project",
        freeze_input(revision, "freeze-ready-request-0003"),
    )
    assert second.version == 2
    assert second.supersedes_freeze_id == first.id
    assert second.outcome.actual_hours == 10
    history = service.freezes("sample-project")
    assert [row.version for row in history] == [2, 1]
    assert history[1].outcome.actual_hours == 9
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ProjectOutcomeFreeze)) == 2
        assert (
            session.scalar(
                select(func.count()).select_from(ProjectOutcomeFreezeMutationRequest)
            )
            == 4
        )


def test_readiness_and_freeze_gets_do_not_write(tmp_path: Path) -> None:
    database, _, service, _ = build_service(tmp_path)
    before = {}
    with database.session() as session:
        for model in (ProjectOutcomeFreeze, ProjectOutcomeFreezeMutationRequest):
            before[model.__tablename__] = session.scalar(select(func.count()).select_from(model))
    service.readiness("sample-project")
    assert service.freezes("sample-project") == []
    with database.session() as session:
        for model in (ProjectOutcomeFreeze, ProjectOutcomeFreezeMutationRequest):
            assert session.scalar(select(func.count()).select_from(model)) == before[model.__tablename__]


def test_0030_to_0031_migration_and_startup_schema_guards(tmp_path: Path) -> None:
    database_path = tmp_path / "phase-0031.db"
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
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260818_0031"],
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
        point_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(codex_acceptance_points)")
        }
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert version == ("20260818_0031",)
    assert {
        "project_outcome_freezes",
        "project_outcome_freeze_mutation_requests",
    }.issubset(tables)
    assert "source" in point_columns

    complete = Database(f"sqlite:///{tmp_path / 'complete-startup.db'}")
    complete.create_all()
    complete.create_all()

    partial_path = tmp_path / "partial-startup.db"
    partial = Database(f"sqlite:///{partial_path}")
    partial.create_all()
    with sqlite3.connect(partial_path) as connection:
        connection.execute("DROP TABLE project_outcome_freeze_mutation_requests")
    with pytest.raises(RuntimeError, match="project outcome freeze schema is incomplete"):
        partial.create_all()

    alembic_partial_path = tmp_path / "partial-alembic-0031.db"
    partial_environment = os.environ.copy()
    partial_environment["DATABASE_URL"] = f"sqlite:///{alembic_partial_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260818_0030"],
        cwd=PROJECT_ROOT,
        env=partial_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(alembic_partial_path) as connection:
        connection.execute(
            "ALTER TABLE codex_acceptance_points ADD COLUMN source "
            "VARCHAR(32) NOT NULL DEFAULT 'codex_plan'"
        )
        connection.execute("CREATE TABLE project_outcome_freezes (id TEXT PRIMARY KEY)")
    rejected = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260818_0031"],
        cwd=PROJECT_ROOT,
        env=partial_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "project outcome freeze schema is partial" in rejected.stderr
