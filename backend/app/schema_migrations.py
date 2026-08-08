from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.engine import Connection


PROJECT_TABLE = "business_projects"
TEMP_PROJECT_TABLE = "business_projects__personal_upgrade"


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
        case_id = f"reqcase-{uuid4()}"
        connection.exec_driver_sql(
            "INSERT INTO requirement_cases "
            "(id, customer_id, title, status, current_version, lead_id, project_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (
                case_id,
                customer_id,
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
    return created
