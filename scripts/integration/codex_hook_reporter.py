#!/usr/bin/env python3
"""Convert supported official Codex Hook inputs into bounded sync events."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib import request
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.codex_sync_api import signature_for  # noqa: E402
from backend.app.config import Settings  # noqa: E402


EVENT_MAP = {
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    "PostToolUse": "tool_use",
    "PermissionRequest": "permission_request",
    "Stop": "stop",
}


def _event_type(data: dict) -> str | None:
    hook_name = str(data.get("hook_event_name") or "")
    if hook_name != "PostToolUse":
        return EVENT_MAP.get(hook_name)
    tool = str(data.get("tool_name") or "")
    if tool in {"apply_patch", "Edit", "Write"}:
        return "file_change"
    if tool == "Bash":
        command = str((data.get("tool_input") or {}).get("command") or "")
        if any(marker in command.lower() for marker in ("pytest", "test", "vitest", "playwright")):
            return "test_result"
        return "command"
    return "tool_use"


def _payload(data: dict, event_type: str) -> dict:
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    tool_response = data.get("tool_response") if isinstance(data.get("tool_response"), dict) else {}
    result = {
        "summary": str(data.get("message") or data.get("reason") or ""),
        "hook_event": str(data.get("hook_event_name") or ""),
        "tool_name": str(data.get("tool_name") or ""),
    }
    if event_type in {"command", "test_result"}:
        result["command"] = str(tool_input.get("command") or "")
        code = tool_response.get("exit_code", data.get("exit_code"))
        if isinstance(code, int):
            result["exit_code"] = code
        result["summary"] = str(
            tool_response.get("summary")
            or tool_response.get("output")
            or result["summary"]
        )
    elif event_type == "file_change":
        path = tool_input.get("path") or tool_input.get("file_path")
        result["files"] = [str(path)] if path else []
        result["summary"] = "Codex file-edit tool completed"
    return result


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(65_537)
        if len(raw) > 65_536:
            return 0
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            return 0
        event_type = _event_type(data)
        project_id = os.environ.get("XUNYING_PROJECT_ID", "").strip()
        if not event_type or not project_id:
            return 0
        settings = Settings()
        secret = settings.xunying_codex_event_secret.get_secret_value().strip()
        if not secret:
            return 0
        session_id = str(data.get("session_id") or os.environ.get("XUNYING_SESSION_ID") or "")
        if not session_id:
            return 0
        path = "/api/codex/events"
        body = json.dumps(
            {
                "request_id": f"hook-request-{uuid4()}",
                "event_id": f"hook-event-{uuid4()}",
                "project_id": project_id,
                "source": "hook",
                "external_session_id": session_id,
                "external_turn_id": str(data.get("turn_id") or ""),
                "event_type": event_type,
                "tool_name": str(data.get("tool_name") or ""),
                "task_key": os.environ.get("XUNYING_TASK_KEY") or None,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "payload": _payload(data, event_type),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = str(time.time())
        req = request.Request(
            settings.xunying_codex_api_base.rstrip("/") + path,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Xunying-Timestamp": timestamp,
                "X-Xunying-Signature": signature_for(
                    secret, timestamp, "POST", path, body
                ),
            },
        )
        with request.urlopen(req, timeout=4) as response:
            response.read(1)
    except Exception:
        # Observability must never block or steer the external Codex session.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
