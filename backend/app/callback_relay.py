from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response


BACKEND_URL = os.getenv("YUDA_BACKEND_URL", "http://127.0.0.1:8877").rstrip("/")
MAX_BODY_BYTES = 64 * 1024

app = FastAPI(
    title="鱼答企业微信回调最小转发器",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


async def _forward(request: Request) -> Response:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="callback body too large")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.request(
            request.method,
            f"{BACKEND_URL}/wechat/callback",
            params=list(request.query_params.multi_items()),
            content=body,
            headers={"content-type": request.headers.get("content-type", "application/xml")},
        )
    content_type = response.headers.get("content-type", "text/plain")
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=content_type.split(";", 1)[0],
    )


@app.get("/wechat/callback")
async def relay_callback_verification(request: Request) -> Response:
    return await _forward(request)


@app.post("/wechat/callback")
async def relay_callback_event(request: Request) -> Response:
    return await _forward(request)


@app.get("/health")
async def relay_health() -> dict[str, str]:
    return {"status": "ok"}
