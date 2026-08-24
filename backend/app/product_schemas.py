from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProductSnapshotView(BaseModel):
    date: str
    source: str
    browse_count: int
    raw_browse_count: int
    collection_views_excluded: int
    collect_count: int
    want_count: int
    sold_count: int
    inquiry_count: int
    converted_project_count: int
    revenue_total: float
    profit_total: float


class ProductWindowMetricsView(BaseModel):
    days: int
    observation_days: int
    snapshot_count: int
    browse_delta: int | None
    inquiry_delta: int | None
    want_delta: int | None
    daily_browse: float | None


class ProductRecommendationView(BaseModel):
    id: str
    item_external_id: str
    item_title: str
    recommendation_date: str
    strategy_code: str
    priority_score: int
    attention: str
    posture: str
    title: str
    summary: str
    evidence: list[str]
    actions: list[str]
    confidence: str
    status: str


class ProductActionView(BaseModel):
    id: str
    action_type: str
    status: str
    note: str
    cost: float
    happened_at: datetime
    observation_until: datetime | None


class ProductLinkedProjectView(BaseModel):
    project_id: str
    project_name: str
    relation_source: str
    latest_confirmed_at: str | None
    confirmed_total: float
    net_confirmed_total: float
    expense_total: float
    refund_total: float
    profit_total: float


class ProductView(BaseModel):
    external_id: str
    title: str
    price: float | None
    status: str
    monitoring_enabled: bool
    monitor_source: str
    ownership_status: str
    ownership_source: str
    last_attempt_at: datetime | None
    last_collection_status: str
    last_error_code: str | None
    last_error_detail: str | None
    last_collected_at: datetime | None
    browse_count: int
    raw_browse_count: int
    collection_views_excluded: int
    collect_count: int
    want_count: int
    sold_count: int
    browse_delta: int | None
    inquiry_count: int
    inbound_message_count: int
    converted_project_count: int
    revenue_total: float
    profit_total: float
    project_expense_total: float
    project_refund_total: float
    profit_is_realtime: bool
    linked_projects: list[ProductLinkedProjectView]
    inquiry_rate: float | None
    deal_rate: float | None
    snapshot_count: int
    freshness_days: int | None
    data_quality: str
    data_gaps: list[str]
    traffic_cooldown_until: datetime | None
    modification_observation_until: datetime | None
    recent_windows: list[ProductWindowMetricsView]
    history: list[ProductSnapshotView]
    recommendation: ProductRecommendationView | None
    actions: list[ProductActionView]


class ProductPlanProductView(BaseModel):
    external_id: str
    title: str
    role: str
    score: int
    data_quality: str
    reason: str


class ProductOperatingPlanSlotView(BaseModel):
    id: str
    date: str
    weekday: str
    scheduled_time: str
    action_type: str
    products: list[ProductPlanProductView]
    planned_cost: float
    reason: str
    change_reason: str
    change_factors: list[str] = Field(default_factory=list)
    evidence: list[str]
    warnings: list[str]
    confidence: str
    locked: bool
    lock_mode: str = "none"
    lock_label: str | None = None
    cooldown_conflict_count: int = 0
    cooldown_until: datetime | None = None
    status: str
    batch_id: str | None
    source_batch_id: str | None = None
    availability_at: datetime | None = None
    is_new_spend: bool = False
    rotation_summary: dict = Field(default_factory=dict)


class ProductOperatingPlanView(BaseModel):
    id: str
    version: int
    start_date: str
    end_date: str
    generated_at: datetime
    weekly_budget: float
    spent_this_week: float
    planned_this_week: float
    remaining_this_week: float
    cadence: str
    change_summary: str
    change_factors: list[str] = Field(default_factory=list)
    data_quality: str
    rules_version: str
    analysis_stage: str
    effective_batch_count: int
    slots: list[ProductOperatingPlanSlotView]


class ProductTrafficItemCheckpointView(BaseModel):
    checkpoint: str
    hours: int
    recorded_at: datetime
    browse_count: int
    collect_count: int
    want_count: int
    inquiry_count: int
    browse_delta: int
    collect_delta: int
    want_delta: int
    inquiry_delta: int


class ProductTrafficExploratoryPointView(BaseModel):
    """A factual observation relative to a non-causal reference point."""

    key: str
    label: str
    source: str
    recorded_at: datetime
    browse_count: int
    collect_count: int
    want_count: int
    inquiry_count: int
    browse_change: int
    collect_change: int
    want_change: int
    inquiry_change: int


