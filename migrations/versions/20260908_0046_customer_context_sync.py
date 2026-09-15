"""Durable scoped context progress independent of expiring authorization."""
from alembic import op
from backend.app.customer_sync_schema import migrate_customer_sync_schema

revision = '20260908_0046'
down_revision = '20260907_0045'
branch_labels = None
depends_on = None


def upgrade():
    migrate_customer_sync_schema(op.get_bind())


def downgrade():
    raise RuntimeError('0046 contains confirmed context receipts; retain data and roll back the reader, or restore an explicitly approved backup')
