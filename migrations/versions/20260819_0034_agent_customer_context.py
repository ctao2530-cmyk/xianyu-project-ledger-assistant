"""Add incremental customer context and persistent image recovery receipts.

Revision ID: 20260819_0034
Revises: 20260819_0033
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260819_0034"
down_revision = "20260819_0033"
branch_labels = None
depends_on = None


NEW_THREAD_COLUMNS = {"context_scope", "conversation_id", "customer_id"}
NEW_RUN_COLUMNS = {"recheck_full_context"}
NEW_TABLE_COLUMNS = {
    "global_agent_conversation_summaries": {
        "id", "conversation_id", "version", "source_run_id",
        "summarized_through_message_id", "message_count", "source_hash",
        "summary_json", "evidence_message_ids_json", "provider", "model",
        "created_at",
    },
    "customer_image_history_recovery_runs": {
        "request_id", "status", "result_json", "started_at", "completed_at",
        "updated_at",
    },
}


def _state(bind) -> tuple[set[str], set[str], set[str], dict[str, set[str]]]:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    thread_columns = (
        {column["name"] for column in inspector.get_columns("global_agent_threads")}
        if "global_agent_threads" in tables
        else set()
    )
    new_columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in NEW_TABLE_COLUMNS
        if table in tables
    }
    run_columns = {
        column["name"] for column in inspector.get_columns("global_agent_runs")
    } if "global_agent_runs" in tables else set()
    return tables, thread_columns, run_columns, new_columns


def upgrade() -> None:
    bind = op.get_bind()
    tables, thread_columns, run_columns, new_columns = _state(bind)
    required_base = {
        "global_agent_threads", "global_agent_runs", "customer_image_archives",
    }
    missing_base = required_base - tables
    if missing_base:
        raise RuntimeError(
            "agent customer context requires phase 0033 and customer image schema: "
            + ", ".join(sorted(missing_base))
        )

    present_tables = set(NEW_TABLE_COLUMNS).intersection(tables)
    present_thread_columns = NEW_THREAD_COLUMNS.intersection(thread_columns)
    present_run_columns = NEW_RUN_COLUMNS.intersection(run_columns)
    complete = (
        present_tables == set(NEW_TABLE_COLUMNS)
        and present_thread_columns == NEW_THREAD_COLUMNS
        and present_run_columns == NEW_RUN_COLUMNS
    )
    if complete:
        incomplete = {
            table: sorted(required - new_columns.get(table, set()))
            for table, required in NEW_TABLE_COLUMNS.items()
            if required - new_columns.get(table, set())
        }
        if incomplete:
            detail = "; ".join(
                f"{table} missing {', '.join(missing)}"
                for table, missing in sorted(incomplete.items())
            )
            raise RuntimeError(
                "agent customer context schema is partial; refusing silent repair "
                + detail
            )
        return
    if present_tables or present_thread_columns or present_run_columns:
        missing_tables = set(NEW_TABLE_COLUMNS) - present_tables
        missing_columns = NEW_THREAD_COLUMNS - present_thread_columns
        missing_run_columns = NEW_RUN_COLUMNS - present_run_columns
        detail = []
        if missing_tables:
            detail.append("tables: " + ", ".join(sorted(missing_tables)))
        if missing_columns:
            detail.append("thread columns: " + ", ".join(sorted(missing_columns)))
        if missing_run_columns:
            detail.append("run columns: " + ", ".join(sorted(missing_run_columns)))
        raise RuntimeError(
            "agent customer context schema is partial; refusing silent repair ("
            + "; ".join(detail)
            + ")"
        )

    op.add_column(
        "global_agent_threads",
        sa.Column(
            "context_scope",
            sa.String(32),
            nullable=False,
            server_default="general_business",
        ),
    )
    # SQLite supports an inline REFERENCES clause on ADD COLUMN, but Alembic's
    # generic add_column path tries to emit the foreign-key constraint as a
    # separate ALTER TABLE statement, which SQLite rejects.  Keep the native
    # SQLite statement aligned with the startup migration while retaining the
    # portable Alembic path for other dialects.
    if bind.dialect.name == "sqlite":
        op.execute(
            "ALTER TABLE global_agent_threads "
            "ADD COLUMN conversation_id INTEGER "
            "REFERENCES conversations(id) ON DELETE SET NULL"
        )
        op.execute(
            "ALTER TABLE global_agent_threads "
            "ADD COLUMN customer_id VARCHAR(128) "
            "REFERENCES business_customers(id) ON DELETE SET NULL"
        )
    else:
        op.add_column(
            "global_agent_threads",
            sa.Column(
                "conversation_id",
                sa.Integer(),
                sa.ForeignKey("conversations.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(
            "global_agent_threads",
            sa.Column(
                "customer_id",
                sa.String(128),
                sa.ForeignKey("business_customers.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    op.create_index(
        "ix_global_agent_threads_context_scope",
        "global_agent_threads",
        ["context_scope"],
    )
    op.create_index(
        "ix_global_agent_threads_conversation_id",
        "global_agent_threads",
        ["conversation_id"],
    )
    op.create_index(
        "ix_global_agent_threads_customer_id",
        "global_agent_threads",
        ["customer_id"],
    )
    op.add_column(
        "global_agent_runs",
        sa.Column(
            "recheck_full_context",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_table(
        "global_agent_conversation_summaries",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "source_run_id",
            sa.String(128),
            sa.ForeignKey("global_agent_runs.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "summarized_through_message_id",
            sa.Integer(),
            sa.ForeignKey("messages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "evidence_message_ids_json", sa.Text(), nullable=False, server_default="[]"
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "conversation_id",
            "version",
            name="uq_global_agent_conversation_summary_version",
        ),
    )
    for column in (
        "conversation_id", "source_run_id", "summarized_through_message_id",
        "source_hash", "created_at",
    ):
        op.create_index(
            f"ix_global_agent_conversation_summaries_{column}",
            "global_agent_conversation_summaries",
            [column],
        )
    op.create_index(
        "idx_global_agent_conversation_summary_latest",
        "global_agent_conversation_summaries",
        ["conversation_id", "version"],
    )

    op.create_table(
        "customer_image_history_recovery_runs",
        sa.Column("request_id", sa.String(128), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_customer_image_history_recovery_runs_status",
        "customer_image_history_recovery_runs",
        ["status"],
    )
    op.create_index(
        "ix_customer_image_history_recovery_runs_started_at",
        "customer_image_history_recovery_runs",
        ["started_at"],
    )


def downgrade() -> None:
    op.drop_table("customer_image_history_recovery_runs")
    op.drop_table("global_agent_conversation_summaries")
    with op.batch_alter_table("global_agent_runs") as batch:
        batch.drop_column("recheck_full_context")
    with op.batch_alter_table("global_agent_threads") as batch:
        batch.drop_column("customer_id")
        batch.drop_column("conversation_id")
        batch.drop_column("context_scope")
