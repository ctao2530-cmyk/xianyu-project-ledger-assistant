"""Add auditable invalidation state for unusable traffic baselines."""

from alembic import op
import sqlalchemy as sa


revision = "20260813_0020"
down_revision = "20260812_0019"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "product_traffic_batches" not in set(inspector.get_table_names()):
        return
    columns = _columns(inspector, "product_traffic_batches")
    if "invalidated_at" not in columns:
        op.add_column(
            "product_traffic_batches",
            sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        )
    if "invalidation_reason" not in columns:
        op.add_column(
            "product_traffic_batches",
            sa.Column("invalidation_reason", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "product_traffic_batches" not in set(inspector.get_table_names()):
        return
    columns = _columns(inspector, "product_traffic_batches")
    if "invalidation_reason" in columns:
        op.drop_column("product_traffic_batches", "invalidation_reason")
    if "invalidated_at" in columns:
        op.drop_column("product_traffic_batches", "invalidated_at")
