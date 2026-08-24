from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CalibrationSufficiency = Literal["insufficient", "exploratory", "actionable"]
CalibrationDecisionAction = Literal["adopt", "reject"]


class CalibrationThresholds(BaseModel):
    exploratory_min: Literal[3] = 3
    actionable_min: Literal[5] = 5


class CalibrationMetrics(BaseModel):
    signed_bias_hours: float | None = None
    mae_hours: float | None = None
    overrun_rate: float | None = Field(default=None, ge=0, le=1)
    interval_coverage: float | None = Field(default=None, ge=0, le=1)
    multiplier_median: float | None = None
    multiplier_lower: float | None = None
    multiplier_upper: float | None = None


class CalibrationCandidateView(BaseModel):
    project_id: str
    project_name: str
    project_status: str
    estimated_hours: float
    actual_hours: float
    verified_progress: int = Field(ge=0, le=100)
    available_at: datetime
    finalized_at: datetime | None
    freeze_id: str | None = None
    freeze_version: int | None = Field(default=None, ge=1)
    sample_readiness_status: str
    freeze_stale: bool = False
    readiness_actions: list[str] = Field(default_factory=list)
    eligible: bool
    exclusion_code: str = ""
    exclusion_reason: str = ""


class CalibrationSummaryView(BaseModel):
    run_id: str | None = None
    record_status: Literal["live", "completed"] = "live"
    cutoff_at: datetime
    input_snapshot_hash: str
    sample_count: int = Field(ge=0)
    sufficiency: CalibrationSufficiency
    thresholds: CalibrationThresholds = Field(default_factory=CalibrationThresholds)
    algorithm_version: str
    metrics: CalibrationMetrics
    sample_start_at: datetime | None = None
    sample_end_at: datetime | None = None
    candidates: list[CalibrationCandidateView] = Field(default_factory=list)
    is_stale: bool = False


class CalibrationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    cutoff_at: datetime | None = None


class CalibrationQuoteAssistView(BaseModel):
    project_id: str
    project_name: str
    original_estimated_hours: float
    run_id: str | None = None
    suggestion_id: str | None = None
    suggestion_revision: int = Field(default=0, ge=0)
    sample_count: int = Field(ge=0)
    sufficiency: CalibrationSufficiency
    suggested_hours: float | None = None
    lower_hours: float | None = None
    upper_hours: float | None = None
    adopted_hours: float | None = None
    status: Literal["unavailable", "preview", "pending", "adopted", "rejected"]
    sample_start_at: datetime | None = None
    sample_end_at: datetime | None = None
    basis: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    formula: str = "采用工时 × 目标时薪 ×（1 + 风险缓冲）"


class CalibrationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    expected_revision: int = Field(ge=0)
    action: CalibrationDecisionAction
    adopted_hours: float | None = Field(default=None, gt=0, le=10000)
    note: str = Field(default="", max_length=2000)
