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
    requirement_attachments: Mapped[list[MessageAttachment]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    customer_images: Mapped[list[CustomerImageArchive]] = relationship(
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
    # Snapshot only when supplied with this message; never backfill from current conversation.item_id.
    source_item_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    drafts: Mapped[list[Draft]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    ai_tasks: Mapped[list[AIGenerationTask]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    requirement_attachments: Mapped[list[MessageAttachment]] = relationship(
        back_populates="message"
    )
    customer_images: Mapped[list[CustomerImageArchive]] = relationship(
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


class MessageAttachment(Base):
    """A locally reviewed image that can be included in a requirement handoff."""

    __tablename__ = "message_attachments"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="manual")
    attachment_type: Mapped[str] = mapped_column(String(32), default="image")
    mime_type: Mapped[str] = mapped_column(String(128))
    original_name: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    privacy_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    conversation: Mapped[Conversation] = relationship(
        back_populates="requirement_attachments"
    )
    message: Mapped[Message | None] = relationship(
        back_populates="requirement_attachments"
    )

    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "message_id",
            "sha256",
            name="uq_message_attachment_conversation_message_sha256",
        ),
        Index(
            "idx_message_attachments_conversation_sort",
            "conversation_id",
            "sort_order",
        ),
    )


class CustomerImageArchive(Base):
    """Immutable original bytes received from a customer image message.

    This archive is intentionally separate from ``MessageAttachment``.  The
    latter is a reviewed requirement-handoff derivative that may be normalized;
    this table points only to byte-for-byte original local copies.
    """

    __tablename__ = "customer_image_archives"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id"), index=True
    )
    channel: Mapped[str] = mapped_column(String(32), index=True)
    platform_message_id: Mapped[str] = mapped_column(String(255))
    media_index: Mapped[int] = mapped_column(Integer, default=0)
    capture_status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True
    )
    capture_source: Mapped[str] = mapped_column(String(32), default="live")
    mime_type: Mapped[str] = mapped_column(String(128), default="")
    original_name: Mapped[str] = mapped_column(String(255), default="")
    storage_path: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    integrity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    captured_at: Mapped[datetime | None] = mapped_column(nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="customer_images")
    message: Mapped[Message] = relationship(back_populates="customer_images")

    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "media_index",
            name="uq_customer_image_archive_message_index",
        ),
        Index(
            "idx_customer_image_archives_status_received",
            "capture_status",
            "received_at",
        ),
        Index(
            "idx_customer_image_archives_channel_platform",
            "channel",
            "platform_message_id",
        ),
    )


class CustomerImageHistoryRecoveryRun(Base):
    """Persistent receipt for one user-triggered history-image recovery run."""

    __tablename__ = "customer_image_history_recovery_runs"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


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


class ConversationHistoryImportRequest(Base):
    """Idempotency receipt for one explicitly confirmed history import.

    Only a payload hash and the sanitized result are retained. Previewed customer
    messages stay in the short-lived in-memory token store and are never copied
    into this audit table.
    """

    __tablename__ = "conversation_history_import_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    preview_token_hash: Mapped[str] = mapped_column(String(64))
    mark_latest_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
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
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_projects.id"), nullable=True, index=True
    )
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0")
    source_type: Mapped[str] = mapped_column(String(32), default="codex_cli")
    source_label: Mapped[str] = mapped_column(String(255), default="Codex 生成")
    imported_at: Mapped[datetime | None] = mapped_column(nullable=True)
    source_filename: Mapped[str] = mapped_column(String(255), default="", server_default="")
    source_sha256: Mapped[str] = mapped_column(
        String(64), default="", server_default="", index=True
    )
    import_metadata_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
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
            "uq_requirement_project_version_partial",
            "project_id",
            "version",
            unique=True,
            sqlite_where=project_id.is_not(None),
        ),
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
    current_need: Mapped[str] = mapped_column(Text, default="", server_default="")
    price_type: Mapped[str] = mapped_column(String(32), default="", server_default="")
    price_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_action: Mapped[str] = mapped_column(Text, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
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
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("items.id"), nullable=True, index=True
    )
    requirement_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_document_versions.id"), nullable=True
    )
    quote_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0)
    start_date: Mapped[str] = mapped_column(String(32), default="")
    due_date: Mapped[str] = mapped_column(String(32), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    # ``progress`` is the verified-delivery percentage.  Pre-phase-four values
    # are retained separately instead of being presented as verified evidence.
    legacy_progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_source: Mapped[str] = mapped_column(
        String(32), default="verified", server_default="verified", index=True
    )
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
    task_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    stage_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    workspace_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    dependency_task_keys_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]"
    )
    deliverables_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    requirement_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_document_versions.id"), nullable=True, index=True
    )
    codex_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_development_plans.id"), nullable=True, index=True
    )
    acceptance_points_json: Mapped[str] = mapped_column(Text, default="[]")
    test_commands_json: Mapped[str] = mapped_column(Text, default="[]")
    # Codex execution state is intentionally independent from the human task
    # lifecycle in ``status``.  In particular, ``implemented`` never means the
    # task has been verified or delivered.
    codex_execution_status: Mapped[str] = mapped_column(
        String(32), default="todo", server_default="todo", index=True
    )
    codex_implemented_at: Mapped[datetime | None] = mapped_column(nullable=True)
    delivery_scope_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", index=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("project_id", "task_key", name="uq_business_task_project_task_key"),
    )


