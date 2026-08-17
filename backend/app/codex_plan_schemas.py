from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


StableKey = str


class RepositorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["requirement_only", "repository"]
    head_sha: str = Field(default="", max_length=64)
    branch: str = Field(default="", max_length=255)
    dirty: bool = False


class PlanEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low_hours: float = Field(ge=0.5, le=10_000)
    expected_hours: float = Field(ge=0.5, le=10_000)
    high_hours: float = Field(ge=0.5, le=10_000)
    confidence: Literal["low", "medium", "high"]

    @model_validator(mode="after")
    def validate_range(self) -> "PlanEstimate":
        if not self.low_hours <= self.expected_hours <= self.high_hours:
            raise ValueError("工时必须满足 low <= expected <= high")
        return self


class PlanAcceptancePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    title: str = Field(min_length=2, max_length=300)
    verification_type: Literal[
        "automated_test", "manual_test", "visual_review", "document_review"
    ]


class PlanDeliverable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deliverable_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    title: str = Field(min_length=2, max_length=300)
    description: str = Field(default="", max_length=3000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=30)


class PlanStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    title: str = Field(min_length=2, max_length=300)
    estimated_hours: float = Field(gt=0, le=5000)
    depends_on: list[str] = Field(default_factory=list, max_length=30)
    deliverable_keys: list[str] = Field(default_factory=list, max_length=30)


class PlanTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    stage_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    title: str = Field(min_length=2, max_length=300)
    description: str = Field(default="", max_length=5000)
    estimated_hours: float = Field(gt=0, le=2000)
    depends_on: list[str] = Field(default_factory=list, max_length=40)
    expected_paths: list[str] = Field(default_factory=list, max_length=60)
    acceptance_points: list[PlanAcceptancePoint] = Field(min_length=1, max_length=40)
    test_commands: list[str] = Field(default_factory=list, max_length=30)
    risks: list[str] = Field(default_factory=list, max_length=30)
    included: bool = True
    note: str = Field(default="", max_length=2000)


class CodexDevelopmentPlanDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=2, max_length=300)
    summary: str = Field(min_length=2, max_length=5000)
    repository_snapshot: RepositorySnapshot
    estimate: PlanEstimate
    assumptions: list[str] = Field(default_factory=list, max_length=40)
    risks: list[str] = Field(default_factory=list, max_length=40)
    deliverables: list[PlanDeliverable] = Field(min_length=1, max_length=60)
    stages: list[PlanStage] = Field(min_length=1, max_length=40)
    tasks: list[PlanTask] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_keys_and_references(self) -> "CodexDevelopmentPlanDocument":
        def unique(values: list[str], label: str) -> set[str]:
            result = set(values)
            if len(result) != len(values):
                raise ValueError(f"{label} Key 不能重复")
            return result

        deliverables = unique([row.deliverable_key for row in self.deliverables], "交付物")
        stages = unique([row.stage_key for row in self.stages], "阶段")
        tasks = unique([row.task_key for row in self.tasks], "任务")
        points = unique(
            [point.point_key for row in self.tasks for point in row.acceptance_points],
            "验收点",
        )
        del points
        for row in self.stages:
            if row.stage_key in row.depends_on or not set(row.depends_on).issubset(stages):
                raise ValueError(f"阶段 {row.stage_key} 的依赖无效")
            if not set(row.deliverable_keys).issubset(deliverables):
                raise ValueError(f"阶段 {row.stage_key} 引用了不存在的交付物")
        for row in self.tasks:
            if row.stage_key not in stages:
                raise ValueError(f"任务 {row.task_key} 引用了不存在的阶段")
            if row.task_key in row.depends_on or not set(row.depends_on).issubset(tasks):
                raise ValueError(f"任务 {row.task_key} 的依赖无效")
        return self


class RepositoryBindingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    requirement_case_id: str = Field(min_length=1, max_length=128)
    project_id: str | None = Field(default=None, max_length=128)
    repository_path: str = Field(min_length=1, max_length=4096)


class RepositoryBindingView(BaseModel):
    id: str
    requirement_case_id: str | None
    project_id: str | None
    repository_name: str
    default_branch: str
    current_head_sha: str
    enabled: bool
    updated_at: datetime
    idempotent: bool = False


class CodexPlanGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    requirement_case_id: str = Field(min_length=1, max_length=128)
    expected_requirement_version: int = Field(ge=1)
    binding_id: str | None = Field(default=None, max_length=128)


class CodexPlanDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_updated_at: datetime
    document: CodexDevelopmentPlanDocument


class CodexPlanConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_updated_at: datetime
    expected_requirement_version: int = Field(ge=1)
    expected_revision: int = Field(ge=0)
    confirmed: Literal[True]


class CodexPlanView(BaseModel):
    id: str
    requirement_case_id: str
    requirement_version_id: int
    requirement_version: int
    project_id: str | None
    binding_id: str | None
    version: int
    status: Literal["draft", "confirmed", "superseded", "cancelled"]
    source: str
    repository_name: str | None
    repository_mode: Literal["requirement_only", "repository"]
    repository_head_sha: str
    repository_branch: str
    repository_dirty: bool
    raw_document: CodexDevelopmentPlanDocument
    document: CodexDevelopmentPlanDocument
    model: str
    reasoning_effort: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    idempotent: bool = False


class CodexPlanConfirmResult(BaseModel):
    plan: CodexPlanView
    project_id: str
    task_ids: list[str]
    revision: int
    idempotent: bool = False
