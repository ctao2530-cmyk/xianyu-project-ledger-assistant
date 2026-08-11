from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class BusinessAnalysisRecommendation(BaseModel):
    id: str
    domain: Literal["portfolio", "products", "customers", "projects", "finance", "data"]
    priority: Literal["low", "medium", "high"]
    title: str
    action: str
    reason: str
    target_page: str
    execution_mode: Literal["manual"] = "manual"
    evidence_refs: list[str] = Field(default_factory=list)


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


class BusinessAnalysisOverview(BaseModel):
    summary: str
    metrics: BusinessAnalysisMetrics
    insights: list[BusinessAnalysisInsight]
    recommendations: list[BusinessAnalysisRecommendation]
    data_sources: list[BusinessAnalysisDataSource]
    future_fields: list[BusinessAnalysisFutureField]
    data_gaps: list[str]
    analysis_method: Literal["evidence_rules_v1"] = "evidence_rules_v1"
    ledger_revision: int
    period: BusinessAnalysisPeriod
    generated_at: datetime
