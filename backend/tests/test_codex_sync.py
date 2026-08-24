from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest
from sqlalchemy import func, select

from backend.app.codex_sync_api import codex_sync_router, signature_for
from backend.app.codex_sync_schemas import CodexEventInput
from backend.app.database import Database
from backend.app.models import (
    BusinessProject,
    BusinessTask,
    CodexEvent,
    CodexRun,
    CodexTaskEvidence,
)
from backend.app.services.codex_sync import CodexSyncError, CodexSyncService


NOW = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
SECRET = "test-only-secret-with-enough-entropy"


class CommitCheckingHub:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.events: list[dict] = []

    def publish_nowait(self, event: dict) -> None:
        with self.database.session() as session:
            assert session.scalar(select(func.count()).select_from(CodexEvent)) >= 1
        self.events.append(event)


def build_service(tmp_path: Path) -> tuple[Database, CodexSyncService, CommitCheckingHub]:
    database = Database(f"sqlite:///{tmp_path / 'codex-sync.db'}")
    database.create_all()
    with database.session() as session:
        session.add_all(
            [
                BusinessProject(
                    id="project-one",
                    name="External sync",
                    status="in_progress",
                    progress=37,
                ),
                BusinessProject(id="project-two", name="Other project"),
                BusinessTask(
                    id="task-one",
                    project_id="project-one",
                    task_key="DEV-001",
                    stage_key="STAGE-001",
                    title="Implement sync",
                    status="todo",
                    estimated_hours=4,
                    actual_hours=1.25,
                    acceptance_points_json='[{"point_key":"AC-1","title":"works"}]',
                    test_commands_json='["pytest -q"]',
                ),
                BusinessTask(
                    id="task-two",
                    project_id="project-two",
                    task_key="DEV-001",
                    title="Same key elsewhere",
                    status="done",
                ),
            ]
        )
        session.commit()
    hub = CommitCheckingHub(database)
    return database, CodexSyncService(database, hub), hub


def event(
    event_type: str,
    *,
    suffix: str,
    task_key: str | None = "DEV-001",
    project_id: str = "project-one",
    payload: dict | None = None,
) -> CodexEventInput:
    return CodexEventInput(
        request_id=f"request-{suffix}",
        event_id=f"event-{suffix}",
        project_id=project_id,
        source="mcp",
        external_session_id="session-one",
        external_turn_id="turn-one",
        event_type=event_type,
        task_key=task_key,
        occurred_at=NOW + timedelta(seconds=len(suffix)),
        payload=payload or {},
    )


def test_lifecycle_is_persisted_without_human_or_project_completion(tmp_path: Path) -> None:
    database, service, hub = build_service(tmp_path)
    records = [
        event("task_start", suffix="1", payload={"summary": "started"}),
        event(
            "checkpoint",
            suffix="2",
            payload={
                "progress": "schema done",
                "changed_files": ["backend/app/models.py"],
                "remaining_work": "UI",
            },
        ),
        event("task_blocked", suffix="3", payload={"reason": "needs fixture"}),
        event(
            "test_result",
            suffix="4",
            payload={"command": "pytest -q", "exit_code": 0, "summary": "12 passed"},
        ),
        event("task_complete", suffix="5", payload={"summary": "implemented"}),
    ]
    statuses = [service.ingest(item).task_execution_status for item in records]

    assert statuses == ["in_progress", "in_progress", "blocked", "blocked", "implemented"]
    assert len(hub.events) == 5
    assert all(item["type"] == "codex_event_committed" for item in hub.events)
    with database.session() as session:
        task = session.get(BusinessTask, "task-one")
        project = session.get(BusinessProject, "project-one")
        assert task is not None
        assert task.status == "todo"
        assert task.actual_hours == 1.25
        assert task.codex_execution_status == "implemented"
        assert task.codex_implemented_at is not None
        assert project is not None and project.progress == 37 and project.status == "in_progress"
        assert session.scalar(select(func.count()).select_from(CodexEvent)) == 5
        assert session.scalar(select(func.count()).select_from(CodexTaskEvidence)) == 5


def test_event_and_request_idempotency_and_conflicts(tmp_path: Path) -> None:
    database, service, hub = build_service(tmp_path)
    original = event("task_start", suffix="same")
    first = service.ingest(original)
    replay = service.ingest(original)

    assert first.idempotent is False
    assert replay.idempotent is True
    assert len(hub.events) == 1
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(CodexEvent)) == 1
    changed = original.model_copy(update={"payload": {"summary": "different"}})
    with pytest.raises(CodexSyncError, match="different content|不同内容") as caught:
        service.ingest(changed)
    assert caught.value.status_code == 409
    reused_request = event("checkpoint", suffix="new").model_copy(
        update={"request_id": original.request_id}
    )
    with pytest.raises(CodexSyncError) as caught_request:
        service.ingest(reused_request)
    assert caught_request.value.code == "event_conflict"


