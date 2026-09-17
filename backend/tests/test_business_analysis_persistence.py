from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from backend.app.ai.base import AIModelOption, AIModelSelection, AIProviderError
from backend.app.business_analysis_api import business_analysis_router
from backend.app.business_analysis_repository import (
    BusinessAnalysisRepositoryError,
    RecommendationTransitionError,
    RecommendationVersionConflict,
)
from backend.app.database import Database
from backend.app.ledger import LedgerService, default_snapshot
from backend.app.models import (
    BusinessAnalysisRecord,
    BusinessAnalysisRecommendationEvent,
    BusinessAnalysisRecommendationRecord,
)
from backend.app.services.business_analysis import (
    BusinessAnalysisProviderSelectionError,
    BusinessAnalysisService,
)
from backend.app.services.business_analysis_reasoning import (
    BusinessAnalysisReasoningService,
)
from backend.app.services.business_recommendations import BusinessRecommendationService


FIXED_NOW = datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class StructuredProvider:
    def __init__(self, *, name: str = "deepseek", mode: str = "success") -> None:
        self.name = name
        self.mode = mode
        self.model_selection = AIModelSelection(
            model="deepseek-test" if name == "deepseek" else "gpt-test-deep",
        )
        self.prompts: list[str] = []
        self.selections: list[AIModelSelection | None] = []

    async def generate_structured(
        self,
        prompt: str,
        *,
        result_type,
        task_key: str,
        model_selection: AIModelSelection | None = None,
        timeout: float | None = None,
    ):
        self.prompts.append(prompt)
        self.selections.append(model_selection)
        if self.mode == "failure":
            raise AIProviderError(
                "deepseek_timeout",
                "DeepSeek 响应超时，请重试或明确改用 Codex",
                retryable=True,
            )
        evidence = (
            ["products.unknown"]
            if self.mode == "invalid_evidence"
            else ["products.ownership_status"]
        )
        return result_type.model_validate(
            {
                "summary": "当前经营基线仍不完整，应先补齐本人商品、客户、项目和收支证据。",
                "insights": [
                    {
                        "id": "product-baseline-missing",
                        "title": "商品证据尚未形成",
                        "reason": "当前没有已验证本人商品，因此不能判断曝光或咨询变化。",
                        "evidence_refs": evidence,
                    }
                ],
                "recommendations": [
                    {
                        "id": "verify-owned-products",
                        "title": "先确认本人商品",
                        "problem": "商品经营基线缺失",
                        "reason": "只有完成归属验证的商品才能进入经营分析。",
                        "action": "人工确认本人商品并执行一次只读数据采集。",
                        "evidence_refs": evidence,
                    }
                ],
            }
        )


class ModelSettingsStub:
    def __init__(self) -> None:
        self.selection = AIModelSelection(
            model="gpt-test-deep",
            reasoning_effort="high",
        )
        self.models = [
            AIModelOption(
                model="gpt-test-deep",
                display_name="GPT Test Deep",
                default_reasoning_effort="high",
                supported_reasoning_efforts=("low", "high"),
            ),
            AIModelOption(
                model="gpt-test-fast",
                display_name="GPT Test Fast",
                default_reasoning_effort="low",
                supported_reasoning_efforts=("low",),
            ),
        ]

    async def get(self, *, refresh: bool = False):
        return SimpleNamespace(selection=self.selection, models=self.models)


