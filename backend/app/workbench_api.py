"""Local read model: one bounded query page, no channel/model calls or writes."""
from fastapi import APIRouter, Depends, Query, Request
from .customer_workflow_access import local_operator_workflow
from .services.workbench import WorkbenchQuery

workbench_router = APIRouter(prefix='/api/workbench', dependencies=[Depends(local_operator_workflow)])

@workbench_router.get('/actions')
def actions(request: Request, offset: int = Query(0, ge=0, le=100000), limit: int = Query(100, ge=1, le=200)):
    return WorkbenchQuery(request.app.state.runtime.database).page(offset=offset, limit=limit)
