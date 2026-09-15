from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import Database
from ..ledger import canonical_json
from ..models import (
    Conversation,
    CustomerContextAccessAudit,
    CustomerContextGrant,
    CustomerContextMutationRequest,
    CustomerContextOAuthBinding,
    CustomerContextThreadBinding,
    CustomerContextTunnelBinding,
    GlobalAgentThread,
    utcnow,
)
from .customer_context_oauth import CustomerContextOAuthIdentity
from ..customer_conversation_models import CustomerContextGroupScope, CustomerConversationGroup
from .customer_conversation_groups import (
    CustomerConversationGroupService, ConversationGroupError, grant_conversation_scope,
)


class CustomerContextGatewayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CustomerContextGateway:
    """Permission boundary for customer text/image context.

    This service never reads message text or image bytes.  It only grants a
    short-lived, conversation-bound capability and persists sanitized access receipts.
    Content assembly lives behind the validated capability in dedicated readers.
    """

    CREATE_OPERATION = "customer_context_grant_create"
    DIRECT_CREATE_OPERATION = "customer_conversation_grant_create"
    REVOKE_OPERATION = "customer_context_grant_revoke"
    TUNNEL_BIND_OPERATION = "customer_context_tunnel_bind"
    TUNNEL_REVOKE_OPERATION = "customer_context_tunnel_revoke"
    THREAD_BIND_OPERATION = "customer_context_thread_bind"
    THREAD_REVOKE_OPERATION = "customer_context_thread_revoke"
    PROVIDER_SCOPE = "openai"
    ALLOWED_AUDIENCES = frozenset({"openai_chatgpt", "openai_api", "codex_cli"})
    ALLOWED_SCOPES = frozenset({"text", "images", "artifact"})
    ALLOWED_TOOLS = frozenset(
        {
            "customer_context_confirm",
            "requirement_blueprint_preview",
            "requirement_blueprint_confirm",
            "customer_context_text",
            "customer_context_image_manifest",
            "customer_context_image_read",
            "customer_requirement_artifact",
            "customer_analysis_status",
        }
    )
    MIN_TTL_SECONDS = 60
    MAX_TTL_SECONDS = 7 * 24 * 60 * 60
    DIRECT_THREAD_STATUS = "external_context_access"
    TUNNEL_SLOT = "openai_chatgpt"
    THREAD_AUTH_MODES = frozenset({"oauth", "tunnel_binding"})

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _begin_mutation(session: Session) -> None:
        if session.bind is not None and session.bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _loads(value: str, fallback: Any) -> Any:
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _mutation_result(
        cls,
        session: Session,
        *,
        request_id: str,
        operation: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        row = session.get(CustomerContextMutationRequest, request_id)
        if row is None:
            return None
        if row.operation != operation or not secrets.compare_digest(
            row.payload_hash, payload_hash
        ):
            raise CustomerContextGatewayError(
                "request_id_reused",
                "该请求编号已经用于不同的客户上下文授权操作",
            )
        result = cls._loads(row.result_json, None)
        if not isinstance(result, dict):
            raise CustomerContextGatewayError(
                "request_record_invalid", "历史授权请求记录无法校验"
            )
        return result

    @staticmethod
    def _save_mutation(
        session: Session,
        *,
        request_id: str,
        operation: str,
        payload_hash: str,
        result: dict[str, Any],
    ) -> None:
        safe_result = json.loads(
            json.dumps(
                result,
                ensure_ascii=False,
                default=lambda value: (
                    value.isoformat() if isinstance(value, datetime) else str(value)
                ),
            )
        )
        session.add(
            CustomerContextMutationRequest(
                request_id=request_id,
                operation=operation,
                payload_hash=payload_hash,
                result_json=canonical_json(safe_result),
            )
        )

    @classmethod
    def _effective_status(
        cls, grant: CustomerContextGrant, *, now: datetime | None = None
    ) -> str:
        if grant.status != "active":
            return grant.status
        if cls._aware(grant.expires_at) <= (now or utcnow()):
            return "expired"
        return "active"

    @classmethod
    def _grant_view(
        cls, grant: CustomerContextGrant, *, thread_revision: int
    ) -> dict[str, Any]:
        return {
            "id": grant.id,
            "thread_id": grant.thread_id,
            "conversation_id": grant.conversation_id,
            "provider_scope": grant.provider_scope,
            "audience": grant.audience,
            "allow_text": grant.allow_text,
            "allow_images": grant.allow_images,
            "allow_artifacts": grant.allow_artifacts,
            "allow_new_messages": grant.allow_new_messages,
            "consent_policy_version": grant.consent_policy_version,
            "consent_text_hash": grant.consent_text_hash,
            "status": cls._effective_status(grant),
            "revision": grant.revision,
            "thread_revision": thread_revision,
            "authorization_note": grant.authorization_note,
            "confirmed_at": grant.confirmed_at,
            "expires_at": grant.expires_at,
            "revoked_at": grant.revoked_at,
            "created_at": grant.created_at,
            "updated_at": grant.updated_at,
        }

    @staticmethod
    def _audit_view(row: CustomerContextAccessAudit) -> dict[str, Any]:
        return {
            "id": row.id,
            "request_id": row.request_id,
            "grant_id": row.grant_id,
            "grant_revision": row.grant_revision,
            "thread_id": row.thread_id,
            "conversation_id": row.conversation_id,
            "provider": row.provider,
            "audience": row.audience,
            "target_model": row.target_model,
            "tool_name": row.tool_name,
            "requested_scopes": CustomerContextGateway._loads(
                row.requested_scopes_json, []
            ),
            "status": row.status,
            "request_hash": row.request_hash,
            "summary_version": row.summary_version,
            "watermark_before": row.watermark_before,
            "watermark_after": row.watermark_after,
            "text_message_count": row.text_message_count,
            "image_count": row.image_count,
            "byte_count": row.byte_count,
            "resource_hashes": CustomerContextGateway._loads(
                row.resource_hashes_json, []
            ),
            "source_hash": row.source_hash,
            "error_code": row.error_code,
            "duration_ms": row.duration_ms,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
        }

    @staticmethod
    def _bound_thread(
        session: Session, *, thread_id: str, expected_revision: int | None = None
    ) -> GlobalAgentThread:
        thread = session.get(GlobalAgentThread, thread_id)
        if thread is None or thread.status not in {
            "active",
            CustomerContextGateway.DIRECT_THREAD_STATUS,
        }:
            raise CustomerContextGatewayError("thread_not_found", "授权上下文不存在或已停用")
        if expected_revision is not None and thread.revision != expected_revision:
            raise CustomerContextGatewayError(
                "thread_revision_conflict", "授权上下文已变化，请刷新后重新授权"
            )
        if thread.context_scope != "customer_conversation" or not thread.conversation_id:
            raise CustomerContextGatewayError(
                "conversation_not_bound", "授权上下文尚未绑定客户会话"
            )
        if session.get(Conversation, thread.conversation_id) is None:
            raise CustomerContextGatewayError(
                "conversation_not_found", "绑定的客户会话不存在"
            )
        return thread

    @staticmethod
    def _direct_thread_id(conversation_id: int) -> str:
        return f"external-context-access-{conversation_id}"

    @classmethod
    def _validate_grant_input(
        cls,
        *,
        provider_scope: str,
        audience: str,
        allow_text: bool,
        allow_images: bool,
        allow_artifacts: bool,
        expires_in_seconds: int,
    ) -> None:
        if provider_scope != cls.PROVIDER_SCOPE:
            raise CustomerContextGatewayError(
                "provider_not_allowed", "客户上下文只允许发送给已授权的 OpenAI 路径"
            )
        if audience not in cls.ALLOWED_AUDIENCES:
            raise CustomerContextGatewayError(
                "audience_not_allowed", "客户上下文授权受众无效"
            )
        if not allow_text and not allow_images and not allow_artifacts:
            raise CustomerContextGatewayError(
                "empty_scope", "至少需要授权文字、图片或需求成果中的一项"
            )
        if not cls.MIN_TTL_SECONDS <= expires_in_seconds <= cls.MAX_TTL_SECONDS:
            raise CustomerContextGatewayError(
                "invalid_expiry", "授权有效期必须在 1 分钟到 7 天之间"
            )

    def create_grant(
        self,
        *,
        thread_id: str,
        request_id: str,
        expected_revision: int,
        allow_text: bool,
        allow_images: bool,
        expires_in_seconds: int,
        authorization_note: str,
        audience: str,
        allow_artifacts: bool = True,
        allow_new_messages: bool = True,
        provider_scope: str = PROVIDER_SCOPE,
    ) -> dict[str, Any]:
        self._validate_grant_input(
            provider_scope=provider_scope,
            audience=audience,
            allow_text=allow_text,
            allow_images=allow_images,
            allow_artifacts=allow_artifacts,
            expires_in_seconds=expires_in_seconds,
        )
        payload = {
            "thread_id": thread_id,
            "expected_revision": expected_revision,
            "provider_scope": provider_scope,
            "audience": audience,
            "allow_text": allow_text,
            "allow_images": allow_images,
            "allow_artifacts": allow_artifacts,
            "allow_new_messages": allow_new_messages,
            "expires_in_seconds": expires_in_seconds,
            "authorization_note": authorization_note,
        }
        payload_hash = self._hash(payload)
        with self.database.session() as session:
            self._begin_mutation(session)
            repeated = self._mutation_result(
                session,
                request_id=request_id,
                operation=self.CREATE_OPERATION,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                return {**repeated, "capability_token": None, "idempotent": True}

            thread = self._bound_thread(
                session, thread_id=thread_id, expected_revision=expected_revision
            )
            now = utcnow()
            for existing in session.scalars(
                select(CustomerContextGrant).where(
                    CustomerContextGrant.thread_id == thread_id,
                    CustomerContextGrant.status == "active",
                )
            ):
                existing.status = "revoked"
                existing.revoked_at = now
                existing.updated_at = now
            thread.revision += 1
            thread.updated_at = now
            capability_token = secrets.token_urlsafe(32)
            grant = CustomerContextGrant(
                id=f"context-grant-{uuid4().hex}",
                thread_id=thread_id,
                conversation_id=int(thread.conversation_id),
                provider_scope=provider_scope,
                audience=audience,
                token_hash=hashlib.sha256(capability_token.encode("utf-8")).hexdigest(),
                allow_text=allow_text,
                allow_images=allow_images,
                allow_artifacts=allow_artifacts,
                allow_new_messages=allow_new_messages,
                consent_policy_version="1",
                consent_text_hash=hashlib.sha256(
                    authorization_note.encode("utf-8")
                ).hexdigest(),
                status="active",
                revision=thread.revision,
                authorization_note=authorization_note,
                confirmed_at=now,
                expires_at=now + timedelta(seconds=expires_in_seconds),
                created_at=now,
                updated_at=now,
            )
            session.add(grant)
            session.flush()
            result = self._grant_view(grant, thread_revision=thread.revision)
            self._save_mutation(
                session,
                request_id=request_id,
                operation=self.CREATE_OPERATION,
                payload_hash=payload_hash,
                result=result,
            )
            session.commit()
            return {
                **result,
                "capability_token": capability_token,
                "idempotent": False,
            }

    def conversation_access_state(self, conversation_id: int) -> dict[str, Any]:
        """Read direct ChatGPT access state without creating a thread or grant."""

        with self.database.session() as session:
            if session.get(Conversation, conversation_id) is None:
                raise CustomerContextGatewayError(
                    "conversation_not_found", "客户会话不存在"
                )
            thread = session.get(
                GlobalAgentThread, self._direct_thread_id(conversation_id)
            )
            if thread is None:
                return {
                    "conversation_id": conversation_id,
                    "revision": 0,
                    "latest_grant": None,
                }
            if (
                thread.status != self.DIRECT_THREAD_STATUS
                or thread.context_scope != "customer_conversation"
                or thread.conversation_id != conversation_id
            ):
                raise CustomerContextGatewayError(
                    "binding_changed", "客户会话外部读取授权状态无法校验"
                )
            grant = session.scalar(
                select(CustomerContextGrant)
                .where(CustomerContextGrant.thread_id == thread.id)
                .order_by(CustomerContextGrant.created_at.desc())
                .limit(1)
            )
            return {
                "conversation_id": conversation_id,
                "revision": thread.revision,
                "latest_grant": (
                    self._grant_view(grant, thread_revision=thread.revision)
                    if grant is not None
                    else None
                ),
            }

    def create_conversation_grant(
        self,
        *,
        conversation_id: int,
        request_id: str,
        expected_revision: int,
        allow_text: bool,
        allow_images: bool,
        expires_in_seconds: int,
        authorization_note: str,
        audience: str,
        allow_artifacts: bool = True,
        allow_new_messages: bool = True,
        provider_scope: str = PROVIDER_SCOPE,
    ) -> dict[str, Any]:
        """Create a conversation-bound capability without any Agent/model run."""

        self._validate_grant_input(
            provider_scope=provider_scope,
            audience=audience,
            allow_text=allow_text,
            allow_images=allow_images,
            allow_artifacts=allow_artifacts,
            expires_in_seconds=expires_in_seconds,
        )
        payload = {
            "conversation_id": conversation_id,
            "expected_revision": expected_revision,
            "provider_scope": provider_scope,
            "audience": audience,
            "allow_text": allow_text,
            "allow_images": allow_images,
            "allow_artifacts": allow_artifacts,
            "allow_new_messages": allow_new_messages,
            "expires_in_seconds": expires_in_seconds,
            "authorization_note": authorization_note,
        }
        payload_hash = self._hash(payload)
        with self.database.session() as session:
            self._begin_mutation(session)
            repeated = self._mutation_result(
                session,
                request_id=request_id,
                operation=self.DIRECT_CREATE_OPERATION,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                return {**repeated, "capability_token": None, "idempotent": True}
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise CustomerContextGatewayError(
                    "conversation_not_found", "客户会话不存在"
                )
            thread_id = self._direct_thread_id(conversation_id)
            thread = session.get(GlobalAgentThread, thread_id)
            if thread is None:
                if expected_revision != 0:
                    raise CustomerContextGatewayError(
                        "conversation_revision_conflict",
                        "客户会话授权状态已变化，请刷新后重试",
                    )
                now = utcnow()
                thread = GlobalAgentThread(
                    id=thread_id,
                    title="ChatGPT 客户会话只读授权",
                    profile_id=None,
                    provider="openai",
                    model="mcp-read-only",
                    reasoning_effort="",
                    context_scope="customer_conversation",
                    conversation_id=conversation_id,
                    customer_id=None,
                    status=self.DIRECT_THREAD_STATUS,
                    revision=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(thread)
                session.flush()
            elif (
                thread.status != self.DIRECT_THREAD_STATUS
                or thread.context_scope != "customer_conversation"
                or thread.conversation_id != conversation_id
            ):
                raise CustomerContextGatewayError(
                    "binding_changed", "客户会话外部读取授权状态无法校验"
                )
            elif thread.revision != expected_revision:
                raise CustomerContextGatewayError(
                    "conversation_revision_conflict",
                    "客户会话授权状态已变化，请刷新后重试",
                )
            now = utcnow()
            for existing in session.scalars(
                select(CustomerContextGrant).where(
                    CustomerContextGrant.thread_id == thread.id,
                    CustomerContextGrant.status == "active",
                )
            ):
                existing.status = "revoked"
                existing.revoked_at = now
                existing.updated_at = now
            thread.revision += 1
            thread.updated_at = now
            capability_token = secrets.token_urlsafe(32)
            grant = CustomerContextGrant(
                id=f"context-grant-{uuid4().hex}",
                thread_id=thread.id,
                conversation_id=conversation_id,
                provider_scope=provider_scope,
                audience=audience,
                token_hash=hashlib.sha256(capability_token.encode("utf-8")).hexdigest(),
                allow_text=allow_text,
                allow_images=allow_images,
                allow_artifacts=allow_artifacts,
                allow_new_messages=allow_new_messages,
                consent_policy_version="2",
                consent_text_hash=hashlib.sha256(
                    authorization_note.encode("utf-8")
                ).hexdigest(),
                status="active",
                revision=thread.revision,
                authorization_note=authorization_note,
                confirmed_at=now,
                expires_at=now + timedelta(seconds=expires_in_seconds),
                created_at=now,
                updated_at=now,
            )
            session.add(grant)
            session.flush()
            result = self._grant_view(grant, thread_revision=thread.revision)
            self._save_mutation(
                session,
                request_id=request_id,
                operation=self.DIRECT_CREATE_OPERATION,
                payload_hash=payload_hash,
                result=result,
            )
            session.commit()
            return {
                **result,
                "capability_token": capability_token,
                "idempotent": False,
            }

    @classmethod
    def _tunnel_binding_view(
        cls,
        session: Session,
        binding: CustomerContextTunnelBinding | None,
    ) -> dict[str, Any]:
        if binding is None:
            return {
                "slot": cls.TUNNEL_SLOT,
                "revision": 0,
                "active": False,
                "grant": None,
            }
        grant = session.get(CustomerContextGrant, binding.grant_id)
        thread = session.get(GlobalAgentThread, grant.thread_id) if grant else None
        active = bool(
            grant is not None
            and cls._effective_status(grant) == "active"
            and thread is not None
            and thread.status == cls.DIRECT_THREAD_STATUS
            and thread.context_scope == "customer_conversation"
            and thread.conversation_id == grant.conversation_id
            and thread.revision == grant.revision
        )
        return {
            "slot": binding.slot,
            "revision": binding.revision,
            "active": active,
            "grant": (
                cls._grant_view(grant, thread_revision=thread.revision)
                if grant is not None and thread is not None
                else None
            ),
        }

    def tunnel_binding_state(self) -> dict[str, Any]:
        """Read the single ChatGPT tunnel binding without changing expiry state."""

        with self.database.session() as session:
            binding = session.get(CustomerContextTunnelBinding, self.TUNNEL_SLOT)
            return self._tunnel_binding_view(session, binding)

    def replace_tunnel_binding(
        self,
        *,
        conversation_id: int,
        request_id: str,
        expected_binding_revision: int,
        expected_conversation_revision: int,
        allow_text: bool,
        allow_images: bool,
        allow_artifacts: bool,
        allow_new_messages: bool,
        expires_in_seconds: int,
        authorization_note: str,
    ) -> dict[str, Any]:
        """Atomically create a grant and make it the only tunnel-visible grant."""

        self._validate_grant_input(
            provider_scope=self.PROVIDER_SCOPE,
            audience=self.TUNNEL_SLOT,
            allow_text=allow_text,
            allow_images=allow_images,
            allow_artifacts=allow_artifacts,
            expires_in_seconds=expires_in_seconds,
        )
        payload = {
            "conversation_id": conversation_id,
            "expected_binding_revision": expected_binding_revision,
            "expected_conversation_revision": expected_conversation_revision,
            "allow_text": allow_text,
            "allow_images": allow_images,
            "allow_artifacts": allow_artifacts,
            "allow_new_messages": allow_new_messages,
            "expires_in_seconds": expires_in_seconds,
            "authorization_note": authorization_note,
        }
        payload_hash = self._hash(payload)
        with self.database.session() as session:
            self._begin_mutation(session)
            repeated = self._mutation_result(
                session,
                request_id=request_id,
                operation=self.TUNNEL_BIND_OPERATION,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                return {**repeated, "idempotent": True}
            binding = session.get(CustomerContextTunnelBinding, self.TUNNEL_SLOT)
            current_binding_revision = binding.revision if binding is not None else 0
            if current_binding_revision != expected_binding_revision:
                raise CustomerContextGatewayError(
                    "tunnel_binding_revision_conflict",
                    "ChatGPT Tunnel 授权已变化，请刷新后重试",
                )
            if session.get(Conversation, conversation_id) is None:
                raise CustomerContextGatewayError(
                    "conversation_not_found", "客户会话不存在"
                )
            thread_id = self._direct_thread_id(conversation_id)
            thread = session.get(GlobalAgentThread, thread_id)
            now = utcnow()
            if thread is None:
                if expected_conversation_revision != 0:
                    raise CustomerContextGatewayError(
                        "conversation_revision_conflict",
                        "客户会话授权状态已变化，请刷新后重试",
                    )
                thread = GlobalAgentThread(
                    id=thread_id,
                    title="ChatGPT 客户会话只读授权",
                    profile_id=None,
                    provider="openai",
                    model="mcp-read-only",
                    reasoning_effort="",
                    context_scope="customer_conversation",
                    conversation_id=conversation_id,
                    customer_id=None,
                    status=self.DIRECT_THREAD_STATUS,
                    revision=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(thread)
                session.flush()
            elif (
                thread.status != self.DIRECT_THREAD_STATUS
                or thread.context_scope != "customer_conversation"
                or thread.conversation_id != conversation_id
            ):
                raise CustomerContextGatewayError(
                    "binding_changed", "客户会话外部读取授权状态无法校验"
                )
            elif thread.revision != expected_conversation_revision:
                raise CustomerContextGatewayError(
                    "conversation_revision_conflict",
                    "客户会话授权状态已变化，请刷新后重试",
                )

            previous_grant = (
                session.get(CustomerContextGrant, binding.grant_id)
                if binding is not None
                else None
            )
            if (
                previous_grant is not None
                and previous_grant.thread_id != thread.id
                and previous_grant.status == "active"
            ):
                previous_grant.status = "revoked"
                previous_grant.revoked_at = now
                previous_grant.updated_at = now
                previous_thread = session.get(
                    GlobalAgentThread, previous_grant.thread_id
                )
                if previous_thread is not None:
                    previous_thread.revision += 1
                    previous_thread.updated_at = now
            for existing in session.scalars(
                select(CustomerContextGrant).where(
                    CustomerContextGrant.thread_id == thread.id,
                    CustomerContextGrant.status == "active",
                )
            ):
                existing.status = "revoked"
                existing.revoked_at = now
                existing.updated_at = now

            thread.revision += 1
            thread.updated_at = now
            discarded_token = secrets.token_urlsafe(32)
            grant = CustomerContextGrant(
                id=f"context-grant-{uuid4().hex}",
                thread_id=thread.id,
                conversation_id=conversation_id,
                provider_scope=self.PROVIDER_SCOPE,
                audience=self.TUNNEL_SLOT,
                token_hash=hashlib.sha256(discarded_token.encode("utf-8")).hexdigest(),
                allow_text=allow_text,
                allow_images=allow_images,
                allow_artifacts=allow_artifacts,
                allow_new_messages=allow_new_messages,
                consent_policy_version="3",
                consent_text_hash=hashlib.sha256(
                    authorization_note.encode("utf-8")
                ).hexdigest(),
                status="active",
                revision=thread.revision,
                authorization_note=authorization_note,
                confirmed_at=now,
                expires_at=now + timedelta(seconds=expires_in_seconds),
                created_at=now,
                updated_at=now,
            )
            session.add(grant)
            session.flush()
            if binding is None:
                binding = CustomerContextTunnelBinding(
                    slot=self.TUNNEL_SLOT,
                    grant_id=grant.id,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(binding)
            else:
                binding.grant_id = grant.id
                binding.revision += 1
                binding.updated_at = now
            session.flush()
            result = self._tunnel_binding_view(session, binding)
            self._save_mutation(
                session,
                request_id=request_id,
                operation=self.TUNNEL_BIND_OPERATION,
                payload_hash=payload_hash,
                result=result,
            )
            session.commit()
            return {**result, "idempotent": False}

    def revoke_tunnel_binding(
        self,
        *,
        request_id: str,
        expected_binding_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        payload = {
            "expected_binding_revision": expected_binding_revision,
            "reason": reason,
        }
        payload_hash = self._hash(payload)
        with self.database.session() as session:
            self._begin_mutation(session)
            repeated = self._mutation_result(
                session,
                request_id=request_id,
                operation=self.TUNNEL_REVOKE_OPERATION,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                return {**repeated, "idempotent": True}
            binding = session.get(CustomerContextTunnelBinding, self.TUNNEL_SLOT)
            if binding is None:
                raise CustomerContextGatewayError(
                    "tunnel_binding_not_found", "ChatGPT Tunnel 尚未绑定客户会话"
                )
            if binding.revision != expected_binding_revision:
                raise CustomerContextGatewayError(
                    "tunnel_binding_revision_conflict",
                    "ChatGPT Tunnel 授权已变化，请刷新后重试",
                )
            grant = session.get(CustomerContextGrant, binding.grant_id)
            thread = self._validate_bound_grant(session, grant)
            now = utcnow()
            grant.status = "revoked"
            grant.revoked_at = now
            grant.updated_at = now
            grant.authorization_note = f"{grant.authorization_note}\n撤销原因：{reason}".strip()
            thread.revision += 1
            thread.updated_at = now
            binding.revision += 1
            binding.updated_at = now
            result = self._tunnel_binding_view(session, binding)
            self._save_mutation(
                session,
                request_id=request_id,
                operation=self.TUNNEL_REVOKE_OPERATION,
                payload_hash=payload_hash,
                result=result,
            )
            session.commit()
            return {**result, "idempotent": False}

    def resolve_active_tunnel_binding(self) -> dict[str, Any]:
        """Resolve the current local binding after transport authentication."""

        with self.database.session() as session:
            binding = session.get(CustomerContextTunnelBinding, self.TUNNEL_SLOT)
            if binding is None:
                raise CustomerContextGatewayError(
                    "tunnel_binding_not_found", "ChatGPT Tunnel 尚未绑定客户会话"
                )
            grant = session.get(CustomerContextGrant, binding.grant_id)
            thread = self._validate_bound_grant(session, grant)
            return self._grant_view(grant, thread_revision=thread.revision)

    @classmethod
    def _thread_binding_view(
        cls,
        session: Session,
        binding: CustomerContextThreadBinding,
    ) -> dict[str, Any]:
        grant = session.get(CustomerContextGrant, binding.grant_id)
        thread = session.get(GlobalAgentThread, grant.thread_id) if grant else None
        group_scope = session.get(CustomerContextGroupScope, grant.id) if grant else None
        current = utcnow()
        active = bool(
            binding.status == "active"
            and cls._aware(binding.expires_at) > current
            and grant is not None
            and cls._effective_status(grant, now=current) == "active"
            and thread is not None
            and thread.status == cls.DIRECT_THREAD_STATUS
            and thread.context_scope == "customer_conversation"
            and thread.conversation_id == grant.conversation_id
            and thread.revision == grant.revision
        )
        effective_status = binding.status
        if effective_status == "active" and not active:
            effective_status = (
                "expired"
                if cls._aware(binding.expires_at) <= current
                or (grant is not None and cls._effective_status(grant, now=current) == "expired")
                else "revoked"
            )
        return {
            "id": binding.id,
            "auth_mode": binding.auth_mode,
            "context_key_hint": binding.context_key_hint,
            "group_id": group_scope.group_id if group_scope else None,
            "group_revision": group_scope.group_revision if group_scope else None,
            "selected_conversation_ids": json.loads(group_scope.conversation_ids_json) if group_scope else None,
            "status": effective_status,
            "revision": binding.revision,
            "active": active,
            "identity_claimed": bool(binding.owner_subject_hash),
            "expires_at": binding.expires_at,
            "revoked_at": binding.revoked_at,
            "last_used_at": binding.last_used_at,
            "created_at": binding.created_at,
            "updated_at": binding.updated_at,
            "grant": (
                cls._grant_view(grant, thread_revision=thread.revision)
                if grant is not None and thread is not None
                else None
            ),
        }

    def list_thread_bindings(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """List sanitized per-thread bindings without replaying context keys."""

        with self.database.session() as session:
            rows = session.scalars(
                select(CustomerContextThreadBinding)
                .order_by(CustomerContextThreadBinding.created_at.desc())
                .limit(max(1, min(limit, 200)))
            )
            return [self._thread_binding_view(session, row) for row in rows]

    def has_active_thread_bindings(self, *, auth_mode: str) -> bool:
        """Return whether keyed bindings now own selection for this auth mode."""

        if auth_mode not in self.THREAD_AUTH_MODES:
            return False
        with self.database.session() as session:
            rows = session.scalars(
                select(CustomerContextThreadBinding).where(
                    CustomerContextThreadBinding.auth_mode == auth_mode,
                    CustomerContextThreadBinding.status == "active",
                    CustomerContextThreadBinding.expires_at > utcnow(),
                )
            )
            return any(self._thread_binding_view(session, row)["active"] for row in rows)

    def create_thread_binding(
        self,
        *,
        conversation_id: int,
        request_id: str,
        expected_conversation_revision: int,
        auth_mode: str,
        allow_text: bool,
        allow_images: bool,
        allow_artifacts: bool,
        allow_new_messages: bool,
        expires_in_seconds: int,
        authorization_note: str,
        group_id: str | None = None,
        expected_group_revision: int | None = None,
        selected_conversation_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Create one opaque key for one ChatGPT conversation context.

        The raw key is returned once and only its SHA-256 digest is persisted.
        Creating a replacement for the same customer revokes that customer's old
        key, but leaves other customer bindings active.
        """

        if auth_mode not in self.THREAD_AUTH_MODES:
            raise CustomerContextGatewayError(
                "thread_auth_mode_invalid", "ChatGPT 线程授权模式无效"
            )
        self._validate_grant_input(
            provider_scope=self.PROVIDER_SCOPE,
            audience="openai_chatgpt",
            allow_text=allow_text,
            allow_images=allow_images,
            allow_artifacts=allow_artifacts,
            expires_in_seconds=expires_in_seconds,
        )
        payload = {
            "conversation_id": conversation_id,
            "expected_conversation_revision": expected_conversation_revision,
            "auth_mode": auth_mode,
            "allow_text": allow_text,
            "allow_images": allow_images,
            "allow_artifacts": allow_artifacts,
            "allow_new_messages": allow_new_messages,
            "expires_in_seconds": expires_in_seconds,
            "authorization_note": authorization_note,
        }
        payload.update(group_id=group_id, expected_group_revision=expected_group_revision,
                       selected_conversation_ids=sorted(selected_conversation_ids or []))
        payload_hash = self._hash(payload)
        with self.database.session() as session:
            self._begin_mutation(session)
            repeated = self._mutation_result(
                session,
                request_id=request_id,
                operation=self.THREAD_BIND_OPERATION,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                return {**repeated, "context_key": None, "idempotent": True}
            if session.get(Conversation, conversation_id) is None:
                raise CustomerContextGatewayError(
                    "conversation_not_found", "客户会话不存在"
                )
            selected_ids = sorted(selected_conversation_ids or [])
            if group_id:
                group = session.get(CustomerConversationGroup, group_id)
                if not group or group.status != "active" or group.revision != expected_group_revision:
                    raise CustomerContextGatewayError("group_revision_conflict", "会话组已变化，请刷新后重新授权")
                allowed = CustomerConversationGroupService.view(session, group)["conversation_ids"]
                if (not selected_ids or conversation_id not in selected_ids
                    or len(selected_ids) != len(set(selected_ids)) or not set(selected_ids) <= set(allowed)):
                    raise CustomerContextGatewayError("group_scope_invalid", "请明确选择该会话组内的授权成员")
                try:
                    candidate_ids = {r.id for r in CustomerConversationGroupService.candidate_rows(session, group.customer_id)}
                    if not set(selected_ids) <= candidate_ids:
                        raise ConversationGroupError("group_scope_invalid", "客户身份关系已变化")
                except ConversationGroupError as exc:
                    raise CustomerContextGatewayError(exc.code, str(exc)) from None
            elif selected_conversation_ids is not None or expected_group_revision is not None:
                raise CustomerContextGatewayError("group_scope_invalid", "多会话授权必须指定已确认的会话组")
            thread_id = self._direct_thread_id(conversation_id)
            thread = session.get(GlobalAgentThread, thread_id)
            now = utcnow()
            if thread is None:
                if expected_conversation_revision != 0:
                    raise CustomerContextGatewayError(
                        "conversation_revision_conflict",
                        "客户会话授权状态已变化，请刷新后重试",
                    )
                thread = GlobalAgentThread(
                    id=thread_id,
                    title="ChatGPT 客户会话只读授权",
                    profile_id=None,
                    provider="openai",
                    model="mcp-read-only",
                    reasoning_effort="",
                    context_scope="customer_conversation",
                    conversation_id=conversation_id,
                    customer_id=None,
                    status=self.DIRECT_THREAD_STATUS,
                    revision=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(thread)
                session.flush()
            elif (
                thread.status != self.DIRECT_THREAD_STATUS
                or thread.context_scope != "customer_conversation"
                or thread.conversation_id != conversation_id
            ):
                raise CustomerContextGatewayError(
                    "binding_changed", "客户会话外部读取授权状态无法校验"
                )
            elif thread.revision != expected_conversation_revision:
                raise CustomerContextGatewayError(
                    "conversation_revision_conflict",
                    "客户会话授权状态已变化，请刷新后重试",
                )

            previous_bindings = list(
                session.scalars(
                    select(CustomerContextThreadBinding)
                    .join(
                        CustomerContextGrant,
                        CustomerContextGrant.id
                        == CustomerContextThreadBinding.grant_id,
                    )
                    .where(
                        CustomerContextGrant.thread_id == thread.id,
                        CustomerContextThreadBinding.status == "active",
                    )
                )
            )
            for previous in previous_bindings:
                previous.status = "revoked"
                previous.revision += 1
                previous.revoked_at = now
                previous.updated_at = now
            for existing in session.scalars(
                select(CustomerContextGrant).where(
                    CustomerContextGrant.thread_id == thread.id,
                    CustomerContextGrant.status == "active",
                )
            ):
                existing.status = "revoked"
                existing.revoked_at = now
                existing.updated_at = now

            if auth_mode == "tunnel_binding":
                legacy_binding = session.get(
                    CustomerContextTunnelBinding, self.TUNNEL_SLOT
                )
                legacy_grant = (
                    session.get(CustomerContextGrant, legacy_binding.grant_id)
                    if legacy_binding is not None
                    else None
                )
                if (
                    legacy_binding is not None
                    and legacy_grant is not None
                    and legacy_grant.thread_id != thread.id
                    and legacy_grant.status == "active"
                ):
                    legacy_grant.status = "revoked"
                    legacy_grant.revoked_at = now
                    legacy_grant.updated_at = now
                    legacy_thread = session.get(
                        GlobalAgentThread, legacy_grant.thread_id
                    )
                    if (
                        legacy_thread is not None
                        and legacy_thread.revision == legacy_grant.revision
                    ):
                        legacy_thread.revision += 1
                        legacy_thread.updated_at = now
                    legacy_binding.revision += 1
                    legacy_binding.updated_at = now

            thread.revision += 1
            thread.updated_at = now
            expires_at = now + timedelta(seconds=expires_in_seconds)
            discarded_token = secrets.token_urlsafe(32)
            grant = CustomerContextGrant(
                id=f"context-grant-{uuid4().hex}",
                thread_id=thread.id,
                conversation_id=conversation_id,
                provider_scope=self.PROVIDER_SCOPE,
                audience="openai_chatgpt",
                token_hash=hashlib.sha256(discarded_token.encode("utf-8")).hexdigest(),
                allow_text=allow_text,
                allow_images=allow_images,
                allow_artifacts=allow_artifacts,
                allow_new_messages=allow_new_messages,
                consent_policy_version="4",
                consent_text_hash=hashlib.sha256(
                    authorization_note.encode("utf-8")
                ).hexdigest(),
                status="active",
                revision=thread.revision,
                authorization_note=authorization_note,
                confirmed_at=now,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            session.add(grant)
            session.flush()
            context_key = f"ctx_{secrets.token_urlsafe(32)}"
            binding = CustomerContextThreadBinding(
                id=f"context-thread-{uuid4().hex}",
                context_key_hash=hashlib.sha256(context_key.encode("utf-8")).hexdigest(),
                context_key_hint=f"…{context_key[-6:]}",
                grant_id=grant.id,
                auth_mode=auth_mode,
                status="active",
                revision=1,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            session.add(binding)
            session.flush()
            if group_id:
                session.add(CustomerContextGroupScope(grant_id=grant.id, group_id=group_id,
                    group_revision=expected_group_revision, conversation_ids_json=canonical_json(selected_ids)))
                session.flush()
            result = self._thread_binding_view(session, binding)
            self._save_mutation(
                session,
                request_id=request_id,
                operation=self.THREAD_BIND_OPERATION,
                payload_hash=payload_hash,
                result=result,
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise CustomerContextGatewayError(
                    "thread_binding_conflict", "ChatGPT 线程授权发生并发冲突"
                ) from exc
            return {
                **result,
                "context_key": context_key,
                "idempotent": False,
            }

    def revoke_thread_binding(
        self,
        binding_id: str,
        *,
        request_id: str,
        expected_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        payload = {
            "binding_id": binding_id,
            "expected_revision": expected_revision,
            "reason": reason,
        }
        payload_hash = self._hash(payload)
        with self.database.session() as session:
            self._begin_mutation(session)
            repeated = self._mutation_result(
                session,
                request_id=request_id,
                operation=self.THREAD_REVOKE_OPERATION,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                return {**repeated, "context_key": None, "idempotent": True}
            binding = session.get(CustomerContextThreadBinding, binding_id)
            if binding is None:
                raise CustomerContextGatewayError(
                    "thread_binding_not_found", "ChatGPT 线程授权不存在"
                )
            if binding.revision != expected_revision:
                raise CustomerContextGatewayError(
                    "thread_binding_revision_conflict",
                    "ChatGPT 线程授权已变化，请刷新后重试",
                )
            if binding.status != "active":
                raise CustomerContextGatewayError(
                    "thread_binding_not_active", "ChatGPT 线程授权已经失效"
                )
            now = utcnow()
            grant = session.get(CustomerContextGrant, binding.grant_id)
            thread = session.get(GlobalAgentThread, grant.thread_id) if grant else None
            binding.status = "revoked"
            binding.revision += 1
            binding.revoked_at = now
            binding.updated_at = now
            if grant is not None and grant.status == "active":
                grant.status = "revoked"
                grant.revoked_at = now
                grant.updated_at = now
                grant.authorization_note = (
                    f"{grant.authorization_note}\n撤销原因：{reason}".strip()
                )
                if thread is not None and thread.revision == grant.revision:
                    thread.revision += 1
                    thread.updated_at = now
            result = self._thread_binding_view(session, binding)
            self._save_mutation(
                session,
                request_id=request_id,
                operation=self.THREAD_REVOKE_OPERATION,
                payload_hash=payload_hash,
                result=result,
            )
            session.commit()
            return {**result, "context_key": None, "idempotent": False}

    def resolve_active_thread_binding(
        self,
        context_key: str,
        *,
        auth_mode: str,
        identity: CustomerContextOAuthIdentity | None = None,
    ) -> dict[str, Any]:
        """Resolve exactly one customer from an opaque per-thread context key."""

        if (
            len(context_key) < 36
            or len(context_key) > 128
            or not context_key.startswith("ctx_")
            or any(
                char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
                for char in context_key[4:]
            )
        ):
            raise CustomerContextGatewayError(
                "context_key_invalid", "ChatGPT 客户线程上下文密钥无效"
            )
        if auth_mode not in self.THREAD_AUTH_MODES:
            raise CustomerContextGatewayError(
                "thread_auth_mode_invalid", "ChatGPT 线程授权模式无效"
            )
        context_key_hash = hashlib.sha256(context_key.encode("utf-8")).hexdigest()
        with self.database.session() as session:
            self._begin_mutation(session)
            binding = session.scalar(
                select(CustomerContextThreadBinding).where(
                    CustomerContextThreadBinding.context_key_hash == context_key_hash
                )
            )
            if binding is None:
                raise CustomerContextGatewayError(
                    "context_key_not_found", "ChatGPT 客户线程上下文密钥无效"
                )
            now = utcnow()
            if binding.auth_mode != auth_mode:
                raise CustomerContextGatewayError(
                    "context_key_auth_mismatch", "ChatGPT 客户线程授权模式不匹配"
                )
            if binding.status != "active" or self._aware(binding.expires_at) <= now:
                raise CustomerContextGatewayError(
                    "context_key_expired", "ChatGPT 客户线程上下文授权已失效"
                )
            grant = session.get(CustomerContextGrant, binding.grant_id)
            thread = self._validate_bound_grant(session, grant, now=now)
            if auth_mode == "oauth":
                if identity is None:
                    raise CustomerContextGatewayError(
                        "oauth_identity_required", "ChatGPT OAuth 身份缺失"
                    )
                subject_hash = self._identity_hash(identity.subject)
                client_id_hash = self._identity_hash(identity.client_id)
                if binding.owner_subject_hash is None:
                    binding.owner_issuer = identity.issuer
                    binding.owner_subject_hash = subject_hash
                    binding.owner_client_id_hash = client_id_hash
                elif (
                    binding.owner_issuer != identity.issuer
                    or not secrets.compare_digest(
                        binding.owner_subject_hash, subject_hash
                    )
                    or not binding.owner_client_id_hash
                    or not secrets.compare_digest(
                        binding.owner_client_id_hash, client_id_hash
                    )
                ):
                    raise CustomerContextGatewayError(
                        "context_key_owner_mismatch",
                        "ChatGPT 客户线程上下文不属于当前 OAuth 用户",
                    )
            elif identity is not None:
                raise CustomerContextGatewayError(
                    "context_key_auth_mismatch", "Tunnel 线程授权不接受 OAuth 身份"
                )
            binding.last_used_at = now
            binding.updated_at = now
            session.commit()
            return self._grant_view(grant, thread_revision=thread.revision)

    def revoke_grant(
        self,
        grant_id: str,
        *,
        request_id: str,
        expected_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        payload = {
            "grant_id": grant_id,
            "expected_revision": expected_revision,
            "reason": reason,
        }
        payload_hash = self._hash(payload)
        with self.database.session() as session:
            self._begin_mutation(session)
            repeated = self._mutation_result(
                session,
                request_id=request_id,
                operation=self.REVOKE_OPERATION,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                return {**repeated, "idempotent": True}
            grant = session.get(CustomerContextGrant, grant_id)
            if grant is None:
                raise CustomerContextGatewayError("grant_not_found", "客户上下文授权不存在")
            thread = self._bound_thread(
                session,
                thread_id=grant.thread_id,
                expected_revision=expected_revision,
            )
            if grant.status != "active":
                raise CustomerContextGatewayError(
                    "grant_not_active", "客户上下文授权已经失效"
                )
            now = utcnow()
            grant.status = "revoked"
            grant.revoked_at = now
            grant.updated_at = now
            grant.authorization_note = f"{grant.authorization_note}\n撤销原因：{reason}".strip()
            thread.revision += 1
            thread.updated_at = now
            result = self._grant_view(grant, thread_revision=thread.revision)
            self._save_mutation(
                session,
                request_id=request_id,
                operation=self.REVOKE_OPERATION,
                payload_hash=payload_hash,
                result=result,
            )
            session.commit()
            return {**result, "idempotent": False}

    def latest_grant(self, thread_id: str) -> dict[str, Any] | None:
        """Read-only view; expiration is computed and never written by GET."""

        with self.database.session() as session:
            thread = session.get(GlobalAgentThread, thread_id)
            if thread is None:
                raise CustomerContextGatewayError("thread_not_found", "小策对话不存在")
            grant = session.scalar(
                select(CustomerContextGrant)
                .where(CustomerContextGrant.thread_id == thread_id)
                .order_by(CustomerContextGrant.created_at.desc())
                .limit(1)
            )
            if grant is None:
                return None
            return self._grant_view(grant, thread_revision=thread.revision)

    @staticmethod
    def _identity_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _grant_for_token_hash(
        session: Session, token_hash: str
    ) -> tuple[CustomerContextGrant | None, CustomerContextOAuthBinding | None]:
        grant = session.scalar(
            select(CustomerContextGrant).where(
                CustomerContextGrant.token_hash == token_hash
            )
        )
        if grant is not None:
            return grant, None
        binding = session.scalar(
            select(CustomerContextOAuthBinding).where(
                CustomerContextOAuthBinding.token_hash == token_hash
            )
        )
        if binding is None:
            return None, None
        return session.get(CustomerContextGrant, binding.grant_id), binding

    @classmethod
    def _validate_bound_grant(
        cls,
        session: Session,
        grant: CustomerContextGrant | None,
        *,
        binding: CustomerContextOAuthBinding | None = None,
        now: datetime | None = None,
    ) -> GlobalAgentThread:
        current = now or utcnow()
        if grant is None:
            raise CustomerContextGatewayError(
                "grant_not_found", "客户上下文短时授权无效"
            )
        if cls._effective_status(grant, now=current) != "active":
            raise CustomerContextGatewayError(
                "grant_expired", "客户上下文短时授权已失效"
            )
        if binding is not None and cls._aware(binding.expires_at) <= current:
            raise CustomerContextGatewayError(
                "oauth_token_expired", "OAuth 授权已过期"
            )
        thread = session.get(GlobalAgentThread, grant.thread_id)
        if (
            thread is None
            or thread.status not in {"active", cls.DIRECT_THREAD_STATUS}
            or thread.context_scope != "customer_conversation"
            or thread.conversation_id != grant.conversation_id
            or thread.revision != grant.revision
        ):
            raise CustomerContextGatewayError(
                "binding_changed", "客户会话授权已经变化，请重新授权"
            )
        return thread

    def resolve_or_bind_oauth_capability(
        self,
        oauth_token: str,
        identity: CustomerContextOAuthIdentity,
        *,
        clock_skew_seconds: int = 60,
    ) -> dict[str, Any]:
        """Bind one verified OAuth token to the latest prior manual grant.

        A token can never inherit a later grant. Only token and identity hashes are
        persisted; customer content and raw external identities are not stored here.
        """

        token_hash = hashlib.sha256(oauth_token.encode("utf-8")).hexdigest()
        subject_hash = self._identity_hash(identity.subject)
        client_id_hash = self._identity_hash(identity.client_id)
        now = utcnow()
        with self.database.session() as session:
            self._begin_mutation(session)
            existing = session.scalar(
                select(CustomerContextOAuthBinding).where(
                    CustomerContextOAuthBinding.token_hash == token_hash
                )
            )
            if existing is not None:
                if (
                    existing.issuer != identity.issuer
                    or existing.audience != identity.audience
                    or not secrets.compare_digest(existing.subject_hash, subject_hash)
                    or not secrets.compare_digest(existing.client_id_hash, client_id_hash)
                ):
                    raise CustomerContextGatewayError(
                        "oauth_binding_mismatch", "OAuth 授权绑定无法校验"
                    )
                grant = session.get(CustomerContextGrant, existing.grant_id)
                thread = self._validate_bound_grant(
                    session, grant, binding=existing, now=now
                )
                existing.last_used_at = now
                session.commit()
                return self._grant_view(grant, thread_revision=thread.revision)

            cutoff = self._aware(identity.issued_at) + timedelta(
                seconds=max(0, clock_skew_seconds)
            )
            candidates = session.scalars(
                select(CustomerContextGrant)
                .where(
                    CustomerContextGrant.provider_scope == self.PROVIDER_SCOPE,
                    CustomerContextGrant.audience == "openai_chatgpt",
                    CustomerContextGrant.status == "active",
                    CustomerContextGrant.confirmed_at <= cutoff,
                    CustomerContextGrant.expires_at > now,
                )
                .order_by(CustomerContextGrant.confirmed_at.desc())
            )
            grant: CustomerContextGrant | None = None
            thread: GlobalAgentThread | None = None
            for candidate in candidates:
                candidate_thread = session.get(GlobalAgentThread, candidate.thread_id)
                if (
                    candidate_thread is not None
                    and candidate_thread.status == self.DIRECT_THREAD_STATUS
                    and candidate_thread.context_scope == "customer_conversation"
                    and candidate_thread.conversation_id == candidate.conversation_id
                    and candidate_thread.revision == candidate.revision
                ):
                    grant = candidate
                    thread = candidate_thread
                    break
            if grant is None or thread is None:
                raise CustomerContextGatewayError(
                    "oauth_grant_not_found",
                    "OAuth Token 签发前没有可绑定的循营客户会话授权",
                )
            binding = CustomerContextOAuthBinding(
                id=f"context-oauth-{uuid4().hex}",
                token_hash=token_hash,
                grant_id=grant.id,
                issuer=identity.issuer,
                audience=identity.audience,
                subject_hash=subject_hash,
                client_id_hash=client_id_hash,
                scopes_json=canonical_json(list(identity.scopes)),
                issued_at=self._aware(identity.issued_at),
                expires_at=self._aware(identity.expires_at),
                created_at=now,
                last_used_at=now,
            )
            session.add(binding)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                repeated = session.scalar(
                    select(CustomerContextOAuthBinding).where(
                        CustomerContextOAuthBinding.token_hash == token_hash
                    )
                )
                if repeated is None or repeated.grant_id != grant.id:
                    raise CustomerContextGatewayError(
                        "oauth_binding_conflict", "OAuth 授权绑定发生并发冲突"
                    ) from exc
            return self._grant_view(grant, thread_revision=thread.revision)

    def resolve_active_capability(self, capability_token: str) -> dict[str, Any]:
        """Read-only transport preflight; content access still requires an audit nonce."""

        token_hash = hashlib.sha256(capability_token.encode("utf-8")).hexdigest()
        with self.database.session() as session:
            grant, binding = self._grant_for_token_hash(session, token_hash)
            thread = self._validate_bound_grant(session, grant, binding=binding)
            return self._grant_view(grant, thread_revision=thread.revision)

    def _record_denial(
        self,
        session: Session,
        *,
        request_id: str,
        grant: CustomerContextGrant | None,
        thread_id: str = "",
        conversation_id: int | None,
        provider: str,
        audience: str,
        target_model: str,
        tool_name: str,
        scopes: list[str],
        request_hash: str,
        error_code: str,
    ) -> None:
        session.add(
            CustomerContextAccessAudit(
                id=f"context-audit-{uuid4().hex}",
                request_id=request_id,
                grant_id=(grant.id if grant is not None else None),
                grant_revision=(grant.revision if grant is not None else None),
                thread_id=(grant.thread_id if grant is not None else thread_id),
                conversation_id=conversation_id,
                provider=provider,
                audience=audience,
                target_model=target_model,
                tool_name=tool_name,
                requested_scopes_json=canonical_json(scopes),
                request_hash=request_hash,
                status="denied",
                error_code=error_code,
                completed_at=utcnow(),
            )
        )

    @staticmethod
    def _commit_access_audit(session: Session) -> None:
        """Commit the nonce receipt, mapping a concurrent duplicate to replay."""

        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise CustomerContextGatewayError(
                "access_request_replayed", "客户上下文读取请求不得重放"
            ) from exc

    def authorize_access(
        self,
        *,
        request_id: str,
        capability_token: str | None = None,
        grant_id: str | None = None,
        provider: str,
        audience: str,
        target_model: str,
        tool_name: str,
        scopes: Iterable[str],
    ) -> dict[str, Any]:
        normalized_scopes = sorted(set(scopes))
        if not normalized_scopes or not set(normalized_scopes).issubset(
            self.ALLOWED_SCOPES
        ):
            raise CustomerContextGatewayError("scope_invalid", "客户上下文读取范围无效")
        if bool(capability_token) == bool(grant_id):
            raise CustomerContextGatewayError(
                "credential_invalid", "客户上下文读取凭证无效"
            )
        request_hash = self._hash(
            {
                "request_id": request_id,
                "provider": provider,
                "audience": audience,
                "target_model": target_model,
                "tool_name": tool_name,
                "scopes": normalized_scopes,
                "credential_kind": "tunnel_binding" if grant_id else "capability",
            }
        )
        token_hash = (
            hashlib.sha256(capability_token.encode("utf-8")).hexdigest()
            if capability_token
            else ""
        )
        with self.database.session() as session:
            if session.scalar(
                select(CustomerContextAccessAudit.id).where(
                    CustomerContextAccessAudit.request_id == request_id
                )
            ):
                raise CustomerContextGatewayError(
                    "access_request_replayed", "客户上下文读取请求不得重放"
                )
            if grant_id:
                grant = session.get(CustomerContextGrant, grant_id)
                binding = None
            else:
                grant, binding = self._grant_for_token_hash(session, token_hash)
            error_code = ""
            thread: GlobalAgentThread | None = None
            if provider != self.PROVIDER_SCOPE:
                error_code = "provider_not_allowed"
            elif audience not in self.ALLOWED_AUDIENCES:
                error_code = "audience_not_allowed"
            elif tool_name not in self.ALLOWED_TOOLS:
                error_code = "tool_not_allowed"
            elif grant is None:
                error_code = "grant_not_found"
            else:
                thread = session.get(GlobalAgentThread, grant.thread_id)
                if grant.provider_scope != provider:
                    error_code = "provider_not_allowed"
                elif grant.audience != audience:
                    error_code = "audience_not_allowed"
                elif self._effective_status(grant) != "active":
                    error_code = (
                        "grant_revoked"
                        if grant.status == "revoked"
                        else "grant_expired"
                    )
                elif binding is not None and self._aware(binding.expires_at) <= utcnow():
                    error_code = "oauth_token_expired"
                elif thread is None or thread.status not in {
                    "active",
                    self.DIRECT_THREAD_STATUS,
                }:
                    error_code = "thread_not_found"
                elif (
                    thread.context_scope != "customer_conversation"
                    or thread.conversation_id != grant.conversation_id
                    or thread.revision != grant.revision
                ):
                    error_code = "binding_changed"
                elif "text" in normalized_scopes and not grant.allow_text:
                    error_code = "text_not_authorized"
                elif "images" in normalized_scopes and not grant.allow_images:
                    error_code = "images_not_authorized"
                elif "artifact" in normalized_scopes and not grant.allow_artifacts:
                    error_code = "artifact_not_authorized"
                if not error_code:
                    try:
                        conversation_ids, group_scope = grant_conversation_scope(session, grant)
                    except ConversationGroupError as exc:
                        error_code = exc.code
            if error_code:
                self._record_denial(
                    session,
                    request_id=request_id,
                    grant=grant,
                    conversation_id=(
                        grant.conversation_id if grant is not None else None
                    ),
                    provider=provider,
                    audience=audience,
                    target_model=target_model,
                    tool_name=tool_name,
                    scopes=normalized_scopes,
                    request_hash=request_hash,
                    error_code=error_code,
                )
                self._commit_access_audit(session)
                raise CustomerContextGatewayError(error_code, "客户上下文读取未获授权")
            audit = CustomerContextAccessAudit(
                id=f"context-audit-{uuid4().hex}",
                request_id=request_id,
                grant_id=grant.id,
                grant_revision=grant.revision,
                thread_id=grant.thread_id,
                conversation_id=grant.conversation_id,
                provider=provider,
                audience=audience,
                target_model=target_model,
                tool_name=tool_name,
                requested_scopes_json=canonical_json(normalized_scopes),
                request_hash=request_hash,
                status="authorized",
            )
            session.add(audit)
            if binding is not None:
                binding.last_used_at = utcnow()
            self._commit_access_audit(session)
            return {
                "audit_id": audit.id,
                "request_id": request_id,
                "grant_id": grant.id,
                "thread_id": grant.thread_id,
                "conversation_id": grant.conversation_id,
                "provider": provider,
                "audience": audience,
                "target_model": target_model,
                "tool_name": tool_name,
                "scopes": normalized_scopes,
                "conversation_ids": conversation_ids,
                "group_scope": group_scope,
                "allow_images": grant.allow_images,
                "allow_new_messages": grant.allow_new_messages,
                "confirmed_at": grant.confirmed_at,
            }

    def revalidate_read(self, authorization: dict[str, Any]) -> None:
        """No cached permit survives revocation or a member removal during I/O."""
        with self.database.session() as session:
            grant = session.get(CustomerContextGrant, authorization["grant_id"])
            self._validate_bound_grant(session, grant)
            try:
                ids, _scope = grant_conversation_scope(session, grant)
            except ConversationGroupError as exc:
                raise CustomerContextGatewayError(exc.code, str(exc)) from None
            if ids != authorization["conversation_ids"]:
                raise CustomerContextGatewayError("group_scope_changed", "授权范围已经变化")

    def complete_access(
        self,
        request_id: str,
        *,
        summary_version: int | None = None,
        watermark_before: int | None = None,
        watermark_after: int | None = None,
        text_message_count: int = 0,
        image_count: int = 0,
        byte_count: int = 0,
        resource_hashes: Iterable[str] = (),
        source_hash: str = "",
        duration_ms: int = 0,
    ) -> dict[str, Any]:
        if source_hash and (
            len(source_hash) != 64
            or any(char not in "0123456789abcdef" for char in source_hash.lower())
        ):
            raise CustomerContextGatewayError("source_hash_invalid", "来源哈希无效")
        normalized_hashes = sorted(set(resource_hashes))
        if any(
            len(value) != 64
            or any(char not in "0123456789abcdef" for char in value.lower())
            for value in normalized_hashes
        ):
            raise CustomerContextGatewayError("resource_hash_invalid", "资源哈希无效")
        with self.database.session() as session:
            row = session.scalar(
                select(CustomerContextAccessAudit).where(
                    CustomerContextAccessAudit.request_id == request_id
                )
            )
            if row is None:
                raise CustomerContextGatewayError("audit_not_found", "读取审计记录不存在")
            if row.status != "authorized":
                raise CustomerContextGatewayError(
                    "audit_not_authorized", "只有已授权的读取才能记录完成"
                )
            row.status = "completed"
            row.summary_version = summary_version
            row.watermark_before = watermark_before
            row.watermark_after = watermark_after
            row.text_message_count = max(0, text_message_count)
            row.image_count = max(0, image_count)
            row.byte_count = max(0, byte_count)
            row.resource_hashes_json = canonical_json(
                [value.lower() for value in normalized_hashes]
            )
            row.source_hash = source_hash.lower()
            row.duration_ms = max(0, duration_ms)
            row.completed_at = utcnow()
            session.commit()
            return self._audit_view(row)

    def fail_access(
        self, request_id: str, *, error_code: str, duration_ms: int = 0
    ) -> dict[str, Any]:
        with self.database.session() as session:
            row = session.scalar(
                select(CustomerContextAccessAudit).where(
                    CustomerContextAccessAudit.request_id == request_id
                )
            )
            if row is None:
                raise CustomerContextGatewayError("audit_not_found", "读取审计记录不存在")
            if row.status != "authorized":
                raise CustomerContextGatewayError(
                    "audit_not_authorized", "只有已授权的读取才能记录失败"
                )
            row.status = "failed"
            row.error_code = error_code[:64]
            row.duration_ms = max(0, duration_ms)
            row.completed_at = utcnow()
            session.commit()
            return self._audit_view(row)

    def access_audits(self, thread_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Sanitized read-only audit history; no message or image content is stored."""

        with self.database.session() as session:
            if session.get(GlobalAgentThread, thread_id) is None:
                raise CustomerContextGatewayError("thread_not_found", "小策对话不存在")
            rows = session.scalars(
                select(CustomerContextAccessAudit)
                .where(CustomerContextAccessAudit.thread_id == thread_id)
                .order_by(CustomerContextAccessAudit.created_at.desc())
                .limit(max(1, min(limit, 200)))
            )
            return [self._audit_view(row) for row in rows]
