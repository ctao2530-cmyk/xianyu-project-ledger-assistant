from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..business_analysis_repository import (
    BusinessAnalysisRepository,
    StoredBusinessRecommendation,
)
from ..business_analysis_schemas import (
    BusinessAnalysisOverview,
    BusinessAnalysisRecommendation,
    BusinessAnalysisRecommendationQueueCounts,
    BusinessAnalysisRecommendationQueueResponse,
    BusinessRecommendationMetricSnapshot,
    BusinessRecommendationMetricValue,
    RecommendationOutcome,
)
from ..database import Database
from ..models import Item, ProductModificationExperiment, utcnow

if TYPE_CHECKING:
    from .business_analysis import BusinessAnalysisService
    from .product_intelligence import ProductIntelligenceService


class BusinessRecommendationServiceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ProductExperimentState:
    id: str
    item_external_id: str
    item_title: str
    baseline: dict[str, object]
    result: dict[str, object]
    started_at: datetime
    observation_until: datetime
    status: str
    decision: str


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError) as exc:
        raise BusinessRecommendationServiceError(
            "recommendation_execution_data_invalid",
            "关联的商品实验记录无法读取",
            status_code=500,
        ) from exc
    if not isinstance(parsed, dict):
        raise BusinessRecommendationServiceError(
            "recommendation_execution_data_invalid",
            "关联的商品实验记录无法读取",
            status_code=500,
        )
    return parsed


