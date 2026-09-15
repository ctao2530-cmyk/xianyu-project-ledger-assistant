from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from ..ai.base import AIModelSelection, AIProvider, AIProviderError
from ..business_analysis_repository import (
    BusinessAnalysisRepository,
    RecommendationTransitionError,
    StoredBusinessAnalysis,
)
from ..business_analysis_schemas import (
    BusinessAnalysisAIError,
    BusinessAnalysisDataSource,
    BusinessAnalysisFutureField,
    BusinessAnalysisHistoryResponse,
    BusinessAnalysisInsight,
    BusinessAnalysisMetrics,
    BusinessAnalysisOverview,
    BusinessAnalysisPeriod,
    BusinessAnalysisRecommendation,
    CustomerAnalysisMetrics,
    FinanceAnalysisMetrics,
    PeriodMetric,
    ProductAnalysisMetrics,
    ProductSignalMetric,
    ProjectAnalysisMetrics,
)
from ..database import Database
from ..ledger import LedgerService
from ..models import BusinessProject, Conversation, LedgerState, ProductDailySnapshot, ProductMonitor
from ..prediction.schemas import PredictionResult
from ..prediction.service import PredictionService
from .business_analysis_reasoning import (
    BusinessAnalysisEvidenceError,
    BusinessAnalysisReasoningService,
)
from .ai_models import AIModelSettingsService
from .project_outcomes import ProjectOutcomeService


ANALYSIS_TIMEZONE = "Asia/Shanghai"
ACTIVE_PRODUCT_MARKERS = ("在售", "上架", "active", "selling", "onsale")


