from __future__ import annotations

import asyncio
import json
from datetime import timezone

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.orm import joinedload
from sqlalchemy import func, select

from .ai import AIProviderError
from .config import PROJECT_ROOT
from .customer_time import utc_from_storage
from .models import (
    AIGenerationTask,
    Conversation,
    Draft,
    ListenerStatusLog,
    Message,
    RequirementAnalysisTask,
    RequirementDocumentVersion,
)
from .runtime import Runtime
from .schemas import (
    ConversationDetail,
    ConversationHistoryCommitRequest,
    ConversationHistoryCommitView,
    ConversationHistoryPreviewRequest,
    ConversationHistoryPreviewView,
    ConversationHistorySearchItem,
    ConversationHistorySearchRequest,
    ConversationListItem,
    ConversationMessagePage,
    AutomationStatusView,
    AutomationUpdateRequest,
    AITaskView,
    AIModelOptionView,
    AIModelSettingsView,
    AIModelUpdateRequest,
    AIProviderStatusView,
    ConnectionRecoveryView,
    ConnectionReloadRequest,
    DeepSeekConnectionRecoverRequest,
    DraftView,
    DraftGenerateRequest,
    ItemView,
    ListenerLogView,
    MessageView,
    SendRequest,
    RequirementRevisionRequest,
    RequirementStageProgressRequest,
    RequirementTaskView,
    RequirementVersionSummaryView,
    RequirementVersionView,
    RequirementWorkspaceView,
    ReplyProfileView,
    ReplyStrategyUpdateRequest,
    ReplyStrategyView,
    StyleLearningUpdateRequest,
    StyleLearningView,
    StatusView,
    XianyuConnectionRecoverRequest,
)
from .services.actions import ActionConflictError, MessageNotFoundError
from .services.ai_models import AIModelSelectionError, AIModelSettingsSnapshot
from .services.automation import ENABLE_CONFIRMATION, AutomationUnavailableError
from .services.connection_recovery import (
    ConnectionRecoveryError,
    ConnectionRecoveryResult,
)
from .services.conversation_history_import import ConversationHistoryImportError
from .services.requirements import RequirementAnalysisService, RequirementServiceError
from .services.requirement_exchange import RequirementExchangeService
from .services.reply_strategy import ReplyStrategyError


router = APIRouter(prefix="/api")


def runtime_from(request: Request) -> Runtime:
    return request.app.state.runtime


def load_json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def message_view(message: Message) -> MessageView:
    from .services.customer_images import CustomerImageArchiveService
    images = [CustomerImageArchiveService._view(row, "") for row in sorted(message.customer_images, key=lambda row: (row.media_index, row.id)) if row.deleted_at is None]
    return MessageView(
        id=message.id,
        channel=message.channel,
        platform_message_id=message.platform_message_id,
        external_id=message.external_id,
        sender_name=message.sender_name,
        direction=message.direction,
        message_type=message.message_type,
        content=message.content,
        status=message.status,
        risk_flags=load_json_list(message.risk_flags_json),
        received_at=utc_from_storage(message.received_at),
        source_item_external_id=message.source_item_external_id,
        images=images,
        customer_images=images,
    )


def ai_task_view(task: AIGenerationTask) -> AITaskView:
    return AITaskView(
        id=task.id,
        provider=task.provider,
        model=task.model,
        status=task.status,
        attempt_count=task.attempt_count,
        risk_level=task.risk_level,
        risk_reasons=load_json_list(task.risk_reasons_json),
        needs_human_confirmation=True,
        error_code=task.error_code,
        error_message=task.error_message,
        repair_command=task.repair_command,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        duration_seconds=(
            round(max(0.0, (task.finished_at - task.started_at).total_seconds()), 1)
            if task.started_at and task.finished_at
            else None
        ),
    )


def ai_model_settings_view(snapshot: AIModelSettingsSnapshot) -> AIModelSettingsView:
    return AIModelSettingsView(
        provider=snapshot.provider,
        selected_model=snapshot.selection.model,
        selected_reasoning_effort=snapshot.selection.reasoning_effort,
        models=[
            AIModelOptionView(
                model=option.model,
                display_name=option.display_name,
                default_reasoning_effort=option.default_reasoning_effort,
                supported_reasoning_efforts=list(option.supported_reasoning_efforts),
            )
            for option in snapshot.models
        ],
    )


