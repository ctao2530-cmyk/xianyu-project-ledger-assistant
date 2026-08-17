"""Add versioned Codex development plans and stable task synchronization.

Revision ID: 20260817_0026
Revises: 20260817_0025
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260817_0026"
down_revision = "20260817_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "codex_project_bindings" not in existing:
        op.create_table(
            "codex_project_bindings",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id"), nullable=True),
            sa.Column("requirement_case_id", sa.String(128), sa.ForeignKey("requirement_cases.id"), nullable=True),
            sa.Column("repository_path", sa.Text(), nullable=False),
            sa.Column("default_branch", sa.String(255), nullable=False, server_default=""),
            sa.Column("planning_worktree_path", sa.Text(), nullable=False, server_default=""),
            sa.Column("current_head_sha", sa.String(64), nullable=False, server_default=""),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("requirement_case_id", "repository_path", name="uq_codex_binding_case_repository"),
        )
        op.create_index("ix_codex_project_bindings_project_id", "codex_project_bindings", ["project_id"])
        op.create_index("ix_codex_project_bindings_requirement_case_id", "codex_project_bindings", ["requirement_case_id"])
        op.create_index("ix_codex_project_bindings_enabled", "codex_project_bindings", ["enabled"])

    if "codex_development_plans" not in existing:
        op.create_table(
            "codex_development_plans",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("requirement_case_id", sa.String(128), sa.ForeignKey("requirement_cases.id"), nullable=False),
            sa.Column("requirement_version_id", sa.Integer(), sa.ForeignKey("requirement_document_versions.id"), nullable=False),
            sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id"), nullable=True),
            sa.Column("binding_id", sa.String(128), sa.ForeignKey("codex_project_bindings.id"), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("source", sa.String(32), nullable=False, server_default="codex_cli"),
            sa.Column("repository_mode", sa.String(32), nullable=False, server_default="requirement_only"),
            sa.Column("repository_head_sha", sa.String(64), nullable=False, server_default=""),
            sa.Column("repository_branch", sa.String(255), nullable=False, server_default=""),
            sa.Column("repository_dirty", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("raw_structured_json", sa.Text(), nullable=False),
            sa.Column("structured_json", sa.Text(), nullable=False),
            sa.Column("estimate_low_hours", sa.Float(), nullable=False),
            sa.Column("estimate_expected_hours", sa.Float(), nullable=False),
            sa.Column("estimate_high_hours", sa.Float(), nullable=False),
            sa.Column("model", sa.String(128), nullable=False, server_default=""),
            sa.Column("reasoning_effort", sa.String(32), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("requirement_case_id", "version", name="uq_codex_plan_case_version"),
        )
        for column in ("requirement_case_id", "requirement_version_id", "project_id", "binding_id", "status", "created_at"):
            op.create_index(f"ix_codex_development_plans_{column}", "codex_development_plans", [column])

    if "codex_plan_mutation_requests" not in existing:
        op.create_table(
            "codex_plan_mutation_requests",
            sa.Column("request_id", sa.String(128), primary_key=True),
            sa.Column("operation", sa.String(64), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_codex_plan_mutation_requests_operation", "codex_plan_mutation_requests", ["operation"])
        op.create_index("ix_codex_plan_mutation_requests_created_at", "codex_plan_mutation_requests", ["created_at"])

    if "business_tasks" in existing:
        columns = {str(row[1]) for row in op.get_bind().exec_driver_sql("PRAGMA table_info(business_tasks)")}
        additions = (
            ("task_key", sa.String(128), True, None),
            ("stage_key", sa.String(128), True, None),
            ("codex_plan_id", sa.String(128), True, None),
            ("acceptance_points_json", sa.Text, False, "[]"),
            ("test_commands_json", sa.Text, False, "[]"),
        )
        with op.batch_alter_table("business_tasks") as batch:
            for name, column_type, nullable, default in additions:
                if name in columns:
                    continue
                kwargs = {"nullable": nullable}
                if default is not None:
                    kwargs["server_default"] = default
                batch.add_column(sa.Column(name, column_type, **kwargs))
            if "codex_plan_id" not in columns:
                batch.create_foreign_key("fk_business_tasks_codex_plan", "codex_development_plans", ["codex_plan_id"], ["id"])
        op.create_index("ix_business_tasks_task_key", "business_tasks", ["task_key"], if_not_exists=True)
        op.create_index("ix_business_tasks_stage_key", "business_tasks", ["stage_key"], if_not_exists=True)
        op.create_index("ix_business_tasks_codex_plan_id", "business_tasks", ["codex_plan_id"], if_not_exists=True)
        op.create_index("uq_business_task_project_task_key", "business_tasks", ["project_id", "task_key"], unique=True, if_not_exists=True)


def downgrade() -> None:
    if "business_tasks" in set(sa.inspect(op.get_bind()).get_table_names()):
        for index in (
            "uq_business_task_project_task_key",
            "ix_business_tasks_codex_plan_id",
            "ix_business_tasks_stage_key",
            "ix_business_tasks_task_key",
        ):
            op.drop_index(index, table_name="business_tasks", if_exists=True)
        with op.batch_alter_table("business_tasks") as batch:
            for column in (
                "test_commands_json",
                "acceptance_points_json",
                "codex_plan_id",
                "stage_key",
                "task_key",
            ):
                batch.drop_column(column)
    for table in (
        "codex_plan_mutation_requests",
        "codex_development_plans",
        "codex_project_bindings",
    ):
        if table in set(sa.inspect(op.get_bind()).get_table_names()):
            op.drop_table(table)
