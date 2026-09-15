from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from .codex_sync_api import _local_only
from .customer_analysis_schemas import (
    CustomerAnalysisRetryRequest,
    CustomerAnalysisSnapshotView,
    CustomerAnalysisSubscriptionPause,
    CustomerAnalysisSubscriptionUpsert,
    CustomerAnalysisSubscriptionView,
)
from .services.customer_auto_analysis import (
    CustomerAutoAnalysisError,
    CustomerAutoAnalysisService,
)


customer_analysis_router = APIRouter(
    prefix="/api/customer-context", tags=["customer-analysis"]
)


def _service(request: Request) -> CustomerAutoAnalysisService:
    _local_only(request)
    return request.app.state.runtime.customer_auto_analysis


def _raise(exc: CustomerAutoAnalysisError) -> None:
    code = exc.status_code
    if code == 400:
        if exc.code.endswith("_not_found"):
            code = status.HTTP_404_NOT_FOUND
        elif "conflict" in exc.code or exc.code in {
            "request_id_reused",
            "request_record_invalid",
            "conversation_already_subscribed",
        }:
            code = status.HTTP_409_CONFLICT
        else:
            code = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": exc.safe_message},
    ) from None


@customer_analysis_router.post(
    "/analysis-subscriptions",
    response_model=CustomerAnalysisSubscriptionView,
)
async def upsert_customer_analysis_subscription(
    payload: CustomerAnalysisSubscriptionUpsert,
    request: Request,
) -> CustomerAnalysisSubscriptionView:
    try:
        return _service(request).upsert_subscription(
            request_id=payload.request_id,
            thread_id=payload.thread_id,
            expected_thread_revision=payload.expected_thread_revision,
            expected_subscription_revision=payload.expected_subscription_revision,
            model=payload.model,
            include_images=payload.include_images,
            debounce_seconds=payload.debounce_seconds,
            max_wait_seconds=payload.max_wait_seconds,
            authorization_note=payload.authorization_note,
        )
    except CustomerAutoAnalysisError as exc:
        _raise(exc)


@customer_analysis_router.get(
    "/threads/{thread_id}/analysis",
    response_model=CustomerAnalysisSubscriptionView | None,
)
async def customer_analysis_subscription(
    thread_id: str,
    request: Request,
) -> CustomerAnalysisSubscriptionView | None:
    return _service(request).subscription(thread_id)


@customer_analysis_router.post(
    "/analysis-subscriptions/{subscription_id}/pause",
    response_model=CustomerAnalysisSubscriptionView,
)
async def pause_customer_analysis_subscription(
    subscription_id: str,
    payload: CustomerAnalysisSubscriptionPause,
    request: Request,
) -> CustomerAnalysisSubscriptionView:
    try:
        return _service(request).pause_subscription(
            subscription_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            reason=payload.reason,
        )
    except CustomerAutoAnalysisError as exc:
        _raise(exc)


@customer_analysis_router.post(
    "/analysis-subscriptions/{subscription_id}/retry",
    response_model=CustomerAnalysisSubscriptionView,
)
async def retry_customer_analysis_subscription(
    subscription_id: str,
    payload: CustomerAnalysisRetryRequest,
    request: Request,
) -> CustomerAnalysisSubscriptionView:
    try:
        return _service(request).retry(
            subscription_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
        )
    except CustomerAutoAnalysisError as exc:
        _raise(exc)


@customer_analysis_router.get(
    "/threads/{thread_id}/analysis-artifacts",
    response_model=CustomerAnalysisSnapshotView,
)
async def customer_analysis_artifacts(
    thread_id: str,
    request: Request,
    version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> CustomerAnalysisSnapshotView:
    try:
        return _service(request).artifacts(thread_id, version=version, limit=limit)
    except CustomerAutoAnalysisError as exc:
        _raise(exc)

