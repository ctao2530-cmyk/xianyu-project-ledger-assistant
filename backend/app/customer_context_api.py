from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status, Depends

from .codex_sync_api import _local_only
from .customer_workflow_access import local_customer_workflow
from .customer_context_schemas import (
    CustomerContextAccessAuditView,
    CustomerConversationAccessView,
    CustomerConversationGrantCreate,
    CustomerContextGrantCreate,
    CustomerContextGrantRevoke,
    CustomerContextGrantView,
    CustomerContextTunnelBindingCreate,
    CustomerContextTunnelBindingRevoke,
    CustomerContextTunnelBindingView,
    CustomerContextThreadBindingCreate,
    CustomerContextThreadBindingListView,
    CustomerContextThreadBindingRevoke,
    CustomerContextThreadBindingView,
)
from .services.customer_context_gateway import (
    CustomerContextGateway,
    CustomerContextGatewayError,
)


customer_context_router = APIRouter(
    prefix="/api/customer-context", tags=["customer-context"], dependencies=[Depends(local_customer_workflow)]
)


def _service(request: Request) -> CustomerContextGateway:
    _local_only(request)
    return request.app.state.runtime.customer_context_gateway


def _tunnel_config(request: Request):
    _local_only(request)
    config = getattr(request.app.state, "customer_context_tunnel_config", None)
    if config is None or not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "tunnel_binding_not_configured",
                "message": "ChatGPT Tunnel 本地绑定模式尚未启用",
            },
        )
    return config


def _thread_auth_status(request: Request) -> dict[str, object]:
    """Resolve the currently configured external MCP authentication mode."""

    _local_only(request)
    tunnel_config = getattr(request.app.state, "customer_context_tunnel_config", None)
    if tunnel_config is not None and tunnel_config.enabled:
        return {"auth_mode": "tunnel_binding", "configured": True}
    oauth_config = getattr(request.app.state, "customer_context_oauth_config", None)
    if oauth_config is not None and oauth_config.enabled:
        return {"auth_mode": "oauth", "configured": True}
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "customer_context_mcp_not_configured",
            "message": "ChatGPT 客户上下文 MCP 尚未配置",
        },
    )


@customer_context_router.get("/oauth/status")
async def customer_context_oauth_status(request: Request) -> dict:
    _local_only(request)
    oauth_config = getattr(request.app.state, "customer_context_oauth_config", None)
    if oauth_config is None:
        return {
            "configured": False,
            "issuer_url": "",
            "resource_server_url": "",
            "resource_metadata_url": "",
            "required_scope": "customer-context.read",
            "allowed_subject_count": 0,
            "allowed_client_id_count": 0,
        }
    return oauth_config.status()


def _raise(exc: CustomerContextGatewayError) -> None:
    if exc.code in {"thread_not_found", "conversation_not_found", "grant_not_found"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        "request_id_reused",
        "request_record_invalid",
        "thread_revision_conflict",
        "conversation_revision_conflict",
        "grant_not_active",
        "access_request_replayed",
        "binding_changed",
        "tunnel_binding_revision_conflict",
        "thread_binding_revision_conflict",
        "thread_binding_conflict",
    }:
        code = status.HTTP_409_CONFLICT
    elif exc.code in {
        "provider_not_allowed",
        "tool_not_allowed",
        "grant_scope_mismatch",
        "grant_expired",
        "grant_revoked",
        "text_not_authorized",
        "images_not_authorized",
        "artifact_not_authorized",
        "tunnel_binding_not_found",
        "thread_binding_not_found",
        "thread_binding_not_active",
        "context_key_not_found",
        "context_key_expired",
        "context_key_auth_mismatch",
        "context_key_owner_mismatch",
    }:
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": str(exc)},
    ) from None


def _tunnel_view(request: Request, value: dict) -> dict:
    config = _tunnel_config(request)
    return {**config.status(), **value}


@customer_context_router.get(
    "/tunnel-binding",
    response_model=CustomerContextTunnelBindingView,
    response_model_exclude={"grant": {"capability_token"}},
)
async def customer_context_tunnel_binding(
    request: Request,
) -> CustomerContextTunnelBindingView:
    return _tunnel_view(request, _service(request).tunnel_binding_state())


@customer_context_router.post(
    "/tunnel-binding",
    response_model=CustomerContextTunnelBindingView,
    response_model_exclude={"grant": {"capability_token"}},
)
async def replace_customer_context_tunnel_binding(
    payload: CustomerContextTunnelBindingCreate,
    request: Request,
) -> CustomerContextTunnelBindingView:
    _tunnel_config(request)
    try:
        result = _service(request).replace_tunnel_binding(
            conversation_id=payload.conversation_id,
            request_id=payload.request_id,
            expected_binding_revision=payload.expected_binding_revision,
            expected_conversation_revision=payload.expected_conversation_revision,
            allow_text=payload.allow_text,
            allow_images=payload.allow_images,
            allow_artifacts=payload.allow_artifacts,
            allow_new_messages=payload.allow_new_messages,
            expires_in_seconds=payload.expires_in_seconds,
            authorization_note=payload.authorization_note,
        )
        return _tunnel_view(request, result)
    except CustomerContextGatewayError as exc:
        _raise(exc)


@customer_context_router.post(
    "/tunnel-binding/revoke",
    response_model=CustomerContextTunnelBindingView,
    response_model_exclude={"grant": {"capability_token"}},
)
async def revoke_customer_context_tunnel_binding(
    payload: CustomerContextTunnelBindingRevoke,
    request: Request,
) -> CustomerContextTunnelBindingView:
    _tunnel_config(request)
    try:
        result = _service(request).revoke_tunnel_binding(
            request_id=payload.request_id,
            expected_binding_revision=payload.expected_binding_revision,
            reason=payload.reason,
        )
        return _tunnel_view(request, result)
    except CustomerContextGatewayError as exc:
        _raise(exc)


