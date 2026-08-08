from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import IncomingMessage, ItemInfo
from ..ai import AIInput, ChatContextMessage, GeneratedDraft
from ..models import AIGenerationTask, Conversation, Draft, Item, Message, OperationLog, utcnow
from .risk import detect_risks


@dataclass(slots=True)
class IngestResult:
    message_id: int
    is_new: bool


def _upsert_item(session: Session, item_info: ItemInfo | None) -> Item | None:
    if not item_info:
        return None
    item = session.scalar(select(Item).where(Item.external_id == item_info.external_id))
    if not item:
        item = Item(external_id=item_info.external_id)
        session.add(item)
    item.title = item_info.title
    item.price = item_info.price
    item.description = item_info.description
    item.raw_json = json.dumps(item_info.raw, ensure_ascii=False)[:100_000]
    session.flush()
    return item


def _merge_conversation_context(
    session: Session,
    conversation: Conversation,
    event: IncomingMessage,
    history: list[IncomingMessage],
    item_info: ItemInfo | None,
) -> None:
    item = _upsert_item(session, item_info)
    if item:
        conversation.item = item

    known_ids = {(event.channel, event.platform_message_id)}
    for old in history:
        identity = (old.channel, old.platform_message_id)
        if identity in known_ids:
            continue
        known_ids.add(identity)
        if session.scalar(
            select(Message.id).where(
                Message.channel == old.channel,
                Message.platform_message_id == old.platform_message_id,
            )
        ):
            continue
        session.add(
            Message(
                channel=old.channel,
                platform_message_id=old.platform_message_id or old.external_id,
                external_id=old.external_id,
                conversation=conversation,
                sender_id=old.sender_id,
                sender_name=old.sender_name,
                direction=old.direction,
                message_type=old.message_type,
                content=old.content,
                status="sent" if old.direction == "outbound" else "history",
                risk_flags_json=json.dumps(detect_risks(old.content), ensure_ascii=False),
                received_at=old.received_at,
            )
        )


def hydrate_conversation_context(
    session: Session,
    event: IncomingMessage,
    history: list[IncomingMessage],
    item_info: ItemInfo | None,
) -> bool:
    """Merge asynchronously fetched context without touching unread state."""
    conversation = session.scalar(
        select(Conversation).where(
            Conversation.channel == event.channel,
            Conversation.external_id == event.conversation_id,
        )
    )
    if not conversation:
        return False
    _merge_conversation_context(session, conversation, event, history, item_info)
    session.commit()
    return True


def ingest_message(
    session: Session,
    event: IncomingMessage,
    history: list[IncomingMessage],
    item_info: ItemInfo | None,
    *,
    source: str = "live",
) -> IngestResult:
    conversation = session.scalar(
        select(Conversation).where(
            Conversation.channel == event.channel,
            Conversation.external_id == event.conversation_id,
        )
    )
    if not conversation:
        conversation = Conversation(
            channel=event.channel,
            external_id=event.conversation_id,
            customer_id=event.sender_id,
            customer_name=event.sender_name,
        )
        session.add(conversation)
        session.flush()
    if event.direction == "inbound":
        conversation.customer_id = event.sender_id
        conversation.customer_name = event.sender_name or conversation.customer_name

    existing = session.scalar(
        select(Message).where(
            Message.channel == event.channel,
            Message.platform_message_id == event.platform_message_id,
        )
    )
    if existing:
        session.rollback()
        return IngestResult(existing.id, False)

    current = Message(
        channel=event.channel,
        platform_message_id=event.platform_message_id or event.external_id,
        external_id=event.external_id,
        conversation=conversation,
        sender_id=event.sender_id,
        sender_name=event.sender_name,
        direction=event.direction,
        message_type=event.message_type,
        content=event.content,
        status="new" if event.direction == "inbound" else "sent",
        risk_flags_json=json.dumps(detect_risks(event.content), ensure_ascii=False),
        received_at=event.received_at,
    )
    session.add(current)
    session.flush()

    _merge_conversation_context(session, conversation, event, history, item_info)
    if event.direction == "inbound":
        conversation.unread_count += 1
    conversation.last_message_at = event.received_at
    session.add(
        OperationLog(
            message_id=current.id,
            action=(
                "message_received"
                if event.direction == "inbound"
                else "outbound_message_synced"
            ),
            detail=(
                "闲鱼实时消息已保存"
                if source == "live"
                else (
                    "闲鱼补偿消息已保存"
                    if source == "reconcile"
                    else (
                        "企业微信消息已保存"
                        if source == "wecom_callback"
                        else "微信 Mock 消息已保存"
                    )
                )
            ),
        )
    )
    session.commit()
    return IngestResult(current.id, True)


