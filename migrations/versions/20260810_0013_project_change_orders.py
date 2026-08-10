"""Add auditable project change orders and payment-node linkage.

Revision ID: 20260810_0013
Revises: 20260810_0012
"""
from __future__ import annotations

from alembic import op

from backend.app.schema_migrations import migrate_project_change_order_schema


revision = "20260810_0013"
down_revision = "20260810_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_project_change_order_schema(op.get_bind())


def downgrade() -> None:
    # Change orders and their payment linkage are financial audit evidence.
    # Restore the pre-upgrade SQLite backup instead of deleting them.
    pass
