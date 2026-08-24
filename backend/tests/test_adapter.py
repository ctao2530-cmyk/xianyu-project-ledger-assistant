from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import stat
import time
from datetime import timezone
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import msgpack
import pytest
from pydantic import SecretStr

from backend.app.adapters import AdapterAccessVerificationError, AdapterError
from backend.app.channels.base import ChannelMedia
from backend.app.adapters.xianyu import (
    XianyuAdapter,
    _verification_url,
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


def test_live_image_message_keeps_only_ephemeral_trusted_media_reference() -> None:
    payload = {
        1: {
            2: "conversation-image@goofish",
            5: 1_750_000_000_000,
            10: {
                "senderUserId": "buyer-image",
                "reminderTitle": "图片客户",
                "reminderContent": "[图片]",
                "extJson": json.dumps(
                    {
                        "messageId": "message-image",
                        "contentType": 2,
                        "image": {"url": "https://img.alicdn.com/customer/original.jpg"},
                        "avatarUrl": "https://img.alicdn.com/avatar/should-not-capture.jpg",
                    }
                ),
            },
        }
    }

    event = parse_live_message(payload, own_user_id="seller-1")

    assert event is not None
    assert event.message_type == "image"
    assert event.content == "[图片]"
    assert len(event.media) == 1
    assert event.media[0].locator == "https://img.alicdn.com/customer/original.jpg"
    assert "should-not-capture" not in event.media[0].locator


@pytest.mark.asyncio
async def test_xianyu_media_download_accepts_only_trusted_image_hosts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "img.alicdn.com"
        return httpx.Response(200, content=b"trusted-image-bytes", headers={"content-type": "image/jpeg"})

    adapter = XianyuAdapter(
        Settings(_env_file=None, xianyu_cookie=SecretStr("unb=seller; _m_h5_tk=token_suffix"))
    )
    await adapter.http.aclose()
    adapter.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        content = await adapter.fetch_media(
            ChannelMedia("remote_url", "https://img.alicdn.com/customer/original.jpg")
        )
        assert content.data == b"trusted-image-bytes"
        assert content.mime_type == "image/jpeg"
        with pytest.raises(AdapterError, match="来源不可信"):
            await adapter.fetch_media(
                ChannelMedia("remote_url", "https://evil.example/customer.jpg")
            )
    finally:
        await adapter.close()


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


def test_optional_session_cache_loads_only_for_matching_account(tmp_path: Path) -> None:
    future_ms = int(time.time() * 1000) + 3_600_000
    cache_path = tmp_path / "private" / "xianyu-session.json"
    cache_path.parent.mkdir()
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "account_fingerprint": hashlib.sha256(b"seller").hexdigest(),
                "cookies": {
                    "_m_h5_tk": f"fresh_{future_ms}",
                    "_m_h5_tk_enc": "fresh-enc",
                },
            }
        ),
        encoding="utf-8",
    )
    cache_path.chmod(0o644)

    adapter = XianyuAdapter(
        Settings(
            _env_file=None,
            xianyu_cookie=SecretStr(
                "unb=seller; _m_h5_tk=stale_suffix; _m_h5_tk_enc=stale-enc"
            ),
            xianyu_session_cache_path=str(cache_path),
        )
    )
    try:
        assert adapter._cookie_token() == "fresh"
        assert stat.S_IMODE(cache_path.stat().st_mode) == 0o600
    finally:
        asyncio.run(adapter.close())

    other_account = XianyuAdapter(
        Settings(
            _env_file=None,
            xianyu_cookie=SecretStr(
                "unb=other; _m_h5_tk=original_suffix; _m_h5_tk_enc=original-enc"
            ),
            xianyu_session_cache_path=str(cache_path),
        )
    )
    try:
        assert other_account._cookie_token() == "original"
    finally:
        asyncio.run(other_account.close())


def test_mtop_refresh_persists_only_short_lived_session_cookies(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        future_ms = int(time.time() * 1000) + 3_600_000
        cache_path = tmp_path / "private" / "xianyu-session.json"
        adapter = XianyuAdapter(
            Settings(
                _env_file=None,
                xianyu_cookie=SecretStr(
                    "unb=seller; cookie2=session; _m_h5_tk=stale_suffix; "
                    "_m_h5_tk_enc=stale-enc; unrelated=must-not-be-cached"
                ),
                xianyu_session_cache_path=str(cache_path),
            )
        )
        await adapter.http.aclose()

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"ret": ["SUCCESS::调用成功"], "data": {}},
                headers=[
                    (
                        "set-cookie",
                        f"_m_h5_tk=fresh_{future_ms}; Domain=.goofish.com; Path=/",
                    ),
                    (
                        "set-cookie",
                        "_m_h5_tk_enc=fresh-enc; Domain=.goofish.com; Path=/",
                    ),
                ],
            )

        adapter.http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            cookies=adapter.cookies,
        )
        try:
            await adapter._mtop("test.api", {})
        finally:
            await adapter.close()

        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        assert set(payload["cookies"]) == {"_m_h5_tk", "_m_h5_tk_enc"}
        assert payload["cookies"]["_m_h5_tk"] == f"fresh_{future_ms}"
        assert "seller" not in cache_path.read_text(encoding="utf-8")
        assert "must-not-be-cached" not in cache_path.read_text(encoding="utf-8")
        assert stat.S_IMODE(cache_path.stat().st_mode) == 0o600

    asyncio.run(scenario())


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


