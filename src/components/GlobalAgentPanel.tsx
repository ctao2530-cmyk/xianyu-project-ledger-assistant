import {
  ArrowRight,
  BookOpenText,
  Brain,
  CaretDown,
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
  type GlobalAgentCustomerCreateProposal,
  type GlobalAgentCustomerContextOption,
  type GlobalAgentMessage,
  type GlobalAgentProfile,
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

function AssistantMessage({ message, proposalStatus, onConfirmProposal, onReviseProposal, onNavigate }: {
  message: GlobalAgentMessage;
  proposalStatus: CustomerProposalStatus;
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
  return <article className="agent-answer-card">
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
    {answer.customer_create_proposal && <CustomerCreateProposalCard proposal={answer.customer_create_proposal} status={proposalStatus} evidenceLabel={evidenceLabel} onRevise={() => onReviseProposal(message)} onConfirm={() => onConfirmProposal(message)} />}
    {answer.limitations.length > 0 && <aside className="agent-limitations"><WarningCircle size={16} /><span><b>限制与反证</b>{answer.limitations.join("；")}</span></aside>}
    {(message.citations.length > 0 || message.tool_references.length > 0) && <details className="agent-evidence-details">
      <summary><LinkSimple size={15} />查看证据与数据来源 <CaretDown size={14} /></summary>
      <div>
        {message.citations.map((citation) => <article key={citation.id}>
          <i><BookOpenText size={16} /></i><span><b>{citation.title}</b><small>{citation.relative_path} · {citation.heading} · {citation.maturity}</small><p>{citation.snippet}</p></span>
        </article>)}
        {message.tool_references.map((tool) => <article key={tool.id}>
          <i><Database size={16} /></i><span><b>{tool.label}</b><small>本地只读工具 · {tool.status === "completed" ? "已读取" : "读取失败"} · {tool.duration_ms}ms</small></span>
        </article>)}
      </div>
    </details>}
  </article>;
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
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const [customerProposalStates, setCustomerProposalStates] = useState<Record<string, CustomerProposalStatus>>({});

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

  useEffect(() => {
    if (!open) return;
    void loadBootstrap();
    const frame = window.requestAnimationFrame(() => panelRef.current?.focus({ preventScroll: true }));
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const disconnect = connectPlatformEvents((event) => {
      if (event.type === "customer_context_updated") {
        if (thread?.customer_context?.conversation_id === Number(event.conversation_id)) void refreshThread(thread.id);
        return;
      }
      if (event.type !== "global_agent_run" && event.type !== "global_agent_tool") return;
      const eventThread = typeof event.thread_id === "string" ? event.thread_id : thread?.id;
      if (eventThread && (!thread || eventThread === thread.id)) void refreshThread(eventThread);
    });
    return disconnect;
  }, [open, thread?.id, thread?.customer_context?.conversation_id]);

  useEffect(() => {
    if (!open || !thread?.active_run) return;
    const timer = window.setInterval(() => void refreshThread(thread.id), 1800);
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
      await localPlatformService.sendGlobalAgentMessage(activeThread.id, {
        request_id: requestId("agent-message"),
        expected_revision: activeThread.revision,
        content,
        recheck_full_context: recheckFullContext,
      });
      setInput("");
      setRecheckFullContext(false);
      await refreshThread(activeThread.id);
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
      await refreshThread(thread.id);
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
        <label><span>上下文</span><select aria-label="选择小策上下文" value={selectedContext} disabled={Boolean(thread?.active_run)} onChange={(event) => void changeContext(event.target.value)}><option value="general_business">经营全局</option>{contextOptions.map((option) => <option key={option.conversation_id} value={`customer:${option.conversation_id}`}>客户会话 · {option.customer_name}</option>)}</select></label>
        <label><span>模型</span><select aria-label="选择小策模型" value={selectedProfileId} disabled={Boolean(thread?.active_run)} onChange={(event) => void changeProfile(event.target.value)}>{profiles.map((profile) => <option value={profile.id} key={profile.id}>{profile.label}{profile.configured ? "" : " · 待配置"}</option>)}</select></label>
        <button type="button" className="agent-new-thread" onClick={() => void chooseThread("")}><Plus size={15} />新对话</button>
      </div>

      {selectedContextOption && <section className="global-agent-context-card" aria-label="已绑定客户会话上下文">
        <header><span><Database size={18} weight="duotone" /></span><div><small>已明确绑定 · 只读</small><h3>{selectedContextOption.customer_name} · {selectedContextOption.channel === "xianyu" ? "闲鱼" : selectedContextOption.channel}</h3></div><em>图片排除</em></header>
        <div className="global-agent-context-meta">
          <span><small>关联商品</small><b>{selectedContextOption.item_title || "未关联商品"}</b></span>
          <span><small>文字消息</small><b>{selectedContextOption.text_message_count} 条 · 首次最多 200</b></span>
          <span><small>总结版本</small><b>{contextHasSummary ? `v${selectedContextOption.summary_version} · 可追溯` : "首次提问后建立"}</b></span>
          <span><small>覆盖状态</small><b>{selectedContextOption.summarized_through_message_id ? `至消息 #${selectedContextOption.summarized_through_message_id}` : "尚未总结"}</b></span>
        </div>
        <div className={`global-agent-context-update ${selectedContextOption.context_updated ? "is-updated" : ""}`}><i /><span><b>{!contextHasSummary ? "首次总结待建立" : selectedContextOption.context_updated ? "上下文已更新" : "上下文已就绪"}</b><small>{!contextHasSummary ? `首次提问读取最近 ${Math.min(200, selectedContextOption.text_message_count)} 条文字并建立总结；选择客户不会自动调用模型` : contextNewMessageCount ? `新增 ${contextNewMessageCount} 条文字消息；下次提问时更新总结，不自动调用模型` : "没有新增文字；下次提问只发送最新总结，不重复发送已经总结的原文"}</small></span><button type="button" className={recheckFullContext ? "is-selected" : ""} onClick={() => setRecheckFullContext((value) => !value)}>{recheckFullContext ? "已选完整核验" : "下次核验 200 条"}</button></div>
      </section>}

      <main className="global-agent-conversation" aria-live="polite">
        {loading && !thread ? <div className="global-agent-loading"><span className="agent-button-spinner" /><p>正在读取本地对话与配置…</p></div> : thread?.messages.length ? thread.messages.map((message) => message.role === "user"
          ? <article className="agent-user-message" key={message.id}><p>{message.content}</p></article>
          : <AssistantMessage key={message.id} message={message} proposalStatus={customerProposalStates[message.id] || { state: "idle" }} onConfirmProposal={(value) => void confirmCustomerProposal(value)} onReviseProposal={reviseCustomerProposal} onNavigate={onNavigate} />)
          : <div className="global-agent-empty">
            <span><Brain size={31} weight="duotone" /></span>
            <h3>从一个真实问题开始</h3>
            <p>{emptyCopy}</p>
            <div><button type="button" onClick={() => setInput("结合当前经营数据，我下一步最应该做什么？")}>下一步优先级</button><button type="button" onClick={() => setInput("查询项目状态并指出最需要核对的风险")}>项目风险</button><button type="button" onClick={() => setInput("分析商品数据，告诉我哪些结论仍缺证据")}>商品证据</button></div>
          </div>}
        {thread?.active_run && <div className="global-agent-running" role="status"><span className="agent-button-spinner" /><p><b>{statusLabel(thread.active_run.status)}</b><small>正在读取已授权证据并生成结构化判断</small></p><button type="button" onClick={() => void cancel()}><StopCircle size={16} />取消</button></div>}
        {!thread?.active_run && thread?.latest_run && ["failed", "cancelled", "interrupted"].includes(thread.latest_run.status) && !thread.messages.some((message) => message.role === "assistant" && message.run_id === thread.latest_run?.id) && <div className="global-agent-run-gap"><WarningCircle size={16} /><span><b>{statusLabel(thread.latest_run.status)}</b>{thread.latest_run.error_message || "上一次回答未形成结果，可重新发送问题。"}</span></div>}
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
