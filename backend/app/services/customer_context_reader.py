from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select

from ..database import Database
from ..models import (
    CustomerImageArchive,
    GlobalAgentConversationSummary,
    Message,
)
from .customer_auto_analysis import (
    CustomerAutoAnalysisError,
    CustomerAutoAnalysisService,
)
from .customer_context_gateway import (
    CustomerContextGateway,
    CustomerContextGatewayError,
)
from .customer_context_images import (
    ArchivedCustomerImage,
    CustomerContextImageError,
    CustomerContextImageInput,
    CustomerContextImageReader,
    CustomerImageReadAuthorization,
)
from .customer_context_text import (
    CustomerContextTextError,
    CustomerTextMessage,
    CustomerTextSummary,
    build_customer_text_context,
)


class CustomerContextReadError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CustomerContextReadService:
    """Assemble authorized customer context without invoking any model."""

    def __init__(
        self,
        database: Database,
        gateway: CustomerContextGateway,
        project_root: Path,
        customer_analysis: CustomerAutoAnalysisService | None = None,
    ) -> None:
        self.database = database
        self.gateway = gateway
        self.project_root = project_root.resolve()
        self.customer_analysis = customer_analysis
        from .customer_context_sync import CustomerContextSync
        self.sync = CustomerContextSync(self)

    def confirm_batch(self, *, batch_id: str, summary=None, **credentials):
        # Determine the kind internally; caller cannot choose customer, scope or cursor.
        from ..customer_sync_models import CustomerContextReadBatch
        with self.database.session() as session:
            batch = session.get(CustomerContextReadBatch, batch_id)
            required_scope = 'images' if batch is not None and batch.kind == 'image' else 'text'
        authorization = self.gateway.authorize_access(**credentials, provider='openai',
            tool_name='customer_context_confirm', scopes=[required_scope])
        try:
            result = self.sync.confirm(authorization, batch_id, summary)
            self.gateway.complete_access(credentials['request_id'])
            return result
        except CustomerContextGatewayError as exc:
            self.gateway.fail_access(credentials['request_id'], error_code=exc.code)
            raise

    def mark_image_transport(self, *, archive_id, source_sha256, **credentials):
        auth = self.gateway.authorize_access(**credentials, provider='openai',
            tool_name='customer_context_image_manifest', scopes=['images'])
        try:
            self.sync.mark_image(auth, archive_id, source_sha256)
            self.gateway.complete_access(credentials['request_id'])
        except CustomerContextGatewayError as exc:
            self.gateway.fail_access(credentials['request_id'], error_code=exc.code)
            raise

    @staticmethod
    def _loads(value: str, fallback: Any) -> Any:
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _raw_text_hash(conversation_id: int, rows: list[Message]) -> str:
        digest = hashlib.sha256()
        digest.update(f"customer_text_original_v1:{conversation_id}\n".encode())
        for row in rows:
            material = {
                "id": row.id,
                "direction": row.direction,
                "message_type": row.message_type,
                "received_at": row.received_at.isoformat(),
                "content": row.content,
            }
            digest.update(
                json.dumps(
                    material,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            digest.update(b"\n")
        return digest.hexdigest()

    def _latest_summary(
        self, conversation_id: int
    ) -> CustomerTextSummary | None:
        with self.database.session() as session:
            row = session.scalar(
                select(GlobalAgentConversationSummary)
                .where(
                    GlobalAgentConversationSummary.conversation_id == conversation_id
                )
                .order_by(GlobalAgentConversationSummary.version.desc())
                .limit(1)
            )
            if row is None:
                return None
            summary = self._loads(row.summary_json, {})
            evidence = self._loads(row.evidence_message_ids_json, [])
            if not isinstance(summary, dict) or not isinstance(evidence, list):
                raise CustomerContextReadError(
                    "summary_invalid", "历史客户上下文摘要无法校验"
                )
            return CustomerTextSummary(
                conversation_id=row.conversation_id,
                version=row.version,
                summarized_through_message_id=row.summarized_through_message_id,
                message_count=row.message_count,
                source_hash=row.source_hash,
                summary=summary,
                evidence_message_ids=tuple(
                    value for value in evidence if isinstance(value, int) and value > 0
                ),
            )

    def read_text(
        self,
        *,
        request_id: str,
        capability_token: str | None = None,
        grant_id: str | None = None,
        audience: str,
        target_model: str,
        include_timeline: bool = False,
    ) -> dict[str, Any]:
        started = perf_counter()
        authorization = self.gateway.authorize_access(
            request_id=request_id,
            capability_token=capability_token,
            grant_id=grant_id,
            provider="openai",
            audience=audience,
            target_model=target_model,
            tool_name="customer_context_text",
            scopes=["text"],
        )
        try:
            durable = self.sync.text(authorization)
            if durable is not None:
                if include_timeline:
                    durable = self._with_timeline(durable, authorization, capability_token=capability_token,
                        grant_id=grant_id, audience=audience, target_model=target_model)
                self.gateway.revalidate_read(authorization)
                self.gateway.complete_access(request_id, text_message_count=durable['new_message_count'],
                    source_hash=durable['source_hash'])
                return durable
            conversation_id = int(authorization["conversation_id"])
            conversation_ids = authorization["conversation_ids"]
            previous_summary = self._latest_summary(conversation_id) if len(conversation_ids) == 1 and authorization["allow_new_messages"] else None
            with self.database.session() as session:
                rows = list(
                    session.scalars(
                        select(Message)
                        .where(Message.conversation_id.in_(conversation_ids),
                               *([] if authorization["allow_new_messages"] else [Message.created_at <= authorization["confirmed_at"]]))
                        .order_by(Message.id.asc())
                    )
                )
            candidates = [
                CustomerTextMessage(
                    message_id=row.id,
                    direction=row.direction,  # type: ignore[arg-type]
                    received_at=row.received_at.isoformat(),
                    content=row.content,
                    message_type=row.message_type,
                )
                for row in rows
            ]
            context = build_customer_text_context(
                conversation_id,
                candidates,
                previous_summary=previous_summary,
            )
            selected_ids = {row.message_id for row in context.messages}
            selected_originals = [row for row in rows if row.id in selected_ids]
            raw_source_hash = (
                previous_summary.source_hash
                if context.cached and previous_summary is not None
                else self._raw_text_hash(conversation_id, selected_originals)
            )
            duration_ms = int((perf_counter() - started) * 1000)
            result = context.as_dict()
            result["payload_source_hash"] = result.pop("source_hash")
            result["source_hash"] = raw_source_hash
            result["current_snapshot"] = "sqlite_read_during_this_request"
            result["conversation_ids"] = conversation_ids
            result["message_sources"] = [{"message_id": r.id, "conversation_id": r.conversation_id,
                "source_item_external_id": r.source_item_external_id} for r in selected_originals]
            result["image_access"] = "authorized" if authorization["allow_images"] else "not_authorized"
            if authorization["allow_images"]:
                with self.database.session() as session:
                    refs = session.scalars(select(CustomerImageArchive).join(Message, Message.id == CustomerImageArchive.message_id)
                        .where(CustomerImageArchive.conversation_id.in_(conversation_ids), Message.direction == "inbound",
                               *([] if authorization["allow_new_messages"] else [Message.created_at <= authorization["confirmed_at"]])))
                    result["image_references"] = [{"archive_id": r.id, "message_id": r.message_id,
                        "conversation_id": r.conversation_id, "status": "deleted" if r.deleted_at else r.capture_status,
                        "error_code": r.error_code} for r in refs]
                result["image_read_instructions"] = "图片增量独立于文字水位线；每次检查 xunying_list_bound_archived_images 的 image_revision，再用 xunying_read_bound_archived_image 读取编号。"
            if include_timeline:
                result = self._with_timeline(result, authorization, capability_token=capability_token,
                    grant_id=grant_id, audience=audience, target_model=target_model)
            self.gateway.revalidate_read(authorization)
            self.gateway.complete_access(request_id,
                summary_version=previous_summary.version if previous_summary else None,
                watermark_before=previous_summary.summarized_through_message_id if previous_summary else None,
                watermark_after=context.latest_text_message_id, text_message_count=context.new_message_count,
                source_hash=raw_source_hash, duration_ms=duration_ms)
            return result
        except CustomerContextGatewayError as exc:
            self.gateway.fail_access(request_id, error_code=exc.code)
            raise
        except (CustomerContextTextError, CustomerContextReadError) as exc:
            self.gateway.fail_access(
                request_id,
                error_code=(
                    str(exc)
                    if isinstance(exc, CustomerContextTextError)
                    else exc.code
                ),
                duration_ms=int((perf_counter() - started) * 1000),
            )
            if isinstance(exc, CustomerContextReadError):
                raise
            raise CustomerContextReadError(
                "text_context_invalid", "客户文字上下文无法安全组装"
            ) from None
        except Exception:
            self.gateway.fail_access(
                request_id,
                error_code="text_context_unavailable",
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise CustomerContextReadError(
                "text_context_unavailable", "客户文字上下文当前不可用"
            ) from None

    def _with_timeline(self, text: dict[str, Any], authorization: dict[str, Any], **credentials) -> dict[str, Any]:
        from .customer_context_timeline import build_event_timeline, timeline_hash, TIMELINE_INSTRUCTIONS

        manifest = self.image_manifest(request_id=f"mcp:timeline-images:{uuid4().hex}", **credentials) if authorization["allow_images"] else None
        images = manifest["images"] if manifest else []
        message_ids = {r["message_id"] for r in text["messages"] + text.get("unsummarized_context", []) + images}
        with self.database.session() as session:
            rows = list(session.scalars(select(Message).where(
                Message.id.in_(message_ids), Message.conversation_id.in_(authorization["conversation_ids"]),
                *([] if authorization["allow_new_messages"] else [Message.created_at <= authorization["confirmed_at"]]))))
            sources = {r.id: {"message_id": r.id, "conversation_id": r.conversation_id,
                "received_at": r.received_at, "direction": r.direction,
                "source_item_external_id": r.source_item_external_id} for r in rows}
            # Do not alter manifest fields/hashes: previously persisted image revisions remain valid.
            archives = {r.id: r for r in session.scalars(select(CustomerImageArchive).where(
                CustomerImageArchive.id.in_([r["archive_id"] for r in images]),
                CustomerImageArchive.conversation_id.in_(authorization["conversation_ids"]))) } if images else {}
            if message_ids != sources.keys() or any(r["archive_id"] not in archives or
                archives[r["archive_id"]].message_id != r["message_id"] or
                archives[r["archive_id"]].conversation_id != sources[r["message_id"]]["conversation_id"] or
                sources[r["message_id"]]["direction"] != "inbound" for r in images):
                raise CustomerContextReadError("timeline_source_changed", "事件来源已变化，请重新读取上下文")
            image_message_ids = {r["message_id"] for r in images}
            captions = [message.as_dict() for row in rows if row.id in image_message_ids
                for message in build_customer_text_context(row.conversation_id, [CustomerTextMessage(
                    row.id, row.direction, row.received_at.isoformat(), row.content, "text")]).messages]
            events = build_event_timeline(dict(text, image_message_context=captions),
                [dict(r, media_index=archives[r["archive_id"]].media_index) for r in images], sources)
        self.gateway.revalidate_read(authorization)
        self.sync.link_timeline(authorization, text.get("batch_id"), manifest.get("batch_id") if manifest else None)
        return {
            "event_contract": "customer_context_events_v1", "analysis_instructions": TIMELINE_INSTRUCTIONS,
            "event_scope": "bound_customer_text_batch_and_authorized_image_delta",
            "event_order": ["received_at", "message_id", "text_before_image", "media_index", "archive_id"],
            "events": events, "event_count": len(events), "timeline_source_hash": timeline_hash(events),
            **text,
            "text_batch_id": text.get("batch_id"),
            "image_batch_id": manifest.get("batch_id") if manifest else None,
            "image_requires_confirmation": bool(manifest and manifest.get("requires_confirmation")),
            "image_revision": manifest["image_revision"] if manifest else None,
            "image_scope_revision": manifest["scope_revision"] if manifest else None,
            "image_event_count": len(images),
            "summary_instructions": TIMELINE_INSTRUCTIONS,
            "image_read_instructions": TIMELINE_INSTRUCTIONS,
        }

    def image_manifest(
        self,
        *,
        request_id: str,
        capability_token: str | None = None,
        grant_id: str | None = None,
        audience: str,
        target_model: str,
    ) -> dict[str, Any]:
        started = perf_counter()
        authorization = self.gateway.authorize_access(
            request_id=request_id,
            capability_token=capability_token,
            grant_id=grant_id,
            provider="openai",
            audience=audience,
            target_model=target_model,
            tool_name="customer_context_image_manifest",
            scopes=["images"],
        )
        try:
            conversation_id = int(authorization["conversation_id"])
            with self.database.session() as session:
                rows = list(
                    session.scalars(
                        select(CustomerImageArchive)
                        .join(Message, Message.id == CustomerImageArchive.message_id)
                        .where(
                            CustomerImageArchive.conversation_id.in_(authorization["conversation_ids"]),
                            Message.direction == "inbound",
                            *([] if authorization["allow_new_messages"] else [Message.created_at <= authorization["confirmed_at"]]),
                        )
                        .order_by(CustomerImageArchive.received_at.asc())
                    )
                )
            images = [
                {
                    "archive_id": row.id,
                    "conversation_id": row.conversation_id,
                    "message_id": row.message_id,
                    "received_at": row.received_at.isoformat(),
                    "mime_type": row.mime_type,
                    "file_size": row.file_size,
                    "width": row.width,
                    "height": row.height,
                    "sha256": row.sha256,
                    "capture_status": "deleted" if row.deleted_at else row.capture_status,
                    "error_code": row.error_code,
                    "updated_at": row.updated_at.isoformat(),
                    "representations": ["original", "compatible"] if row.capture_status == "stored" and not row.deleted_at else [],
                }
                for row in rows
            ]
            source_hash = hashlib.sha256(
                json.dumps(
                    images,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.gateway.revalidate_read(authorization)
            result = self.sync.images(authorization, {
                "scope": "bound_customer_archived_images",
                "conversation_id": conversation_id,
                "images": images,
                "source_hash": source_hash,
                "image_revision": source_hash,
                "scope_revision": hashlib.sha256(json.dumps({"grant_id": authorization["grant_id"],
                    "ids": authorization["conversation_ids"], "group": authorization["group_scope"]}, sort_keys=True).encode()).hexdigest(),
                "conversation_ids": authorization["conversation_ids"],
                "current_snapshot": "sqlite_read_during_this_request",
            })
            self.gateway.revalidate_read(authorization)
            self.gateway.complete_access(request_id, image_count=len(result['images']),
                byte_count=sum(r['file_size'] for r in result['images']),
                resource_hashes=[r['sha256'] for r in result['images'] if r['sha256']],
                source_hash=source_hash, duration_ms=int((perf_counter() - started) * 1000))
            return result
        except CustomerContextGatewayError as exc:
            self.gateway.fail_access(request_id, error_code=exc.code)
            raise
        except Exception:
            self.gateway.fail_access(
                request_id,
                error_code="image_manifest_unavailable",
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise CustomerContextReadError(
                "image_manifest_unavailable", "客户原图清单当前不可用"
            ) from None

    def read_image(
        self,
        archive_id: str,
        *,
        request_id: str,
        capability_token: str | None = None,
        grant_id: str | None = None,
        audience: str,
        target_model: str,
        representation: str = "original",
    ) -> CustomerContextImageInput:
        started = perf_counter()
        authorization = self.gateway.authorize_access(
            request_id=request_id,
            capability_token=capability_token,
            grant_id=grant_id,
            provider="openai",
            audience=audience,
            target_model=target_model,
            tool_name="customer_context_image_read",
            scopes=["images"],
        )
        try:
            conversation_id = int(authorization["conversation_id"])
            with self.database.session() as session:
                row = session.scalar(
                    select(CustomerImageArchive)
                    .join(Message, Message.id == CustomerImageArchive.message_id)
                    .where(
                        CustomerImageArchive.id == archive_id,
                        CustomerImageArchive.conversation_id.in_(authorization["conversation_ids"]),
                        Message.direction == "inbound",
                        *([] if authorization["allow_new_messages"] else [Message.created_at <= authorization["confirmed_at"]]),
                    )
                )
                if row is None:
                    raise CustomerContextReadError(
                        "image_not_in_grant", "客户原图不在当前授权范围"
                    )
                metadata = ArchivedCustomerImage(
                    archive_id=row.id,
                    conversation_id=row.conversation_id,
                    message_id=row.message_id,
                    storage_path=row.storage_path,
                    sha256=row.sha256,
                    mime_type=row.mime_type,
                    file_size=row.file_size,
                    capture_status=row.capture_status,
                    integrity_verified=row.integrity_verified,
                    deleted=row.deleted_at is not None,
                )
            reader = CustomerContextImageReader(
                self.project_root / "data" / "customer-images",
                storage_base=self.project_root,
            )
            result = reader.read(
                metadata,
                CustomerImageReadAuthorization(
                    conversation_id=metadata.conversation_id,
                    original_images_authorized=True,
                ),
                representation=representation,
            )
            self.gateway.revalidate_read(authorization)
            self.gateway.complete_access(
                request_id,
                image_count=1,
                byte_count=result.file_size,
                resource_hashes=[result.sha256],
                source_hash=result.sha256,
                duration_ms=int((perf_counter() - started) * 1000),
            )
            return result
        except CustomerContextGatewayError as exc:
            self.gateway.fail_access(request_id, error_code=exc.code)
            raise
        except (CustomerContextImageError, CustomerContextReadError) as exc:
            self.gateway.fail_access(
                request_id,
                error_code=(exc.code if hasattr(exc, "code") else "image_unavailable"),
                duration_ms=int((perf_counter() - started) * 1000),
            )
            if isinstance(exc, CustomerContextReadError):
                raise
            raise CustomerContextReadError(exc.code, str(exc)) from None
        except Exception:
            self.gateway.fail_access(
                request_id,
                error_code="image_unavailable",
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise CustomerContextReadError(
                "image_unavailable", "客户原图当前不可用"
            ) from None

    def customer_artifact(
        self,
        kind: Literal["requirement_document", "execution_plan"],
        version: int | None = None,
        *,
        request_id: str,
        capability_token: str | None = None,
        grant_id: str | None = None,
        audience: str,
        target_model: str,
    ) -> dict[str, Any]:
        """Return one immutable auto-analysis artifact without invoking a model."""

        if kind not in {"requirement_document", "execution_plan"}:
            raise CustomerContextReadError("artifact_kind_invalid", "需求成果类型无效")
        if version is not None and version < 1:
            raise CustomerContextReadError("artifact_version_invalid", "需求成果版本无效")
        started = perf_counter()
        authorization = self.gateway.authorize_access(
            request_id=request_id,
            capability_token=capability_token,
            grant_id=grant_id,
            provider="openai",
            audience=audience,
            target_model=target_model,
            tool_name="customer_requirement_artifact",
            scopes=["artifact"],
        )
        try:
            conversation_id = int(authorization["conversation_id"])
            if self.customer_analysis is None:
                raise CustomerContextReadError(
                    "artifact_not_found", "当前绑定会话还没有自动分析成果"
                )
            snapshot = self.customer_analysis.artifacts_for_conversation(
                conversation_id, version=version, limit=1
            )
            artifact = (
                snapshot.artifacts[0]
                if version is not None and snapshot.artifacts
                else None if version is not None else snapshot.latest_artifact
            )
            if artifact is None:
                raise CustomerContextReadError(
                    "artifact_not_found", "当前绑定会话还没有自动分析成果"
                )
            if snapshot.subscription.conversation_id != conversation_id:
                raise CustomerContextReadError(
                    "binding_changed", "持续分析成果不属于当前授权会话"
                )
            generated = artifact.content
            content = (
                {
                    "analysis": generated.requirement_analysis.model_dump(mode="json"),
                    "blueprint": generated.requirement_blueprint.model_dump(mode="json"),
                    "customer_summary": generated.customer_summary.model_dump(mode="json"),
                }
                if kind == "requirement_document"
                else generated.execution_plan.model_dump(mode="json")
            )
            result = {
                "scope": "bound_customer_auto_analysis_artifact",
                "analysis_thread_id": snapshot.subscription.thread_id,
                "conversation_id": conversation_id,
                "kind": kind,
                "latest_version": snapshot.subscription.latest_artifact_version,
                "version": artifact.version,
                "source_run_id": artifact.run_id,
                "created_at": artifact.created_at.isoformat(),
                "watermark_before": artifact.watermark_before,
                "watermark_after": artifact.watermark_after,
                "diff": artifact.diff,
                "evidence_message_ids": artifact.evidence_message_ids,
                "evidence_image_ids": artifact.evidence_image_ids,
                "content": content,
                "append_only": True,
                "formal_requirement_case_saved": False,
                "analysis_state": snapshot.subscription.analysis_state,
                "pending_message_count": snapshot.subscription.pending_message_count,
                "last_analyzed_message_id": snapshot.subscription.last_analyzed_message_id,
                "latest_message_id": snapshot.subscription.latest_message_id,
                "current_snapshot": "sqlite_read_during_this_request",
            }
            source_hash = hashlib.sha256(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            result["source_hash"] = source_hash
            self.gateway.complete_access(
                request_id,
                summary_version=artifact.version,
                watermark_before=artifact.watermark_before,
                watermark_after=artifact.watermark_after,
                source_hash=source_hash,
                duration_ms=int((perf_counter() - started) * 1000),
            )
            return result
        except (CustomerContextReadError, CustomerAutoAnalysisError) as exc:
            code = exc.code
            self.gateway.fail_access(
                request_id,
                error_code=code,
                duration_ms=int((perf_counter() - started) * 1000),
            )
            if isinstance(exc, CustomerContextReadError):
                raise
            raise CustomerContextReadError(code, exc.safe_message) from None
        except Exception:
            self.gateway.fail_access(
                request_id,
                error_code="artifact_unavailable",
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise CustomerContextReadError(
                "artifact_unavailable", "需求成果当前不可用"
            ) from None

    def customer_analysis_status(
        self,
        *,
        request_id: str,
        capability_token: str | None = None,
        grant_id: str | None = None,
        audience: str,
        target_model: str,
    ) -> dict[str, Any]:
        """Return freshness and queue state only; never start a model run."""

        started = perf_counter()
        authorization = self.gateway.authorize_access(
            request_id=request_id,
            capability_token=capability_token,
            grant_id=grant_id,
            provider="openai",
            audience=audience,
            target_model=target_model,
            tool_name="customer_analysis_status",
            scopes=["artifact"],
        )
        try:
            conversation_id = int(authorization["conversation_id"])
            if self.customer_analysis is None:
                raise CustomerContextReadError(
                    "analysis_subscription_not_found", "当前绑定会话尚未开启持续分析"
                )
            view = self.customer_analysis.subscription_for_conversation(conversation_id)
            if view is None:
                raise CustomerContextReadError(
                    "subscription_not_found", "当前绑定会话尚未启用持续分析"
                )
            result = {
                "scope": "bound_customer_analysis_status",
                "analysis_thread_id": view.thread_id,
                "conversation_id": view.conversation_id,
                "status": view.status,
                "analysis_state": view.analysis_state,
                "configured": view.configured,
                "latest_artifact_version": view.latest_artifact_version,
                "last_enqueued_message_id": view.last_enqueued_message_id,
                "last_analyzed_message_id": view.last_analyzed_message_id,
                "latest_message_id": view.latest_message_id,
                "pending_message_count": view.pending_message_count,
                "last_completed_at": (
                    view.last_completed_at.isoformat() if view.last_completed_at else None
                ),
                "last_error_code": view.last_error_code,
                "last_error_message": view.last_error_message,
                "model_invoked_by_this_read": False,
                "current_snapshot": "sqlite_read_during_this_request",
            }
            source_hash = hashlib.sha256(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            result["source_hash"] = source_hash
            self.gateway.complete_access(
                request_id,
                summary_version=view.latest_artifact_version or None,
                watermark_before=view.last_analyzed_message_id,
                watermark_after=view.latest_message_id,
                source_hash=source_hash,
                duration_ms=int((perf_counter() - started) * 1000),
            )
            return result
        except CustomerContextReadError as exc:
            self.gateway.fail_access(
                request_id,
                error_code=exc.code,
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise
        except Exception:
            self.gateway.fail_access(
                request_id,
                error_code="analysis_status_unavailable",
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise CustomerContextReadError(
                "analysis_status_unavailable", "客户分析状态当前不可用"
            ) from None
