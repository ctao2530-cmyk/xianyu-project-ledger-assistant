from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from sqlalchemy.engine import Connection


CUSTOMER_INTAKE_COLUMNS = {
    "current_need": "TEXT NOT NULL DEFAULT ''",
    "price_type": "VARCHAR(32) NOT NULL DEFAULT ''",
    "price_amount": "FLOAT",
    "next_action": "TEXT NOT NULL DEFAULT ''",
    "notes": "TEXT NOT NULL DEFAULT ''",
}

PROJECT_REQUIREMENT_HANDOFF_COLUMNS = {
    "project_id": "VARCHAR(128)",
    "source_filename": "VARCHAR(255) NOT NULL DEFAULT ''",
    "source_sha256": "VARCHAR(64) NOT NULL DEFAULT ''",
    "import_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
}

PROJECT_TASK_DRAFT_COLUMNS = {
    "workspace_key": "VARCHAR(128)",
    "dependency_task_keys_json": "TEXT NOT NULL DEFAULT '[]'",
    "deliverables_json": "TEXT NOT NULL DEFAULT '[]'",
    "requirement_version_id": "INTEGER REFERENCES requirement_document_versions(id)",
}


def migrate_project_requirement_handoff_schema(connection: Connection) -> bool:
    """Restore the all-or-nothing 0037 project requirement columns."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    table = "requirement_document_versions"
    if table not in tables:
        return False
    column_rows = list(connection.exec_driver_sql(f"PRAGMA table_info({table})"))
    columns = {str(row[1]) for row in column_rows}
    expected = set(PROJECT_REQUIREMENT_HANDOFF_COLUMNS)
    present = columns.intersection(expected)
    if present and present != expected:
        raise RuntimeError(
            "project requirement handoff schema is partial; refusing silent repair; missing columns: "
            + ", ".join(sorted(expected - present))
        )
    changed = False
    if not present:
        for name, definition in PROJECT_REQUIREMENT_HANDOFF_COLUMNS.items():
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        changed = True
    conversation_required = bool(
        next((row[3] for row in column_rows if str(row[1]) == "conversation_id"), 0)
    )
    if conversation_required:
        temporary = "requirement_document_versions_0037_new"
        if temporary in tables:
            raise RuntimeError(
                "project requirement handoff schema is partial; temporary rebuild table exists"
            )
        connection.exec_driver_sql(
            f"""
            CREATE TABLE {temporary} (
                id INTEGER NOT NULL PRIMARY KEY,
                conversation_id INTEGER,
                case_id VARCHAR(128),
                project_id VARCHAR(128),
                schema_version VARCHAR(16) NOT NULL DEFAULT '1.0',
                source_type VARCHAR(32) NOT NULL DEFAULT 'codex_cli',
                source_label VARCHAR(255) NOT NULL DEFAULT 'Codex 生成',
                imported_at DATETIME,
                source_filename VARCHAR(255) NOT NULL DEFAULT '',
                source_sha256 VARCHAR(64) NOT NULL DEFAULT '',
                import_metadata_json TEXT NOT NULL DEFAULT '{{}}',
                version INTEGER NOT NULL,
                title VARCHAR(300) NOT NULL,
                readiness VARCHAR(32) NOT NULL,
                change_summary TEXT NOT NULL,
                structured_json TEXT NOT NULL,
                content_markdown TEXT NOT NULL,
                stage_progress_json TEXT NOT NULL DEFAULT '{{}}',
                model VARCHAR(128) NOT NULL,
                reasoning_effort VARCHAR(32),
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_requirement_conversation_version UNIQUE (conversation_id, version),
                CONSTRAINT uq_requirement_case_version UNIQUE (case_id, version),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id),
                FOREIGN KEY(case_id) REFERENCES requirement_cases(id),
                FOREIGN KEY(project_id) REFERENCES business_projects(id)
            )
            """
        )
        copy_columns = [
            "id", "conversation_id", "case_id", "project_id", "schema_version",
            "source_type", "source_label", "imported_at", "source_filename",
            "source_sha256", "import_metadata_json", "version", "title", "readiness",
            "change_summary", "structured_json", "content_markdown", "stage_progress_json",
            "model", "reasoning_effort", "created_at",
        ]
        joined = ", ".join(copy_columns)
        connection.exec_driver_sql(
            f"INSERT INTO {temporary} ({joined}) SELECT {joined} FROM {table}"
        )
        connection.exec_driver_sql(f"DROP TABLE {table}")
        connection.exec_driver_sql(f"ALTER TABLE {temporary} RENAME TO {table}")
        changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_requirement_document_versions_conversation_id "
        "ON requirement_document_versions(conversation_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_requirement_document_versions_created_at "
        "ON requirement_document_versions(created_at)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_requirement_versions_conversation_created "
        "ON requirement_document_versions(conversation_id, created_at)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_requirement_document_versions_case_id "
        "ON requirement_document_versions(case_id)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_requirement_case_version_partial "
        "ON requirement_document_versions(case_id, version) WHERE case_id IS NOT NULL"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_requirement_document_versions_project_id "
        "ON requirement_document_versions(project_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_requirement_document_versions_source_sha256 "
        "ON requirement_document_versions(source_sha256)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_requirement_project_version_partial "
        "ON requirement_document_versions(project_id, version) WHERE project_id IS NOT NULL"
    )
    return changed


def migrate_project_task_draft_schema(connection: Connection) -> bool:
    """Add 0038 task columns and reject every partially-created schema."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "business_tasks" not in tables:
        return False
    columns = {
        str(row[1]) for row in connection.exec_driver_sql("PRAGMA table_info(business_tasks)")
    }
    expected_columns = set(PROJECT_TASK_DRAFT_COLUMNS)
    present_columns = columns.intersection(expected_columns)
    expected_tables = {"project_task_draft_previews", "project_task_draft_items"}
    present_tables = tables.intersection(expected_tables)
    if (present_columns and present_columns != expected_columns) or (
        present_tables and present_tables != expected_tables
    ) or (present_tables == expected_tables and present_columns != expected_columns):
        missing = sorted(
            (expected_columns - present_columns) | (expected_tables - present_tables)
        )
        raise RuntimeError(
            "project task draft schema is partial; refusing silent repair; missing: "
            + ", ".join(missing)
        )
    if present_columns == expected_columns and present_tables == expected_tables:
        return False
    if present_columns != expected_columns:
        for name, definition in PROJECT_TASK_DRAFT_COLUMNS.items():
            connection.exec_driver_sql(
                f"ALTER TABLE business_tasks ADD COLUMN {name} {definition}"
            )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_business_tasks_workspace_key "
            "ON business_tasks(workspace_key)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_business_tasks_requirement_version_id "
            "ON business_tasks(requirement_version_id)"
        )
        return True
    return False


