from __future__ import annotations

import base64
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app.database import Database
from backend.app.ledger import (
    LedgerService,
    PaymentConfirmationError,
    ProjectChangeOrderError,
    RevisionConflict,
    SettlementIssueError,
    default_snapshot,
)
from backend.app.models import (
    BusinessProject,
    BusinessTask,
    PaymentNode,
    ProjectChangeOrderRecord,
    ProjectSettlementIssueRecord,
)


def service(tmp_path: Path) -> LedgerService:
    database = Database(f"sqlite:///{tmp_path / 'unified.db'}")
    database.create_all()
    return LedgerService(database, tmp_path)


def sample_snapshot() -> dict:
    snapshot = default_snapshot()
    snapshot["customers"] = [{
        "id": "customer-1",
        "name": "测试客户",
        "source": "xianyu",
        "phone": "",
        "followUpStatus": "won",
        "lastContactAt": "2026-08-06T10:00:00Z",
        "level": "C",
        "tags": ["测试"],
    }]
    snapshot["projects"] = [{
        "id": "project-1",
        "name": "测试项目",
        "customerId": "customer-1",
        "totalAmount": 10000,
        "startDate": "2026-08-06",
        "dueDate": "2026-08-20",
        "progress": 0,
        "status": "pending",
        "type": "定制开发",
        "estimatedHours": 40,
        "accent": "blue",
    }]
    return snapshot


