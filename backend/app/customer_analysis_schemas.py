from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .global_agent_schemas import (
    AgentCustomerConversationSummary,
    AgentExecutionPlan,
    AgentRequirementAnalysis,
    AgentRequirementBlueprint,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CustomerAnalysisSubscriptionUpsert(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    thread_id: str = Field(min_length=8, max_length=128)
    expected_thread_revision: int = Field(ge=1)
    expected_subscription_revision: int = Field(default=0, ge=0)
    provider_scope: Literal["openai"] = "openai"
    model: str = Field(default="", max_length=128)
    include_images: bool = False
    debounce_seconds: int = Field(default=30, ge=5, le=300)
    max_wait_seconds: int = Field(default=60, ge=10, le=600)
    authorization_note: str = Field(min_length=2, max_length=2000)
    confirmed_automatic_analysis: Literal[True]

    @model_validator(mode="after")
    def validate_wait_window(self) -> "CustomerAnalysisSubscriptionUpsert":
        if self.max_wait_seconds < self.debounce_seconds:
            raise ValueError("最长等待时间不得短于静默窗口")
        return self


class CustomerAnalysisSubscriptionPause(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=1000)
    confirmed: Literal[True]


class CustomerAnalysisRetryRequest(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_revision: int = Field(ge=1)
    confirmed: Literal[True]


class CustomerAnalysisSubscriptionView(StrictModel):
    id: str
    thread_id: str
    conversation_id: int
    provider_scope: Literal["openai"]
    model: str
    configured: bool
    external_conversation_ready: bool
    status: Literal["active", "paused"]
    analysis_state: Literal[
        "waiting", "pending", "analyzing", "completed", "failed", "configuration_required"
    ]
    include_images: bool
    debounce_seconds: int
    max_wait_seconds: int
    last_enqueued_message_id: int | None
    last_analyzed_message_id: int | None
    latest_message_id: int | None
    pending_message_count: int
    latest_artifact_version: int
    next_run_at: datetime | None
    last_started_at: datetime | None
    last_completed_at: datetime | None
    last_error_code: str
    last_error_message: str
    consent_policy_version: str
    consent_text_hash: str
    authorization_note: str
    confirmed_at: datetime
    revision: int
    paused_at: datetime | None
    created_at: datetime
    updated_at: datetime
    idempotent: bool = False


class CustomerAutoAnalysisResult(StrictModel):
    """Full replacement snapshot produced from one incremental message batch."""

    customer_summary: AgentCustomerConversationSummary
    requirement_analysis: AgentRequirementAnalysis
    requirement_blueprint: AgentRequirementBlueprint
    execution_plan: AgentExecutionPlan

    def evidence_refs(self) -> list[str]:
        refs: list[str] = []
        refs.extend(self.requirement_analysis.evidence_refs())
        refs.extend(self.requirement_blueprint.evidence_refs())
        refs.extend(self.execution_plan.evidence_refs())
        return list(dict.fromkeys(refs))


class CustomerAnalysisArtifactView(StrictModel):
    id: str
    analysis_thread_id: str
    version: int
    previous_artifact_id: str | None
    run_id: str
    watermark_before: int | None
    watermark_after: int
    source_hash: str
    content_hash: str
    content: CustomerAutoAnalysisResult
    diff: dict[str, object]
    evidence_message_ids: list[int]
    evidence_image_ids: list[str]
    model: str
    external_response_id: str
    created_at: datetime
    append_only: Literal[True] = True


class CustomerAnalysisSnapshotView(StrictModel):
    subscription: CustomerAnalysisSubscriptionView
    latest_artifact: CustomerAnalysisArtifactView | None
    artifacts: list[CustomerAnalysisArtifactView] = Field(default_factory=list)

