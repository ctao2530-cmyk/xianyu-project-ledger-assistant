from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sqlite3
import json

from alembic import command
from alembic.config import Config

from backend.app.config import get_settings
from backend.app.database import Database


ROOT = Path(__file__).resolve().parents[2]


def upgrade(database_path: Path, revision: str) -> None:
    previous = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
        get_settings.cache_clear()
        config = Config(str(ROOT / "alembic.ini"))
        command.upgrade(config, revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def assert_healthy(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []


def _insert_required(
    connection: sqlite3.Connection,
    table: str,
    overrides: dict[str, object],
) -> None:
    values = dict(overrides)
    for _cid, name, declared, not_null, default, primary_key in connection.execute(
        f"PRAGMA table_info({table})"
    ):
        if name in values or (not not_null and not primary_key) or default is not None:
            continue
        upper = str(declared).upper()
        if "INT" in upper:
            values[name] = 0
        elif any(marker in upper for marker in ("REAL", "FLOAT", "DOUBLE", "NUMERIC")):
            values[name] = 0.0
        elif "DATE" in upper or "TIME" in upper:
            values[name] = "2026-08-18 08:00:00"
        else:
            values[name] = ""
    columns = ", ".join(f'"{name}"' for name in values)
    placeholders = ", ".join("?" for _ in values)
    connection.execute(
        f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
        tuple(values.values()),
    )


def test_full_alembic_chain_reaches_phase_two(tmp_path: Path) -> None:
    path = tmp_path / "full-chain.db"
    upgrade(path, "20260817_0027")
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"codex_runs", "codex_events", "codex_task_evidence"}.issubset(tables)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260817_0027",
        )
    assert_healthy(path)


def test_phase_two_to_managed_runtime_and_startup_chain(tmp_path: Path) -> None:
    path = tmp_path / "managed-runtime.db"
    upgrade(path, "20260817_0027")
    upgrade(path, "20260817_0028")
    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(codex_runs)")}
        assert {"codex_run_approvals", "codex_runtime_mutation_requests"}.issubset(tables)
        assert {"runtime_type", "thread_id", "turn_id", "task_key", "base_commit_sha", "branch", "worktree_path", "paused_at"}.issubset(run_columns)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("20260817_0028",)
    assert_healthy(path)


