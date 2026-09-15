from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from .ledger import RevisionConflict
from .project_task_draft_schemas import (
    ProjectRequirementBlueprintView,
    ProjectRequirementImportCommitRequest,
    ProjectRequirementImportPreview,
    ProjectRequirementImportPreviewRequest,
    ProjectRequirementImportResult,
    ProjectTaskDraftConfirmRequest,
    ProjectTaskDraftConfirmResult,
    ProjectTaskDraftPreviewRequest,
    ProjectTaskDraftPreviewView,
)
from .services.project_task_drafts import ProjectTaskDraftError


project_task_draft_router = APIRouter(tags=["project-task-drafts"])


def _service(request: Request):
    return request.app.state.runtime.project_task_drafts


def _error(exc: ProjectTaskDraftError) -> HTTPException:
    if exc.code in {"project_not_found", "preview_not_found", "requirement_version_missing"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        "request_id_reused", "request_record_invalid", "preview_expired", "preview_stale",
        "task_id_conflict", "task_write_failed",
    }:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


def _revision(exc: RevisionConflict, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "ledger_revision_conflict", "message": message, "revision": exc.revision},
    )


@project_task_draft_router.get(
    "/api/projects/{project_id}/requirement-blueprints",
    response_model=list[ProjectRequirementBlueprintView],
)
async def list_project_blueprints(project_id: str, request: Request):
    try:
        return _service(request).list_blueprints(project_id)
    except ProjectTaskDraftError as exc:
        raise _error(exc) from None


@project_task_draft_router.post(
    "/api/projects/{project_id}/requirement-blueprints/preview",
    response_model=ProjectRequirementImportPreview,
)
async def preview_project_blueprint(
    project_id: str,
    payload: ProjectRequirementImportPreviewRequest,
    request: Request,
):
    try:
        return _service(request).preview_blueprint_import(
            project_id,
            expected_revision=payload.expected_revision,
            source_filename=payload.source_filename,
            blueprint_data=payload.blueprint,
        )
    except RevisionConflict as exc:
        raise _revision(exc, "经营数据已变化，请重新预览需求蓝图") from None
    except ProjectTaskDraftError as exc:
        raise _error(exc) from None


@project_task_draft_router.post(
    "/api/projects/{project_id}/requirement-blueprints/commit",
    response_model=ProjectRequirementImportResult,
)
async def commit_project_blueprint(
    project_id: str,
    payload: ProjectRequirementImportCommitRequest,
    request: Request,
):
    try:
        result = _service(request).commit_blueprint_import(
            project_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            source_filename=payload.source_filename,
            blueprint_data=payload.blueprint,
            preview_token=payload.preview_token,
        )
    except RevisionConflict as exc:
        raise _revision(exc, "经营数据已变化，本次蓝图没有导入") from None
    except ProjectTaskDraftError as exc:
        raise _error(exc) from None
    request.app.state.runtime.event_hub.publish_nowait(
        {
            "type": "ledger_updated",
            "source": "project_requirement_import",
            "project_id": project_id,
            "revision": result["revision"],
        }
    )
    return result


@project_task_draft_router.post(
    "/api/projects/{project_id}/task-draft-previews",
    response_model=ProjectTaskDraftPreviewView,
)
async def create_project_task_draft_preview(
    project_id: str,
    payload: ProjectTaskDraftPreviewRequest,
    request: Request,
):
    try:
        return _service(request).create_preview(
            project_id,
            expected_revision=payload.expected_revision,
            requirement_version_id=payload.requirement_version_id,
        )
    except RevisionConflict as exc:
        raise _revision(exc, "经营数据已变化，请重新生成任务差异") from None
    except ProjectTaskDraftError as exc:
        raise _error(exc) from None


@project_task_draft_router.get(
    "/api/projects/{project_id}/task-drafts",
    response_model=ProjectTaskDraftPreviewView | None,
)
async def latest_project_task_draft(project_id: str, request: Request):
    try:
        return _service(request).latest_preview(project_id)
    except ProjectTaskDraftError as exc:
        raise _error(exc) from None


@project_task_draft_router.post(
    "/api/projects/{project_id}/task-drafts/confirm",
    response_model=ProjectTaskDraftConfirmResult,
)
async def confirm_project_task_draft(
    project_id: str,
    payload: ProjectTaskDraftConfirmRequest,
    request: Request,
):
    try:
        result = _service(request).confirm(
            project_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            preview_id=payload.preview_id,
            preview_token=payload.preview_token,
            selected_task_keys=payload.selected_task_keys,
            apply_allowed_updates_only=payload.apply_allowed_updates_only,
            note=payload.note,
        )
    except RevisionConflict as exc:
        raise _revision(exc, "经营数据已变化，本次任务没有写入") from None
    except ProjectTaskDraftError as exc:
        raise _error(exc) from None
    request.app.state.runtime.event_hub.publish_nowait(
        {
            "type": "ledger_updated",
            "source": "project_task_draft_confirm",
            "project_id": project_id,
            "revision": result["revision"],
        }
    )
    return result
