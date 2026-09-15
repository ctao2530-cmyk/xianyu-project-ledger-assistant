"""Bounded local message lookup; never marks read or contacts a channel/model."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, func, tuple_
from ..models import Conversation, Message
from ..customer_time import utc_from_storage
from .customer_conversation_groups import CustomerConversationGroupService, ConversationGroupError


class CustomerMessageSearch:
    def __init__(self, database):
        self.database = database

    def read(self, *, customer_id=None, conversation_id=None, conversation_ids=(),
             query='', date_from=None, date_to=None, before_message_id=None, limit=30, message_id=None):
        if bool(customer_id) == bool(conversation_id):
            raise HTTPException(422, '请选择一个明确客户或未建档会话')
        if len(conversation_ids) > 100:
            raise HTTPException(422, '一次最多选择100条会话')
        if not message_id and not query.strip():
            raise HTTPException(422, '请输入消息关键词')
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, '开始日期不能晚于结束日期')
        if not 1 <= limit <= 100 or len(query) > 200:
            raise HTTPException(422, '搜索分页或关键词超出允许范围')
        if any(day and not date(1900, 1, 1) <= day < date(9999, 12, 31) for day in (date_from, date_to)):
            raise HTTPException(422, '请选择有效的消息日期范围')
        with self.database.session() as session:
            if customer_id:
                try:
                    candidates = CustomerConversationGroupService.candidate_rows(session, customer_id)
                except ConversationGroupError as exc:
                    raise HTTPException(404, '客户不存在') from exc
                allowed = {c.id for c in candidates}
                # No silent customer-wide expansion: caller must select members.
                selected = set(conversation_ids)
                if not selected or not selected <= allowed:
                    raise HTTPException(403, '搜索范围不属于该客户，请重新选择关联会话')
            else:
                if conversation_ids or session.get(Conversation, conversation_id) is None:
                    raise HTTPException(404, '会话不存在或范围不匹配')
                selected = {conversation_id}
            scope = Message.conversation_id.in_(selected)
            if message_id:
                anchor = session.scalar(select(Message).where(scope, Message.id == message_id))
                if anchor is None:
                    raise HTTPException(404, '该消息不在选定范围内')
                # Context belongs to the hit's original conversation, not an inferred merge.
                same = Message.conversation_id == anchor.conversation_id
                pair = tuple_(Message.received_at, Message.id)
                value = tuple_(anchor.received_at, anchor.id)
                before = list(session.scalars(select(Message).where(same, pair < value).order_by(Message.received_at.desc(), Message.id.desc()).limit(5)))
                after = list(session.scalars(select(Message).where(same, pair > value).order_by(Message.received_at, Message.id).limit(5)))
                from ..api import message_view
                rows = [*reversed(before), anchor, *after]
                return {'message_id': anchor.id, 'conversation_id': anchor.conversation_id,
                        'messages': [{**message_view(row).model_dump(mode='json'), 'conversation_id': row.conversation_id} for row in rows]}
            predicates = [scope, Message.content.contains(query.strip(), autoescape=True)]
            def midnight(day):
                return datetime.combine(day, time.min, ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc)
            if date_from:
                predicates.append(Message.received_at >= midnight(date_from))
            if date_to:
                predicates.append(Message.received_at < midnight(date_to + timedelta(days=1)))
            total = session.scalar(select(func.count(Message.id)).where(*predicates)) or 0
            if before_message_id:
                anchor = session.scalar(select(Message).where(*predicates, Message.id == before_message_id))
                if anchor is None:
                    raise HTTPException(409, '搜索游标不属于当前范围，请重新搜索')
                predicates.append(tuple_(Message.received_at, Message.id) < tuple_(anchor.received_at, anchor.id))
            rows = list(session.scalars(select(Message).where(*predicates).order_by(Message.received_at.desc(), Message.id.desc()).limit(limit + 1)))
            has_more = len(rows) > limit
            items = []
            for row in rows[:limit]:
                text = row.content or ''
                position = max(0, text.lower().find(query.strip().lower()))
                start = max(0, position - 70)
                snippet = ('…' if start else '') + text[start:start + 240] + ('…' if len(text) > start + 240 else '')
                items.append({'id': row.id, 'conversation_id': row.conversation_id, 'received_at': utc_from_storage(row.received_at),
                              'direction': row.direction, 'message_type': row.message_type, 'snippet': snippet})
            return {'items': items, 'total': total, 'has_more': has_more,
                    'next_before_message_id': items[-1]['id'] if has_more else None,
                    'conversation_ids': sorted(selected), 'scope': 'local_saved_messages_only'}
