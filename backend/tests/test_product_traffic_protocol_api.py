from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.product_api import product_router
from backend.app.services.product_intelligence import ProductIntelligenceService


def test_legacy_planned_traffic_batch_creation_is_gone() -> None:
    app = FastAPI()
    app.include_router(product_router)

    response = TestClient(app).post(
        "/api/products/traffic-batches",
        json={
            "request_id": "legacy-plan-create",
            "item_external_ids": ["owned-item"],
            "planned_at": "2026-08-27T10:00:00+08:00",
            "actual_cost": 5.9,
            "plan_slot_id": None,
            "note": "不应再创建未来批次",
            "checkpoint_collection_mode": "auto",
        },
    )

    assert response.status_code == 410
    assert response.json() == {
        "detail": "旧计划批次入口已停用；请在闲鱼完成真实投流后使用记录接口"
    }


def test_legacy_planned_creation_is_not_a_production_service_contract() -> None:
    assert not hasattr(ProductIntelligenceService, "create_traffic_batch")
    assert hasattr(
        ProductIntelligenceService,
        "create_legacy_planned_traffic_batch_for_test",
    )
