"""Add opaque per-ChatGPT-thread customer context bindings.

Revision ID: 20260903_0044
Revises: 20260902_0043
"""

from alembic import op
import sqlalchemy as sa


revision = "20260903_0044"
down_revision = "20260902_0043"
branch_labels = None
depends_on = None


EXPECTED_COLUMNS = {
    "id",
    "context_key_hash",
    "context_key_hint",
    "grant_id",
    "auth_mode",
    "owner_issuer",
    "owner_subject_hash",
    "owner_client_id_hash",
    "status",
    "revision",
    "expires_at",
    "revoked_at",
    "last_used_at",
    "created_at",
    "updated_at",
}


def _complete_schema_already_exists() -> bool:
    inspector = sa.inspect(op.get_bind())
    table = "customer_context_thread_bindings"
    if table not in set(inspector.get_table_names()):
        return False
    columns = {column["name"] for column in inspector.get_columns(table)}
    missing = sorted(EXPECTED_COLUMNS - columns)
    if missing:
        raise RuntimeError(
            "customer context thread binding schema is incomplete: "
            + ", ".join(missing)
        )
    if (inspector.get_pk_constraint(table).get("constrained_columns") or []) != ["id"]:
        raise RuntimeError(
            "customer context thread binding schema is incomplete: id primary key missing"
        )
    if not any(
        value.get("constrained_columns") == ["grant_id"]
        and value.get("referred_table") == "customer_context_grants"
        and value.get("referred_columns") == ["id"]
        and str((value.get("options") or {}).get("ondelete", "")).upper()
        == "CASCADE"
        for value in inspector.get_foreign_keys(table)
    ):
        raise RuntimeError(
            "customer context thread binding schema is incomplete: grant foreign key missing"
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
    for required in (("context_key_hash",), ("grant_id",)):
        if required not in unique_sets:
            raise RuntimeError(
                "customer context thread binding schema is incomplete: "
                + required[0]
                + " uniqueness missing"
            )
    return True


def upgrade() -> None:
    if _complete_schema_already_exists():
        return
    op.create_table(
        "customer_context_thread_bindings",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("context_key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("context_key_hint", sa.String(16), nullable=False, server_default=""),
        sa.Column(
            "grant_id",
            sa.String(128),
            sa.ForeignKey("customer_context_grants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("auth_mode", sa.String(32), nullable=False),
        sa.Column("owner_issuer", sa.String(512), nullable=True),
        sa.Column("owner_subject_hash", sa.String(64), nullable=True),
        sa.Column("owner_client_id_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "context_key_hash",
        "grant_id",
        "auth_mode",
        "owner_subject_hash",
        "owner_client_id_hash",
        "status",
        "expires_at",
        "last_used_at",
        "created_at",
        "updated_at",
    ):
        op.create_index(
            f"ix_customer_context_thread_bindings_{column}",
            "customer_context_thread_bindings",
            [column],
        )
    op.create_index(
        "idx_customer_context_thread_binding_mode_status_expiry",
        "customer_context_thread_bindings",
        ["auth_mode", "status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("customer_context_thread_bindings")
