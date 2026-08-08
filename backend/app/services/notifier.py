from __future__ import annotations

import asyncio
import logging
import platform


logger = logging.getLogger(__name__)


class MacOSNotifier:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and platform.system() == "Darwin"

    async def notify(self, title: str, message: str, subtitle: str = "") -> None:
        if not self.enabled:
            return
        script = (
            "on run argv\n"
            "display notification (item 2 of argv) with title (item 1 of argv) "
            "subtitle (item 3 of argv)\n"
            "end run"
        )
        try:
            process = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                title[:100],
                message[:240],
                subtitle[:100],
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await process.communicate()
            if process.returncode:
                logger.warning("macOS 通知发送失败：%s", stderr.decode(errors="replace").strip())
        except OSError as exc:
            logger.warning("macOS 通知不可用：%s", exc)
