from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.app.agents import SalesAgent, SalesAgentError, SalesAnalysisResult
from backend.app.ai import AIInput, AIProvider, AIProviderError, AIResult, ProviderHealth
from backend.app.database import Database
from backend.app.ledger import LedgerService, default_snapshot
from backend.app.models import (
    Conversation,
    CustomerChannelIdentity,
    CustomerMemory,
    Draft,
    Message,
    QuoteProposal,
    SalesAnalysisRun,
    SalesLead,
)


class RecordingSalesProvider(AIProvider):
    name = "sales_test"

    def __init__(self, *, fail: bool = False, name: str = "sales_test") -> None:
        super().__init__()
        self.name = name
        self.fail = fail
        self.prompts: list[str] = []

    async def healthcheck(self, *, validate_execution: bool = True) -> ProviderHealth:
        self.health = ProviderHealth(status="connected")
        return self.health

    async def generate(
        self, payload: AIInput, *, task_key: str, model_selection=None
    ) -> AIResult:
        raise NotImplementedError

    async def generate_structured(
        self,
        prompt: str,
        *,
        result_type,
        task_key: str,
        model_selection=None,
        timeout: float | None = None,
    ):
        self.prompts.append(prompt)
        if self.fail:
            raise AIProviderError(
                "sales_provider_timeout",
                "销售模型响应超时，请重试",
                retryable=True,
            )
        return result_type.model_validate(
            {
                "customer_type": "意向客户",
                "need_type": "小程序开发咨询",
                "purchase_probability": 72,
                "stage": "需求沟通",
                "customer_profile": "已有历史项目，当前正在确认新需求范围。",
                "need_signals": ["询问订单管理功能", "希望确认交付方式"],
                "sales_strategy": "先确认核心角色、流程与交付时间，再进入方案评估。",
                "next_action": "询问首期必须上线的三个核心功能",
                "recommended_reply": "可以，先确认一下首期必须上线的三个核心功能、使用角色和期望交付时间，我再帮你把范围梳理清楚。",
                "evidence_refs": [],
                "risk_flags": [],
                "tools_used": [],
                "needs_human_confirmation": True,
            }
        )


