from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict
from datetime import timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from ..codex_runtime_schemas import (
    ManagedApprovalView,
    ManagedDiffView,
    ManagedRunCreateInput,
    ManagedRunView,
    ManagedRuntimeProjectView,
    RuntimeCapabilitiesView,
)
from ..codex_sync_schemas import CodexEventInput
from ..database import Database
from ..models import (
    BusinessProject,
    BusinessTask,
    CodexDevelopmentPlan,
    CodexProjectBinding,
    CodexRun,
    CodexRunApproval,
    CodexRuntimeMutationRequest,
    RequirementDocumentVersion,
    utcnow,
)
from .codex_runtime import CodexDevelopmentRuntime, RuntimeEvent, WorktreeError, WorktreeManager
from .codex_sync import CodexSyncError, CodexSyncService, sanitize_payload
from .codex_verification import CodexVerificationService


ACTIVE_STATUSES = {"pending", "starting", "running", "waiting_approval", "blocked"}
TASK_LOCK_STATUSES = ACTIVE_STATUSES | {"paused"}


class CodexDevelopmentService:
    def __init__(
        self,
        database: Database,
        sync: CodexSyncService,
        runtime: CodexDevelopmentRuntime,
        worktrees: WorktreeManager,
        *,
        verification: CodexVerificationService | None = None,
        default_model: str = "",
        default_reasoning_effort: str = "",
    ) -> None:
        self.database = database
        self.sync = sync
        self.runtime = runtime
        self.worktrees = worktrees
        self.verification = verification
        self.default_model = default_model
        self.default_reasoning_effort = default_reasoning_effort
        self._event_task: asyncio.Task[None] | None = None
        self._launch_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        now = utcnow()
        with self.database.session() as session:
            for run in session.scalars(
                select(CodexRun).where(
                    CodexRun.runtime_type != "external",
                    CodexRun.status.in_(TASK_LOCK_STATUSES),
                )
            ):
                if self.verification:
                    self.verification.close_active_interval(
                        session,
                        run,
                        stop_reason="restart",
                        ended_at=run.last_event_at,
                    )
                run.status = "paused"
                run.paused_at = now
            for approval in session.scalars(
                select(CodexRunApproval).where(CodexRunApproval.status == "pending")
            ):
                approval.status = "expired"
                approval.decided_at = now
            session.commit()
        self._event_task = asyncio.create_task(self._consume_events())

    async def close(self) -> None:
        launch_tasks = tuple(self._launch_tasks)
        for task in launch_tasks:
            task.cancel()
        if self._event_task:
            self._event_task.cancel()
        for task in launch_tasks:
            with suppress(asyncio.CancelledError):
                await task
        if self._event_task:
            with suppress(asyncio.CancelledError):
                await self._event_task
        await self.runtime.close()

    async def capabilities(self) -> RuntimeCapabilitiesView:
        result = await self.runtime.capabilities()
        return RuntimeCapabilitiesView(**asdict(result))

    @staticmethod
    def _approval_view(row: CodexRunApproval) -> ManagedApprovalView:
        return ManagedApprovalView(
            id=row.id,
            run_id=row.run_id,
            server_request_id=row.server_request_id,
            thread_id=row.thread_id,
            turn_id=row.turn_id,
            item_id=row.item_id,
            approval_kind=row.approval_kind,
            risk_level=row.risk_level,
            reason=row.reason,
            command=row.command,
            cwd=row.cwd,
            status=row.status,
            created_at=row.created_at,
            decided_at=row.decided_at,
        )

    def _run_view(self, session, run: CodexRun) -> ManagedRunView:
        approvals = list(
            session.scalars(
                select(CodexRunApproval)
                .where(CodexRunApproval.run_id == run.id)
                .order_by(CodexRunApproval.created_at.desc())
            )
        )
        return ManagedRunView(
            id=run.id,
            project_id=run.project_id,
            binding_id=run.binding_id,
            task_key=run.task_key,
            runtime_type=run.runtime_type,
            thread_id=run.thread_id,
            turn_id=run.turn_id,
            status=run.status,
            base_commit_sha=run.base_commit_sha,
            branch=run.branch,
            worktree_path=run.worktree_path,
            model=run.model,
            reasoning_effort=run.reasoning_effort,
            sandbox_mode=run.sandbox_mode,
            approval_mode=run.approval_mode,
            started_at=run.started_at,
            paused_at=run.paused_at,
            finished_at=run.finished_at,
            last_event_at=run.last_event_at,
            approvals=[self._approval_view(row) for row in approvals],
        )

    async def project_view(self, project_id: str) -> ManagedRuntimeProjectView:
        capabilities = await self.capabilities()
        sync_view = self.sync.project_sync(project_id)
        with self.database.session() as session:
            project = session.get(BusinessProject, project_id)
            if not project:
                raise CodexSyncError("project_missing", "项目不存在", 404)
            binding = session.scalar(
                select(CodexProjectBinding)
                .where(
                    CodexProjectBinding.project_id == project_id,
                    CodexProjectBinding.enabled.is_(True),
                )
                .order_by(CodexProjectBinding.updated_at.desc())
            )
            plan = session.scalar(
                select(CodexDevelopmentPlan)
                .where(
                    CodexDevelopmentPlan.project_id == project_id,
                    CodexDevelopmentPlan.status == "confirmed",
                )
                .order_by(CodexDevelopmentPlan.confirmed_at.desc())
            )
            runs = list(
                session.scalars(
                    select(CodexRun)
                    .where(
                        CodexRun.project_id == project_id,
                        CodexRun.runtime_type != "external",
                    )
                    .order_by(CodexRun.started_at.desc())
                    .limit(20)
                )
            )
            reasons: list[str] = []
            if not capabilities.available:
                reasons.append("当前 Codex App Server 不可用")
            task_contexts = self.sync.project_context(project_id).tasks
            if not task_contexts:
                reasons.append("项目还没有带稳定 task_key 的任务")
            if not binding:
                reasons.append("项目还没有启用的本地 Git 仓库绑定")
            if not plan:
                reasons.append("项目还没有人工确认的开发计划")
            binding_view = None
            if binding:
                actual_head = ""
                repository_dirty = False
                head_matches = False
                try:
                    _root, actual_head, repository_dirty = self.worktrees.inspect_repository(
                        binding.repository_path
                    )
                    head_matches = not binding.current_head_sha or binding.current_head_sha == actual_head
                except (OSError, WorktreeError):
                    reasons.append("已绑定仓库当前无法验证")
                binding_view = {
                    "id": binding.id,
                    "repository_name": Path(binding.repository_path).name,
                    "default_branch": binding.default_branch,
                    "current_head_sha": binding.current_head_sha,
                    "actual_head_sha": actual_head,
                    "repository_dirty": repository_dirty,
                    "head_matches": head_matches,
                }
                if actual_head and not head_matches:
                    reasons.append("仓库 HEAD 已变化，需要重新确认绑定")
            return ManagedRuntimeProjectView(
                project_id=project_id,
                runtime=capabilities,
                tasks=task_contexts,
                binding=binding_view,
                confirmed_plan_id=plan.id if plan else None,
                ready=not reasons,
                readiness_reasons=reasons,
                current_run=self._run_view(session, runs[0]) if runs else None,
                runs=[self._run_view(session, row) for row in runs],
                events=sync_view.events,
            )

    @staticmethod
    def _canonical(payload: dict[str, Any]) -> tuple[str, str]:
        value = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return value, hashlib.sha256(value.encode()).hexdigest()

    def _mutation_result(self, session, request_id: str, operation: str, digest: str) -> dict[str, Any] | None:
        existing = session.get(CodexRuntimeMutationRequest, request_id)
        if not existing:
            return None
        if existing.operation != operation or existing.payload_hash != digest:
            raise CodexSyncError("request_conflict", "请求编号已用于不同的运行操作", 409)
        return json.loads(existing.result_json)

    def _record_mutation(self, session, request_id: str, operation: str, digest: str, result: dict[str, Any]) -> None:
        session.add(
            CodexRuntimeMutationRequest(
                request_id=request_id,
                operation=operation,
                payload_hash=digest,
                result_json=json.dumps(result, ensure_ascii=False, sort_keys=True),
            )
        )

    async def create(self, payload: ManagedRunCreateInput) -> ManagedRunView:
        raw, digest = self._canonical(payload.model_dump(mode="json"))
        del raw
        run_id = "codex-run-" + hashlib.sha256(
            f"create\n{payload.request_id}".encode()
        ).hexdigest()[:32]
        with self.database.session() as session:
            replay = self._mutation_result(session, payload.request_id, "create", digest)
            if replay:
                existing = session.get(CodexRun, replay["run_id"])
                if not existing:
                    raise CodexSyncError("run_missing", "幂等运行记录不存在", 409)
                return self._run_view(session, existing)
            project = session.get(BusinessProject, payload.project_id)
            task = session.scalar(
                select(BusinessTask).where(
                    BusinessTask.project_id == payload.project_id,
                    BusinessTask.task_key == payload.task_key,
                )
            )
            binding = session.get(CodexProjectBinding, payload.binding_id)
            plan = session.scalar(
                select(CodexDevelopmentPlan)
                .where(
                    CodexDevelopmentPlan.project_id == payload.project_id,
                    CodexDevelopmentPlan.status == "confirmed",
                )
                .order_by(CodexDevelopmentPlan.confirmed_at.desc())
            )
            if not project or not task:
                raise CodexSyncError("task_missing", "任务不存在或没有稳定 task_key", 404)
            if not binding or not binding.enabled or binding.project_id != payload.project_id:
                raise CodexSyncError("binding_mismatch", "启用的仓库绑定不属于该项目", 409)
            if not plan:
                raise CodexSyncError("plan_missing", "项目还没有人工确认的开发计划", 409)
            running = session.scalar(
                select(CodexRun).where(
                    CodexRun.project_id == payload.project_id,
                    CodexRun.task_key == payload.task_key,
                    CodexRun.status.in_(ACTIVE_STATUSES),
                    CodexRun.runtime_type != "external",
                )
            )
            if running:
                raise CodexSyncError("run_active", "这个任务已有未结束的托管运行", 409)
            try:
                managed = self.worktrees.create(
                    repository_path=binding.repository_path,
                    project_id=payload.project_id,
                    task_key=payload.task_key,
                    run_id=run_id,
                    expected_head_sha=binding.current_head_sha,
                    acknowledge_dirty=payload.acknowledge_dirty_repository,
                )
            except (OSError, WorktreeError) as exc:
                raise CodexSyncError("worktree_failed", str(exc), 409) from None
            now = utcnow()
            run = CodexRun(
                id=run_id,
                project_id=payload.project_id,
                binding_id=binding.id,
                source="app_server",
                external_session_id=run_id,
                runtime_type="app_server",
                task_key=payload.task_key,
                base_commit_sha=managed.base_commit_sha,
                branch=managed.branch,
                worktree_path=str(managed.worktree_path),
                model=payload.model or self.default_model,
                reasoning_effort=payload.reasoning_effort or self.default_reasoning_effort,
                sandbox_mode=payload.sandbox_mode,
                approval_mode=payload.approval_mode,
                status="starting",
                started_at=now,
                last_event_at=now,
            )
            session.add(run)
            self._record_mutation(session, payload.request_id, "create", digest, {"run_id": run_id})
            session.commit()
            view = self._run_view(session, run)
        task = asyncio.create_task(self._launch(run_id))
        self._launch_tasks.add(task)
        task.add_done_callback(self._launch_tasks.discard)
        return view

    def _prompt(self, session, run: CodexRun) -> str:
        project = session.get(BusinessProject, run.project_id)
        task = session.scalar(
            select(BusinessTask).where(
                BusinessTask.project_id == run.project_id,
                BusinessTask.task_key == run.task_key,
            )
        )
        plan = session.scalar(
            select(CodexDevelopmentPlan)
            .where(
                CodexDevelopmentPlan.project_id == run.project_id,
                CodexDevelopmentPlan.status == "confirmed",
            )
            .order_by(CodexDevelopmentPlan.confirmed_at.desc())
        )
        if not project or not task or not plan:
            raise CodexSyncError("context_missing", "托管运行上下文已失效", 409)
        requirement = session.get(RequirementDocumentVersion, plan.requirement_version_id)
        document = json.loads(plan.structured_json)
        task_doc = next(
            (item for item in document.get("tasks", []) if item.get("task_key") == run.task_key),
            {},
        )
        requirement_summary = ""
        if requirement:
            req = json.loads(requirement.structured_json)
            requirement_summary = str(req.get("project_goal") or req.get("summary") or requirement.title)
        safe_context = {
            "project_objective": requirement_summary or project.name,
            "requirement_version": requirement.version if requirement else None,
            "development_plan_id": plan.id,
            "task_key": run.task_key,
            "task": {
                "title": task.title,
                "description": task_doc.get("description", ""),
                "depends_on": task_doc.get("depends_on", []),
                "acceptance_points": task_doc.get("acceptance_points", []),
                "expected_paths": task_doc.get("expected_paths", []),
                "test_commands": task_doc.get("test_commands", []),
                "risks": task_doc.get("risks", []),
            },
            "allowed_scope": task_doc.get("expected_paths", []),
            "forbidden_scope": ["unrelated modules", "business data", "credentials", "main workspace", "git history", "push/merge"],
            "compatibility": document.get("assumptions", []),
        }
        return (
            "You are running a single Xunying-managed development task in an isolated Git Worktree.\n"
            "Inspect existing code before editing. Work only on the specified task_key. Do not redesign the whole system, edit unrelated modules, modify Xunying project progress or verified status, commit, push, merge, or access credentials/business records. Run the listed tests. Xunying App Server events are authoritative; use Xunying MCP only when available for additional status context.\n\n"
            + json.dumps(safe_context, ensure_ascii=False, indent=2)
        )

    async def _launch(self, run_id: str) -> None:
        try:
            with self.database.session() as session:
                run = session.get(CodexRun, run_id)
                if not run:
                    return
                prompt = self._prompt(session, run)
                values = (run.worktree_path, run.model, run.sandbox_mode, run.approval_mode, run.reasoning_effort)
            created = await self.runtime.create_run(
                cwd=values[0], model=values[1], sandbox_mode=values[2], approval_mode=values[3],
                developer_instructions="Never call thread/shellCommand. Never commit, push, merge, or modify business data.",
            )
            with self.database.session() as session:
                run = session.get(CodexRun, run_id)
                if not run or run.status == "cancelled":
                    return
                run.thread_id = created.thread_id
                run.status = "running"
                if self.verification:
                    self.verification.open_active_interval(session, run)
                session.commit()
            await self._persist_event(run_id, RuntimeEvent("run_started", created.thread_id, payload={"summary": "Codex 托管运行已启动"}))
            turn = await self.runtime.start_turn(
                thread_id=created.thread_id, prompt=prompt, cwd=values[0], model=values[1], reasoning_effort=values[4]
            )
            with self.database.session() as session:
                run = session.get(CodexRun, run_id)
                if run and run.status != "cancelled":
                    run.turn_id = turn.turn_id
                    run.external_turn_id = turn.turn_id
                    session.commit()
        except Exception as exc:
            await self._persist_event(run_id, RuntimeEvent("run_failed", payload={"summary": str(exc)}))

    async def _consume_events(self) -> None:
        async for event in self.runtime.stream_events():
            with self.database.session() as session:
                run = None
                if event.thread_id:
                    run = session.scalar(
                        select(CodexRun).where(CodexRun.thread_id == event.thread_id)
                    )
                if not run and not event.thread_id:
                    run = session.scalar(
                        select(CodexRun)
                        .where(
                            CodexRun.runtime_type != "external",
                            CodexRun.status.in_(ACTIVE_STATUSES),
                        )
                        .order_by(CodexRun.started_at.desc())
                    )
                run_id = run.id if run else ""
            if run_id:
                await self._persist_event(run_id, event)

    @staticmethod
    def _risk(payload: dict[str, Any], worktree_path: str) -> tuple[str, str]:
        command = str(payload.get("command") or "").lower()
        cwd = str(payload.get("cwd") or "")
        category = "未知脚本或额外权限"
        if cwd:
            try:
                resolved = Path(cwd).expanduser().resolve(strict=False)
                worktree = Path(worktree_path).resolve(strict=False)
                if resolved != worktree and worktree not in resolved.parents:
                    category = "访问绑定目录以外路径"
            except OSError:
                category = "访问绑定目录以外路径"
        if re.search(r"\bgit\s+(reset|rebase|filter-branch|push\s+(-f|--force))\b|\bpush\b.*--force", command):
            category = "修改 Git 历史或强制推送"
        elif re.search(r"\brm\s+(-[^\s]*r[^\s]*f|-rf|-fr)\b|\bfind\b.*\s-delete\b", command):
            category = "删除大量文件"
        elif re.search(r"\b(sudo|brew\s+install|apt(-get)?\s+install|npm\s+install\s+-g|pipx?\s+install)\b", command):
            category = "安装系统软件"
        elif re.search(r"(^|[/~])(\.ssh|\.gnupg|\.aws|\.config/gcloud|keychains?)(/|$)", command + " " + cwd.lower()):
            category = "读取敏感目录"
        elif re.search(r"\b(curl|wget|scp|rsync|nc|ftp)\b.*(https?://|@|:)", command):
            category = "执行网络上传或外部传输"
        elif re.search(r"(^|[/_.-])(prod|production)([/_.-]|$)|\.env\.production", command + " " + cwd.lower()):
            category = "修改生产配置"
        return ("critical" if category != "未知脚本或额外权限" else "high", category)

    async def _persist_event(self, run_id: str, event: RuntimeEvent) -> None:
        time_revision = None
        with self.database.session() as session:
            run = session.get(CodexRun, run_id)
            if not run:
                return
            task_key = run.task_key
            if event.turn_id:
                run.turn_id = event.turn_id
                run.external_turn_id = event.turn_id
            if event.event_type == "approval_requested":
                clean = sanitize_payload(event.payload)
                risk_level, risk_category = self._risk(clean, run.worktree_path)
                reason = str(clean.get("reason") or "")
                approval = CodexRunApproval(
                    id=f"codex-approval-{uuid4()}",
                    run_id=run.id,
                    server_request_id=event.server_request_id,
                    thread_id=event.thread_id,
                    turn_id=event.turn_id,
                    item_id=event.item_id,
                    approval_kind=str(clean.get("approval_kind") or "command"),
                    risk_level=risk_level,
                    reason=f"{risk_category}：{reason}" if reason else risk_category,
                    command=str(clean.get("command") or ""),
                    cwd=str(clean.get("cwd") or ""),
                    payload_json=json.dumps(clean, ensure_ascii=False, sort_keys=True),
                )
                session.add(approval)
                if self.verification:
                    time_revision = self.verification.close_active_interval(
                        session, run, stop_reason="waiting_approval"
                    )
                run.status = "waiting_approval"
                session.commit()
            elif event.event_type == "task_blocked":
                if self.verification:
                    time_revision = self.verification.close_active_interval(
                        session, run, stop_reason="blocked"
                    )
                run.status = "blocked"
                session.commit()
            elif event.event_type in {"run_failed", "run_completed"}:
                if self.verification:
                    time_revision = self.verification.close_active_interval(
                        session, run, stop_reason=event.event_type
                    )
                run.status = "failed" if event.event_type == "run_failed" else "completed"
                run.finished_at = utcnow()
                session.commit()
            else:
                session.commit()
            project_id = run.project_id
            thread_id = run.thread_id or run.id
            turn_id = run.turn_id
        if time_revision is not None and self.verification:
            self.verification._publish(project_id, "project_time_updated", time_revision)
        payload = self._event_payload(event)
        if event.item_id:
            payload.setdefault("item_id", event.item_id)
        if event.event_type == "run_completed" and task_key:
            self.sync.ingest(
                CodexEventInput(
                    request_id=f"managed-{uuid4()}", event_id=f"managed-{uuid4()}",
                    project_id=project_id, run_id=run_id, source="app_server",
                    external_session_id=run_id, external_turn_id=turn_id,
                    event_type="task_implemented", task_key=task_key,
                    occurred_at=utcnow(), payload={"summary": "Codex 已完成本轮实现；仍需人工验收"},
                )
            )
        self.sync.ingest(
            CodexEventInput(
                request_id=f"managed-{uuid4()}", event_id=f"managed-{uuid4()}",
                project_id=project_id, run_id=run_id, source="app_server",
                external_session_id=run_id, external_turn_id=turn_id,
                event_type=event.event_type, task_key=task_key,
                occurred_at=utcnow(), payload=payload,
            )
        )

        command = str(payload.get("command") or "")
        if event.event_type == "command_completed" and re.search(
            r"(^|\s)(pytest|python\s+-m\s+pytest|npm\s+(run\s+)?test|pnpm\s+(run\s+)?test|yarn\s+test|cargo\s+test|go\s+test)(\s|$)",
            command,
            re.IGNORECASE,
        ):
            self.sync.ingest(
                CodexEventInput(
                    request_id=f"managed-{uuid4()}", event_id=f"managed-{uuid4()}",
                    project_id=project_id, run_id=run_id, source="app_server",
                    external_session_id=run_id, external_turn_id=turn_id,
                    event_type="test_reported", task_key=task_key,
                    occurred_at=utcnow(), payload={
                        "summary": payload.get("summary") or "测试命令已完成",
                        "command": command,
                        "exit_code": payload.get("exit_code"),
                        "output": payload.get("output", ""),
                    },
                )
            )

    @staticmethod
    def _event_payload(event: RuntimeEvent) -> dict[str, Any]:
        payload = dict(event.payload)
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        if item:
            command = item.get("command") or item.get("cmd")
            if isinstance(command, list):
                command = " ".join(str(part) for part in command)
            if command:
                payload.setdefault("command", str(command))
            payload.setdefault("cwd", item.get("cwd") or "")
            exit_code = item.get("exitCode")
            if isinstance(exit_code, int):
                payload.setdefault("exit_code", exit_code)
            output = item.get("aggregatedOutput") or item.get("output")
            if output:
                payload.setdefault("output", str(output))
            changes = item.get("changes") or item.get("files")
            if isinstance(changes, list):
                paths = []
                for change in changes:
                    if isinstance(change, dict):
                        path = change.get("path") or change.get("file")
                    else:
                        path = change
                    if path:
                        paths.append(str(path))
                if paths:
                    payload.setdefault("files", paths)
            elif isinstance(changes, dict):
                payload.setdefault("files", [str(path) for path in changes.keys()])
            summary = item.get("text") or item.get("summary") or item.get("status")
            if summary:
                payload.setdefault("summary", str(summary))
        if event.event_type == "approval_requested":
            payload.setdefault("summary", payload.get("reason") or "等待人工审批")
        return payload

    async def _action(self, run_id: str, request_id: str, operation: str) -> ManagedRunView:
        _, digest = self._canonical({"run_id": run_id, "request_id": request_id, "operation": operation})
        with self.database.session() as session:
            replay = self._mutation_result(session, request_id, operation, digest)
            run = session.get(CodexRun, run_id)
            if not run or run.runtime_type == "external":
                raise CodexSyncError("run_missing", "托管运行不存在", 404)
            if replay:
                return self._run_view(session, run)
            thread_id, turn_id = run.thread_id, run.turn_id
            if operation == "resume" and run.status not in {"paused", "blocked", "failed"}:
                raise CodexSyncError("invalid_status", "当前运行状态不能继续", 409)
            if operation in {"pause", "cancel"} and run.status not in ACTIVE_STATUSES:
                raise CodexSyncError("invalid_status", "当前运行状态不能中断", 409)
            self._record_mutation(session, request_id, operation, digest, {"run_id": run_id})
            session.commit()
            values = (run.worktree_path, run.model, run.sandbox_mode, run.approval_mode, run.reasoning_effort)
        if operation in {"pause", "cancel"}:
            await self.runtime.cancel_run(thread_id=thread_id, turn_id=turn_id)
            with self.database.session() as session:
                run = session.get(CodexRun, run_id)
                now = utcnow()
                time_revision = (
                    self.verification.close_active_interval(
                        session, run, stop_reason=operation, ended_at=now
                    )
                    if self.verification
                    else None
                )
                run.status = "paused" if operation == "pause" else "cancelled"
                run.paused_at = now if operation == "pause" else None
                run.finished_at = now if operation == "cancel" else None
                session.commit()
                view = self._run_view(session, run)
            if time_revision is not None and self.verification:
                self.verification._publish(view.project_id, "project_time_updated", time_revision)
            return view
        await self.runtime.resume_run(
            thread_id=thread_id, cwd=values[0], model=values[1], sandbox_mode=values[2], approval_mode=values[3]
        )
        turn = await self.runtime.start_turn(
            thread_id=thread_id,
            prompt="Continue only the same task_key from the persisted Xunying context. Reinspect the Worktree, do not commit or push, and run the listed tests.",
            cwd=values[0], model=values[1], reasoning_effort=values[4],
        )
        with self.database.session() as session:
            run = session.get(CodexRun, run_id)
            run.turn_id = turn.turn_id
            run.external_turn_id = turn.turn_id
            run.status = "running"
            run.paused_at = None
            run.finished_at = None
            if self.verification:
                self.verification.open_active_interval(session, run)
            session.commit()
            return self._run_view(session, run)

    async def pause(self, run_id: str, request_id: str) -> ManagedRunView:
        return await self._action(run_id, request_id, "pause")

    async def resume(self, run_id: str, request_id: str) -> ManagedRunView:
        return await self._action(run_id, request_id, "resume")

    async def cancel(self, run_id: str, request_id: str) -> ManagedRunView:
        return await self._action(run_id, request_id, "cancel")

    async def decide_approval(self, approval_id: str, request_id: str, decision: str) -> ManagedApprovalView:
        _, digest = self._canonical({"approval_id": approval_id, "request_id": request_id, "decision": decision})
        with self.database.session() as session:
            replay = self._mutation_result(session, request_id, "approval", digest)
            approval = session.get(CodexRunApproval, approval_id)
            if not approval:
                raise CodexSyncError("approval_missing", "审批请求不存在", 404)
            if replay:
                return self._approval_view(approval)
            if approval.status != "pending":
                raise CodexSyncError("approval_expired", "审批请求已经处理或失效", 409)
            server_request_id = approval.server_request_id
            self._record_mutation(session, request_id, "approval", digest, {"approval_id": approval_id})
            session.commit()
        if decision == "approve_once":
            await self.runtime.approve_action(server_request_id=server_request_id)
            status = "approved"
        else:
            await self.runtime.reject_action(server_request_id=server_request_id, cancel_turn=decision == "cancel")
            status = "cancelled" if decision == "cancel" else "rejected"
        with self.database.session() as session:
            approval = session.get(CodexRunApproval, approval_id)
            approval.status = status
            approval.decided_at = utcnow()
            run = session.get(CodexRun, approval.run_id)
            if run and run.status == "waiting_approval":
                run.status = "running" if decision != "cancel" else "cancelled"
                if decision != "cancel" and self.verification:
                    self.verification.open_active_interval(session, run)
                if decision == "cancel":
                    run.finished_at = utcnow()
            session.commit()
            return self._approval_view(approval)

    def diff(self, run_id: str) -> ManagedDiffView:
        with self.database.session() as session:
            run = session.get(CodexRun, run_id)
            if not run or run.runtime_type == "external":
                raise CodexSyncError("run_missing", "托管运行不存在", 404)
            try:
                value = self.worktrees.diff(run.worktree_path)
            except (OSError, WorktreeError) as exc:
                raise CodexSyncError("diff_failed", str(exc), 409) from None
            return ManagedDiffView(
                run_id=run.id, base_commit_sha=run.base_commit_sha,
                branch=run.branch, diff=value, truncated=len(value) >= 80_000,
            )

    def open_worktree(self, run_id: str) -> None:
        with self.database.session() as session:
            run = session.get(CodexRun, run_id)
            if not run or run.runtime_type == "external":
                raise CodexSyncError("run_missing", "托管运行不存在", 404)
            try:
                self.worktrees.open_in_finder(run.worktree_path)
            except (OSError, WorktreeError) as exc:
                raise CodexSyncError("open_failed", str(exc), 409) from None