class ProjectTaskDraftPreview(Base):
    """Immutable task-diff preview tied to one blueprint and ledger revision."""

    __tablename__ = "project_task_draft_previews"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id", ondelete="CASCADE"), index=True
    )
    requirement_version_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_document_versions.id", ondelete="CASCADE"), index=True
    )
    project_revision: Mapped[int] = mapped_column(Integer, index=True)
    blueprint_hash: Mapped[str] = mapped_column(String(64))
    preview_token_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="open", server_default="open", index=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ProjectTaskDraftItem(Base):
    __tablename__ = "project_task_draft_items"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    preview_id: Mapped[str] = mapped_column(
        ForeignKey("project_task_draft_previews.id", ondelete="CASCADE"), index=True
    )
    task_key: Mapped[str] = mapped_column(String(128))
    workspace_key: Mapped[str] = mapped_column(String(128), default="", server_default="")
    stage_key: Mapped[str] = mapped_column(String(128), default="", server_default="")
    classification: Mapped[str] = mapped_column(String(32), index=True)
    current_payload_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    proposed_payload_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    protected_fields_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    conflict_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    selected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    ordinal: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint("preview_id", "task_key", name="uq_task_draft_preview_task_key"),
    )


class CodexProjectBinding(Base):
    """A user-approved local Git repository available to read-only planning."""

    __tablename__ = "codex_project_bindings"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_projects.id"), nullable=True, index=True
    )
    requirement_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("requirement_cases.id"), nullable=True, index=True
    )
    repository_path: Mapped[str] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(String(255), default="")
    planning_worktree_path: Mapped[str] = mapped_column(Text, default="")
    current_head_sha: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "requirement_case_id", "repository_path", name="uq_codex_binding_case_repository"
        ),
    )


class CodexDevelopmentPlan(Base):
    """Immutable Codex output plus a separately editable human-confirmation copy."""

    __tablename__ = "codex_development_plans"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    requirement_case_id: Mapped[str] = mapped_column(
        ForeignKey("requirement_cases.id"), index=True
    )
    requirement_version_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_document_versions.id"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_projects.id"), nullable=True, index=True
    )
    binding_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_project_bindings.id"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    source: Mapped[str] = mapped_column(String(32), default="codex_cli")
    repository_mode: Mapped[str] = mapped_column(String(32), default="requirement_only")
    repository_head_sha: Mapped[str] = mapped_column(String(64), default="")
    repository_branch: Mapped[str] = mapped_column(String(255), default="")
    repository_dirty: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_structured_json: Mapped[str] = mapped_column(Text)
    structured_json: Mapped[str] = mapped_column(Text)
    estimate_low_hours: Mapped[float] = mapped_column(Float)
    estimate_expected_hours: Mapped[float] = mapped_column(Float)
    estimate_high_hours: Mapped[float] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(128), default="")
    reasoning_effort: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "requirement_case_id", "version", name="uq_codex_plan_case_version"
        ),
    )


class CodexPlanMutationRequest(Base):
    """Idempotency audit for repository bindings and plan mutations."""

    __tablename__ = "codex_plan_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class CodexRun(Base):
    """One external or Xunying-managed Codex session."""

    __tablename__ = "codex_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id", ondelete="CASCADE"), index=True
    )
    binding_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_project_bindings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), default="mcp", index=True)
    external_session_id: Mapped[str] = mapped_column(String(255), index=True)
    external_turn_id: Mapped[str] = mapped_column(String(255), default="")
    runtime_type: Mapped[str] = mapped_column(String(32), default="external", server_default="external", index=True)
    thread_id: Mapped[str] = mapped_column(String(255), default="", server_default="", index=True)
    turn_id: Mapped[str] = mapped_column(String(255), default="", server_default="")
    task_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    base_commit_sha: Mapped[str] = mapped_column(String(64), default="", server_default="")
    branch: Mapped[str] = mapped_column(String(255), default="", server_default="")
    worktree_path: Mapped[str] = mapped_column(Text, default="", server_default="")
    model: Mapped[str] = mapped_column(String(128), default="", server_default="")
    reasoning_effort: Mapped[str] = mapped_column(String(32), default="", server_default="")
    sandbox_mode: Mapped[str] = mapped_column(String(32), default="", server_default="")
    approval_mode: Mapped[str] = mapped_column(String(32), default="", server_default="")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    paused_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_event_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source",
            "external_session_id",
            name="uq_codex_run_project_source_session",
        ),
    )