def migrate_customer_intake_schema(connection: Connection) -> bool:
    """Add the customer-intake fields as one all-or-nothing schema unit."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "business_customers" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql("PRAGMA table_info(business_customers)")
    }
    expected = set(CUSTOMER_INTAKE_COLUMNS)
    present = expected.intersection(columns)
    if present == expected:
        return False
    if present:
        raise RuntimeError(
            "customer intake schema is incomplete: missing columns "
            + ", ".join(sorted(expected - present))
        )
    for name, definition in CUSTOMER_INTAKE_COLUMNS.items():
        connection.exec_driver_sql(
            f"ALTER TABLE business_customers ADD COLUMN {name} {definition}"
        )
    return True


PHRASE_LIBRARY_TABLE_COLUMNS = {
    "phrase_library_states": {"id", "revision", "created_at", "updated_at"},
    "phrase_categories": {
        "id", "category_key", "name", "source", "position", "active",
        "created_at", "updated_at",
    },
    "phrase_snippets": {
        "id", "category_id", "content", "position", "active", "created_at",
        "updated_at",
    },
    "phrase_library_mutation_requests": {
        "request_id", "operation", "payload_hash", "result_json", "created_at",
    },
}

PHRASE_LIBRARY_DEFAULT_CATEGORIES = (
    ("phrase-category-initial", "initial_consultation", "初次咨询", 0),
    ("phrase-category-kickoff", "before_kickoff", "开工前", 1),
    ("phrase-category-completion", "after_completion", "完工后", 2),
)

PHRASE_LIBRARY_INDEXES = {
    "ix_phrase_categories_category_key",
    "ix_phrase_categories_source",
    "ix_phrase_categories_active",
    "ix_phrase_snippets_category_id",
    "ix_phrase_snippets_active",
    "idx_phrase_snippets_category_position",
    "ix_phrase_library_mutation_requests_operation",
    "ix_phrase_library_mutation_requests_created_at",
}


def migrate_phrase_library_schema(connection: Connection) -> bool:
    """Create the all-or-nothing manual phrase-library schema.

    A partially present schema is rejected so startup never silently turns a
    damaged local database into an apparently healthy phrase library.
    """

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    expected_tables = set(PHRASE_LIBRARY_TABLE_COLUMNS)
    present = expected_tables.intersection(tables)
    if present and present != expected_tables:
        raise RuntimeError(
            "phrase library schema is incomplete: missing tables "
            + ", ".join(sorted(expected_tables - present))
        )
    if present == expected_tables:
        incomplete: list[str] = []
        for table, required in PHRASE_LIBRARY_TABLE_COLUMNS.items():
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            missing = required - columns
            if missing:
                incomplete.append(f"{table}: {', '.join(sorted(missing))}")
        if incomplete:
            raise RuntimeError(
                "phrase library schema is incomplete: " + "; ".join(incomplete)
            )
        indexes = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        missing_indexes = PHRASE_LIBRARY_INDEXES - indexes
        if missing_indexes:
            raise RuntimeError(
                "phrase library schema is incomplete: missing indexes "
                + ", ".join(sorted(missing_indexes))
            )
        state = connection.exec_driver_sql(
            "SELECT revision FROM phrase_library_states WHERE id = 'global'"
        ).first()
        if state is None:
            raise RuntimeError(
                "phrase library schema is incomplete: missing global revision state"
            )
        default_rows = {
            str(row[0]): (str(row[1]), int(row[2]), bool(row[3]))
            for row in connection.exec_driver_sql(
                "SELECT category_key, name, position, active "
                "FROM phrase_categories WHERE source = 'default'"
            )
        }
        expected_rows = {
            row[1]: (row[2], row[3], True)
            for row in PHRASE_LIBRARY_DEFAULT_CATEGORIES
        }
        if any(default_rows.get(key) != value for key, value in expected_rows.items()):
            raise RuntimeError(
                "phrase library schema is incomplete: default categories differ"
            )
        return False

    connection.exec_driver_sql(
        """
        CREATE TABLE phrase_library_states (
            id VARCHAR(32) NOT NULL PRIMARY KEY,
            revision INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE phrase_categories (
            id VARCHAR(128) NOT NULL PRIMARY KEY,
            category_key VARCHAR(128) NOT NULL UNIQUE,
            name VARCHAR(64) NOT NULL,
            source VARCHAR(32) NOT NULL DEFAULT 'custom',
            position INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX ix_phrase_categories_category_key "
        "ON phrase_categories(category_key)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_phrase_categories_source ON phrase_categories(source)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_phrase_categories_active ON phrase_categories(active)"
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE phrase_snippets (
            id VARCHAR(128) NOT NULL PRIMARY KEY,
            category_id VARCHAR(128) NOT NULL,
            content TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(category_id) REFERENCES phrase_categories(id) ON DELETE RESTRICT
        )
        """
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_phrase_snippets_category_id ON phrase_snippets(category_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_phrase_snippets_active ON phrase_snippets(active)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX idx_phrase_snippets_category_position "
        "ON phrase_snippets(category_id, position, created_at)"
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE phrase_library_mutation_requests (
            request_id VARCHAR(128) NOT NULL PRIMARY KEY,
            operation VARCHAR(64) NOT NULL,
            payload_hash VARCHAR(64) NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME NOT NULL
        )
        """
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_phrase_library_mutation_requests_operation "
        "ON phrase_library_mutation_requests(operation)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_phrase_library_mutation_requests_created_at "
        "ON phrase_library_mutation_requests(created_at)"
    )
    now = datetime.now(timezone.utc).isoformat()
    connection.exec_driver_sql(
        "INSERT INTO phrase_library_states "
        "(id, revision, created_at, updated_at) VALUES ('global', 0, ?, ?)",
        (now, now),
    )
    for category_id, category_key, name, position in PHRASE_LIBRARY_DEFAULT_CATEGORIES:
        connection.exec_driver_sql(
            "INSERT INTO phrase_categories "
            "(id, category_key, name, source, position, active, created_at, updated_at) "
            "VALUES (?, ?, ?, 'default', ?, 1, ?, ?)",
            (category_id, category_key, name, position, now, now),
        )
    return True


def migrate_codex_plan_schema(connection: Connection) -> bool:
    """Add stable plan-sync identifiers to legacy business task rows."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "business_tasks" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql("PRAGMA table_info(business_tasks)")
    }
    additions = (
        ("task_key", "VARCHAR(128)"),
        ("stage_key", "VARCHAR(128)"),
        ("codex_plan_id", "VARCHAR(128) REFERENCES codex_development_plans(id)"),
        ("acceptance_points_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("test_commands_json", "TEXT NOT NULL DEFAULT '[]'"),
    )
    changed = False
    for name, definition in additions:
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE business_tasks ADD COLUMN {name} {definition}"
            )
            changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_business_tasks_task_key ON business_tasks(task_key)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_business_tasks_stage_key ON business_tasks(stage_key)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_business_tasks_codex_plan_id ON business_tasks(codex_plan_id)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_business_task_project_task_key "
        "ON business_tasks(project_id, task_key) WHERE task_key IS NOT NULL"
    )
    return changed


def migrate_codex_sync_schema(connection: Connection) -> bool:
    """Add the independent Codex execution state to legacy task rows."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "business_tasks" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql("PRAGMA table_info(business_tasks)")
    }
    changed = False
    additions = (
        ("codex_execution_status", "VARCHAR(32) NOT NULL DEFAULT 'todo'"),
        ("codex_implemented_at", "DATETIME"),
    )
    for name, definition in additions:
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE business_tasks ADD COLUMN {name} {definition}"
            )
            changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_business_tasks_codex_execution_status "
        "ON business_tasks(codex_execution_status)"
    )
    return changed


def migrate_codex_runtime_schema(connection: Connection) -> bool:
    """Add managed-runtime columns to a phase-two SQLite database."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "codex_runs" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql("PRAGMA table_info(codex_runs)")
    }
    additions = (
        ("runtime_type", "VARCHAR(32) NOT NULL DEFAULT 'external'"),
        ("thread_id", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("turn_id", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("task_key", "VARCHAR(128)"),
        ("base_commit_sha", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("branch", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("worktree_path", "TEXT NOT NULL DEFAULT ''"),
        ("model", "VARCHAR(128) NOT NULL DEFAULT ''"),
        ("reasoning_effort", "VARCHAR(32) NOT NULL DEFAULT ''"),
        ("sandbox_mode", "VARCHAR(32) NOT NULL DEFAULT ''"),
        ("approval_mode", "VARCHAR(32) NOT NULL DEFAULT ''"),
        ("paused_at", "DATETIME"),
    )
    changed = False
    for name, definition in additions:
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE codex_runs ADD COLUMN {name} {definition}"
            )
            changed = True
    for column in ("runtime_type", "thread_id", "task_key"):
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS ix_codex_runs_{column} ON codex_runs({column})"
        )
    return changed


def migrate_codex_verification_schema(connection: Connection) -> bool:
    """Prepare legacy project rows before metadata creates phase-four tables."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "business_projects" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(business_projects)"
        )
    }
    changed = False
    added_legacy = "legacy_progress" not in columns
    if added_legacy:
        connection.exec_driver_sql(
            "ALTER TABLE business_projects ADD COLUMN legacy_progress INTEGER"
        )
        changed = True
    if "progress_source" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE business_projects ADD COLUMN progress_source "
            "VARCHAR(32) NOT NULL DEFAULT 'verified'"
        )
        changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_business_projects_progress_source "
        "ON business_projects(progress_source)"
    )
    if added_legacy:
        connection.exec_driver_sql(
            "UPDATE business_projects "
            "SET legacy_progress = progress, progress = 0, progress_source = 'legacy_manual'"
        )
        if "ledger_state" in tables:
            state = connection.exec_driver_sql(
                "SELECT id, snapshot_json FROM ledger_state WHERE id = 1"
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
                    connection.exec_driver_sql(
                        "UPDATE ledger_state SET snapshot_json = ? WHERE id = 1",
                        (
                            json.dumps(
                                snapshot,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        ),
                    )
    if "business_tasks" in tables:
        task_columns = {
            str(row[1])
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(business_tasks)"
            )
        }
        if "delivery_scope_active" not in task_columns:
            connection.exec_driver_sql(
                "ALTER TABLE business_tasks ADD COLUMN delivery_scope_active "
                "BOOLEAN NOT NULL DEFAULT 1"
            )
            changed = True
        if "retired_at" not in task_columns:
            connection.exec_driver_sql(
                "ALTER TABLE business_tasks ADD COLUMN retired_at DATETIME"
            )
            changed = True
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_business_tasks_delivery_scope_active "
            "ON business_tasks(delivery_scope_active)"
        )
    return changed


def migrate_estimate_calibration_schema(connection: Connection) -> bool:
    """Create the phase-five calibration schema or reject partial state.

    The local service does not rely on an ``alembic_version`` table at startup,
    so this idempotent path mirrors migration 0030. It deliberately refuses to
    fill a partial table set or silently accept missing columns.
    """

    from .models import (
        EstimateCalibrationDecision,
        EstimateCalibrationMutationRequest,
        EstimateCalibrationRun,
        EstimateCalibrationSample,
        EstimateCalibrationSuggestion,
    )

    expected = {
        "estimate_calibration_samples": {
            "id", "project_id", "source_hash", "estimated_hours", "actual_hours",
            "available_at", "finalized_at", "cutoff_at", "outcome_json",
        },
        "estimate_calibration_runs": {
            "id", "request_id", "input_snapshot_hash", "cutoff_at", "sample_count",
            "sufficiency", "algorithm_version", "sample_ids_json",
        },
        "estimate_calibration_suggestions": {
            "id", "run_id", "project_id", "original_estimated_hours",
            "suggested_hours", "lower_hours", "upper_hours", "status", "revision",
        },
        "estimate_calibration_decisions": {
            "id", "suggestion_id", "project_id", "request_id", "action",
            "expected_revision", "resulting_revision", "payload_hash",
        },
        "estimate_calibration_mutation_requests": {
            "request_id", "operation", "payload_hash", "result_json", "created_at",
        },
    }
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    present = set(expected).intersection(tables)
    if present and present != set(expected):
        missing = ", ".join(sorted(set(expected) - present))
        raise RuntimeError(
            "estimate calibration schema is incomplete: " + missing
        )
    if present == set(expected):
        for table, required_columns in expected.items():
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            missing_columns = required_columns - columns
            if missing_columns:
                raise RuntimeError(
                    "estimate calibration schema is incomplete: "
                    f"{table} missing {', '.join(sorted(missing_columns))}"
                )
        return False

    for table in (
        EstimateCalibrationSample.__table__,
        EstimateCalibrationRun.__table__,
        EstimateCalibrationSuggestion.__table__,
        EstimateCalibrationDecision.__table__,
        EstimateCalibrationMutationRequest.__table__,
    ):
        table.create(bind=connection, checkfirst=True)
    return True


