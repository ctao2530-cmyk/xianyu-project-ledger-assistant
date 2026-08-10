"""Add multi-product exposure batches and rolling operating plans.

Revision ID: 20260808_0008
Revises: 20260808_0007
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260808_0008"
down_revision = "20260808_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_operating_plans",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("plan_start_date", sa.String(10), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="current"),
        sa.Column("input_signature", sa.String(128), nullable=False),
        sa.Column("weekly_budget", sa.Float(), nullable=False, server_default="24"),
        sa.Column("change_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("data_quality", sa.String(32), nullable=False, server_default="low"),
        sa.Column("rules_version", sa.String(32), nullable=False, server_default="v2"),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "plan_start_date", "version", name="uq_product_operating_plan_version"
        ),
    )
    op.create_index(
        "ix_product_operating_plans_plan_start_date",
        "product_operating_plans",
        ["plan_start_date"],
    )
    op.create_index(
        "ix_product_operating_plans_status", "product_operating_plans", ["status"]
    )
    op.create_index(
        "ix_product_operating_plans_input_signature",
        "product_operating_plans",
        ["input_signature"],
    )
    op.create_index(
        "ix_product_operating_plans_generated_at",
        "product_operating_plans",
        ["generated_at"],
    )
    op.create_index(
        "idx_product_operating_plans_status_start",
        "product_operating_plans",
        ["status", "plan_start_date"],
    )

    op.create_table(
        "product_operating_plan_slots",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(128),
            sa.ForeignKey("product_operating_plans.id"),
            nullable=False,
        ),
        sa.Column("slot_date", sa.String(10), nullable=False),
        sa.Column("scheduled_time", sa.String(5), nullable=False, server_default="20:00"),
        sa.Column("action_type", sa.String(32), nullable=False, server_default="observe"),
        sa.Column("item_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("planned_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("change_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("warnings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.String(16), nullable=False, server_default="low"),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("plan_id", "slot_date", name="uq_product_plan_slot_date"),
    )
    for index_name, columns in (
        ("ix_product_operating_plan_slots_plan_id", ["plan_id"]),
        ("ix_product_operating_plan_slots_slot_date", ["slot_date"]),
        ("ix_product_operating_plan_slots_action_type", ["action_type"]),
        ("ix_product_operating_plan_slots_locked", ["locked"]),
        ("ix_product_operating_plan_slots_status", ["status"]),
        ("idx_product_plan_slots_date_action", ["slot_date", "action_type"]),
    ):
        op.create_index(index_name, "product_operating_plan_slots", columns)

    op.create_table(
        "product_traffic_batches",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "plan_slot_id",
            sa.String(128),
            sa.ForeignKey("product_operating_plan_slots.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        sa.Column("planned_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("actual_cost", sa.Float(), nullable=False, server_default="5.9"),
        sa.Column("total_exposure", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for index_name, columns in (
        ("ix_product_traffic_batches_request_id", ["request_id"]),
        ("ix_product_traffic_batches_plan_slot_id", ["plan_slot_id"]),
        ("ix_product_traffic_batches_status", ["status"]),
        ("ix_product_traffic_batches_planned_at", ["planned_at"]),
        ("ix_product_traffic_batches_started_at", ["started_at"]),
        ("idx_product_traffic_batches_status_planned", ["status", "planned_at"]),
    ):
        op.create_index(index_name, "product_traffic_batches", columns)

    op.create_table(
        "product_traffic_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(128),
            sa.ForeignKey("product_traffic_batches.id"),
            nullable=False,
        ),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline_browse_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline_collect_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline_want_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline_inquiry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline_captured_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("batch_id", "item_id", name="uq_product_traffic_batch_item"),
    )
    op.create_index("ix_product_traffic_batch_items_batch_id", "product_traffic_batch_items", ["batch_id"])
    op.create_index("ix_product_traffic_batch_items_item_id", "product_traffic_batch_items", ["item_id"])
    op.create_index("idx_product_traffic_batch_items_batch_position", "product_traffic_batch_items", ["batch_id", "position"])

    op.create_table(
        "product_traffic_checkpoints",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("batch_id", sa.String(128), sa.ForeignKey("product_traffic_batches.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("checkpoint", sa.String(16), nullable=False),
        sa.Column("browse_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("collect_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("want_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inquiry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("batch_id", "item_id", "checkpoint", name="uq_product_traffic_checkpoint"),
    )
    for index_name, columns in (
        ("ix_product_traffic_checkpoints_batch_id", ["batch_id"]),
        ("ix_product_traffic_checkpoints_item_id", ["item_id"]),
        ("ix_product_traffic_checkpoints_checkpoint", ["checkpoint"]),
        ("ix_product_traffic_checkpoints_recorded_at", ["recorded_at"]),
        ("idx_product_traffic_checkpoints_batch_checkpoint", ["batch_id", "checkpoint"]),
    ):
        op.create_index(index_name, "product_traffic_checkpoints", columns)

    op.create_table(
        "product_traffic_reminder_logs",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("batch_id", sa.String(128), sa.ForeignKey("product_traffic_batches.id"), nullable=False),
        sa.Column("reminder_type", sa.String(32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("batch_id", "reminder_type", name="uq_product_traffic_reminder"),
    )
    op.create_index("ix_product_traffic_reminder_logs_batch_id", "product_traffic_reminder_logs", ["batch_id"])
    op.create_index("ix_product_traffic_reminder_logs_reminder_type", "product_traffic_reminder_logs", ["reminder_type"])
    op.create_index("ix_product_traffic_reminder_logs_scheduled_for", "product_traffic_reminder_logs", ["scheduled_for"])
    op.create_index("idx_product_traffic_reminders_schedule", "product_traffic_reminder_logs", ["scheduled_for", "sent_at"])


def downgrade() -> None:
    # These tables contain user-recorded spend and experiment observations.
    # Avoid a destructive automatic downgrade that could silently remove them.
    pass
