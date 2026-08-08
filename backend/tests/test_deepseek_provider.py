from __future__ import annotations

import json

import httpx
import pytest

from backend.app.ai import AIInput, AIProviderError
from backend.app.ai.deepseek import DeepSeekProvider
from backend.app.config import Settings


def payload() -> AIInput:
    return AIInput(
        customer_message="我想做一个订单管理系统，请问还需要补充什么？",
        product={"title": "软件定制", "price": "待沟通", "description": "定制开发"},
        recent_messages=[],
        seller_rules=["不能自行承诺价格"],
        current_time="2026-08-07T12:00:00+08:00",
    )


def result_json() -> str:
    return json.dumps(
        {
            "direct": "可以的，请补充使用角色、核心流程、期望交付时间和参考产品，我先帮您梳理范围。",
            "friendly": "没问题，我可以先帮您拆一下需求。方便说下谁来使用、主要流程和期望什么时候交付吗？",
            "conversion": "可以承接，建议先确认角色、核心流程、数据量和交付时间，我整理清单后再给您明确方案。",
            "risk_level": "low",
            "risk_reasons": [],
            "needs_human_confirmation": True,
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_deepseek_generates_validated_drafts() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert body["model"] == "deepseek-test"
        return httpx.Response(200, json={"choices": [{"message": {"content": result_json()}}]})

    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-secret",
        deepseek_reply_model="deepseek-test",
    )
    provider = DeepSeekProvider(settings)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await provider.generate(payload(), task_key="reply-1")
    assert len(result.drafts()) == 3
    assert result.needs_human_confirmation is True
    await provider.close()


@pytest.mark.asyncio
async def test_deepseek_retries_invalid_json_exactly_once() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    settings = Settings(_env_file=None, deepseek_api_key="test-secret")
    provider = DeepSeekProvider(settings)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(AIProviderError) as exc_info:
        await provider.generate(payload(), task_key="reply-2")
    assert exc_info.value.code == "deepseek_invalid_json"
    assert calls == 2
    await provider.close()


@pytest.mark.asyncio
async def test_deepseek_unconfigured_is_explicit() -> None:
    provider = DeepSeekProvider(Settings(_env_file=None, deepseek_api_key=""))
    with pytest.raises(AIProviderError) as exc_info:
        await provider.generate(payload(), task_key="reply-3")
    assert exc_info.value.code == "deepseek_not_configured"
    await provider.close()
