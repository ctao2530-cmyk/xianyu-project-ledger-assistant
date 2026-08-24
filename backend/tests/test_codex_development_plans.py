from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.app.codex_plan_schemas import CodexDevelopmentPlanDocument
from backend.app.database import Database
from backend.app.ledger import LedgerService
from backend.app.models import (
    BusinessProject,
    BusinessTask,
    CodexAcceptancePoint,
    CodexDevelopmentPlan,
    CodexProjectBinding,
    RequirementCase,
    RequirementDocumentVersion,
)
from backend.app.services.codex_plans import CodexPlanService


def requirement_document() -> dict:
    return {
        "schema_version": "2.0",
        "title": "订单管理系统",
        "project_type": "Web 管理系统",
        "readiness": "approved",
        "change_summary": "确认首版范围",
        "objectives": [],
        "capabilities": [],
        "stages": [],
        "acceptance_gates": [],
        "out_of_scope": [],
        "assumptions": [],
        "open_questions": [],
        "risks": [],
        "evidence_refs": [],
    }


def plan_document(mode: str = "requirement_only") -> CodexDevelopmentPlanDocument:
    return CodexDevelopmentPlanDocument.model_validate(
        {
            "schema_version": "1.0",
            "title": "订单管理系统开发计划",
            "summary": "先完成订单闭环，再执行回归验收。",
            "repository_snapshot": {
                "mode": mode,
                "head_sha": "" if mode == "requirement_only" else "a" * 40,
                "branch": "" if mode == "requirement_only" else "main",
                "dirty": False,
            },
            "estimate": {
                "low_hours": 6,
                "expected_hours": 8,
                "high_hours": 12,
                "confidence": "medium",
            },
            "assumptions": ["测试账号由客户提供"],
            "risks": ["字段仍可能变化"],
            "deliverables": [
                {
                    "deliverable_key": "DEL-001",
                    "title": "订单模块",
                    "description": "可运行的订单闭环",
                    "acceptance_criteria": ["可以创建并查询订单"],
                }
            ],
            "stages": [
                {
                    "stage_key": "STAGE-001",
                    "title": "核心开发",
                    "estimated_hours": 8,
                    "depends_on": [],
                    "deliverable_keys": ["DEL-001"],
                }
            ],
            "tasks": [
                {
                    "task_key": "DEV-001",
                    "stage_key": "STAGE-001",
                    "title": "实现订单接口",
                    "description": "创建和读取订单",
                    "estimated_hours": 8,
                    "depends_on": [],
                    "expected_paths": ["backend/orders.py"],
                    "acceptance_points": [
                        {
                            "point_key": "DEV-001-AC1",
                            "title": "接口测试通过",
                            "verification_type": "automated_test",
                        }
                    ],
                    "test_commands": ["pytest tests/test_orders.py"],
                    "risks": [],
                    "included": True,
                    "note": "",
                }
            ],
        }
    )


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[Path | None] = []

    async def generate_structured(self, _prompt, **_kwargs):
        self.calls.append(None)
        return plan_document()

    async def generate_structured_in_workspace(self, _prompt, *, workspace, **_kwargs):
        self.calls.append(Path(workspace))
        return plan_document("repository")