def test_mtop_reports_interactive_access_verification() -> None:
    async def scenario() -> None:
        adapter = XianyuAdapter(
            Settings(
                _env_file=None,
                xianyu_cookie=SecretStr("unb=seller; _m_h5_tk=token_suffix"),
            )
        )
        await adapter.http.aclose()

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "ret": [
                        "FAIL_SYS_USER_VALIDATE",
                        "RGV587_ERROR::SM::请稍后重试",
                    ],
                    "data": {
                        "url": "https://passport.taobao.com/punish?one_time=1"
                    },
                },
            )

        adapter.http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            cookies=adapter.cookies,
        )
        try:
            with pytest.raises(AdapterAccessVerificationError) as captured:
                await adapter._mtop("test.api", {})
            assert captured.value.verification_url == (
                "https://passport.taobao.com/punish?one_time=1"
            )
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_verification_url_rejects_non_platform_or_non_https_targets() -> None:
    assert _verification_url({"data": {"url": "https://evil.example/verify"}}) is None
    assert _verification_url({"url": "http://passport.taobao.com/punish"}) is None


def test_item_detail_uses_item_page_context_and_current_browser_headers() -> None:
    async def scenario() -> None:
        adapter = XianyuAdapter(
            Settings(
                _env_file=None,
                xianyu_cookie=SecretStr(
                    "unb=seller; _m_h5_tk=token_suffix; _m_h5_tk_enc=enc"
                ),
            )
        )
        await adapter.http.aclose()

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["spm_cnt"] == "a21ybx.item.0.0"
            assert request.headers["sec-fetch-site"] == "same-site"
            assert request.headers["sec-ch-ua-platform"] == '"macOS"'
            assert "Chrome/146.0.0.0" in request.headers["user-agent"]
            return httpx.Response(
                200,
                json={
                    "ret": ["SUCCESS::调用成功"],
                    "data": {
                        "itemDO": {
                            "title": "测试商品",
                            "soldPrice": "5.90",
                            "trackParams": {"sellerId": "seller"},
                        }
                    },
                },
            )

        adapter.http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            cookies=adapter.cookies,
            headers=adapter.http.headers,
        )
        try:
            item = await adapter.fetch_item("item-1")
        finally:
            await adapter.close()

        assert item is not None
        assert item.title == "测试商品"
        assert item.seller_id == "seller"

    asyncio.run(scenario())


def test_owned_listing_discovery_uses_current_account_and_maps_safe_fields() -> None:
    async def scenario() -> None:
        adapter = XianyuAdapter(
            Settings(
                _env_file=None,
                xianyu_cookie=SecretStr(
                    "unb=seller; _m_h5_tk=token_suffix; _m_h5_tk_enc=enc"
                ),
            )
        )
        await adapter.http.aclose()
        calls: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode().removeprefix("data=") or "{}") if False else None
            body = parse_qs(request.content.decode())
            data = json.loads(body["data"][0])
            calls.append(data)
            return httpx.Response(
                200,
                json={
                    "ret": ["SUCCESS::调用成功"],
                    "data": {
                        "topItem": {"cardData": {"id": "owned-1", "title": "置顶商品", "priceInfo": {"price": "88"}, "itemStatus": 0}},
                        "cardList": [
                            {"cardData": {"id": "owned-1", "title": "重复置顶", "priceInfo": {"price": "88"}, "itemStatus": "0"}},
                            {"cardData": {"id": "owned-2", "title": "普通商品", "priceInfo": {"price": "199"}, "itemStatus": "0"}},
                            {"cardData": {"id": "down-1", "title": "已下架商品", "priceInfo": {"price": "66"}, "itemStatus": 1}},
                        ],
                        "nextPage": False,
                    },
                },
            )

        adapter.http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            cookies=adapter.cookies,
            headers=adapter.http.headers,
        )
        try:
            items = await adapter.list_owned_items()
        finally:
            await adapter.close()

        assert calls == [{"needGroupInfo": True, "pageNumber": 1, "userId": "seller", "pageSize": 20}]
        assert [item.external_id for item in items] == ["owned-1", "owned-2", "down-1"]
        assert [item.status for item in items] == ["在售", "在售", "已下架"]
        assert items[1].title == "普通商品"
        assert items[1].price == "¥199"

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
