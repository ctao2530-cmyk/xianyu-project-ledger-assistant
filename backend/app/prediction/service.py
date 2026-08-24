from __future__ import annotations

from datetime import date, datetime, time, timezone
import json

from sqlalchemy import select

from ..database import Database
from ..ledger import LedgerService
from ..models import PredictionEvaluationRecord, PredictionResultRecord
from ..services.project_outcomes import ProjectOutcomeService
from ..services.project_progress import ProjectProgressService
from .baseline_models import ENGINE_VERSION, build_all_predictions
from .feature_service import FEATURE_SCHEMA_VERSION, PREDICTION_TIMEZONE, PredictionFeatureService
from .repository import PredictionRepository
from .schemas import PredictionLatestView, PredictionResult, PredictionRunView


class PredictionService:
    """Read-only baseline prediction orchestration.

    Only prediction runs/evaluations are persisted. No method in this service
    mutates customer, project, quote, finance, product, or conversation facts.
    """

    def __init__(
        self,
        database: Database,
        ledger: LedgerService,
        outcomes: ProjectOutcomeService | None = None,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.outcomes = outcomes or ProjectOutcomeService()
        self.progress = ProjectProgressService()
        self.features = PredictionFeatureService(database, ledger, self.outcomes)
        self.repository = PredictionRepository(database)

    @staticmethod
    def summarize(run: PredictionRunView) -> PredictionLatestView:
        workload = next(
            (row for row in run.results if row.target == "workload_14d"), None
        )
        cashflow = next(
            (row for row in run.results if row.target == "cashflow_30d"), None
        )
        projects = sorted(
            [row for row in run.results if row.target == "project_delay_risk"],
            key=lambda row: (row.score or 0, row.entity_id or ""),
            reverse=True,
        )
        customers = sorted(
            [
                row
                for row in run.results
                if row.target == "customer_followup_priority"
            ],
            key=lambda row: (row.score or 0, row.entity_id or ""),
            reverse=True,
        )
        return PredictionLatestView(
            run=run,
            workload=workload,
            cashflow=cashflow,
            high_risk_projects=projects[:5],
            priority_customers=customers[:5],
        )

    def preview(self, *, now: datetime | None = None) -> PredictionRunView:
        bundle = self.features.build(now=now)
        return PredictionRunView(
            generated_at=bundle.generated_at,
            input_snapshot_hash=bundle.input_snapshot_hash,
            ledger_revision=bundle.ledger_revision,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            engine_version=ENGINE_VERSION,
            timezone=PREDICTION_TIMEZONE,
            results=build_all_predictions(bundle),
        )

    def latest_or_preview(self, *, now: datetime | None = None) -> PredictionRunView:
        latest = self.repository.latest()
        if latest is None:
            return self.preview(now=now)
        current = self.features.build(now=now)
        return latest.model_copy(
            update={"is_stale": latest.input_snapshot_hash != current.input_snapshot_hash}
        )

    def latest_summary(self, *, now: datetime | None = None) -> PredictionLatestView:
        return self.summarize(self.latest_or_preview(now=now))

    def run(
        self,
        *,
        request_id: str,
        now: datetime | None = None,
    ) -> PredictionRunView:
        replay = self.repository.get_by_request_id(request_id)
        if replay is not None:
            return replay
        self.evaluate_matured_project_delays(now=now)
        return self.repository.persist(self.preview(now=now), request_id=request_id)

    def evaluate_matured_project_delays(
        self,
        *,
        now: datetime | None = None,
    ) -> int:
        """Idempotently close mature delay predictions from verified outcomes.

        This method is called only by an explicit prediction-run write. Read
        endpoints never create evaluations. The planned due date is read from
        the immutable prediction fact snapshot, not the project's current date.
        """

        captured_at = now or datetime.now(timezone.utc)
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        captured_at = captured_at.astimezone(timezone.utc).replace(microsecond=0)
        pending: list[tuple[str, bool, str]] = []
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(PredictionResultRecord)
                    .where(
                        PredictionResultRecord.target == "project_delay_risk",
                        PredictionResultRecord.entity_id.is_not(None),
                        PredictionResultRecord.horizon_end <= captured_at,
                        ~PredictionResultRecord.id.in_(
                            select(PredictionEvaluationRecord.result_id)
                        ),
                    )
                    .order_by(PredictionResultRecord.horizon_end, PredictionResultRecord.id)
                )
            )
            for row in rows:
                facts = json.loads(row.facts_json or "[]")
                due_value = next(
                    (
                        item.get("value")
                        for item in facts
                        if isinstance(item, dict) and item.get("key") == "planned_due_date"
                    ),
                    None,
                )
                if not isinstance(due_value, str) or not due_value:
                    continue
                try:
                    due_date = date.fromisoformat(due_value)
                    due_cutoff = datetime.combine(due_date, time.max, tzinfo=timezone.utc)
                    progress = self.progress.calculate(session, str(row.entity_id))
                    outcome = self.outcomes.build(
                        session,
                        str(row.entity_id),
                        verified_progress=progress.verified_delivery.percent,
                    )
                except (ValueError, LookupError):
                    continue
                if outcome.available_at.tzinfo is None:
                    available_at = outcome.available_at.replace(tzinfo=timezone.utc)
                else:
                    available_at = outcome.available_at.astimezone(timezone.utc)
                if available_at > captured_at:
                    continue
                completed_at = outcome.actual_completed_at
                if completed_at is not None:
                    if completed_at.tzinfo is None:
                        completed_at = completed_at.replace(tzinfo=timezone.utc)
                    else:
                        completed_at = completed_at.astimezone(timezone.utc)
                delayed = completed_at is None or completed_at > due_cutoff
                pending.append(
                    (
                        row.id,
                        delayed,
                        "按预测时保存的交付日期与 verified 项目结果回填；"
                        f"cutoff_at={captured_at.isoformat()}",
                    )
                )
        for result_id, delayed, note in pending:
            self.repository.evaluate(
                result_id,
                request_id=f"auto-delay-eval:{result_id}",
                actual_value=delayed,
                evaluation_method="ledger_actual",
                evaluated_at=captured_at,
                note=note,
            )
        return len(pending)

    def target(
        self,
        target: str,
        *,
        now: datetime | None = None,
    ) -> list[PredictionResult]:
        return [
            row for row in self.latest_or_preview(now=now).results if row.target == target
        ]

    def project(self, project_id: str, *, now: datetime | None = None) -> PredictionResult | None:
        return next(
            (
                row
                for row in self.latest_or_preview(now=now).results
                if row.target == "project_delay_risk" and row.entity_id == project_id
            ),
            None,
        )

    def customer(self, customer_id: str, *, now: datetime | None = None) -> PredictionResult | None:
        return next(
            (
                row
                for row in self.latest_or_preview(now=now).results
                if row.target == "customer_followup_priority"
                and row.entity_id == customer_id
            ),
            None,
        )

    def evaluate(
        self,
        result_id: str,
        *,
        request_id: str,
        actual_value: float | int | bool | str,
        evaluation_method: str,
        evaluated_at: datetime | None,
        note: str,
    ) -> PredictionResult:
        captured_at = evaluated_at or datetime.now(timezone.utc)
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        return self.repository.evaluate(
            result_id,
            request_id=request_id,
            actual_value=actual_value,
            evaluation_method=evaluation_method,
            evaluated_at=captured_at.astimezone(timezone.utc).replace(microsecond=0),
            note=note.strip(),
        )
