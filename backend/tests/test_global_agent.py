from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat

from alembic import command
from alembic.config import Config
import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from backend.app.agents.global_agent import (
    GlobalAgentBusinessTools,
    GlobalAgentRAG,
    GlobalAgentService,
    GlobalAgentServiceError,
)
from backend.app.agents.global_agent.graph import GLOBAL_AGENT_GRAPH_NODE_ORDER
from backend.app.agents.global_agent.langchain_adapter import (
    LOCAL_RUNNABLE_CONFIG,
    local_tracing_disabled,
)
from backend.app.agents.global_agent.tools import ToolExecution
from backend.app.ai.base import AIProvider, AIProviderError, ProviderHealth
from backend.app.config import Settings, get_settings
from backend.app.database import Database
from backend.app.global_agent_schemas import (
    AgentCustomerConversationSummary,
    AgentCustomerCreateProposal,
    AgentCustomerPriceProposal,
    AgentCustomerProposalText,
    AgentCustomerSummaryItem,
    AgentExecutionPlan,
    AgentExecutionPlanStage,
    AgentFact,
    AgentMessageCreate,
    AgentModelAnswer,
    AgentRequirementAcceptanceGate,
    AgentRequirementAnalysis,
    AgentRequirementAnalysisItem,
    AgentRequirementBlueprint,
    AgentRequirementCapability,
    AgentRequirementObjective,
    AgentRequirementStage,
    AgentThreadCreate,
    AgentThreadContextUpdate,
    AgentThreadProfileUpdate,
)
from backend.app.ledger import LedgerService
from backend.app.models import (
    BusinessCustomer,
    Conversation,
    GlobalAgentConversationSummary,
    GlobalAgentKnowledgeDocument,
    GlobalAgentMessage,
    GlobalAgentMutationRequest,
    GlobalAgentRun,
    GlobalAgentRunStep,
    GlobalAgentToolCall,
    Item,
    Message,
    ProductMonitor,
    RequirementCase,
    RequirementDocumentVersion,
)
from backend.app.services.event_hub import EventHub
from backend.app.services.customer_intake import CustomerIntakeService
from langsmith.run_helpers import get_tracing_context


ROOT = Path(__file__).resolve().parents[2]


def upgrade(path: Path, revision: str) -> None:
    previous = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = f"sqlite:///{path}"
        get_settings.cache_clear()
        command.upgrade(Config(str(ROOT / "alembic.ini")), revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


class FakeOverview:
    def __init__(
        self,
        *,
        summary: str = "当前证据基线",
        ledger_revision: int = 7,
        is_stale: bool = False,
    ) -> None:
        self.summary = summary
        self.ledger_revision = ledger_revision
        self.is_stale = is_stale

    def model_dump(self, *, mode: str = "json") -> dict:
        return {
            "summary": self.summary,
            "metrics": {},
            "insights": [],
            "recommendations": [],
            "data_sources": [],
            "data_gaps": ["仍需真实数据"],
            "period": {"timezone": "Asia/Shanghai"},
            "ledger_revision": self.ledger_revision,
            "generated_at": "2026-08-28T00:00:00Z",
            "snapshot_time": "2026-08-28T00:00:00Z",
            "is_stale": self.is_stale,
        }


class FakeAnalysis:
    def __init__(self) -> None:
        self.overview_calls = 0
        self.latest_calls = 0

    def overview(self) -> FakeOverview:
        self.overview_calls += 1
        return FakeOverview()

    def latest_or_overview(self) -> FakeOverview:
        self.latest_calls += 1
        return FakeOverview(
            summary="过期历史分析",
            ledger_revision=1,
            is_stale=True,
        )


class EvidenceProvider(AIProvider):
    name = "codex_cli"

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.prompts: list[dict] = []

    async def healthcheck(self, *, validate_execution: bool = True) -> ProviderHealth:
        return ProviderHealth(status="connected")

    async def generate(self, *args, **kwargs):
        raise NotImplementedError

    async def generate_structured(self, prompt: str, *, result_type, **kwargs):
        self.calls += 1
        payload = json.loads(prompt)
        self.prompts.append(payload)
        allowed = payload["allowed_evidence_ids"]
        knowledge = [value for value in allowed if value.startswith("knowledge:")]
        refs = allowed[:1]
        return result_type(
            conclusion="先核对当前本地证据，再执行一个人工动作。",
            facts=[AgentFact(text="回答仅使用已提供证据", evidence_refs=refs)] if refs else [],
            causes=["证据链比未验证推断更可靠"],
            knowledge_citation_ids=knowledge[:1],
            limitations=[] if allowed else ["当前没有可引用证据"],
            confidence="medium" if allowed else "low",
            observation_period="当前本地快照",
            next_step="打开对应页面人工核对",
            target_page="business-analysis",
        )


class NeverProvider(EvidenceProvider):
    name = "deepseek"


class BlockingProvider(EvidenceProvider):
    async def generate_structured(self, prompt: str, *, result_type, **kwargs):
        self.calls += 1
        await asyncio.Event().wait()


class CustomerContextProvider(EvidenceProvider):
    """Return an answer and its versioned customer summary in one response."""

    async def generate_structured(self, prompt: str, *, result_type, **kwargs):
        self.calls += 1
        payload = json.loads(prompt)
        self.prompts.append(payload)
        update = payload["customer_context_update"]
        allowed_message_ids = [
            int(value) for value in update.get("allowed_evidence_message_ids", [])
        ]
        evidence_ref = (
            f"customer-message:{allowed_message_ids[-1]}"
            if allowed_message_ids
            else None
        )
        summary = None
        if update.get("required"):
            summary = AgentCustomerConversationSummary(
                recent_changes=[
                    AgentCustomerSummaryItem(
                        text="客户文字上下文已纳入增量总结",
                        evidence_message_ids=[allowed_message_ids[-1]],
                    )
                ]
            )
        return result_type(
            conclusion="已依据绑定客户的文字会话完成分析。",
            facts=(
                [AgentFact(text="分析只引用绑定会话", evidence_refs=[evidence_ref])]
                if evidence_ref
                else []
            ),
            causes=["使用总结与新增消息可以避免重复发送历史原文"],
            knowledge_citation_ids=[],
            limitations=["图片与附件未进入本次上下文"],
            confidence="medium",
            observation_period="截至当前本地文字消息",
            next_step="人工核对客户最新补充",
            target_page="customers",
            updated_customer_context=summary,
        )


class RequirementArtifactProvider(CustomerContextProvider):
    """Create chat-only requirement artifacts from customer and operator evidence."""

    async def generate_structured(self, prompt: str, *, result_type, **kwargs):
        self.calls += 1
        payload = json.loads(prompt)
        self.prompts.append(payload)
        customer_ids = [
            value for value in payload["allowed_evidence_ids"]
            if value.startswith("customer-message:")
        ]
        operator_ids = [
            value for value in payload["allowed_evidence_ids"]
            if value.startswith("operator-note:")
        ]
        update = payload["customer_context_update"]
        allowed_message_ids = [
            int(value) for value in update.get("allowed_evidence_message_ids", [])
        ]
        summary = None
        if update.get("required"):
            summary = AgentCustomerConversationSummary(
                recent_changes=[
                    AgentCustomerSummaryItem(
                        text="客户文字已经进入可追溯总结",
                        evidence_message_ids=[allowed_message_ids[-1]],
                    )
                ]
            )
        customer_ref = customer_ids[-1]
        operator_ref = operator_ids[-1]
        return result_type(
            conclusion="已按客户事实与经营者补充形成聊天内需求蓝图。",
            facts=[AgentFact(text="两类证据已经分开", evidence_refs=[customer_ref, operator_ref])],
            causes=["客户确认与经营者判断不能相互替代"],
            knowledge_citation_ids=[],
            limitations=["图片与附件未进入上下文"],
            confidence="medium",
            observation_period="截至当前文字会话",
            next_step="人工核对待确认问题",
            target_page="customers",
            updated_customer_context=summary,
            requirement_analysis=AgentRequirementAnalysis(
                maturity="clarifying",
                summary="已有一项客户确认和一项经营者补充。",
                customer_confirmed=[
                    AgentRequirementAnalysisItem(
                        text="客户需要统一列表样式",
                        evidence_refs=[customer_ref],
                    )
                ],
                operator_decisions=[
                    AgentRequirementAnalysisItem(
                        text="经营者决定保持线上数据结构不变",
                        evidence_refs=[operator_ref],
                    )
                ],
                open_questions=["移动端最终验收视口是否固定为 390px？"],
            ),
            requirement_blueprint=AgentRequirementBlueprint(
                title="网站功能调整",
                maturity="clarifying",
                objectives=[
                    AgentRequirementObjective(
                        id="objective_consistency",
                        title="统一呈现",
                        description="统一列表与搜索结果样式",
                        evidence_refs=[customer_ref],
                    )
                ],
                capabilities=[
                    AgentRequirementCapability(
                        id="capability_list",
                        title="统一列表组件",
                        description="复用同一套列表结构",
                        objective_ids=["objective_consistency"],
                        priority="must",
                        evidence_refs=[customer_ref, operator_ref],
                    )
                ],
                stages=[
                    AgentRequirementStage(
                        id="stage_implementation",
                        title="实现与核对",
                        objective="完成桌面和移动端呈现",
                        capability_ids=["capability_list"],
                        work_items=["实现统一组件", "人工核对响应式"],
                        deliverables=["可验收页面"],
                        estimated_hours=None,
                        evidence_refs=[customer_ref, operator_ref],
                    )
                ],
                acceptance_gates=[
                    AgentRequirementAcceptanceGate(
                        id="acceptance_layout",
                        title="布局验收",
                        description="桌面与移动端均保持统一层级",
                        stage_ids=["stage_implementation"],
                        criteria=["无横向溢出", "列表样式一致"],
                        evidence_refs=[customer_ref],
                    )
                ],
                open_questions=["移动端最终验收视口是否固定为 390px？"],
            ),
        )


class ExecutionPlanProvider(EvidenceProvider):
    """Always proposes a plan so the service-side request filter can be tested."""

    async def generate_structured(self, prompt: str, *, result_type, **kwargs):
        self.calls += 1
        self.prompts.append(json.loads(prompt))
        return result_type(
            conclusion="已形成当前问题的处理建议。",
            facts=[],
            causes=[],
            knowledge_citation_ids=[],
            limitations=[],
            confidence="medium",
            observation_period="当前本地快照",
            next_step="人工核对",
            target_page="",
            execution_plan=AgentExecutionPlan(
                title="客户需求执行计划",
                objective="只实现用户明确确认的范围",
                readiness="ready",
                change_summary="以独立工作区分阶段实施",
                allowed_changes=["计划列明的代码与测试"],
                must_not_change=["客户关系与真实业务数据"],
                out_of_scope=["自动业务动作"],
                stages=[
                    AgentExecutionPlanStage(
                        id="stage_context",
                        task_key="CTX-100",
                        workspace_key="customer-context/gateway",
                        title="上下文授权",
                        objective="完成只读短时授权",
                        allowed_changes=["客户上下文网关"],
                        process_tests=["运行授权对抗性测试"],
                        acceptance_criteria=["未授权时零客户数据释放"],
                    )
                ],
            ),
        )


class CustomerCreateProposalProvider(CustomerContextProvider):
    """Return a reviewable proposal without performing any write."""

    async def generate_structured(self, prompt: str, *, result_type, **kwargs):
        self.calls += 1
        payload = json.loads(prompt)
        self.prompts.append(payload)
        update = payload["customer_context_update"]
        message_ids = [
            int(value) for value in update.get("allowed_evidence_message_ids", [])
        ]
        customer_ref = f"customer-message:{message_ids[-1]}"
        operator_ref = next(
            value
            for value in payload["allowed_evidence_ids"]
            if value.startswith("operator-note:")
        )
        identity = payload["customer_create_rules"]["bound_customer_identity"]
        identity_ref = identity["evidence_id"]
        summary = None
        if update.get("required"):
            summary = AgentCustomerConversationSummary(
                confirmed_requirements=[
                    AgentCustomerSummaryItem(
                        text="客户需要商品展示页",
                        evidence_message_ids=[message_ids[-1]],
                    )
                ]
            )
        return result_type(
            conclusion="已形成一份待人工确认的客户资料提案。",
            facts=[AgentFact(text="客户会话已明确绑定", evidence_refs=[identity_ref])],
            causes=["客户资料写入必须由经营者确认"],
            knowledge_citation_ids=[],
            limitations=["图片、附件和 OCR 未进入上下文"],
            confidence="medium",
            observation_period="截至当前绑定会话",
            next_step="人工核对提案后确认加入客户列表",
            target_page="customers",
            updated_customer_context=summary,
            customer_create_proposal=AgentCustomerCreateProposal(
                conversation_id=int(identity["conversation_id"]),
                customer_name=AgentCustomerProposalText(
                    value=identity["customer_name"], evidence_refs=[identity_ref]
                ),
                source=identity["channel"],
                level="B",
                current_need=AgentCustomerProposalText(
                    value="开发一个商品展示页", evidence_refs=[customer_ref]
                ),
                price=AgentCustomerPriceProposal(
                    price_type="operator_quote",
                    amount=2600,
                    evidence_refs=[operator_ref],
                ),
                next_action=AgentCustomerProposalText(
                    value="人工确认交付范围", evidence_refs=[operator_ref]
                ),
            ),
        )


async def wait_for_run(service: GlobalAgentService, run_id: str):
    current = service.run(run_id)
    for _ in range(200):
        if current.status not in {"pending", "running"}:
            return current
        await asyncio.sleep(0.01)
        current = service.run(run_id)
    raise AssertionError(f"run did not finish: {run_id}")


def create_customer_conversation(
    database: Database,
    *,
    suffix: str,
    text_count: int,
    image_count: int = 0,
) -> tuple[int, list[int], list[int]]:
    with database.session() as session:
        conversation = Conversation(
            channel="xianyu",
            external_id=f"customer-context-{suffix}",
            customer_id=f"platform-customer-{suffix}",
            customer_name=f"客户 {suffix}",
            last_message_at=datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc),
        )
        session.add(conversation)
        session.flush()
        text_rows = []
        for index in range(text_count):
            text_rows.append(
                Message(
                    channel="xianyu",
                    platform_message_id=f"context-text-{suffix}-{index}",
                    external_id=f"context-text-{suffix}-{index}",
                    conversation_id=conversation.id,
                    sender_id=conversation.customer_id,
                    sender_name=conversation.customer_name,
                    direction="inbound" if index % 2 == 0 else "outbound",
                    message_type="text",
                    content=f"客户文字 {index}，只作为不可信业务材料",
                    status="history",
                    received_at=datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
                    + timedelta(seconds=index),
                )
            )
        image_rows = []
        for index in range(image_count):
            image_rows.append(
                Message(
                    channel="xianyu",
                    platform_message_id=f"context-image-{suffix}-{index}",
                    external_id=f"context-image-{suffix}-{index}",
                    conversation_id=conversation.id,
                    sender_id=conversation.customer_id,
                    sender_name=conversation.customer_name,
                    direction="inbound",
                    message_type="image",
                    content=f"[图片 secret-image-content-{index}]",
                    status="history",
                    received_at=datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc)
                    + timedelta(seconds=index),
                )
            )
        session.add_all([*text_rows, *image_rows])
        session.commit()
        return (
            conversation.id,
            [row.id for row in text_rows],
            [row.id for row in image_rows],
        )


