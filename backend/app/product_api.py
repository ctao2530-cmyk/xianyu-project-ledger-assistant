from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from .adapters.base import AdapterAccessVerificationError, LoginExpiredError
from .product_schemas import (
    ProductActionCreateRequest,
    ProductActionView,
    ProductCollectionRunView,
    ProductIntelligenceView,
    ProductLaunchPlanCreateRequest,
    ProductLaunchPlanUpdateRequest,
    ProductLaunchPlanView,
    ProductManualCollectionRequest,
    ProductMarketImportRequest,
    ProductMarketKeywordUpdateRequest,
    ProductMarketReferenceView,
    ProductMarketReminderSnoozeRequest,
    ProductModificationExperimentCreateRequest,
    ProductModificationExperimentUpdateRequest,
    ProductModificationExperimentView,
    ProductMonitorBatchDisableRequest,
    ProductMonitorBatchDisableView,
    ProductMonitorUpdateRequest,
    ProductOperatingPlanView,
    ProductPlanSlotUpdateRequest,
    ProductRecommendationUpdateRequest,
    ProductReferenceResolveRequest,
    ProductRegistrationCommitRequest,
    ProductRegistrationCommitView,
    ProductRegistrationPreviewView,
    ProductTrafficBatchCompleteRequest,
    ProductTrafficBatchCreateRequest,
    ProductTrafficBatchRecordRequest,
    ProductTrafficBaselineRequest,
    ProductTrafficBatchPageView,
    ProductTrafficReplanPreviewView,
    ProductTrafficReplanRequest,
    ProductTrafficStartPreviewView,
    ProductTrafficStartRequest,
    ProductTrafficActualStartRequest,
    ProductTrafficBatchView,
    ProductTrafficCheckpointCreateRequest,
    ProductTrafficCheckpointRetryRequest,
    ProductTrafficCollectionModeRequest,
    ProductView,
)
from .services.product_intelligence import (
    ProductAlreadyCollected,
    ProductCollectionUnavailable,
    ProductMarketConflict,
    ProductOwnershipRestricted,
    ProductRecordNotFound,
    ProductReferenceInvalid,
    ProductTrafficConflict,
)


product_router = APIRouter(prefix="/api/products", tags=["product-intelligence"])


def service_from(request: Request):
    return request.app.state.runtime.product_intelligence


def require_local_desktop(request: Request) -> None:
    client = request.client.host if request.client else ""
    if (
        client not in {"127.0.0.1", "::1", "localhost", "testclient"}
        or request.headers.get("x-yuda-desktop") != "1"
    ):
        raise HTTPException(status_code=403, detail="仅允许本机桌面助手控制")


@product_router.get("/intelligence", response_model=ProductIntelligenceView)
async def product_intelligence(request: Request) -> ProductIntelligenceView:
    return service_from(request).overview()


@product_router.get("/market-reference", response_model=ProductMarketReferenceView)
async def market_reference(request: Request) -> ProductMarketReferenceView:
    return service_from(request).market_reference()


@product_router.put(
    "/market-reference/keyword", response_model=ProductMarketReferenceView
)
async def update_market_keyword(
    payload: ProductMarketKeywordUpdateRequest,
    request: Request,
) -> ProductMarketReferenceView:
    try:
        return service_from(request).update_market_keyword(
            mode=payload.mode,
            keyword=payload.keyword,
            save_as_common=payload.save_as_common,
        )
    except ProductMarketConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/market-reference/import", response_model=ProductMarketReferenceView
)
async def import_market_reference(
    payload: ProductMarketImportRequest,
    request: Request,
) -> ProductMarketReferenceView:
    try:
        return service_from(request).import_market_reference(
            keyword=payload.keyword,
            captured_at=payload.captured_at,
            results=[result.model_dump() for result in payload.results],
            note=payload.note,
        )
    except ProductMarketConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/market-reference/reminder/snooze", response_model=ProductMarketReferenceView
)
async def snooze_market_reminder(
    payload: ProductMarketReminderSnoozeRequest,
    request: Request,
) -> ProductMarketReferenceView:
    try:
        return service_from(request).snooze_market_reminder(payload.hours)
    except ProductMarketConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/market-reference/reminder/skip", response_model=ProductMarketReferenceView
)
async def skip_market_reminder(request: Request) -> ProductMarketReferenceView:
    return service_from(request).skip_market_reminder()


