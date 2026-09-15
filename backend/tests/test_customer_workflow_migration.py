from pathlib import Path
import pytest
from sqlalchemy import create_engine, inspect, MetaData
from backend.app.models import Item, Conversation, Message
from backend.app.database import Database
from backend.app.customer_workflow_schema import TABLES, validate_customer_workflow_schema
from backend.tests.test_customer_context_gateway import upgrade


def legacy_core(path):
    # The pre-Alembic ingestion tables are created by startup, not revision 0001.
    # Reproduce that real prerequisite, excluding only the new nullable column.
    metadata = MetaData()
    for model in (Item, Conversation, Message):
        table = model.__table__.to_metadata(metadata)
        if model is Message:
            table._columns.remove(table.c.source_item_external_id)
    engine = create_engine(f"sqlite:///{path}")
    metadata.create_all(engine)
    engine.dispose()


def test_full_chain_0044_to_0045_and_startup(tmp_path: Path):
    path = tmp_path / "chain.db"
    legacy_core(path)
    upgrade(path, "20260903_0044")
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        assert not validate_customer_workflow_schema(conn)
    upgrade(path, "20260907_0045")
    database = Database(f"sqlite:///{path}")
    database.create_all()
    database.create_all()
    with database.engine.connect() as conn:
        assert validate_customer_workflow_schema(conn)
        assert conn.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
        assert not conn.exec_driver_sql("PRAGMA foreign_key_check").all()
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "20260907_0045"


def test_startup_upgrades_0044_then_alembic_accepts_complete(tmp_path):
    path = tmp_path / "startup.db"
    legacy_core(path)
    upgrade(path, "20260903_0044")
    db = Database(f"sqlite:///{path}")
    db.create_all()
    upgrade(path, "20260907_0045")
    with db.engine.connect() as conn:
        assert validate_customer_workflow_schema(conn)


def test_partial_workflow_fails_before_any_repair(tmp_path):
    path = tmp_path / "partial.db"
    legacy_core(path)
    upgrade(path, "20260903_0044")
    db = Database(f"sqlite:///{path}")
    with db.engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE customer_image_capture_jobs (archive_id TEXT PRIMARY KEY)")
    with pytest.raises(RuntimeError, match="incomplete"):
        db.create_all()
    with pytest.raises(RuntimeError, match="incomplete"):
        upgrade(path, "20260907_0045")
    with db.engine.connect() as conn:
        assert not set(TABLES).difference({"customer_image_capture_jobs"}).intersection(inspect(conn).get_table_names())
        assert "source_item_external_id" not in {c["name"] for c in inspect(conn).get_columns("messages")}


def test_complete_tables_missing_constraint_rejected(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'constraint.db'}")
    db.create_all()
    with db.engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE customer_conversation_group_members RENAME TO old_members")
        conn.exec_driver_sql("CREATE TABLE customer_conversation_group_members (group_id TEXT, conversation_id INTEGER, active BOOLEAN, updated_at DATETIME, PRIMARY KEY(group_id, conversation_id))")
    with pytest.raises(RuntimeError, match="foreign keys"):
        db.create_all()
