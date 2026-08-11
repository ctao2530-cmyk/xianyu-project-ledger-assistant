from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app.customer_relationship_api import customer_relationship_router
from backend.app.database import Database
from backend.app.ledger import LedgerService, RevisionConflict, default_snapshot
from backend.app.models import (
    BusinessCustomer,
    BusinessProject,
    PaymentNode,
    ProjectChangeOrderRecord,
    ProjectSettlementIssueRecord,
)
from backend.app.services.customer_relationships import (
    CustomerRelationshipError,
    CustomerRelationshipService,
)


def build_service(
    tmp_path: Path,
) -> tuple[Database, LedgerService, CustomerRelationshipService]:
    database = Database(f"sqlite:///{tmp_path / 'customer-relationships.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    service = CustomerRelationshipService(database, ledger)
    return database, ledger, service


def relationship_snapshot() -> dict:
    snapshot = default_snapshot()
    snapshot["customers"] = [
        {
            "id": "customer-source",
            "name": "来源客户",
            "source": "xianyu",
            "phone": "",
            "followUpStatus": "contacted",
            "lastContactAt": "2026-08-01T10:00:00+08:00",
            "level": "C",
            "tags": ["待核对"],
        },
        {
            "id": "customer-target",
            "name": "目标客户",
            "source": "wechat",
            "phone": "",
            "followUpStatus": "new",
            "lastContactAt": "",
            "level": "B",
            "tags": ["需求案例"],
        },
        {
            "id": "customer-unrelated",
            "name": "无关客户",
            "source": "other",
            "phone": "",
            "followUpStatus": "inactive",
            "lastContactAt": "",
            "level": "C",
            "tags": [],
        },
    ]
    snapshot["projects"] = [
        {
            "id": "project-transfer",
            "name": "待修正项目",
            "customerId": "customer-source",
            "projectKind": "client",
            "totalAmount": 280,
            "startDate": "2026-07-01",
            "dueDate": "2026-07-20",
            "progress": 100,
            "status": "delivered",
            "type": "定制开发",
            "estimatedHours": 8,
            "accent": "blue",
        },
        {
            "id": "project-unrelated",
            "name": "终止合作项目",
            "customerId": "customer-unrelated",
            "projectKind": "client",
            "totalAmount": 20,
            "startDate": "2026-07-02",
            "dueDate": "2026-07-10",
            "progress": 0,
            "status": "pending",
            "type": "定制开发",
            "estimatedHours": 2,
            "accent": "orange",
        },
        {
            "id": "project-personal",
            "name": "个人实验",
            "customerId": "",
            "projectKind": "personal",
            "totalAmount": 0,
            "startDate": "2026-07-03",
            "dueDate": "2026-07-30",
            "progress": 0,
            "status": "pending",
            "type": "个人开发",
            "estimatedHours": 4,
            "accent": "purple",
        },
    ]
    snapshot["changeOrders"] = [
        {
            "id": "change-transfer",
            "projectId": "project-transfer",
            "customerId": "customer-source",
            "title": "追加修改",
            "amount": 50,
            "confirmedAt": "2026-07-10",
            "status": "confirmed",
            "notes": "保留金额",
            "requestId": "change-transfer-request",
            "createdAt": "2026-07-10T10:00:00+08:00",
        }
    ]
    snapshot["payments"] = [
        {
            "id": "payment-confirmed",
            "projectId": "project-transfer",
            "customerId": "customer-source",
            "amount": 230,
            "type": "milestone",
            "status": "confirmed",
            "paidAt": "2026-07-12T10:00:00+08:00",
            "dueAt": "2026-07-12",
            "notes": "已到账",
        },
        {
            "id": "payment-pending",
            "projectId": "project-transfer",
            "customerId": "customer-source",
            "changeOrderId": "change-transfer",
            "amount": 50,
            "type": "final",
            "status": "pending",
            "paidAt": "",
            "dueAt": "2026-07-20",
            "notes": "待收",
        },
    ]
    snapshot["settlementIssues"] = [
        {
            "id": "issue-transfer",
            "projectId": "project-transfer",
            "customerId": "customer-source",
            "type": "other",
            "receivableImpact": 0,
            "refundAmount": 0,
            "occurredAt": "2026-07-15T10:00:00+08:00",
            "reason": "测试级联",
            "notes": "内容保持不变",
            "requestId": "issue-transfer-request",
            "createdAt": "2026-07-15T10:00:00+08:00",
        },
        {
            "id": "issue-unrelated",
            "projectId": "project-unrelated",
            "customerId": "customer-unrelated",
            "type": "cooperation_terminated",
            "receivableImpact": 20,
            "refundAmount": 0,
            "occurredAt": "2026-07-16T10:00:00+08:00",
            "reason": "终止合作",
            "notes": "必须保留",
            "requestId": "issue-unrelated-request",
            "createdAt": "2026-07-16T10:00:00+08:00",
        },
    ]
    return snapshot


def test_customer_update_is_revision_protected_and_idempotent(tmp_path: Path) -> None:
    database, ledger, service = build_service(tmp_path)
    revision, _ = ledger.save(relationship_snapshot(), 0)

    result = service.update_customer(
        "customer-target",
        request_id="customer-update-request-001",
        expected_revision=revision,
        name="目标客户更新",
        source="wechat",
        phone="",
        follow_up_status="won",
        last_contact_at="",
        level="A",
        tags=["需求案例", "已成交"],
    )
    repeated = service.update_customer(
        "customer-target",
        request_id="customer-update-request-001",
        expected_revision=revision,
        name="目标客户更新",
        source="wechat",
        phone="",
        follow_up_status="won",
        last_contact_at="",
        level="A",
        tags=["需求案例", "已成交"],
    )

    assert result["revision"] == revision + 1
    assert result["idempotent"] is False
    assert repeated["revision"] == result["revision"]
    assert repeated["idempotent"] is True
    updated = next(row for row in result["snapshot"]["customers"] if row["id"] == "customer-target")
    assert updated["followUpStatus"] == "won"
    assert updated["lastContactAt"] == ""
    assert updated["tags"] == ["需求案例", "已成交"]
    with database.session() as session:
        customer = session.get(BusinessCustomer, "customer-target")
        assert customer is not None
        assert customer.name == "目标客户更新"
        assert customer.follow_up_status == "won"
        assert customer.level == "A"

    with pytest.raises(CustomerRelationshipError) as reused:
        service.update_customer(
            "customer-target",
            request_id="customer-update-request-001",
            expected_revision=result["revision"],
            name="不同内容",
            source="wechat",
            phone="",
            follow_up_status="won",
            last_contact_at="",
            level="A",
            tags=[],
        )
    assert reused.value.code == "request_id_reused"

    with pytest.raises(RevisionConflict):
        service.update_customer(
            "customer-source",
            request_id="customer-update-request-002",
            expected_revision=revision,
            name="来源客户",
            source="xianyu",
            phone="",
            follow_up_status="new",
            last_contact_at="",
            level="C",
            tags=[],
        )


def test_preview_and_rebind_cascade_exact_project_relationships(tmp_path: Path) -> None:
    database, ledger, service = build_service(tmp_path)
    revision, original = ledger.save(relationship_snapshot(), 0)

    preview = service.preview_rebind(
        expected_revision=revision,
        project_id="project-transfer",
        current_customer_id="customer-source",
        target_customer_id="customer-target",
    )

    assert preview["impact"] == {
        "project_count": 1,
        "payment_count": 2,
        "change_order_count": 1,
        "settlement_issue_count": 1,
        "confirmed_amount": 230.0,
        "pending_amount": 50.0,
    }
    assert len(preview["preview_token"]) == 64
    assert "需求案例与渠道身份" in preview["preserves"]

    result = service.rebind_project(
        request_id="customer-rebind-request-001",
        expected_revision=revision,
        preview_token=preview["preview_token"],
        project_id="project-transfer",
        current_customer_id="customer-source",
        target_customer_id="customer-target",
    )
    assert result["revision"] == revision + 1
    assert result["idempotent"] is False
    snapshot = result["snapshot"]
    project = next(row for row in snapshot["projects"] if row["id"] == "project-transfer")
    assert project["customerId"] == "customer-target"
    assert project["totalAmount"] == 280
    assert project["status"] == "delivered"
    assert all(row["customerId"] == "customer-target" for row in snapshot["payments"] if row["projectId"] == "project-transfer")
    assert all(row["customerId"] == "customer-target" for row in snapshot["changeOrders"] if row["projectId"] == "project-transfer")
    assert all(row["customerId"] == "customer-target" for row in snapshot["settlementIssues"] if row["projectId"] == "project-transfer")
    unrelated = next(row for row in snapshot["projects"] if row["id"] == "project-unrelated")
    unrelated_issue = next(row for row in snapshot["settlementIssues"] if row["id"] == "issue-unrelated")
    original_unrelated = next(row for row in original["settlementIssues"] if row["id"] == "issue-unrelated")
    assert unrelated["customerId"] == "customer-unrelated"
    assert unrelated_issue == original_unrelated

    repeated = service.rebind_project(
        request_id="customer-rebind-request-001",
        expected_revision=revision,
        preview_token=preview["preview_token"],
        project_id="project-transfer",
        current_customer_id="customer-source",
        target_customer_id="customer-target",
    )
    assert repeated["idempotent"] is True
    assert repeated["revision"] == result["revision"]

    with database.session() as session:
        assert session.get(BusinessProject, "project-transfer").customer_id == "customer-target"
        assert session.get(PaymentNode, "payment-confirmed").customer_id == "customer-target"
        assert session.get(ProjectChangeOrderRecord, "change-transfer").customer_id == "customer-target"
        assert session.get(ProjectSettlementIssueRecord, "issue-transfer").customer_id == "customer-target"
        violations = list(session.connection().exec_driver_sql("PRAGMA foreign_key_check"))
        assert violations == []


def test_rebind_rejects_stale_preview_wrong_source_and_personal_project(tmp_path: Path) -> None:
    _, ledger, service = build_service(tmp_path)
    revision, _ = ledger.save(relationship_snapshot(), 0)
    preview = service.preview_rebind(
        expected_revision=revision,
        project_id="project-transfer",
        current_customer_id="customer-source",
        target_customer_id="customer-target",
    )

    with pytest.raises(CustomerRelationshipError) as stale:
        service.rebind_project(
            request_id="customer-rebind-request-002",
            expected_revision=revision,
            preview_token="0" * 64,
            project_id="project-transfer",
            current_customer_id="customer-source",
            target_customer_id="customer-target",
        )
    assert stale.value.code == "preview_expired"

    with pytest.raises(CustomerRelationshipError) as wrong_source:
        service.preview_rebind(
            expected_revision=revision,
            project_id="project-transfer",
            current_customer_id="customer-unrelated",
            target_customer_id="customer-target",
        )
    assert wrong_source.value.code == "project_customer_changed"

    with pytest.raises(CustomerRelationshipError) as personal:
        service.preview_rebind(
            expected_revision=revision,
            project_id="project-personal",
            current_customer_id="customer-source",
            target_customer_id="customer-target",
        )
    assert personal.value.code == "personal_project_forbidden"

    with pytest.raises(CustomerRelationshipError) as missing:
        service.preview_rebind(
            expected_revision=revision,
            project_id="project-transfer",
            current_customer_id="customer-source",
            target_customer_id="customer-missing",
        )
    assert missing.value.code == "customer_not_found"
    assert preview["revision"] == revision


class EventHubStub:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish_nowait(self, event: dict) -> None:
        self.events.append(event)


def test_customer_relationship_api_returns_safe_conflicts(tmp_path: Path) -> None:
    _, ledger, service = build_service(tmp_path)
    revision, _ = ledger.save(relationship_snapshot(), 0)
    hub = EventHubStub()
    app = FastAPI()
    app.include_router(customer_relationship_router)
    app.state.runtime = SimpleNamespace(customer_relationships=service, event_hub=hub)
    client = TestClient(app)

    updated = client.patch(
        "/api/ledger/customers/customer-target",
        json={
            "request_id": "api-customer-update-001",
            "expected_revision": revision,
            "name": "目标客户",
            "source": "wechat",
            "phone": "",
            "follow_up_status": "won",
            "last_contact_at": "",
            "level": "B",
            "tags": ["需求案例"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == revision + 1
    assert hub.events[-1]["source"] == "customer_update"

    stale = client.post(
        "/api/ledger/customer-relations/preview",
        json={
            "expected_revision": revision,
            "project_id": "project-transfer",
            "current_customer_id": "customer-source",
            "target_customer_id": "customer-target",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "ledger_revision_conflict"
    assert "来源客户" not in stale.text
    assert "目标客户" not in stale.text
