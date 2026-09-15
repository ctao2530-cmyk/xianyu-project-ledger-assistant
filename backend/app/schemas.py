from __future__ import annotations

from datetime import datetime
from typing import Literal, Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .ai.requirements import RequirementAnalysisResult
from .requirement_blueprints import RequirementBlueprintV2


class ItemView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    title: str
    price: str | None
    description: str | None


class MessageView(BaseModel):
    id: int
    channel: str
    platform_message_id: str
    external_id: str
    sender_name: str
    direction: str
    message_type: str
    content: str
    status: str
    risk_flags: list[str]
    received_at: datetime
    source_item_external_id: str | None = None
    images: list[dict[str, Any]] = Field(default_factory=list)
    customer_images: list[dict[str, Any]] = Field(default_factory=list)


class DraftView(BaseModel):
    id: int
    style: str
    content: str
    risk_flags: list[str]


class AITaskView(BaseModel):
    id: int
    provider: str
    model: str | None = None
    status: str
    attempt_count: int
    risk_level: str | None
    risk_reasons: list[str]
    needs_human_confirmation: bool = True
    error_code: str | None
    error_message: str | None
    repair_command: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None = None


class DraftGenerateRequest(BaseModel):
    provider: Literal["deepseek", "codex_cli"]


class AIProviderStatusView(BaseModel):
    provider: Literal["deepseek", "codex_cli"]
    label: str
    configured: bool
    status: str
    detail: str | None
    model: str | None
    last_latency_seconds: float | None = None
    supports_replies: bool = True
    supports_lead_analysis: bool = False
    manual_requirement_import: bool = False
    base_url: str | None = None
    chat_endpoint: str | None = None
    models_endpoint: str | None = None
    config_file: str | None = None
    lead_model: str | None = None


class XianyuConnectionRecoverRequest(BaseModel):
    cookie: SecretStr


class DeepSeekConnectionRecoverRequest(BaseModel):
    api_key: SecretStr


class ConnectionReloadRequest(BaseModel):
    provider: Literal["xianyu", "deepseek"]


class ConnectionRecoveryView(BaseModel):
    provider: Literal["xianyu", "deepseek", "codex_cli"]
    status: str
    detail: str
    configured: bool
    persisted: bool
    repair_command: str | None = None


class ConversationListItem(BaseModel):
    id: int
    channel: str
    customer_name: str
    item_title: str | None
    unread_count: int
    last_message: str | None
    last_message_at: datetime


class ConversationDetail(BaseModel):
    id: int
    channel: str
    external_id: str
    customer_id: str
    linked_customer_id: str | None
    customer_name: str
    unread_count: int
    item: ItemView | None
    messages: list[MessageView]
    has_older_messages: bool = False
    pending_message_id: int | None
    drafts: list[DraftView]
    ai_task: AITaskView | None


class ConversationHistorySearchRequest(BaseModel):
    query: str = Field(default="", max_length=100)
    days: Literal[7, 30, 90, 365] = 30
    limit: int = Field(default=100, ge=1, le=200)


class ConversationHistorySearchItem(BaseModel):
    external_conversation_id: str
    customer_name: str
    item_title: str | None
    last_message: str
    last_message_at: datetime
    direction: Literal["inbound", "outbound"]
    existing_conversation_id: int | None
    known_message_count: int


class ConversationHistoryPreviewRequest(BaseModel):
    external_conversation_id: str = Field(min_length=1, max_length=128)
    message_limit: int = Field(default=100, ge=1, le=200)
    history_scope: Literal["recent", "full", "page"] = "recent"
    continuation_token: str | None = Field(default=None, max_length=4096)


class ConversationHistoryPreviewMessage(BaseModel):
    platform_message_id: str
    sender_name: str
    direction: Literal["inbound", "outbound"]
    message_type: str
    content: str
    received_at: datetime
    import_status: Literal["new", "existing", "unsupported"]


class ConversationHistoryPreviewView(BaseModel):
    token: str
    expires_at: datetime
    external_conversation_id: str
    customer_name: str
    item: ItemView | None
    item_warning: str | None = None
    messages: list[ConversationHistoryPreviewMessage]
    platform_message_count: int
    existing_count: int
    new_count: int
    unsupported_count: int
    history_scope: Literal["recent", "full", "page"]
    image_candidate_count: int = 0
    has_more: bool = False
    next_continuation_token: str | None = None
    history_complete: bool | None = None
    history_limit: int = 200


class ConversationMessagePage(BaseModel):
    messages: list[MessageView]
    has_more: bool


