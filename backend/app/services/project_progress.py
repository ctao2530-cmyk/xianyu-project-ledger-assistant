from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..codex_verification_schemas import (
    ProgressMetricView,
    ProjectProgressView,
)
from ..ledger import LedgerService, RevisionConflict
from ..models import BusinessProject, BusinessTask, CodexAcceptancePoint


CODEX_FRACTION = {
    "todo": 0.0,
    "in_progress": 0.5,
    "blocked": 0.5,
    "implemented": 1.0,
}
IMPLEMENTED_STATUSES = {"implemented", "test_passed", "verified"}


@dataclass(slots=True)
class _Contribution:
    codex: float
    implemented: float
    verified: float


class ProjectProgressService:
    """The single authoritative implementation of all three progress metrics."""

    @staticmethod
    def _point_fraction(points: list[CodexAcceptancePoint]) -> tuple[float, float]:
        if not points:
            return 0.0, 0.0
        explicit = all((point.point_weight or 0) > 0 for point in points)
        if explicit:
            raw_weights = [float(point.point_weight or 0) for point in points]
        else:
            raw_weights = [1.0 for _ in points]
        total = sum(raw_weights) or 1.0
        implemented = 0.0
        verified = 0.0
        for point, raw_weight in zip(points, raw_weights, strict=True):
            weight = raw_weight / total
            if point.status in IMPLEMENTED_STATUSES or (
                point.status == "waived" and point.waived_counts
            ):
                implemented += weight
            if point.status == "verified" or (
                point.status == "waived" and point.waived_counts
            ):
                verified += weight
        return implemented, verified

    def calculate(self, session: Session, project_id: str) -> ProjectProgressView:
        project = session.get(BusinessProject, project_id)
        if project is None:
            raise LookupError("project_missing")
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
        points_by_task: dict[str, list[CodexAcceptancePoint]] = defaultdict(list)
        for point in points:
            points_by_task[point.task_id].append(point)

        warnings: list[str] = []
        positive_total = sum(max(0.0, float(task.estimated_hours)) for task in tasks)
        if tasks and positive_total <= 0:
            task_weights = {task.id: 1.0 / len(tasks) for task in tasks}
            weight_basis = "fallback_equal_weight"
            warnings.append("全部任务预计工时为 0，暂按任务等权计算")
        else:
            task_weights = {
                task.id: max(0.0, float(task.estimated_hours)) / positive_total
                for task in tasks
            }
            weight_basis = "estimated_hours"
            if any(float(task.estimated_hours) <= 0 for task in tasks):
                warnings.append("预计工时为 0 的任务暂不贡献权重，请补充预计工时")

        codex_value = 0.0
        implemented_value = 0.0
        verified_value = 0.0
        for task in tasks:
            weight = task_weights.get(task.id, 0.0)
            task_points = points_by_task.get(task.id, [])
            implemented_fraction, verified_fraction = self._point_fraction(task_points)
            if not task_points and task.codex_execution_status == "implemented":
                implemented_fraction = 1.0
            contribution = _Contribution(
                codex=CODEX_FRACTION.get(task.codex_execution_status, 0.0),
                implemented=implemented_fraction,
                verified=verified_fraction,
            )
            codex_value += weight * contribution.codex
            implemented_value += weight * contribution.implemented
            verified_value += weight * contribution.verified

        def metric(value: float) -> ProgressMetricView:
            bounded = max(0.0, min(1.0, value))
            return ProgressMetricView(
                percent=round(bounded * 100),
                completed_weight=round(bounded, 6),
                total_weight=1.0 if tasks else 0.0,
            )

        waived = [point for point in points if point.status == "waived"]
        return ProjectProgressView(
            project_id=project_id,
            codex_execution=metric(codex_value),
            implemented=metric(implemented_value),
            verified_delivery=metric(verified_value),
            weight_basis=weight_basis if tasks else "no_tasks",
            warnings=warnings,
            waived_count=len(waived),
            waived_counted=sum(1 for point in waived if point.waived_counts),
        )

    def sync_verified_progress(
        self,
        session: Session,
        ledger: LedgerService,
        project_id: str,
        *,
        expected_revision: int,
    ) -> tuple[int, ProjectProgressView]:
        revision, snapshot = ledger.get_in_session(session)
        if revision != expected_revision:
            raise RevisionConflict(revision)
        progress = self.calculate(session, project_id)
        project = session.get(BusinessProject, project_id)
        if project is None:
            raise LookupError("project_missing")
        item = next(
            (row for row in snapshot["projects"] if str(row.get("id") or "") == project_id),
            None,
        )
        if item is None:
            raise LookupError("project_snapshot_missing")
        item["legacyProgress"] = project.legacy_progress
        item["progress"] = progress.verified_delivery.percent
        item["progressSource"] = "verified"
        new_revision, _ = ledger.save_in_session(
            session,
            snapshot,
            revision,
            trusted_delivery_sync=True,
        )
        project = session.get(BusinessProject, project_id)
        assert project is not None
        project.progress = progress.verified_delivery.percent
        project.progress_source = "verified"
        return new_revision, progress