def migrate_project_outcome_freeze_schema(connection: Connection) -> bool:
    """Mirror phase 0031 for the local startup path and reject partial state."""

    from .models import (
        ProjectOutcomeFreeze,
        ProjectOutcomeFreezeMutationRequest,
    )

    expected_tables = {
        "project_outcome_freezes": {
            "id", "project_id", "version", "supersedes_freeze_id",
            "source_ledger_revision", "input_hash", "outcome_json",
            "evidence_summary_json", "confirmed_scope_complete",
            "confirmed_time_complete", "confirmation_note", "frozen_at",
            "created_at",
        },
        "project_outcome_freeze_mutation_requests": {
            "request_id", "operation", "payload_hash", "result_json", "created_at",
        },
    }
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "codex_acceptance_points" not in tables:
        return False
    point_columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(codex_acceptance_points)"
        )
    }
    present_tables = set(expected_tables).intersection(tables)
    source_present = "source" in point_columns
    if present_tables == set(expected_tables) and source_present:
        for table, required_columns in expected_tables.items():
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            missing_columns = required_columns - columns
            if missing_columns:
                raise RuntimeError(
                    "project outcome freeze schema is incomplete: "
                    f"{table} missing {', '.join(sorted(missing_columns))}"
                )
        return False
    if present_tables or source_present:
        missing = sorted(set(expected_tables) - present_tables)
        if not source_present:
            missing.append("codex_acceptance_points.source")
        raise RuntimeError(
            "project outcome freeze schema is incomplete: " + ", ".join(missing)
        )
    if "estimate_calibration_samples" not in tables:
        return False

    connection.exec_driver_sql(
        "ALTER TABLE codex_acceptance_points ADD COLUMN source "
        "VARCHAR(32) NOT NULL DEFAULT 'codex_plan'"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_codex_acceptance_points_source "
        "ON codex_acceptance_points(source)"
    )
    ProjectOutcomeFreeze.__table__.create(bind=connection, checkfirst=True)
    ProjectOutcomeFreezeMutationRequest.__table__.create(
        bind=connection, checkfirst=True
    )
    return True


def migrate_global_agent_schema(connection: Connection) -> bool:
    """Create phase 0033 atomically or reject any partial Agent structure.

    The desktop service starts directly from SQLAlchemy rather than running
    Alembic on every launch.  This mirror therefore performs the same strict
    completeness check as migration 0033 before ``metadata.create_all`` gets a
    chance to hide a damaged or interrupted upgrade.
    """

    from .models import (
        CustomerImageHistoryRecoveryRun,
        GlobalAgentConversationSummary,
        GlobalAgentKnowledgeChunk,
        GlobalAgentKnowledgeDocument,
        GlobalAgentMessage,
        GlobalAgentModelProfile,
        GlobalAgentMutationRequest,
        GlobalAgentRun,
        GlobalAgentThread,
        GlobalAgentToolCall,
    )

    expected = {
        "global_agent_model_profiles": {
            "id", "provider", "model", "reasoning_effort", "label", "enabled",
            "is_default", "revision", "created_at", "updated_at",
        },
        "global_agent_threads": {
            "id", "title", "profile_id", "provider", "model", "reasoning_effort",
            "status", "revision", "created_at", "updated_at",
        },
        "global_agent_messages": {
            "id", "thread_id", "role", "content", "status", "run_id",
            "citations_json", "tool_refs_json", "created_at",
        },
        "global_agent_runs": {
            "id", "request_id", "thread_id", "user_message_id",
            "assistant_message_id", "provider", "model", "reasoning_effort",
            "status", "input_hash", "error_code", "error_message", "started_at",
            "completed_at", "created_at",
        },
        "global_agent_tool_calls": {
            "id", "run_id", "position", "tool_name", "arguments_json",
            "result_json", "status", "duration_ms", "created_at",
        },
        "global_agent_knowledge_documents": {
            "id", "relative_path", "absolute_path", "title", "maturity",
            "content_hash", "active", "exclusion_reason", "indexed_at",
            "created_at", "updated_at",
        },
        "global_agent_knowledge_chunks": {
            "id", "document_id", "ordinal", "heading", "content", "content_hash",
            "created_at",
        },
        "global_agent_mutation_requests": {
            "request_id", "operation", "payload_hash", "result_json", "created_at",
        },
        "global_agent_knowledge_fts": {"chunk_id", "heading", "content"},
    }
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    present = set(expected).intersection(tables)
    if present and present != set(expected):
        raise RuntimeError(
            "global Agent schema is incomplete: "
            + ", ".join(sorted(set(expected) - present))
        )
    if present == set(expected):
        for table, required_columns in expected.items():
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            missing = required_columns - columns
            if missing:
                raise RuntimeError(
                    "global Agent schema is incomplete: "
                    f"{table} missing {', '.join(sorted(missing))}"
                )
        return False

    for table in (
        GlobalAgentModelProfile.__table__,
        GlobalAgentThread.__table__,
        GlobalAgentMessage.__table__,
        GlobalAgentRun.__table__,
        GlobalAgentToolCall.__table__,
        GlobalAgentKnowledgeDocument.__table__,
        GlobalAgentKnowledgeChunk.__table__,
        GlobalAgentMutationRequest.__table__,
        GlobalAgentConversationSummary.__table__,
        CustomerImageHistoryRecoveryRun.__table__,
    ):
        table.create(bind=connection, checkfirst=False)
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE global_agent_knowledge_fts USING fts5("
        "chunk_id UNINDEXED, heading, content, tokenize='trigram')"
    )
    return True


def migrate_agent_customer_context_schema(connection: Connection) -> bool:
    """Mirror phase 0034 and reject incomplete additive Agent/image state."""

    from .models import (
        CustomerImageHistoryRecoveryRun,
        GlobalAgentConversationSummary,
    )

    new_tables = {
        "global_agent_conversation_summaries": {
            "id", "conversation_id", "version", "source_run_id",
            "summarized_through_message_id", "message_count", "source_hash",
            "summary_json", "evidence_message_ids_json", "provider", "model",
            "created_at",
        },
        "customer_image_history_recovery_runs": {
            "request_id", "status", "result_json", "started_at", "completed_at",
            "updated_at",
        },
    }
    thread_required = {"context_scope", "conversation_id", "customer_id"}
    run_required = {"recheck_full_context"}
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "global_agent_threads" not in tables:
        raise RuntimeError("agent customer context requires global Agent phase 0033")
    thread_columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(global_agent_threads)"
        )
    }
    run_columns = {
        str(row[1])
        for row in connection.exec_driver_sql("PRAGMA table_info(global_agent_runs)")
    }
    present_tables = set(new_tables).intersection(tables)
    present_columns = thread_required.intersection(thread_columns)
    present_run_columns = run_required.intersection(run_columns)
    if (
        present_tables == set(new_tables)
        and present_columns == thread_required
        and present_run_columns == run_required
    ):
        for table, required in new_tables.items():
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            missing = required - columns
            if missing:
                raise RuntimeError(
                    "agent customer context schema is incomplete: "
                    f"{table} missing {', '.join(sorted(missing))}"
                )
        return False
    if present_tables or present_columns or present_run_columns:
        missing = (set(new_tables) - present_tables) | {
            f"global_agent_threads.{column}"
            for column in thread_required - present_columns
        }
        missing |= {
            f"global_agent_runs.{column}"
            for column in run_required - present_run_columns
        }
        raise RuntimeError(
            "agent customer context schema is incomplete: "
            + ", ".join(sorted(missing))
        )

    connection.exec_driver_sql(
        "ALTER TABLE global_agent_threads ADD COLUMN context_scope "
        "VARCHAR(32) NOT NULL DEFAULT 'general_business'"
    )
    connection.exec_driver_sql(
        "ALTER TABLE global_agent_threads ADD COLUMN conversation_id INTEGER "
        "REFERENCES conversations(id) ON DELETE SET NULL"
    )
    connection.exec_driver_sql(
        "ALTER TABLE global_agent_threads ADD COLUMN customer_id VARCHAR(128) "
        "REFERENCES business_customers(id) ON DELETE SET NULL"
    )
    connection.exec_driver_sql(
        "ALTER TABLE global_agent_runs ADD COLUMN recheck_full_context "
        "BOOLEAN NOT NULL DEFAULT 0"
    )
    for name, column in (
        ("ix_global_agent_threads_context_scope", "context_scope"),
        ("ix_global_agent_threads_conversation_id", "conversation_id"),
        ("ix_global_agent_threads_customer_id", "customer_id"),
    ):
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {name} ON global_agent_threads({column})"
        )
    GlobalAgentConversationSummary.__table__.create(bind=connection, checkfirst=False)
    CustomerImageHistoryRecoveryRun.__table__.create(bind=connection, checkfirst=False)
    return True


def migrate_global_agent_trace_schema(connection: Connection) -> bool:
    """Mirror phase 0039 and reject a partially created trace table."""

    from .models import GlobalAgentRunStep

    required = {
        "id",
        "run_id",
        "position",
        "node_name",
        "status",
        "summary",
        "detail_json",
        "duration_ms",
        "started_at",
        "completed_at",
        "created_at",
    }
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "global_agent_runs" not in tables:
        return False
    if "global_agent_run_steps" not in tables:
        GlobalAgentRunStep.__table__.create(bind=connection, checkfirst=False)
        return True

    columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(global_agent_run_steps)"
        )
    }
    missing = required - columns
    if missing:
        raise RuntimeError(
            "global Agent run trace schema is incomplete: "
            + ", ".join(sorted(missing))
        )
    return False


def migrate_customer_context_gateway_schema(connection: Connection) -> bool:
    """Mirror phase 0040 and reject any partial customer-context permission domain."""

    from .models import (
        CustomerContextAccessAudit,
        CustomerContextGrant,
        CustomerContextMutationRequest,
    )

    expected = {
        "customer_context_grants": {
            "id", "thread_id", "conversation_id", "provider_scope",
            "audience", "token_hash", "allow_text", "allow_images",
            "allow_artifacts", "allow_new_messages", "consent_policy_version", "consent_text_hash",
            "status", "revision", "authorization_note", "confirmed_at",
            "expires_at", "revoked_at", "created_at", "updated_at",
        },
        "customer_context_access_audits": {
            "id", "request_id", "grant_id", "grant_revision", "thread_id",
            "conversation_id", "provider", "audience", "target_model",
            "tool_name", "requested_scopes_json", "request_hash", "status",
            "summary_version", "watermark_before", "watermark_after",
            "text_message_count", "image_count", "byte_count",
            "resource_hashes_json", "source_hash", "error_code",
            "duration_ms", "created_at", "completed_at",
        },
        "customer_context_mutation_requests": {
            "request_id", "operation", "payload_hash", "result_json", "created_at",
        },
    }
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    present = set(expected).intersection(tables)
    if present and present != set(expected):
        raise RuntimeError(
            "customer context gateway schema is incomplete: "
            + ", ".join(sorted(set(expected) - present))
        )
    if present == set(expected):
        for table, required_columns in expected.items():
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            missing = required_columns - columns
            if missing:
                raise RuntimeError(
                    "customer context gateway schema is incomplete: "
                    f"{table} missing {', '.join(sorted(missing))}"
                )
        return False
    if "global_agent_threads" not in tables or "conversations" not in tables:
        return False

    for table in (
        CustomerContextGrant.__table__,
        CustomerContextAccessAudit.__table__,
        CustomerContextMutationRequest.__table__,
    ):
        table.create(bind=connection, checkfirst=False)
    return True


