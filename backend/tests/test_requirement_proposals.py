from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
import json
import pytest
from sqlalchemy import select, func
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.models import BusinessCustomer, CustomerChannelIdentity, RequirementCase, RequirementDocumentVersion, LedgerMutationRequest
from backend.app.services.requirement_proposals import RequirementProposalService
from backend.app.services.requirement_exchange import RequirementExchangeError
from backend.app.requirement_proposal_api import requirement_proposal_router
from backend.tests.test_customer_context_reader import seed
from backend.tests.test_customer_context_sync import bind, credentials
from backend.tests.test_project_task_drafts import blueprint


def setup(tmp_path):
    db, reader, _, cid = seed(tmp_path)
    with db.session() as session:
        session.add(BusinessCustomer(id='customer-fixture',name='Synthetic customer'))
        session.flush()
        session.add(CustomerChannelIdentity(id='identity-fixture',customer_id='customer-fixture',channel='xianyu',
            external_customer_id='reader-customer',conversation_id=cid,display_name='Synthetic'))
        session.commit()
    key=bind(reader,cid)
    auth=reader.gateway.authorize_access(**credentials(reader,key),provider='openai',tool_name='requirement_blueprint_preview',scopes=['text'])
    return db, reader, auth, RequirementProposalService(db)


def proposed(service,auth,document=None,**kwargs):
    return service.preview(auth,request_id=kwargs.pop('request_id','proposal-'+uuid4().hex),document=document or blueprint(),**kwargs)


def confirm(service,preview,**overrides):
    local=next(p for p in service.list_pending('customer-fixture') if p['id']==preview['id'])
    return service.confirm(**(dict(request_id=local['request_id'],review_token=local['review_token'],
        expected_version=local['expected_version'],confirmed=True)|overrides))


def test_human_confirmation_v1_v2_history_and_conflicts(tmp_path):
    db,reader,auth,service=setup(tmp_path)
    first=proposed(service,auth,request_id='fixed-request-001')
    assert 'review_token' not in first
    with db.session() as session:
        assert session.scalar(select(func.count()).select_from(RequirementCase))==0
    with pytest.raises(RequirementExchangeError):confirm(service,first,confirmed=False)
    v1=confirm(service,first)
    doc=blueprint();doc['capabilities'][0]['description']='新增导出能力';doc['change_summary']='新增导出能力'
    second=proposed(service,auth,doc,case_id=v1['case_id'],expected_version=1)
    stale=proposed(service,auth,doc,case_id=v1['case_id'],expected_version=1)
    assert len(second['diff']['capabilities']['modified'])==1
    assert len(second['diff']['objectives']['unchanged'])==1
    assert confirm(service,second)['version']==2
    with pytest.raises(RequirementExchangeError,match='版本'):confirm(service,stale)
    with db.session() as session:
        versions=list(session.scalars(select(RequirementDocumentVersion).where(RequirementDocumentVersion.case_id==v1['case_id']).order_by(RequirementDocumentVersion.version)))
        assert len(versions)==2
        assert json.loads(versions[0].structured_json)['capabilities'][0]['description']=='展示经营指标'
        assert versions[0].project_id is None


def test_idempotency_no_remote_confirmation_and_source_isolation(tmp_path):
    db,reader,auth,service=setup(tmp_path)
    first=proposed(service,auth,request_id='fixed-request-002')
    assert proposed(service,auth,request_id='fixed-request-002')['id']==first['id']
    changed=blueprint();changed['title']='不同内容'
    with pytest.raises(RequirementExchangeError):proposed(service,auth,changed,request_id='fixed-request-002')
    app=FastAPI();app.state.runtime=SimpleNamespace(database=db);app.include_router(requirement_proposal_router)
    client=TestClient(app)
    assert client.get('/api/customers/customer-fixture/requirement-proposals').status_code==403
    local=client.get('/api/customers/customer-fixture/requirement-proposals',headers={'X-Yuda-Desktop':'1'}).json()[0]
    payload={k:local[k] for k in ('request_id','review_token','expected_version')}|{'confirmed':True}
    assert client.post('/api/requirement-proposals/confirm',json=payload,headers={'X-Yuda-Desktop':'1','Origin':'https://evil.invalid'}).status_code==403
    ok=client.post('/api/requirement-proposals/confirm',json=payload,headers={'X-Yuda-Desktop':'1'})
    assert ok.status_code==200
    assert client.post('/api/requirement-proposals/confirm',json=payload,headers={'X-Yuda-Desktop':'1'}).json()==ok.json()


