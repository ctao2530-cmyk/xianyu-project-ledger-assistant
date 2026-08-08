from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from starlette.requests import Request

from backend.app.main import rate_limit


class RecordingLimiter:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.keys: list[str] = []

    async def allow(self, key: str) -> bool:
        self.keys.append(key)
        return self.allowed


def make_request(app: FastAPI, method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
            "app": app,
        }
    )


def test_options_requests_do_not_consume_page_rate_limit() -> None:
    async def scenario() -> None:
        app = FastAPI()
        limiter = RecordingLimiter(allowed=False)
        app.state.runtime = SimpleNamespace(api_limiter=limiter)
        response = await rate_limit(
            make_request(app, "OPTIONS", "/api/status"),
            lambda _request: asyncio.sleep(0, result=PlainTextResponse("ok")),
        )

        assert response.status_code == 200
        assert limiter.keys == []

    asyncio.run(scenario())


def test_rate_limit_is_scoped_by_method_and_route() -> None:
    async def scenario() -> None:
        app = FastAPI()
        limiter = RecordingLimiter(allowed=True)
        app.state.runtime = SimpleNamespace(api_limiter=limiter)
        call_next = lambda _request: asyncio.sleep(0, result=PlainTextResponse("ok"))

        await rate_limit(make_request(app, "GET", "/api/status"), call_next)
        await rate_limit(make_request(app, "GET", "/api/conversations"), call_next)
        await rate_limit(make_request(app, "POST", "/api/conversations"), call_next)
        await rate_limit(make_request(app, "POST", "/wechat/webhook"), call_next)

        assert limiter.keys == [
            "127.0.0.1:GET:/api/status",
            "127.0.0.1:GET:/api/conversations",
            "127.0.0.1:POST:/api/conversations",
            "127.0.0.1:POST:/wechat/webhook",
        ]

    asyncio.run(scenario())


def test_rejected_page_request_returns_retry_hint() -> None:
    async def scenario() -> None:
        app = FastAPI()
        limiter = RecordingLimiter(allowed=False)
        app.state.runtime = SimpleNamespace(api_limiter=limiter)
        response = await rate_limit(
            make_request(app, "GET", "/api/status"),
            lambda _request: asyncio.sleep(0, result=PlainTextResponse("ok")),
        )

        assert response.status_code == 429
        assert response.headers["retry-after"] == "5"
        assert limiter.keys == ["127.0.0.1:GET:/api/status"]

    asyncio.run(scenario())
