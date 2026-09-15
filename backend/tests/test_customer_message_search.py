from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.app.database import Database
from backend.app.models import BusinessCustomer, CustomerChannelIdentity, Conversation, Message
from backend.app.customer_conversation_api import customer_conversation_router


@pytest.fixture
def setup(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "search.db"}')
    db.create_all()
    with db.session() as session:
        session.add_all([BusinessCustomer(id='a',name='合成同昵称'), BusinessCustomer(id='b',name='合成同昵称')])
        session.flush()
        for index in range(1,5):
            session.add(Conversation(id=index,channel='xianyu',external_id=f'conv-{index}',customer_id='stable-a' if index<3 else f'stable-{index}',customer_name='合成同昵称',unread_count=7))
        session.add_all([CustomerChannelIdentity(id='ia',customer_id='a',channel='xianyu',external_customer_id='stable-a'),CustomerChannelIdentity(id='ib',customer_id='b',channel='xianyu',external_customer_id='stable-3')])
        session.flush()
        for index in range(1,241):
            stamp = datetime(2026,9,10,16,0,index%60,tzinfo=timezone.utc)
            session.add(Message(id=index,channel='xianyu',external_id=f'msg-{index}',platform_message_id=f'msg-{index}',conversation_id=1 if index<=220 else 2 if index<=230 else 3,sender_id='synthetic',sender_name='合成',direction='inbound',message_type='text',content=f'合成 keyword {index}',status='new',received_at=stamp))
        session.add(Message(id=241,channel='xianyu',external_id='literal',platform_message_id='literal',conversation_id=1,sender_id='synthetic',sender_name='合成',direction='inbound',message_type='text',content='100%_literal',status='new',received_at=datetime(2026,9,10,15,59,59,tzinfo=timezone.utc)))
        session.commit()
    app=FastAPI();app.state.runtime=SimpleNamespace(database=db);app.include_router(customer_conversation_router)
    with TestClient(app) as client:
        yield client,db


def test_search_full_saved_history_and_stable_paging(setup):
    client,db=setup
    params={'customer_id':'a','conversation_ids':[1,2],'query':'keyword','limit':100}
    ids=[]
    for _ in range(3):
        response=client.get('/api/customer-message-search',params=params);assert response.status_code==200
        data=response.json();ids.extend(item['id'] for item in data['items'])
        assert data['total']==230
        if not data['has_more']:break
        params['before_message_id']=data['next_before_message_id']
    assert len(ids)==len(set(ids))==230
    with db.session() as session: assert session.get(Conversation,1).unread_count==7


@pytest.mark.parametrize('params,status',[
    ({'customer_id':'b','conversation_ids':[1]},403),
    ({'customer_id':'a','conversation_ids':[3]},403),
    ({'customer_id':'a'},403),
    ({'conversation_id':999},404),
    ({'customer_id':'a','conversation_id':1},422),
])
def test_scope_cannot_expand_by_nickname_or_id(setup,params,status):
    client,_=setup
    assert client.get('/api/customer-message-search',params={**params,'query':'keyword'}).status_code==status


def test_beijing_dates_literal_query_and_empty(setup):
    client,_=setup
    url='/api/customer-message-search'
    p={'conversation_id':1,'query':'keyword','date_from':'2026-09-10','date_to':'2026-09-10'}
    assert client.get(url,params=p).json()['total']==0
    p.update(date_from='2026-09-11',date_to='2026-09-11')
    assert client.get(url,params=p).json()['total']==220
    assert client.get(url,params={'conversation_id':1,'query':'%_'}).json()['total']==1
    assert client.get(url,params={'conversation_id':1,'query':'   '}).status_code==422
    assert client.get(url,params={**p,'date_from':'2026-09-12'}).status_code==422
    assert client.get(url,params={'conversation_id':1,'query':'keyword','date_to':'9999-12-31'}).status_code==422
    assert client.get(url,params={'conversation_id':1,'query':'keyword','date_from':'0001-01-01'}).status_code==422


def test_context_and_cursors_are_bound_and_read_only(setup):
    client,db=setup
    url='/api/customer-message-search/context'
    assert client.get(url,params={'customer_id':'b','conversation_ids':3,'message_id':1}).status_code==404
    data=client.get(url,params={'customer_id':'a','conversation_ids':1,'message_id':100}).json()
    assert len(data['messages'])==11
    assert 100 in [m['id'] for m in data['messages']]
    assert all(m['conversation_id']==1 and (m['received_at'].endswith('Z') or m['received_at'].endswith('+00:00')) for m in data['messages'])
    assert client.get('/api/customer-message-search',params={'customer_id':'a','conversation_ids':1,'query':'keyword','before_message_id':231}).status_code==409
    with db.session() as session:
        assert session.get(Conversation,1).unread_count==7
        assert all(m.status=='new' for m in session.scalars(select(Message)))


def test_remote_access_and_forwarded_headers_rejected(setup):
    client,_=setup
    for path in ['/api/customer-message-search?conversation_id=1&query=keyword','/api/customer-message-search/context?conversation_id=1&message_id=1']:
        assert client.get(path,headers={'x-forwarded-for':'203.0.113.9'}).status_code==403
        assert client.get(path,headers={'host':'example.com'}).status_code==403


def test_search_does_not_write_schema_or_business_records(setup):
    client,db=setup
    def schema():
        with db.engine.connect() as connection:
            return list(connection.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name"))
    original=schema()
    assert client.get('/api/customer-message-search',params={'conversation_id':1,'query':'keyword'}).status_code==200
    assert client.get('/api/customer-message-search/context',params={'conversation_id':1,'message_id':100}).status_code==200
    assert schema()==original
    with db.session() as session:
        assert session.get(Conversation,1).unread_count==7
        assert len(list(session.scalars(select(Message))))==241
