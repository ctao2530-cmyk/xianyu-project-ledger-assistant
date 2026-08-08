from __future__ import annotations

import asyncio
import base64
from datetime import timezone

import httpx
import msgpack
from pydantic import SecretStr

from backend.app.adapters.xianyu import (
    XianyuAdapter,
    decode_sync_payload,
    is_subscription_confirmation,
    mtop_sign,
    parse_live_message,
    parse_live_messages,
)
from backend.app.config import Settings


def test_mtop_sign_matches_protocol_formula() -> None:
    assert mtop_sign("token", "1000", "{}") == "55b46d6001953bc45ee0713ee9e3502f"


def test_subscription_requires_server_confirmation() -> None:
    registration_mid = "registration-1"

    assert is_subscription_confirmation(
        {"code": 200, "headers": {"mid": registration_mid}}, registration_mid
    )
    assert is_subscription_confirmation(
        {"lwp": "/s/vulcan", "headers": {}}, registration_mid
    )
    assert is_subscription_confirmation(
        {"headers": {}, "body": {"syncPushPackage": {"data": []}}},
        registration_mid,
    )
    assert not is_subscription_confirmation(
        {"code": 500, "headers": {"mid": registration_mid}}, registration_mid
    )
    assert not is_subscription_confirmation(
        {"code": 200, "headers": {"mid": "another-request"}}, registration_mid
    )


def test_current_live_message_decoding_and_parsing() -> None:
    payload = {
        1: {
            1: "buyer-1@goofish",
            2: "conversation-1@goofish",
            5: 1_750_000_000_000,
            10: {
                "senderUserId": "buyer-1",
                "reminderTitle": "测试客户",
                "reminderContent": "可以做个企业官网吗？",
                "extJson": '{"messageId":"message-1"}',
                "reminderUrl": "fleamarket://message_chat?itemId=item-1&sid=conversation-1",
            },
        }
    }
    encoded = base64.b64encode(msgpack.packb(payload, use_bin_type=True)).decode()
    decoded = decode_sync_payload(encoded)
    event = parse_live_message(decoded, own_user_id="seller-1")

    assert event is not None
    assert event.external_id == "message-1"
    assert event.conversation_id == "conversation-1"
    assert event.item_id == "item-1"
    assert event.direction == "inbound"
    assert event.received_at.tzinfo == timezone.utc


def test_legacy_nested_live_message_shape_is_still_supported() -> None:
    payload = {
        "1": {
            "1": {
                "2": "conversation-legacy@goofish",
                "5": 1_750_000_000_000,
                "10": {
                    "senderUserId": "buyer-legacy",
                    "reminderTitle": "旧结构客户",
                    "reminderContent": "旧结构消息",
                    "extJson": '{"messageId":"message-legacy"}',
                },
            }
        }
    }

    event = parse_live_message(payload, own_user_id="seller-1")

    assert event is not None
    assert event.external_id == "message-legacy"
    assert event.conversation_id == "conversation-legacy"
    assert event.content == "旧结构消息"


def test_batched_live_message_shape_returns_every_distinct_message() -> None:
    def message(sequence: int, sender: str, content: str) -> dict:
        return {
            2: f"conversation-{sequence}@goofish",
            5: 1_750_000_000_000 + sequence,
            10: {
                "senderUserId": sender,
                "reminderTitle": f"客户{sequence}",
                "reminderContent": content,
                "extJson": f'{{"messageId":"message-{sequence}"}}',
            },
        }

    first = message(1, "buyer-1", "第一条")
    second = message(2, "buyer-2", "第二条")
    payload = {
        1: [
            {1: first},
            [second, {"unrelated": {"status": "paid"}}],
            first,
        ]
    }

    events = parse_live_messages(payload, own_user_id="seller-1")

    assert [event.external_id for event in events] == ["message-1", "message-2"]
    assert [event.content for event in events] == ["第一条", "第二条"]


def test_batched_live_message_parser_rejects_unrelated_numeric_payloads() -> None:
    payload = {
        1: [
            {2: "conversation-without-extension@goofish", 5: 1_750_000_000_000},
            {10: {"senderUserId": "buyer-without-conversation"}},
            {"order": {2: "trade-1", 10: {"status": "paid"}}},
        ]
    }

    assert parse_live_messages(payload, own_user_id="seller-1") == []


