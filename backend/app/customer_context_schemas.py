from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CustomerContextGrantCreate(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    thread_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=1)
    provider_scope: Literal["openai"] = "openai"
    audience: Literal["openai_chatgpt", "openai_api", "codex_cli"]
    allow_text: bool = True
    allow_images: bool = False
    allow_artifacts: bool = True
    allow_new_messages: bool = True
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800)
    authorization_note: str = Field(min_length=2, max_length=2000)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def require_scope(self) -> "CustomerContextGrantCreate":
        if not self.allow_text and not self.allow_images and not self.allow_artifacts:
            raise ValueError("至少需要授权文字、图片或需求成果中的一项")
        return self


class CustomerConversationGrantCreate(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    conversation_id: int = Field(ge=1)
    expected_revision: int = Field(ge=0)
    provider_scope: Literal["openai"] = "openai"
    audience: Literal["openai_chatgpt", "openai_api", "codex_cli"]
    allow_text: bool = True
    allow_images: bool = False
    allow_artifacts: bool = True
    allow_new_messages: bool = True
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800)
    authorization_note: str = Field(min_length=2, max_length=2000)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def require_scope(self) -> "CustomerConversationGrantCreate":
        if not self.allow_text and not self.allow_images and not self.allow_artifacts:
            raise ValueError("至少需要授权文字、图片或需求成果中的一项")
        return self


class CustomerContextGrantRevoke(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=1000)
    confirmed: Literal[True]


class CustomerContextGrantView(StrictModel):
    id: str
    thread_id: str
    conversation_id: int
    provider_scope: Literal["openai"]
    audience: Literal["openai_chatgpt", "openai_api", "codex_cli"]
    allow_text: bool
    allow_images: bool
    allow_artifacts: bool
    allow_new_messages: bool
    consent_policy_version: str
    consent_text_hash: str
    status: Literal["active", "expired", "revoked"]
    revision: int
    thread_revision: int
    authorization_note: str
    confirmed_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    capability_token: str | None = None
    idempotent: bool = False


class CustomerConversationAccessView(StrictModel):
    conversation_id: int
    revision: int
    latest_grant: CustomerContextGrantView | None = None


class CustomerContextTunnelBindingCreate(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    conversation_id: int = Field(ge=1)
    expected_binding_revision: int = Field(ge=0)
    expected_conversation_revision: int = Field(ge=0)
    allow_text: bool = True
    allow_images: bool = False
    allow_artifacts: bool = False
    allow_new_messages: bool = True
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800)
    authorization_note: str = Field(min_length=2, max_length=2000)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def require_scope(self) -> "CustomerContextTunnelBindingCreate":
        if not self.allow_text and not self.allow_images and not self.allow_artifacts:
            raise ValueError("至少需要授权文字、图片或需求成果中的一项")
        return self


class CustomerContextTunnelBindingRevoke(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_binding_revision: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=1000)
    confirmed: Literal[True]


class CustomerContextTunnelBindingView(StrictModel):
    auth_mode: Literal["oauth", "tunnel_binding"]
    configured: bool
    header_name: str
    slot: Literal["openai_chatgpt"]
    revision: int
    active: bool
    grant: CustomerContextGrantView | None = None
    idempotent: bool = False


class CustomerContextThreadBindingCreate(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    conversation_id: int = Field(ge=1)
    expected_conversation_revision: int = Field(ge=0)
    group_id: str | None = Field(default=None, max_length=128)
    expected_group_revision: int | None = Field(default=None, ge=1)
    selected_conversation_ids: list[int] | None = Field(default=None, max_length=100)
    allow_text: bool = True
    allow_images: bool = False
    allow_artifacts: bool = False
    allow_new_messages: bool = True
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800)
    authorization_note: str = Field(min_length=2, max_length=2000)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def require_scope(self) -> "CustomerContextThreadBindingCreate":
        if not self.allow_text and not self.allow_images and not self.allow_artifacts:
            raise ValueError("至少需要授权文字、图片或需求成果中的一项")
        return self


class CustomerContextThreadBindingRevoke(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=1000)
    confirmed: Literal[True]


class CustomerContextThreadBindingView(StrictModel):
    id: str
    auth_mode: Literal["oauth", "tunnel_binding"]
    context_key_hint: str
    status: Literal["active", "expired", "revoked"]
    revision: int
    active: bool
    identity_claimed: bool
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime
    grant: CustomerContextGrantView | None = None
    context_key: str | None = None
    idempotent: bool = False
    group_id: str | None = None
    group_revision: int | None = None
    selected_conversation_ids: list[int] | None = None


class CustomerContextThreadBindingListView(StrictModel):
    auth_mode: Literal["oauth", "tunnel_binding"]
    configured: bool
    legacy_binding_active: bool = False
    legacy_grant: CustomerContextGrantView | None = None
    bindings: list[CustomerContextThreadBindingView]


class CustomerContextAccessAuditView(StrictModel):
    id: str
    request_id: str
    grant_id: str | None
    grant_revision: int | None
    thread_id: str
    conversation_id: int | None
    provider: str
    audience: str
    target_model: str
    tool_name: str
    requested_scopes: list[str]
    request_hash: str
    status: Literal["authorized", "completed", "failed", "denied"]
    summary_version: int | None
    watermark_before: int | None
    watermark_after: int | None
    text_message_count: int
    image_count: int
    byte_count: int
    resource_hashes: list[str]
    source_hash: str
    error_code: str
    duration_ms: int
    created_at: datetime
    completed_at: datetime | None
