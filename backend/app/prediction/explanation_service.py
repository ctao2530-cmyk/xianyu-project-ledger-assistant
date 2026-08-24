from __future__ import annotations


class PredictionExplanationService:
    """Centralized user-facing labels for deterministic prediction outputs."""

    risk_labels = {
        "low": "低",
        "normal": "正常",
        "warning": "需关注",
        "high": "高",
        "urgent": "紧急",
        "overloaded": "超载",
    }

    sufficiency_labels = {
        "low": "低",
        "medium": "中",
        "high": "高",
    }

    @classmethod
    def risk_label(cls, value: str) -> str:
        return cls.risk_labels.get(value, value)

    @classmethod
    def sufficiency_label(cls, value: str) -> str:
        return cls.sufficiency_labels.get(value, value)
