from __future__ import annotations

from ..config import Settings
from .base import AIProvider
from .codex_cli import CodexCliProvider
from .openai_compatible import OpenAICompatibleProvider


def build_ai_provider(settings: Settings) -> AIProvider:
    provider = settings.ai_provider.strip().lower()
    if provider == "codex_cli":
        return CodexCliProvider(settings)
    if provider == "openai_compatible":
        return OpenAICompatibleProvider(settings)
    raise ValueError(f"不支持的 AI_PROVIDER：{settings.ai_provider}")
