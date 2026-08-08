from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..ai import AIModelOption, AIModelSelection, AIProvider
from ..config import Settings
from ..database import Database
from ..models import AIModelPreference, OperationLog


class AIModelSelectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AIModelSettingsSnapshot:
    provider: str
    selection: AIModelSelection
    models: list[AIModelOption]


class AIModelSettingsService:
    """Owns the non-secret global model choice used by future AI processes."""

    def __init__(self, database: Database, provider: AIProvider, settings: Settings) -> None:
        self.database = database
        self.provider = provider
        self.settings = settings
        self._lock = asyncio.Lock()
        self._load_selection()

    def _load_selection(self) -> None:
        default_model = (
            self.settings.codex_model.strip()
            if self.provider.name == "codex_cli"
            else self.settings.ai_model.strip()
        ) or None
        default_effort = (
            self.settings.codex_reasoning_effort.strip()
            if self.provider.name == "codex_cli"
            else ""
        ) or None
        with self.database.session() as session:
            row = session.get(AIModelPreference, self.provider.name)
            if row is None:
                row = AIModelPreference(
                    provider=self.provider.name,
                    model=default_model,
                    reasoning_effort=default_effort,
                )
                session.add(row)
                session.commit()
            selection = AIModelSelection(
                model=row.model or None,
                reasoning_effort=row.reasoning_effort or None,
            )
        self.provider.configure_model(selection)

    @property
    def selection(self) -> AIModelSelection:
        return self.provider.model_selection

    async def get(self, *, refresh: bool = False) -> AIModelSettingsSnapshot:
        models = await self.provider.available_models(refresh=refresh)
        return AIModelSettingsSnapshot(
            provider=self.provider.name,
            selection=self.selection,
            models=models,
        )

    async def update(
        self,
        model: str | None,
        reasoning_effort: str | None,
    ) -> AIModelSettingsSnapshot:
        normalized_model = (model or "").strip() or None
        normalized_effort = (reasoning_effort or "").strip() or None
        if normalized_model is None:
            normalized_effort = None

        async with self._lock:
            models = await self.provider.available_models(refresh=False)
            if normalized_model is not None:
                option = next((item for item in models if item.model == normalized_model), None)
                if option is None:
                    raise AIModelSelectionError("所选模型不在当前 Codex 账号的可用目录中")
                if (
                    normalized_effort is not None
                    and normalized_effort not in option.supported_reasoning_efforts
                ):
                    raise AIModelSelectionError("所选推理强度不受该模型支持")

            selection = AIModelSelection(
                model=normalized_model,
                reasoning_effort=normalized_effort,
            )
            with self.database.session() as session:
                row = session.get(AIModelPreference, self.provider.name)
                if row is None:
                    row = AIModelPreference(provider=self.provider.name)
                    session.add(row)
                row.model = selection.model
                row.reasoning_effort = selection.reasoning_effort
                session.add(
                    OperationLog(
                        action="ai_model_changed",
                        detail=(
                            f"全局模型切换为 {selection.model or 'Codex 默认'}，"
                            f"推理强度 {selection.reasoning_effort or '模型默认'}"
                        ),
                    )
                )
                session.commit()
            self.provider.configure_model(selection)
            return AIModelSettingsSnapshot(
                provider=self.provider.name,
                selection=selection,
                models=models,
            )


__all__ = [
    "AIModelSelectionError",
    "AIModelSettingsService",
    "AIModelSettingsSnapshot",
]
