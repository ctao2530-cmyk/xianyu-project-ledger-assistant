from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from .customer_workflow_access import local_operator_workflow
from .ledger import RevisionConflict
from .services.project_acceptance import ProjectAcceptanceService, AcceptanceError

acceptance_router=APIRouter(prefix='/api/projects', dependencies=[Depends(local_operator_workflow)])
class AcceptanceInput(BaseModel):
    model_config=ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: str=Field(min_length=8,max_length=128)
    expected_revision: int=Field(ge=0)
    case_id: str=Field(min_length=1,max_length=128)
    version: int=Field(ge=1)
    decision: Literal['accepted','rejected','resubmitted']
    reviewer: str=Field(min_length=1,max_length=120)
    evidence: str=Field(min_length=5,max_length=4000)
    confirmed: bool=False

def service(request):
    runtime=request.app.state.runtime
    return ProjectAcceptanceService(runtime.database,runtime.ledger)

@acceptance_router.get('/{project_id}/acceptance')
def history(project_id: str, request: Request, offset: int=Query(0,ge=0), limit: int=Query(20,ge=1,le=100)):
    try:return service(request).history(project_id,offset=offset,limit=limit)
    except AcceptanceError as exc:raise HTTPException(404,detail=str(exc)) from None

@acceptance_router.post('/{project_id}/acceptance')
async def record(project_id: str, payload: AcceptanceInput, request: Request):
    try:
        result=service(request).record(project_id,payload.model_dump())
        request.app.state.runtime.event_hub.publish_nowait({'type':'ledger_updated','revision':result['revision'],'source':'customer_acceptance'})
        return result
    except (AcceptanceError,RevisionConflict) as exc:raise HTTPException(409,detail=str(exc)) from None
