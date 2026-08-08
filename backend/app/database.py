from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from pathlib import Path
import shutil

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str):
    if database_url.startswith("sqlite:///"):
        db_path = Path(database_url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
        future=True,
    )

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


class Database:
    def __init__(self, database_url: str) -> None:
        self.engine = create_database_engine(database_url)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False, class_=Session
        )

    def create_all(self) -> None:
        from . import models  # noqa: F401

        if self.engine.dialect.name == "sqlite":
            self._backup_before_requirement_upgrade()
            self._backup_before_product_monitor_upgrade()
            self._backup_before_settlement_issue_upgrade()
            self._migrate_channel_columns()
        Base.metadata.create_all(self.engine)
        if self.engine.dialect.name == "sqlite":
            self._migrate_personal_project_schema()
            self._migrate_requirement_blueprint_schema()
            self._migrate_product_monitor_schema()
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_messages_channel_platform_message "
                    "ON messages(channel, platform_message_id)"
                )
            connection.exec_driver_sql("PRAGMA optimize")

    def _migrate_personal_project_schema(self) -> None:
        from .schema_migrations import migrate_personal_project_schema

        with self.engine.connect() as connection:
            # SQLite will not rebuild a referenced table while foreign-key
            # enforcement is active. Keep this window local to one connection
            # and validate the completed schema before returning.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            try:
                with connection.begin():
                    migrate_personal_project_schema(connection)
            finally:
                if connection.in_transaction():
                    connection.rollback()
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()
            violations = list(connection.exec_driver_sql("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    f"personal project schema migration left foreign-key violations: {violations[:3]}"
                )

    def _backup_before_requirement_upgrade(self) -> None:
        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "requirement_document_versions" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(requirement_document_versions)"
                )
            }
        if "case_id" in columns:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-requirement-blueprints-{stamp}{path.suffix}"
        shutil.copy2(path, target)

    def _migrate_requirement_blueprint_schema(self) -> None:
        from .schema_migrations import (
            backfill_requirement_cases,
            migrate_requirement_blueprint_schema,
        )

        with self.engine.begin() as connection:
            migrate_requirement_blueprint_schema(connection)
            backfill_requirement_cases(connection)

    def _backup_before_product_monitor_upgrade(self) -> None:
        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "product_monitors" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(product_monitors)"
                )
            }
        if "ownership_status" in columns:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-product-ownership-{stamp}{path.suffix}"
        shutil.copy2(path, target)

    def _migrate_product_monitor_schema(self) -> None:
        from .schema_migrations import migrate_product_monitor_schema

        with self.engine.begin() as connection:
            migrate_product_monitor_schema(connection)

    def _backup_before_settlement_issue_upgrade(self) -> None:
        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        if "ledger_state" not in tables or "project_settlement_issues" in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-settlement-issues-{stamp}{path.suffix}"
        shutil.copy2(path, target)

    def _migrate_channel_columns(self) -> None:
        """Small additive SQLite migration for pre-channel local databases."""
        with self.engine.begin() as connection:
            tables = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "conversations" in tables:
                columns = {
                    row[1]
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(conversations)"
                    )
                }
                if "channel" not in columns:
                    connection.exec_driver_sql(
                        "ALTER TABLE conversations ADD COLUMN channel "
                        "VARCHAR(32) NOT NULL DEFAULT 'xianyu'"
                    )
            if "messages" in tables:
                columns = {
                    row[1]
                    for row in connection.exec_driver_sql("PRAGMA table_info(messages)")
                }
                if "channel" not in columns:
                    connection.exec_driver_sql(
                        "ALTER TABLE messages ADD COLUMN channel "
                        "VARCHAR(32) NOT NULL DEFAULT 'xianyu'"
                    )
                if "platform_message_id" not in columns:
                    connection.exec_driver_sql(
                        "ALTER TABLE messages ADD COLUMN platform_message_id "
                        "VARCHAR(255) NOT NULL DEFAULT ''"
                    )
                connection.exec_driver_sql(
                    "UPDATE messages SET platform_message_id = external_id "
                    "WHERE platform_message_id IS NULL OR platform_message_id = ''"
                )

    def session(self) -> Session:
        return self.session_factory()

    def dependency(self) -> Generator[Session, None, None]:
        with self.session_factory() as session:
            yield session
