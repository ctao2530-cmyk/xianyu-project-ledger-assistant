from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _platform_message_id_default(context) -> str:
    """Keep legacy Message constructors compatible during the channel migration."""
    return str(context.get_current_parameters().get("external_id") or "")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), default="未知商品")
    price: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(
        String(32), default="xianyu", server_default="xianyu", index=True
    )
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(128), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="闲鱼客户")
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    unread_count: Mapped[int] = mapped_column(default=0)
    last_message_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    item: Mapped[Item | None] = relationship()
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(
        String(32), default="xianyu", server_default="xianyu", index=True
    )
    platform_message_id: Mapped[str] = mapped_column(
        String(255), default=_platform_message_id_default, server_default=""
    )
    external_id: Mapped[str] = mapped_column(String(255), unique=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[str] = mapped_column(String(128))
    sender_name: Mapped[str] = mapped_column(String(255), default="闲鱼客户")
    direction: Mapped[str] = mapped_column(String(16))
    message_type: Mapped[str] = mapped_column(String(32), default="text")
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    risk_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    client_send_uuid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    drafts: Mapped[list[Draft]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    ai_tasks: Mapped[list[AIGenerationTask]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_messages_conversation_received", "conversation_id", "received_at"),
        Index(
            "idx_messages_channel_platform_message",
            "channel",
            "platform_message_id",
            unique=True,
        ),
    )


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    style: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    risk_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    message: Mapped[Message] = relationship(back_populates="drafts")

    __table_args__ = (UniqueConstraint("message_id", "style", name="uq_draft_message_style"),)


class AIGenerationTask(Base):
    __tablename__ = "ai_generation_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    trigger_key: Mapped[str] = mapped_column(String(255), unique=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempt_count: Mapped[int] = mapped_column(default=0)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    needs_human_confirmation: Mapped[bool] = mapped_column(default=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    repair_command: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    message: Mapped[Message] = relationship(back_populates="ai_tasks")

    __table_args__ = (
        Index("idx_ai_tasks_status_created", "status", "created_at"),
        Index("idx_ai_tasks_conversation_status", "conversation_id", "status"),
    )


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ListenerStatusLog(Base):
    """Sanitized connection-state history; never stores Cookie or tokens."""

    __tablename__ = "listener_status_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ChannelCursor(Base):
    """Non-secret incremental cursor used by official channel APIs."""

    __tablename__ = "channel_cursors"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), index=True)
    cursor: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AutomationState(Base):
    """Single-row, fail-closed state for temporary unattended replies."""

    __tablename__ = "automation_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(default=False)
    enabled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    enabled_until: Mapped[datetime | None] = mapped_column(nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(default=0)
    last_auto_reply_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AIModelPreference(Base):
    """Persisted non-secret global model choice for future AI tasks."""

    __tablename__ = "ai_model_preference"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ReplyStrategyPreference(Base):
    """Persisted non-secret response-speed profile for future drafts."""

    __tablename__ = "reply_strategy_preference"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    mode: Mapped[str] = mapped_column(String(32), default="balanced")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class SellerStylePreference(Base):
    """Local, non-secret switch controlling seller reply-style learning."""

    __tablename__ = "seller_style_preference"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    collect_after: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class SellerReplySample(Base):
    """One actually sent seller reply used only as a local writing-style example."""

    __tablename__ = "seller_reply_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id"), unique=True, index=True
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="synced_outbound")
    included: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index(
            "idx_seller_style_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )


class RequirementAnalysisTask(Base):
    """One user-triggered Codex job that creates or revises a requirement document."""

    __tablename__ = "requirement_analysis_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    mode: Mapped[str] = mapped_column(String(16), default="initial")
    base_version: Mapped[int | None] = mapped_column(nullable=True)
    change_request: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_version: Mapped[int | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index(
            "idx_requirement_tasks_conversation_status",
            "conversation_id",
            "status",
        ),
    )


class RequirementDocumentVersion(Base):
    """Immutable requirement content plus mutable local phase-progress markers."""

    __tablename__ = "requirement_document_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
    case_id: Mapped[str | None] = mapped_column(
        ForeignKey("requirement_cases.id"), nullable=True, index=True
    )
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0")
    source_type: Mapped[str] = mapped_column(String(32), default="codex_cli")
    source_label: Mapped[str] = mapped_column(String(255), default="Codex 生成")
    imported_at: Mapped[datetime | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column()
    title: Mapped[str] = mapped_column(String(300))
    readiness: Mapped[str] = mapped_column(String(32))
    change_summary: Mapped[str] = mapped_column(Text)
    structured_json: Mapped[str] = mapped_column(Text)
    content_markdown: Mapped[str] = mapped_column(Text)
    stage_progress_json: Mapped[str] = mapped_column(Text, default="{}")
    model: Mapped[str] = mapped_column(String(128))
    reasoning_effort: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "version", name="uq_requirement_conversation_version"
        ),
        UniqueConstraint("case_id", "version", name="uq_requirement_case_version"),
        Index(
            "idx_requirement_versions_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )


class RequirementCase(Base):
    """Customer-level requirement case containing immutable blueprint versions."""

    __tablename__ = "requirement_cases"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("business_customers.id"), index=True
    )
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("items.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300), index=True)
    status: Mapped[str] = mapped_column(String(32), default="clarifying", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    lead_id: Mapped[str | None] = mapped_column(
        ForeignKey("sales_leads.id"), nullable=True, index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class RequirementCaseSource(Base):
    __tablename__ = "requirement_case_sources"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("requirement_cases.id"), index=True
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    last_exported_message_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("case_id", "conversation_id", name="uq_requirement_case_source"),
    )


class LeadAnalysisRun(Base):
    """A read-only DeepSeek analysis; it never creates a sales lead by itself."""

    __tablename__ = "lead_analysis_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(64), default="deepseek")
    model: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    structured_json: Mapped[str] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class SalesAnalysisRun(Base):
    """Independent Sales Agent output; never sends or mutates business records."""

    __tablename__ = "sales_analysis_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    structured_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_used_json: Mapped[str] = mapped_column(Text, default="[]")
    context_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index(
            "idx_sales_analysis_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index("idx_sales_analysis_message_status", "message_id", "status"),
    )


# Unified developer-business records.  The existing reply-assistant tables
# above stay untouched so the copied database can be upgraded additively.


class LedgerState(Base):
    __tablename__ = "ledger_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class LedgerMutationRequest(Base):
    """Idempotency audit for narrow, revision-protected ledger mutations."""

    __tablename__ = "ledger_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class BusinessCustomer(Base):
    __tablename__ = "business_customers"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(32), default="other")
    phone: Mapped[str] = mapped_column(String(100), default="")
    follow_up_status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    last_contact_at: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(8), default="C")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CustomerMemory(Base):
    """Human-confirmed sales context that can be reused on later messages."""

    __tablename__ = "customer_memory"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_customers.id"), nullable=True, index=True
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), unique=True, index=True
    )
    source_analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("sales_analysis_runs.id"), nullable=True, index=True
    )
    customer_background: Mapped[str] = mapped_column(Text, default="")
    requirements_json: Mapped[str] = mapped_column(Text, default="[]")
    communication_summary: Mapped[str] = mapped_column(Text, default="")
    latest_analysis_json: Mapped[str] = mapped_column(Text, default="{}")
    follow_up_status: Mapped[str] = mapped_column(String(64), default="待跟进", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CustomerChannelIdentity(Base):
    __tablename__ = "customer_channel_identities"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_customers.id"), nullable=True, index=True
    )
    channel: Mapped[str] = mapped_column(String(32), index=True)
    external_customer_id: Mapped[str] = mapped_column(String(255))
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
    display_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("channel", "external_customer_id", name="uq_channel_customer_identity"),
    )


