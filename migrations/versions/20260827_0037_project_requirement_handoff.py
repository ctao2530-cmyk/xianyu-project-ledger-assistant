"""Attach imported requirement blueprints to projects.

Revision ID: 20260827_0037
Revises: 20260820_0036
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260827_0037"
down_revision = "20260820_0036"
branch_labels = None
depends_on = None


COLUMNS = {
    "project_id",
    "source_filename",
    "source_sha256",
    "import_metadata_json",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "requirement_document_versions" not in inspector.get_table_names():
        return
    present = {
        column["name"] for column in inspector.get_columns("requirement_document_versions")
    }.intersection(COLUMNS)
    if present == COLUMNS:
        return
    if present:
        raise RuntimeError(
            "project requirement handoff schema is partial; refusing silent repair; missing columns: "
            + ", ".join(sorted(COLUMNS - present))
        )
    op.add_column(
        "requirement_document_versions",
        sa.Column("project_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "requirement_document_versions",
        sa.Column("source_filename", sa.String(255), nullable=False, server_default=""),
    )
    op.add_column(
        "requirement_document_versions",
        sa.Column("source_sha256", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "requirement_document_versions",
        sa.Column("import_metadata_json", sa.Text(), nullable=False, server_default="{}"),
    )
    with op.batch_alter_table("requirement_document_versions") as batch:
        batch.alter_column(
            "conversation_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
    op.create_index(
        "ix_requirement_document_versions_project_id",
        "requirement_document_versions",
        ["project_id"],
    )
    op.create_index(
        "ix_requirement_document_versions_source_sha256",
        "requirement_document_versions",
        ["source_sha256"],
    )
    op.create_index(
        "uq_requirement_project_version_partial",
        "requirement_document_versions",
        ["project_id", "version"],
        unique=True,
        sqlite_where=sa.text("project_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_requirement_project_version_partial", table_name="requirement_document_versions")
    op.drop_index("ix_requirement_document_versions_source_sha256", table_name="requirement_document_versions")
    op.drop_index("ix_requirement_document_versions_project_id", table_name="requirement_document_versions")
    with op.batch_alter_table("requirement_document_versions") as batch:
        batch.drop_column("import_metadata_json")
        batch.drop_column("source_sha256")
        batch.drop_column("source_filename")
        batch.drop_column("project_id")
