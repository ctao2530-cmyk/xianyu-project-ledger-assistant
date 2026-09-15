from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DatabaseError

from backend.app.adapters import IncomingMessage
from backend.app.ai import (
    OpenAIResponseResult,
    OpenAIResponsesError,
)
from backend.app.config import Settings
from backend.app.customer_analysis_schemas import CustomerAutoAnalysisResult
from backend.app.database import Database
from backend.app.models import (
    Conversation,
    CustomerAnalysisArtifact,
    CustomerAnalysisEvent,
    CustomerAnalysisRun,
    CustomerAnalysisThread,
    CustomerImageArchive,
    GlobalAgentThread,
    Message,
    utcnow,
)
from backend.app.services.customer_auto_analysis import (
    CustomerAutoAnalysisError,
    CustomerAutoAnalysisService,
)
from backend.app.services.customer_context_gateway import CustomerContextGateway
from backend.app.services.customer_context_reader import (
    CustomerContextReadError,
    CustomerContextReadService,
)
from backend.app.services.event_hub import EventHub
from backend.app.services.repository import ingest_message


ROOT = Path(__file__).resolve().parents[2]


def upgrade(path: Path, revision: str) -> None:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def result_payload(message_id: int, *, suffix: str = "") -> dict:
    evidence = [f"customer-message:{message_id}"]
    return {
        "customer_summary": {
            "goals": [{"text": f"完成客户目标{suffix}", "evidence_message_ids": [message_id]}],
            "confirmed_requirements": [],
            "unconfirmed_requirements": [],
            "constraints": [],
            "decisions": [],
            "recent_changes": [],
            "pending_questions": [],
            "risks": [],
        },
        "requirement_analysis": {
            "maturity": "ready",
            "summary": f"客户需求已形成{suffix}",
            "customer_confirmed": [
                {"text": f"只实现已确认需求{suffix}", "evidence_refs": evidence}
            ],
            "operator_decisions": [],
            "unconfirmed": [],
            "constraints": [],
            "open_questions": [],
            "assumptions": [],
            "risks": [],
        },
        "requirement_blueprint": {
            "title": "客户需求蓝图",
            "maturity": "ready",
            "objectives": [
                {
                    "id": "goal_main",
                    "title": "项目目标",
                    "description": "完成确认需求",
                    "evidence_refs": evidence,
                }
            ],
            "capabilities": [
                {
                    "id": "capability_main",
                    "title": "核心能力",
                    "description": "实现确认范围",
                    "objective_ids": ["goal_main"],
                    "priority": "must",
                    "evidence_refs": evidence,
                }
            ],
            "stages": [
                {
                    "id": "stage_main",
                    "title": "实施阶段",
                    "objective": "完成实现并验证",
                    "capability_ids": ["capability_main"],
                    "dependency_ids": [],
                    "work_items": ["实现确认范围"],
                    "deliverables": ["可验收结果"],
                    "estimated_hours": None,
                    "evidence_refs": evidence,
                }
            ],
            "acceptance_gates": [
                {
                    "id": "gate_main",
                    "title": "交付验收",
                    "description": "以真实测试为准",
                    "stage_ids": ["stage_main"],
                    "criteria": ["过程测试和验收通过"],
                    "evidence_refs": evidence,
                }
            ],
            "out_of_scope": ["自动发送客户消息"],
            "assumptions": [],
            "open_questions": [],
            "risks": [],
        },
        "execution_plan": {
            "title": "客户需求执行计划",
            "objective": "只实现确认范围",
            "readiness": "ready",
            "change_summary": f"按新证据更新{suffix}",
            "allowed_changes": ["需求范围内代码"],
            "must_not_change": ["客户消息和其他业务记录"],
            "out_of_scope": ["自动业务动作"],
            "stages": [
                {
                    "id": "plan_stage_main",
                    "task_key": "CCTX-201",
                    "workspace_key": "customer-context/analysis",
                    "title": "实现与验证",
                    "objective": "完成有证据的实现",
                    "dependency_task_keys": [],
                    "allowed_changes": ["需求文档和执行计划"],
                    "deliverables": ["需求文档", "执行计划"],
                    "process_tests": ["运行定向测试"],
                    "acceptance_criteria": ["真实测试通过"],
                    "stop_conditions": ["证据不足时停止"],
                    "evidence_refs": evidence,
                }
            ],
            "assumptions": [],
            "open_questions": [],
            "risks": [],
        },
    }