def save_drafts(
    session: Session, message_id: int, drafts: list[GeneratedDraft], *, commit: bool = True
) -> None:
    message = session.get(Message, message_id)
    if not message:
        return
    existing = {
        draft.style: draft
        for draft in session.scalars(select(Draft).where(Draft.message_id == message_id))
    }
    for generated in drafts:
        draft = existing.get(generated.style)
        if not draft:
            draft = Draft(message_id=message_id, style=generated.style, content="")
            session.add(draft)
        draft.content = generated.content
        draft.risk_flags_json = json.dumps(generated.risk_flags, ensure_ascii=False)
    if drafts:
        message.status = "drafted"
        session.add(
            OperationLog(
                message_id=message_id,
                action="drafts_generated",
                detail=f"已生成 {len(drafts)} 条 AI 草稿",
            )
        )
    if commit:
        session.commit()


def get_ai_context(
    session: Session, message_id: int, limit: int = 50
) -> tuple[ItemInfo | None, list[tuple[str, str]]]:
    message = session.get(Message, message_id)
    if not message:
        return None, []
    conversation = message.conversation
    rows = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.received_at.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    history = [
        ("客户" if row.direction == "inbound" else "卖家", row.content) for row in rows
    ]
    item = None
    if conversation.item:
        raw = {}
        if conversation.item.raw_json:
            try:
                raw = json.loads(conversation.item.raw_json)
            except json.JSONDecodeError:
                pass
        item = ItemInfo(
            external_id=conversation.item.external_id,
            title=conversation.item.title,
            price=conversation.item.price,
            description=conversation.item.description,
            raw=raw,
        )
    return item, history


def get_ai_input(
    session: Session,
    message_id: int,
    *,
    message_limit: int,
    total_chars: int,
    seller_rules: list[str],
) -> tuple[int, AIInput] | None:
    message = session.get(Message, message_id)
    if not message:
        return None
    conversation = message.conversation
    rows = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.received_at.desc(), Message.id.desc())
            .limit(message_limit)
        )
    )

    remaining = total_chars
    bounded: list[ChatContextMessage] = []
    for row in rows:
        if remaining <= 0:
            break
        content = row.content.strip()
        if not content:
            continue
        clipped = content[:remaining]
        remaining -= len(clipped)
        bounded.append(
            ChatContextMessage(
                direction="customer" if row.direction == "inbound" else "seller",
                content=clipped,
                time=row.received_at.isoformat(),
            )
        )
    bounded.reverse()

    item = conversation.item
    payload = AIInput(
        customer_message=message.content[: min(total_chars, 4000)],
        product={
            "title": item.title if item else "未能获取商品标题",
            "price": item.price if item and item.price else "未提供",
            "description": item.description if item and item.description else "未提供",
        },
        recent_messages=bounded,
        seller_rules=seller_rules,
        current_time=datetime.now().astimezone().isoformat(),
    )
    return conversation.id, payload


def create_generation_task(
    session: Session,
    message_id: int,
    *,
    provider: str,
    automatic: bool,
) -> tuple[AIGenerationTask | None, bool]:
    message = session.get(Message, message_id)
    if not message or message.direction != "inbound":
        return None, False
    if message.status in {"sent", "sending", "ignored"}:
        return None, False

    if automatic:
        trigger_key = f"message:{message_id}:automatic"
        existing = session.scalar(
            select(AIGenerationTask).where(AIGenerationTask.trigger_key == trigger_key)
        )
        if existing:
            return existing, False
    else:
        existing = session.scalar(
            select(AIGenerationTask)
            .where(
                AIGenerationTask.message_id == message_id,
                AIGenerationTask.status.in_(("pending", "running")),
            )
            .order_by(AIGenerationTask.created_at.desc())
            .limit(1)
        )
        if existing:
            return existing, False
        trigger_key = f"message:{message_id}:manual:{uuid.uuid4()}"

    task = AIGenerationTask(
        message_id=message.id,
        conversation_id=message.conversation_id,
        trigger_key=trigger_key,
        provider=provider,
        status="pending",
        needs_human_confirmation=True,
    )
    message.status = "ai_queued"
    session.add(task)
    session.add(
        OperationLog(
            message_id=message.id,
            action="ai_task_created",
            detail="已创建 AI 草稿生成任务" if automatic else "用户请求重新生成草稿",
        )
    )
    session.commit()
    return task, True


def recover_generation_tasks(session: Session) -> list[int]:
    running = list(
        session.scalars(
            select(AIGenerationTask).where(AIGenerationTask.status == "running")
        )
    )
    for task in running:
        if task.cancel_requested:
            task.status = "cancelled"
            task.finished_at = utcnow()
        else:
            task.status = "pending"
            message = session.get(Message, task.message_id)
            if message and message.status not in {"sent", "sending", "ignored"}:
                message.status = "ai_queued"
    session.commit()
    return list(
        session.scalars(
            select(AIGenerationTask.id)
            .where(AIGenerationTask.status == "pending")
            .order_by(AIGenerationTask.created_at.asc())
        )
    )


def latest_generation_task(session: Session, message_id: int) -> AIGenerationTask | None:
    return session.scalar(
        select(AIGenerationTask)
        .where(AIGenerationTask.message_id == message_id)
        .order_by(AIGenerationTask.created_at.desc(), AIGenerationTask.id.desc())
        .limit(1)
    )
