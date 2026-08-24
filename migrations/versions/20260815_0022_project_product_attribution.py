"""Bind client projects to an owned source listing."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_0022"
down_revision = "20260814_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "business_projects" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("business_projects")}
    if "item_id" not in columns:
        op.add_column(
            "business_projects",
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=True),
        )
    op.create_index(
        "ix_business_projects_item_id",
        "business_projects",
        ["item_id"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "business_projects" not in tables:
        return
    indexes = {index["name"] for index in inspector.get_indexes("business_projects")}
    if "ix_business_projects_item_id" in indexes:
        op.drop_index("ix_business_projects_item_id", table_name="business_projects")
    columns = {column["name"] for column in inspector.get_columns("business_projects")}
    if "item_id" in columns:
        op.drop_column("business_projects", "item_id")
