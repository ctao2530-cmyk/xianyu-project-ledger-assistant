from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AcceptanceStatus = Literal[
    "pending",
    "implemented",
    "test_passed",
    "verified",
    "failed",
    "waived",
]
TimeCategory = Literal["development", "testing", "fixing", "communication"]


class ProgressMetricView(BaseModel):
    percent: int = Field(ge=0, le=100)
    completed_weight: float = Field(ge=0)
    total_weight: float = Field(ge=0)


class ProjectProgressView(BaseModel):
    project_id: str
    codex_execution: ProgressMetricView
    implemented: ProgressMetricView
    verified_delivery: ProgressMetricView
    weight_basis: str
    warnings: list[str]
    waived_count: int
    waived_counted: int


class AcceptanceEvidenceView(BaseModel):
    id: str
    point_id: str | None
    point_key: str
    run_id: str | None
    evidence_type: str
    file_paths: list[str]
    test_command: str
    exit_code: int | None
    test_summary: str
    commit_sha: str
    manual_note: str
    status: str
    created_at: datetime
    verified_at: datetime | None


class AcceptancePointView(BaseModel):
    id: str
    task_id: str
    task_key: str | None
    task_title: str
    point_key: str
    title: str
    verification_type: str
    source: Literal["codex_plan", "manual_historical"]
    status: AcceptanceStatus
    point_weight: float | None
    waived_counts: bool
    waiver_reason: str
    active: bool
    verified_at: datetime | None
    updated_at: datetime
    evidence: list[AcceptanceEvidenceView]


class TimeEntryView(BaseModel):
    id: str
    task_id: str | None
    run_id: str | None
    category: str
    source: str
    hours: float
    note: str
    adjustment_of_id: str | None
    started_at: datetime | None
    ended_at: datetime | None
    occurred_at: datetime


class TimeSummaryView(BaseModel):
    total_hours: float
    codex_hours: float
    manual_hours: float
    by_category: dict[str, float]
    estimated_hours: float
    variance_hours: float
    variance_percent: float | None
    entries: list[TimeEntryView]


class GitLinkView(BaseModel):
    id: str
    task_id: str
    point_id: str | None
    commit_sha: str
    branch: str
    status: str
    note: str
    created_at: datetime


class GitStateView(BaseModel):
    available: bool
    repository_name: str
    branch: str
    base_commit: str
    current_commit: str
    dirty: bool
    changed_files: list[str]
    commits: list[dict[str, str]]
    error: str = ""


class DeliveryTaskView(BaseModel):
    task_id: str
    task_key: str | None
    title: str
    estimated_hours: float
    actual_hours: float
    acceptance_total: int
    acceptance_verified: int
    acceptance_waived: int
    tests_passed: int
    commits: list[str]
    open_issues: list[str]


class DeliveryItemView(BaseModel):
    deliverable_key: str
    title: str
    description: str
    task_ids: list[str]
    acceptance_total: int
    acceptance_verified: int


class DeliveryChecklistView(BaseModel):
    project_id: str
    plan_id: str | None
    deliverables: list[DeliveryItemView]
    tasks: list[DeliveryTaskView]
    delivery_files: list[str]
    unresolved_issues: list[str]
    generated_at: datetime


class ProjectOutcomeView(BaseModel):
    project_id: str
    requirement_complexity: float | None
    estimated_hours: float
    actual_hours: float
    estimated_delivery_at: str
    actual_completed_at: datetime | None
    blocker_count: int
    change_order_count: int
    test_failure_count: int
    rework_hours: float
    verified_progress: int
    revenue: float
    profit: float
    realized_hourly_rate: float
    available_at: datetime
    finalized_at: datetime | None


class ProjectOutcomeFreezeView(BaseModel):
    id: str
    project_id: str
    version: int = Field(ge=1)
    supersedes_freeze_id: str | None
    source_ledger_revision: int = Field(ge=0)
    input_hash: str
    outcome: ProjectOutcomeView
    evidence_summary: dict[str, int | float | str | bool]
    confirmed_scope_complete: bool
    confirmed_time_complete: bool
    confirmation_note: str
    frozen_at: datetime
    created_at: datetime
    is_stale: bool = False


class SampleReadinessBlocker(BaseModel):
    code: str
    message: str
    action: str


class ProjectSampleReadinessView(BaseModel):
    project_id: str
    status: Literal[
        "missing_scope",
        "needs_verification",
        "needs_time",
        "terminal",
        "ready_to_freeze",
        "frozen",
        "stale",
    ]
    can_freeze: bool
    calibration_eligible: bool
    active_task_count: int = Field(ge=0)
    active_point_count: int = Field(ge=0)
    verified_point_count: int = Field(ge=0)
    waived_point_count: int = Field(ge=0)
    estimated_hours: float = Field(ge=0)
    actual_hours: float = Field(ge=0)
    verified_progress: int = Field(ge=0, le=100)
    blockers: list[SampleReadinessBlocker]
    latest_freeze: ProjectOutcomeFreezeView | None = None
    freeze_history: list[ProjectOutcomeFreezeView] = Field(default_factory=list)


class ProjectVerificationView(BaseModel):
    revision: int
    project_id: str
    legacy_progress: int | None
    progress_source: str
    progress: ProjectProgressView
    points: list[AcceptancePointView]
    time: TimeSummaryView
    git: GitStateView
    git_links: list[GitLinkView]
    delivery: DeliveryChecklistView
    outcome: ProjectOutcomeView
    sample_readiness: ProjectSampleReadinessView


class AcceptanceDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=0)
    status: Literal["pending", "verified", "failed", "waived"]
    reason: str = Field(default="", max_length=2000)
    waived_counts: bool = False


class ManualAcceptancePointItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_id: str = Field(min_length=1, max_length=128)
    point_key: str = Field(
        min_length=2,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$",
    )
    title: str = Field(min_length=2, max_length=300)
    verification_type: Literal[
        "automated_test", "manual_test", "visual_review", "document_review"
    ]
    point_weight: float | None = Field(default=None, gt=0, le=1000)


class ManualAcceptancePointsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=2, max_length=2000)
    points: list[ManualAcceptancePointItem] = Field(min_length=1, max_length=100)


class RetireAcceptancePointInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=2, max_length=2000)


class ProjectOutcomeFreezeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=0)
    confirmed_scope_complete: Literal[True]
    confirmed_time_complete: Literal[True]
    confirmation_note: str = Field(min_length=4, max_length=2000)


class TestExecutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=0)
    point_id: str = Field(min_length=1, max_length=128)
    command: str = Field(min_length=1, max_length=2000)
    timeout_seconds: int = Field(default=300, ge=1, le=1800)
    confirmed: Literal[True]


class ManualTimeEntryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=0)
    task_id: str = Field(min_length=1, max_length=128)
    category: TimeCategory
    hours: float = Field(gt=0, le=1000)
    note: str = Field(min_length=2, max_length=2000)
    occurred_at: datetime | None = None


class TimeAdjustmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=0)
    hours_delta: float = Field(ge=-1000, le=1000)
    reason: str = Field(min_length=2, max_length=2000)


class GitLinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=0)
    task_id: str = Field(min_length=1, max_length=128)
    point_id: str | None = Field(default=None, max_length=128)
    commit_sha: str = Field(pattern=r"^[0-9a-fA-F]{7,64}$")
    note: str = Field(default="", max_length=2000)