class FakeResponsesClient:
    def __init__(
        self,
        *,
        configured: bool = True,
        failures: int = 0,
        creation_failures: int = 0,
    ) -> None:
        self.configured = configured
        self.failures = failures
        self.creation_failures = creation_failures
        self.conversation_creations: list[str] = []
        self.calls: list[dict] = []
        self.closed = False

    async def create_conversation(self, *, local_thread_id: str) -> str:
        self.conversation_creations.append(local_thread_id)
        if self.creation_failures:
            self.creation_failures -= 1
            raise OpenAIResponsesError(
                "openai_conversation_timeout",
                "OpenAI 会话创建结果不确定",
            )
        return f"conv-openai-{len(self.conversation_creations)}"

    async def analyze(
        self,
        *,
        conversation_id: str,
        prompt: str,
        result_type,
        images: list,
        model: str,
    ) -> OpenAIResponseResult:
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "prompt": prompt,
                "images": images,
                "model": model,
            }
        )
        if self.failures:
            self.failures -= 1
            raise OpenAIResponsesError("openai_timeout", "OpenAI 客户需求分析超时")
        payload = json.loads(prompt)
        message_id = int(payload["incremental_messages"][-1]["id"])
        result = result_type.model_validate(
            result_payload(message_id, suffix=f"-v{len(self.calls)}")
        )
        return OpenAIResponseResult(
            response_id=f"response-{len(self.calls)}",
            result=result,
        )

    async def close(self) -> None:
        self.closed = True


def build_service(
    tmp_path: Path,
    *,
    configured: bool = True,
    failures: int = 0,
    creation_failures: int = 0,
    with_message: bool = True,
) -> tuple[Database, CustomerAutoAnalysisService, FakeResponsesClient, int, int | None]:
    database = Database(f"sqlite:///{tmp_path / 'analysis.db'}")
    database.create_all()
    with database.session() as session:
        conversation = Conversation(
            channel="xianyu",
            external_id="analysis-conversation",
            customer_id="analysis-customer",
            customer_name="分析测试客户",
        )
        session.add(conversation)
        session.flush()
        session.add(
            GlobalAgentThread(
                id="analysis-agent-thread",
                title="持续分析测试",
                profile_id=None,
                provider="codex_cli",
                model="gpt-test",
                reasoning_effort="medium",
                context_scope="customer_conversation",
                conversation_id=conversation.id,
                customer_id=None,
                status="active",
                revision=1,
            )
        )
        message_id = None
        if with_message:
            message = Message(
                channel="xianyu",
                platform_message_id="analysis-message-1",
                external_id="analysis-message-1",
                conversation_id=conversation.id,
                sender_id="analysis-customer",
                sender_name="分析测试客户",
                direction="inbound",
                message_type="text",
                content="请只实现已确认的客户需求",
                status="new",
                received_at=datetime.now(timezone.utc),
            )
            session.add(message)
            session.flush()
            message_id = message.id
        session.commit()
        conversation_id = conversation.id
    settings = Settings(
        _env_file=None,
        project_root=tmp_path,
        openai_api_key="test-openai-key" if configured else "",
        customer_analysis_model="gpt-test",
        customer_analysis_debounce_seconds=30,
        customer_analysis_max_wait_seconds=60,
        customer_analysis_poll_seconds=0.2,
    )
    client = FakeResponsesClient(
        configured=configured,
        failures=failures,
        creation_failures=creation_failures,
    )
    service = CustomerAutoAnalysisService(database, settings, EventHub(), client)  # type: ignore[arg-type]
    return database, service, client, conversation_id, message_id