CUSTOMER_CONTEXT_OAUTH_COLUMNS = {
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


def validate_customer_context_oauth_schema(connection: Connection) -> bool:
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    table = "customer_context_oauth_bindings"
    if table not in tables:
        return False
    columns = {
        str(row[1]) for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
    }
    missing = CUSTOMER_CONTEXT_OAUTH_COLUMNS - columns
    if missing:
        raise RuntimeError(
            "customer context OAuth schema is incomplete: "
            + ", ".join(sorted(missing))
        )
    foreign_keys = {
        (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
        for row in connection.exec_driver_sql(f"PRAGMA foreign_key_list({table})")
    }
    if ("grant_id", "customer_context_grants", "id", "CASCADE") not in foreign_keys:
        raise RuntimeError(
            "customer context OAuth schema is incomplete: grant foreign key missing"
        )
    unique_sets: set[tuple[str, ...]] = set()
    for index in connection.exec_driver_sql(f"PRAGMA index_list('{table}')"):
        if not bool(index[2]):
            continue
        unique_sets.add(
            tuple(
                str(row[2])
                for row in connection.exec_driver_sql(
                    f"PRAGMA index_info('{str(index[1])}')"
                )
            )
        )
    if ("token_hash",) not in unique_sets:
        raise RuntimeError(
            "customer context OAuth schema is incomplete: token hash uniqueness missing"
        )
    return True


def migrate_customer_context_oauth_schema(connection: Connection) -> bool:
    """Mirror phase 0042 and reject a partially created OAuth binding table."""

    from .models import CustomerContextOAuthBinding

    if validate_customer_context_oauth_schema(connection):
        return False
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "customer_context_grants" not in tables:
        return False
    CustomerContextOAuthBinding.__table__.create(bind=connection, checkfirst=False)
    validate_customer_context_oauth_schema(connection)
    return True


CUSTOMER_CONTEXT_TUNNEL_COLUMNS = {
    "slot",
    "grant_id",
    "revision",
    "created_at",
    "updated_at",
}


def validate_customer_context_tunnel_schema(connection: Connection) -> bool:
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    table = "customer_context_tunnel_bindings"
    if table not in tables:
        return False
    columns = {
        str(row[1]) for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
    }
    missing = CUSTOMER_CONTEXT_TUNNEL_COLUMNS - columns
    if missing:
        raise RuntimeError(
            "customer context tunnel schema is incomplete: "
            + ", ".join(sorted(missing))
        )
    primary_key = tuple(
        str(row[1])
        for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
        if int(row[5]) > 0
    )
    if primary_key != ("slot",):
        raise RuntimeError(
            "customer context tunnel schema is incomplete: slot primary key missing"
        )
    foreign_keys = {
        (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
        for row in connection.exec_driver_sql(f"PRAGMA foreign_key_list({table})")
    }
    if ("grant_id", "customer_context_grants", "id", "CASCADE") not in foreign_keys:
        raise RuntimeError(
            "customer context tunnel schema is incomplete: grant foreign key missing"
        )
    unique_sets: set[tuple[str, ...]] = set()
    for index in connection.exec_driver_sql(f"PRAGMA index_list('{table}')"):
        if not bool(index[2]):
            continue
        unique_sets.add(
            tuple(
                str(row[2])
                for row in connection.exec_driver_sql(
                    f"PRAGMA index_info('{str(index[1])}')"
                )
            )
        )
    if ("grant_id",) not in unique_sets:
        raise RuntimeError(
            "customer context tunnel schema is incomplete: grant uniqueness missing"
        )
    return True


def migrate_customer_context_tunnel_schema(connection: Connection) -> bool:
    """Mirror phase 0043 and reject a partially created tunnel binding table."""

    from .models import CustomerContextTunnelBinding

    if validate_customer_context_tunnel_schema(connection):
        return False
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "customer_context_grants" not in tables:
        return False
    CustomerContextTunnelBinding.__table__.create(bind=connection, checkfirst=False)
    validate_customer_context_tunnel_schema(connection)
    return True


CUSTOMER_CONTEXT_THREAD_BINDING_COLUMNS = {
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


def validate_customer_context_thread_binding_schema(connection: Connection) -> bool:
    table = "customer_context_thread_bindings"
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if table not in tables:
        return False
    columns = {
        str(row[1]) for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
    }
    missing = CUSTOMER_CONTEXT_THREAD_BINDING_COLUMNS - columns
    if missing:
        raise RuntimeError(
            "customer context thread binding schema is incomplete: "
            + ", ".join(sorted(missing))
        )
    primary_key = tuple(
        str(row[1])
        for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
        if int(row[5]) > 0
    )
    if primary_key != ("id",):
        raise RuntimeError(
            "customer context thread binding schema is incomplete: id primary key missing"
        )
    foreign_keys = {
        (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
        for row in connection.exec_driver_sql(f"PRAGMA foreign_key_list({table})")
    }
    if ("grant_id", "customer_context_grants", "id", "CASCADE") not in foreign_keys:
        raise RuntimeError(
            "customer context thread binding schema is incomplete: grant foreign key missing"
        )
    unique_sets: set[tuple[str, ...]] = set()
    for index in connection.exec_driver_sql(f"PRAGMA index_list('{table}')"):
        if not bool(index[2]):
            continue
        unique_sets.add(
            tuple(
                str(row[2])
                for row in connection.exec_driver_sql(
                    f"PRAGMA index_info('{str(index[1])}')"
                )
            )
        )
    for required in (("context_key_hash",), ("grant_id",)):
        if required not in unique_sets:
            raise RuntimeError(
                "customer context thread binding schema is incomplete: "
                + required[0]
                + " uniqueness missing"
            )
    return True


def migrate_customer_context_thread_binding_schema(connection: Connection) -> bool:
    """Mirror phase 0044 and reject a partially created thread-binding table."""

    from .models import CustomerContextThreadBinding

    if validate_customer_context_thread_binding_schema(connection):
        return False
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "customer_context_grants" not in tables:
        return False
    CustomerContextThreadBinding.__table__.create(bind=connection, checkfirst=False)
    validate_customer_context_thread_binding_schema(connection)
    return True


CUSTOMER_ANALYSIS_TABLE_COLUMNS = {
    "customer_analysis_threads": {
        "id", "thread_id", "conversation_id", "provider_scope", "model",
        "external_conversation_id", "status", "analysis_state", "include_images",
        "debounce_seconds", "max_wait_seconds", "last_enqueued_message_id",
        "last_analyzed_message_id", "latest_artifact_version", "pending_since",
        "next_run_at", "last_started_at", "last_completed_at", "last_error_code",
        "last_error_message", "consent_policy_version", "consent_text_hash",
        "authorization_note", "confirmed_at", "revision", "paused_at",
        "created_at", "updated_at",
    },
    "customer_analysis_runs": {
        "id", "analysis_thread_id", "subscription_revision", "run_key", "status", "watermark_before",
        "watermark_after", "source_hash", "provider", "model",
        "external_response_id", "artifact_version", "message_count", "image_count",
        "error_code", "error_message", "created_at", "started_at", "completed_at",
    },
    "customer_analysis_events": {
        "id", "analysis_thread_id", "conversation_id", "message_id", "event_key",
        "status", "run_id", "attempt_count", "created_at", "processing_at",
        "completed_at",
    },
    "customer_analysis_artifacts": {
        "id", "analysis_thread_id", "version", "previous_artifact_id", "run_id",
        "watermark_before", "watermark_after", "source_hash", "content_hash",
        "content_json", "diff_json", "evidence_message_ids_json",
        "evidence_image_ids_json", "model", "external_response_id", "created_at",
    },
    "customer_analysis_mutation_requests": {
        "request_id", "operation", "payload_hash", "result_json", "created_at",
    },
}

CUSTOMER_ANALYSIS_TRIGGER_NAMES = {
    "trg_customer_analysis_thread_binding_insert",
    "trg_customer_analysis_thread_binding_update",
    "trg_global_agent_thread_analysis_binding_update",
    "trg_customer_analysis_event_scope_insert",
    "trg_customer_analysis_event_scope_update",
    "trg_customer_analysis_artifact_scope_insert",
    "trg_customer_analysis_artifact_no_update",
    "trg_customer_analysis_artifact_no_delete",
}

CUSTOMER_ANALYSIS_NULLABLE_COLUMNS = {
    "customer_analysis_threads": {
        "external_conversation_id", "last_enqueued_message_id",
        "last_analyzed_message_id", "pending_since", "next_run_at",
        "last_started_at", "last_completed_at", "paused_at",
    },
    "customer_analysis_runs": {
        "watermark_before", "artifact_version", "started_at", "completed_at",
    },
    "customer_analysis_events": {"run_id", "processing_at", "completed_at"},
    "customer_analysis_artifacts": {"previous_artifact_id", "watermark_before"},
    "customer_analysis_mutation_requests": set(),
}

CUSTOMER_ANALYSIS_DEFAULTS = {
    "customer_analysis_threads": {
        "provider_scope": "openai", "model": "", "status": "active",
        "analysis_state": "waiting", "include_images": "0",
        "debounce_seconds": "30", "max_wait_seconds": "60",
        "latest_artifact_version": "0", "last_error_code": "",
        "last_error_message": "", "consent_policy_version": "2",
        "authorization_note": "", "revision": "1",
    },
    "customer_analysis_runs": {
        "subscription_revision": "1", "status": "pending", "source_hash": "",
        "provider": "openai", "model": "", "external_response_id": "",
        "message_count": "0", "image_count": "0", "error_code": "",
        "error_message": "",
    },
    "customer_analysis_events": {"status": "pending", "attempt_count": "0"},
    "customer_analysis_artifacts": {
        "diff_json": "{}", "evidence_message_ids_json": "[]",
        "evidence_image_ids_json": "[]", "model": "",
        "external_response_id": "",
    },
    "customer_analysis_mutation_requests": {"result_json": "{}"},
}


def _customer_analysis_unique_sets(
    connection: Connection, table: str
) -> set[tuple[str, ...]]:
    result: set[tuple[str, ...]] = set()
    for index in connection.exec_driver_sql(f"PRAGMA index_list('{table}')"):
        if not bool(index[2]):
            continue
        columns = tuple(
            str(row[2])
            for row in connection.exec_driver_sql(
                f"PRAGMA index_info('{str(index[1])}')"
            )
        )
        result.add(columns)
    return result


def validate_customer_auto_analysis_schema(
    connection: Connection, *, require_triggers: bool = True
) -> bool:
    """Validate the SQLite 0041 structure beyond table and column presence."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    present = set(CUSTOMER_ANALYSIS_TABLE_COLUMNS).intersection(tables)
    if not present:
        return False
    if present != set(CUSTOMER_ANALYSIS_TABLE_COLUMNS):
        raise RuntimeError(
            "customer auto analysis schema is incomplete: "
            + ", ".join(sorted(set(CUSTOMER_ANALYSIS_TABLE_COLUMNS) - present))
        )
    for table, required_columns in CUSTOMER_ANALYSIS_TABLE_COLUMNS.items():
        info = list(connection.exec_driver_sql(f"PRAGMA table_info('{table}')"))
        columns = {str(row[1]) for row in info}
        missing = required_columns - columns
        if missing:
            raise RuntimeError(
                "customer auto analysis schema is incomplete: "
                f"{table} missing {', '.join(sorted(missing))}"
            )
        primary_keys = tuple(str(row[1]) for row in info if int(row[5]) > 0)
        expected_pk = (
            "request_id",
        ) if table == "customer_analysis_mutation_requests" else ("id",)
        if primary_keys != expected_pk:
            raise RuntimeError(
                f"customer auto analysis schema is incomplete: {table} primary key"
            )
        by_name = {str(row[1]): row for row in info}
        nullable = CUSTOMER_ANALYSIS_NULLABLE_COLUMNS[table]
        for column in required_columns:
            expected_not_null = column not in nullable
            if bool(by_name[column][3]) != expected_not_null:
                raise RuntimeError(
                    "customer auto analysis schema is incomplete: "
                    f"{table}.{column} nullable"
                )
        for column, expected_default in CUSTOMER_ANALYSIS_DEFAULTS[table].items():
            raw_default = by_name[column][4]
            actual_default = (
                str(raw_default).strip().strip("()").strip("'\"")
                if raw_default is not None
                else None
            )
            if actual_default != expected_default:
                raise RuntimeError(
                    "customer auto analysis schema is incomplete: "
                    f"{table}.{column} default"
                )

    expected_fks = {
        "customer_analysis_threads": {
            ("thread_id", "global_agent_threads", "id", "CASCADE"),
            ("conversation_id", "conversations", "id", "RESTRICT"),
        },
        "customer_analysis_runs": {
            ("analysis_thread_id", "customer_analysis_threads", "id", "CASCADE"),
        },
        "customer_analysis_events": {
            ("analysis_thread_id", "customer_analysis_threads", "id", "CASCADE"),
            ("conversation_id", "conversations", "id", "RESTRICT"),
            ("message_id", "messages", "id", "RESTRICT"),
            ("run_id", "customer_analysis_runs", "id", "SET NULL"),
        },
        "customer_analysis_artifacts": {
            ("analysis_thread_id", "customer_analysis_threads", "id", "RESTRICT"),
            ("previous_artifact_id", "customer_analysis_artifacts", "id", "RESTRICT"),
            ("run_id", "customer_analysis_runs", "id", "RESTRICT"),
        },
    }
    for table, expected in expected_fks.items():
        actual = {
            (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
            for row in connection.exec_driver_sql(f"PRAGMA foreign_key_list('{table}')")
        }
        if not expected.issubset(actual):
            raise RuntimeError(
                f"customer auto analysis schema is incomplete: {table} foreign keys"
            )

    expected_unique = {
        "customer_analysis_threads": {
            ("thread_id",), ("conversation_id",), ("external_conversation_id",),
        },
        "customer_analysis_runs": {("run_key",)},
        "customer_analysis_events": {
            ("event_key",), ("analysis_thread_id", "message_id"),
        },
        "customer_analysis_artifacts": {
            ("run_id",), ("analysis_thread_id", "version"),
        },
    }
    for table, expected in expected_unique.items():
        if not expected.issubset(_customer_analysis_unique_sets(connection, table)):
            raise RuntimeError(
                f"customer auto analysis schema is incomplete: {table} unique constraints"
            )

    required_indexes = {
        "idx_customer_analysis_thread_due",
        "idx_customer_analysis_run_thread_created",
        "idx_customer_analysis_event_pending",
        "idx_customer_analysis_artifact_latest",
    }
    indexes = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    if not required_indexes.issubset(indexes):
        raise RuntimeError("customer auto analysis schema is incomplete: required indexes")
    if require_triggers:
        triggers = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        if not CUSTOMER_ANALYSIS_TRIGGER_NAMES.issubset(triggers):
            raise RuntimeError("customer auto analysis schema is incomplete: safety triggers")
    return True


def _create_customer_auto_analysis_triggers(connection: Connection) -> None:
    statements = (
        """CREATE TRIGGER IF NOT EXISTS trg_customer_analysis_thread_binding_insert
        BEFORE INSERT ON customer_analysis_threads
        WHEN NOT EXISTS (
          SELECT 1 FROM global_agent_threads AS thread
          WHERE thread.id = NEW.thread_id
            AND thread.context_scope = 'customer_conversation'
            AND thread.conversation_id = NEW.conversation_id
        )
        BEGIN SELECT RAISE(ABORT, 'customer analysis binding mismatch'); END""",
        """CREATE TRIGGER trg_customer_analysis_thread_binding_update
        BEFORE UPDATE OF thread_id, conversation_id ON customer_analysis_threads
        WHEN NOT EXISTS (
          SELECT 1 FROM global_agent_threads AS thread
          WHERE thread.id = NEW.thread_id
            AND thread.context_scope = 'customer_conversation'
            AND thread.conversation_id = NEW.conversation_id
        )
        BEGIN SELECT RAISE(ABORT, 'customer analysis binding mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_global_agent_thread_analysis_binding_update
        BEFORE UPDATE OF context_scope, conversation_id ON global_agent_threads
        WHEN EXISTS (
          SELECT 1 FROM customer_analysis_threads AS analysis
          WHERE analysis.thread_id = OLD.id
            AND analysis.status = 'active'
            AND (NEW.context_scope <> 'customer_conversation'
              OR NEW.conversation_id IS NOT analysis.conversation_id)
        )
        BEGIN SELECT RAISE(ABORT, 'active customer analysis binding must be preserved'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_customer_analysis_event_scope_insert
        BEFORE INSERT ON customer_analysis_events
        WHEN NOT EXISTS (
          SELECT 1 FROM messages AS message
          WHERE message.id = NEW.message_id
            AND message.conversation_id = NEW.conversation_id
        ) OR NOT EXISTS (
          SELECT 1 FROM customer_analysis_threads AS analysis
          WHERE analysis.id = NEW.analysis_thread_id
            AND analysis.conversation_id = NEW.conversation_id
        ) OR (NEW.run_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM customer_analysis_runs AS run
          WHERE run.id = NEW.run_id
            AND run.analysis_thread_id = NEW.analysis_thread_id
        ))
        BEGIN SELECT RAISE(ABORT, 'customer analysis event scope mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_customer_analysis_event_scope_update
        BEFORE UPDATE OF analysis_thread_id, conversation_id, message_id, run_id
        ON customer_analysis_events
        WHEN NOT EXISTS (
          SELECT 1 FROM messages AS message
          WHERE message.id = NEW.message_id
            AND message.conversation_id = NEW.conversation_id
        ) OR NOT EXISTS (
          SELECT 1 FROM customer_analysis_threads AS analysis
          WHERE analysis.id = NEW.analysis_thread_id
            AND analysis.conversation_id = NEW.conversation_id
        ) OR (NEW.run_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM customer_analysis_runs AS run
          WHERE run.id = NEW.run_id
            AND run.analysis_thread_id = NEW.analysis_thread_id
        ))
        BEGIN SELECT RAISE(ABORT, 'customer analysis event scope mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_customer_analysis_artifact_scope_insert
        BEFORE INSERT ON customer_analysis_artifacts
        WHEN NOT EXISTS (
          SELECT 1 FROM customer_analysis_runs AS run
          WHERE run.id = NEW.run_id
            AND run.analysis_thread_id = NEW.analysis_thread_id
        ) OR (NEW.previous_artifact_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM customer_analysis_artifacts AS previous
          WHERE previous.id = NEW.previous_artifact_id
            AND previous.analysis_thread_id = NEW.analysis_thread_id
        ))
        BEGIN SELECT RAISE(ABORT, 'customer analysis artifact scope mismatch'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_customer_analysis_artifact_no_update
        BEFORE UPDATE ON customer_analysis_artifacts
        BEGIN SELECT RAISE(ABORT, 'customer analysis artifacts are immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_customer_analysis_artifact_no_delete
        BEFORE DELETE ON customer_analysis_artifacts
        BEGIN SELECT RAISE(ABORT, 'customer analysis artifacts are immutable'); END""",
    )
    for name in sorted(CUSTOMER_ANALYSIS_TRIGGER_NAMES):
        connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{name}"')
    for statement in statements:
        connection.exec_driver_sql(statement)


def migrate_customer_auto_analysis_schema(connection: Connection) -> bool:
    """Mirror phase 0041 and reject every partially created analysis domain."""

    from .models import (
        CustomerAnalysisArtifact,
        CustomerAnalysisEvent,
        CustomerAnalysisMutationRequest,
        CustomerAnalysisRun,
        CustomerAnalysisThread,
    )

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if validate_customer_auto_analysis_schema(connection, require_triggers=False):
        _create_customer_auto_analysis_triggers(connection)
        validate_customer_auto_analysis_schema(connection)
        return False
    required_base = {"global_agent_threads", "conversations", "messages"}
    if not required_base.issubset(tables):
        return False

    for table in (
        CustomerAnalysisThread.__table__,
        CustomerAnalysisRun.__table__,
        CustomerAnalysisEvent.__table__,
        CustomerAnalysisArtifact.__table__,
        CustomerAnalysisMutationRequest.__table__,
    ):
        table.create(bind=connection, checkfirst=False)
    _create_customer_auto_analysis_triggers(connection)
    validate_customer_auto_analysis_schema(connection)
    return True


def seed_codex_verification_data(connection: Connection) -> bool:
    """Materialize legacy time and plan points exactly once after create_all."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    required = {
        "business_tasks",
        "codex_acceptance_points",
        "codex_acceptance_mutation_requests",
        "project_time_entries",
    }
    if not required.issubset(tables):
        return False
    marker = "migration:20260818_0029"
    if connection.exec_driver_sql(
        "SELECT 1 FROM codex_acceptance_mutation_requests WHERE request_id = ?",
        (marker,),
    ).first():
        return False

    now = datetime.now(timezone.utc)
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql("PRAGMA table_info(business_tasks)")
    }
    if not {
        "codex_plan_id",
        "acceptance_points_json",
        "codex_execution_status",
        "actual_hours",
    }.issubset(columns):
        return False
    rows = connection.exec_driver_sql(
        "SELECT id, project_id, codex_plan_id, acceptance_points_json, "
        "codex_execution_status, actual_hours FROM business_tasks"
    ).mappings()
    for row in rows:
        task_id = str(row["id"])
        project_id = str(row["project_id"])
        actual_hours = float(row["actual_hours"] or 0)
        if actual_hours > 0:
            connection.exec_driver_sql(
                "INSERT OR IGNORE INTO project_time_entries "
                "(id, project_id, task_id, category, source, hours, note, "
                "occurred_at, created_at) VALUES (?, ?, ?, 'development', "
                "'legacy_import', ?, '第四阶段迁移前已存在的实际工时', ?, ?)",
                (
                    "legacy-time-" + hashlib.sha256(task_id.encode()).hexdigest()[:32],
                    project_id,
                    task_id,
                    actual_hours,
                    now,
                    now,
                ),
            )
        try:
            points = json.loads(str(row["acceptance_points_json"] or "[]"))
        except (TypeError, ValueError):
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
                if str(row["codex_execution_status"] or "todo") == "implemented"
                else "pending"
            )
            connection.exec_driver_sql(
                "INSERT OR IGNORE INTO codex_acceptance_points "
                "(id, project_id, task_id, plan_id, point_key, title, "
                "verification_type, status, waived_counts, waiver_reason, active, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, '', 1, ?, ?)",
                (
                    point_id,
                    project_id,
                    task_id,
                    row["codex_plan_id"],
                    point_key,
                    str(raw.get("title") or point_key)[:300],
                    str(raw.get("verification_type") or "manual_test")[:32],
                    status,
                    now,
                    now,
                ),
            )
    connection.exec_driver_sql(
        "INSERT INTO codex_acceptance_mutation_requests "
        "(request_id, operation, payload_hash, result_json, created_at) "
        "VALUES (?, 'migration', ?, '{}', ?)",
        (marker, hashlib.sha256(marker.encode()).hexdigest(), now),
    )
    return True


def migrate_project_product_attribution_schema(connection: Connection) -> bool:
    """Add the nullable source-listing relationship to legacy project rows."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "business_projects" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(business_projects)"
        )
    }
    changed = False
    if "item_id" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE business_projects ADD COLUMN item_id INTEGER REFERENCES items(id)"
        )
        changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_business_projects_item_id "
        "ON business_projects(item_id)"
    )
    return changed


def migrate_product_plan_explanation_schema(connection: Connection) -> bool:
    """Add structured, non-sensitive plan change factors to legacy SQLite."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    changed = False
    for table in ("product_operating_plans", "product_operating_plan_slots"):
        if table not in tables:
            continue
        columns = {
            str(row[1])
            for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
        }
        if "change_factors_json" in columns:
            continue
        connection.exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN change_factors_json TEXT NOT NULL DEFAULT '[]'"
        )
        changed = True
    return changed


def migrate_product_traffic_v24_schema(connection: Connection) -> bool:
    """Apply the additive exposure-v2.4 columns to an existing SQLite store.

    Local startup historically uses ``metadata.create_all`` instead of running
    Alembic on every launch.  Adding the columns before SQLAlchemy creates the
    new indexes keeps both startup paths equivalent and preserves all batches.
    """

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    changed = False
    if "product_traffic_batches" in tables:
        columns = {
            str(row[1])
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(product_traffic_batches)"
            )
        }
        if "baseline_prepared_at" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE product_traffic_batches "
                "ADD COLUMN baseline_prepared_at DATETIME"
            )
            changed = True
    if "product_traffic_batch_items" in tables:
        columns = {
            str(row[1])
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(product_traffic_batch_items)"
            )
        }
        if "baseline_source" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE product_traffic_batch_items "
                "ADD COLUMN baseline_source VARCHAR(32) NOT NULL "
                "DEFAULT 'legacy_snapshot'"
            )
            changed = True
    if "product_operating_plan_slots" in tables:
        columns = {
            str(row[1])
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(product_operating_plan_slots)"
            )
        }
        additions = (
            ("source_batch_id", "VARCHAR(128)"),
            ("availability_at", "DATETIME"),
            ("is_new_spend", "BOOLEAN NOT NULL DEFAULT 0"),
            ("rotation_summary_json", "TEXT NOT NULL DEFAULT '{}'"),
        )
        for name, definition in additions:
            if name not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE product_operating_plan_slots ADD COLUMN {name} {definition}"
                )
                changed = True
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS "
            "ix_product_operating_plan_slots_source_batch_id "
            "ON product_operating_plan_slots(source_batch_id)"
        )
    return changed