class CodexRunApproval(Base):
    """One persisted App Server callback awaiting an explicit human decision."""

    __tablename__ = "codex_run_approvals"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("codex_runs.id", ondelete="CASCADE"), index=True
    )
    server_request_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    thread_id: Mapped[str] = mapped_column(String(255), default="")
    turn_id: Mapped[str] = mapped_column(String(255), default="")
    item_id: Mapped[str] = mapped_column(String(255), default="")
    approval_kind: Mapped[str] = mapped_column(String(32), default="command")
    risk_level: Mapped[str] = mapped_column(String(32), default="high", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    command: Mapped[str] = mapped_column(Text, default="")
    cwd: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class CodexRuntimeMutationRequest(Base):
    """Idempotency audit for managed run mutations."""

    __tablename__ = "codex_runtime_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class CodexEvent(Base):
    """Validated, redacted and immutable external Codex event envelope."""

    __tablename__ = "codex_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("codex_runs.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    tool_name: Mapped[str] = mapped_column(String(128), default="")
    task_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(index=True)
    received_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("idx_codex_events_run_occurred", "run_id", "occurred_at"),
    )


class CodexTaskEvidence(Base):
    """Bounded task evidence derived from one persisted Codex event."""

    __tablename__ = "codex_task_evidence"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("codex_runs.id", ondelete="CASCADE"), index=True
    )
    event_record_id: Mapped[str] = mapped_column(
        ForeignKey("codex_events.id", ondelete="CASCADE"), unique=True, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    evidence_type: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    files_json: Mapped[str] = mapped_column(Text, default="[]")
    remaining_work: Mapped[str] = mapped_column(Text, default="")
    blocker: Mapped[str] = mapped_column(Text, default="")
    command: Mapped[str] = mapped_column(Text, default="")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class CodexAcceptancePoint(Base):
    """One stable, auditable acceptance point for the current delivery scope."""

    __tablename__ = "codex_acceptance_points"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_development_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    point_key: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(300))
    verification_type: Mapped[str] = mapped_column(String(32), default="manual_test")
    source: Mapped[str] = mapped_column(
        String(32), default="codex_plan", server_default="codex_plan", index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", index=True
    )
    point_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    waived_counts: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    waiver_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "task_id", "point_key", name="uq_codex_acceptance_task_point_key"
        ),
    )


class CodexAcceptanceEvidence(Base):
    """Immutable evidence; natural-language completion claims are not verification."""

    __tablename__ = "codex_acceptance_evidence"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="CASCADE"), index=True
    )
    point_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_acceptance_points.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    point_key: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(64), index=True)
    file_paths_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    test_command: Mapped[str] = mapped_column(Text, default="", server_default="")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    commit_sha: Mapped[str] = mapped_column(String(64), default="", server_default="")
    manual_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(32), default="recorded", server_default="recorded", index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "source_event_id",
            "point_id",
            name="uq_codex_acceptance_evidence_event_point",
        ),
    )


class CodexAcceptanceStatusHistory(Base):
    """Append-only audit of every acceptance-state transition."""

    __tablename__ = "codex_acceptance_status_history"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    point_id: Mapped[str] = mapped_column(
        ForeignKey("codex_acceptance_points.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_acceptance_evidence.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class CodexAcceptanceMutationRequest(Base):
    """Idempotency receipt for human acceptance and evidence mutations."""

    __tablename__ = "codex_acceptance_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class CodexRunActivityInterval(Base):
    """One countable active interval; pause and approval waits never belong here."""

    __tablename__ = "codex_run_activity_intervals"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("codex_runs.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(index=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    stop_reason: Mapped[str] = mapped_column(String(32), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ProjectTimeEntry(Base):
    """Immutable time ledger; corrections are additional adjustment entries."""

    __tablename__ = "project_time_entries"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    activity_interval_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_run_activity_intervals.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    adjustment_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_time_entries.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    hours: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ProjectTimeMutationRequest(Base):
    """Idempotency receipt for manual time entries and corrections."""

    __tablename__ = "project_time_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ProjectOutcomeFreeze(Base):
    """Append-only, immutable project outcome used by future calibration runs."""

    __tablename__ = "project_outcome_freezes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    supersedes_freeze_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_outcome_freezes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_ledger_revision: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    outcome_json: Mapped[str] = mapped_column(Text)
    evidence_summary_json: Mapped[str] = mapped_column(
        Text, default="{}", server_default="{}"
    )
    confirmed_scope_complete: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1"
    )
    confirmed_time_complete: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1"
    )
    confirmation_note: Mapped[str] = mapped_column(Text)
    frozen_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "project_id", "version", name="uq_project_outcome_freeze_version"
        ),
        Index(
            "idx_project_outcome_freezes_project_created",
            "project_id",
            "created_at",
        ),
    )


