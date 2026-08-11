from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .business_analysis_schemas import (
    BusinessAnalysisHistoryItem,
    BusinessAnalysisHistoryResponse,
    BusinessAnalysisOverview,
    BusinessAnalysisRecommendation,
    BusinessRecommendationMetricSnapshot,
)
from .database import Database
from .models import (
    BusinessAnalysisRecord,
    BusinessAnalysisRecommendationEvent,
    BusinessAnalysisRecommendationRecord,
    utcnow,
)


class BusinessAnalysisRepositoryError(RuntimeError):
    safe_message = "经营分析记录暂时无法访问"


class BusinessAnalysisDataError(BusinessAnalysisRepositoryError):
    safe_message = "历史经营分析记录无法读取"


class BusinessAnalysisNotFound(BusinessAnalysisRepositoryError):
    safe_message = "经营分析记录不存在"


class RecommendationNotFound(BusinessAnalysisRepositoryError):
    safe_message = "经营建议不存在"


class RecommendationVersionConflict(BusinessAnalysisRepositoryError):
    safe_message = "建议状态已在其他页面更新，请刷新后重试"

    def __init__(self, current_version: int) -> None:
        super().__init__(self.safe_message)
        self.current_version = current_version


class RecommendationRequestConflict(BusinessAnalysisRepositoryError):
    safe_message = "该请求编号已经用于其他建议更新"


class RecommendationTransitionError(BusinessAnalysisRepositoryError):
    safe_message = "当前建议状态不支持这次更新"


@dataclass(frozen=True, slots=True)
class StoredBusinessAnalysis:
    result: BusinessAnalysisOverview
    snapshot_hash: str


@dataclass(frozen=True, slots=True)
class StoredBusinessRecommendation:
    result: BusinessAnalysisRecommendation
    snapshot_hash: str
    analysis_snapshot_time: datetime


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise BusinessAnalysisDataError from exc
    if not isinstance(parsed, list) or not all(isinstance(row, str) for row in parsed):
        raise BusinessAnalysisDataError
    return parsed


def _metric_snapshot(value: str) -> BusinessRecommendationMetricSnapshot | None:
    if not value or value == "{}":
        return None
    try:
        return BusinessRecommendationMetricSnapshot.model_validate_json(value)
    except (TypeError, ValueError) as exc:
        raise BusinessAnalysisDataError from exc


