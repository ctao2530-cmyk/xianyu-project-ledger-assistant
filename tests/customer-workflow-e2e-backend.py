"""Independent synthetic counterexamples for the customer image workflow."""
import base64
import hashlib
from io import BytesIO

from PIL import Image
import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from backend.app.customer_context_mcp import bridge, CustomerContextFastMCP, read_bound_archived_image
from backend.app.models import CustomerImageArchive
from backend.app.services.customer_context_gateway import CustomerContextGateway
from backend.app.services.customer_context_gateway import CustomerContextGatewayError
from backend.app.services.customer_context_reader import CustomerContextReadService, CustomerContextReadError
from backend.app.services.customer_images import CustomerImageError
from backend.tests.test_customer_images import build_service, original_jpeg
from backend.tests.test_customer_context_oauth import oauth_config


def test_independent_iso_header_is_not_valid_image(tmp_path):
    _, service, _, message_id = build_service(tmp_path)
    with pytest.raises(CustomerImageError):
        service.store_original(message_id, 0, data=b'\0\0\0\x18ftypheic'+b'x'*100,
            content_type='image/heic', original_name='fake.heic', capture_source='test')


def test_independent_deletion_is_a_replay_tombstone(tmp_path):
    database, service, _, message_id = build_service(tmp_path)
    payload=original_jpeg()
    image=service.store_original(message_id,0,data=payload,content_type='image/jpeg',original_name='synthetic.jpg',capture_source='test')
    service.delete_local_copy(image['id'])
    try:
        service.store_original(message_id,0,data=payload,content_type='image/jpeg',original_name='synthetic.jpg',capture_source='test')
    except CustomerImageError:
        pass
    with database.session() as session:
        row=session.get(CustomerImageArchive,image['id'])
        assert row.deleted_at is not None
        assert row.capture_status=='deleted'
    with pytest.raises(CustomerImageError):
        service.content_file(image['id'])


@pytest.mark.parametrize('image_format,mime', [('PNG','image/png'),('BMP','image/bmp'),('TIFF','image/tiff'),('GIF','image/gif')])
def test_independent_original_to_web_preview_to_mcp_image(tmp_path,image_format,mime):
    database, service, conversation_id, message_id=build_service(tmp_path)
    output=BytesIO()
    Image.new('RGB',(64,48),(20,130,220)).save(output,format=image_format)
    original=output.getvalue()
    archived=service.store_original(message_id,0,data=original,content_type=mime,original_name='synthetic',capture_source='test')
    path,_,_=service.content_file(archived['id'])
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    preview,preview_mime,_=service.preview_file(archived['id'])
    assert preview!=path and preview_mime in {'image/png','image/jpeg','image/webp'}
    with Image.open(preview) as decoded:
        decoded.load()
        assert decoded.size==(64,48)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    gateway=CustomerContextGateway(database)
    grant=gateway.create_conversation_grant(conversation_id=conversation_id,request_id='qa-grant-image-flow',expected_revision=0,allow_text=True,allow_images=True,expires_in_seconds=900,authorization_note='Synthetic explicit image authorization',audience='openai_chatgpt')
    reader=CustomerContextReadService(database,gateway,tmp_path)
    bridge.bind(reader,gateway,oauth_config(),None)
    try:
        server=CustomerContextFastMCP(name='Independent synthetic MCP',stateless_http=True,json_response=True,streamable_http_path='/')
        server.add_tool(read_bound_archived_image,name='xunying_read_bound_archived_image')
        with TestClient(server.streamable_http_app(),base_url='http://127.0.0.1:8877') as client:
            response=client.post('/',headers={'accept':'application/json, text/event-stream','authorization':'Bearer '+grant['capability_token']},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'xunying_read_bound_archived_image','arguments':{'archive_id':archived['id']}}})
            assert response.status_code==200
            result=response.json()['result']
            assert not result.get('isError'), result
            content=[entry for entry in result['content'] if entry['type']=='image']
            assert len(content)==1
            # BMP/TIFF are not native vision inputs; MCP must return a decoder-
            # compatible actual image block, not only text, path or URL.
            assert content[0]['mimeType'] in {'image/png','image/jpeg','image/webp','image/gif'}
            with Image.open(BytesIO(base64.b64decode(content[0]['data']))) as decoded:
                decoded.load()
                assert decoded.size==(64,48)
            assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    finally:
        bridge.reader=None
        bridge.gateway=None
        bridge.oauth_config=None
        bridge.oauth_verifier=None
        bridge.tunnel_config=None


def test_independent_late_image_appears_after_text_read_and_invalidates_cursor(tmp_path):
    from backend.app.customer_context_mcp import _image_cursor, _image_cursor_offset
    database,service,conversation_id,message_id=build_service(tmp_path)
    gateway=CustomerContextGateway(database)
    grant=gateway.create_conversation_grant(conversation_id=conversation_id,request_id='qa-late-image-grant',expected_revision=0,allow_text=True,allow_images=True,expires_in_seconds=900,authorization_note='Synthetic explicit authorization',audience='openai_chatgpt')
    reader=CustomerContextReadService(database,gateway,tmp_path)
    access=dict(capability_token=grant['capability_token'],audience='openai_chatgpt',target_model='synthetic')
    reader.read_text(request_id='qa-read-before-image',**access)
    before=reader.image_manifest(request_id='qa-manifest-before',**access)
    cursor=_image_cursor(0,before)
    archived=service.store_original(message_id,0,data=original_jpeg(),content_type='image/jpeg',original_name='synthetic.jpg',capture_source='history')
    after=reader.image_manifest(request_id='qa-manifest-after',**access)
    assert archived['id'] in {row['archive_id'] for row in after['images']}
    assert before['image_revision']!=after['image_revision']
    with pytest.raises(ValueError):
        _image_cursor_offset(cursor,after)
    other_scope={**after,'scope_revision':'different-authorized-customer'}
    with pytest.raises(ValueError):
        _image_cursor_offset(_image_cursor(0,after),other_scope)


