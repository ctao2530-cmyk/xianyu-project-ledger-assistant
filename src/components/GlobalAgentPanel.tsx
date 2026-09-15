import {
  ArrowRight,
  BookOpenText,
  Brain,
  CaretDown,
  CaretRight,
  CheckCircle,
  Clock,
  Database,
  GearSix,
  LinkSimple,
  PaperPlaneTilt,
  Plus,
  ShieldCheck,
  Sparkle,
  StopCircle,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  type CSSProperties,
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  connectPlatformEvents,
  localPlatformService,
  type GlobalAgentBootstrap,
  type CustomerAnalysisSubscription,
  type GlobalAgentCustomerCreateProposal,
  type GlobalAgentCustomerContextOption,
  type GlobalAgentMessage,
  type GlobalAgentExecutionPlan,
  type GlobalAgentProfile,
  type GlobalAgentRunTrace,
  type GlobalAgentRequirementAnalysis,
  type GlobalAgentRequirementBlueprint,
  type GlobalAgentTargetPage,
  type GlobalAgentThread,
} from "../data/localPlatformService";
import { acceptMigratedLedger } from "../data/mockService";
import "./global-agent.css";


const providerLabels = {
  codex_cli: "Codex",
  deepseek: "DeepSeek",
  openai_compatible: "OpenAI Compatible",
};

const initialAnalysisOptions = {
  allowImages: false,
  authorizationNote: "仅用于当前绑定客户的新消息增量需求分析与执行计划修订",
};

const toolSourceLabels: Record<string, string> = {
  business_customers: "客户业务库",
  owned_product_registry: "当前卖家商品库",
  business_projects: "项目业务库",
  canonical_ledger: "统一账本",
  business_analysis_overview: "本地经营概览",
  bound_customer_conversation: "已绑定客户文字会话",
  local_business_data: "本地业务数据",
};

function formatObservedAt(value: string | null) {
  if (!value) return "读取时间未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "读取时间未记录";
  return `读取于 ${date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })}`;
}

function analysisStateLabel(value: CustomerAnalysisSubscription["analysis_state"]) {
  return {
    waiting: "等待新消息",
    pending: "已收到新消息",
    analyzing: "正在增量分析",
    completed: "最新版本已生成",
    failed: "分析失败",
    configuration_required: "OpenAI API 待配置",
  }[value];
}

function toolProvenance(tool: {
  source: string;
  observed_at: string | null;
  revision: number | null;
  read_only: boolean;
}) {
  return [
    toolSourceLabels[tool.source] || "本地业务数据",
    formatObservedAt(tool.observed_at),
    tool.revision == null ? null : `revision ${tool.revision}`,
    tool.read_only ? "只读" : "权限状态未确认",
  ].filter(Boolean).join(" · ");
}

function requestId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function statusLabel(status: string) {
  return {
    pending: "排队中",
    running: "分析中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    interrupted: "已中断",
  }[status] || status;
}

const executionPhases = [
  ["context", "上下文"],
  ["evidence", "证据"],
  ["tools", "工具"],
  ["generate", "生成"],
  ["validate", "校验"],
  ["persist", "保存"],
] as const;

const completedTraceStatuses = new Set(["completed", "skipped"]);
const terminalTraceStatuses = new Set(["failed", "cancelled", "interrupted"]);

function formatTraceDuration(milliseconds: number) {
  if (milliseconds < 1000) return `${milliseconds} ms`;
  return `${(milliseconds / 1000).toFixed(milliseconds < 10_000 ? 1 : 0)} 秒`;
}

