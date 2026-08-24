from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from .codex_sync_api import _local_only
from .global_agent_schemas import (
    AgentBootstrapView,
    AgentKnowledgeReindex,
    AgentKnowledgeReindexResult,
    AgentKnowledgeStatus,
    AgentMessageCreate,
    AgentModelOptionView,
    AgentProfileCreate,
    AgentProfileUpdate,
    AgentProfileView,
    AgentRunCancel,
    AgentRunView,
    AgentThreadCreate,
    AgentThreadContextUpdate,
    AgentThreadDelete,
    AgentThreadProfileUpdate,
    AgentThreadView,
    AgentCustomerContextOption,
    AgentCustomerCreateConfirm,
)
from .customer_intake_schemas import CustomerCreateResult
from .agents.global_agent import GlobalAgentServiceError


global_agent_router = APIRouter(prefix="/api/global-agent", tags=["global-agent"])


def _raise(exc: GlobalAgentServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.safe_message},
    ) from None


@global_agent_router.get("/bootstrap", response_model=AgentBootstrapView)
async def bootstrap(request: Request) -> AgentBootstrapView:
    _local_only(request)
    return request.app.state.runtime.global_agent.bootstrap_view()


@global_agent_router.get("/profiles", response_model=list[AgentProfileView])
async def profiles(request: Request) -> list[AgentProfileView]:
    _local_only(request)
    return request.app.state.runtime.global_agent.profiles()


@global_agent_router.post(
    "/profiles", response_model=AgentProfileView, status_code=status.HTTP_201_CREATED
)
async def create_profile(
    payload: AgentProfileCreate, request: Request
) -> AgentProfileView:
    _local_only(request)
    try:
        return request.app.state.runtime.global_agent.create_profile(payload)
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.patch(
    "/profiles/{profile_id}", response_model=AgentProfileView
)
async def update_profile(
    profile_id: str, payload: AgentProfileUpdate, request: Request
) -> AgentProfileView:
    _local_only(request)
    try:
        return request.app.state.runtime.global_agent.update_profile(profile_id, payload)
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.get(
    "/providers/{provider}/models", response_model=list[AgentModelOptionView]
)
async def provider_models(
    provider: str, request: Request
) -> list[AgentModelOptionView]:
    _local_only(request)
    try:
        rows = await request.app.state.runtime.global_agent.available_models(provider)
        return [
            AgentModelOptionView(
                model=row.model,
                display_name=row.display_name,
                default_reasoning_effort=row.default_reasoning_effort,
                supported_reasoning_efforts=list(row.supported_reasoning_efforts),
            )
            for row in rows
        ]
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.get("/threads", response_model=list[AgentThreadView])
async def threads(request: Request) -> list[AgentThreadView]:
    _local_only(request)
    return request.app.state.runtime.global_agent.list_threads()


@global_agent_router.get(
    "/customer-context-options", response_model=list[AgentCustomerContextOption]
)
async def customer_context_options(
    request: Request,
) -> list[AgentCustomerContextOption]:
    _local_only(request)
    return request.app.state.runtime.global_agent.customer_context_options()


@global_agent_router.post(
    "/threads", response_model=AgentThreadView, status_code=status.HTTP_201_CREATED
)
async def create_thread(
    payload: AgentThreadCreate, request: Request
) -> AgentThreadView:
    _local_only(request)
    try:
        return request.app.state.runtime.global_agent.create_thread(payload)
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.get("/threads/{thread_id}", response_model=AgentThreadView)
async def thread(thread_id: str, request: Request) -> AgentThreadView:
    _local_only(request)
    try:
        return request.app.state.runtime.global_agent.thread(thread_id)
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.patch(
    "/threads/{thread_id}/profile", response_model=AgentThreadView
)
async def update_thread_profile(
    thread_id: str, payload: AgentThreadProfileUpdate, request: Request
) -> AgentThreadView:
    _local_only(request)
    try:
        return request.app.state.runtime.global_agent.update_thread_profile(
            thread_id, payload
        )
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.patch(
    "/threads/{thread_id}/context", response_model=AgentThreadView
)
async def update_thread_context(
    thread_id: str, payload: AgentThreadContextUpdate, request: Request
) -> AgentThreadView:
    _local_only(request)
    try:
        return request.app.state.runtime.global_agent.update_thread_context(
            thread_id, payload
        )
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.delete(
    "/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_thread(
    thread_id: str, payload: AgentThreadDelete, request: Request
) -> Response:
    _local_only(request)
    try:
        request.app.state.runtime.global_agent.delete_thread(thread_id, payload)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.post(
    "/threads/{thread_id}/messages",
    response_model=AgentRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_message(
    thread_id: str, payload: AgentMessageCreate, request: Request
) -> AgentRunView:
    _local_only(request)
    try:
        return request.app.state.runtime.global_agent.submit_message(thread_id, payload)
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.post(
    "/threads/{thread_id}/customer-create/confirm",
    response_model=CustomerCreateResult,
)
async def confirm_customer_create(
    thread_id: str,
    payload: AgentCustomerCreateConfirm,
    request: Request,
) -> CustomerCreateResult:
    _local_only(request)
    try:
        result = request.app.state.runtime.global_agent.confirm_customer_create(
            thread_id,
            assistant_message_id=payload.assistant_message_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
        )
    except GlobalAgentServiceError as exc:
        _raise(exc)
    return CustomerCreateResult(**result)


@global_agent_router.get("/runs/{run_id}", response_model=AgentRunView)
async def run(run_id: str, request: Request) -> AgentRunView:
    _local_only(request)
    try:
        return request.app.state.runtime.global_agent.run(run_id)
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.post("/runs/{run_id}/cancel", response_model=AgentRunView)
async def cancel_run(
    run_id: str, payload: AgentRunCancel, request: Request
) -> AgentRunView:
    _local_only(request)
    try:
        return await request.app.state.runtime.global_agent.cancel_run(
            run_id, payload.request_id
        )
    except GlobalAgentServiceError as exc:
        _raise(exc)


@global_agent_router.get("/knowledge", response_model=AgentKnowledgeStatus)
async def knowledge_status(request: Request) -> AgentKnowledgeStatus:
    _local_only(request)
    return request.app.state.runtime.global_agent.rag.status()


@global_agent_router.post(
    "/knowledge/reindex", response_model=AgentKnowledgeReindexResult
)
async def reindex_knowledge(
    payload: AgentKnowledgeReindex, request: Request
) -> AgentKnowledgeReindexResult:
    _local_only(request)
    try:
        return request.app.state.runtime.global_agent.reindex_knowledge(
            payload.request_id, confirmed=payload.confirmed
        )
    except GlobalAgentServiceError as exc:
        _raise(exc)
