"""Add explicit factual recording for overlapping traffic batches."""

from alembic import op
import sqlalchemy as sa


revision = "20260812_0019"
down_revision = "20260812_0018"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "product_traffic_batches" not in set(inspector.get_table_names()):
        return
    columns = _columns(inspector, "product_traffic_batches")
    if "recording_mode" not in columns:
        op.add_column(
            "product_traffic_batches",
            sa.Column(
                "recording_mode",
                sa.String(length=32),
                nullable=False,
                server_default="standard",
            ),
        )
    if "attribution_status" not in columns:
        op.add_column(
            "product_traffic_batches",
            sa.Column(
                "attribution_status",
                sa.String(length=32),
                nullable=False,
                server_default="clean",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "product_traffic_batches" not in set(inspector.get_table_names()):
        return
    columns = _columns(inspector, "product_traffic_batches")
    if "attribution_status" in columns:
        op.drop_column("product_traffic_batches", "attribution_status")
    if "recording_mode" in columns:
        op.drop_column("product_traffic_batches", "recording_mode")
