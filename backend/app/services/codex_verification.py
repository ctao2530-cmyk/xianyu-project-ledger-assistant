from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..codex_verification_schemas import (
    AcceptanceDecisionInput,
    AcceptanceEvidenceView,
    AcceptancePointView,
    DeliveryChecklistView,
    DeliveryItemView,
    DeliveryTaskView,
    GitLinkInput,
    GitLinkView,
    GitStateView,
    ManualTimeEntryInput,
    ProjectVerificationView,
    TestExecutionInput,
    TimeAdjustmentInput,
    TimeEntryView,
    TimeSummaryView,
)
from ..database import Database
from ..ledger import LedgerService, RevisionConflict
from ..models import (
    BusinessProject,
    BusinessTask,
    CodexAcceptanceEvidence,
    CodexAcceptanceMutationRequest,
    CodexAcceptancePoint,
    CodexAcceptanceStatusHistory,
    CodexDevelopmentPlan,
    CodexEvent,
    CodexProjectBinding,
    CodexRun,
    CodexRunActivityInterval,
    ProjectGitLink,
    ProjectTimeEntry,
    ProjectTimeMutationRequest,
    utcnow,
)
from .event_hub import EventHub
from .project_outcomes import ProjectOutcomeService
from .project_progress import ProjectProgressService
from .project_sample_formation import ProjectSampleFormationService


class CodexVerificationError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


