from sqlalchemy import create_engine
import pytest
from backend.app.database import Database
from backend.app.customer_sync_schema import validate_customer_sync_schema, migrate_customer_sync_schema
from backend.tests.test_customer_context_gateway import upgrade
from backend.tests.test_customer_workflow_migration import legacy_core


def test_full_chain_0045_0046_and_startup_idempotence(tmp_path):
    path = tmp_path / 'chain.db'
    legacy_core(path)
    upgrade(path, '20260907_0045')
    upgrade(path, '20260908_0046')
    database = Database(f'sqlite:///{path}')
    database.create_all()
    database.create_all()
    with database.engine.connect() as connection:
        assert validate_customer_sync_schema(connection)
        assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar() == '20260908_0046'
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


def test_startup_then_alembic_accepts_complete(tmp_path):
    path = tmp_path / 'startup.db'
    legacy_core(path)
    upgrade(path, '20260907_0045')
    Database(f'sqlite:///{path}').create_all()
    upgrade(path, '20260908_0046')


def test_partial_refused_without_repair(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "partial.db"}')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE customer_context_sync_states (id TEXT PRIMARY KEY)')
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match='incomplete'):
            migrate_customer_sync_schema(connection)
        assert connection.exec_driver_sql("SELECT count(*) FROM sqlite_master WHERE name='customer_context_read_batches'").scalar() == 0