class ProductTrafficBatchItemView(BaseModel):
    external_id: str
    title: str
    baseline_browse_count: int
    baseline_collect_count: int
    baseline_want_count: int
    baseline_inquiry_count: int
    baseline_captured_at: datetime | None
    baseline_source: str = "pending"
    latest_checkpoint: str | None
    latest_browse_count: int
    latest_collect_count: int
    latest_want_count: int
    latest_inquiry_count: int
    browse_delta: int
    collect_delta: int
    want_delta: int
    inquiry_delta: int
    checkpoints: list[ProductTrafficItemCheckpointView]
    exploratory_points: list[ProductTrafficExploratoryPointView] = Field(
        default_factory=list
    )


class ProductTrafficCheckpointMetricsView(BaseModel):
    checkpoint: str
    hours: int
    batch_count: int = 1
    browse_delta: int
    collect_delta: int
    want_delta: int
    inquiry_delta: int
    inquiry_conversion_rate: float | None
    average_browse_delta: float
    average_inquiry_delta: float


class ProductTrafficCheckpointJobItemView(BaseModel):
    external_id: str
    title: str
    status: str
    captured_at: datetime | None = None
    error_code: str | None = None
    error_detail: str = ""


class ProductTrafficCheckpointJobView(BaseModel):
    checkpoint: str
    hours: int
    scheduled_for: datetime
    status: str
    mode: str
    attempt_count: int
    collected_count: int
    total_count: int
    captured_at: datetime | None = None
    completed_at: datetime | None = None
    capture_delay_minutes: int | None = None
    last_error_code: str | None = None
    last_error_detail: str = ""
    can_retry_auto: bool = False
    can_complete_manually: bool = False
    items: list[ProductTrafficCheckpointJobItemView] = Field(default_factory=list)


class ProductTrafficBatchView(BaseModel):
    id: str
    plan_slot_id: str | None
    status: str
    planned_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    baseline_prepared_at: datetime | None
    recording_mode: str = "standard"
    attribution_status: str = "clean"
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None
    invalidation_label: str | None = None
    checkpoint_collection_mode: str = "auto"
    observation_window_hours: int = 72
    terminal_checkpoint: str = "h72"
    checkpoint_sequence: list[str] = Field(
        default_factory=lambda: ["h1", "h6", "h24", "h72"]
    )
    is_legacy_protocol: bool = True
    observation_title: str
    checkpoint_jobs: list[ProductTrafficCheckpointJobView] = Field(default_factory=list)
    has_reliable_baseline: bool = False
    baseline_expires_at: datetime | None
    baseline_status: str
    baseline_status_label: str
    can_prepare_baseline: bool
    can_start: bool
    planned_actual_delta_minutes: int | None
    planned_actual_delta_label: str | None
    needs_replan: bool
    replan_reason: str | None
    actual_cost: float
    total_exposure: int | None
    note: str
    products: list[ProductTrafficBatchItemView]
    completed_checkpoints: list[str]
    due_checkpoint: str | None
    due_at: datetime | None
    due_ready: bool
    checkpoint_progress: int
    baseline_age_minutes: int | None
    baseline_quality: str
    baseline_quality_label: str
    baseline_quality_detail: str
    overlap_warning: str | None
    start_blocked: bool
    start_blocked_reason: str | None
    start_blocked_until: datetime | None
    browse_delta: int
    collect_delta: int
    want_delta: int
    inquiry_delta: int
    inquiry_conversion_rate: float | None
    cost_per_browse: float | None
    cost_per_inquiry: float | None
    observation_checkpoint: str | None
    observation_hours: int
    time_bucket: str
    data_quality: str
    analysis_eligible: bool
    analysis_tier: str = "fact_only"
    analysis_tier_label: str = "事实记录"
    analysis_confidence: str = "low"
    exploratory_available: bool = False
    exploratory_reference_source: str | None = None
    exploratory_reference_label: str | None = None
    exploratory_reference_at: datetime | None = None
    exploratory_through_label: str | None = None
    exploratory_through_at: datetime | None = None
    observed_browse_change: int = 0
    observed_collect_change: int = 0
    observed_want_change: int = 0
    observed_inquiry_change: int = 0
    natural_browse_low: int | None = None
    natural_browse_high: int | None = None
    natural_sample_size: int = 0
    natural_item_count: int = 0
    control_browse_expected: float | None = None
    control_item_count: int = 0
    control_adjusted_browse_change: float | None = None
    directional_browse_low: int | None = None
    directional_browse_high: int | None = None
    exploratory_summary: str | None = None
    analysis_limitations: list[str] = Field(default_factory=list)
    exploratory_points: list[ProductTrafficExploratoryPointView] = Field(
        default_factory=list
    )
    checkpoint_metrics: list[ProductTrafficCheckpointMetricsView]
    created_at: datetime