def enable(service: CustomerAutoAnalysisService):
    return service.upsert_subscription(
        request_id="analysis-enable-0001",
        thread_id="analysis-agent-thread",
        expected_thread_revision=1,
        expected_subscription_revision=0,
        model="gpt-test",
        include_images=False,
        debounce_seconds=30,
        max_wait_seconds=60,
        authorization_note="用户明确授权 OpenAI 持续分析该绑定客户会话",
    )


def incoming(external_id: str, content: str = "客户补充了新需求") -> IncomingMessage:
    return IncomingMessage(
        external_id=external_id,
        platform_message_id=external_id,
        conversation_id="analysis-conversation",
        sender_id="analysis-customer",
        sender_name="分析测试客户",
        content=content,
        message_type="text",
        received_at=datetime.now(timezone.utc),
    )


def test_subscription_revision_request_id_and_configuration_required(tmp_path: Path) -> None:
    database, service, _client, _conversation_id, message_id = build_service(
        tmp_path, configured=False
    )
    view = enable(service)
    assert view.analysis_state == "configuration_required"
    assert view.configured is False
    assert view.pending_message_count == 1
    assert service._due_thread_ids(1) == []

    repeated = enable(service)
    assert repeated.idempotent is True
    with pytest.raises(CustomerAutoAnalysisError) as reused:
        service.upsert_subscription(
            request_id="analysis-enable-0001",
            thread_id="analysis-agent-thread",
            expected_thread_revision=1,
            expected_subscription_revision=0,
            model="different-model",
            include_images=False,
            debounce_seconds=30,
            max_wait_seconds=60,
            authorization_note="不同载荷不得复用同一个请求编号",
        )
    assert reused.value.code == "request_id_reused"
    with database.session() as session:
        assert session.scalar(select(func.count(CustomerAnalysisEvent.id))) == 1
        assert session.get(Message, message_id) is not None


def test_message_and_outbox_share_transaction_and_replay_is_idempotent(tmp_path: Path) -> None:
    database, service, _client, _conversation_id, _message_id = build_service(
        tmp_path, with_message=False
    )
    enable(service)

    def failing_callback(session, message):
        service.persist_message_event(session, message)
        raise RuntimeError("rollback")

    with pytest.raises(RuntimeError, match="rollback"):
        with database.session() as session:
            ingest_message(
                session,
                incoming("analysis-rollback"),
                [],
                None,
                on_persist=failing_callback,
            )
    with database.session() as session:
        assert session.scalar(
            select(func.count(Message.id)).where(
                Message.platform_message_id == "analysis-rollback"
            )
        ) == 0
        assert session.scalar(select(func.count(CustomerAnalysisEvent.id))) == 0

    with database.session() as session:
        first = ingest_message(
            session,
            incoming("analysis-live-1"),
            [],
            None,
            on_persist=service.persist_message_event,
        )
    with database.session() as session:
        duplicate = ingest_message(
            session,
            incoming("analysis-live-1"),
            [],
            None,
            on_persist=service.persist_message_event,
        )
    assert first.is_new is True
    assert duplicate.is_new is False
    with database.session() as session:
        assert session.scalar(select(func.count(CustomerAnalysisEvent.id))) == 1


