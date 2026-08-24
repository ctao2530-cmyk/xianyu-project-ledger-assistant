from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .services.traffic_growth import (
    TrafficGrowthConflict,
    TrafficGrowthNotFound,
)
from .traffic_growth_schemas import (
    TrafficAttributionDecisionRequest,
    TrafficAttributionRefreshRequest,
    TrafficBudgetDecisionApplyRequest,
    TrafficBudgetDecisionRefreshRequest,
    TrafficExperimentAdvanceRequest,
    TrafficExperimentBindBatchRequest,
    TrafficExperimentCreateRequest,
    TrafficExperimentPreviewRequest,
    TrafficExperimentPreviewView,
    TrafficExperimentView,
    TrafficGrowthOverviewView,
    TrafficScaleCohortBindBatchRequest,
    TrafficScaleCohortCreateRequest,
)


traffic_growth_router = APIRouter(
    prefix="/api/products",
    tags=["product-traffic-growth"],
)


def service_from(request: Request):
    return request.app.state.runtime.traffic_growth


def translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TrafficGrowthNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@traffic_growth_router.get(
    "/traffic-growth",
    response_model=TrafficGrowthOverviewView,
)
async def traffic_growth_overview(request: Request) -> TrafficGrowthOverviewView:
    return service_from(request).overview()


@traffic_growth_router.post(
    "/traffic-experiments/preview",
    response_model=TrafficExperimentPreviewView,
)
async def preview_traffic_experiment(
    payload: TrafficExperimentPreviewRequest,
    request: Request,
) -> TrafficExperimentPreviewView:
    try:
        return service_from(request).preview_experiment(**payload.model_dump())
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None


@traffic_growth_router.post(
    "/traffic-experiments",
    response_model=TrafficExperimentView,
)
async def create_traffic_experiment(
    payload: TrafficExperimentCreateRequest,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).create_experiment(**payload.model_dump())
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None


@traffic_growth_router.get(
    "/traffic-experiments/{experiment_id}",
    response_model=TrafficExperimentView,
)
async def get_traffic_experiment(
    experiment_id: str,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).experiment(experiment_id)
    except TrafficGrowthNotFound as exc:
        raise translate_error(exc) from None


@traffic_growth_router.post(
    "/traffic-experiments/{experiment_id}/advance",
    response_model=TrafficExperimentView,
)
async def advance_traffic_experiment(
    experiment_id: str,
    payload: TrafficExperimentAdvanceRequest,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).advance_experiment(
            experiment_id,
            **payload.model_dump(),
        )
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None


@traffic_growth_router.post(
    "/traffic-experiments/{experiment_id}/cells/{cell_id}/bind",
    response_model=TrafficExperimentView,
)
async def bind_traffic_experiment_batch(
    experiment_id: str,
    cell_id: str,
    payload: TrafficExperimentBindBatchRequest,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).bind_experiment_batch(
            experiment_id,
            cell_id,
            **payload.model_dump(),
        )
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None


@traffic_growth_router.post(
    "/traffic-experiments/{experiment_id}/cohorts",
    response_model=TrafficExperimentView,
)
async def create_traffic_scale_cohort(
    experiment_id: str,
    payload: TrafficScaleCohortCreateRequest,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).create_scale_cohort(
            experiment_id,
            **payload.model_dump(),
        )
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None


@traffic_growth_router.post(
    "/traffic-experiments/{experiment_id}/cohorts/{cohort_id}/batches",
    response_model=TrafficExperimentView,
)
async def bind_traffic_scale_batch(
    experiment_id: str,
    cohort_id: str,
    payload: TrafficScaleCohortBindBatchRequest,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).bind_cohort_batch(
            experiment_id,
            cohort_id,
            **payload.model_dump(),
        )
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None


@traffic_growth_router.post(
    "/traffic-experiments/{experiment_id}/attributions/refresh",
    response_model=TrafficExperimentView,
)
async def refresh_traffic_attributions(
    experiment_id: str,
    payload: TrafficAttributionRefreshRequest,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).refresh_attributions(
            experiment_id,
            request_id=payload.request_id,
        )
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None


@traffic_growth_router.post(
    "/traffic-attributions/{attribution_id}/confirm",
    response_model=TrafficExperimentView,
)
async def confirm_traffic_attribution(
    attribution_id: str,
    payload: TrafficAttributionDecisionRequest,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).decide_attribution(
            attribution_id,
            decision="confirm",
            **payload.model_dump(),
        )
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None


@traffic_growth_router.post(
    "/traffic-attributions/{attribution_id}/reject",
    response_model=TrafficExperimentView,
)
async def reject_traffic_attribution(
    attribution_id: str,
    payload: TrafficAttributionDecisionRequest,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).decide_attribution(
            attribution_id,
            decision="reject",
            **payload.model_dump(),
        )
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None


@traffic_growth_router.post(
    "/traffic-experiments/{experiment_id}/budget-decisions/refresh",
    response_model=TrafficExperimentView,
)
async def refresh_traffic_budget_decision(
    experiment_id: str,
    payload: TrafficBudgetDecisionRefreshRequest,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).refresh_budget_decision(
            experiment_id,
            request_id=payload.request_id,
        )
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None


@traffic_growth_router.post(
    "/traffic-budget-decisions/{decision_id}/apply",
    response_model=TrafficExperimentView,
)
async def apply_traffic_budget_decision(
    decision_id: str,
    payload: TrafficBudgetDecisionApplyRequest,
    request: Request,
) -> TrafficExperimentView:
    try:
        return service_from(request).apply_budget_decision(
            decision_id,
            **payload.model_dump(),
        )
    except (TrafficGrowthConflict, TrafficGrowthNotFound) as exc:
        raise translate_error(exc) from None