def migrate_product_traffic_overlap_recording_schema(connection: Connection) -> bool:
    """Add factual overlap-recording state without rewriting existing batches."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "product_traffic_batches" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(product_traffic_batches)"
        )
    }
    changed = False
    additions = (
        ("recording_mode", "VARCHAR(32) NOT NULL DEFAULT 'standard'"),
        ("attribution_status", "VARCHAR(32) NOT NULL DEFAULT 'clean'"),
    )
    for name, definition in additions:
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE product_traffic_batches ADD COLUMN {name} {definition}"
            )
            changed = True
    return changed


def migrate_product_traffic_baseline_invalidation_schema(
    connection: Connection,
) -> bool:
    """Add terminal baseline-invalid state without rewriting traffic facts."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "product_traffic_batches" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(product_traffic_batches)"
        )
    }
    changed = False
    additions = (
        ("invalidated_at", "DATETIME"),
        ("invalidation_reason", "VARCHAR(64)"),
    )
    for name, definition in additions:
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE product_traffic_batches ADD COLUMN {name} {definition}"
            )
            changed = True
    return changed


def migrate_product_traffic_checkpoint_collection_schema(
    connection: Connection,
) -> bool:
    """Add durable, restart-safe exposure checkpoint work queues."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "product_traffic_batches" not in tables:
        return False
    changed = False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(product_traffic_batches)"
        )
    }
    if "checkpoint_collection_mode" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE product_traffic_batches "
            "ADD COLUMN checkpoint_collection_mode VARCHAR(32) NOT NULL DEFAULT 'auto'"
        )
        changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS "
        "ix_product_traffic_batches_checkpoint_collection_mode "
        "ON product_traffic_batches(checkpoint_collection_mode)"
    )
    if "product_traffic_checkpoint_jobs" not in tables:
        connection.exec_driver_sql(
            "CREATE TABLE product_traffic_checkpoint_jobs ("
            "id VARCHAR(128) NOT NULL PRIMARY KEY, "
            "batch_id VARCHAR(128) NOT NULL REFERENCES product_traffic_batches(id), "
            "checkpoint VARCHAR(16) NOT NULL, "
            "scheduled_for DATETIME NOT NULL, "
            "status VARCHAR(32) NOT NULL DEFAULT 'scheduled', "
            "attempt_count INTEGER NOT NULL DEFAULT 0, "
            "collected_count INTEGER NOT NULL DEFAULT 0, "
            "total_count INTEGER NOT NULL DEFAULT 0, "
            "started_at DATETIME, captured_at DATETIME, completed_at DATETIME, "
            "last_attempt_at DATETIME, capture_delay_minutes INTEGER, "
            "last_error_code VARCHAR(64), last_error_detail TEXT NOT NULL DEFAULT '', "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
            "CONSTRAINT uq_product_traffic_checkpoint_job UNIQUE(batch_id, checkpoint)"
            ")"
        )
        changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_product_traffic_checkpoint_jobs_batch_id "
        "ON product_traffic_checkpoint_jobs(batch_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_product_traffic_checkpoint_jobs_checkpoint "
        "ON product_traffic_checkpoint_jobs(checkpoint)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_product_traffic_checkpoint_jobs_scheduled_for "
        "ON product_traffic_checkpoint_jobs(scheduled_for)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_product_traffic_checkpoint_jobs_status "
        "ON product_traffic_checkpoint_jobs(status)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_product_traffic_checkpoint_jobs_due "
        "ON product_traffic_checkpoint_jobs(status, scheduled_for)"
    )
    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "product_traffic_checkpoint_job_items" not in tables:
        connection.exec_driver_sql(
            "CREATE TABLE product_traffic_checkpoint_job_items ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "job_id VARCHAR(128) NOT NULL REFERENCES product_traffic_checkpoint_jobs(id), "
            "item_id INTEGER NOT NULL REFERENCES items(id), "
            "status VARCHAR(32) NOT NULL DEFAULT 'pending', "
            "captured_at DATETIME, error_code VARCHAR(64), "
            "error_detail TEXT NOT NULL DEFAULT '', "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
            "CONSTRAINT uq_product_traffic_checkpoint_job_item UNIQUE(job_id, item_id)"
            ")"
        )
        changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_product_traffic_checkpoint_job_items_job_id "
        "ON product_traffic_checkpoint_job_items(job_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_product_traffic_checkpoint_job_items_item_id "
        "ON product_traffic_checkpoint_job_items(item_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_product_traffic_checkpoint_job_items_status "
        "ON product_traffic_checkpoint_job_items(status)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_product_traffic_checkpoint_job_items_status "
        "ON product_traffic_checkpoint_job_items(job_id, status)"
    )
    return changed


def migrate_product_traffic_48h_schema(connection: Connection) -> bool:
    """Add the phase-0032 protocol column and reject malformed partial state."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "product_traffic_batches" not in tables:
        return False
    rows = list(
        connection.exec_driver_sql("PRAGMA table_info(product_traffic_batches)")
    )
    column = next((row for row in rows if str(row[1]) == "observation_window_hours"), None)
    if column is not None:
        column_type = str(column[2] or "").upper()
        not_null = bool(column[3])
        default = str(column[4] or "").strip("'\"")
        if column_type == "INTEGER" and not_null and default == "72":
            return False
        raise RuntimeError(
            "48h traffic protocol schema is incomplete: observation_window_hours "
            "must be INTEGER NOT NULL DEFAULT 72"
        )
    connection.exec_driver_sql(
        "ALTER TABLE product_traffic_batches ADD COLUMN "
        "observation_window_hours INTEGER NOT NULL DEFAULT 72"
    )
    return True


