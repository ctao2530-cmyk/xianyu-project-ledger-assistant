from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.app.ai import (
    AIInput,
    AIModelOption,
    AIModelSelection,
    AIProvider,
    AIResult,
    ProviderHealth,
)
from backend.app.ai.requirements import RequirementAnalysisResult
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.models import (
    Conversation,
    Item,
    Message,
    RequirementAnalysisTask,
    RequirementDocumentVersion,
)
from backend.app.services.notifier import MacOSNotifier
from backend.app.services.requirements import RequirementAnalysisService


RESULT = {
    "document_title": "企业官网建设需求文档",
    "readiness": "needs_clarification",
    "executive_summary": "客户需要搭建一个用于企业展示的响应式网站，当前已确认基础页面范围。",
    "confirmed_requirements": ["建设企业展示官网", "支持手机端访问"],
    "inferred_requirements": ["可能需要内容管理能力"],
    "scope_items": ["首页", "关于我们", "联系页"],
    "out_of_scope": ["在线支付"],
    "deliverables": ["可部署的网站源码", "使用说明"],
    "constraints": ["不得使用未授权素材"],
    "assumptions": ["客户提供品牌文案与图片"],
    "open_questions": ["是否需要后台内容管理？"],
    "risks": ["品牌素材未准备可能影响实施"],
    "acceptance_criteria": ["主流桌面和手机浏览器布局正常"],
    "stages": [
        {
            "sequence": 1,
            "title": "需求确认",
            "objective": "确认页面范围、素材和验收口径。",
            "work_items": ["整理页面清单", "收集品牌素材"],
            "deliverables": ["确认后的需求清单"],
            "acceptance_criteria": ["所有待确认问题获得客户回复"],
            "dependencies": [],
        },
        {
            "sequence": 2,
            "title": "设计与开发",
            "objective": "完成已确认页面的响应式实现。",
            "work_items": ["建立视觉样式", "实现页面"],
            "deliverables": ["可运行网站"],
            "acceptance_criteria": ["页面与确认范围一致"],
            "dependencies": ["阶段 1 需求已确认"],
        },
    ],
    "change_summary": "首次从客户对话生成需求文档。",
}


class RequirementProvider(AIProvider):
    name = "codex_cli"

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []
        self.selections: list[AIModelSelection | None] = []

    async def healthcheck(self, *, validate_execution: bool = True) -> ProviderHealth:
        return ProviderHealth(status="connected")

    async def available_models(self, *, refresh: bool = False) -> list[AIModelOption]:
        return [
            AIModelOption(
                model="gpt-5.6-sol",
                display_name="GPT-5.6-Sol",
                default_reasoning_effort="low",
                supported_reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
            )
        ]

    async def generate(
        self, payload: AIInput, *, task_key: str, model_selection=None
    ) -> AIResult:
        raise AssertionError("reply generation is not used")

    async def generate_structured(
        self,
        prompt: str,
        *,
        result_type,
        task_key: str,
        model_selection: AIModelSelection | None = None,
        timeout: float | None = None,
    ):
        self.prompts.append(prompt)
        self.selections.append(model_selection)
        payload = dict(RESULT)
        if len(self.prompts) > 1:
            payload["change_summary"] = "根据客户补充，新增了新闻页需求。"
            payload["scope_items"] = [*payload["scope_items"], "新闻页"]
        return result_type.model_validate(payload)


def seed_conversation(database: Database) -> int:
    with database.session() as session:
        item = Item(
            external_id="item-requirement",
            title="企业网站开发",
            price="未确认",
            description="定制化网站开发",
        )
        conversation = Conversation(
            external_id="conversation-requirement",
            customer_id="buyer-requirement",
            customer_name="测试客户",
            item=item,
        )
        session.add(conversation)
        session.flush()
        session.add_all(
            [
                Message(
                    external_id="requirement-message-1",
                    conversation_id=conversation.id,
                    sender_id="buyer-requirement",
                    sender_name="测试客户",
                    direction="inbound",
                    content="想做一个企业官网，要适配手机。",
                    received_at=datetime.now(timezone.utc),
                ),
                Message(
                    external_id="requirement-message-2",
                    conversation_id=conversation.id,
                    sender_id="seller",
                    sender_name="我",
                    direction="outbound",
                    content="可以，请把需要的页面和参考网站发我。",
                    status="sent",
                    received_at=datetime.now(timezone.utc),
                ),
            ]
        )
        session.commit()
        return conversation.id


async def wait_for_task(database: Database, task_id: int) -> RequirementAnalysisTask:
    for _ in range(100):
        with database.session() as session:
            task = session.get(RequirementAnalysisTask, task_id)
            if task and task.status in {"completed", "failed"}:
                return task
        await asyncio.sleep(0.02)
    raise AssertionError("requirement task did not complete")


@pytest.mark.asyncio
async def test_requirement_analysis_versions_revision_and_progress(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'requirements.db'}")
    database.create_all()
    conversation_id = seed_conversation(database)
    provider = RequirementProvider()
    service = RequirementAnalysisService(
        database,
        provider,
        Settings(_env_file=None),
        MacOSNotifier(False),
    )
    await service.start()
    try:
        first_task = await service.enqueue(conversation_id)
        assert (await wait_for_task(database, first_task.id)).status == "completed"

        revision = await service.enqueue(
            conversation_id,
            change_request="客户补充：还需要新闻页。",
        )
        assert (await wait_for_task(database, revision.id)).status == "completed"
    finally:
        await service.stop()

    with database.session() as session:
        versions = list(
            session.scalars(
                select(RequirementDocumentVersion).order_by(
                    RequirementDocumentVersion.version.asc()
                )
            )
        )
    assert [version.version for version in versions] == [1, 2]
    assert "新闻页" in versions[1].content_markdown
    assert "客户补充：还需要新闻页" in provider.prompts[1]
    assert provider.selections == [
        AIModelSelection(model="gpt-5.6-sol", reasoning_effort="max"),
        AIModelSelection(model="gpt-5.6-sol", reasoning_effort="max"),
    ]

    updated = service.set_stage_progress(versions[1].id, 1, "in_progress")
    assert RequirementAnalysisService._load_progress(updated.stage_progress_json)["1"] == "in_progress"


def test_requirement_result_rejects_non_contiguous_stages() -> None:
    payload = dict(RESULT)
    payload["stages"] = [dict(RESULT["stages"][0], sequence=2)]
    with pytest.raises(ValueError, match="sequence"):
        RequirementAnalysisResult.model_validate(payload)
