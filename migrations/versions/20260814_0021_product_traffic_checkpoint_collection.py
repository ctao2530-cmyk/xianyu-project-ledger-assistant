"""Add persistent automatic checkpoint collection jobs."""

from alembic import op
import sqlalchemy as sa


revision = "20260814_0021"
down_revision = "20260813_0020"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "product_traffic_batches" in tables:
        columns = _columns(inspector, "product_traffic_batches")
        if "checkpoint_collection_mode" not in columns:
            op.add_column(
                "product_traffic_batches",
                sa.Column(
                    "checkpoint_collection_mode",
                    sa.String(length=32),
                    nullable=False,
                    server_default="auto",
                ),
            )
        op.create_index(
            "ix_product_traffic_batches_checkpoint_collection_mode",
            "product_traffic_batches",
            ["checkpoint_collection_mode"],
            unique=False,
            if_not_exists=True,
        )
    if "product_traffic_checkpoint_jobs" not in tables:
        op.create_table(
            "product_traffic_checkpoint_jobs",
            sa.Column("id", sa.String(length=128), nullable=False),
            sa.Column("batch_id", sa.String(length=128), nullable=False),
            sa.Column("checkpoint", sa.String(length=16), nullable=False),
            sa.Column("scheduled_for", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="scheduled"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("collected_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("captured_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("capture_delay_minutes", sa.Integer(), nullable=True),
            sa.Column("last_error_code", sa.String(length=64), nullable=True),
            sa.Column("last_error_detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["batch_id"], ["product_traffic_batches.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("batch_id", "checkpoint", name="uq_product_traffic_checkpoint_job"),
        )
        op.create_index("ix_product_traffic_checkpoint_jobs_batch_id", "product_traffic_checkpoint_jobs", ["batch_id"])
        op.create_index("ix_product_traffic_checkpoint_jobs_checkpoint", "product_traffic_checkpoint_jobs", ["checkpoint"])
        op.create_index("ix_product_traffic_checkpoint_jobs_scheduled_for", "product_traffic_checkpoint_jobs", ["scheduled_for"])
        op.create_index("ix_product_traffic_checkpoint_jobs_status", "product_traffic_checkpoint_jobs", ["status"])
        op.create_index("idx_product_traffic_checkpoint_jobs_due", "product_traffic_checkpoint_jobs", ["status", "scheduled_for"])
    if "product_traffic_checkpoint_job_items" not in tables:
        op.create_table(
            "product_traffic_checkpoint_job_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.String(length=128), nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("captured_at", sa.DateTime(), nullable=True),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("error_detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
            sa.ForeignKeyConstraint(["job_id"], ["product_traffic_checkpoint_jobs.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("job_id", "item_id", name="uq_product_traffic_checkpoint_job_item"),
        )
        op.create_index("ix_product_traffic_checkpoint_job_items_item_id", "product_traffic_checkpoint_job_items", ["item_id"])
        op.create_index("ix_product_traffic_checkpoint_job_items_job_id", "product_traffic_checkpoint_job_items", ["job_id"])
        op.create_index("ix_product_traffic_checkpoint_job_items_status", "product_traffic_checkpoint_job_items", ["status"])
        op.create_index("idx_product_traffic_checkpoint_job_items_status", "product_traffic_checkpoint_job_items", ["job_id", "status"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "product_traffic_checkpoint_job_items" in tables:
        op.drop_table("product_traffic_checkpoint_job_items")
    if "product_traffic_checkpoint_jobs" in tables:
        op.drop_table("product_traffic_checkpoint_jobs")
    if "product_traffic_batches" in tables:
        columns = _columns(inspector, "product_traffic_batches")
        indexes = {index["name"] for index in inspector.get_indexes("product_traffic_batches")}
        if "ix_product_traffic_batches_checkpoint_collection_mode" in indexes:
            op.drop_index("ix_product_traffic_batches_checkpoint_collection_mode", table_name="product_traffic_batches")
        if "checkpoint_collection_mode" in columns:
            op.drop_column("product_traffic_batches", "checkpoint_collection_mode")
