from __future__ import annotations

from datetime import timezone

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from backend.app.adapters.base import ItemInfo, OwnedListingInfo
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.ledger import LedgerService
from backend.app.models import Item, ProductDailySnapshot, ProductMonitor, ProductRegistrationRequest
from backend.app.services.event_hub import EventHub
from backend.app.services.product_intelligence import (
    ProductCollectionUnavailable,
    ProductIntelligenceService,
    ProductReferenceInvalid,
)
from backend.app.services.product_references import (
    ProductReferenceResolutionError,
    direct_product_id,
    resolve_product_reference,
)


class RegistrationAdapter:
    own_user_id = "seller"

    def __init__(self) -> None:
        self.list_calls = 0
        self.item_calls: list[str] = []
        self.owned_statuses = {
            "owned-1": "在售",
            "owned-2": "在售",
            "down-1": "已下架",
            "unknown-1": "状态未知",
        }
        self.shared_statuses: dict[str, str] = {}

    async def list_owned_items(self, limit: int = 100):
        self.list_calls += 1
        return [
            OwnedListingInfo("owned-1", "我的网站开发", "¥199", self.owned_statuses["owned-1"]),
            OwnedListingInfo("owned-2", "我的数据库开发", "¥299", self.owned_statuses["owned-2"]),
            OwnedListingInfo("down-1", "已经下架", "¥99", self.owned_statuses["down-1"]),
            OwnedListingInfo("unknown-1", "状态未知", "¥88", self.owned_statuses["unknown-1"]),
        ][:limit]

    async def fetch_item(self, item_id: str):
        self.item_calls.append(item_id)
        seller = "seller" if item_id != "other-1" else "another-seller"
        status = self.shared_statuses.get(item_id, "0")
        return ItemInfo(
            external_id=item_id,
            title="分享商品",
            price="¥188",
            description="商品说明",
            raw={"title": "分享商品", "soldPrice": "188", "itemStatus": status, "trackParams": {"sellerId": seller}},
            seller_id=seller,
        )


def build_registration_service(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'registration.db'}")
    database.create_all()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'registration.db'}",
        xianyu_cookie=SecretStr("unb=seller; _m_h5_tk=token_suffix"),
    )
    adapter = RegistrationAdapter()
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    return database, adapter, ProductIntelligenceService(
        database, adapter, settings, EventHub(), ledger=ledger
    )


def test_share_copy_parses_direct_id_and_full_chinese_copy() -> None:
    assert direct_product_id("1061364390379") == "1061364390379"
    assert direct_product_id("复制这段内容打开闲鱼 https://www.goofish.com/item?id=1061364390379 一起来看看") == "1061364390379"
    with pytest.raises(ProductReferenceResolutionError, match="多个商品"):
        direct_product_id("https://www.goofish.com/item?id=11111 https://www.goofish.com/item?id=22222")
    with pytest.raises(ProductReferenceResolutionError, match="官方"):
        direct_product_id("https://evil.example/item?id=1061364390379")


@pytest.mark.asyncio
async def test_official_short_link_redirect_is_resolved_without_cookie_forwarding() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://www.goofish.com/item?id=1061364390379"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    try:
        result = await resolve_product_reference(
            "手机版分享： https://m.tb.cn/h.test",
            client=client,
        )
    finally:
        await client.aclose()

    assert result == "1061364390379"
    assert len(requests) == 1
    assert requests[0].headers.get("cookie", "") == ""


@pytest.mark.asyncio
async def test_owned_discovery_and_batch_commit_are_idempotent_and_snapshot_free(tmp_path) -> None:
    database, adapter, service = build_registration_service(tmp_path)
    preview = await service.discover_owned_listings()
    assert preview["source"] == "account_listing"
    assert [item["external_id"] for item in preview["items"]] == ["owned-1", "owned-2"]

    result = await service.commit_registration(
        request_id="registration-batch-001",
        preview_token=preview["token"],
        external_ids=["owned-1", "owned-2"],
    )
    repeated = await service.commit_registration(
        request_id="registration-batch-001",
        preview_token=preview["token"],
        external_ids=["owned-1", "owned-2"],
    )

    assert result["registered_count"] == 2
    assert result["already_registered_count"] == 0
    assert result["idempotent"] is False
    assert repeated["idempotent"] is True
    assert all(product.ownership_status == "owned" for product in result["products"])
    assert all(product.monitoring_enabled for product in result["products"])
    assert adapter.item_calls == []
    assert adapter.list_calls == 2

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ProductDailySnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(Item)) == 2
        assert session.scalar(select(func.count()).select_from(ProductMonitor)) == 2
        assert session.scalar(select(func.count()).select_from(ProductRegistrationRequest)) == 1


