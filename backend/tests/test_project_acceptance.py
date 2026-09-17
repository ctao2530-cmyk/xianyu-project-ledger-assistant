import json
import pytest
from backend.app.database import Database
from backend.app.ledger import LedgerService, default_snapshot, RevisionConflict
from backend.app.models import RequirementCase, RequirementDocumentVersion
from backend.app.services.project_acceptance import ProjectAcceptanceService, AcceptanceError

def fixture(tmp_path):
    db=Database(f'sqlite:///{tmp_path / "test.db"}');db.create_all();ledger=LedgerService(db,tmp_path)
    data=default_snapshot();data['customers']=[{'id':'customer','name':'Synthetic'}]
    data['projects']=[{'id':'project','name':'Synthetic','customerId':'customer','totalAmount':1000,'status':'in_progress'}]
    revision,snapshot=ledger.save(data,0)
    with db.session() as s:
        s.add(RequirementCase(id='case',customer_id='customer',project_id='project',title='Synthetic',current_version=1));s.flush()
        s.add(RequirementDocumentVersion(case_id='case',version=1,title='Synthetic',readiness='approved',change_summary='',structured_json='{}',content_markdown='',model='synthetic'));s.commit()
    return db,ledger,revision,snapshot

def test_acceptance_is_append_only_revision_protected_and_never_changes_money_or_status(tmp_path):
    db,ledger,revision,before=fixture(tmp_path);service=ProjectAcceptanceService(db,ledger)
    payload=dict(request_id='acceptance-001',expected_revision=revision,case_id='case',version=1,decision='accepted',reviewer='Synthetic reviewer',evidence='Synthetic evidence reference',confirmed=True)
    result=service.record('project',payload)
    assert service.record('project',payload)==result
    assert ledger.get()[1]==before
    assert service.history('project')['items'][0]['decision']=='accepted'
    with pytest.raises(AcceptanceError):service.record('project',payload|{'evidence':'changed evidence'})
    with pytest.raises(RevisionConflict):service.record('project',payload|{'request_id':'acceptance-002'})
    payload.update(request_id='acceptance-002',expected_revision=result['revision'],decision='rejected')
    service.record('project',payload)
    assert len(service.history('project')['items'])==2
    assert service.history('project',limit=1)['has_more']

def test_acceptance_rejects_unconfirmed_wrong_project_and_stale_formal_version(tmp_path):
    db,ledger,revision,_=fixture(tmp_path);service=ProjectAcceptanceService(db,ledger)
    p=dict(request_id='acceptance-001',expected_revision=revision,case_id='case',version=1,decision='accepted',reviewer='Synthetic',evidence='Synthetic evidence',confirmed=True)
    for project,payload in [('wrong',p),('project',p|{'confirmed':False}),('project',p|{'version':2})]:
        with pytest.raises(AcceptanceError):service.record(project,payload)
    assert ledger.get()[0]==revision
    assert service.history('project')['items']==[]

def test_acceptance_http_confirmation_and_event_boundary(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from backend.app.project_acceptance_api import acceptance_router
    from backend.app.services.event_hub import EventHub
    db,ledger,revision,_=fixture(tmp_path);events=EventHub();subscription=events.subscribe()
    app=FastAPI();app.state.runtime=SimpleNamespace(database=db,ledger=ledger,event_hub=events);app.include_router(acceptance_router)
    headers={'X-Yuda-Desktop':'1'}
    p=dict(request_id='acceptance-001',expected_revision=revision,case_id='case',version=1,decision='accepted',reviewer='Synthetic',evidence='Synthetic evidence',confirmed=True)
    with TestClient(app) as client:
        assert client.post('/api/projects/project/acceptance',json=p).status_code==403
        assert client.post('/api/projects/project/acceptance',headers=headers,json=p|{'confirmed':False}).status_code==409
        assert subscription.queue.empty()
        response=client.post('/api/projects/project/acceptance',headers=headers,json=p)
        assert response.status_code==200
        assert subscription.queue.get_nowait()['revision']==response.json()['revision']
        assert client.get('/api/projects/project/acceptance',headers=headers).json()['items'][0]['evidence_kind']=='operator_recorded'