def test_evidence_cannot_use_export_number_or_other_customer(tmp_path):
    _,_,auth,service=setup(tmp_path)
    doc=blueprint();doc['evidence_refs']=[{'id':'ev-one','message_number':1,'quote':'synthetic'}]
    with pytest.raises(RequirementExchangeError,match='证据'):proposed(service,auth,doc)
    doc['evidence_refs'][0]['message_id']=1
    assert proposed(service,auth,doc)['document']['evidence_refs'][0]['conversation_id']==auth['conversation_id']
    doc['evidence_refs'][0]['message_id']=999999
    with pytest.raises(RequirementExchangeError):proposed(service,auth,doc)


def test_expired_or_revoked_source_rejects_commit(tmp_path):
    _,reader,auth,service=setup(tmp_path)
    first=proposed(service,auth)
    bind(reader,auth['conversation_id'])
    from backend.app.services.customer_context_gateway import CustomerContextGatewayError
    with pytest.raises(CustomerContextGatewayError):confirm(service,first)


def test_mcp_proposal_and_explicit_gpt_confirmation(tmp_path):
    import asyncio
    from backend.app.customer_context_mcp import bridge, preview_requirement_blueprint, confirm_requirement_blueprint
    from backend.tests.test_customer_context_oauth import oauth_config
    from backend.tests.test_customer_context_tunnel import tunnel_config, mcp_context
    db,reader,auth,service=setup(tmp_path)
    key=bind(reader,auth['conversation_id'])
    bridge.bind(reader,reader.gateway,oauth_config(),None,tunnel_config=tunnel_config())
    try:
        result=asyncio.run(preview_requirement_blueprint(context=mcp_context(),request_id='mcp-proposal-001',context_key=key,document=blueprint()))
        assert not result.isError
        payload=json.loads(result.content[0].text)
        assert payload['confirmation_required'] is True
        assert 'review_token' not in payload
        with db.session() as session:
            assert session.scalar(select(func.count()).select_from(RequirementCase))==0
        arguments=dict(context=mcp_context(),context_key=key,request_id=payload['request_id'],
            document_sha256=payload['document_sha256'],expected_version=0,user_confirmation='确认将此版本写入循营')
        assert asyncio.run(confirm_requirement_blueprint(**arguments)).isError
        with db.session() as session:
            assert session.scalar(select(func.count()).select_from(RequirementCase))==0
        saved=asyncio.run(confirm_requirement_blueprint(**arguments,confirmed=True))
        assert not saved.isError
        receipt=json.loads(saved.content[0].text)
        assert receipt['saved'] is True and receipt['version']==1
        assert json.loads(asyncio.run(confirm_requirement_blueprint(**arguments,confirmed=True)).content[0].text)==receipt
        with db.session() as session:
            metadata=json.loads(session.get(RequirementDocumentVersion,receipt['version_id']).import_metadata_json)
            assert metadata['confirmation_source']=='gpt_client_asserted'
            assert '确认将此版本写入循营' not in json.dumps(metadata,ensure_ascii=False)
    finally:
        bridge.bind(reader,reader.gateway)


def remote_confirm(service,auth,proposal,**overrides):
    return service.confirm(**(dict(auth=auth,request_id=proposal['request_id'],
        document_sha256=proposal['document_sha256'],expected_version=proposal['expected_version'],
        confirmed=True,user_confirmation='确认写入以上正式需求')|overrides))


@pytest.mark.parametrize('override',[{'confirmed':False},{'user_confirmation':''},
    {'document_sha256':'0'*64},{'expected_version':99}])
def test_remote_confirmation_rejects_missing_confirmation_and_changed_proposal(tmp_path,override):
    db,reader,auth,service=setup(tmp_path)
    p=proposed(service,auth,gpt_confirmation=True)
    with pytest.raises(RequirementExchangeError):remote_confirm(service,auth,p,**override)
    with db.session() as session:
        assert session.scalar(select(func.count()).select_from(RequirementCase))==0


def test_remote_v2_preserves_history_and_rejects_stale_version(tmp_path):
    db,reader,auth,service=setup(tmp_path)
    v1=remote_confirm(service,auth,proposed(service,auth,gpt_confirmation=True))
    changed=blueprint();changed['change_summary']='增加交付项';changed['stages'][0]['deliverables'].append('合成新增交付')
    p=proposed(service,auth,changed,gpt_confirmation=True,case_id=v1['case_id'],expected_version=1)
    stale=proposed(service,auth,gpt_confirmation=True,case_id=v1['case_id'],expected_version=1)
    assert remote_confirm(service,auth,p)['version']==2
    with pytest.raises(RequirementExchangeError):remote_confirm(service,auth,stale)
    with db.session() as session:
        old=json.loads(session.get(RequirementDocumentVersion,v1['version_id']).structured_json)
        assert '合成新增交付' not in old['stages'][0]['deliverables']


