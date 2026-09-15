"""Bind external OAuth access tokens to approved customer-context grants.

Revision ID: 20260902_0042
Revises: 20260901_0041
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_0042"
down_revision = "20260901_0041"
branch_labels = None
depends_on = None


EXPECTED_COLUMNS = {
    "id",
    "token_hash",
    "grant_id",
    "issuer",
    "audience",
    "subject_hash",
    "client_id_hash",
    "scopes_json",
    "issued_at",
    "expires_at",
    "created_at",
    "last_used_at",
}


def _complete_schema_already_exists() -> bool:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "customer_context_oauth_bindings" not in tables:
        return False
    columns = {
        column["name"]
        for column in inspector.get_columns("customer_context_oauth_bindings")
    }
    missing = sorted(EXPECTED_COLUMNS - columns)
    if missing:
        raise RuntimeError(
            "customer context OAuth schema is incomplete: " + ", ".join(missing)
        )
    return True


def upgrade() -> None:
    if _complete_schema_already_exists():
        return
    op.create_table(
        "customer_context_oauth_bindings",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "grant_id",
            sa.String(128),
            sa.ForeignKey("customer_context_grants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("audience", sa.String(512), nullable=False),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("client_id_hash", sa.String(64), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "token_hash",
        "grant_id",
        "subject_hash",
        "client_id_hash",
        "issued_at",
        "expires_at",
        "created_at",
        "last_used_at",
    ):
        op.create_index(
            f"ix_customer_context_oauth_bindings_{column}",
            "customer_context_oauth_bindings",
            [column],
        )
    op.create_index(
        "idx_customer_context_oauth_binding_grant_expiry",
        "customer_context_oauth_bindings",
        ["grant_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("customer_context_oauth_bindings")
