from datetime import datetime, timezone
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from backend.app.database import Database
from backend.app.api import router
from backend.app.models import Conversation, Message

def test_conversation_list_uses_one_query_and_stable_last_message(tmp_path):
    db=Database(f'sqlite:///{tmp_path / "test.db"}');db.create_all()
    now=datetime.now(timezone.utc)
    with db.session() as s:
        c=Conversation(external_id='synthetic',customer_id='synthetic',customer_name='Synthetic',unread_count=2,last_message_at=now);s.add(c);s.flush()
        for i in range(2):s.add(Message(external_id=f'synthetic-{i}',conversation_id=c.id,direction='inbound',content=f'synthetic-{i}',received_at=now,sender_id='synthetic'))
        s.commit()
    app=FastAPI();app.state.runtime=SimpleNamespace(database=db);app.include_router(router)
    statements=[]
    event.listen(db.engine,'before_cursor_execute',lambda conn,cursor,stmt,params,ctx,many:statements.append(stmt))
    with TestClient(app) as client:
        response=client.get('/api/conversations?channel=xianyu')
    assert response.status_code==200 and response.json()[0]['last_message']=='synthetic-1'
    assert len(statements)==1
    assert response.json()[0]['unread_count']==2
