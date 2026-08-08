"""Add product ownership and per-item collection diagnostics.

Revision ID: 20260807_0005
Revises: 20260807_0004
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.app.schema_migrations import migrate_product_monitor_schema


revision = "20260807_0005"
down_revision = "20260807_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        migrate_product_monitor_schema(bind)
        return
    with op.batch_alter_table("product_monitors") as batch:
        batch.add_column(sa.Column("ownership_status", sa.String(32), server_default="pending", nullable=False))
        batch.add_column(sa.Column("ownership_source", sa.String(64), server_default="unverified", nullable=False))
        batch.add_column(sa.Column("last_attempt_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_collection_status", sa.String(32), server_default="waiting", nullable=False))
        batch.add_column(sa.Column("last_error_code", sa.String(64), nullable=True))
        batch.add_column(sa.Column("last_error_detail", sa.String(500), nullable=True))
        batch.create_index("ix_product_monitors_ownership_status", ["ownership_status"])


def downgrade() -> None:
    # Ownership history explains why a product was excluded from business
    # advice, so destructive downgrades are intentionally not automated.
    pass