def test_refreshed_domain_cookie_wins_without_httpx_cookie_conflict() -> None:
    adapter = XianyuAdapter(
        Settings(
            _env_file=None,
            xianyu_cookie=SecretStr("unb=seller; _m_h5_tk=stale_suffix; foo=bar"),
        )
    )
    try:
        adapter.http.cookies.set(
            "_m_h5_tk", "fresh_suffix", domain=".goofish.com", path="/"
        )
        adapter.http.cookies.set("foo", "fresh-bar", domain=".goofish.com", path="/")

        assert adapter._cookie_token() == "fresh"
        header = adapter._cookie_header()
        assert header.count("_m_h5_tk=") == 1
        assert "_m_h5_tk=fresh_suffix" in header
        assert header.count("foo=") == 1
        assert "foo=fresh-bar" in header
    finally:
        asyncio.run(adapter.close())


def test_mtop_retry_sends_only_the_refreshed_cookie() -> None:
    async def scenario() -> None:
        adapter = XianyuAdapter(
            Settings(
                _env_file=None,
                xianyu_cookie=SecretStr(
                    "unb=seller; _m_h5_tk=stale_suffix; "
                    "_m_h5_tk_enc=stale-enc; foo=bar"
                ),
            )
        )
        await adapter.http.aclose()
        seen_cookie_headers: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            cookie_header = request.headers.get("cookie", "")
            seen_cookie_headers.append(cookie_header)
            if len(seen_cookie_headers) == 1:
                return httpx.Response(
                    200,
                    json={"ret": ["FAIL_SYS_TOKEN_EXOIRED::令牌过期"]},
                    headers=[
                        (
                            "set-cookie",
                            "_m_h5_tk=fresh_suffix; Domain=.goofish.com; "
                            "Path=/; Max-Age=5400",
                        ),
                        (
                            "set-cookie",
                            "_m_h5_tk_enc=fresh-enc; Domain=.goofish.com; "
                            "Path=/; Max-Age=5400",
                        ),
                    ],
                )
            return httpx.Response(200, json={"ret": ["SUCCESS::调用成功"], "data": {}})

        adapter.http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            cookies=adapter.cookies,
        )
        try:
            await adapter._mtop("test.api", {})
        finally:
            await adapter.close()

        assert len(seen_cookie_headers) == 2
        assert seen_cookie_headers[0].count("_m_h5_tk=") == 1
        assert "_m_h5_tk=stale_suffix" in seen_cookie_headers[0]
        assert seen_cookie_headers[1].count("_m_h5_tk=") == 1
        assert "_m_h5_tk=fresh_suffix" in seen_cookie_headers[1]
        assert "_m_h5_tk=stale_suffix" not in seen_cookie_headers[1]

    asyncio.run(scenario())


def test_recent_conversation_fallback_extracts_latest_message() -> None:
    async def scenario() -> None:
        adapter = XianyuAdapter(
            Settings(
                _env_file=None,
                xianyu_cookie=SecretStr("unb=seller; _m_h5_tk=token_suffix"),
            )
        )
        text_payload = base64.b64encode(
            '{"contentType":1,"text":{"text":"刷新后出现的消息"}}'.encode()
        ).decode()

        async def fake_request(lwp: str, body: list, timeout: float = 15) -> dict:
            assert lwp == "/r/Conversation/listNewest"
            assert body == [0, 50]
            return {
                "body": [
                    {
                        "singleChatUserConversation": {
                            "lastMessage": {
                                "cid": "conversation-fallback@goofish",
                                "createAt": 1_750_000_000_000,
                                "content": {"custom": {"data": text_payload}},
                                "extension": {
                                    "senderUserId": "buyer-fallback",
                                    "reminderTitle": "补偿客户",
                                    "extJson": '{"messageId":"message-fallback"}',
                                },
                            }
                        }
                    }
                ]
            }

        adapter._request = fake_request  # type: ignore[method-assign]
        try:
            messages = await adapter.fetch_recent_conversation_messages(50)
        finally:
            await adapter.close()

        assert len(messages) == 1
        assert messages[0].external_id == "message-fallback"
        assert messages[0].conversation_id == "conversation-fallback"
        assert messages[0].content == "刷新后出现的消息"
        assert messages[0].direction == "inbound"
        assert int(messages[0].received_at.timestamp() * 1000) == 1_750_000_000_000

    asyncio.run(scenario())
