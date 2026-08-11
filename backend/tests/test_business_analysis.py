from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.business_analysis_api import business_analysis_router
from backend.app.database import Database
from backend.app.ledger import LedgerService, default_snapshot
from backend.app.models import (
    Conversation,
    Item,
    ProductDailySnapshot,
    ProductMonitor,
)
from backend.app.services.business_analysis import BusinessAnalysisService


FIXED_NOW = datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)


def build_service(tmp_path: Path) -> tuple[Database, LedgerService, BusinessAnalysisService]:
    database = Database(f"sqlite:///{tmp_path / 'business-analysis.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    return database, ledger, BusinessAnalysisService(database, ledger)


def test_empty_analysis_marks_missing_evidence_without_inventing_metrics(tmp_path: Path) -> None:
    _, ledger, service = build_service(tmp_path)

    result = service.overview(now=FIXED_NOW)
    revision_after, snapshot_after = ledger.get()

    assert result.summary.startswith("当前经营状态：基线建设中")
    assert result.analysis_method == "evidence_rules_v1"
    assert result.metrics.products.owned_products == 0
    assert result.metrics.products.exposure.available is False
    assert result.metrics.customers.total == 0
    assert result.metrics.projects.total == 0
    assert result.metrics.finance.all_time_profit == 0
    assert len(result.data_gaps) == 4
    assert {row.id for row in result.insights} >= {
        "product-baseline-missing",
        "customer-baseline-missing",
        "project-baseline-missing",
        "finance-baseline-missing",
    }
    assert all(row.execution_mode == "manual" for row in result.recommendations)
    assert all(row.label == "未来扩展字段" for row in result.future_fields)
    assert revision_after == result.ledger_revision == 0
    assert snapshot_after == default_snapshot()


def test_analysis_aggregates_only_owned_products_and_uses_net_ledger_income(tmp_path: Path) -> None:
    database, ledger, service = build_service(tmp_path)
    snapshot = default_snapshot()
    snapshot["customers"] = [
        {
            "id": "customer-active",
            "name": "示例客户甲",
            "source": "xianyu",
            "phone": "",
            "followUpStatus": "won",
            "lastContactAt": "2026-08-10T10:00:00+08:00",
            "level": "A",
        },
        {
            "id": "customer-stale",
            "name": "示例客户乙",
            "source": "wechat",
            "phone": "",
            "followUpStatus": "inactive",
            "lastContactAt": "2026-05-01T10:00:00+08:00",
            "level": "B",
        },
    ]
    snapshot["projects"] = [
        {
            "id": "project-complete",
            "name": "已完成示例项目",
            "customerId": "customer-active",
            "projectKind": "client",
            "totalAmount": 2500,
            "startDate": "2026-06-01",
            "dueDate": "2026-07-01",
            "progress": 100,
            "status": "completed",
            "type": "定制开发",
            "estimatedHours": 30,
            "accent": "blue",
        },
        {
            "id": "project-overdue",
            "name": "逾期示例项目",
            "customerId": "customer-stale",
            "projectKind": "client",
            "totalAmount": 500,
            "startDate": "2026-07-01",
            "dueDate": "2026-08-01",
            "progress": 40,
            "status": "overdue",
            "type": "页面开发",
            "estimatedHours": 15,
            "accent": "orange",
        },
    ]
    snapshot["payments"] = [
        {
            "id": "payment-previous",
            "projectId": "project-complete",
            "customerId": "customer-active",
            "amount": 1000,
            "type": "deposit",
            "status": "confirmed",
            "paidAt": "2026-07-10T10:00:00+08:00",
            "dueAt": "2026-07-10",
        },
        {
            "id": "payment-current",
            "projectId": "project-complete",
            "customerId": "customer-active",
            "amount": 800,
            "type": "milestone",
            "status": "confirmed",
            "paidAt": "2026-08-05T10:00:00+08:00",
            "dueAt": "2026-08-05",
        },
        {
            "id": "payment-refunded",
            "projectId": "project-complete",
            "customerId": "customer-active",
            "amount": 200,
            "type": "milestone",
            "status": "refunded",
            "paidAt": "2026-08-06T10:00:00+08:00",
            "dueAt": "2026-08-06",
        },
    ]
    snapshot["settlementIssues"] = [
        {
            "id": "issue-refund",
            "projectId": "project-complete",
            "customerId": "customer-active",
            "type": "refund",
            "receivableImpact": 0,
            "refundAmount": 100,
            "occurredAt": "2026-08-07T10:00:00+08:00",
            "reason": "隔离测试退款",
            "createdAt": "2026-08-07T10:00:00+08:00",
            "requestId": "issue-request",
        }
    ]
    snapshot["expenses"] = [
        {
            "id": "expense-previous",
            "name": "上月工具成本",
            "category": "software",
            "amount": 200,
            "paidAt": "2026-07-15T10:00:00+08:00",
        },
    ]
    revision, persisted = ledger.save(snapshot, 0)
    persisted["expenses"].append(
        {
            "id": "expense-current",
            "projectId": "project-complete",
            "name": "本月项目成本",
            "category": "outsourcing",
            "amount": 300,
            "paidAt": "2026-08-08T10:00:00+08:00",
        }
    )
    ledger.save(persisted, revision)

    with database.session() as session:
        owned_item = Item(external_id="owned-product", title="本人示例商品")
        excluded_item = Item(external_id="excluded-product", title="其他卖家商品")
        session.add_all([owned_item, excluded_item])
        session.flush()
        session.add_all(
            [
                ProductMonitor(
                    item_id=owned_item.id,
                    enabled=True,
                    ownership_status="owned",
                    ownership_source="seller_match",
                ),
                ProductMonitor(
                    item_id=excluded_item.id,
                    enabled=True,
                    ownership_status="excluded",
                    ownership_source="seller_mismatch",
                ),
                ProductDailySnapshot(
                    item_id=owned_item.id,
                    snapshot_date="2026-08-03",
                    source="test",
                    title="本人示例商品",
                    status="在售",
                    published_at="2026-07-20T09:00:00+08:00",
                    raw_browse_count=20,
                    browse_count=20,
                    inquiry_count=0,
                    converted_project_count=0,
                    captured_at=datetime(2026, 8, 3, 2, 0, tzinfo=timezone.utc),
                ),
                ProductDailySnapshot(
                    item_id=owned_item.id,
                    snapshot_date="2026-08-10",
                    source="test",
                    title="本人示例商品",
                    status="在售",
                    published_at="2026-07-20T09:00:00+08:00",
                    raw_browse_count=120,
                    browse_count=120,
                    inquiry_count=2,
                    converted_project_count=0,
                    captured_at=datetime(2026, 8, 10, 2, 0, tzinfo=timezone.utc),
                ),
                ProductDailySnapshot(
                    item_id=excluded_item.id,
                    snapshot_date="2026-08-10",
                    source="test",
                    title="其他卖家商品",
                    status="在售",
                    raw_browse_count=9999,
                    browse_count=9999,
                    inquiry_count=999,
                    converted_project_count=99,
                    captured_at=datetime(2026, 8, 10, 2, 0, tzinfo=timezone.utc),
                ),
                Conversation(
                    channel="xianyu",
                    external_id="conversation-example",
                    customer_id="external-customer",
                    customer_name="脱敏客户",
                    item_id=owned_item.id,
                    last_message_at=datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()

    result = service.overview(now=FIXED_NOW)

    assert result.ledger_revision == 2
    assert result.metrics.products.owned_products == 1
    assert result.metrics.products.monitored_products == 1
    assert result.metrics.products.exposure.current == 120
    assert result.metrics.products.exposure.delta_7d == 100
    assert result.metrics.products.inquiries.current == 2
    assert result.metrics.products.inquiries.delta_7d == 2
    assert result.metrics.products.converted_projects.current == 0
    assert result.metrics.products.snapshot_coverage_percent == 100
    assert result.metrics.customers.total == 2
    assert result.metrics.customers.won_customers == 1
    assert result.metrics.customers.active_last_30d == 1
    assert result.metrics.customers.stale_or_missing_contact_30d == 1
    assert result.metrics.projects.total == 2
    assert result.metrics.projects.overdue_projects == 1
    assert result.metrics.projects.confirmed_income == 1700
    assert result.metrics.projects.outstanding_receivables == 1000
    assert result.metrics.finance.income.current == 700
    assert result.metrics.finance.income.previous == 1000
    assert result.metrics.finance.profit.current == 400
    assert result.metrics.finance.profit.previous == 800
    assert result.metrics.finance.all_time_profit == 1200
    assert {row.id for row in result.insights} >= {
        "inquiry-without-project",
        "stale-customer-followup",
        "overdue-projects",
        "income-decline",
    }
    assert result.recommendations[0].priority == "high"
    assert {source.id for source in result.data_sources} == {
        "ledger",
        "products",
        "conversations",
    }
    assert "其他卖家商品" not in result.model_dump_json()
    assert "示例客户甲" not in result.model_dump_json()


def test_overview_api_returns_required_contract(tmp_path: Path) -> None:
    _, _, service = build_service(tmp_path)
    app = FastAPI()
    app.include_router(business_analysis_router)
    app.state.runtime = SimpleNamespace(business_analysis=service)

    response = TestClient(app).get("/api/business-analysis/overview")

    assert response.status_code == 200
    payload = response.json()
    assert {"summary", "metrics", "insights", "recommendations"} <= payload.keys()
    assert payload["analysis_method"] == "evidence_rules_v1"
    assert payload["period"]["timezone"] == "Asia/Shanghai"
    assert payload["data_sources"][0]["source_type"] in {"ledger", "sqlite"}