def test_database_triggers_enforce_analysis_thread_and_event_conversation_scope(
    tmp_path: Path,
) -> None:
    database, service, _client, _conversation_id, _message_id = build_service(tmp_path)
    subscription = enable(service)
    with database.session() as session:
        other = Conversation(
            channel="xianyu",
            external_id="analysis-conversation-other",
            customer_id="analysis-customer-other",
            customer_name="另一测试客户",
        )
        session.add(other)
        session.flush()
        other_message = Message(
            channel="xianyu",
            platform_message_id="analysis-message-other",
            external_id="analysis-message-other",
            conversation_id=other.id,
            sender_id="analysis-customer-other",
            sender_name="另一测试客户",
            direction="inbound",
            message_type="text",
            content="另一会话的测试消息",
            status="new",
            received_at=utcnow(),
        )
        session.add(other_message)
        session.flush()
        other_conversation_id = other.id
        other_message_id = other_message.id
        session.commit()

    with database.session() as session:
        session.add(
            CustomerAnalysisEvent(
                id="cross-conversation-event",
                analysis_thread_id=subscription.id,
                conversation_id=other_conversation_id,
                message_id=other_message_id,
                event_key="cross-conversation-event",
                status="pending",
                created_at=utcnow(),
            )
        )
        with pytest.raises(DatabaseError, match="scope mismatch"):
            session.commit()

    with database.session() as session:
        analysis = session.get(CustomerAnalysisThread, subscription.id)
        assert analysis is not None
        analysis.conversation_id = other_conversation_id
        with pytest.raises(DatabaseError, match="binding mismatch"):
            session.commit()

    with database.session() as session:
        thread = session.get(GlobalAgentThread, "analysis-agent-thread")
        assert thread is not None
        thread.context_scope = "general_business"
        thread.conversation_id = None
        with pytest.raises(DatabaseError, match="active customer analysis binding"):
            session.commit()

    paused = service.pause_subscription(
        subscription.id,
        request_id="analysis-pause-for-context-switch",
        expected_revision=subscription.revision,
        reason="停止后允许小策切换上下文",
    )
    assert paused.status == "paused"
    with database.session() as session:
        thread = session.get(GlobalAgentThread, "analysis-agent-thread")
        assert thread is not None
        thread.context_scope = "general_business"
        thread.conversation_id = None
        session.commit()


def test_debounce_respects_sixty_second_hard_deadline(tmp_path: Path) -> None:
    database, service, _client, _conversation_id, _message_id = build_service(
        tmp_path, with_message=False
    )
    subscription = enable(service)
    with database.session() as session:
        ingest_message(
            session,
            incoming("analysis-debounce-1"),
            [],
            None,
            on_persist=service.persist_message_event,
        )
    with database.session() as session:
        row = session.get(CustomerAnalysisThread, subscription.id)
        assert row is not None
        row.pending_since = utcnow() - timedelta(seconds=59)
        session.commit()
    before = utcnow()
    with database.session() as session:
        ingest_message(
            session,
            incoming("analysis-debounce-2"),
            [],
            None,
            on_persist=service.persist_message_event,
        )
    with database.session() as session:
        row = session.get(CustomerAnalysisThread, subscription.id)
        assert row is not None and row.next_run_at is not None
        assert service._aware(row.next_run_at) <= before + timedelta(seconds=2)


@pytest.mark.asyncio
async def test_incremental_runs_reuse_conversation_and_append_immutable_artifacts(
    tmp_path: Path,
) -> None:
    database, service, client, _conversation_id, first_message_id = build_service(tmp_path)
    subscription = enable(service)
    await service._run_thread(subscription.id)
    with database.session() as session:
        first_artifact = session.scalar(select(CustomerAnalysisArtifact))
        assert first_artifact is not None
        first_content = first_artifact.content_json

    with database.session() as session:
        second = ingest_message(
            session,
            incoming("analysis-live-2"),
            [],
            None,
            on_persist=service.persist_message_event,
        )
    with database.session() as session:
        row = session.get(CustomerAnalysisThread, subscription.id)
        assert row is not None
        row.next_run_at = utcnow()
        session.commit()
    await service._run_thread(subscription.id)

    assert client.conversation_creations == [subscription.id]
    assert [call["conversation_id"] for call in client.calls] == [
        "conv-openai-1",
        "conv-openai-1",
    ]
    second_prompt = json.loads(client.calls[1]["prompt"])
    assert [item["id"] for item in second_prompt["incremental_messages"]] == [
        second.message_id
    ]
    with database.session() as session:
        artifacts = list(
            session.scalars(
                select(CustomerAnalysisArtifact).order_by(CustomerAnalysisArtifact.version)
            )
        )
        assert [artifact.version for artifact in artifacts] == [1, 2]
        assert artifacts[0].content_json == first_content
        assert artifacts[1].previous_artifact_id == artifacts[0].id
        assert artifacts[0].watermark_after == first_message_id
        assert artifacts[1].watermark_before == first_message_id
        assert artifacts[1].watermark_after == second.message_id

    with database.session() as session:
        with pytest.raises(DatabaseError, match="immutable"):
            session.execute(
                update(CustomerAnalysisArtifact)
                .where(CustomerAnalysisArtifact.id == artifacts[-1].id)
                .values(content_json="{}")
            )
            session.commit()
        session.rollback()
        with pytest.raises(DatabaseError, match="immutable"):
            session.execute(
                delete(CustomerAnalysisArtifact).where(
                    CustomerAnalysisArtifact.id == artifacts[-1].id
                )
            )
            session.commit()