def test_independent_revoke_expire_and_text_only_deny_actual_image(tmp_path):
    from datetime import timedelta
    from backend.app.models import CustomerContextGrant, utcnow
    database,service,conversation_id,message_id=build_service(tmp_path)
    image=service.store_original(message_id,0,data=original_jpeg(),content_type='image/jpeg',original_name='synthetic.jpg',capture_source='test')
    gateway=CustomerContextGateway(database)
    grant=gateway.create_conversation_grant(conversation_id=conversation_id,request_id='qa-deny-image-grant',expected_revision=0,allow_text=True,allow_images=False,expires_in_seconds=900,authorization_note='Synthetic text only',audience='openai_chatgpt')
    reader=CustomerContextReadService(database,gateway,tmp_path)
    access=dict(capability_token=grant['capability_token'],audience='openai_chatgpt',target_model='synthetic')
    with pytest.raises(CustomerContextGatewayError) as denied:
        reader.read_image(image['id'],request_id='qa-read-text-only',**access)
    assert denied.value.code=='images_not_authorized'
    with database.session() as session:
        row=session.get(CustomerContextGrant,grant['id']);row.allow_images=True;row.expires_at=utcnow()-timedelta(seconds=5);session.commit()
    with pytest.raises(CustomerContextGatewayError) as expired:
        reader.read_image(image['id'],request_id='qa-read-expired',**access)
    assert expired.value.code=='grant_expired'
    with database.session() as session:
        row=session.get(CustomerContextGrant,grant['id']);row.expires_at=utcnow()+timedelta(seconds=900);row.status='revoked';row.revoked_at=utcnow();session.commit()
    with pytest.raises(CustomerContextGatewayError) as revoked:
        reader.read_image(image['id'],request_id='qa-read-revoked',**access)
    assert revoked.value.code=='grant_revoked'


def test_independent_mcp_encoded_transport_limit_rejects_actual_tool_image(tmp_path,monkeypatch):
    import backend.app.customer_context_mcp as module
    database,service,conversation_id,message_id=build_service(tmp_path)
    original=original_jpeg()
    archived=service.store_original(message_id,0,data=original,content_type='image/jpeg',original_name='synthetic.jpg',capture_source='test')
    assert len(original)<25*1024*1024
    # Bytes fit the limit; base64 framing does not. Check the actual MCP response.
    monkeypatch.setattr(module,'MAX_MCP_IMAGE_ENCODED_BYTES',len(original)+1)
    gateway=CustomerContextGateway(database)
    grant=gateway.create_conversation_grant(conversation_id=conversation_id,request_id='qa-transport-grant',expected_revision=0,allow_text=True,allow_images=True,expires_in_seconds=900,authorization_note='Synthetic transport boundary',audience='openai_chatgpt')
    bridge.bind(CustomerContextReadService(database,gateway,tmp_path),gateway,oauth_config(),None)
    try:
        server=CustomerContextFastMCP(name='Independent transport check',stateless_http=True,json_response=True,streamable_http_path='/')
        server.add_tool(read_bound_archived_image,name='xunying_read_bound_archived_image')
        with TestClient(server.streamable_http_app(),base_url='http://127.0.0.1:8877') as client:
            response=client.post('/',headers={'accept':'application/json, text/event-stream','authorization':'Bearer '+grant['capability_token']},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'xunying_read_bound_archived_image','arguments':{'archive_id':archived['id'],'representation':'original'}}})
            result=response.json()['result']
            assert result.get('isError') is True,result
            assert not any(entry['type']=='image' for entry in result['content'])
            assert 'image_transport_limit' in str(result),result
    finally:
        bridge.reader=None;bridge.gateway=None;bridge.oauth_config=None;bridge.oauth_verifier=None;bridge.tunnel_config=None


@pytest.mark.parametrize('path',['/api/customer-images','/api/customers/synthetic/conversation-group-candidates','/api/customer-context/oauth/status'])
@pytest.mark.parametrize('peer,base_url,headers',[
    (('203.0.113.5',43120),'http://127.0.0.1:8877',{}),
    (('127.0.0.1',43120),'https://synthetic-proxy.invalid',{}),
    (('127.0.0.1',43120),'http://127.0.0.1:8877',{'forwarded':'for=203.0.113.5'}),
    (('127.0.0.1',43120),'http://127.0.0.1:8877',{'x-forwarded-for':'203.0.113.5'}),
])
def test_independent_local_workflow_cannot_bypass_mcp_authorization(path,peer,base_url,headers):
    from fastapi import FastAPI
    from backend.app.customer_image_api import customer_image_router
    from backend.app.customer_conversation_api import customer_conversation_router
    from backend.app.customer_context_api import customer_context_router
    app=FastAPI()
    for router in (customer_image_router,customer_conversation_router,customer_context_router):
        app.include_router(router)
    # No runtime/database exists: denial must occur before any data access.
    with TestClient(app,base_url=base_url,client=peer) as client:
        response=client.get(path,headers=headers)
        assert response.status_code==403,response.text
        assert response.json()['detail']['code']=='local_customer_workflow_only'
