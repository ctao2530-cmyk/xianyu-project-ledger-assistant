from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from ..ai import AIModelSelection, AIProviderError
from ..codex_plan_schemas import (
    CodexDevelopmentPlanDocument,
    CodexPlanView,
    RepositoryBindingView,
)
from ..database import Database
from ..ledger import LedgerService, RevisionConflict
from ..models import (
    BusinessProject,
    BusinessTask,
    CodexAcceptancePoint,
    CodexDevelopmentPlan,
    CodexPlanMutationRequest,
    CodexProjectBinding,
    RequirementCase,
    RequirementDocumentVersion,
    utcnow,
)
from .project_progress import ProjectProgressService


PLAN_SYSTEM_PROMPT = """你是循营的只读开发计划分析器。你只能分析用户已确认的需求和当前绑定仓库，不能修改文件、运行会写入状态的命令、提交 Git、创建项目或创建任务。
输出必须符合给定 JSON Schema，并遵守：
1. task_key、stage_key、deliverable_key、point_key 必须稳定、唯一、可在下一版本复用；
2. 工时必须给 low / expected / high 区间，信息不足写 assumptions 和 risks；
3. expected_paths 只能引用仓库中已存在的路径或明确标注为建议新增的相对路径，禁止虚构已存在模块；
4. 测试命令只作为人工确认后的建议，不要执行；
5. 未绑定仓库时 repository_snapshot.mode 必须是 requirement_only；绑定仓库时必须复述给定 HEAD、分支和 dirty 状态；
6. 所有任务必须至少有一个验收点。只输出 JSON。"""


