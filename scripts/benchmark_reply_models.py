from __future__ import annotations

import argparse
import asyncio
import json
import time

from backend.app.ai import AIInput, AIModelSelection, CodexCliProvider
from backend.app.config import Settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用虚构咨询对本机 Codex 客服回复模型做一次真实延迟基准"
    )
    parser.add_argument(
        "--models",
        default="gpt-5.4-mini,gpt-5.5,gpt-5.6-sol",
        help="逗号分隔的本机可用 Codex 模型 slug",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="low",
        help="基准统一使用的推理强度，默认 low",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    settings = Settings()
    provider = CodexCliProvider(settings)
    health = await provider.healthcheck(validate_execution=False)
    if health.status != "connected":
        print(json.dumps({"status": health.status, "detail": health.detail}, ensure_ascii=False))
        return 1

    payload = AIInput(
        customer_message="想做一个展示公司服务的简单网页，需要准备什么？",
        product={
            "title": "网页制作咨询",
            "price": "未提供",
            "description": "根据客户需求确认功能、范围和交付内容",
        },
        recent_messages=[],
        seller_rules=["不能虚构报价和交付时间", "所有回复需人工确认"],
        current_time="2026-08-04T12:00:00+08:00",
    )
    rows: list[dict[str, object]] = []
    for model in [part.strip() for part in args.models.split(",") if part.strip()]:
        started = time.perf_counter()
        try:
            result = await provider.generate(
                payload,
                task_key=f"benchmark:{model}",
                model_selection=AIModelSelection(
                    model=model,
                    reasoning_effort=args.reasoning_effort or None,
                ),
            )
            rows.append(
                {
                    "model": model,
                    "reasoning_effort": args.reasoning_effort or None,
                    "seconds": round(time.perf_counter() - started, 2),
                    "ok": True,
                    "reply_chars": len(result.direct),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "model": model,
                    "reasoning_effort": args.reasoning_effort or None,
                    "seconds": round(time.perf_counter() - started, 2),
                    "ok": False,
                    "error": type(exc).__name__,
                }
            )
    await provider.close()
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0 if all(row["ok"] for row in rows) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
