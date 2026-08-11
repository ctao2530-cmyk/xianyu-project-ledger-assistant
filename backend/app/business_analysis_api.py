from __future__ import annotations

from fastapi import APIRouter, Request

from .business_analysis_schemas import BusinessAnalysisOverview


business_analysis_router = APIRouter(
    prefix="/api/business-analysis",
    tags=["business-analysis"],
)


@business_analysis_router.get("/overview", response_model=BusinessAnalysisOverview)
async def business_analysis_overview(request: Request) -> BusinessAnalysisOverview:
    return request.app.state.runtime.business_analysis.overview()
