from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any, AsyncIterator

from .base import CodexDevelopmentRuntime, RuntimeCapabilities, RuntimeEvent, RuntimeRun
from .events import normalize_notification, normalize_server_request


class AppServerProtocolError(RuntimeError):
    pass


class AppServerDevelopmentRuntime(CodexDevelopmentRuntime):
    """One supervised ``codex app-server`` stdio child per backend runtime."""

    def __init__(self, command: str = "codex", *, request_timeout: float = 30) -> None:
        self.command = command
        self.request_timeout = request_timeout
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._approval_methods: dict[str, tuple[str, dict[str, Any]]] = {}
        self._recent_methods: list[str] = []
        self._stderr_tail: list[str] = []
        self._events: asyncio.Queue[RuntimeEvent | None] = asyncio.Queue(maxsize=500)
        self._request_counter = 0
        self._write_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()

    async def capabilities(self) -> RuntimeCapabilities:
        path = shutil.which(self.command)
        if not path:
            return RuntimeCapabilities("app_server", False, detail="Codex CLI 未安装")
        version = ""
        try:
            process = await asyncio.create_subprocess_exec(
                self.command,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=5)
            if process.returncode == 0:
                version = stdout.decode(errors="replace").strip()
        except (OSError, asyncio.TimeoutError):
            pass
        return RuntimeCapabilities(
            "app_server",
            True,
            version=version,
            detail="通过 codex app-server stdio 使用 Thread/Turn/Event/Approval",
        )

    async def _ensure_started(self) -> None:
        async with self._start_lock:
            if self._process and self._process.returncode is None:
                return
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                "app-server",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._reader_task = asyncio.create_task(self._reader_loop())
            self._stderr_task = asyncio.create_task(self._stderr_loop())
            await self._request(
                "initialize",
                {"clientInfo": {"name": "xunying", "title": "循营", "version": "0.1.0"}},
            )
            await self._send({"method": "initialized", "params": {}})

    async def _send(self, payload: dict[str, Any]) -> None:
        process = self._process
        if not process or not process.stdin or process.returncode is not None:
            raise AppServerProtocolError("Codex App Server 未运行")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        async with self._write_lock:
            process.stdin.write(encoded)
            await process.stdin.drain()

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_started() if method != "initialize" else None
        self._request_counter += 1
        request_id = f"xunying-{self._request_counter}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        await self._send({"id": request_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(future, timeout=self.request_timeout)
        finally:
            self._pending.pop(request_id, None)

    async def _reader_loop(self) -> None:
        assert self._process and self._process.stdout
        try:
            while line := await self._process.stdout.readline():
                try:
                    message = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                request_id = str(message.get("id") or "")
                if request_id and ("result" in message or "error" in message):
                    future = self._pending.get(request_id)
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(AppServerProtocolError(str(message["error"])))
                        else:
                            future.set_result(message.get("result") or {})
                    continue
                method = str(message.get("method") or "")
                if method:
                    self._recent_methods.append(method)
                    self._recent_methods = self._recent_methods[-80:]
                params = message.get("params") if isinstance(message.get("params"), dict) else {}
                if request_id:
                    event = normalize_server_request(request_id, method, params)
                    if event:
                        self._approval_methods[request_id] = (method, params)
                        await self._events.put(event)
                    else:
                        # Unsupported server callbacks must never hang the child.
                        await self._send({"id": request_id, "error": {"code": -32601, "message": "Unsupported by Xunying"}})
                    continue
                event = normalize_notification(method, params)
                if event:
                    await self._events.put(event)
        finally:
            error = AppServerProtocolError("Codex App Server 已退出")
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            await self._events.put(RuntimeEvent("run_failed", payload={"summary": str(error)}))

    async def _stderr_loop(self) -> None:
        assert self._process and self._process.stderr
        while line := await self._process.stderr.readline():
            value = line.decode(errors="replace").strip()
            if value:
                self._stderr_tail.append(value)
                self._stderr_tail = self._stderr_tail[-40:]

    def diagnostics(self) -> dict[str, Any]:
        return {
            "recent_methods": list(self._recent_methods),
            "stderr_tail": list(self._stderr_tail),
            "returncode": self._process.returncode if self._process else None,
        }

    async def create_run(self, *, cwd: str, model: str, sandbox_mode: str, approval_mode: str, developer_instructions: str) -> RuntimeRun:
        await self._ensure_started()
        result = await self._request(
            "thread/start",
            {
                "cwd": cwd,
                "model": model or None,
                "sandbox": sandbox_mode,
                "approvalPolicy": approval_mode,
                "approvalsReviewer": "user",
                "developerInstructions": developer_instructions,
                "ephemeral": False,
                "serviceName": "xunying",
            },
        )
        thread = result.get("thread") if isinstance(result.get("thread"), dict) else {}
        thread_id = str(thread.get("id") or "")
        if not thread_id:
            raise AppServerProtocolError("thread/start 未返回 thread.id")
        return RuntimeRun(thread_id)

    async def start_turn(self, *, thread_id: str, prompt: str, cwd: str, model: str, reasoning_effort: str) -> RuntimeRun:
        result = await self._request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "cwd": cwd,
                "model": model or None,
                "effort": reasoning_effort or None,
            },
        )
        turn = result.get("turn") if isinstance(result.get("turn"), dict) else {}
        turn_id = str(turn.get("id") or "")
        if not turn_id:
            raise AppServerProtocolError("turn/start 未返回 turn.id")
        return RuntimeRun(thread_id, turn_id)

    async def resume_run(self, *, thread_id: str, cwd: str, model: str, sandbox_mode: str, approval_mode: str) -> RuntimeRun:
        result = await self._request(
            "thread/resume",
            {
                "threadId": thread_id,
                "cwd": cwd,
                "model": model or None,
                "sandbox": sandbox_mode,
                "approvalPolicy": approval_mode,
                "approvalsReviewer": "user",
            },
        )
        thread = result.get("thread") if isinstance(result.get("thread"), dict) else {}
        return RuntimeRun(str(thread.get("id") or thread_id))

    async def cancel_run(self, *, thread_id: str, turn_id: str) -> None:
        if turn_id:
            await self._request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})

    async def approve_action(self, *, server_request_id: str) -> None:
        await self._answer_approval(server_request_id, "accept")

    async def reject_action(self, *, server_request_id: str, cancel_turn: bool = False) -> None:
        await self._answer_approval(server_request_id, "cancel" if cancel_turn else "decline")

    async def _answer_approval(self, request_id: str, decision: str) -> None:
        if request_id not in self._approval_methods:
            raise AppServerProtocolError("审批请求已失效或不属于当前 App Server")
        method, params = self._approval_methods.pop(request_id)
        if method in {"execCommandApproval", "applyPatchApproval"}:
            legacy = {
                "accept": "approved",
                "decline": {"denied": {"rejection": "Rejected by user in Xunying"}},
                "cancel": "abort",
            }[decision]
            result: dict[str, Any] = {"decision": legacy}
        elif method == "item/permissions/requestApproval":
            if decision == "accept":
                result = {
                    "permissions": params.get("permissions") or {},
                    "scope": "turn",
                    "strictAutoReview": True,
                }
            else:
                await self._send({
                    "id": request_id,
                    "error": {"code": -32001, "message": "Permission rejected by user in Xunying"},
                })
                return
        else:
            result = {"decision": decision}
        await self._send({"id": request_id, "result": result})

    async def _event_iterator(self) -> AsyncIterator[RuntimeEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    def stream_events(self) -> AsyncIterator[RuntimeEvent]:
        return self._event_iterator()

    async def close(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        if self._reader_task:
            self._reader_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()
        await self._events.put(None)