def test_remote_legacy_proposal_and_expired_proposal_are_rejected(tmp_path):
    from datetime import timedelta
    from backend.app.models import utcnow
    db,reader,auth,service=setup(tmp_path)
    with pytest.raises(RequirementExchangeError):remote_confirm(service,auth,proposed(service,auth))
    p=proposed(service,auth,gpt_confirmation=True)
    with db.session() as session:
        row=session.get(LedgerMutationRequest,p['request_id']);data=json.loads(row.result_json)
        data['expires_at']=(utcnow()-timedelta(seconds=1)).isoformat();row.result_json=json.dumps(data)
        session.commit()
    with pytest.raises(RequirementExchangeError):remote_confirm(service,auth,p)


def test_remote_cannot_reuse_receipt_after_authorization_revoked(tmp_path):
    from backend.app.services.customer_context_gateway import CustomerContextGatewayError
    db,reader,auth,service=setup(tmp_path)
    p=proposed(service,auth,gpt_confirmation=True)
    remote_confirm(service,auth,p)
    bind(reader,auth['conversation_id'])
    with pytest.raises(CustomerContextGatewayError):remote_confirm(service,auth,p)


def test_remote_confirmation_is_bound_to_original_customer_grant(tmp_path):
    from backend.tests.test_customer_context_thread_bindings import add_second_conversation
    db,reader,auth,service=setup(tmp_path)
    p=proposed(service,auth,gpt_confirmation=True)
    cid=add_second_conversation(db)
    with db.session() as session:
        session.add(BusinessCustomer(id='second-fixture',name='Synthetic B'))
        session.flush()
        session.add(CustomerChannelIdentity(id='second-identity',customer_id='second-fixture',channel='xianyu',
            external_customer_id='parallel-customer',conversation_id=cid,display_name='Synthetic B'))
        session.commit()
    key=bind(reader,cid)
    other=reader.gateway.authorize_access(**credentials(reader,key),provider='openai',
        tool_name='requirement_blueprint_confirm',scopes=['text'])
    with pytest.raises(RequirementExchangeError,match='当前客户授权'):remote_confirm(service,other,p)
    assert remote_confirm(service,auth,p)['version']==1


def test_image_evidence_deleted_after_preview_rejects_confirmation(tmp_path):
    from backend.app.models import CustomerImageArchive, CustomerContextGrant, utcnow
    db,reader,auth,service=setup(tmp_path)
    with db.session() as session:
        session.get(CustomerContextGrant,auth['grant_id']).allow_images=True
        session.add(CustomerImageArchive(id='synthetic-evidence-image',conversation_id=auth['conversation_id'],
            message_id=1,channel='xianyu',platform_message_id='reader-1',media_index=0,
            capture_status='stored',capture_source='live',received_at=utcnow()))
        session.commit()
    doc=blueprint();doc['evidence_refs']=[{'id':'ev-image','archive_id':'synthetic-evidence-image','quote':'synthetic image evidence'}]
    proposal=proposed(service,auth,doc)
    with db.session() as session:
        session.get(CustomerImageArchive,'synthetic-evidence-image').deleted_at=utcnow()
        session.commit()
    with pytest.raises(RequirementExchangeError,match='图片证据已失效'):
        confirm(service,proposal)


def test_explicit_agent_conversion_preserves_keys_evidence_and_boundaries():
    from backend.tests.test_customer_auto_analysis import result_payload
    from backend.app.services.requirement_conversion import convert_agent_blueprint
    data=result_payload(1)
    source=data['requirement_blueprint'];plan=data['execution_plan']
    source['stages'][0]['estimated_hours']=8
    refs=source['objectives'][0]['evidence_refs']
    args=dict(project_type='定制开发',stage_mapping={'stage_main':'plan_stage_main'},implementations={'stage_main':'按明确文件范围实现'},
        evidence_refs=[{'id':'ev-one','message_id':1,'quote':'synthetic'}],evidence_mapping={ref:'ev-one' for ref in refs})
    result=convert_agent_blueprint(source,plan,**args)
    assert result.stages[0].task_key=='CCTX-201'
    assert result.stages[0].workspace_key=='customer-context/analysis'
    assert result.stages[0].deliverables==plan['stages'][0]['deliverables']
    assert result.stages[0].process_tests==plan['stages'][0]['process_tests']
    assert plan['must_not_change'][0] in result.out_of_scope
    assert result.objectives[0].evidence_refs==['ev-one']
    with pytest.raises(ValueError):convert_agent_blueprint(source,plan,**(args|{'stage_mapping':{}}))