def migrate_business_recommendation_feedback_schema(connection: Connection) -> bool:
    """Add the recommendation execution-loop columns to legacy SQLite data."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    table = "business_analysis_recommendations"
    if table not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
    }
    additions = (
        ("target_scope", "VARCHAR(32) NOT NULL DEFAULT 'domain'"),
        ("accepted_at", "DATETIME"),
        ("started_at", "DATETIME"),
        ("observe_until", "DATETIME"),
        ("completed_at", "DATETIME"),
        ("baseline_metrics_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("result_metrics_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("outcome", "VARCHAR(32)"),
        ("actual_cost", "FLOAT"),
        ("actual_hours", "FLOAT"),
        ("user_conclusion", "TEXT NOT NULL DEFAULT ''"),
        ("execution_ref_type", "VARCHAR(64)"),
        ("execution_ref_id", "VARCHAR(128)"),
    )
    changed = False
    for name, definition in additions:
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
            )
            changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS "
        "ix_business_analysis_recommendations_observe_until "
        "ON business_analysis_recommendations(observe_until)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_business_analysis_recommendations_outcome "
        "ON business_analysis_recommendations(outcome)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS "
        "idx_business_analysis_recommendation_lifecycle "
        "ON business_analysis_recommendations(status, observe_until)"
    )
    return changed


PROJECT_TABLE = "business_projects"
TEMP_PROJECT_TABLE = "business_projects__personal_upgrade"


def migrate_project_change_order_schema(connection: Connection) -> bool:
    """Add append-only project change orders and link their payment nodes.

    The migration is deliberately additive. Existing contracts and payment
    nodes keep their original meaning, while future paid scope additions gain
    an explicit audit source instead of being inferred from payment totals.
    """

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    required = {"business_projects", "business_customers", "payment_nodes"}
    if not required.issubset(tables):
        return False

    changed = False
    if "project_change_orders" not in tables:
        connection.exec_driver_sql(
            "CREATE TABLE project_change_orders ("
            "id VARCHAR(128) NOT NULL PRIMARY KEY, "
            "project_id VARCHAR(128) NOT NULL REFERENCES business_projects(id), "
            "customer_id VARCHAR(128) NOT NULL REFERENCES business_customers(id), "
            "title VARCHAR(300) NOT NULL, "
            "amount FLOAT NOT NULL, "
            "confirmed_at VARCHAR(64) NOT NULL DEFAULT '', "
            "status VARCHAR(32) NOT NULL DEFAULT 'confirmed', "
            "notes TEXT NOT NULL DEFAULT '', "
            "request_id VARCHAR(128) NOT NULL UNIQUE, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        changed = True

    payment_columns = {
        str(row[1])
        for row in connection.exec_driver_sql("PRAGMA table_info(payment_nodes)")
    }
    if "change_order_id" not in payment_columns:
        connection.exec_driver_sql(
            "ALTER TABLE payment_nodes ADD COLUMN change_order_id VARCHAR(128) "
            "REFERENCES project_change_orders(id)"
        )
        changed = True

    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_project_change_orders_project_id "
        "ON project_change_orders(project_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_project_change_orders_customer_id "
        "ON project_change_orders(customer_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_project_change_orders_status "
        "ON project_change_orders(status)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_project_change_orders_request_id "
        "ON project_change_orders(request_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_project_change_orders_created_at "
        "ON project_change_orders(created_at)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_payment_nodes_change_order_id "
        "ON payment_nodes(change_order_id)"
    )
    return changed


def migrate_product_browse_accounting_schema(connection: Connection) -> bool:
    """Split platform browse totals from operating browse totals.

    The historical ``browse_count`` value came directly from Xianyu. During the
    one-time migration it becomes the raw audit value, while one successful
    remote detail read per stored snapshot is excluded from the operating
    count. The column-presence gate makes the backfill idempotent at startup.
    """

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "product_daily_snapshots" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(product_daily_snapshots)"
        )
    }
    had_raw = "raw_browse_count" in columns
    had_excluded = "collection_views_excluded" in columns
    if had_raw and had_excluded:
        return False
    if not had_raw:
        connection.exec_driver_sql(
            "ALTER TABLE product_daily_snapshots ADD COLUMN "
            "raw_browse_count INTEGER NOT NULL DEFAULT 0"
        )
    if not had_excluded:
        connection.exec_driver_sql(
            "ALTER TABLE product_daily_snapshots ADD COLUMN "
            "collection_views_excluded INTEGER NOT NULL DEFAULT 0"
        )

    rows = list(
        connection.exec_driver_sql(
            "SELECT id, item_id, source, browse_count, raw_browse_count, "
            "collection_views_excluded FROM product_daily_snapshots "
            "ORDER BY item_id, snapshot_date, captured_at, id"
        )
    )
    excluded_by_item: dict[int, int] = {}
    for row in rows:
        item_id = int(row[1])
        prior_excluded = excluded_by_item.get(item_id, 0)
        if str(row[2]) in {"remote_daily", "remote_manual"}:
            prior_excluded += 1
        if had_raw:
            raw_browse = max(0, int(row[4] or 0))
        elif had_excluded:
            raw_browse = max(0, int(row[3] or 0) + int(row[5] or 0))
        else:
            raw_browse = max(0, int(row[3] or 0))
        connection.exec_driver_sql(
            "UPDATE product_daily_snapshots SET raw_browse_count = ?, "
            "collection_views_excluded = ?, browse_count = ? WHERE id = ?",
            (
                raw_browse,
                prior_excluded,
                max(0, raw_browse - prior_excluded),
                row[0],
            ),
        )
        excluded_by_item[item_id] = prior_excluded
    return True


def backfill_product_collection_attempts(connection: Connection) -> int:
    """Expose old daily runs in the append-only operation log.

    Historical per-item outcomes were not stored, so this deliberately creates
    only the attempt summary. It never invents child item results and is safe to
    call repeatedly during local startup.
    """

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if not {
        "product_collection_runs",
        "product_collection_attempts",
    }.issubset(tables):
        return 0
    rows = list(
        connection.exec_driver_sql(
            "SELECT r.id, r.run_date, r.trigger, r.status, r.monitored_count, "
            "r.collected_count, r.failed_count, r.detail, r.started_at, r.finished_at "
            "FROM product_collection_runs r "
            "LEFT JOIN product_collection_attempts a ON a.daily_run_id = r.id "
            "WHERE a.id IS NULL ORDER BY r.run_date, r.started_at"
        )
    )
    for row in rows:
        connection.exec_driver_sql(
            "INSERT INTO product_collection_attempts ("
            "id, run_date, daily_run_id, trigger, requested_item_id, status, "
            "monitored_count, collected_count, failed_count, skipped_count, detail, "
            "started_at, finished_at) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 0, ?, ?, ?)",
            (
                f"legacy-attempt-{row[0]}",
                row[1],
                row[0],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
            ),
        )
    return len(rows)


def migrate_product_monitor_schema(connection: Connection) -> bool:
    """Add ownership and safe per-item collection diagnostics."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "product_monitors" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql("PRAGMA table_info(product_monitors)")
    }
    changed = False
    additions = (
        ("ownership_status", "VARCHAR(32) NOT NULL DEFAULT 'pending'"),
        ("ownership_source", "VARCHAR(64) NOT NULL DEFAULT 'unverified'"),
        ("last_attempt_at", "DATETIME"),
        ("last_collection_status", "VARCHAR(32) NOT NULL DEFAULT 'waiting'"),
        ("last_error_code", "VARCHAR(64)"),
        ("last_error_detail", "VARCHAR(500)"),
    )
    for name, definition in additions:
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE product_monitors ADD COLUMN {name} {definition}"
            )
            changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_product_monitors_ownership_status "
        "ON product_monitors(ownership_status)"
    )
    return changed


