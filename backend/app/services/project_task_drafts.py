from __future__ import annotations

from datetime import timedelta, timezone
import hashlib
import json
import secrets
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import Database
from ..ledger import LedgerService, RevisionConflict, canonical_json
from ..models import (
    BusinessProject,
    BusinessTask,
    LedgerMutationRequest,
    ProjectTaskDraftItem,
    ProjectTaskDraftPreview,
    RequirementDocumentVersion,
    RequirementCase,
    utcnow,
)
from ..requirement_blueprints import RequirementBlueprintV2


class ProjectTaskDraftError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProjectTaskDraftService:
    IMPORT_OPERATION = "project_requirement_import"
    CONFIRM_OPERATION = "project_task_draft_confirm"

    def __init__(self, database: Database, ledger: LedgerService) -> None:
        self.database = database
        self.ledger = ledger

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _loads(value: str, fallback: Any) -> Any:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return fallback
        return parsed

    @staticmethod
    def _validate_blueprint(blueprint_data: dict[str, Any]) -> RequirementBlueprintV2:
        try:
            return RequirementBlueprintV2.model_validate(blueprint_data)
        except ValidationError as exc:
            message = str(exc.errors()[0].get("msg") or "需求蓝图结构无效")
            raise ProjectTaskDraftError("blueprint_invalid", message) from None

    @staticmethod
    def _request_result(
        session: Session,
        *,
        request_id: str,
        operation: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        row = session.get(LedgerMutationRequest, request_id)
        if row is None:
            return None
        if row.operation != operation or row.payload_hash != payload_hash:
            raise ProjectTaskDraftError(
                "request_id_reused", "该请求编号已用于不同操作，请刷新后重新提交"
            )
        result = ProjectTaskDraftService._loads(row.result_json, None)
        if not isinstance(result, dict):
            raise ProjectTaskDraftError("request_record_invalid", "历史请求记录无法校验")
        return result

    @staticmethod
    def _save_request(
        session: Session,
        *,
        request_id: str,
        operation: str,
        payload_hash: str,
        result: dict[str, Any],
    ) -> None:
        session.add(
            LedgerMutationRequest(
                request_id=request_id,
                operation=operation,
                payload_hash=payload_hash,
                result_json=canonical_json(result),
            )
        )

    def list_blueprints(self, project_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            if session.get(BusinessProject, project_id) is None:
                raise ProjectTaskDraftError("project_not_found", "项目不存在")
            cases = list(session.scalars(select(RequirementCase).where(RequirementCase.project_id == project_id)))
            if len(cases) > 1:
                raise ProjectTaskDraftError('requirement_case_ambiguous', '项目关联多个正式需求，请先人工核对')
            if cases:
                rows = list(session.scalars(select(RequirementDocumentVersion).where(
                    RequirementDocumentVersion.case_id == cases[0].id).order_by(RequirementDocumentVersion.version.desc())))
                legacy = list(session.scalars(select(RequirementDocumentVersion).where(
                    RequirementDocumentVersion.project_id == project_id,
                    RequirementDocumentVersion.case_id.is_(None)).order_by(RequirementDocumentVersion.version.desc())))
                return [dict(self._blueprint_view(row), project_id=project_id, case_id=cases[0].id,
                             customer_id=cases[0].customer_id) for row in rows] + [self._blueprint_view(row) for row in legacy]
            rows = list(
                session.scalars(
                    select(RequirementDocumentVersion)
                    .where(RequirementDocumentVersion.project_id == project_id)
                    .order_by(RequirementDocumentVersion.version.desc())
                )
            )
            return [self._blueprint_view(row) for row in rows]

    @staticmethod
    def _blueprint_view(row: RequirementDocumentVersion) -> dict[str, Any]:
        payload = ProjectTaskDraftService._loads(row.structured_json, {})
        return {
            "id": row.id,
            "project_id": str(row.project_id or ""),
            "version": row.version,
            "schema_version": row.schema_version,
            "title": row.title,
            "readiness": row.readiness,
            "change_summary": row.change_summary,
            "source_type": row.source_type,
            "source_label": row.source_label,
            "source_filename": row.source_filename,
            "source_sha256": row.source_sha256,
            "imported_at": row.imported_at,
            "created_at": row.created_at,
            "case_id": row.case_id,
            "metrics": {"capabilities": len(payload.get('capabilities', [])),
                "stages": len(payload.get('stages', [])),
                "deliverables": sum(len(s.get('deliverables', [])) for s in payload.get('stages', [])),
                "criteria": sum(len(s.get('criteria', [])) for s in payload.get('acceptance_gates', [])),
                "questions": len(payload.get('open_questions', []))},
            "diff": ProjectTaskDraftService._loads(row.import_metadata_json, {}).get('diff', {}),
        }

    def preview_blueprint_import(
        self,
        project_id: str,
        *,
        expected_revision: int,
        source_filename: str,
        blueprint_data: dict[str, Any],
    ) -> dict[str, Any]:
        blueprint = self._validate_blueprint(blueprint_data)
        normalized = blueprint.model_dump(mode="json")
        source_sha = self._hash(normalized)
        with self.database.session() as session:
            revision, _snapshot = self.ledger.get_in_session(session)
            if revision != expected_revision:
                raise RevisionConflict(revision)
            if session.get(BusinessProject, project_id) is None:
                raise ProjectTaskDraftError("project_not_found", "项目不存在")
            next_version = int(
                session.scalar(
                    select(func.max(RequirementDocumentVersion.version)).where(
                        RequirementDocumentVersion.project_id == project_id
                    )
                )
                or 0
            ) + 1
            formal = list(session.scalars(select(RequirementCase).where(RequirementCase.project_id == project_id)))
            if len(formal) > 1:
                raise ProjectTaskDraftError('requirement_case_ambiguous', '项目存在多个正式需求')
            project = session.get(BusinessProject, project_id)
            if not project.customer_id:
                raise ProjectTaskDraftError('formal_customer_required', '正式需求需要明确客户；无客户项目仅保留旧蓝图只读，不创建第二套版本链')
            if project.customer_id:
                next_version = formal[0].current_version + 1 if formal else 1
        token = self._hash(
            {
                "project_id": project_id,
                "revision": expected_revision,
                "version": next_version,
                "source_filename": source_filename,
                "source_sha256": source_sha,
            }
        )
        return {
            "project_id": project_id,
            "current_revision": expected_revision,
            "next_version": next_version,
            "preview_token": token,
            "source_sha256": source_sha,
            "blueprint": normalized,
        }

    def commit_blueprint_import(
        self,
        project_id: str,
        *,
        request_id: str,
        expected_revision: int,
        source_filename: str,
        blueprint_data: dict[str, Any],
        preview_token: str,
    ) -> dict[str, Any]:
        normalized = self._validate_blueprint(blueprint_data).model_dump(mode="json")
        source_sha = self._hash(normalized)
        payload = {
            "project_id": project_id,
            "expected_revision": expected_revision,
            "source_filename": source_filename,
            "source_sha256": source_sha,
            "preview_token": preview_token,
        }
        payload_hash = self._hash(payload)
        with self.database.session() as session:
            repeated = self._request_result(
                session,
                request_id=request_id,
                operation=self.IMPORT_OPERATION,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                return {**repeated, "idempotent": True}
        preview = self.preview_blueprint_import(
            project_id,
            expected_revision=expected_revision,
            source_filename=source_filename,
            blueprint_data=blueprint_data,
        )
        if not secrets.compare_digest(preview_token, preview["preview_token"]):
            raise ProjectTaskDraftError("preview_expired", "蓝图预览已失效，请重新预览")
        with self.database.session() as session:
            revision, snapshot = self.ledger.get_in_session(session)
            if revision != expected_revision:
                raise RevisionConflict(revision)
            project = session.get(BusinessProject, project_id)
            if project is None:
                raise ProjectTaskDraftError("project_not_found", "项目不存在")
            blueprint = RequirementBlueprintV2.model_validate(preview["blueprint"])
            now = utcnow()
            formal = session.scalar(select(RequirementCase).where(RequirementCase.project_id == project_id))
            if project.customer_id and formal is None:
                formal = RequirementCase(id='reqcase-' + uuid4().hex, customer_id=project.customer_id,
                    project_id=project_id, title=blueprint.title, current_version=0)
                session.add(formal)
                session.flush()
            if formal and (formal.customer_id != project.customer_id or formal.current_version + 1 != preview['next_version']):
                raise ProjectTaskDraftError('preview_stale', '正式需求版本或客户关系已经变化')
            from .requirement_conversion import blueprint_diff
            previous = session.scalar(select(RequirementDocumentVersion).where(RequirementDocumentVersion.case_id == formal.id,
                RequirementDocumentVersion.version == formal.current_version)) if formal else None
            row = RequirementDocumentVersion(
                conversation_id=None if formal else project.conversation_id,
                case_id=formal.id if formal else None,
                project_id=None if formal else project_id,
                schema_version=blueprint.schema_version,
                source_type="formal_file_import" if formal else "project_file_import",
                source_label="项目需求蓝图导入",
                imported_at=now,
                source_filename=source_filename,
                source_sha256=preview["source_sha256"],
                import_metadata_json=canonical_json({"request_id": request_id, 'diff': blueprint_diff(
                    self._loads(previous.structured_json, {}) if previous else {}, blueprint.model_dump(mode='json'))}),
                version=preview["next_version"],
                title=blueprint.title,
                readiness=blueprint.readiness,
                change_summary=blueprint.change_summary,
                structured_json=canonical_json(blueprint.model_dump(mode="json")),
                content_markdown=canonical_json(blueprint.model_dump(mode="json")),
                stage_progress_json="{}",
                model="external",
                reasoning_effort=None,
                created_at=now,
            )
            session.add(row)
            session.flush()
            if formal:
                formal.current_version, formal.title, formal.status = row.version, row.title, row.readiness
            snapshot_project = next(
                (item for item in snapshot["projects"] if str(item.get("id") or "") == project_id),
                None,
            )
            if snapshot_project is None:
                raise ProjectTaskDraftError("project_not_found", "项目账本记录不存在")
            snapshot_project["requirementVersionId"] = row.id
            new_revision, _ = self.ledger.save_in_session(
                session, snapshot, expected_revision
            )
            result = {
                "project_id": project_id,
                "requirement_version_id": row.id,
                "version": row.version,
                "revision": new_revision,
            }
            self._save_request(
                session,
                request_id=request_id,
                operation=self.IMPORT_OPERATION,
                payload_hash=payload_hash,
                result=result,
            )
            session.commit()
            return {**result, "idempotent": False}

    def create_preview(
        self,
        project_id: str,
        *,
        expected_revision: int,
        requirement_version_id: int | None,
    ) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        now = utcnow()
        with self.database.session() as session:
            revision, _snapshot = self.ledger.get_in_session(session)
            if revision != expected_revision:
                raise RevisionConflict(revision)
            if session.get(BusinessProject, project_id) is None:
                raise ProjectTaskDraftError("project_not_found", "项目不存在")
            version = self._requirement_version(
                session, project_id, requirement_version_id
            )
            blueprint = RequirementBlueprintV2.model_validate_json(version.structured_json)
            existing = {
                str(row.task_key): row
                for row in session.scalars(
                    select(BusinessTask).where(
                        BusinessTask.project_id == project_id,
                        BusinessTask.task_key.is_not(None),
                    )
                )
            }
            stage_to_task = {
                stage.id: str(stage.task_key or "") for stage in blueprint.stages
            }
            preview_id = f"task-preview-{uuid4()}"
            preview = ProjectTaskDraftPreview(
                id=preview_id,
                project_id=project_id,
                requirement_version_id=version.id,
                project_revision=revision,
                blueprint_hash=self._hash(blueprint.model_dump(mode="json")),
                preview_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                status="open",
                summary_json="{}",
                created_at=now,
                expires_at=now + timedelta(minutes=30),
            )
            session.add(preview)
            session.flush()
            counts = {key: 0 for key in ("new", "unchanged", "update_allowed", "protected", "conflict")}
            items: list[ProjectTaskDraftItem] = []
            for ordinal, stage in enumerate(blueprint.stages):
                task_key = str(stage.task_key or "")
                workspace_key = str(stage.workspace_key or "")
                dependencies = [stage_to_task.get(value, "") for value in stage.dependency_ids]
                conflict = ""
                if not task_key:
                    task_key = f"missing-task-key-{ordinal + 1}"
                    conflict = "蓝图阶段缺少显式 task_key；系统不会根据标题猜测"
                elif not workspace_key:
                    conflict = "蓝图阶段缺少显式 workspace_key"
                elif any(not value for value in dependencies):
                    conflict = "依赖阶段缺少可映射的 task_key"
                proposed = {
                    "title": stage.title,
                    "description": f"{stage.objective}\n\n{stage.implementation}",
                    "estimated_hours": stage.estimated_hours,
                    "workspace_key": workspace_key,
                    "stage_key": stage.id,
                    "dependency_task_keys": dependencies,
                    "deliverables": list(stage.deliverables),
                    "acceptance_criteria": [
                        criterion
                        for gate in blueprint.acceptance_gates
                        if stage.id in gate.stage_ids
                        for criterion in gate.criteria
                    ],
                }
                current_row = existing.get(task_key)
                current = self._task_payload(current_row) if current_row else {}
                protected_fields = self._protected_fields(current_row)
                if conflict:
                    classification = "conflict"
                elif current_row is None:
                    classification = "new"
                elif protected_fields:
                    classification = "protected"
                elif self._allowed_payload(current) == self._allowed_payload(proposed):
                    classification = "unchanged"
                else:
                    classification = "update_allowed"
                selected = classification in {"new", "update_allowed"}
                counts[classification] += 1
                item = ProjectTaskDraftItem(
                    id=f"task-draft-item-{uuid4()}",
                    preview_id=preview_id,
                    task_key=task_key,
                    workspace_key=workspace_key,
                    stage_key=stage.id,
                    classification=classification,
                    current_payload_json=canonical_json(current),
                    proposed_payload_json=canonical_json(proposed),
                    protected_fields_json=canonical_json(protected_fields),
                    conflict_reason=conflict,
                    selected=selected,
                    ordinal=ordinal,
                )
                session.add(item)
                items.append(item)
            preview.summary_json = canonical_json(counts)
            session.commit()
            return self._preview_view(preview, version, items, token)

    def latest_preview(self, project_id: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            preview = session.scalar(
                select(ProjectTaskDraftPreview)
                .where(ProjectTaskDraftPreview.project_id == project_id)
                .order_by(ProjectTaskDraftPreview.created_at.desc())
                .limit(1)
            )
            if preview is None:
                return None
            version = session.get(RequirementDocumentVersion, preview.requirement_version_id)
            self._requirement_version(session, project_id, preview.requirement_version_id)
            if version is None:
                raise ProjectTaskDraftError("requirement_version_missing", "需求蓝图版本不存在")
            items = list(
                session.scalars(
                    select(ProjectTaskDraftItem)
                    .where(ProjectTaskDraftItem.preview_id == preview.id)
                    .order_by(ProjectTaskDraftItem.ordinal)
                )
            )
            return self._preview_view(preview, version, items, "")

    def confirm(
        self,
        project_id: str,
        *,
        request_id: str,
        expected_revision: int,
        preview_id: str,
        preview_token: str,
        selected_task_keys: list[str],
        apply_allowed_updates_only: bool,
        note: str,
    ) -> dict[str, Any]:
        selected = sorted(set(selected_task_keys))
        payload = {
            "project_id": project_id,
            "expected_revision": expected_revision,
            "preview_id": preview_id,
            "selected_task_keys": selected,
            "apply_allowed_updates_only": apply_allowed_updates_only,
            "note": note,
        }
        payload_hash = self._hash(payload)
        with self.database.session() as session:
            repeated = self._request_result(
                session,
                request_id=request_id,
                operation=self.CONFIRM_OPERATION,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                return {**repeated, "idempotent": True}
            revision, snapshot = self.ledger.get_in_session(session)
            if revision != expected_revision:
                raise RevisionConflict(revision)
            preview = session.get(ProjectTaskDraftPreview, preview_id)
            if preview is None or preview.project_id != project_id:
                raise ProjectTaskDraftError("preview_not_found", "任务差异预览不存在")
            expires_at = preview.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if preview.status != "open" or expires_at <= utcnow():
                raise ProjectTaskDraftError("preview_expired", "任务差异预览已失效")
            if preview.project_revision != revision:
                raise ProjectTaskDraftError("preview_stale", "项目数据已变化，请重新生成差异预览")
            if not secrets.compare_digest(
                hashlib.sha256(preview_token.encode("utf-8")).hexdigest(),
                preview.preview_token_hash,
            ):
                raise ProjectTaskDraftError("preview_expired", "预览令牌无效")
            self._requirement_version(session, project_id, preview.requirement_version_id)
            version = session.get(RequirementDocumentVersion, preview.requirement_version_id)
            if version is None or self._hash(
                RequirementBlueprintV2.model_validate_json(version.structured_json).model_dump(mode="json")
            ) != preview.blueprint_hash:
                raise ProjectTaskDraftError("preview_stale", "需求蓝图已经变化，请重新预览")
            item_rows = list(
                session.scalars(
                    select(ProjectTaskDraftItem).where(ProjectTaskDraftItem.preview_id == preview_id)
                )
            )
            by_key = {row.task_key: row for row in item_rows}
            if any(key not in by_key for key in selected):
                raise ProjectTaskDraftError("selection_invalid", "选择中包含不属于本预览的 task_key")
            forbidden = [
                key for key in selected if by_key[key].classification not in {"new", "update_allowed"}
            ]
            if forbidden:
                raise ProjectTaskDraftError(
                    "protected_selection", "受保护、冲突或未变化任务不能写入"
                )
            if not apply_allowed_updates_only:
                raise ProjectTaskDraftError(
                    "unsafe_mode_forbidden", "当前版本只允许写入新增任务和允许更新字段"
                )
            snapshot_tasks = snapshot["tasks"]
            created_ids: list[str] = []
            updated_ids: list[str] = []
            task_ids_by_key: dict[str, str] = {}
            for key in selected:
                item = by_key[key]
                proposed = self._loads(item.proposed_payload_json, {})
                if item.classification == "new":
                    task_id = f"task-{hashlib.sha1(f'{project_id}:{key}'.encode()).hexdigest()[:24]}"
                    if any(str(row.get("id") or "") == task_id for row in snapshot_tasks):
                        raise ProjectTaskDraftError("task_id_conflict", f"任务 {key} 的稳定 ID 已被占用")
                    snapshot_tasks.append(
                        {
                            "id": task_id,
                            "projectId": project_id,
                            "title": proposed["title"],
                            "status": "todo",
                            "startDate": "",
                            "dueDate": "",
                            "estimatedHours": proposed["estimated_hours"],
                            "actualHours": 0,
                            "taskKey": key,
                            "stageKey": item.stage_key,
                            "workspaceKey": item.workspace_key,
                            "dependencyTaskKeys": proposed["dependency_task_keys"],
                            "deliverables": proposed["deliverables"],
                            "requirementVersionId": preview.requirement_version_id,
                            "stage": {
                                "description": proposed["description"],
                                "acceptanceCriteria": proposed["acceptance_criteria"],
                            },
                        }
                    )
                    created_ids.append(task_id)
                    task_ids_by_key[key] = task_id
                else:
                    current = self._loads(item.current_payload_json, {})
                    task_id = str(current.get("id") or "")
                    task = next((row for row in snapshot_tasks if str(row.get("id") or "") == task_id), None)
                    db_task = session.get(BusinessTask, task_id)
                    if task is None or db_task is None or self._protected_fields(db_task):
                        raise ProjectTaskDraftError("preview_stale", f"任务 {key} 已变化，请重新预览")
                    task["title"] = proposed["title"]
                    task["estimatedHours"] = proposed["estimated_hours"]
                    stage_payload = task.get("stage") if isinstance(task.get("stage"), dict) else {}
                    task["stage"] = {
                        **stage_payload,
                        "description": proposed["description"],
                        "acceptanceCriteria": proposed["acceptance_criteria"],
                    }
                    task["taskKey"] = key
                    task["stageKey"] = item.stage_key
                    task["workspaceKey"] = item.workspace_key
                    task["dependencyTaskKeys"] = proposed["dependency_task_keys"]
                    task["deliverables"] = proposed["deliverables"]
                    task["requirementVersionId"] = preview.requirement_version_id
                    updated_ids.append(task_id)
                    task_ids_by_key[key] = task_id
            new_revision, _normalized = self.ledger.save_in_session(
                session,
                snapshot,
                expected_revision,
                trusted_task_trace_sync=True,
            )
            for key in selected:
                item = by_key[key]
                proposed = self._loads(item.proposed_payload_json, {})
                task = session.get(BusinessTask, task_ids_by_key[key])
                if task is None:
                    raise ProjectTaskDraftError("task_write_failed", f"任务 {key} 未能写入")
                task.task_key = key
                task.stage_key = item.stage_key
                task.workspace_key = item.workspace_key
                task.dependency_task_keys_json = canonical_json(proposed["dependency_task_keys"])
                task.deliverables_json = canonical_json(proposed["deliverables"])
                task.requirement_version_id = preview.requirement_version_id
            preview.status = "confirmed"
            preview.confirmed_at = utcnow()
            result = {
                "project_id": project_id,
                "preview_id": preview_id,
                "revision": new_revision,
                "created_task_ids": created_ids,
                "updated_task_ids": updated_ids,
            }
            self._save_request(
                session,
                request_id=request_id,
                operation=self.CONFIRM_OPERATION,
                payload_hash=payload_hash,
                result=result,
            )
            session.commit()
            return {**result, "idempotent": False}

    @staticmethod
    def _requirement_version(
        session: Session,
        project_id: str,
        requirement_version_id: int | None,
    ) -> RequirementDocumentVersion:
        cases = list(session.scalars(select(RequirementCase).where(RequirementCase.project_id == project_id)))
        if len(cases) > 1:
            raise ProjectTaskDraftError('requirement_case_ambiguous', '项目关联多个正式需求，不能自动选择')
        if cases:
            case = cases[0]
            row = session.scalar(select(RequirementDocumentVersion).where(
                RequirementDocumentVersion.case_id == case.id, RequirementDocumentVersion.version == case.current_version))
            if not row or (requirement_version_id is not None and requirement_version_id != row.id):
                raise ProjectTaskDraftError('requirement_version_missing', '请使用最新正式需求版本生成任务差异')
            return row
        if requirement_version_id is not None:
            row = session.get(RequirementDocumentVersion, requirement_version_id)
            if row is None or row.project_id != project_id:
                raise ProjectTaskDraftError("requirement_version_missing", "需求蓝图版本不存在")
            return row
        row = session.scalar(
            select(RequirementDocumentVersion)
            .where(RequirementDocumentVersion.project_id == project_id)
            .order_by(RequirementDocumentVersion.version.desc())
            .limit(1)
        )
        if row is None:
            raise ProjectTaskDraftError("requirement_version_missing", "请先导入项目需求蓝图")
        return row

    @staticmethod
    def _protected_fields(task: BusinessTask | None) -> list[str]:
        if task is None:
            return []
        fields: list[str] = []
        if task.status != "todo":
            fields.append("status")
        if float(task.actual_hours or 0) > 0:
            fields.append("actual_hours")
        if task.acceptance_points_json not in {"", "[]"}:
            fields.append("acceptance_evidence")
        if task.codex_execution_status != "todo" or task.codex_implemented_at is not None:
            fields.append("implementation_history")
        return fields

    def _task_payload(self, task: BusinessTask) -> dict[str, Any]:
        stage = self._loads(task.stage_payload_json, {})
        return {
            "id": task.id,
            "title": task.title,
            "description": str(stage.get("description") or ""),
            "estimated_hours": float(task.estimated_hours),
            "actual_hours": float(task.actual_hours),
            "status": task.status,
            "workspace_key": str(task.workspace_key or ""),
            "stage_key": str(task.stage_key or ""),
            "dependency_task_keys": self._loads(task.dependency_task_keys_json, []),
            "deliverables": self._loads(task.deliverables_json, []),
            "acceptance_criteria": stage.get("acceptanceCriteria") or [],
        }

    @staticmethod
    def _allowed_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: payload.get(key)
            for key in (
                "title", "description", "estimated_hours", "workspace_key", "stage_key",
                "dependency_task_keys", "deliverables", "acceptance_criteria",
            )
        }

    def _preview_view(
        self,
        preview: ProjectTaskDraftPreview,
        version: RequirementDocumentVersion,
        items: list[ProjectTaskDraftItem],
        token: str,
    ) -> dict[str, Any]:
        return {
            "id": preview.id,
            "project_id": preview.project_id,
            "requirement_version_id": preview.requirement_version_id,
            "requirement_version": version.version,
            "source_label": version.source_label,
            "project_revision": preview.project_revision,
            "preview_token": token,
            "status": preview.status,
            "summary": self._loads(preview.summary_json, {}),
            "created_at": preview.created_at,
            "expires_at": preview.expires_at,
            "items": [
                {
                    "id": item.id,
                    "task_key": item.task_key,
                    "workspace_key": item.workspace_key,
                    "stage_key": item.stage_key,
                    "classification": item.classification,
                    "current": self._loads(item.current_payload_json, {}),
                    "proposed": self._loads(item.proposed_payload_json, {}),
                    "protected_fields": self._loads(item.protected_fields_json, []),
                    "conflict_reason": item.conflict_reason,
                    "selected": item.selected,
                    "ordinal": item.ordinal,
                }
                for item in items
            ],
        }