def build_sales_fixture(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'sales-agent.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    snapshot = default_snapshot()
    snapshot["customers"] = [
        {
            "id": "customer-history",
            "name": "历史客户",
            "source": "xianyu",
            "phone": "",
            "followUpStatus": "contacted",
            "lastContactAt": "2026-08-07T10:00:00Z",
            "level": "B",
            "tags": ["老客户"],
        }
    ]
    snapshot["projects"] = [
        {
            "id": "project-history",
            "name": "订单管理小程序",
            "customerId": "customer-history",
            "projectKind": "client",
            "totalAmount": 8000,
            "startDate": "2026-07-01",
            "dueDate": "2026-07-20",
            "progress": 100,
            "status": "completed",
            "type": "小程序开发",
            "estimatedHours": 40,
            "accent": "blue",
        }
    ]
    snapshot["payments"] = [
        {
            "id": "payment-history",
            "projectId": "project-history",
            "customerId": "customer-history",
            "amount": 3000,
            "type": "deposit",
            "status": "confirmed",
            "paidAt": "2026-07-01",
            "dueAt": "2026-07-01",
            "notes": "历史到账",
        }
    ]
    ledger.save(snapshot, 0)
    with database.session() as session:
        old_conversation = Conversation(
            external_id="old-conversation",
            customer_id="old-buyer",
            customer_name="旧客户",
        )
        current = Conversation(
            external_id="current-conversation",
            customer_id="buyer-1",
            customer_name="历史客户",
        )
        session.add_all([old_conversation, current])
        session.flush()
        session.add(
            CustomerChannelIdentity(
                id="identity-current",
                customer_id="customer-history",
                channel="xianyu",
                external_customer_id="buyer-1",
                conversation_id=current.id,
                display_name="历史客户",
            )
        )
        historical_lead = SalesLead(
            id="lead-history",
            conversation_id=old_conversation.id,
            customer_id="customer-history",
            status="won",
        )
        session.add(historical_lead)
        session.flush()
        session.add(
            QuoteProposal(
                id="quote-history",
                lead_id=historical_lead.id,
                version=1,
                status="confirmed",
                hourly_rate=200,
                risk_buffer=0.15,
                estimated_hours=40,
                total_amount=9200,
                stages_json="[]",
                payment_plan_json="[]",
                risks_json="[]",
            )
        )
        session.add(
            Message(
                channel="xianyu",
                platform_message_id="previous-seller-message",
                external_id="previous-seller-message",
                conversation_id=current.id,
                sender_id="seller",
                sender_name="我",
                direction="outbound",
                content="可以，先说一下主要流程。",
                status="sent",
                received_at=datetime.now(timezone.utc),
            )
        )
        message = Message(
            channel="xianyu",
            platform_message_id="current-message",
            external_id="current-message",
            conversation_id=current.id,
            sender_id="buyer-1",
            sender_name="历史客户",
            direction="inbound",
            content="想做一个订单管理小程序，先确认核心功能和交付方式。",
            status="new",
            received_at=datetime.now(timezone.utc),
        )
        session.add(message)
        session.commit()
        return database, ledger, current.id, message.id


@pytest.mark.asyncio
async def test_sales_agent_calls_business_tools_and_requires_confirmation(tmp_path) -> None:
    database, ledger, conversation_id, _message_id = build_sales_fixture(tmp_path)
    provider = RecordingSalesProvider()
    agent = SalesAgent(database, ledger, provider, timeout_seconds=2)

    record = await agent.analyze_conversation(conversation_id)

    assert record.status == "completed"
    assert record.result is not None
    assert record.result.purchase_probability == 72
    assert record.result.tools_used == [
        "customer_history",
        "similar_projects",
        "pricing_history",
    ]
    assert record.context_summary.message_count == 2
    assert record.context_summary.project_count == 1
    assert record.context_summary.quote_count == 1
    assert record.context_summary.confirmed_revenue == 3000
    prompt = provider.prompts[-1]
    assert '"customer_history"' in prompt
    assert '"similar_projects"' in prompt
    assert '"pricing_history"' in prompt
    assert '"confirmed_revenue": 3000.0' in prompt

    with database.session() as session:
        assert session.scalar(
            select(SalesLead).where(SalesLead.conversation_id == conversation_id)
        ) is None
        assert session.scalar(select(CustomerMemory)) is None
        assert session.scalar(select(Draft)) is None


@pytest.mark.asyncio
async def test_confirmed_sales_memory_is_reused_on_next_analysis(tmp_path) -> None:
    database, ledger, conversation_id, _message_id = build_sales_fixture(tmp_path)
    provider = RecordingSalesProvider()
    agent = SalesAgent(database, ledger, provider, timeout_seconds=2)
    first = await agent.analyze_conversation(conversation_id)

    confirmation = agent.confirm_analysis(first.id)

    assert confirmation.idempotent is False
    assert confirmation.customer_id == "customer-history"
    with database.session() as session:
        lead = session.scalar(
            select(SalesLead).where(SalesLead.conversation_id == conversation_id)
        )
        memory = session.scalar(select(CustomerMemory))
        assert lead is not None and lead.customer_id == "customer-history"
        assert memory is not None
        assert memory.version == 1
        assert memory.follow_up_status == "需求沟通"

        follow_up = Message(
            channel="xianyu",
            platform_message_id="follow-up-message",
            external_id="follow-up-message",
            conversation_id=conversation_id,
            sender_id="buyer-1",
            sender_name="历史客户",
            direction="inbound",
            content="主要是管理员、销售和仓库三种角色。",
            status="new",
            received_at=datetime.now(timezone.utc),
        )
        session.add(follow_up)
        session.commit()

    second = await agent.analyze_conversation(conversation_id)
    assert second.context_summary.memory_version == 1
    assert '"latest_version": 1' in provider.prompts[-1]
    assert "先确认核心角色、流程与交付时间" in provider.prompts[-1]

    revision_before, _ = ledger.get()
    repeated = agent.confirm_analysis(first.id)
    revision_after, _ = ledger.get()
    assert repeated.idempotent is True
    assert revision_after == revision_before


@pytest.mark.asyncio
async def test_sales_provider_failure_is_visible_and_writes_no_business_data(tmp_path) -> None:
    database, ledger, conversation_id, _message_id = build_sales_fixture(tmp_path)
    agent = SalesAgent(
        database,
        ledger,
        RecordingSalesProvider(fail=True),
        timeout_seconds=2,
    )

    with pytest.raises(SalesAgentError) as raised:
        await agent.analyze_conversation(conversation_id)

    assert raised.value.code == "sales_provider_timeout"
    with database.session() as session:
        run = session.scalar(select(SalesAnalysisRun))
        assert run is not None
        assert run.status == "failed"
        assert run.error_message == "销售模型响应超时，请重试"
        assert session.scalar(
            select(SalesLead).where(SalesLead.conversation_id == conversation_id)
        ) is None
        assert session.scalar(select(CustomerMemory)) is None


@pytest.mark.asyncio
async def test_sales_agent_uses_explicit_provider_without_silent_fallback(tmp_path) -> None:
    database, ledger, conversation_id, _message_id = build_sales_fixture(tmp_path)
    fast = RecordingSalesProvider(fail=True, name="deepseek")
    deep = RecordingSalesProvider(name="codex_cli")
    agent = SalesAgent(
        database,
        ledger,
        fast,
        providers={"deepseek": fast, "codex_cli": deep},
        timeout_seconds=2,
    )

    record = await agent.analyze_conversation(
        conversation_id,
        refresh=True,
        provider_name="codex_cli",
    )

    assert record.provider == "codex_cli"
    assert len(deep.prompts) == 1
    assert fast.prompts == []


def test_sales_result_rejects_unsupported_business_actions() -> None:
    with pytest.raises(ValueError):
        SalesAnalysisResult.model_validate(
            {
                "customer_type": "潜在客户",
                "need_type": "网站开发",
                "purchase_probability": 60,
                "stage": "需求沟通",
                "customer_profile": "首次咨询",
                "need_signals": [],
                "sales_strategy": "继续澄清",
                "next_action": "询问范围",
                "recommended_reply": "请补充范围和交付时间，我再进一步确认。",
                "evidence_refs": [],
                "risk_flags": [],
                "tools_used": ["delete_customer"],
                "needs_human_confirmation": True,
            }
        )
