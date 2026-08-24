"""Add local global Agent, auditable tools, and approved knowledge RAG.

Revision ID: 20260819_0033
Revises: 20260819_0032
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260819_0033"
down_revision = "20260819_0032"
branch_labels = None
depends_on = None


TABLES = {
    "global_agent_model_profiles",
    "global_agent_threads",
    "global_agent_messages",
    "global_agent_runs",
    "global_agent_tool_calls",
    "global_agent_knowledge_documents",
    "global_agent_knowledge_chunks",
    "global_agent_mutation_requests",
    "global_agent_knowledge_fts",
}

EXPECTED_COLUMNS = {
    "global_agent_model_profiles": {
        "id", "provider", "model", "reasoning_effort", "label", "enabled",
        "is_default", "revision", "created_at", "updated_at",
    },
    "global_agent_threads": {
        "id", "title", "profile_id", "provider", "model", "reasoning_effort",
        "status", "revision", "created_at", "updated_at",
    },
    "global_agent_messages": {
        "id", "thread_id", "role", "content", "status", "run_id",
        "citations_json", "tool_refs_json", "created_at",
    },
    "global_agent_runs": {
        "id", "request_id", "thread_id", "user_message_id",
        "assistant_message_id", "provider", "model", "reasoning_effort",
        "status", "input_hash", "error_code", "error_message", "started_at",
        "completed_at", "created_at",
    },
    "global_agent_tool_calls": {
        "id", "run_id", "position", "tool_name", "arguments_json",
        "result_json", "status", "duration_ms", "created_at",
    },
    "global_agent_knowledge_documents": {
        "id", "relative_path", "absolute_path", "title", "maturity",
        "content_hash", "active", "exclusion_reason", "indexed_at",
        "created_at", "updated_at",
    },
    "global_agent_knowledge_chunks": {
        "id", "document_id", "ordinal", "heading", "content", "content_hash",
        "created_at",
    },
    "global_agent_mutation_requests": {
        "request_id", "operation", "payload_hash", "result_json", "created_at",
    },
    "global_agent_knowledge_fts": {"chunk_id", "heading", "content"},
}


def _inspect_state(bind) -> tuple[set[str], dict[str, set[str]]]:
    inspector = sa.inspect(bind)
    present = TABLES.intersection(inspector.get_table_names())
    columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in present
    }
    return present, columns


def upgrade() -> None:
    bind = op.get_bind()
    present, columns = _inspect_state(bind)
    if present == TABLES:
        incomplete = {
            table: sorted(EXPECTED_COLUMNS[table] - columns.get(table, set()))
            for table in TABLES
            if EXPECTED_COLUMNS[table] - columns.get(table, set())
        }
        if incomplete:
            detail = "; ".join(
                f"{table} missing {', '.join(missing)}"
                for table, missing in sorted(incomplete.items())
            )
            raise RuntimeError(
                "global Agent schema is partial; refusing silent repair " + detail
            )
        return
    if present:
        raise RuntimeError(
            "global Agent schema is partial; refusing silent repair (missing: "
            + ", ".join(sorted(TABLES - present))
            + ")"
        )

    op.create_table(
        "global_agent_model_profiles",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("reasoning_effort", sa.String(32), nullable=False, server_default=""),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "provider", "model", "reasoning_effort",
            name="uq_global_agent_model_profile_choice",
        ),
    )
    op.create_table(
        "global_agent_threads",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "profile_id", sa.String(128),
            sa.ForeignKey("global_agent_model_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(240), nullable=False, server_default="新对话"),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("reasoning_effort", sa.String(32), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "global_agent_messages",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "thread_id", sa.String(128),
            sa.ForeignKey("global_agent_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("run_id", sa.String(128), nullable=True),
        sa.Column("citations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("tool_refs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "global_agent_runs",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "thread_id", sa.String(128),
            sa.ForeignKey("global_agent_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_message_id", sa.String(128),
            sa.ForeignKey("global_agent_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assistant_message_id", sa.String(128),
            sa.ForeignKey("global_agent_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("reasoning_effort", sa.String(32), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "global_agent_tool_calls",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "run_id", sa.String(128),
            sa.ForeignKey("global_agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("arguments_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "run_id", "position", name="uq_global_agent_tool_call_position"
        ),
    )
    op.create_table(
        "global_agent_knowledge_documents",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("relative_path", sa.String(1000), nullable=False, unique=True),
        sa.Column("absolute_path", sa.String(2000), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("maturity", sa.String(32), nullable=False, server_default="candidate"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("exclusion_reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("indexed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "global_agent_knowledge_chunks",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "document_id", sa.String(128),
            sa.ForeignKey("global_agent_knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(500), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "document_id", "ordinal", name="uq_global_agent_knowledge_chunk_order"
        ),
    )
    op.create_table(
        "global_agent_mutation_requests",
        sa.Column("request_id", sa.String(128), primary_key=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.execute(
        "CREATE VIRTUAL TABLE global_agent_knowledge_fts USING fts5("
        "chunk_id UNINDEXED, heading, content, tokenize='trigram')"
    )

    for table, columns in {
        "global_agent_model_profiles": ("provider", "enabled", "is_default"),
        "global_agent_threads": ("profile_id", "status", "created_at"),
        "global_agent_messages": ("thread_id", "status", "run_id", "created_at"),
        "global_agent_runs": ("thread_id", "status", "created_at", "request_id"),
        "global_agent_tool_calls": ("run_id", "tool_name", "created_at"),
        "global_agent_knowledge_documents": ("active", "maturity", "indexed_at"),
        "global_agent_knowledge_chunks": ("document_id", "content_hash"),
        "global_agent_mutation_requests": ("operation", "created_at"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_index(
        "idx_global_agent_messages_thread_created",
        "global_agent_messages",
        ["thread_id", "created_at"],
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS global_agent_knowledge_fts")
    op.drop_table("global_agent_mutation_requests")
    op.drop_table("global_agent_knowledge_chunks")
    op.drop_table("global_agent_knowledge_documents")
    op.drop_table("global_agent_tool_calls")
    op.drop_table("global_agent_runs")
    op.drop_table("global_agent_messages")
    op.drop_table("global_agent_threads")
    op.drop_table("global_agent_model_profiles")