function formatElapsedDuration(milliseconds: number) {
  const totalSeconds = Math.max(1, Math.round(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours} 小时 ${minutes} 分钟 ${seconds} 秒`;
  if (minutes > 0) return `${minutes} 分钟 ${seconds} 秒`;
  return `${seconds} 秒`;
}

function phaseStatus(trace: GlobalAgentRunTrace, phase: typeof executionPhases[number][0]) {
  const steps = trace.steps.filter((step) => step.phase === phase);
  if (steps.some((step) => terminalTraceStatuses.has(step.status))) return "failed";
  if (steps.some((step) => step.status === "running")) return "running";
  if (steps.length > 0 && steps.every((step) => completedTraceStatuses.has(step.status))) return "completed";
  return "pending";
}

function AgentExecutionTrace({ trace, showSteps, onToggleSteps, onCancel }: {
  trace: GlobalAgentRunTrace;
  showSteps: boolean;
  onToggleSteps: () => void;
  onCancel?: () => void;
}) {
  if (trace.legacy) {
    return <section className="agent-execution-trace is-legacy" aria-label="小策执行轨迹">
      <div className="agent-trace-legacy"><Clock size={18} /><span><b>旧记录未保存节点轨迹</b><small>这条回答仍保留原有证据来源，但无法补写当时的步骤与工具状态。</small></span></div>
      <footer><ShieldCheck size={14} />仅显示真实留存记录，不根据回答内容反推执行过程</footer>
    </section>;
  }

  const activeStep = trace.steps.find((step) => step.status === "running");
  const progress = Math.min(
    trace.total_steps,
    trace.completed_steps + (activeStep ? 1 : 0),
  );
  const stateLabel = trace.status === "completed"
    ? "执行完成"
    : trace.status === "running" || trace.status === "pending"
      ? "正在执行"
      : statusLabel(trace.status);

  return <section className={`agent-execution-trace is-${trace.status}`} aria-label="小策执行轨迹">
    <header className="agent-trace-summary">
      <span className="agent-trace-state"><i className={trace.status === "running" || trace.status === "pending" ? "is-active" : ""}>{trace.status === "completed" ? <CheckCircle size={17} weight="fill" /> : <Brain size={17} weight="duotone" />}</i><b>{stateLabel}</b>{activeStep && <small>{activeStep.label}</small>}</span>
      <span><b>{progress} / {trace.total_steps} 步</b><small>固定流程</small></span>
      <span><b>{trace.tool_count} 个只读工具</b><small>无写入权限</small></span>
      <span><b><Clock size={16} />已用 {formatTraceDuration(trace.elapsed_ms)}</b><small>本地计时</small></span>
    </header>

    <ol className="agent-trace-phases" aria-label="执行阶段">
      {executionPhases.map(([phase, label]) => {
        const state = phaseStatus(trace, phase);
        return <li className={`is-${state}`} key={phase}><i>{state === "completed" ? <CheckCircle size={19} weight="fill" /> : state === "failed" ? <WarningCircle size={18} weight="fill" /> : <span />}</i><b>{label}</b></li>;
      })}
    </ol>

    <section className="agent-trace-tools" aria-label="本次工具调用">
      <h3>本次工具调用</h3>
      {trace.tools.length > 0 ? <div>{trace.tools.map((tool) => <article key={tool.id}>
        <i><Database size={17} weight="duotone" /></i>
        <span><b>{tool.label}</b><small>{tool.summary}</small><small className="agent-tool-provenance">{toolProvenance(tool)}</small></span>
        <em className={`is-${tool.status}`}>{tool.status === "completed" ? <CheckCircle size={15} weight="fill" /> : tool.status === "running" ? <span className="agent-button-spinner" /> : terminalTraceStatuses.has(tool.status) ? <WarningCircle size={15} weight="fill" /> : null}{tool.status === "completed" ? "已完成" : statusLabel(tool.status)}</em>
        <time>{formatTraceDuration(tool.duration_ms)}</time>
      </article>)}</div> : <p>本次没有调用额外业务工具。</p>}
      <aside><ShieldCheck size={15} /><span><b>读取原因</b>{trace.decision_summary}</span></aside>
    </section>

    <button className="agent-trace-step-toggle" type="button" aria-expanded={showSteps} onClick={onToggleSteps}><CaretDown size={17} />{showSteps ? "收起步骤明细" : `查看全部 ${trace.total_steps} 个步骤`}</button>
    {showSteps && <ol className="agent-trace-step-list">
      {trace.steps.map((step) => <li className={`is-${step.status}`} key={step.id}><i>{step.position + 1}</i><span><b>{step.label}</b><small>{step.summary}</small></span><em>{statusLabel(step.status)}</em><time>{step.duration_ms > 0 ? formatTraceDuration(step.duration_ms) : "—"}</time></li>)}
    </ol>}
    <footer><span><ShieldCheck size={14} />仅显示可审计摘要 · 不展示隐藏思维、原始 Prompt 或敏感数据</span>{onCancel && <button className="agent-trace-cancel" type="button" onClick={onCancel}><StopCircle size={16} />取消</button>}</footer>
  </section>;
}

function AgentLiveProgress({ trace, onCancel }: {
  trace: GlobalAgentRunTrace;
  onCancel: () => void;
}) {
  const activeStep = trace.steps.find((step) => step.status === "running")
    || trace.steps.find((step) => step.status === "pending");
  const activeTool = trace.tools.find((tool) => tool.status === "running");
  const progress = Math.min(
    trace.total_steps,
    trace.completed_steps + (activeStep?.status === "running" ? 1 : 0),
  );
  const title = activeTool?.summary
    || activeStep?.summary
    || "正在建立可审计执行过程";
  const detail = activeTool
    ? `${activeStep?.label || "调用只读工具"} · 不执行写入`
    : activeStep?.label || "正在读取本次回答所需证据";

  return <section className="agent-live-progress" role="status" aria-live="polite" aria-label="小策当前执行状态">
    <i><Brain size={17} weight="duotone" /></i>
    <span><b>{title}</b><small>{detail} · {progress} / {trace.total_steps} 步 · 已用 {formatTraceDuration(trace.elapsed_ms)}</small></span>
    <button type="button" aria-label="取消小策回答" title="取消" onClick={onCancel}><StopCircle size={18} /></button>
  </section>;
}

const maturityLabels = {
  discovery: "探索中",
  clarifying: "澄清中",
  ready: "可成稿",
};

function RequirementAnalysisCard({ analysis, evidenceLabel }: {
  analysis: GlobalAgentRequirementAnalysis;
  evidenceLabel: (reference: string) => string;
}) {
  const groups = [
    ["客户已确认", analysis.customer_confirmed],
    ["经营者补充", analysis.operator_decisions],
    ["尚未确认", analysis.unconfirmed],
    ["约束", analysis.constraints],
  ] as const;
  return <section className="agent-requirement-artifact agent-requirement-analysis" aria-label="需求分析">
    <header><span><b>需求分析</b><small>客户事实、经营者判断和待确认项分别保留</small></span><em className={`maturity-${analysis.maturity}`}>{maturityLabels[analysis.maturity]}</em></header>
    <p className="agent-requirement-summary">{analysis.summary}</p>
    <div className="agent-requirement-analysis-grid">
      {groups.map(([label, items]) => <section key={label}><h5>{label}</h5>{items.length
        ? <ul>{items.map((item, index) => <li key={`${label}-${index}`}><span>{item.text}</span>{item.evidence_refs.length > 0 && <small>{item.evidence_refs.map(evidenceLabel).join(" · ")}</small>}</li>)}</ul>
        : <p>当前没有可确认内容。</p>}</section>)}
    </div>
    {(analysis.open_questions.length > 0 || analysis.assumptions.length > 0) && <div className="agent-requirement-questions">
      {analysis.open_questions.length > 0 && <section><h5>待确认问题</h5>{analysis.open_questions.map((item) => <p key={item}>{item}</p>)}</section>}
      {analysis.assumptions.length > 0 && <section><h5>假设</h5>{analysis.assumptions.map((item) => <p key={item}>{item}</p>)}</section>}
    </div>}
    {analysis.risks.length > 0 && <aside className="agent-requirement-risks"><WarningCircle size={15} /><span><b>风险与边界</b>{analysis.risks.map((risk) => <small key={risk.id}>{risk.title}：{risk.description}{risk.mitigation ? `；建议：${risk.mitigation}` : ""}</small>)}</span></aside>}
  </section>;
}

function RequirementBlueprintCard({ blueprint, evidenceLabel }: {
  blueprint: GlobalAgentRequirementBlueprint;
  evidenceLabel: (reference: string) => string;
}) {
  const columns = [
    ["项目目标", "为什么要做", blueprint.objectives.map((item) => ({
      id: item.id,
      title: item.title,
      description: item.description,
      evidence_refs: item.evidence_refs,
    }))],
    ["功能能力", "需要实现什么", blueprint.capabilities.map((item) => ({
      id: item.id,
      title: item.title,
      description: `${item.priority.toUpperCase()} · ${item.description}`,
      evidence_refs: item.evidence_refs,
    }))],
    ["实施阶段", "具体怎么实现", blueprint.stages.map((item) => ({
      id: item.id,
      title: item.title,
      description: `${item.objective}${item.estimated_hours === null ? " · 工时待核验" : ` · ${item.estimated_hours} 小时`}`,
      evidence_refs: item.evidence_refs,
    }))],
    ["交付验收", "怎样算完成", blueprint.acceptance_gates.map((item) => ({
      id: item.id,
      title: item.title,
      description: `${item.description}${item.criteria.length ? ` · ${item.criteria.join("；")}` : ""}`,
      evidence_refs: item.evidence_refs,
    }))],
  ] as const;
  return <section className="agent-requirement-artifact agent-requirement-blueprint" aria-label="需求蓝图">
    <header><span><b>需求蓝图</b><small>{blueprint.title} · 项目目标 → 功能能力 → 实施阶段 → 交付验收</small></span><em className={`maturity-${blueprint.maturity}`}>{maturityLabels[blueprint.maturity]}</em></header>
    <div className="agent-blueprint-counts"><span>{blueprint.objectives.length} 个目标</span><span>{blueprint.capabilities.length} 项能力</span><span>{blueprint.stages.length} 个阶段</span><span>{blueprint.acceptance_gates.length} 项验收</span></div>
    <div className="agent-blueprint-grid">
      {columns.map(([title, subtitle, items]) => <section key={title}><header><b>{title}</b><small>{subtitle}</small></header><div>{items.map((item) => <article key={item.id}><b>{item.title}</b><p>{item.description}</p>{item.evidence_refs.length > 0 && <small>{item.evidence_refs.map(evidenceLabel).join(" · ")}</small>}</article>)}</div></section>)}
    </div>
    {(blueprint.open_questions.length > 0 || blueprint.out_of_scope.length > 0 || blueprint.assumptions.length > 0) && <aside className="agent-blueprint-boundary"><WarningCircle size={15} /><span>{blueprint.open_questions.length > 0 && <small>待确认：{blueprint.open_questions.join("；")}</small>}{blueprint.out_of_scope.length > 0 && <small>范围外：{blueprint.out_of_scope.join("；")}</small>}{blueprint.assumptions.length > 0 && <small>假设：{blueprint.assumptions.join("；")}</small>}</span></aside>}
  </section>;
}

function ExecutionPlanCard({ plan, evidenceLabel }: {
  plan: GlobalAgentExecutionPlan;
  evidenceLabel: (reference: string) => string;
}) {
  const boundaries = [
    ["允许修改", plan.allowed_changes, "is-allowed"],
    ["必须保持", plan.must_not_change, "is-protected"],
    ["不在范围", plan.out_of_scope, "is-out-of-scope"],
  ] as const;
  return <section className="agent-requirement-artifact agent-execution-plan-artifact" aria-label="分阶段执行计划">
    <header><span><b>分阶段执行计划</b><small>{plan.title} · 每个 task_key 对应一个可独立验收的阶段</small></span><em className={`maturity-${plan.readiness}`}>{maturityLabels[plan.readiness]}</em></header>
    <div className="agent-plan-summary"><small>目标</small><b>{plan.objective}</b><p>{plan.change_summary}</p></div>
    <div className="agent-plan-boundaries">
      {boundaries.map(([label, values, className]) => <section className={className} key={label}><h5>{label}</h5>{values.length
        ? <ul>{values.map((item, index) => <li key={`${label}-${index}`}>{item}</li>)}</ul>
        : <p>无</p>}</section>)}
    </div>
    <ol className="agent-plan-stages">
      {plan.stages.map((stage, index) => <li key={stage.task_key}>
        <header><i>{index + 1}</i><span><b>{stage.title}</b><small><code>{stage.task_key}</code><code>{stage.workspace_key}</code></small></span></header>
        <p>{stage.objective}</p>
        <small className="agent-plan-dependencies">依赖：{stage.dependency_task_keys.length ? stage.dependency_task_keys.join("、") : "无，可独立开始"}</small>
        <div className="agent-plan-stage-grid">
          <section><h5>本阶段允许修改</h5><ul>{stage.allowed_changes.map((item, itemIndex) => <li key={`allowed-${itemIndex}`}>{item}</li>)}</ul></section>
          {stage.deliverables.length > 0 && <section><h5>交付物</h5><ul>{stage.deliverables.map((item, itemIndex) => <li key={`deliverable-${itemIndex}`}>{item}</li>)}</ul></section>}
          <section><h5>过程测试</h5><ul>{stage.process_tests.map((item, itemIndex) => <li key={`test-${itemIndex}`}>{item}</li>)}</ul></section>
          <section><h5>验收标准</h5><ul>{stage.acceptance_criteria.map((item, itemIndex) => <li key={`acceptance-${itemIndex}`}>{item}</li>)}</ul></section>
          {stage.stop_conditions.length > 0 && <section className="is-stop"><h5>停止条件</h5><ul>{stage.stop_conditions.map((item, itemIndex) => <li key={`stop-${itemIndex}`}>{item}</li>)}</ul></section>}
        </div>
        {stage.evidence_refs.length > 0 && <footer>证据：{stage.evidence_refs.map(evidenceLabel).join(" · ")}</footer>}
      </li>)}
    </ol>
    {(plan.assumptions.length > 0 || plan.open_questions.length > 0 || plan.risks.length > 0) && <aside className="agent-plan-notes"><WarningCircle size={15} /><span>{plan.assumptions.length > 0 && <small>假设：{plan.assumptions.join("；")}</small>}{plan.open_questions.length > 0 && <small>待确认：{plan.open_questions.join("；")}</small>}{plan.risks.length > 0 && <small>风险：{plan.risks.map((risk) => `${risk.title}：${risk.description}`).join("；")}</small>}</span></aside>}
  </section>;
}

type CustomerProposalStatus = {
  state: "idle" | "busy" | "created" | "unavailable";
  message?: string;
};

const customerProposalPriceLabels = {
  "": "价格待确认",
  customer_budget: "客户预算",
  operator_quote: "我的报价",
  agreed_price: "双方确认价",
} as const;

function CustomerCreateProposalCard({
  proposal,
  status,
  evidenceLabel,
  onRevise,
  onConfirm,
}: {
  proposal: GlobalAgentCustomerCreateProposal;
  status: CustomerProposalStatus;
  evidenceLabel: (reference: string) => string;
  onRevise: () => void;
  onConfirm: () => void;
}) {
  const evidence = (references: string[]) => references.length
    ? references.map(evidenceLabel).join(" · ")
    : "暂未提供证据";
  const price = proposal.price.amount === null
    ? "金额待确认"
    : `¥${proposal.price.amount.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return <section className="agent-customer-proposal" aria-label="客户资料提案">
    <header><span><b>客户资料提案</b><small>仅为待确认草稿，尚未写入客户列表</small></span><em>人工确认</em></header>
    <div className="agent-customer-proposal-identity"><i>{proposal.customer_name.value.slice(0, 1)}</i><span><b>{proposal.customer_name.value}</b><small>{proposal.source === "xianyu" ? "闲鱼" : proposal.source === "wechat" ? "微信" : "其他来源"} · {proposal.level} 级客户</small><em>{evidence(proposal.customer_name.evidence_refs)}</em></span></div>
    <div className="agent-customer-proposal-grid">
      <span className="wide"><small>当前需求</small><b>{proposal.current_need.value || "待补充"}</b><em>{evidence(proposal.current_need.evidence_refs)}</em></span>
      <span><small>{customerProposalPriceLabels[proposal.price.price_type]}</small><b>{price}</b><em>{evidence(proposal.price.evidence_refs)}</em></span>
      <span><small>联系方式</small><b>{proposal.phone.value || "暂未提供"}</b><em>{evidence(proposal.phone.evidence_refs)}</em></span>
      <span className="wide"><small>下一步行动</small><b>{proposal.next_action.value || "待补充"}</b><em>{evidence(proposal.next_action.evidence_refs)}</em></span>
      {proposal.notes.value && <span className="wide"><small>补充备注</small><b>{proposal.notes.value}</b><em>{evidence(proposal.notes.evidence_refs)}</em></span>}
    </div>
    {status.message && <p className={`agent-customer-proposal-status is-${status.state}`}><ShieldCheck size={15} />{status.message}</p>}
    <footer><button type="button" disabled={status.state === "busy" || status.state === "created"} onClick={onRevise}>返回修改</button><button className="primary" type="button" disabled={status.state === "busy" || status.state === "created" || status.state === "unavailable"} onClick={onConfirm}>{status.state === "busy" ? "正在核对并写入…" : status.state === "created" ? "已加入客户列表" : "确认加入客户列表"}</button></footer>
  </section>;
}

function AssistantMessage({ message, proposalStatus, trace, traceExpanded, traceStepsExpanded, traceLoading, onToggleTrace, onToggleTraceSteps, onConfirmProposal, onReviseProposal, onNavigate }: {
  message: GlobalAgentMessage;
  proposalStatus: CustomerProposalStatus;
  trace: GlobalAgentRunTrace | null;
  traceExpanded: boolean;
  traceStepsExpanded: boolean;
  traceLoading: boolean;
  onToggleTrace: () => void;
  onToggleTraceSteps: () => void;
  onConfirmProposal: (message: GlobalAgentMessage) => void;
  onReviseProposal: (message: GlobalAgentMessage) => void;
  onNavigate: (target: GlobalAgentTargetPage) => void;
}) {
  const answer = message.answer;
  if (!answer) return <article className="agent-answer-card is-invalid"><WarningCircle size={18} /><p>这条历史回答缺少可读取的结构。</p></article>;
  const evidence = new Map([
    ...message.citations.map((item) => [item.id, `${item.title} · ${item.heading}`] as const),
    ...message.tool_references.map((item) => [item.id, item.label] as const),
  ]);
  const evidenceLabel = (reference: string) => {
    if (reference.startsWith("customer-message:")) return `消息 #${reference.slice("customer-message:".length)}`;
    if (reference.startsWith("operator-note:")) return "经营者补充";
    return evidence.get(reference) || reference;
  };
  const elapsedMs = trace?.elapsed_ms ?? message.run_elapsed_ms;
  return <>
    {message.run_id && <section className="agent-trace-history">
      <button className="agent-run-duration" type="button" aria-expanded={traceExpanded} onClick={onToggleTrace}>
        <span>{elapsedMs == null ? "查看执行过程" : `用时 ${formatElapsedDuration(elapsedMs)}`}</span>
        <CaretRight size={16} />
      </button>
      {traceExpanded && (trace
        ? <AgentExecutionTrace trace={trace} showSteps={traceStepsExpanded} onToggleSteps={onToggleTraceSteps} />
        : <div className="agent-trace-loading"><span className="agent-button-spinner" />{traceLoading ? "正在读取已保存过程…" : "过程暂时无法读取"}</div>)}
    </section>}
    <article className="agent-answer-card">
    <header>
      <span><Sparkle size={16} weight="fill" />小策判断</span>
      <div><em className={`confidence-${answer.confidence}`}>{answer.confidence === "high" ? "高" : answer.confidence === "medium" ? "中" : "低"}置信度</em><small><Clock size={13} />{answer.observation_period}</small></div>
    </header>
    <section className="agent-answer-conclusion"><small>直接结论</small><p>{answer.conclusion}</p></section>
    <div className="agent-answer-chain">
      <section><h4><i>1</i>事实</h4>{answer.facts.length ? <ul>{answer.facts.map((fact, index) => <li key={`${fact.text}-${index}`}><span>{fact.text}</span>{fact.evidence_refs.length > 0 && <small>{fact.evidence_refs.map(evidenceLabel).join(" · ")}</small>}</li>)}</ul> : <p>当前没有足够的可追溯事实。</p>}</section>
      <section><h4><i>2</i>原因</h4>{answer.causes.length ? <ul>{answer.causes.map((cause) => <li key={cause}>{cause}</li>)}</ul> : <p>未形成额外原因判断。</p>}</section>
      <section className="agent-next-step"><h4><i>3</i>建议</h4><p>{answer.next_step}</p>{answer.target_page && <button type="button" onClick={() => onNavigate(answer.target_page)}>打开对应页面 <ArrowRight size={14} /></button>}</section>
    </div>
    {answer.requirement_analysis && <RequirementAnalysisCard analysis={answer.requirement_analysis} evidenceLabel={evidenceLabel} />}
    {answer.requirement_blueprint && <RequirementBlueprintCard blueprint={answer.requirement_blueprint} evidenceLabel={evidenceLabel} />}
    {answer.execution_plan && <ExecutionPlanCard plan={answer.execution_plan} evidenceLabel={evidenceLabel} />}
    {answer.customer_create_proposal && <CustomerCreateProposalCard proposal={answer.customer_create_proposal} status={proposalStatus} evidenceLabel={evidenceLabel} onRevise={() => onReviseProposal(message)} onConfirm={() => onConfirmProposal(message)} />}
    {answer.limitations.length > 0 && <aside className="agent-limitations"><WarningCircle size={16} /><span><b>限制与反证</b>{answer.limitations.join("；")}</span></aside>}
    {(message.citations.length > 0 || message.tool_references.length > 0) && <details className="agent-evidence-details">
      <summary><LinkSimple size={15} />查看证据与数据来源 <CaretDown size={14} /></summary>
      <div>
        {message.citations.map((citation) => <article key={citation.id}>
          <i><BookOpenText size={16} /></i><span><b>{citation.title}</b><small>{citation.relative_path} · {citation.heading} · {citation.maturity}</small><p>{citation.snippet}</p></span>
        </article>)}
        {message.tool_references.map((tool) => <article key={tool.id}>
          <i><Database size={16} /></i><span><b>{tool.label}</b><small>{tool.status === "completed" ? "已读取" : "读取失败"} · {tool.duration_ms}ms</small><small className="agent-tool-provenance">{toolProvenance(tool)}</small></span>
        </article>)}
      </div>
    </details>}
    </article>
  </>;
}

export function GlobalAgentPanel({
  open,
  style,
  onClose,
  onNavigate,
}: {
  open: boolean;
  style: CSSProperties;
  onClose: () => void;
  onNavigate: (target: GlobalAgentTargetPage) => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const [bootstrap, setBootstrap] = useState<GlobalAgentBootstrap | null>(null);
  const [thread, setThread] = useState<GlobalAgentThread | null>(null);
  const [contextOptions, setContextOptions] = useState<GlobalAgentCustomerContextOption[]>([]);
  const [selectedContext, setSelectedContext] = useState("general_business");
  const [recheckFullContext, setRecheckFullContext] = useState(false);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [knowledgeBusy, setKnowledgeBusy] = useState(false);
  const [error, setError] = useState("");
  const [grantPanelOpen, setGrantPanelOpen] = useState(false);
  const [grantBusy, setGrantBusy] = useState(false);
  const [analysisSubscription, setAnalysisSubscription] = useState<CustomerAnalysisSubscription | null>(null);
  const [analysisOptions, setAnalysisOptions] = useState(initialAnalysisOptions);
  const [grantMessage, setGrantMessage] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const [customerProposalStates, setCustomerProposalStates] = useState<Record<string, CustomerProposalStatus>>({});
  const [runTraces, setRunTraces] = useState<Record<string, GlobalAgentRunTrace>>({});
  const [expandedTraceRuns, setExpandedTraceRuns] = useState<Set<string>>(new Set());
  const [expandedStepRuns, setExpandedStepRuns] = useState<Set<string>>(new Set());
  const [traceLoadingRuns, setTraceLoadingRuns] = useState<Set<string>>(new Set());
  const traceRequestSequence = useRef<Record<string, number>>({});
  const grantRequestSequence = useRef(0);

  const profiles = bootstrap?.profiles.filter((profile) => profile.enabled) || [];
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId) || null;

  const loadBootstrap = async () => {
    setLoading(true);
    setError("");
    try {
      const [value, options] = await Promise.all([
        localPlatformService.globalAgentBootstrap(),
        localPlatformService.globalAgentCustomerContextOptions(),
      ]);
      setBootstrap(value);
      setContextOptions(options);
      const preferred = value.profiles.find((profile) => profile.is_default && profile.enabled)
        || value.profiles.find((profile) => profile.enabled);
      setSelectedProfileId((current) => current && value.profiles.some((item) => item.id === current) ? current : preferred?.id || "");
      if (thread) {
        const next = value.threads.find((item) => item.id === thread.id);
        if (!next) setThread(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "小策暂时无法连接本机服务");
    } finally {
      setLoading(false);
    }
  };

  const refreshThread = async (threadId: string) => {
    try {
      const value = await localPlatformService.globalAgentThread(threadId);
      setThread(value);
      setSelectedProfileId(value.profile_id || "");
      setSelectedContext(value.customer_context ? `customer:${value.customer_context.conversation_id}` : "general_business");
      setRecheckFullContext(false);
      setBootstrap((current) => current ? {
        ...current,
        threads: [value, ...current.threads.filter((item) => item.id !== value.id)],
      } : current);
      if (!value.active_run) setSending(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "对话刷新失败");
    }
  };

  const refreshRunTrace = async (runId: string) => {
    const sequence = (traceRequestSequence.current[runId] || 0) + 1;
    traceRequestSequence.current[runId] = sequence;
    setTraceLoadingRuns((current) => new Set(current).add(runId));
    try {
      const value = await localPlatformService.globalAgentRunTrace(runId);
      if (traceRequestSequence.current[runId] !== sequence) return;
      setRunTraces((current) => ({ ...current, [runId]: value }));
    } catch {
      // Thread and answer remain usable if an old trace cannot be loaded.
    } finally {
      if (traceRequestSequence.current[runId] === sequence) {
        setTraceLoadingRuns((current) => {
          const next = new Set(current);
          next.delete(runId);
          return next;
        });
      }
    }
  };

  const toggleRunTrace = (runId: string) => {
    const willOpen = !expandedTraceRuns.has(runId);
    setExpandedTraceRuns((current) => {
      const next = new Set(current);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
    if (willOpen && !runTraces[runId]) void refreshRunTrace(runId);
  };

  const toggleRunTraceSteps = (runId: string) => {
    setExpandedStepRuns((current) => {
      const next = new Set(current);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  };

  useEffect(() => {
    if (!open) return;
    void loadBootstrap();
    const frame = window.requestAnimationFrame(() => panelRef.current?.focus({ preventScroll: true }));
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => {
    const sequence = grantRequestSequence.current + 1;
    grantRequestSequence.current = sequence;
    setGrantMessage("");
    if (!open || !thread?.id || !thread.customer_context) {
      setAnalysisSubscription(null);
      setGrantPanelOpen(false);
      return;
    }
    void localPlatformService.customerAnalysisSubscription(thread.id).then((savedAnalysis) => {
      if (grantRequestSequence.current !== sequence) return;
      setAnalysisSubscription(savedAnalysis);
      setAnalysisOptions((current) => ({
        ...current,
        allowImages: savedAnalysis?.include_images ?? current.allowImages,
        authorizationNote: savedAnalysis?.authorization_note || current.authorizationNote,
      }));
    }).catch(() => {
      if (grantRequestSequence.current !== sequence) return;
      setAnalysisSubscription(null);
      setGrantMessage("OpenAI 持续分析状态读取失败；小策对话仍可正常使用。");
    });
  }, [open, thread?.id, thread?.customer_context?.conversation_id]);

  useEffect(() => {
    if (!open) return;
    const disconnect = connectPlatformEvents((event) => {
      if (event.type === "customer_context_updated") {
        if (thread?.customer_context?.conversation_id === Number(event.conversation_id)) void refreshThread(thread.id);
        return;
      }
      if (event.type === "customer_analysis_status") {
        const threadId = thread?.id;
        if (threadId && threadId === event.thread_id) {
          void localPlatformService.customerAnalysisSubscription(threadId).then(setAnalysisSubscription);
        }
        return;
      }
      if (event.type !== "global_agent_run" && event.type !== "global_agent_tool" && event.type !== "global_agent_step") return;
      const eventThread = typeof event.thread_id === "string" ? event.thread_id : thread?.id;
      const eventRun = typeof event.run_id === "string" ? event.run_id : "";
      if (!eventThread || (thread && eventThread !== thread.id)) return;
      if (eventRun) void refreshRunTrace(eventRun);
      if (event.type === "global_agent_run") void refreshThread(eventThread);
    });
    return disconnect;
  }, [open, thread?.id, thread?.customer_context?.conversation_id]);

  useEffect(() => {
    if (!open || !thread?.active_run) return;
    void refreshRunTrace(thread.active_run.id);
    const timer = window.setInterval(() => {
      void refreshRunTrace(thread.active_run!.id);
      void refreshThread(thread.id);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [open, thread?.active_run?.id, thread?.id]);

  useEffect(() => {
    if (!open) return;
    messagesEndRef.current?.scrollIntoView({ block: "end", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [open, thread?.messages.length, thread?.active_run?.status]);

  useEffect(() => {
    if (!open) return;
    document.body.classList.add("global-agent-open");
    return () => document.body.classList.remove("global-agent-open");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>("button:not([disabled]),select:not([disabled]),textarea:not([disabled]),input:not([disabled]),a[href],[tabindex]:not([tabindex='-1'])")).filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  const chooseThread = async (threadId: string) => {
    setError("");
    if (!threadId) {
      setThread(null);
      setSelectedContext("general_business");
      setRecheckFullContext(false);
      const preferred = profiles.find((profile) => profile.is_default) || profiles[0];
      setSelectedProfileId(preferred?.id || "");
      return;
    }
    setLoading(true);
    try {
      await refreshThread(threadId);
    } finally {
      setLoading(false);
    }
  };

  const changeContext = async (value: string) => {
    const previous = selectedContext;
    setSelectedContext(value);
    setRecheckFullContext(false);
    if (!thread) return;
    const conversationId = value.startsWith("customer:") ? Number(value.slice(9)) : null;
    setError("");
    try {
      const next = await localPlatformService.updateGlobalAgentThreadContext(thread.id, {
        request_id: requestId("agent-context-select"),
        expected_revision: thread.revision,
        context_scope: conversationId ? "customer_conversation" : "general_business",
        conversation_id: conversationId,
      });
      setThread(next);
      setBootstrap((current) => current ? { ...current, threads: [next, ...current.threads.filter((item) => item.id !== next.id)] } : current);
    } catch (reason) {
      setSelectedContext(previous);
      setError(reason instanceof Error ? reason.message : "客户上下文切换失败");
    }
  };

  const changeProfile = async (profileId: string) => {
    setSelectedProfileId(profileId);
    if (!thread) return;
    setError("");
    try {
      const next = await localPlatformService.updateGlobalAgentThreadProfile(thread.id, {
        request_id: requestId("agent-profile-select"),
        expected_revision: thread.revision,
        profile_id: profileId,
      });
      setThread(next);
    } catch (reason) {
      setSelectedProfileId(thread.profile_id || "");
      setError(reason instanceof Error ? reason.message : "模型切换失败");
    }
  };

  const enableAutomaticAnalysis = async () => {
    if (!thread?.customer_context) {
      setGrantMessage("请先把当前小策对话明确绑定到一个客户会话。");
      return;
    }
    if (analysisOptions.authorizationNote.trim().length < 2) {
      setGrantMessage("请填写持续分析用途。");
      return;
    }
    setGrantBusy(true);
    setGrantMessage("");
    try {
      const result = await localPlatformService.upsertCustomerAnalysisSubscription({
        request_id: requestId("customer-analysis-subscription"),
        thread_id: thread.id,
        expected_thread_revision: thread.revision,
        expected_subscription_revision: analysisSubscription?.revision || 0,
        provider_scope: "openai",
        model: "",
        include_images: analysisOptions.allowImages,
        debounce_seconds: 30,
        max_wait_seconds: 60,
        authorization_note: analysisOptions.authorizationNote.trim(),
        confirmed_automatic_analysis: true,
      });
      setAnalysisSubscription(result);
      setGrantMessage(result.configured
        ? "持续分析已启用；新消息入库后会自动合并分析并追加需求与计划版本。"
        : "持续分析授权已保存；请在本机环境配置 OpenAI API 后开始处理待分析消息。");
    } catch (reason) {
      setGrantMessage(reason instanceof Error ? reason.message : "OpenAI 持续分析启用失败");
    } finally {
      setGrantBusy(false);
    }
  };

  const pauseAutomaticAnalysis = async () => {
    if (!analysisSubscription) return;
    setGrantBusy(true);
    setGrantMessage("");
    try {
      const result = await localPlatformService.pauseCustomerAnalysisSubscription(analysisSubscription.id, {
        request_id: requestId("customer-analysis-pause"),
        expected_revision: analysisSubscription.revision,
        reason: "用户在小策中手动停止持续分析",
        confirmed: true,
      });
      setAnalysisSubscription(result);
      setGrantMessage("持续分析已停止；已入库消息和历史成果版本仍保留，停止后的在途结果不会写入成果。");
    } catch (reason) {
      setGrantMessage(reason instanceof Error ? reason.message : "持续分析停止失败");
    } finally {
      setGrantBusy(false);
    }
  };

  const retryAutomaticAnalysis = async () => {
    if (!analysisSubscription) return;
    setGrantBusy(true);
    setGrantMessage("");
    try {
      const result = await localPlatformService.retryCustomerAnalysisSubscription(analysisSubscription.id, {
        request_id: requestId("customer-analysis-retry"),
        expected_revision: analysisSubscription.revision,
        confirmed: true,
      });
      setAnalysisSubscription(result);
      setGrantMessage(result.configured ? "已重新进入分析队列。" : "重试已记录，但 OpenAI API 仍待配置。");
    } catch (reason) {
      setGrantMessage(reason instanceof Error ? reason.message : "持续分析重试失败");
    } finally {
      setGrantBusy(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const content = input.trim();
    if (!content || sending) return;
    if (!selectedProfile) {
      setError("请先选择一个模型配置");
      return;
    }
    if (!selectedProfile.configured) {
      setError(`${providerLabels[selectedProfile.provider]} 尚未配置，不会静默切换其他模型`);
      return;
    }
    setSending(true);
    setError("");
    try {
      let activeThread = thread;
      if (!activeThread) {
        activeThread = await localPlatformService.createGlobalAgentThread({
          request_id: requestId("agent-thread"),
          profile_id: selectedProfile.id,
          title: content.slice(0, 28),
        });
        if (selectedContext.startsWith("customer:")) {
          activeThread = await localPlatformService.updateGlobalAgentThreadContext(activeThread.id, {
            request_id: requestId("agent-context-select"),
            expected_revision: activeThread.revision,
            context_scope: "customer_conversation",
            conversation_id: Number(selectedContext.slice(9)),
          });
        }
        setThread(activeThread);
      }
      const run = await localPlatformService.sendGlobalAgentMessage(activeThread.id, {
        request_id: requestId("agent-message"),
        expected_revision: activeThread.revision,
        content,
        recheck_full_context: recheckFullContext,
      });
      setInput("");
      setRecheckFullContext(false);
      await Promise.all([
        refreshRunTrace(run.id),
        refreshThread(activeThread.id),
      ]);
    } catch (reason) {
      setSending(false);
      setError(reason instanceof Error ? reason.message : "发送失败");
    }
  };

  const cancel = async () => {
    const run = thread?.active_run;
    if (!run) return;
    try {
      await localPlatformService.cancelGlobalAgentRun(run.id, requestId("agent-cancel"));
      await Promise.all([refreshRunTrace(run.id), refreshThread(thread.id)]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "取消失败");
    }
  };

  const reindex = async () => {
    setKnowledgeBusy(true);
    setError("");
    try {
      const result = await localPlatformService.reindexGlobalAgentKnowledge(requestId("agent-rag"));
      setBootstrap((current) => current ? { ...current, knowledge: result } : current);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "知识库更新失败");
    } finally {
      setKnowledgeBusy(false);
    }
  };

  const reviseCustomerProposal = (message: GlobalAgentMessage) => {
    const proposal = message.answer?.customer_create_proposal;
    if (!proposal) return;
    setInput(`请修改刚才的客户资料提案：\n- 客户名称：${proposal.customer_name.value}\n- 需要调整：`);
    window.requestAnimationFrame(() => composerRef.current?.focus());
  };

  const confirmCustomerProposal = async (message: GlobalAgentMessage) => {
    const proposal = message.answer?.customer_create_proposal;
    if (!proposal || !thread) return;
    setCustomerProposalStates((current) => ({ ...current, [message.id]: { state: "busy" } }));
    setError("");
    try {
      const latest = await localPlatformService.customerIntakeCandidates();
      if (!latest.candidates.some((candidate) => candidate.conversation_id === proposal.conversation_id)) {
        setCustomerProposalStates((current) => ({ ...current, [message.id]: { state: "unavailable", message: "该会话已加入客户列表或关系已经变化；本次没有写入。" } }));
        return;
      }
      const result = await localPlatformService.confirmGlobalAgentCustomerCreate(thread.id, {
        assistant_message_id: message.id,
        request_id: requestId("agent-customer-confirm"),
        expected_revision: latest.revision,
        confirmed: true,
      });
      acceptMigratedLedger(result.revision);
      setCustomerProposalStates((current) => ({ ...current, [message.id]: { state: "created", message: `${proposal.customer_name.value} 已加入客户列表；未创建报价、项目或任务。` } }));
      await loadBootstrap();
      await refreshThread(thread.id);
    } catch (reason) {
      const messageText = reason instanceof Error ? reason.message : "客户资料确认失败，本次没有写入";
      setCustomerProposalStates((current) => ({ ...current, [message.id]: { state: "idle", message: messageText } }));
    }
  };

  const emptyCopy = useMemo(() => {
    if (!bootstrap?.knowledge.active_documents) return "知识库尚未建立索引，也可以先询问本地业务数据。";
    return `已连接 ${bootstrap.knowledge.active_documents} 篇已批准知识笔记，可结合本地经营数据回答。`;
  }, [bootstrap?.knowledge.active_documents]);
  const selectedContextOption = thread?.customer_context || (
    selectedContext.startsWith("customer:")
      ? contextOptions.find((item) => item.conversation_id === Number(selectedContext.slice(9))) || null
      : null
  );
  const contextHasSummary = Boolean(selectedContextOption?.summary_version);
  const contextNewMessageCount = selectedContextOption?.new_message_count || 0;
  const activeTrace = thread?.active_run ? runTraces[thread.active_run.id] || null : null;
  const analysisIsActive = Boolean(
    analysisSubscription
    && analysisSubscription.status === "active"
    && thread?.customer_context
    && analysisSubscription.conversation_id === thread.customer_context.conversation_id,
  );
  const analysisStatusText = analysisSubscription
    ? `${analysisStateLabel(analysisSubscription.analysis_state)}${analysisSubscription.latest_artifact_version ? ` · v${analysisSubscription.latest_artifact_version}` : ""}`
    : "未开启持续分析";

  if (!open) return null;
  return <>
    <button className="global-agent-backdrop" aria-label="关闭小策" onClick={onClose} tabIndex={-1} />
    <section ref={panelRef} className="global-agent-panel" style={style} role="dialog" aria-modal="true" aria-labelledby="global-agent-title" tabIndex={-1}>
      <span className="global-agent-sheet-handle" aria-hidden="true" />
      <header className="global-agent-heading">
        <img src="/assets/xunying/xiaoce-avatar.png" alt="" aria-hidden="true" />
        <span><small>AI 技术与商业合伙人</small><h2 id="global-agent-title">小策</h2></span>
        <div className="global-agent-heading-actions">
          <button type="button" title="手动更新已批准知识库" aria-label="手动更新已批准知识库" disabled={knowledgeBusy} onClick={() => void reindex()}><BookOpenText size={18} />{knowledgeBusy && <i className="agent-button-spinner" />}</button>
          <button type="button" title="模型与知识设置" aria-label="打开模型与知识设置" onClick={() => onNavigate("settings")}><GearSix size={18} /></button>
          <button type="button" aria-label="关闭小策" onClick={onClose}><X size={19} /></button>
        </div>
      </header>

      <div className="global-agent-controls">
        <label><span>对话</span><select aria-label="选择小策对话" value={thread?.id || ""} onChange={(event) => void chooseThread(event.target.value)}><option value="">新对话</option>{bootstrap?.threads.map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label>
        <label><span>上下文</span><select aria-label="选择小策上下文" value={selectedContext} disabled={Boolean(thread?.active_run) || analysisIsActive} title={analysisIsActive ? "请先停止当前客户的持续分析" : undefined} onChange={(event) => void changeContext(event.target.value)}><option value="general_business">经营全局</option>{contextOptions.map((option) => <option key={option.conversation_id} value={`customer:${option.conversation_id}`}>客户会话 · {option.customer_name}</option>)}</select></label>
        <label><span>模型</span><select aria-label="选择小策模型" value={selectedProfileId} disabled={Boolean(thread?.active_run)} onChange={(event) => void changeProfile(event.target.value)}>{profiles.map((profile) => <option value={profile.id} key={profile.id}>{profile.label}{profile.configured ? "" : " · 待配置"}</option>)}</select></label>
        <button type="button" className="agent-new-thread" onClick={() => void chooseThread("")}><Plus size={15} />新对话</button>
      </div>

      {selectedContextOption && <section className={`global-agent-context-card ${grantPanelOpen ? "has-openai-grant" : ""}`} aria-label="已绑定客户会话上下文">
        <header><span><Database size={18} weight="duotone" /></span><div><small>已明确绑定 · 只读</small><h3>{selectedContextOption.customer_name} · {selectedContextOption.channel === "xianyu" ? "闲鱼" : selectedContextOption.channel}</h3></div><em>图片按授权</em></header>
        <div className="global-agent-context-meta">
          <span><small>关联商品</small><b>{selectedContextOption.item_title || "未关联商品"}</b></span>
          <span><small>文字消息</small><b>{selectedContextOption.text_message_count} 条 · 首次最多 200</b></span>
          <span><small>总结版本</small><b>{contextHasSummary ? `v${selectedContextOption.summary_version} · 可追溯` : "首次提问后建立"}</b></span>
          <span><small>覆盖状态</small><b>{selectedContextOption.summarized_through_message_id ? `至消息 #${selectedContextOption.summarized_through_message_id}` : "尚未总结"}</b></span>
        </div>
        <div className={`global-agent-context-update ${analysisSubscription?.analysis_state === "pending" || analysisSubscription?.analysis_state === "analyzing" ? "is-updated" : ""}`}><i /><span><b>{analysisIsActive ? analysisStatusText : !contextHasSummary ? "首次总结待建立" : selectedContextOption.context_updated ? "上下文已更新" : "上下文已就绪"}</b><small>{analysisIsActive ? `新消息先写入 SQLite，再于 30 秒静默窗口或 60 秒最长等待后自动增量分析；当前待处理 ${analysisSubscription?.pending_message_count || 0} 条` : !contextHasSummary ? `小策问答首次读取最近 ${Math.min(200, selectedContextOption.text_message_count)} 条文字；持续分析需单独授权` : contextNewMessageCount ? `新增 ${contextNewMessageCount} 条文字消息；小策问答会在下次提问时更新总结` : "小策问答复用最新总结；持续分析未开启时不会自动调用模型"}</small></span><button type="button" className={recheckFullContext ? "is-selected" : ""} onClick={() => setRecheckFullContext((value) => !value)}>{recheckFullContext ? "已选完整核验" : "下次核验 200 条"}</button></div>
        <div className="global-agent-context-access"><span><b>OpenAI 持续后台分析</b><small>{analysisIsActive ? analysisStatusText : "未授权；不会因新消息自动调用模型"}</small></span><button type="button" aria-expanded={grantPanelOpen} disabled={!thread?.customer_context || grantBusy} onClick={() => setGrantPanelOpen((value) => !value)}>{grantPanelOpen ? "收起" : analysisIsActive ? "查看分析" : "设置分析"}</button></div>
        {grantPanelOpen && <section className="global-agent-openai-grant" aria-label="OpenAI 客户上下文授权">
          <header><span><b>持续分析授权</b><small>仅在新消息入库后增量调用 OpenAI；DeepSeek 不可授权</small></span><em className={analysisIsActive ? "is-active" : ""}>{analysisIsActive ? "持续分析中" : "未授权"}</em></header>
          <fieldset><legend>自动分析允许的内容</legend><label><input type="checkbox" checked readOnly /><span><b>原始文字</b><small>持续分析的必需输入</small></span></label><label><input type="checkbox" checked={analysisOptions.allowImages} onChange={(event) => setAnalysisOptions((current) => ({ ...current, allowImages: event.target.checked }))} /><span><b>增量关联原图</b><small>仅本批消息关联且完整性核验通过的入站原图</small></span></label></fieldset>
          <label className="global-agent-grant-note"><span>持续分析用途</span><textarea rows={2} maxLength={2000} value={analysisOptions.authorizationNote} onChange={(event) => setAnalysisOptions((current) => ({ ...current, authorizationNote: event.target.value }))} /></label>
          <div className="global-agent-analysis-control"><span><b>持续后台分析</b><small>{analysisSubscription ? `${analysisStatusText} · 待处理 ${analysisSubscription.pending_message_count} 条 · 最近水位线 ${analysisSubscription.last_analyzed_message_id ? `#${analysisSubscription.last_analyzed_message_id}` : "未建立"}` : "仅明确绑定的客户会话在授权后自动分析新消息；不自动回复"}</small><small>{analysisOptions.allowImages ? "分析范围：原始文字 + 本批获准归档原图" : "分析范围：仅原始文字"}</small></span>{analysisSubscription?.analysis_state === "failed" && <button type="button" disabled={grantBusy} onClick={() => void retryAutomaticAnalysis()}>重试</button>}{analysisIsActive ? <button type="button" disabled={grantBusy} onClick={() => void pauseAutomaticAnalysis()}>停止</button> : <button className="primary" type="button" disabled={grantBusy} onClick={() => void enableAutomaticAnalysis()}>开启持续分析</button>}</div>
          <aside><ShieldCheck size={15} /><span>ChatGPT 网页读取不经过小策，也不会因为创建授权而调用模型。请到“设置中心 → AI与回复”直接选择客户会话并创建短时读取授权。</span></aside>
          {grantMessage && <p className="global-agent-grant-message" role="status">{grantMessage}</p>}
          <footer><span>持续分析与短时读取互相独立</span><button type="button" onClick={() => onNavigate("settings")}>打开独立读取设置</button></footer>
        </section>}
      </section>}

      <main className="global-agent-conversation" aria-live="polite">
        {loading && !thread ? <div className="global-agent-loading"><span className="agent-button-spinner" /><p>正在读取本地对话与配置…</p></div> : thread?.messages.length ? thread.messages.map((message) => message.role === "user"
          ? <article className="agent-user-message" key={message.id}><p>{message.content}</p></article>
          : <AssistantMessage key={message.id} message={message} proposalStatus={customerProposalStates[message.id] || { state: "idle" }} trace={message.run_id ? runTraces[message.run_id] || null : null} traceExpanded={Boolean(message.run_id && expandedTraceRuns.has(message.run_id))} traceStepsExpanded={Boolean(message.run_id && expandedStepRuns.has(message.run_id))} traceLoading={Boolean(message.run_id && traceLoadingRuns.has(message.run_id))} onToggleTrace={() => message.run_id && toggleRunTrace(message.run_id)} onToggleTraceSteps={() => message.run_id && toggleRunTraceSteps(message.run_id)} onConfirmProposal={(value) => void confirmCustomerProposal(value)} onReviseProposal={reviseCustomerProposal} onNavigate={onNavigate} />)
          : <div className="global-agent-empty">
            <span><Brain size={31} weight="duotone" /></span>
            <h3>从一个真实问题开始</h3>
            <p>{emptyCopy}</p>
            <div><button type="button" onClick={() => setInput("结合当前经营数据，我下一步最应该做什么？")}>下一步优先级</button><button type="button" onClick={() => setInput("查询项目状态并指出最需要核对的风险")}>项目风险</button><button type="button" onClick={() => setInput("分析商品数据，告诉我哪些结论仍缺证据")}>商品证据</button></div>
          </div>}
        {thread?.active_run && (activeTrace
          ? <AgentLiveProgress trace={activeTrace} onCancel={() => void cancel()} />
          : <div className="global-agent-running" role="status"><span className="agent-button-spinner" /><p><b>{statusLabel(thread.active_run.status)}</b><small>正在读取已授权证据并建立可审计执行轨迹</small></p><button type="button" onClick={() => void cancel()}><StopCircle size={16} />取消</button></div>)}
        {!thread?.active_run && thread?.latest_run && ["failed", "cancelled", "interrupted"].includes(thread.latest_run.status) && !thread.messages.some((message) => message.role === "assistant" && message.run_id === thread.latest_run?.id) && <>
          <div className="global-agent-run-gap"><WarningCircle size={16} /><span><b>{statusLabel(thread.latest_run.status)}</b>{thread.latest_run.error_message || "上一次回答未形成结果，可重新发送问题。"}</span><button className="agent-run-trace-toggle" type="button" onClick={() => toggleRunTrace(thread.latest_run!.id)}>查看轨迹</button></div>
          {expandedTraceRuns.has(thread.latest_run.id) && (runTraces[thread.latest_run.id]
            ? <AgentExecutionTrace trace={runTraces[thread.latest_run.id]} showSteps={expandedStepRuns.has(thread.latest_run.id)} onToggleSteps={() => toggleRunTraceSteps(thread.latest_run!.id)} />
            : <div className="agent-trace-loading"><span className="agent-button-spinner" />正在读取已保存轨迹…</div>)}
        </>}
        <div ref={messagesEndRef} />
      </main>

      {error && <div className="global-agent-error" role="alert"><WarningCircle size={17} /><span>{error}</span><button type="button" onClick={() => setError("")}><X size={14} /></button></div>}

      <form className="global-agent-composer" onSubmit={submit}>
        <textarea ref={composerRef} aria-label="询问小策" rows={2} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }} placeholder={selectedContextOption ? "围绕这个客户的需求、约束或下一步提问…" : "询问客户、商品、项目、财务，或让小策结合知识库给出下一步…"} />
        <button type="submit" aria-label="发送给小策" disabled={!input.trim() || sending || Boolean(thread?.active_run)}>{sending ? <span className="agent-button-spinner" /> : <PaperPlaneTilt size={19} weight="fill" />}</button>
        <footer><span><ShieldCheck size={13} />分析可读 · 客户写入需人工确认 · {selectedContextOption ? "图片完全排除 · 不自动回复" : "不发送消息"}</span><small>{selectedProfile ? `${providerLabels[selectedProfile.provider]} · ${selectedProfile.model}` : "请选择模型"}</small></footer>
      </form>
    </section>
  </>;
}