def requirement_task_view(task: RequirementAnalysisTask) -> RequirementTaskView:
    return RequirementTaskView(
        id=task.id,
        conversation_id=task.conversation_id,
        mode=task.mode,
        base_version=task.base_version,
        status=task.status,
        attempt_count=task.attempt_count,
        model=task.model,
        reasoning_effort=task.reasoning_effort,
        result_version=task.result_version,
        error_code=task.error_code,
        error_message=task.error_message,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


def requirement_summary_view(
    version: RequirementDocumentVersion,
) -> RequirementVersionSummaryView:
    return RequirementVersionSummaryView(
        id=version.id,
        version=version.version,
        title=version.title,
        readiness=version.readiness,
        change_summary=version.change_summary,
        model=version.model,
        reasoning_effort=version.reasoning_effort,
        created_at=version.created_at,
    )


def requirement_version_view(
    version: RequirementDocumentVersion,
) -> RequirementVersionView:
    return RequirementVersionView(
        **requirement_summary_view(version).model_dump(),
        document=json.loads(version.structured_json),
        content_markdown=version.content_markdown,
        stage_progress=RequirementAnalysisService._load_progress(
            version.stage_progress_json
        ),
    )


def _raise_requirement_error(exc: RequirementServiceError) -> None:
    if exc.code in {
        "conversation_not_found",
        "requirement_version_not_found",
        "stage_not_found",
    }:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        "requirement_task_active",
        "requirement_missing",
        "insufficient_context",
    }:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=str(exc)) from None


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _require_local(request: Request) -> None:
    client = request.client.host if request.client else ""
    desktop_header = request.headers.get("x-yuda-desktop")
    if (
        client not in {"127.0.0.1", "::1", "localhost", "testclient"}
        or desktop_header != "1"
    ):
        raise HTTPException(status_code=403, detail="仅允许本机桌面助手控制")


def _connection_view(result: ConnectionRecoveryResult) -> ConnectionRecoveryView:
    return ConnectionRecoveryView(
        provider=result.provider,
        status=result.status,
        detail=result.detail,
        configured=result.configured,
        persisted=result.persisted,
        repair_command=result.repair_command,
    )


def _raise_connection_error(exc: ConnectionRecoveryError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.safe_message},
    ) from None


def _raise_history_import_error(exc: ConversationHistoryImportError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.safe_message},
    ) from None


@router.post("/desktop/listener/pause")
async def pause_listener(request: Request) -> dict[str, bool]:
    _require_local(request)
    await runtime_from(request).listener_supervisor.pause()
    return {"ok": True}


@router.post("/desktop/listener/resume")
async def resume_listener(request: Request) -> dict[str, bool]:
    _require_local(request)
    await runtime_from(request).listener_supervisor.resume()
    return {"ok": True}


@router.post("/desktop/listener/reconnect")
async def reconnect_listener(request: Request) -> dict[str, bool]:
    _require_local(request)
    await runtime_from(request).listener_supervisor.reconnect()
    return {"ok": True}


@router.post(
    "/connections/xianyu/recover",
    response_model=ConnectionRecoveryView,
)
async def recover_xianyu_connection(
    payload: XianyuConnectionRecoverRequest,
    request: Request,
) -> ConnectionRecoveryView:
    _require_local(request)
    try:
        result = await runtime_from(request).connection_recovery.recover_xianyu(
            payload.cookie.get_secret_value()
        )
    except ConnectionRecoveryError as exc:
        _raise_connection_error(exc)
    return _connection_view(result)


@router.post(
    "/connections/deepseek/recover",
    response_model=ConnectionRecoveryView,
)
async def recover_deepseek_connection(
    payload: DeepSeekConnectionRecoverRequest,
    request: Request,
) -> ConnectionRecoveryView:
    _require_local(request)
    try:
        result = await runtime_from(request).connection_recovery.recover_deepseek(
            payload.api_key.get_secret_value()
        )
    except ConnectionRecoveryError as exc:
        _raise_connection_error(exc)
    return _connection_view(result)


