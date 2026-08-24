from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


PredictionTarget = Literal[
    "workload_14d",
    "project_delay_risk",
    "cashflow_30d",
    "customer_followup_priority",
]
DataSufficiency = Literal["low", "medium", "high"]
PredictionRiskLevel = Literal[
    "low",
    "normal",
    "warning",
    "high",
    "urgent",
    "overloaded",
]


class PredictionDriver(BaseModel):
    code: str
    label: str
    detail: str
    impact: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class PredictionFact(BaseModel):
    key: str
    label: str
    value: float | int | str | bool | None
    unit: str | None = None
    evidence_ref: str


class PredictionResult(BaseModel):
    id: str
    run_id: str | None = None
    statement_type: Literal["prediction"] = "prediction"
    target: PredictionTarget
    entity_type: Literal["portfolio", "project", "customer"]
    entity_id: str | None = None
    entity_label: str | None = None
    horizon: str
    horizon_days: int = Field(ge=1, le=366)
    generated_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    prediction_value: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    risk_level: PredictionRiskLevel | None = None
    data_sufficiency: DataSufficiency
    method: str
    model_version: str
    summary: str
    drivers: list[PredictionDriver] = Field(default_factory=list)
    facts: list[PredictionFact] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    actual_value: Any | None = None
    evaluated_at: datetime | None = None
    evaluation_method: str | None = None


class PredictionRunView(BaseModel):
    id: str | None = None
    request_id: str | None = None
    record_status: Literal["live", "completed"] = "live"
    generated_at: datetime
    input_snapshot_hash: str
    ledger_revision: int
    feature_schema_version: str
    engine_version: str
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    results: list[PredictionResult]
    is_stale: bool = False


class PredictionLatestView(BaseModel):
    run: PredictionRunView
    workload: PredictionResult | None = None
    cashflow: PredictionResult | None = None
    high_risk_projects: list[PredictionResult] = Field(default_factory=list)
    priority_customers: list[PredictionResult] = Field(default_factory=list)


class PredictionRunRequest(BaseModel):
    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class PredictionEvaluationRequest(BaseModel):
    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    actual_value: float | int | bool | str
    evaluation_method: Literal["manual", "ledger_actual", "message_actual"] = "manual"
    evaluated_at: datetime | None = None
    note: str = Field(default="", max_length=1000)
