"""Add immutable per-batch exposure observation protocol.

Revision ID: 20260819_0032
Revises: 20260818_0031
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260819_0032"
down_revision = "20260818_0031"
branch_labels = None
depends_on = None


def _column_state(bind) -> tuple[bool, bool]:
    inspector = sa.inspect(bind)
    if "product_traffic_batches" not in set(inspector.get_table_names()):
        return False, False
    columns = {
        column["name"]: column
        for column in inspector.get_columns("product_traffic_batches")
    }
    column = columns.get("observation_window_hours")
    if column is None:
        return False, True
    default = str(column.get("default") or "").strip("'\"")
    complete = (
        not bool(column.get("nullable"))
        and isinstance(column.get("type"), sa.Integer)
        and default == "72"
    )
    return complete, True


def upgrade() -> None:
    bind = op.get_bind()
    complete, source_exists = _column_state(bind)
    if complete:
        return
    if not source_exists:
        # Some legacy/synthetic branches legitimately omit the product domain.
        # There is no partial phase-0032 structure to repair in that case.
        return
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("product_traffic_batches")}
    if "observation_window_hours" in columns:
        raise RuntimeError(
            "48h traffic protocol schema is partial; refusing silent repair "
            "(observation_window_hours must be INTEGER NOT NULL DEFAULT 72)"
        )
    op.add_column(
        "product_traffic_batches",
        sa.Column(
            "observation_window_hours",
            sa.Integer(),
            nullable=False,
            server_default="72",
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("product_traffic_batches") as batch:
        batch.drop_column("observation_window_hours")
