"""Bind customers and requirement cases to conversation listings.

Revision ID: 20260810_0010
Revises: 20260809_0009
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.app.schema_migrations import backfill_requirement_cases


revision = "20260810_0010"
down_revision = "20260809_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "customer_item_links" not in tables:
        op.create_table(
            "customer_item_links",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("customer_id", sa.String(128), sa.ForeignKey("business_customers.id"), nullable=False),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
            sa.Column("source_conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=True),
            sa.Column("source_type", sa.String(32), nullable=False, server_default="requirement_import"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("customer_id", "item_id", name="uq_customer_item_link"),
        )
        op.create_index("ix_customer_item_links_customer_id", "customer_item_links", ["customer_id"])
        op.create_index("ix_customer_item_links_item_id", "customer_item_links", ["item_id"])
        op.create_index(
            "ix_customer_item_links_source_conversation_id",
            "customer_item_links",
            ["source_conversation_id"],
        )

    case_columns = {column["name"] for column in inspector.get_columns("requirement_cases")}
    if "item_id" not in case_columns:
        if bind.dialect.name == "sqlite":
            op.execute(
                "ALTER TABLE requirement_cases ADD COLUMN item_id INTEGER REFERENCES items(id)"
            )
        else:
            op.add_column(
                "requirement_cases",
                sa.Column("item_id", sa.Integer(), nullable=True),
            )
            op.create_foreign_key(
                "fk_requirement_cases_item",
                "requirement_cases",
                "items",
                ["item_id"],
                ["id"],
            )
    case_indexes = {index["name"] for index in inspector.get_indexes("requirement_cases")}
    if "ix_requirement_cases_item_id" not in case_indexes:
        op.create_index("ix_requirement_cases_item_id", "requirement_cases", ["item_id"])

    if bind.dialect.name == "sqlite":
        backfill_requirement_cases(bind)


def downgrade() -> None:
    # These links are confirmed business provenance. Avoid deleting them during
    # an automated downgrade; restore the pre-migration SQLite backup instead.
    pass
