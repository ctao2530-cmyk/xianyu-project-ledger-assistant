"""Manual, non-customer-data smoke test for the requirement-analysis Codex path."""

from __future__ import annotations

import asyncio
import json

from backend.app.ai import AIModelSelection, AIProviderError, CodexCliProvider
from backend.app.ai.requirements import REQUIREMENT_SYSTEM_TASK, RequirementAnalysisResult
from backend.app.config import get_settings


async def main() -> None:
    settings = get_settings()
    provider = CodexCliProvider(settings)
    try:
        health = await provider.healthcheck(validate_execution=False)
        if health.status != "connected":
            raise AIProviderError("codex_unavailable", health.detail or "Codex 不可用")
        options = await provider.available_models(refresh=True)
        model = settings.requirement_analysis_model
        effort = settings.requirement_analysis_reasoning_effort
        selected = next((option for option in options if option.model == model), None)
        if not selected or effort not in selected.supported_reasoning_efforts:
            raise AIProviderError(
                "requirement_model_unavailable",
                f"当前账号不可用 {model}/{effort}",
            )
        sample = {
            "analysis_mode": "initial",
            "conversation": {
                "customer_name": "脱敏测试客户",
                "product": {
                    "title": "网页制作",
                    "price": "未确认",
                    "description": "定制企业展示网站",
                },
                "messages": [
                    {
                        "speaker": "customer",
                        "content": "需要一个适配手机的三页企业官网，页面是首页、产品和联系我们。",
                        "time": "2026-08-04T10:00:00+08:00",
                    }
                ],
            },
            "current_document": None,
            "change_request": None,
            "current_time": "2026-08-04T10:05:00+08:00",
        }
        result = await provider.generate_structured(
            f"{REQUIREMENT_SYSTEM_TASK}\n\n以下是脱敏验证 JSON：\n{json.dumps(sample, ensure_ascii=False)}",
            result_type=RequirementAnalysisResult,
            task_key="requirement-smoke-test",
            model_selection=AIModelSelection(model=model, reasoning_effort=effort),
            timeout=settings.requirement_analysis_timeout_seconds,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "model": model,
                    "reasoning_effort": effort,
                    "readiness": result.readiness,
                    "stage_count": len(result.stages),
                    "title": result.document_title,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
