from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TrafficGrowthProductView(BaseModel):
    external_id: str
    title: str
    historical_project_count: int
    historical_realized_profit: float
    historical_profit_is_attributed: bool = False


class TrafficExperimentCellView(BaseModel):
    id: str
    phase: str
    window_bucket: str
    time_range: str
    repeat_index: int
    status: str
    scheduled_for: datetime | None
    batch_id: str | None
    actual_bucket: str | None
    exclusion_reason: str | None
    browse_delta: int | None = None
    inquiry_delta: int | None = None
    analysis_eligible: bool = False


class TrafficTimeWindowResultView(BaseModel):
    window_bucket: str
    time_range: str
    valid_batch_count: int
    browse_delta: int
    inquiry_delta: int
    average_browse_delta: float
    average_inquiry_delta: float
    rank: int | None = None
    provisional_winner: bool = False
    confirmed_winner: bool = False


class TrafficScaleCohortView(BaseModel):
    id: str
    stage: str
    status: str
    target_batches_per_week: int
    weekly_budget: float
    no_other_promotion_confirmed: bool
    listing_unchanged_confirmed: bool
    started_at: datetime | None
    ended_at: datetime | None
    tail_ends_at: datetime | None
    commercial_followup_ends_at: datetime | None
    batch_ids: list[str] = Field(default_factory=list)
    batch_count: int = 0
    actual_cost: float = 0


class TrafficCommercialAttributionView(BaseModel):
    id: str
    scope: str
    cohort_id: str | None
    batch_id: str | None
    conversation_id: int
    project_id: str | None
    project_name: str | None
    status: str
    source: str
    first_inbound_at: datetime
    window_start: datetime
    window_end: datetime
    confirmed_by_user_at: datetime | None
    realized_profit: float
    updated_at: datetime


class TrafficGrowthMetricsView(BaseModel):
    actual_cost: float
    attributed_inquiry_count: int
    paid_project_count: int
    realized_contribution_profit: float
    profit_to_cost_ratio: float | None
    net_after_traffic: float
    active_projects: int
    delivery_capacity: int
    observation_complete: bool
    limitations: list[str] = Field(default_factory=list)


class TrafficBudgetDecisionView(BaseModel):
    id: str | None = None
    recommendation: Literal["scale", "hold", "reduce", "pause"]
    status: str
    from_stage: str
    to_stage: str
    current_weekly_budget: float
    recommended_weekly_budget: float
    metrics: TrafficGrowthMetricsView
    evidence: list[str]
    rules_version: str
    decided_at: datetime
    applied_at: datetime | None = None
    can_apply: bool = False


class TrafficExperimentView(BaseModel):
    id: str
    mode: str
    status: str
    phase: str
    product: TrafficGrowthProductView
    target_windows: list[str]
    baseline_weekly_budget: float
    current_weekly_budget: float
    hard_weekly_cap: float
    base_batch_cost: float
    started_at: datetime
    completed_at: datetime | None
    valid_exploration_batches: int
    required_exploration_batches: int = 6
    valid_confirmation_batches: int
    required_confirmation_batches: int = 2
    provisional_winner: str | None
    confirmed_winner: str | None
    cells: list[TrafficExperimentCellView]
    time_windows: list[TrafficTimeWindowResultView]
    cohorts: list[TrafficScaleCohortView]
    attributions: list[TrafficCommercialAttributionView]
    metrics: TrafficGrowthMetricsView
    budget_decision: TrafficBudgetDecisionView
    next_cell: TrafficExperimentCellView | None
    warnings: list[str]
    updated_at: datetime


class TrafficGrowthOverviewView(BaseModel):
    active_experiment: TrafficExperimentView | None
    historical_experiments: list[TrafficExperimentView] = Field(default_factory=list)
    recommended_candidate: TrafficGrowthProductView | None = None
    safety_notice: str


class TrafficExperimentPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    item_external_id: str = Field(min_length=5, max_length=128)
    target_windows: list[str] = Field(default_factory=lambda: ["12", "16", "20"])
    baseline_weekly_budget: float = Field(default=24, ge=0, le=1_000_000)
    hard_weekly_cap: float = Field(default=48, ge=0, le=1_000_000)

    @field_validator("target_windows")
    @classmethod
    def validate_windows(cls, value: list[str]) -> list[str]:
        normalized = [str(window).zfill(2) for window in value]
        if len(normalized) != 3 or len(set(normalized)) != 3:
            raise ValueError("时段实验必须包含三个不同的两小时时间窗")
        if any(not window.isdigit() or int(window) < 0 or int(window) > 22 or int(window) % 2 for window in normalized):
            raise ValueError("时段必须使用 00–22 的偶数小时桶")
        return normalized

    @model_validator(mode="after")
    def cap_covers_baseline(self):
        if self.hard_weekly_cap < self.baseline_weekly_budget:
            raise ValueError("硬预算上限不能低于基准周预算")
        return self


class TrafficExperimentPreviewView(BaseModel):
    product: TrafficGrowthProductView
    target_windows: list[str]
    schedule: list[TrafficExperimentCellView]
    baseline_weekly_budget: float
    hard_weekly_cap: float
    expected_batch_count: int
    expected_minimum_days: int
    estimated_cost: float
    warnings: list[str]
    preserves: list[str]


class TrafficExperimentCreateRequest(TrafficExperimentPreviewRequest):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")


class TrafficExperimentAdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_updated_at: datetime


class TrafficExperimentBindBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    batch_id: str = Field(min_length=8, max_length=128)


class TrafficScaleCohortCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    stage: Literal["S1", "S2", "S3"]
    no_other_promotion_confirmed: bool
    listing_unchanged_confirmed: bool

    @model_validator(mode="after")
    def requires_measurement_declarations(self):
        if not self.no_other_promotion_confirmed or not self.listing_unchanged_confirmed:
            raise ValueError("扩量队列必须确认没有其他同期推广且商品表达保持不变")
        return self


class TrafficScaleCohortBindBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    batch_id: str = Field(min_length=8, max_length=128)


class TrafficAttributionRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")


class TrafficAttributionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_updated_at: datetime
    project_id: str | None = Field(default=None, max_length=128)
    reason: str = Field(default="", max_length=500)


class TrafficBudgetDecisionRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")


class TrafficBudgetDecisionApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_experiment_updated_at: datetime
