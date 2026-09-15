from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters.xianyu import _parse_live_message_candidate
from backend.app.api import router, message_view
from backend.app.customer_image_api import customer_image_router
from backend.app.database import Database
from backend.app.models import Message
from backend.app.services.repository import ingest_message
from backend.app.services.customer_images import CustomerImageArchiveService
from backend.tests.test_customer_images import original_jpeg
from backend.app.customer_time import utc_from_storage


@pytest.mark.parametrize('stamp', ['2026-09-08T10:53:00+00:00', '2026-09-08T16:30:00+00:00'])
def test_platform_sqlite_api_preserves_instant(tmp_path, stamp):
    expected = datetime.fromisoformat(stamp)
    event = _parse_live_message_candidate({'2': 'synthetic-time', '5': int(expected.timestamp()*1000), '10': {'senderUserId': 'synthetic', 'reminderContent': '[图片]'}}, 'seller')
    assert event.received_at == expected and event.received_at.tzinfo is not None
    db = Database(f'sqlite:///{tmp_path / "time.db"}')
    db.create_all()
    with db.session() as session:
        result = ingest_message(session, event, [], None)
        row = session.get(Message, result.message_id)
        cid = row.conversation_id
        assert row.received_at == expected.replace(tzinfo=None)  # SQLite drops only the zone.
        anchor = Message(channel='xianyu', platform_message_id='anchor', external_id='anchor', conversation_id=cid, sender_id='synthetic', sender_name='synthetic', direction='inbound', message_type='text', content='anchor', status='new', received_at=expected)
        session.add(anchor)
        session.commit()
        anchor_id = anchor.id
    images = CustomerImageArchiveService(db, tmp_path)
    images.store_original(result.message_id, 0, data=original_jpeg(), content_type='image/jpeg', original_name='synthetic.jpg', capture_source='test')
    app = FastAPI()
    app.state.runtime = SimpleNamespace(database=db, customer_images=images)
    app.include_router(router)
    app.include_router(customer_image_router)
    with TestClient(app) as client:
        listing = client.get('/api/conversations').json()[0]
        detail = client.get(f'/api/conversations/{cid}').json()['messages'][0]
        old = client.get(f'/api/conversations/{cid}/messages', params={'before_message_id':anchor_id}).json()['messages'][0]
        image = client.get('/api/customer-images').json()['items'][0]
        for value in [listing['last_message_at'], detail['received_at'], old['received_at'], image['received_at'], detail['images'][0]['received_at']]:
            assert datetime.fromisoformat(value.replace('Z', '+00:00')) == expected
        assert datetime.fromisoformat(image['captured_at'].replace('Z', '+00:00')).tzinfo is not None
        local_day = '2026-09-09' if expected.hour == 16 else '2026-09-08'
        assert client.get('/api/customer-images', params={'date_from':local_day,'date_to':local_day}).json()['total'] == 1
        other_day = '2026-09-08' if expected.hour == 16 else '2026-09-09'
        assert client.get('/api/customer-images', params={'date_from':other_day,'date_to':other_day}).json()['total'] == 0


def test_existing_aware_message_is_not_shifted_twice():
    stamp = datetime.fromisoformat('2026-09-08T18:53:00+08:00')
    row = Message(id=1, channel='xianyu', platform_message_id='synthetic', external_id='synthetic', sender_name='synthetic', direction='inbound', message_type='text', content='synthetic', status='new', risk_flags_json='[]', received_at=stamp)
    assert message_view(row).received_at == stamp
    assert utc_from_storage(stamp) is stamp
    assert utc_from_storage(None) is None
    from backend.app.models import CustomerImageArchive
    image = CustomerImageArchive(id='synthetic', received_at=stamp, captured_at=stamp)
    assert CustomerImageArchiveService._view(image, '')['received_at'] == stamp


def test_shanghai_date_filter_exact_midnight():
    parse = CustomerImageArchiveService._parse_date_bound
    assert parse('2026-09-09', end=False) == datetime(2026,9,8,16,tzinfo=timezone.utc)
    assert parse('2026-09-09', end=True) == datetime(2026,9,9,15,59,59,999999,tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_history_preview_and_import_keep_platform_time(tmp_path):
    from dataclasses import replace
    from fastapi.encoders import jsonable_encoder
    from backend.tests.test_conversation_history_import import build_service, history_message
    expected = datetime(2026,9,8,10,53,tzinfo=timezone.utc)
    event = replace(history_message('synthetic-old', with_media=True, message_type='image'), received_at=expected)
    service, db, _, _ = build_service(tmp_path, [event])
    preview = await service.preview(external_conversation_id=event.conversation_id, message_limit=100)
    stamp = jsonable_encoder(preview)['messages'][0]['received_at']
    assert datetime.fromisoformat(stamp.replace('Z','+00:00')) == expected
    result = await service.commit(request_id='synthetic-time-import', preview_token=preview['token'])
    from sqlalchemy import select
    with db.session() as session:
        row = session.scalar(select(Message).where(Message.conversation_id == result['conversation_id']))
        assert row.received_at == expected.replace(tzinfo=None)
        assert message_view(row).received_at == expected
        assert CustomerImageArchiveService._view(row.customer_images[0], '')['received_at'] == expected