def migrate_personal_project_schema(connection: Connection) -> bool:
    """Allow projects without a customer and persist their personal/client kind.

    SQLite cannot remove a NOT NULL constraint in place, so existing local
    databases are rebuilt with the same columns and foreign keys. The caller
    must disable SQLite foreign-key enforcement for the duration of this
    transaction; a foreign-key check is performed after it is re-enabled.
    """

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if PROJECT_TABLE not in tables:
        return False

    column_rows = list(connection.exec_driver_sql(f"PRAGMA table_info({PROJECT_TABLE})"))
    columns = {str(row[1]): row for row in column_rows}
    customer_is_required = bool(columns.get("customer_id") and columns["customer_id"][3])
    has_project_kind = "project_kind" in columns

    if not customer_is_required:
        if not has_project_kind:
            connection.exec_driver_sql(
                "ALTER TABLE business_projects ADD COLUMN project_kind "
                "VARCHAR(32) NOT NULL DEFAULT 'client'"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_business_projects_project_kind "
                "ON business_projects(project_kind)"
            )
            return True
        return False

    project_kind_select = (
        "CASE WHEN project_kind = 'personal' THEN 'personal' ELSE 'client' END"
        if has_project_kind
        else "'client'"
    )
    connection.exec_driver_sql(f"DROP TABLE IF EXISTS {TEMP_PROJECT_TABLE}")
    connection.exec_driver_sql(
        f"""
        CREATE TABLE {TEMP_PROJECT_TABLE} (
            id VARCHAR(128) NOT NULL,
            name VARCHAR(300) NOT NULL,
            customer_id VARCHAR(128),
            project_kind VARCHAR(32) NOT NULL DEFAULT 'client',
            lead_id VARCHAR(128),
            conversation_id INTEGER,
            requirement_version_id INTEGER,
            quote_id VARCHAR(128),
            total_amount FLOAT NOT NULL,
            start_date VARCHAR(32) NOT NULL,
            due_date VARCHAR(32) NOT NULL,
            progress INTEGER NOT NULL,
            status VARCHAR(32) NOT NULL,
            type VARCHAR(100) NOT NULL,
            estimated_hours FLOAT NOT NULL,
            accent VARCHAR(32) NOT NULL,
            notes TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(customer_id) REFERENCES business_customers (id),
            FOREIGN KEY(lead_id) REFERENCES sales_leads (id),
            FOREIGN KEY(conversation_id) REFERENCES conversations (id),
            FOREIGN KEY(requirement_version_id) REFERENCES requirement_document_versions (id)
        )
        """
    )
    connection.exec_driver_sql(
        f"""
        INSERT INTO {TEMP_PROJECT_TABLE} (
            id, name, customer_id, project_kind, lead_id, conversation_id,
            requirement_version_id, quote_id, total_amount, start_date,
            due_date, progress, status, type, estimated_hours, accent, notes,
            created_at, updated_at
        )
        SELECT
            id, name, customer_id, {project_kind_select}, lead_id,
            conversation_id, requirement_version_id, quote_id, total_amount,
            start_date, due_date, progress, status, type, estimated_hours,
            accent, notes, created_at, updated_at
        FROM {PROJECT_TABLE}
        """
    )
    connection.exec_driver_sql(f"DROP TABLE {PROJECT_TABLE}")
    connection.exec_driver_sql(
        f"ALTER TABLE {TEMP_PROJECT_TABLE} RENAME TO {PROJECT_TABLE}"
    )
    for name, column in (
        ("ix_business_projects_name", "name"),
        ("ix_business_projects_customer_id", "customer_id"),
        ("ix_business_projects_project_kind", "project_kind"),
        ("ix_business_projects_lead_id", "lead_id"),
        ("ix_business_projects_conversation_id", "conversation_id"),
        ("ix_business_projects_status", "status"),
    ):
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {name} ON {PROJECT_TABLE}({column})"
        )
    return True


