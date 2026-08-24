"""Add verified-outcome estimate calibration and audited quote decisions.

Revision ID: 20260818_0030
Revises: 20260818_0029
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260818_0030"
down_revision = "20260818_0029"
branch_labels = None
depends_on = None


TABLES = {
    "estimate_calibration_samples",
    "estimate_calibration_runs",
    "estimate_calibration_suggestions",
    "estimate_calibration_decisions",
    "estimate_calibration_mutation_requests",
}


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    partial = TABLES.intersection(existing)
    if partial and partial != TABLES:
        missing = ", ".join(sorted(TABLES - partial))
        raise RuntimeError(
            "estimate calibration schema is partial; refusing silent repair "
            f"(missing: {missing})"
        )
    if partial == TABLES:
        return

    op.create_table(
        "estimate_calibration_samples",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("project_name", sa.String(300), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "supersedes_sample_id",
            sa.String(128),
            sa.ForeignKey("estimate_calibration_samples.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("estimate_source", sa.String(64), nullable=False, server_default="business_project"),
        sa.Column("estimated_hours", sa.Float(), nullable=False),
        sa.Column("actual_hours", sa.Float(), nullable=False),
        sa.Column("signed_error_hours", sa.Float(), nullable=False),
        sa.Column("absolute_error_hours", sa.Float(), nullable=False),
        sa.Column("actual_to_estimate_ratio", sa.Float(), nullable=False),
        sa.Column("estimated_delivery_at", sa.String(64), nullable=False, server_default=""),
        sa.Column("actual_completed_at", sa.DateTime(), nullable=False),
        sa.Column("requirement_complexity", sa.Float(), nullable=True),
        sa.Column("blocker_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("change_order_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("test_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rework_hours", sa.Float(), nullable=False, server_default="0"),
        sa.Column("verified_progress", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(), nullable=False),
        sa.Column("outcome_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "project_id", "source_hash", "actual_completed_at", "available_at",
        "finalized_at", "cutoff_at", "created_at",
    ):
        op.create_index(
            f"ix_estimate_calibration_samples_{column}",
            "estimate_calibration_samples",
            [column],
        )
    op.create_index(
        "idx_estimate_calibration_samples_project_cutoff",
        "estimate_calibration_samples",
        ["project_id", "cutoff_at"],
    )

    op.create_table(
        "estimate_calibration_runs",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sufficiency", sa.String(32), nullable=False),
        sa.Column("signed_bias_hours", sa.Float(), nullable=True),
        sa.Column("mae_hours", sa.Float(), nullable=True),
        sa.Column("overrun_rate", sa.Float(), nullable=True),
        sa.Column("interval_coverage", sa.Float(), nullable=True),
        sa.Column("multiplier_median", sa.Float(), nullable=True),
        sa.Column("multiplier_lower", sa.Float(), nullable=True),
        sa.Column("multiplier_upper", sa.Float(), nullable=True),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("sample_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("request_id", "input_snapshot_hash", "cutoff_at", "sufficiency", "created_at"):
        op.create_index(
            f"ix_estimate_calibration_runs_{column}",
            "estimate_calibration_runs",
            [column],
        )
    op.create_index(
        "idx_estimate_calibration_runs_cutoff",
        "estimate_calibration_runs",
        ["cutoff_at", "created_at"],
    )

    op.create_table(
        "estimate_calibration_suggestions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(128),
            sa.ForeignKey("estimate_calibration_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("project_name", sa.String(300), nullable=False),
        sa.Column("original_estimated_hours", sa.Float(), nullable=False),
        sa.Column("suggested_hours", sa.Float(), nullable=False),
        sa.Column("lower_hours", sa.Float(), nullable=False),
        sa.Column("upper_hours", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("sample_start_at", sa.DateTime(), nullable=False),
        sa.Column("sample_end_at", sa.DateTime(), nullable=False),
        sa.Column("basis_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("invalidation_conditions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("adopted_hours", sa.Float(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "project_id", name="uq_estimate_calibration_run_project"),
    )
    for column in ("run_id", "project_id", "sample_start_at", "sample_end_at", "status", "created_at"):
        op.create_index(
            f"ix_estimate_calibration_suggestions_{column}",
            "estimate_calibration_suggestions",
            [column],
        )
    op.create_index(
        "idx_estimate_calibration_suggestions_project_created",
        "estimate_calibration_suggestions",
        ["project_id", "created_at"],
    )

    op.create_table(
        "estimate_calibration_decisions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "suggestion_id",
            sa.String(128),
            sa.ForeignKey("estimate_calibration_suggestions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("resulting_revision", sa.Integer(), nullable=False),
        sa.Column("adopted_hours", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("suggestion_id", "project_id", "request_id", "action", "created_at"):
        op.create_index(
            f"ix_estimate_calibration_decisions_{column}",
            "estimate_calibration_decisions",
            [column],
        )
    op.create_index(
        "idx_estimate_calibration_decisions_suggestion_time",
        "estimate_calibration_decisions",
        ["suggestion_id", "created_at"],
    )

    op.create_table(
        "estimate_calibration_mutation_requests",
        sa.Column("request_id", sa.String(128), primary_key=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_estimate_calibration_mutation_requests_operation",
        "estimate_calibration_mutation_requests",
        ["operation"],
    )
    op.create_index(
        "ix_estimate_calibration_mutation_requests_created_at",
        "estimate_calibration_mutation_requests",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("estimate_calibration_mutation_requests")
    op.drop_table("estimate_calibration_decisions")
    op.drop_table("estimate_calibration_suggestions")
    op.drop_table("estimate_calibration_runs")
    op.drop_table("estimate_calibration_samples")
