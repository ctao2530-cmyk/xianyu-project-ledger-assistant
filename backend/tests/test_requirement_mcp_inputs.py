import asyncio
import json

import pytest
from sqlalchemy import func, select

from backend.app.customer_context_mcp import bridge, preview_requirement_blueprint
from backend.app.models import RequirementCase, LedgerMutationRequest
from backend.tests.test_requirement_proposals import setup
from backend.tests.test_project_task_drafts import blueprint
from backend.tests.test_customer_context_sync import bind
from backend.tests.test_customer_context_oauth import oauth_config
from backend.tests.test_customer_context_tunnel import tunnel_config, mcp_context


@pytest.mark.parametrize('kind', ['missing', 'extra', 'graph', 'mixed', 'conversion'])
def test_safe_actionable_errors_without_proposal_write(tmp_path, kind):
    db, reader, auth, _ = setup(tmp_path)
    key = bind(reader, auth['conversation_id'])
    bridge.bind(reader, reader.gateway, oauth_config(), None, tunnel_config=tunnel_config())
    document = blueprint()
    args = {'document': document}
    if kind == 'missing':
        del document['stages'][0]['implementation']
    elif kind == 'extra':
        document['private-secret-field'] = 'private-secret-value'
    elif kind == 'graph':
        document['stages'][0]['dependency_ids'] = ['private-secret-value']
    elif kind == 'mixed':
        args['conversion'] = {}
    else:
        args = {'conversion': {}}
    try:
        result = asyncio.run(preview_requirement_blueprint(context=mcp_context(),
            request_id='schema-fixture-001', context_key=key, **args))
        assert result.isError
        text = result.content[0].text
        payload = result.structuredContent['error']
        assert payload['code'] == 'blueprint_invalid'
        assert 'private-secret' not in text
        assert key not in text
        if kind == 'missing':
            assert payload['errors'][0]['path'] == ['document', 'stages', 0, 'implementation']
            assert payload['errors'][0]['type'] == 'missing'
        with db.session() as session:
            assert session.scalar(select(func.count()).select_from(RequirementCase)) == 0
            assert session.get(LedgerMutationRequest, 'schema-fixture-001') is None
        rejected = asyncio.run(preview_requirement_blueprint(context=mcp_context(),
            request_id='schema-fixture-002', context_key='invalid-acceptance-probe', **args))
        assert rejected.structuredContent['error']['code'] == 'context_key_invalid'
    finally:
        bridge.bind(reader, reader.gateway)


def test_conversion_input_round_trip_and_missing_mapping(tmp_path):
    from backend.tests.test_customer_auto_analysis import result_payload
    db, reader, auth, _ = setup(tmp_path)
    key = bind(reader, auth['conversation_id'])
    bridge.bind(reader, reader.gateway, oauth_config(), None, tunnel_config=tunnel_config())
    data = result_payload(1)
    source, plan = data['requirement_blueprint'], data['execution_plan']
    source['stages'][0]['estimated_hours'] = 8
    refs = source['objectives'][0]['evidence_refs']
    mapping = dict(project_type='定制开发', stage_mapping={'stage_main': 'plan_stage_main'},
        implementations={'stage_main': '按明确文件范围实现'},
        evidence_refs=[{'id': 'ev-one', 'message_id': 1, 'quote': 'synthetic'}],
        evidence_mapping={ref: 'ev-one' for ref in refs})
    try:
        args = dict(context=mcp_context(), context_key=key, agent_blueprint=source,
                    execution_plan=plan, request_id='conversion-fixture-001')
        missing = dict(mapping)
        del missing['stage_mapping']
        bad = asyncio.run(preview_requirement_blueprint(**args, conversion=missing))
        assert bad.structuredContent['error']['errors'][0]['path'] == ['conversion', 'stage_mapping']
        good = asyncio.run(preview_requirement_blueprint(**args, conversion=mapping))
        assert not good.isError
        result = json.loads(good.content[0].text)
        assert result['document']['stages'][0]['task_key'] == 'CCTX-201'
        assert result['confirmation_required'] is True
        with db.session() as session:
            assert session.scalar(select(func.count()).select_from(RequirementCase)) == 0
    finally:
        bridge.bind(reader, reader.gateway)