class BusinessRecommendationService:
    """Manual recommendation lifecycle, measurement, and immutable audit."""

    def __init__(
        self,
        database: Database,
        business_analysis: BusinessAnalysisService,
        *,
        product_intelligence: ProductIntelligenceService | None = None,
    ) -> None:
        self.database = database
        self.business_analysis = business_analysis
        self.product_intelligence = product_intelligence
        self.repository: BusinessAnalysisRepository = business_analysis.repository

    @staticmethod
    def _now(value: datetime | None = None) -> datetime:
        current = value or utcnow()
        return _as_utc(current) or utcnow()

    @staticmethod
    def _metric(
        key: str,
        label: str,
        value: int | float,
        unit: str,
        evidence_ref: str,
    ) -> BusinessRecommendationMetricValue:
        return BusinessRecommendationMetricValue(
            key=key,
            label=label,
            value=float(value),
            unit=unit,
            evidence_ref=evidence_ref,
        )

    def _metric_snapshot(
        self,
        overview: BusinessAnalysisOverview,
        *,
        domain: str,
        captured_at: datetime,
        snapshot_hash: str,
    ) -> BusinessRecommendationMetricSnapshot:
        metrics = overview.metrics
        values: list[BusinessRecommendationMetricValue]
        if domain == "products":
            values = [
                self._metric("products.exposure", "经营浏览", metrics.products.exposure.current, "count", "products.exposure.current"),
                self._metric("products.inquiries", "咨询", metrics.products.inquiries.current, "count", "products.inquiries.current"),
                self._metric("products.converted_projects", "转化项目", metrics.products.converted_projects.current, "count", "products.converted_projects.current"),
                self._metric("products.snapshot_coverage", "快照覆盖率", metrics.products.snapshot_coverage_percent, "percent", "products.snapshot_coverage_percent"),
            ]
            if metrics.products.inquiry_rate_percent is not None:
                values.append(
                    self._metric("products.inquiry_rate", "浏览咨询率", metrics.products.inquiry_rate_percent, "percent", "products.inquiry_rate_percent")
                )
        elif domain == "customers":
            values = [
                self._metric("customers.total", "经营客户", metrics.customers.total, "count", "ledger.customers"),
                self._metric("customers.active_30d", "近 30 天活跃", metrics.customers.active_last_30d, "count", "ledger.customers.lastContactAt"),
                self._metric("customers.stale_30d", "待关注客户", metrics.customers.stale_or_missing_contact_30d, "count", "ledger.customers.lastContactAt"),
                self._metric("customers.won", "已成交客户", metrics.customers.won_customers, "count", "ledger.customers.followUpStatus"),
            ]
        elif domain == "projects":
            values = [
                self._metric("projects.total", "项目总数", metrics.projects.total, "count", "ledger.projects"),
                self._metric("projects.active", "进行中项目", metrics.projects.active_projects, "count", "ledger.projects.status"),
                self._metric("projects.completed", "已完成项目", metrics.projects.completed_projects, "count", "ledger.projects.status"),
                self._metric("projects.overdue", "逾期项目", metrics.projects.overdue_projects, "count", "ledger.projects.status"),
                self._metric("projects.receivables", "待回款", metrics.projects.outstanding_receivables, "CNY", "ledger.projects.outstanding_receivables"),
            ]
        elif domain == "finance":
            values = [
                self._metric("finance.income.current", "本月确认收入", metrics.finance.income.current, "CNY", "ledger.finance.current_month_income"),
                self._metric("finance.expenses.current", "本月支出", metrics.finance.expenses.current, "CNY", "ledger.finance.current_month_expenses"),
                self._metric("finance.profit.current", "本月利润", metrics.finance.profit.current, "CNY", "ledger.finance.current_month_profit"),
                self._metric("finance.receivables", "待回款", metrics.projects.outstanding_receivables, "CNY", "ledger.projects.outstanding_receivables"),
            ]
        else:
            values = [
                self._metric("portfolio.profit", "本月利润", metrics.finance.profit.current, "CNY", "ledger.finance.current_month_profit"),
                self._metric("portfolio.active_projects", "进行中项目", metrics.projects.active_projects, "count", "ledger.projects.status"),
                self._metric("portfolio.stale_customers", "待关注客户", metrics.customers.stale_or_missing_contact_30d, "count", "ledger.customers.lastContactAt"),
                self._metric("portfolio.inquiries", "商品咨询", metrics.products.inquiries.current, "count", "products.inquiries.current"),
            ]
        return BusinessRecommendationMetricSnapshot(
            captured_at=captured_at,
            source_snapshot_hash=snapshot_hash,
            values=values,
        )

    def _product_experiment(self, experiment_id: str) -> ProductExperimentState:
        try:
            with self.database.session() as session:
                row = session.get(ProductModificationExperiment, experiment_id)
                if row is None:
                    raise BusinessRecommendationServiceError(
                        "recommendation_execution_reference_not_found",
                        "关联的商品实验不存在",
                        status_code=404,
                    )
                item = session.get(Item, row.item_id)
                if item is None:
                    raise BusinessRecommendationServiceError(
                        "recommendation_execution_reference_invalid",
                        "关联的商品实验缺少商品记录",
                    )
                return ProductExperimentState(
                    id=row.id,
                    item_external_id=item.external_id,
                    item_title=item.title,
                    baseline=_json_object(row.baseline_json),
                    result=_json_object(row.result_json),
                    started_at=_as_utc(row.started_at) or self._now(),
                    observation_until=_as_utc(row.observation_until) or self._now(),
                    status=row.status,
                    decision=row.decision,
                )
        except BusinessRecommendationServiceError:
            raise
        except SQLAlchemyError as exc:
            raise BusinessRecommendationServiceError(
                "recommendation_execution_reference_unavailable",
                "商品实验暂时无法读取",
                status_code=503,
            ) from exc

    @staticmethod
    def _experiment_hash(experiment: ProductExperimentState, phase: str) -> str:
        payload = experiment.baseline if phase == "baseline" else experiment.result
        encoded = json.dumps(
            {"experiment_id": experiment.id, "phase": phase, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _experiment_baseline(
        self,
        experiment: ProductExperimentState,
    ) -> BusinessRecommendationMetricSnapshot:
        keys = (
            ("browse_count", "经营浏览"),
            ("inquiry_count", "咨询"),
            ("want_count", "想要"),
            ("converted_project_count", "转化项目"),
        )
        return BusinessRecommendationMetricSnapshot(
            captured_at=experiment.started_at,
            source_snapshot_hash=self._experiment_hash(experiment, "baseline"),
            values=[
                self._metric(
                    f"product_experiment.{key}",
                    label,
                    float(experiment.baseline.get(key) or 0),
                    "count",
                    "product_modification_experiments.baseline",
                )
                for key, label in keys
            ],
        )

    def _experiment_result(
        self,
        experiment: ProductExperimentState,
        *,
        captured_at: datetime,
    ) -> BusinessRecommendationMetricSnapshot:
        pairs = (
            ("browse_count", "browse_delta", "经营浏览"),
            ("inquiry_count", "inquiry_delta", "咨询"),
            ("want_count", "want_delta", "想要"),
        )
        values = [
            self._metric(
                f"product_experiment.{baseline_key}",
                label,
                float(experiment.baseline.get(baseline_key) or 0)
                + float(experiment.result.get(delta_key) or 0),
                "count",
                "product_modification_experiments.result",
            )
            for baseline_key, delta_key, label in pairs
        ]
        return BusinessRecommendationMetricSnapshot(
            captured_at=captured_at,
            source_snapshot_hash=self._experiment_hash(experiment, "result"),
            values=values,
        )

    def _decorate(
        self,
        stored: StoredBusinessRecommendation,
        *,
        current_snapshot_hash: str,
        now: datetime,
    ) -> BusinessAnalysisRecommendation:
        recommendation = stored.result
        stale = (
            recommendation.status in {"pending", "ignored"}
            and stored.snapshot_hash != current_snapshot_hash
        )
        observe_until = _as_utc(recommendation.observe_until)
        linked_completed = False
        if (
            recommendation.status == "observing"
            and recommendation.execution_ref_type == "product_modification_experiment"
            and recommendation.execution_ref_id
        ):
            experiment = self._product_experiment(recommendation.execution_ref_id)
            observe_until = experiment.observation_until
            linked_completed = experiment.status == "completed"
        review_due = recommendation.status == "observing" and (
            linked_completed or (observe_until is not None and observe_until <= now)
        )
        lifecycle = "review_due" if review_due else recommendation.status
        return recommendation.model_copy(
            update={
                "observe_until": observe_until,
                "lifecycle_status": lifecycle,
                "stale": stale,
                "can_accept": recommendation.status in {"pending", "ignored"} and not stale,
                "can_ignore": recommendation.status in {"pending", "accepted"},
                "can_start": recommendation.status == "accepted",
                "can_complete": review_due,
            }
        )

    def _current(self, *, now: datetime) -> tuple[BusinessAnalysisOverview, str]:
        try:
            overview = self.business_analysis.overview(now=now)
        except SQLAlchemyError as exc:
            raise BusinessRecommendationServiceError(
                "recommendation_metrics_unavailable",
                "经营指标暂时无法读取",
                status_code=503,
            ) from exc
        return overview, self.business_analysis.snapshot_hash(overview)

    def decorate_overview(
        self,
        overview: BusinessAnalysisOverview,
        *,
        now: datetime | None = None,
    ) -> BusinessAnalysisOverview:
        if overview.analysis_id is None or overview.record_status != "completed":
            return overview.model_copy(
                update={
                    "recommendations": [
                        row.model_copy(
                            update={
                                "can_accept": False,
                                "can_ignore": False,
                                "can_start": False,
                                "can_complete": False,
                            }
                        )
                        for row in overview.recommendations
                    ]
                }
            )
        current_time = self._now(now)
        _, current_hash = self._current(now=current_time)
        items = [
            self._decorate(
                self.repository.get_recommendation(row.id),
                current_snapshot_hash=current_hash,
                now=current_time,
            )
            for row in overview.recommendations
        ]
        return overview.model_copy(
            update={
                "recommendations": items,
                "is_stale": any(row.stale for row in items)
                or overview.is_stale,
            }
        )

    def queue(
        self,
        *,
        now: datetime | None = None,
    ) -> BusinessAnalysisRecommendationQueueResponse:
        current_time = self._now(now)
        _, current_hash = self._current(now=current_time)
        items = [
            self._decorate(
                stored,
                current_snapshot_hash=current_hash,
                now=current_time,
            )
            for stored in self.repository.list_recommendations()
        ]
        rank = {
            "review_due": 0,
            "accepted": 1,
            "observing": 2,
            "pending": 3,
            "completed": 4,
            "ignored": 5,
        }
        items.sort(
            key=lambda row: (
                rank[row.lifecycle_status],
                -(_as_utc(row.analysis_snapshot_time) or current_time).timestamp(),
                row.id,
            )
        )
        counts = {
            "pending": 0,
            "accepted": 0,
            "observing": 0,
            "review_due": 0,
            "completed": 0,
            "ignored": 0,
        }
        for row in items:
            counts[row.lifecycle_status] += 1
        return BusinessAnalysisRecommendationQueueResponse(
            items=items,
            counts=BusinessAnalysisRecommendationQueueCounts(
                total=len(items),
                **counts,
            ),
            generated_at=current_time,
        )

    def _replay(
        self,
        recommendation_id: str,
        *,
        event_type: str,
        request_id: str,
        payload: dict[str, object],
        now: datetime,
    ) -> BusinessAnalysisRecommendation | None:
        replay = self.repository.replay_recommendation_event(
            recommendation_id,
            event_type=event_type,
            request_id=request_id,
            payload=payload,
        )
        if replay is None:
            return None
        _, current_hash = self._current(now=now)
        return self._decorate(
            replay,
            current_snapshot_hash=current_hash,
            now=now,
        )

    def update(
        self,
        recommendation_id: str,
        *,
        status: str,
        expected_version: int,
        request_id: str,
        note: str,
        now: datetime | None = None,
    ) -> BusinessAnalysisRecommendation:
        current_time = self._now(now)
        normalized_note = note.strip()
        event_type = {
            "accepted": "accepted",
            "ignored": "ignored",
            "pending": "restored",
        }[status]
        payload: dict[str, object] = {
            "status": status,
            "expected_version": expected_version,
            "note": normalized_note,
        }
        replay = self._replay(
            recommendation_id,
            event_type=event_type,
            request_id=request_id,
            payload=payload,
            now=current_time,
        )
        if replay is not None:
            return replay

        stored = self.repository.get_recommendation(recommendation_id)
        changes: dict[str, object]
        if status == "accepted":
            overview, current_hash = self._current(now=current_time)
            if stored.snapshot_hash != current_hash:
                raise BusinessRecommendationServiceError(
                    "recommendation_stale",
                    "经营事实已变化，请重新生成分析后再采纳该建议",
                )
            baseline = self._metric_snapshot(
                overview,
                domain=stored.result.domain,
                captured_at=current_time,
                snapshot_hash=current_hash,
            )
            changes = {
                "target_scope": stored.result.target_scope,
                "user_note": normalized_note,
                "accepted_at": current_time,
                "started_at": None,
                "observe_until": None,
                "completed_at": None,
                "baseline_metrics_json": baseline.model_dump_json(),
                "result_metrics_json": "{}",
                "outcome": None,
                "actual_cost": None,
                "actual_hours": None,
                "user_conclusion": "",
                "execution_ref_type": None,
                "execution_ref_id": None,
            }
            allowed_from = {"pending", "ignored"}
        elif status == "ignored":
            changes = {
                "user_note": normalized_note,
                "accepted_at": None,
                "started_at": None,
                "observe_until": None,
                "completed_at": None,
                "baseline_metrics_json": "{}",
                "result_metrics_json": "{}",
                "outcome": None,
                "actual_cost": None,
                "actual_hours": None,
                "user_conclusion": "",
                "execution_ref_type": None,
                "execution_ref_id": None,
            }
            allowed_from = {"pending", "accepted"}
        else:
            changes = {
                "user_note": normalized_note,
                "accepted_at": None,
                "started_at": None,
                "observe_until": None,
                "completed_at": None,
                "baseline_metrics_json": "{}",
                "result_metrics_json": "{}",
                "outcome": None,
                "actual_cost": None,
                "actual_hours": None,
                "user_conclusion": "",
                "execution_ref_type": None,
                "execution_ref_id": None,
            }
            allowed_from = {"ignored"}
        transitioned = self.repository.transition_recommendation(
            recommendation_id,
            event_type=event_type,
            to_status=status,
            allowed_from=allowed_from,
            expected_version=expected_version,
            request_id=request_id,
            payload=payload,
            changes=changes,
        )
        _, current_hash = self._current(now=current_time)
        return self._decorate(
            transitioned,
            current_snapshot_hash=current_hash,
            now=current_time,
        )

    def _observation_deadline(
        self,
        recommendation: BusinessAnalysisRecommendation,
        *,
        now: datetime,
    ) -> datetime:
        if recommendation.observe_days:
            return now + timedelta(days=recommendation.observe_days)
        if recommendation.observe_period == "current month":
            local = now.astimezone(self.business_analysis.zone)
            if local.month == 12:
                next_month = datetime(local.year + 1, 1, 1, tzinfo=self.business_analysis.zone)
            else:
                next_month = datetime(local.year, local.month + 1, 1, tzinfo=self.business_analysis.zone)
            return next_month.astimezone(timezone.utc)
        return now + timedelta(days=7)

    def start(
        self,
        recommendation_id: str,
        *,
        expected_version: int,
        request_id: str,
        execution_ref_type: str | None = None,
        execution_ref_id: str | None = None,
        now: datetime | None = None,
    ) -> BusinessAnalysisRecommendation:
        current_time = self._now(now)
        payload: dict[str, object] = {
            "expected_version": expected_version,
            "execution_ref_type": execution_ref_type,
            "execution_ref_id": execution_ref_id,
        }
        replay = self._replay(
            recommendation_id,
            event_type="started",
            request_id=request_id,
            payload=payload,
            now=current_time,
        )
        if replay is not None:
            return replay

        stored = self.repository.get_recommendation(recommendation_id)
        recommendation = stored.result
        if bool(execution_ref_type) != bool(execution_ref_id):
            raise BusinessRecommendationServiceError(
                "recommendation_execution_reference_invalid",
                "执行关联类型和编号必须同时提供",
            )
        experiment: ProductExperimentState | None = None
        if execution_ref_type or execution_ref_id:
            if execution_ref_type != "product_modification_experiment":
                raise BusinessRecommendationServiceError(
                    "recommendation_execution_reference_invalid",
                    "当前只支持关联商品单变量实验",
                )
            if recommendation.domain != "products":
                raise BusinessRecommendationServiceError(
                    "recommendation_execution_reference_invalid",
                    "只有商品建议可以关联商品实验",
                )
            experiment = self._product_experiment(str(execution_ref_id))
            if experiment.status != "observing":
                raise BusinessRecommendationServiceError(
                    "recommendation_execution_reference_invalid",
                    "只能关联正在观察的商品实验",
                )
            if recommendation.entity_id and recommendation.entity_id != experiment.item_external_id:
                raise BusinessRecommendationServiceError(
                    "recommendation_execution_reference_invalid",
                    "商品实验与建议目标不一致",
                )
        baseline = (
            self._experiment_baseline(experiment)
            if experiment
            else recommendation.baseline_metrics
        )
        if baseline is None:
            raise BusinessRecommendationServiceError(
                "recommendation_baseline_missing",
                "建议缺少采纳时冻结的基线，请重新采纳",
            )
        started_at = experiment.started_at if experiment else current_time
        observe_until = (
            experiment.observation_until
            if experiment
            else self._observation_deadline(recommendation, now=current_time)
        )
        transitioned = self.repository.transition_recommendation(
            recommendation_id,
            event_type="started",
            to_status="observing",
            allowed_from={"accepted"},
            expected_version=expected_version,
            request_id=request_id,
            payload=payload,
            changes={
                "started_at": started_at,
                "observe_until": observe_until,
                "baseline_metrics_json": baseline.model_dump_json(),
                "execution_ref_type": execution_ref_type,
                "execution_ref_id": execution_ref_id,
            },
        )
        _, current_hash = self._current(now=current_time)
        return self._decorate(
            transitioned,
            current_snapshot_hash=current_hash,
            now=current_time,
        )

    def complete(
        self,
        recommendation_id: str,
        *,
        expected_version: int,
        request_id: str,
        outcome: RecommendationOutcome,
        actual_cost: float | None,
        actual_hours: float | None,
        user_conclusion: str,
        now: datetime | None = None,
    ) -> BusinessAnalysisRecommendation:
        current_time = self._now(now)
        conclusion = user_conclusion.strip()
        payload: dict[str, object] = {
            "expected_version": expected_version,
            "outcome": outcome,
            "actual_cost": actual_cost,
            "actual_hours": actual_hours,
            "user_conclusion": conclusion,
        }
        replay = self._replay(
            recommendation_id,
            event_type="completed",
            request_id=request_id,
            payload=payload,
            now=current_time,
        )
        if replay is not None:
            return replay

        stored = self.repository.get_recommendation(recommendation_id)
        recommendation = stored.result
        if recommendation.status != "observing":
            # Keep the repository as the final transactional authority, but
            # return the more precise public error for this common path.
            raise BusinessRecommendationServiceError(
                "recommendation_transition_invalid",
                "只有观察中的建议可以提交结果复盘",
            )

        experiment: ProductExperimentState | None = None
        canonical_outcome = outcome
        if (
            recommendation.execution_ref_type == "product_modification_experiment"
            and recommendation.execution_ref_id
        ):
            experiment = self._product_experiment(recommendation.execution_ref_id)
        due_at = experiment.observation_until if experiment else _as_utc(recommendation.observe_until)
        linked_completed = experiment is not None and experiment.status == "completed"
        if not linked_completed and (due_at is None or current_time < due_at):
            raise BusinessRecommendationServiceError(
                "recommendation_observation_not_due",
                "观察期尚未结束，到期后才能提交结果复盘",
            )
        if experiment:
            if experiment.status != "completed":
                raise BusinessRecommendationServiceError(
                    "recommendation_experiment_not_completed",
                    "请先在商品经营中完成商品实验裁决",
                )
            canonical_outcome = {
                "keep": "positive",
                "rollback": "negative",
            }.get(experiment.decision, "inconclusive")
            if outcome != canonical_outcome:
                raise BusinessRecommendationServiceError(
                    "recommendation_outcome_conflict",
                    "复盘结论必须与已完成的商品实验裁决一致",
                )
            baseline = self._experiment_baseline(experiment)
            result = self._experiment_result(experiment, captured_at=current_time)
        else:
            overview, current_hash = self._current(now=current_time)
            baseline = recommendation.baseline_metrics
            if baseline is None:
                raise BusinessRecommendationServiceError(
                    "recommendation_baseline_missing",
                    "建议缺少执行前基线，不能生成结果对比",
                )
            result = self._metric_snapshot(
                overview,
                domain=recommendation.domain,
                captured_at=current_time,
                snapshot_hash=current_hash,
            )
        transitioned = self.repository.transition_recommendation(
            recommendation_id,
            event_type="completed",
            to_status="completed",
            allowed_from={"observing"},
            expected_version=expected_version,
            request_id=request_id,
            payload=payload,
            changes={
                "completed_at": current_time,
                "observe_until": due_at,
                "baseline_metrics_json": baseline.model_dump_json(),
                "result_metrics_json": result.model_dump_json(),
                "outcome": canonical_outcome,
                "actual_cost": actual_cost,
                "actual_hours": actual_hours,
                "user_conclusion": conclusion,
            },
        )
        _, current_hash = self._current(now=current_time)
        return self._decorate(
            transitioned,
            current_snapshot_hash=current_hash,
            now=current_time,
        )
