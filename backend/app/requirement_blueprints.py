from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictBlueprintModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceReference(StrictBlueprintModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    message_number: int = Field(ge=1, le=10_000)
    quote: str = Field(min_length=1, max_length=500)


class ObjectiveNode(StrictBlueprintModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=800)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class CapabilityNode(StrictBlueprintModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=1000)
    objective_ids: list[str] = Field(min_length=1, max_length=20)
    priority: Literal["must", "should", "could"] = "must"
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class StageNode(StrictBlueprintModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    title: str = Field(min_length=2, max_length=120)
    objective: str = Field(min_length=2, max_length=600)
    implementation: str = Field(min_length=2, max_length=1600)
    estimated_hours: float = Field(gt=0, le=2000)
    capability_ids: list[str] = Field(min_length=1, max_length=30)
    dependency_ids: list[str] = Field(default_factory=list, max_length=20)
    work_items: list[str] = Field(min_length=1, max_length=30)
    deliverables: list[str] = Field(min_length=1, max_length=20)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class AcceptanceGateNode(StrictBlueprintModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=800)
    stage_ids: list[str] = Field(min_length=1, max_length=20)
    criteria: list[str] = Field(min_length=1, max_length=30)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class RiskNode(StrictBlueprintModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=800)
    severity: Literal["low", "medium", "high"]
    mitigation: str = Field(min_length=2, max_length=800)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class RequirementBlueprintV2(StrictBlueprintModel):
    schema_version: Literal["2.0"] = "2.0"
    title: str = Field(min_length=2, max_length=300)
    project_type: str = Field(min_length=2, max_length=120)
    readiness: Literal["discovery", "clarifying", "ready", "approved"] = "clarifying"
    change_summary: str = Field(min_length=2, max_length=1000)
    objectives: list[ObjectiveNode] = Field(min_length=1, max_length=20)
    capabilities: list[CapabilityNode] = Field(min_length=1, max_length=60)
    stages: list[StageNode] = Field(min_length=1, max_length=20)
    acceptance_gates: list[AcceptanceGateNode] = Field(min_length=1, max_length=30)
    out_of_scope: list[str] = Field(default_factory=list, max_length=30)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    open_questions: list[str] = Field(default_factory=list, max_length=40)
    risks: list[RiskNode] = Field(default_factory=list, max_length=30)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_graph(self) -> "RequirementBlueprintV2":
        groups = {
            "目标": [node.id for node in self.objectives],
            "功能": [node.id for node in self.capabilities],
            "阶段": [node.id for node in self.stages],
            "验收门": [node.id for node in self.acceptance_gates],
            "风险": [node.id for node in self.risks],
            "证据": [node.id for node in self.evidence_refs],
        }
        all_ids: list[str] = []
        for label, ids in groups.items():
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label}节点存在重复 ID")
            all_ids.extend(ids)
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("不同类型节点之间不能复用 ID")

        objective_ids = set(groups["目标"])
        capability_ids = set(groups["功能"])
        stage_ids = set(groups["阶段"])
        evidence_ids = set(groups["证据"])
        for node in self.capabilities:
            self._require_refs(node.objective_ids, objective_ids, f"功能 {node.id} 的目标")
        for node in self.stages:
            self._require_refs(node.capability_ids, capability_ids, f"阶段 {node.id} 的功能")
            self._require_refs(node.dependency_ids, stage_ids, f"阶段 {node.id} 的依赖")
            if node.id in node.dependency_ids:
                raise ValueError(f"阶段 {node.id} 不能依赖自身")
        for node in self.acceptance_gates:
            self._require_refs(node.stage_ids, stage_ids, f"验收门 {node.id} 的阶段")
        for node in [*self.objectives, *self.capabilities, *self.stages, *self.acceptance_gates, *self.risks]:
            self._require_refs(node.evidence_refs, evidence_ids, f"节点 {node.id} 的证据")
        self._reject_dependency_cycles()
        return self

    @staticmethod
    def _require_refs(refs: list[str], valid: set[str], label: str) -> None:
        missing = [value for value in refs if value not in valid]
        if missing:
            raise ValueError(f"{label}引用不存在：{', '.join(missing[:5])}")

    def _reject_dependency_cycles(self) -> None:
        graph: dict[str, list[str]] = defaultdict(list)
        for stage in self.stages:
            graph[stage.id].extend(stage.dependency_ids)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError(f"阶段依赖存在循环：{node_id}")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency_id in graph[node_id]:
                visit(dependency_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in graph:
            visit(node_id)


class LeadAnalysisResult(StrictBlueprintModel):
    has_project_need: bool
    confidence: float = Field(ge=0, le=1)
    project_type: str = Field(min_length=2, max_length=120)
    suggested_title: str = Field(min_length=2, max_length=200)
    confirmed_signals: list[str] = Field(default_factory=list, max_length=20)
    open_questions: list[str] = Field(default_factory=list, max_length=20)
    budget_signals: list[str] = Field(default_factory=list, max_length=10)
    timeline_signals: list[str] = Field(default_factory=list, max_length=10)
    intent_signals: list[str] = Field(default_factory=list, max_length=10)
    risks: list[str] = Field(default_factory=list, max_length=20)
    message_refs: list[int] = Field(default_factory=list, max_length=50)
    conversion_advice: str = Field(min_length=2, max_length=800)
