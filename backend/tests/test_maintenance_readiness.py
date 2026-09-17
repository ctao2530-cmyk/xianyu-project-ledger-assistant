from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.app.database import Database
from backend.app.config import Settings
from backend.app.maintenance_api import maintenance_router

def test_diagnostics_are_local_read_only_and_unknown_usage_stays_unknown(tmp_path):
    db=Database(f'sqlite:///{tmp_path / "test.db"}');db.create_all()
    with db.engine.begin() as connection:
        connection.execute(text('CREATE TABLE IF NOT EXISTS alembic_version(version_num TEXT PRIMARY KEY)'))
        connection.execute(text("INSERT OR REPLACE INTO alembic_version VALUES('synthetic')"))
    app=FastAPI();app.state.runtime=SimpleNamespace(database=db,settings=Settings(_env_file=None));app.include_router(maintenance_router)
    with TestClient(app) as client:
        assert client.get('/api/maintenance/readiness').status_code==403
        ready=client.get('/api/maintenance/readiness',headers={'X-Yuda-Desktop':'1'}).json()
        assert ready['status']=='ready' and ready['external_services']=='not_checked'
        usage=client.get('/api/maintenance/analysis-usage',headers={'X-Yuda-Desktop':'1'}).json()
        assert usage['reported_tokens'] is None and usage['attempts']==0
