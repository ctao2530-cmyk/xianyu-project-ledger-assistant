"""Durable per-image capture work; media references are encrypted locally."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import utcnow


class CustomerImageCaptureJob(Base):
    __tablename__ = "customer_image_capture_jobs"
    archive_id: Mapped[str] = mapped_column(ForeignKey("customer_image_archives.id"), primary_key=True)
    encrypted_media: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    source_item_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
