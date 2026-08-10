from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.api import requirement_version_view, router
from backend.app.database import Database
from backend.app.ledger import LedgerService, RevisionConflict, default_snapshot
from backend.app.ledger_api import _raise_exchange_error
from backend.app.models import (
    BusinessCustomer,
    Conversation,
    CustomerChannelIdentity,
    CustomerItemLink,
    Item,
    Message,
    RequirementCase,
    RequirementCaseSource,
    RequirementDocumentVersion,
)
from backend.app.requirement_blueprints import RequirementBlueprintV2
from backend.app.schema_migrations import backfill_requirement_cases
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


@pytest.mark.parametrize(
    "code",
    [
        "customer_mismatch",
        "customer_relationship_conflict",
        "case_item_mismatch",
        "item_changed",
    ],
)
def test_requirement_relationship_changes_are_http_conflicts(code: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _raise_exchange_error(RequirementExchangeError(code, "关系已经变化"))
    assert exc_info.value.status_code == 409


def test_requirement_exchange_redacts_and_commits_idempotently(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'requirements.db'}")
    database.create_all()
    with database.session() as session:
        customer = BusinessCustomer(id="customer-1", name="测试客户")
        item = Item(external_id="item-order", title="订单系统开发")
        session.add_all([customer, item])
        session.flush()
        conversation = Conversation(
            channel="xianyu",
            external_id="conversation-1",
            customer_id="external-customer",
            customer_name="客户 13800138000",
            item_id=item.id,
        )
        session.add(conversation)
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
    assert result["case"]["item_external_id"] == "item-order"
    assert result["case"]["item_title"] == "订单系统开发"
    assert again["idempotent"] is True

    with database.session() as session:
        version = session.scalar(select(RequirementDocumentVersion))
        links = list(session.scalars(select(CustomerItemLink)))
        identity = session.scalar(select(CustomerChannelIdentity))
        assert version is not None
        assert len(links) == 1
        assert links[0].customer_id == "customer-1"
        assert links[0].item_id == result["case"]["item_id"]
        assert identity is not None
        assert identity.customer_id == "customer-1"
        view = requirement_version_view(version)

    assert view.document.schema_version == "2.0"
    assert view.document.title == "订单管理系统"


def test_conversation_detail_resolves_customer_from_requirement_case_source(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'case-customer.db'}")
    database.create_all()
    with database.session() as session:
        customer = BusinessCustomer(id="customer-case", name="案例客户")
        item = Item(external_id="item-case", title="案例商品")
        session.add_all([customer, item])
        session.flush()
        conversation = Conversation(
            channel="xianyu",
            external_id="conversation-case",
            customer_id="external-case",
            customer_name="案例客户",
            item_id=item.id,
        )
        session.add(conversation)
        session.flush()
        requirement_case = RequirementCase(
            id="case-customer-link",
            customer_id=customer.id,
            item_id=item.id,
            title="案例需求",
            current_version=0,
        )
        session.add(requirement_case)
        session.flush()
        session.add(
            RequirementCaseSource(
                id="case-customer-source",
                case_id=requirement_case.id,
                conversation_id=conversation.id,
            )
        )
        session.commit()
        conversation_id = conversation.id

    exchange = RequirementExchangeService(database)
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(
        database=database,
        requirement_exchange=exchange,
    )
    response = TestClient(app).get(f"/api/conversations/{conversation_id}")

    assert response.status_code == 200
    assert response.json()["linked_customer_id"] == "customer-case"
    assert response.json()["item"]["external_id"] == "item-case"


def test_requirement_import_rejects_conflicting_existing_customer_sources(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'customer-source-conflict.db'}")
    database.create_all()
    with database.session() as session:
        customer_one = BusinessCustomer(id="customer-1", name="客户一")
        customer_two = BusinessCustomer(id="customer-2", name="客户二")
        item = Item(external_id="item-conflict-source", title="冲突商品")
        session.add_all([customer_one, customer_two, item])
        session.flush()
        conversation = Conversation(
            channel="xianyu",
            external_id="conversation-conflict-source",
            customer_id="external-conflict-source",
            customer_name="冲突客户",
            item_id=item.id,
        )
        session.add(conversation)
        session.flush()
        cases = [
            RequirementCase(id="case-source-one", customer_id=customer_one.id, item_id=item.id, title="需求一", current_version=0),
            RequirementCase(id="case-source-two", customer_id=customer_two.id, item_id=item.id, title="需求二", current_version=0),
        ]
        session.add_all(cases)
        session.flush()
        session.add_all([
            RequirementCaseSource(id="source-one", case_id=cases[0].id, conversation_id=conversation.id),
            RequirementCaseSource(id="source-two", case_id=cases[1].id, conversation_id=conversation.id),
        ])
        session.commit()
        conversation_id = conversation.id

    service = RequirementExchangeService(database)
    with pytest.raises(RequirementExchangeError) as exc_info:
        service.preview_import(
            conversation_id=conversation_id,
            customer_id="customer-1",
            case_id="case-source-one",
            case_title=None,
            source_label="GPT",
            document=blueprint(),
        )
    assert exc_info.value.code == "customer_relationship_conflict"


def test_requirement_import_detects_version_conflict(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'conflict.db'}")
    database.create_all()
    with database.session() as session:
        customer = BusinessCustomer(id="customer-1", name="测试客户")
        item = Item(external_id="item-conflict", title="冲突测试商品")
        session.add_all([customer, item])
        session.flush()
        conversation = Conversation(channel="xianyu", external_id="conversation-1", customer_id="external", customer_name="客户", item_id=item.id)
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id
    service = RequirementExchangeService(database)
    preview = service.preview_import(conversation_id=conversation_id, customer_id="customer-1", case_id=None, case_title="需求", source_label="GPT", document=blueprint())
    with pytest.raises(RequirementExchangeError) as exc_info:
        service.commit_import(preview["token"], 1)
    assert exc_info.value.code == "version_conflict"


def test_requirement_import_rejects_customer_and_item_mismatches(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'relationship-conflicts.db'}")
    database.create_all()
    with database.session() as session:
        customer_one = BusinessCustomer(id="customer-1", name="客户一")
        customer_two = BusinessCustomer(id="customer-2", name="客户二")
        item_one = Item(external_id="item-one", title="商品一")
        item_two = Item(external_id="item-two", title="商品二")
        session.add_all([customer_one, customer_two, item_one, item_two])
        session.flush()
        conversation_one = Conversation(
            channel="xianyu",
            external_id="conversation-one",
            customer_id="external-one",
            customer_name="客户一",
            item_id=item_one.id,
        )
        conversation_two = Conversation(
            channel="xianyu",
            external_id="conversation-two",
            customer_id="external-one",
            customer_name="客户一",
            item_id=item_two.id,
        )
        session.add_all([conversation_one, conversation_two])
        session.flush()
        session.add(
            CustomerChannelIdentity(
                id="identity-one",
                customer_id="customer-1",
                channel="xianyu",
                external_customer_id="external-one",
                conversation_id=conversation_one.id,
                display_name="客户一",
            )
        )
        session.commit()
        conversation_one_id = conversation_one.id
        conversation_two_id = conversation_two.id

    service = RequirementExchangeService(database)
    with pytest.raises(RequirementExchangeError) as customer_error:
        service.preview_import(
            conversation_id=conversation_one_id,
            customer_id="customer-2",
            case_id=None,
            case_title="错误客户",
            source_label="GPT",
            document=blueprint(),
        )
    assert customer_error.value.code == "customer_mismatch"

    first_preview = service.preview_import(
        conversation_id=conversation_one_id,
        customer_id="customer-1",
        case_id=None,
        case_title="商品一需求",
        source_label="GPT",
        document=blueprint(),
    )
    first_result = service.commit_import(first_preview["token"], 0)
    with pytest.raises(RequirementExchangeError) as item_error:
        service.preview_import(
            conversation_id=conversation_two_id,
            customer_id="customer-1",
            case_id=first_result["case"]["id"],
            case_title=None,
            source_label="GPT",
            document=blueprint(),
        )
    assert item_error.value.code == "case_item_mismatch"


def test_xianyu_requirement_import_requires_current_listing(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'missing-item.db'}")
    database.create_all()
    with database.session() as session:
        session.add(BusinessCustomer(id="customer-1", name="测试客户"))
        conversation = Conversation(
            channel="xianyu",
            external_id="conversation-without-item",
            customer_id="external",
            customer_name="客户",
        )
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id

    service = RequirementExchangeService(database)
    with pytest.raises(RequirementExchangeError) as exc_info:
        service.preview_import(
            conversation_id=conversation_id,
            customer_id="customer-1",
            case_id=None,
            case_title="需求",
            source_label="GPT",
            document=blueprint(),
        )
    assert exc_info.value.code == "item_missing"


def test_requirement_case_item_backfill_requires_all_sources_to_agree(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'backfill.db'}")
    database.create_all()
    with database.session() as session:
        customer = BusinessCustomer(id="customer-1", name="测试客户")
        item_one = Item(external_id="item-one", title="商品一")
        item_two = Item(external_id="item-two", title="商品二")
        session.add_all([customer, item_one, item_two])
        session.flush()
        conversations = [
            Conversation(channel="xianyu", external_id="clear-one", customer_id="external", customer_name="客户", item_id=item_one.id),
            Conversation(channel="xianyu", external_id="clear-two", customer_id="external", customer_name="客户", item_id=item_one.id),
            Conversation(channel="xianyu", external_id="ambiguous", customer_id="external", customer_name="客户", item_id=item_two.id),
            Conversation(channel="wechat", external_id="missing", customer_id="external-wechat", customer_name="客户"),
        ]
        session.add_all(conversations)
        session.flush()
        clear_case = RequirementCase(id="case-clear", customer_id=customer.id, title="明确商品", current_version=0)
        mixed_case = RequirementCase(id="case-mixed", customer_id=customer.id, title="多个商品", current_version=0)
        missing_case = RequirementCase(id="case-missing", customer_id=customer.id, title="缺少商品", current_version=0)
        session.add_all([clear_case, mixed_case, missing_case])
        session.flush()
        session.add_all([
            RequirementCaseSource(id="source-clear-1", case_id=clear_case.id, conversation_id=conversations[0].id),
            RequirementCaseSource(id="source-clear-2", case_id=clear_case.id, conversation_id=conversations[1].id),
            RequirementCaseSource(id="source-mixed-1", case_id=mixed_case.id, conversation_id=conversations[0].id),
            RequirementCaseSource(id="source-mixed-2", case_id=mixed_case.id, conversation_id=conversations[2].id),
            RequirementCaseSource(id="source-missing-1", case_id=missing_case.id, conversation_id=conversations[0].id),
            RequirementCaseSource(id="source-missing-2", case_id=missing_case.id, conversation_id=conversations[3].id),
        ])
        session.commit()
        item_one_id = item_one.id

    with database.engine.begin() as connection:
        backfill_requirement_cases(connection)
        backfill_requirement_cases(connection)

    with database.session() as session:
        assert session.get(RequirementCase, "case-clear").item_id == item_one_id
        assert session.get(RequirementCase, "case-mixed").item_id is None
        assert session.get(RequirementCase, "case-missing").item_id is None
        links = list(session.scalars(select(CustomerItemLink)))
        assert len(links) == 1
        assert links[0].customer_id == "customer-1"
        assert links[0].item_id == item_one_id


def test_manual_blueprint_edit_appends_version_without_touching_v1(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'immutable-edit.db'}")
    database.create_all()
    with database.session() as session:
        customer = BusinessCustomer(id="customer-edit", name="编辑客户")
        item = Item(external_id="item-edit", title="编辑商品")
        session.add_all([customer, item])
        session.flush()
        conversation = Conversation(
            channel="xianyu",
            external_id="conversation-edit",
            customer_id="external-edit",
            customer_name="编辑客户",
            item_id=item.id,
        )
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id

    service = RequirementExchangeService(database)
    preview = service.preview_import(
        conversation_id=conversation_id,
        customer_id="customer-edit",
        case_id=None,
        case_title="订单需求",
        source_label="GPT",
        document=blueprint(),
    )
    first = service.commit_import(preview["token"], 0)
    with database.session() as session:
        v1 = session.scalar(
            select(RequirementDocumentVersion).where(
                RequirementDocumentVersion.case_id == first["case"]["id"],
                RequirementDocumentVersion.version == 1,
            )
        )
        assert v1 is not None
        original_json = v1.structured_json
        original_markdown = v1.content_markdown

    edited = blueprint()
    edited["title"] = "订单管理系统二期"
    edited["stages"][0]["estimated_hours"] = 42
    result = service.edit_case(
        first["case"]["id"],
        expected_version=1,
        change_summary="补充二期工时与标题",
        document=edited,
    )

    assert result["version"] == 2
    assert result["case"]["current_version"] == 2
    assert result["case"]["estimated_hours"] == 42
    with database.session() as session:
        versions = list(
            session.scalars(
                select(RequirementDocumentVersion)
                .where(RequirementDocumentVersion.case_id == first["case"]["id"])
                .order_by(RequirementDocumentVersion.version)
            )
        )
        assert len(versions) == 2
        assert versions[0].structured_json == original_json
        assert versions[0].content_markdown == original_markdown
        assert versions[1].source_type == "manual_edit"
        assert versions[1].source_label == "人工编辑"
        assert versions[1].change_summary == "补充二期工时与标题"

    with pytest.raises(RequirementExchangeError) as conflict:
        service.edit_case(
            first["case"]["id"],
            expected_version=1,
            change_summary="过期编辑",
            document=edited,
        )
    assert conflict.value.code == "version_conflict"


def test_requirement_case_transfer_is_atomic_scoped_and_idempotent(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'case-transfer.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    initial = default_snapshot()
    initial["customers"] = [
        {
            "id": "customer-original",
            "name": "原客户",
            "source": "xianyu",
            "phone": "",
            "followUpStatus": "won",
            "lastContactAt": "2026-08-01T00:00:00+08:00",
            "level": "B",
            "tags": ["原有项目"],
        }
    ]
    initial["projects"] = [
        {
            "id": "project-unrelated",
            "name": "原客户已有项目",
            "customerId": "customer-original",
            "projectKind": "client",
            "totalAmount": 500,
            "startDate": "2026-08-01",
            "dueDate": "2026-08-20",
            "progress": 20,
            "status": "in_progress",
            "type": "定制开发",
            "estimatedHours": 20,
            "accent": "blue",
        }
    ]
    initial["payments"] = [
        {
            "id": "payment-unrelated",
            "projectId": "project-unrelated",
            "customerId": "customer-original",
            "amount": 100,
            "type": "deposit",
            "status": "confirmed",
            "paidAt": "2026-08-01T00:00:00+08:00",
            "dueAt": "2026-08-01",
        }
    ]
    revision, _ = ledger.save(initial, 0)
    with database.session() as session:
        item = Item(external_id="item-transfer", title="前端页面美化与功能修改")
        session.add(item)
        session.flush()
        conversation = Conversation(
            channel="xianyu",
            external_id="conversation-transfer",
            customer_id="external-new-customer",
            customer_name="示例客户",
            item_id=item.id,
        )
        session.add(conversation)
        session.flush()
        case = RequirementCase(
            id="case-transfer",
            customer_id="customer-original",
            item_id=item.id,
            title="前端改版需求",
            status="clarifying",
            current_version=1,
        )
        session.add(case)
        session.flush()
        session.add_all(
            [
                RequirementCaseSource(
                    id="source-transfer",
                    case_id=case.id,
                    conversation_id=conversation.id,
                ),
                RequirementDocumentVersion(
                    conversation_id=conversation.id,
                    case_id=case.id,
                    schema_version="2.0",
                    source_type="gpt_import",
                    source_label="GPT",
                    version=1,
                    title="前端改版需求",
                    readiness="clarifying",
                    change_summary="首版",
                    structured_json=RequirementBlueprintV2.model_validate(blueprint()).model_dump_json(),
                    content_markdown="首版",
                    stage_progress_json="{}",
                    model="gpt-manual",
                ),
                CustomerChannelIdentity(
                    id="identity-transfer",
                    customer_id="customer-original",
                    channel="xianyu",
                    external_customer_id=conversation.customer_id,
                    conversation_id=conversation.id,
                    display_name=conversation.customer_name,
                ),
                CustomerItemLink(
                    id="item-link-transfer",
                    customer_id="customer-original",
                    item_id=item.id,
                    source_conversation_id=conversation.id,
                ),
            ]
        )
        session.commit()

    service = RequirementExchangeService(database, ledger)
    payload = dict(
        request_id="request-transfer-demo-customer",
        expected_customer_id="customer-original",
        expected_version=1,
        expected_revision=revision,
        target_customer_id=None,
        new_customer_name="示例客户",
    )
    result = service.transfer_case("case-transfer", **payload)
    again = service.transfer_case("case-transfer", **payload)

    assert result["idempotent"] is False
    assert again["idempotent"] is True
    assert result["target_customer_id"] != "customer-original"
    assert result["case"]["customer_id"] == result["target_customer_id"]
    assert [row["id"] for row in result["snapshot"]["projects"]] == ["project-unrelated"]
    assert result["snapshot"]["projects"][0]["customerId"] == "customer-original"
    assert [row["id"] for row in result["snapshot"]["payments"]] == ["payment-unrelated"]
    assert len(result["snapshot"]["customers"]) == 2
    with database.session() as session:
        moved_case = session.get(RequirementCase, "case-transfer")
        identity = session.get(CustomerChannelIdentity, "identity-transfer")
        item_link = session.get(CustomerItemLink, "item-link-transfer")
        assert moved_case is not None and moved_case.customer_id == result["target_customer_id"]
        assert identity is not None and identity.customer_id == result["target_customer_id"]
        assert item_link is not None and item_link.customer_id == result["target_customer_id"]


def test_requirement_case_transfer_checks_revision_before_mutation(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'case-transfer-conflict.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    revision, snapshot = ledger.get()
    snapshot["customers"].append({"id": "customer-one", "name": "客户一", "source": "xianyu", "phone": "", "followUpStatus": "new", "lastContactAt": "", "level": "C", "tags": []})
    revision, _ = ledger.save(snapshot, revision)
    with database.session() as session:
        session.add(RequirementCase(id="case-conflict", customer_id="customer-one", title="待转移", current_version=1))
        session.commit()
    service = RequirementExchangeService(database, ledger)
    with pytest.raises(RevisionConflict):
        service.transfer_case(
            "case-conflict",
            request_id="request-conflict-1",
            expected_customer_id="customer-one",
            expected_version=1,
            expected_revision=revision - 1,
            target_customer_id=None,
            new_customer_name="客户二",
        )
    with database.session() as session:
        assert session.get(RequirementCase, "case-conflict").customer_id == "customer-one"
        assert session.scalar(select(BusinessCustomer).where(BusinessCustomer.name == "客户二")) is None
