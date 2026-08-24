"""Add durable external Codex run, event and task-evidence sync.

Revision ID: 20260817_0027
Revises: 20260817_0026
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260817_0027"
down_revision = "20260817_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "business_tasks" in existing:
        columns = {str(row[1]) for row in bind.exec_driver_sql("PRAGMA table_info(business_tasks)")}
        with op.batch_alter_table("business_tasks") as batch:
            if "codex_execution_status" not in columns:
                batch.add_column(
                    sa.Column(
                        "codex_execution_status",
                        sa.String(32),
                        nullable=False,
                        server_default="todo",
                    )
                )
            if "codex_implemented_at" not in columns:
                batch.add_column(sa.Column("codex_implemented_at", sa.DateTime(), nullable=True))
        op.create_index(
            "ix_business_tasks_codex_execution_status",
            "business_tasks",
            ["codex_execution_status"],
            if_not_exists=True,
        )

    if "codex_runs" not in existing:
        op.create_table(
            "codex_runs",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("binding_id", sa.String(128), sa.ForeignKey("codex_project_bindings.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source", sa.String(32), nullable=False, server_default="mcp"),
            sa.Column("external_session_id", sa.String(255), nullable=False),
            sa.Column("external_turn_id", sa.String(255), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="running"),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("last_event_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("project_id", "source", "external_session_id", name="uq_codex_run_project_source_session"),
        )
        for column in ("project_id", "binding_id", "source", "external_session_id", "status", "started_at", "last_event_at", "created_at"):
            op.create_index(f"ix_codex_runs_{column}", "codex_runs", [column])

    if "codex_events" not in existing:
        op.create_table(
            "codex_events",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("run_id", sa.String(128), sa.ForeignKey("codex_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("request_id", sa.String(128), nullable=False),
            sa.Column("event_id", sa.String(128), nullable=False),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("tool_name", sa.String(128), nullable=False, server_default=""),
            sa.Column("task_key", sa.String(128), nullable=True),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("request_id", name="uq_codex_events_request_id"),
            sa.UniqueConstraint("event_id", name="uq_codex_events_event_id"),
        )
        for column in ("run_id", "request_id", "event_id", "event_type", "task_key", "payload_hash", "occurred_at", "received_at"):
            op.create_index(f"ix_codex_events_{column}", "codex_events", [column])
        op.create_index("idx_codex_events_run_occurred", "codex_events", ["run_id", "occurred_at"])

    if "codex_task_evidence" not in existing:
        op.create_table(
            "codex_task_evidence",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("run_id", sa.String(128), sa.ForeignKey("codex_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_record_id", sa.String(128), sa.ForeignKey("codex_events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.String(128), sa.ForeignKey("business_tasks.id", ondelete="SET NULL"), nullable=True),
            sa.Column("task_key", sa.String(128), nullable=True),
            sa.Column("evidence_type", sa.String(64), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("files_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("remaining_work", sa.Text(), nullable=False, server_default=""),
            sa.Column("blocker", sa.Text(), nullable=False, server_default=""),
            sa.Column("command", sa.Text(), nullable=False, server_default=""),
            sa.Column("exit_code", sa.Integer(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("event_record_id", name="uq_codex_task_evidence_event_record_id"),
        )
        for column in ("project_id", "run_id", "event_record_id", "task_id", "task_key", "evidence_type", "occurred_at", "created_at"):
            op.create_index(f"ix_codex_task_evidence_{column}", "codex_task_evidence", [column])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("codex_task_evidence", "codex_events", "codex_runs"):
        if table in existing:
            op.drop_table(table)
    if "business_tasks" in existing:
        op.drop_index(
            "ix_business_tasks_codex_execution_status",
            table_name="business_tasks",
            if_exists=True,
        )
        with op.batch_alter_table("business_tasks") as batch:
            batch.drop_column("codex_implemented_at")
            batch.drop_column("codex_execution_status")
