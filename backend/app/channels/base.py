from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


SUPPORTED_CHANNELS = frozenset({"xianyu", "wechat"})


class UnsupportedChannelError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class ChannelMedia:
    """Ephemeral provider media reference.

    ``locator`` may be a signed URL or provider media id, so it must stay in
    memory only.  The archive service persists only the downloaded image facts.
    """

    locator_type: str
    locator: str
    media_index: int = 0
    mime_type: str | None = None
    original_name: str | None = None


@dataclass(frozen=True, slots=True)
class ChannelMediaContent:
    data: bytes
    mime_type: str | None = None
    original_name: str | None = None


@dataclass(slots=True)
class ChannelMessage:
    """Provider-neutral inbound/outbound message consumed by the existing pipeline."""

    external_id: str
    conversation_id: str
    sender_id: str
    sender_name: str
    content: str
    message_type: str
    received_at: datetime
    item_id: str | None = None
    direction: str = "inbound"
    channel: str = "xianyu"
    platform_message_id: str | None = None
    media: tuple[ChannelMedia, ...] = ()

    def __post_init__(self) -> None:
        if self.channel not in SUPPORTED_CHANNELS:
            raise ValueError(f"不支持的消息渠道：{self.channel}")
        if not self.platform_message_id:
            self.platform_message_id = self.external_id


@dataclass(frozen=True, slots=True)
class ChannelConversationInfo:
    channel: str
    conversation_id: str
    customer_id: str
    customer_name: str


@runtime_checkable
class ChannelAdapter(Protocol):
    """Normalize one provider event and expose its conversation identity."""

    channel: str

    async def receive_message(self, payload: Any) -> ChannelMessage: ...

    async def get_conversation_info(
        self, conversation_id: str
    ) -> ChannelConversationInfo | None: ...


@runtime_checkable
class ChannelSender(Protocol):
    channel: str

    async def send_message(
        self,
        conversation_id: str,
        receiver_id: str,
        text: str,
        client_message_id: str,
    ) -> None: ...


class ChannelSenderRegistry:
    def __init__(self, *senders: ChannelSender) -> None:
        self._senders: dict[str, ChannelSender] = {}
        for sender in senders:
            self.register(sender)

    def register(self, sender: ChannelSender) -> None:
        if sender.channel not in SUPPORTED_CHANNELS:
            raise UnsupportedChannelError(f"不支持的发送渠道：{sender.channel}")
        self._senders[sender.channel] = sender

    def get(self, channel: str) -> ChannelSender:
        sender = self._senders.get(channel)
        if sender is None:
            raise UnsupportedChannelError(f"渠道 {channel} 尚未配置发送器")
        return sender

    async def send_message(
        self,
        channel: str,
        conversation_id: str,
        receiver_id: str,
        text: str,
        client_message_id: str,
    ) -> None:
        await self.get(channel).send_message(
            conversation_id,
            receiver_id,
            text,
            client_message_id,
        )