class CustomerItemLink(Base):
    """Human-confirmed relationship between a business customer and a listing."""

    __tablename__ = "customer_item_links"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("business_customers.id"), index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    source_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(
        String(32), default="requirement_import"
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("customer_id", "item_id", name="uq_customer_item_link"),
    )


class SalesLead(Base):
    __tablename__ = "sales_leads"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), unique=True, index=True
    )
    customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_customers.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    requirement_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_document_versions.id"), nullable=True
    )
    latest_quote_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    converted_project_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class BusinessProject(Base):
    __tablename__ = "business_projects"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_customers.id"), nullable=True, index=True
    )
    project_kind: Mapped[str] = mapped_column(
        String(32), default="client", server_default="client", index=True
    )
    lead_id: Mapped[str | None] = mapped_column(
        ForeignKey("sales_leads.id"), nullable=True, index=True
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
    requirement_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_document_versions.id"), nullable=True
    )
    quote_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0)
    start_date: Mapped[str] = mapped_column(String(32), default="")
    due_date: Mapped[str] = mapped_column(String(32), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    type: Mapped[str] = mapped_column(String(100), default="定制开发")
    estimated_hours: Mapped[float] = mapped_column(Float, default=0)
    accent: Mapped[str] = mapped_column(String(32), default="blue")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class BusinessTask(Base):
    __tablename__ = "business_tasks"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(32), default="todo", index=True)
    start_date: Mapped[str] = mapped_column(String(32), default="")
    due_date: Mapped[str] = mapped_column(String(32), default="")
    estimated_hours: Mapped[float] = mapped_column(Float, default=0)
    actual_hours: Mapped[float] = mapped_column(Float, default=0)
    stage_payload_json: Mapped[str] = mapped_column(Text, default="{}")


