from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CodexEventType = Literal[
    "session_start",
    "session_end",
    "task_start",
    "checkpoint",
    "task_blocked",
    "test_result",
    "task_complete",
    "file_change",
    "command",
    "tool_use",
    "permission_request",
    "stop",
    "run_started",
    "plan_updated",
    "task_started",
    "command_started",
    "command_completed",
    "file_changed",
    "diff_updated",
    "test_reported",
    "approval_requested",
    "task_implemented",
    "run_failed",
    "run_completed",
    "run_interrupted",
]
CodexEventSource = Literal["mcp", "hook", "script", "cli", "ide", "app_server", "mock"]


class CodexEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    binding_id: str | None = Field(default=None, min_length=1, max_length=128)
    source: CodexEventSource = "mcp"
    external_session_id: str = Field(min_length=1, max_length=255)
    external_turn_id: str = Field(default="", max_length=255)
    event_type: CodexEventType
    tool_name: str = Field(default="", max_length=128)
    task_key: str | None = Field(default=None, min_length=1, max_length=128)
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class CodexEventReceipt(BaseModel):
    event_id: str
    run_id: str
    project_id: str
    task_key: str | None
    task_mapped: bool
    task_execution_status: str | None
    idempotent: bool = False
    received_at: datetime


class CodexTaskContext(BaseModel):
    task_key: str
    title: str
    stage_key: str | None
    human_status: str
    codex_execution_status: str
    estimated_hours: float
    actual_hours: float
    acceptance_points: list[Any]
    test_commands: list[str]


class CodexProjectContext(BaseModel):
    project_id: str
    project_name: str
    project_status: str
    project_progress: int
    binding: dict[str, Any] | None
    tasks: list[CodexTaskContext]
    safety: dict[str, bool]


class CodexSyncEventView(BaseModel):
    event_id: str
    run_id: str
    event_type: str
    source: str
    tool_name: str
    task_key: str | None
    task_mapped: bool
    summary: str
    files: list[str]
    remaining_work: str
    blocker: str
    command: str
    exit_code: int | None
    payload: dict[str, Any]
    occurred_at: datetime
    received_at: datetime


class CodexRunView(BaseModel):
    id: str
    source: str
    external_session_id: str
    external_turn_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    last_event_at: datetime


class CodexProjectSyncView(BaseModel):
    project_id: str
    connection_status: Literal[
        "not_connected",
        "idle",
        "running",
        "blocked",
        "failed",
        "completed",
        "disconnected",
    ]
    current_run: CodexRunView | None
    current_task: CodexTaskContext | None
    last_sync_at: datetime | None
    runs: list[CodexRunView]
    events: list[CodexSyncEventView]
    counts: dict[str, int]
