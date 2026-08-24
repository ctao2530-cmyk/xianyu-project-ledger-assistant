"""Add structured product operating-plan explanation fields."""

from alembic import op
import sqlalchemy as sa


revision = "20260812_0017"
down_revision = "20260811_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table in ("product_operating_plans", "product_operating_plan_slots"):
        if table not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "change_factors_json" in columns:
            continue
        op.add_column(
            table,
            sa.Column(
                "change_factors_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table in ("product_operating_plan_slots", "product_operating_plans"):
        if table not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "change_factors_json" in columns:
            op.drop_column(table, "change_factors_json")
