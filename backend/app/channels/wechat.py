from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, Field

from .base import ChannelConversationInfo, ChannelMedia, ChannelMessage


logger = logging.getLogger(__name__)


class WechatWebhookPayload(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    nickname: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=1000)
    message_id: str | None = Field(default=None, min_length=1, max_length=255)


class WechatMockProvider:
    """Local-only event source that can later be replaced by Hook or WeCom APIs."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.id_factory = id_factory or (lambda: f"mock-{uuid.uuid4().hex}")
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def receive(self, payload: WechatWebhookPayload) -> dict[str, object]:
        return {
            "message_id": payload.message_id or self.id_factory(),
            "user_id": payload.user_id.strip(),
            "nickname": payload.nickname.strip(),
            "content": payload.content.strip(),
            "received_at": self.clock(),
        }


class WeChatAdapter:
    channel = "wechat"

    def __init__(self, provider: WechatMockProvider | None = None) -> None:
        self.provider = provider or WechatMockProvider()
        self._conversations: dict[str, ChannelConversationInfo] = {}

    async def receive_message(self, payload: WechatWebhookPayload) -> ChannelMessage:
        raw = await self.provider.receive(payload)
        platform_message_id = str(raw["message_id"])
        customer_id = str(raw["user_id"])
        customer_name = str(raw["nickname"])
        conversation_id = f"wechat:{customer_id}"
        info = ChannelConversationInfo(
            channel=self.channel,
            conversation_id=conversation_id,
            customer_id=customer_id,
            customer_name=customer_name,
        )
        self._conversations[conversation_id] = info
        return ChannelMessage(
            channel=self.channel,
            platform_message_id=platform_message_id,
            external_id=f"wechat:{platform_message_id}",
            conversation_id=conversation_id,
            sender_id=customer_id,
            sender_name=customer_name,
            content=str(raw["content"]),
            message_type="text",
            received_at=raw["received_at"],  # type: ignore[arg-type]
        )

    async def receive_wecom_message(
        self,
        raw: dict[str, Any],
        *,
        customer_name: str,
    ) -> ChannelMessage:
        """Normalize one official WeCom Customer Service sync result."""
        platform_message_id = str(raw["msgid"])
        customer_id = str(raw["external_userid"])
        open_kfid = str(raw["open_kfid"])
        conversation_id = f"wechat:{open_kfid}:{customer_id}"
        info = ChannelConversationInfo(
            channel=self.channel,
            conversation_id=conversation_id,
            customer_id=customer_id,
            customer_name=customer_name,
        )
        self._conversations[conversation_id] = info
        send_time = int(raw.get("send_time") or 0)
        received_at = (
            datetime.fromtimestamp(send_time, tz=timezone.utc)
            if send_time > 0
            else datetime.now(timezone.utc)
        )
        direction = "inbound" if int(raw.get("origin") or 0) == 3 else "outbound"
        content, message_type = _wecom_content(raw, inbound=direction == "inbound")
        media: tuple[ChannelMedia, ...] = ()
        if direction == "inbound" and message_type == "image":
            image = raw.get("image")
            image_data = image if isinstance(image, dict) else {}
            media_id = str(image_data.get("media_id") or "").strip()
            if media_id:
                media = (
                    ChannelMedia(
                        locator_type="wecom_media_id",
                        locator=media_id,
                        media_index=0,
                        original_name=f"wechat-{platform_message_id}.jpg",
                    ),
                )
        return ChannelMessage(
            channel=self.channel,
            platform_message_id=platform_message_id,
            external_id=f"wechat:{platform_message_id}",
            conversation_id=conversation_id,
            sender_id=customer_id if direction == "inbound" else "self",
            sender_name=customer_name if direction == "inbound" else "我",
            content=content,
            message_type=message_type,
            received_at=received_at,
            direction=direction,
            media=media,
        )

    async def get_conversation_info(
        self, conversation_id: str
    ) -> ChannelConversationInfo | None:
        return self._conversations.get(conversation_id)


def _wecom_content(raw: dict[str, Any], *, inbound: bool) -> tuple[str, str]:
    msgtype = str(raw.get("msgtype") or "unknown")
    body = raw.get(msgtype)
    data = body if isinstance(body, dict) else {}
    if msgtype == "text":
        content = str(data.get("content") or "").strip()
        return (content or "[空文本消息]", "text")
    labels = {
        "image": "图片",
        "voice": "语音",
        "video": "视频",
        "file": "文件",
        "location": "位置",
        "link": "链接",
        "business_card": "名片",
        "miniprogram": "小程序",
        "msgmenu": "菜单消息",
        "channels_shop_product": "视频号商品",
        "channels_shop_order": "视频号订单",
    }
    actor = "客户" if inbound else "客服"
    detail = data.get("title") or data.get("filename") or data.get("name")
    suffix = f"：{str(detail).strip()}" if detail else ""
    return (f"[{actor}发送了{labels.get(msgtype, msgtype)}{suffix}]", msgtype)


class WechatSender:
    """Mock sender boundary for a future WeChat Hook or WeCom implementation."""

    channel = "wechat"

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str]] = []

    async def send_message(
        self,
        conversation_id: str,
        receiver_id: str,
        text: str,
        client_message_id: str,
    ) -> None:
        record = {
            "conversation_id": conversation_id,
            "receiver_id": receiver_id,
            "content": text,
            "client_message_id": client_message_id,
        }
        self.sent_messages.append(record)
        print(f"[WechatMock] send to {receiver_id}: {text}")
        logger.info(
            "微信 Mock 发送 receiver=%s client_message_id=%s content_length=%s",
            receiver_id,
            client_message_id,
            len(text),
        )