def build_selectable_service(
    tmp_path: Path,
    *,
    codex_mode: str = "success",
) -> tuple[BusinessAnalysisService, StructuredProvider, StructuredProvider]:
    database = Database(f"sqlite:///{tmp_path / 'business-analysis-providers.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    codex = StructuredProvider(name="codex_cli", mode=codex_mode)
    deepseek = StructuredProvider(name="deepseek")
    service = BusinessAnalysisService(
        database,
        ledger,
        reasoning_providers={"codex_cli": codex, "deepseek": deepseek},  # type: ignore[arg-type]
        model_settings=ModelSettingsStub(),  # type: ignore[arg-type]
        provider_selections={
            "deepseek": AIModelSelection(model="deepseek-test"),
        },
        provider_enabled={"codex_cli": True, "deepseek": True},
        reasoning_timeout_seconds=5,
    )
    return service, codex, deepseek


def build_service(
    tmp_path: Path,
    *,
    provider: StructuredProvider | None = None,
) -> tuple[Database, LedgerService, BusinessAnalysisService, StructuredProvider]:
    database = Database(f"sqlite:///{tmp_path / 'business-analysis-persistence.db'}")
    database.create_all()
    ledger = LedgerService(database, tmp_path)
    ledger.get()
    selected = provider or StructuredProvider()
    reasoning = BusinessAnalysisReasoningService(
        selected,  # type: ignore[arg-type]
        model_selection=AIModelSelection(model="deepseek-test"),
        timeout_seconds=5,
    )
    service = BusinessAnalysisService(
        database,
        ledger,
        reasoning=reasoning,
    )
    return database, ledger, service, selected


@pytest.mark.asyncio
async def test_run_persists_explainable_ai_analysis_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database, ledger, service, _ = build_service(tmp_path)

    created = await service.run_analysis(
        request_id="analysis-request-0001",
        provider="deepseek",
        now=FIXED_NOW,
    )
    repeated = await service.run_analysis(
        request_id="analysis-request-0001",
        provider="deepseek",
        now=FIXED_NOW,
    )

    assert created.analysis_id is not None
    assert repeated.analysis_id == created.analysis_id
    assert created.record_status == "completed"
    assert created.analysis_method == "rules_plus_deepseek_v1"
    assert created.ai_status == "succeeded"
    assert created.provider == "deepseek"
    assert created.model == "deepseek-test"
    assert created.fallback_used is False
    assert created.recommendations[0].id.startswith("recommendation-")
    assert created.recommendations[0].source_key == "verify-owned-products"
    assert created.recommendations[0].problem == "商品经营基线缺失"
    assert created.recommendations[0].data_source == ["商品经营快照"]
    assert created.recommendations[0].execution_mode == "manual"
    assert created.recommendations[0].status == "pending"
    with database.session() as session:
        assert session.scalar(select(func.count(BusinessAnalysisRecord.id))) == 1
        assert (
            session.scalar(
                select(func.count(BusinessAnalysisRecommendationRecord.id))
            )
            == len(created.recommendations)
        )

    latest = service.latest_or_overview(now=FIXED_NOW)
    history = service.history(limit=20, offset=0)
    detail = service.history_detail(created.analysis_id)
    assert latest.analysis_id == created.analysis_id
    assert latest.is_stale is False
    assert history.total == 1
    assert history.items[0].insight_count == len(created.insights)
    assert history.items[0].recommendation_count == len(created.recommendations)
    assert detail.analysis_id == created.analysis_id

    revision, changed_snapshot = ledger.get()
    changed_snapshot["expenses"].append(
        {
            "id": "expense-after-analysis",
            "name": "分析后的测试支出",
            "category": "software",
            "amount": 10,
            "paidAt": "2026-08-11T12:00:00+08:00",
        }
    )
    ledger.save(changed_snapshot, revision)
    assert service.latest_or_overview(now=FIXED_NOW).is_stale is True


@pytest.mark.asyncio
async def test_ai_failure_is_saved_as_explicit_rule_fallback(tmp_path: Path) -> None:
    _, _, service, _ = build_service(
        tmp_path,
        provider=StructuredProvider(mode="failure"),
    )

    result = await service.run_analysis(
        request_id="analysis-request-failure",
        provider="deepseek",
        now=FIXED_NOW,
    )

    assert result.analysis_method == "evidence_rules_v1"
    assert result.ai_status == "failed"
    assert result.fallback_used is True
    assert result.ai_error is not None
    assert result.ai_error.code == "deepseek_timeout"
    assert result.ai_error.retryable is True
    assert result.provider == "deepseek"
    assert all(row.execution_mode == "manual" for row in result.recommendations)


@pytest.mark.asyncio
async def test_unknown_ai_evidence_is_rejected_and_not_shown_as_success(
    tmp_path: Path,
) -> None:
    _, _, service, _ = build_service(
        tmp_path,
        provider=StructuredProvider(mode="invalid_evidence"),
    )

    result = await service.run_analysis(
        request_id="analysis-request-invalid-evidence",
        provider="deepseek",
        now=FIXED_NOW,
    )

    assert result.ai_status == "failed"
    assert result.fallback_used is True
    assert result.ai_error is not None
    assert result.ai_error.code == "business_analysis_ai_evidence_rejected"
    assert "products.unknown" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_ai_prompt_contains_aggregates_but_not_customer_identity(tmp_path: Path) -> None:
    _, ledger, service, provider = build_service(tmp_path)
    snapshot = default_snapshot()
    snapshot["customers"] = [
        {
            "id": "customer-secret",
            "name": "SECRET-CUSTOMER-NAME",
            "source": "xianyu",
            "phone": "SECRET-PHONE",
            "followUpStatus": "new",
            "lastContactAt": "2026-08-10T10:00:00+08:00",
            "level": "A",
        }
    ]
    ledger.save(snapshot, 0)

    await service.run_analysis(
        request_id="analysis-request-redaction",
        provider="deepseek",
        now=FIXED_NOW,
    )

    prompt = provider.prompts[0]
    assert "SECRET-CUSTOMER-NAME" not in prompt
    assert "SECRET-PHONE" not in prompt
    assert '"total":1' in prompt


@pytest.mark.asyncio
async def test_gpt_is_default_selectable_provider_and_actual_model_is_persisted(
    tmp_path: Path,
) -> None:
    service, codex, deepseek = build_selectable_service(tmp_path)

    result = await service.run_analysis(
        request_id="analysis-provider-gpt-default",
        provider="codex_cli",
        now=FIXED_NOW,
    )

    assert result.provider == "codex_cli"
    assert result.model == "gpt-test-deep"
    assert result.analysis_method == "rules_plus_codex_v1"
    assert result.ai_status == "succeeded"
    assert codex.selections[-1] == AIModelSelection(
        model="gpt-test-deep",
        reasoning_effort="high",
    )
    assert deepseek.prompts == []
    history = service.history(limit=20, offset=0)
    assert history.items[0].provider == "codex_cli"
    assert history.items[0].model == "gpt-test-deep"


@pytest.mark.asyncio
async def test_explicit_gpt_model_and_deepseek_switch_are_validated(
    tmp_path: Path,
) -> None:
    service, codex, deepseek = build_selectable_service(tmp_path)

    gpt = await service.run_analysis(
        request_id="analysis-provider-gpt-fast",
        provider="codex_cli",
        model="gpt-test-fast",
        reasoning_effort="low",
        now=FIXED_NOW,
    )
    switched = await service.run_analysis(
        request_id="analysis-provider-deepseek",
        provider="deepseek",
        model="deepseek-test",
        now=FIXED_NOW,
    )

    assert gpt.model == "gpt-test-fast"
    assert codex.selections[-1] == AIModelSelection(
        model="gpt-test-fast",
        reasoning_effort="low",
    )
    assert switched.provider == "deepseek"
    assert switched.model == "deepseek-test"
    assert switched.analysis_method == "rules_plus_deepseek_v1"
    assert len(deepseek.prompts) == 1

    with pytest.raises(BusinessAnalysisProviderSelectionError) as invalid_model:
        await service.run_analysis(
            request_id="analysis-provider-invalid-model",
            provider="codex_cli",
            model="gpt-not-in-catalog",
            now=FIXED_NOW,
        )
    assert invalid_model.value.code == "business_analysis_model_invalid"

    with pytest.raises(BusinessAnalysisProviderSelectionError) as invalid_effort:
        await service.run_analysis(
            request_id="analysis-provider-invalid-effort",
            provider="codex_cli",
            model="gpt-test-fast",
            reasoning_effort="high",
            now=FIXED_NOW,
        )
    assert invalid_effort.value.code == "business_analysis_reasoning_effort_invalid"


@pytest.mark.asyncio
async def test_selected_provider_failure_does_not_call_other_provider(
    tmp_path: Path,
) -> None:
    service, codex, deepseek = build_selectable_service(
        tmp_path,
        codex_mode="failure",
    )

    result = await service.run_analysis(
        request_id="analysis-provider-no-silent-switch",
        provider="codex_cli",
        now=FIXED_NOW,
    )

    assert result.provider == "codex_cli"
    assert result.model == "gpt-test-deep"
    assert result.ai_status == "failed"
    assert result.analysis_method == "evidence_rules_v1"
    assert len(codex.prompts) == 1
    assert deepseek.prompts == []


@pytest.mark.asyncio
async def test_analysis_record_and_recommendations_roll_back_together(
    tmp_path: Path,
) -> None:
    database, _, service, _ = build_service(tmp_path)
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_business_analysis_recommendation "
            "BEFORE INSERT ON business_analysis_recommendations "
            "BEGIN SELECT RAISE(ABORT, 'forced test failure'); END"
        )

    with pytest.raises(BusinessAnalysisRepositoryError):
        await service.run_analysis(
            request_id="analysis-request-rollback",
            provider="deepseek",
            now=FIXED_NOW,
        )

    with database.session() as session:
        assert session.scalar(select(func.count(BusinessAnalysisRecord.id))) == 0
        assert (
            session.scalar(
                select(func.count(BusinessAnalysisRecommendationRecord.id))
            )
            == 0
        )


