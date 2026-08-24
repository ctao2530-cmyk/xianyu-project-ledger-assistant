"""Add managed Codex runtime, Worktree and approval persistence.

Revision ID: 20260817_0028
Revises: 20260817_0027
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260817_0028"
down_revision = "20260817_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "codex_runs" in existing:
        columns = {str(row[1]) for row in bind.exec_driver_sql("PRAGMA table_info(codex_runs)")}
        additions = (
            ("runtime_type", sa.Column("runtime_type", sa.String(32), nullable=False, server_default="external")),
            ("thread_id", sa.Column("thread_id", sa.String(255), nullable=False, server_default="")),
            ("turn_id", sa.Column("turn_id", sa.String(255), nullable=False, server_default="")),
            ("task_key", sa.Column("task_key", sa.String(128), nullable=True)),
            ("base_commit_sha", sa.Column("base_commit_sha", sa.String(64), nullable=False, server_default="")),
            ("branch", sa.Column("branch", sa.String(255), nullable=False, server_default="")),
            ("worktree_path", sa.Column("worktree_path", sa.Text(), nullable=False, server_default="")),
            ("model", sa.Column("model", sa.String(128), nullable=False, server_default="")),
            ("reasoning_effort", sa.Column("reasoning_effort", sa.String(32), nullable=False, server_default="")),
            ("sandbox_mode", sa.Column("sandbox_mode", sa.String(32), nullable=False, server_default="")),
            ("approval_mode", sa.Column("approval_mode", sa.String(32), nullable=False, server_default="")),
            ("paused_at", sa.Column("paused_at", sa.DateTime(), nullable=True)),
        )
        with op.batch_alter_table("codex_runs") as batch:
            for name, column in additions:
                if name not in columns:
                    batch.add_column(column)
        for column in ("runtime_type", "thread_id", "task_key"):
            op.create_index(f"ix_codex_runs_{column}", "codex_runs", [column], if_not_exists=True)

    if "codex_run_approvals" not in existing:
        op.create_table(
            "codex_run_approvals",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("run_id", sa.String(128), sa.ForeignKey("codex_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("server_request_id", sa.String(255), nullable=False, unique=True),
            sa.Column("thread_id", sa.String(255), nullable=False, server_default=""),
            sa.Column("turn_id", sa.String(255), nullable=False, server_default=""),
            sa.Column("item_id", sa.String(255), nullable=False, server_default=""),
            sa.Column("approval_kind", sa.String(32), nullable=False, server_default="command"),
            sa.Column("risk_level", sa.String(32), nullable=False, server_default="high"),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("command", sa.Text(), nullable=False, server_default=""),
            sa.Column("cwd", sa.Text(), nullable=False, server_default=""),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        for column in ("run_id", "server_request_id", "risk_level", "status", "created_at"):
            op.create_index(f"ix_codex_run_approvals_{column}", "codex_run_approvals", [column])

    if "codex_runtime_mutation_requests" not in existing:
        op.create_table(
            "codex_runtime_mutation_requests",
            sa.Column("request_id", sa.String(128), primary_key=True),
            sa.Column("operation", sa.String(64), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_codex_runtime_mutation_requests_operation", "codex_runtime_mutation_requests", ["operation"])
        op.create_index("ix_codex_runtime_mutation_requests_created_at", "codex_runtime_mutation_requests", ["created_at"])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("codex_runtime_mutation_requests", "codex_run_approvals"):
        if table in existing:
            op.drop_table(table)
    if "codex_runs" in existing:
        with op.batch_alter_table("codex_runs") as batch:
            for column in ("paused_at", "approval_mode", "sandbox_mode", "reasoning_effort", "model", "worktree_path", "branch", "base_commit_sha", "task_key", "turn_id", "thread_id", "runtime_type"):
                batch.drop_column(column)
