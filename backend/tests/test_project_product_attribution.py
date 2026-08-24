from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app.database import Database
from backend.app.ledger import LedgerService, RevisionConflict, default_snapshot
from backend.app.models import (
    BusinessProject,
    Item,
    ProductDailySnapshot,
    ProductMonitor,
)
from backend.app.services.product_intelligence import ProductIntelligenceService
from backend.app.services.project_product_attribution import (
    ProjectProductAttributionError,
    ProjectProductAttributionService,
)


def build_services(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'project-product.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    with database.session() as session:
        first = Item(external_id="owned-1", title="前端页面美化")
        second = Item(external_id="owned-2", title="网站维护服务")
        excluded = Item(external_id="other-1", title="其他卖家商品")
        session.add_all([first, second, excluded])
        session.flush()
        session.add_all([
            ProductMonitor(item_id=first.id, ownership_status="owned", ownership_source="account_listing"),
            ProductMonitor(item_id=second.id, ownership_status="owned", ownership_source="account_listing"),
            ProductMonitor(item_id=excluded.id, ownership_status="excluded", ownership_source="seller_mismatch"),
        ])
        session.commit()
    return database, ledger, ProjectProductAttributionService(database, ledger)


def project_snapshot() -> dict:
    snapshot = default_snapshot()
    snapshot["customers"] = [{
        "id": "customer-1",
        "name": "测试客户",
        "source": "xianyu",
        "phone": "",
        "followUpStatus": "won",
        "lastContactAt": "2026-08-15T10:00:00+08:00",
        "level": "A",
        "tags": [],
    }]
    snapshot["projects"] = [
        {
            "id": "project-1",
            "name": "网页优化交付",
            "customerId": "customer-1",
            "projectKind": "client",
            "totalAmount": 1000,
            "startDate": "2026-08-15",
            "dueDate": "2026-08-20",
            "progress": 50,
            "status": "in_progress",
            "type": "定制开发",
            "estimatedHours": 10,
            "accent": "purple",
        },
        {
            "id": "project-2",
            "name": "响应式适配",
            "customerId": "customer-1",
            "projectKind": "client",
            "totalAmount": 800,
            "startDate": "2026-08-15",
            "dueDate": "2026-08-22",
            "progress": 20,
            "status": "in_progress",
            "type": "定制开发",
            "estimatedHours": 8,
            "accent": "blue",
        },
        {
            "id": "personal-1",
            "name": "个人实验",
            "customerId": "",
            "projectKind": "personal",
            "totalAmount": 0,
            "startDate": "2026-08-15",
            "dueDate": "2026-08-30",
            "progress": 0,
            "status": "pending",
            "type": "个人开发",
            "estimatedHours": 4,
            "accent": "green",
        },
    ]
    snapshot["payments"] = [
        {
            "id": "payment-1",
            "projectId": "project-1",
            "customerId": "customer-1",
            "amount": 600,
            "type": "deposit",
            "status": "confirmed",
            "paidAt": "2026-08-15T10:20:00+08:00",
            "dueAt": "2026-08-15",
        },
        {
            "id": "payment-2",
            "projectId": "project-2",
            "customerId": "customer-1",
            "amount": 400,
            "type": "deposit",
            "status": "confirmed",
            "paidAt": "2026-08-15T11:20:00+08:00",
            "dueAt": "2026-08-15",
        },
    ]
    snapshot["expenses"] = [
        {
            "id": "expense-1",
            "projectId": "project-1",
            "name": "项目素材",
            "category": "other",
            "amount": 100,
            "paidAt": "2026-08-15T09:00:00+08:00",
        },
    ]
    return snapshot


def save_project_snapshot(ledger: LedgerService) -> tuple[int, dict]:
    """Create project rows first so SQLite can enforce expense foreign keys."""
    snapshot = project_snapshot()
    expenses = snapshot["expenses"]
    snapshot["expenses"] = []
    revision, saved = ledger.save(snapshot, 0)
    saved["expenses"] = expenses
    return ledger.save(saved, revision)


def business_metrics(database: Database, external_id: str) -> dict[str, object]:
    with database.session() as session:
        item = session.scalar(select(Item).where(Item.external_id == external_id))
        assert item is not None
        service = ProductIntelligenceService.__new__(ProductIntelligenceService)
        return service._business_metrics(session, item.id)


def bind(service: ProjectProductAttributionService, revision: int, project_id: str, target: str, request_id: str):
    preview = service.preview(
        expected_revision=revision,
        project_id=project_id,
        target_item_external_id=target,
    )
    return service.commit(
        request_id=request_id,
        expected_revision=revision,
        preview_token=preview["preview_token"],
        project_id=project_id,
        target_item_external_id=target,
    )


def test_unbound_projects_are_excluded_and_multiple_projects_aggregate(tmp_path: Path) -> None:
    database, ledger, attribution = build_services(tmp_path)
    revision, _ = save_project_snapshot(ledger)
    assert business_metrics(database, "owned-1")["converted_project_count"] == 0

    first = bind(attribution, revision, "project-1", "owned-1", "bind-project-001")
    second = bind(attribution, first["revision"], "project-2", "owned-1", "bind-project-002")
    metrics = business_metrics(database, "owned-1")

    assert second["revision"] == revision + 2
    assert metrics["converted_project_count"] == 2
    assert metrics["revenue_total"] == 1000
    assert metrics["project_expense_total"] == 100
    assert metrics["profit_total"] == 900
    assert {row.project_name for row in metrics["linked_projects"]} == {"网页优化交付", "响应式适配"}


def test_confirmed_receipt_increases_realtime_profit_once(tmp_path: Path) -> None:
    database, ledger, attribution = build_services(tmp_path)
    revision, _ = save_project_snapshot(ledger)
    bound = bind(attribution, revision, "project-1", "owned-1", "bind-profit-001")
    before = business_metrics(database, "owned-1")

    result = ledger.confirm_payment(
        request_id="receipt-profit-001",
        expected_revision=bound["revision"],
        project_id="project-1",
        payment_id=None,
        amount=200,
        paid_at="2026-08-15T16:20:00+08:00",
        payment_type="milestone",
        notes="追加确认到账",
    )
    repeated = ledger.confirm_payment(
        request_id="receipt-profit-001",
        expected_revision=bound["revision"],
        project_id="project-1",
        payment_id=None,
        amount=200,
        paid_at="2026-08-15T16:20:00+08:00",
        payment_type="milestone",
        notes="追加确认到账",
    )
    after = business_metrics(database, "owned-1")

    assert before["profit_total"] == 500
    assert result["revision"] == repeated["revision"]
    assert after["profit_total"] == 700


def test_rebinding_moves_profit_without_duplication_and_is_idempotent(tmp_path: Path) -> None:
    database, ledger, attribution = build_services(tmp_path)
    revision, _ = save_project_snapshot(ledger)
    first = bind(attribution, revision, "project-1", "owned-1", "bind-move-001")
    preview = attribution.preview(
        expected_revision=first["revision"],
        project_id="project-1",
        target_item_external_id="owned-2",
    )
    moved = attribution.commit(
        request_id="bind-move-002",
        expected_revision=first["revision"],
        preview_token=preview["preview_token"],
        project_id="project-1",
        target_item_external_id="owned-2",
    )
    repeated = attribution.commit(
        request_id="bind-move-002",
        expected_revision=first["revision"],
        preview_token=preview["preview_token"],
        project_id="project-1",
        target_item_external_id="owned-2",
    )

    assert business_metrics(database, "owned-1")["profit_total"] == 0
    assert business_metrics(database, "owned-2")["profit_total"] == 500
    assert moved["revision"] == repeated["revision"]
    assert repeated["idempotent"] is True
    with pytest.raises(ProjectProductAttributionError, match="请求编号"):
        attribution.commit(
            request_id="bind-move-002",
            expected_revision=moved["revision"],
            preview_token=preview["preview_token"],
            project_id="project-1",
            target_item_external_id="owned-1",
        )


def test_revision_personal_and_non_owned_guards(tmp_path: Path) -> None:
    _database, ledger, attribution = build_services(tmp_path)
    revision, _ = save_project_snapshot(ledger)
    with pytest.raises(RevisionConflict):
        attribution.preview(expected_revision=revision - 1, project_id="project-1", target_item_external_id="owned-1")
    with pytest.raises(ProjectProductAttributionError, match="接单项目"):
        attribution.preview(expected_revision=revision, project_id="personal-1", target_item_external_id="owned-1")
    with pytest.raises(ProjectProductAttributionError, match="本人商品"):
        attribution.preview(expected_revision=revision, project_id="project-1", target_item_external_id="other-1")


def test_binding_preserves_historical_product_snapshot(tmp_path: Path) -> None:
    database, ledger, attribution = build_services(tmp_path)
    revision, _ = save_project_snapshot(ledger)
    with database.session() as session:
        item = session.scalar(select(Item).where(Item.external_id == "owned-1"))
        assert item is not None
        session.add(ProductDailySnapshot(
            item_id=item.id,
            snapshot_date="2026-08-14",
            title=item.title,
            revenue_total=123,
            profit_total=99,
        ))
        session.commit()

    bind(attribution, revision, "project-1", "owned-1", "bind-history-001")

    with database.session() as session:
        snapshot = session.scalar(select(ProductDailySnapshot).where(ProductDailySnapshot.snapshot_date == "2026-08-14"))
        project = session.get(BusinessProject, "project-1")
        assert snapshot is not None and snapshot.revenue_total == 123 and snapshot.profit_total == 99
        assert project is not None and project.item_id is not None
