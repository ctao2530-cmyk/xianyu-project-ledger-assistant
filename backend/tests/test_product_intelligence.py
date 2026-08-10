from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine

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
    ProductTrafficBatch,
    ProductMarketReminderLog,
    ProductMarketSample,
    ProductMarketSampleResult,
    ProjectSettlementIssueRecord,
)
from backend.app.product_schemas import ProductMarketImportRequest
from backend.app.schema_migrations import migrate_product_browse_accounting_schema
from backend.app.services.event_hub import EventHub
from backend.app.services.product_intelligence import (
    ProductAlreadyCollected,
    ProductIntelligenceService,
    ProductMarketConflict,
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
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    return database, adapter, ProductIntelligenceService(
        database,
        adapter,
        settings,
        EventHub(),
        ledger=ledger,
    )


def seed_item(
    database: Database,
    raw: dict,
    *,
    external_id: str = "123456789",
    updated_at: datetime | None = None,
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
        session.commit()
        return item.id


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

    service.bootstrap_cached_state()
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

    service.bootstrap_cached_state()
    overview = service.overview()

    assert overview.summary.active_projects == 1
    assert all("2/" not in line for item in overview.recommendations for line in item.evidence)


def test_collection_schedule_uses_beijing_time(tmp_path: Path) -> None:
    raw = {"title": "测试商品", "browseCnt": 20, "itemStatusStr": "在售"}
    database, _adapter, service = build_service(tmp_path, raw)
    seed_item(database, raw)

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
    service.bootstrap_cached_state()

    with pytest.raises(ProductOwnershipRestricted, match="不能恢复监测"):
        service.update_monitor("excluded-12345", True)


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
    planned_at = datetime.now(timezone.utc) + timedelta(hours=2)

    batch = service.create_traffic_batch(
        request_id="request-batch-0001",
        item_external_ids=["batch-item-a", "batch-item-b"],
        planned_at=planned_at,
        actual_cost=5.9,
        plan_slot_id=None,
        note="两件商品共用一次套餐",
    )
    started = service.start_traffic_batch(batch.id)
    completed = service.complete_traffic_batch(
        batch.id,
        completed_at=datetime.now(timezone.utc),
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
    service.record_traffic_checkpoint(
        batch.id,
        checkpoint="h1",
        recorded_at=datetime.now(timezone.utc),
        items=values,
        note="一小时只有浏览变化",
    )
    values[0]["inquiry_count"] += 1
    service.record_traffic_checkpoint(
        batch.id,
        checkpoint="h24",
        recorded_at=datetime.now(timezone.utc) + timedelta(hours=24),
        items=values,
        note="24 小时后出现咨询",
    )
    closed = service.record_traffic_checkpoint(
        batch.id,
        checkpoint="h72",
        recorded_at=datetime.now(timezone.utc) + timedelta(hours=72),
        items=values,
        note="72 小时完成观察",
    )

    assert closed.status == "closed"
    assert closed.completed_checkpoints == ["h1", "h24", "h72"]
    assert closed.products[0].inquiry_delta == 1
    overview = service.overview()
    assert overview.traffic_summary.effective_batch_count == 1
    assert "达到 6 个" in overview.traffic_summary.analysis_summary


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
            session.commit()
        service.complete_traffic_batch(
            batch.id,
            completed_at=started_local.astimezone(timezone.utc) + timedelta(hours=1),
            actual_cost=6,
            total_exposure=900,
            note="套餐结束不等于效果结束",
        )
        baseline = started.products[0]
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
        batch = service.create_traffic_batch(
            request_id=f"request-overlap-{index}",
            item_external_ids=["overlap-item"],
            planned_at=started_local.astimezone(timezone.utc),
            actual_cost=6,
            plan_slot_id=None,
            note="重叠归因测试",
        )
        started = service.start_traffic_batch(batch.id)
        with database.session() as session:
            stored_batch = session.get(ProductTrafficBatch, batch.id)
            assert stored_batch is not None
            stored_batch.started_at = started_local.astimezone(timezone.utc)
            session.commit()
        baseline = started.products[0]
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

    overview = service.overview()

    assert overview.summary.active_projects == 4
    assert all(slot.action_type != "traffic" for slot in overview.operating_plan.slots)
    assert all(
        recommendation.strategy_code == "capacity_guard"
        for recommendation in overview.recommendations
    )


def test_daily_market_keywords_are_deterministic_and_hypothesis_labeled(
    tmp_path: Path,
) -> None:
    raw = {"title": "已有服务商品", "browseCnt": 20, "itemStatusStr": "在售"}
    _database, _adapter, service = build_service(tmp_path, raw)
    fixed = datetime(2026, 8, 9, 10, 0, tzinfo=service.timezone)
    service._now = lambda: fixed  # type: ignore[method-assign]

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
    service.bootstrap_cached_state()
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
