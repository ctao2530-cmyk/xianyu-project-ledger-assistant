"""Durable image work and explicit conversation-group scope.

Revision ID: 20260907_0045
Revises: 20260903_0044
"""
from alembic import op
from backend.app.customer_workflow_schema import migrate_customer_workflow_schema

revision = "20260907_0045"
down_revision = "20260903_0044"
branch_labels = None
depends_on = None


def upgrade():
    migrate_customer_workflow_schema(op.get_bind())


def downgrade():
    raise RuntimeError("0045 contains media recovery and authorization audit; restore an explicitly approved backup instead")
