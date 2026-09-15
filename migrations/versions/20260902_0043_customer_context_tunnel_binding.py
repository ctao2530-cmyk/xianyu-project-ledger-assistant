"""Add the single active ChatGPT tunnel-to-grant binding.

Revision ID: 20260902_0043
Revises: 20260902_0042
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_0043"
down_revision = "20260902_0042"
branch_labels = None
depends_on = None


EXPECTED_COLUMNS = {
    "slot",
    "grant_id",
    "revision",
    "created_at",
    "updated_at",
}


def _complete_schema_already_exists() -> bool:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    table = "customer_context_tunnel_bindings"
    if table not in tables:
        return False
    columns = {column["name"] for column in inspector.get_columns(table)}
    missing = sorted(EXPECTED_COLUMNS - columns)
    if missing:
        raise RuntimeError(
            "customer context tunnel schema is incomplete: " + ", ".join(missing)
        )
    primary_key = inspector.get_pk_constraint(table).get("constrained_columns") or []
    if primary_key != ["slot"]:
        raise RuntimeError(
            "customer context tunnel schema is incomplete: slot primary key missing"
        )
    foreign_keys = inspector.get_foreign_keys(table)
    if not any(
        value.get("constrained_columns") == ["grant_id"]
        and value.get("referred_table") == "customer_context_grants"
        and value.get("referred_columns") == ["id"]
        and str((value.get("options") or {}).get("ondelete", "")).upper()
        == "CASCADE"
        for value in foreign_keys
    ):
        raise RuntimeError(
            "customer context tunnel schema is incomplete: grant foreign key missing"
        )
    unique_sets = {
        tuple(value.get("column_names") or [])
        for value in inspector.get_unique_constraints(table)
    }
    unique_sets.update(
        tuple(value.get("column_names") or [])
        for value in inspector.get_indexes(table)
        if value.get("unique")
    )
    if ("grant_id",) not in unique_sets:
        raise RuntimeError(
            "customer context tunnel schema is incomplete: grant uniqueness missing"
        )
    return True


def upgrade() -> None:
    if _complete_schema_already_exists():
        return
    op.create_table(
        "customer_context_tunnel_bindings",
        sa.Column("slot", sa.String(64), primary_key=True),
        sa.Column(
            "grant_id",
            sa.String(128),
            sa.ForeignKey("customer_context_grants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("grant_id", "created_at", "updated_at"):
        op.create_index(
            f"ix_customer_context_tunnel_bindings_{column}",
            "customer_context_tunnel_bindings",
            [column],
        )


def downgrade() -> None:
    op.drop_table("customer_context_tunnel_bindings")