class ConversationHistoryCommitRequest(BaseModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    preview_token: str = Field(min_length=16, max_length=256)
    mark_latest_pending: bool = False


class ConversationHistoryCommitView(BaseModel):
    conversation_id: int
    created_conversation: bool
    platform_message_count: int
    imported_count: int
    existing_count: int
    pending_message_id: int | None
    draft_task_queued: bool
    draft_task_id: int | None
    image_candidate_count: int
    image_stored_count: int
    image_failed_count: int
    idempotent: bool
    has_more: bool = False
    next_continuation_token: str | None = None


class SendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class AutomationUpdateRequest(BaseModel):
    enabled: bool
    duration_minutes: int | None = Field(default=None, ge=15, le=1440)
    confirmation: str = Field(default="", max_length=100)


class AutomationStatusView(BaseModel):
    feature_enabled: bool
    enabled: bool
    enabled_until: datetime | None
    remaining_seconds: int
    disabled_reason: str | None
    consecutive_failures: int
    daily_sent: int
    daily_limit: int
    max_duration_minutes: int


class ListenerLogView(BaseModel):
    id: int
    status: str
    detail: str | None
    error_type: str | None
    created_at: datetime


class AIModelOptionView(BaseModel):
    model: str
    display_name: str
    default_reasoning_effort: str | None
    supported_reasoning_efforts: list[str]


class AIModelSettingsView(BaseModel):
    provider: str
    selected_model: str | None
    selected_reasoning_effort: str | None
    models: list[AIModelOptionView]


class AIModelUpdateRequest(BaseModel):
    model: str | None = Field(default=None, max_length=128)
    reasoning_effort: str | None = Field(default=None, max_length=32)


class ReplyProfileView(BaseModel):
    mode: str
    label: str
    description: str
    model: str | None
    reasoning_effort: str | None
    context_messages: int
    context_chars: int


class ReplyStrategyView(BaseModel):
    mode: str
    effective_model: str | None
    effective_reasoning_effort: str | None
    high_risk_routing_enabled: bool
    profiles: list[ReplyProfileView]


class ReplyStrategyUpdateRequest(BaseModel):
    mode: str = Field(pattern="^(fast|balanced|quality|custom)$")


class StyleLearningView(BaseModel):
    enabled: bool
    sample_count: int
    summary: str
    traits: list[str]
    updated_at: datetime | None


class StyleLearningUpdateRequest(BaseModel):
    enabled: bool | None = None
    reset: bool = False


class RequirementTaskView(BaseModel):
    id: int
    conversation_id: int
    mode: str
    base_version: int | None
    status: str
    attempt_count: int
    model: str | None
    reasoning_effort: str | None
    result_version: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RequirementVersionSummaryView(BaseModel):
    id: int
    version: int
    title: str
    readiness: str
    change_summary: str
    model: str
    reasoning_effort: str | None
    created_at: datetime


class RequirementVersionView(RequirementVersionSummaryView):
    document: RequirementAnalysisResult | RequirementBlueprintV2
    content_markdown: str
    stage_progress: dict[str, str]


class RequirementWorkspaceView(BaseModel):
    conversation_id: int
    model_label: str
    configured_model: str
    configured_reasoning_effort: str
    latest: RequirementVersionView | None
    versions: list[RequirementVersionSummaryView]
    task: RequirementTaskView | None


class RequirementRevisionRequest(BaseModel):
    change_request: str = Field(min_length=2, max_length=4000)


class RequirementStageProgressRequest(BaseModel):
    stage_sequence: int = Field(ge=1, le=12)
    status: str = Field(pattern="^(pending|in_progress|completed|blocked)$")


class StatusView(BaseModel):
    listener: str
    listener_detail: str | None
    listener_realtime_delivery: str = "unknown"
    listener_realtime_detail: str | None = None
    listener_subscription_confirmed: bool = False
    listener_last_frame_at: datetime | None = None
    listener_last_decoded_at: datetime | None = None
    listener_frames_received: int = 0
    listener_decode_failures: int = 0
    listener_parse_dropped: int = 0
    listener_live_messages_received: int = 0
    listener_reconcile_recovered_total: int = 0
    listener_last_reconcile_at: datetime | None = None
    performance_sample_size: int = 0
    average_detection_seconds: float | None = None
    average_ai_seconds: float | None = None
    average_end_to_end_seconds: float | None = None
    model: str
    model_detail: str | None
    ai_provider: str
    ai_model: str | None = None
    ai_reasoning_effort: str | None = None
    reply_mode: str = "custom"
    effective_reply_model: str | None = None
    customer_reply_drafts_enabled: bool = False
    customer_quote_conversion_enabled: bool = False
    reply_high_risk_routing_enabled: bool = True
    style_learning_enabled: bool = True
    style_sample_count: int = 0
    style_summary: str = ""
    style_traits: list[str] = Field(default_factory=list)
    codex_installed: bool | None
    codex_logged_in: bool | None
    ai_repair_command: str | None
    ai_pending_tasks: int
    ai_running_tasks: int
    automatic_sending: bool = False
    auto_reply_enabled_until: datetime | None = None
    auto_reply_remaining_seconds: int = 0
    auto_reply_disabled_reason: str | None = None
    auto_reply_daily_sent: int = 0
    auto_reply_daily_limit: int = 0
    auto_reply_max_duration_minutes: int = 0
    auto_reply_feature_enabled: bool = False
    last_event_at: datetime | None
    wechat_provider: str = "mock"
    wechat_configured: bool = False
    wechat_status: str = "config_required"
    wechat_detail: str | None = None
    wechat_last_event_at: datetime | None = None
