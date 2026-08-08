from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from ..config import Settings
from .base import (
    AIInput,
    AIModelSelection,
    AIProvider,
    AIProviderError,
    AIResult,
    ProviderHealth,
)
from .codex_cli import SYSTEM_TASK


class OpenAICompatibleProvider(AIProvider):
    name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(settings.ai_timeout_seconds))
        if not settings.ai_api_key.get_secret_value() or not settings.ai_model:
            self.health = ProviderHealth(
                status="not_configured",
                detail="请配置 AI_API_KEY 和 AI_MODEL",
            )

    @property
    def endpoint(self) -> str:
        return self.settings.ai_base_url.rstrip("/") + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.ai_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    async def healthcheck(self, *, validate_execution: bool = True) -> ProviderHealth:
        if not self.settings.ai_api_key.get_secret_value() or not self.settings.ai_model:
            return self.health
        try:
            response = await self.client.get(
                self.settings.ai_base_url.rstrip("/") + "/models",
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            self.health = ProviderHealth(
                status="connected",
                detail="OpenAI Compatible API 已连接",
                checked_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            self.health = ProviderHealth(
                status="error",
                detail=f"模型连接失败：{type(exc).__name__}",
                checked_at=datetime.now(timezone.utc),
            )
        return self.health

    async def generate(
        self,
        payload: AIInput,
        *,
        task_key: str,
        model_selection: AIModelSelection | None = None,
    ) -> AIResult:
        if not self.settings.ai_api_key.get_secret_value() or not self.settings.ai_model:
            raise AIProviderError("openai_not_configured", "OpenAI Compatible API 未配置")
        request_body = {
            "model": (
                model_selection.model
                if model_selection and model_selection.model
                else self.settings.ai_model
            ),
            "temperature": self.settings.ai_temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_TASK},
                {"role": "user", "content": payload.model_dump_json(indent=2)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "xianyu_reply_drafts",
                    "strict": True,
                    "schema": AIResult.model_json_schema(),
                },
            },
        }
        try:
            response = await self.client.post(
                self.endpoint,
                headers=self._headers(),
                json=request_body,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            result = AIResult.model_validate(json.loads(content)).with_enforced_risks(payload)
        except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise AIProviderError(
                "openai_generation_failed",
                f"OpenAI Compatible 草稿生成失败：{type(exc).__name__}",
                retryable=True,
            ) from exc
        self.health = ProviderHealth(
            status="connected",
            detail="OpenAI Compatible API 调用正常",
            checked_at=datetime.now(timezone.utc),
        )
        return result

    async def close(self) -> None:
        await self.client.aclose()