def test_missing_unknown_and_cross_project_task_keys_never_mutate(tmp_path: Path) -> None:
    database, service, _hub = build_service(tmp_path)
    general = service.ingest(event("file_change", suffix="general", task_key=None))
    unknown = service.ingest(event("task_complete", suffix="unknown", task_key="NOPE"))

    assert general.task_mapped is False
    assert unknown.task_mapped is False
    with database.session() as session:
        first = session.get(BusinessTask, "task-one")
        other = session.get(BusinessTask, "task-two")
        assert first is not None and first.codex_execution_status == "todo" and first.status == "todo"
        assert other is not None and other.codex_execution_status == "todo" and other.status == "done"


def test_payload_is_redacted_truncated_and_bounded_before_persistence(tmp_path: Path) -> None:
    database, service, _hub = build_service(tmp_path)
    service.ingest(
        event(
            "command",
            suffix="redact",
            payload={
                "authorization": "Bearer should-never-persist",
                "environment": {"REAL_SECRET": "hidden"},
                "summary": "ok " + ("x" * 4_000),
                "stdout": "token=abc123 " + ("y" * 8_000),
                "command": "curl -H 'Authorization: Bearer abc123' /local",
                "files": [f"path-{index}" for index in range(75)],
            },
        )
    )
    with database.session() as session:
        stored = session.scalar(select(CodexEvent))
        assert stored is not None
        assert "should-never-persist" not in stored.payload_json
        assert "abc123" not in stored.payload_json
        assert "REAL_SECRET" not in stored.payload_json
        envelope = json.loads(stored.payload_json)
        assert envelope["payload"]["authorization"] == "[REDACTED]"
        assert envelope["payload"]["environment"] == "[REDACTED]"
        assert len(envelope["payload"]["files"]) == 50
        assert "truncated" in envelope["payload"]["summary"]


def make_api(tmp_path: Path) -> tuple[FastAPI, Database]:
    database, service, _hub = build_service(tmp_path)
    app = FastAPI()
    app.include_router(codex_sync_router)
    app.state.runtime = SimpleNamespace(
        codex_sync=service,
        settings=SimpleNamespace(xunying_codex_event_secret=SecretStr(SECRET)),
    )
    return app, database


def signed_body(payload: dict, *, timestamp: str | None = None) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    current = timestamp or str(time.time())
    return body, {
        "X-Xunying-Timestamp": current,
        "X-Xunying-Signature": signature_for(
            SECRET, current, "POST", "/api/codex/events", body
        ),
        "Content-Type": "application/json",
    }


def test_hmac_success_failure_stale_and_payload_limit(tmp_path: Path) -> None:
    app, _database = make_api(tmp_path)
    client = TestClient(app)
    payload = event("task_start", suffix="api").model_dump(mode="json")
    body, headers = signed_body(payload)
    assert client.post("/api/codex/events", content=body, headers=headers).status_code == 200

    bad = dict(headers)
    bad["X-Xunying-Signature"] = "0" * 64
    assert client.post("/api/codex/events", content=body, headers=bad).status_code == 401

    old = str(time.time() - 600)
    stale_body, stale_headers = signed_body(
        event("checkpoint", suffix="stale").model_dump(mode="json"), timestamp=old
    )
    assert client.post("/api/codex/events", content=stale_body, headers=stale_headers).status_code == 401
    assert client.post(
        "/api/codex/events",
        content=b"x" * (65_536 + 1),
        headers={"Content-Type": "application/json"},
    ).status_code == 413


@pytest.mark.asyncio
async def test_event_api_rejects_non_loopback_clients(tmp_path: Path) -> None:
    app, _database = make_api(tmp_path)
    payload = event("checkpoint", suffix="remote").model_dump(mode="json")
    body, headers = signed_body(payload)
    transport = httpx.ASGITransport(app=app, client=("10.10.10.10", 4321))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/codex/events", content=body, headers=headers)
    assert response.status_code == 403


def test_project_history_is_database_backed_and_statuses_are_separate(tmp_path: Path) -> None:
    database, service, _hub = build_service(tmp_path)
    service.ingest(event("task_complete", suffix="history", payload={"summary": "done"}))
    restarted = CodexSyncService(database, CommitCheckingHub(database))
    view = restarted.project_sync("project-one")

    assert view.events[0].summary == "done"
    assert view.current_task is not None
    assert view.current_task.codex_execution_status == "implemented"
    assert view.current_task.human_status == "todo"
    assert view.connection_status == "disconnected"
