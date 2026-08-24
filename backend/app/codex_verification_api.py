from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .codex_sync_api import _local_only
from .codex_verification_schemas import (
    AcceptanceDecisionInput,
    GitLinkInput,
    ManualAcceptancePointsInput,
    ManualTimeEntryInput,
    ProjectOutcomeFreezeInput,
    ProjectOutcomeFreezeView,
    ProjectVerificationView,
    RetireAcceptancePointInput,
    TestExecutionInput,
    TimeAdjustmentInput,
)
from .ledger import RevisionConflict
from .services.codex_verification import CodexVerificationError
from .services.project_sample_formation import ProjectSampleFormationError


codex_verification_router = APIRouter(prefix="/api")


def _raise(exc: Exception) -> None:
    if isinstance(exc, RevisionConflict):
        raise HTTPException(
            409,
            detail={
                "code": "revision_conflict",
                "message": "经营数据已在其他页面更新，请刷新后重试",
                "revision": exc.revision,
            },
        ) from None
    if isinstance(exc, CodexVerificationError):
        raise HTTPException(
            exc.status_code,
            detail={"code": exc.code, "message": exc.safe_message},
        ) from None
    if isinstance(exc, ProjectSampleFormationError):
        raise HTTPException(
            exc.status_code,
            detail={"code": exc.code, "message": exc.safe_message},
        ) from None
    raise exc


@codex_verification_router.get(
    "/projects/{project_id}/verification",
    response_model=ProjectVerificationView,
)
def project_verification(project_id: str, request: Request) -> ProjectVerificationView:
    _local_only(request)
    try:
        return request.app.state.runtime.codex_verification.view(project_id)
    except (CodexVerificationError, ProjectSampleFormationError, RevisionConflict) as exc:
        _raise(exc)


@codex_verification_router.post(
    "/projects/{project_id}/manual-acceptance-points",
    response_model=ProjectVerificationView,
)
def create_manual_acceptance_points(
    project_id: str,
    payload: ManualAcceptancePointsInput,
    request: Request,
) -> ProjectVerificationView:
    _local_only(request)
    try:
        request.app.state.runtime.sample_formation.create_manual_points(
            project_id, payload
        )
        return request.app.state.runtime.codex_verification.view(project_id)
    except (ProjectSampleFormationError, CodexVerificationError, RevisionConflict) as exc:
        _raise(exc)


@codex_verification_router.post(
    "/acceptance-points/{point_id}/retire",
    response_model=ProjectVerificationView,
)
def retire_manual_acceptance_point(
    point_id: str,
    payload: RetireAcceptancePointInput,
    request: Request,
) -> ProjectVerificationView:
    _local_only(request)
    try:
        request.app.state.runtime.sample_formation.retire_manual_point(
            point_id, payload
        )
        point_project_id = request.app.state.runtime.sample_formation.project_id_for_point(
            point_id
        )
        return request.app.state.runtime.codex_verification.view(point_project_id)
    except (ProjectSampleFormationError, CodexVerificationError, RevisionConflict) as exc:
        _raise(exc)


@codex_verification_router.post(
    "/projects/{project_id}/outcome-freezes",
    response_model=ProjectOutcomeFreezeView,
)
def freeze_project_outcome(
    project_id: str,
    payload: ProjectOutcomeFreezeInput,
    request: Request,
) -> ProjectOutcomeFreezeView:
    _local_only(request)
    try:
        return request.app.state.runtime.sample_formation.freeze(project_id, payload)
    except (ProjectSampleFormationError, RevisionConflict) as exc:
        _raise(exc)


@codex_verification_router.get(
    "/projects/{project_id}/outcome-freezes",
    response_model=list[ProjectOutcomeFreezeView],
)
def project_outcome_freezes(
    project_id: str,
    request: Request,
) -> list[ProjectOutcomeFreezeView]:
    _local_only(request)
    try:
        return request.app.state.runtime.sample_formation.freezes(project_id)
    except ProjectSampleFormationError as exc:
        _raise(exc)


@codex_verification_router.post(
    "/acceptance-points/{point_id}/decision",
    response_model=ProjectVerificationView,
)
def decide_acceptance(
    point_id: str,
    payload: AcceptanceDecisionInput,
    request: Request,
) -> ProjectVerificationView:
    _local_only(request)
    try:
        return request.app.state.runtime.codex_verification.decide(point_id, payload)
    except (CodexVerificationError, ProjectSampleFormationError, RevisionConflict) as exc:
        _raise(exc)


@codex_verification_router.post(
    "/projects/{project_id}/tests/run",
    response_model=ProjectVerificationView,
)
async def run_confirmed_test(
    project_id: str,
    payload: TestExecutionInput,
    request: Request,
) -> ProjectVerificationView:
    _local_only(request)
    try:
        return await request.app.state.runtime.codex_verification.run_test(project_id, payload)
    except (CodexVerificationError, ProjectSampleFormationError, RevisionConflict) as exc:
        _raise(exc)


@codex_verification_router.post(
    "/projects/{project_id}/time-entries",
    response_model=ProjectVerificationView,
)
def add_time_entry(
    project_id: str,
    payload: ManualTimeEntryInput,
    request: Request,
) -> ProjectVerificationView:
    _local_only(request)
    try:
        return request.app.state.runtime.codex_verification.add_time(project_id, payload)
    except (CodexVerificationError, ProjectSampleFormationError, RevisionConflict) as exc:
        _raise(exc)


@codex_verification_router.post(
    "/time-entries/{entry_id}/adjust",
    response_model=ProjectVerificationView,
)
def adjust_time_entry(
    entry_id: str,
    payload: TimeAdjustmentInput,
    request: Request,
) -> ProjectVerificationView:
    _local_only(request)
    try:
        return request.app.state.runtime.codex_verification.adjust_time(entry_id, payload)
    except (CodexVerificationError, ProjectSampleFormationError, RevisionConflict) as exc:
        _raise(exc)


@codex_verification_router.post(
    "/projects/{project_id}/git-links",
    response_model=ProjectVerificationView,
)
def link_git_commit(
    project_id: str,
    payload: GitLinkInput,
    request: Request,
) -> ProjectVerificationView:
    _local_only(request)
    try:
        return request.app.state.runtime.codex_verification.link_git(project_id, payload)
    except (CodexVerificationError, ProjectSampleFormationError, RevisionConflict) as exc:
        _raise(exc)