def test_0028_to_0029_preserves_legacy_progress_hours_and_acceptance(tmp_path: Path) -> None:
    path = tmp_path / "verified-delivery.db"
    upgrade(path, "20260817_0028")
    snapshot = {
        "projects": [{"id": "project-legacy", "name": "Legacy", "progress": 65}],
        "tasks": [
            {
                "id": "task-legacy", "projectId": "project-legacy", "title": "Legacy task",
                "estimatedHours": 5, "actualHours": 3.5,
            }
        ],
    }
    with sqlite3.connect(path) as connection:
        # A clean historical migration is loaded through current metadata, so
        # strip phase-four additive columns to reproduce the real 0028 schema.
        # The production database already has these mature pre-0001 parent
        # tables; the synthetic Alembic-only fixture needs minimal equivalents
        # so SQLite batch reflection can follow legacy foreign keys.
        connection.execute("CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY)")
        connection.execute("DROP INDEX IF EXISTS ix_business_projects_progress_source")
        connection.execute("ALTER TABLE business_projects DROP COLUMN progress_source")
        connection.execute("ALTER TABLE business_projects DROP COLUMN legacy_progress")
        connection.execute("DROP INDEX IF EXISTS ix_business_tasks_delivery_scope_active")
        connection.execute("ALTER TABLE business_tasks DROP COLUMN delivery_scope_active")
        connection.execute("ALTER TABLE business_tasks DROP COLUMN retired_at")
        _insert_required(
            connection,
            "business_projects",
            {"id": "project-legacy", "name": "Legacy", "progress": 65, "status": "in_progress"},
        )
        _insert_required(
            connection,
            "business_tasks",
            {
                "id": "task-legacy", "project_id": "project-legacy", "title": "Legacy task",
                "estimated_hours": 5.0, "actual_hours": 3.5, "task_key": "DEV-LEGACY",
                "acceptance_points_json": json.dumps(
                    [{"point_key": "AC-LEGACY", "title": "Legacy acceptance", "verification_type": "manual_check"}]
                ),
            },
        )
        _insert_required(
            connection,
            "ledger_state",
            {"id": 1, "revision": 7, "snapshot_json": json.dumps(snapshot)},
        )
        connection.commit()

    upgrade(path, "20260818_0029")
    with sqlite3.connect(path) as connection:
        project = connection.execute(
            "SELECT progress, legacy_progress, progress_source FROM business_projects WHERE id='project-legacy'"
        ).fetchone()
        ledger_snapshot = json.loads(
            connection.execute("SELECT snapshot_json FROM ledger_state WHERE id=1").fetchone()[0]
        )
        time_entry = connection.execute(
            "SELECT source, hours FROM project_time_entries WHERE task_id='task-legacy'"
        ).fetchone()
        point = connection.execute(
            "SELECT point_key, status FROM codex_acceptance_points WHERE task_id='task-legacy'"
        ).fetchone()
        marker = connection.execute(
            "SELECT operation FROM codex_acceptance_mutation_requests WHERE request_id='migration:20260818_0029'"
        ).fetchone()
    assert project == (0, 65, "legacy_manual")
    assert ledger_snapshot["projects"][0]["progress"] == 0
    assert ledger_snapshot["projects"][0]["legacyProgress"] == 65
    assert time_entry == ("legacy_import", 3.5)
    assert point == ("AC-LEGACY", "pending")
    assert marker == ("migration",)
    assert_healthy(path)

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE codex_runtime_mutation_requests")
        connection.execute("DROP TABLE codex_run_approvals")
        connection.execute("DROP TABLE alembic_version")
        connection.commit()
    Database(f"sqlite:///{path}").create_all()
    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"codex_run_approvals", "codex_runtime_mutation_requests"}.issubset(tables)
        assert "alembic_version" not in tables
    backups = list((path.parent / "backups").glob("*-before-codex-runtime-*.db"))
    assert backups and oct(backups[-1].stat().st_mode & 0o777) == "0o600"
    assert_healthy(path)


def test_0026_to_0027_and_startup_without_alembic_version(tmp_path: Path) -> None:
    path = tmp_path / "phase-one.db"
    upgrade(path, "20260817_0026")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260817_0026",
        )
    upgrade(path, "20260817_0027")
    assert_healthy(path)

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE alembic_version")
        connection.execute("DROP TABLE codex_task_evidence")
        connection.execute("DROP TABLE codex_events")
        connection.execute("DROP TABLE codex_runs")
        connection.commit()
    database = Database(f"sqlite:///{path}")
    database.create_all()
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        task_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(business_tasks)")
        }
        assert {"codex_runs", "codex_events", "codex_task_evidence"}.issubset(tables)
        assert {"codex_execution_status", "codex_implemented_at"}.issubset(task_columns)
        assert "alembic_version" not in tables
    backups = list((path.parent / "backups").glob("*-before-codex-sync-*.db"))
    assert backups
    assert oct(backups[-1].stat().st_mode & 0o777) == "0o600"
    assert_healthy(backups[-1])
    assert_healthy(path)


def test_secret_configuration_is_atomic_private_and_never_returned(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "integration" / "configure_codex_sync.py"
    spec = importlib.util.spec_from_file_location("configure_codex_sync", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=value\n")
    env_path.chmod(0o644)

    result = module.configure(env_path)
    first = env_path.read_text()
    replay = module.configure(env_path)

    assert result["secret_printed"] is False
    assert replay["generated"] is False
    assert first == env_path.read_text()
    assert "XUNYING_CODEX_EVENT_SECRET=" in first
    assert oct(env_path.stat().st_mode & 0o777) == "0o600"
    secret = next(
        line.split("=", 1)[1]
        for line in first.splitlines()
        if line.startswith("XUNYING_CODEX_EVENT_SECRET=")
    )
    assert len(secret) >= 32
    assert secret not in str(result)
