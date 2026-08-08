from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import SecretStr

from backend.app.adapters.base import ItemInfo
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.models import Conversation, Item, Message
from backend.app.services.event_hub import EventHub
from backend.app.services.product_intelligence import (
    ProductAlreadyCollected,
    ProductIntelligenceService,
    ProductOwnershipRestricted,
)


class FakeProductAdapter:
    def __init__(self, raw: dict) -> None:
        self.own_user_id = "seller"
        self.raw = {**raw}
        self.raw.setdefault("trackParams", {"sellerId": "seller"})
        self.calls: list[str] = []

    async def fetch_item(self, item_id: str) -> ItemInfo:
        self.calls.append(item_id)
        return ItemInfo(
            external_id=item_id,
            title=str(self.raw.get("title") or "测试商品"),
            price=f"¥{self.raw.get('soldPrice', 100)}",
            description=str(self.raw.get("desc") or "商品说明"),
            seller_id=str(self.raw.get("trackParams", {}).get("sellerId") or "") or None,
            raw=self.raw,
        )


def build_service(tmp_path: Path, raw: dict) -> tuple[Database, FakeProductAdapter, ProductIntelligenceService]:
    database = Database(f"sqlite:///{tmp_path / 'products.db'}")
    database.create_all()
    adapter = FakeProductAdapter(raw)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'products.db'}",
        xianyu_cookie=SecretStr("unb=seller; _m_h5_tk=token_suffix"),
        product_collection_request_delay_seconds=0,
        product_collection_check_interval_seconds=60,
    )
    return database, adapter, ProductIntelligenceService(
        database, adapter, settings, EventHub()
    )


def seed_item(database: Database, raw: dict, *, external_id: str = "123456789") -> int:
    stored_raw = {**raw}
    stored_raw.setdefault("trackParams", {"sellerId": "seller"})
    with database.session() as session:
        item = Item(
            external_id=external_id,
            title=str(stored_raw.get("title") or "测试商品"),
            price=f"¥{stored_raw.get('soldPrice', 100)}",
            description=str(stored_raw.get("desc") or "商品说明"),
            raw_json=json.dumps(stored_raw, ensure_ascii=False),
        )
        session.add(item)
        session.commit()
        return item.id


@pytest.mark.asyncio
async def test_remote_collection_is_limited_to_once_per_local_day(tmp_path: Path) -> None:
    raw = {
        "title": "网站开发",
        "soldPrice": 500,
        "browseCnt": 120,
        "collectCnt": 4,
        "wantCnt": 8,
        "soldCnt": 1,
        "itemStatusStr": "在售",
    }
    database, adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)

    run = await service.collect_today(trigger="manual")

    assert run.status == "success"
    assert run.collected_count == 1
    assert adapter.calls == ["123456789"]
    with pytest.raises(ProductAlreadyCollected):
        await service.collect_today(trigger="manual")
    assert adapter.calls == ["123456789"]


def test_cached_baseline_generates_evidence_based_conversion_advice(tmp_path: Path) -> None:
    raw = {
        "title": "高浏览低咨询商品",
        "soldPrice": 300,
        "browseCnt": 240,
        "collectCnt": 1,
        "wantCnt": 2,
        "soldCnt": 0,
        "itemStatusStr": "在售",
    }
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)

    service.bootstrap_cached_state()
    overview = service.overview()

    assert overview.summary.monitored_products == 1
    assert overview.recommendations[0].strategy_code == "views_no_inquiry"
    assert overview.recommendations[0].confidence == "low"
    assert any("累计浏览 240" in line for line in overview.recommendations[0].evidence)