@router.post(
    "/connections/reload",
    response_model=ConnectionRecoveryView,
)
async def reload_connection(
    payload: ConnectionReloadRequest,
    request: Request,
) -> ConnectionRecoveryView:
    _require_local(request)
    try:
        result = await runtime_from(request).connection_recovery.reload(payload.provider)
    except ConnectionRecoveryError as exc:
        _raise_connection_error(exc)
    return _connection_view(result)


@router.post(
    "/connections/codex/check",
    response_model=ConnectionRecoveryView,
)
async def check_codex_connection(request: Request) -> ConnectionRecoveryView:
    _require_local(request)
    result = await runtime_from(request).connection_recovery.check_codex()
    return _connection_view(result)


@router.get("/status", response_model=StatusView)
async def get_status(request: Request) -> StatusView:
    runtime = runtime_from(request)
    automation = runtime.automation.snapshot()
    style = runtime.style_learning.snapshot()
    with runtime.database.session() as session:
        pending = session.scalar(
            select(func.count()).select_from(AIGenerationTask).where(
                AIGenerationTask.status == "pending"
            )
        ) or 0
        running = session.scalar(
            select(func.count()).select_from(AIGenerationTask).where(
                AIGenerationTask.status == "running"
            )
        ) or 0
        timing_rows = session.execute(
            select(
                Message.received_at,
                Message.created_at,
                AIGenerationTask.started_at,
                AIGenerationTask.finished_at,
            )
            .join(AIGenerationTask, AIGenerationTask.message_id == Message.id)
            .where(
                AIGenerationTask.status == "completed",
                AIGenerationTask.started_at.is_not(None),
                AIGenerationTask.finished_at.is_not(None),
            )
            .order_by(AIGenerationTask.id.desc())
            .limit(20)
        ).all()

    detection_seconds = [
        max(0.0, (created_at - received_at).total_seconds())
        for received_at, created_at, _started_at, _finished_at in timing_rows
    ]
    ai_seconds = [
        max(0.0, (finished_at - started_at).total_seconds())
        for _received_at, _created_at, started_at, finished_at in timing_rows
        if started_at and finished_at
    ]
    end_to_end_seconds = [
        max(0.0, (finished_at - received_at).total_seconds())
        for received_at, _created_at, _started_at, finished_at in timing_rows
        if finished_at
    ]

    def average(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 1) if values else None
    health = runtime.ai.health
    effective_strategy = runtime.reply_strategy.resolve(
        base_selection=runtime.ai_models.selection,
        has_local_risk=False,
    )
    wechat = runtime.wecom.snapshot()
    return StatusView(
        listener=runtime.status.listener,
        listener_detail=runtime.status.listener_detail,
        listener_realtime_delivery=runtime.status.realtime_delivery,
        listener_realtime_detail=runtime.status.realtime_detail,
        listener_subscription_confirmed=runtime.adapter.subscription_confirmed,
        listener_last_frame_at=runtime.adapter.last_frame_at,
        listener_last_decoded_at=runtime.adapter.last_decoded_at,
        listener_frames_received=runtime.adapter.frames_received,
        listener_decode_failures=runtime.adapter.decode_failures,
        listener_parse_dropped=runtime.adapter.parse_dropped,
        listener_live_messages_received=runtime.adapter.live_messages_received,
        listener_reconcile_recovered_total=runtime.status.reconcile_recovered_total,
        listener_last_reconcile_at=runtime.status.last_reconcile_at,
        performance_sample_size=len(timing_rows),
        average_detection_seconds=average(detection_seconds),
        average_ai_seconds=average(ai_seconds),
        average_end_to_end_seconds=average(end_to_end_seconds),
        model=runtime.ai.status,
        model_detail=runtime.ai.detail,
        ai_provider=runtime.ai.name,
        ai_model=runtime.ai_models.selection.model,
        ai_reasoning_effort=runtime.ai_models.selection.reasoning_effort,
        reply_mode=runtime.reply_strategy.mode,
        effective_reply_model=effective_strategy.model_selection.model,
        customer_reply_drafts_enabled=runtime.settings.customer_reply_drafts_enabled,
        customer_quote_conversion_enabled=runtime.settings.customer_quote_conversion_enabled,
        reply_high_risk_routing_enabled=(
            runtime.settings.reply_high_risk_routing_enabled
        ),
        style_learning_enabled=style.enabled,
        style_sample_count=style.sample_count,
        style_summary=style.summary,
        style_traits=list(style.traits),
        codex_installed=health.installed,
        codex_logged_in=health.logged_in,
        ai_repair_command=health.repair_command,
        ai_pending_tasks=pending,
        ai_running_tasks=running,
        automatic_sending=automation.enabled,
        auto_reply_enabled_until=automation.enabled_until,
        auto_reply_remaining_seconds=automation.remaining_seconds,
        auto_reply_disabled_reason=automation.disabled_reason,
        auto_reply_daily_sent=automation.daily_sent,
        auto_reply_daily_limit=automation.daily_limit,
        auto_reply_max_duration_minutes=automation.max_duration_minutes,
        auto_reply_feature_enabled=automation.feature_enabled,
        last_event_at=runtime.status.last_event_at,
        wechat_provider=wechat.provider,
        wechat_configured=wechat.configured,
        wechat_status=wechat.status,
        wechat_detail=wechat.detail,
        wechat_last_event_at=wechat.last_event_at,
    )