class ProjectOutcomeFreezeMutationRequest(Base):
    """Idempotency receipt for manual scope and outcome-freeze operations."""

    __tablename__ = "project_outcome_freeze_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ProjectGitLink(Base):
    """A local, read-only association between delivery scope and one commit."""

    __tablename__ = "project_git_links"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("business_projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="CASCADE"), index=True
    )
    point_id: Mapped[str | None] = mapped_column(
        ForeignKey("codex_acceptance_points.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    commit_sha: Mapped[str] = mapped_column(String(64), index=True)
    branch: Mapped[str] = mapped_column(String(255), default="", server_default="")
    status: Mapped[str] = mapped_column(String(32), default="committed", index=True)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


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


# Immutable prediction snapshots. Prediction records are read-only evidence:
# they never authorize customer, project, finance, quote, or listing writes.


class PredictionRun(Base):
    __tablename__ = "prediction_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(index=True)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    ledger_revision: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    feature_schema_version: Mapped[str] = mapped_column(String(32))
    engine_version: Mapped[str] = mapped_column(String(32))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("idx_prediction_runs_status_generated", "status", "generated_at"),
    )


class PredictionResultRecord(Base):
    __tablename__ = "prediction_results"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("prediction_runs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    target: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    entity_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    horizon: Mapped[str] = mapped_column(String(32))
    horizon_days: Mapped[int] = mapped_column(Integer)
    horizon_start: Mapped[datetime] = mapped_column(index=True)
    horizon_end: Mapped[datetime] = mapped_column(index=True)
    prediction_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    lower_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    data_sufficiency: Mapped[str] = mapped_column(String(16), index=True)
    method: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)
    drivers_json: Mapped[str] = mapped_column(Text, default="[]")
    facts_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    input_features_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("idx_prediction_results_run_position", "run_id", "position"),
        Index("idx_prediction_results_target_entity", "target", "entity_type", "entity_id"),
    )


class PredictionEvaluationRecord(Base):
    __tablename__ = "prediction_evaluations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    result_id: Mapped[str] = mapped_column(
        ForeignKey("prediction_results.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    actual_value_json: Mapped[str] = mapped_column(Text)
    evaluation_method: Mapped[str] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("idx_prediction_evaluations_result_time", "result_id", "evaluated_at"),
    )


# Estimate calibration is an evidence layer on top of verified project outcomes.
# Samples and runs are immutable. Suggestions keep only a revision-guarded
# decision projection; every human decision is preserved append-only below.


class EstimateCalibrationSample(Base):
    __tablename__ = "estimate_calibration_samples"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    project_name: Mapped[str] = mapped_column(String(300))
    source_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    supersedes_sample_id: Mapped[str | None] = mapped_column(
        ForeignKey("estimate_calibration_samples.id", ondelete="SET NULL"),
        nullable=True,
    )
    estimate_source: Mapped[str] = mapped_column(
        String(64), default="business_project", server_default="business_project"
    )
    estimated_hours: Mapped[float] = mapped_column(Float)
    actual_hours: Mapped[float] = mapped_column(Float)
    signed_error_hours: Mapped[float] = mapped_column(Float)
    absolute_error_hours: Mapped[float] = mapped_column(Float)
    actual_to_estimate_ratio: Mapped[float] = mapped_column(Float)
    estimated_delivery_at: Mapped[str] = mapped_column(String(64), default="")
    actual_completed_at: Mapped[datetime] = mapped_column(index=True)
    requirement_complexity: Mapped[float | None] = mapped_column(Float, nullable=True)
    blocker_count: Mapped[int] = mapped_column(Integer, default=0)
    change_order_count: Mapped[int] = mapped_column(Integer, default=0)
    test_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    rework_hours: Mapped[float] = mapped_column(Float, default=0)
    verified_progress: Mapped[int] = mapped_column(Integer, default=100)
    available_at: Mapped[datetime] = mapped_column(index=True)
    finalized_at: Mapped[datetime] = mapped_column(index=True)
    cutoff_at: Mapped[datetime] = mapped_column(index=True)
    outcome_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index(
            "idx_estimate_calibration_samples_project_cutoff",
            "project_id",
            "cutoff_at",
        ),
    )


class EstimateCalibrationRun(Base):
    __tablename__ = "estimate_calibration_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    cutoff_at: Mapped[datetime] = mapped_column(index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    sufficiency: Mapped[str] = mapped_column(String(32), index=True)
    signed_bias_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    overrun_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    interval_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    multiplier_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    multiplier_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    multiplier_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    algorithm_version: Mapped[str] = mapped_column(String(64))
    sample_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("idx_estimate_calibration_runs_cutoff", "cutoff_at", "created_at"),
    )


class EstimateCalibrationSuggestion(Base):
    __tablename__ = "estimate_calibration_suggestions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("estimate_calibration_runs.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    project_name: Mapped[str] = mapped_column(String(300))
    original_estimated_hours: Mapped[float] = mapped_column(Float)
    suggested_hours: Mapped[float] = mapped_column(Float)
    lower_hours: Mapped[float] = mapped_column(Float)
    upper_hours: Mapped[float] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer)
    sample_start_at: Mapped[datetime] = mapped_column(index=True)
    sample_end_at: Mapped[datetime] = mapped_column(index=True)
    basis_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    invalidation_conditions_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", index=True
    )
    adopted_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "project_id", name="uq_estimate_calibration_run_project"
        ),
        Index(
            "idx_estimate_calibration_suggestions_project_created",
            "project_id",
            "created_at",
        ),
    )


class EstimateCalibrationDecision(Base):
    __tablename__ = "estimate_calibration_decisions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    suggestion_id: Mapped[str] = mapped_column(
        ForeignKey("estimate_calibration_suggestions.id", ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    expected_revision: Mapped[int] = mapped_column(Integer)
    resulting_revision: Mapped[int] = mapped_column(Integer)
    adopted_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index(
            "idx_estimate_calibration_decisions_suggestion_time",
            "suggestion_id",
            "created_at",
        ),
    )


class EstimateCalibrationMutationRequest(Base):
    __tablename__ = "estimate_calibration_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


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