@pytest.mark.asyncio
async def test_recommendation_feedback_uses_version_and_request_protection(
    tmp_path: Path,
) -> None:
    database, _, service, _ = build_service(tmp_path)
    feedback = BusinessRecommendationService(database, service)
    result = await service.run_analysis(
        request_id="analysis-request-feedback",
        provider="deepseek",
        now=FIXED_NOW,
    )
    recommendation_id = result.recommendations[0].id

    accepted = feedback.update(
        recommendation_id,
        status="accepted",
        expected_version=1,
        request_id="feedback-request-0001",
        note="先人工验证",
        now=FIXED_NOW,
    )
    repeated = feedback.update(
        recommendation_id,
        status="accepted",
        expected_version=1,
        request_id="feedback-request-0001",
        note="先人工验证",
        now=FIXED_NOW,
    )
    assert accepted.version == 2
    assert repeated.version == 2
    assert accepted.status == "accepted"
    assert accepted.user_note == "先人工验证"

    with pytest.raises(RecommendationVersionConflict):
        feedback.update(
            recommendation_id,
            status="ignored",
            expected_version=1,
            request_id="feedback-request-0002",
            note="",
            now=FIXED_NOW,
        )

    started = feedback.start(
        recommendation_id,
        expected_version=2,
        request_id="feedback-request-0003",
        now=FIXED_NOW,
    )
    assert started.status == "observing"
    completed = feedback.complete(
        recommendation_id,
        expected_version=3,
        request_id="feedback-request-0004",
        outcome="positive",
        actual_cost=0,
        actual_hours=1.5,
        user_conclusion="已人工完成并观察到改善",
        now=datetime(2026, 8, 19, 4, 0, tzinfo=timezone.utc),
    )
    assert completed.status == "completed"
    assert completed.version == 4
    assert completed.outcome == "positive"
    assert completed.baseline_metrics is not None
    assert completed.result_metrics is not None
    with pytest.raises(RecommendationTransitionError):
        feedback.update(
            recommendation_id,
            status="ignored",
            expected_version=4,
            request_id="feedback-request-0005",
            note="",
            now=FIXED_NOW,
        )
    with database.session() as session:
        assert session.scalar(select(func.count(BusinessAnalysisRecommendationEvent.id))) == 3