@pytest.mark.asyncio
async def test_large_incremental_batch_never_advances_past_unsent_messages(
    tmp_path: Path,
) -> None:
    database, service, client, _conversation_id, _message_id = build_service(tmp_path)
    service.settings.customer_analysis_max_context_chars = 10_000
    subscription = enable(service)
    await service._run_thread(subscription.id)

    with database.session() as session:
        first = ingest_message(
            session,
            incoming("analysis-large-1", "甲" * 7_000),
            [],
            None,
            on_persist=service.persist_message_event,
        )
    with database.session() as session:
        second = ingest_message(
            session,
            incoming("analysis-large-2", "乙" * 7_000),
            [],
            None,
            on_persist=service.persist_message_event,
        )
        row = session.get(CustomerAnalysisThread, subscription.id)
        assert row is not None
        row.next_run_at = utcnow()
        session.commit()

    await service._run_thread(subscription.id)
    first_increment = json.loads(client.calls[-1]["prompt"])["incremental_messages"]
    assert [item["id"] for item in first_increment] == [first.message_id]
    with database.session() as session:
        row = session.get(CustomerAnalysisThread, subscription.id)
        events = list(
            session.scalars(
                select(CustomerAnalysisEvent)
                .where(CustomerAnalysisEvent.message_id.in_([first.message_id, second.message_id]))
                .order_by(CustomerAnalysisEvent.message_id)
            )
        )
        assert row is not None
        assert row.last_analyzed_message_id == first.message_id
        assert [event.status for event in events] == ["completed", "pending"]

    await service._run_thread(subscription.id)
    second_increment = json.loads(client.calls[-1]["prompt"])["incremental_messages"]
    assert [item["id"] for item in second_increment] == [second.message_id]
    with database.session() as session:
        row = session.get(CustomerAnalysisThread, subscription.id)
        assert row is not None and row.last_analyzed_message_id == second.message_id


