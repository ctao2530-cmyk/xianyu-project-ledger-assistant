from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .codex_runtime_schemas import (
    ApprovalDecisionInput,
    ManagedApprovalView,
    ManagedDiffView,
    ManagedRunActionInput,
    ManagedRunCreateInput,
    ManagedRunView,
    ManagedRuntimeProjectView,
    RuntimeCapabilitiesView,
)
from .codex_sync_api import _local_only
from .services.codex_sync import CodexSyncError


codex_runtime_router = APIRouter(prefix="/api")


def _raise(exc: CodexSyncError) -> None:
    raise HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.safe_message}) from None


@codex_runtime_router.get("/codex/runtime/capabilities", response_model=RuntimeCapabilitiesView)
async def runtime_capabilities(request: Request) -> RuntimeCapabilitiesView:
    _local_only(request)
    return await request.app.state.runtime.codex_development.capabilities()


@codex_runtime_router.get("/projects/{project_id}/codex-runtime", response_model=ManagedRuntimeProjectView)
async def project_runtime(project_id: str, request: Request) -> ManagedRuntimeProjectView:
    _local_only(request)
    try:
        return await request.app.state.runtime.codex_development.project_view(project_id)
    except CodexSyncError as exc:
        _raise(exc)


@codex_runtime_router.post("/codex/runs", response_model=ManagedRunView)
async def create_run(payload: ManagedRunCreateInput, request: Request) -> ManagedRunView:
    _local_only(request)
    try:
        return await request.app.state.runtime.codex_development.create(payload)
    except CodexSyncError as exc:
        _raise(exc)


@codex_runtime_router.post("/codex/runs/{run_id}/pause", response_model=ManagedRunView)
async def pause_run(run_id: str, payload: ManagedRunActionInput, request: Request) -> ManagedRunView:
    _local_only(request)
    try:
        return await request.app.state.runtime.codex_development.pause(run_id, payload.request_id)
    except CodexSyncError as exc:
        _raise(exc)


@codex_runtime_router.post("/codex/runs/{run_id}/resume", response_model=ManagedRunView)
async def resume_run(run_id: str, payload: ManagedRunActionInput, request: Request) -> ManagedRunView:
    _local_only(request)
    try:
        return await request.app.state.runtime.codex_development.resume(run_id, payload.request_id)
    except CodexSyncError as exc:
        _raise(exc)


@codex_runtime_router.post("/codex/runs/{run_id}/cancel", response_model=ManagedRunView)
async def cancel_run(run_id: str, payload: ManagedRunActionInput, request: Request) -> ManagedRunView:
    _local_only(request)
    try:
        return await request.app.state.runtime.codex_development.cancel(run_id, payload.request_id)
    except CodexSyncError as exc:
        _raise(exc)


@codex_runtime_router.get("/codex/runs/{run_id}/diff", response_model=ManagedDiffView)
async def run_diff(run_id: str, request: Request) -> ManagedDiffView:
    _local_only(request)
    try:
        return request.app.state.runtime.codex_development.diff(run_id)
    except CodexSyncError as exc:
        _raise(exc)


@codex_runtime_router.post("/codex/runs/{run_id}/open", status_code=204)
async def open_worktree(run_id: str, request: Request) -> None:
    _local_only(request)
    try:
        request.app.state.runtime.codex_development.open_worktree(run_id)
    except CodexSyncError as exc:
        _raise(exc)


@codex_runtime_router.post("/codex/approvals/{approval_id}/decision", response_model=ManagedApprovalView)
async def decide_approval(approval_id: str, payload: ApprovalDecisionInput, request: Request) -> ManagedApprovalView:
    _local_only(request)
    try:
        return await request.app.state.runtime.codex_development.decide_approval(
            approval_id, payload.request_id, payload.decision
        )
    except CodexSyncError as exc:
        _raise(exc)