@router.get("/style-learning", response_model=StyleLearningView)
async def get_style_learning(request: Request) -> StyleLearningView:
    return StyleLearningView(**runtime_from(request).style_learning.snapshot().to_dict())


@router.post("/style-learning", response_model=StyleLearningView)
async def update_style_learning(
    payload: StyleLearningUpdateRequest,
    request: Request,
) -> StyleLearningView:
    _require_local(request)
    service = runtime_from(request).style_learning
    if payload.reset:
        snapshot = service.reset()
    elif payload.enabled is not None:
        snapshot = service.set_enabled(payload.enabled)
    else:
        snapshot = service.snapshot()
    return StyleLearningView(**snapshot.to_dict())


@router.get("/ai/models", response_model=AIModelSettingsView)
async def get_ai_models(
    request: Request,
    refresh: bool = Query(default=False),
) -> AIModelSettingsView:
    try:
        snapshot = await runtime_from(request).ai_models.get(refresh=refresh)
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=exc.safe_message) from None
    return ai_model_settings_view(snapshot)


def _provider_latency(runtime: Runtime, provider: str) -> float | None:
    with runtime.database.session() as session:
        row = session.execute(
            select(AIGenerationTask.started_at, AIGenerationTask.finished_at)
            .where(
                AIGenerationTask.provider == provider,
                AIGenerationTask.status == "completed",
                AIGenerationTask.started_at.is_not(None),
                AIGenerationTask.finished_at.is_not(None),
            )
            .order_by(AIGenerationTask.id.desc())
            .limit(1)
        ).first()
    if not row or not row.started_at or not row.finished_at:
        return None
    return round(max(0.0, (row.finished_at - row.started_at).total_seconds()), 1)


@router.get("/ai/providers", response_model=list[AIProviderStatusView])
async def get_ai_providers(
    request: Request,
    refresh: bool = Query(default=False),
) -> list[AIProviderStatusView]:
    runtime = runtime_from(request)
    # Healthchecks return sanitized state only; API keys and prompts never cross
    # the backend boundary.
    if refresh:
        await asyncio.gather(
            runtime.deepseek.healthcheck(validate_execution=True),
            runtime.ai.healthcheck(validate_execution=False),
        )
    codex_health = runtime.ai.health
    deepseek_health = runtime.deepseek.health
    deepseek_base_url = runtime.settings.deepseek_base_url.rstrip("/")
    return [
        AIProviderStatusView(
            provider="deepseek",
            label="DeepSeek 快速",
            configured=runtime.settings.deepseek_configured,
            status=deepseek_health.status,
            detail=deepseek_health.detail,
            model=runtime.settings.deepseek_reply_model,
            last_latency_seconds=_provider_latency(runtime, "deepseek"),
            supports_lead_analysis=True,
            base_url=deepseek_base_url,
            chat_endpoint=f"{deepseek_base_url}/chat/completions",
            models_endpoint=f"{deepseek_base_url}/models",
            config_file=str(PROJECT_ROOT / ".env"),
            lead_model=runtime.settings.deepseek_lead_model,
        ),
        AIProviderStatusView(
            provider="codex_cli",
            label="Codex 深度",
            configured=runtime.settings.ai_configured,
            status=codex_health.status,
            detail=codex_health.detail,
            model=runtime.ai_models.selection.model,
            last_latency_seconds=_provider_latency(runtime, "codex_cli"),
            manual_requirement_import=True,
        ),
    ]


