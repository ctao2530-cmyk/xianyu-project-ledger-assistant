from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import SecretStr

from backend.app.adapters import (
    AdapterAccessVerificationError,
    AdapterDisconnectedError,
    IncomingMessage,
    LoginExpiredError,
)
from backend.app.config import Settings
from backend.app.services.listener import ListenerService
from backend.app.services.status import RuntimeStatus


class FakeNotifier:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str, str]] = []

    async def notify(self, title: str, message: str, subtitle: str = "") -> None:
        self.notifications.append((title, message, subtitle))


class FakeProcessor:
    def __init__(self) -> None:
        self.processed = asyncio.Event()

    async def process(self, _event: IncomingMessage) -> None:
        self.processed.set()


class ReconnectingAdapter:
    connected = False

    def __init__(self) -> None:
        self.calls = 0
        self.closed = asyncio.Event()

    async def listen(self, on_ready=None):
        self.calls += 1
        if self.calls == 1:
            raise AdapterDisconnectedError("temporary")
        self.connected = True
        if on_ready:
            on_ready()
        yield IncomingMessage(
            external_id="m1",
            conversation_id="c1",
            sender_id="u1",
            sender_name="客户",
            content="你好",
            message_type="text",
            received_at=datetime.now(timezone.utc),
        )
        await self.closed.wait()

    async def close(self) -> None:
        self.connected = False
        self.closed.set()


class ExpiredAdapter:
    connected = False

    def __init__(self) -> None:
        self.calls = 0

    async def listen(self, on_ready=None):
        self.calls += 1
        if False:
            yield None
        raise LoginExpiredError("登录已过期")

    async def close(self) -> None:
        pass


class VerificationRequiredAdapter:
    connected = False

    def __init__(self) -> None:
        self.calls = 0

    async def listen(self, on_ready=None):
        self.calls += 1
        if False:
            yield None
        raise AdapterAccessVerificationError("verification required")

    async def close(self) -> None:
        pass


def listener_settings() -> Settings:
    return Settings(
        _env_file=None,
        xianyu_cookie=SecretStr("unb=seller; _m_h5_tk=token_suffix"),
        xianyu_reconnect_min_seconds=0.001,
        xianyu_reconnect_max_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_listener_reconnects_and_processes_message() -> None:
    adapter = ReconnectingAdapter()
    processor = FakeProcessor()
    notifier = FakeNotifier()
    status = RuntimeStatus()
    service = ListenerService(
        listener_settings(), adapter, processor, notifier, status  # type: ignore[arg-type]
    )
    task = asyncio.create_task(service.run_forever())
    await asyncio.wait_for(processor.processed.wait(), timeout=1)
    await service.stop()
    await asyncio.wait_for(task, timeout=1)

    assert adapter.calls >= 2
    assert status.listener == "connected"


@pytest.mark.asyncio
async def test_login_expiry_notifies_once_while_retrying() -> None:
    adapter = ExpiredAdapter()
    processor = FakeProcessor()
    notifier = FakeNotifier()
    status = RuntimeStatus()
    service = ListenerService(
        listener_settings(), adapter, processor, notifier, status  # type: ignore[arg-type]
    )
    task = asyncio.create_task(service.run_forever())
    for _ in range(50):
        if adapter.calls >= 2:
            break
        await asyncio.sleep(0.005)
    await service.stop()
    await asyncio.wait_for(task, timeout=1)

    assert status.listener == "login_required"
    assert len(notifier.notifications) == 1


@pytest.mark.asyncio
async def test_access_verification_stops_automatic_retries() -> None:
    adapter = VerificationRequiredAdapter()
    processor = FakeProcessor()
    notifier = FakeNotifier()
    status = RuntimeStatus()
    service = ListenerService(
        listener_settings(), adapter, processor, notifier, status  # type: ignore[arg-type]
    )

    await asyncio.wait_for(service.run_forever(), timeout=1)
    await asyncio.sleep(0.03)

    assert adapter.calls == 1
    assert status.listener == "verification_required"
    assert status.listener_detail == "闲鱼要求完成人工访问验证，自动重连已暂停"
    assert status.realtime_delivery == "paused"
    assert "Ego Lite" in (status.realtime_detail or "")