class ProductTrafficOverlapItemView(BaseModel):
    external_id: str
    title: str
    source_batch_id: str
    source_started_at: datetime
    cooldown_until: datetime


class ProductTrafficConflictingBatchView(BaseModel):
    batch_id: str
    started_at: datetime
    cooldown_until: datetime
    item_count: int
    item_external_ids: list[str] = Field(default_factory=list)


class ProductTrafficStartPreviewView(BaseModel):
    batch: ProductTrafficBatchView
    can_start: bool
    can_start_clean: bool = False
    can_start_cohort: bool = False
    can_record_actual: bool = False
    blocked_reasons: list[str]
    ownership_ready: bool
    baseline_status: str
    baseline_expires_at: datetime | None
    earliest_start_at: datetime | None
    cooldown_until: datetime | None = None
    overlap_items: list[ProductTrafficOverlapItemView] = Field(default_factory=list)
    conflicting_batches: list[ProductTrafficConflictingBatchView] = Field(
        default_factory=list
    )
    analysis_impact: str = ""
    safety_notice: str = ""
    actions: list[str]


class ProductTrafficReplanPreviewView(BaseModel):
    batch_id: str
    updated_at: datetime
    preview_hash: str
    can_replan: bool
    proposed_planned_at: datetime
    current_products: list[ProductPlanProductView]
    proposed_products: list[ProductPlanProductView]
    retained_products: list[ProductPlanProductView]
    removed_products: list[ProductPlanProductView]
    added_products: list[ProductPlanProductView]
    source_batch_id: str | None
    availability_at: datetime | None
    is_new_spend: bool
    fee_impact: float
    reasons: list[str]
    warnings: list[str]


class ProductTrafficBatchPageView(BaseModel):
    items: list[ProductTrafficBatchView]
    next_cursor: str | None
    has_more: bool


class ProductTrafficTimeBucketView(BaseModel):
    bucket: str
    time_range: str
    batch_count: int
    total_cost: float
    browse_delta: int
    inquiry_delta: int
    average_browse_delta: float
    average_inquiry_delta: float
    inquiry_conversion_rate: float | None
    cost_per_browse: float | None
    cost_per_inquiry: float | None
    confidence: str
    recommended: bool


class ProductExposureAnalyticsView(BaseModel):
    window_days: int
    total_spent: float
    observed_cost: float
    eligible_batch_count: int
    excluded_batch_count: int
    browse_delta: int
    collect_delta: int
    want_delta: int
    inquiry_delta: int
    average_browse_delta: float
    average_inquiry_delta: float
    inquiry_conversion_rate: float | None
    cost_per_browse: float | None
    cost_per_inquiry: float | None
    confidence: str
    best_time_bucket: str | None
    summary: str
    checkpoints: list[ProductTrafficCheckpointMetricsView]
    time_buckets: list[ProductTrafficTimeBucketView]


class ProductTrafficSummaryView(BaseModel):
    batch_count: int
    effective_batch_count: int
    active_batch_count: int
    planned_batch_count: int
    observation_batch_count: int
    due_checkpoint_count: int
    spent_this_week: float
    analysis_stage: str
    analysis_summary: str


class ProductCollectionRunView(BaseModel):
    id: str
    run_date: str
    trigger: str
    status: str
    monitored_count: int
    collected_count: int
    failed_count: int
    detail: str
    started_at: datetime
    finished_at: datetime | None


class ProductCollectionAttemptItemView(BaseModel):
    external_id: str
    title: str
    status: str
    error_code: str | None
    detail: str
    finished_at: datetime | None


