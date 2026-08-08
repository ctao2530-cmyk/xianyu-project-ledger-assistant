from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProductSnapshotView(BaseModel):
    date: str
    source: str
    browse_count: int
    collect_count: int
    want_count: int
    sold_count: int
    inquiry_count: int
    converted_project_count: int
    revenue_total: float
    profit_total: float


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
    collect_count: int
    want_count: int
    sold_count: int
    browse_delta: int | None
    inquiry_count: int
    inbound_message_count: int
    converted_project_count: int
    revenue_total: float
    profit_total: float
    inquiry_rate: float | None
    deal_rate: float | None
    history: list[ProductSnapshotView]
    recommendation: ProductRecommendationView | None
    actions: list[ProductActionView]


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
    safety_note: str


class ProductIntelligenceView(BaseModel):
    collection: ProductCollectionStatusView
    summary: ProductPortfolioSummary
    products: list[ProductView]
    candidates: list[ProductView]
    recommendations: list[ProductRecommendationView]
    publish_timing: PublishTimingView
    demand_opportunities: list[DemandOpportunityView]


class ProductRegisterRequest(BaseModel):
    item_reference: str = Field(min_length=5, max_length=1000)


class ProductMonitorUpdateRequest(BaseModel):
    enabled: bool


class ProductActionCreateRequest(BaseModel):
    action_type: str = Field(
        pattern="^(title|cover|description|price|republish|traffic|hold|other)$"
    )
    status: str = Field(default="completed", pattern="^(planned|completed|cancelled)$")
    note: str = Field(default="", max_length=2000)
    cost: float = Field(default=0, ge=0, le=1_000_000)
    recommendation_id: str | None = Field(default=None, max_length=128)
    observation_days: int = Field(default=7, ge=1, le=90)


class ProductRecommendationUpdateRequest(BaseModel):
    status: str = Field(pattern="^(active|in_progress|completed|dismissed)$")