class ProjectChangeOrderRecord(Base):
    """A customer-confirmed paid scope addition within an existing project."""

    __tablename__ = "project_change_orders"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id"), index=True
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("business_customers.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    amount: Mapped[float] = mapped_column(Float)
    confirmed_at: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="confirmed", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class PaymentNode(Base):
    __tablename__ = "payment_nodes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id"), index=True
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("business_customers.id"), index=True
    )
    change_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_change_orders.id"), nullable=True, index=True
    )
    amount: Mapped[float] = mapped_column(Float, default=0)
    type: Mapped[str] = mapped_column(String(32), default="milestone")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    paid_at: Mapped[str] = mapped_column(String(64), default="")
    due_at: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class ProjectSettlementIssueRecord(Base):
    __tablename__ = "project_settlement_issues"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id"), index=True
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("business_customers.id"), index=True
    )
    issue_type: Mapped[str] = mapped_column(String(64), index=True)
    receivable_impact: Mapped[float] = mapped_column(Float, default=0)
    refund_amount: Mapped[float] = mapped_column(Float, default=0)
    occurred_at: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class BusinessExpense(Base):
    __tablename__ = "business_expenses"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_projects.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(32), default="other")
    amount: Mapped[float] = mapped_column(Float, default=0)
    paid_at: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class ProjectDevelopmentLog(Base):
    __tablename__ = "project_development_logs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id"), index=True
    )
    created_at_text: Mapped[str] = mapped_column(String(64), default="")
    content: Mapped[str] = mapped_column(Text)
    hours: Mapped[float] = mapped_column(Float, default=0)
    category: Mapped[str] = mapped_column(String(32), default="development")


class AttachmentMetadata(Base):
    __tablename__ = "attachment_metadata"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(500))
    size: Mapped[str] = mapped_column(String(64), default="")
    type: Mapped[str] = mapped_column(String(32), default="document")
    uploaded_at: Mapped[str] = mapped_column(String(64), default="")
    storage_path: Mapped[str] = mapped_column(String(1000), default="")


class QuoteProposal(Base):
    __tablename__ = "quote_proposals"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("sales_leads.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    requirement_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_document_versions.id"), nullable=True
    )
    hourly_rate: Mapped[float] = mapped_column(Float)
    risk_buffer: Mapped[float] = mapped_column(Float, default=0.15)
    estimated_hours: Mapped[float] = mapped_column(Float)
    total_amount: Mapped[float] = mapped_column(Float)
    stages_json: Mapped[str] = mapped_column(Text)
    payment_plan_json: Mapped[str] = mapped_column(Text)
    risks_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("lead_id", "version", name="uq_quote_lead_version"),
    )


