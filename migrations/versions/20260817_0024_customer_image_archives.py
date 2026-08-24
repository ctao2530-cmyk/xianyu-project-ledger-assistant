"""Add immutable customer image archive metadata.

Revision ID: 20260817_0024
Revises: 20260816_0023
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260817_0024"
down_revision = "20260816_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "customer_image_archives" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "customer_image_archives",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("platform_message_id", sa.String(255), nullable=False),
        sa.Column("media_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capture_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("capture_source", sa.String(32), nullable=False, server_default="live"),
        sa.Column("mime_type", sa.String(128), nullable=False, server_default=""),
        sa.Column("original_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("storage_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("integrity_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("message_id", "media_index", name="uq_customer_image_archive_message_index"),
    )
    op.create_index("ix_customer_image_archives_conversation_id", "customer_image_archives", ["conversation_id"])
    op.create_index("ix_customer_image_archives_message_id", "customer_image_archives", ["message_id"])
    op.create_index("ix_customer_image_archives_channel", "customer_image_archives", ["channel"])
    op.create_index("ix_customer_image_archives_capture_status", "customer_image_archives", ["capture_status"])
    op.create_index("ix_customer_image_archives_sha256", "customer_image_archives", ["sha256"])
    op.create_index("ix_customer_image_archives_received_at", "customer_image_archives", ["received_at"])
    op.create_index("idx_customer_image_archives_status_received", "customer_image_archives", ["capture_status", "received_at"])
    op.create_index("idx_customer_image_archives_channel_platform", "customer_image_archives", ["channel", "platform_message_id"])


def downgrade() -> None:
    # The metadata and original files are user evidence. Restore the verified
    # pre-migration backup instead of deleting them in place.
    pass