class ProductCollectionAttemptView(BaseModel):
    id: str
    run_date: str
    daily_run_id: str | None
    trigger: str
    requested_external_id: str | None
    requested_title: str | None
    status: str
    monitored_count: int
    collected_count: int
    failed_count: int
    skipped_count: int
    detail: str
    started_at: datetime
    finished_at: datetime | None
    items: list[ProductCollectionAttemptItemView]


class ProductPortfolioSummary(BaseModel):
    monitored_products: int
    active_products: int
    pending_products: int
    excluded_products: int
    needs_attention: int
    traffic_candidates: int
    snapshot_days: int
    active_projects: int
    delivery_capacity: int


class PublishWindowView(BaseModel):
    weekday: str
    time_range: str
    inquiry_count: int
    share: float


class PublishTimingView(BaseModel):
    sample_size: int
    confidence: str
    summary: str
    windows: list[PublishWindowView]


class DemandOpportunityView(BaseModel):
    theme: str
    message_count: int
    conversation_count: int
    converted_project_count: int
    posture: str
    suggestion: str


class ProductCollectionStatusView(BaseModel):
    configured: bool
    schedule: str
    timezone: str
    can_collect_today: bool
    next_collection_at: datetime | None
    last_run: ProductCollectionRunView | None
    latest_attempt: ProductCollectionAttemptView | None
    attempts: list[ProductCollectionAttemptView]
    safety_note: str


class ProductMarketKeywordCandidateView(BaseModel):
    keyword: str
    theme: str
    score: int
    reason: str
    evidence: list[str]
    confidence: str


class ProductMarketSampleResultView(BaseModel):
    position: int
    title: str
    price: float | None
    tags: list[str]


class ProductMarketSampleView(BaseModel):
    id: str
    keyword: str
    sample_date: str
    source: str
    captured_at: datetime
    result_count: int
    note: str
    results: list[ProductMarketSampleResultView]


class ProductMarketStabilityView(BaseModel):
    keyword: str
    sample_days: int
    visible_days: int
    average_best_position: float | None
    status: str
    label: str


class ProductMarketBenchmarkView(BaseModel):
    keyword: str
    sample_days: int
    high_visibility_result_count: int
    priced_result_count: int
    repeated_result_count: int
    median_price: float | None
    price_low: float | None
    price_high: float | None
    common_title_terms: list[str]
    common_tags: list[str]
    median_title_length: int | None
    confidence: str
    evidence: list[str]


class ProductMarketReminderView(BaseModel):
    date: str
    status: str
    scheduled_for: datetime
    due: bool
    snoozed_until: datetime | None


class ProductMarketReferenceView(BaseModel):
    date: str
    mode: str
    selected_keyword: str
    custom_keyword: str
    recommendations: list[ProductMarketKeywordCandidateView]
    common_keywords: list[str]
    current_sample: ProductMarketSampleView | None
    recent_samples: list[ProductMarketSampleView]
    stability: ProductMarketStabilityView
    benchmark: ProductMarketBenchmarkView
    reminder: ProductMarketReminderView
    update_completed: bool
    last_updated_at: datetime | None
    rules_version: str
    safety_note: str


class ProductLaunchRecommendationView(BaseModel):
    keyword: str
    theme: str
    title: str
    recommended_window: str
    demand_conversations: int
    matching_product_count: int
    capacity_available: int
    confidence: str
    market_validation_required: bool
    ready: bool
    recommended_action: str
    suggested_product_type: str
    title_direction: str
    price_reference: str
    market_differentiation: str
    timing_basis: str
    benchmark: ProductMarketBenchmarkView
    rationale: list[str]
    evidence: list[str]


class ProductLaunchPlanView(BaseModel):
    id: str
    keyword: str
    theme: str
    title: str
    recommended_window: str
    rationale: list[str]
    evidence: list[str]
    confidence: str
    status: str
    created_at: datetime
    updated_at: datetime


class ProductModificationSuggestionView(BaseModel):
    external_id: str
    title: str
    variable: str | None
    reason: str
    suggested_change: str
    confidence: str
    blocked_reason: str | None
    benchmark_keyword: str | None
    market_evidence: list[str]
    market_gap: str | None
    reference_price_range: str | None
    confidence_basis: list[str]
    evidence_sources: list[str]


class ProductModificationExperimentView(BaseModel):
    id: str
    item_external_id: str
    item_title: str
    variable: str
    before_value: str
    after_value: str
    baseline: dict
    started_at: datetime
    observation_until: datetime
    status: str
    result: dict
    decision: str
    evidence: list[str]
    can_evaluate: bool