def test_snapshot_revision_prevents_cross_browser_overwrite(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, snapshot = ledger.get()
    assert revision == 0
    next_revision, saved = ledger.save(sample_snapshot(), revision)
    assert next_revision == 1
    assert saved["projects"][0]["name"] == "测试项目"
    with pytest.raises(RevisionConflict) as raised:
        ledger.save(snapshot, revision)
    assert raised.value.revision == 1


def test_personal_project_and_task_persist_without_customer(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    snapshot = default_snapshot()
    snapshot["projects"] = [{
        "id": "personal-project-1",
        "name": "个人产品实验",
        "customerId": "",
        "projectKind": "personal",
        "totalAmount": 0,
        "startDate": "2026-08-06",
        "dueDate": "2026-08-27",
        "progress": 0,
        "status": "pending",
        "type": "个人开发",
        "estimatedHours": 40,
        "accent": "purple",
    }]
    snapshot["tasks"] = [{
        "id": "personal-task-1",
        "projectId": "personal-project-1",
        "title": "验证核心需求",
        "status": "todo",
        "startDate": "2026-08-06",
        "dueDate": "2026-08-10",
        "estimatedHours": 4,
        "actualHours": 0,
    }]

    revision, saved = ledger.save(snapshot, 0)

    assert revision == 1
    assert saved["projects"][0]["projectKind"] == "personal"
    with ledger.database.session() as session:
        project = session.scalar(
            select(BusinessProject).where(BusinessProject.id == "personal-project-1")
        )
        task = session.scalar(
            select(BusinessTask).where(BusinessTask.id == "personal-task-1")
        )
        assert project is not None
        assert project.customer_id is None
        assert project.project_kind == "personal"
        assert task is not None
        assert task.project_id == project.id


def test_migration_requires_conflict_choice_and_writes_backups(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    ledger.save(sample_snapshot(), 0)
    incoming = sample_snapshot()
    incoming["projects"][0]["totalAmount"] = 12000
    incoming["attachments"] = [{
        "id": "file-1",
        "projectId": "project-1",
        "name": "说明.txt",
        "size": "4 B",
        "type": "document",
        "uploadedAt": "2026-08-06T10:00:00Z",
        "dataUrl": "data:text/plain;base64," + base64.b64encode(b"test").decode(),
    }]
    preview = ledger.preview_migration(incoming)
    assert len(preview["conflicts"]) == 1
    conflict = preview["conflicts"][0]
    result = ledger.commit_migration(
        incoming,
        preview["token"],
        {conflict["key"]: "browser"},
    )
    assert result["snapshot"]["projects"][0]["totalAmount"] == 12000
    assert result["attachments_written"] == 1
    assert (tmp_path / "data" / "backups" / result["backup_name"] / "xianyu-operator.db").exists()
    assert (tmp_path / result["snapshot"]["attachments"][0]["storagePath"]).read_bytes() == b"test"


def confirm(
    ledger: LedgerService,
    *,
    revision: int,
    request_id: str = "receipt-request-001",
    payment_id: str | None = None,
    amount: float = 10_000,
) -> dict:
    return ledger.confirm_payment(
        request_id=request_id,
        expected_revision=revision,
        project_id="project-1",
        payment_id=payment_id,
        amount=amount,
        paid_at="2026-08-07T12:30:00+08:00",
        payment_type="full",
        notes="测试确认到账",
    )


def create_change_order(
    ledger: LedgerService,
    *,
    revision: int,
    request_id: str = "change-order-request-001",
    amount: float = 1_200,
    title: str = "新增登录方式",
    payment_plan: list[dict] | None = None,
) -> dict:
    return ledger.create_project_change_order(
        request_id=request_id,
        expected_revision=revision,
        project_id="project-1",
        title=title,
        amount=amount,
        confirmed_at="2026-08-10",
        notes="客户已在聊天中确认增项",
        payment_plan=payment_plan or [{
            "amount": amount,
            "type": "milestone",
            "status": "pending",
            "paidAt": "",
            "dueAt": "2026-08-15",
            "notes": "追加修改款",
        }],
    )


def record_issue(
    ledger: LedgerService,
    *,
    revision: int,
    request_id: str = "settlement-request-001",
    issue_type: str = "customer_dissatisfied",
    receivable_impact: float = 0,
    refund_amount: float = 0,
    reason: str = "客户对交付结果不满意",
) -> dict:
    return ledger.record_settlement_issue(
        request_id=request_id,
        expected_revision=revision,
        project_id="project-1",
        issue_type=issue_type,
        receivable_impact=receivable_impact,
        refund_amount=refund_amount,
        occurred_at="2026-08-08T12:30:00+08:00",
        reason=reason,
        notes="已保存沟通记录",
    )


def test_confirm_full_receipt_without_payment_nodes(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)

    result = confirm(ledger, revision=revision)

    assert result["revision"] == 2
    assert result["remainder_payment_id"] is None
    payment = result["snapshot"]["payments"][0]
    assert payment["amount"] == 10_000
    assert payment["status"] == "confirmed"
    assert payment["confirmationRequestId"] == "receipt-request-001"
    assert result["snapshot"]["projects"][0]["status"] == "pending"
    assert result["snapshot"]["completedOrderCount"] == 0


def test_confirm_partial_receipt_without_nodes_creates_remainder(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)

    result = confirm(ledger, revision=revision, amount=3_000)

    confirmed = next(row for row in result["snapshot"]["payments"] if row["status"] == "confirmed")
    remainder = next(row for row in result["snapshot"]["payments"] if row["status"] == "pending")
    assert confirmed["amount"] == 3_000
    assert remainder["amount"] == 7_000
    assert remainder["type"] == "final"
    assert remainder["remainderOfRequestId"] == "receipt-request-001"


def test_confirm_existing_node_reuses_id_and_splits_partial_amount(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    snapshot = sample_snapshot()
    snapshot["payments"] = [{
        "id": "payment-node-1",
        "projectId": "project-1",
        "customerId": "customer-1",
        "amount": 6_000,
        "type": "milestone",
        "status": "pending",
        "paidAt": "2026-08-07T00:00:00Z",
        "dueAt": "2026-08-15",
        "notes": "阶段款",
    }]
    revision, _saved = ledger.save(snapshot, 0)

    result = confirm(
        ledger,
        revision=revision,
        payment_id="payment-node-1",
        amount=2_500,
    )

    confirmed = next(row for row in result["snapshot"]["payments"] if row["id"] == "payment-node-1")
    remainder = next(row for row in result["snapshot"]["payments"] if row["status"] == "pending")
    assert result["payment_id"] == "payment-node-1"
    assert confirmed["status"] == "confirmed"
    assert confirmed["amount"] == 2_500
    assert remainder["amount"] == 3_500
    assert remainder["dueAt"] == "2026-08-15"


def test_multiple_pending_nodes_require_explicit_selection(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    snapshot = sample_snapshot()
    snapshot["payments"] = [
        {"id": "pay-a", "projectId": "project-1", "customerId": "customer-1", "amount": 3_000, "type": "deposit", "status": "pending", "paidAt": "2026-08-07T00:00:00Z", "dueAt": "2026-08-10"},
        {"id": "pay-b", "projectId": "project-1", "customerId": "customer-1", "amount": 7_000, "type": "final", "status": "pending", "paidAt": "2026-08-07T00:00:00Z", "dueAt": "2026-08-20"},
    ]
    revision, _saved = ledger.save(snapshot, 0)

    with pytest.raises(PaymentConfirmationError, match="多个待收节点"):
        confirm(ledger, revision=revision, amount=3_000)


def test_confirmation_rejects_overpayment_and_revision_conflict(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)

    with pytest.raises(PaymentConfirmationError, match="不能超过当前未收金额"):
        confirm(ledger, revision=revision, amount=10_001)
    ledger.save(sample_snapshot(), revision)
    with pytest.raises(RevisionConflict):
        confirm(ledger, revision=revision, amount=1_000)


def test_confirmation_request_is_idempotent(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)

    first = confirm(ledger, revision=revision, amount=4_000)
    repeated = confirm(ledger, revision=revision, amount=4_000)

    assert first["idempotent"] is False
    assert repeated["idempotent"] is True
    assert repeated["revision"] == first["revision"]
    assert len(repeated["snapshot"]["payments"]) == 2


def test_change_order_expands_settled_contract_and_creates_pending_receivable(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    settled = confirm(ledger, revision=revision)

    result = create_change_order(ledger, revision=settled["revision"])

    project = result["snapshot"]["projects"][0]
    order = result["snapshot"]["changeOrders"][0]
    added_payment = next(
        row for row in result["snapshot"]["payments"]
        if row.get("changeOrderId") == order["id"]
    )
    assert project["totalAmount"] == 11_200
    assert project["status"] == "pending"
    assert order["title"] == "新增登录方式"
    assert order["amount"] == 1_200
    assert order["status"] == "confirmed"
    assert added_payment["status"] == "pending"
    assert added_payment["amount"] == 1_200


def test_change_order_can_record_immediate_receipt_without_completing_project(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    settled = confirm(ledger, revision=revision)
    result = create_change_order(
        ledger,
        revision=settled["revision"],
        payment_plan=[{
            "amount": 1_200,
            "type": "full",
            "status": "confirmed",
            "paidAt": "2026-08-10T15:30:00+08:00",
            "dueAt": "2026-08-10",
            "notes": "追加款已到账",
        }],
    )

    confirmed_total = sum(
        row["amount"]
        for row in result["snapshot"]["payments"]
        if row["status"] == "confirmed"
    )
    assert result["snapshot"]["projects"][0]["totalAmount"] == 11_200
    assert result["snapshot"]["projects"][0]["status"] == "pending"
    assert confirmed_total == 11_200
    assert result["snapshot"]["completedOrderCount"] == 0


def test_change_order_installments_must_equal_added_amount(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    plan = [
        {"amount": 500, "type": "milestone", "status": "pending", "paidAt": "", "dueAt": "2026-08-12"},
        {"amount": 700, "type": "final", "status": "pending", "paidAt": "", "dueAt": "2026-08-20"},
    ]
    result = create_change_order(ledger, revision=revision, payment_plan=plan)
    linked = [
        row for row in result["snapshot"]["payments"]
        if row.get("changeOrderId") == result["change_order_id"]
    ]
    assert [row["amount"] for row in linked] == [500, 700]

    with pytest.raises(ProjectChangeOrderError, match="必须等于追加金额"):
        create_change_order(
            ledger,
            revision=result["revision"],
            request_id="change-order-request-002",
            payment_plan=[{
                "amount": 1_199,
                "type": "full",
                "status": "pending",
                "paidAt": "",
                "dueAt": "2026-08-20",
            }],
        )


def test_change_order_is_idempotent_and_revision_protected(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    first = create_change_order(ledger, revision=revision)
    repeated = create_change_order(ledger, revision=revision)

    assert repeated["idempotent"] is True
    assert repeated["change_order_id"] == first["change_order_id"]
    assert len(repeated["snapshot"]["changeOrders"]) == 1
    assert repeated["snapshot"]["projects"][0]["totalAmount"] == 11_200

    with pytest.raises(ProjectChangeOrderError, match="已经用于另一笔记录"):
        create_change_order(
            ledger,
            revision=first["revision"],
            amount=1_300,
        )
    latest_revision, _latest = ledger.save(first["snapshot"], first["revision"])
    assert latest_revision == first["revision"] + 1
    with pytest.raises(RevisionConflict):
        create_change_order(
            ledger,
            revision=first["revision"],
            request_id="change-order-request-003",
        )


def test_change_order_schema_links_payment_nodes_and_keeps_foreign_keys_valid(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    result = create_change_order(ledger, revision=revision)

    with ledger.database.session() as session:
        order = session.get(ProjectChangeOrderRecord, result["change_order_id"])
        payment = session.get(PaymentNode, result["payment_ids"][0])
        assert order is not None
        assert order.request_id == "change-order-request-001"
        assert payment is not None
        assert payment.change_order_id == order.id
    with ledger.database.engine.connect() as connection:
        payment_columns = {
            str(row[1])
            for row in connection.exec_driver_sql("PRAGMA table_info(payment_nodes)")
        }
        indexes = {
            str(row[1])
            for row in connection.exec_driver_sql(
                "PRAGMA index_list(project_change_orders)"
            )
        }
        violations = list(connection.exec_driver_sql("PRAGMA foreign_key_check"))
    assert "change_order_id" in payment_columns
    assert any("request_id" in name for name in indexes)
    assert violations == []


def test_change_order_rejects_cancelled_or_terminated_project(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    terminated = record_issue(
        ledger,
        revision=revision,
        issue_type="cooperation_terminated",
        receivable_impact=10_000,
        reason="双方确认终止原合作",
    )

    with pytest.raises(ProjectChangeOrderError, match="创建新项目") as raised:
        create_change_order(ledger, revision=terminated["revision"])
    assert raised.value.code == "project_terminated"


def test_settlement_issue_can_record_risk_before_amount_is_known(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)

    result = record_issue(ledger, revision=revision)

    assert result["revision"] == 2
    issue = result["snapshot"]["settlementIssues"][0]
    assert issue["type"] == "customer_dissatisfied"
    assert issue["receivableImpact"] == 0
    assert issue["refundAmount"] == 0
    assert issue["reason"] == "客户对交付结果不满意"
    with ledger.database.session() as session:
        stored = session.get(ProjectSettlementIssueRecord, result["issue_id"])
        assert stored is not None
        assert stored.request_id == "settlement-request-001"


def test_uncollectible_without_payment_nodes_removes_collectible_balance(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)

    result = record_issue(
        ledger,
        revision=revision,
        issue_type="project_cancelled",
        receivable_impact=10_000,
        reason="客户取消合作，双方确认合同余额不再收取",
    )

    assert result["snapshot"]["settlementIssues"][0]["receivableImpact"] == 10_000
    assert result["snapshot"]["payments"] == []
    with pytest.raises(PaymentConfirmationError, match="已经没有未收金额"):
        confirm(ledger, revision=result["revision"], amount=1)


def test_terminal_issue_must_write_off_the_full_remaining_balance(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)

    with pytest.raises(SettlementIssueError) as raised:
        record_issue(
            ledger,
            revision=revision,
            issue_type="cooperation_terminated",
            receivable_impact=0,
            reason="双方确认终止合作",
        )

    assert raised.value.code == "terminal_issue_requires_full_writeoff"
    assert "全部确认为无法收回" in str(raised.value)


def test_full_pending_node_is_written_off_by_issue(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    snapshot = sample_snapshot()
    snapshot["payments"] = [{
        "id": "payment-node-1",
        "projectId": "project-1",
        "customerId": "customer-1",
        "amount": 6_000,
        "type": "final",
        "status": "pending",
        "paidAt": "2026-08-07T00:00:00Z",
        "dueAt": "2026-08-20",
        "notes": "尾款",
    }]
    revision, _saved = ledger.save(snapshot, 0)

    result = record_issue(
        ledger,
        revision=revision,
        issue_type="payment_refused",
        receivable_impact=6_000,
        reason="客户明确拒绝支付尾款",
    )

    node = next(row for row in result["snapshot"]["payments"] if row["id"] == "payment-node-1")
    assert node["status"] == "written_off"
    assert node["amount"] == 6_000
    assert "项目异常核销" in node["notes"]


def test_partial_pending_node_is_split_into_collectible_and_written_off(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    snapshot = sample_snapshot()
    snapshot["payments"] = [{
        "id": "payment-node-1",
        "projectId": "project-1",
        "customerId": "customer-1",
        "amount": 6_000,
        "type": "final",
        "status": "pending",
        "paidAt": "2026-08-07T00:00:00Z",
        "dueAt": "2026-08-20",
        "notes": "尾款",
    }]
    revision, _saved = ledger.save(snapshot, 0)

    result = record_issue(
        ledger,
        revision=revision,
        issue_type="scope_dispute",
        receivable_impact=2_500,
        reason="双方对增项范围存在争议，同意减免部分尾款",
    )

    pending = next(row for row in result["snapshot"]["payments"] if row["id"] == "payment-node-1")
    written_off = next(row for row in result["snapshot"]["payments"] if row["status"] == "written_off")
    assert pending["status"] == "pending"
    assert pending["amount"] == 3_500
    assert written_off["amount"] == 2_500
    assert written_off["dueAt"] == "2026-08-20"


def test_refund_is_limited_to_historical_net_receipts(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    receipt = confirm(ledger, revision=revision, amount=3_000)

    refunded = record_issue(
        ledger,
        revision=receipt["revision"],
        issue_type="refund",
        refund_amount=1_200,
        reason="客户不满意，双方确认退回部分已收款",
    )

    assert refunded["snapshot"]["settlementIssues"][0]["refundAmount"] == 1_200
    with pytest.raises(SettlementIssueError, match="不能超过当前可退款净到账"):
        record_issue(
            ledger,
            revision=refunded["revision"],
            request_id="settlement-request-002",
            issue_type="refund",
            refund_amount=1_801,
            reason="尝试超额退款",
        )


def test_refund_and_remaining_balance_writeoff_can_be_recorded_together(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    receipt = confirm(ledger, revision=revision, amount=3_000)

    result = record_issue(
        ledger,
        revision=receipt["revision"],
        issue_type="cooperation_terminated",
        receivable_impact=7_000,
        refund_amount=3_000,
        reason="终止合作，退回定金并放弃剩余合同款",
    )

    issue = result["snapshot"]["settlementIssues"][0]
    assert issue["refundAmount"] == 3_000
    assert issue["receivableImpact"] == 7_000
    assert any(row["status"] == "written_off" and row["amount"] == 7_000 for row in result["snapshot"]["payments"])


def test_issue_rejects_excess_impact_and_personal_project(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    with pytest.raises(SettlementIssueError, match="不能超过当前可收余额"):
        record_issue(ledger, revision=revision, receivable_impact=10_001)

    personal = sample_snapshot()
    personal["projects"][0]["projectKind"] = "personal"
    personal["projects"][0]["customerId"] = ""
    personal_revision, _saved = ledger.save(personal, revision)
    with pytest.raises(SettlementIssueError, match="只有接单项目"):
        record_issue(ledger, revision=personal_revision)


def test_issue_request_is_idempotent_and_revision_protected(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    first = record_issue(ledger, revision=revision, receivable_impact=500)
    repeated = record_issue(ledger, revision=revision, receivable_impact=500)
    assert repeated["idempotent"] is True
    assert repeated["issue_id"] == first["issue_id"]
    assert len(repeated["snapshot"]["settlementIssues"]) == 1

    with pytest.raises(SettlementIssueError, match="已经用于其他记录"):
        record_issue(ledger, revision=first["revision"], receivable_impact=600)

    latest_revision, latest = ledger.save(first["snapshot"], first["revision"])
    assert latest_revision == first["revision"] + 1
    with pytest.raises(RevisionConflict):
        record_issue(
            ledger,
            revision=first["revision"],
            request_id="settlement-request-002",
            reason="新的异常记录",
        )
    assert latest["settlementIssues"][0]["id"] == first["issue_id"]


def test_confirmation_respects_balance_after_writeoff(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    issue = record_issue(ledger, revision=revision, receivable_impact=4_000)

    with pytest.raises(PaymentConfirmationError, match="不能超过当前未收金额"):
        confirm(
            ledger,
            revision=issue["revision"],
            request_id="receipt-after-writeoff-too-large",
            amount=6_001,
        )
    confirmed = confirm(
        ledger,
        revision=issue["revision"],
        request_id="receipt-after-writeoff-valid",
        amount=6_000,
    )
    assert confirmed["snapshot"]["payments"][0]["amount"] == 6_000
    assert confirmed["remainder_payment_id"] is None


def test_settlement_issue_schema_has_indexes_and_valid_foreign_keys(tmp_path: Path) -> None:
    ledger = service(tmp_path)
    revision, _snapshot = ledger.save(sample_snapshot(), 0)
    record_issue(ledger, revision=revision, receivable_impact=500)

    with ledger.database.engine.connect() as connection:
        columns = {
            str(row[1])
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(project_settlement_issues)"
            )
        }
        indexes = {
            str(row[1])
            for row in connection.exec_driver_sql(
                "PRAGMA index_list(project_settlement_issues)"
            )
        }
        violations = list(connection.exec_driver_sql("PRAGMA foreign_key_check"))
    assert {
        "project_id",
        "customer_id",
        "issue_type",
        "receivable_impact",
        "refund_amount",
        "reason",
        "request_id",
    }.issubset(columns)
    assert any("project_id" in name for name in indexes)
    assert any("request_id" in name for name in indexes)
    assert violations == []