@router.post("/ai/models", response_model=AIModelSettingsView)
async def update_ai_model(
    payload: AIModelUpdateRequest,
    request: Request,
) -> AIModelSettingsView:
    try:
        snapshot = await runtime_from(request).ai_models.update(
            payload.model,
            payload.reasoning_effort,
        )
        runtime_from(request).reply_strategy.set_mode("custom")
    except AIModelSelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=exc.safe_message) from None
    return ai_model_settings_view(snapshot)


def reply_strategy_view(runtime: Runtime) -> ReplyStrategyView:
    resolved = runtime.reply_strategy.resolve(
        base_selection=runtime.ai_models.selection,
        has_local_risk=False,
    )
    return ReplyStrategyView(
        mode=runtime.reply_strategy.mode,
        effective_model=resolved.model_selection.model,
        effective_reasoning_effort=resolved.model_selection.reasoning_effort,
        high_risk_routing_enabled=runtime.settings.reply_high_risk_routing_enabled,
        profiles=[
            ReplyProfileView(
                mode=profile.mode,
                label=profile.label,
                description=profile.description,
                model=profile.model,
                reasoning_effort=profile.reasoning_effort,
                context_messages=profile.context_messages,
                context_chars=profile.context_chars,
            )
            for profile in runtime.reply_strategy.profiles()
        ],
    )


@router.get("/ai/reply-strategy", response_model=ReplyStrategyView)
async def get_reply_strategy(request: Request) -> ReplyStrategyView:
    return reply_strategy_view(runtime_from(request))


@router.post("/ai/reply-strategy", response_model=ReplyStrategyView)
async def update_reply_strategy(
    payload: ReplyStrategyUpdateRequest,
    request: Request,
) -> ReplyStrategyView:
    _require_local(request)
    runtime = runtime_from(request)
    profile = runtime.reply_strategy.profile(payload.mode)
    if profile and profile.model:
        try:
            catalog = await runtime.ai_models.get(refresh=False)
        except AIProviderError as exc:
            raise HTTPException(status_code=503, detail=exc.safe_message) from exc
        if not any(option.model == profile.model for option in catalog.models):
            raise HTTPException(
                status_code=400,
                detail=f"当前 Codex 账号不支持模型 {profile.model}",
            )
    try:
        runtime.reply_strategy.set_mode(payload.mode)
    except ReplyStrategyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return reply_strategy_view(runtime)


@router.get("/automation", response_model=AutomationStatusView)
async def get_automation(request: Request) -> AutomationStatusView:
    return AutomationStatusView(**runtime_from(request).automation.snapshot().to_dict())


@router.get("/logs/listener", response_model=list[ListenerLogView])
async def get_listener_logs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ListenerLogView]:
    runtime = runtime_from(request)
    with runtime.database.session() as session:
        rows = list(
            session.scalars(
                select(ListenerStatusLog)
                .order_by(ListenerStatusLog.created_at.desc(), ListenerStatusLog.id.desc())
                .limit(limit)
            )
        )
    return [
        ListenerLogView(
            id=row.id,
            status=row.status,
            detail=row.detail,
            error_type=row.error_type,
            # SQLite returns naive datetimes even though the application stores
            # UTC. Restore the timezone before serialization so browsers display
            # the actual macOS local time instead of shifting it by eight hours.
            created_at=(
                row.created_at
                if row.created_at.tzinfo is not None
                else row.created_at.replace(tzinfo=timezone.utc)
            ),
        )
        for row in rows
    ]


@router.post("/automation", response_model=AutomationStatusView)
async def update_automation(
    payload: AutomationUpdateRequest, request: Request
) -> AutomationStatusView:
    _require_local(request)
    runtime = runtime_from(request)
    if payload.enabled:
        if payload.confirmation != ENABLE_CONFIRMATION:
            raise HTTPException(status_code=400, detail="需要明确确认无人值守自动回复风险")
        if runtime.status.listener != "connected":
            raise HTTPException(status_code=409, detail="闲鱼监听未连接，不能开启无人值守")
        if runtime.ai.status != "connected":
            raise HTTPException(status_code=409, detail="Codex 未就绪，不能开启无人值守")
        try:
            snapshot = await runtime.automation.enable(payload.duration_minutes)
        except AutomationUnavailableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
    else:
        snapshot = await runtime.automation.disable()
    return AutomationStatusView(**snapshot.to_dict())


