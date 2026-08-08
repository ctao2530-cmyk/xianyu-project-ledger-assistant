from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from backend.app.channels.wechat import WeChatAdapter, WechatMockProvider
from backend.app.channels.wecom import (
    WeComAPIClient,
    WeComCallbackEvent,
    WeComCrypto,
    WeComSender,
    WeComSignatureError,
)
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.models import ChannelCursor, Conversation, Message, SellerReplySample
from backend.app.services.notifier import MacOSNotifier
from backend.app.services.processor import MessageProcessor
from backend.app.services.style_learning import StyleLearningService
from backend.app.services.wecom import WeComService
from backend.app.wechat_api import wechat_router


def wecom_settings(tmp_path) -> Settings:
    aes_key = base64.b64encode(bytes(range(32))).decode("ascii").rstrip("=")
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'wecom.db'}",
        wechat_provider="wecom",
        wecom_corp_id="ww-test-corp",
        wecom_corp_secret="secret-for-test",
        wecom_callback_token="callback-token",
        wecom_encoding_aes_key=aes_key,
        wecom_api_base_url="https://qyapi.weixin.qq.com",
        wecom_sync_max_pages=3,
        reply_burst_coalesce_seconds=0,
        macos_notifications=False,
    )


def test_wecom_crypto_verifies_signature_and_decrypts(tmp_path) -> None:
    settings = wecom_settings(tmp_path)
    crypto = WeComCrypto(
        settings.wecom_callback_token.get_secret_value(),
        settings.wecom_encoding_aes_key.get_secret_value(),
        settings.wecom_corp_id,
    )
    encrypted, signature = crypto.encrypt_for_test(
        "callback-ok", timestamp="1700000000", nonce="nonce"
    )

    assert crypto.decrypt(
        encrypted,
        signature=signature,
        timestamp="1700000000",
        nonce="nonce",
    ) == "callback-ok"
    with pytest.raises(WeComSignatureError):
        crypto.decrypt(
            encrypted,
            signature="0" * 40,
            timestamp="1700000000",
            nonce="nonce",
        )


