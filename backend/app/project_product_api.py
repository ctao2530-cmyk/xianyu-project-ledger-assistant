from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from .ledger import RevisionConflict
from .project_product_schemas import (
    ProjectProductCommitRequest,
    ProjectProductCommitResult,
    ProjectProductPreview,
    ProjectProductPreviewRequest,
)
from .services.project_product_attribution import ProjectProductAttributionError


project_product_router = APIRouter(
    prefix="/api/ledger/project-products",
    tags=["project-product-attribution"],
)


def _service(request: Request):
    return request.app.state.runtime.project_product_attribution


def _attribution_error(exc: ProjectProductAttributionError) -> HTTPException:
    if exc.code == "project_not_found":
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        "request_id_reused",
        "request_record_invalid",
        "preview_expired",
    }:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": str(exc)},
    )


@project_product_router.post("/preview", response_model=ProjectProductPreview)
async def preview_project_product(
    payload: ProjectProductPreviewRequest,
    request: Request,
) -> ProjectProductPreview:
    try:
        result = _service(request).preview(
            expected_revision=payload.expected_revision,
            project_id=payload.project_id,
            target_item_external_id=payload.target_item_external_id,
        )
    except RevisionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ledger_revision_conflict",
                "message": "经营数据已经变化，请刷新后重新预览利润归属",
                "revision": exc.revision,
            },
        ) from None
    except ProjectProductAttributionError as exc:
        raise _attribution_error(exc) from None
    return ProjectProductPreview(**result)


@project_product_router.post("/commit", response_model=ProjectProductCommitResult)
async def commit_project_product(
    payload: ProjectProductCommitRequest,
    request: Request,
) -> ProjectProductCommitResult:
    try:
        result = _service(request).commit(
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            preview_token=payload.preview_token,
            project_id=payload.project_id,
            target_item_external_id=payload.target_item_external_id,
        )
    except RevisionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ledger_revision_conflict",
                "message": "经营数据已经变化，本次利润归属没有修改，请重新预览",
                "revision": exc.revision,
            },
        ) from None
    except ProjectProductAttributionError as exc:
        raise _attribution_error(exc) from None
    request.app.state.runtime.event_hub.publish_nowait(
        {
            "type": "ledger_updated",
            "revision": result["revision"],
            "source": "project_product_attribution",
            "project_id": result["project_id"],
            "item_external_id": result["target_item_external_id"],
        }
    )
    return ProjectProductCommitResult(**result)
