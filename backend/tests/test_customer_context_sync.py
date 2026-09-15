"""Synthetic data only; no provider or production connection."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import json

import pytest
from sqlalchemy import select

from backend.app.models import Message, CustomerContextGrant, CustomerContextThreadBinding, utcnow
from backend.app.models import GlobalAgentConversationSummary, CustomerImageArchive
from backend.app.customer_sync_models import CustomerContextSyncState
from backend.app.services.customer_context_gateway import CustomerContextGatewayError
from backend.tests.test_customer_context_reader import seed
from backend.tests.test_customer_context_thread_bindings import create_binding, add_second_conversation


def credentials(reader, key):
    grant = reader.gateway.resolve_active_thread_binding(key, auth_mode='tunnel_binding')
    return dict(request_id='sync-' + uuid4().hex, grant_id=grant['id'], audience='openai_chatgpt', target_model='gpt-test')


def bind(reader, cid):
    return create_binding(reader.gateway, cid, 'bind-' + uuid4().hex, 'tunnel_binding')['context_key']


def read(reader, key):
    return reader.read_text(**credentials(reader, key))


def confirm(reader, key, batch, summary=None):
    return reader.confirm_batch(batch_id=batch['batch_id'], summary=summary, **credentials(reader, key))


def append(database, cid, count):
    with database.session() as session:
        for _ in range(count):
            session.add(Message(conversation_id=cid, channel='xianyu', external_id=uuid4().hex,
                platform_message_id=uuid4().hex, sender_id='reader-customer', sender_name='fixture',
                direction='inbound', message_type='text', content='synthetic delta', status='new'))
        session.commit()


def test_initial_incremental_rekey_summary_and_empty(tmp_path):
    db, reader, _, cid = seed(tmp_path)
    key = bind(reader, cid)
    first = read(reader, key)
    assert first['context_mode'] == 'full_initial'
    assert len(first['messages']) == 200
    assert read(reader, key)['batch_id'] == first['batch_id']
    confirmed = confirm(reader, key, first, {'requirements': ['synthetic']})
    assert confirmed['acknowledged_through_message_id'] == 505
    append(db, cid, 5)
    second = read(reader, key)
    assert [r['message_id'] for r in second['messages']] == list(range(506, 511))
    confirm(reader, key, second, {'requirements': ['updated']})
    new = bind(reader, cid)
    with pytest.raises(CustomerContextGatewayError):
        read(reader, key)
    empty = read(reader, new)
    assert empty['context_mode'] == 'incremental_resume'
    assert empty['messages'] == []
    assert empty['previous_summary'] == {'requirements': ['updated']}
    append(db, cid, 10)
    assert [r['message_id'] for r in read(reader, new)['messages']] == list(range(511, 521))


def test_expiry_pending_rekey_and_isolation(tmp_path):
    db, reader, _, cid = seed(tmp_path)
    key = bind(reader, cid)
    first = read(reader, key)
    with db.session() as session:
        binding = session.scalar(select(CustomerContextThreadBinding))
        binding.expires_at = utcnow() - timedelta(seconds=1)
        session.get(CustomerContextGrant, binding.grant_id).expires_at = binding.expires_at
        session.commit()
    with pytest.raises(CustomerContextGatewayError):
        read(reader, key)
    new = bind(reader, cid)
    replay = read(reader, new)
    assert replay['batch_id'] == first['batch_id']
    assert replay['context_mode'] == 'incremental_resume'
    other = bind(reader, add_second_conversation(db))
    with pytest.raises(CustomerContextGatewayError, match='批次'):
        confirm(reader, other, first)
    assert read(reader, other)['previous_summary'] is None


def test_concurrent_reads_and_idempotent_confirmation(tmp_path):
    db, reader, _, cid = seed(tmp_path)
    key = bind(reader, cid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(lambda _: read(reader, key), range(2)))
    assert batches[0]['batch_id'] == batches[1]['batch_id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(reader, key, batches[0], {'facts': []}), range(2)))
    assert results[0] == results[1]
    with db.session() as session:
        state = session.scalar(select(CustomerContextSyncState))
        assert state.text_version == 1 and state.text_watermark == 505
    with pytest.raises(CustomerContextGatewayError):
        confirm(reader, key, batches[0], {'different': True})


def test_forward_pagination_does_not_skip_intermediate_messages(tmp_path):
    db, reader, _, cid = seed(tmp_path)
    key = bind(reader, cid)
    confirm(reader, key, read(reader, key), {'facts': []})
    append(db, cid, 405)
    seen = []
    for _ in range(3):
        batch = read(reader, key)
        seen.extend(r['message_id'] for r in batch['messages'])
        confirm(reader, key, batch, {'facts': []})
    assert seen == list(range(506, 911))


def test_existing_summary_is_bootstrapped_without_overwriting_it(tmp_path):
    db, reader, _, cid = seed(tmp_path)
    with db.session() as session:
        session.add(GlobalAgentConversationSummary(id='old-summary', conversation_id=cid, version=8,
            summarized_through_message_id=500, message_count=500, source_hash='a' * 64,
            summary_json=json.dumps({'facts': ['prior']}), provider='fixture', model='fixture'))
        session.commit()
    key = bind(reader, cid)
    result = read(reader, key)
    assert result['summary_version'] == 8
    assert result['summarized_through_message_id'] == 500
    assert len(result['messages']) == 5
    confirm(reader, key, result, {'facts': ['external']})
    new = bind(reader, cid)
    assert read(reader, new)['previous_summary'] == {'facts': ['external']}
    with db.session() as session:
        assert json.loads(session.get(GlobalAgentConversationSummary, 'old-summary').summary_json) == {'facts': ['prior']}


def test_unsummarized_tail_and_evidence_guard(tmp_path):
    db, reader, _, cid = seed(tmp_path)
    key = bind(reader, cid)
    first = read(reader, key)
    confirm(reader, key, first)
    new = bind(reader, cid)
    resumed = read(reader, new)
    assert resumed['messages'] == [] and len(resumed['unsummarized_context']) == 200
    append(db, cid, 1)
    batch = read(reader, new)
    with pytest.raises(CustomerContextGatewayError, match='摘要'):
        confirm(reader, new, batch)
    with pytest.raises(CustomerContextGatewayError, match='证据'):
        confirm(reader, new, batch, {'evidence_message_ids': [999999]})
    confirm(reader, new, batch, {'evidence_message_ids': [506]})
    assert read(reader, new)['unsummarized_context'] == []


def image_binding(reader, cid, *, allow_images=True):
    state = reader.gateway.conversation_access_state(cid)
    return reader.gateway.create_thread_binding(conversation_id=cid,
        request_id='image-bind-' + uuid4().hex, expected_conversation_revision=state['revision'],
        auth_mode='tunnel_binding', allow_text=True, allow_images=allow_images, allow_artifacts=False,
        allow_new_messages=True, expires_in_seconds=3600, authorization_note='synthetic image authorization')['context_key']


def archive(db, cid, name, status='failed'):
    with db.session() as session:
        session.add(CustomerImageArchive(id=name, conversation_id=cid, message_id=1, channel='xianyu',
            platform_message_id='synthetic-image-' + name, media_index=int(uuid4().hex[:7], 16), capture_status=status,
            capture_source='live', mime_type='image/png', original_name='synthetic.png', storage_path='',
            sha256='b' * 64 if status == 'stored' else '', file_size=10, width=2, height=2,
            received_at=utcnow(), error_code='download_timeout' if status == 'failed' else ''))
        session.commit()


def test_image_delta_rekey_delayed_archive_and_deletion(tmp_path):
    db, reader, _, cid = seed(tmp_path)
    key = image_binding(reader, cid)
    archive(db, cid, 'image-one')
    first = reader.image_manifest(**credentials(reader, key))
    confirm(reader, key, first)
    new = image_binding(reader, cid)
    assert reader.image_manifest(**credentials(reader, new))['images'] == []
    archive(db, cid, 'image-two')
    delta = reader.image_manifest(**credentials(reader, new))
    assert [r['archive_id'] for r in delta['images']] == ['image-two']
    confirm(reader, new, delta)
    with db.session() as session:
        row = session.get(CustomerImageArchive, 'image-one')
        row.capture_status, row.error_code, row.sha256 = 'stored', '', 'b' * 64
        session.commit()
    delayed = reader.image_manifest(**credentials(reader, new))
    assert [r['archive_id'] for r in delayed['images']] == ['image-one']
    with pytest.raises(CustomerContextGatewayError, match='读取'):
        confirm(reader, new, delayed)
    with db.session() as session:
        session.get(CustomerImageArchive, 'image-one').deleted_at = utcnow()
        session.commit()
    deleted = reader.image_manifest(**credentials(reader, new))
    assert deleted['batch_id'] != delayed['batch_id']
    assert deleted['images'][0]['capture_status'] == 'deleted'
    confirm(reader, new, deleted)


def test_reduced_permissions_do_not_inherit_image_scope_summary(tmp_path):
    db, reader, _, cid = seed(tmp_path)
    broad = image_binding(reader, cid)
    confirm(reader, broad, read(reader, broad), {'facts': ['image-derived']})
    narrow = image_binding(reader, cid, allow_images=False)
    result = read(reader, narrow)
    assert result['context_mode'] == 'full_initial' and result['previous_summary'] is None


def test_mcp_image_content_then_ack_then_rekey_no_replay(tmp_path, monkeypatch):
    import asyncio
    import hashlib
    from io import BytesIO
    from PIL import Image
    from backend.app.customer_context_mcp import bridge, list_bound_archived_images, read_bound_archived_image, confirm_bound_context_batch
    from backend.tests.test_customer_context_oauth import oauth_config
    from backend.tests.test_customer_context_tunnel import tunnel_config, mcp_context
    db, reader, _, cid = seed(tmp_path)
    key = image_binding(reader, cid)
    output = BytesIO()
    Image.new('RGB', (4, 4), 'blue').save(output, format='PNG')
    content = output.getvalue()
    sha = hashlib.sha256(content).hexdigest()
    relative = f'data/customer-images/2026/09/{sha}.png'
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    archive(db, cid, 'real-synthetic', 'stored')
    with db.session() as session:
        row = session.get(CustomerImageArchive, 'real-synthetic')
        row.storage_path, row.sha256, row.file_size = relative, sha, len(content)
        row.width, row.height, row.integrity_verified = 4, 4, True
        session.commit()
    bridge.bind(reader, reader.gateway, oauth_config(), None, tunnel_config())
    try:
        async def exercise():
            result = await list_bound_archived_images(mcp_context(), context_key=key)
            assert not result.isError
            batch_id = result.structuredContent['batch_id']
            import backend.app.customer_context_mcp as module
            limit = module.MAX_MCP_IMAGE_ENCODED_BYTES
            monkeypatch.setattr(module, 'MAX_MCP_IMAGE_ENCODED_BYTES', 0)
            oversized = await read_bound_archived_image(context=mcp_context(), archive_id='real-synthetic', context_key=key, representation='original')
            assert oversized.isError
            rejected = await confirm_bound_context_batch(mcp_context(), batch_id=batch_id, context_key=key)
            assert rejected.isError
            monkeypatch.setattr(module, 'MAX_MCP_IMAGE_ENCODED_BYTES', limit)
            image = await read_bound_archived_image(context=mcp_context(), archive_id='real-synthetic', context_key=key, representation='original')
            assert not image.isError
            assert image.content[0].type == 'image'
            ack = await confirm_bound_context_batch(mcp_context(), batch_id=batch_id, context_key=key)
            assert not ack.isError
            new_key = image_binding(reader, cid)
            again = await list_bound_archived_images(mcp_context(), context_key=new_key)
            assert again.structuredContent['images'] == []
        asyncio.run(exercise())
    finally:
        bridge.bind(reader, reader.gateway)


def test_restart_preserves_pending_and_acknowledged_state(tmp_path):
    from backend.app.services.customer_context_reader import CustomerContextReadService
    db, reader, _, cid = seed(tmp_path)
    key = bind(reader, cid)
    batch = read(reader, key)
    restarted = CustomerContextReadService(db, reader.gateway, tmp_path)
    assert read(restarted, key)['batch_id'] == batch['batch_id']
    confirm(restarted, key, batch, {'facts': []})
    restarted_again = CustomerContextReadService(db, reader.gateway, tmp_path)
    assert read(restarted_again, bind(reader, cid))['messages'] == []


def test_image_pending_rekey_pagination_scope(tmp_path):
    import asyncio
    import backend.app.customer_context_mcp as module
    from backend.tests.test_customer_context_oauth import oauth_config
    from backend.tests.test_customer_context_tunnel import tunnel_config, mcp_context
    db, reader, _, cid = seed(tmp_path)
    key = image_binding(reader, cid)
    for index in range(51):
        archive(db, cid, f'failed-{index}')
    module.bridge.bind(reader, reader.gateway, oauth_config(), None, tunnel_config())
    try:
        async def exercise():
            first = await module.list_bound_archived_images(mcp_context(), context_key=key)
            assert len(first.structuredContent['images']) == 50
            cursor = first.structuredContent['next_cursor']
            second = await module.list_bound_archived_images(mcp_context(), context_key=key, cursor=cursor)
            assert len(second.structuredContent['images']) == 1
            new = image_binding(reader, cid)
            stale = await module.list_bound_archived_images(mcp_context(), context_key=new, cursor=cursor)
            assert stale.isError
            resumed = await module.list_bound_archived_images(mcp_context(), context_key=new)
            assert resumed.structuredContent['batch_id'] == first.structuredContent['batch_id']
        asyncio.run(exercise())
    finally:
        module.bridge.bind(reader, reader.gateway)


def test_oauth_principal_scope_does_not_cross_reauthorization(tmp_path):
    from backend.tests.test_customer_context_oauth import identity
    db, reader, _, cid = seed(tmp_path)
    key = create_binding(reader.gateway, cid, 'oauth-first-scope', 'oauth')['context_key']
    principal = identity()
    def oauth_credentials(key, principal):
        grant = reader.gateway.resolve_active_thread_binding(key, auth_mode='oauth', identity=principal)
        return dict(request_id='oauth-' + uuid4().hex, grant_id=grant['id'], audience='openai_chatgpt', target_model='fixture')
    result = reader.read_text(**oauth_credentials(key, principal))
    reader.confirm_batch(batch_id=result['batch_id'], summary={'facts': []}, **oauth_credentials(key, principal))
    new = create_binding(reader.gateway, cid, 'oauth-second-scope', 'oauth')['context_key']
    assert reader.read_text(**oauth_credentials(new, principal))['messages'] == []
    from dataclasses import replace
    other = replace(principal, subject='another-synthetic-owner')
    third = create_binding(reader.gateway, cid, 'oauth-third-scope', 'oauth')['context_key']
    assert reader.read_text(**oauth_credentials(third, other))['context_mode'] == 'full_initial'