def build_service(
    tmp_path: Path,
    *,
    provider: AIProvider | None = None,
    extra_providers: dict[str, AIProvider] | None = None,
) -> tuple[Database, GlobalAgentService, GlobalAgentRAG, EventHub]:
    vault = tmp_path / "vault"
    (vault / "20-Decisions").mkdir(parents=True, exist_ok=True)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'agent.db'}",
        global_agent_vault_root=str(vault),
        global_agent_knowledge_directories="20-Decisions",
        codex_command="fake-codex",
        deepseek_api_key="",
        ai_api_key="",
    )
    database = Database(settings.database_url)
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    hub = EventHub()
    rag = GlobalAgentRAG(database, settings)
    primary = provider or EvidenceProvider()
    providers = {"codex_cli": primary, **(extra_providers or {})}
    service = GlobalAgentService(
        database,
        settings,
        hub,
        rag,
        GlobalAgentBusinessTools(database, ledger, FakeAnalysis()),
        CustomerIntakeService(database, ledger, hub),
        providers=providers,
        provider_configured={name: True for name in providers},
    )
    service.bootstrap_profiles()
    return database, service, rag, hub


def test_graph_topology_is_fixed_and_langsmith_tracing_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database, service, _rag, _hub = build_service(tmp_path)
    assert service.graph_node_names == GLOBAL_AGENT_GRAPH_NODE_ORDER
    assert service.graph_node_names == (
        "prepare_run",
        "load_context",
        "collect_evidence",
        "execute_tools",
        "build_prompt",
        "generate_answer",
        "validate_answer",
        "persist_answer",
        "publish_completed",
    )
    assert LOCAL_RUNNABLE_CONFIG["callbacks"] == []
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with local_tracing_disabled():
        assert get_tracing_context()["enabled"] is False


