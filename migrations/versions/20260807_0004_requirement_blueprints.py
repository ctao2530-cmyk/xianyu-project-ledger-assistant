"""Add customer requirement cases, GPT imports and lead analysis.

Revision ID: 20260807_0004
Revises: 20260806_0003
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.app.schema_migrations import (
    backfill_requirement_cases,
    migrate_requirement_blueprint_schema,
)


revision = "20260807_0004"
down_revision = "20260806_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "requirement_cases" not in tables:
        op.create_table(
            "requirement_cases",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("customer_id", sa.String(128), sa.ForeignKey("business_customers.id"), nullable=False),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("current_version", sa.Integer(), nullable=False),
            sa.Column("lead_id", sa.String(128), sa.ForeignKey("sales_leads.id"), nullable=True),
            sa.Column("project_id", sa.String(128), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_requirement_cases_customer_id", "requirement_cases", ["customer_id"])
        op.create_index("ix_requirement_cases_status", "requirement_cases", ["status"])
    if "requirement_case_sources" not in tables:
        op.create_table(
            "requirement_case_sources",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("case_id", sa.String(128), sa.ForeignKey("requirement_cases.id"), nullable=False),
            sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False),
            sa.Column("last_exported_message_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("case_id", "conversation_id", name="uq_requirement_case_source"),
        )
        op.create_index("ix_requirement_case_sources_case_id", "requirement_case_sources", ["case_id"])
        op.create_index("ix_requirement_case_sources_conversation_id", "requirement_case_sources", ["conversation_id"])
    if "lead_analysis_runs" not in tables:
        op.create_table(
            "lead_analysis_runs",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False),
            sa.Column("provider", sa.String(64), nullable=False),
            sa.Column("model", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("structured_json", sa.Text(), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_lead_analysis_runs_conversation_id", "lead_analysis_runs", ["conversation_id"])
    task_columns = {column["name"] for column in inspector.get_columns("ai_generation_tasks")} if "ai_generation_tasks" in tables else set()
    if "ai_generation_tasks" in tables and "model" not in task_columns:
        op.add_column("ai_generation_tasks", sa.Column("model", sa.String(128), nullable=True))
    if bind.dialect.name == "sqlite":
        migrate_requirement_blueprint_schema(bind)
        backfill_requirement_cases(bind)
    else:
        with op.batch_alter_table("requirement_document_versions") as batch:
            batch.alter_column("conversation_id", existing_type=sa.Integer(), nullable=True)
            batch.add_column(sa.Column("case_id", sa.String(128), nullable=True))
            batch.add_column(sa.Column("schema_version", sa.String(16), server_default="1.0", nullable=False))
            batch.add_column(sa.Column("source_type", sa.String(32), server_default="codex_cli", nullable=False))
            batch.add_column(sa.Column("source_label", sa.String(255), server_default="Codex 生成", nullable=False))
            batch.add_column(sa.Column("imported_at", sa.DateTime(), nullable=True))
            batch.create_foreign_key("fk_requirement_versions_case", "requirement_cases", ["case_id"], ["id"])
            batch.create_unique_constraint("uq_requirement_case_version", ["case_id", "version"])


def downgrade() -> None:
    # Imported requirement versions are durable business data.  A destructive
    # downgrade is intentionally not automated.
    pass