class RequirementQuoteLink(Base):
    __tablename__ = "requirement_quote_links"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    requirement_version_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_document_versions.id"), index=True
    )
    quote_id: Mapped[str] = mapped_column(ForeignKey("quote_proposals.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class BusinessSetting(Base):
    __tablename__ = "business_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


# Additive, auditable snapshots produced by the business-analysis center. These
# tables only store aggregated analysis output and manual recommendation
# feedback. They never authorize or execute listing, customer, project, or
# financial mutations.


class BusinessAnalysisRecord(Base):
    __tablename__ = "business_analysis_records"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    snapshot_time: Mapped[datetime] = mapped_column(index=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    ledger_revision: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    analysis_method: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_status: Mapped[str] = mapped_column(String(32), default="not_requested", index=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index(
            "idx_business_analysis_status_snapshot",
            "status",
            "snapshot_time",
        ),
    )


class BusinessAnalysisRecommendationRecord(Base):
    __tablename__ = "business_analysis_recommendations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("business_analysis_records.id", ondelete="CASCADE"), index=True
    )
    source_key: Mapped[str] = mapped_column(String(128), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    domain: Mapped[str] = mapped_column(String(32), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    entity_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    problem: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[str] = mapped_column(String(16))
    observe_period: Mapped[str] = mapped_column(String(64))
    observe_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_sources_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    target_page: Mapped[str] = mapped_column(String(500), default="")
    target_scope: Mapped[str] = mapped_column(String(32), default="domain")
    execution_mode: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_request_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    user_note: Mapped[str] = mapped_column(Text, default="")
    accepted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    observe_until: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    baseline_metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    result_metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_conclusion: Mapped[str] = mapped_column(Text, default="")
    execution_ref_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_ref_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "source_key",
            name="uq_business_analysis_recommendation_source",
        ),
        Index(
            "idx_business_analysis_recommendation_order",
            "analysis_id",
            "position",
        ),
        Index(
            "idx_business_analysis_recommendation_lifecycle",
            "status",
            "observe_until",
        ),
    )


class BusinessAnalysisRecommendationEvent(Base):
    """Immutable, idempotent audit event for one recommendation transition."""

    __tablename__ = "business_analysis_recommendation_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("business_analysis_recommendations.id", ondelete="CASCADE"),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index(
            "idx_business_analysis_recommendation_event_timeline",
            "recommendation_id",
            "created_at",
        ),
    )


# Read-only Xianyu product intelligence. These records never contain cookies
# and never trigger listing edits, publishing, delisting, or paid promotion.


class ProductMonitor(Base):
    __tablename__ = "product_monitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id"), unique=True, index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="conversation")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    ownership_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", index=True
    )
    ownership_source: Mapped[str] = mapped_column(
        String(64), default="unverified", server_default="unverified"
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_collection_status: Mapped[str] = mapped_column(
        String(32), default="waiting", server_default="waiting"
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    item: Mapped[Item] = relationship()


class ProductDailySnapshot(Base):
    __tablename__ = "product_daily_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(32), default="remote_daily")
    title: Mapped[str] = mapped_column(String(500), default="未知商品")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="unknown")
    published_at: Mapped[str] = mapped_column(String(64), default="")
    # Keep the platform counter for audit while exposing browse_count as the
    # operating counter used by trends and recommendations. Successful remote
    # detail reads are excluded conservatively one at a time.
    raw_browse_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    collection_views_excluded: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    browse_count: Mapped[int] = mapped_column(Integer, default=0)
    collect_count: Mapped[int] = mapped_column(Integer, default=0)
    want_count: Mapped[int] = mapped_column(Integer, default=0)
    sold_count: Mapped[int] = mapped_column(Integer, default=0)
    inquiry_count: Mapped[int] = mapped_column(Integer, default=0)
    inbound_message_count: Mapped[int] = mapped_column(Integer, default=0)
    converted_project_count: Mapped[int] = mapped_column(Integer, default=0)
    revenue_total: Mapped[float] = mapped_column(Float, default=0)
    profit_total: Mapped[float] = mapped_column(Float, default=0)
    captured_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    item: Mapped[Item] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "item_id", "snapshot_date", name="uq_product_snapshot_item_date"
        ),
        Index(
            "idx_product_snapshots_item_date",
            "item_id",
            "snapshot_date",
        ),
    )


class ProductCollectionRun(Base):
    __tablename__ = "product_collection_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_date: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="scheduled")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    monitored_count: Mapped[int] = mapped_column(Integer, default=0)
    collected_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(String(500), default="")
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ProductCollectionAttempt(Base):
    """Append-only record of every scheduled or explicit collection attempt.

    ``ProductCollectionRun`` remains the once-per-Beijing-day scheduler gate.
    Attempts are intentionally separate so a later manual recovery can become
    the current visible state without deleting the earlier failed daily run.
    """

    __tablename__ = "product_collection_attempts"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_date: Mapped[str] = mapped_column(String(10), index=True)
    daily_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_collection_runs.id"), nullable=True, unique=True, index=True
    )
    trigger: Mapped[str] = mapped_column(String(32), index=True)
    requested_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("items.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    monitored_count: Mapped[int] = mapped_column(Integer, default=0)
    collected_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(String(500), default="")
    started_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("idx_product_collection_attempts_date_finished", "run_date", "finished_at"),
    )