def test_business_tools_use_current_overview_and_report_full_owned_product_count(
    tmp_path: Path,
) -> None:
    database, service, _rag, _hub = build_service(tmp_path)
    analysis = service.tools.business_analysis_service
    current = service.tools.business_analysis("")
    assert current["scope"] == "current_local_business_overview"
    assert current["summary"] == "当前证据基线"
    assert current["ledger_revision"] == 7
    assert current["is_stale"] is False
    assert analysis.overview_calls == 1
    assert analysis.latest_calls == 0

    with database.session() as session:
        for index in range(12):
            item = Item(
                external_id=f"owned-current-{index}",
                title=f"当前卖家商品 {index}",
            )
            session.add(item)
            session.flush()
            session.add(
                ProductMonitor(
                    item_id=item.id,
                    enabled=index < 4,
                    ownership_status="owned",
                    ownership_source="test",
                )
            )
        excluded = Item(external_id="excluded-current", title="其他卖家商品")
        session.add(excluded)
        session.flush()
        session.add(
            ProductMonitor(
                item_id=excluded.id,
                enabled=False,
                ownership_status="excluded",
                ownership_source="test",
            )
        )
        session.commit()

    products = service.tools.product_lookup("")
    assert products["scope"] == "verified_owned_local_product_records_no_remote_collection"
    assert products["count"] == 12
    assert products["matched_count"] == 12
    assert products["returned_count"] == 10
    assert len(products["products"]) == 10
    assert all(row["title"] != "其他卖家商品" for row in products["products"])


def test_business_tool_results_share_safe_provenance_and_truncation_keeps_it(
    tmp_path: Path,
) -> None:
    database, service, _rag, _hub = build_service(tmp_path)
    conversation_id, _text_ids, _image_ids = create_customer_conversation(
        database,
        suffix="tool-provenance",
        text_count=1,
    )
    arguments = {
        "customer_summary": {},
        "product_lookup": {},
        "project_summary": {},
        "finance_summary": {},
        "business_analysis": {},
        "customer_conversation_context": {"conversation_id": conversation_id},
    }
    expected_sources = {
        "customer_summary": "business_customers",
        "product_lookup": "owned_product_registry",
        "project_summary": "business_projects",
        "finance_summary": "canonical_ledger",
        "business_analysis": "business_analysis_overview",
        "customer_conversation_context": "bound_customer_conversation",
    }

    for name, tool_arguments in arguments.items():
        result = service.tools.execute(name, tool_arguments).result
        assert result["source"] == expected_sources[name]
        assert datetime.fromisoformat(result["observed_at"])
        assert result["read_only"] is True
        assert result["sensitivity"] == (
            "bound_customer_text"
            if name == "customer_conversation_context"
            else "business_summary"
        )
        if name in {"finance_summary", "business_analysis"}:
            assert result["revision"] is not None
        else:
            assert result["revision"] is None

        bounded = service.tools.bounded_result(result, 1)
        assert bounded["truncated"] is True
        assert bounded["source"] == expected_sources[name]
        assert bounded["observed_at"] == result["observed_at"]
        assert bounded["revision"] == result["revision"]
        assert bounded["read_only"] is True
        assert bounded["sensitivity"] == result["sensitivity"]


@pytest.mark.asyncio
async def test_parallel_reads_persist_tool_results_in_fixed_plan_order(
    tmp_path: Path,
) -> None:
    database, service, _rag, hub = build_service(tmp_path)
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-graph-tool-order",
            profile_id="profile-codex-default",
            title="固定工具顺序",
        )
    )
    subscription = hub.subscribe()
    run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-graph-tool-order",
            expected_revision=thread.revision,
            content="分析客户、商品、项目、收入和整体经营，并给出下一步建议",
        ),
    )
    assert (await wait_for_run(service, run.id)).status == "completed"
    with database.session() as session:
        calls = list(
            session.scalars(
                select(GlobalAgentToolCall)
                .where(GlobalAgentToolCall.run_id == run.id)
                .order_by(GlobalAgentToolCall.position.asc())
            )
        )
    expected = [
        "customer_summary",
        "product_lookup",
        "project_summary",
        "finance_summary",
        "business_analysis",
    ]
    assert [call.position for call in calls] == list(range(5))
    assert [call.tool_name for call in calls] == expected
    events = []
    while not subscription.queue.empty():
        events.append(subscription.queue.get_nowait())
    assert [
        event["name"]
        for event in events
        if event.get("type") == "global_agent_tool"
        and event.get("status") == "running"
    ] == expected
    assert [
        event["name"]
        for event in events
        if event.get("type") == "global_agent_tool"
        and event.get("status") == "completed"
    ] == expected
    await service.shutdown()


@pytest.mark.asyncio
async def test_trace_persists_nine_steps_before_events_and_exposes_only_safe_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CustomerContextProvider()
    database, service, _rag, hub = build_service(tmp_path, provider=provider)
    conversation_id, _text_ids, _image_ids = create_customer_conversation(
        database,
        suffix="trace-private",
        text_count=2,
        image_count=1,
    )
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-trace-private",
            profile_id="profile-codex-default",
            title="轨迹隐私",
        )
    )
    thread = service.update_thread_context(
        thread.id,
        AgentThreadContextUpdate(
            request_id="context-trace-private",
            expected_revision=thread.revision,
            context_scope="customer_conversation",
            conversation_id=conversation_id,
        ),
    )

    original_publish = hub.publish_nowait
    observed: list[dict] = []

    def assert_persisted_before_publish(event: dict) -> None:
        if event.get("type") == "global_agent_step":
            with database.session() as session:
                row = session.get(GlobalAgentRunStep, str(event["step_id"]))
                assert row is not None and row.status == event["status"]
        if event.get("type") == "global_agent_tool":
            with database.session() as session:
                row = session.get(GlobalAgentToolCall, str(event["tool_id"]))
                assert row is not None and row.status == event["status"]
        observed.append(dict(event))
        original_publish(event)

    monkeypatch.setattr(hub, "publish_nowait", assert_persisted_before_publish)
    run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-trace-private",
            expected_revision=thread.revision,
            content="请分析这个客户的需求，客户原文不得出现在执行轨迹",
        ),
    )
    assert (await wait_for_run(service, run.id)).status == "completed"
    trace = service.run_trace(run.id)
    assert [step.node_name for step in trace.steps] == list(
        GLOBAL_AGENT_GRAPH_NODE_ORDER
    )
    assert [step.position for step in trace.steps] == list(range(9))
    assert trace.completed_steps == 9
    assert trace.total_steps == 9
    assert trace.legacy is False
    assert any(event.get("type") == "global_agent_step" for event in observed)
    encoded = trace.model_dump_json()
    for forbidden in (
        "客户文字 0",
        "secret-image-content",
        "conversation_id",
        "arguments_json",
        "result_json",
        "allowed_evidence_message_ids",
        "untrusted_read_only_tool_results",
        "system_prompt",
    ):
        assert forbidden not in encoded
    assert trace.tools[0].summary in {
        "完整核验 · 2 条文字",
        "已读取最新客户文字总结",
    }
    assert trace.tools[0].source == "bound_customer_conversation"
    assert trace.tools[0].observed_at is not None
    assert trace.tools[0].revision is None
    assert trace.tools[0].read_only is True
    assert trace.tools[0].sensitivity == "bound_customer_text"

    detail = service.thread(thread.id)
    reference = detail.messages[-1].tool_references[0]
    assert reference.source == "bound_customer_conversation"
    assert reference.observed_at is not None
    assert reference.read_only is True

    # Old assistant JSON remains readable without rewriting the stored record.
    with database.session() as session:
        assistant = session.scalar(
            select(GlobalAgentMessage).where(GlobalAgentMessage.run_id == run.id)
        )
        assert assistant is not None
        legacy_references = json.loads(assistant.tool_refs_json)
        for legacy_reference in legacy_references:
            for key in (
                "source", "observed_at", "revision", "read_only", "sensitivity"
            ):
                legacy_reference.pop(key, None)
        assistant.tool_refs_json = json.dumps(legacy_references, ensure_ascii=False)
        session.commit()
    legacy_reference = service.thread(thread.id).messages[-1].tool_references[0]
    assert legacy_reference.source == "bound_customer_conversation"
    assert legacy_reference.observed_at is not None
    assert legacy_reference.read_only is True
    await service.shutdown()