class BusinessAnalysisProviderSelectionError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_datetime(value: Any, zone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _month_bounds(now: datetime) -> tuple[datetime, datetime, datetime]:
    current_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if current_start.month == 1:
        previous_start = current_start.replace(year=current_start.year - 1, month=12)
    else:
        previous_start = current_start.replace(month=current_start.month - 1)
    if current_start.month == 12:
        next_start = current_start.replace(year=current_start.year + 1, month=1)
    else:
        next_start = current_start.replace(month=current_start.month + 1)
    return previous_start, current_start, next_start


def _in_period(value: Any, start: datetime, end: datetime, zone: ZoneInfo) -> bool:
    parsed = _parse_datetime(value, zone)
    return parsed is not None and start <= parsed < end


def _round_money(value: float) -> float:
    return round(value + 0.0, 2)


def _period_metric(current: float, previous: float) -> PeriodMetric:
    current = _round_money(current)
    previous = _round_money(previous)
    delta = _round_money(current - previous)
    if delta > 0.005:
        direction = "up"
    elif delta < -0.005:
        direction = "down"
    else:
        direction = "flat"
    change_percent = None
    if abs(previous) > 0.005:
        change_percent = round((delta / abs(previous)) * 100, 1)
    return PeriodMetric(
        current=current,
        previous=previous,
        delta=delta,
        change_percent=change_percent,
        direction=direction,
    )


class BusinessAnalysisService:
    """Cross-domain evidence, AI reasoning, and persisted feedback layer.

    Metric calculation stays deterministic. A user-triggered run may ask the
    explicitly selected provider to clarify and order evidence, but model output can
    never change business facts or execute a recommendation.
    """

    def __init__(
        self,
        database: Database,
        ledger: LedgerService,
        *,
        timezone_name: str = ANALYSIS_TIMEZONE,
        repository: BusinessAnalysisRepository | None = None,
        reasoning: BusinessAnalysisReasoningService | None = None,
        reasoning_providers: dict[str, AIProvider] | None = None,
        model_settings: AIModelSettingsService | None = None,
        provider_selections: dict[str, AIModelSelection] | None = None,
        provider_enabled: dict[str, bool] | None = None,
        reasoning_timeout_seconds: float = 20,
        predictions: PredictionService | None = None,
        outcomes: ProjectOutcomeService | None = None,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.timezone_name = timezone_name
        self.zone = ZoneInfo(timezone_name)
        self.repository = repository or BusinessAnalysisRepository(database)
        self.reasoning = reasoning
        self.reasoning_providers = dict(reasoning_providers or {})
        self.model_settings = model_settings
        self.provider_selections = dict(provider_selections or {})
        self.provider_enabled = dict(provider_enabled or {})
        self.reasoning_timeout_seconds = reasoning_timeout_seconds
        self.predictions = predictions
        self.outcomes = outcomes or ProjectOutcomeService()

    async def _resolve_reasoning(
        self,
        *,
        provider_name: str,
        model: str | None,
        reasoning_effort: str | None,
    ) -> BusinessAnalysisReasoningService | None:
        if not self.reasoning_providers:
            return self.reasoning

        provider = self.reasoning_providers.get(provider_name)
        if provider is None:
            raise BusinessAnalysisProviderSelectionError(
                "business_analysis_provider_unavailable",
                "所选分析服务当前不可用",
                status_code=409,
            )
        if not self.provider_enabled.get(provider_name, True):
            raise BusinessAnalysisProviderSelectionError(
                "business_analysis_provider_not_configured",
                "所选分析服务尚未配置",
                status_code=409,
            )

        requested_model = (model or "").strip() or None
        requested_effort = (reasoning_effort or "").strip() or None
        if provider_name == "codex_cli":
            if self.model_settings is None:
                raise BusinessAnalysisProviderSelectionError(
                    "business_analysis_model_catalog_unavailable",
                    "GPT 模型目录当前不可用",
                    status_code=503,
                )
            catalog = await self.model_settings.get(refresh=False)
            effective_model = requested_model or catalog.selection.model
            if effective_model is None:
                raise BusinessAnalysisProviderSelectionError(
                    "business_analysis_model_required",
                    "请先选择一个当前账号可用的 GPT 模型",
                )
            option = next(
                (row for row in catalog.models if row.model == effective_model),
                None,
            )
            if option is None:
                raise BusinessAnalysisProviderSelectionError(
                    "business_analysis_model_invalid",
                    "所选 GPT 模型不在当前账号的可用目录中",
                )
            effective_effort = (
                requested_effort
                or catalog.selection.reasoning_effort
                or option.default_reasoning_effort
            )
            if (
                effective_effort is not None
                and effective_effort not in option.supported_reasoning_efforts
            ):
                raise BusinessAnalysisProviderSelectionError(
                    "business_analysis_reasoning_effort_invalid",
                    "所选推理强度不受该 GPT 模型支持",
                )
            selection = AIModelSelection(
                model=effective_model,
                reasoning_effort=effective_effort,
            )
        else:
            configured = self.provider_selections.get(provider_name)
            configured_model = (
                configured.model
                if configured and configured.model
                else provider.model_selection.model
            )
            if configured_model is None:
                raise BusinessAnalysisProviderSelectionError(
                    "business_analysis_model_required",
                    "所选分析服务没有可用模型",
                    status_code=409,
                )
            if requested_model is not None and requested_model != configured_model:
                raise BusinessAnalysisProviderSelectionError(
                    "business_analysis_model_invalid",
                    "所选模型与当前 DeepSeek 配置不一致",
                )
            if requested_effort is not None:
                raise BusinessAnalysisProviderSelectionError(
                    "business_analysis_reasoning_effort_invalid",
                    "DeepSeek 当前不支持单独选择推理强度",
                )
            selection = AIModelSelection(model=configured_model)

        return BusinessAnalysisReasoningService(
            provider,
            model_selection=selection,
            timeout_seconds=self.reasoning_timeout_seconds,
        )

    def overview(self, *, now: datetime | None = None) -> BusinessAnalysisOverview:
        generated_at = now or datetime.now(timezone.utc)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        local_now = generated_at.astimezone(self.zone)
        previous_start, current_start, next_start = _month_bounds(local_now)

        revision, snapshot = self.ledger.get()
        products, product_source = self._product_metrics()
        conversation_stats = self._conversation_stats()
        customers = self._customer_metrics(snapshot, conversation_stats, local_now)
        finance = self._finance_metrics(
            snapshot,
            previous_start=previous_start,
            current_start=current_start,
            next_start=next_start,
        )
        projects = self._project_metrics(snapshot, finance)
        ledger_source = self._ledger_source(snapshot)

        metrics = BusinessAnalysisMetrics(
            products=products,
            customers=customers,
            projects=projects,
            finance=finance,
        )
        prediction_run = self.predictions.preview(now=generated_at) if self.predictions else None
        prediction_rows = prediction_run.results if prediction_run else []
        insights, recommendations, data_gaps = self._decision_layer(
            metrics,
            predictions=prediction_rows,
        )
        recommendations = self._explain_recommendations(
            recommendations,
            insights=insights,
        )
        recommendations.sort(
            key=lambda row: ({"high": 0, "medium": 1, "low": 2}[row.priority], row.id)
        )
        insights.sort(
            key=lambda row: (
                {"critical": 0, "warning": 1, "info": 2, "positive": 3}[row.severity],
                row.id,
            )
        )

        if data_gaps:
            summary = (
                f"当前经营状态：基线建设中。{len(data_gaps)} 类关键证据仍不完整，"
                "建议先补齐数据，再扩大投入或调整长期策略。"
            )
        elif any(row.priority == "high" for row in recommendations):
            summary = (
                "当前经营状态：存在优先处理项。经营数据已经形成跨域基线，"
                "但利润、交付或转化信号需要先处理。"
            )
        else:
            summary = (
                "当前经营状态：基础稳定。商品、客户、项目和财务数据已形成可解释基线，"
                "可以按建议进行人工验证并持续记录结果。"
            )

        return BusinessAnalysisOverview(
            summary=summary,
            metrics=metrics,
            insights=insights,
            recommendations=recommendations[:6],
            data_sources=[ledger_source, product_source, conversation_stats["source"]],
            future_fields=self._future_fields(),
            data_gaps=data_gaps,
            predictions=prediction_rows,
            prediction_run_id=prediction_run.id if prediction_run else None,
            prediction_snapshot_hash=(
                prediction_run.input_snapshot_hash if prediction_run else None
            ),
            ledger_revision=revision,
            period=BusinessAnalysisPeriod(
                timezone=self.timezone_name,
                current_month_start=current_start.date().isoformat(),
                current_month_end=(next_start.date() - timedelta(days=1)).isoformat(),
                previous_month_start=previous_start.date().isoformat(),
                previous_month_end=(current_start.date() - timedelta(days=1)).isoformat(),
            ),
            generated_at=generated_at.astimezone(timezone.utc),
            snapshot_time=generated_at.astimezone(timezone.utc),
        )

    @staticmethod
    def _evidence_source_labels(evidence_refs: list[str]) -> list[str]:
        labels: list[str] = []
        for reference in evidence_refs:
            if reference.startswith("products"):
                label = "商品经营快照"
            elif reference.startswith("conversations"):
                label = "客户沟通时间元数据"
            elif reference.startswith("prediction."):
                label = "本地预测引擎"
            elif reference.startswith("ledger.customers"):
                label = "客户关系账本"
            elif reference.startswith("ledger.projects"):
                label = "项目与应收账本"
            elif reference.startswith(("ledger.finance", "ledger.payments", "ledger.expenses")):
                label = "统一收支账本"
            elif reference.startswith("ledger"):
                label = "统一经营账本"
            else:
                label = "经营事实指标"
            if label not in labels:
                labels.append(label)
        return labels

    @staticmethod
    def _observe_period(domain: str) -> str:
        return {
            "products": "7 days",
            "customers": "30 days",
            "projects": "7 days",
            "finance": "current month",
            "portfolio": "30 days",
            "data": "7 days",
        }.get(domain, "7 days")

    def _explain_recommendations(
        self,
        recommendations: list[BusinessAnalysisRecommendation],
        *,
        insights: list[BusinessAnalysisInsight],
    ) -> list[BusinessAnalysisRecommendation]:
        explained: list[BusinessAnalysisRecommendation] = []
        for recommendation in recommendations:
            evidence = set(recommendation.evidence_refs)
            ranked = sorted(
                insights,
                key=lambda insight: (
                    len(evidence.intersection(insight.evidence_refs)),
                    insight.domain == recommendation.domain,
                    insight.severity in {"critical", "warning"},
                ),
                reverse=True,
            )
            matching = ranked[0] if ranked else None
            has_match = bool(
                matching
                and (
                    evidence.intersection(matching.evidence_refs)
                    or matching.domain == recommendation.domain
                )
            )
            problem = (
                matching.title
                if matching is not None and has_match
                else "需要继续验证当前经营信号"
            )
            confidence = (
                "low"
                if recommendation.domain == "data"
                or any(reference in {"products", "ledger", "conversations"} for reference in evidence)
                else "medium"
            )
            explained.append(
                recommendation.model_copy(
                    update={
                        "source_key": recommendation.id,
                        "problem": problem,
                        "data_source": self._evidence_source_labels(
                            recommendation.evidence_refs
                        ),
                        "confidence": confidence,
                        "observe_period": self._observe_period(recommendation.domain),
                        "status": "pending",
                        "version": 1,
                        "user_note": "",
                    }
                )
            )
        return explained

    @staticmethod
    def snapshot_hash(result: BusinessAnalysisOverview) -> str:
        payload = {
            "ledger_revision": result.ledger_revision,
            "period": result.period.model_dump(mode="json"),
            "metrics": result.metrics.model_dump(mode="json"),
            "data_sources": [row.model_dump(mode="json") for row in result.data_sources],
            "data_gaps": result.data_gaps,
            "prediction_snapshot_hash": result.prediction_snapshot_hash,
            "predictions": [
                {
                    "target": row.target,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "prediction_value": row.prediction_value,
                    "score": row.score,
                    "risk_level": row.risk_level,
                    "data_sufficiency": row.data_sufficiency,
                    "model_version": row.model_version,
                }
                for row in result.predictions
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def latest_or_overview(
        self, *, now: datetime | None = None
    ) -> BusinessAnalysisOverview:
        latest = self.repository.latest()
        if latest is None:
            return self.overview(now=now)
        current = self.overview(now=now)
        return latest.result.model_copy(
            update={"is_stale": latest.snapshot_hash != self.snapshot_hash(current)}
        )

    def history(self, *, limit: int, offset: int) -> BusinessAnalysisHistoryResponse:
        return self.repository.history(limit=limit, offset=offset)

    def history_detail(self, analysis_id: str) -> BusinessAnalysisOverview:
        return self.repository.get(analysis_id).result

    def update_recommendation(
        self,
        recommendation_id: str,
        *,
        status: str,
        expected_version: int,
        request_id: str,
        note: str,
    ) -> BusinessAnalysisRecommendation:
        # Compatibility entrypoint for callers that have not yet switched to
        # Runtime.business_recommendations. Completing a recommendation is no
        # longer accepted here because it requires an observed result/outcome.
        if status not in {"pending", "accepted", "ignored"}:
            raise RecommendationTransitionError
        from .business_recommendations import BusinessRecommendationService

        return BusinessRecommendationService(self.database, self).update(
            recommendation_id,
            status=status,
            expected_version=expected_version,
            request_id=request_id,
            note=note,
        )

    async def run_analysis(
        self,
        *,
        request_id: str,
        provider: str,
        model: str | None = None,
        reasoning_effort: str | None = None,
        now: datetime | None = None,
    ) -> BusinessAnalysisOverview:
        existing = self.repository.get_by_request_id(request_id)
        if existing is not None:
            if existing.result.provider != provider or (
                model is not None and existing.result.model != model
            ):
                raise BusinessAnalysisProviderSelectionError(
                    "business_analysis_request_conflict",
                    "该请求编号已用于不同的分析模型",
                    status_code=409,
                )
            return existing.result

        baseline = self.overview(now=now)
        if self.predictions is not None:
            prediction_run = self.predictions.run(
                request_id=f"prediction:{request_id}",
                now=now,
            )
            baseline = baseline.model_copy(
                update={
                    "predictions": prediction_run.results,
                    "prediction_run_id": prediction_run.id,
                    "prediction_snapshot_hash": prediction_run.input_snapshot_hash,
                }
            )
        snapshot_hash = self.snapshot_hash(baseline)
        result = baseline
        reasoning = await self._resolve_reasoning(
            provider_name=provider,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        if reasoning is None:
            result = baseline.model_copy(
                update={
                    "provider": provider,
                    "ai_status": "failed",
                    "fallback_used": True,
                    "ai_error": BusinessAnalysisAIError(
                        code="business_analysis_ai_unavailable",
                        message="AI经营分析服务尚未连接，已保留规则分析结果",
                    ),
                }
            )
        elif provider != reasoning.provider_name:
            result = baseline.model_copy(
                update={
                    "provider": provider,
                    "model": reasoning.model_name,
                    "ai_status": "failed",
                    "fallback_used": True,
                    "ai_error": BusinessAnalysisAIError(
                        code="business_analysis_provider_mismatch",
                        message="请求的分析模型与当前配置不一致，已保留规则分析结果",
                    ),
                }
            )
        else:
            try:
                result = await reasoning.enhance(
                    baseline,
                    task_key=f"business-analysis:{request_id}",
                )
            except AIProviderError as exc:
                result = baseline.model_copy(
                    update={
                        "provider": reasoning.provider_name,
                        "model": reasoning.model_name,
                        "ai_status": "failed",
                        "fallback_used": True,
                        "ai_error": BusinessAnalysisAIError(
                            code=exc.code,
                            message=exc.safe_message,
                            retryable=exc.retryable,
                        ),
                    }
                )
            except BusinessAnalysisEvidenceError:
                result = baseline.model_copy(
                    update={
                        "provider": reasoning.provider_name,
                        "model": reasoning.model_name,
                        "ai_status": "failed",
                        "fallback_used": True,
                        "ai_error": BusinessAnalysisAIError(
                            code="business_analysis_ai_evidence_rejected",
                            message="AI返回内容缺少有效数据依据，已保留规则分析结果",
                            retryable=True,
                        ),
                    }
                )
        result = result.model_copy(update={"snapshot_time": baseline.generated_at})
        stored: StoredBusinessAnalysis = self.repository.save_completed(
            request_id=request_id,
            snapshot_hash=snapshot_hash,
            result=result,
        )
        return stored.result

    def _product_metrics(
        self,
    ) -> tuple[ProductAnalysisMetrics, BusinessAnalysisDataSource]:
        with self.database.session() as session:
            monitors = list(
                session.scalars(
                    select(ProductMonitor)
                    .where(ProductMonitor.ownership_status == "owned")
                    .order_by(ProductMonitor.id)
                ).all()
            )
            item_ids = [monitor.item_id for monitor in monitors]
            snapshots = (
                list(
                    session.scalars(
                        select(ProductDailySnapshot)
                        .where(ProductDailySnapshot.item_id.in_(item_ids))
                        .order_by(
                            ProductDailySnapshot.item_id,
                            ProductDailySnapshot.snapshot_date,
                            ProductDailySnapshot.id,
                        )
                    ).all()
                )
                if item_ids
                else []
            )

        histories: dict[int, list[ProductDailySnapshot]] = defaultdict(list)
        for snapshot in snapshots:
            histories[snapshot.item_id].append(snapshot)

        status_counts: Counter[str] = Counter()
        current_browse = 0
        current_inquiries = 0
        current_conversions = 0
        platform_sold = 0
        browse_delta = 0
        inquiry_delta = 0
        conversion_delta = 0
        comparable_products = 0
        published_values: list[tuple[datetime, str]] = []

        for monitor in monitors:
            history = histories.get(monitor.item_id, [])
            if not history:
                status_counts["等待快照"] += 1
                continue
            current = history[-1]
            status = current.status.strip() or "未知"
            status_counts[status] += 1
            current_browse += max(0, current.browse_count)
            current_inquiries += max(0, current.inquiry_count)
            current_conversions += max(0, current.converted_project_count)
            platform_sold += max(0, current.sold_count)
            published_at = _parse_datetime(current.published_at, self.zone)
            if published_at is not None:
                published_values.append((published_at, current.published_at))

            current_date = _parse_date(current.snapshot_date)
            if current_date is None:
                continue
            threshold = current_date - timedelta(days=7)
            baseline = next(
                (
                    row
                    for row in reversed(history[:-1])
                    if (_parse_date(row.snapshot_date) or current_date) <= threshold
                ),
                None,
            )
            if baseline is None:
                continue
            comparable_products += 1
            browse_delta += max(0, current.browse_count - baseline.browse_count)
            inquiry_delta += max(0, current.inquiry_count - baseline.inquiry_count)
            conversion_delta += max(
                0,
                current.converted_project_count - baseline.converted_project_count,
            )

        latest_snapshots = sum(1 for monitor in monitors if histories.get(monitor.item_id))
        coverage = round((latest_snapshots / len(monitors)) * 100, 1) if monitors else 0.0
        active_products = sum(
            count
            for status, count in status_counts.items()
            if any(marker in status.casefold() for marker in ACTIVE_PRODUCT_MARKERS)
        )
        captured_values = [
            parsed
            for row in snapshots
            if (parsed := _parse_datetime(row.captured_at, self.zone)) is not None
        ]
        latest_captured = max(captured_values, default=None)
        latest_published = max(published_values, default=None, key=lambda row: row[0])
        inquiry_rate = (
            round((current_inquiries / current_browse) * 100, 2)
            if current_browse > 0
            else None
        )

        metrics = ProductAnalysisMetrics(
            owned_products=len(monitors),
            monitored_products=sum(1 for monitor in monitors if monitor.enabled),
            active_products=active_products,
            status_counts=dict(status_counts),
            latest_published_at=latest_published[1] if latest_published else None,
            snapshot_days=len({row.snapshot_date for row in snapshots}),
            snapshot_coverage_percent=coverage,
            exposure=ProductSignalMetric(
                current=current_browse,
                delta_7d=browse_delta if comparable_products else None,
                comparison_products=comparable_products,
                available=bool(latest_snapshots),
                unit="经营浏览",
            ),
            inquiries=ProductSignalMetric(
                current=current_inquiries,
                delta_7d=inquiry_delta if comparable_products else None,
                comparison_products=comparable_products,
                available=bool(latest_snapshots),
                unit="咨询",
            ),
            converted_projects=ProductSignalMetric(
                current=current_conversions,
                delta_7d=conversion_delta if comparable_products else None,
                comparison_products=comparable_products,
                available=bool(latest_snapshots),
                unit="转化项目",
            ),
            platform_sold_count=platform_sold,
            inquiry_rate_percent=inquiry_rate,
        )
        source = BusinessAnalysisDataSource(
            id="products",
            label="本人商品经营快照",
            source_type="sqlite",
            tables=["product_monitors", "product_daily_snapshots"],
            fields=[
                "ownership_status",
                "enabled",
                "status",
                "published_at",
                "browse_count",
                "inquiry_count",
                "sold_count",
                "converted_project_count",
            ],
            available=bool(monitors),
            record_count=len(snapshots),
            latest_at=latest_captured.isoformat() if latest_captured else None,
            note="只统计 ownership_status=owned 的商品；经营浏览已排除保守采集自访问。",
        )
        return metrics, source

    def _conversation_stats(self) -> dict[str, Any]:
        with self.database.session() as session:
            record_count = int(session.scalar(select(func.count(Conversation.id))) or 0)
            customer_count = int(
                session.scalar(select(func.count(func.distinct(Conversation.customer_id)))) or 0
            )
            latest = session.scalar(select(func.max(Conversation.last_message_at)))
        latest_at = _parse_datetime(latest, self.zone)
        return {
            "record_count": record_count,
            "customer_count": customer_count,
            "latest_at": latest_at,
            "source": BusinessAnalysisDataSource(
                id="conversations",
                label="客户沟通时间元数据",
                source_type="sqlite",
                tables=["conversations"],
                fields=["customer_id", "last_message_at", "channel"],
                available=record_count > 0,
                record_count=record_count,
                latest_at=latest_at.isoformat() if latest_at else None,
                note="仅聚合沟通时间和去重数量，不读取或返回客户消息正文。",
            ),
        }

    def _customer_metrics(
        self,
        snapshot: dict[str, Any],
        conversation_stats: dict[str, Any],
        now: datetime,
    ) -> CustomerAnalysisMetrics:
        customers = snapshot.get("customers", [])
        statuses = Counter(str(row.get("followUpStatus") or "unknown") for row in customers)
        threshold = now - timedelta(days=30)
        contact_dates = [
            parsed
            for row in customers
            if (parsed := _parse_datetime(row.get("lastContactAt"), self.zone)) is not None
        ]
        active = sum(1 for parsed in contact_dates if parsed >= threshold)
        stale = len(customers) - active
        latest_contact = max(contact_dates, default=None)
        latest_message = conversation_stats["latest_at"]
        latest_overall = max(
            [row for row in (latest_contact, latest_message) if row is not None],
            default=None,
        )
        return CustomerAnalysisMetrics(
            total=len(customers),
            follow_up_status_counts=dict(statuses),
            won_customers=statuses.get("won", 0),
            active_last_30d=active,
            stale_or_missing_contact_30d=stale,
            latest_contact_at=latest_overall.isoformat() if latest_overall else None,
            conversation_customers=conversation_stats["customer_count"],
            latest_message_at=latest_message.isoformat() if latest_message else None,
        )

    def _finance_metrics(
        self,
        snapshot: dict[str, Any],
        *,
        previous_start: datetime,
        current_start: datetime,
        next_start: datetime,
    ) -> FinanceAnalysisMetrics:
        payments = snapshot.get("payments", [])
        issues = snapshot.get("settlementIssues", [])
        expenses = snapshot.get("expenses", [])

        def net_income(start: datetime | None = None, end: datetime | None = None) -> float:
            def matches(value: Any) -> bool:
                if start is None or end is None:
                    return True
                return _in_period(value, start, end, self.zone)

            gross = sum(
                _number(row.get("amount"))
                for row in payments
                if row.get("status") in {"confirmed", "refunded"}
                and matches(row.get("paidAt"))
            )
            legacy_refunds = sum(
                _number(row.get("amount"))
                for row in payments
                if row.get("status") == "refunded" and matches(row.get("paidAt"))
            )
            issue_refunds = sum(
                _number(row.get("refundAmount"))
                for row in issues
                if matches(row.get("occurredAt"))
            )
            return gross - legacy_refunds - issue_refunds

        def expense_total(start: datetime | None = None, end: datetime | None = None) -> float:
            return sum(
                _number(row.get("amount"))
                for row in expenses
                if start is None
                or end is None
                or _in_period(row.get("paidAt"), start, end, self.zone)
            )

        current_income = net_income(current_start, next_start)
        previous_income = net_income(previous_start, current_start)
        current_expenses = expense_total(current_start, next_start)
        previous_expenses = expense_total(previous_start, current_start)
        all_time_income = net_income()
        all_time_expenses = expense_total()
        return FinanceAnalysisMetrics(
            income=_period_metric(current_income, previous_income),
            expenses=_period_metric(current_expenses, previous_expenses),
            profit=_period_metric(
                current_income - current_expenses,
                previous_income - previous_expenses,
            ),
            all_time_income=_round_money(all_time_income),
            all_time_expenses=_round_money(all_time_expenses),
            all_time_profit=_round_money(all_time_income - all_time_expenses),
            confirmed_payment_count=sum(
                1 for row in payments if row.get("status") in {"confirmed", "refunded"}
            ),
            expense_count=len(expenses),
        )

    def _project_metrics(
        self,
        snapshot: dict[str, Any],
        finance: FinanceAnalysisMetrics,
    ) -> ProjectAnalysisMetrics:
        projects = snapshot.get("projects", [])
        payments = snapshot.get("payments", [])
        issues = snapshot.get("settlementIssues", [])
        statuses = Counter(str(row.get("status") or "unknown") for row in projects)
        outstanding = 0.0
        for project in projects:
            project_id = project.get("id")
            gross = sum(
                _number(row.get("amount"))
                for row in payments
                if row.get("projectId") == project_id
                and row.get("status") in {"confirmed", "refunded"}
            )
            uncollectible = sum(
                _number(row.get("receivableImpact"))
                for row in issues
                if row.get("projectId") == project_id
            )
            outstanding += max(0.0, _number(project.get("totalAmount")) - gross - uncollectible)
        outcome_rows = []
        with self.database.session() as session:
            relational_projects = {
                row.id: row for row in session.scalars(select(BusinessProject))
            }
            for project in projects:
                project_id = str(project.get("id") or "")
                relational = relational_projects.get(project_id)
                if not relational:
                    continue
                outcome_rows.append(
                    self.outcomes.build(
                        session,
                        project_id,
                        verified_progress=max(0, min(100, int(relational.progress or 0))),
                    )
                )
        return ProjectAnalysisMetrics(
            total=len(projects),
            status_counts=dict(statuses),
            active_projects=statuses.get("in_progress", 0) + statuses.get("overdue", 0),
            completed_projects=statuses.get("delivered", 0) + statuses.get("completed", 0),
            overdue_projects=statuses.get("overdue", 0),
            contract_total=_round_money(
                sum(_number(project.get("totalAmount")) for project in projects)
            ),
            confirmed_income=finance.all_time_income,
            outstanding_receivables=_round_money(outstanding),
            verified_progress_average=(
                round(sum(row.verified_progress for row in outcome_rows) / len(outcome_rows), 2)
                if outcome_rows else 0
            ),
            actual_hours=round(sum(row.actual_hours for row in outcome_rows), 4),
            rework_hours=round(sum(row.rework_hours for row in outcome_rows), 4),
            blocker_count=sum(row.blocker_count for row in outcome_rows),
            test_failure_count=sum(row.test_failure_count for row in outcome_rows),
            outcome_sample_count=len(outcome_rows),
        )

    def _ledger_source(self, snapshot: dict[str, Any]) -> BusinessAnalysisDataSource:
        with self.database.session() as session:
            state = session.get(LedgerState, 1)
            latest = _parse_datetime(state.updated_at, self.zone) if state else None
        collections = ("projects", "payments", "settlementIssues", "expenses", "customers")
        return BusinessAnalysisDataSource(
            id="ledger",
            label="统一经营账本",
            source_type="ledger",
            tables=[
                "ledger_state",
                "business_customers",
                "business_projects",
                "payment_nodes",
                "project_settlement_issues",
                "business_expenses",
            ],
            fields=[
                "followUpStatus",
                "lastContactAt",
                "project.status",
                "project.totalAmount",
                "payment.status",
                "payment.paidAt",
                "expense.amount",
                "expense.paidAt",
            ],
            available=state is not None,
            record_count=sum(len(snapshot.get(name, [])) for name in collections),
            latest_at=latest.isoformat() if latest else None,
            note="收入使用确认到账净额；利润为净到账减支出，退款和无法收回金额按统一账本口径处理。",
        )

    def _decision_layer(
        self,
        metrics: BusinessAnalysisMetrics,
        *,
        predictions: list[PredictionResult] | None = None,
    ) -> tuple[
        list[BusinessAnalysisInsight],
        list[BusinessAnalysisRecommendation],
        list[str],
    ]:
        insights: list[BusinessAnalysisInsight] = []
        recommendations: list[BusinessAnalysisRecommendation] = []
        data_gaps: list[str] = []
        products = metrics.products
        customers = metrics.customers
        projects = metrics.projects
        finance = metrics.finance
        prediction_rows = predictions or []

        if products.owned_products == 0:
            data_gaps.append("缺少已验证属于当前卖家的商品")
            insights.append(
                BusinessAnalysisInsight(
                    id="product-baseline-missing",
                    domain="data",
                    severity="warning",
                    title="商品经营基线尚未建立",
                    reason="数据库没有可纳入经营指标的已验证本人商品，不能据此判断曝光、咨询或成交表现。",
                    evidence_refs=["products.ownership_status"],
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="verify-owned-products",
                    domain="products",
                    priority="high",
                    title="先确认本人商品范围",
                    action="在商品经营中完成本人商品确认并进行一次只读采集。",
                    reason="未验证归属的商品不能进入经营指标和建议，先补齐来源比直接优化更可靠。",
                    target_page="商品经营",
                    evidence_refs=["products.ownership_status", "products.snapshot_coverage_percent"],
                )
            )
        elif products.snapshot_coverage_percent < 100:
            data_gaps.append("部分已验证商品缺少经营快照")
            insights.append(
                BusinessAnalysisInsight(
                    id="product-snapshot-gap",
                    domain="data",
                    severity="warning",
                    title="部分商品缺少可比较快照",
                    reason=f"当前商品快照覆盖率为 {products.snapshot_coverage_percent:.1f}%，缺失商品不会被推断为零表现。",
                    evidence_refs=["products.snapshot_coverage_percent"],
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="refresh-product-snapshots",
                    domain="products",
                    priority="high",
                    title="补齐商品快照",
                    action="对缺少快照的本人商品执行一次人工只读刷新。",
                    reason="只有覆盖完整后，商品之间的曝光与咨询比较才具有一致口径。",
                    target_page="商品经营",
                    evidence_refs=["products.snapshot_coverage_percent"],
                )
            )
        else:
            if products.exposure.current >= 50 and products.inquiries.current == 0:
                insights.append(
                    BusinessAnalysisInsight(
                        id="exposure-without-inquiry",
                        domain="products",
                        severity="warning",
                        title="已有曝光但尚未形成咨询",
                        reason=f"已记录 {products.exposure.current} 次经营浏览，但咨询仍为 0；当前瓶颈更接近商品表达或匹配度，而不是曝光不足。",
                        evidence_refs=["products.exposure.current", "products.inquiries.current"],
                    )
                )
                recommendations.append(
                    BusinessAnalysisRecommendation(
                        id="improve-listing-conversion",
                        domain="products",
                        priority="high",
                        title="先验证商品转化表达",
                        action="选择一个变量检查标题、封面或交付边界，并记录修改前后的咨询变化。",
                        reason="当前证据不支持继续扩大曝光投入，应先验证浏览到咨询的转化环节。",
                        target_page="商品经营",
                        evidence_refs=["products.exposure.current", "products.inquiries.current"],
                    )
                )
            elif (
                products.inquiry_rate_percent is not None
                and products.exposure.current >= 100
                and products.inquiry_rate_percent < 1
            ):
                insights.append(
                    BusinessAnalysisInsight(
                        id="low-inquiry-rate",
                        domain="products",
                        severity="warning",
                        title="浏览到咨询转化偏弱",
                        reason=f"当前经营浏览到咨询比例约为 {products.inquiry_rate_percent:.2f}%，需要先定位商品表达和目标客户匹配问题。",
                        evidence_refs=["products.inquiry_rate_percent"],
                    )
                )
                recommendations.append(
                    BusinessAnalysisRecommendation(
                        id="test-product-message",
                        domain="products",
                        priority="medium",
                        title="做一次单变量商品实验",
                        action="只调整一个商品变量并观察至少 7 天，避免同时改动导致无法归因。",
                        reason="单变量记录可以把优化建议转化为可复验的数据资产。",
                        target_page="商品经营",
                        evidence_refs=["products.inquiry_rate_percent", "products.snapshot_days"],
                    )
                )
            if products.inquiries.current > 0 and products.converted_projects.current == 0:
                insights.append(
                    BusinessAnalysisInsight(
                        id="inquiry-without-project",
                        domain="products",
                        severity="warning",
                        title="咨询尚未转化为项目",
                        reason=f"已有 {products.inquiries.current} 次咨询记录，但关联转化项目仍为 0。",
                        evidence_refs=["products.inquiries.current", "products.converted_projects.current"],
                    )
                )
                recommendations.append(
                    BusinessAnalysisRecommendation(
                        id="review-consultation-conversion",
                        domain="customers",
                        priority="medium",
                        title="复核咨询到项目的断点",
                        action="检查近期咨询是否完成需求澄清、报价和项目关联。",
                        reason="已有需求信号但没有项目转化，优先检查销售流程比增加曝光更直接。",
                        target_page="客户消息",
                        evidence_refs=["products.inquiries.current", "products.converted_projects.current"],
                    )
                )

        if customers.total == 0:
            data_gaps.append("客户关系账本为空")
            reason = (
                f"目前有 {customers.conversation_customers} 个沟通身份，但尚未形成已确认客户记录。"
                if customers.conversation_customers
                else "当前没有已确认客户或沟通身份可用于客户经营分析。"
            )
            insights.append(
                BusinessAnalysisInsight(
                    id="customer-baseline-missing",
                    domain="data",
                    severity="warning",
                    title="客户经营基线尚未建立",
                    reason=reason,
                    evidence_refs=["ledger.customers", "conversations.customer_id"],
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="confirm-customer-records",
                    domain="customers",
                    priority="medium",
                    title="建立已确认客户记录",
                    action="从真实咨询中人工确认需要持续跟进的客户关系。",
                    reason="会话身份不能自动等同于经营客户，必须保留人工确认边界。",
                    target_page="客户消息",
                    evidence_refs=["ledger.customers", "conversations.customer_id"],
                )
            )
        elif customers.stale_or_missing_contact_30d > 0:
            insights.append(
                BusinessAnalysisInsight(
                    id="stale-customer-followup",
                    domain="customers",
                    severity="warning",
                    title="存在长期未更新的客户关系",
                    reason=f"{customers.stale_or_missing_contact_30d} 个客户超过 30 天未联系或缺少联系时间。",
                    evidence_refs=["ledger.customers.lastContactAt"],
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="review-stale-customers",
                    domain="customers",
                    priority="medium",
                    title="人工复核待跟进客户",
                    action="逐个判断继续跟进、暂缓或结束，不自动发送消息。",
                    reason="客户状态长期不更新会放大漏跟进和虚假机会数量。",
                    target_page="客户管理",
                    evidence_refs=["ledger.customers.lastContactAt", "ledger.customers.followUpStatus"],
                )
            )

        if projects.total == 0:
            data_gaps.append("项目账本为空")
            insights.append(
                BusinessAnalysisInsight(
                    id="project-baseline-missing",
                    domain="data",
                    severity="warning",
                    title="项目交付基线尚未建立",
                    reason="当前没有项目状态、合同或交付样本，无法判断项目结构和收入质量。",
                    evidence_refs=["ledger.projects"],
                )
            )
        elif projects.overdue_projects > 0:
            insights.append(
                BusinessAnalysisInsight(
                    id="overdue-projects",
                    domain="projects",
                    severity="critical",
                    title="存在逾期项目",
                    reason=f"当前有 {projects.overdue_projects} 个逾期项目，交付风险应优先于新增投入。",
                    evidence_refs=["ledger.projects.status"],
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="stabilize-overdue-projects",
                    domain="projects",
                    priority="high",
                    title="先收口逾期交付",
                    action="核对逾期项目的剩余任务、交付边界和下一次可验证节点。",
                    reason="逾期会同时影响客户信任、回款和后续接单容量。",
                    target_page="项目管理",
                    evidence_refs=["ledger.projects.status"],
                )
            )

        if finance.confirmed_payment_count == 0 and finance.expense_count == 0:
            data_gaps.append("缺少确认收支记录")
            insights.append(
                BusinessAnalysisInsight(
                    id="finance-baseline-missing",
                    domain="data",
                    severity="warning",
                    title="财务经营基线尚未建立",
                    reason="没有确认到账或支出记录，利润与趋势只能标记为未知，不能按零利润处理。",
                    evidence_refs=["ledger.payments", "ledger.expenses"],
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="record-cashflow-baseline",
                    domain="finance",
                    priority="high",
                    title="补齐真实收支记录",
                    action="记录已确认到账和真实支出，再重新查看经营分析。",
                    reason="利润建议只有建立在真实现金流上才可执行。",
                    target_page="收入记录",
                    evidence_refs=["ledger.payments", "ledger.expenses"],
                )
            )
        elif finance.profit.current < 0:
            insights.append(
                BusinessAnalysisInsight(
                    id="negative-month-profit",
                    domain="finance",
                    severity="critical",
                    title="本月利润为负",
                    reason=f"本月净到账 ¥{finance.income.current:.2f}，支出 ¥{finance.expenses.current:.2f}，利润 ¥{finance.profit.current:.2f}。",
                    evidence_refs=["ledger.finance.current_month_income", "ledger.finance.current_month_expenses"],
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="repair-month-profit",
                    domain="finance",
                    priority="high",
                    title="先修复本月利润结构",
                    action="按项目核对确认到账、关联支出和工时，定位亏损来源。",
                    reason="在亏损原因未明确前扩大投入可能放大损失。",
                    target_page="数据统计",
                    evidence_refs=["ledger.finance.current_month_profit"],
                )
            )
        elif finance.income.change_percent is not None and finance.income.change_percent <= -20:
            insights.append(
                BusinessAnalysisInsight(
                    id="income-decline",
                    domain="finance",
                    severity="warning",
                    title="本月净到账较上月下降",
                    reason=f"本月净到账较上月变化 {finance.income.change_percent:.1f}%。",
                    evidence_refs=["ledger.finance.current_month_income", "ledger.finance.previous_month_income"],
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="trace-income-decline",
                    domain="finance",
                    priority="medium",
                    title="拆解收入下降来源",
                    action="分别检查近期咨询、在途项目和待确认到账，不把合同额当成已收入。",
                    reason="先定位是获客、交付还是回款变化，再选择对应动作。",
                    target_page="数据统计",
                    evidence_refs=["ledger.finance.current_month_income", "ledger.projects.status"],
                )
            )
        else:
            insights.append(
                BusinessAnalysisInsight(
                    id="finance-baseline-readable",
                    domain="finance",
                    severity="positive",
                    title="财务口径已经可以追踪",
                    reason=f"累计净到账 ¥{finance.all_time_income:.2f}、累计支出 ¥{finance.all_time_expenses:.2f}、累计利润 ¥{finance.all_time_profit:.2f}。",
                    evidence_refs=["ledger.finance.all_time_income", "ledger.finance.all_time_expenses"],
                )
            )

        if projects.outstanding_receivables > 0:
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="review-receivables",
                    domain="finance",
                    priority="medium",
                    title="复核仍可收余额",
                    action="按项目确认待收节点、已核销金额和真实回款状态。",
                    reason=f"当前仍可收余额为 ¥{projects.outstanding_receivables:.2f}，需要保持合同额与确认到账口径一致。",
                    target_page="收入记录",
                    evidence_refs=["ledger.projects.outstanding_receivables"],
                )
            )

        workload = next(
            (row for row in prediction_rows if row.target == "workload_14d"),
            None,
        )
        if workload is not None and workload.risk_level in {"high", "overloaded"}:
            workload_value = workload.prediction_value or 0
            workload_ref = "prediction.workload_14d.prediction_value"
            workload_evidence = [workload_ref, *workload.evidence_refs]
            insights.append(
                BusinessAnalysisInsight(
                    id="predicted-workload-pressure",
                    domain="projects",
                    severity="critical" if workload.risk_level == "overloaded" else "warning",
                    title="未来 14 天工作负载偏高",
                    reason=(
                        f"本地规则预计未来 14 天负载率为 {workload_value:.1f}%，"
                        f"当前等级为 {workload.risk_level}；这是容量预测，不是项目延期概率。"
                    ),
                    evidence_refs=workload_evidence,
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="review-future-workload",
                    domain="projects",
                    priority="high",
                    title="人工校准未来两周排期",
                    action="核对剩余工时、每日可用工时和交付顺序，人工调整排期或范围。",
                    reason="容量规则显示未来两周接近或超过可用工时，应先验证排期再承诺新增交付。",
                    target_page="项目管理",
                    execution_mode="manual",
                    evidence_refs=workload_evidence,
                )
            )

        project_risks = [
            row
            for row in prediction_rows
            if row.target == "project_delay_risk"
            and row.risk_level == "high"
            and row.entity_id
        ]
        if project_risks:
            highest_project = max(
                project_risks,
                key=lambda row: (row.score or 0, row.entity_id or ""),
            )
            project_ref = f"prediction.project_delay_risk.{highest_project.entity_id}.score"
            project_evidence = [project_ref, *highest_project.evidence_refs]
            insights.append(
                BusinessAnalysisInsight(
                    id=f"predicted-project-delay-{highest_project.entity_id}",
                    domain="projects",
                    severity="critical",
                    title="存在高延期风险分项目",
                    reason=(
                        f"{highest_project.entity_label or '当前项目'}的延期风险分为 "
                        f"{highest_project.score or 0:.0f}/100；该分数来自透明规则，不是延期概率。"
                    ),
                    evidence_refs=project_evidence,
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id=f"review-project-delay-{highest_project.entity_id}",
                    domain="projects",
                    entity_type="project",
                    entity_id=highest_project.entity_id,
                    entity_label=highest_project.entity_label,
                    target_scope="entity",
                    priority="high",
                    title="人工复核高风险项目",
                    action="核对剩余任务、可用工时、交付边界和待确认事项，再决定是否调整计划。",
                    reason="延期风险分已进入高风险区间，需要人工确认真实阻塞和可执行的收口节点。",
                    target_page="项目管理",
                    execution_mode="manual",
                    evidence_refs=project_evidence,
                )
            )

        urgent_customers = [
            row
            for row in prediction_rows
            if row.target == "customer_followup_priority"
            and row.risk_level == "urgent"
            and row.entity_id
        ]
        if urgent_customers:
            highest_customer = max(
                urgent_customers,
                key=lambda row: (row.score or 0, row.entity_id or ""),
            )
            customer_ref = (
                f"prediction.customer_followup_priority.{highest_customer.entity_id}.score"
            )
            customer_evidence = [customer_ref, *highest_customer.evidence_refs]
            insights.append(
                BusinessAnalysisInsight(
                    id=f"predicted-customer-priority-{highest_customer.entity_id}",
                    domain="customers",
                    severity="warning",
                    title="存在今日优先跟进客户",
                    reason=(
                        f"{highest_customer.entity_label or '当前客户'}的跟进优先级为 "
                        f"{highest_customer.score or 0:.0f}/100；这是处理顺序，不是成交概率。"
                    ),
                    evidence_refs=customer_evidence,
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id=f"review-customer-priority-{highest_customer.entity_id}",
                    domain="customers",
                    entity_type="customer",
                    entity_id=highest_customer.entity_id,
                    entity_label=highest_customer.entity_label,
                    target_scope="entity",
                    priority="high",
                    title="人工处理今日优先客户",
                    action="打开客户记录核对等待回复、需求和报价状态，再由你决定是否跟进。",
                    reason="本地规则根据已绑定关系和沟通元数据将该客户列为今日优先处理项。",
                    target_page="客户管理",
                    execution_mode="manual",
                    evidence_refs=customer_evidence,
                )
            )

        cashflow = next(
            (row for row in prediction_rows if row.target == "cashflow_30d"),
            None,
        )
        if (
            cashflow is not None
            and cashflow.data_sufficiency in {"medium", "high"}
            and cashflow.prediction_value is not None
            and cashflow.prediction_value < 0
        ):
            cashflow_ref = "prediction.cashflow_30d.prediction_value"
            cashflow_evidence = [cashflow_ref, *cashflow.evidence_refs]
            insights.append(
                BusinessAnalysisInsight(
                    id="predicted-negative-cashflow",
                    domain="finance",
                    severity="critical",
                    title="未来 30 天现金流预测为负",
                    reason=(
                        f"已知现金流与合格历史基线合计预测为 ¥{cashflow.prediction_value:.2f}；"
                        "该结果不包含虚构订单收入。"
                    ),
                    evidence_refs=cashflow_evidence,
                )
            )
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="review-predicted-cashflow",
                    domain="finance",
                    priority="high",
                    title="人工复核未来 30 天现金安排",
                    action="核对确定性待回款和已知支出，必要时调整支出节奏或回款跟进。",
                    reason="现金流基线为负时应优先核对已知事实，不自动修改账本或项目。",
                    target_page="收入记录",
                    execution_mode="manual",
                    evidence_refs=cashflow_evidence,
                )
            )

        if not data_gaps and not any(row.severity in {"critical", "warning"} for row in insights):
            insights.append(
                BusinessAnalysisInsight(
                    id="cross-domain-baseline-ready",
                    domain="portfolio",
                    severity="positive",
                    title="跨域经营基线已经形成",
                    reason="商品、客户、项目与财务均有可追溯来源，可以开始小步执行并记录结果。",
                    evidence_refs=["products", "ledger", "conversations"],
                )
            )
        if not recommendations:
            recommendations.append(
                BusinessAnalysisRecommendation(
                    id="continue-evidence-loop",
                    domain="portfolio",
                    priority="low",
                    title="继续积累可比较样本",
                    action="保持商品快照、客户状态、项目交付和收支记录同步更新。",
                    reason="稳定样本比单次判断更能支持后续 AI 增强和经营复盘。",
                    target_page="首页概览",
                    evidence_refs=["products", "ledger", "conversations"],
                )
            )
        return insights, recommendations, data_gaps

    @staticmethod
    def _future_fields() -> list[BusinessAnalysisFutureField]:
        return [
            BusinessAnalysisFutureField(
                domain="customers",
                field="won_at",
                reason="当前只有成交状态，没有状态变更时间，暂不能计算客户成交周期趋势。",
            ),
            BusinessAnalysisFutureField(
                domain="projects",
                field="completed_at",
                reason="当前只有项目状态，没有统一完成时间，暂不能精确计算月度完工趋势。",
            ),
            BusinessAnalysisFutureField(
                domain="recommendations",
                field="validated_rule_id",
                reason="本阶段只保存建议结果，不会把单次结果自动晋升为长期经营规则。",
            ),
        ]
