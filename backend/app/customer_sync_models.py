"""Sync progress is durable; none of these rows grants access."""
from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import utcnow


class CustomerContextSyncState(Base):
    __tablename__ = 'customer_context_sync_states'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_json: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(default=0)
    text_version: Mapped[int] = mapped_column(default=0)
    image_version: Mapped[int] = mapped_column(default=0)
    text_watermark: Mapped[int] = mapped_column(default=0)
    summary_watermark: Mapped[int] = mapped_column(default=0)
    summary_version: Mapped[int] = mapped_column(default=0)
    summary_json: Mapped[str] = mapped_column(Text, default='null')
    summary_source: Mapped[str] = mapped_column(Text, default='')
    image_versions_json: Mapped[str] = mapped_column(Text, default='{}')
    last_text_grant: Mapped[str] = mapped_column(String(128), default='')
    last_image_grant: Mapped[str] = mapped_column(String(128), default='')
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class CustomerContextReadBatch(Base):
    __tablename__ = 'customer_context_read_batches'
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    state_id: Mapped[str] = mapped_column(ForeignKey('customer_context_sync_states.id'), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    base_version: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default='pending')
    grant_id: Mapped[str] = mapped_column(String(128))
    payload_json: Mapped[str] = mapped_column(Text)
    image_reads_json: Mapped[str] = mapped_column(Text, default='[]')
    confirmation_hash: Mapped[str] = mapped_column(String(64), default='')
    summary_json: Mapped[str] = mapped_column(Text, default='null')
    result_json: Mapped[str] = mapped_column(Text, default='{}')
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (UniqueConstraint('state_id', 'kind', 'base_version', name='uq_customer_context_batch_version'),)
