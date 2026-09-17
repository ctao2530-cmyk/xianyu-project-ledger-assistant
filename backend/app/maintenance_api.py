"""Read-only local readiness; no provider checks, credentials or business records."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from .customer_workflow_access import local_operator_workflow

maintenance_router=APIRouter(prefix='/api/maintenance',dependencies=[Depends(local_operator_workflow)])

@maintenance_router.get('/readiness')
def readiness(request: Request):
    runtime=request.app.state.runtime
    try:
        with runtime.database.engine.connect() as connection:
            connection.execute(text('SELECT 1')).scalar_one()
            revision=connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one_or_none()
        return {'status':'ready','database':'readable','schema_revision':revision,'external_services':'not_checked'}
    except Exception:
        return JSONResponse(status_code=503,content={'status':'not_ready','database':'unavailable','external_services':'not_checked'})

@maintenance_router.get('/analysis-usage')
def analysis_usage(request: Request):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, func
    from .models import CustomerAnalysisRun, CustomerAnalysisArtifact
    now=datetime.now(timezone(timedelta(hours=8)))
    start=now.replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
    runtime=request.app.state.runtime
    with runtime.database.session() as s:
        attempts=s.scalar(select(func.count()).select_from(CustomerAnalysisRun).where(CustomerAnalysisRun.created_at>=start,CustomerAnalysisRun.created_at<start+timedelta(days=1))) or 0
        fields=s.execute(select(
            func.count(),func.count(func.json_extract(CustomerAnalysisArtifact.diff_json,'$.provider_usage.total_tokens')),
            func.sum(func.json_extract(CustomerAnalysisArtifact.diff_json,'$.provider_usage.total_tokens'))
        ).where(CustomerAnalysisArtifact.created_at>=start,CustomerAnalysisArtifact.created_at<start+timedelta(days=1))).one()
    limit=request.app.state.runtime.settings.customer_analysis_daily_run_limit
    return {'date':now.date().isoformat(),'attempts':attempts,'daily_limit':limit,'admission_paused':attempts>=limit,
            'completed_artifacts':fields[0],'artifacts_with_usage':fields[1],'reported_tokens':fields[2],
            'scope':'OpenAI持续客户分析；仅统计已保存产物的提供方用量，失败或未知请求可能另有费用'}
