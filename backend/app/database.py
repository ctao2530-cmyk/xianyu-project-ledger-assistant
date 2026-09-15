from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
import hashlib
from pathlib import Path
import sqlite3
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
        from .customer_workflow_schema import validate_customer_workflow_schema, migrate_customer_workflow_schema
        from .customer_sync_schema import validate_customer_sync_schema, migrate_customer_sync_schema

        # Reject partial 0045 before any older startup migration can write.
        with self.engine.connect() as connection:
            validate_customer_sync_schema(connection)
            validate_customer_workflow_schema(connection)

        if self.engine.dialect.name == "sqlite":
            self._backup_before_requirement_upgrade()
            self._backup_before_customer_item_upgrade()
            self._backup_before_product_monitor_upgrade()
            self._backup_before_product_traffic_upgrade()
            self._backup_before_market_reference_upgrade()
            self._backup_before_collection_attempt_upgrade()
            self._backup_before_browse_accounting_upgrade()
            self._backup_before_settlement_issue_upgrade()
            self._backup_before_project_change_order_upgrade()
            self._backup_before_business_recommendation_feedback_upgrade()
            self._backup_before_conversation_history_import_upgrade()
            self._backup_before_product_registration_upgrade()
            self._backup_before_product_plan_explanation_upgrade()
            self._backup_before_product_traffic_v24_upgrade()
            self._backup_before_product_traffic_overlap_upgrade()
            self._backup_before_product_traffic_baseline_invalidation_upgrade()
            self._backup_before_product_traffic_checkpoint_collection_upgrade()
            self._backup_before_product_traffic_48h_upgrade()
            self._backup_before_project_product_attribution_upgrade()
            self._backup_before_prediction_upgrade()
            self._backup_before_customer_image_archive_upgrade()
            self._backup_before_product_traffic_growth_upgrade()
            self._backup_before_codex_plan_upgrade()
            self._backup_before_codex_sync_upgrade()
            self._backup_before_codex_runtime_upgrade()
            self._backup_before_codex_verification_upgrade()
            self._backup_before_estimate_calibration_upgrade()
            self._backup_before_project_outcome_freeze_upgrade()
            self._backup_before_global_agent_upgrade()
            self._backup_before_agent_customer_context_upgrade()
            self._backup_before_global_agent_trace_upgrade()
            self._backup_before_customer_auto_analysis_upgrade()
            self._backup_before_customer_context_oauth_upgrade()
            self._backup_before_customer_context_tunnel_upgrade()
            self._backup_before_customer_context_thread_binding_upgrade()
            self._backup_before_phrase_library_upgrade()
            self._backup_before_customer_intake_upgrade()
            self._backup_before_project_task_draft_upgrade()
            self._migrate_channel_columns()
            # Existing analysis tables must gain the additive feedback columns
            # before SQLAlchemy creates indexes declared by the current model.
            self._migrate_business_recommendation_feedback_schema()
            self._migrate_product_traffic_v24_schema()
            self._migrate_product_traffic_overlap_recording_schema()
            self._migrate_product_traffic_baseline_invalidation_schema()
            self._migrate_product_traffic_checkpoint_collection_schema()
            self._migrate_product_traffic_48h_schema()
            self._migrate_project_product_attribution_schema()
            self._migrate_codex_plan_schema()
            self._migrate_codex_sync_schema()
            self._migrate_codex_runtime_schema()
            self._migrate_codex_verification_schema()
            self._migrate_estimate_calibration_schema()
            self._migrate_project_outcome_freeze_schema()
            self._migrate_global_agent_schema()
            self._migrate_agent_customer_context_schema()
            self._migrate_global_agent_trace_schema()
            self._migrate_customer_context_gateway_schema()
            self._migrate_customer_context_oauth_schema()
            self._migrate_customer_context_tunnel_schema()
            self._migrate_customer_context_thread_binding_schema()
            self._migrate_customer_auto_analysis_schema()
            self._migrate_phrase_library_schema()
            self._migrate_customer_intake_schema()
            self._migrate_project_requirement_handoff_schema()
            self._migrate_project_task_draft_schema()
        with self.engine.begin() as connection:
            migrate_customer_workflow_schema(connection)
            migrate_customer_sync_schema(connection)
        Base.metadata.create_all(self.engine)
        with self.engine.connect() as connection:
            validate_customer_workflow_schema(connection)
        if self.engine.dialect.name == "sqlite":
            # The analysis domain depends on global-agent and conversation
            # tables that may themselves be created by Base.metadata above.
            # Re-run the idempotent verifier to install safety triggers on a
            # brand-new database and to reject structural drift.
            self._migrate_customer_auto_analysis_schema()
            self._migrate_customer_context_oauth_schema()
            self._migrate_customer_context_tunnel_schema()
            self._migrate_customer_context_thread_binding_schema()
            self._seed_codex_verification_data()
            self._migrate_personal_project_schema()
            self._migrate_requirement_blueprint_schema()
            self._migrate_product_monitor_schema()
            self._migrate_product_collection_attempt_schema()
            self._migrate_product_browse_accounting_schema()
            self._migrate_project_change_order_schema()
            self._migrate_product_plan_explanation_schema()
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

    def _migrate_project_product_attribution_schema(self) -> None:
        from .schema_migrations import migrate_project_product_attribution_schema

        with self.engine.begin() as connection:
            migrate_project_product_attribution_schema(connection)

    def _migrate_codex_plan_schema(self) -> None:
        from .schema_migrations import migrate_codex_plan_schema

        with self.engine.begin() as connection:
            migrate_codex_plan_schema(connection)

    def _migrate_codex_sync_schema(self) -> None:
        from .schema_migrations import migrate_codex_sync_schema

        with self.engine.begin() as connection:
            migrate_codex_sync_schema(connection)

    def _migrate_codex_runtime_schema(self) -> None:
        from .schema_migrations import migrate_codex_runtime_schema

        with self.engine.begin() as connection:
            migrate_codex_runtime_schema(connection)

    def _migrate_codex_verification_schema(self) -> None:
        from .schema_migrations import migrate_codex_verification_schema

        with self.engine.begin() as connection:
            migrate_codex_verification_schema(connection)

    def _migrate_estimate_calibration_schema(self) -> None:
        from .schema_migrations import migrate_estimate_calibration_schema

        with self.engine.begin() as connection:
            migrate_estimate_calibration_schema(connection)

    def _migrate_project_requirement_handoff_schema(self) -> None:
        from .schema_migrations import migrate_project_requirement_handoff_schema

        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            try:
                with connection.begin():
                    migrate_project_requirement_handoff_schema(connection)
            finally:
                if connection.in_transaction():
                    connection.rollback()
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()
            violations = list(connection.exec_driver_sql("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "project requirement handoff migration left foreign-key violations: "
                    f"{violations[:3]}"
                )

    def _migrate_project_task_draft_schema(self) -> None:
        from .schema_migrations import migrate_project_task_draft_schema

        with self.engine.begin() as connection:
            migrate_project_task_draft_schema(connection)

    def _migrate_project_outcome_freeze_schema(self) -> None:
        from .schema_migrations import migrate_project_outcome_freeze_schema

        with self.engine.begin() as connection:
            migrate_project_outcome_freeze_schema(connection)

    def _migrate_global_agent_schema(self) -> None:
        from .schema_migrations import migrate_global_agent_schema

        with self.engine.begin() as connection:
            migrate_global_agent_schema(connection)

    def _migrate_agent_customer_context_schema(self) -> None:
        from .schema_migrations import migrate_agent_customer_context_schema

        with self.engine.begin() as connection:
            migrate_agent_customer_context_schema(connection)

    def _migrate_global_agent_trace_schema(self) -> None:
        from .schema_migrations import migrate_global_agent_trace_schema

        with self.engine.begin() as connection:
            migrate_global_agent_trace_schema(connection)

    def _migrate_customer_context_gateway_schema(self) -> None:
        from .schema_migrations import migrate_customer_context_gateway_schema

        with self.engine.begin() as connection:
            migrate_customer_context_gateway_schema(connection)

    def _migrate_customer_context_oauth_schema(self) -> None:
        from .schema_migrations import migrate_customer_context_oauth_schema

        with self.engine.begin() as connection:
            migrate_customer_context_oauth_schema(connection)

    def _migrate_customer_context_tunnel_schema(self) -> None:
        from .schema_migrations import migrate_customer_context_tunnel_schema

        with self.engine.begin() as connection:
            migrate_customer_context_tunnel_schema(connection)

    def _migrate_customer_context_thread_binding_schema(self) -> None:
        from .schema_migrations import migrate_customer_context_thread_binding_schema

        with self.engine.begin() as connection:
            migrate_customer_context_thread_binding_schema(connection)

    def _migrate_customer_auto_analysis_schema(self) -> None:
        from .schema_migrations import migrate_customer_auto_analysis_schema

        with self.engine.begin() as connection:
            migrate_customer_auto_analysis_schema(connection)

    def _migrate_phrase_library_schema(self) -> None:
        from .schema_migrations import migrate_phrase_library_schema

        with self.engine.begin() as connection:
            migrate_phrase_library_schema(connection)

    def _migrate_customer_intake_schema(self) -> None:
        from .schema_migrations import migrate_customer_intake_schema

        with self.engine.begin() as connection:
            migrate_customer_intake_schema(connection)

    def _backup_before_customer_intake_upgrade(self) -> None:
        """Create a WAL-safe private backup before the additive phase 0036 fields."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        expected = {
            "current_need",
            "price_type",
            "price_amount",
            "next_action",
            "notes",
        }
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "business_customers" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(business_customers)"
                )
            }
        present = expected.intersection(columns)
        if present == expected:
            return
        if present:
            raise RuntimeError(
                "customer intake schema is incomplete: missing columns "
                + ", ".join(sorted(expected - present))
            )
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-customer-intake-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("customer intake backup failed SQLite integrity check")
        target.chmod(0o600)

    def _backup_before_phrase_library_upgrade(self) -> None:
        """Create a WAL-safe private backup before the additive phase 0035 schema."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        expected = {
            "phrase_library_states",
            "phrase_categories",
            "phrase_snippets",
            "phrase_library_mutation_requests",
        }
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        present = expected.intersection(tables)
        if present == expected:
            return
        if present:
            raise RuntimeError(
                "phrase library schema is incomplete: "
                + ", ".join(sorted(expected - present))
            )
        if "ledger_state" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-phrase-library-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("phrase library backup failed SQLite integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "phrase library backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        if len(hashlib.sha256(target.read_bytes()).hexdigest()) != 64:
            raise RuntimeError("phrase library backup failed SHA-256 verification")

    def _backup_before_customer_auto_analysis_upgrade(self) -> None:
        """Create a private WAL-safe backup before the additive phase 0041 schema."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        expected = {
            "customer_analysis_threads",
            "customer_analysis_runs",
            "customer_analysis_events",
            "customer_analysis_artifacts",
            "customer_analysis_mutation_requests",
        }
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            present = expected.intersection(tables)
            if present == expected:
                from .schema_migrations import validate_customer_auto_analysis_schema

                try:
                    if validate_customer_auto_analysis_schema(connection):
                        return
                except RuntimeError:
                    # Back up the malformed structure before startup migration
                    # rejects it below.
                    pass
        if "ledger_state" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / (
            f"{path.stem}-before-customer-auto-analysis-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "customer auto analysis backup failed SQLite integrity check"
                )
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "customer auto analysis backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        if len(hashlib.sha256(target.read_bytes()).hexdigest()) != 64:
            raise RuntimeError("customer auto analysis backup failed SHA-256 verification")

    def _backup_before_customer_context_oauth_upgrade(self) -> None:
        """Create a private WAL-safe backup before the additive phase 0042 table."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        table = "customer_context_oauth_bindings"
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if table in tables:
                from .schema_migrations import validate_customer_context_oauth_schema

                try:
                    if validate_customer_context_oauth_schema(connection):
                        return
                except RuntimeError:
                    pass
        if "ledger_state" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / (
            f"{path.stem}-before-customer-context-oauth-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "customer context OAuth backup failed SQLite integrity check"
                )
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "customer context OAuth backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        if len(hashlib.sha256(target.read_bytes()).hexdigest()) != 64:
            raise RuntimeError("customer context OAuth backup failed SHA-256 verification")

    def _backup_before_customer_context_tunnel_upgrade(self) -> None:
        """Create a private WAL-safe backup before the additive phase 0043 table."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        table = "customer_context_tunnel_bindings"
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if table in tables:
                from .schema_migrations import validate_customer_context_tunnel_schema

                try:
                    if validate_customer_context_tunnel_schema(connection):
                        return
                except RuntimeError:
                    pass
        if "ledger_state" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / (
            f"{path.stem}-before-customer-context-tunnel-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "customer context tunnel backup failed SQLite integrity check"
                )
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "customer context tunnel backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        if len(hashlib.sha256(target.read_bytes()).hexdigest()) != 64:
            raise RuntimeError("customer context tunnel backup failed SHA-256 verification")

    def _backup_before_customer_context_thread_binding_upgrade(self) -> None:
        """Create a private WAL-safe backup before the additive phase 0044 table."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        table = "customer_context_thread_bindings"
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if table in tables:
                from .schema_migrations import (
                    validate_customer_context_thread_binding_schema,
                )

                try:
                    if validate_customer_context_thread_binding_schema(connection):
                        return
                except RuntimeError:
                    pass
        if "ledger_state" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / (
            f"{path.stem}-before-customer-context-thread-binding-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "customer context thread binding backup failed SQLite integrity check"
                )
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "customer context thread binding backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        if len(hashlib.sha256(target.read_bytes()).hexdigest()) != 64:
            raise RuntimeError(
                "customer context thread binding backup failed SHA-256 verification"
            )

    def _backup_before_agent_customer_context_upgrade(self) -> None:
        """Create a WAL-safe private backup before the additive phase 0034 schema."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        new_tables = {
            "global_agent_conversation_summaries",
            "customer_image_history_recovery_runs",
        }
        required_thread_columns = {
            "context_scope", "conversation_id", "customer_id",
        }
        required_run_columns = {"recheck_full_context"}
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "global_agent_threads" not in tables:
                return
            thread_columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(global_agent_threads)"
                )
            }
            run_columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(global_agent_runs)"
                )
            }
        present_tables = new_tables.intersection(tables)
        present_columns = required_thread_columns.intersection(thread_columns)
        present_run_columns = required_run_columns.intersection(run_columns)
        if (
            present_tables == new_tables
            and present_columns == required_thread_columns
            and present_run_columns == required_run_columns
        ):
            return
        if present_tables or present_columns or present_run_columns:
            raise RuntimeError(
                "agent customer context schema is incomplete: "
                + ", ".join(
                    sorted(
                        (new_tables - present_tables)
                        | {
                            f"global_agent_threads.{column}"
                            for column in required_thread_columns - present_columns
                        }
                        | {
                            f"global_agent_runs.{column}"
                            for column in required_run_columns - present_run_columns
                        }
                    )
                )
            )
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / (
            f"{path.stem}-before-agent-customer-context-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "agent customer context backup failed SQLite integrity check"
                )
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "agent customer context backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        if len(hashlib.sha256(target.read_bytes()).hexdigest()) != 64:
            raise RuntimeError(
                "agent customer context backup failed SHA-256 verification"
            )

    def _backup_before_global_agent_upgrade(self) -> None:
        """Create a WAL-safe private backup before adding global Agent state."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        expected = {
            "global_agent_model_profiles",
            "global_agent_threads",
            "global_agent_messages",
            "global_agent_runs",
            "global_agent_tool_calls",
            "global_agent_knowledge_documents",
            "global_agent_knowledge_chunks",
            "global_agent_mutation_requests",
            "global_agent_knowledge_fts",
        }
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        present = expected.intersection(tables)
        if present == expected:
            return
        if present:
            raise RuntimeError(
                "global Agent schema is incomplete: "
                + ", ".join(sorted(expected - present))
            )
        # A brand-new test database has nothing worth backing up.  The ledger
        # table distinguishes a real in-place application upgrade from that
        # empty bootstrap path without assuming every optional domain exists.
        if "ledger_state" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-global-agent-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("global Agent backup failed SQLite integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "global Agent backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        if len(hashlib.sha256(target.read_bytes()).hexdigest()) != 64:
            raise RuntimeError("global Agent backup failed SHA-256 verification")

    def _backup_before_global_agent_trace_upgrade(self) -> None:
        """Create one private backup before the additive phase 0039 table."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
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
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "global_agent_runs" not in tables:
                return
            columns = (
                {
                    str(row[1])
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(global_agent_run_steps)"
                    )
                }
                if "global_agent_run_steps" in tables
                else set()
            )
        if columns == required:
            return
        if columns:
            raise RuntimeError(
                "global Agent run trace schema is incomplete: "
                + ", ".join(sorted(required - columns))
            )
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / (
            f"{path.stem}-before-global-agent-trace-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "global Agent run trace backup failed SQLite integrity check"
                )
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "global Agent run trace backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        if len(hashlib.sha256(target.read_bytes()).hexdigest()) != 64:
            raise RuntimeError(
                "global Agent run trace backup failed SHA-256 verification"
            )

    def _seed_codex_verification_data(self) -> None:
        from .schema_migrations import seed_codex_verification_data

        with self.engine.begin() as connection:
            seed_codex_verification_data(connection)

    def _backup_before_codex_verification_upgrade(self) -> None:
        """Create one WAL-safe private backup before verified-delivery migration."""

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
            columns = (
                {
                    str(row[1])
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(business_projects)"
                    )
                }
                if "business_projects" in tables
                else set()
            )
        expected = {
            "codex_acceptance_points",
            "codex_acceptance_evidence",
            "codex_acceptance_status_history",
            "codex_run_activity_intervals",
            "project_time_entries",
            "project_git_links",
        }
        if expected.issubset(tables) and {
            "legacy_progress",
            "progress_source",
        }.issubset(columns):
            return
        if "business_projects" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-codex-verification-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("Codex verification backup failed SQLite integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    f"Codex verification backup has foreign-key violations: {violations[:3]}"
                )
        target.chmod(0o600)

    def _backup_before_estimate_calibration_upgrade(self) -> None:
        """Back up SQLite before creating verified-outcome calibration evidence."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        expected = {
            "estimate_calibration_samples",
            "estimate_calibration_runs",
            "estimate_calibration_suggestions",
            "estimate_calibration_decisions",
            "estimate_calibration_mutation_requests",
        }
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        present = expected.intersection(tables)
        if present == expected:
            return
        if present:
            missing = ", ".join(sorted(expected - present))
            raise RuntimeError(
                "estimate calibration schema is incomplete: " + missing
            )
        if "prediction_runs" not in tables or "business_projects" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / (
            f"{path.stem}-before-estimate-calibration-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "estimate calibration backup failed SQLite integrity check"
                )
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "estimate calibration backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if len(digest) != 64:
            raise RuntimeError("estimate calibration backup failed SHA-256 verification")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if len(digest) != 64:
            raise RuntimeError("Codex verification backup failed SHA-256 verification")

    def _backup_before_project_outcome_freeze_upgrade(self) -> None:
        """Back up SQLite before adding manual scope provenance and outcome freezes."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        expected_tables = {
            "project_outcome_freezes",
            "project_outcome_freeze_mutation_requests",
        }
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            point_columns = (
                {
                    str(row[1])
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(codex_acceptance_points)"
                    )
                }
                if "codex_acceptance_points" in tables
                else set()
            )
        present_tables = expected_tables.intersection(tables)
        source_present = "source" in point_columns
        if present_tables == expected_tables and source_present:
            return
        if present_tables or source_present:
            missing = sorted(expected_tables - present_tables)
            if not source_present:
                missing.append("codex_acceptance_points.source")
            raise RuntimeError(
                "project outcome freeze schema is incomplete: " + ", ".join(missing)
            )
        if "estimate_calibration_samples" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / (
            f"{path.stem}-before-project-outcome-freeze-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "project outcome freeze backup failed SQLite integrity check"
                )
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "project outcome freeze backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if len(digest) != 64:
            raise RuntimeError(
                "project outcome freeze backup failed SHA-256 verification"
            )

    def _backup_before_codex_runtime_upgrade(self) -> None:
        """Create one WAL-safe private backup before managed Codex runs."""

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
            columns = (
                {
                    str(row[1])
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(codex_runs)"
                    )
                }
                if "codex_runs" in tables
                else set()
            )
        if "runtime_type" in columns and {
            "codex_run_approvals",
            "codex_runtime_mutation_requests",
        }.issubset(tables):
            return
        if "codex_runs" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-codex-runtime-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("Codex runtime backup failed SQLite integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    f"Codex runtime backup has foreign-key violations: {violations[:3]}"
                )
        target.chmod(0o600)
        if len(hashlib.sha256(target.read_bytes()).hexdigest()) != 64:
            raise RuntimeError("Codex runtime backup failed SHA-256 verification")

    def _backup_before_codex_sync_upgrade(self) -> None:
        """Create one private, verified backup before phase-two event sync."""

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
            task_columns = (
                {
                    str(row[1])
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(business_tasks)"
                    )
                }
                if "business_tasks" in tables
                else set()
            )
        expected_tables = {"codex_runs", "codex_events", "codex_task_evidence"}
        if expected_tables.issubset(tables) and "codex_execution_status" in task_columns:
            return
        if "business_tasks" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-codex-sync-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("Codex sync backup failed SQLite integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    f"Codex sync backup has foreign-key violations: {violations[:3]}"
                )
        target.chmod(0o600)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if len(digest) != 64:
            raise RuntimeError("Codex sync backup failed SHA-256 verification")

    def _backup_before_codex_plan_upgrade(self) -> None:
        """Create one private, verified backup before the phase-one planning schema."""

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
            task_columns = (
                {
                    str(row[1])
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(business_tasks)"
                    )
                }
                if "business_tasks" in tables
                else set()
            )
        expected_tables = {
            "codex_project_bindings",
            "codex_development_plans",
            "codex_plan_mutation_requests",
        }
        if expected_tables.issubset(tables) and "task_key" in task_columns:
            return
        if "business_tasks" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-codex-plans-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("Codex plan backup failed SQLite integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    f"Codex plan backup has foreign-key violations: {violations[:3]}"
                )
        target.chmod(0o600)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if len(digest) != 64:
            raise RuntimeError("Codex plan backup failed SHA-256 verification")

    def _backup_before_project_product_attribution_upgrade(self) -> None:
        """Create a WAL-safe private backup before adding project attribution."""

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
            if "business_projects" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(business_projects)"
                )
            }
        if "item_id" in columns:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-project-product-attribution-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("project product attribution backup failed SQLite integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    f"project product attribution backup has foreign-key violations: {violations[:3]}"
                )
        target.chmod(0o600)

    def _backup_before_prediction_upgrade(self) -> None:
        """Create a WAL-safe backup before adding immutable prediction tables."""

        database_path = self.engine.url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_file():
            return
        prediction_tables = {
            "prediction_runs",
            "prediction_results",
            "prediction_evaluations",
        }
        with self.engine.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        existing = prediction_tables.intersection(tables)
        if existing == prediction_tables:
            return
        if existing:
            raise RuntimeError(
                "prediction schema is incomplete: " + ", ".join(sorted(existing))
            )
        if "ledger_state" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-prediction-foundation-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("prediction backup failed SQLite integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    f"prediction backup has foreign-key violations: {violations[:3]}"
                )
        target.chmod(0o600)

    def _backup_before_customer_image_archive_upgrade(self) -> None:
        """Create a WAL-safe private backup before adding original-image metadata."""

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
        if "customer_image_archives" in tables or "messages" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-customer-images-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("customer image backup failed SQLite integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    f"customer image backup has foreign-key violations: {violations[:3]}"
                )
        target.chmod(0o600)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if len(digest) != 64:
            raise RuntimeError("customer image backup failed SHA-256 verification")

    def _backup_before_product_traffic_growth_upgrade(self) -> None:
        """Create a WAL-safe private backup before adding growth experiments."""

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
        growth_tables = {
            "product_traffic_experiments",
            "product_traffic_experiment_cells",
            "product_traffic_scale_cohorts",
            "product_traffic_scale_cohort_batches",
            "product_traffic_commercial_attributions",
            "product_traffic_budget_decisions",
            "product_traffic_growth_requests",
        }
        existing_growth_tables = growth_tables.intersection(tables)
        if existing_growth_tables and existing_growth_tables != growth_tables:
            missing = sorted(growth_tables - existing_growth_tables)
            raise RuntimeError(
                "product traffic growth schema is partial; refusing to fill it "
                f"silently (missing: {', '.join(missing)})"
            )
        if existing_growth_tables == growth_tables or "product_traffic_batches" not in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / (
            f"{path.stem}-before-product-traffic-growth-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("product traffic growth backup failed integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "product traffic growth backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if len(digest) != 64:
            raise RuntimeError("product traffic growth backup failed SHA-256 verification")

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

    def _backup_before_project_task_draft_upgrade(self) -> None:
        """Create one private WAL-safe backup before the 0037/0038 rebuild."""

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
            if "requirement_document_versions" not in tables or "business_tasks" not in tables:
                return
            requirement_rows = list(
                connection.exec_driver_sql("PRAGMA table_info(requirement_document_versions)")
            )
            requirement_columns = {str(row[1]) for row in requirement_rows}
            conversation_nullable = not bool(
                next((row[3] for row in requirement_rows if str(row[1]) == "conversation_id"), 0)
            )
            task_columns = {
                str(row[1])
                for row in connection.exec_driver_sql("PRAGMA table_info(business_tasks)")
            }
        requirement_complete = {
            "project_id", "source_filename", "source_sha256", "import_metadata_json"
        }.issubset(requirement_columns) and conversation_nullable
        task_complete = {
            "workspace_key", "dependency_task_keys_json", "deliverables_json",
            "requirement_version_id",
        }.issubset(task_columns)
        draft_complete = {
            "project_task_draft_previews", "project_task_draft_items"
        }.issubset(tables)
        if requirement_complete and task_complete and draft_complete:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-project-task-drafts-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("project task draft backup failed integrity check")
            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "project task draft backup has foreign-key violations: "
                    f"{violations[:3]}"
                )
        target.chmod(0o600)
        if len(hashlib.sha256(target.read_bytes()).hexdigest()) != 64:
            raise RuntimeError("project task draft backup failed SHA-256 verification")

    def _backup_before_conversation_history_import_upgrade(self) -> None:
        """Create one WAL-safe backup before adding history-import audit state."""

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
        if (
            "conversations" not in tables
            or "messages" not in tables
            or "conversation_history_import_requests" in tables
        ):
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-history-import-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("conversation history import backup failed SQLite integrity check")
        target.chmod(0o600)

    def _backup_before_product_registration_upgrade(self) -> None:
        """Create one WAL-safe backup before adding registration audit state."""

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
        if "items" not in tables or "product_registration_requests" in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / (
            f"{path.stem}-before-product-registration-{stamp}{path.suffix}"
        )
        source = sqlite3.connect(path)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        target.chmod(0o600)

    def _migrate_requirement_blueprint_schema(self) -> None:
        from .schema_migrations import (
            backfill_requirement_cases,
            migrate_requirement_blueprint_schema,
        )

        with self.engine.begin() as connection:
            migrate_requirement_blueprint_schema(connection)
            backfill_requirement_cases(connection)

    def _backup_before_customer_item_upgrade(self) -> None:
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
            if "requirement_cases" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(requirement_cases)"
                )
            }
        if "item_id" in columns and "customer_item_links" in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-customer-item-links-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("customer-item relationship backup failed SQLite integrity check")
        target.chmod(0o600)

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

    def _migrate_product_collection_attempt_schema(self) -> None:
        from .schema_migrations import backfill_product_collection_attempts

        with self.engine.begin() as connection:
            backfill_product_collection_attempts(connection)

    def _migrate_product_browse_accounting_schema(self) -> None:
        from .schema_migrations import migrate_product_browse_accounting_schema

        with self.engine.begin() as connection:
            migrate_product_browse_accounting_schema(connection)

    def _migrate_project_change_order_schema(self) -> None:
        from .schema_migrations import migrate_project_change_order_schema

        with self.engine.begin() as connection:
            migrate_project_change_order_schema(connection)

    def _migrate_business_recommendation_feedback_schema(self) -> None:
        from .schema_migrations import migrate_business_recommendation_feedback_schema

        with self.engine.begin() as connection:
            migrate_business_recommendation_feedback_schema(connection)

    def _backup_before_business_recommendation_feedback_upgrade(self) -> None:
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
            if "business_analysis_recommendations" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(business_analysis_recommendations)"
                )
            }
        if "target_scope" in columns:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-recommendation-feedback-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "recommendation feedback backup failed SQLite integrity check"
                )
        target.chmod(0o600)

    def _backup_before_collection_attempt_upgrade(self) -> None:
        """Create one WAL-safe backup before append-only attempt logs appear."""

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
        if (
            "product_collection_runs" not in tables
            or "product_collection_attempts" in tables
        ):
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = (
            backup_dir
            / f"{path.stem}-before-collection-attempts-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "collection-attempt backup failed SQLite integrity check"
                )
        target.chmod(0o600)

    def _backup_before_browse_accounting_upgrade(self) -> None:
        """Create a WAL-safe backup before historical browse values change."""

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
            if "product_daily_snapshots" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(product_daily_snapshots)"
                )
            }
        if {
            "raw_browse_count",
            "collection_views_excluded",
        }.issubset(columns):
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = (
            backup_dir
            / f"{path.stem}-before-browse-accounting-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "browse-accounting backup failed SQLite integrity check"
                )
        target.chmod(0o600)

    def _backup_before_product_traffic_upgrade(self) -> None:
        """Back up an existing product database before adding planning tables."""

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
        if "product_monitors" not in tables or "product_traffic_batches" in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-product-traffic-v2-{stamp}{path.suffix}"
        shutil.copy2(path, target)

    def _backup_before_product_plan_explanation_upgrade(self) -> None:
        """Create a WAL-safe backup before structured plan reasons are added."""

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
            if "product_operating_plans" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(product_operating_plans)"
                )
            }
        if "change_factors_json" in columns:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = (
            backup_dir
            / f"{path.stem}-before-product-plan-explanations-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(
                    "product plan explanation backup failed SQLite integrity check"
                )
        target.chmod(0o600)

    def _migrate_product_plan_explanation_schema(self) -> None:
        from .schema_migrations import migrate_product_plan_explanation_schema

        with self.engine.begin() as connection:
            migrate_product_plan_explanation_schema(connection)

    def _backup_before_product_traffic_v24_upgrade(self) -> None:
        """Create a private WAL-safe backup before the v2.4 additive upgrade."""

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
            if "product_traffic_batches" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(product_traffic_batches)"
                )
            }
        if "baseline_prepared_at" in columns:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-product-traffic-v24-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            violations = destination.execute("PRAGMA foreign_key_check").fetchall()
            if not integrity or integrity[0] != "ok" or violations:
                raise RuntimeError("product traffic v2.4 backup failed SQLite validation")
        target.chmod(0o600)

    def _migrate_product_traffic_v24_schema(self) -> None:
        from .schema_migrations import migrate_product_traffic_v24_schema

        with self.engine.begin() as connection:
            migrate_product_traffic_v24_schema(connection)

    def _backup_before_product_traffic_overlap_upgrade(self) -> None:
        """Create a private WAL-safe backup before overlap-recording fields."""

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
            if "product_traffic_batches" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(product_traffic_batches)"
                )
            }
        if {"recording_mode", "attribution_status"}.issubset(columns):
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = (
            backup_dir
            / f"{path.stem}-before-product-traffic-overlap-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            violations = destination.execute("PRAGMA foreign_key_check").fetchall()
            if not integrity or integrity[0] != "ok" or violations:
                raise RuntimeError(
                    "product traffic overlap backup failed SQLite validation"
                )
        target.chmod(0o600)

    def _migrate_product_traffic_overlap_recording_schema(self) -> None:
        from .schema_migrations import (
            migrate_product_traffic_overlap_recording_schema,
        )

        with self.engine.begin() as connection:
            migrate_product_traffic_overlap_recording_schema(connection)

    def _backup_before_product_traffic_baseline_invalidation_upgrade(self) -> None:
        """Create a private WAL-safe backup before terminal baseline fields."""

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
            if "product_traffic_batches" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(product_traffic_batches)"
                )
            }
        if {"invalidated_at", "invalidation_reason"}.issubset(columns):
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = (
            backup_dir
            / f"{path.stem}-before-product-traffic-baseline-invalidation-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            violations = destination.execute("PRAGMA foreign_key_check").fetchall()
            if not integrity or integrity[0] != "ok" or violations:
                raise RuntimeError(
                    "product traffic baseline invalidation backup failed SQLite validation"
                )
        target.chmod(0o600)

    def _migrate_product_traffic_baseline_invalidation_schema(self) -> None:
        from .schema_migrations import (
            migrate_product_traffic_baseline_invalidation_schema,
        )

        with self.engine.begin() as connection:
            migrate_product_traffic_baseline_invalidation_schema(connection)

    def _backup_before_product_traffic_checkpoint_collection_upgrade(self) -> None:
        """Create a private WAL-safe backup before adding checkpoint jobs."""

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
            if "product_traffic_batches" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(product_traffic_batches)"
                )
            }
        if (
            "checkpoint_collection_mode" in columns
            and "product_traffic_checkpoint_jobs" in tables
            and "product_traffic_checkpoint_job_items" in tables
        ):
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = (
            backup_dir
            / f"{path.stem}-before-checkpoint-collection-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            violations = destination.execute("PRAGMA foreign_key_check").fetchall()
            if not integrity or integrity[0] != "ok" or violations:
                raise RuntimeError(
                    "traffic checkpoint collection backup failed SQLite validation"
                )
        target.chmod(0o600)

    def _migrate_product_traffic_checkpoint_collection_schema(self) -> None:
        from .schema_migrations import (
            migrate_product_traffic_checkpoint_collection_schema,
        )

        with self.engine.begin() as connection:
            migrate_product_traffic_checkpoint_collection_schema(connection)

    def _migrate_product_traffic_48h_schema(self) -> None:
        from .schema_migrations import migrate_product_traffic_48h_schema

        with self.engine.begin() as connection:
            migrate_product_traffic_48h_schema(connection)

    def _backup_before_product_traffic_48h_upgrade(self) -> None:
        """Create a private WAL-safe backup before adding the protocol column."""

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
            if "product_traffic_batches" not in tables:
                return
            columns = {
                str(row[1])
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(product_traffic_batches)"
                )
            }
        if "observation_window_hours" in columns:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = path.parent / "backups" / (
            f"{path.stem}-before-traffic-48h-{stamp}{path.suffix}"
        )
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            violations = destination.execute("PRAGMA foreign_key_check").fetchall()
            if not integrity or integrity[0] != "ok" or violations:
                raise RuntimeError("traffic 48h protocol backup failed SQLite validation")
        target.chmod(0o600)

    def _backup_before_market_reference_upgrade(self) -> None:
        """Create a WAL-safe SQLite backup before adding market planning tables."""

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
        if "product_monitors" not in tables or "product_market_keyword_plans" in tables:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-market-reference-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("market reference backup failed SQLite integrity check")

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

    def _backup_before_project_change_order_upgrade(self) -> None:
        """Create a WAL-safe backup before adding financial audit records."""

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
            if "ledger_state" not in tables or "payment_nodes" not in tables:
                return
            payment_columns = {
                str(row[1])
                for row in connection.exec_driver_sql("PRAGMA table_info(payment_nodes)")
            }
        if "project_change_orders" in tables and "change_order_id" in payment_columns:
            return
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{path.stem}-before-project-change-orders-{stamp}{path.suffix}"
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError("project change-order backup failed SQLite integrity check")
        target.chmod(0o600)

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
