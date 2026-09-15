from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from .customer_workflow_access import local_customer_workflow
from .services.requirement_proposals import RequirementProposalService
from .services.requirement_exchange import RequirementExchangeError
from .services.customer_context_gateway import CustomerContextGatewayError
from .models import RequirementCase, BusinessProject, LedgerMutationRequest
from .services.project_task_drafts import ProjectTaskDraftService, ProjectTaskDraftError

def local_review(request: Request):
    local_customer_workflow(request)
    from urllib.parse import urlsplit
    origin = request.headers.get('origin')
    if request.headers.get('x-yuda-desktop') != '1' or (origin and urlsplit(origin).netloc != request.url.netloc):
        raise HTTPException(403, detail='正式需求确认仅允许本机同源界面')


requirement_proposal_router = APIRouter(prefix='/api', dependencies=[Depends(local_review)])


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=8, max_length=128)
    review_token: str
    expected_version: int = Field(ge=0)
    confirmed: bool = False


@requirement_proposal_router.get('/customers/{customer_id}/requirement-proposals')
def pending(customer_id: str, request: Request):
    return RequirementProposalService(request.app.state.runtime.database).list_pending(customer_id)


@requirement_proposal_router.post('/requirement-proposals/confirm')
def confirm(payload: Confirmation, request: Request):
    try:
        return RequirementProposalService(request.app.state.runtime.database).confirm(**payload.model_dump())
    except (RequirementExchangeError, CustomerContextGatewayError) as exc:
        raise HTTPException(409, detail={'code': exc.code, 'message': str(exc)}) from None


class CaseLink(BaseModel):
    model_config = ConfigDict(extra='forbid')
    case_id: str
    expected_revision: int
    request_id: str = Field(min_length=8, max_length=128)
    confirmed: bool = False


@requirement_proposal_router.post('/projects/{project_id}/requirement-case')
def link(project_id: str, payload: CaseLink, request: Request):
    if not payload.confirmed:
        raise HTTPException(422, detail='请确认关联正式需求，不会变更客户、商品或项目状态')
    runtime = request.app.state.runtime
    with runtime.database.session() as session:
        session.execute(text('BEGIN IMMEDIATE'))
        hash_value = ProjectTaskDraftService._hash({'project_id': project_id, **payload.model_dump()})
        try:
            repeated = ProjectTaskDraftService._request_result(session, request_id=payload.request_id,
                operation='project_requirement_case_link', payload_hash=hash_value)
        except ProjectTaskDraftError as exc:
            raise HTTPException(409, detail={'code': exc.code, 'message': str(exc)}) from None
        if repeated:
            return repeated
        revision, snapshot = runtime.ledger.get_in_session(session)
        if revision != payload.expected_revision:
            raise HTTPException(409, detail='经营数据已变化，请刷新后关联')
        project = session.get(BusinessProject, project_id)
        case = session.get(RequirementCase, payload.case_id)
        linked = list(session.scalars(select(RequirementCase).where(RequirementCase.project_id == project_id)))
        if not project or not case or not project.customer_id or case.customer_id != project.customer_id:
            raise HTTPException(422, detail='只能选择项目当前客户的正式需求')
        if (case.project_id and case.project_id != project_id) or any(c.id != case.id for c in linked):
            raise HTTPException(409, detail='已有关联需求，请先核对关系，不自动替换')
        case.project_id = project_id
        revision, _ = runtime.ledger.save_in_session(session, snapshot, revision)
        result = {'case_id': case.id, 'project_id': project_id, 'revision': revision}
        ProjectTaskDraftService._save_request(session, request_id=payload.request_id,
            operation='project_requirement_case_link', payload_hash=hash_value, result=result)
        session.commit()
        return result
