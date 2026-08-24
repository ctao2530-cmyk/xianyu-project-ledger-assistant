from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    runtime_type: str
    available: bool
    version: str = ""
    supports_resume: bool = True
    supports_cancel: bool = True
    supports_approvals: bool = True
    supports_event_stream: bool = True
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeRun:
    thread_id: str
    turn_id: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    event_type: str
    thread_id: str = ""
    turn_id: str = ""
    item_id: str = ""
    server_request_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class CodexDevelopmentRuntime(ABC):
    """Transport-independent interface for managed development runs."""

    @abstractmethod
    async def capabilities(self) -> RuntimeCapabilities: ...

    @abstractmethod
    async def create_run(
        self,
        *,
        cwd: str,
        model: str,
        sandbox_mode: str,
        approval_mode: str,
        developer_instructions: str,
    ) -> RuntimeRun: ...

    @abstractmethod
    async def start_turn(
        self,
        *,
        thread_id: str,
        prompt: str,
        cwd: str,
        model: str,
        reasoning_effort: str,
    ) -> RuntimeRun: ...

    @abstractmethod
    async def resume_run(
        self,
        *,
        thread_id: str,
        cwd: str,
        model: str,
        sandbox_mode: str,
        approval_mode: str,
    ) -> RuntimeRun: ...

    @abstractmethod
    async def cancel_run(self, *, thread_id: str, turn_id: str) -> None: ...

    @abstractmethod
    async def approve_action(self, *, server_request_id: str) -> None: ...

    @abstractmethod
    async def reject_action(
        self, *, server_request_id: str, cancel_turn: bool = False
    ) -> None: ...

    @abstractmethod
    def stream_events(self) -> AsyncIterator[RuntimeEvent]: ...

    @abstractmethod
    async def close(self) -> None: ...
