from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, select

from backend.app.adapters.base import AdapterAccessVerificationError, ItemInfo
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.ledger import LedgerService, RevisionConflict, default_snapshot
from backend.app.models import (
    BusinessExpense,
    BusinessCustomer,
    BusinessProject,
    Conversation,
    Item,
    Message,
    ProductDailySnapshot,
    ProductOperatingPlan,
    ProductOperatingPlanSlot,
    ProductTrafficBatch,
    ProductTrafficBatchEvent,
    ProductTrafficBatchItem,
    ProductTrafficCheckpoint,
    ProductTrafficCheckpointJob,
    ProductTrafficCheckpointJobItem,
    ProductTrafficReminderLog,
    ProductMonitor,
    ProductMarketReminderLog,
    ProductMarketSample,
    ProductMarketSampleResult,
    ProjectSettlementIssueRecord,
)
from backend.app.product_schemas import ProductMarketImportRequest
from backend.app.schema_migrations import (
    migrate_product_browse_accounting_schema,
    migrate_product_traffic_baseline_invalidation_schema,
    migrate_product_traffic_checkpoint_collection_schema,
    migrate_product_traffic_48h_schema,
    migrate_product_traffic_overlap_recording_schema,
)
from backend.app.services.event_hub import EventHub
from backend.app.services.product_intelligence import (
    ProductAlreadyCollected,
    ProductCollectionUnavailable,
    ProductIntelligenceService,
    ProductMarketConflict,
    ProductOwnershipRestricted,
    ProductRecordNotFound,
    ProductTrafficConflict,
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
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    service = ProductIntelligenceService(
        database,
        adapter,
        settings,
        EventHub(),
        ledger=ledger,
    )
    return database, adapter, service


def prepare_service(service: ProductIntelligenceService) -> None:
    """Mirror service startup after each test has seeded its domain state."""

    service.bootstrap_cached_state()
    service._maintain_daily_plans()


def seed_item(
    database: Database,
    raw: dict,
    *,
    external_id: str = "123456789",
    updated_at: datetime | None = None,
    create_monitor: bool = True,
) -> int:
    stored_raw = {**raw}
    stored_raw.setdefault("trackParams", {"sellerId": "seller"})
    with database.session() as session:
        values = {
            "external_id": external_id,
            "title": str(stored_raw.get("title") or "测试商品"),
            "price": f"¥{stored_raw.get('soldPrice', 100)}",
            "description": str(stored_raw.get("desc") or "商品说明"),
            "raw_json": json.dumps(stored_raw, ensure_ascii=False),
        }
        if updated_at is not None:
            values["updated_at"] = updated_at.astimezone(timezone.utc)
        item = Item(
            **values,
        )
        session.add(item)
        session.flush()
        if create_monitor:
            seller_id = str(stored_raw.get("trackParams", {}).get("sellerId") or "")
            owned = seller_id == "seller"
            session.add(
                ProductMonitor(
                    item_id=item.id,
                    source="manual",
                    enabled=owned,
                    ownership_status="owned" if owned else "excluded",
                    ownership_source="test_seed",
                )
            )
        session.commit()
        return item.id


def seed_invalid_actual_traffic_batch(
    database: Database,
    service: ProductIntelligenceService,
    *,
    request_id: str,
    external_ids: list[str],
    started_at: datetime,
) -> str:
    """Create a historical missing-T0 row without using the live-T0 path."""

    created = service.create_traffic_batch(
        request_id=request_id,
        item_external_ids=external_ids,
        planned_at=started_at.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="历史缺失 T0",
    )
    with database.session() as session:
        batch = session.get(ProductTrafficBatch, created.id)
        assert batch is not None
        batch.status = "invalidated"
        batch.started_at = started_at.astimezone(timezone.utc)
        batch.invalidated_at = started_at.astimezone(timezone.utc)
        batch.invalidation_reason = "missing_baseline"
        batch.recording_mode = "actual_now"
        batch.observation_window_hours = 48
        batch.baseline_prepared_at = None
        for item in session.scalars(
            select(ProductTrafficBatchItem).where(
                ProductTrafficBatchItem.batch_id == batch.id
            )
        ).all():
            item.baseline_browse_count = 0
            item.baseline_collect_count = 0
            item.baseline_want_count = 0
            item.baseline_inquiry_count = 0
            item.baseline_captured_at = None
            item.baseline_source = "missing"
        session.commit()
    return created.id


def seed_market_benchmark(
    database: Database,
    *,
    keyword: str,
    fixed: datetime,
    title_prefix: str = "网站功能修改",
) -> None:
    price_rows = ((80, 90, 100), (90, 100, 110), (100, 110, 120))
    with database.session() as session:
        for offset, prices in ((2, price_rows[0]), (1, price_rows[1]), (0, price_rows[2])):
            day = (fixed.date() - timedelta(days=offset)).isoformat()
            sample = ProductMarketSample(
                id=f"benchmark-{offset}-{abs(hash(keyword))}",
                keyword=keyword,
                sample_date=day,
                source="edge_codex",
                captured_at=(fixed - timedelta(days=offset)).astimezone(timezone.utc),
                result_count=3,
                note="隔离测试市场参考",
            )
            session.add(sample)
            session.flush()
            result_rows = (
                (1, f"{title_prefix} Vue 前端 交付", prices[0], ["技术服务", "可验收"]),
                (4, f"{title_prefix} 响应式开发 API 验收", prices[1], ["技术服务"]),
                (9, f"{title_prefix} 定制开发 第{offset + 1}天", prices[2], ["定制开发"]),
            )
            for position, title, price, tags in result_rows:
                session.add(
                    ProductMarketSampleResult(
                        sample_id=sample.id,
                        position=position,
                        title=title,
                        price=price,
                        tags_json=json.dumps(tags, ensure_ascii=False),
                    )
                )
        session.commit()


def seed_snapshot_history(
    database: Database,
    *,
    item_id: int,
    fixed: datetime,
    title: str,
    price: float,
    current_browse: int,
    current_inquiries: int,
) -> None:
    with database.session() as session:
        current = (
            session.query(ProductDailySnapshot)
            .filter(
                ProductDailySnapshot.item_id == item_id,
                ProductDailySnapshot.snapshot_date == fixed.date().isoformat(),
            )
            .one_or_none()
        )
        assert current is not None
        current.title = title
        current.price = price
        current.raw_browse_count = current_browse
        current.collection_views_excluded = 0
        current.browse_count = current_browse
        current.inquiry_count = current_inquiries
        current.converted_project_count = 0
        for offset in range(1, 7):
            session.add(
                ProductDailySnapshot(
                    item_id=item_id,
                    snapshot_date=(fixed.date() - timedelta(days=offset)).isoformat(),
                    source="test_history",
                    title=title,
                    price=price,
                    status="在售",
                    raw_browse_count=max(0, current_browse - offset * 8),
                    browse_count=max(0, current_browse - offset * 8),
                    inquiry_count=max(0, current_inquiries - 1),
                    converted_project_count=0,
                    captured_at=(fixed - timedelta(days=offset)).astimezone(timezone.utc),
                )
            )
        session.commit()


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


@pytest.mark.asyncio
async def test_manual_single_refresh_is_available_after_daily_collection(tmp_path: Path) -> None:
    raw = {
        "title": "可手动刷新的商品",
        "soldPrice": 300,
        "browseCnt": 12,
        "itemStatusStr": "在售",
    }
    database, adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)

    await service.collect_today(trigger="scheduled")
    adapter.raw["browseCnt"] = 21
    manual = await service.collect_manual("123456789")
    product = service.product("123456789")
    overview = service.overview()

    assert manual.trigger == "manual_single"
    assert manual.status == "success"
    assert manual.collected_count == 1
    assert adapter.calls == ["123456789", "123456789"]
    assert product.raw_browse_count == 21
    assert product.collection_views_excluded == 2
    assert product.browse_count == 19
    assert len(product.history) == 1
    assert product.history[0].source == "remote_manual"
    assert product.history[0].raw_browse_count == 21
    assert product.history[0].collection_views_excluded == 2
    assert overview.collection.latest_attempt is not None
    assert overview.collection.latest_attempt.trigger == "manual_single"
    assert overview.collection.latest_attempt.status == "success"
    assert len(overview.collection.attempts) == 2
    assert overview.collection.last_run is not None
    assert overview.collection.last_run.trigger == "scheduled"


@pytest.mark.asyncio
async def test_same_day_remote_reads_do_not_create_fake_browse_growth(
    tmp_path: Path,
) -> None:
    raw = {
        "title": "采集自访问测试",
        "browseCnt": 12,
        "itemStatusStr": "在售",
    }
    database, adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)

    await service.collect_today(trigger="scheduled")
    first = service.product("123456789")
    adapter.raw["browseCnt"] = 13
    await service.collect_manual("123456789")
    second = service.product("123456789")

    assert first.raw_browse_count == 12
    assert first.collection_views_excluded == 1
    assert first.browse_count == 11
    assert second.raw_browse_count == 13
    assert second.collection_views_excluded == 2
    assert second.browse_count == 11
    assert len(second.history) == 1


@pytest.mark.asyncio
async def test_later_manual_success_becomes_current_without_deleting_daily_failure(
    tmp_path: Path,
) -> None:
    raw = {"title": "恢复测试商品", "browseCnt": 8, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)

    class FailingAdapter:
        own_user_id = "seller"

        async def fetch_item(self, _item_id: str):
            raise AdapterAccessVerificationError("raw verification response")

    service.adapter = FailingAdapter()
    daily = await service.collect_today(trigger="scheduled")
    service.adapter = FakeProductAdapter(raw)
    manual = await service.collect_manual("123456789")
    overview = service.overview()

    assert daily.status == "failed"
    assert manual.status == "success"
    assert overview.collection.last_run is not None
    assert overview.collection.last_run.status == "failed"
    assert overview.collection.latest_attempt is not None
    assert overview.collection.latest_attempt.trigger == "manual_single"
    assert overview.collection.latest_attempt.status == "success"
    assert any(attempt.status == "failed" for attempt in overview.collection.attempts)
    assert all(
        "raw verification response" not in attempt.detail
        for attempt in overview.collection.attempts
    )


@pytest.mark.asyncio
async def test_manual_single_does_not_consume_the_daily_batch(tmp_path: Path) -> None:
    raw = {"title": "先手动后自动", "browseCnt": 8, "itemStatusStr": "在售"}
    database, adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)

    manual = await service.collect_manual("123456789")
    daily = await service.collect_today(trigger="scheduled")

    assert manual.status == "success"
    assert daily.status == "success"
    assert adapter.calls == ["123456789", "123456789"]


@pytest.mark.asyncio
async def test_manual_all_only_reads_enabled_owned_products(tmp_path: Path) -> None:
    raw = {"title": "本人商品", "browseCnt": 8, "itemStatusStr": "在售"}
    database, adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="owned-11111")
    seed_item(
        database,
        {
            "title": "其他卖家的商品",
            "browseCnt": 18,
            "itemStatusStr": "在售",
            "trackParams": {"sellerId": "another-seller"},
        },
        external_id="other-22222",
    )
    service.bootstrap_cached_state()

    result = await service.collect_manual()

    assert result.trigger == "manual_all"
    assert result.monitored_count == 1
    assert adapter.calls == ["owned-11111"]
    with pytest.raises(ProductOwnershipRestricted):
        await service.collect_manual("other-22222")


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

    prepare_service(service)
    overview = service.overview()

    assert overview.summary.monitored_products == 1
    assert overview.recommendations[0].strategy_code == "views_no_inquiry"
    assert overview.recommendations[0].confidence == "low"
    assert overview.products[0].raw_browse_count == 240
    assert overview.products[0].collection_views_excluded == 0
    assert overview.products[0].browse_count == 240
    assert any("经营浏览 240" in line for line in overview.recommendations[0].evidence)


