from __future__ import annotations

import asyncio

from backend.app.ai import AIInput, CodexCliProvider
from backend.app.config import Settings


async def main() -> None:
    settings = Settings()
    provider = CodexCliProvider(settings)
    health = await provider.healthcheck(validate_execution=False)
    print(
        {
            "status": health.status,
            "installed": health.installed,
            "logged_in": health.logged_in,
            "detail": health.detail,
            "repair_command": health.repair_command,
        }
    )
    if health.status != "connected":
        raise SystemExit(1)
    result = await provider.generate(
        AIInput(
            customer_message="你好，我想做一个企业官网，需要准备哪些资料？",
            product={
                "title": "企业官网制作",
                "price": "未提供",
                "description": "根据客户需求进行网页设计与开发",
            },
            recent_messages=[],
            seller_rules=["任何回复都必须人工确认后发送"],
            current_time="2026-08-03T12:00:00+08:00",
        ),
        task_key="manual-validation",
    )
    print(result.model_dump_json(indent=2))
    await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
