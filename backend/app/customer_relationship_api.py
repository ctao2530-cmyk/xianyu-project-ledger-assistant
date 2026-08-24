from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from .customer_relationship_schemas import (
    CustomerRelationPreview,
    CustomerRelationPreviewRequest,
    CustomerRelationRebindRequest,
    CustomerRelationRebindResult,
    CustomerUpdateRequest,
    CustomerUpdateResult,
)
from .ledger import RevisionConflict
from .services.customer_relationships import CustomerRelationshipError


customer_relationship_router = APIRouter(
    prefix="/api/ledger",
    tags=["customer-relationships"],
)


def _service(request: Request):
    return request.app.state.runtime.customer_relationships


def _relationship_http_error(exc: CustomerRelationshipError) -> HTTPException:
    if exc.code in {"customer_not_found", "project_not_found"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        "request_id_reused",
        "request_record_invalid",
        "project_customer_changed",
        "relationship_inconsistent",
        "preview_expired",
    }:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _revision_http_error(exc: RevisionConflict, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "ledger_revision_conflict", "message": message, "revision": exc.revision},
    )


@customer_relationship_router.patch(
    "/customers/{customer_id}",
    response_model=CustomerUpdateResult,
)
async def update_customer(
    customer_id: str,
    payload: CustomerUpdateRequest,
    request: Request,
) -> CustomerUpdateResult:
    try:
        result = _service(request).update_customer(
            customer_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            name=payload.name,
            source=payload.source,
            phone=payload.phone,
            follow_up_status=payload.follow_up_status,
            last_contact_at=payload.last_contact_at,
            level=payload.level,
            tags=payload.tags,
            current_need=payload.current_need,
            price_type=payload.price_type,
            price_amount=payload.price_amount,
            next_action=payload.next_action,
            notes=payload.notes,
        )
    except RevisionConflict as exc:
        raise _revision_http_error(
            exc,
            "经营数据已在其他页面更新，请刷新后重新编辑客户",
        ) from None
    except CustomerRelationshipError as exc:
        raise _relationship_http_error(exc) from None
    request.app.state.runtime.event_hub.publish_nowait(
        {"type": "ledger_updated", "revision": result["revision"], "source": "customer_update"}
    )
    return CustomerUpdateResult(**result)


@customer_relationship_router.post(
    "/customer-relations/preview",
    response_model=CustomerRelationPreview,
)
async def preview_customer_relation(
    payload: CustomerRelationPreviewRequest,
    request: Request,
) -> CustomerRelationPreview:
    try:
        result = _service(request).preview_rebind(
            expected_revision=payload.expected_revision,
            project_id=payload.project_id,
            current_customer_id=payload.current_customer_id,
            target_customer_id=payload.target_customer_id,
        )
    except RevisionConflict as exc:
        raise _revision_http_error(
            exc,
            "经营数据已经变化，请刷新后重新预览关系影响",
        ) from None
    except CustomerRelationshipError as exc:
        raise _relationship_http_error(exc) from None
    return CustomerRelationPreview(**result)


@customer_relationship_router.post(
    "/customer-relations/rebind",
    response_model=CustomerRelationRebindResult,
)
async def rebind_customer_relation(
    payload: CustomerRelationRebindRequest,
    request: Request,
) -> CustomerRelationRebindResult:
    try:
        result = _service(request).rebind_project(
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            preview_token=payload.preview_token,
            project_id=payload.project_id,
            current_customer_id=payload.current_customer_id,
            target_customer_id=payload.target_customer_id,
        )
    except RevisionConflict as exc:
        raise _revision_http_error(
            exc,
            "经营数据已经变化，本次关系修正未执行，请重新预览",
        ) from None
    except CustomerRelationshipError as exc:
        raise _relationship_http_error(exc) from None
    request.app.state.runtime.event_hub.publish_nowait(
        {"type": "ledger_updated", "revision": result["revision"], "source": "customer_relation_rebind"}
    )
    return CustomerRelationRebindResult(**result)
