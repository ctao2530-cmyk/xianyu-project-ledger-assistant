from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.database import Database
from backend.app.models import BusinessCustomer, Conversation, Message
from backend.app.requirement_blueprints import RequirementBlueprintV2
from backend.app.services.requirement_exchange import RequirementExchangeError, RequirementExchangeService


def blueprint() -> dict:
    return {
        "schema_version": "2.0",
        "title": "订单管理系统",
        "project_type": "Web 管理系统",
        "readiness": "clarifying",
        "change_summary": "根据最新对话整理首版范围",
        "objectives": [{"id": "obj-order", "title": "统一订单流程", "description": "减少人工表格和重复录入", "evidence_refs": ["ev-1"]}],
        "capabilities": [{"id": "cap-order", "title": "订单管理", "description": "创建、查询和更新订单", "objective_ids": ["obj-order"], "priority": "must", "evidence_refs": ["ev-1"]}],
        "stages": [{"id": "stage-build", "title": "核心开发", "objective": "完成订单闭环", "implementation": "使用前后端分层和版本化数据库迁移", "estimated_hours": 36, "capability_ids": ["cap-order"], "dependency_ids": [], "work_items": ["订单模型", "列表与详情"], "deliverables": ["源代码", "部署包"], "evidence_refs": ["ev-1"]}],
        "acceptance_gates": [{"id": "gate-order", "title": "订单验收", "description": "核心流程可操作", "stage_ids": ["stage-build"], "criteria": ["可以创建并查询订单"], "evidence_refs": ["ev-1"]}],
        "out_of_scope": ["自动支付"],
        "assumptions": ["客户提供测试账号"],
        "open_questions": ["是否需要批量导入"],
        "risks": [{"id": "risk-scope", "title": "范围变化", "description": "字段仍可能变化", "severity": "medium", "mitigation": "开发前冻结字段", "evidence_refs": ["ev-1"]}],
        "evidence_refs": [{"id": "ev-1", "message_number": 1, "quote": "想做一个订单管理系统"}],
    }


def test_blueprint_rejects_broken_and_cyclic_references() -> None:
    broken = blueprint()
    broken["capabilities"][0]["objective_ids"] = ["missing"]
    with pytest.raises(ValidationError):
        RequirementBlueprintV2.model_validate(broken)

    cyclic = blueprint()
    cyclic["stages"].append({
        "id": "stage-test", "title": "测试阶段", "objective": "完成测试", "implementation": "执行回归测试", "estimated_hours": 8,
        "capability_ids": ["cap-order"], "dependency_ids": ["stage-build"], "work_items": ["回归"], "deliverables": ["测试报告"], "evidence_refs": [],
    })
    cyclic["stages"][0]["dependency_ids"] = ["stage-test"]
    with pytest.raises(ValidationError):
        RequirementBlueprintV2.model_validate(cyclic)


def test_requirement_exchange_redacts_and_commits_idempotently(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'requirements.db'}")
    database.create_all()
    with database.session() as session:
        customer = BusinessCustomer(id="customer-1", name="测试客户")
        conversation = Conversation(
            channel="xianyu",
            external_id="conversation-1",
            customer_id="external-customer",
            customer_name="客户 13800138000",
        )
        session.add_all([customer, conversation])
        session.flush()
        session.add(
            Message(
                channel="xianyu",
                platform_message_id="message-1",
                external_id="message-1",
                conversation_id=conversation.id,
                sender_id="external-customer",
                sender_name="客户",
                direction="inbound",
                message_type="text",
                content="想做订单系统，邮箱 demo@example.com，微信 vxexample88",
                status="new",
                received_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        conversation_id = conversation.id

    service = RequirementExchangeService(database)
    exported = service.export_conversation(conversation_id)
    assert exported["redaction_count"] == 3
    assert exported["filename"].endswith(".md")
    assert "# 客户需求分析材料" in exported["analysis_document"]
    assert "给 GPT 的固定提示词" in exported["analysis_document"]
    assert "客户对话记录（待分析资料）" in exported["analysis_document"]
    assert "最终只输出一个符合文末 JSON Schema 的 JSON 对象" in exported["analysis_document"]
    assert "13800138000" not in exported["prompt"]
    assert "demo@example.com" not in exported["prompt"]
    assert "vxexample88" not in exported["prompt"]
    assert "13800138000" not in exported["analysis_document"]
    assert "demo@example.com" not in exported["analysis_document"]
    assert "vxexample88" not in exported["analysis_document"]

    preview = service.preview_import(
        conversation_id=conversation_id,
        customer_id="customer-1",
        case_id=None,
        case_title="订单系统需求",
        source_label="GPT 人工导入",
        document=blueprint(),
    )
    result = service.commit_import(preview["token"], preview["expected_version"])
    again = service.commit_import(preview["token"], preview["expected_version"])
    assert result["version"] == 1
    assert result["case"]["estimated_hours"] == 36
    assert again["idempotent"] is True


def test_requirement_import_detects_version_conflict(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'conflict.db'}")
    database.create_all()
    with database.session() as session:
        session.add(BusinessCustomer(id="customer-1", name="测试客户"))
        conversation = Conversation(channel="xianyu", external_id="conversation-1", customer_id="external", customer_name="客户")
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id
    service = RequirementExchangeService(database)
    preview = service.preview_import(conversation_id=conversation_id, customer_id="customer-1", case_id=None, case_title="需求", source_label="GPT", document=blueprint())
    with pytest.raises(RequirementExchangeError) as exc_info:
        service.commit_import(preview["token"], 1)
    assert exc_info.value.code == "version_conflict"