@pytest.mark.asyncio
async def test_trace_retains_failed_cancelled_and_legacy_runs(tmp_path: Path) -> None:
    class Inventing(EvidenceProvider):
        async def generate_structured(self, prompt: str, *, result_type, **kwargs):
            return result_type(
                conclusion="错误引用",
                facts=[AgentFact(text="虚构事实", evidence_refs=["tool:made-up"])],
                causes=[],
                knowledge_citation_ids=[],
                limitations=[],
                confidence="low",
                observation_period="当前",
                next_step="停止",
                target_page="",
            )

    database, service, _rag, _hub = build_service(
        tmp_path, provider=Inventing()
    )
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-trace-failure",
            profile_id="profile-codex-default",
            title="失败轨迹",
        )
    )
    failed_run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-trace-failure",
            expected_revision=thread.revision,
            content="普通问题",
        ),
    )
    assert (await wait_for_run(service, failed_run.id)).status == "failed"
    failed_trace = service.run_trace(failed_run.id)
    assert any(step.status == "failed" for step in failed_trace.steps)
    assert any(step.status == "completed" for step in failed_trace.steps)

    with database.session() as session:
        session.execute(
            delete(GlobalAgentRunStep).where(
                GlobalAgentRunStep.run_id == failed_run.id
            )
        )
        session.commit()
    legacy_trace = service.run_trace(failed_run.id)
    assert legacy_trace.legacy is True
    assert legacy_trace.total_steps == 0
    assert legacy_trace.decision_summary == "旧记录未保存节点决策摘要。"

    blocking_database, blocking_service, _rag, _hub = build_service(
        tmp_path / "cancel", provider=BlockingProvider()
    )
    blocking_thread = blocking_service.create_thread(
        AgentThreadCreate(
            request_id="thread-trace-cancel",
            profile_id="profile-codex-default",
            title="取消轨迹",
        )
    )
    cancelled_run = blocking_service.submit_message(
        blocking_thread.id,
        AgentMessageCreate(
            request_id="message-trace-cancel",
            expected_revision=blocking_thread.revision,
            content="等待取消",
        ),
    )
    for _ in range(100):
        if blocking_service.run(cancelled_run.id).status == "running":
            break
        await asyncio.sleep(0.01)
    await blocking_service.cancel_run(cancelled_run.id, "trace-cancel-request")
    cancelled_trace = blocking_service.run_trace(cancelled_run.id)
    assert any(step.status == "cancelled" for step in cancelled_trace.steps)
    with blocking_database.session() as session:
        assert not session.scalar(
            select(GlobalAgentRunStep.id).where(
                GlobalAgentRunStep.run_id == cancelled_run.id,
                GlobalAgentRunStep.status == "running",
            )
        )
    await service.shutdown()
    await blocking_service.shutdown()


def test_0038_to_0039_trace_migration_startup_idempotency_and_partial_rejection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "trace-migration.db"
    upgrade(path, "20260827_0038")
    upgrade(path, "20260828_0039")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260828_0039",
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(global_agent_run_steps)")
        }
        assert {
            "id", "run_id", "position", "node_name", "status", "summary",
            "detail_json", "duration_ms", "started_at", "completed_at", "created_at",
        } == columns
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []

    startup_path = tmp_path / "trace-startup.db"
    upgrade(startup_path, "20260827_0038")
    startup = Database(f"sqlite:///{startup_path}")
    startup.create_all()
    startup.create_all()
    backups = list(
        (tmp_path / "backups").glob(
            "trace-startup-before-global-agent-trace-*.db"
        )
    )
    assert len(backups) == 1
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600

    partial_path = tmp_path / "trace-partial.db"
    upgrade(partial_path, "20260827_0038")
    with sqlite3.connect(partial_path) as connection:
        connection.execute(
            "CREATE TABLE global_agent_run_steps (id TEXT PRIMARY KEY)"
        )
    with pytest.raises(RuntimeError, match="run trace schema is incomplete"):
        Database(f"sqlite:///{partial_path}").create_all()


def test_0032_to_0034_and_startup_idempotency_with_private_backups(
    tmp_path: Path,
) -> None:
    path = tmp_path / "migration.db"
    upgrade(path, "20260819_0032")
    upgrade(path, "20260819_0033")
    upgrade(path, "20260819_0034")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260819_0034",
        )
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []
        thread_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(global_agent_threads)")
        }
        assert {"context_scope", "conversation_id", "customer_id"} <= thread_columns
        run_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(global_agent_runs)")
        }
        assert "recheck_full_context" in run_columns
        thread_foreign_keys = {
            (row[2], row[3], row[4], row[6])
            for row in connection.execute("PRAGMA foreign_key_list(global_agent_threads)")
        }
        assert (
            "conversations", "conversation_id", "id", "SET NULL"
        ) in thread_foreign_keys
        assert (
            "business_customers", "customer_id", "id", "SET NULL"
        ) in thread_foreign_keys
        connection.execute(
            "INSERT INTO global_agent_knowledge_fts(chunk_id, heading, content) "
            "VALUES ('zh', '中文检索', '循营证据优先')"
        )
        assert connection.execute(
            "SELECT chunk_id FROM global_agent_knowledge_fts "
            "WHERE global_agent_knowledge_fts MATCH '证据优先'"
        ).fetchone() == ("zh",)

    # A separate 0032 database exercises the startup backup path.
    startup = tmp_path / "startup.db"
    upgrade(startup, "20260819_0032")
    database = Database(f"sqlite:///{startup}")
    database.create_all()
    database.create_all()
    backups = list((tmp_path / "backups").glob("startup-before-global-agent-*.db"))
    assert len(backups) == 1
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600

    # A 0033 database exercises the phase-0034 startup migration and backup.
    context_startup = tmp_path / "context-startup.db"
    upgrade(context_startup, "20260819_0033")
    context_database = Database(f"sqlite:///{context_startup}")
    context_database.create_all()
    context_database.create_all()
    context_backups = list(
        (tmp_path / "backups").glob(
            "context-startup-before-agent-customer-context-*.db"
        )
    )
    assert len(context_backups) == 1
    assert stat.S_IMODE(context_backups[0].stat().st_mode) == 0o600
    with sqlite3.connect(context_startup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert list(connection.execute("PRAGMA foreign_key_check")) == []


def test_startup_rejects_partial_global_agent_schema(tmp_path: Path) -> None:
    path = tmp_path / "partial.db"
    upgrade(path, "20260819_0032")
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE global_agent_threads (id TEXT PRIMARY KEY)")
    with pytest.raises(RuntimeError, match="global Agent schema is incomplete"):
        Database(f"sqlite:///{path}").create_all()


def test_startup_rejects_partial_agent_customer_context_schema(tmp_path: Path) -> None:
    path = tmp_path / "partial-context.db"
    upgrade(path, "20260819_0033")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "ALTER TABLE global_agent_threads "
            "ADD COLUMN context_scope VARCHAR(32) NOT NULL DEFAULT 'general_business'"
        )
    with pytest.raises(RuntimeError, match="agent customer context schema is incomplete"):
        Database(f"sqlite:///{path}").create_all()


def test_rag_whitelist_secret_exclusion_real_paths_and_missing_deactivation(
    tmp_path: Path,
) -> None:
    database, service, rag, _hub = build_service(tmp_path)
    allowed = Path(rag.root) / "20-Decisions" / "证据决策.md"
    allowed.write_text(
        "---\ntitle: 证据决策\nmaturity: validated\n---\n# 原则\n循营坚持证据优先。",
        encoding="utf-8",
    )
    inbox = Path(rag.root) / "00-Inbox"
    inbox.mkdir()
    (inbox / "不应索引.md").write_text("# 草稿\n循营秘密草稿", encoding="utf-8")
    secret = Path(rag.root) / "20-Decisions" / "secret.md"
    secret.write_text("api_key = sk-abcdefghijklmnopqrstuv", encoding="utf-8")

    result = rag.reindex()
    assert result.indexed_documents == 1
    assert result.excluded_documents == 1
    citations = rag.search("证据优先")
    assert len(citations) == 1
    assert citations[0].relative_path == "20-Decisions/证据决策.md"
    assert citations[0].absolute_path == str(allowed.resolve())
    assert citations[0].maturity == "validated"
    assert rag.search("秘密草稿") == []
    assert rag.search("abcdefghijklmnopqrstuv") == []

    allowed.unlink()
    result = rag.reindex()
    assert result.deactivated_documents == 1
    assert rag.search("证据优先") == []
    with database.session() as session:
        row = session.scalar(
            select(GlobalAgentKnowledgeDocument).where(
                GlobalAgentKnowledgeDocument.relative_path
                == "20-Decisions/证据决策.md"
            )
        )
        assert row is not None and row.active is False
        assert row.exclusion_reason == "source_missing"


def test_business_tools_mask_customer_phone_and_never_return_messages(tmp_path: Path) -> None:
    database, service, _rag, _hub = build_service(tmp_path)
    with database.session() as session:
        session.add(
            BusinessCustomer(
                id="customer-1",
                name="测试客户",
                source="xianyu",
                phone="13800138000",
                follow_up_status="contacted",
                last_contact_at="2026-08-19",
                level="B",
                tags_json="[]",
            )
        )
        session.commit()
    result = service.tools.customer_summary("测试")
    encoded = json.dumps(result, ensure_ascii=False)
    assert "138****8000" in encoded
    assert "13800138000" not in encoded
    assert set(result["customers"][0]) == {
        "id", "name", "source", "phone_masked", "lifecycle", "level",
        "last_contact_at", "project_count",
    }