@pytest.mark.asyncio
async def test_pause_discards_inflight_result_and_resume_requeues_same_watermark(
    tmp_path: Path,
) -> None:
    database, service, client, _conversation_id, _message_id = build_service(tmp_path)
    subscription = enable(service)
    run_id = service._claim_run(subscription.id)
    assert run_id is not None
    context = service._build_context(run_id)
    paused = service.pause_subscription(
        subscription.id,
        request_id="analysis-pause-0001",
        expected_revision=subscription.revision,
        reason="测试暂停",
    )
    resumed = service.upsert_subscription(
        request_id="analysis-resume-0001",
        thread_id="analysis-agent-thread",
        expected_thread_revision=1,
        expected_subscription_revision=paused.revision,
        model="gpt-test",
        include_images=False,
        debounce_seconds=30,
        max_wait_seconds=60,
        authorization_note="重新授权继续处理原水位线",
    )
    prompt = json.loads(context["prompt"])
    result = CustomerAutoAnalysisResult.model_validate(
        result_payload(prompt["incremental_messages"][-1]["id"])
    )
    service._complete_run(
        run_id,
        result=result,
        response_id="response-after-pause",
        source_hash=context["source_hash"],
        evidence_message_ids=sorted(context["allowed_message_ids"]),
        evidence_image_ids=[],
        image_count=0,
    )
    with database.session() as session:
        run = session.get(CustomerAnalysisRun, run_id)
        event = session.scalar(select(CustomerAnalysisEvent))
        row = session.get(CustomerAnalysisThread, subscription.id)
        assert run is not None and run.status == "cancelled"
        assert event is not None and event.status == "pending" and event.run_id is None
        assert row is not None and row.analysis_state == "pending"
        assert session.scalar(select(func.count(CustomerAnalysisArtifact.id))) == 0
    assert resumed.status == "active"
    await service._run_thread(subscription.id)
    with database.session() as session:
        runs = list(session.scalars(select(CustomerAnalysisRun).order_by(CustomerAnalysisRun.created_at)))
        assert [run.status for run in runs] == ["cancelled", "completed"]
        assert session.scalar(select(func.count(CustomerAnalysisArtifact.id))) == 1
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_failed_run_requires_explicit_retry_and_keeps_attempt_history(
    tmp_path: Path,
) -> None:
    database, service, client, _conversation_id, _message_id = build_service(
        tmp_path, failures=1
    )
    subscription = enable(service)
    await service._run_thread(subscription.id)
    failed = service.subscription("analysis-agent-thread")
    assert failed is not None
    assert failed.analysis_state == "failed"
    assert failed.last_error_code == "openai_response_uncertain"
    assert service._due_thread_ids(1) == []
    with database.session() as session:
        first_run = session.scalar(select(CustomerAnalysisRun))
        assert first_run is not None
        assert first_run.external_response_id.startswith("uncertain:")

    retried = service.retry(
        subscription.id,
        request_id="analysis-retry-0001",
        expected_revision=failed.revision,
    )
    with database.session() as session:
        first_run = session.scalar(
            select(CustomerAnalysisRun).order_by(CustomerAnalysisRun.created_at.asc())
        )
        assert first_run is not None
        assert first_run.external_response_id.startswith("retry-authorized:")
    await service._run_thread(subscription.id)
    assert retried.analysis_state == "pending"
    with database.session() as session:
        runs = list(
            session.scalars(
                select(CustomerAnalysisRun).order_by(CustomerAnalysisRun.created_at)
            )
        )
        assert [run.status for run in runs] == ["failed", "completed"]
        assert len({run.run_key for run in runs}) == 2
        assert session.scalar(select(func.count(CustomerAnalysisArtifact.id))) == 1
    assert len(client.calls) == 2


def test_uncertain_response_after_pause_requires_explicit_retry(tmp_path: Path) -> None:
    database, service, _client, _conversation_id, _message_id = build_service(tmp_path)
    subscription = enable(service)
    run_id = service._claim_run(subscription.id)
    assert run_id is not None
    lease = service._start_response_lease(run_id)
    assert lease is not None
    assert service._mark_response_uncertain(run_id, lease) is True

    paused = service.pause_subscription(
        subscription.id,
        request_id="analysis-pause-uncertain-0001",
        expected_revision=subscription.revision,
        reason="模拟 OpenAI 请求结果不确定后停止",
    )
    service._cancel_run(run_id)
    resumed = service.upsert_subscription(
        request_id="analysis-resume-uncertain-0001",
        thread_id="analysis-agent-thread",
        expected_thread_revision=1,
        expected_subscription_revision=paused.revision,
        model="gpt-test",
        include_images=False,
        debounce_seconds=30,
        max_wait_seconds=60,
        authorization_note="恢复后仍须人工确认不确定请求",
    )
    assert resumed.analysis_state == "pending"
    assert service._claim_run(subscription.id) is None
    blocked = service.subscription("analysis-agent-thread")
    assert blocked is not None
    assert blocked.analysis_state == "failed"
    assert blocked.last_error_code == "openai_response_uncertain"

    service.retry(
        subscription.id,
        request_id="analysis-retry-uncertain-0001",
        expected_revision=blocked.revision,
    )
    assert service._claim_run(subscription.id) is not None


