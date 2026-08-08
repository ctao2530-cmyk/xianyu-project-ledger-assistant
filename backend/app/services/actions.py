from __future__ import annotations

import json
import time

from sqlalchemy import select

from ..adapters import XianyuAdapterProtocol
from ..channels.base import ChannelSenderRegistry
from ..channels.xianyu import XianyuSender
from ..database import Database
from ..models import Conversation, Message, OperationLog
from .risk import detect_risks
from .style_learning import StyleLearningService


class ActionConflictError(RuntimeError):
    pass


class MessageNotFoundError(RuntimeError):
    pass


class HumanActions:
    def __init__(
        self,
        database: Database,
        adapter: XianyuAdapterProtocol | ChannelSenderRegistry,
        style_learning: StyleLearningService | None = None,
    ) -> None:
        self.database = database
        self.sender_registry = (
            adapter
            if isinstance(adapter, ChannelSenderRegistry)
            else ChannelSenderRegistry(XianyuSender(adapter))
        )
        self.style_learning = style_learning

    def channel_for_message(self, message_id: int) -> str:
        with self.database.session() as session:
            message = session.get(Message, message_id)
            if not message:
                raise MessageNotFoundError
            return message.channel

    async def confirm_send(self, message_id: int, content: str) -> list[str]:
        return await self._send(message_id, content, actor="human")

    async def auto_send(self, message_id: int, content: str) -> list[str]:
        """Send one pre-vetted draft after the user armed unattended mode."""
        return await self._send(message_id, content, actor="automatic")

    async def _send(self, message_id: int, content: str, *, actor: str) -> list[str]:
        with self.database.session() as session:
            message = session.get(Message, message_id)
            if not message:
                raise MessageNotFoundError
            if message.direction != "inbound" or message.status in {"sent", "sending", "ignored"}:
                raise ActionConflictError(f"消息当前状态不能发送：{message.status}")
            if actor == "automatic" and message.status != "drafted":
                raise ActionConflictError(f"消息当前状态不能自动回复：{message.status}")
            conversation = message.conversation
            client_uuid = message.client_send_uuid or f"-{message.id}-{int(time.time() * 1000)}1"
            message.client_send_uuid = client_uuid
            message.status = "sending"
            session.add(
                OperationLog(
                    message_id=message.id,
                    action=(
                        "auto_reply_authorized"
                        if actor == "automatic"
                        else "human_send_confirmed"
                    ),
                    detail=(
                        "无人值守开关已授权低风险自动回复"
                        if actor == "automatic"
                        else "用户在管理页面确认发送"
                    ),
                )
            )
            session.commit()
            conversation_id = conversation.external_id
            receiver_id = conversation.customer_id
            channel = message.channel

        try:
            await self.sender_registry.send_message(
                channel, conversation_id, receiver_id, content, client_uuid
            )
        except Exception as exc:
            with self.database.session() as session:
                message = session.get(Message, message_id)
                if message:
                    message.status = "send_failed"
                    session.add(
                        OperationLog(
                            message_id=message_id,
                            action="send_failed",
                            detail=type(exc).__name__,
                        )
                    )
                    session.commit()
            raise

        flags = detect_risks(content)
        with self.database.session() as session:
            message = session.get(Message, message_id)
            if not message:
                raise MessageNotFoundError
            conversation = message.conversation
            message.status = "sent"
            platform_outbound_id = f"local-{message.client_send_uuid}"
            outbound_id = (
                platform_outbound_id
                if message.channel == "xianyu"
                else f"{message.channel}:{platform_outbound_id}"
            )
            outbound = session.scalar(
                select(Message).where(
                    Message.channel == message.channel,
                    Message.platform_message_id == platform_outbound_id,
                )
            )
            if not outbound:
                outbound = Message(
                    channel=message.channel,
                    platform_message_id=platform_outbound_id,
                    external_id=outbound_id,
                    conversation=conversation,
                    sender_id="self",
                    sender_name="我",
                    direction="outbound",
                    message_type="text",
                    content=content,
                    status="sent",
                    risk_flags_json=json.dumps(flags, ensure_ascii=False),
                )
                session.add(outbound)
                session.flush()
            if self.style_learning:
                self.style_learning.record_message(
                    session,
                    outbound,
                    source="automatic" if actor == "automatic" else "human_confirmed",
                    included=actor != "automatic",
                )
            conversation.unread_count = max(0, conversation.unread_count - 1)
            session.add(
                OperationLog(
                    message_id=message_id,
                    action="auto_reply_sent" if actor == "automatic" else "message_sent",
                    detail=(
                        "无人值守模式已自动发送低风险回复"
                        if actor == "automatic"
                        else "人工确认内容已发送"
                    ),
                )
            )
            session.commit()
        return flags

    def ignore(self, message_id: int) -> None:
        with self.database.session() as session:
            message = session.get(Message, message_id)
            if not message:
                raise MessageNotFoundError
            if message.status in {"sent", "sending"}:
                raise ActionConflictError(f"消息当前状态不能忽略：{message.status}")
            message.status = "ignored"
            message.conversation.unread_count = max(
                0, message.conversation.unread_count - 1
            )
            session.add(
                OperationLog(
                    message_id=message_id,
                    action="message_ignored",
                    detail="用户在管理页面忽略消息",
                )
            )
            session.commit()