class ProductRegistrationRequest(Base):
    """Idempotency receipt for a user-confirmed product registration batch."""

    __tablename__ = "product_registration_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


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
    change_factors_json: Mapped[str] = mapped_column(Text, default="[]")
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
    change_factors_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    locked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    # Deliberately kept as a service-validated identifier instead of a database
    # foreign key: traffic batches already reference plan slots, and introducing
    # the reverse SQLite FK would make additive upgrades cyclic.  The service
    # only writes an existing source batch and clears stale references when a
    # plan is rebuilt.
    source_batch_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    availability_at: Mapped[datetime | None] = mapped_column(nullable=True)
    is_new_spend: Mapped[bool] = mapped_column(Boolean, default=False)
    rotation_summary_json: Mapped[str] = mapped_column(Text, default="{}")
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
    baseline_prepared_at: Mapped[datetime | None] = mapped_column(nullable=True)
    recording_mode: Mapped[str] = mapped_column(
        String(32), default="standard", server_default="standard"
    )
    attribution_status: Mapped[str] = mapped_column(
        String(32), default="clean", server_default="clean"
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    invalidation_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    checkpoint_collection_mode: Mapped[str] = mapped_column(
        String(32), default="auto", server_default="auto", index=True
    )
    # Existing rows and the legacy plan-driven flow retain the original 72h
    # protocol.  The actual-now flow writes 48 explicitly, so protocol choice
    # is immutable per batch rather than inferred from dates or UI state.
    observation_window_hours: Mapped[int] = mapped_column(
        Integer, default=72, server_default="72"
    )
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
    baseline_source: Mapped[str] = mapped_column(String(32), default="pending")

    item: Mapped[Item] = relationship()

    __table_args__ = (
        UniqueConstraint("batch_id", "item_id", name="uq_product_traffic_batch_item"),
        Index("idx_product_traffic_batch_items_batch_position", "batch_id", "position"),
    )


class ProductTrafficBatchEvent(Base):
    """Idempotent, redacted audit record for traffic-batch mutations."""

    __tablename__ = "product_traffic_batch_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_batches.id"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index(
            "idx_product_traffic_batch_events_batch_created",
            "batch_id",
            "created_at",
        ),
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


class ProductTrafficCheckpointJob(Base):
    """Persistent execution state for one paid-exposure checkpoint."""

    __tablename__ = "product_traffic_checkpoint_jobs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_batches.id"), index=True
    )
    checkpoint: Mapped[str] = mapped_column(String(16), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(32), default="scheduled", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    collected_count: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    capture_delay_minutes: Mapped[int | None] = mapped_column(nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "batch_id", "checkpoint", name="uq_product_traffic_checkpoint_job"
        ),
        Index(
            "idx_product_traffic_checkpoint_jobs_due",
            "status",
            "scheduled_for",
        ),
    )


class ProductTrafficCheckpointJobItem(Base):
    """Per-listing outcome so partial collections can resume safely."""

    __tablename__ = "product_traffic_checkpoint_job_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_checkpoint_jobs.id"), index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    captured_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    item: Mapped[Item] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "job_id", "item_id", name="uq_product_traffic_checkpoint_job_item"
        ),
        Index(
            "idx_product_traffic_checkpoint_job_items_status",
            "job_id",
            "status",
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


class ProductTrafficExperiment(Base):
    """One user-approved paid-exposure growth experiment for an owned listing."""

    __tablename__ = "product_traffic_experiments"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    mode: Mapped[str] = mapped_column(String(32), default="time_test", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    phase: Mapped[str] = mapped_column(String(32), default="exploration", index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    target_windows_json: Mapped[str] = mapped_column(Text, default='["12","16","20"]')
    baseline_weekly_budget: Mapped[float] = mapped_column(Float, default=24)
    current_weekly_budget: Mapped[float] = mapped_column(Float, default=24)
    hard_weekly_cap: Mapped[float] = mapped_column(Float, default=48)
    base_batch_cost: Mapped[float] = mapped_column(Float, default=5.9)
    profit_ratio_scale_threshold: Mapped[float] = mapped_column(Float, default=5)
    profit_ratio_hold_threshold: Mapped[float] = mapped_column(Float, default=2)
    profit_ratio_break_even: Mapped[float] = mapped_column(Float, default=1)
    min_attributed_inquiries: Mapped[int] = mapped_column(Integer, default=3)
    min_paid_projects: Mapped[int] = mapped_column(Integer, default=2)
    min_realized_profit: Mapped[float] = mapped_column(Float, default=120)
    cohort_days: Mapped[int] = mapped_column(Integer, default=14)
    tail_days: Mapped[int] = mapped_column(Integer, default=7)
    commercial_followup_days: Mapped[int] = mapped_column(Integer, default=14)
    started_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    item: Mapped[Item] = relationship()

    __table_args__ = (
        Index(
            "idx_product_traffic_experiments_item_status",
            "item_id",
            "status",
        ),
    )


class ProductTrafficExperimentCell(Base):
    """One required replication in the clean Beijing-time experiment matrix."""

    __tablename__ = "product_traffic_experiment_cells"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_experiments.id"), index=True
    )
    phase: Mapped[str] = mapped_column(String(32), default="exploration", index=True)
    window_bucket: Mapped[str] = mapped_column(String(2), index=True)
    repeat_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_traffic_batches.id"), nullable=True, unique=True, index=True
    )
    actual_bucket: Mapped[str | None] = mapped_column(String(2), nullable=True)
    exclusion_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            "phase",
            "window_bucket",
            "repeat_index",
            name="uq_product_traffic_experiment_cell",
        ),
        Index(
            "idx_product_traffic_experiment_cells_status_schedule",
            "status",
            "scheduled_for",
        ),
    )