class CodexPlanError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _same_time(left: datetime, right: datetime) -> bool:
    def aware(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    return abs((aware(left) - aware(right)).total_seconds()) < 0.001


class CodexPlanService:
    def __init__(
        self,
        database: Database,
        ledger: LedgerService,
        provider: Any,
        settings: Any,
        *,
        progress: ProjectProgressService | None = None,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.provider = provider
        self.settings = settings
        self.progress = progress or ProjectProgressService()

    @staticmethod
    def _git(repository_path: str) -> tuple[Path, str, str, bool]:
        try:
            requested = Path(repository_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise CodexPlanError("repository_missing", "所选本地目录不存在") from exc
        if not requested.is_dir():
            raise CodexPlanError("repository_invalid", "所选路径不是目录")

        def run(*args: str) -> str:
            result = subprocess.run(
                ["git", "-C", str(requested), *args],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                raise CodexPlanError("repository_invalid", "所选目录不是可读取的 Git 仓库")
            return result.stdout.strip()

        root = Path(run("rev-parse", "--show-toplevel")).resolve(strict=True)
        if root != requested:
            raise CodexPlanError("repository_root_required", "请绑定 Git 仓库根目录，而不是仓库内子目录")
        head = run("rev-parse", "HEAD")
        branch_result = subprocess.run(
            ["git", "-C", str(root), "symbolic-ref", "--short", "-q", "HEAD"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        branch = branch_result.stdout.strip() or "detached"
        dirty = bool(run("status", "--porcelain=v1", "--untracked-files=normal"))
        return root, branch, head, dirty

    @staticmethod
    def _request(session, request_id: str, operation: str, payload: Any) -> dict[str, Any] | None:
        digest = _payload_hash(payload)
        row = session.get(CodexPlanMutationRequest, request_id)
        if row is None:
            return None
        if row.operation != operation or row.payload_hash != digest:
            raise CodexPlanError("request_id_reused", "该请求编号已用于不同操作，请刷新后重试")
        return json.loads(row.result_json or "{}")

    @staticmethod
    def _record_request(session, request_id: str, operation: str, payload: Any, result: Any) -> None:
        session.add(
            CodexPlanMutationRequest(
                request_id=request_id,
                operation=operation,
                payload_hash=_payload_hash(payload),
                result_json=_canonical(result),
            )
        )

    def create_binding(
        self,
        *,
        request_id: str,
        requirement_case_id: str,
        project_id: str | None,
        repository_path: str,
    ) -> RepositoryBindingView:
        payload = {
            "requirement_case_id": requirement_case_id,
            "project_id": project_id,
            "repository_path": str(Path(repository_path).expanduser()),
        }
        with self.database.session() as session:
            replay = self._request(session, request_id, "create_binding", payload)
            if replay:
                row = session.get(CodexProjectBinding, replay["binding_id"])
                if row is None:
                    raise CodexPlanError("binding_missing", "仓库绑定不存在")
                return self.binding_view(row, idempotent=True)
            case = session.get(RequirementCase, requirement_case_id)
            if case is None:
                raise CodexPlanError("requirement_case_missing", "需求案例不存在")
            if project_id and session.get(BusinessProject, project_id) is None:
                raise CodexPlanError("project_missing", "所选项目不存在")
            if project_id and case.project_id and case.project_id != project_id:
                raise CodexPlanError("project_conflict", "需求案例已绑定到另一个项目")

        root, branch, head, _dirty = self._git(repository_path)
        with self.database.session() as session:
            existing = session.scalar(
                select(CodexProjectBinding).where(
                    CodexProjectBinding.requirement_case_id == requirement_case_id,
                    CodexProjectBinding.repository_path == str(root),
                )
            )
            row = existing or CodexProjectBinding(
                id=f"codex-binding-{uuid4()}",
                requirement_case_id=requirement_case_id,
                project_id=project_id,
                repository_path=str(root),
                planning_worktree_path=str(root),
            )
            row.project_id = project_id or row.project_id
            row.default_branch = branch
            row.current_head_sha = head
            row.enabled = True
            session.add(row)
            self._record_request(
                session, request_id, "create_binding", payload, {"binding_id": row.id}
            )
            session.commit()
            return self.binding_view(row)

    @staticmethod
    def binding_view(row: CodexProjectBinding, *, idempotent: bool = False) -> RepositoryBindingView:
        return RepositoryBindingView(
            id=row.id,
            requirement_case_id=row.requirement_case_id,
            project_id=row.project_id,
            repository_name=Path(row.repository_path).name,
            default_branch=row.default_branch,
            current_head_sha=row.current_head_sha,
            enabled=row.enabled,
            updated_at=row.updated_at,
            idempotent=idempotent,
        )

    def bindings_for_case(self, case_id: str) -> list[RepositoryBindingView]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(CodexProjectBinding)
                    .where(
                        CodexProjectBinding.requirement_case_id == case_id,
                        CodexProjectBinding.enabled.is_(True),
                    )
                    .order_by(CodexProjectBinding.updated_at.desc())
                )
            )
            return [self.binding_view(row) for row in rows]

    async def generate(
        self,
        *,
        request_id: str,
        requirement_case_id: str,
        expected_requirement_version: int,
        binding_id: str | None,
    ) -> CodexPlanView:
        payload = {
            "requirement_case_id": requirement_case_id,
            "expected_requirement_version": expected_requirement_version,
            "binding_id": binding_id,
        }
        with self.database.session() as session:
            replay = self._request(session, request_id, "generate_plan", payload)
            if replay:
                row = session.get(CodexDevelopmentPlan, replay["plan_id"])
                if row is None:
                    raise CodexPlanError("plan_missing", "开发计划不存在")
                return self.plan_view(session, row, idempotent=True)
            case = session.get(RequirementCase, requirement_case_id)
            if case is None:
                raise CodexPlanError("requirement_case_missing", "需求案例不存在")
            if case.current_version != expected_requirement_version:
                raise CodexPlanError("requirement_version_conflict", "需求版本已变化，请刷新后重新生成")
            requirement = session.scalar(
                select(RequirementDocumentVersion).where(
                    RequirementDocumentVersion.case_id == requirement_case_id,
                    RequirementDocumentVersion.version == expected_requirement_version,
                )
            )
            if requirement is None:
                raise CodexPlanError("requirement_version_missing", "需求版本不存在")
            binding = session.get(CodexProjectBinding, binding_id) if binding_id else None
            if binding_id and (
                binding is None
                or not binding.enabled
                or binding.requirement_case_id != requirement_case_id
            ):
                raise CodexPlanError("binding_invalid", "仓库绑定不存在或不属于当前需求")
            requirement_payload = json.loads(requirement.structured_json)
            requirement_id = requirement.id
            project_id = case.project_id

        repository_mode = "requirement_only"
        branch = head = ""
        dirty = False
        workspace: Path | None = None
        if binding is not None:
            workspace, branch, head, dirty = self._git(binding.repository_path)
            repository_mode = "repository"
        prompt_payload = {
            "requirement": requirement_payload,
            "repository_snapshot": {
                "mode": repository_mode,
                "head_sha": head,
                "branch": branch,
                "dirty": dirty,
            },
        }
        prompt = f"{PLAN_SYSTEM_PROMPT}\n\n本次输入 JSON：\n{_canonical(prompt_payload)}"
        selection = AIModelSelection(
            model=self.settings.requirement_analysis_model,
            reasoning_effort=self.settings.requirement_analysis_reasoning_effort,
        )
        try:
            if workspace is not None:
                method = getattr(self.provider, "generate_structured_in_workspace", None)
                if method is None:
                    raise CodexPlanError("workspace_planning_unsupported", "当前 Codex Provider 不支持仓库只读计划")
                document = await method(
                    prompt,
                    workspace=workspace,
                    result_type=CodexDevelopmentPlanDocument,
                    task_key=f"codex-plan:{requirement_case_id}:{expected_requirement_version}",
                    model_selection=selection,
                    timeout=self.settings.requirement_analysis_timeout_seconds,
                )
            else:
                document = await self.provider.generate_structured(
                    prompt,
                    result_type=CodexDevelopmentPlanDocument,
                    task_key=f"codex-plan:{requirement_case_id}:{expected_requirement_version}",
                    model_selection=selection,
                    timeout=self.settings.requirement_analysis_timeout_seconds,
                )
        except AIProviderError:
            raise

        document.repository_snapshot.mode = repository_mode
        document.repository_snapshot.head_sha = head
        document.repository_snapshot.branch = branch
        document.repository_snapshot.dirty = dirty
        raw = document.model_dump(mode="json")
        with self.database.session() as session:
            case = session.get(RequirementCase, requirement_case_id)
            if case is None or case.current_version != expected_requirement_version:
                raise CodexPlanError("requirement_version_conflict", "生成期间需求版本已变化，请重新生成")
            version = int(
                session.scalar(
                    select(func.coalesce(func.max(CodexDevelopmentPlan.version), 0)).where(
                        CodexDevelopmentPlan.requirement_case_id == requirement_case_id
                    )
                )
                or 0
            ) + 1
            row = CodexDevelopmentPlan(
                id=f"codex-plan-{uuid4()}",
                requirement_case_id=requirement_case_id,
                requirement_version_id=requirement_id,
                project_id=project_id,
                binding_id=binding_id,
                version=version,
                status="draft",
                repository_mode=repository_mode,
                repository_head_sha=head,
                repository_branch=branch,
                repository_dirty=dirty,
                raw_structured_json=_canonical(raw),
                structured_json=_canonical(raw),
                estimate_low_hours=document.estimate.low_hours,
                estimate_expected_hours=document.estimate.expected_hours,
                estimate_high_hours=document.estimate.high_hours,
                model=selection.model or "",
                reasoning_effort=selection.reasoning_effort,
            )
            session.add(row)
            session.flush()
            self._record_request(
                session, request_id, "generate_plan", payload, {"plan_id": row.id}
            )
            session.commit()
            return self.plan_view(session, row)

    def update_draft(
        self,
        plan_id: str,
        *,
        request_id: str,
        expected_updated_at: datetime,
        document: CodexDevelopmentPlanDocument,
    ) -> CodexPlanView:
        payload = {
            "plan_id": plan_id,
            "expected_updated_at": expected_updated_at.isoformat(),
            "document": document.model_dump(mode="json"),
        }
        with self.database.session() as session:
            replay = self._request(session, request_id, "update_plan_draft", payload)
            if replay:
                row = session.get(CodexDevelopmentPlan, plan_id)
                if row is None:
                    raise CodexPlanError("plan_missing", "开发计划不存在")
                return self.plan_view(session, row, idempotent=True)
            row = session.get(CodexDevelopmentPlan, plan_id)
            if row is None:
                raise CodexPlanError("plan_missing", "开发计划不存在")
            if row.status != "draft":
                raise CodexPlanError("plan_not_editable", "只有草稿计划可以修改")
            if not _same_time(row.updated_at, expected_updated_at):
                raise CodexPlanError("plan_version_conflict", "计划已在其他页面更新，请刷新后重试")
            if document.repository_snapshot.mode != row.repository_mode:
                raise CodexPlanError("repository_snapshot_immutable", "仓库分析模式不可在草稿中修改")
            document.repository_snapshot.head_sha = row.repository_head_sha
            document.repository_snapshot.branch = row.repository_branch
            document.repository_snapshot.dirty = row.repository_dirty
            row.structured_json = _canonical(document.model_dump(mode="json"))
            row.estimate_low_hours = document.estimate.low_hours
            row.estimate_expected_hours = document.estimate.expected_hours
            row.estimate_high_hours = document.estimate.high_hours
            row.updated_at = utcnow()
            self._record_request(
                session, request_id, "update_plan_draft", payload, {"plan_id": row.id}
            )
            session.commit()
            return self.plan_view(session, row)

    def confirm(
        self,
        plan_id: str,
        *,
        request_id: str,
        expected_updated_at: datetime,
        expected_requirement_version: int,
        expected_revision: int,
    ) -> dict[str, Any]:
        payload = {
            "plan_id": plan_id,
            "expected_updated_at": expected_updated_at.isoformat(),
            "expected_requirement_version": expected_requirement_version,
            "expected_revision": expected_revision,
            "confirmed": True,
        }
        with self.database.session() as session:
            replay = self._request(session, request_id, "confirm_plan", payload)
            if replay:
                row = session.get(CodexDevelopmentPlan, plan_id)
                assert row is not None
                return {
                    "plan": self.plan_view(session, row, idempotent=True),
                    "project_id": replay["project_id"],
                    "task_ids": replay["task_ids"],
                    "revision": replay["revision"],
                    "idempotent": True,
                }
            row = session.get(CodexDevelopmentPlan, plan_id)
            if row is None:
                raise CodexPlanError("plan_missing", "开发计划不存在")
            case = session.get(RequirementCase, row.requirement_case_id)
            if case is None:
                raise CodexPlanError("requirement_case_missing", "需求案例不存在")
            if case.current_version != expected_requirement_version:
                raise CodexPlanError("requirement_version_conflict", "需求版本已变化，请重新生成计划")
            if row.status == "confirmed":
                revision, _snapshot = self.ledger.get()
                task_ids = [
                    task.id
                    for task in session.scalars(
                        select(BusinessTask).where(BusinessTask.codex_plan_id == row.id)
                    )
                ]
                result = {
                    "project_id": row.project_id,
                    "task_ids": task_ids,
                    "revision": revision,
                }
                self._record_request(session, request_id, "confirm_plan", payload, result)
                session.commit()
                return {
                    "plan": self.plan_view(session, row, idempotent=True),
                    **result,
                    "idempotent": True,
                }
            if row.status != "draft":
                raise CodexPlanError("plan_not_confirmable", "该计划当前不能确认")
            if not _same_time(row.updated_at, expected_updated_at):
                raise CodexPlanError("plan_version_conflict", "计划已更新，请刷新后再确认")

            document = CodexDevelopmentPlanDocument.model_validate_json(row.structured_json)
            selected_tasks = [task for task in document.tasks if task.included]
            if not selected_tasks:
                raise CodexPlanError("plan_tasks_empty", "至少保留一个开发任务")
            revision, snapshot = self.ledger.get()
            if revision != expected_revision:
                raise RevisionConflict(revision)
            project_id = row.project_id or case.project_id
            project = next(
                (item for item in snapshot["projects"] if item.get("id") == project_id),
                None,
            )
            if project is None:
                project_id = f"project-{uuid4()}"
                start = datetime.now(timezone.utc).date()
                duration = max(7, math.ceil(sum(t.estimated_hours for t in selected_tasks) / 5))
                project = {
                    "id": project_id,
                    "name": document.title,
                    "customerId": case.customer_id,
                    "projectKind": "client",
                    "totalAmount": 0,
                    "startDate": start.isoformat(),
                    "dueDate": (start + timedelta(days=duration)).isoformat(),
                    "progress": 0,
                    "status": "pending",
                    "notes": "由已确认的 Codex 开发计划创建；金额与收款仍需人工补充",
                    "type": "定制开发",
                    "estimatedHours": 0,
                    "accent": "blue",
                    "leadId": case.lead_id,
                    "requirementVersionId": row.requirement_version_id,
                }
                snapshot["projects"].insert(0, project)
            total_hours = round(sum(task.estimated_hours for task in selected_tasks), 1)
            project["estimatedHours"] = total_hours
            project["requirementVersionId"] = row.requirement_version_id
            existing_by_key = {
                str((item.get("stage") or {}).get("codexTaskKey") or ""): item
                for item in snapshot["tasks"]
                if item.get("projectId") == project_id
            }
            task_ids: list[str] = []
            for task in selected_tasks:
                item = existing_by_key.get(task.task_key)
                if item is None:
                    item = {
                        "id": f"task-{uuid4()}",
                        "projectId": project_id,
                        "title": task.title,
                        "status": "todo",
                        "startDate": project.get("startDate") or "",
                        "dueDate": project.get("dueDate") or "",
                        "estimatedHours": task.estimated_hours,
                        "actualHours": 0,
                        "stage": {},
                    }
                    snapshot["tasks"].append(item)
                # Human status and actual time are intentionally preserved.
                if item.get("status") != "done":
                    item["title"] = task.title
                    item["estimatedHours"] = task.estimated_hours
                item["stage"] = {
                    **(item.get("stage") or {}),
                    "codexTaskKey": task.task_key,
                    "codexStageKey": task.stage_key,
                    "codexPlanId": row.id,
                    "description": task.description,
                    "dependsOn": task.depends_on,
                    "expectedPaths": task.expected_paths,
                    "acceptancePoints": [point.model_dump(mode="json") for point in task.acceptance_points],
                    "testCommands": task.test_commands,
                    "risks": task.risks,
                    "note": task.note,
                }
                task_ids.append(str(item["id"]))
            selected_task_keys = {task.task_key for task in selected_tasks}
            for stored in session.scalars(
                select(BusinessTask).where(
                    BusinessTask.project_id == project_id,
                    BusinessTask.task_key.is_not(None),
                )
            ):
                if stored.task_key in selected_task_keys:
                    continue
                stored.delivery_scope_active = False
                stored.retired_at = stored.retired_at or utcnow()
                for point in session.scalars(
                    select(CodexAcceptancePoint).where(
                        CodexAcceptancePoint.task_id == stored.id,
                        CodexAcceptancePoint.active.is_(True),
                    )
                ):
                    point.active = False
                    point.retired_at = point.retired_at or utcnow()
            snapshot["tasks"] = [
                item
                for item in snapshot["tasks"]
                if item.get("projectId") != project_id
                or not str((item.get("stage") or {}).get("codexTaskKey") or "")
                or str((item.get("stage") or {}).get("codexTaskKey") or "")
                in selected_task_keys
            ]
            # The ledger's legacy-delete guard reads active scope from the
            # relational rows, so retire removed plan tasks before saving the
            # filtered canonical snapshot.
            session.flush()
            new_revision, _saved = self.ledger.save_in_session(session, snapshot, revision)
            for task_id, task in zip(task_ids, selected_tasks, strict=True):
                stored = session.get(BusinessTask, task_id)
                assert stored is not None
                stored.task_key = task.task_key
                stored.stage_key = task.stage_key
                stored.codex_plan_id = row.id
                stored.acceptance_points_json = _canonical(
                    [point.model_dump(mode="json") for point in task.acceptance_points]
                )
                stored.test_commands_json = _canonical(task.test_commands)
                stored.delivery_scope_active = True
                stored.retired_at = None
                existing_points = {
                    point.point_key: point
                    for point in session.scalars(
                        select(CodexAcceptancePoint).where(
                            CodexAcceptancePoint.task_id == task_id
                        )
                    )
                }
                selected_point_keys = {point.point_key for point in task.acceptance_points}
                for point in task.acceptance_points:
                    current = existing_points.get(point.point_key)
                    if current is None:
                        digest = hashlib.sha256(
                            f"{task_id}\n{point.point_key}".encode()
                        ).hexdigest()[:32]
                        current = CodexAcceptancePoint(
                            id=f"acceptance-{digest}",
                            project_id=project_id,
                            task_id=task_id,
                            plan_id=row.id,
                            point_key=point.point_key,
                            title=point.title,
                            verification_type=point.verification_type,
                            source="codex_plan",
                            status="pending",
                        )
                        session.add(current)
                    else:
                        current.plan_id = row.id
                        current.title = point.title
                        current.verification_type = point.verification_type
                        current.source = "codex_plan"
                        current.active = True
                        current.retired_at = None
                for point_key, current in existing_points.items():
                    if point_key not in selected_point_keys:
                        current.active = False
                        current.retired_at = utcnow()
            # A confirmed plan can add, retire, or reweight delivery scope.
            # Recompute from the relational tasks and acceptance points in this
            # same transaction so BusinessProject.progress never carries a
            # stale verified-delivery value from the previous plan version.
            session.flush()
            new_revision, _progress = self.progress.sync_verified_progress(
                session,
                self.ledger,
                project_id,
                expected_revision=new_revision,
            )
            row.status = "confirmed"
            row.project_id = project_id
            row.confirmed_at = utcnow()
            row.updated_at = row.confirmed_at
            case.project_id = project_id
            for previous in session.scalars(
                select(CodexDevelopmentPlan).where(
                    CodexDevelopmentPlan.requirement_case_id == row.requirement_case_id,
                    CodexDevelopmentPlan.id != row.id,
                    CodexDevelopmentPlan.status == "confirmed",
                )
            ):
                previous.status = "superseded"
            result = {
                "project_id": project_id,
                "task_ids": task_ids,
                "revision": new_revision,
            }
            self._record_request(session, request_id, "confirm_plan", payload, result)
            session.commit()
            return {
                "plan": self.plan_view(session, row),
                **result,
                "idempotent": False,
            }

    def get(self, plan_id: str) -> CodexPlanView:
        with self.database.session() as session:
            row = session.get(CodexDevelopmentPlan, plan_id)
            if row is None:
                raise CodexPlanError("plan_missing", "开发计划不存在")
            return self.plan_view(session, row)

    def latest_for_project(self, project_id: str) -> CodexPlanView | None:
        with self.database.session() as session:
            row = session.scalar(
                select(CodexDevelopmentPlan)
                .where(CodexDevelopmentPlan.project_id == project_id)
                .order_by(CodexDevelopmentPlan.version.desc())
                .limit(1)
            )
            return self.plan_view(session, row) if row else None

    def latest_for_case(self, case_id: str) -> CodexPlanView | None:
        with self.database.session() as session:
            row = session.scalar(
                select(CodexDevelopmentPlan)
                .where(CodexDevelopmentPlan.requirement_case_id == case_id)
                .order_by(CodexDevelopmentPlan.version.desc())
                .limit(1)
            )
            return self.plan_view(session, row) if row else None

    @staticmethod
    def plan_view(session, row: CodexDevelopmentPlan, *, idempotent: bool = False) -> CodexPlanView:
        requirement = session.get(RequirementDocumentVersion, row.requirement_version_id)
        binding = session.get(CodexProjectBinding, row.binding_id) if row.binding_id else None
        return CodexPlanView(
            id=row.id,
            requirement_case_id=row.requirement_case_id,
            requirement_version_id=row.requirement_version_id,
            requirement_version=requirement.version if requirement else 0,
            project_id=row.project_id,
            binding_id=row.binding_id,
            version=row.version,
            status=row.status,
            source=row.source,
            repository_name=Path(binding.repository_path).name if binding else None,
            repository_mode=row.repository_mode,
            repository_head_sha=row.repository_head_sha,
            repository_branch=row.repository_branch,
            repository_dirty=row.repository_dirty,
            raw_document=CodexDevelopmentPlanDocument.model_validate_json(row.raw_structured_json),
            document=CodexDevelopmentPlanDocument.model_validate_json(row.structured_json),
            model=row.model,
            reasoning_effort=row.reasoning_effort,
            created_at=row.created_at,
            updated_at=row.updated_at,
            confirmed_at=row.confirmed_at,
            idempotent=idempotent,
        )