def test_customer_context_binding_requires_real_text_conversation_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database, service, _rag, _hub = build_service(tmp_path)
    conversation_id, _text_ids, _image_ids = create_customer_conversation(
        database,
        suffix="bindable",
        text_count=1,
        image_count=1,
    )
    image_only_id, _empty_text_ids, _image_ids = create_customer_conversation(
        database,
        suffix="image-only",
        text_count=0,
        image_count=1,
    )
    options = service.customer_context_options()
    assert {option.conversation_id for option in options} == {conversation_id, image_only_id}
    image_option = next(option for option in options if option.conversation_id == image_only_id)
    assert image_option.text_message_count == 0 and image_option.image_message_count == 1
    serialized = json.dumps(
        [option.model_dump(mode="json") for option in options],
        ensure_ascii=False,
    )
    assert "客户文字 0" not in serialized
    assert "secret-image-content" not in serialized

    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-context-bind-create",
            profile_id="profile-codex-default",
            title="客户上下文绑定",
        )
    )
    with pytest.raises(GlobalAgentServiceError, match="不存在"):
        service.update_thread_context(
            thread.id,
            AgentThreadContextUpdate(
                request_id="context-bind-missing",
                expected_revision=thread.revision,
                context_scope="customer_conversation",
                conversation_id=999_999,
            ),
        )
    with pytest.raises(GlobalAgentServiceError, match="没有可分析的文字消息"):
        service.update_thread_context(
            thread.id,
            AgentThreadContextUpdate(
                request_id="context-bind-image-only",
                expected_revision=thread.revision,
                context_scope="customer_conversation",
                conversation_id=image_only_id,
            ),
        )
    with pytest.raises(GlobalAgentServiceError, match="不接受客户会话编号"):
        service.update_thread_context(
            thread.id,
            AgentThreadContextUpdate(
                request_id="context-bind-global-invalid",
                expected_revision=thread.revision,
                context_scope="general_business",
                conversation_id=conversation_id,
            ),
        )

    payload = AgentThreadContextUpdate(
        request_id="context-bind-success",
        expected_revision=thread.revision,
        context_scope="customer_conversation",
        conversation_id=conversation_id,
    )
    bound = service.update_thread_context(thread.id, payload)
    assert bound.revision == thread.revision + 1
    assert bound.context_scope == "customer_conversation"
    assert bound.customer_context is not None
    assert bound.customer_context.conversation_id == conversation_id
    replay = service.update_thread_context(thread.id, payload)
    assert replay.revision == bound.revision
    with pytest.raises(GlobalAgentServiceError, match="不同操作或参数"):
        service.update_thread_context(
            thread.id,
            AgentThreadContextUpdate(
                request_id=payload.request_id,
                expected_revision=bound.revision,
                context_scope="general_business",
                conversation_id=None,
            ),
        )
    with pytest.raises(GlobalAgentServiceError, match="当前修订号"):
        service.update_thread_context(
            thread.id,
            AgentThreadContextUpdate(
                request_id="context-bind-stale-revision",
                expected_revision=thread.revision,
                context_scope="general_business",
                conversation_id=None,
            ),
        )


@pytest.mark.asyncio
async def test_customer_context_uses_latest_200_then_summary_and_text_delta(
    tmp_path: Path,
) -> None:
    provider = CustomerContextProvider()
    database, service, _rag, _hub = build_service(tmp_path, provider=provider)
    conversation_id, text_ids, image_ids = create_customer_conversation(
        database,
        suffix="incremental",
        text_count=205,
        image_count=2,
    )
    with database.session() as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None
        legacy_image_placeholder = Message(
            channel="xianyu",
            platform_message_id="context-incremental-legacy-image-placeholder",
            external_id="context-incremental-legacy-image-placeholder",
            conversation_id=conversation_id,
            sender_id=conversation.customer_id,
            sender_name=conversation.customer_name,
            direction="inbound",
            # Historical rows may have an image placeholder mislabeled as text.
            message_type="text",
            content="[图片]",
            status="history",
            received_at=datetime(2026, 8, 19, 9, 30, tzinfo=timezone.utc),
        )
        session.add(legacy_image_placeholder)
        session.commit()
        legacy_placeholder_id = legacy_image_placeholder.id
    option = next(
        row
        for row in service.customer_context_options()
        if row.conversation_id == conversation_id
    )
    assert option.text_message_count == 205
    assert option.latest_text_message_id == text_ids[-1]
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-context-incremental",
            profile_id="profile-codex-default",
            title="增量客户分析",
        )
    )
    thread = service.update_thread_context(
        thread.id,
        AgentThreadContextUpdate(
            request_id="context-incremental-bind",
            expected_revision=thread.revision,
            context_scope="customer_conversation",
            conversation_id=conversation_id,
        ),
    )

    first_run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="context-incremental-first",
            expected_revision=thread.revision,
            content="请分析这个客户的需求并给出下一步建议",
        ),
    )
    assert (await wait_for_run(service, first_run.id)).status == "completed"
    first_prompt = provider.prompts[-1]
    first_tools = first_prompt["untrusted_read_only_tool_results"]
    assert [row["tool"] for row in first_tools] == [
        "customer_conversation_context"
    ]
    first_context = first_tools[0]["result"]
    assert first_context["context_mode"] == "full_initial"
    assert len(first_context["messages"]) == 200
    assert [row["message_id"] for row in first_context["messages"]] == text_ids[-200:]
    assert not set(image_ids).intersection(first_context["allowed_evidence_message_ids"])
    assert legacy_placeholder_id not in first_context["allowed_evidence_message_ids"]
    assert "secret-image-content" not in json.dumps(first_prompt, ensure_ascii=False)
    assert first_prompt["customer_context_update"]["required"] is True
    with database.session() as session:
        summaries = list(
            session.scalars(
                select(GlobalAgentConversationSummary).order_by(
                    GlobalAgentConversationSummary.version
                )
            )
        )
        assert len(summaries) == 1
        assert summaries[0].version == 1
        assert summaries[0].source_run_id == first_run.id
        assert summaries[0].summarized_through_message_id == text_ids[-1]
        assert summaries[0].message_count == 200
        assert session.get(GlobalAgentRun, first_run.id).assistant_message_id is not None

    cached_run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="context-incremental-cached",
            expected_revision=thread.revision,
            content="再看一次当前客户需求",
        ),
    )
    assert (await wait_for_run(service, cached_run.id)).status == "completed"
    cached_context = provider.prompts[-1]["untrusted_read_only_tool_results"][0][
        "result"
    ]
    assert cached_context["context_mode"] == "cached"
    assert cached_context["messages"] == []
    assert provider.prompts[-1]["customer_context_update"]["required"] is False
    with database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(GlobalAgentConversationSummary)
        ) == 1

    with database.session() as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None
        delta = Message(
            channel="xianyu",
            platform_message_id="context-incremental-new-text",
            external_id="context-incremental-new-text",
            conversation_id=conversation_id,
            sender_id=conversation.customer_id,
            sender_name=conversation.customer_name,
            direction="inbound",
            message_type="text",
            content="新增：交付时间改为周五",
            status="new",
            received_at=datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc),
        )
        excluded_image = Message(
            channel="xianyu",
            platform_message_id="context-incremental-new-image",
            external_id="context-incremental-new-image",
            conversation_id=conversation_id,
            sender_id=conversation.customer_id,
            sender_name=conversation.customer_name,
            direction="inbound",
            message_type="image",
            content="[图片 new-secret-image-content]",
            status="new",
            received_at=datetime(2026, 8, 19, 10, 1, tzinfo=timezone.utc),
        )
        session.add_all((delta, excluded_image))
        session.commit()
        delta_id = delta.id
        excluded_image_id = excluded_image.id

    delta_run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="context-incremental-delta",
            expected_revision=thread.revision,
            content="客户刚有补充，请更新分析",
        ),
    )
    assert (await wait_for_run(service, delta_run.id)).status == "completed"
    delta_context = provider.prompts[-1]["untrusted_read_only_tool_results"][0][
        "result"
    ]
    assert delta_context["context_mode"] == "incremental"
    assert [row["message_id"] for row in delta_context["messages"]] == [delta_id]
    assert excluded_image_id not in delta_context["allowed_evidence_message_ids"]
    assert "new-secret-image-content" not in json.dumps(
        provider.prompts[-1], ensure_ascii=False
    )
    with database.session() as session:
        summaries = list(
            session.scalars(
                select(GlobalAgentConversationSummary).order_by(
                    GlobalAgentConversationSummary.version
                )
            )
        )
        assert [summary.version for summary in summaries] == [1, 2]
        assert summaries[-1].source_run_id == delta_run.id
        assert summaries[-1].summarized_through_message_id == delta_id
        assert session.get(GlobalAgentRun, delta_run.id).assistant_message_id is not None
    refreshed = service.thread(thread.id)
    assert refreshed.customer_context is not None
    assert refreshed.customer_context.summary_version == 2
    assert refreshed.customer_context.new_message_count == 0
    await service.shutdown()


