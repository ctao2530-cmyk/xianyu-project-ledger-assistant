from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.database import Database
from backend.app.events import event_router
from backend.app.services.event_hub import EventHub
from backend.app.services.listener_supervisor import ListenerSupervisor
from backend.app.services.status import RuntimeStatus


def test_event_hub_fans_out_and_replays_reply_events() -> None:
    hub = EventHub(queue_size=2, replay_size=2)
    first = hub.subscribe()

    hub.publish_nowait({"type": "status", "listener": "connected"})
    hub.publish_nowait({"type": "new_reply", "event_id": "reply-1"})
    hub.publish_nowait({"type": "new_reply", "event_id": "reply-2"})

    assert first.queue.get_nowait()["type"] == "status"
    assert first.queue.get_nowait()["event_id"] == "reply-1"

    second = hub.subscribe()
    assert [event["event_id"] for event in second.replay] == ["reply-1", "reply-2"]
    assert hub.subscriber_count == 2
    hub.unsubscribe(first.queue)
    hub.unsubscribe(second.queue)
    assert hub.subscriber_count == 0


def test_websocket_sends_status_then_committed_reply_replay(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'events.db'}")
    database.create_all()
    hub = EventHub()
    reply = {
        "type": "new_reply",
        "event_id": "ai-task-9",
        "recommended_reply": "请发具体需求，我确认工作范围后再回复。",
    }
    hub.publish_nowait(reply)
    runtime = SimpleNamespace(
        event_hub=hub,
        database=database,
        status=RuntimeStatus(listener="connected"),
        ai=SimpleNamespace(status="connected", detail=None),
        settings=SimpleNamespace(
            cors_origin_list=["http://127.0.0.1:3000", "http://localhost:3000"]
        ),
    )
    app = FastAPI()
    app.state.runtime = runtime
    app.include_router(event_router)

    with TestClient(app).websocket_connect("/events") as websocket:
        status = websocket.receive_json()
        replay = websocket.receive_json()

    assert status["type"] == "status"
    assert status["listener"] == "connected"
    assert status["codex"] == "ready"
    assert replay == reply

    with pytest.raises(WebSocketDisconnect) as rejected:
        with TestClient(app).websocket_connect(
            "/events", headers={"origin": "https://untrusted.example"}
        ):
            pass
    assert rejected.value.code == 1008


class FakeListener:
    def __init__(self) -> None:
        self.runs = 0
        self.cancelled = 0
        self.stopped = 0
        self.running = asyncio.Event()

    async def run_forever(self) -> None:
        self.runs += 1
        self.running.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise

    async def stop(self) -> None:
        self.stopped += 1


@pytest.mark.asyncio
async def test_listener_supervisor_pauses_resumes_and_reconnects() -> None:
    listener = FakeListener()
    status = RuntimeStatus()
    supervisor = ListenerSupervisor(listener, status)  # type: ignore[arg-type]

    await supervisor.start()
    await asyncio.wait_for(listener.running.wait(), timeout=1)
    await supervisor.pause()
    assert supervisor.paused is True
    assert status.listener == "paused"
    assert listener.cancelled == 1

    listener.running.clear()
    await supervisor.resume()
    await asyncio.wait_for(listener.running.wait(), timeout=1)
    assert listener.runs == 2
    assert status.listener == "connecting"

    listener.running.clear()
    await supervisor.reconnect()
    await asyncio.wait_for(listener.running.wait(), timeout=1)
    assert listener.runs == 3
    assert listener.cancelled == 2
    assert status.listener == "reconnecting"

    await supervisor.shutdown()
    assert listener.cancelled == 3
    assert listener.stopped == 1
