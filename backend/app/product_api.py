from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .product_schemas import (
    ProductActionCreateRequest,
    ProductActionView,
    ProductCollectionRunView,
    ProductIntelligenceView,
    ProductMonitorUpdateRequest,
    ProductRecommendationUpdateRequest,
    ProductRegisterRequest,
    ProductView,
)
from .services.product_intelligence import (
    ProductAlreadyCollected,
    ProductCollectionUnavailable,
    ProductOwnershipRestricted,
    ProductRecordNotFound,
    ProductReferenceInvalid,
)


product_router = APIRouter(prefix="/api/products", tags=["product-intelligence"])


def service_from(request: Request):
    return request.app.state.runtime.product_intelligence


@product_router.get("/intelligence", response_model=ProductIntelligenceView)
async def product_intelligence(request: Request) -> ProductIntelligenceView:
    return service_from(request).overview()


@product_router.post("/collect", response_model=ProductCollectionRunView)
async def collect_products(request: Request) -> ProductCollectionRunView:
    try:
        return await service_from(request).collect_today(trigger="manual")
    except ProductCollectionUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ProductAlreadyCollected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post("/register", response_model=ProductView)
async def register_product(
    payload: ProductRegisterRequest,
    request: Request,
) -> ProductView:
    try:
        return service_from(request).register(payload.item_reference)
    except ProductReferenceInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@product_router.put("/{external_id}/monitor", response_model=ProductView)
async def update_product_monitor(
    external_id: str,
    payload: ProductMonitorUpdateRequest,
    request: Request,
) -> ProductView:
    try:
        return service_from(request).update_monitor(external_id, payload.enabled)
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductOwnershipRestricted as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post("/{external_id}/actions", response_model=ProductActionView)
async def record_product_action(
    external_id: str,
    payload: ProductActionCreateRequest,
    request: Request,
) -> ProductActionView:
    try:
        return service_from(request).create_action(
            external_id,
            action_type=payload.action_type,
            status=payload.status,
            note=payload.note,
            cost=payload.cost,
            recommendation_id=payload.recommendation_id,
            observation_days=payload.observation_days,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@product_router.put("/recommendations/{recommendation_id}", status_code=204)
async def update_product_recommendation(
    recommendation_id: str,
    payload: ProductRecommendationUpdateRequest,
    request: Request,
) -> None:
    try:
        service_from(request).update_recommendation(
            recommendation_id,
            payload.status,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
