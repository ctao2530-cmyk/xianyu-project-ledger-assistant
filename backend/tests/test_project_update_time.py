from datetime import datetime, timezone
import json

from backend.app.ledger import LedgerService, default_snapshot
from backend.app.database import Database
from backend.app.models import BusinessProject, LedgerState


def make_ledger(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_all()
    service = LedgerService(db, tmp_path)
    snapshot = default_snapshot()
    snapshot['projects'] = [{'id': 'project-z', 'name': 'Synthetic project', 'projectKind': 'personal', 'updatedAt': '2099-01-01T00:00:00Z'}]
    revision, saved = service.save(snapshot, 0)
    return db, service, revision, saved


def test_read_and_save_return_server_time_and_never_persist_client_time(tmp_path):
    db, service, revision, saved = make_ledger(tmp_path)
    assert saved['projects'][0]['updatedAt'] != '2099-01-01T00:00:00Z'
    assert datetime.fromisoformat(saved['projects'][0]['updatedAt']).tzinfo is not None
    with db.session() as session:
        state = session.get(LedgerState, 1)
        assert 'updatedAt' not in json.loads(state.snapshot_json)['projects'][0]
        project = session.get(BusinessProject, 'project-z')
        project.updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        session.commit()
    assert service.get()[1]['projects'][0]['updatedAt'] == '2020-01-01T00:00:00+00:00'
    with db.session() as session:
        assert service.get_in_session(session)[1]['projects'][0]['updatedAt'] == '2020-01-01T00:00:00+00:00'


def test_unrelated_save_does_not_make_project_look_updated(tmp_path):
    db, service, revision, saved = make_ledger(tmp_path)
    before = saved['projects'][0]['updatedAt']
    saved['settings']['profileName'] = 'Synthetic operator'
    revision, saved = service.save(saved, revision)
    assert saved['projects'][0]['updatedAt'] == before
    with db.session() as session:
        session.get(BusinessProject, 'project-z').updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        session.commit()
    saved['projects'][0]['name'] = 'Changed project'
    _, updated = service.save(saved, revision)
    assert datetime.fromisoformat(updated['projects'][0]['updatedAt']).year > 2020


def test_legacy_snapshot_without_normalized_record_has_unknown_time(tmp_path):
    db, service, _, _ = make_ledger(tmp_path)
    with db.session() as session:
        state = session.get(LedgerState, 1)
        snapshot = json.loads(state.snapshot_json)
        snapshot['projects'].append({'id': 'unknown', 'updatedAt': '2099-01-01T00:00:00Z'})
        state.snapshot_json = json.dumps(snapshot)
        session.commit()
    assert service.get()[1]['projects'][1]['updatedAt'] is None
