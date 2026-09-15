from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ProviderName = Literal["codex_cli", "deepseek", "openai_compatible"]
AgentContextScope = Literal["general_business", "customer_conversation"]
AgentRunStatus = Literal[
    "pending", "running", "completed", "failed", "cancelled", "interrupted"
]
AgentRunStepStatus = Literal[
    "pending", "running", "completed", "failed", "cancelled", "interrupted", "skipped"
]
AgentRunTracePhase = Literal[
    "context", "evidence", "tools", "generate", "validate", "persist"
]
AgentTargetPage = Literal[
    "", "home", "products", "customers", "projects", "finance",
    "business-analysis", "settings",
]


class AgentProfileView(BaseModel):
    id: str
    provider: ProviderName
    model: str
    reasoning_effort: str = ""
    label: str
    enabled: bool
    is_default: bool
    configured: bool
    revision: int
    created_at: datetime
    updated_at: datetime


class AgentModelOptionView(BaseModel):
    model: str
    display_name: str
    default_reasoning_effort: str | None = None
    supported_reasoning_efforts: list[str] = Field(default_factory=list)


class AgentProfileCreate(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: Literal[0]
    provider: ProviderName
    model: str = Field(min_length=1, max_length=128)
    reasoning_effort: str = Field(default="", max_length=32)
    label: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    is_default: bool = False


class AgentProfileUpdate(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=1)
    model: str = Field(min_length=1, max_length=128)
    reasoning_effort: str = Field(default="", max_length=32)
    label: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    is_default: bool = False


class AgentThreadCreate(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    profile_id: str = Field(min_length=1, max_length=128)
    title: str = Field(default="新对话", min_length=1, max_length=240)


class AgentThreadProfileUpdate(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=1)
    profile_id: str = Field(min_length=1, max_length=128)


class AgentThreadContextUpdate(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=1)
    context_scope: AgentContextScope
    conversation_id: int | None = Field(default=None, ge=1)


class AgentThreadDelete(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=1)


class AgentKnowledgeCitation(BaseModel):
    id: str
    relative_path: str
    absolute_path: str
    title: str
    heading: str
    snippet: str
    maturity: str
    content_hash: str


class AgentToolReference(BaseModel):
    id: str
    name: str
    label: str
    status: str
    duration_ms: int
    source: str = "local_business_data"
    observed_at: datetime | None = None
    revision: int | None = None
    read_only: bool = True
    sensitivity: str = "business_summary"


class AgentFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=800)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)


class AgentRequirementAnalysisItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=800)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class AgentRequirementRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1_200)
    severity: Literal["low", "medium", "high"]
    mitigation: str = Field(default="", max_length=1_200)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class AgentRequirementAnalysis(BaseModel):
    """Optional chat artifact created only when the operator explicitly asks for it."""

    model_config = ConfigDict(extra="forbid")

    maturity: Literal["discovery", "clarifying", "ready"]
    summary: str = Field(min_length=1, max_length=2_000)
    customer_confirmed: list[AgentRequirementAnalysisItem] = Field(
        default_factory=list, max_length=40
    )
    operator_decisions: list[AgentRequirementAnalysisItem] = Field(
        default_factory=list, max_length=40
    )
    unconfirmed: list[AgentRequirementAnalysisItem] = Field(
        default_factory=list, max_length=40
    )
    constraints: list[AgentRequirementAnalysisItem] = Field(
        default_factory=list, max_length=40
    )
    open_questions: list[str] = Field(default_factory=list, max_length=30)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    risks: list[AgentRequirementRisk] = Field(default_factory=list, max_length=30)

    def evidence_refs(self) -> list[str]:
        refs: list[str] = []
        for field_name in (
            "customer_confirmed", "operator_decisions", "unconfirmed", "constraints"
        ):
            for item in getattr(self, field_name):
                refs.extend(item.evidence_refs)
        for risk in self.risks:
            refs.extend(risk.evidence_refs)
        return list(dict.fromkeys(refs))


