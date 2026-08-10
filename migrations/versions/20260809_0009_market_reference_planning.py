"""Add sanitized market reference, launch planning and modification experiments.

Revision ID: 20260809_0009
Revises: 20260808_0008
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260809_0009"
down_revision = "20260808_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_market_keyword_plans",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("plan_date", sa.String(10), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False, server_default="recommended"),
        sa.Column("selected_keyword", sa.String(120), nullable=False, server_default=""),
        sa.Column("custom_keyword", sa.String(120), nullable=False, server_default=""),
        sa.Column("recommended_candidates_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("rules_version", sa.String(32), nullable=False, server_default="market-v1"),
        sa.Column("save_as_common", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("plan_date", name="uq_product_market_keyword_plan_date"),
    )
    op.create_index("ix_product_market_keyword_plans_plan_date", "product_market_keyword_plans", ["plan_date"], unique=True)
    op.create_index("ix_product_market_keyword_plans_mode", "product_market_keyword_plans", ["mode"])
    op.create_index("ix_product_market_keyword_plans_save_as_common", "product_market_keyword_plans", ["save_as_common"])

    op.create_table(
        "product_market_samples",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("keyword", sa.String(120), nullable=False),
        sa.Column("sample_date", sa.String(10), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="edge_codex"),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("keyword", "sample_date", name="uq_product_market_sample_keyword_day"),
    )
    op.create_index("ix_product_market_samples_keyword", "product_market_samples", ["keyword"])
    op.create_index("ix_product_market_samples_sample_date", "product_market_samples", ["sample_date"])
    op.create_index("ix_product_market_samples_captured_at", "product_market_samples", ["captured_at"])
    op.create_index("idx_product_market_samples_keyword_date", "product_market_samples", ["keyword", "sample_date"])

    op.create_table(
        "product_market_sample_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sample_id", sa.String(128), sa.ForeignKey("product_market_samples.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("sample_id", "position", name="uq_product_market_result_position"),
    )
    op.create_index("ix_product_market_sample_results_sample_id", "product_market_sample_results", ["sample_id"])
    op.create_index("idx_product_market_results_sample_position", "product_market_sample_results", ["sample_id", "position"])

    op.create_table(
        "product_market_reminder_logs",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("reminder_date", sa.String(10), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="sent"),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("reminder_date", name="uq_product_market_reminder_date"),
    )
    op.create_index("ix_product_market_reminder_logs_reminder_date", "product_market_reminder_logs", ["reminder_date"], unique=True)
    op.create_index("ix_product_market_reminder_logs_status", "product_market_reminder_logs", ["status"])
    op.create_index("ix_product_market_reminder_logs_scheduled_for", "product_market_reminder_logs", ["scheduled_for"])

    op.create_table(
        "product_launch_plans",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("keyword", sa.String(120), nullable=False),
        sa.Column("theme", sa.String(120), nullable=False, server_default=""),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("recommended_window", sa.String(120), nullable=False, server_default=""),
        sa.Column("rationale_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.String(16), nullable=False, server_default="low"),
        sa.Column("status", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_product_launch_plans_keyword", "product_launch_plans", ["keyword"])
    op.create_index("ix_product_launch_plans_status", "product_launch_plans", ["status"])
    op.create_index("ix_product_launch_plans_created_at", "product_launch_plans", ["created_at"])

    op.create_table(
        "product_modification_experiments",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("variable", sa.String(32), nullable=False),
        sa.Column("before_value", sa.Text(), nullable=False),
        sa.Column("after_value", sa.Text(), nullable=False),
        sa.Column("baseline_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("observation_until", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="observing"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("decision", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_product_modification_experiments_item_id", "product_modification_experiments", ["item_id"])
    op.create_index("ix_product_modification_experiments_variable", "product_modification_experiments", ["variable"])
    op.create_index("ix_product_modification_experiments_started_at", "product_modification_experiments", ["started_at"])
    op.create_index("ix_product_modification_experiments_observation_until", "product_modification_experiments", ["observation_until"])
    op.create_index("ix_product_modification_experiments_status", "product_modification_experiments", ["status"])
    op.create_index("ix_product_modification_experiments_decision", "product_modification_experiments", ["decision"])
    op.create_index("idx_product_modification_item_status_until", "product_modification_experiments", ["item_id", "status", "observation_until"])


def downgrade() -> None:
    # These tables contain user-entered market observations and experiment
    # history. Avoid a destructive automatic downgrade.
    pass