@router.get("/conversations", response_model=list[ConversationListItem])
async def list_conversations(
    request: Request,
    channel: str = Query(default="all", pattern="^(all|xianyu|wechat)$"),
) -> list[ConversationListItem]:
    runtime = runtime_from(request)
    with runtime.database.session() as session:
        latest_text = (select(Message.content)
            .where(Message.conversation_id == Conversation.id)
            .order_by(Message.received_at.desc(), Message.id.desc())
            .limit(1).correlate(Conversation).scalar_subquery())
        statement = select(Conversation, latest_text).options(joinedload(Conversation.item))
        if channel != "all":
            statement = statement.where(Conversation.channel == channel)
        rows = session.execute(statement.order_by(Conversation.last_message_at.desc(), Conversation.id.desc())).all()
        result = [ConversationListItem(
            id=conversation.id, channel=conversation.channel,
            customer_name=conversation.customer_name,
            item_title=conversation.item.title if conversation.item else None,
            unread_count=conversation.unread_count,
            last_message=latest_text,
            last_message_at=utc_from_storage(conversation.last_message_at),
        ) for conversation, latest_text in rows]
        return result


@router.post(
    "/conversations/history-import/search",
    response_model=list[ConversationHistorySearchItem],
)
async def search_conversation_history(
    payload: ConversationHistorySearchRequest,
    request: Request,
) -> list[ConversationHistorySearchItem]:
    _require_local(request)
    try:
        result = await runtime_from(request).conversation_history_import.search(
            query=payload.query,
            days=payload.days,
            limit=payload.limit,
        )
    except ConversationHistoryImportError as exc:
        _raise_history_import_error(exc)
    return [ConversationHistorySearchItem(**row) for row in result]


@router.post(
    "/conversations/history-import/preview",
    response_model=ConversationHistoryPreviewView,
)
async def preview_conversation_history(
    payload: ConversationHistoryPreviewRequest,
    request: Request,
) -> ConversationHistoryPreviewView:
    _require_local(request)
    try:
        result = await runtime_from(request).conversation_history_import.preview(
            external_conversation_id=payload.external_conversation_id,
            message_limit=payload.message_limit,
            full_history=payload.history_scope == "full",
            **({"paged": True, "continuation_token": payload.continuation_token} if payload.history_scope == "page" else {}),
        )
    except ConversationHistoryImportError as exc:
        _raise_history_import_error(exc)
    return ConversationHistoryPreviewView(**result)


