from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import select

from backend.app.codex_runtime_schemas import ManagedRunCreateInput
from backend.app.database import Database
from backend.app.models import (
    BusinessCustomer,
    BusinessProject,
    BusinessTask,
    CodexDevelopmentPlan,
    CodexProjectBinding,
    CodexRun,
    CodexRunApproval,
    RequirementCase,
    RequirementDocumentVersion,
)
from backend.app.services.codex_development import CodexDevelopmentService
from backend.app.services.codex_runtime import MockDevelopmentRuntime, RuntimeEvent, WorktreeError, WorktreeManager
from backend.app.services.codex_sync import CodexSyncService
from backend.app.services.event_hub import EventHub


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "customer-repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "fixture@example.com")
    git(repo, "config", "user.name", "Fixture")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "fixture")
    return repo, git(repo, "rev-parse", "HEAD")


def test_worktree_is_contained_and_preserves_dirty_main_workspace(tmp_path: Path) -> None:
    repo, head = repository(tmp_path)
    (repo / "README.md").write_text("user dirty change\n", encoding="utf-8")
    manager = WorktreeManager(tmp_path / "managed")
    with pytest.raises(WorktreeError, match="未提交"):
        manager.create(
            repository_path=str(repo), project_id="../project", task_key="DEV/001",
            run_id="run-one", expected_head_sha=head, acknowledge_dirty=False,
        )
    created = manager.create(
        repository_path=str(repo), project_id="../project", task_key="DEV/001",
        run_id="run-one", expected_head_sha=head, acknowledge_dirty=True,
    )
    assert manager.managed_root in created.worktree_path.parents
    assert created.worktree_path != repo
    assert git(repo, "branch", "--show-current") == "main"
    assert (repo / "README.md").read_text() == "user dirty change\n"
    assert (created.worktree_path / "README.md").read_text() == "fixture\n"
    assert created.branch.startswith("codex/project/DEV-001-")
    with pytest.raises(WorktreeError, match="HEAD"):
        manager.create(
            repository_path=str(repo), project_id="p", task_key="t", run_id="two",
            expected_head_sha="0" * 40, acknowledge_dirty=True,
        )
    with pytest.raises(WorktreeError, match="不得与绑定仓库重叠"):
        WorktreeManager(repo / "nested-managed").create(
            repository_path=str(repo), project_id="p", task_key="t", run_id="three",
            expected_head_sha=head, acknowledge_dirty=True,
        )


def build_managed_service(tmp_path: Path):
    repo, head = repository(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'managed.db'}")
    database.create_all()
    requirement = {
        "title": "Fixture project",
        "project_goal": "Change the fixture safely",
        "assumptions": [],
    }
    plan = {
        "title": "Fixture plan",
        "assumptions": [],
        "tasks": [{
            "task_key": "DEV-001", "title": "Edit fixture", "description": "Make a tiny change",
            "depends_on": [], "expected_paths": ["README.md"],
            "acceptance_points": [{"point_key": "AC-1", "title": "test passes"}],
            "test_commands": ["test -s README.md"], "risks": [],
        }],
    }
    with database.session() as session:
        session.add(BusinessCustomer(id="customer-1", name="Fixture"))
        session.flush()
        session.add(RequirementCase(id="case-1", customer_id="customer-1", title="Fixture", status="approved", current_version=1, project_id="project-1"))
        session.add(BusinessProject(id="project-1", name="Fixture project", customer_id="customer-1", status="in_progress", progress=13))
        session.flush()
        version = RequirementDocumentVersion(case_id="case-1", version=1, title="Fixture", readiness="approved", change_summary="approved", structured_json=json.dumps(requirement), content_markdown="# Fixture", model="manual")
        session.add(version)
        session.flush()
        binding = CodexProjectBinding(id="binding-1", project_id="project-1", requirement_case_id="case-1", repository_path=str(repo), default_branch="main", current_head_sha=head, enabled=True)
        session.add(binding)
        session.flush()
        development_plan = CodexDevelopmentPlan(
            id="plan-1", requirement_case_id="case-1", requirement_version_id=version.id,
            project_id="project-1", binding_id="binding-1", version=1, status="confirmed",
            source="codex_cli", repository_mode="repository", repository_head_sha=head,
            repository_branch="main", repository_dirty=False,
            raw_structured_json=json.dumps(plan), structured_json=json.dumps(plan),
            estimate_low_hours=1, estimate_expected_hours=2, estimate_high_hours=3,
            model="fixture",
        )
        session.add(development_plan)
        session.flush()
        session.add(BusinessTask(
            id="task-1", project_id="project-1", title="Edit fixture", task_key="DEV-001",
            codex_plan_id="plan-1", status="todo", codex_execution_status="todo",
            acceptance_points_json=json.dumps(plan["tasks"][0]["acceptance_points"]),
            test_commands_json=json.dumps(plan["tasks"][0]["test_commands"]),
        ))
        session.commit()
    mock = MockDevelopmentRuntime()
    sync = CodexSyncService(database, EventHub())
    service = CodexDevelopmentService(database, sync, mock, WorktreeManager(tmp_path / "managed-root"))
    return service, database, mock, repo


async def wait_until(predicate, attempts: int = 100) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition did not become true")