def migrate_requirement_blueprint_schema(connection: Connection) -> bool:
    """Add the customer requirement-blueprint columns to legacy SQLite data."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "requirement_document_versions" not in tables:
        return False
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(requirement_document_versions)"
        )
    }
    changed = False
    additions = (
        ("case_id", "VARCHAR(128)"),
        ("schema_version", "VARCHAR(16) NOT NULL DEFAULT '1.0'"),
        ("source_type", "VARCHAR(32) NOT NULL DEFAULT 'codex_cli'"),
        ("source_label", "VARCHAR(255) NOT NULL DEFAULT 'Codex 生成'"),
        ("imported_at", "DATETIME"),
    )
    for name, definition in additions:
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE requirement_document_versions ADD COLUMN {name} {definition}"
            )
            changed = True
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_requirement_document_versions_case_id "
        "ON requirement_document_versions(case_id)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_requirement_case_version_partial "
        "ON requirement_document_versions(case_id, version) WHERE case_id IS NOT NULL"
    )
    if "requirement_cases" in tables:
        case_columns = {
            str(row[1])
            for row in connection.exec_driver_sql("PRAGMA table_info(requirement_cases)")
        }
        if "item_id" not in case_columns:
            connection.exec_driver_sql(
                "ALTER TABLE requirement_cases ADD COLUMN item_id INTEGER "
                "REFERENCES items(id)"
            )
            changed = True
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_requirement_cases_item_id "
            "ON requirement_cases(item_id)"
        )
    if "ai_generation_tasks" in tables:
        task_columns = {
            str(row[1])
            for row in connection.exec_driver_sql("PRAGMA table_info(ai_generation_tasks)")
        }
        if "model" not in task_columns:
            connection.exec_driver_sql(
                "ALTER TABLE ai_generation_tasks ADD COLUMN model VARCHAR(128)"
            )
            changed = True
    return changed


def backfill_requirement_cases(connection: Connection) -> int:
    """Safely group old Codex versions only when one customer mapping is certain."""

    tables = {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    required = {
        "requirement_cases",
        "requirement_case_sources",
        "requirement_document_versions",
        "business_customers",
        "sales_leads",
        "customer_channel_identities",
        "conversations",
        "messages",
    }
    if not required.issubset(tables):
        return 0
    conversation_ids = [
        int(row[0])
        for row in connection.exec_driver_sql(
            "SELECT DISTINCT conversation_id FROM requirement_document_versions "
            "WHERE case_id IS NULL AND conversation_id IS NOT NULL"
        )
    ]
    created = 0
    now = datetime.now(timezone.utc).isoformat()
    for conversation_id in conversation_ids:
        customer_rows = list(
            connection.exec_driver_sql(
                "SELECT DISTINCT customer_id FROM ("
                "SELECT customer_id FROM sales_leads WHERE conversation_id = ? "
                "UNION ALL "
                "SELECT customer_id FROM customer_channel_identities WHERE conversation_id = ?"
                ") WHERE customer_id IS NOT NULL AND customer_id != ''",
                (conversation_id, conversation_id),
            )
        )
        customer_ids = {str(row[0]) for row in customer_rows}
        if len(customer_ids) != 1:
            continue
        customer_id = next(iter(customer_ids))
        latest = connection.exec_driver_sql(
            "SELECT title, readiness, MAX(version) FROM requirement_document_versions "
            "WHERE conversation_id = ?",
            (conversation_id,),
        ).first()
        if not latest:
            continue
        lead = connection.exec_driver_sql(
            "SELECT id FROM sales_leads WHERE conversation_id = ? LIMIT 1",
            (conversation_id,),
        ).first()
        item_id = connection.exec_driver_sql(
            "SELECT item_id FROM conversations WHERE id = ? LIMIT 1",
            (conversation_id,),
        ).scalar()
        case_id = f"reqcase-{uuid4()}"
        connection.exec_driver_sql(
            "INSERT INTO requirement_cases "
            "(id, customer_id, item_id, title, status, current_version, lead_id, project_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (
                case_id,
                customer_id,
                item_id,
                str(latest[0] or "历史需求"),
                str(latest[1] or "clarifying"),
                int(latest[2] or 0),
                str(lead[0]) if lead else None,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "UPDATE requirement_document_versions SET case_id = ?, "
            "schema_version = COALESCE(NULLIF(schema_version, ''), '1.0'), "
            "source_type = COALESCE(NULLIF(source_type, ''), 'codex_cli'), "
            "source_label = COALESCE(NULLIF(source_label, ''), 'Codex 生成') "
            "WHERE conversation_id = ? AND case_id IS NULL",
            (case_id, conversation_id),
        )
        max_message = connection.exec_driver_sql(
            "SELECT MAX(id) FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).scalar()
        connection.exec_driver_sql(
            "INSERT INTO requirement_case_sources "
            "(id, case_id, conversation_id, last_exported_message_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"reqsource-{uuid4()}",
                case_id,
                conversation_id,
                max_message,
                now,
                now,
            ),
        )
        created += 1

    # Older customer-level cases did not persist their listing. Bind only when
    # every known source conversation points to the same non-null item.
    case_rows = list(
        connection.exec_driver_sql(
            "SELECT id, customer_id FROM requirement_cases WHERE item_id IS NULL"
        )
    )
    for case_id, customer_id in case_rows:
        source_count = int(
            connection.exec_driver_sql(
                "SELECT COUNT(*) FROM requirement_case_sources WHERE case_id = ?",
                (case_id,),
            ).scalar()
            or 0
        )
        item_rows = list(
            connection.exec_driver_sql(
                "SELECT DISTINCT c.item_id FROM requirement_case_sources s "
                "JOIN conversations c ON c.id = s.conversation_id "
                "WHERE s.case_id = ? AND c.item_id IS NOT NULL",
                (case_id,),
            )
        )
        item_ids = {int(row[0]) for row in item_rows}
        item_source_count = int(
            connection.exec_driver_sql(
                "SELECT COUNT(*) FROM requirement_case_sources s "
                "JOIN conversations c ON c.id = s.conversation_id "
                "WHERE s.case_id = ? AND c.item_id IS NOT NULL",
                (case_id,),
            ).scalar()
            or 0
        )
        if source_count > 0 and item_source_count == source_count and len(item_ids) == 1:
            connection.exec_driver_sql(
                "UPDATE requirement_cases SET item_id = ? WHERE id = ?",
                (next(iter(item_ids)), case_id),
            )

    if "customer_item_links" in tables:
        linked_cases = list(
            connection.exec_driver_sql(
                "SELECT id, customer_id, item_id FROM requirement_cases "
                "WHERE item_id IS NOT NULL"
            )
        )
        for case_id, customer_id, item_id in linked_cases:
            source_conversation_id = connection.exec_driver_sql(
                "SELECT conversation_id FROM requirement_case_sources "
                "WHERE case_id = ? ORDER BY created_at ASC LIMIT 1",
                (case_id,),
            ).scalar()
            exists = connection.exec_driver_sql(
                "SELECT 1 FROM customer_item_links "
                "WHERE customer_id = ? AND item_id = ? LIMIT 1",
                (customer_id, item_id),
            ).first()
            if not exists:
                connection.exec_driver_sql(
                    "INSERT INTO customer_item_links "
                    "(id, customer_id, item_id, source_conversation_id, source_type, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'requirement_backfill', ?, ?)",
                    (
                        f"customer-item-{uuid4()}",
                        customer_id,
                        item_id,
                        source_conversation_id,
                        now,
                        now,
                    ),
                )
    return created
