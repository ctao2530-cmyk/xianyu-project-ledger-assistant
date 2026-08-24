from __future__ import annotations

from typing import Any

from ...prediction.service import PredictionService


class BusinessPredictionTool:
    """Read-only Prediction access for 小策 and future agent orchestration."""

    name = "business_predictions"

    def __init__(self, predictions: PredictionService) -> None:
        self.predictions = predictions

    def get_business_predictions(self) -> dict[str, Any]:
        return self.predictions.latest_summary().model_dump(mode="json")

    def get_project_prediction(self, project_id: str) -> dict[str, Any] | None:
        result = self.predictions.project(project_id)
        return result.model_dump(mode="json") if result is not None else None

    def get_customer_priority(self, customer_id: str) -> dict[str, Any] | None:
        result = self.predictions.customer(customer_id)
        return result.model_dump(mode="json") if result is not None else None
