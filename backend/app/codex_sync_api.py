from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from .codex_sync_schemas import (
    CodexEventInput,
    CodexEventReceipt,
    CodexProjectContext,
    CodexProjectSyncView,
    CodexTaskContext,
)
from .services.codex_sync import CodexSyncError, MAX_PAYLOAD_BYTES


codex_sync_router = APIRouter(prefix="/api")
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
MAX_CLOCK_SKEW_SECONDS = 300


def _local_only(request: Request) -> None:
    client = request.client.host if request.client else ""
    if client not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="Codex 同步仅允许本机访问")


def _safe_error(exc: CodexSyncError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.safe_message},
    ) from None


def signature_for(secret: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    signed = (
        timestamp.encode("utf-8")
        + b"\n"
        + method.upper().encode("ascii")
        + b"\n"
        + path.encode("utf-8")
        + b"\n"
        + body
    )
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def verify_hmac(request: Request, body: bytes) -> None:
    _local_only(request)
    runtime = request.app.state.runtime
    secret = runtime.settings.xunying_codex_event_secret.get_secret_value().strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Codex 同步密钥尚未配置")
    timestamp = request.headers.get("x-xunying-timestamp", "")
    provided = request.headers.get("x-xunying-signature", "")
    try:
        parsed = datetime.fromtimestamp(float(timestamp), timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=401, detail="Codex 同步签名时间无效") from None
    if abs((datetime.now(timezone.utc) - parsed).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Codex 同步签名已过期")
    expected = signature_for(secret, timestamp, request.method, request.url.path, body)
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Codex 同步签名无效")


@codex_sync_router.post("/codex/events", response_model=CodexEventReceipt)
async def receive_codex_event(request: Request) -> CodexEventReceipt:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_PAYLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Codex 事件超过 64 KiB 限制")
        except ValueError:
            raise HTTPException(status_code=400, detail="Content-Length 无效") from None
    body = await request.body()
    if len(body) > MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Codex 事件超过 64 KiB 限制")
    verify_hmac(request, body)
    try:
        event = CodexEventInput.model_validate_json(body)
    except (ValidationError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="Codex 事件结构无效") from None
    try:
        return request.app.state.runtime.codex_sync.ingest(event)
    except CodexSyncError as exc:
        _safe_error(exc)


@codex_sync_router.get(
    "/projects/{project_id}/codex-sync", response_model=CodexProjectSyncView
)
async def project_codex_sync(project_id: str, request: Request) -> CodexProjectSyncView:
    _local_only(request)
    try:
        return request.app.state.runtime.codex_sync.project_sync(project_id)
    except CodexSyncError as exc:
        _safe_error(exc)


@codex_sync_router.get(
    "/codex/projects/{project_id}/context", response_model=CodexProjectContext
)
async def codex_project_context(project_id: str, request: Request) -> CodexProjectContext:
    verify_hmac(request, b"")
    try:
        return request.app.state.runtime.codex_sync.project_context(project_id)
    except CodexSyncError as exc:
        _safe_error(exc)


@codex_sync_router.get(
    "/codex/projects/{project_id}/tasks", response_model=list[CodexTaskContext]
)
async def codex_task_list(project_id: str, request: Request) -> list[CodexTaskContext]:
    verify_hmac(request, b"")
    try:
        return request.app.state.runtime.codex_sync.project_context(project_id).tasks
    except CodexSyncError as exc:
        _safe_error(exc)


@codex_sync_router.get(
    "/codex/projects/{project_id}/tasks/{task_key}", response_model=CodexTaskContext
)
async def codex_task_context(
    project_id: str, task_key: str, request: Request
) -> CodexTaskContext:
    verify_hmac(request, b"")
    try:
        return request.app.state.runtime.codex_sync.task_context(project_id, task_key)
    except CodexSyncError as exc:
        _safe_error(exc)
