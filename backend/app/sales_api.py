from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from .agents import SalesAgentError
from .agents.sales_agent import SalesAnalysisRecord
from .ledger_schemas import LeadView
from .models import CustomerMemory, SalesAnalysisRun, SalesLead


sales_router = APIRouter(prefix="/api", tags=["sales-agent"])


class SalesMemoryItemView(BaseModel):
    id: str
    customer_id: str | None
    conversation_id: int
    source_analysis_id: str | None
    customer_background: str
    requirements: list[str]
    communication_summary: str
    latest_analysis: dict[str, Any]
    follow_up_status: str
    version: int
    created_at: str
    updated_at: str


class SalesMemoryView(BaseModel):
    customer_id: str | None
    memories: list[SalesMemoryItemView]
    memory_count: int
    latest_version: int


class SalesConfirmationRequest(BaseModel):
    confirmed: Literal[True]
    analysis_run_id: str = Field(min_length=1, max_length=128)


class SalesConfirmationView(BaseModel):
    analysis: SalesAnalysisRecord
    lead: LeadView
    memory: SalesMemoryItemView
    revision: int
    idempotent: bool


def runtime_from(request: Request):
    return request.app.state.runtime


def _raise_sales_error(exc: SalesAgentError) -> None:
    if exc.code in {
        "conversation_not_found",
        "message_not_found",
        "analysis_not_found",
    }:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {"analysis_not_ready", "revision_conflict"}:
        code = status.HTTP_409_CONFLICT
    elif exc.code in {
        "sales_analysis_failed",
        "invalid_evidence_refs",
        "deepseek_not_configured",
        "deepseek_timeout",
        "codex_timeout",
    } or "timeout" in exc.code or exc.code.startswith(("deepseek_", "codex_")):
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(status_code=code, detail=exc.safe_message) from None


def _lead_view(lead: SalesLead) -> LeadView:
    return LeadView(
        id=lead.id,
        conversation_id=lead.conversation_id,
        customer_id=lead.customer_id,
        status=lead.status,
        requirement_version_id=lead.requirement_version_id,
        latest_quote_id=lead.latest_quote_id,
        converted_project_id=lead.converted_project_id,
    )


@sales_router.get(
    "/conversations/{conversation_id}/sales/analysis",
    response_model=SalesAnalysisRecord | None,
)
async def latest_sales_analysis(
    conversation_id: int,
    request: Request,
) -> SalesAnalysisRecord | None:
    return runtime_from(request).sales_agent.latest(conversation_id)


@sales_router.get(
    "/conversations/{conversation_id}/sales/history",
    response_model=list[SalesAnalysisRecord],
)
async def sales_analysis_history(
    conversation_id: int,
    request: Request,
    limit: int = Query(default=10, ge=1, le=30),
) -> list[SalesAnalysisRecord]:
    return runtime_from(request).sales_agent.history(conversation_id, limit=limit)


@sales_router.get(
    "/conversations/{conversation_id}/sales/memory",
    response_model=SalesMemoryView,
)
async def customer_sales_memory(
    conversation_id: int,
    request: Request,
) -> SalesMemoryView:
    try:
        memory = runtime_from(request).sales_agent.memory(conversation_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="会话不存在") from None
    return SalesMemoryView.model_validate(memory)


@sales_router.post(
    "/conversations/{conversation_id}/sales/analyze",
    response_model=SalesAnalysisRecord,
)
async def analyze_sales_conversation(
    conversation_id: int,
    request: Request,
    refresh: bool = Query(default=False),
    provider: Literal["deepseek", "codex_cli"] | None = Query(default=None),
) -> SalesAnalysisRecord:
    runtime = runtime_from(request)
    if not runtime.settings.sales_agent_enabled:
        raise HTTPException(status_code=409, detail="Sales Agent 已在本机配置中关闭")
    try:
        return await runtime.sales_agent.analyze_conversation(
            conversation_id,
            refresh=refresh,
            provider_name=provider,
        )
    except SalesAgentError as exc:
        _raise_sales_error(exc)


@sales_router.post(
    "/conversations/{conversation_id}/sales/confirm",
    response_model=SalesConfirmationView,
)
async def confirm_sales_analysis(
    conversation_id: int,
    payload: SalesConfirmationRequest,
    request: Request,
) -> SalesConfirmationView:
    runtime = runtime_from(request)
    with runtime.database.session() as session:
        run = session.get(SalesAnalysisRun, payload.analysis_run_id)
        if run is None or run.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="销售分析记录不存在")
    try:
        result = runtime.sales_agent.confirm_analysis(payload.analysis_run_id)
    except SalesAgentError as exc:
        _raise_sales_error(exc)
    with runtime.database.session() as session:
        run = session.get(SalesAnalysisRun, result.analysis_id)
        lead = session.get(SalesLead, result.lead_id)
        memory = session.get(CustomerMemory, result.memory_id)
        if run is None or lead is None or memory is None:
            raise HTTPException(status_code=500, detail="销售确认结果读取失败")
        analysis_view = runtime.sales_agent.record_from_run(run)
        memory_view = SalesMemoryItemView.model_validate(
            runtime.sales_agent.memory_store.to_dict(memory)
        )
        return SalesConfirmationView(
            analysis=analysis_view,
            lead=_lead_view(lead),
            memory=memory_view,
            revision=result.revision,
            idempotent=result.idempotent,
        )