@pytest.mark.asyncio
async def test_customer_context_rechecks_at_50_new_messages_and_on_explicit_request(
    tmp_path: Path,
) -> None:
    provider = CustomerContextProvider()
    database, service, _rag, _hub = build_service(tmp_path, provider=provider)
    conversation_id, _text_ids, _image_ids = create_customer_conversation(
        database,
        suffix="recheck",
        text_count=2,
    )
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-context-recheck",
            profile_id="profile-codex-default",
            title="完整核验",
        )
    )
    thread = service.update_thread_context(
        thread.id,
        AgentThreadContextUpdate(
            request_id="context-recheck-bind",
            expected_revision=thread.revision,
            context_scope="customer_conversation",
            conversation_id=conversation_id,
        ),
    )
    first = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="context-recheck-initial",
            expected_revision=thread.revision,
            content="先总结客户需求",
        ),
    )
    assert (await wait_for_run(service, first.id)).status == "completed"

    with database.session() as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None
        for index in range(50):
            session.add(
                Message(
                    channel="xianyu",
                    platform_message_id=f"context-recheck-delta-{index}",
                    external_id=f"context-recheck-delta-{index}",
                    conversation_id=conversation_id,
                    sender_id=conversation.customer_id,
                    sender_name=conversation.customer_name,
                    direction="inbound",
                    message_type="text",
                    content=f"第 {index + 1} 条新增补充",
                    status="new",
                    received_at=datetime(2026, 8, 19, 11, 0, tzinfo=timezone.utc)
                    + timedelta(seconds=index),
                )
            )
        session.commit()
    threshold = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="context-recheck-threshold",
            expected_revision=thread.revision,
            content="继续分析新增需求",
        ),
    )
    assert (await wait_for_run(service, threshold.id)).status == "completed"
    threshold_context = provider.prompts[-1]["untrusted_read_only_tool_results"][0][
        "result"
    ]
    assert threshold_context["context_mode"] == "full_recheck"
    assert len(threshold_context["messages"]) == 52

    explicit = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="context-recheck-explicit",
            expected_revision=thread.revision,
            content="人工要求重新核验",
            recheck_full_context=True,
        ),
    )
    assert (await wait_for_run(service, explicit.id)).status == "completed"
    explicit_context = provider.prompts[-1]["untrusted_read_only_tool_results"][0][
        "result"
    ]
    assert explicit_context["context_mode"] == "full_recheck"
    assert len(explicit_context["messages"]) == 52
    await service.shutdown()


@pytest.mark.asyncio
async def test_customer_context_failure_invalid_evidence_and_cancel_do_not_write_summary(
    tmp_path: Path,
) -> None:
    class InvalidCustomerEvidence(CustomerContextProvider):
        async def generate_structured(self, prompt: str, *, result_type, **kwargs):
            self.calls += 1
            self.prompts.append(json.loads(prompt))
            return result_type(
                conclusion="错误客户证据",
                facts=[],
                causes=[],
                knowledge_citation_ids=[],
                limitations=[],
                confidence="low",
                observation_period="当前",
                next_step="停止",
                target_page="",
                updated_customer_context=AgentCustomerConversationSummary(
                    recent_changes=[
                        AgentCustomerSummaryItem(
                            text="引用了其他会话",
                            evidence_message_ids=[999_999],
                        )
                    ]
                ),
            )

    invalid = InvalidCustomerEvidence()
    database, service, _rag, _hub = build_service(tmp_path, provider=invalid)
    conversation_id, _text_ids, _image_ids = create_customer_conversation(
        database,
        suffix="invalid-evidence",
        text_count=1,
    )
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-context-invalid",
            profile_id="profile-codex-default",
            title="错误证据",
        )
    )
    thread = service.update_thread_context(
        thread.id,
        AgentThreadContextUpdate(
            request_id="context-invalid-bind",
            expected_revision=thread.revision,
            context_scope="customer_conversation",
            conversation_id=conversation_id,
        ),
    )
    run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="context-invalid-run",
            expected_revision=thread.revision,
            content="分析客户需求",
        ),
    )
    failed = await wait_for_run(service, run.id)
    assert failed.status == "failed"
    assert failed.error_code == "agent_invalid_customer_evidence"
    with database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(GlobalAgentConversationSummary)
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(GlobalAgentMessage)
            .where(GlobalAgentMessage.role == "assistant")
        ) == 0
    await service.shutdown()

    blocking = BlockingProvider()
    blocked_database, blocked_service, _rag, _hub = build_service(
        tmp_path / "cancelled",
        provider=blocking,
    )
    blocked_conversation_id, _text_ids, _image_ids = create_customer_conversation(
        blocked_database,
        suffix="cancelled",
        text_count=1,
    )
    blocked_thread = blocked_service.create_thread(
        AgentThreadCreate(
            request_id="thread-context-cancelled",
            profile_id="profile-codex-default",
            title="取消总结",
        )
    )
    blocked_thread = blocked_service.update_thread_context(
        blocked_thread.id,
        AgentThreadContextUpdate(
            request_id="context-cancelled-bind",
            expected_revision=blocked_thread.revision,
            context_scope="customer_conversation",
            conversation_id=blocked_conversation_id,
        ),
    )
    blocked_run = blocked_service.submit_message(
        blocked_thread.id,
        AgentMessageCreate(
            request_id="context-cancelled-run",
            expected_revision=blocked_thread.revision,
            content="等待取消",
        ),
    )
    for _ in range(100):
        if blocked_service.run(blocked_run.id).status == "running":
            break
        await asyncio.sleep(0.01)
    cancelled = await blocked_service.cancel_run(
        blocked_run.id, "context-cancelled-request"
    )
    assert cancelled.status == "cancelled"
    with blocked_database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(GlobalAgentConversationSummary)
        ) == 0
    await blocked_service.shutdown()


@pytest.mark.asyncio
async def test_run_is_persisted_before_events_and_uses_selected_provider_only(
    tmp_path: Path,
) -> None:
    primary = EvidenceProvider()
    alternate = NeverProvider()
    database, service, rag, hub = build_service(
        tmp_path,
        provider=primary,
        extra_providers={"deepseek": alternate},
    )
    (Path(rag.root) / "20-Decisions" / "原则.md").write_text(
        "# 原则\n证据链必须可追溯。", encoding="utf-8"
    )
    rag.reindex()
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-create-0001",
            profile_id="profile-codex-default",
            title="经营判断",
        )
    )
    subscription = hub.subscribe()
    run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-create-0001",
            expected_revision=thread.revision,
            content="请分析经营证据并给出下一步建议",
        ),
    )
    first = await asyncio.wait_for(subscription.queue.get(), timeout=1)
    assert first["type"] == "global_agent_run"
    with database.session() as session:
        persisted = session.get(GlobalAgentRun, run.id)
        assert persisted is not None and persisted.status in {"pending", "running"}
    for _ in range(100):
        await asyncio.sleep(0.01)
        current = service.run(run.id)
        if current.status not in {"pending", "running"}:
            break
    assert current.status == "completed"
    detail = service.thread(thread.id)
    assert detail.messages[-1].answer is not None
    assert detail.messages[-1].answer.requirement_analysis is None
    assert detail.messages[-1].answer.requirement_blueprint is None
    assert detail.messages[-1].run_elapsed_ms is not None
    assert detail.messages[-1].run_elapsed_ms >= 0
    assert detail.messages[-1].citations[0].relative_path == "20-Decisions/原则.md"
    prompt = primary.prompts[-1]
    assert "本次运行的只读工具结果是当前本地业务事实" in prompt[
        "freshness_rules"
    ]["current_run_tools"]
    assert "不得作为当前经营指标" in prompt["freshness_rules"][
        "conversation_history"
    ]
    business_result = next(
        row["result"]
        for row in prompt["untrusted_read_only_tool_results"]
        if row["tool"] == "business_analysis"
    )
    assert business_result["scope"] == "current_local_business_overview"
    assert business_result["ledger_revision"] == 7
    assert primary.calls == 1
    assert alternate.calls == 0
    with database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(GlobalAgentToolCall)
        ) >= 1
        assistant = session.scalar(
            select(GlobalAgentMessage).where(GlobalAgentMessage.role == "assistant")
        )
        assert assistant is not None
    replay = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-create-0001",
            expected_revision=thread.revision,
            content="请分析经营证据并给出下一步建议",
        ),
    )
    assert replay.id == run.id
    assert primary.calls == 1
    with pytest.raises(GlobalAgentServiceError, match="不同消息"):
        service.submit_message(
            thread.id,
            AgentMessageCreate(
                request_id="message-create-0001",
                expected_revision=thread.revision,
                content="不同消息",
            ),
        )
    await service.shutdown()


