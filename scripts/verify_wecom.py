#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from backend.app.channels.wecom import WeComAPIClient, WeComError
from backend.app.config import Settings


async def verify() -> int:
    settings = Settings()
    missing: list[str] = []
    if settings.wechat_provider != "wecom":
        missing.append("WECHAT_PROVIDER=wecom")
    if not settings.wecom_corp_id:
        missing.append("WECOM_CORP_ID")
    if not settings.wecom_corp_secret.get_secret_value():
        missing.append("WECOM_CORP_SECRET")
    if not settings.wecom_callback_token.get_secret_value():
        missing.append("WECOM_CALLBACK_TOKEN")
    if len(settings.wecom_encoding_aes_key.get_secret_value()) != 43:
        missing.append("WECOM_ENCODING_AES_KEY（应为 43 位）")
    if missing:
        print("企业微信配置不完整：" + "、".join(missing))
        print("请先运行：python scripts/configure_wecom.py")
        return 1

    client = WeComAPIClient(settings)
    try:
        await client.healthcheck()
    except WeComError as exc:
        print(f"企业微信接口验证失败：{exc}")
        return 1
    except Exception as exc:
        print(f"企业微信网络验证失败：{type(exc).__name__}")
        return 1
    finally:
        await client.close()
    print("企业微信凭证和微信客服 API 权限均有效。")
    print("下一步：配置公网 HTTPS 回调 URL，并在后台完成 URL 验证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(verify()))
