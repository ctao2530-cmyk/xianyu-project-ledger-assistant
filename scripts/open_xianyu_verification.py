#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.adapters.base import AdapterAccessVerificationError  # noqa: E402
from backend.app.adapters.xianyu import XianyuAdapter  # noqa: E402
from backend.app.config import Settings  # noqa: E402


EDGE_APPLESCRIPT = r'''
on run argv
    set urlFile to POSIX file (item 1 of argv)
    set verificationUrl to read urlFile as «class utf8»
    tell application "Microsoft Edge"
        if not running then error "edge-not-running"
        repeat with browserWindow in windows
            set tabCount to count of tabs of browserWindow
            repeat with tabIndex from 1 to tabCount
                set browserTab to tab tabIndex of browserWindow
                set currentUrl to URL of browserTab
                if currentUrl contains "goofish.com" or currentUrl contains "taobao.com" then
                    set active tab index of browserWindow to tabIndex
                    set URL of browserTab to verificationUrl
                    set index of browserWindow to 1
                    activate
                    return "opened"
                end if
            end repeat
        end repeat
    end tell
    error "existing-xianyu-tab-not-found"
end run
'''


async def request_verification_url(item_id: str) -> tuple[str, str | None]:
    adapter = XianyuAdapter(Settings())
    try:
        item = await adapter.fetch_item(item_id)
        return ("success" if item is not None else "item_unavailable"), None
    except AdapterAccessVerificationError as exc:
        return "access_verification", exc.verification_url
    finally:
        await adapter.close()


def open_in_existing_edge(verification_url: str) -> None:
    """Navigate an existing Xianyu tab without exposing the one-time URL.

    The URL is passed through a mode-0600 temporary file instead of argv,
    stdout, logs or clipboard. AppleScript receives only the temporary path.
    """
    fd, temporary_name = tempfile.mkstemp(prefix=".xianyu-verification-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(verification_url)
        os.chmod(temporary_name, 0o600)
        completed = subprocess.run(
            ["osascript", "-", temporary_name],
            input=EDGE_APPLESCRIPT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode != 0:
            raise RuntimeError("无法接管现有 Edge 闲鱼标签页")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("无法接管现有 Edge 闲鱼标签页") from exc
    finally:
        Path(temporary_name).unlink(missing_ok=True)


async def run(item_id: str) -> int:
    status, verification_url = await request_verification_url(item_id)
    if status == "success":
        print("该商品当前可以正常读取，无需访问验证。")
        return 0
    if status != "access_verification":
        print("该商品未返回可用详情，也没有提供访问验证入口。")
        return 2
    if not verification_url:
        print("闲鱼要求访问验证，但本次响应未提供可安全打开的官方验证地址。")
        return 3
    try:
        open_in_existing_edge(verification_url)
    except RuntimeError as exc:
        print(str(exc))
        return 4
    print("已在现有 Edge 闲鱼标签页打开官方验证页面；验证地址未显示或保存。")
    print("请本人完成页面中的验证，完成后再同步登录态并执行一次单件复测。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在现有 Edge 闲鱼标签页打开一次性官方访问验证页面"
    )
    parser.add_argument("--item-id", required=True, help="用于触发验证的本人商品 ID")
    args = parser.parse_args()
    if not args.item_id.isdigit():
        parser.error("--item-id 必须是数字")
    return asyncio.run(run(args.item_id))


if __name__ == "__main__":
    raise SystemExit(main())
