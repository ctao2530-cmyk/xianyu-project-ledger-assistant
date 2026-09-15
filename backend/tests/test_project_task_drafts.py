from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from backend.app.database import Database
from backend.app.ledger import LedgerService, RevisionConflict, default_snapshot
from backend.app.models import BusinessTask, ProjectTaskDraftPreview, RequirementDocumentVersion
from backend.app.project_task_draft_api import _error
from backend.app.services.project_task_drafts import ProjectTaskDraftError, ProjectTaskDraftService


def blueprint(*, task_key: str | None = "frontend-dashboard") -> dict:
    stage = {
        "id": "stage-ui",
        "task_key": task_key,
        "workspace_key": "frontend",
        "title": "dashboard 页面实现",
        "objective": "完成经营看板",
        "implementation": "基于现有组件实现信息结构与交互。",
        "estimated_hours": 6,
        "capability_ids": ["cap-dashboard"],
        "dependency_ids": [],
        "work_items": ["实现页面"],
        "deliverables": ["响应式页面"],
        "evidence_refs": [],
    }
    return {
        "schema_version": "2.0",
        "title": "经营看板需求蓝图",
        "project_type": "定制开发",
        "readiness": "approved",
        "change_summary": "确认页面交付范围",
        "objectives": [
            {"id": "goal-dashboard", "title": "经营判断", "description": "集中展示经营事实", "evidence_refs": []}
        ],
        "capabilities": [
            {
                "id": "cap-dashboard",
                "title": "经营看板",
                "description": "展示经营指标",
                "objective_ids": ["goal-dashboard"],
                "priority": "must",
                "evidence_refs": [],
            }
        ],
        "stages": [stage],
        "acceptance_gates": [
            {
                "id": "gate-ui",
                "title": "页面验收",
                "description": "桌面与移动端均可使用",
                "stage_ids": ["stage-ui"],
                "criteria": ["桌面无横向溢出", "移动端操作目标不小于 44px"],
                "evidence_refs": [],
            }
        ],
        "out_of_scope": [],
        "assumptions": [],
        "open_questions": [],
        "risks": [],
        "evidence_refs": [],
    }


