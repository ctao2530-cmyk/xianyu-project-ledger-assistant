from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from .prediction.calibration_repository import CalibrationRepositoryError
from .prediction.calibration_schemas import (
    CalibrationDecisionRequest,
    CalibrationQuoteAssistView,
    CalibrationRunRequest,
    CalibrationSummaryView,
)
from .prediction.repository import (
    PredictionEvaluationConflict,
    PredictionRepositoryError,
    PredictionResultNotFound,
)
from .prediction.schemas import (
    PredictionEvaluationRequest,
    PredictionLatestView,
    PredictionResult,
    PredictionRunRequest,
    PredictionRunView,
)


prediction_router = APIRouter(prefix="/api/predictions", tags=["predictions"])
VALID_TARGETS = {
    "workload_14d",
    "project_delay_risk",
    "cashflow_30d",
    "customer_followup_priority",
}


def _prediction_error(exc: PredictionRepositoryError) -> HTTPException:
    if isinstance(exc, PredictionResultNotFound):
        return HTTPException(status_code=404, detail=exc.safe_message)
    if isinstance(exc, PredictionEvaluationConflict):
        return HTTPException(
            status_code=409,
            detail={"code": "prediction_evaluation_conflict", "message": exc.safe_message},
        )
    return HTTPException(status_code=503, detail=exc.safe_message)


def _calibration_error(exc: CalibrationRepositoryError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.safe_message},
    )


@prediction_router.get("", response_model=PredictionLatestView)
async def prediction_latest(request: Request) -> PredictionLatestView:
    try:
        return request.app.state.runtime.predictions.latest_summary()
    except PredictionRepositoryError as exc:
        raise _prediction_error(exc) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="预测数据暂时无法读取") from exc


@prediction_router.post(
    "/runs",
    response_model=PredictionRunView,
    status_code=status.HTTP_201_CREATED,
)
async def create_prediction_run(
    payload: PredictionRunRequest,
    request: Request,
) -> PredictionRunView:
    try:
        return request.app.state.runtime.predictions.run(request_id=payload.request_id)
    except PredictionRepositoryError as exc:
        raise _prediction_error(exc) from exc


@prediction_router.get(
    "/calibration",
    response_model=CalibrationSummaryView,
)
async def estimate_calibration_summary(request: Request) -> CalibrationSummaryView:
    try:
        return request.app.state.runtime.estimate_calibration.summary()
    except CalibrationRepositoryError as exc:
        raise _calibration_error(exc) from exc


@prediction_router.post(
    "/calibration/runs",
    response_model=CalibrationSummaryView,
    status_code=status.HTTP_201_CREATED,
)
async def create_estimate_calibration_run(
    payload: CalibrationRunRequest,
    request: Request,
) -> CalibrationSummaryView:
    try:
        return request.app.state.runtime.estimate_calibration.run(
            request_id=payload.request_id,
            cutoff_at=payload.cutoff_at,
        )
    except CalibrationRepositoryError as exc:
        raise _calibration_error(exc) from exc


@prediction_router.get(
    "/calibration/projects/{project_id}",
    response_model=CalibrationQuoteAssistView,
)
async def estimate_calibration_project(
    project_id: str,
    request: Request,
) -> CalibrationQuoteAssistView:
    try:
        return request.app.state.runtime.estimate_calibration.quote_assist(project_id)
    except CalibrationRepositoryError as exc:
        raise _calibration_error(exc) from exc


@prediction_router.post(
    "/calibration/projects/{project_id}/suggestions/{suggestion_id}/decisions",
    response_model=CalibrationQuoteAssistView,
)
async def decide_estimate_calibration_suggestion(
    project_id: str,
    suggestion_id: str,
    payload: CalibrationDecisionRequest,
    request: Request,
) -> CalibrationQuoteAssistView:
    try:
        return request.app.state.runtime.estimate_calibration.decide(
            project_id,
            suggestion_id,
            payload,
        )
    except CalibrationRepositoryError as exc:
        raise _calibration_error(exc) from exc


@prediction_router.get("/targets/{target}", response_model=list[PredictionResult])
async def prediction_target(target: str, request: Request) -> list[PredictionResult]:
    if target not in VALID_TARGETS:
        raise HTTPException(status_code=404, detail="预测类型不存在")
    try:
        return request.app.state.runtime.predictions.target(target)
    except PredictionRepositoryError as exc:
        raise _prediction_error(exc) from exc


@prediction_router.get("/projects/{project_id}", response_model=PredictionResult)
async def project_prediction(project_id: str, request: Request) -> PredictionResult:
    try:
        result = request.app.state.runtime.predictions.project(project_id)
    except PredictionRepositoryError as exc:
        raise _prediction_error(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="项目预测不存在")
    return result


@prediction_router.get("/customers/{customer_id}", response_model=PredictionResult)
async def customer_prediction(customer_id: str, request: Request) -> PredictionResult:
    try:
        result = request.app.state.runtime.predictions.customer(customer_id)
    except PredictionRepositoryError as exc:
        raise _prediction_error(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="客户优先级预测不存在")
    return result


@prediction_router.post(
    "/results/{result_id}/evaluations",
    response_model=PredictionResult,
)
async def evaluate_prediction(
    result_id: str,
    payload: PredictionEvaluationRequest,
    request: Request,
) -> PredictionResult:
    try:
        return request.app.state.runtime.predictions.evaluate(
            result_id,
            request_id=payload.request_id,
            actual_value=payload.actual_value,
            evaluation_method=payload.evaluation_method,
            evaluated_at=payload.evaluated_at,
            note=payload.note,
        )
    except PredictionRepositoryError as exc:
        raise _prediction_error(exc) from exc
