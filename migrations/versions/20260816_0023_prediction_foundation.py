"""Add immutable first-stage business prediction snapshots.

Revision ID: 20260816_0023
Revises: 20260815_0022
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260816_0023"
down_revision = "20260815_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    prediction_tables = {
        "prediction_runs",
        "prediction_results",
        "prediction_evaluations",
    }
    if prediction_tables.issubset(existing_tables):
        return
    partial = prediction_tables.intersection(existing_tables)
    if partial:
        raise RuntimeError(
            "prediction migration found a partial schema: "
            + ", ".join(sorted(partial))
        )

    op.create_table(
        "prediction_runs",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("ledger_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("feature_schema_version", sa.String(32), nullable=False),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_prediction_runs_request_id", "prediction_runs", ["request_id"], unique=True)
    op.create_index("ix_prediction_runs_generated_at", "prediction_runs", ["generated_at"])
    op.create_index("ix_prediction_runs_input_snapshot_hash", "prediction_runs", ["input_snapshot_hash"])
    op.create_index("ix_prediction_runs_status", "prediction_runs", ["status"])
    op.create_index("ix_prediction_runs_created_at", "prediction_runs", ["created_at"])
    op.create_index("idx_prediction_runs_status_generated", "prediction_runs", ["status", "generated_at"])

    op.create_table(
        "prediction_results",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("run_id", sa.String(128), sa.ForeignKey("prediction_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=True),
        sa.Column("entity_label", sa.String(300), nullable=True),
        sa.Column("horizon", sa.String(32), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("horizon_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prediction_value", sa.Float(), nullable=True),
        sa.Column("lower_bound", sa.Float(), nullable=True),
        sa.Column("upper_bound", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(32), nullable=True),
        sa.Column("data_sufficiency", sa.String(16), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("drivers_json", sa.Text(), nullable=False),
        sa.Column("facts_json", sa.Text(), nullable=False),
        sa.Column("evidence_refs_json", sa.Text(), nullable=False),
        sa.Column("input_features_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("run_id", "target", "entity_type", "entity_id", "horizon_start", "horizon_end", "risk_level", "data_sufficiency", "created_at"):
        op.create_index(f"ix_prediction_results_{column}", "prediction_results", [column])
    op.create_index("idx_prediction_results_run_position", "prediction_results", ["run_id", "position"])
    op.create_index("idx_prediction_results_target_entity", "prediction_results", ["target", "entity_type", "entity_id"])

    op.create_table(
        "prediction_evaluations",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("result_id", sa.String(128), sa.ForeignKey("prediction_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actual_value_json", sa.Text(), nullable=False),
        sa.Column("evaluation_method", sa.String(64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_prediction_evaluations_result_id", "prediction_evaluations", ["result_id"])
    op.create_index("ix_prediction_evaluations_request_id", "prediction_evaluations", ["request_id"], unique=True)
    op.create_index("ix_prediction_evaluations_evaluated_at", "prediction_evaluations", ["evaluated_at"])
    op.create_index("ix_prediction_evaluations_created_at", "prediction_evaluations", ["created_at"])
    op.create_index("idx_prediction_evaluations_result_time", "prediction_evaluations", ["result_id", "evaluated_at"])


def downgrade() -> None:
    # Prediction history is user evidence. Restore the verified pre-migration
    # SQLite backup instead of silently deleting it during downgrade.
    pass
