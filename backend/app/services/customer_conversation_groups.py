"""Versioned, explicitly selected conversation views and immutable grant scopes."""
from __future__ import annotations
import hashlib
import json
import secrets
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, text, func
from ..database import Database
from ..models import BusinessCustomer, Conversation, CustomerChannelIdentity, CustomerContextGrant, CustomerImageArchive, Item, Message, utcnow
from ..customer_conversation_models import (
    CustomerConversationGroup as Group, CustomerConversationGroupMember as Member,
    CustomerConversationGroupPreview as Preview, CustomerConversationGroupMutation as Mutation,
    CustomerContextGroupScope as GroupScope,
)


class ConversationGroupError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class CustomerConversationGroupService:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def candidate_rows(session, customer_id):
        if session.get(BusinessCustomer, customer_id) is None:
            raise ConversationGroupError("customer_not_found", "客户不存在")
        return list(session.scalars(select(Conversation).join(
            CustomerChannelIdentity,
            (CustomerChannelIdentity.channel == Conversation.channel)
            & (CustomerChannelIdentity.external_customer_id == Conversation.customer_id),
        ).where(CustomerChannelIdentity.customer_id == customer_id).order_by(Conversation.id)).unique())

    @staticmethod
    def member_view(session, row):
        item = session.get(Item, row.item_id) if row.item_id else None
        return {"id": row.id, "conversation_id": row.id, "customer_name": row.customer_name,
                "channel": row.channel, "item_id": row.item_id,
                "item_external_id": item.external_id if item else None,
                "item_title": item.title if item else None}

    @classmethod
    def view(cls, session, group):
        rows = list(session.scalars(select(Conversation).join(Member, Member.conversation_id == Conversation.id)
            .where(Member.group_id == group.id, Member.active.is_(True)).order_by(Conversation.id)))
        return {"id": group.id, "customer_id": group.customer_id, "revision": group.revision,
                "title": "合并会话", "active": group.status == "active",
                "status": group.status, "conversation_ids": [r.id for r in rows],
                "members": [cls.member_view(session, r) for r in rows]}

    def candidates(self, customer_id):
        with self.database.session() as session:
            rows = self.candidate_rows(session, customer_id)
            groups = session.scalars(select(Group).where(Group.customer_id == customer_id).order_by(Group.created_at))
            return {"conversations": [self.member_view(session, r) for r in rows],
                    "groups": [self.view(session, group) for group in groups]}

    def _validate(self, session, customer_id, group_id, conversation_ids, expected_revision):
        if len(conversation_ids) != len(set(conversation_ids)) or len(conversation_ids) > 100:
            raise ConversationGroupError("invalid_members", "会话选择重复或超过100项")
        allowed = {r.id for r in self.candidate_rows(session, customer_id)}
        if not set(conversation_ids) <= allowed:
            raise ConversationGroupError("customer_identity_mismatch", "只能选择已通过稳定渠道身份关联到该客户的会话")
        group = session.get(Group, group_id) if group_id else None
        if group_id and (not group or group.customer_id != customer_id):
            raise ConversationGroupError("group_not_found", "会话组不存在")
        if expected_revision != (group.revision if group else 0):
            raise ConversationGroupError("group_revision_conflict", "会话组已变化，请重新预览")
        if not group and len(conversation_ids) < 2:
            raise ConversationGroupError("invalid_members", "创建合并视图至少选择两个会话")
        return group

    def change(self, customer_id, *, group_id=None, conversation_ids, expected_revision,
               request_id, reason, confirmed=False, preview_token=None):
        ids = sorted(conversation_ids)
        payload = dict(customer_id=customer_id, group_id=group_id, conversation_ids=ids,
                       expected_revision=expected_revision, request_id=request_id, reason=reason)
        payload_hash = digest(payload)
        with self.database.session() as session:
            session.execute(text("BEGIN IMMEDIATE") if session.bind.dialect.name == "sqlite" else text("SELECT 1"))
            repeated = session.get(Mutation, request_id)
            if repeated:
                if repeated.payload_hash != payload_hash:
                    raise ConversationGroupError("request_id_reused", "请求编号已用于不同操作")
                return {**json.loads(repeated.result_json), "idempotent": True}
            group = self._validate(session, customer_id, group_id, ids, expected_revision)
            before = self.view(session, group) if group else {"conversation_ids": []}
            if not confirmed:
                token = secrets.token_urlsafe(32)
                session.add(Preview(token_hash=digest(token), payload_hash=payload_hash,
                                    expires_at=utcnow() + timedelta(minutes=10)))
                session.commit()
                return {"preview_token": token, **payload, "revision": expected_revision,
                        "members": [self.member_view(session, session.get(Conversation, i)) for i in ids],
                        "effects": {"added": sorted(set(ids)-set(before["conversation_ids"])),
                                    "removed": sorted(set(before["conversation_ids"])-set(ids)),
                                    "originals_unchanged": True, "new_members_not_auto_authorized": True,
                                    "previously_sent_content_not_retractable": True}}
            preview = session.get(Preview, digest(preview_token or ""))
            if not preview or preview.payload_hash != payload_hash or preview.expires_at.replace(tzinfo=utcnow().tzinfo) <= utcnow():
                raise ConversationGroupError("preview_invalid", "预览失效，请重新预览并确认")
            now = utcnow()
            if group is None:
                group = Group(id=f"conversation-group-{uuid4().hex}", customer_id=customer_id, revision=1)
                session.add(group)
                session.flush()
            else:
                group.revision += 1
            group.status = "active" if ids else "disbanded"
            group.updated_at = now
            removed = set(before["conversation_ids"]) - set(ids)
            for member in session.scalars(select(Member).where(Member.group_id == group.id)):
                member.active = member.conversation_id in ids
                member.updated_at = now
            for cid in ids:
                if not session.get(Member, (group.id, cid)):
                    session.add(Member(group_id=group.id, conversation_id=cid, active=True))
            # Revocation is permanent: re-adding a member never resurrects access.
            for scope in session.scalars(select(GroupScope).where(GroupScope.group_id == group.id)):
                if removed.intersection(json.loads(scope.conversation_ids_json)) or not ids:
                    grant = session.get(CustomerContextGrant, scope.grant_id)
                    if grant and grant.status == "active":
                        grant.status, grant.revoked_at, grant.updated_at = "revoked", now, now
            session.flush()
            result = self.view(session, group)
            session.add(Mutation(request_id=request_id, group_id=group.id, payload_hash=payload_hash,
                                 reason=reason, before_json=encoded(before), result_json=encoded(result)))
            session.delete(preview)
            session.commit()
            return result

    def timeline(self, group_id, *, limit=50, offset=0, item_id=None):
        with self.database.session() as session:
            group = session.get(Group, group_id)
            if not group or group.status != "active":
                raise ConversationGroupError("group_not_found", "会话组不存在或已取消")
            view = self.view(session, group)
            # Recheck identities; do not trust membership after an identity reassignment.
            allowed = {r.id for r in self.candidate_rows(session, group.customer_id)}
            if not set(view["conversation_ids"]) <= allowed:
                raise ConversationGroupError("customer_identity_mismatch", "客户身份关系已变化，请重新确认")
            criteria = [Message.conversation_id.in_(view["conversation_ids"])]
            if item_id is not None:
                item = session.get(Item, item_id)
                criteria.append(Message.source_item_external_id == (item.external_id if item else ""))
            total = session.scalar(select(func.count(Message.id)).where(*criteria)) or 0
            rows = list(session.scalars(select(Message).where(*criteria)
                .order_by(Message.received_at, Message.id).offset(offset).limit(limit)))
            messages = [{"id": r.id, "conversation_id": r.conversation_id, "direction": r.direction,
                         "message_type": r.message_type, "content": r.content, "received_at": r.received_at.isoformat(),
                         "sender_name": r.sender_name, "source_item_external_id": r.source_item_external_id,
                         "source_status": "known" if r.source_item_external_id else "unknown"} for r in rows]
            from .customer_images import CustomerImageArchiveService
            archives = list(session.scalars(select(CustomerImageArchive).where(
                CustomerImageArchive.message_id.in_([r.id for r in rows]), CustomerImageArchive.deleted_at.is_(None))
                .order_by(CustomerImageArchive.message_id, CustomerImageArchive.media_index)))
            images = [CustomerImageArchiveService._view(r, session.get(Conversation, r.conversation_id).customer_name) for r in archives]
            for message in messages:
                source = session.scalar(select(Item).where(Item.external_id == message["source_item_external_id"])) if message["source_item_external_id"] else None
                message["source_item_title"] = source.title if source else None
                message["images"] = [i for i in images if i["message_id"] == message["id"]]
        return {"messages": messages, "images": images, "total_count": total, "has_more": offset+len(messages)<total,
                "revision": view["revision"], "conversation_ids": view["conversation_ids"]}


def grant_conversation_scope(session, grant):
    """Revalidate every read; return only the immutable user-selected member set."""
    scope = session.get(GroupScope, grant.id)
    if not scope:
        return [grant.conversation_id], None
    group = session.get(Group, scope.group_id)
    ids = json.loads(scope.conversation_ids_json)
    members = set(session.scalars(select(Member.conversation_id).where(Member.group_id == scope.group_id, Member.active.is_(True))))
    if not group or group.status != "active" or not set(ids) <= members:
        raise ConversationGroupError("group_scope_changed", "会话组范围已撤销，请重新授权")
    allowed = {r.id for r in CustomerConversationGroupService.candidate_rows(session, group.customer_id)}
    if not set(ids) <= allowed:
        raise ConversationGroupError("group_scope_changed", "客户身份关联已变化，请重新授权")
    return ids, {"group_id": group.id, "group_revision": scope.group_revision,
                 "current_group_revision": group.revision}