@product_router.post("/launch-plans", response_model=ProductLaunchPlanView)
async def create_launch_plan(
    payload: ProductLaunchPlanCreateRequest,
    request: Request,
) -> ProductLaunchPlanView:
    try:
        return service_from(request).create_launch_plan(
            keyword=payload.keyword, title=payload.title
        )
    except ProductMarketConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.put("/launch-plans/{plan_id}", response_model=ProductLaunchPlanView)
async def update_launch_plan(
    plan_id: str,
    payload: ProductLaunchPlanUpdateRequest,
    request: Request,
) -> ProductLaunchPlanView:
    try:
        return service_from(request).update_launch_plan(plan_id, payload.status)
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@product_router.post(
    "/{external_id}/modification-experiments",
    response_model=ProductModificationExperimentView,
)
async def create_modification_experiment(
    external_id: str,
    payload: ProductModificationExperimentCreateRequest,
    request: Request,
) -> ProductModificationExperimentView:
    try:
        return service_from(request).create_modification_experiment(
            external_id,
            variable=payload.variable,
            before_value=payload.before_value,
            after_value=payload.after_value,
            observation_days=payload.observation_days,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (ProductMarketConflict, ProductOwnershipRestricted) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.put(
    "/modification-experiments/{experiment_id}",
    response_model=ProductModificationExperimentView,
)
async def update_modification_experiment(
    experiment_id: str,
    payload: ProductModificationExperimentUpdateRequest,
    request: Request,
) -> ProductModificationExperimentView:
    try:
        return service_from(request).update_modification_experiment(
            experiment_id, decision=payload.decision, note=payload.note
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductMarketConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post("/collect", response_model=ProductCollectionRunView)
async def collect_products(request: Request) -> ProductCollectionRunView:
    try:
        return await service_from(request).collect_today(trigger="manual")
    except ProductCollectionUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ProductAlreadyCollected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post("/collect/manual", response_model=ProductCollectionRunView)
async def collect_products_manually(
    payload: ProductManualCollectionRequest,
    request: Request,
) -> ProductCollectionRunView:
    try:
        return await service_from(request).collect_manual(payload.external_id)
    except ProductCollectionUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ProductOwnershipRestricted as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductReferenceInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@product_router.post("/traffic-batches", response_model=ProductTrafficBatchView)
async def create_traffic_batch(
    payload: ProductTrafficBatchCreateRequest,
    request: Request,
) -> ProductTrafficBatchView:
    try:
        return service_from(request).create_traffic_batch(
            request_id=payload.request_id,
            item_external_ids=payload.item_external_ids,
            planned_at=payload.planned_at,
            actual_cost=payload.actual_cost,
            plan_slot_id=payload.plan_slot_id,
            note=payload.note,
            checkpoint_collection_mode=payload.checkpoint_collection_mode,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (ProductTrafficConflict, ProductOwnershipRestricted) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/traffic-batches/recorded",
    response_model=ProductTrafficBatchView,
)
async def record_traffic_batch_now(
    payload: ProductTrafficBatchRecordRequest,
    request: Request,
) -> ProductTrafficBatchView:
    """Atomically record a purchase using the server confirmation minute."""

    try:
        return await service_from(request).record_traffic_batch_now(
            request_id=payload.request_id,
            item_external_ids=payload.item_external_ids,
            actual_cost=payload.actual_cost,
            plan_slot_id=payload.plan_slot_id,
            note=payload.note,
            confirmed_already_purchased=payload.confirmed_already_purchased,
            checkpoint_collection_mode=payload.checkpoint_collection_mode,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (
        ProductCollectionUnavailable,
        ProductTrafficConflict,
        ProductOwnershipRestricted,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.get("/traffic-batches", response_model=ProductTrafficBatchPageView)
async def list_traffic_batches(
    request: Request,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, max_length=32),
) -> ProductTrafficBatchPageView:
    try:
        return service_from(request).traffic_batches(
            cursor=cursor,
            limit=limit,
            status=status,
        )
    except ProductTrafficConflict as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@product_router.get(
    "/traffic-batches/{batch_id}/replan-preview",
    response_model=ProductTrafficReplanPreviewView,
)
async def traffic_batch_replan_preview(
    batch_id: str, request: Request
) -> ProductTrafficReplanPreviewView:
    try:
        return service_from(request).traffic_replan_preview(batch_id)
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductTrafficConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/traffic-batches/{batch_id}/replan",
    response_model=ProductTrafficBatchView,
)
async def replan_traffic_batch(
    batch_id: str,
    payload: ProductTrafficReplanRequest,
    request: Request,
) -> ProductTrafficBatchView:
    try:
        return service_from(request).replan_traffic_batch(
            batch_id,
            request_id=payload.request_id,
            expected_updated_at=payload.expected_updated_at,
            preview_hash=payload.preview_hash,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (ProductTrafficConflict, ProductOwnershipRestricted) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.get(
    "/traffic-batches/{batch_id}/start-preview",
    response_model=ProductTrafficStartPreviewView,
)
async def traffic_batch_start_preview(
    batch_id: str, request: Request
) -> ProductTrafficStartPreviewView:
    try:
        return service_from(request).traffic_start_preview(batch_id)
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@product_router.post(
    "/traffic-batches/{batch_id}/baseline",
    response_model=ProductTrafficBatchView,
)
async def prepare_traffic_batch_baseline(
    batch_id: str,
    payload: ProductTrafficBaselineRequest,
    request: Request,
) -> ProductTrafficBatchView:
    try:
        return await service_from(request).prepare_traffic_baseline(
            batch_id,
            request_id=payload.request_id,
            expected_updated_at=payload.expected_updated_at,
            mode=payload.mode,
            items=[item.model_dump() for item in payload.items],
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductCollectionUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (ProductTrafficConflict, ProductOwnershipRestricted) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/traffic-batches/{batch_id}/start",
    response_model=ProductTrafficBatchView,
)
async def start_traffic_batch(
    batch_id: str,
    payload: ProductTrafficStartRequest,
    request: Request,
) -> ProductTrafficBatchView:
    try:
        return service_from(request).start_traffic_batch(
            batch_id,
            request_id=payload.request_id,
            expected_updated_at=payload.expected_updated_at,
            expected_baseline_captured_at=payload.expected_baseline_captured_at,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (ProductTrafficConflict, ProductOwnershipRestricted) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/traffic-batches/{batch_id}/actual-start",
    response_model=ProductTrafficBatchView,
)
async def record_actual_overlap_start(
    batch_id: str,
    payload: ProductTrafficActualStartRequest,
    request: Request,
) -> ProductTrafficBatchView:
    try:
        return service_from(request).record_actual_overlap_start(
            batch_id,
            request_id=payload.request_id,
            expected_updated_at=payload.expected_updated_at,
            actual_started_at=payload.actual_started_at,
            confirmed_already_purchased=payload.confirmed_already_purchased,
            items=[item.model_dump() for item in payload.items],
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (ProductTrafficConflict, ProductOwnershipRestricted) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/traffic-batches/{batch_id}/complete",
    response_model=ProductTrafficBatchView,
)
async def complete_traffic_batch(
    batch_id: str,
    payload: ProductTrafficBatchCompleteRequest,
    request: Request,
) -> ProductTrafficBatchView:
    try:
        return service_from(request).complete_traffic_batch(
            batch_id,
            completed_at=payload.completed_at,
            actual_cost=payload.actual_cost,
            total_exposure=payload.total_exposure,
            note=payload.note,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductTrafficConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/traffic-batches/{batch_id}/checkpoints",
    response_model=ProductTrafficBatchView,
)
async def record_traffic_checkpoint(
    batch_id: str,
    payload: ProductTrafficCheckpointCreateRequest,
    request: Request,
) -> ProductTrafficBatchView:
    try:
        return service_from(request).record_traffic_checkpoint(
            batch_id,
            checkpoint=payload.checkpoint,
            recorded_at=payload.recorded_at,
            items=[item.model_dump() for item in payload.items],
            note=payload.note,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductTrafficConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.put(
    "/traffic-batches/{batch_id}/checkpoint-collection-mode",
    response_model=ProductTrafficBatchView,
)
async def update_traffic_checkpoint_collection_mode(
    batch_id: str,
    payload: ProductTrafficCollectionModeRequest,
    request: Request,
) -> ProductTrafficBatchView:
    try:
        return service_from(request).update_traffic_checkpoint_collection_mode(
            batch_id,
            request_id=payload.request_id,
            expected_updated_at=payload.expected_updated_at,
            mode=payload.mode,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductTrafficConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/traffic-batches/{batch_id}/checkpoints/{checkpoint}/retry",
    response_model=ProductTrafficBatchView,
)
async def retry_traffic_checkpoint_collection(
    batch_id: str,
    checkpoint: str,
    payload: ProductTrafficCheckpointRetryRequest,
    request: Request,
) -> ProductTrafficBatchView:
    try:
        return await service_from(request).retry_traffic_checkpoint_collection(
            batch_id,
            checkpoint,
            request_id=payload.request_id,
            expected_updated_at=payload.expected_updated_at,
        )
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (ProductTrafficConflict, ProductOwnershipRestricted) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/traffic-batches/{batch_id}/cancel",
    response_model=ProductTrafficBatchView,
)
async def cancel_traffic_batch(batch_id: str, request: Request) -> ProductTrafficBatchView:
    try:
        return service_from(request).cancel_traffic_batch(batch_id)
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductTrafficConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.post(
    "/operating-plan/refresh",
    response_model=ProductOperatingPlanView,
)
async def refresh_operating_plan(request: Request) -> ProductOperatingPlanView:
    return service_from(request).refresh_operating_plan()


@product_router.put(
    "/operating-plan/slots/{slot_id}",
    response_model=ProductOperatingPlanView,
)
async def update_operating_plan_slot(
    slot_id: str,
    payload: ProductPlanSlotUpdateRequest,
    request: Request,
) -> ProductOperatingPlanView:
    try:
        return service_from(request).update_plan_slot_lock(slot_id, payload.locked)
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductTrafficConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@product_router.get(
    "/owned-listings/discover",
    response_model=ProductRegistrationPreviewView,
)
async def discover_owned_listings(
    request: Request,
) -> ProductRegistrationPreviewView:
    require_local_desktop(request)
    try:
        return await service_from(request).discover_owned_listings()
    except ProductCollectionUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except AdapterAccessVerificationError as exc:
        raise HTTPException(
            status_code=409,
            detail="闲鱼要求人工完成访问验证，请在现有 Ego Lite 登录页处理后再重试",
        ) from None
    except LoginExpiredError as exc:
        raise HTTPException(status_code=409, detail="闲鱼登录已失效，请先恢复连接") from None


@product_router.post(
    "/references/resolve",
    response_model=ProductRegistrationPreviewView,
)
async def resolve_product_reference(
    payload: ProductReferenceResolveRequest,
    request: Request,
) -> ProductRegistrationPreviewView:
    require_local_desktop(request)
    try:
        return await service_from(request).resolve_registration_reference(
            payload.reference
        )
    except ProductReferenceInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ProductCollectionUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except AdapterAccessVerificationError as exc:
        raise HTTPException(
            status_code=409,
            detail="闲鱼要求人工完成访问验证，请在现有 Ego Lite 登录页处理后再重试",
        ) from None
    except LoginExpiredError as exc:
        raise HTTPException(status_code=409, detail="闲鱼登录已失效，请先恢复连接") from None


@product_router.post(
    "/register/batch",
    response_model=ProductRegistrationCommitView,
)
async def register_products_batch(
    payload: ProductRegistrationCommitRequest,
    request: Request,
) -> ProductRegistrationCommitView:
    require_local_desktop(request)
    try:
        return await service_from(request).commit_registration(
            request_id=payload.request_id,
            preview_token=payload.preview_token,
            external_ids=payload.external_ids,
        )
    except ProductReferenceInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ProductCollectionUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except AdapterAccessVerificationError as exc:
        raise HTTPException(
            status_code=409,
            detail="闲鱼要求人工完成访问验证，请在现有 Ego Lite 登录页处理后再重试",
        ) from None
    except LoginExpiredError as exc:
        raise HTTPException(status_code=409, detail="闲鱼登录已失效，请先恢复连接") from None


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


@product_router.post(
    "/monitors/disable-batch",
    response_model=ProductMonitorBatchDisableView,
)
async def disable_product_monitors_batch(
    payload: ProductMonitorBatchDisableRequest,
    request: Request,
) -> ProductMonitorBatchDisableView:
    require_local_desktop(request)
    try:
        return service_from(request).disable_monitors(payload.external_ids)
    except ProductRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


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