def test_project_reads_formal_latest_generates_tasks_and_keeps_legacy(tmp_path):
    from backend.app.ledger import LedgerService, default_snapshot
    from backend.app.services.project_task_drafts import ProjectTaskDraftService, ProjectTaskDraftError
    from backend.app.models import BusinessTask
    db,reader,auth,service=setup(tmp_path)
    ledger=LedgerService(db,tmp_path)
    snapshot=default_snapshot()
    snapshot['customers']=[{'id':'customer-fixture','name':'Synthetic customer','source':'xianyu','level':'C','followUpStatus':'contacted'}]
    snapshot['projects']=[{'id':'project-fixture','name':'Synthetic project','customerId':'customer-fixture','projectKind':'client',
        'totalAmount':4000,'startDate':'2026-09-01','dueDate':'2026-09-20','progress':0,'status':'pending','estimatedHours':10,'accent':'blue'}]
    ledger.save(snapshot,0)
    v1=confirm(service,proposed(service,auth))
    with db.session() as session:
        case=session.get(RequirementCase,v1['case_id']);case.project_id='project-fixture'
        legacy=RequirementDocumentVersion(project_id='project-fixture',version=9,title='legacy',schema_version='2.0',
            source_type='project_file_import',readiness='approved',change_summary='historical',structured_json=json.dumps(blueprint()),content_markdown='',model='fixture')
        session.add(legacy);session.commit();legacy_id=legacy.id
    drafts=ProjectTaskDraftService(db,ledger)
    assert drafts.list_blueprints('project-fixture')[0]['id']==v1['version_id']
    revision,before=ledger.get()
    preview=drafts.create_preview('project-fixture',expected_revision=revision,requirement_version_id=v1['version_id'])
    result=drafts.confirm('project-fixture',request_id='confirm-formal-task-001',expected_revision=revision,
        preview_id=preview['id'],preview_token=preview['preview_token'],selected_task_keys=['frontend-dashboard'],apply_allowed_updates_only=True,note='人工确认正式需求任务')
    with db.session() as session:
        task=session.get(BusinessTask,result['created_task_ids'][0])
        assert json.loads(task.deliverables_json)==['响应式页面']
        assert json.loads(task.stage_payload_json)['acceptanceCriteria']==blueprint()['acceptance_gates'][0]['criteria']
        assert task.status=='todo'
        assert session.get(RequirementDocumentVersion,legacy_id).source_type=='project_file_import'
    stale_revision=ledger.get()[0]
    stale_preview=drafts.create_preview('project-fixture',expected_revision=stale_revision,requirement_version_id=v1['version_id'])
    v2=confirm(service,proposed(service,auth,case_id=v1['case_id'],expected_version=1))
    with pytest.raises(ProjectTaskDraftError):
        drafts.confirm('project-fixture',request_id='stale-formal-task-001',expected_revision=stale_revision,
            preview_id=stale_preview['id'],preview_token=stale_preview['preview_token'],selected_task_keys=[],
            apply_allowed_updates_only=True,note='stale proposal must be refused')
    assert drafts.list_blueprints('project-fixture')[0]['version']==2
    with pytest.raises(ProjectTaskDraftError):drafts.create_preview('project-fixture',expected_revision=ledger.get()[0],requirement_version_id=v1['version_id'])
    _,after=ledger.get()
    assert after['projects'][0]['totalAmount']==before['projects'][0]['totalAmount']
    assert after['projects'][0]['status']==before['projects'][0]['status']


def test_project_link_is_explicit_and_blocks_other_customer(tmp_path):
    from backend.app.ledger import LedgerService, default_snapshot
    db,reader,auth,service=setup(tmp_path)
    v1=confirm(service,proposed(service,auth))
    ledger=LedgerService(db,tmp_path);snap=default_snapshot()
    snap['customers']=[{'id':'customer-fixture','name':'Synthetic','source':'other','level':'C','followUpStatus':'contacted'}]
    snap['projects']=[{'id':'project-link','name':'Synthetic','customerId':'customer-fixture','projectKind':'client','totalAmount':1,'startDate':'2026-09-01','dueDate':'2026-09-10','progress':0,'status':'pending','accent':'blue'}]
    revision,_=ledger.save(snap,0)
    app=FastAPI();app.state.runtime=SimpleNamespace(database=db,ledger=ledger);app.include_router(requirement_proposal_router)
    client=TestClient(app);url='/api/projects/project-link/requirement-case';headers={'X-Yuda-Desktop':'1'}
    payload={'case_id':v1['case_id'],'expected_revision':revision,'request_id':'formal-link-001','confirmed':False}
    assert client.post(url,json=payload,headers=headers).status_code==422
    payload['confirmed']=True
    response=client.post(url,json=payload,headers=headers)
    assert response.status_code==200
    assert client.post(url,json=payload,headers=headers).json()==response.json()
    assert client.post(url,json=payload|{'case_id':'different-case'},headers=headers).status_code==409
