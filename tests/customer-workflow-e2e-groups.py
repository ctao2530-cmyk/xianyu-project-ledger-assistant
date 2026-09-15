"""Independent membership, audit, concurrency and grant-boundary checks."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from sqlalchemy import select, func

from backend.app.database import Database
from backend.app.models import BusinessCustomer, Conversation, CustomerChannelIdentity, Message, CustomerContextGrant
from backend.app.customer_conversation_models import CustomerConversationGroupMutation
from backend.app.services.customer_conversation_groups import CustomerConversationGroupService, ConversationGroupError, grant_conversation_scope
from backend.app.services.customer_context_gateway import CustomerContextGateway, CustomerContextGatewayError
from backend.app.services.customer_context_reader import CustomerContextReadService


def seed_groups(tmp_path):
    db=Database(f"sqlite:///{tmp_path/'groups.db'}")
    db.create_all()
    with db.session() as session:
        session.add_all([BusinessCustomer(id='qa-a',name='同昵称'),BusinessCustomer(id='qa-b',name='同昵称')])
        session.flush()
        ids=[]
        for index in range(1,5):
            identity='stable-a' if index<4 else 'stable-b'
            row=Conversation(channel='xianyu',external_id=f'qa-conversation-{index}',customer_id=identity,customer_name='同昵称')
            session.add(row);session.flush();ids.append(row.id)
            session.add(Message(channel='xianyu',external_id=f'qa-message-{index}',platform_message_id=f'qa-message-{index}',conversation_id=row.id,sender_id=identity,sender_name='同昵称',direction='inbound',message_type='text',content='相同文字',status='new'))
        session.add_all([CustomerChannelIdentity(id='identity-a',customer_id='qa-a',channel='xianyu',external_customer_id='stable-a'),CustomerChannelIdentity(id='identity-b',customer_id='qa-b',channel='xianyu',external_customer_id='stable-b')])
        session.commit()
    return db,CustomerConversationGroupService(db),ids


def confirmed(service,ids,*,group_id=None,revision=0,request_id='qa-create-group'):
    values=dict(group_id=group_id,conversation_ids=ids,expected_revision=revision,request_id=request_id,reason='独立合成测试确认范围')
    preview=service.change('qa-a',**values)
    return service.change('qa-a',**values,confirmed=True,preview_token=preview['preview_token'])


def test_same_nickname_never_substitutes_stable_identity(tmp_path):
    db,service,ids=seed_groups(tmp_path)
    assert {row['conversation_id'] for row in service.candidates('qa-a')['conversations']}==set(ids[:3])
    with pytest.raises(ConversationGroupError,match='稳定渠道身份'):
        confirmed(service,[ids[0],ids[3]])
    group=confirmed(service,ids[:2])
    timeline=service.timeline(group['id'])
    assert len(timeline['messages'])==2 # identical bodies must not collapse
    assert {row['conversation_id'] for row in timeline['messages']}==set(ids[:2])
    assert all(row['source_status']=='unknown' for row in timeline['messages'])


def test_change_is_idempotent_concurrent_and_auditable(tmp_path):
    db,service,ids=seed_groups(tmp_path)
    values=dict(conversation_ids=ids[:2],expected_revision=0,request_id='qa-concurrent-create',reason='并发合成确认')
    preview=service.change('qa-a',**values)
    def commit():
        return service.change('qa-a',**values,confirmed=True,preview_token=preview['preview_token'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:commit(),range(2)))
    assert results[0]['id']==results[1]['id']
    assert sum(bool(r.get('idempotent')) for r in results)==1
    group=results[0]
    with pytest.raises(ConversationGroupError) as conflict:
        confirmed(service,ids[:3],group_id=group['id'],revision=0,request_id='qa-stale-change')
    assert conflict.value.code=='group_revision_conflict'
    ended=confirmed(service,[],group_id=group['id'],revision=1,request_id='qa-disband-group')
    assert ended['status']=='disbanded'
    with pytest.raises(ConversationGroupError):
        service.timeline(group['id'])
    with db.session() as session:
        assert session.scalar(select(func.count(Message.id)))==4
        assert session.scalar(select(func.count(Conversation.id)))==4
        assert session.scalar(select(func.count(CustomerConversationGroupMutation.request_id)))==2


def test_group_scope_never_expands_and_removal_revokes_permanently(tmp_path):
    db,service,ids=seed_groups(tmp_path)
    group=confirmed(service,ids[:2])
    gateway=CustomerContextGateway(db)
    binding=gateway.create_thread_binding(conversation_id=ids[0],request_id='qa-group-bind-key',expected_conversation_revision=0,auth_mode='tunnel_binding',allow_text=True,allow_images=True,allow_artifacts=False,allow_new_messages=True,expires_in_seconds=900,authorization_note='合成成员明确授权',group_id=group['id'],expected_group_revision=1,selected_conversation_ids=ids[:2])
    grant=gateway.resolve_active_thread_binding(binding['context_key'],auth_mode='tunnel_binding')
    reader=CustomerContextReadService(db,gateway,tmp_path)
    first=reader.read_text(request_id='qa-group-read-initial',grant_id=grant['id'],audience='openai_chatgpt',target_model='synthetic')
    assert {m['message_id'] for m in first['messages']}==set(ids[:2])
    expanded=confirmed(service,ids[:3],group_id=group['id'],revision=1,request_id='qa-expand-group')
    with db.session() as session:
        scope,_=grant_conversation_scope(session,session.get(CustomerContextGrant,grant['id']))
        assert set(scope)==set(ids[:2])
    confirmed(service,[ids[0],ids[2]],group_id=group['id'],revision=expanded['revision'],request_id='qa-remove-selected')
    with pytest.raises(CustomerContextGatewayError):
        gateway.resolve_active_thread_binding(binding['context_key'],auth_mode='tunnel_binding')
    confirmed(service,ids[:3],group_id=group['id'],revision=3,request_id='qa-readd-selected')
    with pytest.raises(CustomerContextGatewayError):
        gateway.resolve_active_thread_binding(binding['context_key'],auth_mode='tunnel_binding')


def test_group_binding_rejects_unselected_and_other_customer(tmp_path):
    db,service,ids=seed_groups(tmp_path)
    group=confirmed(service,ids[:2])
    gateway=CustomerContextGateway(db)
    for selected in ([ids[0],ids[2]],[ids[0],ids[3]]):
        with pytest.raises(CustomerContextGatewayError):
            gateway.create_thread_binding(conversation_id=ids[0],request_id='qa-invalid-scope-'+str(selected[-1]),expected_conversation_revision=0,auth_mode='tunnel_binding',allow_text=True,allow_images=True,allow_artifacts=False,allow_new_messages=True,expires_in_seconds=900,authorization_note='合成拒绝范围',group_id=group['id'],expected_group_revision=1,selected_conversation_ids=selected)


def test_frontend_group_api_contract_and_image_timeline(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.customer_conversation_api import customer_conversation_router
    from backend.app.services.customer_images import CustomerImageArchiveService
    from backend.tests.test_customer_images import original_jpeg
    db,service,ids=seed_groups(tmp_path)
    image_service=CustomerImageArchiveService(db,tmp_path)
    with db.session() as session:
        msg=session.scalar(select(Message).where(Message.conversation_id==ids[0]));msg.message_type='image';msg.content='[图片]';session.commit();mid=msg.id
    image=image_service.store_original(mid,0,data=original_jpeg(),content_type='image/jpeg',original_name='synthetic.jpg',capture_source='test')
    app=FastAPI();app.state.runtime=SimpleNamespace(database=db);app.include_router(customer_conversation_router)
    with TestClient(app,base_url='http://127.0.0.1:8877') as client:
        headers={'X-Yuda-Desktop':'1'}
        response=client.get('/api/customers/qa-a/conversation-group-candidates',headers=headers)
        assert response.status_code==200
        assert set(response.json())=={'conversations','groups'}
        payload={'conversation_ids':ids[:2],'expected_revision':0,'request_id':'qa-ui-contract','reason':'合成接口验收','confirmed':False}
        preview=client.post('/api/customers/qa-a/conversation-groups/preview',json=payload,headers=headers)
        assert preview.status_code==200,preview.text
        body=preview.json();assert body['effects']['added']==ids[:2]
        saved=client.post('/api/customers/qa-a/conversation-groups',json={**payload,'confirmed':True,'preview_token':body['preview_token']},headers=headers)
        assert saved.status_code==200,saved.text
        group=saved.json();assert group['active'] is True and group['title']
        timeline=client.get(f"/api/conversation-groups/{group['id']}/timeline?limit=100&offset=0",headers=headers)
        assert timeline.status_code==200,timeline.text
        page=timeline.json();assert page['total_count']==2 and page['has_more'] is False
        assert image['id'] in {entry['id'] for message in page['messages'] for entry in message['images']}