class ProductTrafficScaleCohort(Base):
    """A 14-day overlapping scale cohort evaluated only as one aggregate."""

    __tablename__ = "product_traffic_scale_cohorts"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_experiments.id"), index=True
    )
    stage: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    target_batches_per_week: Mapped[int] = mapped_column(Integer)
    weekly_budget: Mapped[float] = mapped_column(Float)
    no_other_promotion_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    listing_unchanged_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    tail_ends_at: Mapped[datetime | None] = mapped_column(nullable=True)
    commercial_followup_ends_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index(
            "idx_product_traffic_scale_cohorts_experiment_status",
            "experiment_id",
            "status",
        ),
    )


class ProductTrafficScaleCohortBatch(Base):
    __tablename__ = "product_traffic_scale_cohort_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_scale_cohorts.id"), index=True
    )
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_batches.id"), unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "cohort_id", "batch_id", name="uq_product_traffic_scale_cohort_batch"
        ),
    )


class ProductTrafficCommercialAttribution(Base):
    """Auditable conversation/project evidence linked to a batch or scale cohort."""

    __tablename__ = "product_traffic_commercial_attributions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    attribution_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_experiments.id"), index=True
    )
    cohort_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_traffic_scale_cohorts.id"), nullable=True, index=True
    )
    batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_traffic_batches.id"), nullable=True, index=True
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_projects.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    source: Mapped[str] = mapped_column(String(32), default="automatic")
    first_inbound_at: Mapped[datetime] = mapped_column(index=True)
    window_start: Mapped[datetime] = mapped_column()
    window_end: Mapped[datetime] = mapped_column()
    confirmed_by_user_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index(
            "idx_product_traffic_attributions_experiment_status",
            "experiment_id",
            "status",
        ),
        Index(
            "idx_product_traffic_attributions_scope_conversation",
            "batch_id",
            "cohort_id",
            "conversation_id",
        ),
    )


class ProductTrafficBudgetDecision(Base):
    """Immutable rule snapshot; applying it only changes future advisory budget."""

    __tablename__ = "product_traffic_budget_decisions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    decision_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("product_traffic_experiments.id"), index=True
    )
    cohort_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_traffic_scale_cohorts.id"), nullable=True, index=True
    )
    recommendation: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    from_stage: Mapped[str] = mapped_column(String(16))
    to_stage: Mapped[str] = mapped_column(String(16))
    current_weekly_budget: Mapped[float] = mapped_column(Float)
    recommended_weekly_budget: Mapped[float] = mapped_column(Float)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    rules_version: Mapped[str] = mapped_column(String(32), default="growth-v1")
    observation_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    observation_ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decided_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    applied_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ProductTrafficGrowthRequest(Base):
    """Idempotency ledger for experiment, attribution and budget mutations."""

    __tablename__ = "product_traffic_growth_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


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


# Local-only global Agent state. Model credentials never enter these tables;
# profiles contain only the provider/model choice that a user can audit later.


class GlobalAgentModelProfile(Base):
    __tablename__ = "global_agent_model_profiles"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128))
    reasoning_effort: Mapped[str] = mapped_column(String(32), default="")
    label: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "model",
            "reasoning_effort",
            name="uq_global_agent_model_profile_choice",
        ),
    )


class GlobalAgentThread(Base):
    __tablename__ = "global_agent_threads"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(240), default="新对话")
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("global_agent_model_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    reasoning_effort: Mapped[str] = mapped_column(String(32), default="")
    context_scope: Mapped[str] = mapped_column(
        String(32), default="general_business", index=True
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class GlobalAgentMessage(Base):
    __tablename__ = "global_agent_messages"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("global_agent_threads.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), index=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    run_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    tool_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index(
            "idx_global_agent_messages_thread_created",
            "thread_id",
            "created_at",
        ),
    )


class GlobalAgentRun(Base):
    __tablename__ = "global_agent_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("global_agent_threads.id", ondelete="CASCADE"), index=True
    )
    user_message_id: Mapped[str] = mapped_column(
        ForeignKey("global_agent_messages.id", ondelete="CASCADE"), index=True
    )
    assistant_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("global_agent_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128))
    reasoning_effort: Mapped[str] = mapped_column(String(32), default="")
    recheck_full_context: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class GlobalAgentRunStep(Base):
    """Persisted, redacted observability for one fixed LangGraph node."""

    __tablename__ = "global_agent_run_steps"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("global_agent_runs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    node_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "position", name="uq_global_agent_run_step_position"
        ),
    )


