from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from .channels.wechat import WechatWebhookPayload
from .channels.wecom import (
    WeComConfigurationError,
    WeComSignatureError,
)


wechat_router = APIRouter(prefix="/wechat", tags=["wechat"])


@wechat_router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def receive_wechat_mock_message(
    payload: WechatWebhookPayload,
    request: Request,
) -> dict[str, object]:
    """Inject one local WeChat mock event into the shared message/AI pipeline."""
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="微信 Mock 仅允许本机调用")
    runtime = request.app.state.runtime
    runtime_settings = getattr(runtime, "settings", None)
    if runtime_settings and runtime_settings.wechat_provider != "mock":
        raise HTTPException(status_code=404, detail="真实企业微信模式下已关闭 Mock 入口")
    event = await runtime.wechat_adapter.receive_message(payload)
    message_id = await runtime.processor.process(event, source="wechat_webhook")
    return {
        "ok": True,
        "channel": event.channel,
        "message_id": message_id,
        "platform_message_id": event.platform_message_id,
    }


@wechat_router.get("/callback", response_class=PlainTextResponse)
async def verify_wecom_callback(
    request: Request,
    msg_signature: str = Query(min_length=40, max_length=40),
    timestamp: str = Query(min_length=1, max_length=32),
    nonce: str = Query(min_length=1, max_length=128),
    echostr: str = Query(min_length=1, max_length=4096),
) -> PlainTextResponse:
    """Complete the official WeCom callback URL verification handshake."""
    try:
        echo = request.app.state.runtime.wecom.verify_url(
            signature=msg_signature,
            timestamp=timestamp,
            nonce=nonce,
            echo=echostr,
        )
    except WeComConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except WeComSignatureError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    return PlainTextResponse(echo)


@wechat_router.post("/callback", response_class=PlainTextResponse)
async def receive_wecom_callback(
    request: Request,
    msg_signature: str = Query(min_length=40, max_length=40),
    timestamp: str = Query(min_length=1, max_length=32),
    nonce: str = Query(min_length=1, max_length=128),
) -> PlainTextResponse:
    """Verify/decrypt one notification and schedule incremental message sync."""
    payload = await request.body()
    if len(payload) > 64 * 1024:
        raise HTTPException(status_code=413, detail="企业微信回调内容过大")
    try:
        request.app.state.runtime.wecom.accept_callback(
            payload,
            signature=msg_signature,
            timestamp=timestamp,
            nonce=nonce,
        )
    except WeComConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except WeComSignatureError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    return PlainTextResponse("success")


@wechat_router.get("/status")
async def get_wecom_status(request: Request) -> dict[str, object]:
    snapshot = request.app.state.runtime.wecom.snapshot()
    return {
        "provider": snapshot.provider,
        "configured": snapshot.configured,
        "status": snapshot.status,
        "detail": snapshot.detail,
        "last_event_at": snapshot.last_event_at,
    }
