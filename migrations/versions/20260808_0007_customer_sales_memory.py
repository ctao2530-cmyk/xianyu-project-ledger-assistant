"""Add independent Sales Agent analysis and customer memory.

Revision ID: 20260808_0007
Revises: 20260808_0006
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260808_0007"
down_revision = "20260808_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_analysis_runs",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("messages.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("structured_json", sa.Text(), nullable=True),
        sa.Column("tools_used_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("context_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_sales_analysis_conversation_created",
        "sales_analysis_runs",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "idx_sales_analysis_message_status",
        "sales_analysis_runs",
        ["message_id", "status"],
    )
    op.create_index(
        "ix_sales_analysis_runs_conversation_id",
        "sales_analysis_runs",
        ["conversation_id"],
    )
    op.create_index(
        "ix_sales_analysis_runs_message_id",
        "sales_analysis_runs",
        ["message_id"],
    )
    op.create_index(
        "ix_sales_analysis_runs_status",
        "sales_analysis_runs",
        ["status"],
    )
    op.create_index(
        "ix_sales_analysis_runs_created_at",
        "sales_analysis_runs",
        ["created_at"],
    )

    op.create_table(
        "customer_memory",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "customer_id",
            sa.String(128),
            sa.ForeignKey("business_customers.id"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "source_analysis_id",
            sa.String(128),
            sa.ForeignKey("sales_analysis_runs.id"),
            nullable=True,
        ),
        sa.Column("customer_background", sa.Text(), nullable=False, server_default=""),
        sa.Column("requirements_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("communication_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("latest_analysis_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("follow_up_status", sa.String(64), nullable=False, server_default="待跟进"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", name="uq_customer_memory_conversation"),
    )
    op.create_index(
        "ix_customer_memory_customer_id",
        "customer_memory",
        ["customer_id"],
    )
    op.create_index(
        "ix_customer_memory_conversation_id",
        "customer_memory",
        ["conversation_id"],
    )
    op.create_index(
        "ix_customer_memory_source_analysis_id",
        "customer_memory",
        ["source_analysis_id"],
    )
    op.create_index(
        "ix_customer_memory_follow_up_status",
        "customer_memory",
        ["follow_up_status"],
    )


def downgrade() -> None:
    # Sales memory is user-confirmed CRM context. Avoid destructive automatic
    # downgrades that could silently erase follow-up history.
    pass