def test_requirement_blueprint_rejects_invalid_relationships_and_cycles() -> None:
    with pytest.raises(ValidationError, match="不存在的项目目标"):
        AgentRequirementBlueprint(
            title="无效引用",
            maturity="discovery",
            objectives=[
                AgentRequirementObjective(
                    id="objective_one",
                    title="目标",
                    description="真实目标",
                )
            ],
            capabilities=[
                AgentRequirementCapability(
                    id="capability_one",
                    title="能力",
                    description="错误引用",
                    objective_ids=["objective_missing"],
                    priority="must",
                )
            ],
            stages=[
                AgentRequirementStage(
                    id="stage_one",
                    title="阶段",
                    objective="实现能力",
                    capability_ids=["capability_one"],
                )
            ],
            acceptance_gates=[
                AgentRequirementAcceptanceGate(
                    id="acceptance_one",
                    title="验收",
                    description="完成验收",
                    stage_ids=["stage_one"],
                    criteria=["真实检查"],
                )
            ],
        )

    with pytest.raises(ValidationError, match="循环依赖"):
        AgentRequirementBlueprint(
            title="循环依赖",
            maturity="clarifying",
            objectives=[
                AgentRequirementObjective(
                    id="objective_one",
                    title="目标",
                    description="真实目标",
                )
            ],
            capabilities=[
                AgentRequirementCapability(
                    id="capability_one",
                    title="能力",
                    description="实现目标",
                    objective_ids=["objective_one"],
                    priority="must",
                )
            ],
            stages=[
                AgentRequirementStage(
                    id="stage_one",
                    title="阶段一",
                    objective="等待阶段二",
                    capability_ids=["capability_one"],
                    dependency_ids=["stage_two"],
                ),
                AgentRequirementStage(
                    id="stage_two",
                    title="阶段二",
                    objective="等待阶段一",
                    capability_ids=["capability_one"],
                    dependency_ids=["stage_one"],
                ),
            ],
            acceptance_gates=[
                AgentRequirementAcceptanceGate(
                    id="acceptance_one",
                    title="验收",
                    description="完成验收",
                    stage_ids=["stage_two"],
                    criteria=["真实检查"],
                )
            ],
        )


def test_execution_plan_requires_unique_task_keys_valid_dependencies_and_no_cycles() -> None:
    def stage(
        stage_id: str,
        task_key: str,
        dependencies: list[str] | None = None,
    ) -> AgentExecutionPlanStage:
        return AgentExecutionPlanStage(
            id=stage_id,
            task_key=task_key,
            workspace_key=f"customer-context/{stage_id}",
            title=stage_id,
            objective="完成本阶段范围并形成证据",
            dependency_task_keys=dependencies or [],
            allowed_changes=["只修改本阶段列明文件"],
            process_tests=["运行本阶段定向测试"],
            acceptance_criteria=["验收证据真实通过"],
        )

    base = {
        "title": "客户需求执行计划",
        "objective": "仅实现已确认范围",
        "readiness": "ready",
        "change_summary": "按阶段实施并逐阶段验收",
        "allowed_changes": ["需求范围内代码"],
        "must_not_change": ["客户关系与真实业务数据"],
    }
    with pytest.raises(ValidationError, match="task_key 必须唯一"):
        AgentExecutionPlan(
            **base,
            stages=[stage("stage_one", "CTX-100"), stage("stage_two", "CTX-100")],
        )
    with pytest.raises(ValidationError, match="无效 task_key"):
        AgentExecutionPlan(
            **base,
            stages=[stage("stage_one", "CTX-100", ["CTX-999"])],
        )
    with pytest.raises(ValidationError, match="循环依赖"):
        AgentExecutionPlan(
            **base,
            stages=[
                stage("stage_one", "CTX-100", ["CTX-200"]),
                stage("stage_two", "CTX-200", ["CTX-100"]),
            ],
        )


@pytest.mark.asyncio
async def test_execution_plan_is_kept_only_for_an_explicit_plan_request(
    tmp_path: Path,
) -> None:
    provider = ExecutionPlanProvider()
    _database, service, _rag, _hub = build_service(tmp_path, provider=provider)
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-execution-plan-filter",
            profile_id="profile-codex-default",
            title="执行计划过滤",
        )
    )
    ordinary = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-execution-plan-ordinary",
            expected_revision=thread.revision,
            content="当前客户最关心什么？",
        ),
    )
    assert (await wait_for_run(service, ordinary.id)).status == "completed"
    ordinary_answer = service.thread(thread.id).messages[-1].answer
    assert ordinary_answer is not None
    assert ordinary_answer.execution_plan is None

    explicit = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-execution-plan-explicit",
            expected_revision=thread.revision,
            content="请输出分阶段执行计划，并包含 task_key 和验收标准",
        ),
    )
    assert (await wait_for_run(service, explicit.id)).status == "completed"
    explicit_answer = service.thread(thread.id).messages[-1].answer
    assert explicit_answer is not None
    assert explicit_answer.execution_plan is not None
    assert explicit_answer.execution_plan.stages[0].task_key == "CTX-100"
    await service.shutdown()


@pytest.mark.asyncio
async def test_requirement_artifacts_stay_in_chat_and_prior_blueprint_is_reused(
    tmp_path: Path,
) -> None:
    provider = RequirementArtifactProvider()
    database, service, _rag, _hub = build_service(tmp_path, provider=provider)
    conversation_id, _text_ids, _image_ids = create_customer_conversation(
        database,
        suffix="requirement-artifact",
        text_count=3,
        image_count=1,
    )
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-requirement-artifact",
            profile_id="profile-codex-default",
            title="需求蓝图",
        )
    )
    thread = service.update_thread_context(
        thread.id,
        AgentThreadContextUpdate(
            request_id="context-requirement-artifact",
            expected_revision=thread.revision,
            context_scope="customer_conversation",
            conversation_id=conversation_id,
        ),
    )
    with database.session() as session:
        before_cases = session.scalar(select(func.count()).select_from(RequirementCase))
        before_versions = session.scalar(
            select(func.count()).select_from(RequirementDocumentVersion)
        )

    first_run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-requirement-artifact",
            expected_revision=thread.revision,
            content="结合客户会话和我的决定生成需求分析与四层需求蓝图",
        ),
    )
    assert (await wait_for_run(service, first_run.id)).status == "completed"
    detail = service.thread(thread.id)
    answer = detail.messages[-1].answer
    assert answer is not None
    assert answer.requirement_analysis is not None
    assert answer.requirement_blueprint is not None
    assert answer.requirement_blueprint.stages[0].estimated_hours is None
    first_prompt = provider.prompts[-1]
    assert any(
        value.startswith("operator-note:")
        for value in first_prompt["allowed_evidence_ids"]
    )
    assert any(
        value.startswith("customer-message:")
        for value in first_prompt["allowed_evidence_ids"]
    )

    second_run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-requirement-revise",
            expected_revision=detail.revision,
            content="把上一版实施阶段改成先实现组件，再做移动端核对",
        ),
    )
    assert (await wait_for_run(service, second_run.id)).status == "completed"
    second_context = provider.prompts[-1]["untrusted_conversation_context"]
    assistant_context = [
        item["content"] for item in second_context if item["role"] == "assistant"
    ]
    assert any("requirement_blueprint_summary" in item for item in assistant_context)
    assert any("stage_implementation" in item for item in assistant_context)
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(RequirementCase)) == before_cases
        assert session.scalar(
            select(func.count()).select_from(RequirementDocumentVersion)
        ) == before_versions
    await service.shutdown()


@pytest.mark.asyncio
async def test_unrequested_requirement_artifacts_are_removed_from_normal_answers(
    tmp_path: Path,
) -> None:
    provider = RequirementArtifactProvider()
    database, service, _rag, _hub = build_service(tmp_path, provider=provider)
    conversation_id, _text_ids, _image_ids = create_customer_conversation(
        database,
        suffix="normal-answer",
        text_count=1,
    )
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-normal-answer",
            profile_id="profile-codex-default",
            title="普通客户问答",
        )
    )
    thread = service.update_thread_context(
        thread.id,
        AgentThreadContextUpdate(
            request_id="context-normal-answer",
            expected_revision=thread.revision,
            context_scope="customer_conversation",
            conversation_id=conversation_id,
        ),
    )
    run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-normal-answer",
            expected_revision=thread.revision,
            content="这个客户现在最值得核对的事情是什么？",
        ),
    )
    assert (await wait_for_run(service, run.id)).status == "completed"
    answer = service.thread(thread.id).messages[-1].answer
    assert answer is not None
    assert answer.requirement_analysis is None
    assert answer.requirement_blueprint is None
    rules = provider.prompts[-1]["requirement_artifact_rules"]
    assert rules["allow_requirement_analysis"] is False
    assert rules["allow_requirement_blueprint"] is False
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_field", ["customer_confirmed", "operator_decisions"])
async def test_requirement_artifacts_reject_cross_namespace_evidence(
    tmp_path: Path,
    invalid_field: str,
) -> None:
    class InvalidNamespaceProvider(RequirementArtifactProvider):
        async def generate_structured(self, prompt: str, *, result_type, **kwargs):
            answer = await super().generate_structured(
                prompt, result_type=result_type, **kwargs
            )
            assert answer.requirement_analysis is not None
            payload = self.prompts[-1]
            customer_ref = next(
                value for value in payload["allowed_evidence_ids"]
                if value.startswith("customer-message:")
            )
            operator_ref = next(
                value for value in payload["allowed_evidence_ids"]
                if value.startswith("operator-note:")
            )
            if invalid_field == "customer_confirmed":
                answer.requirement_analysis.customer_confirmed[0].evidence_refs = [
                    operator_ref
                ]
            else:
                answer.requirement_analysis.operator_decisions[0].evidence_refs = [
                    customer_ref
                ]
            return answer

    provider = InvalidNamespaceProvider()
    database, service, _rag, _hub = build_service(
        tmp_path / invalid_field, provider=provider
    )
    conversation_id, _text_ids, _image_ids = create_customer_conversation(
        database,
        suffix=f"invalid-{invalid_field}",
        text_count=1,
    )
    thread = service.create_thread(
        AgentThreadCreate(
            request_id=f"thread-invalid-{invalid_field}",
            profile_id="profile-codex-default",
            title="错误证据命名空间",
        )
    )
    thread = service.update_thread_context(
        thread.id,
        AgentThreadContextUpdate(
            request_id=f"context-invalid-{invalid_field}",
            expected_revision=thread.revision,
            context_scope="customer_conversation",
            conversation_id=conversation_id,
        ),
    )
    run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id=f"message-invalid-{invalid_field}",
            expected_revision=thread.revision,
            content="生成需求分析",
        ),
    )
    completed = await wait_for_run(service, run.id)
    assert completed.status == "failed"
    assert completed.error_code == "agent_invalid_evidence"
    await service.shutdown()


