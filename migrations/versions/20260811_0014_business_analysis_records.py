"""Add persisted business-analysis history and recommendation feedback.

Revision ID: 20260811_0014
Revises: 20260810_0013
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_0014"
down_revision = "20260810_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    analysis_tables = {
        "business_analysis_records",
        "business_analysis_recommendations",
    }
    if analysis_tables.issubset(existing_tables):
        # Local startup uses Base.metadata.create_all before some installations
        # begin tracking Alembic. Treat the already-complete additive schema as
        # migrated instead of attempting to create the same tables twice.
        return
    partial = analysis_tables.intersection(existing_tables)
    if partial:
        raise RuntimeError(
            "business analysis migration found a partial schema: "
            + ", ".join(sorted(partial))
        )
    op.create_table(
        "business_analysis_records",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("snapshot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("ledger_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("analysis_method", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("ai_status", sa.String(length=32), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(
        "ix_business_analysis_records_request_id",
        "business_analysis_records",
        ["request_id"],
        unique=True,
    )
    op.create_index(
        "ix_business_analysis_records_snapshot_hash",
        "business_analysis_records",
        ["snapshot_hash"],
        unique=False,
    )
    op.create_index(
        "ix_business_analysis_records_snapshot_time",
        "business_analysis_records",
        ["snapshot_time"],
        unique=False,
    )
    op.create_index(
        "ix_business_analysis_records_status",
        "business_analysis_records",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_business_analysis_records_ai_status",
        "business_analysis_records",
        ["ai_status"],
        unique=False,
    )
    op.create_index(
        "ix_business_analysis_records_created_at",
        "business_analysis_records",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_business_analysis_status_snapshot",
        "business_analysis_records",
        ["status", "snapshot_time"],
        unique=False,
    )

    op.create_table(
        "business_analysis_recommendations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("analysis_id", sa.String(length=128), nullable=False),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column("entity_label", sa.String(length=300), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("observe_period", sa.String(length=64), nullable=False),
        sa.Column("observe_days", sa.Integer(), nullable=True),
        sa.Column("data_sources_json", sa.Text(), nullable=False),
        sa.Column("evidence_refs_json", sa.Text(), nullable=False),
        sa.Column("target_page", sa.String(length=500), nullable=False),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_request_id", sa.String(length=128), nullable=True),
        sa.Column("user_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["business_analysis_records.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("last_request_id"),
        sa.UniqueConstraint(
            "analysis_id",
            "source_key",
            name="uq_business_analysis_recommendation_source",
        ),
    )
    op.create_index(
        "ix_business_analysis_recommendations_analysis_id",
        "business_analysis_recommendations",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        "ix_business_analysis_recommendations_source_key",
        "business_analysis_recommendations",
        ["source_key"],
        unique=False,
    )
    op.create_index(
        "ix_business_analysis_recommendations_domain",
        "business_analysis_recommendations",
        ["domain"],
        unique=False,
    )
    op.create_index(
        "ix_business_analysis_recommendations_status",
        "business_analysis_recommendations",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_business_analysis_recommendations_last_request_id",
        "business_analysis_recommendations",
        ["last_request_id"],
        unique=False,
    )
    op.create_index(
        "ix_business_analysis_recommendations_created_at",
        "business_analysis_recommendations",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_business_analysis_recommendation_order",
        "business_analysis_recommendations",
        ["analysis_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    # Analysis history is user feedback and audit evidence. Restore a database
    # backup instead of deleting it during an automatic downgrade.
    pass