class GlobalAgentConversationSummary(Base):
    """Immutable versioned summary of one bound customer's text conversation."""

    __tablename__ = "global_agent_conversation_summaries"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    source_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("global_agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    summarized_through_message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), index=True
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_message_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "version",
            name="uq_global_agent_conversation_summary_version",
        ),
        Index(
            "idx_global_agent_conversation_summary_latest",
            "conversation_id",
            "version",
        ),
    )


class CustomerContextGrant(Base):
    """Short-lived operator authorization for one bound customer conversation."""

    __tablename__ = "customer_context_grants"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("global_agent_threads.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), index=True
    )
    provider_scope: Mapped[str] = mapped_column(String(32), default="openai", index=True)
    audience: Mapped[str] = mapped_column(String(32), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    allow_text: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_images: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_artifacts: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_new_messages: Mapped[bool] = mapped_column(Boolean, default=True)
    consent_policy_version: Mapped[str] = mapped_column(String(32), default="1")
    consent_text_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    authorization_note: Mapped[str] = mapped_column(Text, default="")
    confirmed_at: Mapped[datetime] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index(
            "idx_customer_context_grants_thread_status",
            "thread_id",
            "status",
        ),
    )


class CustomerContextOAuthBinding(Base):
    """Hashed OAuth access-token binding to one operator-approved grant."""

    __tablename__ = "customer_context_oauth_bindings"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    grant_id: Mapped[str] = mapped_column(
        ForeignKey("customer_context_grants.id", ondelete="CASCADE"), index=True
    )
    issuer: Mapped[str] = mapped_column(String(512))
    audience: Mapped[str] = mapped_column(String(512))
    subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    client_id_hash: Mapped[str] = mapped_column(String(64), index=True)
    scopes_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    issued_at: Mapped[datetime] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    last_used_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index(
            "idx_customer_context_oauth_binding_grant_expiry",
            "grant_id",
            "expires_at",
        ),
    )


class CustomerContextTunnelBinding(Base):
    """Current operator-approved grant exposed through one private tunnel slot."""

    __tablename__ = "customer_context_tunnel_bindings"

    slot: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[str] = mapped_column(
        ForeignKey("customer_context_grants.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, index=True)


class CustomerContextThreadBinding(Base):
    """Opaque per-ChatGPT-thread key bound to one approved customer grant."""

    __tablename__ = "customer_context_thread_bindings"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    context_key_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    context_key_hint: Mapped[str] = mapped_column(String(16), default="")
    grant_id: Mapped[str] = mapped_column(
        ForeignKey("customer_context_grants.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    auth_mode: Mapped[str] = mapped_column(String(32), index=True)
    owner_issuer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    owner_subject_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    owner_client_id_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, index=True
    )

    __table_args__ = (
        Index(
            "idx_customer_context_thread_binding_mode_status_expiry",
            "auth_mode",
            "status",
            "expires_at",
        ),
    )


class CustomerContextAccessAudit(Base):
    """Sanitized receipt for one customer-context access attempt."""

    __tablename__ = "customer_context_access_audits"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    grant_id: Mapped[str | None] = mapped_column(
        ForeignKey("customer_context_grants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    grant_revision: Mapped[int | None] = mapped_column(nullable=True)
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), default="openai", index=True)
    audience: Mapped[str] = mapped_column(String(32), default="", index=True)
    target_model: Mapped[str] = mapped_column(String(128), default="")
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    requested_scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    request_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    summary_version: Mapped[int | None] = mapped_column(nullable=True)
    watermark_before: Mapped[int | None] = mapped_column(nullable=True)
    watermark_after: Mapped[int | None] = mapped_column(nullable=True)
    text_message_count: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    byte_count: Mapped[int] = mapped_column(Integer, default=0)
    resource_hashes_json: Mapped[str] = mapped_column(Text, default="[]")
    source_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    error_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index(
            "idx_customer_context_access_thread_created",
            "thread_id",
            "created_at",
        ),
    )


class CustomerContextMutationRequest(Base):
    """Idempotency receipt for grant and revoke mutations only."""

    __tablename__ = "customer_context_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class CustomerAnalysisThread(Base):
    """Persistent OpenAI analysis subscription for one bound conversation."""

    __tablename__ = "customer_analysis_threads"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("global_agent_threads.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
    )
    provider_scope: Mapped[str] = mapped_column(
        String(32), default="openai", server_default="openai", index=True
    )
    model: Mapped[str] = mapped_column(String(128), default="", server_default="")
    external_conversation_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active", server_default="active", index=True
    )
    analysis_state: Mapped[str] = mapped_column(
        String(32), default="waiting", server_default="waiting", index=True
    )
    include_images: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    debounce_seconds: Mapped[int] = mapped_column(
        Integer, default=30, server_default="30"
    )
    max_wait_seconds: Mapped[int] = mapped_column(
        Integer, default=60, server_default="60"
    )
    last_enqueued_message_id: Mapped[int | None] = mapped_column(nullable=True)
    last_analyzed_message_id: Mapped[int | None] = mapped_column(nullable=True)
    latest_artifact_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    pending_since: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    next_run_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    last_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error_code: Mapped[str] = mapped_column(
        String(64), default="", server_default="", index=True
    )
    last_error_message: Mapped[str] = mapped_column(
        Text, default="", server_default=""
    )
    consent_policy_version: Mapped[str] = mapped_column(
        String(32), default="2", server_default="2"
    )
    consent_text_hash: Mapped[str] = mapped_column(String(64), index=True)
    authorization_note: Mapped[str] = mapped_column(
        Text, default="", server_default=""
    )
    confirmed_at: Mapped[datetime] = mapped_column(index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    paused_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index(
            "idx_customer_analysis_thread_due",
            "status",
            "analysis_state",
            "next_run_at",
        ),
    )


class CustomerAnalysisEvent(Base):
    """Transactional outbox event created in the same commit as a message."""

    __tablename__ = "customer_analysis_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_thread_id: Mapped[str] = mapped_column(
        ForeignKey("customer_analysis_threads.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), index=True
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), index=True
    )
    event_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("customer_analysis_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    processing_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "analysis_thread_id",
            "message_id",
            name="uq_customer_analysis_event_message",
        ),
        Index(
            "idx_customer_analysis_event_pending",
            "analysis_thread_id",
            "status",
            "message_id",
        ),
    )


