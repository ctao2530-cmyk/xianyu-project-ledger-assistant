from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


RecommendationStatus = Literal[
    "pending",
    "accepted",
    "observing",
    "completed",
    "ignored",
]
RecommendationLifecycleStatus = Literal[
    "pending",
    "accepted",
    "observing",
    "review_due",
    "completed",
    "ignored",
]
RecommendationOutcome = Literal["positive", "negative", "inconclusive"]


class ProductSignalMetric(BaseModel):
    current: int
    delta_7d: int | None
    comparison_products: int
    available: bool
    unit: str


class ProductAnalysisMetrics(BaseModel):
    owned_products: int
    monitored_products: int
    active_products: int
    status_counts: dict[str, int]
    latest_published_at: str | None
    snapshot_days: int
    snapshot_coverage_percent: float
    exposure: ProductSignalMetric
    inquiries: ProductSignalMetric
    converted_projects: ProductSignalMetric
    platform_sold_count: int
    inquiry_rate_percent: float | None


class CustomerAnalysisMetrics(BaseModel):
    total: int
    follow_up_status_counts: dict[str, int]
    won_customers: int
    active_last_30d: int
    stale_or_missing_contact_30d: int
    latest_contact_at: str | None
    conversation_customers: int
    latest_message_at: str | None


class ProjectAnalysisMetrics(BaseModel):
    total: int
    status_counts: dict[str, int]
    active_projects: int
    completed_projects: int
    overdue_projects: int
    contract_total: float
    confirmed_income: float
    outstanding_receivables: float


class PeriodMetric(BaseModel):
    current: float
    previous: float
    delta: float
    change_percent: float | None
    direction: Literal["up", "down", "flat"]
    unit: str = "CNY"


class FinanceAnalysisMetrics(BaseModel):
    income: PeriodMetric
    expenses: PeriodMetric
    profit: PeriodMetric
    all_time_income: float
    all_time_expenses: float
    all_time_profit: float
    confirmed_payment_count: int
    expense_count: int


class BusinessAnalysisMetrics(BaseModel):
    products: ProductAnalysisMetrics
    customers: CustomerAnalysisMetrics
    projects: ProjectAnalysisMetrics
    finance: FinanceAnalysisMetrics


class BusinessAnalysisInsight(BaseModel):
    id: str
    domain: Literal["portfolio", "products", "customers", "projects", "finance", "data"]
    severity: Literal["info", "positive", "warning", "critical"]
    title: str
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)


class BusinessRecommendationMetricValue(BaseModel):
    key: str
    label: str
    value: float
    unit: str
    evidence_ref: str


class BusinessRecommendationMetricSnapshot(BaseModel):
    captured_at: datetime
    source_snapshot_hash: str
    values: list[BusinessRecommendationMetricValue] = Field(default_factory=list)


class BusinessAnalysisRecommendation(BaseModel):
    id: str
    analysis_id: str | None = None
    analysis_snapshot_time: datetime | None = None
    source_key: str | None = None
    domain: Literal["portfolio", "products", "customers", "projects", "finance", "data"]
    entity_type: str | None = None
    entity_id: str | None = None
    entity_label: str | None = None
    target_scope: Literal["portfolio", "domain", "entity"] = "domain"
    priority: Literal["low", "medium", "high"]
    title: str
    problem: str = ""
    action: str
    reason: str
    data_source: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    observe_period: str = "7 days"
    observe_days: int | None = None
    status: RecommendationStatus = "pending"
    lifecycle_status: RecommendationLifecycleStatus = "pending"
    version: int = 1
    user_note: str = ""
    target_page: str
    execution_mode: Literal["manual"] = "manual"
    evidence_refs: list[str] = Field(default_factory=list)
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    observe_until: datetime | None = None
    completed_at: datetime | None = None
    baseline_metrics: BusinessRecommendationMetricSnapshot | None = None
    result_metrics: BusinessRecommendationMetricSnapshot | None = None
    outcome: RecommendationOutcome | None = None
    actual_cost: float | None = None
    actual_hours: float | None = None
    user_conclusion: str = ""
    execution_ref_type: Literal["product_modification_experiment"] | None = None
    execution_ref_id: str | None = None
    stale: bool = False
    can_accept: bool = False
    can_ignore: bool = False
    can_start: bool = False
    can_complete: bool = False


