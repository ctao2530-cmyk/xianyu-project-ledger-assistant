from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ...database import Database
from ...models import BusinessProject, QuoteProposal


class PricingHistoryTool:
    """Read-only real quote and contract history; it never confirms a price."""

    name = "pricing_history"

    def __init__(self, database: Database, *, limit: int = 8) -> None:
        self.database = database
        self.limit = max(1, min(limit, 20))

    def run(self, similar_project_ids: list[str] | None = None) -> dict[str, Any]:
        project_ids = [value for value in (similar_project_ids or []) if value]
        with self.database.session() as session:
            project_query = select(BusinessProject).where(
                BusinessProject.project_kind == "client"
            )
            if project_ids:
                project_query = project_query.where(BusinessProject.id.in_(project_ids))
            projects = list(
                session.scalars(
                    project_query.order_by(BusinessProject.created_at.desc()).limit(self.limit)
                )
            )
            quotes = list(
                session.scalars(
                    select(QuoteProposal)
                    .order_by(QuoteProposal.created_at.desc())
                    .limit(self.limit)
                )
            )

        project_prices = [
            {
                "project_id": project.id,
                "name": project.name,
                "type": project.type,
                "contract_amount": round(float(project.total_amount or 0), 2),
                "estimated_hours": round(float(project.estimated_hours or 0), 1),
                "contract_hourly_rate": (
                    round(float(project.total_amount) / float(project.estimated_hours), 2)
                    if project.estimated_hours and project.total_amount
                    else None
                ),
            }
            for project in projects
        ]
        quote_history = [
            {
                "quote_id": quote.id,
                "status": quote.status,
                "total_amount": round(float(quote.total_amount or 0), 2),
                "estimated_hours": round(float(quote.estimated_hours or 0), 1),
                "hourly_rate": round(float(quote.hourly_rate or 0), 2),
                "risk_buffer": round(float(quote.risk_buffer or 0), 3),
            }
            for quote in quotes
        ]
        observed_amounts = [
            float(item["contract_amount"])
            for item in project_prices
            if float(item["contract_amount"]) > 0
        ] + [
            float(item["total_amount"])
            for item in quote_history
            if float(item["total_amount"]) > 0
        ]
        return {
            "project_prices": project_prices,
            "quote_history": quote_history,
            "quote_count": len(quote_history),
            "observed_amount_range": (
                {
                    "minimum": round(min(observed_amounts), 2),
                    "maximum": round(max(observed_amounts), 2),
                }
                if observed_amounts
                else None
            ),
            "note": (
                "只提供真实历史参考，不生成或确认本次报价；最终金额仍需人工确认。"
            ),
        }