class CustomerAnalysisRun(Base):
    """One idempotent incremental OpenAI analysis attempt."""

    __tablename__ = "customer_analysis_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_thread_id: Mapped[str] = mapped_column(
        ForeignKey("customer_analysis_threads.id", ondelete="CASCADE"), index=True
    )
    subscription_revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1"
    )
    run_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", index=True
    )
    watermark_before: Mapped[int | None] = mapped_column(nullable=True)
    watermark_after: Mapped[int] = mapped_column(Integer, index=True)
    source_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    provider: Mapped[str] = mapped_column(
        String(32), default="openai", server_default="openai", index=True
    )
    model: Mapped[str] = mapped_column(String(128), default="", server_default="")
    external_response_id: Mapped[str] = mapped_column(
        String(255), default="", server_default="", index=True
    )
    artifact_version: Mapped[int | None] = mapped_column(nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    image_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_code: Mapped[str] = mapped_column(
        String(64), default="", server_default="", index=True
    )
    error_message: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index(
            "idx_customer_analysis_run_thread_created",
            "analysis_thread_id",
            "created_at",
        ),
    )


class CustomerAnalysisArtifact(Base):
    """Append-only requirement document and execution plan snapshot."""

    __tablename__ = "customer_analysis_artifacts"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_thread_id: Mapped[str] = mapped_column(
        ForeignKey("customer_analysis_threads.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    previous_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("customer_analysis_artifacts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("customer_analysis_runs.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
    )
    watermark_before: Mapped[int | None] = mapped_column(nullable=True)
    watermark_after: Mapped[int] = mapped_column(Integer, index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_json: Mapped[str] = mapped_column(Text)
    diff_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    evidence_message_ids_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]"
    )
    evidence_image_ids_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]"
    )
    model: Mapped[str] = mapped_column(String(128), default="", server_default="")
    external_response_id: Mapped[str] = mapped_column(
        String(255), default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "analysis_thread_id",
            "version",
            name="uq_customer_analysis_artifact_version",
        ),
        Index(
            "idx_customer_analysis_artifact_latest",
            "analysis_thread_id",
            "version",
        ),
    )


class CustomerAnalysisMutationRequest(Base):
    """Idempotency receipt for persistent analysis subscription mutations."""

    __tablename__ = "customer_analysis_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class GlobalAgentToolCall(Base):
    __tablename__ = "global_agent_tool_calls"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("global_agent_runs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    arguments_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "position", name="uq_global_agent_tool_call_position"
        ),
    )


class GlobalAgentKnowledgeDocument(Base):
    __tablename__ = "global_agent_knowledge_documents"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    relative_path: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    absolute_path: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(500))
    maturity: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    exclusion_reason: Mapped[str] = mapped_column(String(500), default="")
    indexed_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class GlobalAgentKnowledgeChunk(Base):
    __tablename__ = "global_agent_knowledge_chunks"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("global_agent_knowledge_documents.id", ondelete="CASCADE"),
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "document_id", "ordinal", name="uq_global_agent_knowledge_chunk_order"
        ),
    )


class GlobalAgentMutationRequest(Base):
    __tablename__ = "global_agent_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class PhraseLibraryState(Base):
    __tablename__ = "phrase_library_states"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class PhraseCategory(Base):
    __tablename__ = "phrase_categories"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    category_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32), default="custom", index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    phrases: Mapped[list["PhraseSnippet"]] = relationship(
        back_populates="category"
    )


class PhraseSnippet(Base):
    __tablename__ = "phrase_snippets"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    category_id: Mapped[str] = mapped_column(
        ForeignKey("phrase_categories.id", ondelete="RESTRICT"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    category: Mapped[PhraseCategory] = relationship(back_populates="phrases")

    __table_args__ = (
        Index(
            "idx_phrase_snippets_category_position",
            "category_id",
            "position",
            "created_at",
        ),
    )


class PhraseLibraryMutationRequest(Base):
    __tablename__ = "phrase_library_mutation_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


# Register additive workflow models without duplicating the existing customer domain.
from . import customer_media_models, customer_conversation_models  # noqa: E402,F401
from . import customer_sync_models  # noqa: E402,F401
