from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .services.customer_images import CustomerImageArchiveService, CustomerImageError


customer_image_router = APIRouter(prefix="/api/customer-images", tags=["customer-images"])


class HistoryRecoveryRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    confirmed: bool


class DeleteCustomerImageRequest(BaseModel):
    confirmed: bool


def _service(request: Request) -> CustomerImageArchiveService:
    return request.app.state.runtime.customer_images


def _http_error(exc: CustomerImageError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


@customer_image_router.get("")
async def list_customer_images(
    request: Request,
    channel: str | None = Query(default=None, max_length=32),
    conversation_id: int | None = Query(default=None, ge=1),
    date_from: str | None = Query(default=None, max_length=10),
    date_to: str | None = Query(default=None, max_length=10),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    try:
        return _service(request).list_images(
            channel=channel,
            conversation_id=conversation_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except CustomerImageError as exc:
        raise _http_error(exc) from exc


@customer_image_router.get("/status")
async def customer_image_status(request: Request):
    return _service(request).status()


@customer_image_router.get("/filters")
async def customer_image_filters(request: Request):
    return _service(request).filters()


@customer_image_router.get("/history-preview")
async def customer_image_history_preview(request: Request):
    runtime = request.app.state.runtime
    return runtime.customer_images.history_preview(runtime.status.listener)


@customer_image_router.get("/attention")
async def customer_image_attention(request: Request):
    return _service(request).attention_items()


@customer_image_router.post("/history-recover")
async def recover_customer_image_history(
    request: Request,
    payload: HistoryRecoveryRequest,
):
    if not payload.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "confirmation_required", "message": "请先确认自动恢复"},
        )
    runtime = request.app.state.runtime
    try:
        return await runtime.customer_images.recover_xianyu_history(
            payload.request_id,
            runtime.adapter,
            runtime.processor,
        )
    except CustomerImageError as exc:
        raise _http_error(exc) from exc


@customer_image_router.get("/{archive_id}/content")
async def customer_image_content(
    request: Request,
    archive_id: str,
    download: bool = Query(default=False),
):
    try:
        path, mime_type, original_name = _service(request).content_file(archive_id)
    except CustomerImageError as exc:
        raise _http_error(exc) from exc
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        media_type=mime_type,
        filename=original_name if download else None,
        content_disposition_type=disposition,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@customer_image_router.post("/{archive_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer_image(
    request: Request,
    archive_id: str,
    payload: DeleteCustomerImageRequest,
):
    if not payload.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "confirmation_required", "message": "请先确认删除本地副本"},
        )
    try:
        _service(request).delete_local_copy(archive_id)
    except CustomerImageError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
