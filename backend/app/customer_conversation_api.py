from fastapi import APIRouter, Request, HTTPException, Query, Depends
from pydantic import BaseModel, ConfigDict, Field
from .codex_sync_api import _local_only
from .services.customer_conversation_groups import CustomerConversationGroupService, ConversationGroupError
from .customer_workflow_access import local_customer_workflow
from datetime import date
from .services.customer_message_search import CustomerMessageSearch

customer_conversation_router = APIRouter(prefix="/api", tags=["customer-conversation-groups"], dependencies=[Depends(local_customer_workflow)])


class GroupChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    group_id: str | None = None
    conversation_ids: list[int] = Field(max_length=100)
    expected_revision: int = Field(ge=0)
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    reason: str = Field(min_length=2, max_length=1000)
    confirmed: bool = False
    preview_token: str | None = None


def service(request):
    _local_only(request)
    return CustomerConversationGroupService(request.app.state.runtime.database)


def failure(exc):
    status = 409 if exc.code in {"group_revision_conflict", "request_id_reused", "preview_invalid"} else 422
    if exc.code.endswith("not_found"):
        status = 404
    raise HTTPException(status, detail={"code": exc.code, "message": str(exc)})


@customer_conversation_router.get("/customers/{customer_id}/conversation-group-candidates")
async def candidates(customer_id: str, request: Request):
    try:
        return service(request).candidates(customer_id)
    except ConversationGroupError as exc:
        failure(exc)


@customer_conversation_router.get("/customers/{customer_id}/conversation-groups")
async def groups(customer_id: str, request: Request):
    try:
        return service(request).candidates(customer_id)["groups"]
    except ConversationGroupError as exc:
        failure(exc)


@customer_conversation_router.post("/customers/{customer_id}/conversation-groups/preview")
async def preview(customer_id: str, payload: GroupChange, request: Request):
    try:
        values = payload.model_dump()
        values["confirmed"] = False
        return service(request).change(customer_id, **values)
    except ConversationGroupError as exc:
        failure(exc)


@customer_conversation_router.post("/customers/{customer_id}/conversation-groups")
async def change(customer_id: str, payload: GroupChange, request: Request):
    if not payload.confirmed:
        raise HTTPException(422, detail={"code": "confirmation_required", "message": "请确认合并预览范围"})
    try:
        return service(request).change(customer_id, **payload.model_dump())
    except ConversationGroupError as exc:
        failure(exc)


@customer_conversation_router.get("/conversation-groups/{group_id}/timeline")
async def timeline(group_id: str, request: Request, limit: int = Query(50, ge=1, le=100),
                   offset: int = Query(0, ge=0), item_id: int | None = None):
    try:
        return service(request).timeline(group_id, limit=limit, offset=offset, item_id=item_id)
    except ConversationGroupError as exc:
        failure(exc)


@customer_conversation_router.get('/customer-message-search')
def search_messages(request: Request, query: str = Query(min_length=1, max_length=200),
                    customer_id: str | None = None, conversation_id: int | None = Query(None, gt=0),
                    conversation_ids: list[int] = Query(default=[]), date_from: date | None = None,
                    date_to: date | None = None, before_message_id: int | None = Query(None, gt=0),
                    limit: int = Query(30, ge=1, le=100)):
    return CustomerMessageSearch(request.app.state.runtime.database).read(customer_id=customer_id,
        conversation_id=conversation_id, conversation_ids=conversation_ids, query=query,
        date_from=date_from, date_to=date_to, before_message_id=before_message_id, limit=limit)


@customer_conversation_router.get('/customer-message-search/context')
def search_message_context(request: Request, message_id: int = Query(gt=0),
                           customer_id: str | None = None, conversation_id: int | None = Query(None, gt=0),
                           conversation_ids: list[int] = Query(default=[])):
    return CustomerMessageSearch(request.app.state.runtime.database).read(customer_id=customer_id,
        conversation_id=conversation_id, conversation_ids=conversation_ids, message_id=message_id)
