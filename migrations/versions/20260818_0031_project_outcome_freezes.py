"""Add evidence-backed manual acceptance scope and immutable outcome freezes.

Revision ID: 20260818_0031
Revises: 20260818_0030
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260818_0031"
down_revision = "20260818_0030"
branch_labels = None
depends_on = None


NEW_TABLES = {
    "project_outcome_freezes",
    "project_outcome_freeze_mutation_requests",
}
EXPECTED_COLUMNS = {
    "project_outcome_freezes": {
        "id", "project_id", "version", "supersedes_freeze_id",
        "source_ledger_revision", "input_hash", "outcome_json",
        "evidence_summary_json", "confirmed_scope_complete",
        "confirmed_time_complete", "confirmation_note", "frozen_at",
        "created_at",
    },
    "project_outcome_freeze_mutation_requests": {
        "request_id", "operation", "payload_hash", "result_json", "created_at",
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    point_columns = (
        {column["name"] for column in inspector.get_columns("codex_acceptance_points")}
        if "codex_acceptance_points" in tables
        else set()
    )
    present_tables = NEW_TABLES.intersection(tables)
    source_present = "source" in point_columns
    complete = present_tables == NEW_TABLES and source_present
    if complete:
        incomplete = {
            table: sorted(columns - {
                column["name"] for column in inspector.get_columns(table)
            })
            for table, columns in EXPECTED_COLUMNS.items()
        }
        incomplete = {table: columns for table, columns in incomplete.items() if columns}
        if incomplete:
            detail = "; ".join(
                f"{table} missing {', '.join(columns)}"
                for table, columns in sorted(incomplete.items())
            )
            raise RuntimeError(
                "project outcome freeze schema is partial; refusing silent repair "
                f"({detail})"
            )
        return
    if present_tables or source_present:
        missing = sorted(NEW_TABLES - present_tables)
        if not source_present:
            missing.append("codex_acceptance_points.source")
        raise RuntimeError(
            "project outcome freeze schema is partial; refusing silent repair "
            f"(missing: {', '.join(missing)})"
        )
    if "codex_acceptance_points" not in tables:
        raise RuntimeError("project outcome freeze schema requires phase 0029")

    op.add_column(
        "codex_acceptance_points",
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default="codex_plan",
        ),
    )
    op.create_index(
        "ix_codex_acceptance_points_source",
        "codex_acceptance_points",
        ["source"],
    )

    op.create_table(
        "project_outcome_freezes",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(128),
            sa.ForeignKey("business_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "supersedes_freeze_id",
            sa.String(128),
            sa.ForeignKey("project_outcome_freezes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_ledger_revision", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("outcome_json", sa.Text(), nullable=False),
        sa.Column("evidence_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "confirmed_scope_complete", sa.Boolean(), nullable=False, server_default="1"
        ),
        sa.Column(
            "confirmed_time_complete", sa.Boolean(), nullable=False, server_default="1"
        ),
        sa.Column("confirmation_note", sa.Text(), nullable=False),
        sa.Column("frozen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "version", name="uq_project_outcome_freeze_version"
        ),
    )
    for column in ("project_id", "supersedes_freeze_id", "input_hash", "frozen_at", "created_at"):
        op.create_index(
            f"ix_project_outcome_freezes_{column}",
            "project_outcome_freezes",
            [column],
        )
    op.create_index(
        "idx_project_outcome_freezes_project_created",
        "project_outcome_freezes",
        ["project_id", "created_at"],
    )

    op.create_table(
        "project_outcome_freeze_mutation_requests",
        sa.Column("request_id", sa.String(128), primary_key=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_project_outcome_freeze_mutation_requests_operation",
        "project_outcome_freeze_mutation_requests",
        ["operation"],
    )
    op.create_index(
        "ix_project_outcome_freeze_mutation_requests_created_at",
        "project_outcome_freeze_mutation_requests",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("project_outcome_freeze_mutation_requests")
    op.drop_table("project_outcome_freezes")
    op.drop_index("ix_codex_acceptance_points_source", table_name="codex_acceptance_points")
    with op.batch_alter_table("codex_acceptance_points") as batch:
        batch.drop_column("source")
