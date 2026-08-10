"""Persist product collection attempts for operation-level history.

Revision ID: 20260810_0011
Revises: 20260810_0010
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.app.schema_migrations import backfill_product_collection_attempts


revision = "20260810_0011"
down_revision = "20260810_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "product_collection_attempts" not in tables:
        op.create_table(
            "product_collection_attempts",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("run_date", sa.String(10), nullable=False),
            sa.Column(
                "daily_run_id",
                sa.String(128),
                sa.ForeignKey("product_collection_runs.id"),
                nullable=True,
                unique=True,
            ),
            sa.Column(
                "requested_item_id",
                sa.Integer(),
                sa.ForeignKey("items.id"),
                nullable=True,
            ),
            sa.Column("trigger", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("monitored_count", sa.Integer(), nullable=False),
            sa.Column("collected_count", sa.Integer(), nullable=False),
            sa.Column("failed_count", sa.Integer(), nullable=False),
            sa.Column("skipped_count", sa.Integer(), nullable=False),
            sa.Column("detail", sa.String(500), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
        for name, columns in (
            ("ix_product_collection_attempts_run_date", ["run_date"]),
            ("ix_product_collection_attempts_daily_run_id", ["daily_run_id"]),
            ("ix_product_collection_attempts_requested_item_id", ["requested_item_id"]),
            ("ix_product_collection_attempts_trigger", ["trigger"]),
            ("ix_product_collection_attempts_status", ["status"]),
            ("ix_product_collection_attempts_started_at", ["started_at"]),
            ("ix_product_collection_attempts_finished_at", ["finished_at"]),
            ("idx_product_collection_attempts_date_finished", ["run_date", "finished_at"]),
        ):
            op.create_index(name, "product_collection_attempts", columns)
    if "product_collection_attempt_items" not in tables:
        op.create_table(
            "product_collection_attempt_items",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "attempt_id",
                sa.String(128),
                sa.ForeignKey("product_collection_attempts.id"),
                nullable=False,
            ),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("error_code", sa.String(64), nullable=True),
            sa.Column("detail", sa.String(500), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "attempt_id",
                "item_id",
                name="uq_product_collection_attempt_item",
            ),
        )
        for name, columns in (
            ("ix_product_collection_attempt_items_attempt_id", ["attempt_id"]),
            ("ix_product_collection_attempt_items_item_id", ["item_id"]),
            ("ix_product_collection_attempt_items_status", ["status"]),
            ("ix_product_collection_attempt_items_finished_at", ["finished_at"]),
            (
                "idx_product_collection_attempt_items_item_finished",
                ["item_id", "finished_at"],
            ),
        ):
            op.create_index(name, "product_collection_attempt_items", columns)
    backfill_product_collection_attempts(bind)


def downgrade() -> None:
    # Collection attempts are an audit trail. Restore the pre-upgrade backup
    # instead of deleting operation history automatically.
    pass
