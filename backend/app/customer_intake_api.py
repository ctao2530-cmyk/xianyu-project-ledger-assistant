from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from .codex_sync_api import _local_only
from .customer_intake_schemas import (
    CustomerCreateRequest,
    CustomerCreateResult,
    CustomerIntakeCandidatesView,
)
from .ledger import RevisionConflict
from .services.customer_intake import CustomerIntakeError


customer_intake_router = APIRouter(prefix="/api/customers", tags=["customer-intake"])


def _error(exc: CustomerIntakeError) -> None:
    if exc.code == "conversation_not_found":
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        "request_id_reused",
        "request_record_invalid",
        "conversation_relationship_changed",
        "conversation_relationship_conflict",
        "conversation_already_linked",
    }:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": str(exc)},
    ) from None


@customer_intake_router.get(
    "/intake-candidates",
    response_model=CustomerIntakeCandidatesView,
)
async def intake_candidates(request: Request) -> CustomerIntakeCandidatesView:
    _local_only(request)
    return CustomerIntakeCandidatesView(
        **request.app.state.runtime.customer_intake.candidates()
    )


@customer_intake_router.post("", response_model=CustomerCreateResult)
async def create_customer(
    payload: CustomerCreateRequest,
    request: Request,
) -> CustomerCreateResult:
    _local_only(request)
    try:
        result = request.app.state.runtime.customer_intake.create_customer(
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            conversation_id=payload.conversation_id,
            name=payload.name,
            source=payload.source,
            phone=payload.phone,
            level=payload.level,
            current_need=payload.current_need,
            price_type=payload.price_type,
            price_amount=payload.price_amount,
            next_action=payload.next_action,
            notes=payload.notes,
        )
    except RevisionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ledger_revision_conflict",
                "message": "经营数据已在其他页面更新，请刷新后重新确认客户",
                "revision": exc.revision,
            },
        ) from None
    except CustomerIntakeError as exc:
        _error(exc)
    return CustomerCreateResult(**result)