class ProductIntelligenceView(BaseModel):
    collection: ProductCollectionStatusView
    summary: ProductPortfolioSummary
    products: list[ProductView]
    candidates: list[ProductView]
    recommendations: list[ProductRecommendationView]
    publish_timing: PublishTimingView
    demand_opportunities: list[DemandOpportunityView]
    operating_plan: ProductOperatingPlanView
    traffic_batches: list[ProductTrafficBatchView]
    traffic_summary: ProductTrafficSummaryView
    exposure_analytics: ProductExposureAnalyticsView
    market_reference: ProductMarketReferenceView
    launch_recommendation: ProductLaunchRecommendationView
    launch_plans: list[ProductLaunchPlanView]
    modification_suggestions: list[ProductModificationSuggestionView]
    modification_experiments: list[ProductModificationExperimentView]


class ProductRegistrationCandidateView(BaseModel):
    external_id: str
    title: str
    price: float | None
    status: str
    ownership_status: str
    already_registered: bool
    monitoring_enabled: bool
    can_register: bool
    blocked_reason: str | None


class ProductRegistrationPreviewView(BaseModel):
    token: str
    expires_at: datetime
    source: str
    items: list[ProductRegistrationCandidateView]
    warnings: list[str]


class ProductReferenceResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reference: str = Field(min_length=5, max_length=4000)


class ProductRegistrationCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    preview_token: str = Field(min_length=20, max_length=200)
    external_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("external_ids")
    @classmethod
    def normalize_external_ids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            candidate = value.strip()
            if not candidate or len(candidate) > 128:
                raise ValueError("商品 ID 无效")
            if candidate not in normalized:
                normalized.append(candidate)
        return normalized


class ProductRegistrationCommitView(BaseModel):
    products: list[ProductView]
    registered_count: int
    already_registered_count: int
    idempotent: bool


class ProductMonitorUpdateRequest(BaseModel):
    enabled: bool


class ProductMonitorBatchDisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    external_ids: list[str] = Field(min_length=1, max_length=100)
    confirmed: Literal[True]

    @field_validator("external_ids")
    @classmethod
    def normalize_external_ids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            candidate = value.strip()
            if not candidate or len(candidate) > 128:
                raise ValueError("商品 ID 无效")
            if candidate not in normalized:
                normalized.append(candidate)
        return normalized


class ProductMonitorBatchDisableView(BaseModel):
    disabled_external_ids: list[str]
    disabled_count: int


class ProductManualCollectionRequest(BaseModel):
    external_id: str | None = Field(default=None, min_length=5, max_length=128)


class ProductActionCreateRequest(BaseModel):
    action_type: str = Field(
        pattern="^(title|cover|description|price|republish|traffic|hold|other)$"
    )
    status: str = Field(default="completed", pattern="^(planned|completed|cancelled)$")
    note: str = Field(default="", max_length=2000)
    cost: float = Field(default=0, ge=0, le=1_000_000)
    recommendation_id: str | None = Field(default=None, max_length=128)
    observation_days: int = Field(default=7, ge=1, le=90)


class ProductTrafficBatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=128)
    item_external_ids: list[str] = Field(min_length=1, max_length=5)
    planned_at: datetime
    actual_cost: float = Field(default=5.9, ge=0, le=1_000_000)
    plan_slot_id: str | None = Field(default=None, max_length=128)
    note: str = Field(default="", max_length=2000)
    checkpoint_collection_mode: str = Field(
        default="auto", pattern="^(auto|manual)$"
    )


