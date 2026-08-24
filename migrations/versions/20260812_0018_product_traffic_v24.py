"""Add traffic-batch v2.4 baselines, plan linkage, and audit events."""

from alembic import op
import sqlalchemy as sa


revision = "20260812_0018"
down_revision = "20260812_0017"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "product_traffic_batches" in tables:
        columns = _columns(inspector, "product_traffic_batches")
        if "baseline_prepared_at" not in columns:
            op.add_column(
                "product_traffic_batches",
                sa.Column("baseline_prepared_at", sa.DateTime(), nullable=True),
            )
    if "product_traffic_batch_items" in tables:
        columns = _columns(inspector, "product_traffic_batch_items")
        if "baseline_source" not in columns:
            op.add_column(
                "product_traffic_batch_items",
                sa.Column(
                    "baseline_source",
                    sa.String(length=32),
                    nullable=False,
                    server_default="legacy_snapshot",
                ),
            )
    if "product_operating_plan_slots" in tables:
        columns = _columns(inspector, "product_operating_plan_slots")
        additions = (
            ("source_batch_id", sa.String(length=128), True, None),
            ("availability_at", sa.DateTime(), True, None),
            ("is_new_spend", sa.Boolean(), False, sa.false()),
            ("rotation_summary_json", sa.Text(), False, "{}"),
        )
        for name, column_type, nullable, default in additions:
            if name not in columns:
                op.add_column(
                    "product_operating_plan_slots",
                    sa.Column(
                        name,
                        column_type,
                        nullable=nullable,
                        server_default=default,
                    ),
                )
        op.create_index(
            "ix_product_operating_plan_slots_source_batch_id",
            "product_operating_plan_slots",
            ["source_batch_id"],
            unique=False,
            if_not_exists=True,
        )
    if "product_traffic_batch_events" not in tables:
        op.create_table(
            "product_traffic_batch_events",
            sa.Column("id", sa.String(length=128), nullable=False),
            sa.Column("batch_id", sa.String(length=128), nullable=False),
            sa.Column("request_id", sa.String(length=128), nullable=False),
            sa.Column("event_type", sa.String(length=32), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["batch_id"], ["product_traffic_batches.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("request_id"),
        )
        op.create_index(
            "ix_product_traffic_batch_events_batch_id",
            "product_traffic_batch_events",
            ["batch_id"],
            unique=False,
        )
        op.create_index(
            "ix_product_traffic_batch_events_event_type",
            "product_traffic_batch_events",
            ["event_type"],
            unique=False,
        )
        op.create_index(
            "ix_product_traffic_batch_events_request_id",
            "product_traffic_batch_events",
            ["request_id"],
            unique=True,
        )
        op.create_index(
            "idx_product_traffic_batch_events_batch_created",
            "product_traffic_batch_events",
            ["batch_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "product_traffic_batch_events" in tables:
        op.drop_table("product_traffic_batch_events")
    if "product_operating_plan_slots" in tables:
        columns = _columns(inspector, "product_operating_plan_slots")
        indexes = {
            index["name"] for index in inspector.get_indexes("product_operating_plan_slots")
        }
        if "ix_product_operating_plan_slots_source_batch_id" in indexes:
            op.drop_index(
                "ix_product_operating_plan_slots_source_batch_id",
                table_name="product_operating_plan_slots",
            )
        for name in (
            "rotation_summary_json",
            "is_new_spend",
            "availability_at",
            "source_batch_id",
        ):
            if name in columns:
                op.drop_column("product_operating_plan_slots", name)
    if "product_traffic_batch_items" in tables:
        columns = _columns(inspector, "product_traffic_batch_items")
        if "baseline_source" in columns:
            op.drop_column("product_traffic_batch_items", "baseline_source")
    if "product_traffic_batches" in tables:
        columns = _columns(inspector, "product_traffic_batches")
        if "baseline_prepared_at" in columns:
            op.drop_column("product_traffic_batches", "baseline_prepared_at")
