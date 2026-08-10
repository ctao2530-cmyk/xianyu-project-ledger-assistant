"""Separate raw platform views from operating browse totals.

Revision ID: 20260810_0012
Revises: 20260810_0011
"""
from __future__ import annotations

from alembic import op

from backend.app.schema_migrations import migrate_product_browse_accounting_schema


revision = "20260810_0012"
down_revision = "20260810_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_product_browse_accounting_schema(op.get_bind())


def downgrade() -> None:
    # These columns preserve audit evidence. Restore the pre-upgrade backup
    # instead of destructively folding the two counters back together.
    pass
