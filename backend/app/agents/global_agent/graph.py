from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from .langchain_adapter import LOCAL_RUNNABLE_CONFIG, local_tracing_disabled


class GlobalAgentGraphState(TypedDict, total=False):
    run_id: str
    skip: bool
    question: str
    thread_id: str
    message_id: str
    provider_name: str
    model: str
    effort: str
    recheck_full_context: bool
    customer_conversation_id: int | None
    context: list[dict[str, str]]
    citations: list[Any]
    planned_tools: list[tuple[str, dict[str, Any]]]
    tool_payloads: list[tuple[Any, dict[str, Any]]]
    customer_context: dict[str, Any] | None
    prompt: str
    answer: Any
    used_citations: list[Any]
    tool_references: list[Any]
    completed_run: Any


GraphNode = Callable[
    [GlobalAgentGraphState],
    Awaitable[dict[str, Any]],
]


GLOBAL_AGENT_GRAPH_NODE_ORDER = (
    "prepare_run",
    "load_context",
    "collect_evidence",
    "execute_tools",
    "build_prompt",
    "generate_answer",
    "validate_answer",
    "persist_answer",
    "publish_completed",
)


@dataclass(frozen=True, slots=True)
class GlobalAgentGraphNodes:
    prepare_run: GraphNode
    load_context: GraphNode
    collect_evidence: GraphNode
    execute_tools: GraphNode
    build_prompt: GraphNode
    generate_answer: GraphNode
    validate_answer: GraphNode
    persist_answer: GraphNode
    publish_completed: GraphNode

    def as_dict(self) -> dict[str, GraphNode]:
        return {
            name: getattr(self, name)
            for name in GLOBAL_AGENT_GRAPH_NODE_ORDER
        }


class GlobalAgentGraphRunner:
    """A fixed, single-agent graph with no autonomous tool loop or checkpointer."""

    def __init__(self, nodes: GlobalAgentGraphNodes) -> None:
        builder = StateGraph(GlobalAgentGraphState)
        for name, handler in nodes.as_dict().items():
            builder.add_node(name, handler)
        builder.add_edge(START, "prepare_run")
        builder.add_conditional_edges(
            "prepare_run",
            lambda state: "stop" if state.get("skip") else "continue",
            {"stop": END, "continue": "load_context"},
        )
        for current, following in zip(
            GLOBAL_AGENT_GRAPH_NODE_ORDER[1:-1],
            GLOBAL_AGENT_GRAPH_NODE_ORDER[2:],
            strict=True,
        ):
            builder.add_edge(current, following)
        builder.add_edge("publish_completed", END)
        self._compiled = builder.compile()

    @property
    def node_names(self) -> tuple[str, ...]:
        return GLOBAL_AGENT_GRAPH_NODE_ORDER

    async def ainvoke(self, run_id: str) -> GlobalAgentGraphState:
        with local_tracing_disabled():
            result = await self._compiled.ainvoke(
                {"run_id": run_id},
                config=LOCAL_RUNNABLE_CONFIG,
            )
        return GlobalAgentGraphState(**result)
