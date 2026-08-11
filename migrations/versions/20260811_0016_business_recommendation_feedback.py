"""Add recommendation execution and result feedback.

Revision ID: 20260811_0016
Revises: 20260811_0015
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_0016"
down_revision = "20260811_0015"
branch_labels = None
depends_on = None


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {str(row["name"]) for row in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    recommendation_table = "business_analysis_recommendations"
    if recommendation_table not in tables:
        raise RuntimeError("business recommendation feedback migration requires revision 0014")

    existing_columns = {
        str(row["name"]) for row in inspector.get_columns(recommendation_table)
    }
    additions = (
        sa.Column("target_scope", sa.String(length=32), nullable=False, server_default="domain"),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observe_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baseline_metrics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_metrics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("actual_cost", sa.Float(), nullable=True),
        sa.Column("actual_hours", sa.Float(), nullable=True),
        sa.Column("user_conclusion", sa.Text(), nullable=False, server_default=""),
        sa.Column("execution_ref_type", sa.String(length=64), nullable=True),
        sa.Column("execution_ref_id", sa.String(length=128), nullable=True),
    )
    for column in additions:
        if column.name not in existing_columns:
            op.add_column(recommendation_table, column)

    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, recommendation_table)
    if "ix_business_analysis_recommendations_observe_until" not in indexes:
        op.create_index(
            "ix_business_analysis_recommendations_observe_until",
            recommendation_table,
            ["observe_until"],
            unique=False,
        )
    if "ix_business_analysis_recommendations_outcome" not in indexes:
        op.create_index(
            "ix_business_analysis_recommendations_outcome",
            recommendation_table,
            ["outcome"],
            unique=False,
        )
    if "idx_business_analysis_recommendation_lifecycle" not in indexes:
        op.create_index(
            "idx_business_analysis_recommendation_lifecycle",
            recommendation_table,
            ["status", "observe_until"],
            unique=False,
        )

    event_table = "business_analysis_recommendation_events"
    if event_table not in tables:
        op.create_table(
            event_table,
            sa.Column("id", sa.String(length=128), nullable=False),
            sa.Column("recommendation_id", sa.String(length=128), nullable=False),
            sa.Column("event_type", sa.String(length=32), nullable=False),
            sa.Column("from_status", sa.String(length=32), nullable=False),
            sa.Column("to_status", sa.String(length=32), nullable=False),
            sa.Column("request_id", sa.String(length=128), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["recommendation_id"],
                ["business_analysis_recommendations.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("request_id"),
        )
        op.create_index(
            "ix_business_analysis_recommendation_events_recommendation_id",
            event_table,
            ["recommendation_id"],
            unique=False,
        )
        op.create_index(
            "ix_business_analysis_recommendation_events_event_type",
            event_table,
            ["event_type"],
            unique=False,
        )
        op.create_index(
            "ix_business_analysis_recommendation_events_request_id",
            event_table,
            ["request_id"],
            unique=True,
        )
        op.create_index(
            "ix_business_analysis_recommendation_events_created_at",
            event_table,
            ["created_at"],
            unique=False,
        )
        op.create_index(
            "idx_business_analysis_recommendation_event_timeline",
            event_table,
            ["recommendation_id", "created_at"],
            unique=False,
        )
    else:
        expected_event_columns = {
            "id",
            "recommendation_id",
            "event_type",
            "from_status",
            "to_status",
            "request_id",
            "payload_hash",
            "result_json",
            "created_at",
        }
        existing_event_columns = {
            str(row["name"]) for row in sa.inspect(bind).get_columns(event_table)
        }
        missing = expected_event_columns - existing_event_columns
        if missing:
            raise RuntimeError(
                "business recommendation event table is incomplete: "
                + ", ".join(sorted(missing))
            )
        event_indexes = _index_names(sa.inspect(bind), event_table)
        for index_name, columns, unique in (
            (
                "ix_business_analysis_recommendation_events_recommendation_id",
                ["recommendation_id"],
                False,
            ),
            (
                "ix_business_analysis_recommendation_events_event_type",
                ["event_type"],
                False,
            ),
            (
                "ix_business_analysis_recommendation_events_request_id",
                ["request_id"],
                True,
            ),
            (
                "ix_business_analysis_recommendation_events_created_at",
                ["created_at"],
                False,
            ),
            (
                "idx_business_analysis_recommendation_event_timeline",
                ["recommendation_id", "created_at"],
                False,
            ),
        ):
            if index_name not in event_indexes:
                op.create_index(
                    index_name,
                    event_table,
                    columns,
                    unique=unique,
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    event_table = "business_analysis_recommendation_events"
    if event_table in tables:
        op.drop_table(event_table)

    recommendation_table = "business_analysis_recommendations"
    if recommendation_table not in tables:
        return
    indexes = _index_names(sa.inspect(bind), recommendation_table)
    for index_name in (
        "idx_business_analysis_recommendation_lifecycle",
        "ix_business_analysis_recommendations_outcome",
        "ix_business_analysis_recommendations_observe_until",
    ):
        if index_name in indexes:
            op.drop_index(index_name, table_name=recommendation_table)
    existing_columns = {
        str(row["name"])
        for row in sa.inspect(bind).get_columns(recommendation_table)
    }
    with op.batch_alter_table(recommendation_table) as batch:
        for column_name in (
            "execution_ref_id",
            "execution_ref_type",
            "user_conclusion",
            "actual_hours",
            "actual_cost",
            "outcome",
            "result_metrics_json",
            "baseline_metrics_json",
            "completed_at",
            "observe_until",
            "started_at",
            "accepted_at",
            "target_scope",
        ):
            if column_name in existing_columns:
                batch.drop_column(column_name)
