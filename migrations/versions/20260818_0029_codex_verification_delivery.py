"""Add verified delivery, acceptance evidence and audited time accounting.

Revision ID: 20260818_0029
Revises: 20260817_0028
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260818_0029"
down_revision = "20260817_0028"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables()

    if "business_projects" in existing:
        columns = {
            str(row[1])
            for row in bind.exec_driver_sql("PRAGMA table_info(business_projects)")
        }
        if "legacy_progress" not in columns:
            op.add_column(
                "business_projects",
                sa.Column("legacy_progress", sa.Integer(), nullable=True),
            )
        if "progress_source" not in columns:
            op.add_column(
                "business_projects",
                sa.Column(
                    "progress_source",
                    sa.String(32),
                    nullable=False,
                    server_default="verified",
                ),
            )
        op.create_index(
            "ix_business_projects_progress_source",
            "business_projects",
            ["progress_source"],
            if_not_exists=True,
        )

    if "business_tasks" in existing:
        task_columns = {
            str(row[1])
            for row in bind.exec_driver_sql("PRAGMA table_info(business_tasks)")
        }
        if "delivery_scope_active" not in task_columns:
            op.add_column(
                "business_tasks",
                sa.Column(
                    "delivery_scope_active",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("1"),
                ),
            )
        if "retired_at" not in task_columns:
            op.add_column(
                "business_tasks",
                sa.Column("retired_at", sa.DateTime(), nullable=True),
            )
        op.create_index(
            "ix_business_tasks_delivery_scope_active",
            "business_tasks",
            ["delivery_scope_active"],
            if_not_exists=True,
        )

    if "codex_acceptance_points" not in existing:
        op.create_table(
            "codex_acceptance_points",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.String(128), sa.ForeignKey("business_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_id", sa.String(128), sa.ForeignKey("codex_development_plans.id", ondelete="SET NULL"), nullable=True),
            sa.Column("point_key", sa.String(128), nullable=False),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("verification_type", sa.String(32), nullable=False, server_default="manual_test"),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("point_weight", sa.Float(), nullable=True),
            sa.Column("waived_counts", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("waiver_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("retired_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("task_id", "point_key", name="uq_codex_acceptance_task_point_key"),
        )
        for column in ("project_id", "task_id", "plan_id", "point_key", "status", "active", "created_at"):
            op.create_index(f"ix_codex_acceptance_points_{column}", "codex_acceptance_points", [column])

    if "codex_acceptance_evidence" not in existing:
        op.create_table(
            "codex_acceptance_evidence",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.String(128), sa.ForeignKey("business_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("point_id", sa.String(128), sa.ForeignKey("codex_acceptance_points.id", ondelete="SET NULL"), nullable=True),
            sa.Column("point_key", sa.String(128), nullable=False),
            sa.Column("run_id", sa.String(128), sa.ForeignKey("codex_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_event_id", sa.String(128), sa.ForeignKey("codex_events.id", ondelete="SET NULL"), nullable=True),
            sa.Column("evidence_type", sa.String(64), nullable=False),
            sa.Column("file_paths_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("test_command", sa.Text(), nullable=False, server_default=""),
            sa.Column("exit_code", sa.Integer(), nullable=True),
            sa.Column("test_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("commit_sha", sa.String(64), nullable=False, server_default=""),
            sa.Column("manual_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="recorded"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "source_event_id",
                "point_id",
                name="uq_codex_acceptance_evidence_event_point",
            ),
        )
        for column in ("project_id", "task_id", "point_id", "point_key", "run_id", "source_event_id", "evidence_type", "status", "created_at"):
            op.create_index(f"ix_codex_acceptance_evidence_{column}", "codex_acceptance_evidence", [column])

    if "codex_acceptance_status_history" not in existing:
        op.create_table(
            "codex_acceptance_status_history",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("point_id", sa.String(128), sa.ForeignKey("codex_acceptance_points.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.String(128), sa.ForeignKey("business_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("from_status", sa.String(32), nullable=False),
            sa.Column("to_status", sa.String(32), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("evidence_id", sa.String(128), sa.ForeignKey("codex_acceptance_evidence.id", ondelete="SET NULL"), nullable=True),
            sa.Column("request_id", sa.String(128), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
        )
        for column in ("point_id", "project_id", "task_id", "to_status", "request_id", "occurred_at"):
            op.create_index(f"ix_codex_acceptance_status_history_{column}", "codex_acceptance_status_history", [column])

    for table in ("codex_acceptance_mutation_requests", "project_time_mutation_requests"):
        if table not in existing:
            op.create_table(
                table,
                sa.Column("request_id", sa.String(128), primary_key=True),
                sa.Column("operation", sa.String(64), nullable=False),
                sa.Column("payload_hash", sa.String(64), nullable=False),
                sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
                sa.Column("created_at", sa.DateTime(), nullable=False),
            )
            op.create_index(f"ix_{table}_operation", table, ["operation"])
            op.create_index(f"ix_{table}_created_at", table, ["created_at"])

    if "codex_run_activity_intervals" not in existing:
        op.create_table(
            "codex_run_activity_intervals",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("run_id", sa.String(128), sa.ForeignKey("codex_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.String(128), sa.ForeignKey("business_tasks.id", ondelete="SET NULL"), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("stop_reason", sa.String(32), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        for column in ("run_id", "project_id", "task_id", "started_at", "ended_at", "created_at"):
            op.create_index(f"ix_codex_run_activity_intervals_{column}", "codex_run_activity_intervals", [column])

    if "project_time_entries" not in existing:
        op.create_table(
            "project_time_entries",
            sa.Column("id", sa.String(255), primary_key=True),
            sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.String(128), sa.ForeignKey("business_tasks.id", ondelete="SET NULL"), nullable=True),
            sa.Column("run_id", sa.String(128), sa.ForeignKey("codex_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("activity_interval_id", sa.String(128), sa.ForeignKey("codex_run_activity_intervals.id", ondelete="SET NULL"), nullable=True, unique=True),
            sa.Column("adjustment_of_id", sa.String(255), sa.ForeignKey("project_time_entries.id", ondelete="SET NULL"), nullable=True),
            sa.Column("category", sa.String(32), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("hours", sa.Float(), nullable=False),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        for column in ("project_id", "task_id", "run_id", "category", "source", "occurred_at", "created_at"):
            op.create_index(f"ix_project_time_entries_{column}", "project_time_entries", [column])

    if "project_git_links" not in existing:
        op.create_table(
            "project_git_links",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("project_id", sa.String(128), sa.ForeignKey("business_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.String(128), sa.ForeignKey("business_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("point_id", sa.String(128), sa.ForeignKey("codex_acceptance_points.id", ondelete="SET NULL"), nullable=True),
            sa.Column("commit_sha", sa.String(64), nullable=False),
            sa.Column("branch", sa.String(255), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="committed"),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("request_id", sa.String(128), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        for column in ("project_id", "task_id", "point_id", "commit_sha", "status", "request_id", "created_at"):
            op.create_index(f"ix_project_git_links_{column}", "project_git_links", [column])

    now = datetime.now(timezone.utc)
    if "business_projects" in existing:
        bind.execute(
            sa.text(
                "UPDATE business_projects "
                "SET legacy_progress = progress, progress = 0, progress_source = 'legacy_manual' "
                "WHERE legacy_progress IS NULL"
            )
        )
        if "ledger_state" in existing:
            state = bind.execute(
                sa.text("SELECT id, snapshot_json FROM ledger_state WHERE id = 1")
            ).mappings().first()
            if state:
                try:
                    snapshot = json.loads(str(state["snapshot_json"] or "{}"))
                except (TypeError, ValueError):
                    snapshot = {}
                projects = snapshot.get("projects") if isinstance(snapshot, dict) else None
                if isinstance(projects, list):
                    for project in projects:
                        if not isinstance(project, dict):
                            continue
                        old_progress = max(0, min(100, int(project.get("progress") or 0)))
                        project["legacyProgress"] = old_progress
                        project["progress"] = 0
                        project["progressSource"] = "legacy_manual"
                    bind.execute(
                        sa.text(
                            "UPDATE ledger_state SET snapshot_json = :snapshot WHERE id = 1"
                        ),
                        {
                            "snapshot": json.dumps(
                                snapshot,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                        },
                    )

    if "business_tasks" in existing:
        task_rows = bind.execute(
            sa.text(
                "SELECT id, project_id, codex_plan_id, acceptance_points_json, "
                "codex_execution_status, actual_hours FROM business_tasks"
            )
        ).mappings()
        for task in task_rows:
            task_id = str(task["id"])
            project_id = str(task["project_id"])
            actual_hours = float(task["actual_hours"] or 0)
            if actual_hours > 0:
                bind.execute(
                    sa.text(
                        "INSERT OR IGNORE INTO project_time_entries "
                        "(id, project_id, task_id, category, source, hours, note, occurred_at, created_at) "
                        "VALUES (:id, :project_id, :task_id, 'development', 'legacy_import', :hours, "
                        "'第四阶段迁移前已存在的实际工时', :now, :now)"
                    ),
                    {
                        "id": f"legacy-time-{hashlib.sha256(task_id.encode()).hexdigest()[:32]}",
                        "project_id": project_id,
                        "task_id": task_id,
                        "hours": actual_hours,
                        "now": now,
                    },
                )

            try:
                points = json.loads(str(task["acceptance_points_json"] or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                points = []
            for raw in points if isinstance(points, list) else []:
                if not isinstance(raw, dict):
                    continue
                point_key = str(raw.get("point_key") or "").strip()
                if not point_key:
                    continue
                point_id = "acceptance-" + hashlib.sha256(
                    f"{task_id}\n{point_key}".encode()
                ).hexdigest()[:32]
                status = (
                    "implemented"
                    if str(task["codex_execution_status"] or "todo") == "implemented"
                    else "pending"
                )
                bind.execute(
                    sa.text(
                        "INSERT OR IGNORE INTO codex_acceptance_points "
                        "(id, project_id, task_id, plan_id, point_key, title, verification_type, "
                        "status, waived_counts, waiver_reason, active, created_at, updated_at) "
                        "VALUES (:id, :project_id, :task_id, :plan_id, :point_key, :title, "
                        ":verification_type, :status, 0, '', 1, :now, :now)"
                    ),
                    {
                        "id": point_id,
                        "project_id": project_id,
                        "task_id": task_id,
                        "plan_id": task["codex_plan_id"],
                        "point_key": point_key,
                        "title": str(raw.get("title") or point_key)[:300],
                        "verification_type": str(raw.get("verification_type") or "manual_test")[:32],
                        "status": status,
                        "now": now,
                    },
                )

    marker = "migration:20260818_0029"
    bind.execute(
        sa.text(
            "INSERT OR IGNORE INTO codex_acceptance_mutation_requests "
            "(request_id, operation, payload_hash, result_json, created_at) "
            "VALUES (:request_id, 'migration', :payload_hash, '{}', :created_at)"
        ),
        {
            "request_id": marker,
            "payload_hash": hashlib.sha256(marker.encode()).hexdigest(),
            "created_at": now,
        },
    )


def downgrade() -> None:
    existing = _tables()
    if "business_projects" in existing:
        op.execute(
            "UPDATE business_projects SET progress = COALESCE(legacy_progress, progress)"
        )
    for table in (
        "project_git_links",
        "project_time_mutation_requests",
        "project_time_entries",
        "codex_run_activity_intervals",
        "codex_acceptance_mutation_requests",
        "codex_acceptance_status_history",
        "codex_acceptance_evidence",
        "codex_acceptance_points",
    ):
        if table in existing:
            op.drop_table(table)
    if "business_projects" in existing:
        with op.batch_alter_table("business_projects") as batch:
            batch.drop_column("progress_source")
            batch.drop_column("legacy_progress")
    if "business_tasks" in existing:
        with op.batch_alter_table("business_tasks") as batch:
            batch.drop_column("retired_at")
            batch.drop_column("delivery_scope_active")
