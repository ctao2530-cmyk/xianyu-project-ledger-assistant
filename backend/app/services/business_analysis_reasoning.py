from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from ..ai.base import AIModelSelection, AIProvider
from ..business_analysis_schemas import (
    BusinessAnalysisInsight,
    BusinessAnalysisOverview,
    BusinessAnalysisRecommendation,
)


class BusinessAnalysisEvidenceError(RuntimeError):
    """Raised when model output escapes the supplied evidence whitelist."""


class AIInsightEnhancement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=4, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=12)


class AIRecommendationEnhancement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=2, max_length=120)
    problem: str = Field(min_length=2, max_length=300)
    reason: str = Field(min_length=4, max_length=500)
    action: str = Field(min_length=4, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=12)


class BusinessAnalysisAIResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=10, max_length=500)
    insights: list[AIInsightEnhancement] = Field(default_factory=list, max_length=12)
    recommendations: list[AIRecommendationEnhancement] = Field(
        default_factory=list,
        max_length=8,
    )


class BusinessAnalysisReasoningService:
    """Model enhancement constrained to deterministic, aggregated evidence.

    The model may summarize, reorder, and clarify existing findings. It cannot
    create new entity IDs, evidence references, financial figures, execution
    modes, or business mutations.
    """

    def __init__(
        self,
        provider: AIProvider,
        *,
        model_selection: AIModelSelection,
        timeout_seconds: float,
    ) -> None:
        self.provider = provider
        self.model_selection = model_selection
        self.timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return self.provider.name

    @property
    def model_name(self) -> str | None:
        return self.model_selection.model or self.provider.model_selection.model

    @staticmethod
    def _prompt_payload(baseline: BusinessAnalysisOverview) -> dict[str, object]:
        return {
            "period": baseline.period.model_dump(mode="json"),
            "metrics": baseline.metrics.model_dump(mode="json"),
            "insights": [row.model_dump(mode="json") for row in baseline.insights],
            "recommendations": [
                {
                    "id": row.id,
                    "domain": row.domain,
                    "priority": row.priority,
                    "title": row.title,
                    "problem": row.problem,
                    "reason": row.reason,
                    "action": row.action,
                    "data_source": row.data_source,
                    "confidence": row.confidence,
                    "observe_period": row.observe_period,
                    "evidence_refs": row.evidence_refs,
                }
                for row in baseline.recommendations
            ],
            "data_sources": [
                {
                    "id": row.id,
                    "label": row.label,
                    "fields": row.fields,
                    "available": row.available,
                    "record_count": row.record_count,
                    "latest_at": row.latest_at,
                    "note": row.note,
                }
                for row in baseline.data_sources
            ],
            "data_gaps": baseline.data_gaps,
            "predictions": [
                {
                    "target": row.target,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "horizon": row.horizon,
                    "prediction_value": row.prediction_value,
                    "score": row.score,
                    "risk_level": row.risk_level,
                    "data_sufficiency": row.data_sufficiency,
                    "method": row.method,
                    "summary": row.summary,
                    "facts": [fact.model_dump(mode="json") for fact in row.facts],
                    "evidence_refs": row.evidence_refs,
                }
                for row in baseline.predictions
            ],
        }

    @staticmethod
    def _require_unique_ids(rows: list[object], *, kind: str) -> None:
        ids = [getattr(row, "id") for row in rows]
        if len(ids) != len(set(ids)):
            raise BusinessAnalysisEvidenceError(f"duplicate_{kind}_id")

    @staticmethod
    def _validate_refs(
        returned: list[str],
        allowed: list[str],
        *,
        kind: str,
    ) -> None:
        if not returned or not set(returned).issubset(set(allowed)):
            raise BusinessAnalysisEvidenceError(f"unknown_{kind}_evidence")

    def _merge(
        self,
        baseline: BusinessAnalysisOverview,
        enhanced: BusinessAnalysisAIResult,
    ) -> BusinessAnalysisOverview:
        self._require_unique_ids(enhanced.insights, kind="insight")
        self._require_unique_ids(enhanced.recommendations, kind="recommendation")

        source_insights = {row.id: row for row in baseline.insights}
        source_recommendations = {row.id: row for row in baseline.recommendations}
        merged_insights: list[BusinessAnalysisInsight] = []
        returned_insight_ids: set[str] = set()
        for row in enhanced.insights:
            source = source_insights.get(row.id)
            if source is None:
                raise BusinessAnalysisEvidenceError("unknown_insight_id")
            self._validate_refs(
                row.evidence_refs,
                source.evidence_refs,
                kind="insight",
            )
            returned_insight_ids.add(row.id)
            merged_insights.append(
                source.model_copy(
                    update={
                        "title": row.title,
                        "reason": row.reason,
                        "evidence_refs": row.evidence_refs,
                    }
                )
            )
        merged_insights.extend(
            row for row in baseline.insights if row.id not in returned_insight_ids
        )

        merged_recommendations: list[BusinessAnalysisRecommendation] = []
        returned_recommendation_ids: set[str] = set()
        for row in enhanced.recommendations:
            source = source_recommendations.get(row.id)
            if source is None:
                raise BusinessAnalysisEvidenceError("unknown_recommendation_id")
            self._validate_refs(
                row.evidence_refs,
                source.evidence_refs,
                kind="recommendation",
            )
            returned_recommendation_ids.add(row.id)
            merged_recommendations.append(
                source.model_copy(
                    update={
                        "title": row.title,
                        "problem": row.problem,
                        "reason": row.reason,
                        "action": row.action,
                        "evidence_refs": row.evidence_refs,
                    }
                )
            )
        merged_recommendations.extend(
            row
            for row in baseline.recommendations
            if row.id not in returned_recommendation_ids
        )

        return baseline.model_copy(
            update={
                "summary": enhanced.summary,
                "insights": merged_insights,
                "recommendations": merged_recommendations,
                "analysis_method": (
                    "rules_plus_deepseek_v1"
                    if self.provider_name == "deepseek"
                    else "rules_plus_codex_v1"
                ),
                "provider": self.provider_name,
                "model": self.model_name,
                "ai_status": "succeeded",
                "fallback_used": False,
                "ai_error": None,
            }
        )

    async def enhance(
        self,
        baseline: BusinessAnalysisOverview,
        *,
        task_key: str,
    ) -> BusinessAnalysisOverview:
        payload = self._prompt_payload(baseline)
        prompt = (
            "请基于以下脱敏聚合经营事实，输出主动经营分析。你只能改写、排序已给出的"
            " insight 和 recommendation，所有 id 必须来自输入，evidence_refs 只能从对应"
            "条目的白名单中选择。不得新增经营数字、客户身份、商品操作、自动发送、自动"
            "发布、自动投流或自动购买行为。建议动作必须保持人工执行。不要把缺失数据"
            "当成零。\n\n脱敏事实：\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        enhanced = await self.provider.generate_structured(
            prompt,
            result_type=BusinessAnalysisAIResult,
            task_key=task_key,
            model_selection=self.model_selection,
            timeout=self.timeout_seconds,
        )
        return self._merge(baseline, enhanced)
