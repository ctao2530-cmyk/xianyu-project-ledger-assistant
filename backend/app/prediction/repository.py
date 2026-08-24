from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..database import Database
from ..models import (
    PredictionEvaluationRecord,
    PredictionResultRecord,
    PredictionRun,
)
from .feature_service import FEATURE_SCHEMA_VERSION, PREDICTION_TIMEZONE
from .schemas import PredictionResult, PredictionRunView
from .baseline_models import ENGINE_VERSION


class PredictionRepositoryError(RuntimeError):
    safe_message = "预测记录暂时无法读取"


class PredictionResultNotFound(PredictionRepositoryError):
    safe_message = "预测结果不存在"


class PredictionEvaluationConflict(PredictionRepositoryError):
    safe_message = "该预测评估请求已用于不同内容"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


class PredictionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _evaluation_value(value: str) -> Any:
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None

    def _result_schema(
        self,
        row: PredictionResultRecord,
        run: PredictionRun,
        evaluation: PredictionEvaluationRecord | None,
    ) -> PredictionResult:
        return PredictionResult(
            id=row.id,
            run_id=row.run_id,
            target=row.target,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            entity_label=row.entity_label,
            horizon=row.horizon,
            horizon_days=row.horizon_days,
            generated_at=run.generated_at,
            horizon_start=row.horizon_start,
            horizon_end=row.horizon_end,
            prediction_value=row.prediction_value,
            lower_bound=row.lower_bound,
            upper_bound=row.upper_bound,
            score=row.score,
            risk_level=row.risk_level,
            data_sufficiency=row.data_sufficiency,
            method=row.method,
            model_version=row.model_version,
            summary=row.summary,
            drivers=json.loads(row.drivers_json or "[]"),
            facts=json.loads(row.facts_json or "[]"),
            evidence_refs=json.loads(row.evidence_refs_json or "[]"),
            actual_value=(
                self._evaluation_value(evaluation.actual_value_json)
                if evaluation is not None
                else None
            ),
            evaluated_at=evaluation.evaluated_at if evaluation is not None else None,
            evaluation_method=(
                evaluation.evaluation_method if evaluation is not None else None
            ),
        )

    def _run_schema(self, session, run: PredictionRun) -> PredictionRunView:
        rows = list(
            session.scalars(
                select(PredictionResultRecord)
                .where(PredictionResultRecord.run_id == run.id)
                .order_by(PredictionResultRecord.position.asc())
            )
        )
        evaluations: dict[str, PredictionEvaluationRecord] = {}
        if rows:
            all_evaluations = list(
                session.scalars(
                    select(PredictionEvaluationRecord)
                    .where(
                        PredictionEvaluationRecord.result_id.in_([row.id for row in rows])
                    )
                    .order_by(
                        PredictionEvaluationRecord.evaluated_at.desc(),
                        PredictionEvaluationRecord.created_at.desc(),
                    )
                )
            )
            for evaluation in all_evaluations:
                evaluations.setdefault(evaluation.result_id, evaluation)
        return PredictionRunView(
            id=run.id,
            request_id=run.request_id,
            record_status="completed",
            generated_at=run.generated_at,
            input_snapshot_hash=run.input_snapshot_hash,
            ledger_revision=run.ledger_revision,
            feature_schema_version=run.feature_schema_version,
            engine_version=run.engine_version,
            timezone=run.timezone,
            results=[
                self._result_schema(row, run, evaluations.get(row.id)) for row in rows
            ],
        )

    def latest(self) -> PredictionRunView | None:
        try:
            with self.database.session() as session:
                run = session.scalar(
                    select(PredictionRun)
                    .where(PredictionRun.status == "completed")
                    .order_by(PredictionRun.generated_at.desc(), PredictionRun.created_at.desc())
                    .limit(1)
                )
                return self._run_schema(session, run) if run is not None else None
        except (SQLAlchemyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PredictionRepositoryError from exc

    def get_by_request_id(self, request_id: str) -> PredictionRunView | None:
        try:
            with self.database.session() as session:
                run = session.scalar(
                    select(PredictionRun).where(PredictionRun.request_id == request_id)
                )
                return self._run_schema(session, run) if run is not None else None
        except (SQLAlchemyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PredictionRepositoryError from exc

    def persist(self, preview: PredictionRunView, *, request_id: str) -> PredictionRunView:
        try:
            with self.database.session() as session:
                existing = session.scalar(
                    select(PredictionRun).where(PredictionRun.request_id == request_id)
                )
                if existing is not None:
                    return self._run_schema(session, existing)
                run_id = f"prediction-run-{uuid4().hex}"
                completed_at = datetime.now(timezone.utc).replace(microsecond=0)
                run = PredictionRun(
                    id=run_id,
                    request_id=request_id,
                    generated_at=preview.generated_at,
                    input_snapshot_hash=preview.input_snapshot_hash,
                    ledger_revision=preview.ledger_revision,
                    status="completed",
                    feature_schema_version=FEATURE_SCHEMA_VERSION,
                    engine_version=ENGINE_VERSION,
                    timezone=PREDICTION_TIMEZONE,
                    result_count=len(preview.results),
                    completed_at=completed_at,
                )
                session.add(run)
                # No ORM relationship is required for these immutable rows, so
                # flush the parent explicitly before inserting FK children.
                session.flush()
                for position, result in enumerate(preview.results):
                    session.add(
                        PredictionResultRecord(
                            id=f"prediction-result-{uuid4().hex}",
                            run_id=run_id,
                            position=position,
                            target=result.target,
                            entity_type=result.entity_type,
                            entity_id=result.entity_id,
                            entity_label=result.entity_label,
                            horizon=result.horizon,
                            horizon_days=result.horizon_days,
                            horizon_start=result.horizon_start,
                            horizon_end=result.horizon_end,
                            prediction_value=result.prediction_value,
                            lower_bound=result.lower_bound,
                            upper_bound=result.upper_bound,
                            score=result.score,
                            risk_level=result.risk_level,
                            data_sufficiency=result.data_sufficiency,
                            method=result.method,
                            model_version=result.model_version,
                            summary=result.summary,
                            drivers_json=_json(
                                [row.model_dump(mode="json") for row in result.drivers]
                            ),
                            facts_json=_json(
                                [row.model_dump(mode="json") for row in result.facts]
                            ),
                            evidence_refs_json=_json(result.evidence_refs),
                            input_features_json="{}",
                        )
                    )
                session.commit()
                return self._run_schema(session, run)
        except PredictionRepositoryError:
            raise
        except (SQLAlchemyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PredictionRepositoryError from exc

    def evaluate(
        self,
        result_id: str,
        *,
        request_id: str,
        actual_value: float | int | bool | str,
        evaluation_method: str,
        evaluated_at: datetime,
        note: str,
    ) -> PredictionResult:
        payload = {
            "result_id": result_id,
            "actual_value": actual_value,
            "evaluation_method": evaluation_method,
            "evaluated_at": evaluated_at.isoformat(),
            "note": note,
        }
        fingerprint = _payload_hash(payload)
        try:
            with self.database.session() as session:
                replay = session.scalar(
                    select(PredictionEvaluationRecord).where(
                        PredictionEvaluationRecord.request_id == request_id
                    )
                )
                if replay is not None:
                    if replay.result_id != result_id or replay.payload_hash != fingerprint:
                        raise PredictionEvaluationConflict
                    row = session.get(PredictionResultRecord, result_id)
                    run = session.get(PredictionRun, row.run_id) if row else None
                    if row is None or run is None:
                        raise PredictionResultNotFound
                    return self._result_schema(row, run, replay)
                row = session.get(PredictionResultRecord, result_id)
                if row is None:
                    raise PredictionResultNotFound
                run = session.get(PredictionRun, row.run_id)
                if run is None:
                    raise PredictionResultNotFound
                evaluation = PredictionEvaluationRecord(
                    id=f"prediction-evaluation-{uuid4().hex}",
                    result_id=result_id,
                    request_id=request_id,
                    payload_hash=fingerprint,
                    actual_value_json=_json(actual_value),
                    evaluation_method=evaluation_method,
                    evaluated_at=evaluated_at,
                    note=note,
                )
                session.add(evaluation)
                session.commit()
                return self._result_schema(row, run, evaluation)
        except PredictionRepositoryError:
            raise
        except (SQLAlchemyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PredictionRepositoryError from exc
