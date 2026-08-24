from __future__ import annotations

from typing import Any

from .base import RuntimeEvent


def _ids(params: dict[str, Any]) -> tuple[str, str, str]:
    item = params.get("item") if isinstance(params.get("item"), dict) else {}
    return (
        str(params.get("threadId") or item.get("threadId") or ""),
        str(params.get("turnId") or item.get("turnId") or ""),
        str(params.get("itemId") or item.get("id") or ""),
    )


def normalize_notification(method: str, params: dict[str, Any]) -> RuntimeEvent | None:
    """Normalize only names advertised by the current App Server schema.

    Unknown notifications are deliberately ignored instead of being guessed.
    The raw payload is bounded and redacted later by ``CodexSyncService``.
    """

    thread_id, turn_id, item_id = _ids(params)
    mapping = {
        "thread/started": "run_started",
        "turn/started": "task_started",
        "turn/plan/updated": "plan_updated",
        "item/plan/delta": "plan_updated",
        "item/fileChange/patchUpdated": "diff_updated",
        "turn/diff/updated": "diff_updated",
        "error": "run_failed",
    }
    if method in mapping:
        return RuntimeEvent(mapping[method], thread_id, turn_id, item_id, payload=params)
    if method == "item/started":
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        kind = str(item.get("type") or "")
        event_type = "command_started" if kind in {"commandExecution", "command"} else "task_started"
        return RuntimeEvent(event_type, thread_id, turn_id, item_id, payload=params)
    if method == "item/completed":
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        kind = str(item.get("type") or "")
        if kind in {"commandExecution", "command"}:
            event_type = "command_completed"
        elif kind in {"fileChange", "patch"}:
            event_type = "file_changed"
        else:
            event_type = "checkpoint"
        return RuntimeEvent(event_type, thread_id, turn_id, item_id, payload=params)
    if method == "turn/completed":
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        status = str(turn.get("status") or params.get("status") or "completed").lower()
        if status in {"failed", "error"}:
            event_type = "run_failed"
        elif status in {"interrupted", "cancelled", "canceled"}:
            event_type = "run_interrupted"
        else:
            event_type = "run_completed"
        return RuntimeEvent(event_type, thread_id, turn_id or str(turn.get("id") or ""), payload=params)
    if method in {
        "item/commandExecution/outputDelta",
        "command/exec/outputDelta",
        "item/commandExecution/terminalInteraction",
    }:
        return RuntimeEvent("checkpoint", thread_id, turn_id, item_id, payload=params)
    if method in {"item/fileChange/outputDelta"}:
        return RuntimeEvent("diff_updated", thread_id, turn_id, item_id, payload=params)
    return None


def normalize_server_request(
    request_id: str, method: str, params: dict[str, Any]
) -> RuntimeEvent | None:
    if method not in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "execCommandApproval",
        "applyPatchApproval",
    }:
        return None
    thread_id, turn_id, item_id = _ids(params)
    thread_id = thread_id or str(params.get("conversationId") or "")
    item_id = item_id or str(params.get("callId") or "")
    payload = dict(params)
    if "command" in method.lower() or method == "execCommandApproval":
        payload["approval_kind"] = "command"
    elif "permissions" in method:
        payload["approval_kind"] = "permissions"
    else:
        payload["approval_kind"] = "file_change"
    if isinstance(payload.get("command"), list):
        payload["command"] = " ".join(str(part) for part in payload["command"])
    if method == "applyPatchApproval" and isinstance(payload.get("fileChanges"), dict):
        payload["files"] = list(payload["fileChanges"].keys())
    payload["server_request_id"] = request_id
    return RuntimeEvent(
        "approval_requested",
        thread_id,
        turn_id,
        item_id,
        request_id,
        payload,
    )
