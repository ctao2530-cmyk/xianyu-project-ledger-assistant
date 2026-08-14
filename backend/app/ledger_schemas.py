from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .requirement_blueprints import LeadAnalysisResult, RequirementBlueprintV2


class LedgerSnapshotEnvelope(BaseModel):
    revision: int
    snapshot: dict[str, Any]


class LedgerSnapshotUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    snapshot: dict[str, Any]


class PaymentConfirmationRequest(BaseModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    expected_revision: int = Field(ge=0)
    project_id: str = Field(min_length=1, max_length=128)
    payment_id: str | None = Field(default=None, max_length=128)
    amount: float = Field(gt=0, le=100_000_000)
    paid_at: datetime
    type: Literal["deposit", "milestone", "final", "full"]
    notes: str = Field(default="", max_length=2000)


class PaymentConfirmationResult(LedgerSnapshotEnvelope):
    payment_id: str
    remainder_payment_id: str | None = None
    idempotent: bool = False


class ProjectChangeOrderPaymentRequest(BaseModel):
    amount: float = Field(gt=0, le=100_000_000)
    type: Literal["deposit", "milestone", "final", "full"]
    status: Literal["pending", "confirmed"]
    paid_at: datetime | None = None
    due_at: date | None = None
    notes: str = Field(default="", max_length=1000)


class ProjectChangeOrderRequest(BaseModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    expected_revision: int = Field(ge=0)
    project_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=2, max_length=300)
    amount: float = Field(gt=0, le=100_000_000)
    confirmed_at: date
    notes: str = Field(default="", max_length=2000)
    payment_plan: list[ProjectChangeOrderPaymentRequest] = Field(
        min_length=1,
        max_length=6,
    )


class ProjectChangeOrderResult(LedgerSnapshotEnvelope):
    change_order_id: str
    payment_ids: list[str]
    idempotent: bool = False


SettlementIssueType = Literal[
    "customer_dissatisfied",
    "refund",
    "project_cancelled",
    "payment_refused",
    "cooperation_terminated",
    "scope_dispute",
    "other",
]


class SettlementIssueRequest(BaseModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    expected_revision: int = Field(ge=0)
    project_id: str = Field(min_length=1, max_length=128)
    type: SettlementIssueType
    receivable_impact: float = Field(default=0, ge=0, le=100_000_000)
    refund_amount: float = Field(default=0, ge=0, le=100_000_000)
    occurred_at: datetime
    reason: str = Field(min_length=2, max_length=2000)
    notes: str = Field(default="", max_length=4000)


class SettlementIssueResult(LedgerSnapshotEnvelope):
    issue_id: str
    idempotent: bool = False


class MigrationPreviewRequest(BaseModel):
    snapshot: dict[str, Any]


class MigrationConflict(BaseModel):
    key: str
    collection: str
    incoming_id: str
    existing_id: str
    reason: str
    incoming: dict[str, Any]
    existing: dict[str, Any]


class MigrationPreview(BaseModel):
    token: str
    current_revision: int
    incoming_counts: dict[str, int]
    additions: dict[str, int]
    identical: dict[str, int]
    conflicts: list[MigrationConflict]
    can_import_without_review: bool


class MigrationCommitRequest(BaseModel):
    snapshot: dict[str, Any]
    token: str
    resolutions: dict[str, Literal["sqlite", "browser"]] = Field(default_factory=dict)


class MigrationCommitResult(BaseModel):
    revision: int
    imported: dict[str, int]
    kept_sqlite: int
    attachments_written: int
    backup_name: str
    snapshot: dict[str, Any]


class LeadView(BaseModel):
    id: str
    conversation_id: int
    customer_id: str | None
    status: str
    requirement_version_id: int | None
    latest_quote_id: str | None
    converted_project_id: str | None


class LeadAnalysisView(BaseModel):
    id: str
    conversation_id: int
    provider: str
    model: str
    result: LeadAnalysisResult
    confirmed_at: datetime | None
    created_at: datetime


class LeadConfirmationRequest(BaseModel):
    confirmed: Literal[True]
    analysis_run_id: str | None = None


class RequirementExportView(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    conversation_id: int
    filename: str
    prompt: str
    analysis_document: str
    json_schema: dict[str, Any] = Field(alias="schema")
    conversation_package: dict[str, Any]
    redaction_count: int
    private_content_included: bool


class RequirementAttachmentView(BaseModel):
    id: str
    conversation_id: int
    message_id: int | None
    message_number: int | None
    source: Literal["manual", "edge"]
    attachment_type: Literal["image"]
    mime_type: str
    original_name: str
    sha256: str
    file_size: int
    width: int
    height: int
    sort_order: int
    privacy_status: Literal["pending", "reviewed", "excluded"]
    reviewed_at: datetime | None
    created_at: datetime
    content_url: str
    duplicate: bool = False


class RequirementImageCandidateView(BaseModel):
    message_id: int
    message_number: int
    direction: str
    time: datetime
    label: str
    captured: bool
    attachment_ids: list[str]


class RequirementExportPreviewView(BaseModel):
    conversation_id: int
    text_message_count: int
    image_candidate_count: int
    captured_image_count: int
    missing_image_count: int
    total_bytes: int
    redaction_count: int
    package_complete: bool
    attachments: list[RequirementAttachmentView]
    image_candidates: list[RequirementImageCandidateView]


class RequirementAttachmentPrivacyRequest(BaseModel):
    privacy_status: Literal["pending", "reviewed", "excluded"]


class RequirementExportPackageRequest(BaseModel):
    confirmed: Literal[True]
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)
    allow_incomplete: bool = False


class RequirementExportPackageView(BaseModel):
    export_id: str
    conversation_id: int
    package_root: str
    readme_path: str
    manifest_path: str
    image_paths: list[str]
    codex_prompt: str
    selected_image_count: int
    missing_image_count: int
    package_complete: bool
    redaction_count: int


class RequirementImportPreviewRequest(BaseModel):
    conversation_id: int
    customer_id: str
    case_id: str | None = None
    case_title: str | None = Field(default=None, min_length=2, max_length=300)
    source_label: str = Field(default="GPT 人工导入", min_length=2, max_length=255)
    document: dict[str, Any] | str


class RequirementImportPreviewView(BaseModel):
    token: str
    expires_at: datetime
    customer_id: str
    item_id: int | None
    item_external_id: str | None
    item_title: str | None
    case_id: str | None
    case_title: str
    target_version: int
    expected_version: int
    document: RequirementBlueprintV2
    estimated_hours: float
    warnings: list[str]
    changes: list[str]


class RequirementImportCommitRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    expected_version: int = Field(ge=0)


class RequirementCaseEditRequest(BaseModel):
    expected_version: int = Field(ge=1)
    change_summary: str = Field(min_length=2, max_length=1000)
    document: RequirementBlueprintV2


class RequirementCaseTransferRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    expected_customer_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)
    expected_revision: int = Field(ge=0)
    target_customer_id: str | None = Field(default=None, max_length=128)
    new_customer_name: str | None = Field(default=None, max_length=255)


class RequirementCaseTransferResult(BaseModel):
    revision: int
    snapshot: dict[str, Any]
    target_customer_id: str
    case: "RequirementCaseDetailView"
    idempotent: bool = False


class RequirementVersionCaseSummary(BaseModel):
    id: int
    version: int
    schema_version: str
    source_type: str
    source_label: str
    title: str
    readiness: str
    change_summary: str
    imported_at: datetime | None
    created_at: datetime


class RequirementCaseSummaryView(BaseModel):
    id: str
    customer_id: str
    item_id: int | None
    item_external_id: str | None
    item_title: str | None
    title: str
    status: str
    current_version: int
    source_count: int
    estimated_hours: float
    open_question_count: int
    updated_at: datetime


class RequirementCaseDetailView(RequirementCaseSummaryView):
    lead_id: str | None
    project_id: str | None
    versions: list[RequirementVersionCaseSummary]
    selected_version: RequirementVersionCaseSummary | None
    document: dict[str, Any] | None
    sources: list[dict[str, Any]]


class RequirementImportCommitResult(BaseModel):
    case: RequirementCaseDetailView
    version_id: int
    version: int
    idempotent: bool = False


class QuoteGenerateRequest(BaseModel):
    hourly_rate: float | None = Field(default=None, gt=0)
    risk_buffer: float = Field(default=0.15, ge=0, le=1)


class QuoteStageEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1, le=12)
    title: str = Field(min_length=2, max_length=100)
    objective: str = Field(min_length=2, max_length=500)
    estimated_hours: float = Field(gt=0, le=2000)
    dependencies: list[str] = Field(default_factory=list, max_length=10)
    work_items: list[str] = Field(default_factory=list, max_length=20)
    deliverables: list[str] = Field(default_factory=list, max_length=15)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=20)


class QuoteScopeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[QuoteStageEstimate] = Field(min_length=1, max_length=12)
    risks: list[str] = Field(default_factory=list, max_length=20)
    schedule_notes: list[str] = Field(default_factory=list, max_length=12)


class QuoteView(BaseModel):
    id: str
    lead_id: str
    version: int
    status: str
    requirement_version_id: int | None
    hourly_rate: float
    risk_buffer: float
    estimated_hours: float
    total_amount: float
    stages: list[dict[str, Any]]
    payment_plan: list[dict[str, Any]]
    risks: list[str]


class LeadConversionRequest(BaseModel):
    quote_id: str
    confirmed: bool
    customer_id: str | None = None
    customer_name: str | None = Field(default=None, max_length=255)
    project_name: str | None = Field(default=None, max_length=300)
    start_date: str | None = None


class LeadConversionResult(BaseModel):
    lead: LeadView
    project_id: str
    customer_id: str
    revision: int


class StandaloneRequirementRequest(BaseModel):
    content: str = Field(min_length=10, max_length=40_000)


class StandaloneRequirementResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_type: str = Field(min_length=2, max_length=120)
    features: list[str] = Field(min_length=1, max_length=30)
    estimated_days_min: int = Field(ge=1, le=365)
    estimated_days_max: int = Field(ge=1, le=730)
    estimated_hours: float = Field(gt=0, le=5000)
    risks: list[str] = Field(default_factory=list, max_length=20)
    scope_notes: list[str] = Field(default_factory=list, max_length=20)


class StandaloneRequirementResponse(StandaloneRequirementResult):
    quote_min: float | None = None
    quote_max: float | None = None
    hourly_rate: float | None = None
    pricing_blocked: bool = False


class StandaloneQuoteRequest(BaseModel):
    analysis: StandaloneRequirementResult
    complexity: Literal["standard", "advanced", "complex"] = "advanced"
    hourly_rate: float | None = Field(default=None, gt=0)
    risk_buffer: float = Field(default=0.15, ge=0, le=1)


class StandaloneQuoteResponse(BaseModel):
    total_amount: float
    hourly_rate: float
    risk_buffer: float
    estimated_hours: float
    items: list[dict[str, Any]]
    payment_plan: list[dict[str, Any]]
    delivery_note: str


class ProjectReviewRequest(BaseModel):
    project: dict[str, Any]
    income: float
    expenses: float
    profit: float
    actual_hours: float
    hourly_income: float
    outstanding: float
    payment_progress: float


class ProjectReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=10, max_length=1200)
    pricing_advice: str = Field(min_length=5, max_length=500)
    recommended_increase_percent: int = Field(ge=0, le=100)
    improvements: list[str] = Field(min_length=1, max_length=12)
    risks: list[str] = Field(default_factory=list, max_length=12)
