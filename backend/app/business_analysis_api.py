from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.exc import SQLAlchemyError

from .ai.base import AIProviderError

from .business_analysis_repository import (
    BusinessAnalysisDataError,
    BusinessAnalysisNotFound,
    BusinessAnalysisRepositoryError,
    RecommendationNotFound,
    RecommendationRequestConflict,
    RecommendationTransitionError,
    RecommendationVersionConflict,
)
from .business_analysis_schemas import (
    BusinessAnalysisHistoryResponse,
    BusinessAnalysisOverview,
    BusinessAnalysisRecommendation,
    BusinessAnalysisRecommendationUpdate,
    BusinessAnalysisRunRequest,
)
from .services.business_analysis import BusinessAnalysisProviderSelectionError


business_analysis_router = APIRouter(
    prefix="/api/business-analysis",
    tags=["business-analysis"],
)


def _repository_http_error(exc: BusinessAnalysisRepositoryError) -> HTTPException:
    if isinstance(exc, (BusinessAnalysisNotFound, RecommendationNotFound)):
        return HTTPException(status_code=404, detail=exc.safe_message)
    if isinstance(exc, RecommendationVersionConflict):
        return HTTPException(
            status_code=409,
            detail={
                "code": "recommendation_version_conflict",
                "message": exc.safe_message,
                "current_version": exc.current_version,
            },
        )
    if isinstance(exc, RecommendationRequestConflict):
        return HTTPException(
            status_code=409,
            detail={
                "code": "recommendation_request_conflict",
                "message": exc.safe_message,
            },
        )
    if isinstance(exc, RecommendationTransitionError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "recommendation_transition_invalid",
                "message": exc.safe_message,
            },
        )
    if isinstance(exc, BusinessAnalysisDataError):
        return HTTPException(status_code=500, detail=exc.safe_message)
    return HTTPException(status_code=503, detail=exc.safe_message)


@business_analysis_router.get("", response_model=BusinessAnalysisOverview)
async def business_analysis_latest(request: Request) -> BusinessAnalysisOverview:
    try:
        return request.app.state.runtime.business_analysis.latest_or_overview()
    except BusinessAnalysisRepositoryError as exc:
        raise _repository_http_error(exc) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="经营数据暂时无法读取",
        ) from exc


@business_analysis_router.get("/overview", response_model=BusinessAnalysisOverview)
async def business_analysis_overview(request: Request) -> BusinessAnalysisOverview:
    try:
        return request.app.state.runtime.business_analysis.overview()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="经营数据暂时无法读取",
        ) from exc


@business_analysis_router.post(
    "/runs",
    response_model=BusinessAnalysisOverview,
    status_code=status.HTTP_201_CREATED,
)
async def create_business_analysis_run(
    request: Request,
    payload: BusinessAnalysisRunRequest,
) -> BusinessAnalysisOverview:
    try:
        return await request.app.state.runtime.business_analysis.run_analysis(
            request_id=payload.request_id,
            provider=payload.provider,
            model=payload.model,
            reasoning_effort=payload.reasoning_effort,
        )
    except BusinessAnalysisProviderSelectionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from None
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=exc.safe_message) from None
    except BusinessAnalysisRepositoryError as exc:
        raise _repository_http_error(exc) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="经营数据暂时无法读取",
        ) from exc


@business_analysis_router.get(
    "/history",
    response_model=BusinessAnalysisHistoryResponse,
)
async def business_analysis_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> BusinessAnalysisHistoryResponse:
    try:
        return request.app.state.runtime.business_analysis.history(
            limit=limit,
            offset=offset,
        )
    except BusinessAnalysisRepositoryError as exc:
        raise _repository_http_error(exc) from exc


@business_analysis_router.get(
    "/history/{analysis_id}",
    response_model=BusinessAnalysisOverview,
)
async def business_analysis_history_detail(
    request: Request,
    analysis_id: str,
) -> BusinessAnalysisOverview:
    try:
        return request.app.state.runtime.business_analysis.history_detail(analysis_id)
    except BusinessAnalysisRepositoryError as exc:
        raise _repository_http_error(exc) from exc


@business_analysis_router.patch(
    "/recommendations/{recommendation_id}",
    response_model=BusinessAnalysisRecommendation,
)
async def update_business_analysis_recommendation(
    request: Request,
    recommendation_id: str,
    payload: BusinessAnalysisRecommendationUpdate,
) -> BusinessAnalysisRecommendation:
    try:
        return request.app.state.runtime.business_analysis.update_recommendation(
            recommendation_id,
            status=payload.status,
            expected_version=payload.expected_version,
            request_id=payload.request_id,
            note=payload.note,
        )
    except BusinessAnalysisRepositoryError as exc:
        raise _repository_http_error(exc) from exc