class AgentRequirementObjective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1_200)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class AgentRequirementCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1_200)
    objective_ids: list[str] = Field(min_length=1, max_length=20)
    priority: Literal["must", "should", "could"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class AgentRequirementStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1, max_length=1_200)
    capability_ids: list[str] = Field(min_length=1, max_length=30)
    dependency_ids: list[str] = Field(default_factory=list, max_length=20)
    work_items: list[str] = Field(default_factory=list, max_length=40)
    deliverables: list[str] = Field(default_factory=list, max_length=40)
    estimated_hours: float | None = Field(default=None, gt=0, le=100_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class AgentRequirementAcceptanceGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1_200)
    stage_ids: list[str] = Field(min_length=1, max_length=20)
    criteria: list[str] = Field(min_length=1, max_length=40)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class AgentRequirementBlueprint(BaseModel):
    """Four-layer chat blueprint with stable IDs and validated relationships."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    maturity: Literal["discovery", "clarifying", "ready"]
    objectives: list[AgentRequirementObjective] = Field(min_length=1, max_length=30)
    capabilities: list[AgentRequirementCapability] = Field(
        min_length=1, max_length=60
    )
    stages: list[AgentRequirementStage] = Field(min_length=1, max_length=40)
    acceptance_gates: list[AgentRequirementAcceptanceGate] = Field(
        min_length=1, max_length=60
    )
    out_of_scope: list[str] = Field(default_factory=list, max_length=40)
    assumptions: list[str] = Field(default_factory=list, max_length=40)
    open_questions: list[str] = Field(default_factory=list, max_length=40)
    risks: list[AgentRequirementRisk] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_relationships(self) -> "AgentRequirementBlueprint":
        collections = {
            "项目目标": [item.id for item in self.objectives],
            "功能能力": [item.id for item in self.capabilities],
            "实施阶段": [item.id for item in self.stages],
            "交付验收": [item.id for item in self.acceptance_gates],
            "风险": [item.id for item in self.risks],
        }
        all_ids: list[str] = []
        for label, values in collections.items():
            if len(values) != len(set(values)):
                raise ValueError(f"{label}存在重复 ID")
            all_ids.extend(values)
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("蓝图节点 ID 必须全局唯一")

        objective_ids = set(collections["项目目标"])
        capability_ids = set(collections["功能能力"])
        stage_ids = set(collections["实施阶段"])
        for capability in self.capabilities:
            if not set(capability.objective_ids).issubset(objective_ids):
                raise ValueError("功能能力引用了不存在的项目目标")
        for stage in self.stages:
            if not set(stage.capability_ids).issubset(capability_ids):
                raise ValueError("实施阶段引用了不存在的功能能力")
            if stage.id in stage.dependency_ids or not set(stage.dependency_ids).issubset(stage_ids):
                raise ValueError("实施阶段引用了无效依赖")
        for gate in self.acceptance_gates:
            if not set(gate.stage_ids).issubset(stage_ids):
                raise ValueError("交付验收引用了不存在的实施阶段")

        dependencies = {stage.id: set(stage.dependency_ids) for stage in self.stages}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(stage_id: str) -> None:
            if stage_id in visiting:
                raise ValueError("实施阶段存在循环依赖")
            if stage_id in visited:
                return
            visiting.add(stage_id)
            for dependency_id in dependencies[stage_id]:
                visit(dependency_id)
            visiting.remove(stage_id)
            visited.add(stage_id)

        for stage_id in stage_ids:
            visit(stage_id)
        return self

    def evidence_refs(self) -> list[str]:
        refs: list[str] = []
        for values in (
            self.objectives, self.capabilities, self.stages,
            self.acceptance_gates, self.risks,
        ):
            for item in values:
                refs.extend(item.evidence_refs)
        return list(dict.fromkeys(refs))


class AgentExecutionPlanStage(BaseModel):
    """One independently verifiable implementation stage."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    task_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]*-[0-9]{3,4}$")
    workspace_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]{1,127}$")
    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1, max_length=1_200)
    dependency_task_keys: list[str] = Field(default_factory=list, max_length=20)
    allowed_changes: list[str] = Field(min_length=1, max_length=40)
    deliverables: list[str] = Field(default_factory=list, max_length=40)
    process_tests: list[str] = Field(min_length=1, max_length=40)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=40)
    stop_conditions: list[str] = Field(default_factory=list, max_length=20)
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)