@router.post(
    "/conversations/history-import/commit",
    response_model=ConversationHistoryCommitView,
)
async def commit_conversation_history(
    payload: ConversationHistoryCommitRequest,
    request: Request,
) -> ConversationHistoryCommitView:
    _require_local(request)
    try:
        result = await runtime_from(request).conversation_history_import.commit(
            request_id=payload.request_id,
            preview_token=payload.preview_token,
            mark_latest_pending=payload.mark_latest_pending,
        )
    except ConversationHistoryImportError as exc:
        _raise_history_import_error(exc)
    return ConversationHistoryCommitView(**result)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: int, request: Request) -> ConversationDetail:
    runtime = runtime_from(request)
    with runtime.database.session() as session:
        conversation = session.get(Conversation, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = list(
            session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.received_at.desc(), Message.id.desc())
                .limit(101)
            )
        )
        has_older_messages = len(messages) > 100
        messages = messages[:100]
        messages.reverse()
        pending = next(
            (
                message
                for message in reversed(messages)
                if message.direction == "inbound"
                and message.status
                in {
                    "new",
                    "ai_queued",
                    "ai_generating",
                    "ai_failed",
                    "ai_cancelled",
                    "drafted",
                    "send_failed",
                }
            ),
            None,
        )
        drafts: list[DraftView] = []
        ai_task = None
        if pending:
            draft_rows = list(
                session.scalars(
                    select(Draft)
                    .where(Draft.message_id == pending.id)
                    .order_by(Draft.id.asc())
                )
            )
            drafts = [
                DraftView(
                    id=draft.id,
                    style=draft.style,
                    content=draft.content,
                    risk_flags=load_json_list(draft.risk_flags_json),
                )
                for draft in draft_rows
            ]
            task_row = session.scalar(
                select(AIGenerationTask)
                .where(AIGenerationTask.message_id == pending.id)
                .order_by(AIGenerationTask.created_at.desc(), AIGenerationTask.id.desc())
                .limit(1)
            )
            ai_task = ai_task_view(task_row) if task_row else None
        linked_customer_id = RequirementExchangeService._linked_customer_id(
            session,
            conversation,
        )
        item = (
            ItemView.model_validate(conversation.item) if conversation.item else None
        )
        return ConversationDetail(
            id=conversation.id,
            channel=conversation.channel,
            external_id=conversation.external_id,
            customer_id=conversation.customer_id,
            linked_customer_id=linked_customer_id,
            customer_name=conversation.customer_name,
            unread_count=conversation.unread_count,
            item=item,
            messages=[message_view(message) for message in messages],
            has_older_messages=has_older_messages,
            pending_message_id=pending.id if pending else None,
            drafts=drafts,
            ai_task=ai_task,
        )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationMessagePage,
)
async def get_older_conversation_messages(
    conversation_id: int,
    request: Request,
    before_message_id: int = Query(gt=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> ConversationMessagePage:
    runtime = runtime_from(request)
    with runtime.database.session() as session:
        conversation = session.get(Conversation, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="会话不存在")
        anchor = session.get(Message, before_message_id)
        if anchor is None or anchor.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="分页锚点不存在")
        rows = list(
            session.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    (
                        (Message.received_at < anchor.received_at)
                        | (
                            (Message.received_at == anchor.received_at)
                            & (Message.id < anchor.id)
                        )
                    ),
                )
                .order_by(Message.received_at.desc(), Message.id.desc())
                .limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()
        return ConversationMessagePage(
            messages=[message_view(message) for message in rows],
            has_more=has_more,
        )


@router.post("/messages/{message_id}/drafts/regenerate", status_code=status.HTTP_202_ACCEPTED)
async def regenerate_drafts(message_id: int, request: Request) -> dict[str, object]:
    runtime = runtime_from(request)
    if not runtime.settings.customer_reply_drafts_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="回复草稿功能已暂时停用",
        )
    task_id = await runtime.processor.regenerate(message_id)
    if task_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="消息不存在或当前状态不能重新生成",
        )
    return {"ok": True, "task_id": task_id}


@router.post(
    "/messages/{message_id}/drafts/generate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_drafts_with_provider(
    message_id: int,
    payload: DraftGenerateRequest,
    request: Request,
) -> dict[str, object]:
    runtime = runtime_from(request)
    if not runtime.settings.customer_reply_drafts_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="回复草稿功能已暂时停用",
        )
    if payload.provider == "deepseek" and not runtime.settings.deepseek_configured:
        raise HTTPException(status_code=409, detail="DeepSeek API 尚未配置")
    try:
        task_id = await runtime.processor.regenerate(
            message_id,
            provider_name=payload.provider,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=409, detail=exc.safe_message) from None
    if task_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="消息不存在或当前状态不能重新生成",
        )
    return {"ok": True, "task_id": task_id, "provider": payload.provider}