@pytest.fixture()
def service(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'task-drafts.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    snapshot = default_snapshot()
    snapshot['customers'] = [{'id':'customer-1','name':'Synthetic customer','source':'other','level':'C','followUpStatus':'contacted'}]
    snapshot["projects"] = [
        {
            "id": "project-1",
            "name": "经营看板",
            "customerId": "customer-1",
            "projectKind": "client",
            "totalAmount": 0,
            "startDate": "2026-08-27",
            "dueDate": "2026-09-10",
            "progress": 0,
            "status": "pending",
            "type": "个人开发",
            "estimatedHours": 10,
            "accent": "blue",
            "notes": "",
        }
    ]
    ledger.save(snapshot, 0)
    return ProjectTaskDraftService(database, ledger), database, ledger


def import_blueprint(service: ProjectTaskDraftService, ledger: LedgerService) -> dict:
    revision, _ = ledger.get()
    preview = service.preview_blueprint_import(
        "project-1",
        expected_revision=revision,
        source_filename="requirement-blueprint.json",
        blueprint_data=blueprint(),
    )
    result = service.commit_blueprint_import(
        "project-1",
        request_id="blueprint-import-0001",
        expected_revision=revision,
        source_filename="requirement-blueprint.json",
        blueprint_data=blueprint(),
        preview_token=preview["preview_token"],
    )
    return {**result, "_expected_revision": revision, "_preview_token": preview["preview_token"]}


def test_preview_is_read_only_and_confirmation_is_idempotent(service) -> None:
    draft_service, database, ledger = service
    imported = import_blueprint(draft_service, ledger)
    assert imported["idempotent"] is False
    repeated_import = draft_service.commit_blueprint_import(
        "project-1",
        request_id="blueprint-import-0001",
        expected_revision=imported["_expected_revision"],
        source_filename="requirement-blueprint.json",
        blueprint_data=blueprint(),
        preview_token=imported["_preview_token"],
    )
    assert repeated_import["idempotent"] is True

    revision, before = ledger.get()
    preview = draft_service.create_preview(
        "project-1",
        expected_revision=revision,
        requirement_version_id=imported["requirement_version_id"],
    )
    assert preview["summary"]["new"] == 1
    assert ledger.get() == (revision, before)
    with database.session() as session:
        assert session.query(BusinessTask).count() == 0

    result = draft_service.confirm(
        "project-1",
        request_id="task-draft-confirm-0001",
        expected_revision=revision,
        preview_id=preview["id"],
        preview_token=preview["preview_token"],
        selected_task_keys=["frontend-dashboard"],
        apply_allowed_updates_only=True,
        note="确认按蓝图新增前端任务",
    )
    assert result["idempotent"] is False
    assert len(result["created_task_ids"]) == 1
    repeated = draft_service.confirm(
        "project-1",
        request_id="task-draft-confirm-0001",
        expected_revision=revision,
        preview_id=preview["id"],
        preview_token=preview["preview_token"],
        selected_task_keys=["frontend-dashboard"],
        apply_allowed_updates_only=True,
        note="确认按蓝图新增前端任务",
    )
    assert repeated["idempotent"] is True
    with database.session() as session:
        task = session.get(BusinessTask, result["created_task_ids"][0])
        assert task is not None
        assert task.task_key == "frontend-dashboard"
        assert task.workspace_key == "frontend"
        assert task.status == "todo"
        assert task.actual_hours == 0
        assert json.loads(task.deliverables_json) == ["响应式页面"]
    trace_revision, trace_snapshot = ledger.get()
    trace_task = trace_snapshot["tasks"][0]
    assert trace_task["taskKey"] == "frontend-dashboard"
    assert trace_task["workspaceKey"] == "frontend"
    assert trace_task["dependencyTaskKeys"] == []
    assert trace_task["deliverables"] == ["响应式页面"]
    assert trace_task["requirementVersionId"] == imported["requirement_version_id"]

    for key in (
        "taskKey", "stageKey", "workspaceKey", "dependencyTaskKeys",
        "deliverables", "requirementVersionId",
    ):
        trace_task.pop(key, None)
    ledger.save(trace_snapshot, trace_revision)
    _revision, preserved = ledger.get()
    assert preserved["tasks"][0]["taskKey"] == "frontend-dashboard"
    assert preserved["tasks"][0]["workspaceKey"] == "frontend"
    assert preserved["tasks"][0]["requirementVersionId"] == imported["requirement_version_id"]


def test_missing_task_key_conflicts_and_never_guesses_from_title(service) -> None:
    draft_service, database, ledger = service
    revision, _ = ledger.get()
    preview = draft_service.preview_blueprint_import(
        "project-1",
        expected_revision=revision,
        source_filename="missing-key.json",
        blueprint_data=blueprint(task_key=None),
    )
    imported = draft_service.commit_blueprint_import(
        "project-1",
        request_id="blueprint-import-0002",
        expected_revision=revision,
        source_filename="missing-key.json",
        blueprint_data=blueprint(task_key=None),
        preview_token=preview["preview_token"],
    )
    revision, _ = ledger.get()
    draft = draft_service.create_preview(
        "project-1",
        expected_revision=revision,
        requirement_version_id=imported["requirement_version_id"],
    )
    assert draft["summary"]["conflict"] == 1
    assert "不会根据标题猜测" in draft["items"][0]["conflict_reason"]
    with pytest.raises(ProjectTaskDraftError, match="不能写入"):
        draft_service.confirm(
            "project-1",
            request_id="task-draft-confirm-0002",
            expected_revision=revision,
            preview_id=draft["id"],
            preview_token=draft["preview_token"],
            selected_task_keys=[draft["items"][0]["task_key"]],
            apply_allowed_updates_only=True,
            note="不应允许冲突任务写入",
        )
    with database.session() as session:
        assert session.query(BusinessTask).count() == 0


def test_missing_workspace_is_a_non_writable_conflict(service) -> None:
    draft_service, _database, ledger = service
    invalid = blueprint()
    invalid["stages"][0]["workspace_key"] = None
    revision, _ = ledger.get()
    preview = draft_service.preview_blueprint_import(
        "project-1",
        expected_revision=revision,
        source_filename="missing-workspace.json",
        blueprint_data=invalid,
    )
    imported = draft_service.commit_blueprint_import(
        "project-1",
        request_id="blueprint-import-workspace",
        expected_revision=revision,
        source_filename="missing-workspace.json",
        blueprint_data=invalid,
        preview_token=preview["preview_token"],
    )
    revision, _ = ledger.get()
    task_preview = draft_service.create_preview(
        "project-1",
        expected_revision=revision,
        requirement_version_id=imported["requirement_version_id"],
    )
    assert task_preview["summary"]["conflict"] == 1
    assert "workspace_key" in task_preview["items"][0]["conflict_reason"]


@pytest.mark.parametrize("invalid_kind", ["duplicate-task-key", "dependency-cycle"])
def test_invalid_task_identity_or_dependency_graph_is_rejected(service, invalid_kind) -> None:
    draft_service, _database, ledger = service
    invalid = deepcopy(blueprint())
    second = deepcopy(invalid["stages"][0])
    second.update(
        {
            "id": "stage-api",
            "task_key": (
                "frontend-dashboard" if invalid_kind == "duplicate-task-key" else "backend-api"
            ),
            "workspace_key": "backend",
            "title": "接口实现",
        }
    )
    invalid["stages"].append(second)
    invalid["acceptance_gates"][0]["stage_ids"].append("stage-api")
    if invalid_kind == "dependency-cycle":
        invalid["stages"][0]["dependency_ids"] = ["stage-api"]
        invalid["stages"][1]["dependency_ids"] = ["stage-ui"]
    revision, _ = ledger.get()
    with pytest.raises(ProjectTaskDraftError) as caught:
        draft_service.preview_blueprint_import(
            "project-1",
            expected_revision=revision,
            source_filename=f"{invalid_kind}.json",
            blueprint_data=invalid,
        )
    assert caught.value.code == "blueprint_invalid"


def test_started_task_is_protected_and_stale_preview_is_rejected(service) -> None:
    draft_service, database, ledger = service
    imported = import_blueprint(draft_service, ledger)
    revision, snapshot = ledger.get()
    snapshot["tasks"] = [
        {
            "id": "task-existing",
            "projectId": "project-1",
            "title": "旧标题",
            "status": "in_progress",
            "startDate": "2026-08-27",
            "dueDate": "",
            "estimatedHours": 4,
            "actualHours": 2,
            "stage": {},
        }
    ]
    revision, _ = ledger.save(snapshot, revision)
    with database.session() as session:
        task = session.get(BusinessTask, "task-existing")
        task.task_key = "frontend-dashboard"
        task.actual_hours = 2
        task.acceptance_points_json = '[{"point_key":"visual-proof"}]'
        task.codex_execution_status = "implemented"
        task.codex_implemented_at = datetime.now(timezone.utc)
        session.commit()
    preview = draft_service.create_preview(
        "project-1",
        expected_revision=revision,
        requirement_version_id=imported["requirement_version_id"],
    )
    assert preview["summary"]["protected"] == 1
    assert set(preview["items"][0]["protected_fields"]) == {
        "status",
        "actual_hours",
        "acceptance_evidence",
        "implementation_history",
    }

    before_invalid_token = ledger.get()
    with pytest.raises(ProjectTaskDraftError) as invalid_token:
        draft_service.confirm(
            "project-1",
            request_id="task-draft-confirm-invalid-token",
            expected_revision=revision,
            preview_id=preview["id"],
            preview_token="0" * 64,
            selected_task_keys=["frontend-dashboard"],
            apply_allowed_updates_only=True,
            note="无效令牌不得写入",
        )
    assert invalid_token.value.code == "preview_expired"
    assert _error(invalid_token.value).status_code == 409
    assert ledger.get() == before_invalid_token

    current_revision, current = ledger.get()
    current["projects"][0]["notes"] = "项目事实变化"
    ledger.save(current, current_revision)
    with pytest.raises(RevisionConflict):
        draft_service.confirm(
            "project-1",
            request_id="task-draft-confirm-0003",
            expected_revision=revision,
            preview_id=preview["id"],
            preview_token=preview["preview_token"],
            selected_task_keys=["frontend-dashboard"],
            apply_allowed_updates_only=True,
            note="旧预览必须失败",
        )
    with database.session() as session:
        preserved = session.get(BusinessTask, "task-existing")
        assert preserved is not None
        assert preserved.status == "in_progress"
        assert preserved.actual_hours == 2
        assert preserved.acceptance_points_json == '[{"point_key":"visual-proof"}]'
        assert preserved.codex_execution_status == "implemented"
        assert preserved.codex_implemented_at is not None


def test_startup_migration_rejects_partial_task_draft_schema(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'partial.db'}")
    database.create_all()
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE project_task_draft_items")
    with pytest.raises(RuntimeError, match="partial"):
        database.create_all()
