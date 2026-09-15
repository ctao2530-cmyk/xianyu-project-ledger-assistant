"""Add persistent, event-driven OpenAI customer analysis.

Revision ID: 20260901_0041
Revises: 20260901_0040
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901_0041"
down_revision = "20260901_0040"
branch_labels = None
depends_on = None


EXPECTED_COLUMNS = {
    "customer_analysis_threads": {
        "id", "thread_id", "conversation_id", "provider_scope", "model",
        "external_conversation_id", "status", "analysis_state", "include_images",
        "debounce_seconds", "max_wait_seconds", "last_enqueued_message_id",
        "last_analyzed_message_id", "latest_artifact_version", "pending_since",
        "next_run_at", "last_started_at", "last_completed_at", "last_error_code",
        "last_error_message", "consent_policy_version", "consent_text_hash",
        "authorization_note", "confirmed_at", "revision", "paused_at",
        "created_at", "updated_at",
    },
    "customer_analysis_runs": {
        "id", "analysis_thread_id", "subscription_revision", "run_key", "status", "watermark_before",
        "watermark_after", "source_hash", "provider", "model",
        "external_response_id", "artifact_version", "message_count", "image_count",
        "error_code", "error_message", "created_at", "started_at", "completed_at",
    },
    "customer_analysis_events": {
        "id", "analysis_thread_id", "conversation_id", "message_id", "event_key",
        "status", "run_id", "attempt_count", "created_at", "processing_at",
        "completed_at",
    },
    "customer_analysis_artifacts": {
        "id", "analysis_thread_id", "version", "previous_artifact_id", "run_id",
        "watermark_before", "watermark_after", "source_hash", "content_hash",
        "content_json", "diff_json", "evidence_message_ids_json",
        "evidence_image_ids_json", "model", "external_response_id", "created_at",
    },
    "customer_analysis_mutation_requests": {
        "request_id", "operation", "payload_hash", "result_json", "created_at",
    },
}

def _complete_schema_already_exists() -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        from backend.app.schema_migrations import (
            _create_customer_auto_analysis_triggers,
            validate_customer_auto_analysis_schema,
        )

        if validate_customer_auto_analysis_schema(bind, require_triggers=False):
            _create_customer_auto_analysis_triggers(bind)
            validate_customer_auto_analysis_schema(bind)
            return True
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    present = set(EXPECTED_COLUMNS).intersection(tables)
    if not present:
        return False
    if present != set(EXPECTED_COLUMNS):
        missing = sorted(set(EXPECTED_COLUMNS) - present)
        raise RuntimeError(
            "customer auto analysis schema is incomplete: " + ", ".join(missing)
        )
    for table, expected in EXPECTED_COLUMNS.items():
        columns = {column["name"] for column in inspector.get_columns(table)}
        missing = sorted(expected - columns)
        if missing:
            raise RuntimeError(
                "customer auto analysis schema is incomplete: "
                f"{table} missing {', '.join(missing)}"
            )
    return True


def upgrade() -> None:
    if _complete_schema_already_exists():
        return

    op.create_table(
        "customer_analysis_threads",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("thread_id", sa.String(128), sa.ForeignKey("global_agent_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider_scope", sa.String(32), nullable=False, server_default="openai"),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("external_conversation_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("analysis_state", sa.String(32), nullable=False, server_default="waiting"),
        sa.Column("include_images", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("debounce_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_wait_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("last_enqueued_message_id", sa.Integer(), nullable=True),
        sa.Column("last_analyzed_message_id", sa.Integer(), nullable=True),
        sa.Column("latest_artifact_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_since", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("last_error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("consent_policy_version", sa.String(32), nullable=False, server_default="2"),
        sa.Column("consent_text_hash", sa.String(64), nullable=False),
        sa.Column("authorization_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("confirmed_at", sa.DateTime(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("paused_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "thread_id", "conversation_id", "provider_scope", "external_conversation_id",
        "status", "analysis_state", "pending_since", "next_run_at", "last_error_code",
        "consent_text_hash", "confirmed_at", "created_at",
    ):
        op.create_index(
            f"ix_customer_analysis_threads_{column}",
            "customer_analysis_threads",
            [column],
            unique=column in {"thread_id", "conversation_id", "external_conversation_id"},
        )
    op.create_index(
        "idx_customer_analysis_thread_due",
        "customer_analysis_threads",
        ["status", "analysis_state", "next_run_at"],
    )

    op.create_table(
        "customer_analysis_runs",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("analysis_thread_id", sa.String(128), sa.ForeignKey("customer_analysis_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("run_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("watermark_before", sa.Integer(), nullable=True),
        sa.Column("watermark_after", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("provider", sa.String(32), nullable=False, server_default="openai"),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("external_response_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("artifact_version", sa.Integer(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for column in (
        "analysis_thread_id", "run_key", "status", "watermark_after", "provider",
        "external_response_id", "error_code", "created_at",
    ):
        op.create_index(
            f"ix_customer_analysis_runs_{column}",
            "customer_analysis_runs",
            [column],
            unique=column == "run_key",
        )
    op.create_index(
        "idx_customer_analysis_run_thread_created",
        "customer_analysis_runs",
        ["analysis_thread_id", "created_at"],
    )

    op.create_table(
        "customer_analysis_events",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("analysis_thread_id", sa.String(128), sa.ForeignKey("customer_analysis_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("run_id", sa.String(128), sa.ForeignKey("customer_analysis_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("processing_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "analysis_thread_id",
            "message_id",
            name="uq_customer_analysis_event_message",
        ),
    )
    for column in (
        "analysis_thread_id", "conversation_id", "message_id", "event_key", "status",
        "run_id", "created_at",
    ):
        op.create_index(
            f"ix_customer_analysis_events_{column}",
            "customer_analysis_events",
            [column],
            unique=column == "event_key",
        )
    op.create_index(
        "idx_customer_analysis_event_pending",
        "customer_analysis_events",
        ["analysis_thread_id", "status", "message_id"],
    )

    op.create_table(
        "customer_analysis_artifacts",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("analysis_thread_id", sa.String(128), sa.ForeignKey("customer_analysis_threads.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("previous_artifact_id", sa.String(128), sa.ForeignKey("customer_analysis_artifacts.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("run_id", sa.String(128), sa.ForeignKey("customer_analysis_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("watermark_before", sa.Integer(), nullable=True),
        sa.Column("watermark_after", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("diff_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_message_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_image_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("external_response_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("analysis_thread_id", "version", name="uq_customer_analysis_artifact_version"),
    )
    for column in (
        "analysis_thread_id", "previous_artifact_id", "run_id", "watermark_after",
        "source_hash", "content_hash", "created_at",
    ):
        op.create_index(
            f"ix_customer_analysis_artifacts_{column}",
            "customer_analysis_artifacts",
            [column],
            unique=column == "run_id",
        )
    op.create_index(
        "idx_customer_analysis_artifact_latest",
        "customer_analysis_artifacts",
        ["analysis_thread_id", "version"],
    )

    op.create_table(
        "customer_analysis_mutation_requests",
        sa.Column("request_id", sa.String(128), primary_key=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("operation", "payload_hash", "created_at"):
        op.create_index(
            f"ix_customer_analysis_mutation_requests_{column}",
            "customer_analysis_mutation_requests",
            [column],
        )
    if op.get_bind().dialect.name == "sqlite":
        from backend.app.schema_migrations import (
            _create_customer_auto_analysis_triggers,
            validate_customer_auto_analysis_schema,
        )

        _create_customer_auto_analysis_triggers(op.get_bind())
        validate_customer_auto_analysis_schema(op.get_bind())

def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        from backend.app.schema_migrations import CUSTOMER_ANALYSIS_TRIGGER_NAMES

        for trigger in sorted(CUSTOMER_ANALYSIS_TRIGGER_NAMES):
            op.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
    op.drop_table("customer_analysis_mutation_requests")
    op.drop_table("customer_analysis_artifacts")
    op.drop_table("customer_analysis_events")
    op.drop_table("customer_analysis_runs")
    op.drop_table("customer_analysis_threads")
