"""Additive conversation views. Original customer/message ownership never moves."""
from datetime import datetime
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import utcnow


class CustomerConversationGroup(Base):
    __tablename__ = "customer_conversation_groups"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("business_customers.id"), index=True)
    revision: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class CustomerConversationGroupMember(Base):
    __tablename__ = "customer_conversation_group_members"
    group_id: Mapped[str] = mapped_column(ForeignKey("customer_conversation_groups.id"), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class CustomerConversationGroupPreview(Base):
    __tablename__ = "customer_conversation_group_previews"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column()


class CustomerConversationGroupMutation(Base):
    __tablename__ = "customer_conversation_group_mutations"
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("customer_conversation_groups.id"), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    before_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class CustomerContextGroupScope(Base):
    __tablename__ = "customer_context_group_scopes"
    grant_id: Mapped[str] = mapped_column(ForeignKey("customer_context_grants.id"), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("customer_conversation_groups.id"), index=True)
    group_revision: Mapped[int] = mapped_column()
    conversation_ids_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
