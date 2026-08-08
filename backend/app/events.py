from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .runtime import Runtime
from .services.desktop_status import build_desktop_status_event


event_router = APIRouter()


def _runtime(websocket: WebSocket) -> Runtime:
    return websocket.app.state.runtime


def _trusted_origin(origin: str, runtime: Runtime) -> bool:
    if origin in runtime.settings.cors_origin_list:
        return True
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "127.0.0.1",
        "::1",
        "localhost",
    }


@event_router.websocket("/events")
async def desktop_events(websocket: WebSocket) -> None:
    client_host = websocket.client.host if websocket.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        await websocket.close(code=1008, reason="Local clients only")
        return

    runtime = _runtime(websocket)
    origin = websocket.headers.get("origin")
    if origin and not _trusted_origin(origin, runtime):
        await websocket.close(code=1008, reason="Untrusted origin")
        return
    await websocket.accept()
    subscription = runtime.event_hub.subscribe()
    try:
        await websocket.send_json(
            build_desktop_status_event(
                runtime.database,
                runtime.status,
                runtime.ai,
                getattr(runtime, "automation", None),
                getattr(runtime, "style_learning", None),
            )
        )
        for event in subscription.replay:
            await websocket.send_json(event)
        while True:
            try:
                event = await asyncio.wait_for(subscription.queue.get(), timeout=5)
            except TimeoutError:
                event = build_desktop_status_event(
                    runtime.database,
                    runtime.status,
                    runtime.ai,
                    getattr(runtime, "automation", None),
                    getattr(runtime, "style_learning", None),
                )
            await websocket.send_json(event)
            if event.get("type") != "status":
                subscription.queue.task_done()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        runtime.event_hub.unsubscribe(subscription.queue)
