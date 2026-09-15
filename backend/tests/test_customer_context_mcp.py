from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from backend.app.customer_context_mcp import (
    CustomerContextFastMCP,
    bridge,
    customer_context_mcp_app,
)
from backend.app.models import CustomerContextAccessAudit
from backend.tests.test_customer_context_oauth import oauth_config
from backend.tests.test_customer_context_reader import seed


@pytest.mark.parametrize("metadata_version", [None, "", 7, PermissionError(), "9.9.9"])
def test_mcp_initialization_does_not_depend_on_package_metadata(
    monkeypatch: pytest.MonkeyPatch, metadata_version: object
) -> None:
    def unavailable_version(_package: str):
        if isinstance(metadata_version, Exception):
            raise metadata_version
        return metadata_version

    monkeypatch.setattr("importlib.metadata.version", unavailable_version)
    server = CustomerContextFastMCP(
        name="initialization-regression", stateless_http=True, json_response=True,
        streamable_http_path="/",
    )
    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:8877") as client:
        response = client.post(
            "/",
            headers={"accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "regression-test", "version": "1"},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["version"] == "0.2.0"


def rpc(client: TestClient, token: str, payload: dict) -> dict:
    response = client.post(
        "/",
        headers={
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
        },
        json=payload,
    )
    assert response.status_code == 200
    return response.json()


def test_mcp_exposes_only_five_read_tools_and_audits_content_access(
    tmp_path: Path,
) -> None:
    database, reader, grant, _conversation_id = seed(tmp_path)
    bridge.bind(reader, reader.gateway, oauth_config(), None)
    token = grant["capability_token"]
    try:
        with TestClient(
            customer_context_mcp_app,
            base_url="http://127.0.0.1:8877",
        ) as client:
            discovery = client.get("/")
            assert discovery.status_code == 401
            assert "resource_metadata=" in discovery.headers["www-authenticate"]

            initialized = client.post(
                "/",
                headers={
                    "accept": "application/json, text/event-stream",
                    "content-type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
            assert initialized.status_code == 200
            assert initialized.json()["result"]["serverInfo"]["name"] == (
                "循营客户上下文"
            )

            listed = client.post(
                "/",
                headers={
                    "accept": "application/json, text/event-stream",
                    "content-type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            )
            assert listed.status_code == 200
            tools = listed.json()["result"]["tools"]
            ack = next(tool for tool in tools if tool['name'] == 'xunying_confirm_bound_context_batch')
            assert ack['annotations']['readOnlyHint'] is False
            assert set(ack['inputSchema']['properties']) == {'context_key', 'batch_id', 'summary'}
            proposal = next(tool for tool in tools if tool['name'] == 'xunying_preview_requirement_blueprint')
            assert proposal['annotations']['readOnlyHint'] is False
            assert 'confirmed' not in proposal['inputSchema']['properties']
            props = proposal['inputSchema']['properties']
            document_schema = next(s for s in props['document']['anyOf'] if s.get('type') == 'object')
            assert 'objectives' in document_schema['required']
            stage_schema = document_schema['properties']['stages']['items']
            assert 'implementation' in stage_schema['required']
            assert 'task_key' in stage_schema['properties']
            mapping_schema = next(s for s in props['conversion']['anyOf'] if s.get('type') == 'object')
            assert {'stage_mapping', 'implementations', 'evidence_refs'} <= set(mapping_schema['required'])
            assert '$ref' not in json.dumps(document_schema)
            commit = next(tool for tool in tools if tool['name'] == 'xunying_confirm_requirement_blueprint')
            assert commit['annotations']['readOnlyHint'] is False
            assert commit['annotations']['destructiveHint'] is True
            assert commit['inputSchema']['properties']['confirmed']['default'] is False
            assert not {'customer_id','conversation_id','document'} & set(commit['inputSchema']['properties'])
            tools = [tool for tool in tools if tool is not ack and tool is not proposal and tool is not commit]
            assert [tool["name"] for tool in tools] == [
                "xunying_get_bound_conversation_context",
                "xunying_list_bound_archived_images",
                "xunying_read_bound_archived_image",
                "xunying_get_customer_analysis_status",
                "xunying_get_confirmed_customer_artifact",
            ]
            assert set(tools[0]["inputSchema"]["properties"]) == {"context_key"}
            assert set(tools[1]["inputSchema"]["properties"]) == {
                "cursor",
                "context_key",
            }
            assert set(tools[2]["inputSchema"]["properties"]) == {
                "archive_id",
                "context_key",
                "representation",
            }
            assert set(tools[3]["inputSchema"]["properties"]) == {"context_key"}
            assert set(tools[4]["inputSchema"]["properties"]) == {
                "kind",
                "version",
                "context_key",
            }
            assert all(
                "context_key" in tool["inputSchema"].get("required", [])
                for tool in tools
            )
            assert all(
                tool["securitySchemes"]
                == [{"type": "oauth2", "scopes": ["customer-context.read"]}]
                for tool in tools
            )

            called = rpc(
                client,
                token,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "xunying_get_bound_conversation_context",
                        "arguments": {},
                    },
                },
            )
            assert called["result"]["isError"] is False
            payload = json.loads(called["result"]["content"][0]["text"])
            assert payload["conversation_id"] == 1
            assert len(payload["messages"]) == 200

            missing = client.post(
                "/",
                headers={
                    "accept": "application/json, text/event-stream",
                    "content-type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "xunying_get_bound_conversation_context",
                        "arguments": {},
                    },
                },
            )
            assert missing.status_code == 200
            missing_result = missing.json()["result"]
            assert missing_result["isError"] is True
            assert "客户文字" not in missing.text
            assert "resource_metadata=" in missing_result["_meta"][
                "mcp/www_authenticate"
            ][0]
    finally:
        bridge.bind(reader, reader.gateway)

    with database.session() as session:
        audit = session.scalar(
            select(CustomerContextAccessAudit).where(
                CustomerContextAccessAudit.tool_name == "customer_context_text"
            )
        )
        assert audit is not None
        assert audit.status == "completed"
        assert audit.target_model == "external-openai-mcp"
        assert audit.request_id.startswith("mcp:text:")