@pytest.mark.asyncio
async def test_mock_runtime_lifecycle_approval_cancel_and_implemented_boundary(tmp_path: Path) -> None:
    service, database, mock, repo = build_managed_service(tmp_path)
    (repo / "local.txt").write_text("uncommitted", encoding="utf-8")
    await service.start()
    try:
        run = await service.create(ManagedRunCreateInput(
            request_id="create-1", project_id="project-1", task_key="DEV-001",
            binding_id="binding-1", acknowledge_dirty_repository=True,
        ))

        def launched() -> bool:
            with database.session() as session:
                row = session.get(CodexRun, run.id)
                return bool(row and row.thread_id and row.turn_id)

        await wait_until(launched)
        assert (repo / "local.txt").exists()
        await mock.emit(RuntimeEvent(
            "approval_requested", "mock-thread-1", "mock-turn-1", "item-1", "request-approval-1",
            {"approval_kind": "command", "command": "git push --force", "cwd": str(repo), "reason": "publish"},
        ))

        def has_approval() -> bool:
            with database.session() as session:
                return session.scalar(select(CodexRunApproval)) is not None

        await wait_until(has_approval)
        with database.session() as session:
            approval = session.scalar(select(CodexRunApproval))
            assert approval and approval.status == "pending" and approval.risk_level == "critical"
            approval_id = approval.id
        decided = await service.decide_approval(approval_id, "approve-1", "approve_once")
        assert decided.status == "approved"
        assert mock.approved == ["request-approval-1"]

        await mock.emit(RuntimeEvent("run_completed", "mock-thread-1", "mock-turn-1", payload={"status": "completed"}))

        def completed() -> bool:
            with database.session() as session:
                row = session.get(BusinessTask, "task-1")
                return bool(row and row.codex_execution_status == "implemented")

        await wait_until(completed)
        with database.session() as session:
            task = session.get(BusinessTask, "task-1")
            project = session.get(BusinessProject, "project-1")
            assert task and task.status == "todo" and task.codex_execution_status == "implemented"
            assert project and project.progress == 13
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_restart_marks_active_runs_paused_without_automatic_resume(tmp_path: Path) -> None:
    service, database, mock, _repo = build_managed_service(tmp_path)
    with database.session() as session:
        session.add(CodexRun(
            id="run-recover", project_id="project-1", binding_id="binding-1", source="app_server",
            external_session_id="run-recover", runtime_type="app_server", task_key="DEV-001",
            thread_id="thread-old", turn_id="turn-old", status="running",
        ))
        session.add(CodexRunApproval(
            id="approval-old", run_id="run-recover", server_request_id="request-old",
            status="pending",
        ))
        session.commit()
    await service.start()
    try:
        with database.session() as session:
            run = session.get(CodexRun, "run-recover")
            approval = session.get(CodexRunApproval, "approval-old")
            assert run and run.status == "paused" and run.paused_at is not None
            assert approval and approval.status == "expired"
            assert mock.interrupted == []
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_pause_resume_cancel_and_reject_are_explicit_and_idempotent(tmp_path: Path) -> None:
    service, database, mock, _repo = build_managed_service(tmp_path)
    await service.start()
    try:
        created = await service.create(ManagedRunCreateInput(
            request_id="create-controls", project_id="project-1", task_key="DEV-001",
            binding_id="binding-1", acknowledge_dirty_repository=False,
        ))

        def launched() -> bool:
            with database.session() as session:
                run = session.get(CodexRun, created.id)
                return bool(run and run.turn_id)

        await wait_until(launched)
        paused = await service.pause(created.id, "pause-1")
        replay = await service.pause(created.id, "pause-1")
        assert paused.status == replay.status == "paused"
        assert len(mock.interrupted) == 1
        resumed = await service.resume(created.id, "resume-1")
        assert resumed.status == "running" and resumed.turn_id

        await mock.emit(RuntimeEvent(
            "approval_requested", resumed.thread_id, resumed.turn_id, "item-reject",
            "request-reject", {"approval_kind": "command", "command": "unknown-script", "reason": "run it"},
        ))

        def approval_id() -> str:
            with database.session() as session:
                row = session.scalar(
                    select(CodexRunApproval).where(
                        CodexRunApproval.server_request_id == "request-reject"
                    )
                )
                return row.id if row else ""

        await wait_until(lambda: bool(approval_id()))
        rejected = await service.decide_approval(
            approval_id(), "reject-1", "reject"
        )
        assert rejected.status == "rejected"
        assert mock.rejected == ["request-reject"]
        cancelled = await service.cancel(created.id, "cancel-1")
        assert cancelled.status == "cancelled" and cancelled.finished_at is not None
        assert len(mock.interrupted) == 2
        await mock.emit(RuntimeEvent(
            "run_interrupted", cancelled.thread_id, cancelled.turn_id,
            payload={"status": "interrupted"},
        ))
        await asyncio.sleep(0.05)
        with database.session() as session:
            stored = session.get(CodexRun, created.id)
            task = session.get(BusinessTask, "task-1")
            assert stored and stored.status == "cancelled"
            assert task and task.codex_execution_status != "implemented"
    finally:
        await service.close()