def _payload_hash(
    *,
    recommendation_id: str,
    event_type: str,
    payload: dict[str, object],
) -> str:
    encoded = json.dumps(
        {
            "recommendation_id": recommendation_id,
            "event_type": event_type,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _observe_days(value: str) -> int | None:
    match = re.search(r"\b(\d{1,3})\b", value)
    return int(match.group(1)) if match else None


def _result_insight_count(value: str) -> int:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise BusinessAnalysisDataError from exc
    if not isinstance(parsed, dict):
        raise BusinessAnalysisDataError
    insights = parsed.get("insights")
    if not isinstance(insights, list) or not all(
        isinstance(row, dict) for row in insights
    ):
        raise BusinessAnalysisDataError
    return len(insights)


class BusinessAnalysisRepository:
    """Persistence boundary for analysis snapshots and manual feedback only."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _recommendation_schema(
        row: BusinessAnalysisRecommendationRecord,
        *,
        analysis_snapshot_time: datetime | None = None,
    ) -> BusinessAnalysisRecommendation:
        return BusinessAnalysisRecommendation(
            id=row.id,
            analysis_id=row.analysis_id,
            analysis_snapshot_time=analysis_snapshot_time,
            source_key=row.source_key,
            domain=row.domain,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            entity_label=row.entity_label,
            target_scope=row.target_scope,
            priority=row.priority,
            title=row.title,
            problem=row.problem,
            action=row.action,
            reason=row.reason,
            data_source=_json_list(row.data_sources_json),
            confidence=row.confidence,
            observe_period=row.observe_period,
            observe_days=row.observe_days,
            status=row.status,
            lifecycle_status=row.status,
            version=row.version,
            user_note=row.user_note,
            target_page=row.target_page,
            execution_mode="manual",
            evidence_refs=_json_list(row.evidence_refs_json),
            accepted_at=row.accepted_at,
            started_at=row.started_at,
            observe_until=row.observe_until,
            completed_at=row.completed_at,
            baseline_metrics=_metric_snapshot(row.baseline_metrics_json),
            result_metrics=_metric_snapshot(row.result_metrics_json),
            outcome=row.outcome,
            actual_cost=row.actual_cost,
            actual_hours=row.actual_hours,
            user_conclusion=row.user_conclusion,
            execution_ref_type=row.execution_ref_type,
            execution_ref_id=row.execution_ref_id,
        )

    def _hydrate_record(
        self,
        session,
        record: BusinessAnalysisRecord,
    ) -> StoredBusinessAnalysis:
        try:
            result = BusinessAnalysisOverview.model_validate_json(record.result_json)
        except (TypeError, ValueError) as exc:
            raise BusinessAnalysisDataError from exc
        rows = list(
            session.scalars(
                select(BusinessAnalysisRecommendationRecord)
                .where(BusinessAnalysisRecommendationRecord.analysis_id == record.id)
                .order_by(
                    BusinessAnalysisRecommendationRecord.position,
                    BusinessAnalysisRecommendationRecord.id,
                )
            ).all()
        )
        result = result.model_copy(
            update={
                "analysis_id": record.id,
                "record_status": "completed",
                "provider": record.provider,
                "model": record.model,
                "ai_status": record.ai_status,
                "fallback_used": record.fallback_used,
                "snapshot_time": record.snapshot_time,
                "recommendations": [
                    self._recommendation_schema(
                        row,
                        analysis_snapshot_time=record.snapshot_time,
                    )
                    for row in rows
                ],
            }
        )
        return StoredBusinessAnalysis(result=result, snapshot_hash=record.snapshot_hash)

    def get_by_request_id(self, request_id: str) -> StoredBusinessAnalysis | None:
        try:
            with self.database.session() as session:
                record = session.scalar(
                    select(BusinessAnalysisRecord).where(
                        BusinessAnalysisRecord.request_id == request_id
                    )
                )
                return self._hydrate_record(session, record) if record else None
        except BusinessAnalysisRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise BusinessAnalysisRepositoryError from exc

    def latest(self) -> StoredBusinessAnalysis | None:
        try:
            with self.database.session() as session:
                record = session.scalar(
                    select(BusinessAnalysisRecord)
                    .where(BusinessAnalysisRecord.status == "completed")
                    .order_by(
                        BusinessAnalysisRecord.snapshot_time.desc(),
                        BusinessAnalysisRecord.created_at.desc(),
                    )
                    .limit(1)
                )
                return self._hydrate_record(session, record) if record else None
        except BusinessAnalysisRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise BusinessAnalysisRepositoryError from exc

    def get(self, analysis_id: str) -> StoredBusinessAnalysis:
        try:
            with self.database.session() as session:
                record = session.get(BusinessAnalysisRecord, analysis_id)
                if record is None:
                    raise BusinessAnalysisNotFound
                return self._hydrate_record(session, record)
        except BusinessAnalysisRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise BusinessAnalysisRepositoryError from exc

    def save_completed(
        self,
        *,
        request_id: str,
        snapshot_hash: str,
        result: BusinessAnalysisOverview,
    ) -> StoredBusinessAnalysis:
        existing = self.get_by_request_id(request_id)
        if existing is not None:
            return existing

        analysis_id = f"analysis-{uuid4().hex}"
        completed_at = utcnow()
        snapshot_time = result.snapshot_time or result.generated_at
        recommendations: list[BusinessAnalysisRecommendation] = []
        rows: list[BusinessAnalysisRecommendationRecord] = []
        for position, recommendation in enumerate(result.recommendations):
            recommendation_id = f"recommendation-{uuid4().hex}"
            source_key = recommendation.source_key or recommendation.id
            persisted = recommendation.model_copy(
                update={
                    "id": recommendation_id,
                    "analysis_id": analysis_id,
                    "analysis_snapshot_time": snapshot_time,
                    "source_key": source_key,
                    "target_scope": (
                        "entity"
                        if recommendation.entity_id
                        else "portfolio"
                        if recommendation.domain == "portfolio"
                        else "domain"
                    ),
                    "status": "pending",
                    "lifecycle_status": "pending",
                    "version": 1,
                    "user_note": "",
                }
            )
            recommendations.append(persisted)
            rows.append(
                BusinessAnalysisRecommendationRecord(
                    id=recommendation_id,
                    analysis_id=analysis_id,
                    source_key=source_key,
                    position=position,
                    domain=persisted.domain,
                    entity_type=persisted.entity_type,
                    entity_id=persisted.entity_id,
                    entity_label=persisted.entity_label,
                    title=persisted.title,
                    problem=persisted.problem,
                    reason=persisted.reason,
                    action=persisted.action,
                    priority=persisted.priority,
                    confidence=persisted.confidence,
                    observe_period=persisted.observe_period,
                    observe_days=_observe_days(persisted.observe_period),
                    data_sources_json=json.dumps(
                        persisted.data_source,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    evidence_refs_json=json.dumps(
                        persisted.evidence_refs,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    target_page=persisted.target_page,
                    target_scope=(
                        "entity"
                        if persisted.entity_id
                        else "portfolio"
                        if persisted.domain == "portfolio"
                        else "domain"
                    ),
                    execution_mode="manual",
                    status="pending",
                    version=1,
                    user_note="",
                )
            )

        persisted_result = result.model_copy(
            update={
                "analysis_id": analysis_id,
                "record_status": "completed",
                "snapshot_time": snapshot_time,
                "recommendations": recommendations,
                "is_stale": False,
            }
        )
        record = BusinessAnalysisRecord(
            id=analysis_id,
            request_id=request_id,
            snapshot_time=snapshot_time,
            snapshot_hash=snapshot_hash,
            ledger_revision=persisted_result.ledger_revision,
            status="completed",
            analysis_method=persisted_result.analysis_method,
            provider=persisted_result.provider,
            model=persisted_result.model,
            ai_status=persisted_result.ai_status,
            fallback_used=persisted_result.fallback_used,
            summary=persisted_result.summary,
            result_json=persisted_result.model_dump_json(),
            error_code=(
                persisted_result.ai_error.code if persisted_result.ai_error else None
            ),
            error_message=(
                persisted_result.ai_error.message if persisted_result.ai_error else None
            ),
            completed_at=completed_at,
        )
        try:
            with self.database.session() as session:
                session.add(record)
                # The rows are assembled without ORM relationships so that the
                # persistence layer stays explicit. Flush the parent first to
                # satisfy SQLite foreign-key ordering inside the same transaction.
                session.flush()
                session.add_all(rows)
                session.commit()
        except IntegrityError as exc:
            existing = self.get_by_request_id(request_id)
            if existing is not None:
                return existing
            raise BusinessAnalysisRepositoryError from exc
        except SQLAlchemyError as exc:
            raise BusinessAnalysisRepositoryError from exc
        return StoredBusinessAnalysis(result=persisted_result, snapshot_hash=snapshot_hash)

    def history(self, *, limit: int, offset: int) -> BusinessAnalysisHistoryResponse:
        try:
            with self.database.session() as session:
                total = int(
                    session.scalar(select(func.count(BusinessAnalysisRecord.id))) or 0
                )
                records = list(
                    session.scalars(
                        select(BusinessAnalysisRecord)
                        .where(BusinessAnalysisRecord.status == "completed")
                        .order_by(
                            BusinessAnalysisRecord.snapshot_time.desc(),
                            BusinessAnalysisRecord.created_at.desc(),
                        )
                        .limit(limit)
                        .offset(offset)
                    ).all()
                )
                items: list[BusinessAnalysisHistoryItem] = []
                for record in records:
                    insight_count = _result_insight_count(record.result_json)
                    recommendation_count = int(
                        session.scalar(
                            select(
                                func.count(BusinessAnalysisRecommendationRecord.id)
                            ).where(
                                BusinessAnalysisRecommendationRecord.analysis_id
                                == record.id
                            )
                        )
                        or 0
                    )
                    pending_count = int(
                        session.scalar(
                            select(
                                func.count(BusinessAnalysisRecommendationRecord.id)
                            ).where(
                                BusinessAnalysisRecommendationRecord.analysis_id
                                == record.id,
                                BusinessAnalysisRecommendationRecord.status == "pending",
                            )
                        )
                        or 0
                    )
                    items.append(
                        BusinessAnalysisHistoryItem(
                            id=record.id,
                            snapshot_time=record.snapshot_time,
                            created_at=record.created_at,
                            provider=record.provider,
                            model=record.model,
                            ai_status=record.ai_status,
                            fallback_used=record.fallback_used,
                            status="completed",
                            summary=record.summary,
                            insight_count=insight_count,
                            recommendation_count=recommendation_count,
                            pending_recommendation_count=pending_count,
                        )
                    )
                return BusinessAnalysisHistoryResponse(
                    items=items,
                    total=total,
                    limit=limit,
                    offset=offset,
                )
        except BusinessAnalysisRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise BusinessAnalysisRepositoryError from exc

    def get_recommendation(
        self,
        recommendation_id: str,
    ) -> StoredBusinessRecommendation:
        try:
            with self.database.session() as session:
                row = session.get(BusinessAnalysisRecommendationRecord, recommendation_id)
                if row is None:
                    raise RecommendationNotFound
                analysis = session.get(BusinessAnalysisRecord, row.analysis_id)
                if analysis is None:
                    raise BusinessAnalysisDataError
                return StoredBusinessRecommendation(
                    result=self._recommendation_schema(
                        row,
                        analysis_snapshot_time=analysis.snapshot_time,
                    ),
                    snapshot_hash=analysis.snapshot_hash,
                    analysis_snapshot_time=analysis.snapshot_time,
                )
        except BusinessAnalysisRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise BusinessAnalysisRepositoryError from exc

    def list_recommendations(self) -> list[StoredBusinessRecommendation]:
        try:
            with self.database.session() as session:
                pairs = list(
                    session.execute(
                        select(
                            BusinessAnalysisRecommendationRecord,
                            BusinessAnalysisRecord,
                        )
                        .join(
                            BusinessAnalysisRecord,
                            BusinessAnalysisRecommendationRecord.analysis_id
                            == BusinessAnalysisRecord.id,
                        )
                        .where(BusinessAnalysisRecord.status == "completed")
                        .order_by(
                            BusinessAnalysisRecord.snapshot_time.desc(),
                            BusinessAnalysisRecommendationRecord.position,
                            BusinessAnalysisRecommendationRecord.id,
                        )
                    ).all()
                )
                return [
                    StoredBusinessRecommendation(
                        result=self._recommendation_schema(
                            row,
                            analysis_snapshot_time=analysis.snapshot_time,
                        ),
                        snapshot_hash=analysis.snapshot_hash,
                        analysis_snapshot_time=analysis.snapshot_time,
                    )
                    for row, analysis in pairs
                ]
        except BusinessAnalysisRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise BusinessAnalysisRepositoryError from exc

    @staticmethod
    def _event_result(
        session,
        *,
        request_id: str,
        recommendation_id: str,
        event_type: str,
        payload_hash: str,
    ) -> StoredBusinessRecommendation | None:
        event = session.scalar(
            select(BusinessAnalysisRecommendationEvent).where(
                BusinessAnalysisRecommendationEvent.request_id == request_id
            )
        )
        if event is None:
            return None
        if (
            event.recommendation_id != recommendation_id
            or event.event_type != event_type
            or event.payload_hash != payload_hash
        ):
            raise RecommendationRequestConflict
        try:
            result = BusinessAnalysisRecommendation.model_validate_json(event.result_json)
        except (TypeError, ValueError) as exc:
            raise BusinessAnalysisDataError from exc
        row = session.get(BusinessAnalysisRecommendationRecord, recommendation_id)
        if row is None:
            raise RecommendationNotFound
        analysis = session.get(BusinessAnalysisRecord, row.analysis_id)
        if analysis is None:
            raise BusinessAnalysisDataError
        return StoredBusinessRecommendation(
            result=result,
            snapshot_hash=analysis.snapshot_hash,
            analysis_snapshot_time=analysis.snapshot_time,
        )

    def transition_recommendation(
        self,
        recommendation_id: str,
        *,
        event_type: str,
        to_status: str,
        allowed_from: set[str],
        expected_version: int,
        request_id: str,
        payload: dict[str, object],
        changes: dict[str, object],
    ) -> StoredBusinessRecommendation:
        allowed_changes = {
            "target_scope",
            "user_note",
            "accepted_at",
            "started_at",
            "observe_until",
            "completed_at",
            "baseline_metrics_json",
            "result_metrics_json",
            "outcome",
            "actual_cost",
            "actual_hours",
            "user_conclusion",
            "execution_ref_type",
            "execution_ref_id",
        }
        if not set(changes).issubset(allowed_changes):
            raise ValueError("unsupported recommendation mutation field")
        fingerprint = _payload_hash(
            recommendation_id=recommendation_id,
            event_type=event_type,
            payload=payload,
        )
        try:
            with self.database.session() as session:
                replay = self._event_result(
                    session,
                    request_id=request_id,
                    recommendation_id=recommendation_id,
                    event_type=event_type,
                    payload_hash=fingerprint,
                )
                if replay is not None:
                    return replay

                row = session.get(BusinessAnalysisRecommendationRecord, recommendation_id)
                if row is None:
                    raise RecommendationNotFound
                analysis = session.get(BusinessAnalysisRecord, row.analysis_id)
                if analysis is None:
                    raise BusinessAnalysisDataError
                legacy_request = session.scalar(
                    select(BusinessAnalysisRecommendationRecord.id).where(
                        BusinessAnalysisRecommendationRecord.last_request_id
                        == request_id
                    )
                )
                if legacy_request is not None:
                    raise RecommendationRequestConflict
                if row.version != expected_version:
                    raise RecommendationVersionConflict(row.version)
                if row.status not in allowed_from:
                    raise RecommendationTransitionError

                from_status = row.status
                for field, value in changes.items():
                    setattr(row, field, value)
                row.status = to_status
                row.version += 1
                row.last_request_id = request_id
                row.updated_at = utcnow()
                session.flush()
                result = self._recommendation_schema(
                    row,
                    analysis_snapshot_time=analysis.snapshot_time,
                )
                session.add(
                    BusinessAnalysisRecommendationEvent(
                        id=f"recommendation-event-{uuid4().hex}",
                        recommendation_id=recommendation_id,
                        event_type=event_type,
                        from_status=from_status,
                        to_status=to_status,
                        request_id=request_id,
                        payload_hash=fingerprint,
                        result_json=result.model_dump_json(),
                    )
                )
                session.commit()
                return StoredBusinessRecommendation(
                    result=result,
                    snapshot_hash=analysis.snapshot_hash,
                    analysis_snapshot_time=analysis.snapshot_time,
                )
        except BusinessAnalysisRepositoryError:
            raise
        except IntegrityError as exc:
            try:
                with self.database.session() as session:
                    replay = self._event_result(
                        session,
                        request_id=request_id,
                        recommendation_id=recommendation_id,
                        event_type=event_type,
                        payload_hash=fingerprint,
                    )
                    if replay is not None:
                        return replay
            except BusinessAnalysisRepositoryError:
                raise
            raise BusinessAnalysisRepositoryError from exc
        except SQLAlchemyError as exc:
            raise BusinessAnalysisRepositoryError from exc

    def replay_recommendation_event(
        self,
        recommendation_id: str,
        *,
        event_type: str,
        request_id: str,
        payload: dict[str, object],
    ) -> StoredBusinessRecommendation | None:
        fingerprint = _payload_hash(
            recommendation_id=recommendation_id,
            event_type=event_type,
            payload=payload,
        )
        try:
            with self.database.session() as session:
                return self._event_result(
                    session,
                    request_id=request_id,
                    recommendation_id=recommendation_id,
                    event_type=event_type,
                    payload_hash=fingerprint,
                )
        except BusinessAnalysisRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise BusinessAnalysisRepositoryError from exc