class BusinessAnalysisDataSource(BaseModel):
    id: str
    label: str
    source_type: Literal["sqlite", "ledger"]
    tables: list[str]
    fields: list[str]
    available: bool
    record_count: int
    latest_at: str | None
    note: str


class BusinessAnalysisFutureField(BaseModel):
    domain: Literal["products", "customers", "projects", "finance", "recommendations"]
    field: str
    label: Literal["未来扩展字段"] = "未来扩展字段"
    reason: str


class BusinessAnalysisPeriod(BaseModel):
    timezone: str
    current_month_start: str
    current_month_end: str
    previous_month_start: str
    previous_month_end: str
    product_change_window_days: int = 7


class BusinessAnalysisAIError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class BusinessAnalysisOverview(BaseModel):
    summary: str
    metrics: BusinessAnalysisMetrics
    insights: list[BusinessAnalysisInsight]
    recommendations: list[BusinessAnalysisRecommendation]
    data_sources: list[BusinessAnalysisDataSource]
    future_fields: list[BusinessAnalysisFutureField]
    data_gaps: list[str]
    analysis_method: Literal[
        "evidence_rules_v1",
        "rules_plus_deepseek_v1",
        "rules_plus_codex_v1",
    ] = (
        "evidence_rules_v1"
    )
    ledger_revision: int
    period: BusinessAnalysisPeriod
    generated_at: datetime
    analysis_id: str | None = None
    record_status: Literal["live", "completed"] = "live"
    provider: str | None = None
    model: str | None = None
    ai_status: Literal["not_requested", "succeeded", "failed"] = "not_requested"
    fallback_used: bool = False
    snapshot_time: datetime | None = None
    is_stale: bool = False
    ai_error: BusinessAnalysisAIError | None = None


class BusinessAnalysisRunRequest(BaseModel):
    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    provider: Literal["codex_cli", "deepseek"] = "codex_cli"
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    reasoning_effort: str | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class BusinessAnalysisHistoryItem(BaseModel):
    id: str
    snapshot_time: datetime
    created_at: datetime
    provider: str | None
    model: str | None
    ai_status: Literal["not_requested", "succeeded", "failed"]
    fallback_used: bool
    status: Literal["completed"]
    summary: str
    insight_count: int
    recommendation_count: int
    pending_recommendation_count: int


class BusinessAnalysisHistoryResponse(BaseModel):
    items: list[BusinessAnalysisHistoryItem]
    total: int
    limit: int
    offset: int


class BusinessAnalysisRecommendationUpdate(BaseModel):
    status: Literal["pending", "accepted", "ignored"]
    expected_version: int = Field(ge=1)
    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    note: str = Field(default="", max_length=1000)


class BusinessAnalysisRecommendationStart(BaseModel):
    expected_version: int = Field(ge=1)
    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    execution_ref_type: Literal["product_modification_experiment"] | None = None
    execution_ref_id: str | None = Field(default=None, max_length=128)


class BusinessAnalysisRecommendationComplete(BaseModel):
    expected_version: int = Field(ge=1)
    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    outcome: RecommendationOutcome
    actual_cost: float | None = Field(default=None, ge=0, le=1_000_000_000)
    actual_hours: float | None = Field(default=None, ge=0, le=100_000)
    user_conclusion: str = Field(default="", max_length=2000)


class BusinessAnalysisRecommendationQueueCounts(BaseModel):
    total: int
    pending: int
    accepted: int
    observing: int
    review_due: int
    completed: int
    ignored: int


class BusinessAnalysisRecommendationQueueResponse(BaseModel):
    items: list[BusinessAnalysisRecommendation]
    counts: BusinessAnalysisRecommendationQueueCounts
    generated_at: datetime
