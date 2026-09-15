from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectRequirementBlueprintView(StrictModel):
    case_id: str | None = None
    customer_id: str | None = None
    metrics: dict[str, int] = Field(default_factory=dict)
    diff: dict[str, Any] = Field(default_factory=dict)
    id: int
    project_id: str
    version: int
    schema_version: str
    title: str
    readiness: str
    change_summary: str
    source_type: str
    source_label: str
    source_filename: str
    source_sha256: str
    imported_at: datetime | None
    created_at: datetime


class ProjectRequirementImportPreviewRequest(StrictModel):
    expected_revision: int = Field(ge=0)
    source_filename: str = Field(min_length=1, max_length=255)
    blueprint: dict[str, Any]


class ProjectRequirementImportPreview(StrictModel):
    project_id: str
    current_revision: int
    next_version: int
    preview_token: str
    source_sha256: str
    blueprint: dict[str, Any]


class ProjectRequirementImportCommitRequest(ProjectRequirementImportPreviewRequest):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    preview_token: str = Field(min_length=32, max_length=128)
    confirmed: Literal[True]


class ProjectRequirementImportResult(StrictModel):
    project_id: str
    requirement_version_id: int
    version: int
    revision: int
    idempotent: bool = False


TaskDraftClassification = Literal[
    "new", "unchanged", "update_allowed", "protected", "conflict"
]


class ProjectTaskDraftItemView(StrictModel):
    id: str
    task_key: str
    workspace_key: str
    stage_key: str
    classification: TaskDraftClassification
    current: dict[str, Any]
    proposed: dict[str, Any]
    protected_fields: list[str]
    conflict_reason: str
    selected: bool
    ordinal: int


class ProjectTaskDraftPreviewRequest(StrictModel):
    expected_revision: int = Field(ge=0)
    requirement_version_id: int | None = Field(default=None, ge=1)


class ProjectTaskDraftPreviewView(StrictModel):
    id: str
    project_id: str
    requirement_version_id: int
    requirement_version: int
    source_label: str
    project_revision: int
    preview_token: str
    status: str
    summary: dict[str, int]
    created_at: datetime
    expires_at: datetime
    items: list[ProjectTaskDraftItemView]


class ProjectTaskDraftConfirmRequest(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_revision: int = Field(ge=0)
    preview_id: str = Field(min_length=8, max_length=128)
    preview_token: str = Field(min_length=32, max_length=128)
    selected_task_keys: list[str] = Field(min_length=1, max_length=100)
    apply_allowed_updates_only: bool = True
    note: str = Field(min_length=2, max_length=2000)
    confirmed: Literal[True]


class ProjectTaskDraftConfirmResult(StrictModel):
    project_id: str
    preview_id: str
    revision: int
    created_task_ids: list[str]
    updated_task_ids: list[str]
    idempotent: bool = False
