"""Add project settlement issues and exception accounting.

Revision ID: 20260808_0006
Revises: 20260807_0005
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260808_0006"
down_revision = "20260807_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_settlement_issues",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(128),
            sa.ForeignKey("business_projects.id"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.String(128),
            sa.ForeignKey("business_customers.id"),
            nullable=False,
        ),
        sa.Column("issue_type", sa.String(64), nullable=False),
        sa.Column("receivable_impact", sa.Float(), nullable=False, server_default="0"),
        sa.Column("refund_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("occurred_at", sa.String(64), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_project_settlement_issue_request"),
    )
    op.create_index(
        "idx_project_settlement_issues_project_id",
        "project_settlement_issues",
        ["project_id"],
    )
    op.create_index(
        "idx_project_settlement_issues_customer_id",
        "project_settlement_issues",
        ["customer_id"],
    )
    op.create_index(
        "idx_project_settlement_issues_type",
        "project_settlement_issues",
        ["issue_type"],
    )
    op.create_index(
        "idx_project_settlement_issues_created_at",
        "project_settlement_issues",
        ["created_at"],
    )


def downgrade() -> None:
    # These rows are financial audit evidence. Destructive downgrades are
    # intentionally not automated.
    pass
