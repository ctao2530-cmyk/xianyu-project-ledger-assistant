"""Add customer-intake profile fields.

Revision ID: 20260820_0036
Revises: 20260819_0035
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260820_0036"
down_revision = "20260819_0035"
branch_labels = None
depends_on = None


COLUMNS = {
    "current_need",
    "price_type",
    "price_amount",
    "next_action",
    "notes",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "business_customers" not in inspector.get_table_names():
        return
    present = {
        column["name"]
        for column in inspector.get_columns("business_customers")
    }.intersection(COLUMNS)
    if present == COLUMNS:
        return
    if present:
        raise RuntimeError(
            "customer intake schema is partial; refusing silent repair; missing columns: "
            + ", ".join(sorted(COLUMNS - present))
        )
    op.add_column(
        "business_customers",
        sa.Column("current_need", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "business_customers",
        sa.Column("price_type", sa.String(32), nullable=False, server_default=""),
    )
    op.add_column(
        "business_customers",
        sa.Column("price_amount", sa.Float(), nullable=True),
    )
    op.add_column(
        "business_customers",
        sa.Column("next_action", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "business_customers",
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    with op.batch_alter_table("business_customers") as batch:
        batch.drop_column("notes")
        batch.drop_column("next_action")
        batch.drop_column("price_amount")
        batch.drop_column("price_type")
        batch.drop_column("current_need")
