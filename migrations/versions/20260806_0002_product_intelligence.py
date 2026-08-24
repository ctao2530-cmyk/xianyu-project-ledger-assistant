"""Add read-only daily product intelligence tables.

Revision ID: 20260806_0002
Revises: 20260806_0001
"""
from __future__ import annotations

from alembic import op

from backend.app.database import Base
from backend.app import models  # noqa: F401


revision = "20260806_0002"
down_revision = "20260806_0001"
branch_labels = None
depends_on = None


NEW_TABLES = (
    "product_action_logs",
    "product_strategy_recommendations",
    "product_collection_runs",
    "product_daily_snapshots",
    "product_monitors",
)


def upgrade() -> None:
    # Keep this revision temporally isolated from tables added by later
    # migrations.  ``Base.metadata`` reflects today's model, not the 0002
    # snapshot, so creating all metadata here would poison the remaining chain.
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=[Base.metadata.tables[name] for name in NEW_TABLES],
        checkfirst=True,
    )


def downgrade() -> None:
    for table_name in NEW_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table_name}")
