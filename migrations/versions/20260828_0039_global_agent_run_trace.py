"""Add persisted redacted global Agent run steps.

Revision ID: 20260828_0039
Revises: 20260827_0038
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260828_0039"
down_revision = "20260827_0038"
branch_labels = None
depends_on = None


REQUIRED_COLUMNS = {
    "id",
    "run_id",
    "position",
    "node_name",
    "status",
    "summary",
    "detail_json",
    "duration_ms",
    "started_at",
    "completed_at",
    "created_at",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "global_agent_runs" not in tables:
        return
    if "global_agent_run_steps" in tables:
        columns = {
            column["name"]
            for column in inspector.get_columns("global_agent_run_steps")
        }
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise RuntimeError(
                "global Agent run trace schema is partial; refusing silent repair; "
                "missing: " + ", ".join(sorted(missing))
            )
        return

    op.create_table(
        "global_agent_run_steps",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("summary", sa.String(500), nullable=False, server_default=""),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["global_agent_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "run_id", "position", name="uq_global_agent_run_step_position"
        ),
    )
    op.create_index(
        "ix_global_agent_run_steps_run_id",
        "global_agent_run_steps",
        ["run_id"],
    )
    op.create_index(
        "ix_global_agent_run_steps_node_name",
        "global_agent_run_steps",
        ["node_name"],
    )
    op.create_index(
        "ix_global_agent_run_steps_status",
        "global_agent_run_steps",
        ["status"],
    )
    op.create_index(
        "ix_global_agent_run_steps_created_at",
        "global_agent_run_steps",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("global_agent_run_steps")
