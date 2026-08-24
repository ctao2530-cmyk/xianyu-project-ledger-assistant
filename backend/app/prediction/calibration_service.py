from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from statistics import mean, median
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..codex_verification_schemas import ProjectOutcomeView
from ..database import Database
from ..models import (
    BusinessProject,
    EstimateCalibrationDecision,
    EstimateCalibrationMutationRequest,
    EstimateCalibrationRun,
    EstimateCalibrationSample,
    EstimateCalibrationSuggestion,
    ProjectSettlementIssueRecord,
    utcnow,
)
from ..services.project_outcomes import ProjectOutcomeService
from ..services.project_progress import ProjectProgressService
from ..services.project_sample_formation import ProjectSampleFormationService
from .calibration_repository import (
    CalibrationDecisionInvalid,
    CalibrationNotFound,
    CalibrationRepositoryError,
    CalibrationRequestConflict,
    CalibrationRevisionConflict,
    EstimateCalibrationRepository,
)
from .calibration_schemas import (
    CalibrationCandidateView,
    CalibrationDecisionRequest,
    CalibrationMetrics,
    CalibrationQuoteAssistView,
    CalibrationSummaryView,
)


ALGORITHM_VERSION = "verified-outcome-calibration-v2-frozen"
TERMINAL_SETTLEMENT_ISSUES = {"project_cancelled", "cooperation_terminated"}
TERMINAL_PROJECT_STATUSES = {
    "cancelled",
    "canceled",
    "terminated",
    "project_cancelled",
    "cooperation_terminated",
}
INVALIDATION_CONDITIONS = [
    "需求范围、技术栈或交付口径发生实质变化",
    "新增追加订单、关键阻塞或未计入的返工",
    "样本窗口、原始估算或目标项目预计工时发生变化",
]


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _quantile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("quantile requires values")
    rows = sorted(values)
    if len(rows) == 1:
        return rows[0]
    position = (len(rows) - 1) * fraction
    lower = int(position)
    upper = min(len(rows) - 1, lower + 1)
    weight = position - lower
    return rows[lower] * (1 - weight) + rows[upper] * weight


def _sufficiency(sample_count: int) -> str:
    if sample_count >= 5:
        return "actionable"
    if sample_count >= 3:
        return "exploratory"
    return "insufficient"


@dataclass(slots=True)
class _Candidate:
    view: CalibrationCandidateView
    outcome: ProjectOutcomeView
    source_hash: str