@pytest.mark.asyncio
async def test_shared_reference_preview_verifies_ownership_before_commit(tmp_path, monkeypatch) -> None:
    database, adapter, service = build_registration_service(tmp_path)

    async def fake_resolve(_reference: str) -> str:
        return "other-1"

    monkeypatch.setattr(
        "backend.app.services.product_intelligence.resolve_product_reference",
        fake_resolve,
    )
    preview = await service.resolve_registration_reference("官方分享内容")
    assert preview["items"][0]["ownership_status"] == "excluded"
    assert preview["items"][0]["can_register"] is False
    with pytest.raises(ProductReferenceInvalid, match="未验证为当前账号本人商品"):
        await service.commit_registration(
            request_id="registration-share-001",
            preview_token=preview["token"],
            external_ids=["other-1"],
        )
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ProductDailySnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(ProductMonitor)) == 0


@pytest.mark.asyncio
async def test_paused_owned_listing_can_be_revalidated_and_reenabled(tmp_path) -> None:
    database, _adapter, service = build_registration_service(tmp_path)
    first_preview = await service.discover_owned_listings()
    await service.commit_registration(
        request_id="registration-reenable-001",
        preview_token=first_preview["token"],
        external_ids=["owned-1"],
    )
    active_preview = await service.discover_owned_listings()
    active_candidate = next(
        item for item in active_preview["items"] if item["external_id"] == "owned-1"
    )
    assert active_candidate["monitoring_enabled"] is True
    assert active_candidate["can_register"] is False
    assert active_candidate["blocked_reason"] == "已在采集"
    with pytest.raises(ProductReferenceInvalid, match="已在采集"):
        await service.commit_registration(
            request_id="registration-duplicate-active-001",
            preview_token=active_preview["token"],
            external_ids=["owned-1"],
        )
    service.update_monitor("owned-1", False)

    second_preview = await service.discover_owned_listings()
    candidate = next(
        item for item in second_preview["items"] if item["external_id"] == "owned-1"
    )
    assert candidate["already_registered"] is True
    assert candidate["monitoring_enabled"] is False
    assert candidate["can_register"] is True

    result = await service.commit_registration(
        request_id="registration-reenable-002",
        preview_token=second_preview["token"],
        external_ids=["owned-1"],
    )
    assert result["registered_count"] == 0
    assert result["already_registered_count"] == 1
    assert result["products"][0].monitoring_enabled is True


@pytest.mark.asyncio
async def test_commit_rejects_listing_that_was_delisted_after_preview(tmp_path) -> None:
    database, adapter, service = build_registration_service(tmp_path)
    preview = await service.discover_owned_listings()
    adapter.owned_statuses["owned-1"] = "已下架"

    with pytest.raises(ProductReferenceInvalid, match="当前不是在售状态"):
        await service.commit_registration(
            request_id="registration-delisted-001",
            preview_token=preview["token"],
            external_ids=["owned-1"],
        )
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ProductMonitor)) == 0


@pytest.mark.asyncio
async def test_commit_fails_closed_when_current_status_cannot_be_rechecked(
    tmp_path, monkeypatch
) -> None:
    database, adapter, service = build_registration_service(tmp_path)
    preview = await service.discover_owned_listings()

    async def fail_list(_limit: int = 100):
        raise RuntimeError("temporary network failure")

    monkeypatch.setattr(adapter, "list_owned_items", fail_list)
    with pytest.raises(ProductCollectionUnavailable, match="未加入任何商品"):
        await service.commit_registration(
            request_id="registration-recheck-failed-001",
            preview_token=preview["token"],
            external_ids=["owned-1"],
        )
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ProductMonitor)) == 0


@pytest.mark.asyncio
async def test_shared_reference_rejects_unknown_or_delisted_status(tmp_path, monkeypatch) -> None:
    _database, adapter, service = build_registration_service(tmp_path)

    async def fake_resolve(_reference: str) -> str:
        return "owned-shared"

    monkeypatch.setattr(
        "backend.app.services.product_intelligence.resolve_product_reference",
        fake_resolve,
    )
    adapter.shared_statuses["owned-shared"] = "1"
    preview = await service.resolve_registration_reference("官方分享内容")
    assert preview["items"][0]["status"] == "已下架"
    assert preview["items"][0]["can_register"] is False
    with pytest.raises(ProductReferenceInvalid, match="当前不是在售状态"):
        await service.commit_registration(
            request_id="registration-shared-down-001",
            preview_token=preview["token"],
            external_ids=["owned-shared"],
        )