@pytest.mark.asyncio
async def test_wecom_sync_reuses_existing_storage_and_ai_pipeline(tmp_path) -> None:
    settings = wecom_settings(tmp_path)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/cgi-bin/gettoken":
            return httpx.Response(
                200,
                json={"errcode": 0, "access_token": "access-token", "expires_in": 7200},
            )
        if request.url.path == "/cgi-bin/kf/sync_msg":
            payload = json.loads(request.content)
            assert payload["open_kfid"] == "wk-test"
            assert payload["token"] == "event-token"
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "next_cursor": "cursor-2",
                    "has_more": 0,
                    "msg_list": [
                        {
                            "msgid": "wx-inbound-1",
                            "open_kfid": "wk-test",
                            "external_userid": "wm-customer-1",
                            "send_time": 1785816000,
                            "origin": 3,
                            "msgtype": "text",
                            "text": {"content": "这个小程序多少钱"},
                        },
                        {
                            "msgid": "wx-agent-1",
                            "open_kfid": "wk-test",
                            "external_userid": "wm-customer-1",
                            "send_time": 1785816001,
                            "origin": 5,
                            "msgtype": "text",
                            "text": {"content": "请先把功能清单和截止时间发我。"},
                        },
                    ],
                },
            )
        if request.url.path == "/cgi-bin/kf/customer/batchget":
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "customer_list": [
                        {
                            "external_userid": "wm-customer-1",
                            "nickname": "微信客户甲",
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        api_client = WeComAPIClient(settings, http_client=http_client)
        database = Database(settings.database_url)
        database.create_all()
        style = StyleLearningService(database, settings)
        style.bootstrap()

        class Queue:
            def __init__(self) -> None:
                self.message_ids: list[int] = []

            async def enqueue(self, message_id: int, automatic: bool = True):
                self.message_ids.append(message_id)
                return SimpleNamespace(id=message_id)

        queue = Queue()
        processor = MessageProcessor(
            database,
            object(),
            queue,  # type: ignore[arg-type]
            MacOSNotifier(False),
            history_limit=20,
        )
        service = WeComService(
            settings,
            database,
            WeChatAdapter(WechatMockProvider()),
            processor,
            style,
            MacOSNotifier(False),
            client=api_client,
        )

        await service.sync_event(
            WeComCallbackEvent("kf_msg_or_event", "event-token", "wk-test")
        )

        with database.session() as session:
            conversation = session.scalar(select(Conversation))
            messages = list(session.scalars(select(Message).order_by(Message.id)))
            cursor = session.get(ChannelCursor, "wecom_customer_service:wk-test")
            samples = list(session.scalars(select(SellerReplySample)))
            assert conversation is not None
            assert conversation.external_id == "wechat:wk-test:wm-customer-1"
            assert conversation.customer_name == "微信客户甲"
            assert [message.direction for message in messages] == ["inbound", "outbound"]
            assert cursor is not None and cursor.cursor == "cursor-2"
            assert len(samples) == 1
        assert len(queue.message_ids) == 1
        assert calls.count("/cgi-bin/gettoken") == 1
        await processor.stop()
        await service.stop()


@pytest.mark.asyncio
async def test_wecom_callback_handshake_and_encrypted_event(tmp_path) -> None:
    settings = wecom_settings(tmp_path)
    database = Database(settings.database_url)
    database.create_all()
    crypto = WeComCrypto(
        settings.wecom_callback_token.get_secret_value(),
        settings.wecom_encoding_aes_key.get_secret_value(),
        settings.wecom_corp_id,
    )

    class StubWeCom:
        def __init__(self) -> None:
            self.events: list[WeComCallbackEvent] = []

        def verify_url(self, **kwargs) -> str:
            return crypto.decrypt(
                kwargs["echo"],
                signature=kwargs["signature"],
                timestamp=kwargs["timestamp"],
                nonce=kwargs["nonce"],
            )

        def accept_callback(self, payload: bytes, **kwargs) -> WeComCallbackEvent:
            from backend.app.channels.wecom import callback_event_from_xml, encrypted_value_from_xml

            plain = crypto.decrypt(
                encrypted_value_from_xml(payload),
                signature=kwargs["signature"],
                timestamp=kwargs["timestamp"],
                nonce=kwargs["nonce"],
            )
            event = callback_event_from_xml(plain)
            self.events.append(event)
            return event

    stub = StubWeCom()
    app = FastAPI()
    app.state.runtime = SimpleNamespace(wecom=stub)
    app.include_router(wechat_router)

    timestamp = "1785816000"
    nonce = "callback-nonce"
    echo, echo_signature = crypto.encrypt_for_test(
        "verified", timestamp=timestamp, nonce=nonce
    )
    event_xml = (
        "<xml><ToUserName><![CDATA[ww-test-corp]]></ToUserName>"
        "<MsgType><![CDATA[event]]></MsgType>"
        "<Event><![CDATA[kf_msg_or_event]]></Event>"
        "<Token><![CDATA[sync-token]]></Token>"
        "<OpenKfId><![CDATA[wk-test]]></OpenKfId></xml>"
    )
    encrypted_event, event_signature = crypto.encrypt_for_test(
        event_xml, timestamp=timestamp, nonce=nonce
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        verify = await client.get(
            "/wechat/callback",
            params={
                "msg_signature": echo_signature,
                "timestamp": timestamp,
                "nonce": nonce,
                "echostr": echo,
            },
        )
        assert verify.status_code == 200
        assert verify.text == "verified"

        callback = await client.post(
            "/wechat/callback",
            params={
                "msg_signature": event_signature,
                "timestamp": timestamp,
                "nonce": nonce,
            },
            content=f"<xml><Encrypt><![CDATA[{encrypted_event}]]></Encrypt></xml>",
        )
        assert callback.status_code == 200
        assert callback.text == "success"
        assert stub.events == [
            WeComCallbackEvent("kf_msg_or_event", "sync-token", "wk-test")
        ]

        rejected = await client.post(
            "/wechat/callback",
            params={
                "msg_signature": "0" * 40,
                "timestamp": timestamp,
                "nonce": nonce,
            },
            content=f"<xml><Encrypt><![CDATA[{encrypted_event}]]></Encrypt></xml>",
        )
        assert rejected.status_code == 403


@pytest.mark.asyncio
async def test_wecom_sender_uses_official_customer_service_endpoint(tmp_path) -> None:
    settings = wecom_settings(tmp_path)
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/gettoken":
            return httpx.Response(
                200,
                json={"errcode": 0, "access_token": "access-token", "expires_in": 7200},
            )
        if request.url.path == "/cgi-bin/kf/send_msg":
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "msgid": "sent-1"})
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        sender = WeComSender(WeComAPIClient(settings, http_client=http_client))
        await sender.send_message(
            "wechat:wk-test:wm-customer-1",
            "wm-customer-1",
            "您好，请把功能清单和截止时间发来。",
            "local-message-1",
        )

    assert sent[0]["touser"] == "wm-customer-1"
    assert sent[0]["open_kfid"] == "wk-test"
    assert sent[0]["msgtype"] == "text"


@pytest.mark.asyncio
async def test_wecom_healthcheck_verifies_customer_service_permission(tmp_path) -> None:
    settings = wecom_settings(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/gettoken":
            return httpx.Response(
                200,
                json={"errcode": 0, "access_token": "access-token", "expires_in": 7200},
            )
        if request.url.path == "/cgi-bin/kf/account/list":
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "account_list": []},
            )
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = WeComAPIClient(settings, http_client=http_client)
        await client.healthcheck()
