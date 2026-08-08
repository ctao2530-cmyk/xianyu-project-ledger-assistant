from __future__ import annotations

from ..adapters.base import XianyuAdapterProtocol


class XianyuSender:
    """ChannelSender bridge; the existing Xianyu protocol implementation is unchanged."""

    channel = "xianyu"

    def __init__(self, adapter: XianyuAdapterProtocol) -> None:
        self.adapter = adapter

    async def send_message(
        self,
        conversation_id: str,
        receiver_id: str,
        text: str,
        client_message_id: str,
    ) -> None:
        await self.adapter.send_text(
            conversation_id,
            receiver_id,
            text,
            client_message_id,
        )
