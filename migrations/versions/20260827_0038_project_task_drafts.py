"""Add revision-bound blueprint task draft previews.

Revision ID: 20260827_0038
Revises: 20260827_0037
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260827_0038"
down_revision = "20260827_0037"
branch_labels = None
depends_on = None


TASK_COLUMNS = {
    "workspace_key",
    "dependency_task_keys_json",
    "deliverables_json",
    "requirement_version_id",
}
TABLES = {"project_task_draft_previews", "project_task_draft_items"}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "business_tasks" not in tables:
        return
    task_columns = {
        column["name"] for column in inspector.get_columns("business_tasks")
    }.intersection(TASK_COLUMNS)
    existing_tables = tables.intersection(TABLES)
    if task_columns == TASK_COLUMNS and existing_tables == TABLES:
        return
    if (task_columns and task_columns != TASK_COLUMNS) or (
        existing_tables and existing_tables != TABLES
    ) or (existing_tables == TABLES and task_columns != TASK_COLUMNS):
        missing = sorted((TASK_COLUMNS - task_columns) | (TABLES - existing_tables))
        raise RuntimeError(
            "project task draft schema is partial; refusing silent repair; missing: "
            + ", ".join(missing)
        )
    if task_columns != TASK_COLUMNS:
        op.add_column("business_tasks", sa.Column("workspace_key", sa.String(128), nullable=True))
        op.add_column(
            "business_tasks",
            sa.Column("dependency_task_keys_json", sa.Text(), nullable=False, server_default="[]"),
        )
        op.add_column(
            "business_tasks",
            sa.Column("deliverables_json", sa.Text(), nullable=False, server_default="[]"),
        )
        op.add_column(
            "business_tasks",
            sa.Column("requirement_version_id", sa.Integer(), nullable=True),
        )
        op.create_index("ix_business_tasks_workspace_key", "business_tasks", ["workspace_key"])
        op.create_index(
            "ix_business_tasks_requirement_version_id",
            "business_tasks",
            ["requirement_version_id"],
        )

    op.create_table(
        "project_task_draft_previews",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("requirement_version_id", sa.Integer(), nullable=False),
        sa.Column("project_revision", sa.Integer(), nullable=False),
        sa.Column("blueprint_hash", sa.String(64), nullable=False),
        sa.Column("preview_token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["business_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_version_id"], ["requirement_document_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_project_task_draft_previews_project_id", "project_task_draft_previews", ["project_id"])
    op.create_index("ix_project_task_draft_previews_requirement_version_id", "project_task_draft_previews", ["requirement_version_id"])
    op.create_index("ix_project_task_draft_previews_project_revision", "project_task_draft_previews", ["project_revision"])
    op.create_index("ix_project_task_draft_previews_status", "project_task_draft_previews", ["status"])
    op.create_index("ix_project_task_draft_previews_created_at", "project_task_draft_previews", ["created_at"])
    op.create_index("ix_project_task_draft_previews_expires_at", "project_task_draft_previews", ["expires_at"])

    op.create_table(
        "project_task_draft_items",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("preview_id", sa.String(128), nullable=False),
        sa.Column("task_key", sa.String(128), nullable=False),
        sa.Column("workspace_key", sa.String(128), nullable=False, server_default=""),
        sa.Column("stage_key", sa.String(128), nullable=False, server_default=""),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("current_payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("proposed_payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("protected_fields_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("conflict_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["preview_id"], ["project_task_draft_previews.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("preview_id", "task_key", name="uq_task_draft_preview_task_key"),
    )
    op.create_index("ix_project_task_draft_items_preview_id", "project_task_draft_items", ["preview_id"])
    op.create_index("ix_project_task_draft_items_classification", "project_task_draft_items", ["classification"])


def downgrade() -> None:
    op.drop_table("project_task_draft_items")
    op.drop_table("project_task_draft_previews")
    op.drop_index("ix_business_tasks_requirement_version_id", table_name="business_tasks")
    op.drop_index("ix_business_tasks_workspace_key", table_name="business_tasks")
    with op.batch_alter_table("business_tasks") as batch:
        batch.drop_column("requirement_version_id")
        batch.drop_column("deliverables_json")
        batch.drop_column("dependency_task_keys_json")
        batch.drop_column("workspace_key")
