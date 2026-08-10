from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol

from ..channels.base import ChannelMessage


class AdapterError(RuntimeError):
    pass


class LoginExpiredError(AdapterError):
    pass


class AdapterAccessVerificationError(AdapterError):
    """The platform accepted the request but required interactive validation."""

    def __init__(self, message: str, *, verification_url: str | None = None) -> None:
        super().__init__(message)
        self.verification_url = verification_url


class AdapterDisconnectedError(AdapterError):
    pass


IncomingMessage = ChannelMessage


@dataclass(slots=True)
class ItemInfo:
    external_id: str
    title: str
    price: str | None
    description: str | None
    raw: dict
    seller_id: str | None = None


class XianyuAdapterProtocol(Protocol):
    connected: bool
    own_user_id: str

    async def listen(
        self, on_ready: Callable[[], None] | None = None
    ) -> AsyncIterator[IncomingMessage]: ...

    async def fetch_recent_messages(
        self, conversation_id: str, limit: int
    ) -> list[IncomingMessage]: ...

    async def fetch_recent_conversation_messages(
        self, limit: int
    ) -> list[IncomingMessage]: ...

    async def fetch_item(self, item_id: str) -> ItemInfo | None: ...

    async def send_text(
        self,
        conversation_id: str,
        receiver_id: str,
        text: str,
        client_message_id: str,
    ) -> None: ...

    async def close(self) -> None: ...
