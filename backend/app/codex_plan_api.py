from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from .ai import AIProviderError
from .codex_plan_schemas import (
    CodexPlanConfirmRequest,
    CodexPlanConfirmResult,
    CodexPlanDraftUpdateRequest,
    CodexPlanGenerateRequest,
    CodexPlanView,
    RepositoryBindingCreateRequest,
    RepositoryBindingView,
)
from .ledger import RevisionConflict
from .services.codex_plans import CodexPlanError


codex_plan_router = APIRouter(prefix="/api", tags=["codex-plans"])


def _service(request: Request):
    return request.app.state.runtime.codex_plans


def _require_local(request: Request) -> None:
    client = request.client.host if request.client else ""
    if (
        client not in {"127.0.0.1", "::1", "localhost", "testclient"}
        or request.headers.get("x-yuda-desktop") != "1"
    ):
        raise HTTPException(status_code=403, detail="本地仓库与开发计划只允许本机桌面端访问")


def _raise(exc: CodexPlanError) -> None:
    if exc.code.endswith("_missing"):
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        "request_id_reused",
        "requirement_version_conflict",
        "plan_version_conflict",
        "plan_not_editable",
        "plan_not_confirmable",
        "project_conflict",
        "repository_snapshot_immutable",
    }:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=exc.message) from None


@codex_plan_router.post(
    "/codex/repository-bindings", response_model=RepositoryBindingView
)
async def create_repository_binding(
    payload: RepositoryBindingCreateRequest, request: Request
) -> RepositoryBindingView:
    _require_local(request)
    try:
        return _service(request).create_binding(**payload.model_dump())
    except CodexPlanError as exc:
        _raise(exc)


@codex_plan_router.get(
    "/requirement-cases/{case_id}/codex-bindings",
    response_model=list[RepositoryBindingView],
)
async def list_repository_bindings(case_id: str, request: Request) -> list[RepositoryBindingView]:
    _require_local(request)
    return _service(request).bindings_for_case(case_id)


@codex_plan_router.post("/codex/plans/generate", response_model=CodexPlanView)
async def generate_codex_plan(
    payload: CodexPlanGenerateRequest, request: Request
) -> CodexPlanView:
    _require_local(request)
    try:
        return await _service(request).generate(**payload.model_dump())
    except CodexPlanError as exc:
        _raise(exc)
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=exc.safe_message) from None


@codex_plan_router.get("/codex/plans/{plan_id}", response_model=CodexPlanView)
async def get_codex_plan(plan_id: str, request: Request) -> CodexPlanView:
    _require_local(request)
    try:
        return _service(request).get(plan_id)
    except CodexPlanError as exc:
        _raise(exc)


@codex_plan_router.put("/codex/plans/{plan_id}/draft", response_model=CodexPlanView)
async def update_codex_plan_draft(
    plan_id: str, payload: CodexPlanDraftUpdateRequest, request: Request
) -> CodexPlanView:
    _require_local(request)
    try:
        return _service(request).update_draft(plan_id, **payload.model_dump())
    except CodexPlanError as exc:
        _raise(exc)


@codex_plan_router.post(
    "/codex/plans/{plan_id}/confirm", response_model=CodexPlanConfirmResult
)
async def confirm_codex_plan(
    plan_id: str, payload: CodexPlanConfirmRequest, request: Request
) -> CodexPlanConfirmResult:
    _require_local(request)
    try:
        result = _service(request).confirm(
            plan_id,
            **payload.model_dump(exclude={"confirmed"}),
        )
        return CodexPlanConfirmResult(**result)
    except RevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "经营数据已变化，请刷新后重新确认", "revision": exc.revision},
        ) from None
    except CodexPlanError as exc:
        _raise(exc)


@codex_plan_router.get(
    "/projects/{project_id}/codex-plan", response_model=CodexPlanView | None
)
async def project_codex_plan(project_id: str, request: Request) -> CodexPlanView | None:
    _require_local(request)
    return _service(request).latest_for_project(project_id)


@codex_plan_router.get(
    "/requirement-cases/{case_id}/codex-plan", response_model=CodexPlanView | None
)
async def requirement_case_codex_plan(case_id: str, request: Request) -> CodexPlanView | None:
    _require_local(request)
    return _service(request).latest_for_case(case_id)
