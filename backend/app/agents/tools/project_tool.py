from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from ...database import Database
from ...models import BusinessProject


def _search_chars(value: str) -> set[str]:
    return {
        char
        for char in re.sub(r"\s+", "", value.casefold())
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    }


class SimilarProjectTool:
    """Read-only lookup of real project records that resemble the current need."""

    name = "similar_projects"

    def __init__(self, database: Database, *, limit: int = 5) -> None:
        self.database = database
        self.limit = max(1, min(limit, 10))

    def run(self, query: str) -> dict[str, Any]:
        query_chars = _search_chars(query)
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(BusinessProject)
                    .where(BusinessProject.project_kind == "client")
                    .order_by(BusinessProject.created_at.desc())
                    .limit(80)
                )
            )

        scored: list[tuple[float, BusinessProject]] = []
        for project in rows:
            haystack = f"{project.name} {project.type} {project.notes}"
            project_chars = _search_chars(haystack)
            overlap = (
                len(query_chars & project_chars) / max(1, len(query_chars))
                if query_chars
                else 0.0
            )
            exact_bonus = 0.35 if project.type and project.type.casefold() in query.casefold() else 0
            scored.append((min(1.0, overlap + exact_bonus), project))
        scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        matches = [
            {
                "project_id": project.id,
                "name": project.name,
                "type": project.type,
                "status": project.status,
                "contract_amount": round(float(project.total_amount or 0), 2),
                "estimated_hours": round(float(project.estimated_hours or 0), 1),
                "similarity": round(score, 2),
            }
            for score, project in scored[: self.limit]
        ]
        return {
            "query": query[:500],
            "matches": matches,
            "match_count": len(matches),
            "note": (
                "仅返回 SQLite 中真实项目；相似度为本地文本匹配，不代表成交预测。"
            ),
        }