def _json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class CodexVerificationService:
    """Acceptance, evidence, time, Git and delivery truth in one service."""

    OUTPUT_LIMIT = 64_000
    _SHELL_META = re.compile(r"[|;&<>`\n\r]|\$\(")
    _DENIED_COMMAND = re.compile(
        r"^(git\s+(commit|push|merge|reset|rebase|checkout|switch|clean|tag)|"
        r"(npm|pnpm|yarn|pip|pip3|uv|poetry|brew|apt|apt-get)\s+(install|add)|"
        r"(vercel|wrangler|firebase|netlify)\s+(deploy|publish)|"
        r"(rm|rmdir|dd|chmod|chown|kill|pkill|launchctl|sqlite3|psql|mysql|ssh|scp|rsync|curl|wget)\b)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        database: Database,
        ledger: LedgerService,
        event_hub: EventHub,
        *,
        progress: ProjectProgressService | None = None,
        outcomes: ProjectOutcomeService | None = None,
        sample_formation: ProjectSampleFormationService | None = None,
        managed_worktree_root: Path | None = None,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.event_hub = event_hub
        self.progress = progress or ProjectProgressService()
        self.outcomes = outcomes or ProjectOutcomeService()
        self.sample_formation = sample_formation or ProjectSampleFormationService(
            database,
            ledger,
            event_hub,
            outcomes=self.outcomes,
            progress=self.progress,
        )
        self.managed_worktree_root = (
            managed_worktree_root.expanduser().resolve(strict=False)
            if managed_worktree_root
            else None
        )

    @staticmethod
    def _canonical(operation: str, payload: dict[str, Any]) -> tuple[str, str]:
        raw = json.dumps(
            {"operation": operation, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return raw, hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _receipt(
        session: Session,
        model: type[CodexAcceptanceMutationRequest] | type[ProjectTimeMutationRequest],
        request_id: str,
        operation: str,
        digest: str,
    ) -> dict[str, Any] | None:
        existing = session.get(model, request_id)
        if existing is None:
            return None
        if existing.operation != operation or existing.payload_hash != digest:
            raise CodexVerificationError(
                "request_conflict", "请求编号已用于不同操作", 409
            )
        return _json(existing.result_json, {})

    @staticmethod
    def _record_receipt(
        session: Session,
        model: type[CodexAcceptanceMutationRequest] | type[ProjectTimeMutationRequest],
        request_id: str,
        operation: str,
        digest: str,
        result: dict[str, Any],
    ) -> None:
        session.add(
            model(
                request_id=request_id,
                operation=operation,
                payload_hash=digest,
                result_json=json.dumps(result, ensure_ascii=False, sort_keys=True),
            )
        )

    @staticmethod
    def _transition(
        session: Session,
        point: CodexAcceptancePoint,
        status: str,
        *,
        reason: str,
        request_id: str,
        evidence_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        if point.status == status:
            return
        previous = point.status
        point.status = status
        point.updated_at = occurred_at or utcnow()
        point.verified_at = point.updated_at if status == "verified" else None
        session.add(
            CodexAcceptanceStatusHistory(
                id=f"codex-acceptance-history-{uuid4()}",
                point_id=point.id,
                project_id=point.project_id,
                task_id=point.task_id,
                from_status=previous,
                to_status=status,
                reason=reason,
                evidence_id=evidence_id,
                request_id=request_id,
                occurred_at=occurred_at or utcnow(),
            )
        )

    def apply_persisted_event(
        self,
        session: Session,
        *,
        event: CodexEvent,
        run: CodexRun,
        task: BusinessTask | None,
        payload: dict[str, Any],
    ) -> None:
        """Derive evidence only after the immutable event row has an id.

        The caller owns the transaction and must commit before publishing to
        EventHub. Events without a mapped task intentionally stop here.
        """

        if task is None:
            return
        points = list(
            session.scalars(
                select(CodexAcceptancePoint).where(
                    CodexAcceptancePoint.task_id == task.id,
                    CodexAcceptancePoint.active.is_(True),
                )
            )
        )
        if event.event_type in {"task_complete", "task_implemented"}:
            for point in points:
                if point.status not in {"verified", "waived", "test_passed"}:
                    self._transition(
                        session,
                        point,
                        "implemented",
                        reason="Codex 声明实现完成；尚未验证",
                        request_id=event.event_id,
                        occurred_at=event.occurred_at,
                    )

        raw_files = payload.get("files")
        if not isinstance(raw_files, list):
            raw_files = payload.get("changed_files")
        files = raw_files if isinstance(raw_files, list) else []
        if event.event_type in {"file_change", "file_changed", "diff_updated"} and files:
            session.add(
                CodexAcceptanceEvidence(
                    id=f"codex-acceptance-evidence-{uuid4()}",
                    project_id=task.project_id,
                    task_id=task.id,
                    point_id=None,
                    point_key=task.task_key or task.id,
                    run_id=run.id,
                    source_event_id=event.id,
                    evidence_type="file_change",
                    file_paths_json=json.dumps(files, ensure_ascii=False),
                    test_summary=str(payload.get("summary") or ""),
                )
            )

        if event.event_type not in {"test_result", "test_reported"}:
            return
        exit_code = payload.get("exit_code")
        if not isinstance(exit_code, int):
            return
        test_points = [point for point in points if point.verification_type == "automated_test"]
        for point in test_points:
            evidence = CodexAcceptanceEvidence(
                id=f"codex-acceptance-evidence-{uuid4()}",
                project_id=task.project_id,
                task_id=task.id,
                point_id=point.id,
                point_key=point.point_key,
                run_id=run.id,
                source_event_id=event.id,
                evidence_type="automated_test",
                test_command=str(payload.get("command") or ""),
                exit_code=exit_code,
                test_summary=str(payload.get("summary") or payload.get("output") or "")[:4000],
                status="passed" if exit_code == 0 else "failed",
            )
            session.add(evidence)
            session.flush()
            if point.status not in {"verified", "waived"}:
                self._transition(
                    session,
                    point,
                    "test_passed" if exit_code == 0 else "failed",
                    reason="自动测试通过" if exit_code == 0 else "自动测试失败",
                    request_id=event.event_id,
                    evidence_id=evidence.id,
                    occurred_at=event.occurred_at,
                )

    def _sync_task_time(
        self,
        session: Session,
        task: BusinessTask,
        *,
        expected_revision: int | None,
    ) -> int:
        revision, snapshot = self.ledger.get_in_session(session)
        if expected_revision is not None and revision != expected_revision:
            raise RevisionConflict(revision)
        total = float(
            session.scalar(
                select(func.coalesce(func.sum(ProjectTimeEntry.hours), 0.0)).where(
                    ProjectTimeEntry.task_id == task.id
                )
            )
            or 0.0
        )
        if total < -1e-8:
            raise CodexVerificationError(
                "negative_time", "工时修正不能使任务累计工时小于 0", 409
            )
        task.actual_hours = round(max(0.0, total), 6)
        row = next(
            (item for item in snapshot["tasks"] if str(item.get("id") or "") == task.id),
            None,
        )
        if row is None:
            raise CodexVerificationError("task_snapshot_missing", "账本任务不存在", 409)
        row["actualHours"] = task.actual_hours
        new_revision, _ = self.ledger.save_in_session(
            session,
            snapshot,
            revision,
            trusted_delivery_sync=True,
        )
        return new_revision

    def _advance_revision(
        self,
        session: Session,
        *,
        expected_revision: int | None = None,
    ) -> int:
        revision, snapshot = self.ledger.get_in_session(session)
        if expected_revision is not None and revision != expected_revision:
            raise RevisionConflict(revision)
        new_revision, _ = self.ledger.save_in_session(
            session,
            snapshot,
            revision,
            trusted_delivery_sync=True,
        )
        return new_revision

    def open_active_interval(
        self,
        session: Session,
        run: CodexRun,
        *,
        started_at: datetime | None = None,
    ) -> CodexRunActivityInterval | None:
        existing = session.scalar(
            select(CodexRunActivityInterval).where(
                CodexRunActivityInterval.run_id == run.id,
                CodexRunActivityInterval.ended_at.is_(None),
            )
        )
        if existing:
            return None
        task = session.scalar(
            select(BusinessTask).where(
                BusinessTask.project_id == run.project_id,
                BusinessTask.task_key == run.task_key,
            )
        ) if run.task_key else None
        interval = CodexRunActivityInterval(
            id=f"codex-activity-{uuid4()}",
            run_id=run.id,
            project_id=run.project_id,
            task_id=task.id if task else None,
            started_at=started_at or utcnow(),
        )
        session.add(interval)
        return interval

    def close_active_interval(
        self,
        session: Session,
        run: CodexRun,
        *,
        stop_reason: str,
        ended_at: datetime | None = None,
    ) -> int | None:
        interval = session.scalar(
            select(CodexRunActivityInterval).where(
                CodexRunActivityInterval.run_id == run.id,
                CodexRunActivityInterval.ended_at.is_(None),
            )
        )
        if interval is None:
            return None
        end = ended_at or utcnow()
        seconds = max(0.0, (_aware(end) - _aware(interval.started_at)).total_seconds())
        interval.ended_at = end
        interval.stop_reason = stop_reason
        entry = ProjectTimeEntry(
            id=f"codex-time-{interval.id}",
            project_id=interval.project_id,
            task_id=interval.task_id,
            run_id=run.id,
            activity_interval_id=interval.id,
            category="development",
            source="codex_run",
            hours=round(seconds / 3600.0, 6),
            note=f"Codex Run 活跃区间：{stop_reason}",
            started_at=interval.started_at,
            ended_at=end,
            occurred_at=end,
        )
        session.add(entry)
        session.flush()
        if interval.task_id:
            task = session.get(BusinessTask, interval.task_id)
            if task:
                return self._sync_task_time(session, task, expected_revision=None)
        return None

    def decide(
        self,
        point_id: str,
        payload: AcceptanceDecisionInput,
    ) -> ProjectVerificationView:
        operation = "acceptance_decision"
        _, digest = self._canonical(operation, payload.model_dump(mode="json"))
        with self.database.session() as session:
            replay = self._receipt(
                session, CodexAcceptanceMutationRequest, payload.request_id, operation, digest
            )
            point = session.get(CodexAcceptancePoint, point_id)
            if point is None or not point.active:
                raise CodexVerificationError("point_missing", "验收点不存在", 404)
            if replay:
                project_id = str(replay.get("project_id") or point.project_id)
                return self._view_in_session(session, project_id)
            revision, _snapshot = self.ledger.get_in_session(session)
            if revision != payload.expected_revision:
                raise RevisionConflict(revision)
            if payload.status in {"failed", "waived"} and not payload.reason.strip():
                raise CodexVerificationError("reason_required", "驳回或放弃必须填写原因")
            if payload.status != "waived" and payload.waived_counts:
                raise CodexVerificationError(
                    "waiver_invalid", "只有 waived 状态可以设置 waived_counts"
                )
            evidence_id = None
            if payload.status == "verified":
                evidence = CodexAcceptanceEvidence(
                    id=f"codex-acceptance-evidence-{uuid4()}",
                    project_id=point.project_id,
                    task_id=point.task_id,
                    point_id=point.id,
                    point_key=point.point_key,
                    evidence_type="manual_check",
                    manual_note=payload.reason.strip() or "人工确认满足验收条件",
                    status="verified",
                    verified_at=utcnow(),
                )
                session.add(evidence)
                session.flush()
                evidence_id = evidence.id
            point.waived_counts = payload.waived_counts if payload.status == "waived" else False
            point.waiver_reason = payload.reason.strip() if payload.status == "waived" else ""
            self._transition(
                session,
                point,
                payload.status,
                reason=payload.reason.strip() or "人工重新打开验收点",
                request_id=payload.request_id,
                evidence_id=evidence_id,
            )
            new_revision, _progress = self.progress.sync_verified_progress(
                session,
                self.ledger,
                point.project_id,
                expected_revision=revision,
            )
            self._record_receipt(
                session,
                CodexAcceptanceMutationRequest,
                payload.request_id,
                operation,
                digest,
                {"project_id": point.project_id, "revision": new_revision},
            )
            session.commit()
            project_id = point.project_id
        self._publish(project_id, "acceptance_updated", new_revision)
        return self.view(project_id)

    def add_time(
        self,
        project_id: str,
        payload: ManualTimeEntryInput,
    ) -> ProjectVerificationView:
        operation = "manual_time"
        _, digest = self._canonical(operation, payload.model_dump(mode="json"))
        with self.database.session() as session:
            replay = self._receipt(
                session, ProjectTimeMutationRequest, payload.request_id, operation, digest
            )
            task = session.get(BusinessTask, payload.task_id)
            if task is None or task.project_id != project_id:
                raise CodexVerificationError("task_missing", "任务不存在", 404)
            if replay:
                return self._view_in_session(session, project_id)
            revision, _ = self.ledger.get_in_session(session)
            if revision != payload.expected_revision:
                raise RevisionConflict(revision)
            entry = ProjectTimeEntry(
                id=f"project-time-{uuid4()}",
                project_id=project_id,
                task_id=task.id,
                category=payload.category,
                source="manual",
                hours=round(float(payload.hours), 6),
                note=payload.note,
                occurred_at=payload.occurred_at or utcnow(),
            )
            session.add(entry)
            session.flush()
            new_revision = self._sync_task_time(
                session, task, expected_revision=payload.expected_revision
            )
            self._record_receipt(
                session,
                ProjectTimeMutationRequest,
                payload.request_id,
                operation,
                digest,
                {"project_id": project_id, "entry_id": entry.id, "revision": new_revision},
            )
            session.commit()
        self._publish(project_id, "project_time_updated", new_revision)
        return self.view(project_id)

    def adjust_time(
        self,
        entry_id: str,
        payload: TimeAdjustmentInput,
    ) -> ProjectVerificationView:
        operation = "time_adjustment"
        _, digest = self._canonical(operation, {"entry_id": entry_id, **payload.model_dump(mode="json")})
        with self.database.session() as session:
            replay = self._receipt(
                session, ProjectTimeMutationRequest, payload.request_id, operation, digest
            )
            original = session.get(ProjectTimeEntry, entry_id)
            if original is None or original.task_id is None:
                raise CodexVerificationError("time_entry_missing", "工时记录不存在", 404)
            task = session.get(BusinessTask, original.task_id)
            if task is None:
                raise CodexVerificationError("task_missing", "任务不存在", 404)
            if replay:
                return self._view_in_session(session, original.project_id)
            revision, _ = self.ledger.get_in_session(session)
            if revision != payload.expected_revision:
                raise RevisionConflict(revision)
            current_total = float(
                session.scalar(
                    select(func.coalesce(func.sum(ProjectTimeEntry.hours), 0.0)).where(
                        ProjectTimeEntry.task_id == task.id
                    )
                )
                or 0.0
            )
            if current_total + float(payload.hours_delta) < -1e-8:
                raise CodexVerificationError(
                    "negative_time", "工时修正不能使任务累计工时小于 0", 409
                )
            adjustment = ProjectTimeEntry(
                id=f"project-time-adjustment-{uuid4()}",
                project_id=original.project_id,
                task_id=task.id,
                run_id=original.run_id,
                adjustment_of_id=original.id,
                category=original.category,
                source="adjustment",
                hours=round(float(payload.hours_delta), 6),
                note=payload.reason,
                occurred_at=utcnow(),
            )
            session.add(adjustment)
            session.flush()
            new_revision = self._sync_task_time(
                session, task, expected_revision=payload.expected_revision
            )
            self._record_receipt(
                session,
                ProjectTimeMutationRequest,
                payload.request_id,
                operation,
                digest,
                {"project_id": original.project_id, "entry_id": adjustment.id, "revision": new_revision},
            )
            session.commit()
            project_id = original.project_id
        self._publish(project_id, "project_time_updated", new_revision)
        return self.view(project_id)

    @staticmethod
    def _git(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(path), *args],
            text=True,
            capture_output=True,
            timeout=5,
            check=check,
        )

    def _git_state(self, session: Session, project_id: str) -> GitStateView:
        binding = session.scalar(
            select(CodexProjectBinding)
            .where(
                CodexProjectBinding.project_id == project_id,
                CodexProjectBinding.enabled.is_(True),
            )
            .order_by(CodexProjectBinding.updated_at.desc())
        )
        if not binding:
            return GitStateView(
                available=False, repository_name="", branch="", base_commit="",
                current_commit="", dirty=False, changed_files=[], commits=[],
                error="项目未绑定本地 Git 仓库",
            )
        path = Path(binding.repository_path).expanduser().resolve(strict=False)
        try:
            current = self._git(path, "rev-parse", "HEAD").stdout.strip()
            branch = self._git(path, "branch", "--show-current").stdout.strip()
            status = self._git(path, "status", "--porcelain", "--untracked-files=normal").stdout
            changed = [line[3:].strip() for line in status.splitlines() if len(line) > 3][:200]
            log = self._git(path, "log", "-10", "--pretty=format:%H%x1f%s%x1f%aI").stdout
            commits = []
            for line in log.splitlines():
                parts = line.split("\x1f", 2)
                if len(parts) == 3:
                    commits.append({"sha": parts[0], "subject": parts[1][:300], "authored_at": parts[2]})
            latest_run = session.scalar(
                select(CodexRun)
                .where(CodexRun.project_id == project_id, CodexRun.base_commit_sha != "")
                .order_by(CodexRun.started_at.desc())
            )
            return GitStateView(
                available=True,
                repository_name=path.name,
                branch=branch,
                base_commit=latest_run.base_commit_sha if latest_run else binding.current_head_sha,
                current_commit=current,
                dirty=bool(status.strip()),
                changed_files=changed,
                commits=commits,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return GitStateView(
                available=False, repository_name=path.name, branch="", base_commit="",
                current_commit="", dirty=False, changed_files=[], commits=[],
                error=f"本地 Git 状态不可读：{type(exc).__name__}",
            )

    def link_git(self, project_id: str, payload: GitLinkInput) -> ProjectVerificationView:
        operation = "git_link"
        _, digest = self._canonical(operation, payload.model_dump(mode="json"))
        with self.database.session() as session:
            replay = self._receipt(
                session, CodexAcceptanceMutationRequest, payload.request_id, operation, digest
            )
            task = session.get(BusinessTask, payload.task_id)
            point = session.get(CodexAcceptancePoint, payload.point_id) if payload.point_id else None
            if task is None or task.project_id != project_id:
                raise CodexVerificationError("task_missing", "任务不存在", 404)
            if point and (point.project_id != project_id or point.task_id != task.id):
                raise CodexVerificationError("point_mismatch", "验收点不属于该任务", 409)
            if replay:
                return self._view_in_session(session, project_id)
            revision, _ = self.ledger.get_in_session(session)
            if revision != payload.expected_revision:
                raise RevisionConflict(revision)
            binding = session.scalar(
                select(CodexProjectBinding).where(
                    CodexProjectBinding.project_id == project_id,
                    CodexProjectBinding.enabled.is_(True),
                )
            )
            if binding is None:
                raise CodexVerificationError("binding_missing", "项目未绑定 Git 仓库", 409)
            path = Path(binding.repository_path).expanduser().resolve(strict=False)
            try:
                full_sha = self._git(path, "rev-parse", "--verify", f"{payload.commit_sha}^{{commit}}").stdout.strip()
                branch = self._git(path, "branch", "--show-current").stdout.strip()
                pushed = bool(self._git(path, "branch", "-r", "--contains", full_sha).stdout.strip())
                merged = False
                default_ref = binding.default_branch.strip()
                if default_ref:
                    result = self._git(path, "merge-base", "--is-ancestor", full_sha, default_ref, check=False)
                    merged = result.returncode == 0
            except (OSError, subprocess.SubprocessError):
                raise CodexVerificationError("commit_missing", "提交不在当前本地仓库中", 409) from None
            status = "merged" if merged else "pushed" if pushed else "committed"
            link = ProjectGitLink(
                id=f"project-git-link-{uuid4()}", project_id=project_id,
                task_id=task.id, point_id=point.id if point else None,
                commit_sha=full_sha, branch=branch, status=status,
                note=payload.note, request_id=payload.request_id,
            )
            session.add(link)
            if point:
                session.add(
                    CodexAcceptanceEvidence(
                        id=f"codex-acceptance-evidence-{uuid4()}",
                        project_id=project_id, task_id=task.id, point_id=point.id,
                        point_key=point.point_key, evidence_type="git_commit",
                        commit_sha=full_sha, manual_note=payload.note,
                    )
                )
            new_revision = self._advance_revision(
                session,
                expected_revision=payload.expected_revision,
            )
            self._record_receipt(
                session, CodexAcceptanceMutationRequest, payload.request_id,
                operation, digest, {"project_id": project_id, "revision": new_revision},
            )
            session.commit()
        self._publish(project_id, "project_git_linked", new_revision)
        return self.view(project_id)

    @classmethod
    def _test_argv(cls, command: str) -> list[str]:
        value = command.strip()
        if (
            cls._SHELL_META.search(value)
            or cls._DENIED_COMMAND.search(value)
            or re.search(r"\b(deploy|publish|release|upload|production)\b", value, re.IGNORECASE)
        ):
            raise CodexVerificationError("test_command_denied", "测试命令包含高风险或 Shell 操作")
        try:
            argv = shlex.split(value, posix=True)
        except ValueError:
            raise CodexVerificationError("test_command_invalid", "测试命令无法安全解析") from None
        if not argv or any(part in {"|", "&&", ";", ">", ">>"} for part in argv):
            raise CodexVerificationError("test_command_invalid", "测试命令无法安全解析")
        executable = Path(argv[0]).name.lower()
        safe = False
        if executable in {"pytest", "py.test"}:
            safe = True
        elif executable in {"python", "python3"}:
            if len(argv) >= 3 and argv[1:3] == ["-m", "pytest"]:
                safe = True
            elif len(argv) >= 2 and not argv[1].startswith("-"):
                script = Path(argv[1])
                safe = (
                    not script.is_absolute()
                    and ".." not in script.parts
                    and script.suffix == ".py"
                    and any(marker in script.name.lower() for marker in ("test", "check", "verify"))
                )
        elif executable in {"npm", "pnpm", "yarn"}:
            safe = len(argv) >= 2 and (argv[1] == "test" or argv[1] == "run")
        elif executable in {
            "cargo", "go", "swift", "dotnet", "mvn", "gradle", "gradlew", "node", "make", "test"
        }:
            safe = (
                executable == "test"
                or "test" in [part.lower() for part in argv[1:3]]
                or (executable == "node" and "--test" in argv[1:])
            )
        if not safe:
            raise CodexVerificationError(
                "test_command_denied",
                "只允许经确认的测试运行器或项目内检查脚本",
            )
        return argv

    async def run_test(self, project_id: str, payload: TestExecutionInput) -> ProjectVerificationView:
        operation = "confirmed_test"
        _, digest = self._canonical(operation, {"project_id": project_id, **payload.model_dump(mode="json")})
        with self.database.session() as session:
            replay = self._receipt(
                session, CodexAcceptanceMutationRequest, payload.request_id, operation, digest
            )
            point = session.get(CodexAcceptancePoint, payload.point_id)
            if point is None or point.project_id != project_id or not point.active:
                raise CodexVerificationError("point_missing", "验收点不存在", 404)
            if replay:
                return self._view_in_session(session, project_id)
            revision, _ = self.ledger.get_in_session(session)
            if revision != payload.expected_revision:
                raise RevisionConflict(revision)
            task = session.get(BusinessTask, point.task_id)
            if task is None:
                raise CodexVerificationError("task_missing", "任务不存在", 404)
            commands = _json(task.test_commands_json, [])
            allowed = [str(row.get("command") if isinstance(row, dict) else row).strip() for row in commands]
            if payload.command.strip() not in allowed:
                raise CodexVerificationError(
                    "test_not_confirmed", "测试命令必须精确来自人工确认的开发计划", 409
                )
            run = session.scalar(
                select(CodexRun)
                .where(
                    CodexRun.project_id == project_id,
                    CodexRun.task_key == task.task_key,
                    CodexRun.runtime_type != "external",
                    CodexRun.worktree_path != "",
                )
                .order_by(CodexRun.started_at.desc())
            )
            if run is None:
                raise CodexVerificationError("worktree_missing", "该任务没有可用的托管 Worktree", 409)
            try:
                cwd = Path(run.worktree_path).expanduser().resolve(strict=True)
            except OSError:
                raise CodexVerificationError(
                    "worktree_missing", "该任务的托管 Worktree 已不可用", 409
                ) from None
            if (
                self.managed_worktree_root is not None
                and self.managed_worktree_root not in cwd.parents
            ):
                raise CodexVerificationError(
                    "worktree_outside_managed_root",
                    "测试目录不在循营托管 Worktree 根目录内",
                    409,
                )
            if not (cwd / ".git").exists():
                raise CodexVerificationError(
                    "worktree_invalid", "测试目录不是有效的托管 Git Worktree", 409
                )
            argv = self._test_argv(payload.command)
            run_id = run.id
            task_id = task.id
            point_key = point.point_key
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async def collect_output() -> bytes:
            chunks: list[bytes] = []
            captured = 0
            assert process.stdout is not None
            while True:
                chunk = await process.stdout.read(8192)
                if not chunk:
                    break
                if captured < self.OUTPUT_LIMIT:
                    kept = chunk[: self.OUTPUT_LIMIT - captured]
                    chunks.append(kept)
                    captured += len(kept)
            await process.wait()
            return b"".join(chunks)
        try:
            output = await asyncio.wait_for(collect_output(), payload.timeout_seconds)
        except TimeoutError:
            process.kill()
            output = await collect_output()
            exit_code = -9
            summary = "测试执行超时并已终止"
        else:
            exit_code = int(process.returncode or 0)
            summary = "测试通过" if exit_code == 0 else "测试失败"
        bounded = output.decode("utf-8", errors="replace")
        with self.database.session() as session:
            point = session.get(CodexAcceptancePoint, payload.point_id)
            if point is None:
                raise CodexVerificationError("point_missing", "验收点不存在", 404)
            evidence = CodexAcceptanceEvidence(
                id=f"codex-acceptance-evidence-{uuid4()}", project_id=project_id,
                task_id=task_id, point_id=point.id, point_key=point_key,
                run_id=run_id, evidence_type="automated_test",
                test_command=payload.command, exit_code=exit_code,
                test_summary=f"{summary}\n{bounded}"[: self.OUTPUT_LIMIT],
                status="passed" if exit_code == 0 else "failed",
            )
            session.add(evidence)
            session.flush()
            if point.status not in {"verified", "waived"}:
                self._transition(
                    session, point, "test_passed" if exit_code == 0 else "failed",
                    reason=summary, request_id=payload.request_id, evidence_id=evidence.id,
                )
            current_revision = self._advance_revision(session)
            self._record_receipt(
                session, CodexAcceptanceMutationRequest, payload.request_id,
                operation, digest, {"project_id": project_id, "revision": current_revision},
            )
            session.commit()
        self._publish(project_id, "acceptance_test_recorded", current_revision)
        return self.view(project_id)

    @staticmethod
    def _evidence_view(row: CodexAcceptanceEvidence) -> AcceptanceEvidenceView:
        files = _json(row.file_paths_json, [])
        return AcceptanceEvidenceView(
            id=row.id, point_id=row.point_id, point_key=row.point_key,
            run_id=row.run_id, evidence_type=row.evidence_type,
            file_paths=[str(item) for item in files if isinstance(item, str)],
            test_command=row.test_command, exit_code=row.exit_code,
            test_summary=row.test_summary, commit_sha=row.commit_sha,
            manual_note=row.manual_note, status=row.status,
            created_at=row.created_at, verified_at=row.verified_at,
        )

    @staticmethod
    def _time_view(row: ProjectTimeEntry) -> TimeEntryView:
        return TimeEntryView(
            id=row.id, task_id=row.task_id, run_id=row.run_id,
            category=row.category, source=row.source, hours=round(float(row.hours), 6),
            note=row.note, adjustment_of_id=row.adjustment_of_id,
            started_at=row.started_at, ended_at=row.ended_at, occurred_at=row.occurred_at,
        )

    def _view_in_session(self, session: Session, project_id: str) -> ProjectVerificationView:
        project = session.get(BusinessProject, project_id)
        if project is None:
            raise CodexVerificationError("project_missing", "项目不存在", 404)
        revision, _ = self.ledger.get_in_session(session)
        progress = self.progress.calculate(session, project_id)
        tasks = list(
            session.scalars(
                select(BusinessTask)
                .where(BusinessTask.project_id == project_id)
                .order_by(BusinessTask.id)
            )
        )
        task_by_id = {task.id: task for task in tasks}
        points = list(
            session.scalars(
                select(CodexAcceptancePoint)
                .where(CodexAcceptancePoint.project_id == project_id)
                .order_by(CodexAcceptancePoint.task_id, CodexAcceptancePoint.point_key)
            )
        )
        evidence = list(
            session.scalars(
                select(CodexAcceptanceEvidence)
                .where(CodexAcceptanceEvidence.project_id == project_id)
                .order_by(CodexAcceptanceEvidence.created_at.desc())
            )
        )
        evidence_by_point: dict[str, list[CodexAcceptanceEvidence]] = defaultdict(list)
        for row in evidence:
            if row.point_id:
                evidence_by_point[row.point_id].append(row)
        point_views = [
            AcceptancePointView(
                id=point.id, task_id=point.task_id,
                task_key=task_by_id.get(point.task_id).task_key if task_by_id.get(point.task_id) else None,
                task_title=task_by_id.get(point.task_id).title if task_by_id.get(point.task_id) else "已移除任务",
                point_key=point.point_key, title=point.title,
                verification_type=point.verification_type, status=point.status,
                source=point.source,
                point_weight=point.point_weight, waived_counts=point.waived_counts,
                waiver_reason=point.waiver_reason, active=point.active,
                verified_at=point.verified_at, updated_at=point.updated_at,
                evidence=[self._evidence_view(row) for row in evidence_by_point.get(point.id, [])],
            )
            for point in points
        ]
        entries = list(
            session.scalars(
                select(ProjectTimeEntry)
                .where(ProjectTimeEntry.project_id == project_id)
                .order_by(ProjectTimeEntry.occurred_at.desc())
            )
        )
        by_category: dict[str, float] = defaultdict(float)
        for entry in entries:
            by_category[entry.category] += float(entry.hours)
        total_hours = sum(float(entry.hours) for entry in entries)
        codex_hours = sum(float(entry.hours) for entry in entries if entry.source == "codex_run")
        estimated = max(0.0, float(project.estimated_hours or 0.0))
        time_view = TimeSummaryView(
            total_hours=round(total_hours, 4), codex_hours=round(codex_hours, 4),
            manual_hours=round(total_hours - codex_hours, 4),
            by_category={key: round(value, 4) for key, value in sorted(by_category.items())},
            estimated_hours=round(estimated, 4), variance_hours=round(total_hours - estimated, 4),
            variance_percent=round((total_hours - estimated) / estimated * 100, 2) if estimated > 0 else None,
            entries=[self._time_view(row) for row in entries],
        )
        git_links = list(
            session.scalars(
                select(ProjectGitLink)
                .where(ProjectGitLink.project_id == project_id)
                .order_by(ProjectGitLink.created_at.desc())
            )
        )
        git_link_views = [
            GitLinkView(
                id=row.id, task_id=row.task_id, point_id=row.point_id,
                commit_sha=row.commit_sha, branch=row.branch, status=row.status,
                note=row.note, created_at=row.created_at,
            )
            for row in git_links
        ]
        plan = session.scalar(
            select(CodexDevelopmentPlan)
            .where(
                CodexDevelopmentPlan.project_id == project_id,
                CodexDevelopmentPlan.status == "confirmed",
            )
            .order_by(CodexDevelopmentPlan.confirmed_at.desc())
        )
        document = _json(plan.structured_json, {}) if plan else {}
        points_by_task: dict[str, list[CodexAcceptancePoint]] = defaultdict(list)
        for point in points:
            if point.active:
                points_by_task[point.task_id].append(point)
        links_by_task: dict[str, list[ProjectGitLink]] = defaultdict(list)
        for link in git_links:
            links_by_task[link.task_id].append(link)
        task_delivery_views: list[DeliveryTaskView] = []
        unresolved: list[str] = []
        for task in tasks:
            if not task.delivery_scope_active:
                continue
            task_points = points_by_task.get(task.id, [])
            open_issues = [
                f"{point.point_key}：{point.status}"
                for point in task_points
                if point.status not in {"verified", "waived"}
            ]
            unresolved.extend(open_issues)
            task_delivery_views.append(
                DeliveryTaskView(
                    task_id=task.id, task_key=task.task_key, title=task.title,
                    estimated_hours=float(task.estimated_hours), actual_hours=float(task.actual_hours),
                    acceptance_total=len(task_points),
                    acceptance_verified=sum(1 for point in task_points if point.status == "verified"),
                    acceptance_waived=sum(1 for point in task_points if point.status == "waived"),
                    tests_passed=sum(
                        1 for point in task_points
                        if any(row.evidence_type == "automated_test" and row.exit_code == 0 for row in evidence_by_point.get(point.id, []))
                    ),
                    commits=[link.commit_sha for link in links_by_task.get(task.id, [])],
                    open_issues=open_issues,
                )
            )
        task_doc_by_key = {
            str(row.get("task_key") or ""): row
            for row in document.get("tasks", [])
            if isinstance(row, dict)
        }
        stage_deliverables = {
            str(row.get("stage_key") or ""): [str(key) for key in row.get("deliverable_keys", [])]
            for row in document.get("stages", [])
            if isinstance(row, dict)
        }
        delivery_items: list[DeliveryItemView] = []
        for item in document.get("deliverables", []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("deliverable_key") or "")
            included_tasks = [
                task for task in tasks
                if task.delivery_scope_active and key in stage_deliverables.get(task.stage_key or "", [])
            ]
            item_points = [point for task in included_tasks for point in points_by_task.get(task.id, [])]
            delivery_items.append(
                DeliveryItemView(
                    deliverable_key=key, title=str(item.get("title") or key),
                    description=str(item.get("description") or ""),
                    task_ids=[task.id for task in included_tasks],
                    acceptance_total=len(item_points),
                    acceptance_verified=sum(1 for point in item_points if point.status == "verified"),
                )
            )
        delivery_files = sorted(
            {
                path
                for row in evidence
                for path in _json(row.file_paths_json, [])
                if isinstance(path, str)
            }
        )[:500]
        delivery = DeliveryChecklistView(
            project_id=project_id, plan_id=plan.id if plan else None,
            deliverables=delivery_items, tasks=task_delivery_views,
            delivery_files=delivery_files, unresolved_issues=unresolved,
            generated_at=utcnow(),
        )
        return ProjectVerificationView(
            revision=revision, project_id=project_id,
            legacy_progress=project.legacy_progress, progress_source=project.progress_source,
            progress=progress, points=point_views, time=time_view,
            git=self._git_state(session, project_id), git_links=git_link_views,
            delivery=delivery,
            outcome=self.outcomes.build(
                session, project_id,
                verified_progress=progress.verified_delivery.percent,
            ),
            sample_readiness=self.sample_formation.readiness_in_session(
                session, project_id
            ),
        )

    def view(self, project_id: str) -> ProjectVerificationView:
        with self.database.session() as session:
            return self._view_in_session(session, project_id)

    def _publish(self, project_id: str, event_type: str, revision: int) -> None:
        self.event_hub.publish_nowait(
            {
                "type": event_type,
                "project_id": project_id,
                "revision": revision,
                "occurred_at": utcnow().isoformat(),
            }
        )
