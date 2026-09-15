from dataclasses import replace
from datetime import timedelta

from sqlalchemy import select
from backend.app.database import Database
from backend.app.models import Conversation
from backend.app.services.customer_names import stable_customer_name
from backend.app.services.repository import ingest_message
from backend.app.services.conversation_history_import import ConversationHistoryImportService
from backend.tests.test_repository import make_event


def test_name_is_fixed_across_messages_and_replay(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'names.db'}")
    db.create_all()
    first = make_event()
    with db.session() as session:
        ingest_message(session, first, [], None)
        for index, name in enumerate(['我完成了评价', '工作台通知', '改过的昵称']):
            ingest_message(session, replace(first, external_id=f'new-{index}', platform_message_id=f'new-{index}', sender_name=name), [], None)
        ingest_message(session, replace(first, sender_name='通知'), [], None)
        assert session.scalar(select(Conversation)).customer_name == '客户甲'


def test_placeholder_can_be_filled_but_notification_cannot_be_name():
    assert stable_customer_name('闲鱼客户', '客户甲') == '客户甲'
    assert stable_customer_name(None, '工作台通知') == '闲鱼客户'
    assert stable_customer_name('客户甲', '客户乙') == '客户甲'


def test_history_uses_first_name_and_preserves_existing():
    first = make_event()
    later = replace(first, sender_name='我完成了评价', received_at=first.received_at + timedelta(seconds=1))
    assert ConversationHistoryImportService._customer_identity([later, first], None)[1] == '客户甲'
    existing = Conversation(customer_id='buyer-1', customer_name='已保存姓名')
    assert ConversationHistoryImportService._customer_identity([first, later], existing)[1] == '已保存姓名'


def test_customers_are_independent(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'isolated.db'}")
    db.create_all()
    with db.session() as session:
        ingest_message(session, make_event(), [], None)
        ingest_message(session, replace(make_event(), external_id='other', platform_message_id='other', conversation_id='other', sender_id='buyer-2', sender_name='客户乙'), [], None)
        assert [c.customer_name for c in session.scalars(select(Conversation).order_by(Conversation.id))] == ['客户甲', '客户乙']
