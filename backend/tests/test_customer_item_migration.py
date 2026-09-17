from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from backend.app.database import Database
from backend.app.models import (
    BusinessCustomer,
    Conversation,
    Item,
    RequirementCase,
    RequirementCaseSource,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_customer_item_alembic_migration_backfills_clear_listing(tmp_path) -> None:
    database_path = tmp_path / "migration.db"
    database = Database(f"sqlite:///{database_path}")
    database.create_all()
    with database.session() as session:
        customer = BusinessCustomer(id="customer-probe", name="迁移测试客户")
        item = Item(external_id="item-probe", title="迁移测试商品")
        session.add_all([customer, item])
        session.flush()
        conversation = Conversation(
            channel="xianyu",
            external_id="conversation-probe",
            customer_id="external-probe",
            customer_name="迁移客户",
            item_id=item.id,
        )
        session.add(conversation)
        session.flush()
        requirement_case = RequirementCase(
            id="case-probe",
            customer_id=customer.id,
            title="迁移需求",
            current_version=0,
        )
        session.add(requirement_case)
        session.flush()
        session.add(
            RequirementCaseSource(
                id="source-probe",
                case_id=requirement_case.id,
                conversation_id=conversation.id,
            )
        )
        session.commit()

    # Recreate the one affected table exactly as the previous 0009 schema so
    # this test exercises the real 0009 -> 0010 Alembic upgrade path.
    with database.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        with connection.begin():
            connection.exec_driver_sql("DROP TABLE customer_item_links")
            connection.exec_driver_sql(
                "CREATE TABLE requirement_cases_legacy ("
                "id VARCHAR(128) NOT NULL PRIMARY KEY, "
                "customer_id VARCHAR(128) NOT NULL REFERENCES business_customers(id), "
                "title VARCHAR(300) NOT NULL, status VARCHAR(32) NOT NULL, "
                "current_version INTEGER NOT NULL, "
                "lead_id VARCHAR(128) REFERENCES sales_leads(id), "
                "project_id VARCHAR(128), created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO requirement_cases_legacy "
                "(id, customer_id, title, status, current_version, lead_id, project_id, created_at, updated_at) "
                "SELECT id, customer_id, title, status, current_version, lead_id, project_id, created_at, updated_at "
                "FROM requirement_cases"
            )
            connection.exec_driver_sql("DROP TABLE requirement_cases")
            connection.exec_driver_sql(
                "ALTER TABLE requirement_cases_legacy RENAME TO requirement_cases"
            )
            for name, column in (
                ("ix_requirement_cases_customer_id", "customer_id"),
                ("ix_requirement_cases_title", "title"),
                ("ix_requirement_cases_status", "status"),
                ("ix_requirement_cases_lead_id", "lead_id"),
                ("ix_requirement_cases_project_id", "project_id"),
            ):
                connection.exec_driver_sql(
                    f"CREATE INDEX {name} ON requirement_cases({column})"
                )
            connection.exec_driver_sql(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "INSERT INTO alembic_version(version_num) VALUES ('20260809_0009')"
            )

    database._backup_before_customer_item_upgrade()
    backups = list((tmp_path / "backups").glob("*-before-customer-item-links-*.db"))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(requirement_cases)")
        }
        case_item_id = connection.execute(
            "SELECT item_id FROM requirement_cases WHERE id = 'case-probe'"
        ).fetchone()
        links = connection.execute(
            "SELECT customer_id, item_id, source_type FROM customer_item_links"
        ).fetchall()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        version = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()

    assert "item_id" in columns
    assert case_item_id and case_item_id[0] is not None
    assert links == [("customer-probe", case_item_id[0], "requirement_backfill")]
    assert violations == []
    assert version == ("20260908_0046",)