class ProductCollectionAttemptItem(Base):
    """Safe per-listing result for a collection attempt.

    Only user-readable error codes/details are stored. Raw platform responses,
    seller identifiers and credentials never enter this audit trail.
    """

    __tablename__ = "product_collection_attempt_items"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("product_collection_attempts.id"), index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str] = mapped_column(String(500), default="")
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "item_id", name="uq_product_collection_attempt_item"
        ),
        Index(
            "idx_product_collection_attempt_items_item_finished",
            "item_id",
            "finished_at",
        ),
    )


class ProductStrategyRecommendation(Base):
    __tablename__ = "product_strategy_recommendations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("product_daily_snapshots.id"), index=True
    )
    recommendation_date: Mapped[str] = mapped_column(String(10), index=True)
    strategy_code: Mapped[str] = mapped_column(String(64), index=True)
    priority_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    attention: Mapped[str] = mapped_column(String(16), default="low", index=True)
    posture: Mapped[str] = mapped_column(String(64), default="observe")
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    actions_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    item: Mapped[Item] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "recommendation_date",
            name="uq_product_recommendation_item_date",
        ),
        Index(
            "idx_product_recommendations_status_priority",
            "status",
            "priority_score",
        ),
    )


class ProductActionLog(Base):
    __tablename__ = "product_action_logs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    recommendation_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_strategy_recommendations.id"),
        nullable=True,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    cost: Mapped[float] = mapped_column(Float, default=0)
    happened_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    observation_until: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    item: Mapped[Item] = relationship()


class ProductOperatingPlan(Base):
    """Versioned rolling plan produced by the local rules engine."""

    __tablename__ = "product_operating_plans"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    plan_start_date: Mapped[str] = mapped_column(String(10), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="current", index=True)
    input_signature: Mapped[str] = mapped_column(String(128), index=True)
    weekly_budget: Mapped[float] = mapped_column(Float, default=24)
    change_summary: Mapped[str] = mapped_column(Text, default="")
    data_quality: Mapped[str] = mapped_column(String(32), default="low")
    rules_version: Mapped[str] = mapped_column(String(32), default="v2")
    generated_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "plan_start_date", "version", name="uq_product_operating_plan_version"
        ),
        Index(
            "idx_product_operating_plans_status_start",
            "status",
            "plan_start_date",
        ),
    )


class ProductOperatingPlanSlot(Base):
    __tablename__ = "product_operating_plan_slots"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("product_operating_plans.id"), index=True
    )
    slot_date: Mapped[str] = mapped_column(String(10), index=True)
    scheduled_time: Mapped[str] = mapped_column(String(5), default="20:00")
    action_type: Mapped[str] = mapped_column(String(32), default="observe", index=True)
    item_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    planned_cost: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    change_reason: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    locked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    plan: Mapped[ProductOperatingPlan] = relationship()

    __table_args__ = (
        UniqueConstraint("plan_id", "slot_date", name="uq_product_plan_slot_date"),
        Index(
            "idx_product_plan_slots_date_action",
            "slot_date",
            "action_type",
        ),
    )


class ProductTrafficBatch(Base):
    """A user-recorded Xianyu exposure purchase covering multiple products."""

    __tablename__ = "product_traffic_batches"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    plan_slot_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_operating_plan_slots.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    planned_at: Mapped[datetime] = mapped_column(index=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    actual_cost: Mapped[float] = mapped_column(Float, default=5.9)
    total_exposure: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index(
            "idx_product_traffic_batches_status_planned",
            "status",
            "planned_at",
        ),
    )


