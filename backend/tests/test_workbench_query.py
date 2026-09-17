import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import event
from backend.app.database import Database
from backend.app.models import Conversation, BusinessCustomer, RequirementCase, RequirementDocumentVersion, LedgerMutationRequest
from backend.app.services.workbench import WorkbenchQuery

def test_page_is_bounded_stable_read_only_and_constant_query_count(tmp_path):
    db=Database(f'sqlite:///{tmp_path / "test.db"}'); db.create_all()
    now=datetime.now(timezone.utc)
    with db.session() as s:
        s.add(BusinessCustomer(id='c',name='Synthetic'))
        for i in range(150):
            s.add(Conversation(external_id=str(i),customer_id='synthetic',customer_name='Synthetic',unread_count=1,last_message_at=now))
        s.commit()
        s.add(RequirementCase(id='case',customer_id='c',title='Synthetic requirement',current_version=1,status='approved'))
        s.flush()
        s.add(RequirementDocumentVersion(case_id='case',version=1,title='Synthetic',readiness='approved',change_summary='',content_markdown='',model='synthetic',structured_json=json.dumps({'open_questions':['question']})))
        for key,expiry,result in [('valid',now+timedelta(days=1),None),('expired',now-timedelta(days=1),None),('done',now+timedelta(days=1),{'ok':True})]:
            s.add(LedgerMutationRequest(request_id=key,operation='requirement_gpt_proposal',payload_hash='test',result_json=json.dumps({'customer_id':'c','expires_at':expiry.isoformat(),'result':result,'review_token':'must-not-leak'})))
        s.commit()
    statements=[]
    event.listen(db.engine,'before_cursor_execute',lambda conn,cursor,stmt,params,ctx,many:statements.append(stmt))
    first=WorkbenchQuery(db).page(limit=100); second=WorkbenchQuery(db).page(offset=100,limit=100)
    assert first['total']==152 and first['hasMore'] and len(second['items'])==52 and not second['hasMore']
    assert len({r['id'] for r in first['items']+second['items']})==152
    assert len(statements)==6 # BEGIN + count + page per request, independent of customer count
    assert all(not x.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for x in statements)
    assert 'must-not-leak' not in json.dumps(first)+json.dumps(second)
    proposals=[r for r in first['items']+second['items'] if r['id']=='proposals-c']
    assert proposals[0]['detail']=='1 份 GPT 拟写入提案'
    assert all(r['updatedAt'].endswith('+00:00') for r in first['items'])

def test_workbench_requires_local_same_origin_desktop_client(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from backend.app.workbench_api import workbench_router
    db=Database(f'sqlite:///{tmp_path / "test.db"}');db.create_all()
    app=FastAPI();app.state.runtime=SimpleNamespace(database=db);app.include_router(workbench_router)
    with TestClient(app) as client:
        assert client.get('/api/workbench/actions').status_code==403
        assert client.get('/api/workbench/actions',headers={'X-Yuda-Desktop':'1'}).json()['total']==0
        assert client.get('/api/workbench/actions',headers={'X-Yuda-Desktop':'1','Origin':'https://untrusted.example'}).status_code==403
        assert client.get('/api/workbench/actions?limit=201',headers={'X-Yuda-Desktop':'1'}).status_code==422
