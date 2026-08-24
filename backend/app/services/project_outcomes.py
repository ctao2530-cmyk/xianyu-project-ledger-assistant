from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..codex_verification_schemas import ProjectOutcomeView
from ..models import (
    BusinessExpense,
    BusinessProject,
    CodexAcceptanceEvidence,
    CodexAcceptancePoint,
    CodexEvent,
    CodexRun,
    PaymentNode,
    ProjectChangeOrderRecord,
    ProjectSettlementIssueRecord,
    ProjectTimeEntry,
    RequirementDocumentVersion,
    utcnow,
)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class ProjectOutcomeService:
    """One read-only source for delivery outcomes used by analysis and prediction."""

    @staticmethod
    def _complexity(session: Session, project: BusinessProject) -> float | None:
        if not project.requirement_version_id:
            return None
        version = session.get(RequirementDocumentVersion, project.requirement_version_id)
        if version is None:
            return None
        try:
            document = json.loads(version.structured_json or "{}")
        except (TypeError, ValueError):
            return None
        value = document.get("complexity") or document.get("requirement_complexity")
        if isinstance(value, (int, float)):
            return round(max(0.0, float(value)), 4)
        if isinstance(value, str):
            return {"low": 1.0, "medium": 2.0, "high": 3.0}.get(value.lower())
        return None

    def build(
        self,
        session: Session,
        project_id: str,
        *,
        verified_progress: int,
        available_at: datetime | None = None,
    ) -> ProjectOutcomeView:
        project = session.get(BusinessProject, project_id)
        if project is None:
            raise LookupError("project_missing")
        actual_hours = float(
            session.scalar(
                select(func.coalesce(func.sum(ProjectTimeEntry.hours), 0.0)).where(
                    ProjectTimeEntry.project_id == project_id
                )
            )
            or 0.0
        )
        rework_hours = float(
            session.scalar(
                select(func.coalesce(func.sum(ProjectTimeEntry.hours), 0.0)).where(
                    ProjectTimeEntry.project_id == project_id,
                    ProjectTimeEntry.category == "fixing",
                )
            )
            or 0.0
        )
        blocker_count = int(
            session.scalar(
                select(func.count(CodexEvent.id))
                .join(CodexRun, CodexRun.id == CodexEvent.run_id)
                .where(
                    CodexRun.project_id == project_id,
                    CodexEvent.event_type == "task_blocked",
                )
            )
            or 0
        )
        change_order_count = int(
            session.scalar(
                select(func.count(ProjectChangeOrderRecord.id)).where(
                    ProjectChangeOrderRecord.project_id == project_id
                )
            )
            or 0
        )
        test_failure_count = int(
            session.scalar(
                select(func.count(CodexAcceptanceEvidence.id)).where(
                    CodexAcceptanceEvidence.project_id == project_id,
                    CodexAcceptanceEvidence.evidence_type == "automated_test",
                    CodexAcceptanceEvidence.exit_code.is_not(None),
                    CodexAcceptanceEvidence.exit_code != 0,
                )
            )
            or 0
        )
        expenses = float(
            session.scalar(
                select(func.coalesce(func.sum(BusinessExpense.amount), 0.0)).where(
                    BusinessExpense.project_id == project_id
                )
            )
            or 0.0
        )
        gross_receipts = float(
            session.scalar(
                select(func.coalesce(func.sum(PaymentNode.amount), 0.0)).where(
                    PaymentNode.project_id == project_id,
                    PaymentNode.status.in_({"confirmed", "refunded"}),
                )
            )
            or 0.0
        )
        legacy_refunds = float(
            session.scalar(
                select(func.coalesce(func.sum(PaymentNode.amount), 0.0)).where(
                    PaymentNode.project_id == project_id,
                    PaymentNode.status == "refunded",
                )
            )
            or 0.0
        )
        issue_refunds = float(
            session.scalar(
                select(
                    func.coalesce(func.sum(ProjectSettlementIssueRecord.refund_amount), 0.0)
                ).where(ProjectSettlementIssueRecord.project_id == project_id)
            )
            or 0.0
        )
        revenue = max(0.0, gross_receipts - legacy_refunds - issue_refunds)
        profit = revenue - expenses
        terminal = verified_progress == 100
        actual_completed_at = (
            session.scalar(
                select(func.max(CodexAcceptancePoint.updated_at)).where(
                    CodexAcceptancePoint.project_id == project_id,
                    CodexAcceptancePoint.active.is_(True),
                )
            )
            if terminal
            else None
        )
        latest_time = session.scalar(
            select(func.max(ProjectTimeEntry.occurred_at)).where(
                ProjectTimeEntry.project_id == project_id
            )
        )
        latest_evidence = session.scalar(
            select(func.max(CodexAcceptanceEvidence.created_at)).where(
                CodexAcceptanceEvidence.project_id == project_id
            )
        )
        stable_available_at = max(
            (_aware(value) for value in (project.updated_at, latest_time, latest_evidence) if value),
            default=utcnow(),
        )
        return ProjectOutcomeView(
            project_id=project_id,
            requirement_complexity=self._complexity(session, project),
            estimated_hours=round(max(0.0, float(project.estimated_hours or 0.0)), 4),
            actual_hours=round(actual_hours, 4),
            estimated_delivery_at=project.due_date,
            actual_completed_at=actual_completed_at,
            blocker_count=blocker_count,
            change_order_count=change_order_count,
            test_failure_count=test_failure_count,
            rework_hours=round(rework_hours, 4),
            verified_progress=verified_progress,
            revenue=round(revenue, 2),
            profit=round(profit, 2),
            realized_hourly_rate=round(profit / actual_hours, 2) if actual_hours > 0 else 0.0,
            available_at=available_at or stable_available_at,
            finalized_at=actual_completed_at,
        )