def test_collection_schedule_uses_beijing_time(tmp_path: Path) -> None:
    raw = {"title": "测试商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)

    overview = service.overview()

    assert overview.collection.timezone == "Asia/Shanghai"
    assert overview.collection.schedule == "每天 08:30（北京时间），每个北京时间自然日最多一次"
    assert overview.collection.next_collection_at is not None
    assert overview.collection.next_collection_at.utcoffset() == timedelta(hours=8)


def test_publish_window_uses_real_inbound_message_times(tmp_path: Path) -> None:
    raw = {"title": "测试商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    item_id = seed_item(database, raw)
    with database.session() as session:
        conversation = Conversation(
            external_id="conversation-product",
            customer_id="buyer",
            customer_name="客户",
            item_id=item_id,
        )
        session.add(conversation)
        session.flush()
        for index in range(12):
            session.add(
                Message(
                    external_id=f"message-{index}",
                    platform_message_id=f"message-{index}",
                    conversation_id=conversation.id,
                    sender_id="buyer",
                    sender_name="客户",
                    direction="inbound",
                    content="可以做网站修改吗",
                    received_at=datetime(2026, 8, 3, 12, index, tzinfo=timezone.utc),
                )
            )
        session.commit()

    overview = service.overview()

    assert overview.publish_timing.sample_size == 12
    assert overview.publish_timing.confidence == "medium"
    assert overview.publish_timing.windows[0].time_range == "20:00–22:00"
    assert overview.demand_opportunities[0].theme in {
        "网站与网页开发",
        "修改、修复与二开",
    }


def test_recording_an_action_never_calls_the_xianyu_adapter(tmp_path: Path) -> None:
    raw = {"title": "测试商品", "browseCnt": 100, "itemStatusStr": "在售"}
    database, adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)
    overview = service.overview()
    recommendation = overview.recommendations[0]

    action = service.create_action(
        recommendation.item_external_id,
        action_type="title",
        status="completed",
        note="我已经手动修改标题",
        cost=0,
        recommendation_id=recommendation.id,
        observation_days=7,
    )

    assert action.note == "我已经手动修改标题"
    assert action.observation_until is not None
    assert adapter.calls == []


def test_cached_items_are_split_into_owned_and_excluded(tmp_path: Path) -> None:
    raw = {"title": "本人商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="owned-12345")
    seed_item(
        database,
        {
            "title": "其他卖家的商品",
            "browseCnt": 99,
            "itemStatusStr": "在售",
            "trackParams": {"sellerId": "another-seller"},
        },
        external_id="other-12345",
    )

    overview = service.overview()

    assert [item.external_id for item in overview.products] == ["owned-12345"]
    assert [item.external_id for item in overview.candidates] == ["other-12345"]
    assert overview.summary.monitored_products == 1
    assert overview.summary.excluded_products == 1
    assert overview.candidates[0].ownership_status == "excluded"
    assert overview.candidates[0].monitoring_enabled is False


@pytest.mark.asyncio
async def test_manual_product_waits_for_remote_owner_verification(tmp_path: Path) -> None:
    raw = {"title": "新商品", "browseCnt": 12, "itemStatusStr": "在售"}
    _database, adapter, service = build_service(tmp_path, raw)

    registered = service.register("manual-12345")
    assert registered.ownership_status == "pending"
    assert registered.monitoring_enabled is False
    with pytest.raises(ProductOwnershipRestricted):
        service.update_monitor("manual-12345", True)

    run = await service.collect_today(trigger="manual")
    product = service.product("manual-12345")

    assert run.collected_count == 1
    assert adapter.calls == ["manual-12345"]
    assert product.ownership_status == "owned"
    assert product.monitoring_enabled is True
    assert product.last_collection_status == "success"


@pytest.mark.asyncio
async def test_empty_item_detail_records_safe_diagnostic(tmp_path: Path) -> None:
    raw = {"title": "暂不可读取商品", "browseCnt": 12, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="missing-12345")

    class MissingItemAdapter:
        own_user_id = "seller"

        async def fetch_item(self, _item_id: str):
            return None

    service.adapter = MissingItemAdapter()
    run = await service.collect_today(trigger="manual")
    product = service.product("missing-12345")

    assert run.status == "failed"
    assert product.last_collection_status == "failed"
    assert product.last_error_code == "item_unavailable"
    assert "下架" in (product.last_error_detail or "")


def test_excluded_product_cannot_be_restored(tmp_path: Path) -> None:
    raw = {
        "title": "其他卖家商品",
        "browseCnt": 12,
        "itemStatusStr": "在售",
        "trackParams": {"sellerId": "another-seller"},
    }
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="excluded-12345")
    service.bootstrap_cached_state()

    with pytest.raises(ProductOwnershipRestricted, match="不能恢复监测"):
        service.update_monitor("excluded-12345", True)