def service_fixture(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'plans.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    revision, snapshot = ledger.get()
    snapshot["customers"].append(
        {
            "id": "customer-1",
            "name": "测试客户",
            "source": "other",
            "phone": "",
            "followUpStatus": "contacted",
            "lastContactAt": "",
            "level": "C",
            "tags": [],
        }
    )
    revision, _ = ledger.save(snapshot, revision)
    with database.session() as session:
        case = RequirementCase(
            id="case-1",
            customer_id="customer-1",
            title="订单系统需求",
            current_version=1,
            status="approved",
        )
        session.add(case)
        session.flush()
        session.add(
            RequirementDocumentVersion(
                case_id=case.id,
                version=1,
                title="订单管理系统",
                readiness="approved",
                change_summary="确认首版范围",
                structured_json=json.dumps(requirement_document(), ensure_ascii=False),
                content_markdown="# 订单管理系统",
                model="manual",
            )
        )
        session.commit()
    provider = FakeProvider()
    settings = SimpleNamespace(
        requirement_analysis_model="gpt-5.4",
        requirement_analysis_reasoning_effort="high",
        requirement_analysis_timeout_seconds=300,
    )
    return CodexPlanService(database, ledger, provider, settings), database, ledger, provider, revision


@pytest.mark.asyncio
async def test_plan_generation_edit_and_confirm_are_versioned_and_idempotent(tmp_path: Path) -> None:
    service, database, ledger, provider, revision = service_fixture(tmp_path)
    generated = await service.generate(
        request_id="generate-plan-001",
        requirement_case_id="case-1",
        expected_requirement_version=1,
        binding_id=None,
    )
    replay = await service.generate(
        request_id="generate-plan-001",
        requirement_case_id="case-1",
        expected_requirement_version=1,
        binding_id=None,
    )
    assert generated.version == 1
    assert replay.id == generated.id
    assert replay.idempotent is True
    assert provider.calls == [None]

    draft = generated.document.model_copy(deep=True)
    draft.tasks[0].estimated_hours = 7
    updated = service.update_draft(
        generated.id,
        request_id="update-plan-001",
        expected_updated_at=generated.updated_at,
        document=draft,
    )
    assert updated.raw_document.tasks[0].estimated_hours == 8
    assert updated.document.tasks[0].estimated_hours == 7

    confirmed = service.confirm(
        generated.id,
        request_id="confirm-plan-001",
        expected_updated_at=updated.updated_at,
        expected_requirement_version=1,
        expected_revision=revision,
    )
    repeated = service.confirm(
        generated.id,
        request_id="confirm-plan-001",
        expected_updated_at=updated.updated_at,
        expected_requirement_version=1,
        expected_revision=revision,
    )
    assert confirmed["project_id"]
    assert len(confirmed["task_ids"]) == 1
    assert repeated["idempotent"] is True
    current_revision, snapshot = ledger.get()
    assert current_revision == revision + 2
    assert len([row for row in snapshot["tasks"] if row["projectId"] == confirmed["project_id"]]) == 1
    assert next(row for row in snapshot["projects"] if row["id"] == confirmed["project_id"])["estimatedHours"] == 7
    with database.session() as session:
        task = session.scalar(select(BusinessTask))
        plan = session.get(CodexDevelopmentPlan, generated.id)
        assert task is not None and task.task_key == "DEV-001"
        assert task.actual_hours == 0
        assert plan is not None and plan.status == "confirmed"

    # A later plan version must immediately reweight verified delivery while
    # preserving the stable task and its already verified acceptance point.
    with database.session() as session:
        point = session.scalar(select(CodexAcceptancePoint))
        assert point is not None
        point.status = "verified"
        session.flush()
        current_revision, _ = service.progress.sync_verified_progress(
            session,
            ledger,
            confirmed["project_id"],
            expected_revision=current_revision,
        )
        session.commit()

    generated_v2 = await service.generate(
        request_id="generate-plan-002",
        requirement_case_id="case-1",
        expected_requirement_version=1,
        binding_id=None,
    )
    draft_v2 = generated_v2.document.model_copy(deep=True)
    draft_v2.tasks[0].estimated_hours = 7
    added_task = draft_v2.tasks[0].model_copy(deep=True)
    added_task.task_key = "DEV-002"
    added_task.title = "补充订单回归"
    added_task.acceptance_points[0].point_key = "DEV-002-AC1"
    added_task.acceptance_points[0].title = "回归测试通过"
    draft_v2.tasks.append(added_task)
    updated_v2 = service.update_draft(
        generated_v2.id,
        request_id="update-plan-002",
        expected_updated_at=generated_v2.updated_at,
        document=draft_v2,
    )
    confirmed_v2 = service.confirm(
        generated_v2.id,
        request_id="confirm-plan-002",
        expected_updated_at=updated_v2.updated_at,
        expected_requirement_version=1,
        expected_revision=current_revision,
    )
    assert confirmed_v2["revision"] == current_revision + 2
    with database.session() as session:
        project = session.get(BusinessProject, confirmed["project_id"])
        points = list(session.scalars(select(CodexAcceptancePoint)))
        assert project is not None and project.progress == 50
        assert {point.point_key: point.status for point in points} == {
            "DEV-001-AC1": "verified",
            "DEV-002-AC1": "pending",
        }


@pytest.mark.asyncio
async def test_repository_binding_requires_root_and_workspace_generation(tmp_path: Path) -> None:
    service, database, _ledger, provider, _revision = service_fixture(tmp_path)
    repository = tmp_path / "customer-repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repository)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
    (repository / "README.md").write_text("customer repository", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-m", "init"], check=True, capture_output=True)

    binding = service.create_binding(
        request_id="binding-plan-001",
        requirement_case_id="case-1",
        project_id=None,
        repository_path=str(repository),
    )
    generated = await service.generate(
        request_id="generate-plan-repo-001",
        requirement_case_id="case-1",
        expected_requirement_version=1,
        binding_id=binding.id,
    )
    assert generated.repository_mode == "repository"
    assert generated.repository_name == "customer-repo"
    assert generated.repository_head_sha
    assert provider.calls == [repository.resolve()]
    with database.session() as session:
        stored = session.get(CodexProjectBinding, binding.id)
        assert stored is not None
        assert stored.repository_path == str(repository.resolve())