class ProductTrafficBatchRecordRequest(BaseModel):
    """Record a multi-listing exposure purchase at confirmation time.

    The server, rather than the browser, supplies the authoritative start
    timestamp.  This keeps retries idempotent and prevents a planned time from
    being mistaken for an actual purchase time.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    item_external_ids: list[str] = Field(min_length=1, max_length=5)
    actual_cost: float = Field(default=5.9, ge=0, le=1_000_000)
    plan_slot_id: str | None = Field(default=None, max_length=128)
    note: str = Field(default="", max_length=2000)
    checkpoint_collection_mode: str = Field(
        default="auto", pattern="^(auto|manual)$"
    )
    confirmed_already_purchased: bool

    @model_validator(mode="after")
    def requires_purchase_confirmation(self):
        if not self.confirmed_already_purchased:
            raise ValueError("只有已经在闲鱼真实购买的批次才能记录")
        return self


class ProductTrafficBatchCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    completed_at: datetime | None = None
    actual_cost: float = Field(ge=0, le=1_000_000)
    total_exposure: int | None = Field(default=None, ge=0, le=1_000_000_000)
    note: str = Field(default="", max_length=2000)


class ProductTrafficCheckpointItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    external_id: str = Field(min_length=5, max_length=128)
    browse_count: int = Field(ge=0, le=1_000_000_000)
    collect_count: int = Field(default=0, ge=0, le=1_000_000_000)
    want_count: int = Field(default=0, ge=0, le=1_000_000_000)
    inquiry_count: int = Field(default=0, ge=0, le=1_000_000_000)


class ProductTrafficCheckpointCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    checkpoint: str = Field(pattern="^(h1|h6|h24|h48|h72)$")
    recorded_at: datetime | None = None
    items: list[ProductTrafficCheckpointItemRequest] = Field(min_length=1, max_length=5)
    note: str = Field(default="", max_length=2000)


class ProductTrafficCollectionModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_updated_at: datetime
    mode: str = Field(pattern="^(auto|manual)$")


class ProductTrafficCheckpointRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_updated_at: datetime


class ProductTrafficBaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_updated_at: datetime
    mode: str = Field(pattern="^(remote_refresh|manual)$")
    items: list[ProductTrafficCheckpointItemRequest] = Field(
        default_factory=list, max_length=5
    )

    @model_validator(mode="after")
    def manual_requires_items(self):
        if self.mode == "manual" and not self.items:
            raise ValueError("人工 T0 必须填写批次内全部商品")
        if self.mode == "remote_refresh" and self.items:
            raise ValueError("远程刷新模式不接受人工 T0 数据")
        return self


class ProductTrafficStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_updated_at: datetime
    expected_baseline_captured_at: datetime


class ProductTrafficActualStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_updated_at: datetime
    actual_started_at: datetime | None = None
    confirmed_already_purchased: bool
    items: list[ProductTrafficCheckpointItemRequest] = Field(
        default_factory=list, max_length=5
    )

    @model_validator(mode="after")
    def requires_purchase_confirmation(self):
        if not self.confirmed_already_purchased:
            raise ValueError("只有已经在闲鱼真实购买的批次才能补录")
        return self


class ProductTrafficReplanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_updated_at: datetime
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProductPlanSlotUpdateRequest(BaseModel):
    locked: bool


class ProductRecommendationUpdateRequest(BaseModel):
    status: str = Field(pattern="^(active|in_progress|completed|dismissed)$")


class ProductMarketKeywordUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = Field(pattern="^(recommended|custom)$")
    keyword: str = Field(min_length=2, max_length=80)
    save_as_common: bool = False


class ProductMarketSampleResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=1, le=100)
    title: str = Field(min_length=1, max_length=300)
    price: float | None = Field(default=None, ge=0, le=10_000_000)
    tags: list[str] = Field(default_factory=list, max_length=12)


class ProductMarketImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(min_length=2, max_length=80)
    captured_at: datetime
    results: list[ProductMarketSampleResultRequest] = Field(min_length=1, max_length=30)
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def positions_are_unique(self):
        positions = [result.position for result in self.results]
        if len(positions) != len(set(positions)):
            raise ValueError("搜索位置不能重复")
        for result in self.results:
            if any(not tag.strip() or len(tag.strip()) > 40 for tag in result.tags):
                raise ValueError("标签必须为 1–40 个字符")
        return self


class ProductMarketReminderSnoozeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: int = Field(default=2, ge=1, le=12)


class ProductLaunchPlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(min_length=2, max_length=80)
    title: str | None = Field(default=None, max_length=300)


class ProductLaunchPlanUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(proposed|planned|completed|cancelled)$")


class ProductModificationExperimentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable: str = Field(pattern="^(title|cover|description|price)$")
    before_value: str = Field(min_length=1, max_length=3000)
    after_value: str = Field(min_length=1, max_length=3000)
    observation_days: int = Field(default=7, ge=3, le=30)


class ProductModificationExperimentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern="^(keep|rollback|continue)$")
    note: str = Field(default="", max_length=1000)
