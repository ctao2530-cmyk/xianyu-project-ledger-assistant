from __future__ import annotations

import asyncio
import json
import logging
from itertools import count
from collections.abc import Awaitable, Callable
from contextlib import suppress

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..ai import AIProvider, AIProviderError, AIResult, SellerStyleContext
from ..config import Settings
from ..database import Database
from ..models import AIGenerationTask, Message, OperationLog, utcnow
from .repository import (
    create_generation_task,
    get_ai_input,
    recover_generation_tasks,
    save_drafts,
)
from .event_hub import EventHub
from .reply_strategy import ReplyStrategyService, ResolvedReplyStrategy
from .style_learning import StyleLearningService


logger = logging.getLogger(__name__)

SELLER_RULES = [
    "你只负责生成回复草稿，不决定是否发送；默认逐条人工确认，只有卖家预先开启本地限时无人值守且本地规则判定低风险时才可能发送。",
    "无法确认价格、能力、优惠或完成时间时，不得自行承诺。",
    "信息不足时询问具体需求、截止时间和参考资料。",
    "不得索要密码、验证码或敏感账号信息。",
    "可以模仿卖家已发送回复的语言风格，但不得复用示例中的价格、日期、联系方式、能力或承诺。",
]


class AIJobQueue:
    def __init__(
        self,
        database: Database,
        provider: AIProvider,
        settings: Settings,
        event_hub: EventHub | None = None,
        on_completed: Callable[[int], Awaitable[str]] | None = None,
        style_learning: StyleLearningService | None = None,
        reply_strategy: ReplyStrategyService | None = None,
        providers: dict[str, AIProvider] | None = None,
        automatic_provider: str | None = None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.providers = dict(providers or {provider.name: provider})
        self.providers.setdefault(provider.name, provider)
        self.automatic_provider = automatic_provider or provider.name
        self.settings = settings
        self.event_hub = event_hub
        self.on_completed = on_completed
        self.style_learning = style_learning
        self.reply_strategy = reply_strategy
        self._queue: asyncio.PriorityQueue[tuple[int, int, int]] = asyncio.PriorityQueue(
            maxsize=max(100, settings.codex_max_concurrency * 50)
        )
        self._queue_sequence = count()
        self._workers: list[asyncio.Task[None]] = []
        self._busy_conversations: set[int] = set()
        self._busy_lock = asyncio.Lock()
        self._stopping = False

    async def start(self) -> None:
        if self._workers:
            return
        self._stopping = False
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"ai-worker-{index}")
            for index in range(self.settings.codex_max_concurrency)
        ]
        with self.database.session() as session:
            task_ids = recover_generation_tasks(session)
            recovered_priorities = {
                task_id: (
                    0
                    if (
                        (task := session.get(AIGenerationTask, task_id))
                        and task.trigger_key.endswith(":automatic")
                    )
                    else 1
                )
                for task_id in task_ids
            }
        for task_id in task_ids:
            await self._put(task_id, priority=recovered_priorities[task_id])

    async def stop(self) -> None:
        self._stopping = True
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            with suppress(asyncio.CancelledError):
                await worker
        self._workers.clear()
        closed: set[int] = set()
        for provider in self.providers.values():
            if id(provider) in closed:
                continue
            closed.add(id(provider))
            await provider.close()

    async def enqueue(
        self,
        message_id: int,
        *,
        automatic: bool,
        provider_name: str | None = None,
    ) -> AIGenerationTask | None:
        selected_provider = provider_name or (
            self.automatic_provider if automatic else self.provider.name
        )
        if selected_provider not in self.providers:
            raise AIProviderError(
                "provider_unavailable",
                f"AI Provider {selected_provider} 当前不可用",
            )
        with self.database.session() as session:
            try:
                task, is_new = create_generation_task(
                    session,
                    message_id,
                    provider=selected_provider,
                    automatic=automatic,
                )
            except IntegrityError:
                session.rollback()
                if not automatic:
                    raise
                task = session.scalar(
                    select(AIGenerationTask).where(
                        AIGenerationTask.trigger_key == f"message:{message_id}:automatic"
                    )
                )
                is_new = False
            task_id = task.id if task else None
        if task_id is not None and is_new:
            await self._put(task_id, priority=0 if automatic else 1)
        if task_id is None:
            return None
        with self.database.session() as session:
            return session.get(AIGenerationTask, task_id)

    async def cancel(self, task_id: int) -> bool:
        running = False
        with self.database.session() as session:
            task = session.get(AIGenerationTask, task_id)
            if not task or task.status not in {"pending", "running"}:
                return False
            task.cancel_requested = True
            running = task.status == "running"
            if not running:
                task.status = "cancelled"
                task.finished_at = utcnow()
                message = session.get(Message, task.message_id)
                if message and message.status not in {"sent", "sending", "ignored"}:
                    message.status = "ai_cancelled"
            session.add(
                OperationLog(
                    message_id=task.message_id,
                    action="ai_task_cancel_requested",
                    detail="用户取消 AI 草稿生成任务",
                )
            )
            session.commit()
        if running:
            provider = self.providers.get(task.provider, self.provider)
            await provider.cancel(str(task_id))
        return True

    def _provider_for(self, provider_name: str) -> AIProvider:
        provider = self.providers.get(provider_name)
        if provider is None:
            raise AIProviderError(
                "provider_unavailable",
                f"AI Provider {provider_name} 当前不可用",
            )
        return provider

    async def _reserve_conversation(self, conversation_id: int) -> bool:
        async with self._busy_lock:
            if conversation_id in self._busy_conversations:
                return False
            self._busy_conversations.add(conversation_id)
            return True

    async def _put(self, task_id: int, *, priority: int) -> None:
        await self._queue.put((priority, next(self._queue_sequence), task_id))

    async def _release_conversation(self, conversation_id: int) -> None:
        async with self._busy_lock:
            self._busy_conversations.discard(conversation_id)

    async def _worker(self, _index: int) -> None:
        while True:
            priority, _sequence, task_id = await self._queue.get()
            try:
                with self.database.session() as session:
                    task = session.get(AIGenerationTask, task_id)
                    if not task or task.status != "pending":
                        continue
                    conversation_id = task.conversation_id
                    earlier_task = session.scalar(
                        select(AIGenerationTask.id)
                        .where(
                            AIGenerationTask.conversation_id == conversation_id,
                            AIGenerationTask.status.in_(("pending", "running")),
                            AIGenerationTask.id < task.id,
                        )
                        .limit(1)
                    )
                if earlier_task is not None:
                    await self._put(task_id, priority=priority)
                    await asyncio.sleep(0.05)
                    continue
                if not await self._reserve_conversation(conversation_id):
                    await self._put(task_id, priority=priority)
                    await asyncio.sleep(0.05)
                    continue
                try:
                    await self._run_task(task_id)
                finally:
                    await self._release_conversation(conversation_id)
            finally:
                self._queue.task_done()

    async def _run_task(self, task_id: int) -> None:
        with self.database.session() as session:
            task = session.get(AIGenerationTask, task_id)
            if not task or task.status != "pending":
                return
            if task.cancel_requested:
                task.status = "cancelled"
                task.finished_at = utcnow()
                session.commit()
                return
            task.status = "running"
            task.started_at = utcnow()
            task.attempt_count += 1
            task.error_code = None
            task.error_message = None
            task.repair_command = None
            message = session.get(Message, task.message_id)
            if message and message.status not in {"sent", "sending", "ignored"}:
                message.status = "ai_generating"
            try:
                local_risks = json.loads(message.risk_flags_json) if message else []
            except json.JSONDecodeError:
                local_risks = []
            session.commit()
            message_id = task.message_id
            provider_name = task.provider

        try:
            provider = self._provider_for(provider_name)
        except AIProviderError as exc:
            self._fail_task(task_id, exc)
            return

        resolved_strategy: ResolvedReplyStrategy | None = None
        message_limit = self.settings.codex_max_context_messages
        context_chars = self.settings.codex_max_context_chars
        model_selection = None
        if self.reply_strategy and provider.name != "deepseek":
            resolved_strategy = self.reply_strategy.resolve(
                base_selection=provider.model_selection,
                has_local_risk=bool(local_risks),
            )
            message_limit = resolved_strategy.context_messages
            context_chars = resolved_strategy.context_chars
            model_selection = resolved_strategy.model_selection
            with self.database.session() as session:
                session.add(
                    OperationLog(
                        message_id=message_id,
                        action="ai_task_started",
                        detail=(
                            f"回复模式 {resolved_strategy.mode}，"
                            f"模型 {model_selection.model or 'Codex 默认'}，"
                            f"推理 {model_selection.reasoning_effort or '默认'}"
                        ),
                    )
                )
                session.commit()

        used_model = (
            model_selection.model
            if model_selection and model_selection.model
            else provider.model_selection.model
        )
        with self.database.session() as session:
            current_task = session.get(AIGenerationTask, task_id)
            if current_task:
                current_task.model = used_model
                session.add(
                    OperationLog(
                        message_id=message_id,
                        action="ai_provider_selected",
                        detail=(
                            f"Provider {provider.name}，模型 {used_model or 'Provider 默认'}"
                        ),
                    )
                )
                session.commit()

        with self.database.session() as session:
            context = get_ai_input(
                session,
                message_id,
                message_limit=message_limit,
                total_chars=context_chars,
                seller_rules=SELLER_RULES,
            )
        if not context:
            self._fail_task(
                task_id,
                AIProviderError("message_not_found", "找不到待生成草稿的消息"),
            )
            return
        conversation_id, payload = context
        if self.style_learning:
            payload = payload.model_copy(
                update={
                    "seller_style": self.style_learning.build_context(conversation_id)
                }
            )

        try:
            result = await provider.generate(
                payload,
                task_key=str(task_id),
                model_selection=model_selection,
            )
        except asyncio.CancelledError:
            self._return_to_pending(task_id)
            raise
        except AIProviderError as exc:
            if self._is_cancel_requested(task_id):
                self._mark_cancelled(task_id)
            else:
                self._fail_task(task_id, exc)
            return
        except Exception as exc:
            logger.exception("AI 任务发生未预期错误 task_id=%s", task_id)
            self._fail_task(
                task_id,
                AIProviderError("ai_internal_error", f"AI 任务失败：{type(exc).__name__}"),
            )
            return

        if self._is_cancel_requested(task_id):
            self._mark_cancelled(task_id)
            return
        event = self._complete_task(
            task_id,
            result,
            provider,
            payload.seller_style,
            resolved_strategy,
        )
        outcome = "disabled"
        if self.on_completed:
            try:
                outcome = await self.on_completed(message_id)
            except Exception as exc:
                logger.exception(
                    "无人值守安全检查失败 task_id=%s error=%s",
                    task_id,
                    type(exc).__name__,
                )
                outcome = "failed"
        if event and self.event_hub:
            event["auto_reply_status"] = outcome
            if outcome == "sent":
                event["type"] = "auto_reply_sent"
            self.event_hub.publish_nowait(event)

    def _is_cancel_requested(self, task_id: int) -> bool:
        with self.database.session() as session:
            task = session.get(AIGenerationTask, task_id)
            return bool(task and task.cancel_requested)

    def _complete_task(
        self,
        task_id: int,
        result: AIResult,
        provider: AIProvider,
        seller_style: SellerStyleContext | None = None,
        resolved_strategy: ResolvedReplyStrategy | None = None,
    ) -> dict[str, object] | None:
        event: dict[str, object] | None = None
        with self.database.session() as session:
            task = session.get(AIGenerationTask, task_id)
            if not task:
                return
            task.status = "completed"
            task.risk_level = result.risk_level
            task.risk_reasons_json = json.dumps(result.risk_reasons, ensure_ascii=False)
            task.needs_human_confirmation = True
            task.finished_at = utcnow()
            save_drafts(session, task.message_id, result.drafts(), commit=False)
            message = session.get(Message, task.message_id)
            if message:
                conversation = message.conversation
                event = {
                    "type": "new_reply",
                    "channel": message.channel,
                    "event_id": f"ai-task-{task.id}",
                    "task_id": task.id,
                    "message_id": message.id,
                    "conversation_id": conversation.external_id,
                    "customer_name": conversation.customer_name,
                    "product_title": (
                        conversation.item.title
                        if conversation.item
                        else (
                            "微信咨询"
                            if message.channel == "wechat"
                            else "商品信息未同步"
                        )
                    ),
                    "customer_message": message.content,
                    "recommended_reply": result.direct,
                    "alternatives": [result.friendly, result.conversion],
                    "risk_level": result.risk_level,
                    "risk_reasons": result.risk_reasons,
                    "needs_human_confirmation": True,
                    "reply_mode": resolved_strategy.mode if resolved_strategy else "custom",
                    "reply_model": (
                        resolved_strategy.model_selection.model
                        if resolved_strategy
                        else provider.model_selection.model
                    ),
                    "provider": provider.name,
                    "risk_escalated_model": bool(
                        resolved_strategy and resolved_strategy.escalated_for_risk
                    ),
                    "style_learning_enabled": bool(
                        seller_style and seller_style.enabled
                    ),
                    "style_sample_count": (
                        seller_style.sample_count if seller_style else 0
                    ),
                    "style_summary": seller_style.summary if seller_style else "",
                    "style_traits": seller_style.traits if seller_style else [],
                    "created_at": task.finished_at.isoformat(),
                }
            session.add(
                OperationLog(
                    message_id=task.message_id,
                    action="ai_task_completed",
                    detail=f"AI 任务 {task.id} 已完成，风险等级 {result.risk_level}",
                )
            )
            session.commit()
        return event

    def _fail_task(self, task_id: int, error: AIProviderError) -> None:
        with self.database.session() as session:
            task = session.get(AIGenerationTask, task_id)
            if not task:
                return
            task.status = "failed"
            task.error_code = error.code
            task.error_message = error.safe_message
            task.repair_command = error.repair_command
            task.finished_at = utcnow()
            message = session.get(Message, task.message_id)
            if message and message.status not in {"sent", "sending", "ignored"}:
                message.status = "ai_failed"
            session.add(
                OperationLog(
                    message_id=task.message_id,
                    action="ai_task_failed",
                    detail=f"{error.code}：{error.safe_message}",
                )
            )
            session.commit()

    def _mark_cancelled(self, task_id: int) -> None:
        with self.database.session() as session:
            task = session.get(AIGenerationTask, task_id)
            if not task:
                return
            task.status = "cancelled"
            task.finished_at = utcnow()
            message = session.get(Message, task.message_id)
            if message and message.status not in {"sent", "sending", "ignored"}:
                message.status = "ai_cancelled"
            session.commit()

    def _return_to_pending(self, task_id: int) -> None:
        with self.database.session() as session:
            task = session.get(AIGenerationTask, task_id)
            if not task or task.cancel_requested:
                return
            task.status = "pending"
            message = session.get(Message, task.message_id)
            if message and message.status not in {"sent", "sending", "ignored"}:
                message.status = "ai_queued"
            session.commit()
