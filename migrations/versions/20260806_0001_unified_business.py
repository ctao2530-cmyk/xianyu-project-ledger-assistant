"""Add unified ledger, CRM, lead, quote and project tables.

Revision ID: 20260806_0001
Revises:
"""
from __future__ import annotations

from alembic import op

from backend.app.database import Base
from backend.app import models  # noqa: F401


revision = "20260806_0001"
down_revision = None
branch_labels = None
depends_on = None


NEW_TABLES = (
    "requirement_quote_links",
    "quote_proposals",
    "customer_channel_identities",
    "attachment_metadata",
    "project_development_logs",
    "business_expenses",
    "payment_nodes",
    "business_tasks",
    "business_projects",
    "sales_leads",
    "business_customers",
    "business_settings",
    "ledger_state",
)


def upgrade() -> None:
    # This first migration upgrades a mature pre-existing reply database. Using
    # SQLAlchemy metadata here is intentionally additive: existing message,
    # draft and requirement tables are never recreated or altered.  Restrict
    # creation to the tables owned by this revision; using the entire *current*
    # metadata would accidentally create tables from future revisions and make
    # a clean 0001 -> head migration fail on duplicate table creation.
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=[Base.metadata.tables[name] for name in NEW_TABLES],
        checkfirst=True,
    )


def downgrade() -> None:
    for table_name in NEW_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table_name}")
