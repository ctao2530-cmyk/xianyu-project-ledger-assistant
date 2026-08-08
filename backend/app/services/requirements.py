from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..ai import AIModelSelection, AIProvider, AIProviderError
from ..ai.requirements import REQUIREMENT_SYSTEM_TASK, RequirementAnalysisResult
from ..config import Settings
from ..database import Database
from ..models import (
    Conversation,
    Message,
    OperationLog,
    RequirementAnalysisTask,
    RequirementDocumentVersion,
    utcnow,
)
from .event_hub import EventHub
from .notifier import MacOSNotifier


logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
ACTIVE_STATUSES = ("pending", "running")
STAGE_STATUSES = {"pending", "in_progress", "completed", "blocked"}


class RequirementServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RequirementAnalysisService:
    """Bounded local queue for deliberate, per-conversation requirement analysis."""

    def __init__(
        self,
        database: Database,
        provider: AIProvider,
        settings: Settings,
        notifier: MacOSNotifier,
        event_hub: EventHub | None = None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.settings = settings
        self.notifier = notifier
        self.event_hub = event_hub
        self._queue: asyncio.Queue[int] = asyncio.Queue(maxsize=50)
        self._worker_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker_task:
            return
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(RequirementAnalysisTask)
                    .where(RequirementAnalysisTask.status.in_(ACTIVE_STATUSES))
                    .order_by(RequirementAnalysisTask.id.asc())
                )
            )
            task_ids: list[int] = []
            for task in rows:
                if task.cancel_requested:
                    task.status = "cancelled"
                    task.finished_at = utcnow()
                    continue
                task.status = "pending"
                task.started_at = None
                task_ids.append(task.id)
            session.commit()
        self._worker_task = asyncio.create_task(
            self._worker(), name="requirement-analysis-worker"
        )
        for task_id in task_ids:
            await self._queue.put(task_id)

    async def stop(self) -> None:
        if not self._worker_task:
            return
        self._worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._worker_task
        self._worker_task = None

    async def enqueue(
        self,
        conversation_id: int,
        *,
        change_request: str | None = None,
    ) -> RequirementAnalysisTask:
        cleaned_change = change_request.strip() if change_request else None
        with self.database.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if not conversation:
                raise RequirementServiceError("conversation_not_found", "会话不存在")
            active = session.scalar(
                select(RequirementAnalysisTask)
                .where(
                    RequirementAnalysisTask.conversation_id == conversation_id,
                    RequirementAnalysisTask.status.in_(ACTIVE_STATUSES),
                )
                .order_by(RequirementAnalysisTask.id.desc())
                .limit(1)
            )
            if active:
                raise RequirementServiceError(
                    "requirement_task_active", "该会话的需求方案正在生成"
                )
            has_customer_message = session.scalar(
                select(Message.id)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.direction == "inbound",
                    Message.content != "",
                )
                .limit(1)
            )
            if not has_customer_message:
                raise RequirementServiceError(
                    "insufficient_context", "当前会话还没有可分析的客户需求"
                )
            latest = session.scalar(
                select(RequirementDocumentVersion)
                .where(RequirementDocumentVersion.conversation_id == conversation_id)
                .order_by(RequirementDocumentVersion.version.desc())
                .limit(1)
            )
            if cleaned_change and not latest:
                raise RequirementServiceError(
                    "requirement_missing", "请先生成第一版需求文档"
                )
            mode = "revision" if cleaned_change else ("refresh" if latest else "initial")
            task = RequirementAnalysisTask(
                conversation_id=conversation_id,
                mode=mode,
                base_version=latest.version if latest else None,
                change_request=cleaned_change,
                status="pending",
                model=self.settings.requirement_analysis_model.strip() or None,
                reasoning_effort=(
                    self.settings.requirement_analysis_reasoning_effort.strip() or None
                ),
            )
            session.add(task)
            session.flush()
            session.add(
                OperationLog(
                    action="requirement_task_created",
                    detail=f"会话 {conversation_id} 创建需求分析任务 {task.id}（{mode}）",
                )
            )
            session.commit()
            task_id = task.id
        await self._queue.put(task_id)
        with self.database.session() as session:
            saved = session.get(RequirementAnalysisTask, task_id)
            assert saved
            return saved

    async def cancel(self, task_id: int) -> bool:
        running = False
        with self.database.session() as session:
            task = session.get(RequirementAnalysisTask, task_id)
            if not task or task.status not in ACTIVE_STATUSES:
                return False
            task.cancel_requested = True
            running = task.status == "running"
            if not running:
                task.status = "cancelled"
                task.finished_at = utcnow()
            session.commit()
        if running:
            await self.provider.cancel(f"requirement:{task_id}")
        return True

    def set_stage_progress(
        self,
        version_id: int,
        stage_sequence: int,
        stage_status: str,
    ) -> RequirementDocumentVersion:
        if stage_status not in STAGE_STATUSES:
            raise RequirementServiceError("invalid_stage_status", "无效的阶段状态")
        with self.database.session() as session:
            version = session.get(RequirementDocumentVersion, version_id)
            if not version:
                raise RequirementServiceError("requirement_version_not_found", "需求版本不存在")
            result = RequirementAnalysisResult.model_validate_json(version.structured_json)
            if stage_sequence not in {stage.sequence for stage in result.stages}:
                raise RequirementServiceError("stage_not_found", "需求阶段不存在")
            progress = self._load_progress(version.stage_progress_json)
            progress[str(stage_sequence)] = stage_status
            version.stage_progress_json = json.dumps(progress, ensure_ascii=False)
            session.add(
                OperationLog(
                    action="requirement_stage_updated",
                    detail=(
                        f"需求文档 {version.id} 阶段 {stage_sequence} "
                        f"更新为 {stage_status}"
                    ),
                )
            )
            session.commit()
            return version

    @staticmethod
    def _load_progress(value: str) -> dict[str, str]:
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return {
            str(key): str(status)
            for key, status in parsed.items()
            if str(status) in STAGE_STATUSES
        } if isinstance(parsed, dict) else {}

    async def _worker(self) -> None:
        while True:
            task_id = await self._queue.get()
            try:
                await self._run_task(task_id)
            finally:
                self._queue.task_done()

    async def _run_task(self, task_id: int) -> None:
        with self.database.session() as session:
            task = session.get(RequirementAnalysisTask, task_id)
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
            session.commit()

        try:
            selection = await self._resolve_model()
            context = self._build_context(task_id)
            prompt = (
                f"{REQUIREMENT_SYSTEM_TASK}\n\n"
                "以下是本次待分析的结构化 JSON：\n"
                f"{json.dumps(context, ensure_ascii=False, indent=2)}"
            )
            generated = await self.provider.generate_structured(
                prompt,
                result_type=RequirementAnalysisResult,
                task_key=f"requirement:{task_id}",
                model_selection=selection,
                timeout=self.settings.requirement_analysis_timeout_seconds,
            )
            assert isinstance(generated, RequirementAnalysisResult)
        except asyncio.CancelledError:
            self._return_to_pending(task_id)
            raise
        except AIProviderError as exc:
            if self._is_cancel_requested(task_id):
                self._mark_cancelled(task_id)
            else:
                self._fail(task_id, exc.code, exc.safe_message)
            return
        except Exception as exc:
            logger.exception("需求分析任务失败 task_id=%s", task_id)
            self._fail(task_id, "requirement_internal_error", f"需求分析失败：{type(exc).__name__}")
            return

        if self._is_cancel_requested(task_id):
            self._mark_cancelled(task_id)
            return
        version = self._complete(task_id, generated, selection)
        await self.notifier.notify(
            "鱼答：需求方案已生成",
            f"{version.title} · V{version.version}",
            "可在工作台查看分阶段计划",
        )
        if self.event_hub:
            self.event_hub.publish_nowait(
                {
                    "type": "requirement_completed",
                    "conversation_id": version.conversation_id,
                    "version_id": version.id,
                    "version": version.version,
                    "title": version.title,
                }
            )

    async def _resolve_model(self) -> AIModelSelection:
        requested_model = self.settings.requirement_analysis_model.strip() or "gpt-5.6-sol"
        requested_effort = (
            self.settings.requirement_analysis_reasoning_effort.strip() or "max"
        )
        options = await self.provider.available_models()
        option = next((item for item in options if item.model == requested_model), None)
        if not option:
            raise AIProviderError(
                "requirement_model_unavailable",
                f"当前 Codex 账号不可用需求分析模型 {requested_model}",
            )
        if requested_effort not in option.supported_reasoning_efforts:
            raise AIProviderError(
                "requirement_reasoning_unavailable",
                f"模型 {requested_model} 不支持推理档位 {requested_effort}",
            )
        return AIModelSelection(model=requested_model, reasoning_effort=requested_effort)

    def _build_context(self, task_id: int) -> dict[str, Any]:
        with self.database.session() as session:
            task = session.get(RequirementAnalysisTask, task_id)
            if not task:
                raise RequirementServiceError("requirement_task_not_found", "需求分析任务不存在")
            conversation = session.get(Conversation, task.conversation_id)
            if not conversation:
                raise RequirementServiceError("conversation_not_found", "会话不存在")
            rows = list(
                session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.received_at.desc(), Message.id.desc())
                    .limit(self.settings.requirement_analysis_max_messages)
                )
            )
            selected: list[dict[str, str]] = []
            remaining = self.settings.requirement_analysis_max_context_chars
            for message in rows:
                if remaining <= 0:
                    break
                content = message.content.strip()
                if not content:
                    continue
                clipped = content[:remaining]
                remaining -= len(clipped)
                selected.append(
                    {
                        "speaker": "customer" if message.direction == "inbound" else "seller",
                        "content": clipped,
                        "time": message.received_at.isoformat(),
                    }
                )
            selected.reverse()
            base_document: dict[str, Any] | None = None
            if task.base_version is not None:
                base = session.scalar(
                    select(RequirementDocumentVersion).where(
                        RequirementDocumentVersion.conversation_id == conversation.id,
                        RequirementDocumentVersion.version == task.base_version,
                    )
                )
                if base:
                    base_document = json.loads(base.structured_json)
            item = conversation.item
            return {
                "analysis_mode": task.mode,
                "conversation": {
                    "customer_name": conversation.customer_name,
                    "product": {
                        "title": item.title if item else "商品信息未同步",
                        "price": item.price if item and item.price else "未确认",
                        "description": item.description if item and item.description else "",
                    },
                    "messages": selected,
                },
                "current_document": base_document,
                "change_request": task.change_request,
                "current_time": datetime.now(SHANGHAI).isoformat(),
            }

    def _complete(
        self,
        task_id: int,
        result: RequirementAnalysisResult,
        selection: AIModelSelection,
    ) -> RequirementDocumentVersion:
        with self.database.session() as session:
            task = session.get(RequirementAnalysisTask, task_id)
            if not task:
                raise RequirementServiceError("requirement_task_not_found", "需求分析任务不存在")
            latest = session.scalar(
                select(RequirementDocumentVersion)
                .where(RequirementDocumentVersion.conversation_id == task.conversation_id)
                .order_by(RequirementDocumentVersion.version.desc())
                .limit(1)
            )
            next_version = (latest.version if latest else 0) + 1
            markdown = self.render_markdown(
                result,
                version=next_version,
                model=selection.model or "Codex default",
                reasoning_effort=selection.reasoning_effort,
            )
            progress = {str(stage.sequence): "pending" for stage in result.stages}
            version = RequirementDocumentVersion(
                conversation_id=task.conversation_id,
                version=next_version,
                title=result.document_title,
                readiness=result.readiness,
                change_summary=result.change_summary,
                structured_json=result.model_dump_json(),
                content_markdown=markdown,
                stage_progress_json=json.dumps(progress, ensure_ascii=False),
                model=selection.model or "default",
                reasoning_effort=selection.reasoning_effort,
            )
            session.add(version)
            session.flush()
            task.status = "completed"
            task.model = selection.model
            task.reasoning_effort = selection.reasoning_effort
            task.result_version = next_version
            task.finished_at = utcnow()
            session.add(
                OperationLog(
                    action=(
                        "requirement_revised"
                        if task.mode == "revision"
                        else "requirement_generated"
                    ),
                    detail=(
                        f"会话 {task.conversation_id} 需求文档 V{next_version} "
                        f"已由 {selection.model}/{selection.reasoning_effort} 生成"
                    ),
                )
            )
            session.commit()
            return version

    @staticmethod
    def render_markdown(
        result: RequirementAnalysisResult,
        *,
        version: int,
        model: str,
        reasoning_effort: str | None,
    ) -> str:
        def section(title: str, values: list[str]) -> list[str]:
            rows = [f"## {title}", ""]
            rows.extend([f"- {value}" for value in values] or ["- 暂无"])
            rows.append("")
            return rows

        lines = [
            f"# {result.document_title}",
            "",
            f"> 文档版本：V{version}",
            f"> 需求状态：{'可进入实施' if result.readiness == 'ready' else '仍需补充确认'}",
            f"> 分析模型：{model} / {reasoning_effort or 'default'}",
            "",
            "## 项目概述",
            "",
            result.executive_summary,
            "",
        ]
        lines += section("已确认需求", result.confirmed_requirements)
        lines += section("推测需求（待确认）", result.inferred_requirements)
        lines += section("项目范围", result.scope_items)
        lines += section("不在范围内", result.out_of_scope)
        lines += section("交付物", result.deliverables)
        lines += section("约束条件", result.constraints)
        lines += section("假设", result.assumptions)
        lines += section("待客户确认的问题", result.open_questions)
        lines += section("风险", result.risks)
        lines += section("总体验收标准", result.acceptance_criteria)
        lines += ["## 分阶段实施计划", ""]
        for stage in result.stages:
            lines += [
                f"### 阶段 {stage.sequence}：{stage.title}",
                "",
                f"**阶段目标：** {stage.objective}",
                "",
                "**工作项**",
                "",
                *[f"- {item}" for item in stage.work_items],
                "",
                "**交付物**",
                "",
                *[f"- {item}" for item in stage.deliverables],
                "",
                "**验收标准**",
                "",
                *[f"- {item}" for item in stage.acceptance_criteria],
                "",
                "**依赖**",
                "",
                *([f"- {item}" for item in stage.dependencies] or ["- 无"]),
                "",
            ]
        lines += ["## 本版变更说明", "", result.change_summary, ""]
        return "\n".join(lines)

    def _is_cancel_requested(self, task_id: int) -> bool:
        with self.database.session() as session:
            task = session.get(RequirementAnalysisTask, task_id)
            return bool(task and task.cancel_requested)

    def _mark_cancelled(self, task_id: int) -> None:
        with self.database.session() as session:
            task = session.get(RequirementAnalysisTask, task_id)
            if task:
                task.status = "cancelled"
                task.finished_at = utcnow()
                session.commit()

    def _return_to_pending(self, task_id: int) -> None:
        with self.database.session() as session:
            task = session.get(RequirementAnalysisTask, task_id)
            if task and not task.cancel_requested:
                task.status = "pending"
                task.started_at = None
                session.commit()

    def _fail(self, task_id: int, code: str, message: str) -> None:
        with self.database.session() as session:
            task = session.get(RequirementAnalysisTask, task_id)
            if not task:
                return
            task.status = "failed"
            task.error_code = code
            task.error_message = message
            task.finished_at = utcnow()
            session.add(
                OperationLog(
                    action="requirement_task_failed",
                    detail=f"需求分析任务 {task.id} 失败：{code}：{message}",
                )
            )
            session.commit()