@router.get(
    "/conversations/{conversation_id}/requirements",
    response_model=RequirementWorkspaceView,
)
async def get_requirement_workspace(
    conversation_id: int,
    request: Request,
) -> RequirementWorkspaceView:
    runtime = runtime_from(request)
    with runtime.database.session() as session:
        if not session.get(Conversation, conversation_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        versions = list(
            session.scalars(
                select(RequirementDocumentVersion)
                .where(RequirementDocumentVersion.conversation_id == conversation_id)
                .order_by(RequirementDocumentVersion.version.desc())
            )
        )
        task = session.scalar(
            select(RequirementAnalysisTask)
            .where(RequirementAnalysisTask.conversation_id == conversation_id)
            .order_by(RequirementAnalysisTask.id.desc())
            .limit(1)
        )
    latest = versions[0] if versions else None
    return RequirementWorkspaceView(
        conversation_id=conversation_id,
        model_label="GPT-5.6 Pro",
        configured_model=runtime.settings.requirement_analysis_model,
        configured_reasoning_effort=(
            runtime.settings.requirement_analysis_reasoning_effort
        ),
        latest=requirement_version_view(latest) if latest else None,
        versions=[requirement_summary_view(version) for version in versions],
        task=requirement_task_view(task) if task else None,
    )


@router.get(
    "/requirements/versions/{version_id}",
    response_model=RequirementVersionView,
)
async def get_requirement_version(
    version_id: int,
    request: Request,
) -> RequirementVersionView:
    runtime = runtime_from(request)
    with runtime.database.session() as session:
        version = session.get(RequirementDocumentVersion, version_id)
        if not version:
            raise HTTPException(status_code=404, detail="需求版本不存在")
        return requirement_version_view(version)


@router.post(
    "/conversations/{conversation_id}/requirements/generate",
    response_model=RequirementTaskView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_requirement_document(
    conversation_id: int,
    request: Request,
) -> RequirementTaskView:
    try:
        task = await runtime_from(request).requirements.enqueue(conversation_id)
    except RequirementServiceError as exc:
        _raise_requirement_error(exc)
    return requirement_task_view(task)


@router.post(
    "/conversations/{conversation_id}/requirements/revise",
    response_model=RequirementTaskView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def revise_requirement_document(
    conversation_id: int,
    payload: RequirementRevisionRequest,
    request: Request,
) -> RequirementTaskView:
    try:
        task = await runtime_from(request).requirements.enqueue(
            conversation_id,
            change_request=payload.change_request,
        )
    except RequirementServiceError as exc:
        _raise_requirement_error(exc)
    return requirement_task_view(task)


@router.post("/requirements/tasks/{task_id}/cancel")
async def cancel_requirement_task(task_id: int, request: Request) -> dict[str, bool]:
    if not await runtime_from(request).requirements.cancel(task_id):
        raise HTTPException(status_code=409, detail="需求分析任务不存在或已结束")
    return {"ok": True}


@router.post(
    "/requirements/versions/{version_id}/stage-progress",
    response_model=RequirementVersionView,
)
async def update_requirement_stage_progress(
    version_id: int,
    payload: RequirementStageProgressRequest,
    request: Request,
) -> RequirementVersionView:
    try:
        version = runtime_from(request).requirements.set_stage_progress(
            version_id,
            payload.stage_sequence,
            payload.status,
        )
    except RequirementServiceError as exc:
        _raise_requirement_error(exc)
    return requirement_version_view(version)


@router.post("/ai/tasks/{task_id}/cancel")
async def cancel_ai_task(task_id: int, request: Request) -> dict[str, bool]:
    runtime = runtime_from(request)
    if not await runtime.ai_queue.cancel(task_id):
        raise HTTPException(status_code=409, detail="AI 任务不存在或已结束")
    return {"ok": True}


@router.post("/messages/{message_id}/send")
async def send_message(
    message_id: int, payload: SendRequest, request: Request
) -> dict[str, object]:
    runtime = runtime_from(request)
    try:
        channel = runtime.actions.channel_for_message(message_id)
    except MessageNotFoundError:
        raise HTTPException(status_code=404, detail="消息不存在") from None
    if not await runtime.send_limiter.allow(f"{channel}_send"):
        raise HTTPException(status_code=429, detail="发送过于频繁，请稍后再试")
    try:
        flags = await runtime.actions.confirm_send(message_id, payload.content.strip())
        return {"ok": True, "risk_flags": flags}
    except MessageNotFoundError:
        raise HTTPException(status_code=404, detail="消息不存在") from None
    except ActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"发送失败：{type(exc).__name__}",
        ) from None


@router.post("/messages/{message_id}/ignore")
async def ignore_message(message_id: int, request: Request) -> dict[str, bool]:
    runtime = runtime_from(request)
    try:
        runtime.actions.ignore(message_id)
        return {"ok": True}
    except MessageNotFoundError:
        raise HTTPException(status_code=404, detail="消息不存在") from None
    except ActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