def test_subscription_scope_cannot_change_while_openai_run_is_claimed(
    tmp_path: Path,
) -> None:
    _database, service, _client, _conversation_id, _message_id = build_service(tmp_path)
    subscription = enable(service)
    assert service._claim_run(subscription.id) is not None

    with pytest.raises(CustomerAutoAnalysisError) as blocked:
        service.upsert_subscription(
            request_id="analysis-update-during-run-0001",
            thread_id="analysis-agent-thread",
            expected_thread_revision=1,
            expected_subscription_revision=subscription.revision,
            model="gpt-test-updated",
            include_images=True,
            debounce_seconds=30,
            max_wait_seconds=60,
            authorization_note="运行中不得扩大或缩小客户数据授权",
        )
    assert blocked.value.code == "analysis_in_progress"


@pytest.mark.asyncio
async def test_uncertain_conversation_creation_never_retries_without_confirmation(
    tmp_path: Path,
) -> None:
    database, service, client, _conversation_id, _message_id = build_service(
        tmp_path,
        creation_failures=1,
    )
    subscription = enable(service)
    await service._run_thread(subscription.id)
    failed = service.subscription("analysis-agent-thread")
    assert failed is not None and failed.analysis_state == "failed"
    assert failed.external_conversation_ready is False
    assert client.conversation_creations == [subscription.id]

    # A new wake-up cannot create a second OpenAI Conversation.
    await service._run_thread(subscription.id)
    assert client.conversation_creations == [subscription.id]

    service.retry(
        subscription.id,
        request_id="analysis-conversation-retry-0001",
        expected_revision=failed.revision,
    )
    await service._run_thread(subscription.id)
    assert client.conversation_creations == [subscription.id, subscription.id]
    with database.session() as session:
        row = session.get(CustomerAnalysisThread, subscription.id)
        assert row is not None
        assert row.external_conversation_id == "conv-openai-2"
        assert row.latest_artifact_version == 1


@pytest.mark.asyncio
async def test_explicit_missing_artifact_version_never_falls_back_to_latest(
    tmp_path: Path,
) -> None:
    database, service, _client, _conversation_id, _message_id = build_service(tmp_path)
    subscription = enable(service)
    await service._run_thread(subscription.id)
    gateway = CustomerContextGateway(database)
    grant = gateway.create_grant(
        thread_id="analysis-agent-thread",
        request_id="analysis-artifact-grant-0001",
        expected_revision=1,
        allow_text=False,
        allow_images=False,
        allow_artifacts=True,
        allow_new_messages=True,
        expires_in_seconds=900,
        authorization_note="测试精确读取需求成果版本",
        audience="openai_chatgpt",
    )
    reader = CustomerContextReadService(database, gateway, tmp_path, service)
    with pytest.raises(CustomerContextReadError) as missing:
        reader.customer_artifact(
            "execution_plan",
            999,
            request_id="analysis-artifact-read-0001",
            capability_token=grant["capability_token"],
            audience="openai_chatgpt",
            target_model="external-openai-mcp",
        )
    assert missing.value.code == "artifact_not_found"
    with pytest.raises(CustomerAutoAnalysisError) as service_missing:
        service.artifacts("analysis-agent-thread", version=999)
    assert service_missing.value.code == "artifact_not_found"
    assert service_missing.value.status_code == 404


@pytest.mark.asyncio
async def test_new_messages_stay_durable_while_failed_until_manual_retry(
    tmp_path: Path,
) -> None:
    database, service, client, _conversation_id, _message_id = build_service(
        tmp_path, failures=1
    )
    subscription = enable(service)
    await service._run_thread(subscription.id)
    with database.session() as session:
        added = ingest_message(
            session,
            incoming("analysis-after-failure"),
            [],
            None,
            on_persist=service.persist_message_event,
        )
    view = service.subscription("analysis-agent-thread")
    assert view is not None
    assert view.analysis_state == "failed"
    assert view.next_run_at is None
    assert view.last_enqueued_message_id == added.message_id
    assert service._due_thread_ids(1) == []
    assert len(client.calls) == 1


