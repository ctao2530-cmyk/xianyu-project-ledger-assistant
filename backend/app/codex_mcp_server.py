"""Read-only context plus bounded lifecycle reporting for external Codex.

This MCP process never opens SQLite. Every read and report goes through the
loopback FastAPI surface and the same HMAC/service boundary as Hook events.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from mcp.server.fastmcp import FastMCP

from .codex_sync_api import signature_for
from .config import get_settings


mcp = FastMCP(
    "xunying-codex-sync",
    instructions=(
        "Read Xunying project/task context and report external Codex activity. "
        "These tools cannot control Codex, verify tasks, or mutate business data."
    ),
)


def _settings() -> tuple[str, str]:
    settings = get_settings()
    secret = settings.xunying_codex_event_secret.get_secret_value().strip()
    if not secret:
        raise RuntimeError("XUNYING_CODEX_EVENT_SECRET is not configured")
    return settings.xunying_codex_api_base.rstrip("/"), secret


def _headers(method: str, path: str, body: bytes = b"") -> dict[str, str]:
    _base, secret = _settings()
    timestamp = str(time.time())
    return {
        "X-Xunying-Timestamp": timestamp,
        "X-Xunying-Signature": signature_for(secret, timestamp, method, path, body),
        "Content-Type": "application/json",
    }


def _get(path: str) -> Any:
    base, _secret = _settings()
    with httpx.Client(timeout=10.0, trust_env=False) as client:
        response = client.get(base + path, headers=_headers("GET", path))
    response.raise_for_status()
    return response.json()


def _report(
    *,
    project_id: str,
    external_session_id: str,
    event_type: str,
    task_key: str | None = None,
    external_turn_id: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = "/api/codex/events"
    request_id = f"mcp-request-{uuid4()}"
    event_id = f"mcp-event-{uuid4()}"
    body = json.dumps(
        {
            "request_id": request_id,
            "event_id": event_id,
            "project_id": project_id,
            "source": "mcp",
            "external_session_id": external_session_id,
            "external_turn_id": external_turn_id,
            "event_type": event_type,
            "task_key": task_key,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    base, _secret = _settings()
    with httpx.Client(timeout=10.0, trust_env=False) as client:
        response = client.post(base + path, content=body, headers=_headers("POST", path, body))
    response.raise_for_status()
    return response.json()


@mcp.tool()
def xunying_get_project_context(project_id: str) -> dict[str, Any]:
    """Read one project's delivery context and exact task keys."""

    return _get(f"/api/codex/projects/{quote(project_id, safe='')}/context")


@mcp.tool()
def xunying_get_task_list(project_id: str) -> list[dict[str, Any]]:
    """List only stable-key tasks for one Xunying project."""

    return _get(f"/api/codex/projects/{quote(project_id, safe='')}/tasks")


@mcp.tool()
def xunying_get_task(project_id: str, task_key: str) -> dict[str, Any]:
    """Read a single task by exact project id and task_key."""

    return _get(
        f"/api/codex/projects/{quote(project_id, safe='')}/tasks/{quote(task_key, safe='')}"
    )


@mcp.tool()
def xunying_task_start(
    project_id: str,
    task_key: str,
    external_session_id: str,
    external_turn_id: str = "",
    summary: str = "",
) -> dict[str, Any]:
    """Mark only the independent Codex execution state as in_progress."""

    return _report(
        project_id=project_id,
        task_key=task_key,
        external_session_id=external_session_id,
        external_turn_id=external_turn_id,
        event_type="task_start",
        payload={"summary": summary},
    )


@mcp.tool()
def xunying_task_checkpoint(
    project_id: str,
    task_key: str,
    external_session_id: str,
    progress: str,
    changed_files: list[str] | None = None,
    remaining_work: str = "",
    problems: str = "",
    external_turn_id: str = "",
) -> dict[str, Any]:
    """Persist a bounded development checkpoint without changing human status."""

    return _report(
        project_id=project_id,
        task_key=task_key,
        external_session_id=external_session_id,
        external_turn_id=external_turn_id,
        event_type="checkpoint",
        payload={
            "progress": progress,
            "files": changed_files or [],
            "remaining_work": remaining_work,
            "problem": problems,
        },
    )


@mcp.tool()
def xunying_task_blocked(
    project_id: str,
    task_key: str,
    external_session_id: str,
    reason: str,
    remaining_work: str = "",
    external_turn_id: str = "",
) -> dict[str, Any]:
    """Record a blocker without modifying delivery dates or business status."""

    return _report(
        project_id=project_id,
        task_key=task_key,
        external_session_id=external_session_id,
        external_turn_id=external_turn_id,
        event_type="task_blocked",
        payload={"reason": reason, "remaining_work": remaining_work},
    )


@mcp.tool()
def xunying_report_test_result(
    project_id: str,
    external_session_id: str,
    command: str,
    exit_code: int,
    summary: str,
    task_key: str | None = None,
    external_turn_id: str = "",
) -> dict[str, Any]:
    """Persist one test command, exit code and bounded summary."""

    return _report(
        project_id=project_id,
        task_key=task_key,
        external_session_id=external_session_id,
        external_turn_id=external_turn_id,
        event_type="test_result",
        payload={"command": command, "exit_code": exit_code, "summary": summary},
    )


@mcp.tool()
def xunying_task_complete(
    project_id: str,
    task_key: str,
    external_session_id: str,
    summary: str,
    changed_files: list[str] | None = None,
    remaining_work: str = "",
    external_turn_id: str = "",
) -> dict[str, Any]:
    """Declare implementation complete; this can never verify the task."""

    return _report(
        project_id=project_id,
        task_key=task_key,
        external_session_id=external_session_id,
        external_turn_id=external_turn_id,
        event_type="task_complete",
        payload={
            "summary": summary,
            "files": changed_files or [],
            "remaining_work": remaining_work,
            "verification": "pending_human_acceptance",
        },
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
