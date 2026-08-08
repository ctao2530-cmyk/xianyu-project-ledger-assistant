"""Allow customer-free personal projects and persist project kind.

Revision ID: 20260806_0003
Revises: 20260806_0002
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.app.schema_migrations import migrate_personal_project_schema


revision = "20260806_0003"
down_revision = "20260806_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        migrate_personal_project_schema(bind)
        return

    op.alter_column(
        "business_projects",
        "customer_id",
        existing_type=sa.String(length=128),
        nullable=True,
    )
    op.add_column(
        "business_projects",
        sa.Column("project_kind", sa.String(length=32), server_default="client", nullable=False),
    )
    op.create_index(
        "ix_business_projects_project_kind",
        "business_projects",
        ["project_kind"],
    )


def downgrade() -> None:
    # A personal project deliberately has no customer, so changing the column
    # back to NOT NULL would destroy valid data. Only remove the derived kind
    # column when an explicit downgrade is requested.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        columns = {
            str(row[1])
            for row in bind.exec_driver_sql("PRAGMA table_info(business_projects)")
        }
        if "project_kind" in columns:
            with op.batch_alter_table("business_projects") as batch:
                batch.drop_index("ix_business_projects_project_kind")
                batch.drop_column("project_kind")
        return
    op.drop_index("ix_business_projects_project_kind", table_name="business_projects")
    op.drop_column("business_projects", "project_kind")
