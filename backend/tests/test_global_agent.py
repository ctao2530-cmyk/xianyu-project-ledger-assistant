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
from sqlalchemy import func, select

from backend.app.agents.global_agent import (
    GlobalAgentBusinessTools,
    GlobalAgentRAG,
    GlobalAgentService,
    GlobalAgentServiceError,
)
from backend.app.ai.base import AIProvider, AIProviderError, ProviderHealth
from backend.app.config import Settings, get_settings
from backend.app.database import Database
from backend.app.global_agent_schemas import (
    AgentCustomerConversationSummary,
    AgentCustomerCreateProposal,
    AgentCustomerPriceProposal,
    AgentCustomerProposalText,
    AgentCustomerSummaryItem,
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
    GlobalAgentToolCall,
    Message,
    RequirementCase,
    RequirementDocumentVersion,
)
from backend.app.services.event_hub import EventHub
from backend.app.services.customer_intake import CustomerIntakeService


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
    def model_dump(self, *, mode: str = "json") -> dict:
        return {
            "summary": "当前证据基线",
            "metrics": {},
            "insights": [],
            "recommendations": [],
            "data_gaps": ["仍需真实数据"],
            "period": {"timezone": "Asia/Shanghai"},
            "generated_at": "2026-08-19T00:00:00Z",
        }


class FakeAnalysis:
    def latest_or_overview(self) -> FakeOverview:
        return FakeOverview()


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
    assert [option.conversation_id for option in options] == [conversation_id]
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
    assert detail.messages[-1].citations[0].relative_path == "20-Decisions/原则.md"
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
