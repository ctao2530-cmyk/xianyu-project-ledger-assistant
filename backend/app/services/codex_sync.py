from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import or_, select

from ..codex_sync_schemas import (
    CodexEventInput,
    CodexEventReceipt,
    CodexProjectContext,
    CodexProjectSyncView,
    CodexRunView,
    CodexSyncEventView,
    CodexTaskContext,
)
from ..database import Database
from ..models import (
    BusinessProject,
    BusinessTask,
    CodexEvent,
    CodexProjectBinding,
    CodexRun,
    CodexTaskEvidence,
    utcnow,
)
from .event_hub import EventHub

if TYPE_CHECKING:
    from .codex_verification import CodexVerificationService


MAX_PAYLOAD_BYTES = 64 * 1024
MAX_TEXT = 8_000
MAX_SUMMARY = 2_000
MAX_COMMAND = 2_000
MAX_OUTPUT = 4_000
MAX_FILES = 50
MAX_FILE_PATH = 500
MAX_COLLECTION = 100
MAX_DEPTH = 8

SENSITIVE_KEYS = re.compile(
    r"(^|[_-])(authorization|cookie|set_cookie|token|password|passwd|secret|api[_-]?key|access[_-]?key|private[_-]?key|headers?|environment|env)([_-]|$)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(Basic)\s+[A-Za-z0-9+/=]+"),
    re.compile(
        r"(?i)\b(token|cookie|authorization|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+"
    ),
)


class CodexSyncError(RuntimeError):
    def __init__(self, code: str, safe_message: str, status_code: int = 400) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"…[truncated {len(value) - limit} chars]"


def _redact_string(value: str, limit: int = MAX_TEXT) -> str:
    redacted = value
    for pattern in SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return _truncate(redacted, limit)


def sanitize_payload(value: Any, *, depth: int = 0, key: str = "") -> Any:
    """Bound and redact event data before any persistent copy is made."""

    if SENSITIVE_KEYS.search(key):
        return "[REDACTED]"
    if depth >= MAX_DEPTH:
        return "[TRUNCATED_DEPTH]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= MAX_COLLECTION:
                result["__truncated_items__"] = len(value) - MAX_COLLECTION
                break
            normalized_key = _truncate(str(raw_key), 128)
            result[normalized_key] = sanitize_payload(
                item, depth=depth + 1, key=normalized_key
            )
        return result
    if isinstance(value, (list, tuple)):
        return [
            sanitize_payload(item, depth=depth + 1, key=key)
            for item in list(value)[:MAX_COLLECTION]
        ]
    if isinstance(value, str):
        limit = MAX_OUTPUT if key.lower() in {"output", "stdout", "stderr"} else MAX_TEXT
        return _redact_string(value, limit)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_string(str(value))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