class ProductTrafficBatchItem(Base):
    __tablename__ = "product_traffic_batch_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_batches.id"), index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    baseline_browse_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_collect_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_want_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_inquiry_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_captured_at: Mapped[datetime | None] = mapped_column(nullable=True)

    item: Mapped[Item] = relationship()

    __table_args__ = (
        UniqueConstraint("batch_id", "item_id", name="uq_product_traffic_batch_item"),
        Index("idx_product_traffic_batch_items_batch_position", "batch_id", "position"),
    )


class ProductTrafficCheckpoint(Base):
    __tablename__ = "product_traffic_checkpoints"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_batches.id"), index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    checkpoint: Mapped[str] = mapped_column(String(16), index=True)
    browse_count: Mapped[int] = mapped_column(Integer, default=0)
    collect_count: Mapped[int] = mapped_column(Integer, default=0)
    want_count: Mapped[int] = mapped_column(Integer, default=0)
    inquiry_count: Mapped[int] = mapped_column(Integer, default=0)
    recorded_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    note: Mapped[str] = mapped_column(Text, default="")

    item: Mapped[Item] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "item_id",
            "checkpoint",
            name="uq_product_traffic_checkpoint",
        ),
        Index(
            "idx_product_traffic_checkpoints_batch_checkpoint",
            "batch_id",
            "checkpoint",
        ),
    )


class ProductTrafficReminderLog(Base):
    __tablename__ = "product_traffic_reminder_logs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_batches.id"), index=True
    )
    reminder_type: Mapped[str] = mapped_column(String(32), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(index=True)
    sent_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "batch_id", "reminder_type", name="uq_product_traffic_reminder"
        ),
        Index(
            "idx_product_traffic_reminders_schedule",
            "scheduled_for",
            "sent_at",
        ),
    )


class ProductMarketKeywordPlan(Base):
    """One deterministic keyword decision for each Beijing calendar day."""

    __tablename__ = "product_market_keyword_plans"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    plan_date: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(32), default="recommended", index=True)
    selected_keyword: Mapped[str] = mapped_column(String(120), default="")
    custom_keyword: Mapped[str] = mapped_column(String(120), default="")
    recommended_candidates_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    rules_version: Mapped[str] = mapped_column(String(32), default="market-v1")
    save_as_common: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ProductMarketSample(Base):
    """Sanitized public search observations imported from the user's Edge tab."""

    __tablename__ = "product_market_samples"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    keyword: Mapped[str] = mapped_column(String(120), index=True)
    sample_date: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(32), default="edge_codex")
    captured_at: Mapped[datetime] = mapped_column(index=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("keyword", "sample_date", name="uq_product_market_sample_keyword_day"),
        Index("idx_product_market_samples_keyword_date", "keyword", "sample_date"),
    )


class ProductMarketSampleResult(Base):
    __tablename__ = "product_market_sample_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("product_market_samples.id"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")

    sample: Mapped[ProductMarketSample] = relationship()

    __table_args__ = (
        UniqueConstraint("sample_id", "position", name="uq_product_market_result_position"),
        Index("idx_product_market_results_sample_position", "sample_id", "position"),
    )


class ProductMarketReminderLog(Base):
    """Mutable, deduplicated reminder state for one Beijing day."""

    __tablename__ = "product_market_reminder_logs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    reminder_date: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="sent", index=True)
    scheduled_for: Mapped[datetime] = mapped_column(index=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ProductLaunchPlan(Base):
    """A trackable manual listing plan; it never publishes to Xianyu."""

    __tablename__ = "product_launch_plans"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    keyword: Mapped[str] = mapped_column(String(120), index=True)
    theme: Mapped[str] = mapped_column(String(120), default="")
    title: Mapped[str] = mapped_column(String(500))
    recommended_window: Mapped[str] = mapped_column(String(120), default="")
    rationale_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    status: Mapped[str] = mapped_column(String(32), default="proposed", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ProductModificationExperiment(Base):
    """One-variable manual listing experiment with a frozen baseline."""

    __tablename__ = "product_modification_experiments"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    variable: Mapped[str] = mapped_column(String(32), index=True)
    before_value: Mapped[str] = mapped_column(Text)
    after_value: Mapped[str] = mapped_column(Text)
    baseline_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(index=True)
    observation_until: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(32), default="observing", index=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    decision: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    item: Mapped[Item] = relationship()

    __table_args__ = (
        Index(
            "idx_product_modification_item_status_until",
            "item_id",
            "status",
            "observation_until",
        ),
    )
