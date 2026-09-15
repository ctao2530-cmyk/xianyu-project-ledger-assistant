"""Add isolated customer context grants and sanitized access audit receipts.

Revision ID: 20260901_0040
Revises: 20260828_0039
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901_0040"
down_revision = "20260828_0039"
branch_labels = None
depends_on = None


EXPECTED_COLUMNS = {
    "customer_context_grants": {
        "id", "thread_id", "conversation_id", "provider_scope", "audience",
        "token_hash", "allow_text", "allow_images", "allow_artifacts",
        "allow_new_messages", "consent_policy_version", "consent_text_hash",
        "status", "revision", "authorization_note", "confirmed_at",
        "expires_at", "revoked_at", "created_at", "updated_at",
    },
    "customer_context_access_audits": {
        "id", "request_id", "grant_id", "grant_revision", "thread_id",
        "conversation_id", "provider", "audience", "target_model",
        "tool_name", "requested_scopes_json", "request_hash", "status",
        "summary_version", "watermark_before", "watermark_after",
        "text_message_count", "image_count", "byte_count",
        "resource_hashes_json", "source_hash", "error_code", "duration_ms",
        "created_at", "completed_at",
    },
    "customer_context_mutation_requests": {
        "request_id", "operation", "payload_hash", "result_json", "created_at",
    },
}


def _complete_schema_already_exists() -> bool:
    """Accept startup-created complete metadata, but never mask a partial schema."""

    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    present = set(EXPECTED_COLUMNS).intersection(tables)
    if not present:
        return False
    if present != set(EXPECTED_COLUMNS):
        missing = sorted(set(EXPECTED_COLUMNS) - present)
        raise RuntimeError(
            "customer context gateway schema is incomplete: " + ", ".join(missing)
        )
    for table, expected in EXPECTED_COLUMNS.items():
        columns = {column["name"] for column in inspector.get_columns(table)}
        missing = sorted(expected - columns)
        if missing:
            raise RuntimeError(
                "customer context gateway schema is incomplete: "
                f"{table} missing {', '.join(missing)}"
            )
    return True


def upgrade() -> None:
    if _complete_schema_already_exists():
        return
    op.create_table(
        "customer_context_grants",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "thread_id",
            sa.String(128),
            sa.ForeignKey("global_agent_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_scope", sa.String(32), nullable=False, server_default="openai"),
        sa.Column("audience", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("allow_text", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_images", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allow_artifacts", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_new_messages", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("consent_policy_version", sa.String(32), nullable=False, server_default="1"),
        sa.Column("consent_text_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("authorization_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("confirmed_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "thread_id",
        "conversation_id",
        "provider_scope",
        "audience",
        "token_hash",
        "consent_text_hash",
        "status",
        "expires_at",
        "confirmed_at",
        "created_at",
    ):
        op.create_index(
            f"ix_customer_context_grants_{column}",
            "customer_context_grants",
            [column],
        )
    op.create_index(
        "idx_customer_context_grants_thread_status",
        "customer_context_grants",
        ["thread_id", "status"],
    )

    op.create_table(
        "customer_context_access_audits",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "grant_id",
            sa.String(128),
            sa.ForeignKey("customer_context_grants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("grant_revision", sa.Integer(), nullable=True),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False, server_default="openai"),
        sa.Column("audience", sa.String(32), nullable=False, server_default=""),
        sa.Column("target_model", sa.String(128), nullable=False, server_default=""),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("requested_scopes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("request_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary_version", sa.Integer(), nullable=True),
        sa.Column("watermark_before", sa.Integer(), nullable=True),
        sa.Column("watermark_after", sa.Integer(), nullable=True),
        sa.Column("text_message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("byte_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resource_hashes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("source_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("error_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for column in (
        "request_id",
        "grant_id",
        "audience",
        "thread_id",
        "conversation_id",
        "provider",
        "tool_name",
        "request_hash",
        "status",
        "source_hash",
        "error_code",
        "created_at",
    ):
        op.create_index(
            f"ix_customer_context_access_audits_{column}",
            "customer_context_access_audits",
            [column],
        )
    op.create_index(
        "idx_customer_context_access_thread_created",
        "customer_context_access_audits",
        ["thread_id", "created_at"],
    )

    op.create_table(
        "customer_context_mutation_requests",
        sa.Column("request_id", sa.String(128), primary_key=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("operation", "payload_hash", "created_at"):
        op.create_index(
            f"ix_customer_context_mutation_requests_{column}",
            "customer_context_mutation_requests",
            [column],
        )


def downgrade() -> None:
    op.drop_table("customer_context_mutation_requests")
    op.drop_table("customer_context_access_audits")
    op.drop_table("customer_context_grants")