class CodexSyncService:
    def __init__(
        self,
        database: Database,
        event_hub: EventHub,
        verification: "CodexVerificationService | None" = None,
    ) -> None:
        self.database = database
        self.event_hub = event_hub
        self.verification = verification

    @staticmethod
    def normalized_envelope(event: CodexEventInput) -> dict[str, Any]:
        payload = sanitize_payload(event.payload)
        if isinstance(payload, dict):
            for field, limit in (
                ("summary", MAX_SUMMARY),
                ("progress", MAX_SUMMARY),
                ("remaining_work", MAX_SUMMARY),
                ("blocker", MAX_SUMMARY),
                ("problem", MAX_SUMMARY),
                ("command", MAX_COMMAND),
            ):
                if isinstance(payload.get(field), str):
                    payload[field] = _truncate(payload[field], limit)
            files = payload.get("files") or payload.get("changed_files")
            if isinstance(files, list):
                payload["files"] = [
                    _truncate(_redact_string(str(path)), MAX_FILE_PATH)
                    for path in files[:MAX_FILES]
                ]
                payload.pop("changed_files", None)
        return {
            "project_id": event.project_id,
            "run_id": event.run_id,
            "binding_id": event.binding_id,
            "source": event.source,
            "external_session_id": event.external_session_id,
            "external_turn_id": event.external_turn_id,
            "event_type": event.event_type,
            "tool_name": _redact_string(event.tool_name, 128),
            "task_key": event.task_key,
            "occurred_at": _aware(event.occurred_at).isoformat(),
            "payload": payload,
        }

    @staticmethod
    def payload_hash(envelope: dict[str, Any]) -> str:
        return hashlib.sha256(_canonical(envelope).encode("utf-8")).hexdigest()

    @staticmethod
    def _derived_run_id(event: CodexEventInput) -> str:
        digest = hashlib.sha256(
            f"{event.project_id}\n{event.source}\n{event.external_session_id}".encode()
        ).hexdigest()[:32]
        return f"codex-run-{digest}"

    @staticmethod
    def _task_context(task: BusinessTask) -> CodexTaskContext:
        return CodexTaskContext(
            task_key=task.task_key or "",
            title=task.title,
            stage_key=task.stage_key,
            human_status=task.status,
            codex_execution_status=task.codex_execution_status,
            estimated_hours=task.estimated_hours,
            actual_hours=task.actual_hours,
            acceptance_points=_load_json(task.acceptance_points_json, []),
            test_commands=_load_json(task.test_commands_json, []),
        )

    def project_context(self, project_id: str) -> CodexProjectContext:
        with self.database.session() as session:
            project = session.get(BusinessProject, project_id)
            if project is None:
                raise CodexSyncError("project_missing", "项目不存在", 404)
            binding = session.scalar(
                select(CodexProjectBinding)
                .where(
                    CodexProjectBinding.project_id == project_id,
                    CodexProjectBinding.enabled.is_(True),
                )
                .order_by(CodexProjectBinding.updated_at.desc())
            )
            tasks = list(
                session.scalars(
                    select(BusinessTask)
                    .where(
                        BusinessTask.project_id == project_id,
                        BusinessTask.task_key.is_not(None),
                    )
                    .order_by(BusinessTask.stage_key, BusinessTask.task_key)
                )
            )
            return CodexProjectContext(
                project_id=project.id,
                project_name=project.name,
                project_status=project.status,
                project_progress=project.progress,
                binding=(
                    {
                        "id": binding.id,
                        "repository_name": binding.repository_path.rstrip("/").split("/")[-1],
                        "default_branch": binding.default_branch,
                        "current_head_sha": binding.current_head_sha,
                    }
                    if binding
                    else None
                ),
                tasks=[self._task_context(task) for task in tasks],
                safety={
                    "can_control_codex": False,
                    "can_verify_tasks": False,
                    "can_mutate_business_records": False,
                },
            )

    def task_context(self, project_id: str, task_key: str) -> CodexTaskContext:
        context = self.project_context(project_id)
        for task in context.tasks:
            if task.task_key == task_key:
                return task
        raise CodexSyncError("task_missing", "任务不存在或不属于该项目", 404)

    def ingest(self, event: CodexEventInput) -> CodexEventReceipt:
        envelope = self.normalized_envelope(event)
        digest = self.payload_hash(envelope)
        run_id = event.run_id or self._derived_run_id(event)
        occurred_at = _aware(event.occurred_at)
        received_at = utcnow()

        with self.database.session() as session:
            duplicate = session.scalar(
                select(CodexEvent).where(
                    or_(
                        CodexEvent.event_id == event.event_id,
                        CodexEvent.request_id == event.request_id,
                    )
                )
            )
            if duplicate is not None:
                if duplicate.event_id != event.event_id or duplicate.payload_hash != digest:
                    raise CodexSyncError(
                        "event_conflict",
                        "事件编号或请求编号已用于不同内容",
                        409,
                    )
                evidence = session.scalar(
                    select(CodexTaskEvidence).where(
                        CodexTaskEvidence.event_record_id == duplicate.id
                    )
                )
                task = session.get(BusinessTask, evidence.task_id) if evidence and evidence.task_id else None
                run = session.get(CodexRun, duplicate.run_id)
                if run is None:
                    raise CodexSyncError("run_missing", "事件对应的运行不存在", 409)
                return CodexEventReceipt(
                    event_id=duplicate.event_id,
                    run_id=duplicate.run_id,
                    project_id=run.project_id,
                    task_key=duplicate.task_key,
                    task_mapped=task is not None,
                    task_execution_status=task.codex_execution_status if task else None,
                    idempotent=True,
                    received_at=duplicate.received_at,
                )

            project = session.get(BusinessProject, event.project_id)
            if project is None:
                raise CodexSyncError("project_missing", "项目不存在", 404)
            binding = session.get(CodexProjectBinding, event.binding_id) if event.binding_id else None
            if event.binding_id and (binding is None or binding.project_id != event.project_id):
                raise CodexSyncError("binding_mismatch", "仓库绑定不属于该项目", 409)

            run = session.get(CodexRun, run_id)
            if run is None:
                run = session.scalar(
                    select(CodexRun).where(
                        CodexRun.project_id == event.project_id,
                        CodexRun.source == event.source,
                        CodexRun.external_session_id == event.external_session_id,
                    )
                )
            if run is not None and (
                run.project_id != event.project_id
                or run.source != event.source
                or run.external_session_id != event.external_session_id
            ):
                raise CodexSyncError("run_mismatch", "运行编号与外部会话不一致", 409)
            if run is None:
                run = CodexRun(
                    id=run_id,
                    project_id=event.project_id,
                    binding_id=event.binding_id,
                    source=event.source,
                    external_session_id=event.external_session_id,
                    external_turn_id=event.external_turn_id,
                    status="running",
                    started_at=occurred_at,
                    last_event_at=occurred_at,
                )
                session.add(run)
            elif event.binding_id and run.binding_id and run.binding_id != event.binding_id:
                raise CodexSyncError("binding_mismatch", "运行已绑定到另一个仓库", 409)
            else:
                run.binding_id = run.binding_id or event.binding_id
                run.external_turn_id = event.external_turn_id or run.external_turn_id
                run.last_event_at = max(_aware(run.last_event_at), occurred_at)
            # These models intentionally have no ORM navigation relationships.
            # Flush parent rows explicitly so SQLite foreign-key enforcement is
            # deterministic for a newly observed run.
            session.flush()

            task = None
            if event.task_key:
                task = session.scalar(
                    select(BusinessTask).where(
                        BusinessTask.project_id == event.project_id,
                        BusinessTask.task_key == event.task_key,
                    )
                )

            if event.event_type in {"task_start", "task_started"} and task is not None:
                task.codex_execution_status = "in_progress"
                task.codex_implemented_at = None
            elif event.event_type == "task_blocked" and task is not None:
                task.codex_execution_status = "blocked"
            elif event.event_type in {"task_complete", "task_implemented"} and task is not None:
                task.codex_execution_status = "implemented"
                task.codex_implemented_at = occurred_at

            if event.event_type == "task_blocked":
                run.status = "blocked"
            elif event.event_type == "approval_requested":
                run.status = "waiting_approval"
            elif event.event_type == "session_end":
                result = str(envelope["payload"].get("status", "completed"))
                run.status = "failed" if result in {"failed", "error"} else "completed"
                run.finished_at = occurred_at
            elif event.event_type == "run_failed":
                run.status = "failed"
                run.finished_at = occurred_at
            elif event.event_type == "run_completed":
                run.status = "completed"
                run.finished_at = occurred_at
            elif event.event_type in {"task_start", "task_started", "checkpoint", "file_change", "file_changed", "diff_updated", "command", "command_started", "command_completed", "test_result", "test_reported", "task_complete", "task_implemented", "tool_use", "plan_updated", "run_started"}:
                run.status = "running"

            record = CodexEvent(
                id=f"codex-event-{uuid4()}",
                run_id=run.id,
                request_id=event.request_id,
                event_id=event.event_id,
                event_type=event.event_type,
                tool_name=envelope["tool_name"],
                task_key=event.task_key,
                payload_hash=digest,
                payload_json=_canonical(envelope),
                occurred_at=occurred_at,
                received_at=received_at,
            )
            session.add(record)
            session.flush()
            payload = envelope["payload"]
            raw_files = payload.get("files")
            if not isinstance(raw_files, list):
                raw_files = payload.get("changed_files")
            files = raw_files if isinstance(raw_files, list) else []
            exit_code = payload.get("exit_code")
            session.add(
                CodexTaskEvidence(
                    id=f"codex-evidence-{uuid4()}",
                    project_id=event.project_id,
                    run_id=run.id,
                    event_record_id=record.id,
                    task_id=task.id if task else None,
                    task_key=event.task_key,
                    evidence_type=event.event_type,
                    summary=str(payload.get("summary") or payload.get("progress") or ""),
                    files_json=_canonical(files),
                    remaining_work=str(payload.get("remaining_work") or ""),
                    blocker=str(payload.get("blocker") or payload.get("reason") or ""),
                    command=str(payload.get("command") or ""),
                    exit_code=exit_code if isinstance(exit_code, int) else None,
                    occurred_at=occurred_at,
                )
            )
            if self.verification is not None:
                self.verification.apply_persisted_event(
                    session,
                    event=record,
                    run=run,
                    task=task,
                    payload=payload,
                )
            session.commit()
            receipt = CodexEventReceipt(
                event_id=event.event_id,
                run_id=run.id,
                project_id=event.project_id,
                task_key=event.task_key,
                task_mapped=task is not None,
                task_execution_status=task.codex_execution_status if task else None,
                received_at=received_at,
            )

        # Persistence is the source of truth; WebSocket fan-out is strictly
        # after the successful commit above.
        self.event_hub.publish_nowait(
            {
                "type": "codex_event_committed",
                "project_id": event.project_id,
                "run_id": receipt.run_id,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "task_key": event.task_key,
                "received_at": received_at.isoformat(),
            }
        )
        return receipt

    @staticmethod
    def _run_view(row: CodexRun) -> CodexRunView:
        return CodexRunView(
            id=row.id,
            source=row.source,
            external_session_id=row.external_session_id,
            external_turn_id=row.external_turn_id,
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            last_event_at=row.last_event_at,
        )

    def project_sync(self, project_id: str, *, limit: int = 500) -> CodexProjectSyncView:
        with self.database.session() as session:
            if session.get(BusinessProject, project_id) is None:
                raise CodexSyncError("project_missing", "项目不存在", 404)
            runs = list(
                session.scalars(
                    select(CodexRun)
                    .where(CodexRun.project_id == project_id)
                    .order_by(CodexRun.last_event_at.desc())
                )
            )
            event_rows = list(
                session.execute(
                    select(CodexEvent, CodexTaskEvidence, CodexRun.source)
                    .join(CodexRun, CodexRun.id == CodexEvent.run_id)
                    .join(
                        CodexTaskEvidence,
                        CodexTaskEvidence.event_record_id == CodexEvent.id,
                    )
                    .where(CodexRun.project_id == project_id)
                    .order_by(CodexEvent.occurred_at.desc(), CodexEvent.received_at.desc())
                    .limit(max(1, min(limit, 1000)))
                )
            )
            current_run = runs[0] if runs else None
            current_task = None
            if current_run:
                task_key = session.scalar(
                    select(CodexEvent.task_key)
                    .where(
                        CodexEvent.run_id == current_run.id,
                        CodexEvent.task_key.is_not(None),
                    )
                    .order_by(CodexEvent.occurred_at.desc())
                    .limit(1)
                )
                if task_key:
                    task = session.scalar(
                        select(BusinessTask).where(
                            BusinessTask.project_id == project_id,
                            BusinessTask.task_key == task_key,
                        )
                    )
                    if task:
                        current_task = self._task_context(task)

            views: list[CodexSyncEventView] = []
            counts = {"files": 0, "commands": 0, "tests": 0, "blockers": 0}
            for event, evidence, source in event_rows:
                envelope = _load_json(event.payload_json, {})
                payload = envelope.get("payload") if isinstance(envelope, dict) else {}
                files = _load_json(evidence.files_json, [])
                counts["files"] += len(files)
                counts["commands"] += int(event.event_type in {"command", "command_completed"})
                counts["tests"] += int(event.event_type in {"test_result", "test_reported"})
                counts["blockers"] += int(event.event_type == "task_blocked")
                views.append(
                    CodexSyncEventView(
                        event_id=event.event_id,
                        run_id=event.run_id,
                        event_type=event.event_type,
                        source=source,
                        tool_name=event.tool_name,
                        task_key=event.task_key,
                        task_mapped=evidence.task_id is not None,
                        summary=evidence.summary,
                        files=files,
                        remaining_work=evidence.remaining_work,
                        blocker=evidence.blocker,
                        command=evidence.command,
                        exit_code=evidence.exit_code,
                        payload=payload if isinstance(payload, dict) else {},
                        occurred_at=event.occurred_at,
                        received_at=event.received_at,
                    )
                )

            connection_status = "not_connected"
            if current_run:
                connection_status = current_run.status
                if connection_status not in {"running", "blocked", "failed", "completed", "idle"}:
                    connection_status = "idle"
                if (
                    connection_status in {"running", "blocked"}
                    and _aware(current_run.last_event_at) < datetime.now(timezone.utc) - timedelta(minutes=5)
                ):
                    connection_status = "disconnected"
            return CodexProjectSyncView(
                project_id=project_id,
                connection_status=connection_status,
                current_run=self._run_view(current_run) if current_run else None,
                current_task=current_task,
                last_sync_at=current_run.last_event_at if current_run else None,
                runs=[self._run_view(run) for run in runs],
                events=views,
                counts=counts,
            )