class EstimateCalibrationService:
    """Transparent calibration built only from verified ProjectOutcomeService facts."""

    def __init__(
        self,
        database: Database,
        outcomes: ProjectOutcomeService | None = None,
        progress: ProjectProgressService | None = None,
        sample_formation: ProjectSampleFormationService | None = None,
    ) -> None:
        self.database = database
        self.outcomes = outcomes or ProjectOutcomeService()
        self.progress = progress or ProjectProgressService()
        self.sample_formation = sample_formation
        self.repository = EstimateCalibrationRepository(database)

    @staticmethod
    def _normalized_cutoff(value: datetime | None) -> datetime:
        cutoff = value or datetime.now(timezone.utc)
        return _aware(cutoff).replace(microsecond=0)

    @staticmethod
    def _metrics(candidates: list[_Candidate]) -> CalibrationMetrics:
        eligible = [row for row in candidates if row.view.eligible]
        if not eligible:
            return CalibrationMetrics()
        errors = [row.outcome.actual_hours - row.outcome.estimated_hours for row in eligible]
        ratios = [row.outcome.actual_hours / row.outcome.estimated_hours for row in eligible]
        coverage: float | None = None
        if len(ratios) >= 6:
            outcomes: list[bool] = []
            for index, ratio in enumerate(ratios):
                comparison = ratios[:index] + ratios[index + 1 :]
                lower = _quantile(comparison, 0.25)
                upper = _quantile(comparison, 0.75)
                outcomes.append(lower <= ratio <= upper)
            coverage = round(sum(outcomes) / len(outcomes), 4)
        return CalibrationMetrics(
            signed_bias_hours=round(mean(errors), 4),
            mae_hours=round(mean(abs(value) for value in errors), 4),
            overrun_rate=round(sum(1 for value in errors if value > 0) / len(errors), 4),
            interval_coverage=coverage,
            multiplier_median=round(median(ratios), 6),
            multiplier_lower=round(_quantile(ratios, 0.25), 6),
            multiplier_upper=round(_quantile(ratios, 0.75), 6),
        )

    def _candidate(
        self,
        session,
        project: BusinessProject,
        *,
        cutoff_at: datetime,
    ) -> _Candidate:
        progress = self.progress.calculate(session, project.id)
        live_outcome = self.outcomes.build(
            session,
            project.id,
            verified_progress=progress.verified_delivery.percent,
        )
        if self.sample_formation is None:
            raise CalibrationRepositoryError
        frozen_outcome, readiness = self.sample_formation.calibration_outcome_in_session(
            session, project.id
        )
        outcome = frozen_outcome or live_outcome
        issue = session.scalar(
            select(ProjectSettlementIssueRecord)
            .where(
                ProjectSettlementIssueRecord.project_id == project.id,
                ProjectSettlementIssueRecord.issue_type.in_(TERMINAL_SETTLEMENT_ISSUES),
            )
            .limit(1)
        )
        exclusion_code = ""
        exclusion_reason = ""
        if issue is not None or project.status in TERMINAL_PROJECT_STATUSES:
            exclusion_code = "terminal_settlement"
            exclusion_reason = "项目已取消或终止合作，不进入估算校准样本"
        elif frozen_outcome is None:
            if readiness.latest_freeze is not None and readiness.latest_freeze.is_stale:
                exclusion_code = "stale_freeze"
                exclusion_reason = "最新结果冻结已过期，需要重新核验并追加冻结"
            else:
                exclusion_code = (
                    readiness.blockers[0].code if readiness.blockers else "not_frozen"
                )
                exclusion_reason = (
                    readiness.blockers[0].message
                    if readiness.blockers
                    else "项目结果尚未通过证据核验并冻结"
                )
        elif _aware(outcome.available_at) > cutoff_at:
            exclusion_code = "future_available"
            exclusion_reason = "结果在本次 cutoff_at 时仍不可见"
        elif _aware(outcome.finalized_at) > cutoff_at:
            exclusion_code = "future_finalized"
            exclusion_reason = "结果在本次 cutoff_at 之后才冻结"

        payload = outcome.model_dump(mode="json")
        source_hash = _hash(
            {
                "project_id": project.id,
                "project_name": project.name,
                "outcome": payload,
                "freeze_id": readiness.latest_freeze.id if readiness.latest_freeze else None,
                "freeze_input_hash": (
                    readiness.latest_freeze.input_hash if readiness.latest_freeze else None
                ),
                "estimate_source": "business_project",
                "algorithm_version": ALGORITHM_VERSION,
            }
        )
        return _Candidate(
            view=CalibrationCandidateView(
                project_id=project.id,
                project_name=project.name,
                project_status=project.status,
                estimated_hours=outcome.estimated_hours,
                actual_hours=outcome.actual_hours,
                verified_progress=outcome.verified_progress,
                available_at=outcome.available_at,
                finalized_at=outcome.finalized_at,
                freeze_id=readiness.latest_freeze.id if readiness.latest_freeze else None,
                freeze_version=(
                    readiness.latest_freeze.version if readiness.latest_freeze else None
                ),
                sample_readiness_status=readiness.status,
                freeze_stale=bool(
                    readiness.latest_freeze and readiness.latest_freeze.is_stale
                ),
                readiness_actions=[row.action for row in readiness.blockers],
                eligible=not exclusion_code,
                exclusion_code=exclusion_code,
                exclusion_reason=exclusion_reason,
            ),
            outcome=outcome,
            source_hash=source_hash,
        )

    def _candidates(self, session, cutoff_at: datetime) -> list[_Candidate]:
        projects = list(
            session.scalars(select(BusinessProject).order_by(BusinessProject.created_at, BusinessProject.id))
        )
        return [self._candidate(session, project, cutoff_at=cutoff_at) for project in projects]

    @staticmethod
    def _snapshot_hash(candidates: list[_Candidate], _cutoff_at: datetime) -> str:
        # Candidate eligibility already reflects the cutoff. Excluding the moving
        # wall-clock value keeps an unchanged fact set from appearing stale.
        return _hash(
            {
                "algorithm_version": ALGORITHM_VERSION,
                "candidates": [
                    {
                        **row.view.model_dump(mode="json"),
                        "source_hash": row.source_hash,
                    }
                    for row in candidates
                ],
            }
        )

    @staticmethod
    def _sample_window(candidates: list[_Candidate]) -> tuple[datetime | None, datetime | None]:
        values = [
            _aware(row.outcome.finalized_at)
            for row in candidates
            if row.view.eligible and row.outcome.finalized_at is not None
        ]
        return (min(values), max(values)) if values else (None, None)

    def _live_summary(self, cutoff_at: datetime) -> CalibrationSummaryView:
        try:
            with self.database.session() as session:
                candidates = self._candidates(session, cutoff_at)
        except (SQLAlchemyError, LookupError, ValueError) as exc:
            raise CalibrationRepositoryError from exc
        eligible = [row for row in candidates if row.view.eligible]
        start_at, end_at = self._sample_window(candidates)
        return CalibrationSummaryView(
            cutoff_at=cutoff_at,
            input_snapshot_hash=self._snapshot_hash(candidates, cutoff_at),
            sample_count=len(eligible),
            sufficiency=_sufficiency(len(eligible)),
            algorithm_version=ALGORITHM_VERSION,
            metrics=self._metrics(candidates),
            sample_start_at=start_at,
            sample_end_at=end_at,
            candidates=[row.view for row in candidates],
        )

    @staticmethod
    def _run_summary(run: EstimateCalibrationRun) -> CalibrationSummaryView:
        return CalibrationSummaryView(
            run_id=run.id,
            record_status="completed",
            cutoff_at=run.cutoff_at,
            input_snapshot_hash=run.input_snapshot_hash,
            sample_count=run.sample_count,
            sufficiency=run.sufficiency,  # type: ignore[arg-type]
            algorithm_version=run.algorithm_version,
            metrics=CalibrationMetrics(
                signed_bias_hours=run.signed_bias_hours,
                mae_hours=run.mae_hours,
                overrun_rate=run.overrun_rate,
                interval_coverage=run.interval_coverage,
                multiplier_median=run.multiplier_median,
                multiplier_lower=run.multiplier_lower,
                multiplier_upper=run.multiplier_upper,
            ),
        )

    def summary(self, *, cutoff_at: datetime | None = None) -> CalibrationSummaryView:
        live = self._live_summary(self._normalized_cutoff(cutoff_at))
        latest = self.repository.latest_run()
        if latest is None:
            return live
        completed = self._run_summary(latest)
        return completed.model_copy(
            update={
                "candidates": live.candidates,
                "sample_start_at": live.sample_start_at,
                "sample_end_at": live.sample_end_at,
                "is_stale": latest.input_snapshot_hash != live.input_snapshot_hash,
            }
        )

    @staticmethod
    def _suggestion_values(original: float, metrics: CalibrationMetrics) -> tuple[float, float, float]:
        if metrics.multiplier_median is None or metrics.multiplier_lower is None or metrics.multiplier_upper is None:
            raise CalibrationDecisionInvalid
        suggested = max(0.5, original * metrics.multiplier_median)
        lower = max(0.5, original * metrics.multiplier_lower)
        upper = max(lower, original * metrics.multiplier_upper)
        return round(suggested, 2), round(lower, 2), round(upper, 2)

    def run(self, *, request_id: str, cutoff_at: datetime | None = None) -> CalibrationSummaryView:
        cutoff = self._normalized_cutoff(cutoff_at)
        operation = "create_calibration_run"
        digest = _hash({"request_id": request_id, "cutoff_at": cutoff.isoformat()})
        try:
            with self.database.session() as session:
                receipt = session.get(EstimateCalibrationMutationRequest, request_id)
                if receipt is not None:
                    if receipt.operation != operation or receipt.payload_hash != digest:
                        raise CalibrationRequestConflict
                    result = json.loads(receipt.result_json or "{}")
                    existing = session.get(EstimateCalibrationRun, result.get("run_id"))
                    if existing is None:
                        raise CalibrationNotFound
                    return self._run_summary(existing)

                candidates = self._candidates(session, cutoff)
                eligible = [row for row in candidates if row.view.eligible]
                metrics = self._metrics(candidates)
                sample_rows: list[EstimateCalibrationSample] = []
                for candidate in eligible:
                    sample = self.repository.sample_by_hash(session, candidate.source_hash)
                    if sample is None:
                        previous = self.repository.latest_project_sample(
                            session, candidate.view.project_id
                        )
                        outcome = candidate.outcome
                        assert outcome.finalized_at is not None
                        signed_error = outcome.actual_hours - outcome.estimated_hours
                        sample = EstimateCalibrationSample(
                            id=f"estimate-calibration-sample-{uuid4()}",
                            project_id=candidate.view.project_id,
                            project_name=candidate.view.project_name,
                            source_hash=candidate.source_hash,
                            supersedes_sample_id=previous.id if previous else None,
                            estimated_hours=outcome.estimated_hours,
                            actual_hours=outcome.actual_hours,
                            signed_error_hours=round(signed_error, 4),
                            absolute_error_hours=round(abs(signed_error), 4),
                            actual_to_estimate_ratio=round(
                                outcome.actual_hours / outcome.estimated_hours, 8
                            ),
                            estimated_delivery_at=outcome.estimated_delivery_at,
                            actual_completed_at=_aware(outcome.actual_completed_at or outcome.finalized_at),
                            requirement_complexity=outcome.requirement_complexity,
                            blocker_count=outcome.blocker_count,
                            change_order_count=outcome.change_order_count,
                            test_failure_count=outcome.test_failure_count,
                            rework_hours=outcome.rework_hours,
                            verified_progress=outcome.verified_progress,
                            available_at=_aware(outcome.available_at),
                            finalized_at=_aware(outcome.finalized_at),
                            cutoff_at=cutoff,
                            outcome_json=_json(outcome.model_dump(mode="json")),
                        )
                        session.add(sample)
                        session.flush()
                    sample_rows.append(sample)

                run = EstimateCalibrationRun(
                    id=f"estimate-calibration-run-{uuid4()}",
                    request_id=request_id,
                    input_snapshot_hash=self._snapshot_hash(candidates, cutoff),
                    cutoff_at=cutoff,
                    sample_count=len(eligible),
                    sufficiency=_sufficiency(len(eligible)),
                    signed_bias_hours=metrics.signed_bias_hours,
                    mae_hours=metrics.mae_hours,
                    overrun_rate=metrics.overrun_rate,
                    interval_coverage=metrics.interval_coverage,
                    multiplier_median=metrics.multiplier_median,
                    multiplier_lower=metrics.multiplier_lower,
                    multiplier_upper=metrics.multiplier_upper,
                    algorithm_version=ALGORITHM_VERSION,
                    sample_ids_json=_json([row.id for row in sample_rows]),
                )
                session.add(run)
                session.flush()

                if run.sufficiency == "actionable" and sample_rows:
                    sample_start = min(_aware(row.finalized_at) for row in sample_rows)
                    sample_end = max(_aware(row.finalized_at) for row in sample_rows)
                    targets = list(
                        session.scalars(
                            select(BusinessProject)
                            .where(BusinessProject.estimated_hours > 0)
                            .order_by(BusinessProject.id)
                        )
                    )
                    for project in targets:
                        if project.status in TERMINAL_PROJECT_STATUSES:
                            continue
                        terminal_issue = session.scalar(
                            select(ProjectSettlementIssueRecord.id)
                            .where(
                                ProjectSettlementIssueRecord.project_id == project.id,
                                ProjectSettlementIssueRecord.issue_type.in_(TERMINAL_SETTLEMENT_ISSUES),
                            )
                            .limit(1)
                        )
                        if terminal_issue is not None:
                            continue
                        suggested, lower, upper = self._suggestion_values(
                            float(project.estimated_hours), metrics
                        )
                        session.add(
                            EstimateCalibrationSuggestion(
                                id=f"estimate-calibration-suggestion-{uuid4()}",
                                run_id=run.id,
                                project_id=project.id,
                                project_name=project.name,
                                original_estimated_hours=float(project.estimated_hours),
                                suggested_hours=suggested,
                                lower_hours=lower,
                                upper_hours=upper,
                                sample_count=len(sample_rows),
                                sample_start_at=sample_start,
                                sample_end_at=sample_end,
                                basis_json=_json(
                                    [
                                        f"{len(sample_rows)} 个已验证且已冻结的项目结果",
                                        "建议值采用 actual/estimate 比率中位数",
                                        "建议区间采用历史比率 P25–P75",
                                    ]
                                ),
                                invalidation_conditions_json=_json(INVALIDATION_CONDITIONS),
                            )
                        )

                session.add(
                    EstimateCalibrationMutationRequest(
                        request_id=request_id,
                        operation=operation,
                        payload_hash=digest,
                        result_json=_json({"run_id": run.id}),
                    )
                )
                session.commit()
                summary = self._run_summary(run)
                start_at, end_at = self._sample_window(candidates)
                return summary.model_copy(
                    update={
                        "candidates": [row.view for row in candidates],
                        "sample_start_at": start_at,
                        "sample_end_at": end_at,
                    }
                )
        except CalibrationRepositoryError:
            raise
        except (SQLAlchemyError, LookupError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CalibrationRepositoryError from exc

    @staticmethod
    def _quote_from_suggestion(
        project: BusinessProject,
        suggestion: EstimateCalibrationSuggestion,
    ) -> CalibrationQuoteAssistView:
        return CalibrationQuoteAssistView(
            project_id=project.id,
            project_name=project.name,
            original_estimated_hours=float(project.estimated_hours),
            run_id=suggestion.run_id,
            suggestion_id=suggestion.id,
            suggestion_revision=suggestion.revision,
            sample_count=suggestion.sample_count,
            sufficiency="actionable",
            suggested_hours=suggestion.suggested_hours,
            lower_hours=suggestion.lower_hours,
            upper_hours=suggestion.upper_hours,
            adopted_hours=suggestion.adopted_hours,
            status=suggestion.status,  # type: ignore[arg-type]
            sample_start_at=suggestion.sample_start_at,
            sample_end_at=suggestion.sample_end_at,
            basis=json.loads(suggestion.basis_json or "[]"),
            invalidation_conditions=json.loads(
                suggestion.invalidation_conditions_json or "[]"
            ),
        )

    def quote_assist(self, project_id: str) -> CalibrationQuoteAssistView:
        try:
            with self.database.session() as session:
                project = session.get(BusinessProject, project_id)
                if project is None:
                    raise CalibrationNotFound
                suggestion = session.scalar(
                    select(EstimateCalibrationSuggestion)
                    .where(EstimateCalibrationSuggestion.project_id == project_id)
                    .order_by(EstimateCalibrationSuggestion.created_at.desc())
                    .limit(1)
                )
                if suggestion is not None:
                    return self._quote_from_suggestion(project, suggestion)
                candidates = self._candidates(session, self._normalized_cutoff(None))
                eligible = [row for row in candidates if row.view.eligible]
                metrics = self._metrics(candidates)
                sufficiency = _sufficiency(len(eligible))
                start_at, end_at = self._sample_window(candidates)
                if sufficiency != "actionable" or float(project.estimated_hours) <= 0:
                    return CalibrationQuoteAssistView(
                        project_id=project.id,
                        project_name=project.name,
                        original_estimated_hours=float(project.estimated_hours),
                        sample_count=len(eligible),
                        sufficiency=sufficiency,  # type: ignore[arg-type]
                        status="unavailable",
                        sample_start_at=start_at,
                        sample_end_at=end_at,
                        invalidation_conditions=INVALIDATION_CONDITIONS,
                    )
                suggested, lower, upper = self._suggestion_values(
                    float(project.estimated_hours), metrics
                )
                return CalibrationQuoteAssistView(
                    project_id=project.id,
                    project_name=project.name,
                    original_estimated_hours=float(project.estimated_hours),
                    sample_count=len(eligible),
                    sufficiency="actionable",
                    suggested_hours=suggested,
                    lower_hours=lower,
                    upper_hours=upper,
                    status="preview",
                    sample_start_at=start_at,
                    sample_end_at=end_at,
                    basis=[
                        f"{len(eligible)} 个已验证且已冻结的项目结果",
                        "运行一次校准快照后才能人工采纳或拒绝",
                    ],
                    invalidation_conditions=INVALIDATION_CONDITIONS,
                )
        except CalibrationRepositoryError:
            raise
        except (SQLAlchemyError, LookupError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CalibrationRepositoryError from exc

    def decide(
        self,
        project_id: str,
        suggestion_id: str,
        payload: CalibrationDecisionRequest,
    ) -> CalibrationQuoteAssistView:
        operation = "decide_calibration_suggestion"
        body = {
            "project_id": project_id,
            "suggestion_id": suggestion_id,
            **payload.model_dump(mode="json"),
        }
        digest = _hash(body)
        try:
            with self.database.session() as session:
                receipt = session.get(
                    EstimateCalibrationMutationRequest, payload.request_id
                )
                if receipt is not None:
                    if receipt.operation != operation or receipt.payload_hash != digest:
                        raise CalibrationRequestConflict
                    suggestion = session.get(EstimateCalibrationSuggestion, suggestion_id)
                    project = session.get(BusinessProject, project_id)
                    if suggestion is None or project is None:
                        raise CalibrationNotFound
                    return self._quote_from_suggestion(project, suggestion)

                suggestion = session.get(EstimateCalibrationSuggestion, suggestion_id)
                project = session.get(BusinessProject, project_id)
                if suggestion is None or project is None or suggestion.project_id != project_id:
                    raise CalibrationNotFound
                if suggestion.revision != payload.expected_revision:
                    raise CalibrationRevisionConflict
                if suggestion.sample_count < 5:
                    raise CalibrationDecisionInvalid
                if payload.action == "reject" and payload.adopted_hours is not None:
                    raise CalibrationDecisionInvalid
                adopted = (
                    payload.adopted_hours or suggestion.suggested_hours
                    if payload.action == "adopt"
                    else None
                )
                next_revision = suggestion.revision + 1
                suggestion.status = "adopted" if payload.action == "adopt" else "rejected"
                suggestion.adopted_hours = round(float(adopted), 2) if adopted is not None else None
                suggestion.revision = next_revision
                suggestion.decided_at = utcnow()
                session.add(
                    EstimateCalibrationDecision(
                        id=f"estimate-calibration-decision-{uuid4()}",
                        suggestion_id=suggestion.id,
                        project_id=project_id,
                        request_id=payload.request_id,
                        action=payload.action,
                        expected_revision=payload.expected_revision,
                        resulting_revision=next_revision,
                        adopted_hours=suggestion.adopted_hours,
                        note=payload.note,
                        payload_hash=digest,
                    )
                )
                session.add(
                    EstimateCalibrationMutationRequest(
                        request_id=payload.request_id,
                        operation=operation,
                        payload_hash=digest,
                        result_json=_json(
                            {
                                "suggestion_id": suggestion.id,
                                "revision": next_revision,
                                "status": suggestion.status,
                            }
                        ),
                    )
                )
                session.commit()
                return self._quote_from_suggestion(project, suggestion)
        except CalibrationRepositoryError:
            raise
        except (SQLAlchemyError, LookupError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CalibrationRepositoryError from exc
