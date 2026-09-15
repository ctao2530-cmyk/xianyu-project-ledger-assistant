from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping

from langchain_core.runnables import RunnableLambda, RunnableParallel
from langsmith.run_helpers import tracing_context

from ...ai import AIProvider


LOCAL_RUNNABLE_CONFIG: dict[str, Any] = {
    "callbacks": [],
    "tags": ["xunying-local-only"],
    "metadata": {"xunying_local_only": True},
}


@contextmanager
def local_tracing_disabled() -> Iterator[None]:
    """Disable LangSmith tracing even when the host environment enables it."""

    with tracing_context(enabled=False):
        yield


async def invoke_local_parallel(
    branches: Mapping[str, Callable[[dict[str, Any]], Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run bounded read-only LangChain branches without remote callbacks."""

    runnable = RunnableParallel(
        {name: RunnableLambda(handler) for name, handler in branches.items()}
    )
    with local_tracing_disabled():
        result = await runnable.ainvoke(payload, config=LOCAL_RUNNABLE_CONFIG)
    return dict(result)


class StructuredProviderRunnable:
    """Expose the existing provider contract as a local-only LangChain Runnable."""

    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider
        self._runnable = RunnableLambda(self._invoke)

    async def _invoke(self, payload: dict[str, Any]) -> Any:
        return await self.provider.generate_structured(
            payload["prompt"],
            result_type=payload["result_type"],
            task_key=payload["task_key"],
            model_selection=payload["model_selection"],
            timeout=payload["timeout"],
        )

    async def ainvoke(self, payload: dict[str, Any]) -> Any:
        with local_tracing_disabled():
            return await self._runnable.ainvoke(
                payload,
                config=LOCAL_RUNNABLE_CONFIG,
            )
