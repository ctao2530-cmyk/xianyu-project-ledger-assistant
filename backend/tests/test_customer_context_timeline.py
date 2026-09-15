"""Synthetic SQLite/MCP contract tests; no real data, model or network access."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from uuid import uuid4

from PIL import Image
import pytest
from sqlalchemy import select

from backend.app.database import Database
from backend.app.models import Conversation, Message, CustomerImageArchive, CustomerContextGrant, utcnow
from backend.app.customer_sync_models import CustomerContextSyncState
from backend.app.services.customer_context_gateway import CustomerContextGateway, CustomerContextGatewayError
from backend.app.services.customer_context_reader import CustomerContextReadService
from backend.app.services.customer_context_timeline import build_event_timeline, event_time
from backend.app.services.customer_images import CustomerImageArchiveService
from backend.tests.test_customer_context_sync import credentials, image_binding, confirm


def synthetic_png():
    output = BytesIO()
    Image.new('RGB', (4, 3), '#4488bb').save(output, format='PNG')
    return output.getvalue()


def make_message(db, cid, timestamp, kind='text', content='synthetic text'):
    with db.session() as session:
        row = Message(conversation_id=cid, channel='xianyu', external_id=uuid4().hex,
            platform_message_id=uuid4().hex, sender_id='synthetic-customer', sender_name='synthetic',
            direction='inbound', message_type=kind, content=content, status='new',
            received_at=datetime.fromisoformat(timestamp))
        session.add(row)
        session.commit()
        return row.id


@pytest.fixture
def context(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "timeline.db"}')
    db.create_all()
    with db.session() as session:
        row = Conversation(channel='xianyu', external_id='synthetic-timeline',
            customer_id='synthetic-customer', customer_name='synthetic')
        session.add(row)
        session.commit()
        cid = row.id
    reader = CustomerContextReadService(db, CustomerContextGateway(db), tmp_path)
    # Deliberately inserted out of event order. The watermark must remain ID-based.
    ids = [make_message(db, cid, '2026-09-10T10:55:00'),
        make_message(db, cid, '2026-09-10T10:54:00', 'image', '[图片]'),
        make_message(db, cid, '2026-09-10T10:53:00')]
    archive_service = CustomerImageArchiveService(db, tmp_path)
    for index in (2, 0):
        archive_service.store_original(ids[1], index, data=synthetic_png(), content_type='image/png',
            original_name='synthetic.png', capture_source='test')
    # Archive timestamps intentionally differ: the timeline must use Message.received_at.
    with db.session() as session:
        for row in session.scalars(select(CustomerImageArchive)):
            row.received_at = datetime(2026, 9, 11)
        session.commit()
    key = image_binding(reader, cid)
    return db, reader, cid, ids, key


def timeline(reader, key):
    return reader.read_text(include_timeline=True, **credentials(reader, key))


def stored_reads(reader, key, result):
    for event in result['events']:
        if event['type'] == 'image' and event['status'] == 'stored':
            image = reader.read_image(event['archive_id'], representation='compatible', **credentials(reader, key))
            reader.mark_image_transport(archive_id=image.archive_id, source_sha256=image.source_sha256,
                **credentials(reader, key))


def test_timeline_orders_by_message_time_but_preserves_watermarks_and_legacy_fields(context):
    db, reader, cid, ids, key = context
    legacy = reader.read_text(**credentials(reader, key))
    manifest = reader.image_manifest(**credentials(reader, key))
    result = timeline(reader, key)
    assert [event['type'] for event in result['events']] == ['text', 'image', 'image', 'text']
    assert [event['message_id'] for event in result['events']] == [ids[2], ids[1], ids[1], ids[0]]
    assert [event['media_index'] for event in result['events'] if event['type'] == 'image'] == [0, 2]
    assert all(event['received_at'].endswith('+00:00') for event in result['events'])
    assert {e['received_at'] for e in result['events'] if e['type'] == 'image'} == {'2026-09-10T10:54:00+00:00'}
    for field in ('messages', 'batch_id', 'source_hash', 'latest_text_message_id', 'acknowledged_through_message_id'):
        assert result[field] == legacy[field]
    assert result['latest_text_message_id'] == ids[2] != result['events'][-1]['message_id']
    assert result['image_revision'] == manifest['image_revision']
    assert result['image_batch_id'] == manifest['batch_id']
    assert {e['archive_id'] for e in result['events'] if e['type'] == 'image'} == {r['archive_id'] for r in manifest['images']}
    assert 'events' not in legacy  # explicit legacy reader behavior is unchanged
    assert 'storage_path' not in json.dumps(result)
    assert all(e['conversation_id'] == cid and e['untrusted'] for e in result['events'])


def test_timezone_instant_then_numeric_id_and_same_message_order():
    sources = {2: dict(message_id=2, conversation_id=1, direction='inbound', received_at='2026-09-10T18:53:00+08:00'),
        10: dict(message_id=10, conversation_id=1, direction='inbound', received_at='2026-09-10T10:53:00Z')}
    text = {'messages': [dict(message_id=10, content='ten'), dict(message_id=2, content='two')]}
    images = [dict(archive_id='b', message_id=2, media_index=0, capture_status='pending', error_code='', mime_type=''),
        dict(archive_id='a', message_id=2, media_index=0, capture_status='pending', error_code='', mime_type='')]
    result = build_event_timeline(text, images, sources)
    assert [(e['message_id'], e['type'], e['archive_id']) for e in result] == [(2, 'text', None), (2, 'image', 'a'), (2, 'image', 'b'), (10, 'text', None)]
    assert {e['received_at'] for e in result} == {'2026-09-10T10:53:00+00:00'}
    assert event_time('2026-09-10T16:30:00Z').astimezone(timezone(timedelta(hours=8))).day == 11
    with pytest.raises(ValueError):
        event_time('not-a-date')


def test_caption_is_preserved_without_becoming_a_new_text_watermark(context):
    db, reader, cid, ids, key = context
    with db.session() as session:
        session.get(Message, ids[1]).content = 'synthetic image caption'
        session.commit()
    result = timeline(reader, key)
    same_message = [e for e in result['events'] if e['message_id'] == ids[1]]
    assert [e['type'] for e in same_message] == ['text', 'image', 'image']
    assert same_message[0]['content'] == 'synthetic image caption'
    assert same_message[0]['context_origin'] == 'image_message_context'
    assert result['new_message_count'] == 2


def test_unified_confirmation_requires_actual_images_but_legacy_text_is_compatible(context):
    db, reader, cid, ids, key = context
    result = timeline(reader, key)
    with pytest.raises(CustomerContextGatewayError) as error:
        confirm(reader, key, result, {'facts': []})
    assert error.value.code == 'timeline_images_unread'
    stored_reads(reader, key, result)
    acknowledged = confirm(reader, key, result, {'evidence_message_ids': ids})
    assert acknowledged['acknowledged_through_message_id'] == max(ids)
    confirm(reader, key, {'batch_id': result['image_batch_id']})
    empty = timeline(reader, key)
    assert empty['events'] == [] and empty['image_revision'] == result['image_revision']
    assert empty['batch_id'] is None and empty['image_batch_id'] is None
    # A text-only legacy read on a new, narrower grant remains independently confirmable.
    narrow = image_binding(reader, cid, allow_images=False)
    old = reader.read_text(**credentials(reader, narrow))
    confirm(reader, narrow, old, {'facts': []})


def test_rekey_replay_and_late_image_delta_do_not_reset_text(context):
    db, reader, cid, ids, key = context
    first = timeline(reader, key)
    replacement = image_binding(reader, cid)
    replay = timeline(reader, replacement)
    assert replay['timeline_source_hash'] == first['timeline_source_hash']
    assert replay['text_batch_id'] == first['text_batch_id']
    assert replay['image_batch_id'] == first['image_batch_id']
    assert replay['context_mode'] == 'incremental_resume'
    stored_reads(reader, replacement, replay)
    confirm(reader, replacement, replay, {'facts': ['synthetic summary']})
    confirm(reader, replacement, {'batch_id': replay['image_batch_id']})
    another = image_binding(reader, cid)
    assert timeline(reader, another)['events'] == []
    service = CustomerImageArchiveService(db, reader.project_root)
    service.store_original(ids[1], 1, data=synthetic_png(), content_type='image/png', original_name='late.png', capture_source='test')
    late = timeline(reader, another)
    assert late['messages'] == [] and late['new_message_count'] == 0
    assert late['acknowledged_through_message_id'] == max(ids)
    assert late['previous_summary'] == {'facts': ['synthetic summary']}
    assert len(late['events']) == 1 and late['events'][0]['message_id'] == ids[1]
    assert late['events'][0]['received_at'] == '2026-09-10T10:54:00+00:00'
    assert late['image_revision'] != replay['image_revision']


@pytest.mark.parametrize('status', ['pending', 'failed', 'deleted'])
def test_per_image_status_is_visible_without_inventing_image_content(context, status):
    db, reader, cid, ids, key = context
    with db.session() as session:
        for image in session.scalars(select(CustomerImageArchive)):
            if status == 'deleted':
                image.deleted_at = utcnow()
            else:
                image.capture_status = status
                image.error_code = 'download_timeout' if status == 'failed' else ''
        session.commit()
    result = timeline(reader, key)
    images = [e for e in result['events'] if e['type'] == 'image']
    assert len(images) == 2 and all(e['status'] == status and e['read_tool'] is None for e in images)
    confirm(reader, key, result, {'facts': ['image contents unknown']})
    confirm(reader, key, {'batch_id': result['image_batch_id']})


def test_text_only_grant_never_queries_images_or_leaks_archive_ids(context, monkeypatch):
    db, reader, cid, ids, key = context
    narrow = image_binding(reader, cid, allow_images=False)
    monkeypatch.setattr(reader, 'image_manifest', lambda **kw: pytest.fail('no image permission'))
    result = timeline(reader, narrow)
    assert all(e['type'] == 'text' and e['archive_id'] is None for e in result['events'])
    assert result['image_revision'] is None and result['image_event_count'] == 0


def test_expiry_revocation_and_cross_customer_isolation(context):
    db, reader, cid, ids, key = context
    with db.session() as session:
        other = Conversation(channel='xianyu', external_id='other', customer_id='other', customer_name='synthetic')
        session.add(other)
        session.commit()
        other_cid = other.id
    other_id = make_message(db, other_cid, '2026-09-10T10:54:30', 'image', '[图片]')
    CustomerImageArchiveService(db, reader.project_root).store_original(other_id, 0, data=synthetic_png(), content_type='image/png', original_name='other.png', capture_source='test')
    result = timeline(reader, key)
    assert all(e['conversation_id'] == cid for e in result['events'])
    other_key = image_binding(reader, other_cid)
    with pytest.raises(CustomerContextGatewayError):
        confirm(reader, other_key, result, {'facts': []})
    grant = reader.gateway.resolve_active_thread_binding(key, auth_mode='tunnel_binding')
    with db.session() as session:
        session.get(CustomerContextGrant, grant['id']).expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    with pytest.raises(CustomerContextGatewayError):
        timeline(reader, key)
    new = image_binding(reader, cid)
    auth = reader.gateway.resolve_active_thread_binding(new, auth_mode='tunnel_binding')
    with db.session() as session:
        session.get(CustomerContextGrant, auth['id']).status = 'revoked'
        session.commit()
    with pytest.raises(CustomerContextGatewayError):
        timeline(reader, new)


def test_concurrent_reads_preserve_independent_batch_versions(context):
    db, reader, cid, ids, key = context
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: timeline(reader, key), range(2)))
    for field in ('events', 'batch_id', 'image_batch_id', 'image_revision', 'timeline_source_hash'):
        assert results[0][field] == results[1][field]
    with db.session() as session:
        state = session.scalar(select(CustomerContextSyncState))
        assert state.text_watermark == 0 and state.text_version == 0 and state.image_version == 0


def test_image_only_and_unsummarized_context_are_in_the_same_timeline(context):
    db, reader, cid, ids, key = context
    first = reader.read_text(**credentials(reader, key))
    confirm(reader, key, first)  # old client consumed but did not summarize text
    result = timeline(reader, key)
    assert result['messages'] == [] and result['new_message_count'] == 0
    assert [e['type'] for e in result['events']] == ['text', 'image', 'image', 'text']
    assert {e['context_origin'] for e in result['events'] if e['type'] == 'text'} == {'unsummarized_context'}
    # A genuinely image-only customer still receives image events.
    with db.session() as session:
        other = Conversation(channel='xianyu', external_id='image-only', customer_id='image-only', customer_name='synthetic')
        session.add(other)
        session.commit()
        other_cid = other.id
    mid = make_message(db, other_cid, '2026-09-10T10:54:30', 'image', '[图片]')
    CustomerImageArchiveService(db, reader.project_root).store_original(mid, 0, data=synthetic_png(), content_type='image/png', original_name='image-only.png', capture_source='test')
    image_only = timeline(reader, image_binding(reader, other_cid))
    assert image_only['messages'] == [] and [e['type'] for e in image_only['events']] == ['image']
    assert image_only['latest_text_message_id'] == 0


def test_static_grant_excludes_new_source_messages(context):
    db, reader, cid, ids, key = context
    auth = reader.gateway.resolve_active_thread_binding(key, auth_mode='tunnel_binding')
    with db.session() as session:
        session.get(CustomerContextGrant, auth['id']).allow_new_messages = False
        session.commit()
    mid = make_message(db, cid, '2026-09-09T01:00:00', 'image', '[图片]')
    CustomerImageArchiveService(db, reader.project_root).store_original(mid, 0, data=synthetic_png(), content_type='image/png', original_name='new.png', capture_source='test')
    result = timeline(reader, key)
    assert mid not in {e['message_id'] for e in result['events']}


def test_image_change_supersedes_link_without_advancing_text(context):
    db, reader, cid, ids, key = context
    old = timeline(reader, key)
    with db.session() as session:
        for image in session.scalars(select(CustomerImageArchive)):
            image.deleted_at = utcnow()
        session.commit()
    reader.image_manifest(**credentials(reader, key))
    with pytest.raises(CustomerContextGatewayError) as error:
        confirm(reader, key, old, {'facts': []})
    assert error.value.code == 'timeline_batch_changed'
    refreshed = timeline(reader, key)
    assert refreshed['text_batch_id'] == old['text_batch_id']
    assert refreshed['image_batch_id'] != old['image_batch_id']
    assert refreshed['acknowledged_through_message_id'] == 0
    confirm(reader, key, refreshed, {'facts': ['image deleted']})


def test_group_timeline_never_includes_unselected_members(context):
    from backend.app.models import BusinessCustomer, CustomerChannelIdentity
    from backend.app.services.customer_conversation_groups import CustomerConversationGroupService
    db, reader, cid, ids, key = context
    with db.session() as session:
        session.add(BusinessCustomer(id='timeline-customer', name='synthetic'))
        session.flush()
        session.add(CustomerChannelIdentity(id='timeline-identity', customer_id='timeline-customer',
            channel='xianyu', external_customer_id='synthetic-customer'))
        members = [cid]
        for index in (2, 3):
            row = Conversation(channel='xianyu', external_id=f'group-{index}', customer_id='synthetic-customer', customer_name='synthetic')
            session.add(row)
            session.flush()
            members.append(row.id)
        session.commit()
    mids = [make_message(db, member, '2026-09-10T10:54:00', 'image', '[图片]') for member in members[1:]]
    service = CustomerImageArchiveService(db, reader.project_root)
    for mid in mids:
        service.store_original(mid, 0, data=synthetic_png(), content_type='image/png', original_name='group.png', capture_source='test')
    groups = CustomerConversationGroupService(db)
    values = dict(conversation_ids=members, expected_revision=0, request_id='timeline-group-preview', reason='synthetic')
    preview = groups.change('timeline-customer', **values)
    group = groups.change('timeline-customer', **values, confirmed=True, preview_token=preview['preview_token'])
    binding = reader.gateway.create_thread_binding(conversation_id=cid, request_id='timeline-group-bind',
        expected_conversation_revision=reader.gateway.conversation_access_state(cid)['revision'],
        auth_mode='tunnel_binding', allow_text=True, allow_images=True, allow_artifacts=False,
        allow_new_messages=True, expires_in_seconds=900, authorization_note='synthetic group scope',
        group_id=group['id'], expected_group_revision=group['revision'], selected_conversation_ids=members[:2])
    result = timeline(reader, binding['context_key'])
    assert {e['conversation_id'] for e in result['events']} == set(members[:2])
    assert mids[1] not in {e['message_id'] for e in result['events']}


def test_mcp_returns_ordered_events_actual_image_and_compatible_tool_schema(context):
    from backend.app.customer_context_mcp import bridge, mcp, get_bound_conversation_context, read_bound_archived_image, confirm_bound_context_batch
    from backend.tests.test_customer_context_tunnel import tunnel_config, mcp_context
    db, reader, cid, ids, key = context
    bridge.bind(reader, reader.gateway, tunnel_config=tunnel_config())
    try:
        async def run():
            catalog = await mcp.list_tools()
            tool = next(t for t in catalog if t.name == 'xunying_get_bound_conversation_context')
            assert set(tool.inputSchema['properties']) == {'context_key'}
            assert '不得先总结全部文字' in tool.description
            response = await get_bound_conversation_context(mcp_context(), context_key=key)
            assert not response.isError
            data = response.structuredContent
            assert json.loads(response.content[0].text)['events'] == data['events']
            assert '不得先总结全部文字再单独处理图片' in data['analysis_instructions']
            blocked = await confirm_bound_context_batch(mcp_context(), context_key=key, batch_id=data['batch_id'], summary={'facts': []})
            assert blocked.isError
            seen = []
            for event in data['events']:
                seen.append(event['type'])
                if event['type'] == 'image':
                    image = await read_bound_archived_image(context=mcp_context(), context_key=key, archive_id=event['archive_id'])
                    assert not image.isError and image.content[0].type == 'image'
                    assert image.content[0].mimeType == 'image/png'
                    assert json.loads(image.content[1].text)['archive_id'] == event['archive_id']
            assert seen == ['text', 'image', 'image', 'text']
            accepted = await confirm_bound_context_batch(mcp_context(), context_key=key, batch_id=data['batch_id'], summary={'evidence_message_ids': ids})
            assert not accepted.isError
        asyncio.run(run())
    finally:
        bridge.bind(reader, reader.gateway)


def test_mcp_http_transport_returns_interleaved_events(context):
    from starlette.testclient import TestClient
    from backend.app.customer_context_mcp import bridge, CustomerContextFastMCP, get_bound_conversation_context
    from backend.tests.test_customer_context_tunnel import tunnel_config, mcp_headers
    db, reader, cid, ids, key = context
    bridge.bind(reader, reader.gateway, tunnel_config=tunnel_config())
    # FastMCP's lifespan is single-use. Do not consume the shared app needed by
    # existing transport tests; register the real handler on an isolated server.
    server = CustomerContextFastMCP(name='timeline-transport-test', stateless_http=True,
        json_response=True, streamable_http_path='/')
    server.add_tool(get_bound_conversation_context, name='xunying_get_bound_conversation_context')
    try:
        with TestClient(server.streamable_http_app(), base_url='http://127.0.0.1:8877') as client:
            response = client.post('/', headers=mcp_headers(), json={'jsonrpc': '2.0', 'id': 1,
                'method': 'tools/call', 'params': {'name': 'xunying_get_bound_conversation_context', 'arguments': {'context_key': key}}})
            assert response.status_code == 200
            result = response.json()['result']
            assert not result['isError']
            assert [e['type'] for e in result['structuredContent']['events']] == ['text', 'image', 'image', 'text']
            assert json.loads(result['content'][0]['text']) == result['structuredContent']
    finally:
        bridge.bind(reader, reader.gateway)