@customer_context_router.get(
    "/thread-bindings",
    response_model=CustomerContextThreadBindingListView,
    response_model_exclude={
        "legacy_grant": {"capability_token": True},
        "bindings": {
            "__all__": {
                "context_key": True,
                "grant": {"capability_token": True},
            }
        }
    },
)
async def customer_context_thread_bindings(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
) -> CustomerContextThreadBindingListView:
    status_view = _thread_auth_status(request)
    service = _service(request)
    legacy = (
        service.tunnel_binding_state()
        if status_view["auth_mode"] == "tunnel_binding"
        else {"active": False, "grant": None}
    )
    return {
        **status_view,
        "legacy_binding_active": bool(legacy["active"]),
        "legacy_grant": legacy["grant"],
        "bindings": service.list_thread_bindings(limit=limit),
    }


@customer_context_router.post(
    "/thread-bindings",
    response_model=CustomerContextThreadBindingView,
    response_model_exclude={"grant": {"capability_token"}},
)
async def create_customer_context_thread_binding(
    payload: CustomerContextThreadBindingCreate,
    request: Request,
) -> CustomerContextThreadBindingView:
    auth_status = _thread_auth_status(request)
    try:
        return _service(request).create_thread_binding(
            conversation_id=payload.conversation_id,
            request_id=payload.request_id,
            expected_conversation_revision=payload.expected_conversation_revision,
            auth_mode=str(auth_status["auth_mode"]),
            group_id=payload.group_id,
            expected_group_revision=payload.expected_group_revision,
            selected_conversation_ids=payload.selected_conversation_ids,
            allow_text=payload.allow_text,
            allow_images=payload.allow_images,
            allow_artifacts=payload.allow_artifacts,
            allow_new_messages=payload.allow_new_messages,
            expires_in_seconds=payload.expires_in_seconds,
            authorization_note=payload.authorization_note,
        )
    except CustomerContextGatewayError as exc:
        _raise(exc)


@customer_context_router.post(
    "/thread-bindings/{binding_id}/revoke",
    response_model=CustomerContextThreadBindingView,
    response_model_exclude={
        "context_key": True,
        "grant": {"capability_token": True},
    },
)
async def revoke_customer_context_thread_binding(
    binding_id: str,
    payload: CustomerContextThreadBindingRevoke,
    request: Request,
) -> CustomerContextThreadBindingView:
    try:
        return _service(request).revoke_thread_binding(
            binding_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            reason=payload.reason,
        )
    except CustomerContextGatewayError as exc:
        _raise(exc)


@customer_context_router.get(
    "/conversations/{conversation_id}/access",
    response_model=CustomerConversationAccessView,
)
async def customer_conversation_access(
    conversation_id: int, request: Request
) -> CustomerConversationAccessView:
    try:
        return _service(request).conversation_access_state(conversation_id)
    except CustomerContextGatewayError as exc:
        _raise(exc)


@customer_context_router.post(
    "/conversation-grants", response_model=CustomerContextGrantView
)
async def create_customer_conversation_grant(
    payload: CustomerConversationGrantCreate, request: Request
) -> CustomerContextGrantView:
    try:
        return _service(request).create_conversation_grant(
            conversation_id=payload.conversation_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            allow_text=payload.allow_text,
            allow_images=payload.allow_images,
            allow_artifacts=payload.allow_artifacts,
            expires_in_seconds=payload.expires_in_seconds,
            authorization_note=payload.authorization_note,
            audience=payload.audience,
            allow_new_messages=payload.allow_new_messages,
            provider_scope=payload.provider_scope,
        )
    except CustomerContextGatewayError as exc:
        _raise(exc)


@customer_context_router.post(
    "/grants", response_model=CustomerContextGrantView
)
async def create_customer_context_grant(
    payload: CustomerContextGrantCreate, request: Request
) -> CustomerContextGrantView:
    try:
        return _service(request).create_grant(
            thread_id=payload.thread_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            allow_text=payload.allow_text,
            allow_images=payload.allow_images,
            allow_artifacts=payload.allow_artifacts,
            expires_in_seconds=payload.expires_in_seconds,
            authorization_note=payload.authorization_note,
            audience=payload.audience,
            allow_new_messages=payload.allow_new_messages,
            provider_scope=payload.provider_scope,
        )
    except CustomerContextGatewayError as exc:
        _raise(exc)


@customer_context_router.get(
    "/threads/{thread_id}/grant", response_model=CustomerContextGrantView | None
)
async def latest_customer_context_grant(
    thread_id: str, request: Request
) -> CustomerContextGrantView | None:
    try:
        return _service(request).latest_grant(thread_id)
    except CustomerContextGatewayError as exc:
        _raise(exc)


@customer_context_router.post(
    "/grants/{grant_id}/revoke", response_model=CustomerContextGrantView
)
async def revoke_customer_context_grant(
    grant_id: str,
    payload: CustomerContextGrantRevoke,
    request: Request,
) -> CustomerContextGrantView:
    try:
        return _service(request).revoke_grant(
            grant_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            reason=payload.reason,
        )
    except CustomerContextGatewayError as exc:
        _raise(exc)


@customer_context_router.get(
    "/threads/{thread_id}/audits",
    response_model=list[CustomerContextAccessAuditView],
)
async def customer_context_access_audits(
    thread_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CustomerContextAccessAuditView]:
    try:
        return _service(request).access_audits(thread_id, limit=limit)
    except CustomerContextGatewayError as exc:
        _raise(exc)
