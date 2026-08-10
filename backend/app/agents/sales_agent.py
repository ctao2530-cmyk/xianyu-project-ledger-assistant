from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..ai import AIModelSelection, AIProvider, AIProviderError
from ..database import Database
from ..ledger import LedgerService, RevisionConflict
from ..models import (
    BusinessCustomer,
    Conversation,
    CustomerChannelIdentity,
    CustomerMemory,
    Message,
    RequirementDocumentVersion,
    SalesAnalysisRun,
    SalesLead,
    utcnow,
)
from ..services.event_hub import EventHub
from ..services.risk import detect_risks
from .memory import SalesMemoryStore
from .prompts import build_sales_analysis_prompt
from .tools import CustomerHistoryTool, PricingHistoryTool, SimilarProjectTool


logger = logging.getLogger(__name__)

SalesStage = Literal[
    "初次咨询",
    "需求沟通",
    "方案评估",
    "报价决策",
    "待跟进",
    "已成交",
    "暂不匹配",
]
SalesCustomerType = Literal[
    "新访客",
    "潜在客户",
    "意向客户",
    "已有客户",
    "低匹配客户",
]
SalesToolName = Literal["customer_history", "similar_projects", "pricing_history"]


class SalesAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_type: SalesCustomerType
    need_type: str = Field(min_length=2, max_length=120)
    purchase_probability: int = Field(ge=0, le=100)
    stage: SalesStage
    customer_profile: str = Field(min_length=2, max_length=600)
    need_signals: list[str] = Field(default_factory=list, max_length=20)
    sales_strategy: str = Field(min_length=2, max_length=800)
    next_action: str = Field(min_length=2, max_length=300)
    recommended_reply: str = Field(min_length=10, max_length=600)
    evidence_refs: list[int] = Field(default_factory=list, max_length=50)
    risk_flags: list[str] = Field(default_factory=list, max_length=20)
    tools_used: list[SalesToolName] = Field(default_factory=list, max_length=3)
    needs_human_confirmation: Literal[True] = True


class SalesContextSummary(BaseModel):
    message_count: int = 0
    project_count: int = 0
    quote_count: int = 0
    confirmed_revenue: float = 0
    memory_version: int = 0


class SalesAnalysisRecord(BaseModel):
    id: str
    conversation_id: int
    message_id: int
    provider: str
    model: str
    status: str
    result: SalesAnalysisResult | None = None
    tools_used: list[str] = Field(default_factory=list)
    context_summary: SalesContextSummary = Field(default_factory=SalesContextSummary)
    error_code: str | None = None
    error_message: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    finished_at: datetime | None = None


@dataclass(slots=True)
class SalesConfirmationResult:
    analysis_id: str
    lead_id: str
    customer_id: str
    memory_id: str
    memory_version: int
    revision: int
    idempotent: bool


class SalesAgentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class SalesAgent:
    """Independent sales analysis orchestration around read-only business tools."""

    tool_names = ["customer_history", "similar_projects", "pricing_history"]

    def __init__(
        self,
        database: Database,
        ledger: LedgerService,
        provider: AIProvider,
        *,
        model_selection: AIModelSelection | None = None,
        providers: dict[str, AIProvider] | None = None,
        model_selections: dict[str, AIModelSelection] | None = None,
        timeout_seconds: float = 15,
        event_hub: EventHub | None = None,
        history_limit: int = 30,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.provider = provider
        self.providers = dict(providers or {provider.name: provider})
        self.providers.setdefault(provider.name, provider)
        self.model_selection = model_selection or AIModelSelection()
        self.model_selections = dict(model_selections or {})
        self.model_selections.setdefault(provider.name, self.model_selection)
        self.timeout_seconds = timeout_seconds
        self.event_hub = event_hub
        self.customer_tool = CustomerHistoryTool(
            database, message_limit=history_limit
        )
        self.project_tool = SimilarProjectTool(database)
        self.pricing_tool = PricingHistoryTool(database)
        self.memory_store = SalesMemoryStore(database)
        self._locks: dict[int, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _resolve_provider(
        self, provider_name: str | None
    ) -> tuple[AIProvider, AIModelSelection]:
        provider = self.providers.get(provider_name or self.provider.name)
        if provider is None:
            raise SalesAgentError(
                "provider_unavailable",
                f"Sales Agent Provider {provider_name} 当前不可用",
            )
        selection = self.model_selections.get(provider.name, AIModelSelection())
        return provider, selection

    @staticmethod
    def _json_list(value: str) -> list[str]:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @staticmethod
    def _json_dict(value: str) -> dict[str, Any]:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def record_from_run(self, run: SalesAnalysisRun) -> SalesAnalysisRecord:
        result = None
        if run.structured_json:
            try:
                result = SalesAnalysisResult.model_validate_json(run.structured_json)
            except ValueError:
                result = None
        return SalesAnalysisRecord(
            id=run.id,
            conversation_id=run.conversation_id,
            message_id=run.message_id,
            provider=run.provider,
            model=run.model,
            status=run.status,
            result=result,
            tools_used=self._json_list(run.tools_used_json),
            context_summary=SalesContextSummary.model_validate(
                self._json_dict(run.context_summary_json)
            ),
            error_code=run.error_code,
            error_message=run.error_message,
            confirmed_at=run.confirmed_at,
            created_at=run.created_at,
            finished_at=run.finished_at,
        )

    def latest(self, conversation_id: int) -> SalesAnalysisRecord | None:
        with self.database.session() as session:
            run = session.scalar(
                select(SalesAnalysisRun)
                .where(SalesAnalysisRun.conversation_id == conversation_id)
                .order_by(SalesAnalysisRun.created_at.desc())
                .limit(1)
            )
            return self.record_from_run(run) if run else None

    def history(self, conversation_id: int, *, limit: int = 10) -> list[SalesAnalysisRecord]:
        with self.database.session() as session:
            runs = list(
                session.scalars(
                    select(SalesAnalysisRun)
                    .where(SalesAnalysisRun.conversation_id == conversation_id)
                    .order_by(SalesAnalysisRun.created_at.desc())
                    .limit(max(1, min(limit, 30)))
                )
            )
            return [self.record_from_run(run) for run in runs]

    def memory(self, conversation_id: int) -> dict[str, Any]:
        return self.memory_store.read(conversation_id)

    def schedule(self, message_id: int) -> None:
        task = asyncio.create_task(
            self._run_scheduled(message_id),
            name=f"sales-analysis-{message_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_scheduled(self, message_id: int) -> None:
        try:
            await self.analyze_message(message_id)
        except SalesAgentError as exc:
            logger.warning(
                "Sales Agent 自动分析失败 message_id=%s code=%s",
                message_id,
                exc.code,
            )

    async def stop(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def analyze_conversation(
        self,
        conversation_id: int,
        *,
        refresh: bool = False,
        provider_name: str | None = None,
    ) -> SalesAnalysisRecord:
        with self.database.session() as session:
            if not session.get(Conversation, conversation_id):
                raise SalesAgentError("conversation_not_found", "会话不存在")
            message_id = session.scalar(
                select(Message.id)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.direction == "inbound",
                )
                .order_by(Message.received_at.desc(), Message.id.desc())
                .limit(1)
            )
        if message_id is None:
            raise SalesAgentError("message_not_found", "当前会话没有可分析的客户消息")
        return await self.analyze_message(
            message_id,
            refresh=refresh,
            provider_name=provider_name,
        )

    async def analyze_message(
        self,
        message_id: int,
        *,
        refresh: bool = False,
        provider_name: str | None = None,
    ) -> SalesAnalysisRecord:
        selected_provider, selected_model = self._resolve_provider(provider_name)
        with self.database.session() as session:
            message = session.get(Message, message_id)
            if message is None or message.direction != "inbound":
                raise SalesAgentError("message_not_found", "客户消息不存在")
            conversation_id = message.conversation_id

        lock = self._locks.setdefault(conversation_id, asyncio.Lock())
        async with lock:
            with self.database.session() as session:
                message = session.get(Message, message_id)
                if message is None:
                    raise SalesAgentError("message_not_found", "客户消息不存在")
                if not refresh:
                    cached = session.scalar(
                        select(SalesAnalysisRun)
                        .where(
                            SalesAnalysisRun.message_id == message_id,
                            SalesAnalysisRun.status == "completed",
                            SalesAnalysisRun.provider == selected_provider.name,
                        )
                        .order_by(SalesAnalysisRun.created_at.desc())
                        .limit(1)
                    )
                    if cached:
                        return self.record_from_run(cached)
                run = SalesAnalysisRun(
                    id=f"sales-analysis-{uuid4()}",
                    conversation_id=conversation_id,
                    message_id=message_id,
                    provider=selected_provider.name,
                    model=selected_model.model or selected_provider.name,
                    status="running",
                    tools_used_json=json.dumps(self.tool_names),
                )
                current_message = {
                    "message_id": message.id,
                    "content": message.content[:2000],
                    "received_at": message.received_at.isoformat(),
                }
                session.add(run)
                session.commit()

            try:
                customer_history = self.customer_tool.run(conversation_id)
                query = " ".join(
                    [
                        str(current_message["content"]),
                        *[
                            str(item.get("content") or "")
                            for item in customer_history.get("message_history", [])[-8:]
                        ],
                    ]
                )[:5000]
                similar_projects = self.project_tool.run(query)
                pricing_history = self.pricing_tool.run(
                    [
                        str(item.get("project_id") or "")
                        for item in similar_projects.get("matches", [])
                    ]
                )
                sales_memory = self.memory_store.read(conversation_id)
                context_summary = {
                    "message_count": int(customer_history.get("message_count") or 0),
                    "project_count": int(customer_history.get("project_count") or 0),
                    "quote_count": int(pricing_history.get("quote_count") or 0),
                    "confirmed_revenue": float(
                        customer_history.get("confirmed_revenue") or 0
                    ),
                    "memory_version": int(sales_memory.get("latest_version") or 0),
                }
                prompt = build_sales_analysis_prompt(
                    current_message=current_message,
                    customer_history=customer_history,
                    similar_projects=similar_projects,
                    pricing_history=pricing_history,
                    sales_memory=sales_memory,
                )
                result = await selected_provider.generate_structured(
                    prompt,
                    result_type=SalesAnalysisResult,
                    task_key=run.id,
                    model_selection=selected_model,
                    timeout=self.timeout_seconds,
                )
                valid_message_ids = {
                    int(item["message_id"])
                    for item in customer_history.get("message_history", [])
                    if item.get("message_id") is not None
                }
                invalid_refs = [
                    value for value in result.evidence_refs if value not in valid_message_ids
                ]
                if invalid_refs:
                    raise SalesAgentError(
                        "invalid_evidence_refs",
                        "销售分析返回了无效的对话证据，请重试",
                    )
                local_risks = detect_risks(
                    f"{current_message['content']}\n{result.recommended_reply}"
                )
                result = result.model_copy(
                    update={
                        "risk_flags": list(
                            dict.fromkeys([*result.risk_flags, *local_risks])
                        )[:20],
                        "tools_used": self.tool_names,
                        "needs_human_confirmation": True,
                    }
                )
            except (AIProviderError, SalesAgentError) as exc:
                code = exc.code
                message_text = (
                    exc.safe_message if isinstance(exc, AIProviderError) else exc.safe_message
                )
                self._mark_failed(run.id, code, message_text)
                self._publish(
                    {
                        "type": "sales_analysis_failed",
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "analysis_id": run.id,
                    }
                )
                raise SalesAgentError(code, message_text) from None
            except Exception as exc:
                logger.exception(
                    "Sales Agent 分析异常 conversation_id=%s error=%s",
                    conversation_id,
                    type(exc).__name__,
                )
                message_text = "销售分析暂时失败，请稍后重试"
                self._mark_failed(run.id, "sales_analysis_failed", message_text)
                self._publish(
                    {
                        "type": "sales_analysis_failed",
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "analysis_id": run.id,
                    }
                )
                raise SalesAgentError("sales_analysis_failed", message_text) from None

            with self.database.session() as session:
                stored = session.get(SalesAnalysisRun, run.id)
                if stored is None:
                    raise SalesAgentError("analysis_missing", "销售分析记录不存在")
                stored.status = "completed"
                stored.structured_json = result.model_dump_json()
                stored.tools_used_json = json.dumps(self.tool_names)
                stored.context_summary_json = json.dumps(
                    context_summary, ensure_ascii=False
                )
                stored.finished_at = utcnow()
                session.commit()
                record = self.record_from_run(stored)
            self._publish(
                {
                    "type": "sales_analysis_completed",
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "analysis_id": record.id,
                }
            )
            return record

    def _mark_failed(self, run_id: str, code: str, message: str) -> None:
        with self.database.session() as session:
            run = session.get(SalesAnalysisRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.error_code = code[:64]
            run.error_message = message[:1000]
            run.finished_at = utcnow()
            session.commit()

    def _publish(self, event: dict[str, Any]) -> None:
        if self.event_hub:
            self.event_hub.publish_nowait(event)

    @staticmethod
    def _customer_level(probability: int) -> str:
        if probability >= 75:
            return "A"
        if probability >= 45:
            return "B"
        return "C"

    @staticmethod
    def _follow_up_status(stage: str) -> str:
        if stage in {"方案评估", "报价决策"}:
            return "proposal"
        return "contacted"

    def confirm_analysis(self, analysis_id: str) -> SalesConfirmationResult:
        revision, snapshot = self.ledger.get()
        with self.database.session() as session:
            run = session.get(SalesAnalysisRun, analysis_id)
            if run is None:
                raise SalesAgentError("analysis_not_found", "销售分析记录不存在")
            if run.status != "completed" or not run.structured_json:
                raise SalesAgentError("analysis_not_ready", "销售分析尚未完成")
            conversation = session.get(Conversation, run.conversation_id)
            if conversation is None:
                raise SalesAgentError("conversation_not_found", "原会话不存在")
            analysis = SalesAnalysisResult.model_validate_json(run.structured_json)
            existing_lead = session.scalar(
                select(SalesLead).where(
                    SalesLead.conversation_id == conversation.id
                )
            )
            existing_memory = session.scalar(
                select(CustomerMemory).where(
                    CustomerMemory.conversation_id == conversation.id
                )
            )
            if run.confirmed_at and existing_lead and existing_memory and existing_lead.customer_id:
                return SalesConfirmationResult(
                    analysis_id=run.id,
                    lead_id=existing_lead.id,
                    customer_id=existing_lead.customer_id,
                    memory_id=existing_memory.id,
                    memory_version=existing_memory.version,
                    revision=revision,
                    idempotent=True,
                )

            identity = session.scalar(
                select(CustomerChannelIdentity).where(
                    CustomerChannelIdentity.channel == conversation.channel,
                    CustomerChannelIdentity.external_customer_id
                    == conversation.customer_id,
                )
            )
            customer_id = (
                (identity.customer_id if identity else None)
                or (existing_lead.customer_id if existing_lead else None)
            )
            customer = (
                session.get(BusinessCustomer, customer_id) if customer_id else None
            )
            if customer_id and customer is None:
                customer_id = None
            now_text = utcnow().isoformat()
            requested_level = self._customer_level(analysis.purchase_probability)
            follow_up = self._follow_up_status(analysis.stage)

            snapshot_customer = next(
                (
                    row
                    for row in snapshot["customers"]
                    if customer_id and str(row.get("id")) == customer_id
                ),
                None,
            )
            if customer_id is None:
                customer_id = f"customer-{uuid4()}"
                snapshot_customer = {
                    "id": customer_id,
                    "name": conversation.customer_name or "新客户",
                    "source": (
                        conversation.channel
                        if conversation.channel in {"xianyu", "wechat"}
                        else "other"
                    ),
                    "phone": "待补充",
                    "followUpStatus": follow_up,
                    "lastContactAt": now_text,
                    "level": requested_level,
                    "tags": ["AI 销售线索", analysis.need_type],
                    "channelIdentities": [
                        {
                            "channel": conversation.channel,
                            "externalCustomerId": conversation.customer_id,
                            "conversationId": conversation.id,
                        }
                    ],
                }
                snapshot["customers"].insert(0, snapshot_customer)
            elif snapshot_customer is None:
                try:
                    existing_tags = json.loads(customer.tags_json) if customer else []
                except (TypeError, json.JSONDecodeError):
                    existing_tags = []
                snapshot_customer = {
                    "id": customer_id,
                    "name": customer.name if customer else conversation.customer_name,
                    "source": customer.source if customer else conversation.channel,
                    "phone": customer.phone if customer else "待补充",
                    "followUpStatus": (
                        customer.follow_up_status if customer else follow_up
                    ),
                    "lastContactAt": now_text,
                    "level": customer.level if customer else requested_level,
                    "tags": existing_tags if isinstance(existing_tags, list) else [],
                }
                snapshot["customers"].insert(0, snapshot_customer)
            else:
                snapshot_customer["lastContactAt"] = now_text
                if snapshot_customer.get("followUpStatus") not in {"won"}:
                    snapshot_customer["followUpStatus"] = follow_up
                level_rank = {"A": 0, "B": 1, "C": 2}
                current_level = str(snapshot_customer.get("level") or "C")
                if level_rank.get(requested_level, 2) < level_rank.get(current_level, 2):
                    snapshot_customer["level"] = requested_level
                tags = [str(value) for value in snapshot_customer.get("tags") or []]
                snapshot_customer["tags"] = list(
                    dict.fromkeys([*tags, "AI 销售线索", analysis.need_type])
                )[:12]

            try:
                new_revision, _saved = self.ledger.save_in_session(
                    session, snapshot, revision
                )
            except RevisionConflict as exc:
                raise SalesAgentError(
                    "revision_conflict",
                    f"经营数据已在其他浏览器更新（修订 {exc.revision}），请刷新后重试",
                ) from None

            if identity is None:
                identity = CustomerChannelIdentity(
                    id=f"identity-{uuid4()}",
                    customer_id=customer_id,
                    channel=conversation.channel,
                    external_customer_id=conversation.customer_id,
                    conversation_id=conversation.id,
                    display_name=conversation.customer_name,
                )
                session.add(identity)
            else:
                identity.customer_id = customer_id
                identity.conversation_id = conversation.id
                identity.display_name = conversation.customer_name

            lead = existing_lead
            if lead is None:
                latest_requirement = session.scalar(
                    select(RequirementDocumentVersion)
                    .where(
                        RequirementDocumentVersion.conversation_id
                        == conversation.id
                    )
                    .order_by(RequirementDocumentVersion.version.desc())
                    .limit(1)
                )
                lead = SalesLead(
                    id=f"lead-{uuid4()}",
                    conversation_id=conversation.id,
                    customer_id=customer_id,
                    status="analyzed",
                    requirement_version_id=(
                        latest_requirement.id if latest_requirement else None
                    ),
                    notes=f"下一步：{analysis.next_action}",
                )
                session.add(lead)
            else:
                lead.customer_id = customer_id
                if lead.status not in {"won", "lost"}:
                    lead.status = "analyzed"
                lead.notes = f"下一步：{analysis.next_action}"

            memory = self.memory_store.upsert_in_session(
                session,
                conversation_id=conversation.id,
                customer_id=customer_id,
                analysis_id=run.id,
                analysis=analysis.model_dump(),
            )
            run.confirmed_at = utcnow()
            session.commit()
            result = SalesConfirmationResult(
                analysis_id=run.id,
                lead_id=lead.id,
                customer_id=customer_id,
                memory_id=memory.id,
                memory_version=memory.version,
                revision=new_revision,
                idempotent=False,
            )

        self._publish(
            {
                "type": "sales_analysis_confirmed",
                "conversation_id": run.conversation_id,
                "analysis_id": run.id,
                "lead_id": result.lead_id,
                "customer_id": result.customer_id,
            }
        )
        self._publish(
            {
                "type": "lead_updated",
                "lead_id": result.lead_id,
                "status": "analyzed",
            }
        )
        self._publish(
            {
                "type": "customer_memory_updated",
                "customer_id": result.customer_id,
                "memory_id": result.memory_id,
            }
        )
        self._publish(
            {
                "type": "ledger_updated",
                "revision": result.revision,
                "source": "sales_analysis_confirmation",
            }
        )
        return result
