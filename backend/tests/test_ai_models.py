from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.app.ai import (
    AIInput,
    AIModelOption,
    AIProvider,
    AIResult,
    ProviderHealth,
)
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.models import AIModelPreference, OperationLog
from backend.app.services.ai_models import AIModelSelectionError, AIModelSettingsService


class CatalogProvider(AIProvider):
    name = "codex_cli"

    async def healthcheck(self, *, validate_execution: bool = True) -> ProviderHealth:
        return ProviderHealth(status="connected")

    async def available_models(self, *, refresh: bool = False) -> list[AIModelOption]:
        return [
            AIModelOption(
                model="gpt-5.6-terra",
                display_name="GPT-5.6-Terra",
                default_reasoning_effort="medium",
                supported_reasoning_efforts=("low", "medium", "high"),
            ),
            AIModelOption(
                model="gpt-5.5",
                display_name="GPT-5.5",
                default_reasoning_effort="medium",
                supported_reasoning_efforts=("low", "medium", "high", "xhigh"),
            ),
        ]

    async def generate(
        self, payload: AIInput, *, task_key: str, model_selection=None
    ) -> AIResult:
        raise AssertionError("not used")


@pytest.mark.asyncio
async def test_model_selection_persists_and_validates_effort(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'models.db'}")
    database.create_all()
    provider = CatalogProvider()
    service = AIModelSettingsService(database, provider, Settings(_env_file=None))

    snapshot = await service.update("gpt-5.5", "high")
    assert snapshot.selection.model == "gpt-5.5"
    assert snapshot.selection.reasoning_effort == "high"
    assert provider.model_selection == snapshot.selection

    restarted_provider = CatalogProvider()
    restarted = AIModelSettingsService(
        database,
        restarted_provider,
        Settings(_env_file=None),
    )
    assert restarted.selection.model == "gpt-5.5"
    assert restarted.selection.reasoning_effort == "high"

    with database.session() as session:
        row = session.get(AIModelPreference, "codex_cli")
        logs = list(
            session.scalars(
                select(OperationLog).where(OperationLog.action == "ai_model_changed")
            )
        )
    assert row is not None and row.model == "gpt-5.5"
    assert len(logs) == 1

    with pytest.raises(AIModelSelectionError, match="不受该模型支持"):
        await restarted.update("gpt-5.6-terra", "ultra")
    assert restarted.selection.model == "gpt-5.5"


@pytest.mark.asyncio
async def test_codex_default_clears_reasoning_effort(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'default-model.db'}")
    database.create_all()
    service = AIModelSettingsService(
        database,
        CatalogProvider(),
        Settings(_env_file=None, codex_model="gpt-5.5", codex_reasoning_effort="high"),
    )

    snapshot = await service.update(None, "xhigh")
    assert snapshot.selection.model is None
    assert snapshot.selection.reasoning_effort is None
