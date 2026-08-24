from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from ..codex_verification_schemas import (
    ManualAcceptancePointsInput,
    ProjectOutcomeFreezeInput,
    ProjectOutcomeFreezeView,
    ProjectOutcomeView,
    ProjectSampleReadinessView,
    RetireAcceptancePointInput,
    SampleReadinessBlocker,
)
from ..database import Database
from ..ledger import LedgerService, RevisionConflict
from ..models import (
    BusinessProject,
    BusinessTask,
    CodexAcceptanceEvidence,
    CodexAcceptancePoint,
    CodexAcceptanceStatusHistory,
    CodexDevelopmentPlan,
    ProjectOutcomeFreeze,
    ProjectOutcomeFreezeMutationRequest,
    ProjectSettlementIssueRecord,
    ProjectTimeEntry,
    utcnow,
)
from .event_hub import EventHub
from .project_outcomes import ProjectOutcomeService
from .project_progress import ProjectProgressService


TERMINAL_SETTLEMENT_ISSUES = {"project_cancelled", "cooperation_terminated"}
TERMINAL_PROJECT_STATUSES = {
    "cancelled",
    "canceled",
    "terminated",
    "project_cancelled",
    "cooperation_terminated",
}


class ProjectSampleFormationError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class ProjectSampleFormationService:
    """Manual delivery scope, readiness, and append-only verified outcome freezes."""

    def __init__(
        self,
        database: Database,
        ledger: LedgerService,
        event_hub: EventHub,
        *,
        outcomes: ProjectOutcomeService | None = None,
        progress: ProjectProgressService | None = None,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.event_hub = event_hub
        self.outcomes = outcomes or ProjectOutcomeService()
        self.progress = progress or ProjectProgressService()

    @staticmethod
    def _receipt(
        session,
        request_id: str,
        operation: str,
        digest: str,
    ) -> dict[str, Any] | None:
        row = session.get(ProjectOutcomeFreezeMutationRequest, request_id)
        if row is None:
            return None
        if row.operation != operation or row.payload_hash != digest:
            raise ProjectSampleFormationError(
                "request_conflict", "请求编号已用于不同的样本形成操作", 409
            )
        return json.loads(row.result_json or "{}")

    @staticmethod
    def _record_receipt(
        session,
        request_id: str,
        operation: str,
        digest: str,
        result: dict[str, Any],
    ) -> None:
        session.add(
            ProjectOutcomeFreezeMutationRequest(
                request_id=request_id,
                operation=operation,
                payload_hash=digest,
                result_json=_json(result),
            )
        )

    @staticmethod
    def _latest_freeze(session, project_id: str) -> ProjectOutcomeFreeze | None:
        return session.scalar(
            select(ProjectOutcomeFreeze)
            .where(ProjectOutcomeFreeze.project_id == project_id)
            .order_by(ProjectOutcomeFreeze.version.desc())
            .limit(1)
        )

    @staticmethod
    def _freeze_view(row: ProjectOutcomeFreeze, current_hash: str) -> ProjectOutcomeFreezeView:
        return ProjectOutcomeFreezeView(
            id=row.id,
            project_id=row.project_id,
            version=row.version,
            supersedes_freeze_id=row.supersedes_freeze_id,
            source_ledger_revision=row.source_ledger_revision,
            input_hash=row.input_hash,
            outcome=ProjectOutcomeView.model_validate(json.loads(row.outcome_json)),
            evidence_summary=json.loads(row.evidence_summary_json or "{}"),
            confirmed_scope_complete=row.confirmed_scope_complete,
            confirmed_time_complete=row.confirmed_time_complete,
            confirmation_note=row.confirmation_note,
            frozen_at=row.frozen_at,
            created_at=row.created_at,
            is_stale=row.input_hash != current_hash,
        )

    def _source_state(self, session, project_id: str) -> dict[str, Any]:
        project = session.get(BusinessProject, project_id)
        if project is None:
            raise ProjectSampleFormationError("project_missing", "项目不存在", 404)
        progress = self.progress.calculate(session, project_id)
        outcome = self.outcomes.build(
            session,
            project_id,
            verified_progress=progress.verified_delivery.percent,
        )
        tasks = list(
            session.scalars(
                select(BusinessTask)
                .where(
                    BusinessTask.project_id == project_id,
                    BusinessTask.delivery_scope_active.is_(True),
                )
                .order_by(BusinessTask.id)
            )
        )
        points = list(
            session.scalars(
                select(CodexAcceptancePoint)
                .where(
                    CodexAcceptancePoint.project_id == project_id,
                    CodexAcceptancePoint.active.is_(True),
                )
                .order_by(CodexAcceptancePoint.task_id, CodexAcceptancePoint.point_key)
            )
        )
        evidence = list(
            session.scalars(
                select(CodexAcceptanceEvidence)
                .where(CodexAcceptanceEvidence.project_id == project_id)
                .order_by(CodexAcceptanceEvidence.created_at, CodexAcceptanceEvidence.id)
            )
        )
        time_entries = list(
            session.scalars(
                select(ProjectTimeEntry)
                .where(ProjectTimeEntry.project_id == project_id)
                .order_by(ProjectTimeEntry.occurred_at, ProjectTimeEntry.id)
            )
        )
        terminal_issues = list(
            session.scalars(
                select(ProjectSettlementIssueRecord)
                .where(
                    ProjectSettlementIssueRecord.project_id == project_id,
                    ProjectSettlementIssueRecord.issue_type.in_(TERMINAL_SETTLEMENT_ISSUES),
                )
                .order_by(ProjectSettlementIssueRecord.created_at)
            )
        )
        payload = {
            "project": {
                "id": project.id,
                "name": project.name,
                "status": project.status,
                "estimated_hours": float(project.estimated_hours or 0),
                "due_date": project.due_date,
                "requirement_version_id": project.requirement_version_id,
            },
            "tasks": [
                {
                    "id": row.id,
                    "title": row.title,
                    "estimated_hours": float(row.estimated_hours or 0),
                    "task_key": row.task_key,
                    "codex_plan_id": row.codex_plan_id,
                }
                for row in tasks
            ],
            "points": [
                {
                    "id": row.id,
                    "task_id": row.task_id,
                    "point_key": row.point_key,
                    "title": row.title,
                    "verification_type": row.verification_type,
                    "source": row.source,
                    "status": row.status,
                    "point_weight": row.point_weight,
                    "waived_counts": row.waived_counts,
                    "verified_at": row.verified_at,
                    "updated_at": row.updated_at,
                }
                for row in points
            ],
            "evidence": [
                {
                    "id": row.id,
                    "point_id": row.point_id,
                    "evidence_type": row.evidence_type,
                    "status": row.status,
                    "exit_code": row.exit_code,
                    "commit_sha": row.commit_sha,
                    "verified_at": row.verified_at,
                    "created_at": row.created_at,
                }
                for row in evidence
            ],
            "time_entries": [
                {
                    "id": row.id,
                    "task_id": row.task_id,
                    "category": row.category,
                    "source": row.source,
                    "hours": float(row.hours),
                    "adjustment_of_id": row.adjustment_of_id,
                    "occurred_at": row.occurred_at,
                }
                for row in time_entries
            ],
            "terminal_issues": [
                {"id": row.id, "issue_type": row.issue_type, "created_at": row.created_at}
                for row in terminal_issues
            ],
            "outcome": outcome.model_dump(mode="json"),
        }
        evidence_summary: dict[str, int | float | str | bool] = {
            "active_task_count": len(tasks),
            "active_point_count": len(points),
            "verified_point_count": sum(row.status == "verified" for row in points),
            "waived_point_count": sum(row.status == "waived" for row in points),
            "evidence_count": len(evidence),
            "time_entry_count": len(time_entries),
            "actual_hours": outcome.actual_hours,
            "verified_progress": outcome.verified_progress,
        }
        return {
            "project": project,
            "progress": progress,
            "outcome": outcome,
            "tasks": tasks,
            "points": points,
            "terminal_issues": terminal_issues,
            "input_hash": _hash(payload),
            "evidence_summary": evidence_summary,
        }

    def readiness_in_session(self, session, project_id: str) -> ProjectSampleReadinessView:
        state = self._source_state(session, project_id)
        project: BusinessProject = state["project"]
        tasks: list[BusinessTask] = state["tasks"]
        points: list[CodexAcceptancePoint] = state["points"]
        outcome: ProjectOutcomeView = state["outcome"]
        input_hash: str = state["input_hash"]
        point_task_ids = {row.task_id for row in points}
        blockers: list[SampleReadinessBlocker] = []
        terminal = bool(state["terminal_issues"]) or project.status in TERMINAL_PROJECT_STATUSES
        if terminal:
            blockers.append(
                SampleReadinessBlocker(
                    code="terminal_project",
                    message="项目已取消或终止合作，不能形成正常交付校准样本",
                    action="保留结算历史，并将新工作建立为新项目",
                )
            )
        if not tasks:
            blockers.append(
                SampleReadinessBlocker(
                    code="tasks_missing",
                    message="项目没有有效交付任务",
                    action="先补充真实 BusinessTask",
                )
            )
        if not points:
            blockers.append(
                SampleReadinessBlocker(
                    code="acceptance_scope_missing",
                    message="项目没有可核验的验收点",
                    action="为真实任务人工建立验收清单",
                )
            )
        missing_task_points = [row.title for row in tasks if row.id not in point_task_ids]
        if missing_task_points:
            blockers.append(
                SampleReadinessBlocker(
                    code="task_acceptance_missing",
                    message=f"{len(missing_task_points)} 个有效任务没有验收点",
                    action="为每个有效任务至少补充一个真实验收点",
                )
            )
        waived = [row for row in points if row.status == "waived"]
        if waived:
            blockers.append(
                SampleReadinessBlocker(
                    code="waiver_present",
                    message=f"存在 {len(waived)} 个 waived 验收点，不能作为决策级样本",
                    action="补齐验证证据或明确该项目不进入校准",
                )
            )
        incomplete = [row for row in points if row.status != "verified"]
        if incomplete and not waived:
            blockers.append(
                SampleReadinessBlocker(
                    code="verification_incomplete",
                    message=f"仍有 {len(incomplete)} 个验收点未达到 verified",
                    action="逐项核验证据；implemented 和 test_passed 不算 verified",
                )
            )
        if outcome.verified_progress != 100:
            blockers.append(
                SampleReadinessBlocker(
                    code="verified_progress_incomplete",
                    message=f"已验证交付进度为 {outcome.verified_progress}%",
                    action="完成全部有效验收点的人工核验",
                )
            )
        if outcome.estimated_hours <= 0:
            blockers.append(
                SampleReadinessBlocker(
                    code="estimate_missing",
                    message="缺少大于 0 的原始预计工时",
                    action="补充项目原始预计工时，不使用校准建议回填",
                )
            )
        if outcome.actual_hours <= 0:
            blockers.append(
                SampleReadinessBlocker(
                    code="actual_hours_missing",
                    message="缺少大于 0 的实际工时",
                    action="通过现有追加式工时账本补齐真实记录",
                )
            )
        can_freeze = not blockers
        rows = list(
            session.scalars(
                select(ProjectOutcomeFreeze)
                .where(ProjectOutcomeFreeze.project_id == project_id)
                .order_by(ProjectOutcomeFreeze.version.desc())
                .limit(20)
            )
        )
        history = [self._freeze_view(row, input_hash) for row in rows]
        latest = history[0] if history else None
        calibration_eligible = bool(latest and not latest.is_stale and can_freeze)
        if terminal:
            status = "terminal"
        elif not tasks or not points or missing_task_points:
            status = "missing_scope"
        elif waived or incomplete or outcome.verified_progress != 100:
            status = "needs_verification"
        elif outcome.estimated_hours <= 0 or outcome.actual_hours <= 0:
            status = "needs_time"
        elif latest is None:
            status = "ready_to_freeze"
        elif latest.is_stale:
            status = "stale"
        else:
            status = "frozen"
        return ProjectSampleReadinessView(
            project_id=project_id,
            status=status,
            can_freeze=can_freeze,
            calibration_eligible=calibration_eligible,
            active_task_count=len(tasks),
            active_point_count=len(points),
            verified_point_count=sum(row.status == "verified" for row in points),
            waived_point_count=len(waived),
            estimated_hours=outcome.estimated_hours,
            actual_hours=outcome.actual_hours,
            verified_progress=outcome.verified_progress,
            blockers=blockers,
            latest_freeze=latest,
            freeze_history=history,
        )

    def readiness(self, project_id: str) -> ProjectSampleReadinessView:
        try:
            with self.database.session() as session:
                return self.readiness_in_session(session, project_id)
        except ProjectSampleFormationError:
            raise
        except (SQLAlchemyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ProjectSampleFormationError(
                "sample_readiness_unavailable", "样本准备度暂时无法读取", 503
            ) from exc

    def create_manual_points(
        self,
        project_id: str,
        payload: ManualAcceptancePointsInput,
    ) -> int:
        operation = "create_manual_acceptance_points"
        body = {"project_id": project_id, **payload.model_dump(mode="json")}
        digest = _hash(body)
        with self.database.session() as session:
            replay = self._receipt(session, payload.request_id, operation, digest)
            if replay is not None:
                return int(replay["revision"])
            project = session.get(BusinessProject, project_id)
            if project is None:
                raise ProjectSampleFormationError("project_missing", "项目不存在", 404)
            confirmed_plan = session.scalar(
                select(CodexDevelopmentPlan.id)
                .where(
                    CodexDevelopmentPlan.project_id == project_id,
                    CodexDevelopmentPlan.status == "confirmed",
                )
                .limit(1)
            )
            if confirmed_plan is not None:
                raise ProjectSampleFormationError(
                    "confirmed_plan_scope",
                    "项目已有确认 Codex 计划，请通过计划版本维护验收范围",
                    409,
                )
            revision, _ = self.ledger.get_in_session(session)
            if revision != payload.expected_revision:
                raise RevisionConflict(revision)
            composite_keys = [(row.task_id, row.point_key) for row in payload.points]
            if len(composite_keys) != len(set(composite_keys)):
                raise ProjectSampleFormationError(
                    "point_key_duplicate", "同一请求中存在重复验收点 key", 409
                )
            tasks = {
                row.id: row
                for row in session.scalars(
                    select(BusinessTask).where(
                        BusinessTask.project_id == project_id,
                        BusinessTask.id.in_({row.task_id for row in payload.points}),
                    )
                )
            }
            if len(tasks) != len({row.task_id for row in payload.points}) or any(
                not tasks[row.task_id].delivery_scope_active for row in payload.points
            ):
                raise ProjectSampleFormationError(
                    "task_missing", "验收点只能关联当前项目的有效任务", 404
                )
            existing = {
                (str(task_id), str(point_key))
                for task_id, point_key in session.execute(
                    select(CodexAcceptancePoint.task_id, CodexAcceptancePoint.point_key)
                    .where(
                        CodexAcceptancePoint.project_id == project_id,
                        CodexAcceptancePoint.task_id.in_(set(tasks)),
                    )
                ).all()
            }
            reused = [key for key in composite_keys if key in existing]
            if reused:
                raise ProjectSampleFormationError(
                    "point_key_reused",
                    "验收点 key 已使用；退役记录也不能复用原 key",
                    409,
                )
            created_ids: list[str] = []
            now = utcnow()
            for item in payload.points:
                point_id = "manual-acceptance-" + hashlib.sha256(
                    f"{project_id}\n{item.task_id}\n{item.point_key}".encode("utf-8")
                ).hexdigest()[:32]
                point = CodexAcceptancePoint(
                    id=point_id,
                    project_id=project_id,
                    task_id=item.task_id,
                    plan_id=None,
                    point_key=item.point_key,
                    title=item.title,
                    verification_type=item.verification_type,
                    source="manual_historical",
                    status="pending",
                    point_weight=item.point_weight,
                    active=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(point)
                session.add(
                    CodexAcceptanceStatusHistory(
                        id=f"codex-acceptance-history-{uuid4()}",
                        point_id=point_id,
                        project_id=project_id,
                        task_id=item.task_id,
                        from_status="",
                        to_status="pending",
                        reason=payload.reason,
                        request_id=payload.request_id,
                        occurred_at=now,
                    )
                )
                created_ids.append(point_id)
            session.flush()
            new_revision, _ = self.progress.sync_verified_progress(
                session,
                self.ledger,
                project_id,
                expected_revision=revision,
            )
            self._record_receipt(
                session,
                payload.request_id,
                operation,
                digest,
                {"project_id": project_id, "point_ids": created_ids, "revision": new_revision},
            )
            session.commit()
        self._publish(project_id, "manual_acceptance_scope_created", new_revision)
        return new_revision

    def retire_manual_point(
        self,
        point_id: str,
        payload: RetireAcceptancePointInput,
    ) -> int:
        operation = "retire_manual_acceptance_point"
        body = {"point_id": point_id, **payload.model_dump(mode="json")}
        digest = _hash(body)
        with self.database.session() as session:
            replay = self._receipt(session, payload.request_id, operation, digest)
            point = session.get(CodexAcceptancePoint, point_id)
            if point is None:
                raise ProjectSampleFormationError("point_missing", "验收点不存在", 404)
            if replay is not None:
                return int(replay["revision"])
            if point.source != "manual_historical":
                raise ProjectSampleFormationError(
                    "plan_point_immutable", "计划验收点必须通过新的计划版本维护", 409
                )
            if not point.active:
                raise ProjectSampleFormationError(
                    "point_retired", "验收点已经退役", 409
                )
            revision, _ = self.ledger.get_in_session(session)
            if revision != payload.expected_revision:
                raise RevisionConflict(revision)
            previous = point.status
            now = utcnow()
            point.status = "waived"
            point.waived_counts = False
            point.waiver_reason = payload.reason
            point.active = False
            point.retired_at = now
            point.updated_at = now
            session.add(
                CodexAcceptanceStatusHistory(
                    id=f"codex-acceptance-history-{uuid4()}",
                    point_id=point.id,
                    project_id=point.project_id,
                    task_id=point.task_id,
                    from_status=previous,
                    to_status="waived",
                    reason=f"退役人工验收点：{payload.reason}",
                    request_id=payload.request_id,
                    occurred_at=now,
                )
            )
            new_revision, _ = self.progress.sync_verified_progress(
                session,
                self.ledger,
                point.project_id,
                expected_revision=revision,
            )
            self._record_receipt(
                session,
                payload.request_id,
                operation,
                digest,
                {"project_id": point.project_id, "point_id": point.id, "revision": new_revision},
            )
            session.commit()
            project_id = point.project_id
        self._publish(project_id, "manual_acceptance_point_retired", new_revision)
        return new_revision

    def freeze(
        self,
        project_id: str,
        payload: ProjectOutcomeFreezeInput,
    ) -> ProjectOutcomeFreezeView:
        operation = "freeze_project_outcome"
        body = {"project_id": project_id, **payload.model_dump(mode="json")}
        digest = _hash(body)
        with self.database.session() as session:
            replay = self._receipt(session, payload.request_id, operation, digest)
            if replay is not None:
                row = session.get(ProjectOutcomeFreeze, replay.get("freeze_id"))
                if row is None:
                    raise ProjectSampleFormationError(
                        "freeze_missing", "结果冻结记录不存在", 404
                    )
                current = self._source_state(session, project_id)
                return self._freeze_view(row, current["input_hash"])
            revision, _ = self.ledger.get_in_session(session)
            if revision != payload.expected_revision:
                raise RevisionConflict(revision)
            readiness = self.readiness_in_session(session, project_id)
            if not readiness.can_freeze:
                raise ProjectSampleFormationError(
                    "sample_not_ready",
                    "项目尚未满足结果冻结条件："
                    + "；".join(row.message for row in readiness.blockers),
                    409,
                )
            state = self._source_state(session, project_id)
            current_hash: str = state["input_hash"]
            latest = self._latest_freeze(session, project_id)
            if latest is not None and latest.input_hash == current_hash:
                row = latest
            else:
                frozen_at = utcnow()
                live: ProjectOutcomeView = state["outcome"]
                frozen_outcome = live.model_copy(
                    update={"available_at": frozen_at, "finalized_at": frozen_at}
                )
                version = (latest.version if latest else 0) + 1
                row = ProjectOutcomeFreeze(
                    id=f"project-outcome-freeze-{uuid4()}",
                    project_id=project_id,
                    version=version,
                    supersedes_freeze_id=latest.id if latest else None,
                    source_ledger_revision=revision,
                    input_hash=current_hash,
                    outcome_json=_json(frozen_outcome.model_dump(mode="json")),
                    evidence_summary_json=_json(state["evidence_summary"]),
                    confirmed_scope_complete=payload.confirmed_scope_complete,
                    confirmed_time_complete=payload.confirmed_time_complete,
                    confirmation_note=payload.confirmation_note,
                    frozen_at=frozen_at,
                    created_at=frozen_at,
                )
                session.add(row)
                session.flush()
            self._record_receipt(
                session,
                payload.request_id,
                operation,
                digest,
                {"project_id": project_id, "freeze_id": row.id, "version": row.version},
            )
            session.commit()
            view = self._freeze_view(row, current_hash)
        self._publish(project_id, "project_outcome_frozen", revision)
        return view

    def freezes(self, project_id: str) -> list[ProjectOutcomeFreezeView]:
        with self.database.session() as session:
            readiness = self.readiness_in_session(session, project_id)
            return readiness.freeze_history

    def project_id_for_point(self, point_id: str) -> str:
        with self.database.session() as session:
            point = session.get(CodexAcceptancePoint, point_id)
            if point is None:
                raise ProjectSampleFormationError("point_missing", "验收点不存在", 404)
            return point.project_id

    def calibration_outcome_in_session(
        self,
        session,
        project_id: str,
    ) -> tuple[ProjectOutcomeView | None, ProjectSampleReadinessView]:
        readiness = self.readiness_in_session(session, project_id)
        if not readiness.calibration_eligible or readiness.latest_freeze is None:
            return None, readiness
        return readiness.latest_freeze.outcome, readiness

    def _publish(self, project_id: str, event_type: str, revision: int) -> None:
        self.event_hub.publish_nowait(
            {
                "type": event_type,
                "project_id": project_id,
                "revision": revision,
                "occurred_at": utcnow().isoformat(),
            }
        )
