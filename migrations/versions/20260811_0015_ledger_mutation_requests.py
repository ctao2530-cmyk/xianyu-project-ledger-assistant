"""Add idempotency audit for narrow ledger mutations.

Revision ID: 20260811_0015
Revises: 20260811_0014
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_0015"
down_revision = "20260811_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ledger_mutation_requests" in set(inspector.get_table_names()):
        existing_columns = {
            str(column["name"])
            for column in inspector.get_columns("ledger_mutation_requests")
        }
        expected_columns = {
            "request_id",
            "operation",
            "payload_hash",
            "result_json",
            "created_at",
        }
        if expected_columns.issubset(existing_columns):
            # Local startup creates additive model tables before some legacy
            # installations begin tracking Alembic. Accept only the complete
            # schema; a partial audit table must remain a hard failure.
            return
        raise RuntimeError(
            "ledger mutation migration found an incomplete schema: "
            + ", ".join(sorted(existing_columns))
        )
    op.create_table(
        "ledger_mutation_requests",
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index(
        "ix_ledger_mutation_requests_operation",
        "ledger_mutation_requests",
        ["operation"],
        unique=False,
    )
    op.create_index(
        "ix_ledger_mutation_requests_created_at",
        "ledger_mutation_requests",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    # These rows are audit evidence for idempotent business writes. Restore a
    # backup instead of deleting them during an automatic downgrade.
    pass