class AgentExecutionPlan(BaseModel):
    """Append-only chat artifact for phased, bounded implementation work."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1, max_length=2_000)
    readiness: Literal["discovery", "clarifying", "ready"]
    change_summary: str = Field(min_length=1, max_length=2_000)
    allowed_changes: list[str] = Field(min_length=1, max_length=60)
    must_not_change: list[str] = Field(min_length=1, max_length=60)
    out_of_scope: list[str] = Field(default_factory=list, max_length=60)
    stages: list[AgentExecutionPlanStage] = Field(min_length=1, max_length=40)
    assumptions: list[str] = Field(default_factory=list, max_length=40)
    open_questions: list[str] = Field(default_factory=list, max_length=40)
    risks: list[AgentRequirementRisk] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_stage_graph(self) -> "AgentExecutionPlan":
        stage_ids = [stage.id for stage in self.stages]
        task_keys = [stage.task_key for stage in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("执行计划阶段 ID 必须唯一")
        if len(task_keys) != len(set(task_keys)):
            raise ValueError("执行计划 task_key 必须唯一")
        known = set(task_keys)
        dependencies = {
            stage.task_key: set(stage.dependency_task_keys) for stage in self.stages
        }
        for task_key, values in dependencies.items():
            if task_key in values or not values.issubset(known):
                raise ValueError("执行计划引用了无效 task_key 依赖")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_key: str) -> None:
            if task_key in visiting:
                raise ValueError("执行计划阶段存在循环依赖")
            if task_key in visited:
                return
            visiting.add(task_key)
            for dependency in dependencies[task_key]:
                visit(dependency)
            visiting.remove(task_key)
            visited.add(task_key)

        for task_key in task_keys:
            visit(task_key)
        return self

    def evidence_refs(self) -> list[str]:
        refs: list[str] = []
        for stage in self.stages:
            refs.extend(stage.evidence_refs)
        for risk in self.risks:
            refs.extend(risk.evidence_refs)
        return list(dict.fromkeys(refs))


class AgentCustomerSummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=800)
    evidence_message_ids: list[int] = Field(default_factory=list, max_length=20)


class AgentCustomerConversationSummary(BaseModel):
    """Provider-produced summary; every assertion stays tied to message IDs."""

    model_config = ConfigDict(extra="forbid")

    goals: list[AgentCustomerSummaryItem] = Field(default_factory=list, max_length=20)
    confirmed_requirements: list[AgentCustomerSummaryItem] = Field(
        default_factory=list, max_length=30
    )
    unconfirmed_requirements: list[AgentCustomerSummaryItem] = Field(
        default_factory=list, max_length=30
    )
    constraints: list[AgentCustomerSummaryItem] = Field(default_factory=list, max_length=20)
    decisions: list[AgentCustomerSummaryItem] = Field(default_factory=list, max_length=20)
    recent_changes: list[AgentCustomerSummaryItem] = Field(default_factory=list, max_length=20)
    pending_questions: list[AgentCustomerSummaryItem] = Field(
        default_factory=list, max_length=20
    )
    risks: list[AgentCustomerSummaryItem] = Field(default_factory=list, max_length=20)

    def evidence_message_ids(self) -> list[int]:
        values: list[int] = []
        for field_name in (
            "goals", "confirmed_requirements", "unconfirmed_requirements",
            "constraints", "decisions", "recent_changes", "pending_questions",
            "risks",
        ):
            for item in getattr(self, field_name):
                values.extend(item.evidence_message_ids)
        return list(dict.fromkeys(values))


class AgentModelAnswer(BaseModel):
    """Strict provider output, validated again against supplied evidence IDs."""

    model_config = ConfigDict(extra="forbid")

    conclusion: str = Field(min_length=1, max_length=2_000)
    facts: list[AgentFact] = Field(default_factory=list, max_length=12)
    causes: list[str] = Field(default_factory=list, max_length=12)
    knowledge_citation_ids: list[str] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=12)
    confidence: Literal["low", "medium", "high"]
    observation_period: str = Field(default="当前本地快照", max_length=160)
    next_step: str = Field(min_length=1, max_length=800)
    target_page: AgentTargetPage = ""
    updated_customer_context: AgentCustomerConversationSummary | None = None
    requirement_analysis: AgentRequirementAnalysis | None = None
    requirement_blueprint: AgentRequirementBlueprint | None = None
    execution_plan: AgentExecutionPlan | None = None
    customer_create_proposal: "AgentCustomerCreateProposal | None" = None

    @field_validator(
        "causes", "knowledge_citation_ids", "limitations", mode="after"
    )
    @classmethod
    def deduplicate(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class AgentCustomerProposalText(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    value: str = Field(default="", max_length=4_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def value_requires_evidence(self):
        if self.value and not self.evidence_refs:
            raise ValueError("非空客户资料字段必须提供证据引用")
        return self


class AgentCustomerPriceProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_type: Literal["", "customer_budget", "operator_quote", "agreed_price"] = ""
    amount: float | None = Field(default=None, gt=0, le=100_000_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def price_requires_type_and_evidence(self):
        if self.amount is not None and not self.price_type:
            raise ValueError("客户价格金额必须包含价格类型")
        if (self.price_type or self.amount is not None) and not self.evidence_refs:
            raise ValueError("客户价格必须提供证据引用")
        return self


class AgentCustomerCreateProposal(BaseModel):
    """A reviewable proposal only; it never grants the model write authority."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: int = Field(ge=1)
    customer_name: AgentCustomerProposalText
    phone: AgentCustomerProposalText = Field(default_factory=AgentCustomerProposalText)
    source: Literal["xianyu", "wechat", "other"]
    level: Literal["A", "B", "C"] = "C"
    current_need: AgentCustomerProposalText = Field(default_factory=AgentCustomerProposalText)
    price: AgentCustomerPriceProposal = Field(default_factory=AgentCustomerPriceProposal)
    next_action: AgentCustomerProposalText = Field(default_factory=AgentCustomerProposalText)
    notes: AgentCustomerProposalText = Field(default_factory=AgentCustomerProposalText)

    @model_validator(mode="after")
    def customer_name_required(self):
        if not self.customer_name.value:
            raise ValueError("客户新增提案必须包含客户名称")
        return self

    def evidence_refs(self) -> set[str]:
        values = {
            *self.customer_name.evidence_refs,
            *self.phone.evidence_refs,
            *self.current_need.evidence_refs,
            *self.price.evidence_refs,
            *self.next_action.evidence_refs,
            *self.notes.evidence_refs,
        }
        return {value for value in values if value}


class AgentCustomerCreateConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    assistant_message_id: str = Field(min_length=8, max_length=128)
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_revision: int = Field(ge=0)
    confirmed: Literal[True]


class AgentMessageView(BaseModel):
    id: str
    thread_id: str
    role: Literal["user", "assistant"]
    content: str
    status: str
    run_id: str | None = None
    run_elapsed_ms: int | None = None
    answer: AgentModelAnswer | None = None
    citations: list[AgentKnowledgeCitation] = Field(default_factory=list)
    tool_references: list[AgentToolReference] = Field(default_factory=list)
    created_at: datetime


class AgentRunView(BaseModel):
    id: str
    request_id: str
    thread_id: str
    user_message_id: str
    assistant_message_id: str | None = None
    provider: ProviderName
    model: str
    reasoning_effort: str = ""
    status: AgentRunStatus
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class AgentRunStepView(BaseModel):
    id: str
    position: int
    node_name: str
    label: str
    phase: AgentRunTracePhase
    status: AgentRunStepStatus
    summary: str
    duration_ms: int
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AgentRunToolView(BaseModel):
    id: str
    position: int
    name: str
    label: str
    status: Literal[
        "pending", "running", "completed", "failed", "cancelled", "interrupted"
    ]
    summary: str
    duration_ms: int
    source: str = "local_business_data"
    observed_at: datetime | None = None
    revision: int | None = None
    read_only: bool = True
    sensitivity: str = "business_summary"
    created_at: datetime


class AgentRunTraceView(BaseModel):
    run_id: str
    thread_id: str
    provider: ProviderName
    model: str
    status: AgentRunStatus
    completed_steps: int
    total_steps: int
    tool_count: int
    elapsed_ms: int
    decision_summary: str
    legacy: bool = False
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    steps: list[AgentRunStepView] = Field(default_factory=list)
    tools: list[AgentRunToolView] = Field(default_factory=list)


class AgentCustomerContextOption(BaseModel):
    conversation_id: int
    customer_id: str | None = None
    channel: str
    customer_name: str
    item_title: str | None = None
    text_message_count: int
    image_message_count: int = 0
    latest_text_message_id: int | None = None
    latest_message_at: datetime | None = None
    summary_version: int | None = None
    summarized_through_message_id: int | None = None
    new_message_count: int = 0
    context_updated: bool = False


class AgentCustomerContextState(AgentCustomerContextOption):
    pass


class AgentThreadView(BaseModel):
    id: str
    title: str
    profile_id: str | None = None
    provider: ProviderName
    model: str
    reasoning_effort: str = ""
    context_scope: AgentContextScope = "general_business"
    customer_context: AgentCustomerContextState | None = None
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime
    messages: list[AgentMessageView] = Field(default_factory=list)
    active_run: AgentRunView | None = None
    latest_run: AgentRunView | None = None


class AgentMessageCreate(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=8_000)
    recheck_full_context: bool = False


class AgentRunCancel(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)


class AgentKnowledgeReindex(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    confirmed: Literal[True]


class AgentKnowledgeStatus(BaseModel):
    root: str
    approved_directories: list[str]
    active_documents: int
    inactive_documents: int
    chunks: int
    last_indexed_at: datetime | None = None


class AgentKnowledgeReindexResult(AgentKnowledgeStatus):
    indexed_documents: int
    excluded_documents: int
    deactivated_documents: int
    idempotent: bool = False


class AgentBootstrapView(BaseModel):
    profiles: list[AgentProfileView]
    threads: list[AgentThreadView]
    knowledge: AgentKnowledgeStatus


AgentModelAnswer.model_rebuild()