def test_browse_accounting_history_backfill_is_idempotent(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-browse.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE product_daily_snapshots ("
            "id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, "
            "snapshot_date VARCHAR(10) NOT NULL, source VARCHAR(32) NOT NULL, "
            "browse_count INTEGER NOT NULL, captured_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO product_daily_snapshots "
            "(id, item_id, snapshot_date, source, browse_count, captured_at) VALUES "
            "(1, 10, '2026-08-08', 'cached_baseline', 10, '2026-08-08 08:00:00'),"
            "(2, 10, '2026-08-09', 'remote_daily', 11, '2026-08-09 08:30:00'),"
            "(3, 10, '2026-08-10', 'remote_manual', 12, '2026-08-10 10:00:00'),"
            "(4, 20, '2026-08-10', 'test_history', 7, '2026-08-10 11:00:00')"
        )
        assert migrate_product_browse_accounting_schema(connection) is True
        first = list(
            connection.exec_driver_sql(
                "SELECT id, raw_browse_count, collection_views_excluded, "
                "browse_count FROM product_daily_snapshots ORDER BY id"
            )
        )
        assert first == [
            (1, 10, 0, 10),
            (2, 11, 1, 10),
            (3, 12, 2, 10),
            (4, 7, 0, 7),
        ]
        assert migrate_product_browse_accounting_schema(connection) is False
        second = list(
            connection.exec_driver_sql(
                "SELECT id, raw_browse_count, collection_views_excluded, "
                "browse_count FROM product_daily_snapshots ORDER BY id"
            )
        )
        assert second == first


def test_delivery_load_excludes_terminal_settlement_projects(tmp_path: Path) -> None:
    raw = {"title": "测试商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)
    with database.session() as session:
        session.add(BusinessCustomer(id="customer-active", name="有效客户"))
        session.add(BusinessCustomer(id="customer-ended", name="终止客户"))
        session.add(
            BusinessProject(
                id="project-active",
                name="有效合作",
                customer_id="customer-active",
                status="in_progress",
            )
        )
        session.add(
            BusinessProject(
                id="project-ended",
                name="已终止合作",
                customer_id="customer-ended",
                status="in_progress",
            )
        )
        session.add(
            ProjectSettlementIssueRecord(
                id="issue-ended",
                project_id="project-ended",
                customer_id="customer-ended",
                issue_type="cooperation_terminated",
                occurred_at="2026-08-08T10:00:00+08:00",
                reason="双方确认停止合作",
                request_id="request-ended",
            )
        )
        session.commit()

    prepare_service(service)
    overview = service.overview()

    assert overview.summary.active_projects == 1
    assert all("2/" not in line for item in overview.recommendations for line in item.evidence)


def test_collection_schedule_uses_beijing_time(tmp_path: Path) -> None:
    raw = {"title": "测试商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)
    prepare_service(service)

    overview = service.overview()

    assert overview.collection.timezone == "Asia/Shanghai"
    assert overview.collection.schedule == "自动采集每天 08:30（北京时间）；也可手动采集全部或指定商品"
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

    prepare_service(service)
    overview = service.overview()

    # Repeated follow-up messages from one customer count as one timing sample.
    assert overview.publish_timing.sample_size == 1
    assert overview.publish_timing.confidence == "low"
    assert overview.publish_timing.windows[0].time_range == "20:00–22:00"
    assert overview.demand_opportunities[0].theme in {
        "网站与网页开发",
        "修改、修复与二开",
    }


def test_recording_an_action_never_calls_the_xianyu_adapter(tmp_path: Path) -> None:
    raw = {"title": "测试商品", "browseCnt": 100, "itemStatusStr": "在售"}
    database, adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)
    prepare_service(service)
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

    prepare_service(service)
    overview = service.overview()

    assert [item.external_id for item in overview.products] == ["owned-12345"]
    assert [item.external_id for item in overview.candidates] == ["other-12345"]
    assert overview.summary.monitored_products == 1
    assert overview.summary.excluded_products == 1
    assert overview.candidates[0].ownership_status == "excluded"
    assert overview.candidates[0].monitoring_enabled is False


def test_conversation_discovery_never_auto_enables_collection(tmp_path: Path) -> None:
    raw = {"title": "会话中新出现的本人商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    item_id = seed_item(
        database,
        raw,
        external_id="conversation-owned-12345",
        create_monitor=False,
    )

    service.bootstrap_cached_state()

    with database.session() as session:
        monitor = session.scalar(
            select(ProductMonitor).where(ProductMonitor.item_id == item_id)
        )
        assert monitor is not None
        assert monitor.source == "conversation"
        assert monitor.ownership_status == "owned"
        assert monitor.enabled is False
    service._maintain_daily_plans()
    assert service.overview().summary.monitored_products == 0


def test_legacy_pending_registration_bypass_is_removed(tmp_path: Path) -> None:
    raw = {"title": "新商品", "browseCnt": 12, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)

    assert not hasattr(service, "register")
    with database.session() as session:
        assert session.scalar(
            select(Item).where(Item.external_id == "manual-12345")
        ) is None


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


@pytest.mark.asyncio
async def test_access_verification_records_safe_diagnostic(tmp_path: Path) -> None:
    raw = {"title": "需要访问验证的商品", "browseCnt": 12, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="verify-12345")

    class VerificationAdapter:
        own_user_id = "seller"

        async def fetch_item(self, _item_id: str):
            raise AdapterAccessVerificationError("sensitive platform response")

    service.adapter = VerificationAdapter()
    run = await service.collect_today(trigger="manual")
    product = service.product("verify-12345")

    assert run.status == "failed"
    assert product.last_collection_status == "failed"
    assert product.last_error_code == "access_verification"
    assert "本批次已停止后续请求" in (product.last_error_detail or "")
    assert "先手动采集单件商品" in (product.last_error_detail or "")
    assert "sensitive platform response" not in (product.last_error_detail or "")
    assert "1 个未取得当日数据" in run.detail


@pytest.mark.asyncio
async def test_daily_collection_stops_batch_after_first_access_verification(
    tmp_path: Path,
) -> None:
    raw = {"title": "批量验证商品", "browseCnt": 12, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    external_ids = ["verify-batch-1", "verify-batch-2", "verify-batch-3"]
    for external_id in external_ids:
        seed_item(database, raw, external_id=external_id)

    class VerificationAdapter:
        own_user_id = "seller"

        def __init__(self) -> None:
            self.calls: list[str] = []

        async def fetch_item(self, item_id: str):
            self.calls.append(item_id)
            raise AdapterAccessVerificationError("raw platform verification body")

    adapter = VerificationAdapter()
    service.adapter = adapter
    run = await service.collect_today(trigger="scheduled")
    products = [service.product(external_id) for external_id in external_ids]

    assert adapter.calls == [external_ids[0]]
    assert run.status == "failed"
    assert run.monitored_count == 3
    assert run.collected_count == 0
    assert run.failed_count == 1
    assert products[0].last_collection_status == "failed"
    assert products[0].last_error_code == "access_verification"
    assert all(product.last_collection_status == "skipped" for product in products[1:])
    assert all(
        product.last_error_code == "access_verification_batch_stopped"
        for product in products[1:]
    )
    assert all(product.last_attempt_at is None for product in products[1:])
    assert "1 个触发访问验证" in run.detail
    assert "2 个为保护账号而跳过" in run.detail
    assert "raw platform verification body" not in run.detail
    attempt = service.overview().collection.latest_attempt
    assert attempt is not None
    assert [item.status for item in attempt.items] == ["failed", "skipped", "skipped"]
    assert all("raw platform verification body" not in item.detail for item in attempt.items)


@pytest.mark.asyncio
async def test_manual_all_stops_batch_after_first_access_verification(
    tmp_path: Path,
) -> None:
    raw = {"title": "手动批量验证商品", "browseCnt": 12, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    external_ids = ["manual-verify-1", "manual-verify-2", "manual-verify-3"]
    for external_id in external_ids:
        seed_item(database, raw, external_id=external_id)

    class VerificationAdapter:
        own_user_id = "seller"

        def __init__(self) -> None:
            self.calls: list[str] = []

        async def fetch_item(self, item_id: str):
            self.calls.append(item_id)
            raise AdapterAccessVerificationError("raw manual verification body")

    adapter = VerificationAdapter()
    service.adapter = adapter
    run = await service.collect_manual()
    products = [service.product(external_id) for external_id in external_ids]

    assert adapter.calls == [external_ids[0]]
    assert run.trigger == "manual_all"
    assert run.status == "failed"
    assert run.monitored_count == 3
    assert run.failed_count == 1
    assert products[0].last_collection_status == "failed"
    assert all(product.last_collection_status == "skipped" for product in products[1:])
    assert "1 个触发访问验证" in run.detail
    assert "2 个为保护账号而跳过" in run.detail
    assert "raw manual verification body" not in run.detail


def test_excluded_product_cannot_be_restored(tmp_path: Path) -> None:
    raw = {
        "title": "其他卖家商品",
        "browseCnt": 12,
        "itemStatusStr": "在售",
        "trackParams": {"sellerId": "another-seller"},
    }
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="excluded-12345")
    prepare_service(service)

    with pytest.raises(ProductOwnershipRestricted, match="不能恢复监测"):
        service.update_monitor("excluded-12345", True)


def test_batch_disable_is_atomic_reversible_and_keeps_history(tmp_path: Path) -> None:
    raw = {"title": "批量移出测试商品", "browseCnt": 12, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    first_id = seed_item(database, raw, external_id="disable-batch-1")
    second_id = seed_item(database, raw, external_id="disable-batch-2")
    service.bootstrap_cached_state()
    with database.session() as session:
        snapshot_count = session.query(ProductDailySnapshot).count()

    result = service.disable_monitors(["disable-batch-1", "disable-batch-2"])
    repeated = service.disable_monitors(["disable-batch-1", "disable-batch-2"])

    assert result == {
        "disabled_external_ids": ["disable-batch-1", "disable-batch-2"],
        "disabled_count": 2,
    }
    assert repeated["disabled_count"] == 0
    with database.session() as session:
        monitors = session.scalars(
            select(ProductMonitor).where(ProductMonitor.item_id.in_([first_id, second_id]))
        ).all()
        assert all(monitor.enabled is False for monitor in monitors)
        assert session.query(ProductDailySnapshot).count() == snapshot_count

    service.update_monitor("disable-batch-1", True)
    with pytest.raises(ProductRecordNotFound, match="刷新后重试"):
        service.disable_monitors(["disable-batch-1", "missing-product"])
    assert service.product("disable-batch-1").monitoring_enabled is True


def test_rolling_plan_uses_multi_product_batches_and_rotates_for_cooldown(
    tmp_path: Path,
) -> None:
    raw = {"title": "服务商品", "browseCnt": 10, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    for index in range(8):
        seed_item(
            database,
            {**raw, "title": f"服务商品 {index}"},
            external_id=f"owned-plan-{index}",
        )

    prepare_service(service)
    overview = service.overview()
    traffic_slots = [
        slot for slot in overview.operating_plan.slots if slot.action_type == "traffic"
    ]

    assert traffic_slots
    assert all(3 <= len(slot.products) <= 5 for slot in traffic_slots)
    assert all(slot.planned_cost == pytest.approx(5.9) for slot in traffic_slots)
    for earlier, later in zip(traffic_slots, traffic_slots[1:]):
        earlier_ids = {product.external_id for product in earlier.products}
        later_ids = {product.external_id for product in later.products}
        earlier_day = datetime.fromisoformat(earlier.date)
        later_day = datetime.fromisoformat(later.date)
        if (later_day - earlier_day).total_seconds() < 72 * 3600:
            assert earlier_ids.isdisjoint(later_ids)
    assert overview.operating_plan.analysis_stage == "baseline_learning"
    assert overview.operating_plan.weekly_budget == pytest.approx(24)


def test_multi_product_batch_tracks_one_cost_and_long_tail_checkpoints(
    tmp_path: Path,
) -> None:
    raw = {"title": "服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, {**raw, "title": "商品 A"}, external_id="batch-item-a")
    seed_item(database, {**raw, "title": "商品 B"}, external_id="batch-item-b")
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 11, 8, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    planned_at = fixed.astimezone(timezone.utc) + timedelta(hours=2)

    batch = service.create_traffic_batch(
        request_id="request-batch-0001",
        item_external_ids=["batch-item-a", "batch-item-b"],
        planned_at=planned_at,
        actual_cost=5.9,
        plan_slot_id=None,
        note="两件商品共用一次套餐",
    )
    started = service.start_traffic_batch(batch.id)
    with database.session() as session:
        stored_batch = session.get(ProductTrafficBatch, batch.id)
        assert stored_batch is not None
        stored_batch.started_at = fixed.astimezone(timezone.utc)
        for batch_item in session.query(ProductTrafficBatchItem).filter_by(batch_id=batch.id):
            batch_item.baseline_captured_at = fixed.astimezone(timezone.utc)
            batch_item.baseline_source = "manual"
        session.commit()
    completed = service.complete_traffic_batch(
        batch.id,
        completed_at=fixed.astimezone(timezone.utc) + timedelta(hours=1),
        actual_cost=6,
        total_exposure=1_200,
        note="套餐在一小时内完成",
    )

    assert started.started_at is not None
    assert completed.actual_cost == pytest.approx(6)
    assert completed.total_exposure == 1_200
    assert all(not hasattr(item, "cost") for item in completed.products)

    values = [
        {
            "external_id": item.external_id,
            "browse_count": item.baseline_browse_count + 6,
            "collect_count": item.baseline_collect_count,
            "want_count": item.baseline_want_count + 1,
            "inquiry_count": item.baseline_inquiry_count,
        }
        for item in completed.products
    ]
    h1_recorded_at = fixed.astimezone(timezone.utc) + timedelta(hours=1)
    service._now = lambda: fixed + timedelta(hours=1)  # type: ignore[method-assign]
    service.record_traffic_checkpoint(
        batch.id,
        checkpoint="h1",
        recorded_at=h1_recorded_at,
        items=values,
        note="一小时只有浏览变化",
    )
    values[0]["inquiry_count"] += 1
    h24_recorded_at = fixed.astimezone(timezone.utc) + timedelta(hours=24)
    service._now = lambda: fixed + timedelta(hours=24)  # type: ignore[method-assign]
    service.record_traffic_checkpoint(
        batch.id,
        checkpoint="h24",
        recorded_at=h24_recorded_at,
        items=values,
        note="24 小时后出现咨询",
    )
    h72_recorded_at = fixed.astimezone(timezone.utc) + timedelta(hours=72)
    service._now = lambda: fixed + timedelta(hours=72)  # type: ignore[method-assign]
    closed = service.record_traffic_checkpoint(
        batch.id,
        checkpoint="h72",
        recorded_at=h72_recorded_at,
        items=values,
        note="72 小时完成观察",
    )

    assert closed.status == "closed"
    assert closed.completed_checkpoints == ["h1", "h24", "h72"]
    assert closed.products[0].inquiry_delta == 1
    first_product = closed.products[0]
    assert [value.checkpoint for value in first_product.checkpoints] == [
        "h1",
        "h24",
        "h72",
    ]
    assert [value.hours for value in first_product.checkpoints] == [1, 24, 72]
    assert first_product.checkpoints[0].browse_count == (
        first_product.baseline_browse_count + 6
    )
    assert first_product.checkpoints[0].browse_delta == 6
    assert first_product.checkpoints[0].inquiry_delta == 0
    assert first_product.checkpoints[1].inquiry_count == (
        first_product.baseline_inquiry_count + 1
    )
    assert first_product.checkpoints[1].inquiry_delta == 1
    assert service._utc(first_product.checkpoints[0].recorded_at) == h1_recorded_at
    assert all(
        value.checkpoint != "h6" for value in first_product.checkpoints
    )
    overview = service.overview()
    assert overview.traffic_summary.effective_batch_count == 1
    assert "达到 6 个" in overview.traffic_summary.analysis_summary


def test_checkpoint_rejects_early_and_future_timestamp(tmp_path: Path) -> None:
    raw = {"title": "检查点时钟", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="checkpoint-clock-item")
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 12, 16, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    batch = service.create_traffic_batch(
        request_id="request-checkpoint-clock",
        item_external_ids=["checkpoint-clock-item"],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="时间门槛",
    )
    started = service.start_traffic_batch(batch.id)
    with database.session() as session:
        stored = session.get(ProductTrafficBatch, batch.id)
        assert stored is not None
        stored.started_at = fixed.astimezone(timezone.utc)
        session.commit()
    values = [{
        "external_id": "checkpoint-clock-item",
        "browse_count": started.products[0].baseline_browse_count,
        "collect_count": started.products[0].baseline_collect_count,
        "want_count": started.products[0].baseline_want_count,
        "inquiry_count": started.products[0].baseline_inquiry_count,
    }]
    with pytest.raises(ProductTrafficConflict, match="最早可在北京时间"):
        service.record_traffic_checkpoint(
            batch.id,
            checkpoint="h24",
            recorded_at=fixed.astimezone(timezone.utc),
            items=values,
            note="不能提前",
        )
    service._now = lambda: fixed + timedelta(hours=24)  # type: ignore[method-assign]
    with pytest.raises(ProductTrafficConflict, match="不能晚于当前北京时间"):
        service.record_traffic_checkpoint(
            batch.id,
            checkpoint="h24",
            recorded_at=(fixed + timedelta(hours=25)).astimezone(timezone.utc),
            items=values,
            note="不能未来记账",
        )


def test_stale_t0_is_terminally_invalidated_without_deleting_facts(tmp_path: Path) -> None:
    raw = {"title": "T0 质量测试", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="stale-t0-item")
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 12, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    batch = service.create_traffic_batch(
        request_id="request-stale-t0",
        item_external_ids=["stale-t0-item"],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="旧基线",
    )
    started = service.start_traffic_batch(batch.id)
    with database.session() as session:
        stored = session.get(ProductTrafficBatch, batch.id)
        assert stored is not None
        stored.started_at = fixed.astimezone(timezone.utc)
        batch_item = session.query(ProductTrafficBatchItem).filter_by(batch_id=batch.id).one()
        batch_item.baseline_captured_at = (
            fixed - timedelta(hours=7, minutes=12)
        ).astimezone(timezone.utc)
        batch_item.baseline_source = "manual"
        session.commit()
    assert service._invalidate_unusable_traffic_baselines() == [batch.id]
    viewed = service.overview().traffic_batches[0]
    assert viewed.baseline_age_minutes == 432
    assert viewed.status == "invalidated"
    assert viewed.invalidation_reason == "stale_baseline"
    assert viewed.baseline_quality == "invalidated"
    assert viewed.data_quality == "invalidated"
    assert viewed.due_checkpoint is None
    assert viewed.analysis_eligible is False
    analytics = service.overview().exposure_analytics
    assert analytics.eligible_batch_count == 0
    assert analytics.excluded_batch_count == 1
    assert "已终止批次无需继续补录" in analytics.summary
    assert "先补齐长尾检查点" not in analytics.summary
    assert "另有 1 批" not in analytics.summary
    with pytest.raises(ProductTrafficConflict, match="终止观察"):
        service.record_traffic_checkpoint(
            batch.id,
            checkpoint="h24",
            recorded_at=(fixed + timedelta(hours=24)).astimezone(timezone.utc),
            items=[],
            note="不得继续写入",
        )
    with pytest.raises(ProductTrafficConflict, match="保留终止状态"):
        service.cancel_traffic_batch(batch.id)
    with pytest.raises(ProductTrafficConflict, match="终止观察"):
        service.complete_traffic_batch(
            batch.id,
            completed_at=None,
            actual_cost=5.9,
            total_exposure=900,
            note="不得覆盖终止状态",
        )


def test_baseline_invalidation_schema_is_additive_and_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-baseline-invalidation.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE product_traffic_batches ("
            "id VARCHAR(128) PRIMARY KEY, status VARCHAR(32) NOT NULL)"
        )
        connection.execute(
            "INSERT INTO product_traffic_batches (id, status) VALUES (?, ?)",
            ("legacy-batch", "observing"),
        )
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        assert migrate_product_traffic_baseline_invalidation_schema(connection) is True
        assert migrate_product_traffic_baseline_invalidation_schema(connection) is False
        row = connection.exec_driver_sql(
            "SELECT status, invalidated_at, invalidation_reason "
            "FROM product_traffic_batches WHERE id='legacy-batch'"
        ).one()
    assert tuple(row) == ("observing", None, None)


def test_checkpoint_collection_schema_is_additive_and_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-checkpoint-jobs.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, external_id VARCHAR(128))"
        )
        connection.execute(
            "CREATE TABLE product_traffic_batches ("
            "id VARCHAR(128) PRIMARY KEY, status VARCHAR(32) NOT NULL)"
        )
        connection.execute(
            "INSERT INTO product_traffic_batches (id, status) VALUES (?, ?)",
            ("legacy-batch", "observing"),
        )
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        assert migrate_product_traffic_checkpoint_collection_schema(connection) is True
        assert migrate_product_traffic_checkpoint_collection_schema(connection) is False
        mode = connection.exec_driver_sql(
            "SELECT checkpoint_collection_mode FROM product_traffic_batches "
            "WHERE id='legacy-batch'"
        ).scalar_one()
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert mode == "auto"
    assert {
        "product_traffic_checkpoint_jobs",
        "product_traffic_checkpoint_job_items",
    }.issubset(tables)


def test_traffic_48h_startup_migration_defaults_legacy_rows_and_is_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-traffic-48h.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE product_traffic_batches ("
            "id VARCHAR(128) PRIMARY KEY, status VARCHAR(32) NOT NULL)"
        )
        connection.execute(
            "INSERT INTO product_traffic_batches (id, status) VALUES (?, ?)",
            ("legacy-batch", "closed"),
        )
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        assert migrate_product_traffic_48h_schema(connection) is True
        assert migrate_product_traffic_48h_schema(connection) is False
        window = connection.exec_driver_sql(
            "SELECT observation_window_hours FROM product_traffic_batches "
            "WHERE id='legacy-batch'"
        ).scalar_one()
    assert window == 72


def test_traffic_48h_startup_migration_rejects_partial_column(
    tmp_path: Path,
) -> None:
    path = tmp_path / "partial-traffic-48h.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE product_traffic_batches ("
            "id VARCHAR(128) PRIMARY KEY, "
            "observation_window_hours INTEGER)"
        )
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection, pytest.raises(
        RuntimeError,
        match="must be INTEGER NOT NULL DEFAULT 72",
    ):
        migrate_product_traffic_48h_schema(connection)


@pytest.mark.asyncio
async def test_invalid_baselines_cover_missing_legacy_and_broken_time_without_reminders(
    tmp_path: Path,
) -> None:
    raw = {"title": "无效基线矩阵", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    ids = ["invalid-missing", "invalid-legacy", "invalid-after-start"]
    for external_id in ids:
        seed_item(database, raw, external_id=external_id)
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 13, 16, 20, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    expected = {
        ids[0]: "missing_baseline",
        ids[1]: "legacy_baseline",
        ids[2]: "invalid_baseline_time",
    }
    batch_by_item: dict[str, str] = {}
    with database.session() as session:
        for index, external_id in enumerate(ids):
            item = session.scalar(select(Item).where(Item.external_id == external_id))
            assert item is not None
            batch = ProductTrafficBatch(
                id=f"invalid-matrix-{index}",
                request_id=f"invalid-matrix-request-{index}",
                status="observing",
                planned_at=(fixed - timedelta(hours=1)).astimezone(timezone.utc),
                started_at=fixed.astimezone(timezone.utc),
                actual_cost=6,
                note="保留真实事实",
            )
            session.add(batch)
            session.flush()
            baseline_source = "missing" if index == 0 else "legacy_snapshot" if index == 1 else "manual"
            captured_at = None if index == 0 else (fixed - timedelta(minutes=5)).astimezone(timezone.utc) if index == 1 else (fixed + timedelta(minutes=1)).astimezone(timezone.utc)
            session.add(
                ProductTrafficBatchItem(
                    batch_id=batch.id,
                    item_id=item.id,
                    position=0,
                    baseline_browse_count=20,
                    baseline_collect_count=0,
                    baseline_want_count=0,
                    baseline_inquiry_count=0,
                    baseline_captured_at=captured_at,
                    baseline_source=baseline_source,
                )
            )
            batch_by_item[external_id] = batch.id
        session.commit()

    changed = set(service._invalidate_unusable_traffic_baselines())
    assert changed == set(batch_by_item.values())
    await service._dispatch_due_traffic_reminders()

    with database.session() as session:
        assert session.query(ProductTrafficReminderLog).count() == 0
        for external_id, batch_id in batch_by_item.items():
            stored = session.get(ProductTrafficBatch, batch_id)
            assert stored is not None
            assert stored.status == "invalidated"
            assert stored.invalidation_reason == expected[external_id]
            assert session.query(ProductTrafficBatchEvent).filter_by(
                request_id=f"traffic-auto-invalidate-{batch_id}"
            ).count() == 1
    assert service._invalidate_unusable_traffic_baselines() == []


def test_expired_planned_t0_can_be_prepared_again_and_is_not_invalidated(
    tmp_path: Path,
) -> None:
    raw = {"title": "计划批次 T0 过期", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="planned-expired-t0")
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 13, 16, 20, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    batch = service.create_traffic_batch(
        request_id="planned-expired-create",
        item_external_ids=["planned-expired-t0"],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="过期后重新准备",
    )
    with database.session() as session:
        stored = session.get(ProductTrafficBatch, batch.id)
        assert stored is not None
        stored.baseline_prepared_at = (fixed - timedelta(minutes=31)).astimezone(timezone.utc)
        batch_item = session.query(ProductTrafficBatchItem).filter_by(batch_id=batch.id).one()
        batch_item.baseline_captured_at = stored.baseline_prepared_at
        batch_item.baseline_source = "manual"
        session.commit()

    assert service._invalidate_unusable_traffic_baselines() == []
    viewed = next(value for value in service.overview().traffic_batches if value.id == batch.id)
    assert viewed.status == "planned"
    assert viewed.baseline_status == "expired"
    assert viewed.invalidated_at is None


def test_reliable_manual_overlap_baseline_keeps_factual_observation_open(
    tmp_path: Path,
) -> None:
    raw = {"title": "人工重叠 T0", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="manual-overlap-stays-open")
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 13, 16, 20, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    first = service.create_traffic_batch(
        request_id="manual-overlap-source",
        item_external_ids=["manual-overlap-stays-open"],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=6,
        plan_slot_id=None,
        note="来源",
    )
    service.start_traffic_batch(first.id)
    service._now = lambda: fixed + timedelta(hours=2)  # type: ignore[method-assign]
    second = service.create_traffic_batch(
        request_id="manual-overlap-target",
        item_external_ids=["manual-overlap-stays-open"],
        planned_at=(fixed + timedelta(hours=2)).astimezone(timezone.utc),
        actual_cost=6,
        plan_slot_id=None,
        note="已有完整人工 T0",
    )
    recorded = service.record_actual_overlap_start(
        second.id,
        request_id="manual-overlap-actual-start",
        expected_updated_at=second.updated_at,
        actual_started_at=None,
        confirmed_already_purchased=True,
        items=[{
            "external_id": "manual-overlap-stays-open",
            "browse_count": 20,
            "collect_count": 0,
            "want_count": 0,
            "inquiry_count": 0,
        }],
    )
    invalidated = service._invalidate_unusable_traffic_baselines()
    assert second.id not in invalidated
    current = next(value for value in service.overview().traffic_batches if value.id == second.id)
    assert current.status == "running"
    assert current.attribution_status == "overlap"
    assert current.has_reliable_baseline is True
    assert current.analysis_eligible is False


def test_invalidated_batch_preserves_raw_checkpoints_but_never_derives_lift(
    tmp_path: Path,
) -> None:
    raw = {"title": "无效增量不得派生", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="invalidated-no-delta")
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 13, 16, 20, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    batch = service.create_traffic_batch(
        request_id="invalidated-no-delta-create",
        item_external_ids=["invalidated-no-delta"],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=6,
        plan_slot_id=None,
        note="历史事实",
    )
    started = service.start_traffic_batch(batch.id)
    product = started.products[0]
    with database.session() as session:
        stored = session.get(ProductTrafficBatch, batch.id)
        assert stored is not None
        stored.status = "invalidated"
        stored.invalidated_at = fixed.astimezone(timezone.utc)
        stored.invalidation_reason = "legacy_baseline"
        batch_item = session.query(ProductTrafficBatchItem).filter_by(batch_id=batch.id).one()
        session.add(
            ProductTrafficCheckpoint(
                id="checkpoint-invalidated-no-delta-h24",
                batch_id=batch.id,
                item_id=batch_item.item_id,
                checkpoint="h24",
                recorded_at=(fixed + timedelta(hours=24)).astimezone(timezone.utc),
                browse_count=product.baseline_browse_count + 50,
                collect_count=product.baseline_collect_count + 2,
                want_count=product.baseline_want_count + 3,
                inquiry_count=product.baseline_inquiry_count + 1,
                note="仅保留累计事实",
            )
        )
        session.commit()

    viewed = next(value for value in service.overview().traffic_batches if value.id == batch.id)
    assert viewed.completed_checkpoints == ["h24"]
    assert viewed.checkpoint_metrics == []
    assert viewed.products[0].checkpoints[0].browse_count == product.baseline_browse_count + 50
    assert viewed.products[0].checkpoints[0].browse_delta == 0
    assert viewed.products[0].browse_delta == 0


def test_invalidated_batch_exposes_checkpoint_exploration_without_decision_leak(
    tmp_path: Path,
) -> None:
    raw = {"title": "探索性检查点", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    item_id = seed_item(database, raw, external_id="exploratory-checkpoints")
    service.bootstrap_cached_state()
    started_at = datetime(2026, 8, 11, 16, 0, tzinfo=service.timezone)
    with database.session() as session:
        for offset, browse in ((2, 10), (1, 12), (0, 14)):
            captured = started_at - timedelta(days=offset, hours=8)
            session.add(
                ProductDailySnapshot(
                    item_id=item_id,
                    snapshot_date=captured.date().isoformat(),
                    source="test_history",
                    title=raw["title"],
                    status="在售",
                    raw_browse_count=browse,
                    browse_count=browse,
                    captured_at=captured.astimezone(timezone.utc),
                )
            )
        batch = ProductTrafficBatch(
            id="exploratory-checkpoint-batch",
            request_id="exploratory-checkpoint-request",
            status="invalidated",
            planned_at=started_at.astimezone(timezone.utc),
            started_at=started_at.astimezone(timezone.utc),
            invalidated_at=(started_at + timedelta(days=2)).astimezone(timezone.utc),
            invalidation_reason="legacy_baseline",
            actual_cost=5.9,
            note="只保留弱观察",
        )
        session.add(batch)
        session.flush()
        session.add(
            ProductTrafficBatchItem(
                batch_id=batch.id,
                item_id=item_id,
                position=0,
                baseline_browse_count=14,
                baseline_collect_count=0,
                baseline_want_count=0,
                baseline_inquiry_count=0,
                baseline_captured_at=(started_at - timedelta(hours=8)).astimezone(timezone.utc),
                baseline_source="legacy_snapshot",
            )
        )
        for checkpoint, hours, browse, want in (
            ("h1", 1, 20, 1),
            ("h6", 6, 24, 2),
            ("h24", 24, 32, 3),
        ):
            session.add(
                ProductTrafficCheckpoint(
                    id=f"exploratory-checkpoint-{checkpoint}",
                    batch_id=batch.id,
                    item_id=item_id,
                    checkpoint=checkpoint,
                    browse_count=browse,
                    collect_count=0,
                    want_count=want,
                    inquiry_count=0,
                    recorded_at=(started_at + timedelta(hours=hours)).astimezone(timezone.utc),
                    note="真实累计记录",
                )
            )
        session.commit()

    service._maintain_daily_plans()
    viewed = next(
        value
        for value in service.overview().traffic_batches
        if value.id == "exploratory-checkpoint-batch"
    )
    assert viewed.status == "invalidated"
    assert viewed.analysis_tier == "exploratory"
    assert viewed.exploratory_reference_source == "checkpoint"
    assert viewed.exploratory_reference_label == "+1h"
    assert viewed.exploratory_through_label == "+24h"
    assert viewed.observed_browse_change == 12
    assert viewed.observed_want_change == 2
    assert [value.browse_change for value in viewed.exploratory_points] == [0, 4, 12]
    assert viewed.products[0].exploratory_points[-1].browse_change == 12
    assert viewed.natural_sample_size == 2
    assert viewed.natural_browse_low is not None
    assert viewed.natural_browse_high is not None
    assert viewed.analysis_eligible is False
    assert viewed.checkpoint_metrics == []
    assert viewed.browse_delta == 0
    analytics = service.overview().exposure_analytics
    assert analytics.eligible_batch_count == 0
    assert analytics.excluded_batch_count == 1
    assert analytics.browse_delta == 0
    assert analytics.time_buckets == []


def test_zero_checkpoint_falls_back_to_daily_snapshot_exploration(
    tmp_path: Path,
) -> None:
    raw = {"title": "快照弱观察", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    item_id = seed_item(database, raw, external_id="exploratory-snapshots")
    service.bootstrap_cached_state()
    started_at = datetime(2026, 8, 12, 16, 20, tzinfo=service.timezone)
    with database.session() as session:
        before_at = started_at - timedelta(hours=7, minutes=22)
        after_at = started_at + timedelta(hours=16, minutes=40)
        session.add(
            ProductDailySnapshot(
                item_id=item_id,
                snapshot_date=before_at.date().isoformat(),
                source="test_before",
                title=raw["title"],
                status="在售",
                raw_browse_count=100,
                browse_count=100,
                want_count=5,
                inquiry_count=0,
                captured_at=before_at.astimezone(timezone.utc),
            )
        )
        after = session.query(ProductDailySnapshot).filter_by(item_id=item_id).one()
        after.snapshot_date = after_at.date().isoformat()
        after.source = "test_after"
        after.raw_browse_count = 112
        after.browse_count = 112
        after.want_count = 7
        after.inquiry_count = 1
        after.captured_at = after_at.astimezone(timezone.utc)
        batch = ProductTrafficBatch(
            id="exploratory-snapshot-batch",
            request_id="exploratory-snapshot-request",
            status="invalidated",
            recording_mode="actual_overlap",
            attribution_status="overlap",
            planned_at=started_at.astimezone(timezone.utc),
            started_at=started_at.astimezone(timezone.utc),
            invalidated_at=(started_at + timedelta(days=1)).astimezone(timezone.utc),
            invalidation_reason="missing_baseline",
            actual_cost=6.1,
            note="没有 T0",
        )
        session.add(batch)
        session.flush()
        session.add(
            ProductTrafficBatchItem(
                batch_id=batch.id,
                item_id=item_id,
                position=0,
                baseline_source="missing",
            )
        )
        session.add(
            ProductTrafficCheckpoint(
                id="exploratory-zero-h1",
                batch_id=batch.id,
                item_id=item_id,
                checkpoint="h1",
                browse_count=0,
                collect_count=0,
                want_count=0,
                inquiry_count=0,
                recorded_at=(started_at + timedelta(hours=1)).astimezone(timezone.utc),
                note="冲突的零累计值",
            )
        )
        session.commit()

    service._maintain_daily_plans()
    viewed = next(
        value
        for value in service.overview().traffic_batches
        if value.id == "exploratory-snapshot-batch"
    )
    assert viewed.analysis_tier == "exploratory"
    assert viewed.exploratory_reference_source == "daily_snapshot"
    assert viewed.observed_browse_change == 12
    assert viewed.observed_want_change == 2
    assert viewed.observed_inquiry_change == 1
    assert [value.browse_change for value in viewed.exploratory_points] == [0, 12]
    assert any("累计值与已有快照冲突" in line for line in viewed.analysis_limitations)
    assert any("不能区分各批次贡献" in line for line in viewed.analysis_limitations)
    assert viewed.analysis_eligible is False
    assert viewed.due_checkpoint is None


def test_overview_is_read_only_and_semantic_noop_reuses_plan_version(
    tmp_path: Path,
) -> None:
    raw = {"title": "只读方案", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    for index in range(5):
        seed_item(
            database,
            {**raw, "title": f"只读方案 {index}"},
            external_id=f"read-only-plan-{index}",
        )
    prepare_service(service)
    first = service.refresh_operating_plan()
    before_revision, _snapshot = service.ledger.get()
    with database.session() as session:
        before_count = session.query(ProductOperatingPlan).count()
    service.overview()
    service.overview()
    after_revision, _snapshot = service.ledger.get()
    with database.session() as session:
        assert session.query(ProductOperatingPlan).count() == before_count
        current = (
            session.query(ProductOperatingPlan)
            .filter(ProductOperatingPlan.status == "current")
            .one()
        )
        assert current.id == first.id
        assert current.version == first.version
    assert after_revision == before_revision
    second = service.refresh_operating_plan()
    with database.session() as session:
        assert session.query(ProductOperatingPlan).count() == before_count
    assert second.id == first.id
    assert second.version == first.version
    assert "未创建噪声版本" in second.change_factors[0]


def test_operating_plan_uses_exact_24_hour_stability_and_alternating_traffic(
    tmp_path: Path,
) -> None:
    raw = {"title": "稳定窗口商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    for index in range(17):
        seed_item(
            database,
            {**raw, "title": f"稳定窗口商品 {index}"},
            external_id=f"stability-plan-{index}",
        )
    fixed = datetime(2026, 8, 15, 10, 15, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    prepare_service(service)

    plan = service.refresh_operating_plan()
    assert plan.rules_version == "v2.4.3"
    assert [slot.date for slot in plan.slots if slot.action_type == "traffic"] == [
        "2026-08-15",
        "2026-08-17",
        "2026-08-19",
        "2026-08-21",
    ]
    today, tomorrow = plan.slots[:2]
    assert today.locked is False
    assert today.lock_mode == "stability"
    assert today.lock_label == "24h内 · 计划固定"
    assert tomorrow.lock_mode == "none"
    assert tomorrow.lock_label is None


def test_v242_automatic_locks_do_not_preserve_consecutive_traffic(
    tmp_path: Path,
) -> None:
    raw = {"title": "旧锁升级商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    for index in range(17):
        seed_item(
            database,
            {**raw, "title": f"旧锁升级商品 {index}"},
            external_id=f"legacy-lock-{index}",
        )
    fixed = datetime(2026, 8, 15, 10, 15, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    prepare_service(service)
    original = service.refresh_operating_plan()

    with database.session() as session:
        stored_plan = session.get(ProductOperatingPlan, original.id)
        assert stored_plan is not None
        stored_plan.rules_version = "v2.4.2"
        tomorrow = session.scalar(
            select(ProductOperatingPlanSlot).where(
                ProductOperatingPlanSlot.plan_id == original.id,
                ProductOperatingPlanSlot.slot_date == "2026-08-16",
            )
        )
        today = session.scalar(
            select(ProductOperatingPlanSlot).where(
                ProductOperatingPlanSlot.plan_id == original.id,
                ProductOperatingPlanSlot.slot_date == "2026-08-15",
            )
        )
        assert today is not None and tomorrow is not None
        today.locked = True
        tomorrow.locked = True
        tomorrow.action_type = "traffic"
        tomorrow.item_ids_json = today.item_ids_json
        tomorrow.planned_cost = today.planned_cost
        session.commit()

    upgraded = service.refresh_operating_plan()
    assert upgraded.rules_version == "v2.4.3"
    assert upgraded.slots[0].action_type == "traffic"
    assert upgraded.slots[0].locked is False
    assert upgraded.slots[1].action_type != "traffic"
    assert not any(
        left.action_type == right.action_type == "traffic"
        for left, right in zip(upgraded.slots, upgraded.slots[1:])
    )


def test_manual_plan_lock_survives_reassessment_outside_stability_window(
    tmp_path: Path,
) -> None:
    raw = {"title": "手动固定商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    for index in range(17):
        seed_item(
            database,
            {**raw, "title": f"手动固定商品 {index}"},
            external_id=f"manual-lock-{index}",
        )
    fixed = datetime(2026, 8, 15, 10, 15, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    prepare_service(service)
    initial = service.refresh_operating_plan()
    future = initial.slots[2]

    locked = service.update_plan_slot_lock(future.id, True)
    locked_slot = next(slot for slot in locked.slots if slot.id == future.id)
    assert locked_slot.locked is True
    assert locked_slot.lock_mode == "manual"
    assert locked_slot.lock_label == "手动固定"

    refreshed = service.refresh_operating_plan()
    refreshed_slot = next(slot for slot in refreshed.slots if slot.date == future.date)
    assert refreshed_slot.locked is True
    assert refreshed_slot.lock_mode == "manual"


def test_invalidated_batch_cooldown_does_not_create_an_observation_day(
    tmp_path: Path,
) -> None:
    raw = {"title": "轮换商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    item_ids = []
    for index in range(15):
        item_ids.append(
            seed_item(
                database,
                {**raw, "title": f"轮换商品 {index}"},
                external_id=f"invalidated-plan-{index}",
            )
        )
    for index in range(2):
        seed_item(
            database,
            {
                **raw,
                "title": f"应先优化商品 {index}",
                "browseCnt": 120 + index,
                "wantCnt": 0,
            },
            external_id=f"invalidated-optimize-{index}",
        )
    fixed = datetime(2026, 8, 15, 10, 15, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    prepare_service(service)
    with database.session() as session:
        batch = ProductTrafficBatch(
            id="invalidated-plan-source",
            request_id="invalidated-plan-source-request",
            status="invalidated",
            planned_at=(fixed - timedelta(hours=42)).astimezone(timezone.utc),
            started_at=(fixed - timedelta(hours=42)).astimezone(timezone.utc),
            invalidated_at=(fixed - timedelta(hours=20)).astimezone(timezone.utc),
            invalidation_reason="invalid_baseline_time",
            actual_cost=6.1,
        )
        session.add(batch)
        session.flush()
        session.add(
            ProductTrafficBatchItem(
                batch_id=batch.id,
                item_id=item_ids[0],
                position=0,
                baseline_source="legacy_snapshot",
            )
        )
        session.commit()

    plan = service.refresh_operating_plan()
    tomorrow = next(slot for slot in plan.slots if slot.date == "2026-08-16")
    assert tomorrow.action_type == "optimize"
    assert [product.title for product in tomorrow.products] == [
        "应先优化商品 0",
        "应先优化商品 1",
    ]
    assert tomorrow.source_batch_id is None


def test_executed_traffic_freezes_today_while_future_slots_respect_cooldown(
    tmp_path: Path,
) -> None:
    raw = {"title": "观察保护商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    for index in range(5):
        seed_item(
            database,
            {**raw, "title": f"观察保护商品 {index}"},
            external_id=f"observation-guard-{index}",
        )
    fixed = datetime(2026, 8, 12, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    prepare_service(service)
    initial = service.refresh_operating_plan()
    initial_traffic = next(
        slot for slot in initial.slots if slot.action_type == "traffic"
    )
    batch = service.create_traffic_batch(
        request_id="request-observation-guard",
        item_external_ids=[
            f"observation-guard-{index}" for index in range(5)
        ],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=initial_traffic.id,
        note="验证 72 小时防重叠",
    )
    started = service.start_traffic_batch(batch.id)
    with database.session() as session:
        stored = session.get(ProductTrafficBatch, batch.id)
        assert stored is not None
        stored.started_at = fixed.astimezone(timezone.utc)
        session.commit()

    refreshed = service.refresh_operating_plan()
    today = refreshed.slots[0]
    assert today.action_type == "traffic"
    assert today.status == "executed"
    assert today.batch_id == batch.id
    assert today.lock_mode == "executed"
    assert today.is_new_spend is False
    assert today.planned_cost == 5.9
    assert any("真实执行事实已冻结" in factor for factor in today.change_factors)
    assert all(
        slot.action_type != "traffic"
        for slot in refreshed.slots[1:4]
    )
    assert started.products


def test_planned_batch_cannot_start_with_listing_inside_another_72h_window(
    tmp_path: Path,
) -> None:
    raw = {"title": "重叠启动保护", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="start-guard-shared")
    seed_item(
        database,
        {**raw, "title": "重叠启动保护 B"},
        external_id="start-guard-other",
    )
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 12, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    observing = service.create_traffic_batch(
        request_id="request-start-guard-observing",
        item_external_ids=["start-guard-shared"],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="正在观察",
    )
    observing_started = service.start_traffic_batch(observing.id)
    service.complete_traffic_batch(
        observing.id,
        completed_at=(fixed + timedelta(hours=1)).astimezone(timezone.utc),
        actual_cost=5.9,
        total_exposure=900,
        note="套餐已完成，归因仍继续",
    )
    planned = service.create_traffic_batch(
        request_id="request-start-guard-planned",
        item_external_ids=["start-guard-shared", "start-guard-other"],
        planned_at=(fixed + timedelta(hours=2)).astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="不应绕过 72h 保护",
    )

    blocked_view = next(
        batch
        for batch in service.overview().traffic_batches
        if batch.id == planned.id
    )
    assert blocked_view.start_blocked is True
    assert blocked_view.can_prepare_baseline is False
    assert blocked_view.can_start is False
    assert blocked_view.start_blocked_until == (
        fixed + timedelta(hours=72)
    ).astimezone(timezone.utc)
    assert "1 件商品与其他批次重叠" in (blocked_view.start_blocked_reason or "")
    with pytest.raises(ProductTrafficConflict, match="1 件商品与其他批次重叠"):
        service.start_traffic_batch(planned.id)
    with database.session() as session:
        stored = session.get(ProductTrafficBatch, planned.id)
        assert stored is not None
        assert stored.status == "planned"
        assert stored.started_at is None
    revision, snapshot = service.ledger.get()
    assert revision == 1
    assert [expense["id"] for expense in snapshot["expenses"]] == [
        f"expense-traffic-{observing.id}"
    ]

    service._now = lambda: fixed + timedelta(hours=72)  # type: ignore[method-assign]
    service.record_traffic_checkpoint(
        observing.id,
        checkpoint="h72",
        recorded_at=(fixed + timedelta(hours=72)).astimezone(timezone.utc),
        items=[{
            "external_id": "start-guard-shared",
            "browse_count": observing_started.products[0].baseline_browse_count,
            "collect_count": observing_started.products[0].baseline_collect_count,
            "want_count": observing_started.products[0].baseline_want_count,
            "inquiry_count": observing_started.products[0].baseline_inquiry_count,
        }],
        note="完成 72h 观察后解除保护",
    )
    service._now = lambda: fixed + timedelta(hours=72, minutes=1)  # type: ignore[method-assign]
    started = service.start_traffic_batch(planned.id)
    assert started.status == "running"
    assert started.start_blocked is False


def test_non_overlapping_batch_can_start_while_another_batch_is_observing(
    tmp_path: Path,
) -> None:
    raw = {"title": "按商品冷却", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="cooldown-a")
    seed_item(database, {**raw, "title": "按商品冷却 B"}, external_id="cooldown-b")
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 12, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    first = service.create_traffic_batch(
        request_id="request-cooldown-first",
        item_external_ids=["cooldown-a"],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="第一批",
    )
    service.start_traffic_batch(first.id)
    second = service.create_traffic_batch(
        request_id="request-cooldown-second",
        item_external_ids=["cooldown-b"],
        planned_at=(fixed + timedelta(minutes=5)).astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="完全不同商品",
    )

    preview = service.traffic_start_preview(second.id)
    assert preview.overlap_items == []
    assert preview.can_record_actual is False
    assert preview.batch.start_blocked is False
    started = service.start_traffic_batch(second.id)
    assert started.status == "running"


def test_operating_plan_can_schedule_disjoint_rotation_before_source_h72(
    tmp_path: Path,
) -> None:
    raw = {"title": "分组轮换", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    ids = [f"disjoint-plan-{index}" for index in range(10)]
    for index, external_id in enumerate(ids):
        seed_item(
            database,
            {**raw, "title": f"分组轮换 {index}"},
            external_id=external_id,
        )
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 12, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    source = service.create_traffic_batch(
        request_id="request-disjoint-plan-source",
        item_external_ids=ids[:5],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="A 组继续观察",
    )
    service.start_traffic_batch(source.id)

    plan = service.refresh_operating_plan()
    assert plan.slots[0].action_type == "traffic"
    assert plan.slots[0].status == "executed"
    assert plan.slots[0].batch_id == source.id
    future_traffic = next(
        slot for slot in plan.slots[1:] if slot.action_type == "traffic"
    )
    selected_ids = {product.external_id for product in future_traffic.products}
    assert len(selected_ids) >= 3
    assert selected_ids.isdisjoint(ids[:5])
    assert future_traffic.source_batch_id == source.id
    assert future_traffic.is_new_spend is True
    assert any(
        "不重叠" in factor or "轮换" in factor
        for factor in [future_traffic.reason, *future_traffic.change_factors]
    )


def test_actual_overlap_record_without_t0_is_idempotent_and_excluded(
    tmp_path: Path,
) -> None:
    raw = {"title": "真实重叠补录", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="actual-overlap-shared")
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 12, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    first = service.create_traffic_batch(
        request_id="request-actual-overlap-first",
        item_external_ids=["actual-overlap-shared"],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="第一批",
    )
    service.start_traffic_batch(first.id)
    service._now = lambda: fixed + timedelta(hours=2)  # type: ignore[method-assign]
    second = service.create_traffic_batch(
        request_id="request-actual-overlap-second",
        item_external_ids=["actual-overlap-shared"],
        planned_at=(fixed + timedelta(hours=1)).astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="已经人工购买",
    )
    preview = service.traffic_start_preview(second.id)
    assert preview.can_start_clean is False
    assert preview.can_record_actual is True
    assert len(preview.overlap_items) == 1
    payload = {
        "request_id": "actual-start-overlap-idempotent",
        "expected_updated_at": second.updated_at,
        "actual_started_at": None,
        "confirmed_already_purchased": True,
        "items": [],
    }
    recorded = service.record_actual_overlap_start(second.id, **payload)
    service._now = lambda: fixed + timedelta(hours=2, minutes=1)  # type: ignore[method-assign]
    replay = service.record_actual_overlap_start(second.id, **payload)
    assert replay.id == recorded.id
    assert recorded.recording_mode == "actual_overlap"
    assert recorded.attribution_status == "overlap"
    assert recorded.status == "invalidated"
    assert recorded.invalidation_reason == "missing_baseline"
    assert recorded.due_checkpoint is None
    assert recorded.has_reliable_baseline is False
    assert recorded.data_quality == "invalidated"
    assert recorded.analysis_eligible is False
    assert recorded.products[0].baseline_source == "missing"
    assert "永久排除" in (recorded.overlap_warning or "")
    service._now = lambda: fixed + timedelta(hours=90)  # type: ignore[method-assign]
    service._maintain_daily_plans()
    persisted = next(
        value
        for value in service.overview().traffic_batches
        if value.id == second.id
    )
    assert persisted.analysis_eligible is False
    assert "永久排除" in (persisted.overlap_warning or "")
    with database.session() as session:
        assert session.query(ProductTrafficBatchEvent).filter_by(
            request_id=payload["request_id"]
        ).count() == 1
        assert session.query(BusinessExpense).filter_by(
            id=f"expense-traffic-{second.id}"
        ).count() == 1


def test_actual_overlap_record_with_manual_t0_and_guards(tmp_path: Path) -> None:
    raw = {"title": "人工 T0 重叠", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="actual-overlap-manual")
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 12, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    first = service.create_traffic_batch(
        request_id="request-actual-manual-first",
        item_external_ids=["actual-overlap-manual"],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="第一批",
    )
    service.start_traffic_batch(first.id)
    service._now = lambda: fixed + timedelta(hours=3)  # type: ignore[method-assign]
    second = service.create_traffic_batch(
        request_id="request-actual-manual-second",
        item_external_ids=["actual-overlap-manual"],
        planned_at=(fixed + timedelta(hours=2)).astimezone(timezone.utc),
        actual_cost=6,
        plan_slot_id=None,
        note="人工 T0",
    )
    manual = [{
        "external_id": "actual-overlap-manual",
        "browse_count": 20,
        "collect_count": 0,
        "want_count": 0,
        "inquiry_count": 0,
    }]
    recorded = service.record_actual_overlap_start(
        second.id,
        request_id="actual-start-manual-overlap",
        expected_updated_at=second.updated_at,
        actual_started_at=None,
        confirmed_already_purchased=True,
        items=manual,
    )
    assert recorded.has_reliable_baseline is True
    assert recorded.products[0].baseline_source == "manual"
    assert recorded.status == "running"
    assert recorded.analysis_eligible is False
    with pytest.raises(ProductTrafficConflict, match="相同 request_id"):
        service.record_actual_overlap_start(
            second.id,
            request_id="actual-start-manual-overlap",
            expected_updated_at=second.updated_at,
            actual_started_at=None,
            confirmed_already_purchased=True,
            items=[{**manual[0], "browse_count": 21}],
        )


@pytest.mark.asyncio
async def test_recorded_batch_collects_live_t0_and_is_idempotent(
    tmp_path: Path,
) -> None:
    raw = {"title": "新建即开始", "browseCnt": 20, "itemStatusStr": "在售"}
    database, adapter, service = build_service(tmp_path, raw)
    external_ids = [f"record-now-live-{index}" for index in range(3)]
    for external_id in external_ids:
        seed_item(database, raw, external_id=external_id)
    service.bootstrap_cached_state()
    clicked = datetime(
        2026, 8, 14, 16, 20, 47, 321000, tzinfo=service.timezone
    )
    service._now = lambda: clicked  # type: ignore[method-assign]
    payload = {
        "request_id": "record-now-live-idempotent",
        "item_external_ids": external_ids,
        "actual_cost": 6.0,
        "plan_slot_id": None,
        "note": "已经在闲鱼购买",
        "confirmed_already_purchased": True,
    }

    recorded = await service.record_traffic_batch_now(**payload)
    service._now = lambda: clicked + timedelta(minutes=2)  # type: ignore[method-assign]
    replay = await service.record_traffic_batch_now(**payload)

    expected = clicked.replace(second=0, microsecond=0).astimezone(timezone.utc)
    assert service._utc(recorded.created_at) == expected
    assert service._utc(recorded.started_at) == expected
    assert recorded.status == "running"
    assert recorded.has_reliable_baseline is True
    assert all(
        item.baseline_source == "remote_refresh"
        and item.baseline_captured_at is not None
        for item in recorded.products
    )
    assert recorded.observation_window_hours == 48
    assert recorded.terminal_checkpoint == "h48"
    assert recorded.checkpoint_sequence == ["h1", "h6", "h24", "h48"]
    assert recorded.is_legacy_protocol is False
    assert recorded.plan_slot_id is None
    assert "8月14日 16:20 投流后的 48 小时观察结论" == recorded.observation_title
    assert recorded.invalidation_reason is None
    assert recorded.due_checkpoint == "h1"
    assert replay.id == recorded.id
    assert service._utc(replay.started_at) == expected
    assert adapter.calls == external_ids
    with database.session() as session:
        assert session.query(ProductTrafficBatchEvent).filter_by(
            request_id=payload["request_id"]
        ).count() == 1
        expense = session.get(BusinessExpense, f"expense-traffic-{recorded.id}")
        assert expense is not None
        assert expense.amount == 6.0
        assert expense.paid_at == "2026-08-14T16:20:00+08:00"


@pytest.mark.asyncio
async def test_recorded_batch_access_verification_creates_no_batch_or_expense(
    tmp_path: Path,
) -> None:
    raw = {"title": "T0 熔断", "browseCnt": 20, "itemStatusStr": "在售"}
    database, adapter, service = build_service(tmp_path, raw)
    external_ids = ["record-now-fuse-a", "record-now-fuse-b"]
    for external_id in external_ids:
        seed_item(database, raw, external_id=external_id)
    service.bootstrap_cached_state()

    async def fail_with_verification(item_id: str) -> ItemInfo:
        adapter.calls.append(item_id)
        raise AdapterAccessVerificationError("private platform verification body")

    adapter.fetch_item = fail_with_verification  # type: ignore[method-assign]
    with pytest.raises(
        ProductCollectionUnavailable,
        match="未创建曝光批次或费用",
    ):
        await service.record_traffic_batch_now(
            request_id="record-now-fuse-request",
            item_external_ids=external_ids,
            actual_cost=5.9,
            plan_slot_id=None,
            note="触发访问验证",
            confirmed_already_purchased=True,
        )

    assert adapter.calls == [external_ids[0]]
    with database.session() as session:
        assert session.query(ProductTrafficBatch).count() == 0
        assert session.query(BusinessExpense).count() == 0
        monitors = session.scalars(
            select(ProductMonitor)
            .join(Item, Item.id == ProductMonitor.item_id)
            .where(Item.external_id.in_(external_ids))
            .order_by(Item.external_id)
        ).all()
        assert [monitor.last_error_code for monitor in monitors] == [
            "access_verification",
            "access_verification_batch_stopped",
        ]


@pytest.mark.asyncio
async def test_recorded_batch_refreshes_live_t0_and_marks_overlap(
    tmp_path: Path,
) -> None:
    raw = {"title": "已有可靠快照", "browseCnt": 30, "itemStatusStr": "在售"}
    database, adapter, service = build_service(tmp_path, raw)
    first_time = datetime(2026, 8, 14, 10, 0, tzinfo=service.timezone)
    seed_item(
        database,
        raw,
        external_id="record-now-recent",
        updated_at=first_time - timedelta(hours=2),
    )
    service.bootstrap_cached_state()
    service._now = lambda: first_time  # type: ignore[method-assign]
    first = await service.record_traffic_batch_now(
        request_id="record-now-recent-first",
        item_external_ids=["record-now-recent"],
        actual_cost=5.9,
        plan_slot_id=None,
        note="首批",
        confirmed_already_purchased=True,
    )
    assert first.status == "running"

    second_time = first_time + timedelta(hours=2)
    service._now = lambda: second_time  # type: ignore[method-assign]
    second = await service.record_traffic_batch_now(
        request_id="record-now-recent-overlap",
        item_external_ids=["record-now-recent"],
        actual_cost=6.1,
        plan_slot_id=None,
        note="重叠真实投放",
        confirmed_already_purchased=True,
    )

    assert second.status == "running"
    assert second.has_reliable_baseline is True
    assert second.products[0].baseline_source == "remote_refresh"
    assert second.recording_mode == "actual_overlap"
    assert second.attribution_status == "overlap"
    assert second.analysis_eligible is False
    assert service._local(second.due_at) == second_time + timedelta(hours=1)
    assert second.observation_window_hours == 48
    assert [job.checkpoint for job in second.checkpoint_jobs] == [
        "h1", "h6", "h24", "h48"
    ]
    assert "h72" not in {job.checkpoint for job in second.checkpoint_jobs}
    assert adapter.calls == ["record-now-recent", "record-now-recent"]
    service._now = lambda: second_time + timedelta(hours=48)  # type: ignore[method-assign]
    closed = service.record_traffic_checkpoint(
        second.id,
        checkpoint="h48",
        recorded_at=(second_time + timedelta(hours=48)).astimezone(timezone.utc),
        items=[{
            "external_id": "record-now-recent",
            "browse_count": 40,
            "collect_count": 3,
            "want_count": 4,
            "inquiry_count": 2,
        }],
        note="48 小时终点",
    )
    assert closed.status == "closed"
    assert closed.observation_checkpoint == "h48"
    assert closed.observation_hours == 48


@pytest.mark.asyncio
async def test_recorded_batch_rejects_plan_link_for_actual_time_protocol(
    tmp_path: Path,
) -> None:
    raw = {"title": "拒绝计划关联", "browseCnt": 12, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="record-now-no-plan")
    service.bootstrap_cached_state()

    with pytest.raises(ProductTrafficConflict, match="不再接受经营计划关联"):
        await service.record_traffic_batch_now(
            request_id="record-now-plan-rejected",
            item_external_ids=["record-now-no-plan"],
            actual_cost=5.9,
            plan_slot_id="legacy-plan-slot",
            note="",
            confirmed_already_purchased=True,
        )


@pytest.mark.asyncio
async def test_actual_48h_batch_respects_legacy_72h_overlap_window(
    tmp_path: Path,
) -> None:
    raw = {"title": "混合协议窗口", "browseCnt": 50, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="mixed-window-item")
    service.bootstrap_cached_state()
    legacy_started = datetime(2026, 8, 10, 8, 0, tzinfo=service.timezone)
    legacy = service.create_traffic_batch(
        request_id="mixed-window-legacy-create",
        item_external_ids=["mixed-window-item"],
        planned_at=legacy_started.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="历史 72h",
    )
    actual_started = legacy_started + timedelta(hours=60)
    with database.session() as session:
        row = session.get(ProductTrafficBatch, legacy.id)
        assert row is not None
        row.status = "closed"
        row.started_at = legacy_started.astimezone(timezone.utc)
        row.observation_window_hours = 72
        session.commit()
    service._now = lambda: actual_started  # type: ignore[method-assign]

    recorded = await service.record_traffic_batch_now(
        request_id="mixed-window-actual-record",
        item_external_ids=["mixed-window-item"],
        actual_cost=6,
        plan_slot_id=None,
        note="60 小时后真实投流",
        confirmed_already_purchased=True,
    )

    assert recorded.observation_window_hours == 48
    assert recorded.recording_mode == "actual_overlap"
    assert recorded.attribution_status == "overlap"


def test_historical_start_correction_updates_expense_and_invalidates_late_t0(
    tmp_path: Path,
) -> None:
    raw = {"title": "历史时间更正", "browseCnt": 40, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="historical-start-repair")
    service.bootstrap_cached_state()
    created_local = datetime(
        2026, 8, 13, 16, 14, 45, 845536, tzinfo=service.timezone
    )
    started_local = datetime(2026, 8, 13, 18, 6, tzinfo=service.timezone)
    batch = service.create_traffic_batch(
        request_id="historical-start-repair-create",
        item_external_ids=["historical-start-repair"],
        planned_at=created_local.astimezone(timezone.utc),
        actual_cost=6.1,
        plan_slot_id=None,
        note="等待审计更正",
    )
    with database.session() as session:
        stored = session.get(ProductTrafficBatch, batch.id)
        assert stored is not None
        stored.created_at = created_local.astimezone(timezone.utc)
        stored.started_at = started_local.astimezone(timezone.utc)
        stored.status = "observing"
        stored.baseline_prepared_at = (
            started_local + timedelta(seconds=30)
        ).astimezone(timezone.utc)
        item = session.query(ProductTrafficBatchItem).filter_by(
            batch_id=batch.id
        ).one()
        item.baseline_source = "remote_refresh"
        item.baseline_captured_at = stored.baseline_prepared_at
        item.baseline_browse_count = 40
        service._sync_traffic_expense_in_session(session, stored)
        session.commit()
    service._now = lambda: datetime(  # type: ignore[method-assign]
        2026, 8, 14, 9, 30, tzinfo=service.timezone
    )

    repaired = service.correct_traffic_batch_start_from_created_at(
        batch.id,
        request_id="historical-start-repair-20260814",
        expected_created_at=created_local.astimezone(timezone.utc),
        expected_started_at=started_local.astimezone(timezone.utc),
    )
    replay = service.correct_traffic_batch_start_from_created_at(
        batch.id,
        request_id="historical-start-repair-20260814",
        expected_created_at=created_local.astimezone(timezone.utc),
        expected_started_at=started_local.astimezone(timezone.utc),
    )

    expected = created_local.replace(second=0, microsecond=0)
    assert service._local(repaired.started_at) == expected
    assert repaired.status == "invalidated"
    assert repaired.invalidation_reason == "invalid_baseline_time"
    assert replay.id == repaired.id
    with database.session() as session:
        expense = session.get(BusinessExpense, f"expense-traffic-{batch.id}")
        assert expense is not None
        assert expense.paid_at == "2026-08-13T16:14:00+08:00"
        assert session.query(ProductTrafficBatchEvent).filter_by(
            request_id="historical-start-repair-20260814"
        ).count() == 1


def test_invalid_batch_can_restore_daily_snapshot_as_exploratory_only(
    tmp_path: Path,
) -> None:
    raw = {"title": "早间探索参考", "browseCnt": 40, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    external_ids = [f"exploratory-restore-{index}" for index in range(5)]
    for index, external_id in enumerate(external_ids):
        seed_item(
            database,
            {**raw, "title": f"早间探索参考 {index}"},
            external_id=external_id,
        )
    started_local = datetime(2026, 8, 16, 16, 10, tzinfo=service.timezone)
    reference_local = datetime(2026, 8, 16, 8, 40, tzinfo=service.timezone)
    service._now = lambda: started_local  # type: ignore[method-assign]
    prepare_service(service)
    with database.session() as session:
        snapshots = session.scalars(
            select(ProductDailySnapshot).where(
                ProductDailySnapshot.item_id.in_(
                    select(Item.id).where(Item.external_id.in_(external_ids))
                )
            )
        ).all()
        assert len(snapshots) == 5
        for index, snapshot in enumerate(snapshots):
            snapshot.snapshot_date = "2026-08-16"
            snapshot.source = "automatic"
            snapshot.captured_at = (
                reference_local + timedelta(seconds=index)
            ).astimezone(timezone.utc)
            snapshot.browse_count = 40 + index
            snapshot.raw_browse_count = 40 + index
            snapshot.want_count = index
            snapshot.collect_count = 0
            snapshot.inquiry_count = 0
        session.commit()
    invalid_id = seed_invalid_actual_traffic_batch(
        database,
        service,
        request_id="exploratory-restore-record",
        external_ids=external_ids,
        started_at=started_local,
    )

    restored = service.restore_traffic_batch_exploratory_observation(
        invalid_id,
        request_id="exploratory-restore-request",
        snapshot_date="2026-08-16",
    )
    replay = service.restore_traffic_batch_exploratory_observation(
        invalid_id,
        request_id="exploratory-restore-request",
        snapshot_date="2026-08-16",
    )

    assert restored.status == "running"
    assert restored.recording_mode == "exploratory_recovery"
    assert restored.attribution_status == "exploratory"
    assert restored.analysis_tier == "fact_only"
    assert restored.analysis_eligible is False
    assert restored.baseline_quality == "exploratory"
    assert all(
        item.baseline_source == "daily_exploratory"
        for item in restored.products
    )
    assert replay.id == restored.id
    assert [service._local(job.scheduled_for) for job in restored.checkpoint_jobs] == [
        started_local + timedelta(hours=1),
        started_local + timedelta(hours=6),
        started_local + timedelta(hours=24),
        started_local + timedelta(hours=48),
    ]
    with database.session() as session:
        assert session.query(ProductTrafficBatchEvent).filter_by(
            request_id="exploratory-restore-request"
        ).count() == 1

    service._invalidate_unusable_traffic_baselines()
    after_scan = next(
        batch for batch in service.traffic_batches(limit=20).items
        if batch.id == restored.id
    )
    assert after_scan.status == "running"
    current_plan = service.overview().operating_plan
    today = next(slot for slot in current_plan.slots if slot.date == "2026-08-16")
    assert today.status == "executed"
    assert today.batch_id == restored.id

    service._now = lambda: started_local + timedelta(hours=1)  # type: ignore[method-assign]
    observed = service.record_traffic_checkpoint(
        restored.id,
        checkpoint="h1",
        recorded_at=None,
        items=[
            {
                "external_id": item.external_id,
                "browse_count": item.baseline_browse_count + 3,
                "collect_count": item.baseline_collect_count,
                "want_count": item.baseline_want_count,
                "inquiry_count": item.baseline_inquiry_count,
            }
            for item in restored.products
        ],
        note="第一条真实检查点",
    )
    assert observed.exploratory_available is True
    assert observed.analysis_tier == "exploratory"
    assert observed.observed_browse_change == 15
    assert observed.analysis_eligible is False


def test_exploratory_restore_rejects_incomplete_daily_snapshot(
    tmp_path: Path,
) -> None:
    raw = {"title": "探索参考不完整", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    external_ids = ["exploratory-incomplete-a", "exploratory-incomplete-b"]
    for external_id in external_ids:
        seed_item(database, raw, external_id=external_id)
    started_local = datetime(2026, 8, 16, 16, 10, tzinfo=service.timezone)
    service._now = lambda: started_local  # type: ignore[method-assign]
    service.bootstrap_cached_state()
    with database.session() as session:
        snapshots = session.scalars(select(ProductDailySnapshot)).all()
        for snapshot in snapshots:
            snapshot.snapshot_date = "2026-08-16"
            snapshot.source = "automatic"
            snapshot.captured_at = datetime(
                2026, 8, 16, 8, 40, tzinfo=service.timezone
            ).astimezone(timezone.utc)
        snapshots[-1].captured_at = (
            started_local + timedelta(minutes=1)
        ).astimezone(timezone.utc)
        session.commit()
    invalid_id = seed_invalid_actual_traffic_batch(
        database,
        service,
        request_id="exploratory-incomplete-record",
        external_ids=external_ids,
        started_at=started_local,
    )
    with pytest.raises(
        ProductTrafficConflict,
        match="没有覆盖整批商品",
    ):
        service.restore_traffic_batch_exploratory_observation(
            invalid_id,
            request_id="exploratory-incomplete-restore",
            snapshot_date="2026-08-16",
        )


def test_actual_overlap_record_rejects_future_clean_stale_and_unowned_cases(
    tmp_path: Path,
) -> None:
    raw = {"title": "补录边界", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="actual-boundary-shared")
    seed_item(database, {**raw, "title": "不重叠商品"}, external_id="actual-boundary-clean")
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 12, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    source = service.create_traffic_batch(
        request_id="actual-boundary-source",
        item_external_ids=["actual-boundary-shared"],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="来源批次",
    )
    service.start_traffic_batch(source.id)
    service._now = lambda: fixed + timedelta(hours=2)  # type: ignore[method-assign]
    overlapping = service.create_traffic_batch(
        request_id="actual-boundary-overlap",
        item_external_ids=["actual-boundary-shared"],
        planned_at=(fixed + timedelta(hours=1)).astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="真实补录边界",
    )
    clean = service.create_traffic_batch(
        request_id="actual-boundary-clean",
        item_external_ids=["actual-boundary-clean"],
        planned_at=(fixed + timedelta(hours=1)).astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="正常批次",
    )

    with pytest.raises(ProductTrafficConflict, match="确认时由系统记录"):
        service.record_actual_overlap_start(
            overlapping.id,
            request_id="actual-boundary-future",
            expected_updated_at=overlapping.updated_at,
            actual_started_at=(fixed + timedelta(hours=3)).astimezone(timezone.utc),
            confirmed_already_purchased=True,
            items=[],
        )
    with pytest.raises(ProductTrafficConflict, match="没有重叠商品"):
        service.record_actual_overlap_start(
            clean.id,
            request_id="actual-boundary-clean-attempt",
            expected_updated_at=clean.updated_at,
            actual_started_at=None,
            confirmed_already_purchased=True,
            items=[],
        )
    with pytest.raises(ProductTrafficConflict, match="已在其他页面更新"):
        service.record_actual_overlap_start(
            overlapping.id,
            request_id="actual-boundary-stale",
            expected_updated_at=overlapping.updated_at - timedelta(seconds=1),
            actual_started_at=None,
            confirmed_already_purchased=True,
            items=[],
        )
    with database.session() as session:
        monitor = session.scalar(
            select(ProductMonitor)
            .join(Item, Item.id == ProductMonitor.item_id)
            .where(Item.external_id == "actual-boundary-shared")
        )
        assert monitor is not None
        monitor.enabled = False
        session.commit()
    with pytest.raises(ProductOwnershipRestricted, match="未验证为本人或未启用"):
        service.record_actual_overlap_start(
            overlapping.id,
            request_id="actual-boundary-unowned",
            expected_updated_at=overlapping.updated_at,
            actual_started_at=None,
            confirmed_already_purchased=True,
            items=[],
        )


def test_planned_batch_without_prepared_t0_is_not_reported_as_reliable(
    tmp_path: Path,
) -> None:
    raw = {"title": "待准备基线", "browseCnt": 20, "itemStatusStr": "在售"}
    _database, _adapter, service = build_service(tmp_path, raw)
    seed_item(_database, raw, external_id="pending-baseline")
    service.bootstrap_cached_state()
    planned = service.create_traffic_batch(
        request_id="pending-baseline-create",
        item_external_ids=["pending-baseline"],
        planned_at=datetime.now(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="尚未准备",
    )
    assert planned.baseline_status == "pending"
    assert planned.has_reliable_baseline is False


def test_overlap_recording_migration_upgrades_legacy_sqlite_without_rewrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-overlap.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE product_traffic_batches ("
            "id VARCHAR(128) PRIMARY KEY, status VARCHAR(32) NOT NULL)"
        )
        connection.execute(
            "INSERT INTO product_traffic_batches (id, status) VALUES (?, ?)",
            ("legacy-batch", "observing"),
        )
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        assert migrate_product_traffic_overlap_recording_schema(connection) is True
        assert migrate_product_traffic_overlap_recording_schema(connection) is False
        row = connection.exec_driver_sql(
            "SELECT status, recording_mode, attribution_status "
            "FROM product_traffic_batches WHERE id='legacy-batch'"
        ).one()
    assert tuple(row) == ("observing", "standard", "clean")


def test_semantic_change_creates_exactly_one_new_plan_version_with_factors(
    tmp_path: Path,
) -> None:
    raw = {"title": "方案变化商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    for index in range(5):
        seed_item(
            database,
            {**raw, "title": f"方案变化商品 {index}"},
            external_id=f"plan-change-{index}",
        )
    fixed = datetime(2026, 8, 12, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    prepare_service(service)
    first = service.refresh_operating_plan()
    traffic_slot = next(slot for slot in first.slots if slot.action_type == "traffic")
    batch = service.create_traffic_batch(
        request_id="request-plan-change",
        item_external_ids=[f"plan-change-{index}" for index in range(5)],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=traffic_slot.id,
        note="真实写入改变经营安排",
    )
    service.start_traffic_batch(batch.id)
    with database.session() as session:
        plans = session.query(ProductOperatingPlan).order_by(ProductOperatingPlan.version).all()
        assert len(plans) == 2
        assert plans[-1].version == first.version + 1
    current = service.overview().operating_plan
    assert current.version == first.version + 1
    assert current.slots[0].status == "executed"
    assert current.slots[0].batch_id == batch.id
    assert any(
        "真实执行事实已冻结" in factor
        for factor in current.slots[0].change_factors
    )




def test_traffic_batch_cost_enters_ledger_once_and_updates_in_place(
    tmp_path: Path,
) -> None:
    raw = {"title": "服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="ledger-traffic-item")
    service.bootstrap_cached_state()
    assert service.ledger is not None

    batch = service.create_traffic_batch(
        request_id="request-ledger-traffic",
        item_external_ids=["ledger-traffic-item"],
        planned_at=datetime.now(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="先建立计划，不应记账",
    )
    revision, snapshot = service.ledger.get()
    assert revision == 0
    assert snapshot["expenses"] == []

    subscription = service.event_hub.subscribe()
    service.start_traffic_batch(batch.id)
    revision, snapshot = service.ledger.get()
    assert revision == 1
    assert len(snapshot["expenses"]) == 1
    assert snapshot["expenses"][0]["id"] == f"expense-traffic-{batch.id}"
    assert snapshot["expenses"][0]["category"] == "traffic"
    assert snapshot["expenses"][0]["amount"] == pytest.approx(5.9)
    event_types = [subscription.queue.get_nowait()["type"] for _ in range(2)]
    assert event_types == ["product_traffic_batch_updated", "ledger_updated"]

    service.start_traffic_batch(batch.id)
    repeated_revision, repeated_snapshot = service.ledger.get()
    assert repeated_revision == revision
    assert len(repeated_snapshot["expenses"]) == 1

    service.complete_traffic_batch(
        batch.id,
        completed_at=datetime.now(timezone.utc),
        actual_cost=6,
        total_exposure=1_000,
        note="按实际支付修正",
    )
    completed_revision, completed_snapshot = service.ledger.get()
    assert completed_revision == 2
    assert len(completed_snapshot["expenses"]) == 1
    assert completed_snapshot["expenses"][0]["amount"] == pytest.approx(6)
    with database.session() as session:
        stored = session.get(BusinessExpense, f"expense-traffic-{batch.id}")
        assert stored is not None
        assert stored.amount == pytest.approx(6)
        assert stored.category == "traffic"
    with pytest.raises(RevisionConflict):
        service.ledger.save(default_snapshot(), expected_revision=0)


def test_exposure_analytics_uses_long_tail_and_beijing_time_windows(
    tmp_path: Path,
) -> None:
    raw = {"title": "服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    external_ids = ["analytics-a", "analytics-b", "analytics-c"]
    for index, external_id in enumerate(external_ids):
        seed_item(
            database,
            {**raw, "title": f"分析商品 {index + 1}"},
            external_id=external_id,
        )
    service.bootstrap_cached_state()
    beijing = service.timezone
    scenarios = [
        (external_ids[0], datetime(2026, 8, 1, 10, 20, tzinfo=beijing), 8, 30, 2, 2, 1),
        (external_ids[1], datetime(2026, 8, 4, 10, 40, tzinfo=beijing), 5, 20, 1, 1, 2),
        (external_ids[2], datetime(2026, 8, 7, 20, 10, tzinfo=beijing), 4, 8, 0, 0, 1),
    ]

    for index, (
        external_id,
        started_local,
        h1_browse,
        h24_browse,
        h24_inquiry,
        h24_want,
        h24_collect,
    ) in enumerate(scenarios):
        service._now = lambda started_local=started_local: started_local  # type: ignore[method-assign]
        batch = service.create_traffic_batch(
            request_id=f"request-analytics-{index}",
            item_external_ids=[external_id],
            planned_at=started_local.astimezone(timezone.utc),
            actual_cost=6,
            plan_slot_id=None,
            note="时段对比",
        )
        started = service.start_traffic_batch(batch.id)
        with database.session() as session:
            stored_batch = session.get(ProductTrafficBatch, batch.id)
            assert stored_batch is not None
            stored_batch.started_at = started_local.astimezone(timezone.utc)
            for batch_item in session.query(ProductTrafficBatchItem).filter_by(
                batch_id=batch.id
            ):
                batch_item.baseline_source = "manual"
            session.commit()
        service.complete_traffic_batch(
            batch.id,
            completed_at=started_local.astimezone(timezone.utc) + timedelta(hours=1),
            actual_cost=6,
            total_exposure=900,
            note="套餐结束不等于效果结束",
        )
        baseline = started.products[0]
        service._now = lambda started_local=started_local: started_local + timedelta(hours=1)  # type: ignore[method-assign]
        service.record_traffic_checkpoint(
            batch.id,
            checkpoint="h1",
            recorded_at=started_local.astimezone(timezone.utc) + timedelta(hours=1),
            items=[{
                "external_id": external_id,
                "browse_count": baseline.baseline_browse_count + h1_browse,
                "collect_count": baseline.baseline_collect_count,
                "want_count": baseline.baseline_want_count,
                "inquiry_count": baseline.baseline_inquiry_count,
            }],
            note="只记录早期变化",
        )
        service._now = lambda started_local=started_local: started_local + timedelta(hours=24)  # type: ignore[method-assign]
        service.record_traffic_checkpoint(
            batch.id,
            checkpoint="h24",
            recorded_at=started_local.astimezone(timezone.utc) + timedelta(hours=24),
            items=[{
                "external_id": external_id,
                "browse_count": baseline.baseline_browse_count + h24_browse,
                "collect_count": baseline.baseline_collect_count + h24_collect,
                "want_count": baseline.baseline_want_count + h24_want,
                "inquiry_count": baseline.baseline_inquiry_count + h24_inquiry,
            }],
            note="成熟效果",
        )
        service._now = lambda started_local=started_local: started_local + timedelta(hours=72)  # type: ignore[method-assign]
        service.record_traffic_checkpoint(
            batch.id,
            checkpoint="h72",
            recorded_at=started_local.astimezone(timezone.utc) + timedelta(hours=72),
            items=[{
                "external_id": external_id,
                "browse_count": baseline.baseline_browse_count + h24_browse,
                "collect_count": baseline.baseline_collect_count + h24_collect,
                "want_count": baseline.baseline_want_count + h24_want,
                "inquiry_count": baseline.baseline_inquiry_count + h24_inquiry,
            }],
            note="完成归因窗口",
        )

    overview = service.overview()
    analytics = overview.exposure_analytics
    assert analytics.eligible_batch_count == 3
    assert analytics.excluded_batch_count == 0
    assert analytics.browse_delta == 58
    assert analytics.inquiry_delta == 3
    assert analytics.want_delta == 3
    assert analytics.collect_delta == 4
    assert analytics.cost_per_inquiry == pytest.approx(6)
    assert analytics.best_time_bucket == "10:00–11:59"
    assert analytics.time_buckets[0].recommended is True
    assert analytics.time_buckets[0].batch_count == 2
    h1 = next(value for value in analytics.checkpoints if value.checkpoint == "h1")
    h24 = next(value for value in analytics.checkpoints if value.checkpoint == "h24")
    assert h1.browse_delta == 17
    assert h24.browse_delta == 58
    assert h24.average_inquiry_delta == pytest.approx(1)
    assert overview.traffic_summary.effective_batch_count == 3
    assert all(
        slot.scheduled_time == "10:00"
        for slot in overview.operating_plan.slots
        if slot.action_type == "traffic"
    )


def test_overlapping_mature_batches_are_excluded_from_time_recommendations(
    tmp_path: Path,
) -> None:
    raw = {"title": "重叠商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="overlap-item")
    service.bootstrap_cached_state()
    started_times = [
        datetime(2026, 8, 6, 10, 0, tzinfo=service.timezone),
        datetime(2026, 8, 7, 10, 0, tzinfo=service.timezone),
    ]
    for index, started_local in enumerate(started_times):
        service._now = lambda current=started_local: current  # type: ignore[method-assign]
        batch = service.create_traffic_batch(
            request_id=f"request-overlap-{index}",
            item_external_ids=["overlap-item"],
            planned_at=started_local.astimezone(timezone.utc),
            actual_cost=6,
            plan_slot_id=None,
            note="重叠归因测试",
        )
        if index == 0:
            started = service.start_traffic_batch(batch.id)
        else:
            # Preserve coverage for legacy/imported overlapping rows. New
            # public starts reject this state before it can be created.
            with database.session() as session:
                stored_batch = session.get(ProductTrafficBatch, batch.id)
                assert stored_batch is not None
                stored_batch.status = "running"
                stored_batch.started_at = started_local.astimezone(timezone.utc)
                for batch_item in session.query(ProductTrafficBatchItem).filter_by(
                    batch_id=batch.id
                ):
                    batch_item.baseline_captured_at = started_local.astimezone(
                        timezone.utc
                    )
                session.commit()
            started = next(
                value
                for value in service.overview().traffic_batches
                if value.id == batch.id
            )
        with database.session() as session:
            stored_batch = session.get(ProductTrafficBatch, batch.id)
            assert stored_batch is not None
            stored_batch.started_at = started_local.astimezone(timezone.utc)
            session.commit()
        baseline = started.products[0]
        service._now = lambda current=started_local: current + timedelta(hours=24)  # type: ignore[method-assign]
        service.record_traffic_checkpoint(
            batch.id,
            checkpoint="h24",
            recorded_at=started_local.astimezone(timezone.utc) + timedelta(hours=24),
            items=[{
                "external_id": "overlap-item",
                "browse_count": baseline.baseline_browse_count + 10,
                "collect_count": baseline.baseline_collect_count,
                "want_count": baseline.baseline_want_count,
                "inquiry_count": baseline.baseline_inquiry_count + 1,
            }],
            note="成熟但与另一批重叠",
        )

    analytics = service.overview().exposure_analytics
    assert analytics.eligible_batch_count == 0
    assert analytics.excluded_batch_count == 2
    assert analytics.best_time_bucket is None
    assert analytics.time_buckets == []


def test_capacity_guard_stops_all_planned_traffic(tmp_path: Path) -> None:
    raw = {"title": "服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    for index in range(4):
        seed_item(database, {**raw, "title": f"商品 {index}"}, external_id=f"capacity-item-{index}")
    with database.session() as session:
        for index in range(4):
            customer_id = f"capacity-customer-{index}"
            session.add(BusinessCustomer(id=customer_id, name=f"客户 {index}"))
            session.add(
                BusinessProject(
                    id=f"capacity-project-{index}",
                    name=f"项目 {index}",
                    customer_id=customer_id,
                    status="in_progress",
                )
            )
        session.commit()

    prepare_service(service)
    overview = service.overview()

    assert overview.summary.active_projects == 4
    assert all(slot.action_type != "traffic" for slot in overview.operating_plan.slots)
    assert all(
        recommendation.strategy_code == "capacity_guard"
        for recommendation in overview.recommendations
    )


@pytest.mark.asyncio
async def test_v24_manual_t0_uses_actual_start_time_and_is_idempotent(
    tmp_path: Path,
) -> None:
    raw = {"title": "实际时间商品", "browseCnt": 30, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    external_id = "v24-actual-time"
    seed_item(database, raw, external_id=external_id)
    service.bootstrap_cached_state()
    planned = datetime(2026, 8, 12, 16, 0, tzinfo=service.timezone)
    actual = planned + timedelta(minutes=12)
    service._now = lambda: actual  # type: ignore[method-assign]
    batch = service.create_traffic_batch(
        request_id="v24-create-actual-time",
        item_external_ids=[external_id],
        planned_at=planned.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="计划与实际时间分离",
    )
    latest = service.product(external_id)
    prepared = await service.prepare_traffic_baseline(
        batch.id,
        request_id="v24-baseline-actual-time",
        expected_updated_at=batch.updated_at,
        mode="manual",
        items=[{
            "external_id": external_id,
            "browse_count": latest.browse_count,
            "collect_count": latest.collect_count,
            "want_count": latest.want_count,
            "inquiry_count": latest.inquiry_count,
        }],
    )
    started = service.start_traffic_batch(
        batch.id,
        request_id="v24-start-actual-time",
        expected_updated_at=prepared.updated_at,
        expected_baseline_captured_at=prepared.baseline_prepared_at,
    )
    replay = service.start_traffic_batch(
        batch.id,
        request_id="v24-start-actual-time",
        expected_updated_at=prepared.updated_at,
        expected_baseline_captured_at=prepared.baseline_prepared_at,
    )

    assert service._utc(started.started_at) == actual.astimezone(timezone.utc)
    assert started.planned_actual_delta_minutes == 12
    assert started.planned_actual_delta_label == "较计划晚 12 分钟"
    assert service._utc(started.due_at) == actual.astimezone(timezone.utc) + timedelta(hours=1)
    assert replay.id == started.id
    with database.session() as session:
        assert session.query(ProductTrafficBatchEvent).filter_by(
            request_id="v24-start-actual-time"
        ).count() == 1


@pytest.mark.asyncio
async def test_confirmation_at_1620_anchors_every_checkpoint_to_actual_minute(
    tmp_path: Path,
) -> None:
    raw = {"title": "16时20分时间锚点", "browseCnt": 30, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    external_id = "actual-minute-anchor"
    seed_item(database, raw, external_id=external_id)
    service.bootstrap_cached_state()
    planned = datetime(2026, 8, 13, 16, 0, tzinfo=service.timezone)
    clicked = planned.replace(minute=20, second=47, microsecond=321000)
    service._now = lambda: clicked  # type: ignore[method-assign]
    batch = service.create_traffic_batch(
        request_id="actual-minute-create",
        item_external_ids=[external_id],
        planned_at=planned.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="确认时间为唯一锚点",
    )
    latest = service.product(external_id)
    prepared = await service.prepare_traffic_baseline(
        batch.id,
        request_id="actual-minute-baseline",
        expected_updated_at=batch.updated_at,
        mode="manual",
        items=[{
            "external_id": external_id,
            "browse_count": latest.browse_count,
            "collect_count": latest.collect_count,
            "want_count": latest.want_count,
            "inquiry_count": latest.inquiry_count,
        }],
    )
    current = service.start_traffic_batch(
        batch.id,
        request_id="actual-minute-start",
        expected_updated_at=prepared.updated_at,
        expected_baseline_captured_at=prepared.baseline_prepared_at,
    )
    actual = planned.replace(minute=20)
    assert service._local(current.started_at) == actual
    assert service._traffic_datetime_label(current.started_at) == "8月13日16时20分"

    due_times = {
        "h1": actual + timedelta(hours=1),
        "h6": actual + timedelta(hours=6),
        "h24": actual + timedelta(hours=24),
        "h72": actual + timedelta(hours=72),
    }
    values = [{
        "external_id": external_id,
        "browse_count": latest.browse_count,
        "collect_count": latest.collect_count,
        "want_count": latest.want_count,
        "inquiry_count": latest.inquiry_count,
    }]
    assert service._local(current.due_at) == due_times["h1"]
    for checkpoint in ("h1", "h6", "h24", "h72"):
        service._now = lambda checkpoint=checkpoint: due_times[checkpoint]  # type: ignore[method-assign]
        current = service.record_traffic_checkpoint(
            batch.id,
            checkpoint=checkpoint,
            recorded_at=None,
            items=values,
            note=f"记录 {checkpoint}",
        )
        remaining = [value for value in ("h1", "h6", "h24", "h72") if value not in current.completed_checkpoints]
        if remaining:
            assert service._local(current.due_at) == due_times[remaining[0]]
        else:
            assert current.due_at is None
    assert current.status == "closed"
    assert current.completed_checkpoints == ["h1", "h6", "h24", "h72"]

    assert service._traffic_datetime_label(datetime(2026, 8, 13, 1, 5, tzinfo=timezone.utc)) == "8月13日9时05分"
    assert service._traffic_datetime_label(datetime(2026, 8, 31, 16, 5, tzinfo=timezone.utc)) == "9月1日0时05分"


def test_traffic_duration_label_keeps_long_plan_offsets_readable() -> None:
    assert ProductIntelligenceService._duration_label(0) == "0 分钟"
    assert ProductIntelligenceService._duration_label(12) == "12 分钟"
    assert ProductIntelligenceService._duration_label(60) == "1 小时"
    assert ProductIntelligenceService._duration_label(1439) == "23 小时 59 分钟"


@pytest.mark.asyncio
async def test_automatic_checkpoint_jobs_use_actual_start_and_collect_once(
    tmp_path: Path,
) -> None:
    raw = {
        "title": "自动检查点",
        "browseCnt": 30,
        "collectCnt": 2,
        "wantCnt": 3,
        "itemStatusStr": "在售",
    }
    database, adapter, service = build_service(tmp_path, raw)
    external_id = "automatic-checkpoint-item"
    seed_item(database, raw, external_id=external_id)
    service.bootstrap_cached_state()
    started_local = datetime(2026, 8, 14, 16, 20, tzinfo=service.timezone)
    service._now = lambda: started_local  # type: ignore[method-assign]
    batch = service.create_traffic_batch(
        request_id="auto-checkpoint-create",
        item_external_ids=[external_id],
        planned_at=(started_local - timedelta(minutes=20)).astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="自动采集",
        checkpoint_collection_mode="auto",
    )
    latest = service.product(external_id)
    prepared = await service.prepare_traffic_baseline(
        batch.id,
        request_id="auto-checkpoint-baseline",
        expected_updated_at=batch.updated_at,
        mode="manual",
        items=[{
            "external_id": external_id,
            "browse_count": latest.browse_count,
            "collect_count": latest.collect_count,
            "want_count": latest.want_count,
            "inquiry_count": latest.inquiry_count,
        }],
    )
    started = service.start_traffic_batch(
        batch.id,
        request_id="auto-checkpoint-start",
        expected_updated_at=prepared.updated_at,
        expected_baseline_captured_at=prepared.baseline_prepared_at,
    )
    assert started.checkpoint_collection_mode == "auto"
    assert [service._local(job.scheduled_for) for job in started.checkpoint_jobs] == [
        started_local + timedelta(hours=1),
        started_local + timedelta(hours=6),
        started_local + timedelta(hours=24),
        started_local + timedelta(hours=72),
    ]

    adapter.raw["browseCnt"] = 38
    service._now = lambda: started_local + timedelta(hours=1, minutes=3)  # type: ignore[method-assign]
    await service._dispatch_due_traffic_checkpoint_jobs()
    assert adapter.calls == [external_id]
    with database.session() as session:
        job = session.scalar(
            select(ProductTrafficCheckpointJob).where(
                ProductTrafficCheckpointJob.batch_id == batch.id,
                ProductTrafficCheckpointJob.checkpoint == "h1",
            )
        )
        assert job is not None
        assert job.status == "completed"
        assert job.attempt_count == 1
        assert job.capture_delay_minutes == 3
        checkpoint = session.scalar(
            select(ProductTrafficCheckpoint).where(
                ProductTrafficCheckpoint.batch_id == batch.id,
                ProductTrafficCheckpoint.checkpoint == "h1",
            )
        )
        assert checkpoint is not None and checkpoint.source == "automatic"
    await service._dispatch_due_traffic_checkpoint_jobs()
    assert adapter.calls == [external_id]


@pytest.mark.asyncio
async def test_automatic_checkpoint_access_verification_keeps_partial_results(
    tmp_path: Path,
) -> None:
    raw = {"title": "自动熔断", "browseCnt": 30, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    ids = ["checkpoint-fuse-a", "checkpoint-fuse-b", "checkpoint-fuse-c"]
    for external_id in ids:
        seed_item(database, {**raw, "title": external_id}, external_id=external_id)
    service.bootstrap_cached_state()
    started_local = datetime(2026, 8, 14, 10, 0, tzinfo=service.timezone)
    service._now = lambda: started_local  # type: ignore[method-assign]
    batch = service.create_traffic_batch(
        request_id="checkpoint-fuse-create",
        item_external_ids=ids,
        planned_at=started_local.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="熔断",
    )
    values = []
    for external_id in ids:
        product = service.product(external_id)
        values.append({
            "external_id": external_id,
            "browse_count": product.browse_count,
            "collect_count": product.collect_count,
            "want_count": product.want_count,
            "inquiry_count": product.inquiry_count,
        })
    prepared = await service.prepare_traffic_baseline(
        batch.id,
        request_id="checkpoint-fuse-baseline",
        expected_updated_at=batch.updated_at,
        mode="manual",
        items=values,
    )
    service.start_traffic_batch(
        batch.id,
        request_id="checkpoint-fuse-start",
        expected_updated_at=prepared.updated_at,
        expected_baseline_captured_at=prepared.baseline_prepared_at,
    )

    class PartialVerificationAdapter(FakeProductAdapter):
        async def fetch_item(self, item_id: str) -> ItemInfo:
            self.calls.append(item_id)
            if item_id == ids[1]:
                raise AdapterAccessVerificationError("private verification body")
            return ItemInfo(
                external_id=item_id,
                title=item_id,
                price="¥100",
                description="测试",
                seller_id="seller",
                raw={**self.raw, "title": item_id, "browseCnt": 35},
            )

    adapter = PartialVerificationAdapter(raw)
    service.adapter = adapter
    service._now = lambda: started_local + timedelta(hours=1)  # type: ignore[method-assign]
    await service._dispatch_due_traffic_checkpoint_jobs()
    assert adapter.calls == ids[:2]
    with database.session() as session:
        job = session.scalar(
            select(ProductTrafficCheckpointJob).where(
                ProductTrafficCheckpointJob.batch_id == batch.id,
                ProductTrafficCheckpointJob.checkpoint == "h1",
            )
        )
        assert job is not None and job.status == "circuit_open"
        rows = session.scalars(
            select(ProductTrafficCheckpointJobItem)
            .where(ProductTrafficCheckpointJobItem.job_id == job.id)
            .order_by(ProductTrafficCheckpointJobItem.id)
        ).all()
        assert [row.status for row in rows] == [
            "completed",
            "failed",
            "protection_skipped",
        ]


@pytest.mark.asyncio
async def test_manual_checkpoint_mode_only_marks_due_job_waiting_manual(
    tmp_path: Path,
) -> None:
    raw = {"title": "人工检查点", "browseCnt": 20, "itemStatusStr": "在售"}
    database, adapter, service = build_service(tmp_path, raw)
    external_id = "manual-checkpoint-item"
    seed_item(database, raw, external_id=external_id)
    service.bootstrap_cached_state()
    started_local = datetime(2026, 8, 14, 8, 0, tzinfo=service.timezone)
    service._now = lambda: started_local  # type: ignore[method-assign]
    batch = service.create_traffic_batch(
        request_id="manual-checkpoint-create",
        item_external_ids=[external_id],
        planned_at=started_local.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="人工提醒",
        checkpoint_collection_mode="manual",
    )
    latest = service.product(external_id)
    prepared = await service.prepare_traffic_baseline(
        batch.id,
        request_id="manual-checkpoint-baseline",
        expected_updated_at=batch.updated_at,
        mode="manual",
        items=[{
            "external_id": external_id,
            "browse_count": latest.browse_count,
            "collect_count": latest.collect_count,
            "want_count": latest.want_count,
            "inquiry_count": latest.inquiry_count,
        }],
    )
    service.start_traffic_batch(
        batch.id,
        request_id="manual-checkpoint-start",
        expected_updated_at=prepared.updated_at,
        expected_baseline_captured_at=prepared.baseline_prepared_at,
    )
    service._now = lambda: started_local + timedelta(hours=1)  # type: ignore[method-assign]
    await service._dispatch_due_traffic_checkpoint_jobs()
    assert adapter.calls == []
    with database.session() as session:
        job = session.scalar(
            select(ProductTrafficCheckpointJob).where(
                ProductTrafficCheckpointJob.batch_id == batch.id,
                ProductTrafficCheckpointJob.checkpoint == "h1",
            )
        )
        assert job is not None and job.status == "waiting_manual"


@pytest.mark.asyncio
async def test_v24_manual_t0_rejects_partial_stale_and_conflicting_requests(
    tmp_path: Path,
) -> None:
    raw = {"title": "T0 审计", "browseCnt": 40, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    ids = ["v24-t0-a", "v24-t0-b"]
    for external_id in ids:
        seed_item(database, raw, external_id=external_id)
    service.bootstrap_cached_state()
    fixed = datetime(2026, 8, 12, 18, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    batch = service.create_traffic_batch(
        request_id="v24-create-t0",
        item_external_ids=ids,
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="整批 T0",
    )
    first = service.product(ids[0])
    with pytest.raises(ProductTrafficConflict, match="全部商品"):
        await service.prepare_traffic_baseline(
            batch.id,
            request_id="v24-baseline-partial",
            expected_updated_at=batch.updated_at,
            mode="manual",
            items=[{
                "external_id": ids[0],
                "browse_count": first.browse_count,
                "collect_count": first.collect_count,
                "want_count": first.want_count,
                "inquiry_count": first.inquiry_count,
            }],
        )
    items = [
        {
            "external_id": value,
            "browse_count": service.product(value).browse_count,
            "collect_count": service.product(value).collect_count,
            "want_count": service.product(value).want_count,
            "inquiry_count": service.product(value).inquiry_count,
        }
        for value in ids
    ]
    prepared = await service.prepare_traffic_baseline(
        batch.id,
        request_id="v24-baseline-complete",
        expected_updated_at=batch.updated_at,
        mode="manual",
        items=items,
    )
    with pytest.raises(ProductTrafficConflict, match="request_id"):
        await service.prepare_traffic_baseline(
            batch.id,
            request_id="v24-baseline-complete",
            expected_updated_at=prepared.updated_at,
            mode="manual",
            items=[{**value, "browse_count": value["browse_count"] + 1} for value in items],
        )
    service._now = lambda: fixed + timedelta(minutes=31)  # type: ignore[method-assign]
    with pytest.raises(ProductTrafficConflict, match="超过 30 分钟"):
        service.start_traffic_batch(
            batch.id,
            request_id="v24-start-expired-t0",
            expected_updated_at=prepared.updated_at,
            expected_baseline_captured_at=prepared.baseline_prepared_at,
        )


@pytest.mark.asyncio
async def test_v24_remote_t0_access_verification_opens_batch_fuse(
    tmp_path: Path,
) -> None:
    raw = {"title": "远程 T0", "browseCnt": 50, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    ids = ["v24-fuse-a", "v24-fuse-b", "v24-fuse-c"]
    for external_id in ids:
        seed_item(database, raw, external_id=external_id)
    service.bootstrap_cached_state()

    class VerifyingAdapter(FakeProductAdapter):
        async def fetch_item(self, item_id: str) -> ItemInfo:
            self.calls.append(item_id)
            raise AdapterAccessVerificationError("private platform body")

    adapter = VerifyingAdapter(raw)
    service.adapter = adapter
    batch = service.create_traffic_batch(
        request_id="v24-create-fuse",
        item_external_ids=ids,
        planned_at=datetime.now(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="熔断测试",
    )
    with pytest.raises(Exception, match="整批 T0"):
        await service.prepare_traffic_baseline(
            batch.id,
            request_id="v24-baseline-fuse",
            expected_updated_at=batch.updated_at,
            mode="remote_refresh",
            items=[],
        )
    assert adapter.calls == [ids[0]]
    with pytest.raises(Exception, match="整批 T0"):
        await service.prepare_traffic_baseline(
            batch.id,
            request_id="v24-baseline-fuse",
            expected_updated_at=batch.updated_at,
            mode="remote_refresh",
            items=[],
        )
    assert adapter.calls == [ids[0]]
    with database.session() as session:
        monitors = session.scalars(
            select(ProductMonitor)
            .join(Item, Item.id == ProductMonitor.item_id)
            .where(Item.external_id.in_(ids))
            .order_by(Item.external_id)
        ).all()
        assert monitors[0].last_error_code == "access_verification"
        assert all(
            value.last_error_code == "access_verification_batch_stopped"
            for value in monitors[1:]
        )
        stored = session.get(ProductTrafficBatch, batch.id)
        assert stored is not None and stored.baseline_prepared_at is None
        assert all(
            value.baseline_source == "pending"
            for value in session.query(ProductTrafficBatchItem).filter_by(
                batch_id=batch.id
            )
        )


def test_v24_replan_preview_is_read_only_and_commit_preserves_batch_identity(
    tmp_path: Path,
) -> None:
    raw = {"title": "轮换商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    ids = [f"v24-rotate-{index}" for index in range(10)]
    for index, external_id in enumerate(ids):
        seed_item(database, {**raw, "title": f"轮换商品 {index}"}, external_id=external_id)
    service.bootstrap_cached_state()
    fixed = datetime.now(service.timezone).replace(
        hour=9, minute=0, second=0, microsecond=0
    ) - timedelta(hours=72)
    service._now = lambda: fixed  # type: ignore[method-assign]
    source = service.create_traffic_batch(
        request_id="v24-source-create",
        item_external_ids=ids[:5],
        planned_at=fixed.astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="旧 T0 来源批次",
    )
    started = service.start_traffic_batch(source.id)
    service._now = lambda: fixed + timedelta(hours=72)  # type: ignore[method-assign]
    service.record_traffic_checkpoint(
        source.id,
        checkpoint="h72",
        recorded_at=(fixed + timedelta(hours=72)).astimezone(timezone.utc),
        items=[{
            "external_id": value.external_id,
            "browse_count": value.baseline_browse_count + 10,
            "collect_count": value.baseline_collect_count,
            "want_count": value.baseline_want_count + 1,
            "inquiry_count": value.baseline_inquiry_count + (1 if index < 3 else 0),
        } for index, value in enumerate(started.products)],
        note="旧基线批次即使有咨询也不能保留",
    )
    planned = service.create_traffic_batch(
        request_id="v24-planned-create",
        item_external_ids=ids[:5],
        planned_at=(fixed + timedelta(hours=73)).astimezone(timezone.utc),
        actual_cost=5.9,
        plan_slot_id=None,
        note="等待人工重排",
    )
    before_ids = [value.external_id for value in planned.products]
    preview = service.traffic_replan_preview(planned.id)
    unchanged = service.traffic_batches(limit=20)
    current = next(value for value in unchanged.items if value.id == planned.id)

    assert [value.external_id for value in current.products] == before_ids
    assert preview.retained_products == []
    assert len(preview.proposed_products) >= 3
    assert all(value.external_id not in ids[:5] for value in preview.proposed_products)
    committed = service.replan_traffic_batch(
        planned.id,
        request_id="v24-replan-commit",
        expected_updated_at=preview.updated_at,
        preview_hash=preview.preview_hash,
    )
    assert committed.id == planned.id
    assert committed.actual_cost == pytest.approx(5.9)
    assert committed.baseline_status == "pending"
    assert [value.external_id for value in committed.products] == [
        value.external_id for value in preview.proposed_products
    ]
    replay = service.replan_traffic_batch(
        planned.id,
        request_id="v24-replan-commit",
        expected_updated_at=preview.updated_at,
        preview_hash=preview.preview_hash,
    )
    assert replay.id == committed.id


def test_v24_traffic_batch_cursor_page_is_stable(tmp_path: Path) -> None:
    raw = {"title": "分页商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw, external_id="v24-page-item")
    service.bootstrap_cached_state()
    for index in range(3):
        service.create_traffic_batch(
            request_id=f"v24-page-create-{index}",
            item_external_ids=["v24-page-item"],
            planned_at=datetime.now(timezone.utc) + timedelta(hours=index),
            actual_cost=5.9,
            plan_slot_id=None,
            note=f"第 {index + 1} 批",
        )
    first = service.traffic_batches(limit=2)
    assert len(first.items) == 2
    assert first.has_more is True and first.next_cursor
    second = service.traffic_batches(cursor=first.next_cursor, limit=2)
    assert len(second.items) == 1
    assert second.has_more is False
    assert {value.id for value in first.items}.isdisjoint(
        {value.id for value in second.items}
    )


def test_daily_market_keywords_are_deterministic_and_hypothesis_labeled(
    tmp_path: Path,
) -> None:
    raw = {"title": "已有服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    _database, _adapter, service = build_service(tmp_path, raw)
    fixed = datetime(2026, 8, 9, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    prepare_service(service)

    first = service.market_reference()
    second = service.market_reference()

    assert len(first.recommendations) == 3
    assert [value.keyword for value in first.recommendations] == [
        value.keyword for value in second.recommendations
    ]
    assert first.selected_keyword == first.recommendations[0].keyword
    assert "不代表闲鱼官方热度" in first.safety_note or all(
        "验证" in value.reason or value.confidence != "low"
        for value in first.recommendations
    )


def test_custom_keyword_replaces_today_recommendation_without_becoming_common(
    tmp_path: Path,
) -> None:
    raw = {"title": "已有服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    _database, _adapter, service = build_service(tmp_path, raw)
    fixed = datetime(2026, 8, 9, 11, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]

    custom = service.update_market_keyword(
        mode="custom", keyword="uni-app 页面修改", save_as_common=False
    )

    assert custom.mode == "custom"
    assert custom.selected_keyword == "uni-app 页面修改"
    assert custom.common_keywords == []
    common = service.update_market_keyword(
        mode="custom", keyword="uni-app 页面修改", save_as_common=True
    )
    assert common.common_keywords == ["uni-app 页面修改"]


def test_same_keyword_day_import_is_upserted_and_strictly_validated(
    tmp_path: Path,
) -> None:
    raw = {"title": "已有服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    fixed = datetime(2026, 8, 9, 15, 30, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    prepare_service(service)
    plan = service.market_reference()
    payload = {
        "keyword": plan.selected_keyword,
        "captured_at": fixed,
        "results": [
            {"position": 1, "title": "公开搜索结果 A", "price": 99, "tags": ["技术服务"]},
            {"position": 2, "title": "公开搜索结果 B", "price": None, "tags": []},
        ],
        "note": "来自现有 Edge",
    }

    first = service.import_market_reference(**payload)
    payload["results"] = [
        {"position": 1, "title": "更新后的公开结果", "price": 88, "tags": ["开发"]}
    ]
    second = service.import_market_reference(**payload)

    assert first.update_completed is True
    assert second.current_sample is not None
    assert second.current_sample.result_count == 1
    assert second.current_sample.results[0].title == "更新后的公开结果"
    with database.session() as session:
        assert session.query(ProductMarketSample).count() == 1
        assert session.query(ProductMarketSampleResult).count() == 1
    with pytest.raises(ValidationError):
        ProductMarketImportRequest.model_validate(
            {
                **payload,
                "cookie": "must-not-be-accepted",
            }
        )


def test_market_stability_requires_repeated_multi_day_visibility(tmp_path: Path) -> None:
    raw = {"title": "已有服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    fixed = datetime(2026, 8, 9, 16, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    prepare_service(service)
    market = service.market_reference()
    keyword = market.selected_keyword
    with database.session() as session:
        for offset, position in ((2, 3), (1, 5), (0, 4)):
            day = (fixed.date() - timedelta(days=offset)).isoformat()
            sample = ProductMarketSample(
                id=f"sample-{offset}",
                keyword=keyword,
                sample_date=day,
                source="edge_codex",
                captured_at=(fixed - timedelta(days=offset)).astimezone(timezone.utc),
                result_count=1,
                note="",
            )
            session.add(sample)
            session.flush()
            session.add(
                ProductMarketSampleResult(
                    sample_id=sample.id,
                    position=position,
                    title=f"公开结果 {offset}",
                    price=100,
                    tags_json="[]",
                )
            )
        session.commit()

    stability = service.market_reference().stability

    assert stability.status == "stable"
    assert stability.sample_days == 3
    assert "官方" not in stability.label


def test_market_benchmark_derives_repeat_terms_price_range_and_tags(
    tmp_path: Path,
) -> None:
    raw = {"title": "已有服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    fixed = datetime(2026, 8, 9, 16, 30, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    prepare_service(service)
    keyword = service.market_reference().selected_keyword
    seed_market_benchmark(database, keyword=keyword, fixed=fixed)

    benchmark = service.market_reference().benchmark

    assert benchmark.sample_days == 3
    assert benchmark.high_visibility_result_count == 9
    assert benchmark.repeated_result_count >= 2
    assert benchmark.median_price == pytest.approx(100)
    assert benchmark.price_low == pytest.approx(90)
    assert benchmark.price_high == pytest.approx(110)
    assert "开发" in benchmark.common_title_terms
    assert "技术服务" in benchmark.common_tags
    assert benchmark.confidence == "high"
    assert any("公开标价不等于最终成交价" in line for line in benchmark.evidence)


def test_launch_decision_uses_demand_supply_capacity_and_market_benchmark(
    tmp_path: Path,
) -> None:
    raw = {
        "title": "MySQL 数据库接口服务",
        "soldPrice": 300,
        "browseCnt": 80,
        "itemStatusStr": "在售",
    }
    database, _adapter, service = build_service(tmp_path, raw)
    item_id = seed_item(database, raw)
    fixed = datetime(2026, 8, 9, 17, 30, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    with database.session() as session:
        for index in range(3):
            conversation = Conversation(
                external_id=f"launch-demand-{index}",
                customer_id=f"launch-buyer-{index}",
                customer_name=f"客户 {index}",
                item_id=item_id,
            )
            session.add(conversation)
            session.flush()
            session.add(
                Message(
                    external_id=f"launch-message-{index}",
                    platform_message_id=f"launch-message-{index}",
                    conversation_id=conversation.id,
                    sender_id=conversation.customer_id,
                    sender_name=conversation.customer_name,
                    direction="inbound",
                    content="想做网站、网页和前端开发",
                    received_at=(fixed - timedelta(hours=index)).astimezone(timezone.utc),
                )
            )
        session.commit()

    prepare_service(service)
    market = service.market_reference()
    assert market.selected_keyword == "网站功能修改"
    seed_market_benchmark(
        database,
        keyword=market.selected_keyword,
        fixed=fixed,
        title_prefix="网站功能修改",
    )

    recommendation = service.overview().launch_recommendation

    assert recommendation.recommended_action == "launch"
    assert recommendation.ready is True
    assert recommendation.benchmark.confidence == "high"
    assert "交付边界" in recommendation.suggested_product_type
    assert "不要照搬" in recommendation.title_direction
    assert "公开标价中位数" in recommendation.price_reference

    with database.session() as session:
        item = session.get(Item, item_id)
        assert item is not None
        item.title = "网站前端开发服务"
        session.commit()

    existing_supply = service.overview().launch_recommendation
    assert existing_supply.recommended_action == "modify_existing"
    assert existing_supply.ready is False
    assert any("避免重复上新" in line for line in existing_supply.rationale)


def test_modification_suggestion_uses_only_matching_market_theme(
    tmp_path: Path,
) -> None:
    raw = {
        "title": "前端页面美化",
        "soldPrice": 100,
        "browseCnt": 120,
        "itemStatusStr": "在售",
    }
    database, _adapter, service = build_service(tmp_path, raw)
    fixed = datetime(2026, 8, 9, 18, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    item_id = seed_item(
        database,
        raw,
        external_id="market-match-item",
        updated_at=fixed,
    )
    service.bootstrap_cached_state()
    seed_snapshot_history(
        database,
        item_id=item_id,
        fixed=fixed,
        title=raw["title"],
        price=100,
        current_browse=120,
        current_inquiries=0,
    )
    seed_market_benchmark(
        database,
        keyword="网站功能修改",
        fixed=fixed,
        title_prefix="网站前端功能修改",
    )
    seed_market_benchmark(
        database,
        keyword="数据库接口开发",
        fixed=fixed,
        title_prefix="MySQL 数据库 API 开发",
    )

    prepare_service(service)
    suggestion = service.overview().modification_suggestions[0]

    assert suggestion.variable == "description"
    assert suggestion.benchmark_keyword == "网站功能修改"
    assert suggestion.evidence_sources == ["内部表现", "高可见市场参考"]
    assert "交付物" in suggestion.suggested_change
    assert all("数据库接口开发" not in line for line in suggestion.market_evidence)


def test_price_experiment_requires_conversion_gap_and_robust_market_outlier(
    tmp_path: Path,
) -> None:
    raw = {
        "title": "网站前端功能修改",
        "soldPrice": 500,
        "browseCnt": 120,
        "itemStatusStr": "在售",
    }
    database, _adapter, service = build_service(tmp_path, raw)
    fixed = datetime(2026, 8, 9, 18, 30, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    item_id = seed_item(
        database,
        raw,
        external_id="market-price-item",
        updated_at=fixed,
    )
    service.bootstrap_cached_state()
    seed_snapshot_history(
        database,
        item_id=item_id,
        fixed=fixed,
        title=raw["title"],
        price=500,
        current_browse=120,
        current_inquiries=3,
    )
    seed_market_benchmark(
        database,
        keyword="网站功能修改",
        fixed=fixed,
        title_prefix="网站前端功能修改",
    )

    prepare_service(service)
    suggestion = service.overview().modification_suggestions[0]

    assert suggestion.variable == "price"
    assert suggestion.reference_price_range == "¥90–¥110"
    assert suggestion.market_gap is not None
    assert "明显高于" in suggestion.market_gap
    assert "最终金额仍按需求范围与工时确认" in suggestion.suggested_change


def test_launch_guard_uses_capacity_and_marks_missing_market_validation(
    tmp_path: Path,
) -> None:
    raw = {"title": "服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    fixed = datetime(2026, 8, 9, 17, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    with database.session() as session:
        for index in range(service.settings.product_delivery_capacity):
            customer_id = f"market-capacity-customer-{index}"
            session.add(BusinessCustomer(id=customer_id, name=f"客户 {index}"))
            session.add(
                BusinessProject(
                    id=f"market-capacity-project-{index}",
                    name=f"项目 {index}",
                    customer_id=customer_id,
                    status="in_progress",
                )
            )
        session.commit()

    prepare_service(service)
    recommendation = service.overview().launch_recommendation

    assert recommendation.capacity_available == 0
    assert recommendation.ready is False
    assert recommendation.market_validation_required is True
    assert any("容量已满" in line for line in recommendation.rationale)


def test_modification_experiment_prevents_overlap_and_evaluates_after_window(
    tmp_path: Path,
) -> None:
    raw = {
        "title": "需要优化的商品",
        "browseCnt": 120,
        "wantCnt": 2,
        "itemStatusStr": "在售",
    }
    _database, _adapter, service = build_service(tmp_path, raw)
    seed_item(_database, raw, external_id="experiment-item")
    fixed = datetime(2026, 8, 9, 12, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]
    service.bootstrap_cached_state()

    experiment = service.create_modification_experiment(
        "experiment-item",
        variable="description",
        before_value="旧描述",
        after_value="新描述",
        observation_days=7,
    )
    with pytest.raises(ProductMarketConflict):
        service.create_modification_experiment(
            "experiment-item",
            variable="title",
            before_value="旧标题",
            after_value="新标题",
            observation_days=7,
        )
    with pytest.raises(ProductMarketConflict):
        service.update_modification_experiment(
            experiment.id, decision="keep", note="过早判断"
        )

    service._now = lambda: fixed + timedelta(days=8)  # type: ignore[method-assign]
    completed = service.update_modification_experiment(
        experiment.id, decision="keep", note="观察期结束"
    )
    assert completed.status == "completed"
    assert completed.decision == "keep"


@pytest.mark.asyncio
async def test_market_reminder_uses_20_beijing_deduplicates_and_can_snooze(
    tmp_path: Path,
) -> None:
    raw = {"title": "已有服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    fixed = datetime(2026, 8, 9, 20, 5, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]

    await service._dispatch_due_market_reminder()
    await service._dispatch_due_market_reminder()
    with database.session() as session:
        reminders = session.query(ProductMarketReminderLog).all()
        assert len(reminders) == 1
        assert reminders[0].status == "sent"
        assert service._local(reminders[0].scheduled_for).hour == 20

    snoozed = service.snooze_market_reminder(2)
    assert snoozed.reminder.status == "snoozed"
    assert snoozed.reminder.snoozed_until is not None
    skipped = service.skip_market_reminder()
    assert skipped.reminder.status == "skipped"
