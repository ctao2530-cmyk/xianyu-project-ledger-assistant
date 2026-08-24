from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .codex_sync_schemas import CodexSyncEventView, CodexTaskContext


class ManagedRunCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    task_key: str = Field(min_length=1, max_length=128)
    binding_id: str = Field(min_length=1, max_length=128)
    model: str = Field(default="", max_length=128)
    reasoning_effort: str = Field(default="", max_length=32)
    sandbox_mode: Literal["workspace-write"] = "workspace-write"
    approval_mode: Literal["untrusted"] = "untrusted"
    acknowledge_dirty_repository: bool = False


class ManagedRunActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)


class ApprovalDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    decision: Literal["approve_once", "reject", "cancel"]


class RuntimeCapabilitiesView(BaseModel):
    runtime_type: str
    available: bool
    version: str
    supports_resume: bool
    supports_cancel: bool
    supports_approvals: bool
    supports_event_stream: bool
    detail: str


class ManagedApprovalView(BaseModel):
    id: str
    run_id: str
    server_request_id: str
    thread_id: str
    turn_id: str
    item_id: str
    approval_kind: str
    risk_level: str
    reason: str
    command: str
    cwd: str
    status: str
    created_at: datetime
    decided_at: datetime | None


class ManagedRunView(BaseModel):
    id: str
    project_id: str
    binding_id: str | None
    task_key: str | None
    runtime_type: str
    thread_id: str
    turn_id: str
    status: str
    base_commit_sha: str
    branch: str
    worktree_path: str
    model: str
    reasoning_effort: str
    sandbox_mode: str
    approval_mode: str
    started_at: datetime
    paused_at: datetime | None
    finished_at: datetime | None
    last_event_at: datetime
    approvals: list[ManagedApprovalView]


class ManagedRuntimeProjectView(BaseModel):
    project_id: str
    runtime: RuntimeCapabilitiesView
    tasks: list[CodexTaskContext]
    binding: dict[str, Any] | None
    confirmed_plan_id: str | None
    ready: bool
    readiness_reasons: list[str]
    current_run: ManagedRunView | None
    runs: list[ManagedRunView]
    events: list[CodexSyncEventView]


class ManagedDiffView(BaseModel):
    run_id: str
    base_commit_sha: str
    branch: str
    diff: str
    truncated: bool = False