def test_restart_preserves_failed_batch_for_explicit_retry(tmp_path: Path) -> None:
    database, service, _client, _conversation_id, _message_id = build_service(tmp_path)
    subscription = enable(service)
    run_id = service._claim_run(subscription.id)
    assert run_id is not None
    service._recover_interrupted()
    with database.session() as session:
        run = session.get(CustomerAnalysisRun, run_id)
        row = session.get(CustomerAnalysisThread, subscription.id)
        event = session.scalar(select(CustomerAnalysisEvent))
        assert run is not None and run.status == "failed"
        assert run.error_code == "service_restarted"
        assert event is not None and event.status == "failed" and event.run_id == run.id
        assert row is not None and row.analysis_state == "failed"
        assert row.next_run_at is None


@pytest.mark.asyncio
async def test_invalid_archived_image_is_skipped_without_blocking_text_analysis(
    tmp_path: Path,
) -> None:
    database, service, client, conversation_id, message_id = build_service(tmp_path)
    with database.session() as session:
        session.add(
            CustomerImageArchive(
                id="analysis-broken-image",
                conversation_id=conversation_id,
                message_id=message_id,
                channel="xianyu",
                platform_message_id="analysis-message-1",
                media_index=0,
                capture_status="stored",
                capture_source="live",
                mime_type="image/png",
                original_name="broken.png",
                storage_path="data/customer-images/2026/09/missing.png",
                sha256="a" * 64,
                file_size=123,
                width=1,
                height=1,
                integrity_verified=True,
                received_at=utcnow(),
                captured_at=utcnow(),
            )
        )
        session.commit()
    subscription = service.upsert_subscription(
        request_id="analysis-enable-images",
        thread_id="analysis-agent-thread",
        expected_thread_revision=1,
        expected_subscription_revision=0,
        model="gpt-test",
        include_images=True,
        debounce_seconds=30,
        max_wait_seconds=60,
        authorization_note="用户明确授权本批已归档原图交由 OpenAI 分析",
    )
    await service._run_thread(subscription.id)
    assert len(client.calls) == 1
    assert client.calls[0]["images"] == []
    with database.session() as session:
        run = session.scalar(select(CustomerAnalysisRun))
        assert run is not None and run.status == "completed" and run.image_count == 0


def test_schema_rejects_invalid_task_keys_and_dependency_cycles() -> None:
    invalid_key = result_payload(1)
    invalid_key["execution_plan"]["stages"][0]["task_key"] = "invalid"
    with pytest.raises(Exception):
        CustomerAutoAnalysisResult.model_validate(invalid_key)

    cyclic = result_payload(1)
    first = cyclic["execution_plan"]["stages"][0]
    first["dependency_task_keys"] = ["CCTX-202"]
    cyclic["execution_plan"]["stages"].append(
        {
            **first,
            "id": "plan_stage_second",
            "task_key": "CCTX-202",
            "dependency_task_keys": ["CCTX-201"],
        }
    )
    with pytest.raises(Exception):
        CustomerAutoAnalysisResult.model_validate(cyclic)


def test_0040_to_0041_and_startup_migration_guards(tmp_path: Path) -> None:
    path = tmp_path / "alembic-analysis.db"
    upgrade(path, "20260901_0040")
    upgrade(path, "20260901_0041")
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260901_0041",)
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "customer_analysis_threads",
            "customer_analysis_events",
            "customer_analysis_runs",
            "customer_analysis_artifacts",
            "customer_analysis_mutation_requests",
        } <= tables

    startup_path = tmp_path / "startup-analysis.db"
    Database(f"sqlite:///{startup_path}").create_all()
    Database(f"sqlite:///{startup_path}").create_all()
    with sqlite3.connect(startup_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DROP TABLE customer_analysis_runs")
        connection.commit()
    with pytest.raises(RuntimeError, match="customer auto analysis schema is incomplete"):
        Database(f"sqlite:///{startup_path}").create_all()