def test_business_analysis_api_supports_runs_history_and_feedback(tmp_path: Path) -> None:
    database, _, service, _ = build_service(tmp_path)
    feedback = BusinessRecommendationService(database, service)
    app = FastAPI()
    app.include_router(business_analysis_router)
    app.state.runtime = SimpleNamespace(
        business_analysis=service,
        business_recommendations=feedback,
    )
    client = TestClient(app)

    initial = client.get("/api/business-analysis")
    assert initial.status_code == 200
    assert initial.json()["record_status"] == "live"

    created = client.post(
        "/api/business-analysis/runs",
        json={"request_id": "api-analysis-request-0001", "provider": "deepseek"},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["record_status"] == "completed"

    history = client.get("/api/business-analysis/history")
    detail = client.get(
        f"/api/business-analysis/history/{payload['analysis_id']}"
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert detail.status_code == 200

    recommendation = payload["recommendations"][0]
    updated = client.patch(
        f"/api/business-analysis/recommendations/{recommendation['id']}",
        json={
            "status": "accepted",
            "expected_version": 1,
            "request_id": "api-feedback-request-0001",
            "note": "人工采纳",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "accepted"
    conflict = client.patch(
        f"/api/business-analysis/recommendations/{recommendation['id']}",
        json={
            "status": "ignored",
            "expected_version": 1,
            "request_id": "api-feedback-request-0002",
            "note": "",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["current_version"] == 2


def test_business_analysis_api_sanitizes_repository_failure(tmp_path: Path) -> None:
    database, _, service, _ = build_service(tmp_path)

    def fail_latest():
        raise BusinessAnalysisRepositoryError("raw sqlite detail")

    service.repository.latest = fail_latest  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(business_analysis_router)
    app.state.runtime = SimpleNamespace(
        business_analysis=service,
        business_recommendations=BusinessRecommendationService(database, service),
    )

    response = TestClient(app).get("/api/business-analysis")

    assert response.status_code == 503
    assert response.json() == {"detail": "经营分析记录暂时无法访问"}
    assert "raw sqlite detail" not in response.text


def test_business_analysis_alembic_migration_upgrades_existing_0013_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "business-analysis-migration.db"
    database = Database(f"sqlite:///{database_path}")
    database.create_all()
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE business_analysis_recommendations")
        connection.execute("DROP TABLE business_analysis_records")
        connection.execute("DROP TABLE ledger_mutation_requests")
        connection.execute(
            "CREATE TABLE alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO alembic_version(version_num) VALUES ('20260810_0013')"
        )

    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    with sqlite3.connect(database_path) as connection:
        version = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name LIKE 'business_analysis_%'"
            )
        }
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        assert version == ("20260908_0046",)
    assert tables == {
        "business_analysis_records",
        "business_analysis_recommendation_events",
        "business_analysis_recommendations",
    }
    assert violations == []
