from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.customer_context_api import customer_context_router
from backend.app.services.customer_context_gateway import CustomerContextGatewayError
from backend.tests.test_customer_context_gateway import build_gateway
from backend.tests.test_customer_context_tunnel import tunnel_config


@pytest.mark.parametrize('seconds', [900, 3600, 14400, 86400, 259200, 432000, 604800])
def test_authorization_duration_and_exact_expiry(tmp_path: Path, monkeypatch, seconds):
    _, gateway, conversation_id, _ = build_gateway(tmp_path)
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    monkeypatch.setattr('backend.app.services.customer_context_gateway.utcnow', lambda: now)
    app = FastAPI()
    app.state.runtime = type('Runtime', (), {'customer_context_gateway': gateway})()
    app.state.customer_context_tunnel_config = tunnel_config()
    app.include_router(customer_context_router)
    with TestClient(app, base_url='http://127.0.0.1:8877') as client:
        payload = {
            'request_id': 'expiry-create-0001',
            'conversation_id': conversation_id,
            'expected_conversation_revision': 0,
            'allow_text': True,
            'allow_images': False,
            'expires_in_seconds': seconds,
            'authorization_note': '测试所选消息读取有效期',
            'confirmed': True,
        }
        response = client.post('/api/customer-context/thread-bindings', json=payload)
        assert response.status_code == 200
        created = response.json()
        expiry = now + timedelta(seconds=seconds)
        assert datetime.fromisoformat(created['expires_at']) == expiry
        assert datetime.fromisoformat(created['grant']['expires_at']) == expiry
        key = created['context_key']
        repeated = client.post('/api/customer-context/thread-bindings', json=payload).json()
        assert repeated['idempotent'] is True
        assert repeated['context_key'] is None
        assert repeated['expires_at'] == created['expires_at']
        now = expiry - timedelta(seconds=1)
        gateway.resolve_active_thread_binding(key, auth_mode='tunnel_binding')
        now = expiry
        with pytest.raises(CustomerContextGatewayError) as denied:
            gateway.resolve_active_thread_binding(key, auth_mode='tunnel_binding')
        assert denied.value.code == 'context_key_expired'
        assert gateway.list_thread_bindings()[0]['active'] is False


@pytest.mark.parametrize('seconds', [59, 604801])
def test_duration_outside_bounds_rejected_by_api_and_gateway(tmp_path: Path, seconds):
    _, gateway, conversation_id, _ = build_gateway(tmp_path)
    app = FastAPI()
    app.state.runtime = type('Runtime', (), {'customer_context_gateway': gateway})()
    app.state.customer_context_tunnel_config = tunnel_config()
    app.include_router(customer_context_router)
    payload = {
        'request_id': 'expiry-invalid-0001',
        'conversation_id': conversation_id,
        'expected_conversation_revision': 0,
        'allow_text': True,
        'allow_images': False,
        'allow_artifacts': False,
        'allow_new_messages': True,
        'expires_in_seconds': seconds,
        'authorization_note': '测试无效授权期限',
    }
    with TestClient(app, base_url='http://127.0.0.1:8877') as client:
        response = client.post('/api/customer-context/thread-bindings', json={**payload, 'confirmed': True})
        assert response.status_code == 422
    with pytest.raises(CustomerContextGatewayError) as denied:
        gateway.create_thread_binding(**payload, auth_mode='tunnel_binding')
    assert denied.value.code == 'invalid_expiry'
    assert gateway.list_thread_bindings() == []