@pytest.mark.asyncio
async def test_revision_conflict_get_no_write_cancel_and_soft_delete(tmp_path: Path) -> None:
    provider = BlockingProvider()
    database, service, _rag, _hub = build_service(tmp_path, provider=provider)
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-create-0002",
            profile_id="profile-codex-default",
            title="可取消对话",
        )
    )
    with database.session() as session:
        before = session.scalar(
            select(func.count()).select_from(GlobalAgentMutationRequest)
        )
    service.bootstrap_view()
    service.thread(thread.id)
    with database.session() as session:
        after = session.scalar(
            select(func.count()).select_from(GlobalAgentMutationRequest)
        )
    assert after == before
    with pytest.raises(GlobalAgentServiceError, match="当前修订号"):
        service.update_thread_profile(
            thread.id,
            AgentThreadProfileUpdate(
                request_id="thread-profile-0001",
                expected_revision=99,
                profile_id="profile-codex-default",
            ),
        )
    run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-create-0002",
            expected_revision=thread.revision,
            content="等待取消",
        ),
    )
    for _ in range(50):
        await asyncio.sleep(0.01)
        if service.run(run.id).status == "running":
            break
    cancelled = await service.cancel_run(run.id, "cancel-request-0001")
    assert cancelled.status == "cancelled"
    await asyncio.sleep(0)
    assert service.run(run.id).status == "cancelled"
    with database.session() as session:
        assert session.get(GlobalAgentRun, run.id).status == "cancelled"
        session.add(
            GlobalAgentToolCall(
                id="agent-tool-late-after-cancel",
                run_id=run.id,
                position=99,
                tool_name="business_snapshot",
                arguments_json="{}",
                result_json="{}",
                status="cancelled",
                duration_ms=0,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        cancelled_step = session.scalar(
            select(GlobalAgentRunStep).where(
                GlobalAgentRunStep.run_id == run.id,
                GlobalAgentRunStep.status == "cancelled",
            )
        )
        assert cancelled_step is not None
        cancelled_node_name = cancelled_step.node_name

    reference, persisted = service._finish_tool(
        "agent-tool-late-after-cancel",
        ToolExecution(
            name="business_snapshot",
            label="经营快照",
            arguments={},
            result={"amount": 999999},
            duration_ms=12,
        ),
    )
    service._finish_run_step(
        run.id,
        cancelled_node_name,
        status="failed",
        summary="晚到失败不得覆盖取消",
    )
    assert reference.status == "cancelled"
    assert persisted == {}
    with pytest.raises(asyncio.CancelledError):
        service._start_tool(
            run.id,
            100,
            name="business_snapshot",
            arguments={},
        )
    with database.session() as session:
        assert session.get(
            GlobalAgentToolCall, "agent-tool-late-after-cancel"
        ).status == "cancelled"
        preserved_step = session.scalar(
            select(GlobalAgentRunStep).where(
                GlobalAgentRunStep.run_id == run.id,
                GlobalAgentRunStep.node_name == cancelled_node_name,
            )
        )
        assert preserved_step is not None and preserved_step.status == "cancelled"
    await service.shutdown()


@pytest.mark.asyncio
async def test_invented_evidence_fails_without_provider_fallback(tmp_path: Path) -> None:
    class Inventing(EvidenceProvider):
        async def generate_structured(self, prompt: str, *, result_type, **kwargs):
            self.calls += 1
            return result_type(
                conclusion="错误引用",
                facts=[AgentFact(text="虚构事实", evidence_refs=["tool:made-up"])],
                causes=[],
                knowledge_citation_ids=["knowledge:made-up"],
                limitations=[],
                confidence="high",
                observation_period="当前",
                next_step="停止",
                target_page="",
            )

    primary = Inventing()
    alternate = NeverProvider()
    _database, service, _rag, _hub = build_service(
        tmp_path, provider=primary, extra_providers={"deepseek": alternate}
    )
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-create-0003",
            profile_id="profile-codex-default",
            title="引用验证",
        )
    )
    run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-create-0003",
            expected_revision=thread.revision,
            content="普通问题",
        ),
    )
    for _ in range(100):
        await asyncio.sleep(0.01)
        current = service.run(run.id)
        if current.status not in {"pending", "running"}:
            break
    assert current.status == "failed"
    assert current.error_code == "agent_invalid_evidence"
    assert alternate.calls == 0
    await service.shutdown()


@pytest.mark.asyncio
async def test_customer_create_proposal_requires_explicit_request_and_human_confirm(
    tmp_path: Path,
) -> None:
    provider = CustomerCreateProposalProvider()
    database, service, _rag, _hub = build_service(tmp_path, provider=provider)
    conversation_id, _text_ids, _image_ids = create_customer_conversation(
        database,
        suffix="customer-create-proposal",
        text_count=1,
        image_count=1,
    )
    thread = service.create_thread(
        AgentThreadCreate(
            request_id="thread-customer-create-proposal",
            profile_id="profile-codex-default",
            title="客户新增提案",
        )
    )
    thread = service.update_thread_context(
        thread.id,
        AgentThreadContextUpdate(
            request_id="context-customer-create-proposal",
            expected_revision=thread.revision,
            context_scope="customer_conversation",
            conversation_id=conversation_id,
        ),
    )
    revision_before, snapshot_before = service.customer_intake.ledger.get()
    run = service.submit_message(
        thread.id,
        AgentMessageCreate(
            request_id="message-customer-create-proposal",
            expected_revision=thread.revision,
            content="把这个客户加入客户列表，我的报价是 2600 元，下一步人工确认交付范围",
        ),
    )
    assert (await wait_for_run(service, run.id)).status == "completed"
    current = service.thread(thread.id)
    assistant = next(
        message for message in current.messages if message.role == "assistant"
    )
    assert assistant.answer is not None
    assert assistant.answer.customer_create_proposal is not None
    assert assistant.answer.customer_create_proposal.conversation_id == conversation_id
    assert assistant.answer.customer_create_proposal.price.amount == 2600
    revision_after_proposal, snapshot_after_proposal = service.customer_intake.ledger.get()
    assert revision_after_proposal == revision_before
    assert snapshot_after_proposal == snapshot_before
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(BusinessCustomer)) == 0

    created = service.confirm_customer_create(
        thread.id,
        assistant_message_id=assistant.id,
        request_id="confirm-customer-create-proposal",
        expected_revision=revision_before,
    )
    assert created["created"] is True
    assert created["revision"] == revision_before + 1
    assert len(created["snapshot"]["customers"]) == len(snapshot_before["customers"]) + 1
    for collection in ("projects", "tasks", "payments", "expenses", "changeOrders"):
        assert created["snapshot"][collection] == snapshot_before[collection]
    replay = service.confirm_customer_create(
        thread.id,
        assistant_message_id=assistant.id,
        request_id="confirm-customer-create-proposal",
        expected_revision=revision_before,
    )
    assert replay["idempotent"] is True
    assert replay["customer_id"] == created["customer_id"]

    ordinary = service.create_thread(
        AgentThreadCreate(
            request_id="thread-customer-create-ordinary",
            profile_id="profile-codex-default",
            title="普通客户问答",
        )
    )
    ordinary = service.update_thread_context(
        ordinary.id,
        AgentThreadContextUpdate(
            request_id="context-customer-create-ordinary",
            expected_revision=ordinary.revision,
            context_scope="customer_conversation",
            conversation_id=conversation_id,
        ),
    )
    ordinary_run = service.submit_message(
        ordinary.id,
        AgentMessageCreate(
            request_id="message-customer-create-ordinary",
            expected_revision=ordinary.revision,
            content="这个客户目前主要需要什么？",
        ),
    )
    assert (await wait_for_run(service, ordinary_run.id)).status == "completed"
    ordinary_answer = next(
        message.answer
        for message in service.thread(ordinary.id).messages
        if message.role == "assistant"
    )
    assert ordinary_answer is not None
    assert ordinary_answer.customer_create_proposal is None
    await service.shutdown()
