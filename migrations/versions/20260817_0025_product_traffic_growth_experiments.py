"""Add paid-exposure time experiments and staged growth cohorts.

Revision ID: 20260817_0025
Revises: 20260817_0024
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260817_0025"
down_revision = "20260817_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    tables = {
        "product_traffic_experiments",
        "product_traffic_experiment_cells",
        "product_traffic_scale_cohorts",
        "product_traffic_scale_cohort_batches",
        "product_traffic_commercial_attributions",
        "product_traffic_budget_decisions",
        "product_traffic_growth_requests",
    }
    if tables.issubset(existing):
        return
    partial = tables.intersection(existing)
    if partial:
        raise RuntimeError(
            "product traffic growth migration found a partial schema: "
            + ", ".join(sorted(partial))
        )

    op.create_table(
        "product_traffic_experiments",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False, server_default="time_test"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("phase", sa.String(32), nullable=False, server_default="exploration"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("target_windows_json", sa.Text(), nullable=False, server_default='["12","16","20"]'),
        sa.Column("baseline_weekly_budget", sa.Float(), nullable=False, server_default="24"),
        sa.Column("current_weekly_budget", sa.Float(), nullable=False, server_default="24"),
        sa.Column("hard_weekly_cap", sa.Float(), nullable=False, server_default="48"),
        sa.Column("base_batch_cost", sa.Float(), nullable=False, server_default="5.9"),
        sa.Column("profit_ratio_scale_threshold", sa.Float(), nullable=False, server_default="5"),
        sa.Column("profit_ratio_hold_threshold", sa.Float(), nullable=False, server_default="2"),
        sa.Column("profit_ratio_break_even", sa.Float(), nullable=False, server_default="1"),
        sa.Column("min_attributed_inquiries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("min_paid_projects", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("min_realized_profit", sa.Float(), nullable=False, server_default="120"),
        sa.Column("cohort_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("tail_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("commercial_followup_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_product_traffic_experiments_request_id", "product_traffic_experiments", ["request_id"], unique=True)
    op.create_index("ix_product_traffic_experiments_item_id", "product_traffic_experiments", ["item_id"])
    op.create_index("ix_product_traffic_experiments_mode", "product_traffic_experiments", ["mode"])
    op.create_index("ix_product_traffic_experiments_status", "product_traffic_experiments", ["status"])
    op.create_index("ix_product_traffic_experiments_phase", "product_traffic_experiments", ["phase"])
    op.create_index("ix_product_traffic_experiments_started_at", "product_traffic_experiments", ["started_at"])
    op.create_index("idx_product_traffic_experiments_item_status", "product_traffic_experiments", ["item_id", "status"])

    op.create_table(
        "product_traffic_experiment_cells",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("experiment_id", sa.String(128), sa.ForeignKey("product_traffic_experiments.id"), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False, server_default="exploration"),
        sa.Column("window_bucket", sa.String(2), nullable=False),
        sa.Column("repeat_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        sa.Column("batch_id", sa.String(128), sa.ForeignKey("product_traffic_batches.id"), nullable=True, unique=True),
        sa.Column("actual_bucket", sa.String(2), nullable=True),
        sa.Column("exclusion_reason", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("experiment_id", "phase", "window_bucket", "repeat_index", name="uq_product_traffic_experiment_cell"),
    )
    for column in ("experiment_id", "phase", "window_bucket", "status", "scheduled_for"):
        op.create_index(f"ix_product_traffic_experiment_cells_{column}", "product_traffic_experiment_cells", [column])
    op.create_index("ix_product_traffic_experiment_cells_batch_id", "product_traffic_experiment_cells", ["batch_id"], unique=True)
    op.create_index("idx_product_traffic_experiment_cells_status_schedule", "product_traffic_experiment_cells", ["status", "scheduled_for"])

    op.create_table(
        "product_traffic_scale_cohorts",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("experiment_id", sa.String(128), sa.ForeignKey("product_traffic_experiments.id"), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        sa.Column("target_batches_per_week", sa.Integer(), nullable=False),
        sa.Column("weekly_budget", sa.Float(), nullable=False),
        sa.Column("no_other_promotion_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("listing_unchanged_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("tail_ends_at", sa.DateTime(), nullable=True),
        sa.Column("commercial_followup_ends_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("request_id", "experiment_id", "stage", "status", "started_at"):
        op.create_index(f"ix_product_traffic_scale_cohorts_{column}", "product_traffic_scale_cohorts", [column], unique=column == "request_id")
    op.create_index("idx_product_traffic_scale_cohorts_experiment_status", "product_traffic_scale_cohorts", ["experiment_id", "status"])

    op.create_table(
        "product_traffic_scale_cohort_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cohort_id", sa.String(128), sa.ForeignKey("product_traffic_scale_cohorts.id"), nullable=False),
        sa.Column("batch_id", sa.String(128), sa.ForeignKey("product_traffic_batches.id"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cohort_id", "batch_id", name="uq_product_traffic_scale_cohort_batch"),
    )
    op.create_index("ix_product_traffic_scale_cohort_batches_cohort_id", "product_traffic_scale_cohort_batches", ["cohort_id"])
    op.create_index("ix_product_traffic_scale_cohort_batches_batch_id", "product_traffic_scale_cohort_batches", ["batch_id"], unique=True)

    op.create_table(
        "product_traffic_commercial_attributions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("attribution_key", sa.String(256), nullable=False, unique=True),
        sa.Column("experiment_id", sa.String(128), sa.ForeignKey("product_traffic_experiments.id"), nullable=False),
        sa.Column("cohort_id", sa.String(128), sa.ForeignKey("product_traffic_scale_cohorts.id"), nullable=True),
        sa.Column("batch_id", sa.String(128), sa.ForeignKey("product_traffic_batches.id"), nullable=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="candidate"),
        sa.Column("source", sa.String(32), nullable=False, server_default="automatic"),
        sa.Column("first_inbound_at", sa.DateTime(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("confirmed_by_user_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("attribution_key", "experiment_id", "cohort_id", "batch_id", "item_id", "conversation_id", "project_id", "status", "first_inbound_at"):
        op.create_index(f"ix_product_traffic_commercial_attributions_{column}", "product_traffic_commercial_attributions", [column], unique=column == "attribution_key")
    op.create_index("idx_product_traffic_attributions_experiment_status", "product_traffic_commercial_attributions", ["experiment_id", "status"])
    op.create_index("idx_product_traffic_attributions_scope_conversation", "product_traffic_commercial_attributions", ["batch_id", "cohort_id", "conversation_id"])

    op.create_table(
        "product_traffic_budget_decisions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("decision_key", sa.String(256), nullable=False, unique=True),
        sa.Column("experiment_id", sa.String(128), sa.ForeignKey("product_traffic_experiments.id"), nullable=False),
        sa.Column("cohort_id", sa.String(128), sa.ForeignKey("product_traffic_scale_cohorts.id"), nullable=True),
        sa.Column("recommendation", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("from_stage", sa.String(16), nullable=False),
        sa.Column("to_stage", sa.String(16), nullable=False),
        sa.Column("current_weekly_budget", sa.Float(), nullable=False),
        sa.Column("recommended_weekly_budget", sa.Float(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("rules_version", sa.String(32), nullable=False, server_default="growth-v1"),
        sa.Column("observation_started_at", sa.DateTime(), nullable=True),
        sa.Column("observation_ended_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("decision_key", "experiment_id", "cohort_id", "recommendation", "status", "decided_at"):
        op.create_index(f"ix_product_traffic_budget_decisions_{column}", "product_traffic_budget_decisions", [column], unique=column == "decision_key")

    op.create_table(
        "product_traffic_growth_requests",
        sa.Column("request_id", sa.String(128), primary_key=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_product_traffic_growth_requests_operation", "product_traffic_growth_requests", ["operation"])
    op.create_index("ix_product_traffic_growth_requests_created_at", "product_traffic_growth_requests", ["created_at"])


def downgrade() -> None:
    for table in (
        "product_traffic_growth_requests",
        "product_traffic_budget_decisions",
        "product_traffic_commercial_attributions",
        "product_traffic_scale_cohort_batches",
        "product_traffic_scale_cohorts",
        "product_traffic_experiment_cells",
        "product_traffic_experiments",
    ):
        if table in set(sa.inspect(op.get_bind()).get_table_names()):
            op.drop_table(table)
