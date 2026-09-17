from datetime import timedelta
import json
from sqlalchemy import select
from backend.tests.test_customer_auto_analysis import build_service, enable, incoming
from backend.app.models import CustomerAnalysisRun, CustomerAnalysisThread, CustomerAnalysisArtifact, utcnow
from backend.app.services.repository import ingest_message

async def test_daily_limit_keeps_messages_pending_and_resumes_next_day(tmp_path):
    db,service,client,_,_=build_service(tmp_path);service.settings.customer_analysis_daily_run_limit=1
    subscription=enable(service);await service._run_thread(subscription.id)
    with db.session() as s:ingest_message(s,incoming('new-pending-message'),[],None,on_persist=service.persist_message_event)
    with db.session() as s:
        row=s.get(CustomerAnalysisThread,subscription.id);row.next_run_at=utcnow();s.commit()
    assert service._due_thread_ids(2)==[]
    await service._run_thread(subscription.id)
    assert len(client.calls)==1
    with db.session() as s:
        run=s.scalar(select(CustomerAnalysisRun));run.created_at=utcnow()-timedelta(days=2);s.commit()
    assert service._due_thread_ids(2)==[subscription.id]
    await service._run_thread(subscription.id)
    assert len(client.calls)==2

async def test_provider_token_usage_is_persisted_as_metadata_not_business_content(tmp_path):
    from backend.app.ai import OpenAIResponseResult
    db,service,client,_,_=build_service(tmp_path)
    original=client.analyze
    async def analyze(**kwargs):
        result=await original(**kwargs)
        return OpenAIResponseResult(result.response_id,result.result,{'input_tokens':12,'output_tokens':8,'total_tokens':20})
    client.analyze=analyze
    subscription=enable(service);await service._run_thread(subscription.id)
    with db.session() as s:
        artifact=s.scalar(select(CustomerAnalysisArtifact))
        assert json.loads(artifact.diff_json)['provider_usage']['total_tokens']==20
        assert 'provider_usage' not in json.loads(artifact.content_json)

async def test_response_client_limits_output_and_only_returns_safe_usage():
    import httpx
    from pydantic import BaseModel
    from backend.app.config import Settings
    from backend.app.ai.openai_responses import OpenAIResponsesClient
    class Result(BaseModel):
        ok: bool
    seen=[]
    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'synthetic-response','output_text':'{"ok":true}',
            'usage':{'input_tokens':12,'output_tokens':8,'total_tokens':20,'private_payload':'excluded'}})
    client=OpenAIResponsesClient(Settings(_env_file=None,openai_api_key='synthetic',customer_analysis_model='synthetic',customer_analysis_max_output_tokens=2000))
    await client.client.aclose();client.client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    result=await client.analyze(conversation_id='synthetic',prompt='synthetic',result_type=Result,images=[],model='synthetic')
    await client.client.aclose()
    assert seen[0]['max_output_tokens']==2000
    assert result.usage=={'input_tokens':12,'output_tokens':8,'total_tokens':20}
