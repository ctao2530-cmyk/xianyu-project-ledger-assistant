import {
  ArrowClockwise,
  ArrowRight,
  Brain,
  ChatCircleDots,
  Check,
  CheckCircle,
  Clock,
  Copy,
  DownloadSimple,
  FileText,
  Funnel,
  PaperPlaneTilt,
  ShieldCheck,
  Sparkle,
  Storefront,
  UploadSimple,
  UserCircle,
  WarningCircle,
  WechatLogo,
  X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import {
  connectPlatformEvents,
  localPlatformService,
  type ConversationDetail,
  type ConversationSummary,
  type AIProviderStatus,
  type DraftProvider,
  type LeadView,
  type PlatformStatus,
  type QuoteView,
  type RequirementWorkspace,
  type RequirementExport,
  type RequirementImportPreview,
  type RequirementCaseSummary,
  type SalesAnalysis,
  type SalesMemory,
} from "../data/localPlatformService";
import type { Customer } from "../types";
import "./customer-messages.css";


type ChannelFilter = "all" | "xianyu" | "wechat";
type WorkbenchTab = "reply" | "requirements" | "conversion";

function readConversationRouteId() {
  try {
    const [page, kind, rawId] = decodeURIComponent(window.location.hash.replace(/^#/, "")).split("/");
    if (page !== "客户消息" || kind !== "conversation") return null;
    const value = Number(rawId);
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

function conversationRouteHash(conversationId: number) {
  return `#${encodeURIComponent(`客户消息/conversation/${conversationId}`)}`;
}

const dateTime = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
});

function channelLabel(channel: string) {
  return channel === "wechat" ? "微信" : "闲鱼";
}

function ChannelIcon({ channel }: { channel: string }) {
  return channel === "wechat" ? <WechatLogo size={16} weight="fill" /> : <Storefront size={16} weight="fill" />;
}

function EmptyMessages({ offline }: { offline: boolean }) {
  return <section className="messages-empty">
    <span><ChatCircleDots size={34} weight="duotone" /></span>
    <h2>{offline ? "需要连接本机经营服务" : "暂时没有客户会话"}</h2>
    <p>{offline ? "客户消息、Codex CLI 和渠道监听只在本机统一服务运行时可用；静态站点不会读取 Cookie 或显示发送按钮。" : "闲鱼或微信收到新咨询后，会话会自动出现在这里。"}</p>
  </section>;
}

function SalesInsightCard({
  analysis,
  history,
  memory,
  lead,
  working,
  showHistory,
  onAnalyze,
  onConfirm,
  onToggleHistory,
  onCreateProject,
  onCopyReply,
}: {
  analysis: SalesAnalysis | null;
  history: SalesAnalysis[];
  memory: SalesMemory | null;
  lead: LeadView | null;
  working: string;
  showHistory: boolean;
  onAnalyze: (refresh?: boolean, provider?: DraftProvider) => void;
  onConfirm: () => void;
  onToggleHistory: () => void;
  onCreateProject: () => void;
  onCopyReply: (reply: string) => void;
}) {
  const result = analysis?.result;
  const providerLabel = analysis?.provider === "deepseek" ? "DeepSeek 快速分析" : "Codex 销售分析";
  const completedHistory = history.filter((item) => item.status === "completed" && item.result);

  return <article className={`sales-agent-card status-${analysis?.status || "empty"}`}>
    <header className="sales-agent-heading">
      <span><Sparkle size={17} weight="fill" /><b>AI 销售助手</b><small>独立 Sales Agent</small></span>
      <em>{analysis ? providerLabel : "等待分析"}</em>
    </header>

    {!analysis && <div className="sales-agent-state">
      <Brain size={28} weight="duotone" />
      <div><strong>把回复升级为销售决策</strong><p>读取客户历史、相似项目和真实报价后，给出客户价值、策略与下一步。</p></div>
      <button type="button" disabled={Boolean(working)} onClick={() => onAnalyze(false)}><Sparkle size={15} />生成客户分析</button>
    </div>}

    {analysis?.status === "running" && <div className="sales-agent-state compact" role="status">
      <ArrowClockwise size={22} className="spin" />
      <div><strong>正在分析客户意图</strong><p>只读调用业务工具，不会写入客户、发送消息或确认报价。</p></div>
    </div>}

    {analysis?.status === "failed" && <div className="sales-agent-state compact failed" role="alert">
      <WarningCircle size={22} weight="fill" />
      <div><strong>销售分析未完成</strong><p>{analysis.error_message || "模型暂时不可用，请明确重试。"}</p></div>
      <div className="sales-error-actions"><button type="button" disabled={Boolean(working)} onClick={() => onAnalyze(true, analysis.provider === "codex_cli" ? "codex_cli" : "deepseek")}><ArrowClockwise size={14} />重试当前模型</button>{analysis.provider === "deepseek" && <button type="button" disabled={Boolean(working)} onClick={() => onAnalyze(true, "codex_cli")}><Brain size={14} />改用 Codex</button>}</div>
    </div>}

    {analysis?.status === "completed" && result && <>
      <div className="sales-signal-grid">
        <span><small>客户类型</small><b>{result.customer_type}</b></span>
        <span><small>当前阶段</small><b>{result.stage}</b></span>
        <span className="probability"><small>购买意愿</small><b>{result.purchase_probability}%</b><i><em style={{ width: `${result.purchase_probability}%` }} /></i></span>
      </div>

      <div className="sales-need-line"><TargetIcon /><span><small>需求判断</small><b>{result.need_type}</b><p>{result.customer_profile}</p></span></div>

      <div className="sales-strategy-block">
        <span><small>建议策略</small><p>{result.sales_strategy}</p></span>
        <span><small>下一步动作</small><p>{result.next_action}</p></span>
      </div>

      <div className="sales-recommended-reply">
        <header><span>推荐回复</span><small>复制后仍需人工审核</small></header>
        <p>{result.recommended_reply}</p>
        {result.risk_flags.length > 0 && <div><WarningCircle size={14} weight="fill" />{result.risk_flags.join(" · ")}</div>}
      </div>

      <div className="sales-agent-actions">
        <button type="button" className="primary" onClick={() => onCopyReply(result.recommended_reply)}><Copy size={14} />复制回复</button>
        <button type="button" className={analysis.confirmed_at ? "confirmed" : ""} disabled={Boolean(working) || Boolean(analysis.confirmed_at)} onClick={onConfirm}><UserCircle size={14} />{analysis.confirmed_at ? "客户已保存" : "保存客户"}</button>
        <button type="button" disabled={!lead} title={lead ? "进入报价与项目转化" : "请先人工确认保存客户"} onClick={onCreateProject}><Funnel size={14} />创建项目</button>
        <button type="button" onClick={onToggleHistory}><Clock size={14} />{showHistory ? "收起历史" : "查看历史"}</button>
      </div>

      <footer className="sales-context-proof">
        <span>已读取 {analysis.context_summary.message_count} 条对话</span>
        <span>{analysis.context_summary.project_count} 个历史项目</span>
        <span>{analysis.context_summary.quote_count} 份历史报价</span>
        {analysis.context_summary.confirmed_revenue > 0 && <span>历史到账 {money.format(analysis.context_summary.confirmed_revenue)}</span>}
      </footer>

      {showHistory && <section className="sales-history-panel" aria-label="销售分析历史">
        <header><span>客户销售记忆</span><small>{memory?.latest_version ? `记忆 V${memory.latest_version}` : "尚未确认保存"}</small></header>
        {memory?.memories[0] && <article className="sales-memory-summary"><b>{memory.memories[0].customer_background}</b><p>{memory.memories[0].communication_summary}</p><small>跟进状态：{memory.memories[0].follow_up_status}</small></article>}
        {!memory?.memories.length && <p className="sales-history-empty">点击“保存客户”后，本次客户背景、需求和跟进动作会写入可复用销售记忆。</p>}
        <div className="sales-history-list">{completedHistory.slice(0, 5).map((item) => <article key={item.id}><span><b>{item.result?.need_type}</b><small>{dateTime.format(new Date(item.created_at))} · {item.result?.stage}</small></span><strong>{item.result?.purchase_probability}%</strong><p>{item.result?.next_action}</p></article>)}</div>
      </section>}

      <button type="button" className="sales-refresh-link" disabled={Boolean(working)} onClick={() => onAnalyze(true, analysis.provider === "codex_cli" ? "codex_cli" : "deepseek")}><ArrowClockwise size={13} />基于最新对话重新分析</button>
    </>}
  </article>;
}

function TargetIcon() {
  return <span className="sales-target-icon"><Funnel size={17} weight="duotone" /></span>;
}

export function CustomerMessagesPage({ customers, onProjectCreated, onOpenRequirement }: { customers: Customer[]; onProjectCreated?: (projectId: string) => void; onOpenRequirement?: (customerId: string, caseId: string) => void }) {
  const [filter, setFilter] = useState<ChannelFilter>("all");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(() => readConversationRouteId());
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [requirements, setRequirements] = useState<RequirementWorkspace | null>(null);
  const [lead, setLead] = useState<LeadView | null>(null);
  const [salesAnalysis, setSalesAnalysis] = useState<SalesAnalysis | null>(null);
  const [salesHistory, setSalesHistory] = useState<SalesAnalysis[]>([]);
  const [salesMemory, setSalesMemory] = useState<SalesMemory | null>(null);
  const [showSalesHistory, setShowSalesHistory] = useState(false);
  const [quotes, setQuotes] = useState<QuoteView[]>([]);
  const [status, setStatus] = useState<PlatformStatus | null>(null);
  const [providers, setProviders] = useState<AIProviderStatus[]>([]);
  const [replyProvider, setReplyProvider] = useState<DraftProvider>("deepseek");
  const [tab, setTab] = useState<WorkbenchTab>("reply");
  const [draftIndex, setDraftIndex] = useState(0);
  const [draftText, setDraftText] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState("");
  const [offline, setOffline] = useState(false);
  const [notice, setNotice] = useState("");
  const [exportBundle, setExportBundle] = useState<RequirementExport | null>(null);
  const [jsonInput, setJsonInput] = useState("");
  const [importPreview, setImportPreview] = useState<RequirementImportPreview | null>(null);
  const [selectedCustomerId, setSelectedCustomerId] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [caseTitle, setCaseTitle] = useState("");
  const [customerCases, setCustomerCases] = useState<RequirementCaseSummary[]>([]);

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 2600);
  };

  const loadList = async (preferredId?: number | null) => {
    try {
      const [rows, health, providerRows] = await Promise.all([
        localPlatformService.conversations(filter),
        localPlatformService.status(),
        localPlatformService.providers().catch(() => []),
      ]);
      setConversations(rows);
      setStatus(health);
      setProviders(providerRows);
      const deepseek = providerRows.find((item) => item.provider === "deepseek");
      setReplyProvider((current) => current === "deepseek" && !deepseek?.configured ? "codex_cli" : current);
      setOffline(false);
      const nextId = preferredId && rows.some((row) => row.id === preferredId)
        ? preferredId
        : rows[0]?.id ?? null;
      setSelectedId(nextId);
      if (preferredId && nextId !== preferredId) {
        const nextHash = nextId === null ? `#${encodeURIComponent("客户消息")}` : conversationRouteHash(nextId);
        window.history.replaceState(window.history.state, "", nextHash);
      }
    } catch {
      setOffline(true);
      setConversations([]);
      setSelectedId(null);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  };

  const loadConversation = async (conversationId: number) => {
    try {
      const [nextDetail, requirementResult, nextLead, nextSales, nextMemory, nextSalesHistory] = await Promise.all([
        localPlatformService.conversation(conversationId),
        localPlatformService.requirements(conversationId)
          .then((value) => ({ value, failed: false as const }))
          .catch(() => ({ value: null, failed: true as const })),
        localPlatformService.getLead(conversationId).catch(() => null),
        localPlatformService.salesAnalysis(conversationId).catch(() => null),
        localPlatformService.salesMemory(conversationId).catch(() => null),
        localPlatformService.salesHistory(conversationId).catch(() => []),
      ]);
      setDetail(nextDetail);
      setRequirements(requirementResult.value);
      setDraftIndex(0);
      setDraftText(nextDetail.drafts[0]?.content || "");
      setLead(nextLead);
      setSelectedCustomerId(nextDetail.linked_customer_id || nextLead?.customer_id || "");
      setSelectedCaseId("");
      setSalesAnalysis(nextSales);
      setSalesMemory(nextMemory);
      setSalesHistory(nextSalesHistory);
      setShowSalesHistory(false);
      setQuotes(nextLead ? await localPlatformService.quotes(nextLead.id).catch(() => []) : []);
      setExportBundle(null);
      setJsonInput("");
      setImportPreview(null);
      setCaseTitle(nextDetail.item?.title || `${nextDetail.customer_name}需求`);
      setConversations((rows) => rows.map((row) => row.id === conversationId ? { ...row, unread_count: 0 } : row));
      if (requirementResult.failed) showNotice("会话已载入，但需求版本暂时无法读取");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "会话加载失败");
    }
  };

  useEffect(() => { void loadList(selectedId); }, [filter]);
  useEffect(() => {
    const syncRoute = () => {
      const requestedId = readConversationRouteId();
      if (requestedId !== null) setSelectedId(requestedId);
    };
    window.addEventListener("hashchange", syncRoute);
    window.addEventListener("popstate", syncRoute);
    window.addEventListener("xianyu:route-focus", syncRoute);
    return () => {
      window.removeEventListener("hashchange", syncRoute);
      window.removeEventListener("popstate", syncRoute);
      window.removeEventListener("xianyu:route-focus", syncRoute);
    };
  }, []);
  useEffect(() => {
    if (selectedId !== null) void loadConversation(selectedId);
  }, [selectedId]);
  useEffect(() => connectPlatformEvents((event) => {
    if (["new_reply", "requirement_completed", "requirement_imported", "customer_requirement_updated", "lead_updated", "quote_completed", "project_created", "sales_analysis_completed", "sales_analysis_failed", "sales_analysis_confirmed", "customer_memory_updated"].includes(String(event.type))) {
      void loadList(selectedId);
      if (selectedId !== null) void loadConversation(selectedId);
    }
  }), [filter, selectedId]);

  useEffect(() => {
    if (!selectedCustomerId) { setCustomerCases([]); return; }
    let active = true;
    void localPlatformService.customerRequirements(selectedCustomerId)
      .then((rows) => { if (active) setCustomerCases(rows); })
      .catch(() => { if (active) setCustomerCases([]); });
    return () => { active = false; };
  }, [selectedCustomerId]);
  useEffect(() => {
    if (selectedCustomerId && !customers.some((item) => item.id === selectedCustomerId)) {
      setSelectedCustomerId("");
    }
  }, [customers, selectedCustomerId]);

  const selectedDraft = detail?.drafts[draftIndex];
  const compatibleCustomerCases = useMemo(() => customerCases.filter((item) => (
    !item.item_external_id || item.item_external_id === detail?.item?.external_id
  )), [customerCases, detail?.item?.external_id]);
  const selectedCustomer = customers.find((item) => item.id === selectedCustomerId) || null;
  const riskFlags = useMemo(() => Array.from(new Set([
    ...(selectedDraft?.risk_flags || []),
    ...(detail?.ai_task?.risk_reasons || []),
  ])), [detail?.ai_task?.risk_reasons, selectedDraft?.risk_flags]);
  const refreshCurrent = async () => {
    await loadList(selectedId);
    if (selectedId !== null) await loadConversation(selectedId);
  };

  const doWork = async (label: string, action: () => Promise<unknown>, success: string) => {
    setWorking(label);
    try {
      await action();
      showNotice(success);
      await refreshCurrent();
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "操作失败");
    } finally {
      setWorking("");
    }
  };

  const ensureLead = async () => {
    if (!lead) throw new Error("请先分析并人工确认保存线索");
    return lead;
  };

  const generateDrafts = () => {
    if (!detail?.pending_message_id) return;
    void doWork(
      "regenerate",
      () => localPlatformService.regenerateDrafts(detail.pending_message_id!, replyProvider),
      `已提交${replyProvider === "deepseek" ? " DeepSeek 快速" : " Codex 深度"}草稿`,
    );
  };

  const openConversationExport = () => {
    setTab("requirements");
    if (window.matchMedia("(max-width: 820px)").matches) {
      window.setTimeout(() => {
        document.getElementById("conversation-export-panel")?.scrollIntoView({
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
          block: "start",
        });
      }, 0);
    }
  };

  const loadRequirementExport = async () => {
    if (!detail) return null;
    const bundle = await localPlatformService.requirementExport(detail.id);
    setExportBundle(bundle);
    return bundle;
  };

  const copyRequirementAnalysisDocument = async () => {
    setWorking("export");
    try {
      const bundle = exportBundle || await loadRequirementExport();
      if (!bundle) return;
      await navigator.clipboard.writeText(bundle.analysis_document);
      showNotice(`需求分析材料已复制，包含固定提示词并隐藏 ${bundle.redaction_count} 处隐私信息`);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "需求分析材料复制失败");
    } finally {
      setWorking("");
    }
  };

  const downloadRequirementAnalysisDocument = async () => {
    setWorking("download");
    try {
      const bundle = exportBundle || await loadRequirementExport();
      if (!bundle) return;
      const file = new Blob([`\ufeff${bundle.analysis_document}`], { type: "text/markdown;charset=utf-8" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(file);
      link.download = bundle.filename;
      link.click();
      URL.revokeObjectURL(link.href);
      showNotice("需求分析文档已下载，可直接上传给 GPT");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "需求分析文档下载失败");
    } finally {
      setWorking("");
    }
  };

  const loadRequirementJsonFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 2_000_000) {
      showNotice("JSON 文件不能超过 2MB");
      return;
    }
    try {
      const content = await file.text();
      if (!content.trim()) throw new Error("所选文件没有内容");
      setJsonInput(content.trim());
      setImportPreview(null);
      showNotice("已读取 GPT 分析结果，请校验后再保存");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "GPT JSON 文件读取失败");
    }
  };

  const previewRequirement = async () => {
    if (!detail || !selectedCustomerId || !jsonInput.trim()) {
      showNotice("请选择客户并粘贴 GPT 返回的 JSON");
      return;
    }
    if (detail.channel === "xianyu" && !detail.item) {
      showNotice("当前闲鱼会话没有关联商品，请先同步会话商品后再保存需求");
      return;
    }
    setWorking("preview");
    try {
      const preview = await localPlatformService.previewRequirementImport({
        conversation_id: detail.id,
        customer_id: selectedCustomerId,
        case_id: selectedCaseId || null,
        case_title: selectedCaseId ? null : caseTitle.trim() || `${detail.customer_name}需求`,
        source_label: "GPT 人工导入",
        document: jsonInput,
      });
      setImportPreview(preview);
      showNotice("JSON 校验通过，请确认预览后保存");
    } catch (error) {
      setImportPreview(null);
      showNotice(error instanceof Error ? error.message : "需求 JSON 校验失败");
    } finally {
      setWorking("");
    }
  };

  const commitRequirement = async () => {
    if (!importPreview) return;
    setWorking("commit");
    try {
      const result = await localPlatformService.commitRequirementImport(importPreview.token, importPreview.expected_version);
      setImportPreview(null);
      setJsonInput("");
      await refreshCurrent();
      showNotice(`需求蓝图 V${result.version} 已保存`);
      onOpenRequirement?.(result.case.customer_id, result.case.id);
    } catch (error) {
      setImportPreview(null);
      showNotice(error instanceof Error ? error.message : "需求蓝图保存失败");
    } finally {
      setWorking("");
    }
  };

  const analyzeSales = async (refresh = false, provider?: DraftProvider) => {
    if (!detail) return;
    setWorking("sales-analysis");
    try {
      const result = await localPlatformService.analyzeSales(detail.id, refresh, provider);
      setSalesAnalysis(result);
      setSalesHistory(await localPlatformService.salesHistory(detail.id).catch(() => [result]));
      showNotice("AI 销售分析完成，尚未写入客户或线索");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "销售分析失败");
    } finally {
      setWorking("");
    }
  };

  const confirmSales = async () => {
    if (!detail || !salesAnalysis?.result || !window.confirm("确认保存客户、销售线索和本次销售记忆？系统不会自动报价、创建项目或发送消息。")) return;
    setWorking("sales-confirm");
    try {
      const confirmed = await localPlatformService.confirmSales(detail.id, salesAnalysis.id);
      setLead(confirmed.lead);
      setSelectedCustomerId(confirmed.lead.customer_id || "");
      setSalesAnalysis(confirmed.analysis);
      setSalesMemory((current) => ({
        customer_id: confirmed.lead.customer_id,
        memories: [confirmed.memory, ...(current?.memories || []).filter((item) => item.id !== confirmed.memory.id)],
        memory_count: Math.max(1, current?.memory_count || 0),
        latest_version: confirmed.memory.version,
      }));
      showNotice(confirmed.idempotent ? "客户与线索已经保存" : "客户、线索和销售记忆已人工确认保存");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "客户与线索保存失败");
    } finally {
      setWorking("");
    }
  };

  if (loading) return <div className="messages-loading"><ArrowClockwise size={22} className="spin" />正在连接本机客户消息…</div>;
  if (!conversations.length) return <div className="customer-messages-page"><MessagesToolbar filter={filter} onFilter={setFilter} status={status} providers={providers} onRefresh={() => void loadList()} /><EmptyMessages offline={offline} /></div>;

  return <div className="customer-messages-page">
    <MessagesToolbar filter={filter} onFilter={setFilter} status={status} providers={providers} onRefresh={() => void refreshCurrent()} />
    <section className="messages-workbench">
      <aside className="conversation-list" aria-label="客户会话列表">
        <header><span>会话</span><b>{conversations.length}</b></header>
        {conversations.map((conversation) => <button
          type="button"
          className={selectedId === conversation.id ? "active" : ""}
          aria-current={selectedId === conversation.id ? "true" : undefined}
          onClick={() => {
            setSelectedId(conversation.id);
            window.history.replaceState(window.history.state, "", conversationRouteHash(conversation.id));
          }}
          key={conversation.id}
        >
          <span className={`channel-avatar ${conversation.channel}`}><ChannelIcon channel={conversation.channel} /></span>
          <span className="conversation-copy"><strong>{conversation.customer_name}</strong><small>{conversation.last_message || "暂无消息"}</small><em>{conversation.item_title || channelLabel(conversation.channel)}</em></span>
          <time>{dateTime.format(new Date(conversation.last_message_at))}</time>
          {conversation.unread_count > 0 && <i>{conversation.unread_count}</i>}
        </button>)}
      </aside>

      <main className="message-thread">
        {detail && <>
          <header className="thread-header">
            <span className={`channel-avatar large ${detail.channel}`}><ChannelIcon channel={detail.channel} /></span>
            <div className="thread-header-copy"><h2>{detail.customer_name}</h2><p>{channelLabel(detail.channel)} · {detail.item?.title || "未关联商品"}</p></div>
            <div className="thread-header-actions">
              <button type="button" className="thread-export-button" onClick={openConversationExport} title="需求明确后，手动导出对话记录与固定 GPT 提示词"><DownloadSimple size={15} />需求分析导出</button>
              <span className="human-boundary"><ShieldCheck size={15} weight="fill" />人工确认发送</span>
            </div>
          </header>
          <div className="thread-messages" aria-live="polite">
            {detail.messages.map((message) => <article className={message.direction === "outbound" ? "outbound" : "inbound"} key={message.id}>
              <div><p>{message.content}</p><time>{dateTime.format(new Date(message.received_at))}</time></div>
            </article>)}
          </div>
        </>}
      </main>

      <aside className="reply-inspector">
        <nav className="inspector-tabs" aria-label="会话工作区">
          <button className={tab === "reply" ? "active" : ""} onClick={() => setTab("reply")}>回复草稿</button>
          <button className={tab === "requirements" ? "active" : ""} onClick={() => setTab("requirements")}>需求分析</button>
          <button className={tab === "conversion" ? "active" : ""} onClick={() => setTab("conversion")}>报价转化</button>
        </nav>

        {tab === "reply" && detail && <section className="reply-panel">
          <SalesInsightCard
            analysis={salesAnalysis}
            history={salesHistory}
            memory={salesMemory}
            lead={lead}
            working={working}
            showHistory={showSalesHistory}
            onAnalyze={(refresh = false, provider) => void analyzeSales(refresh, provider)}
            onConfirm={() => void confirmSales()}
            onToggleHistory={() => setShowSalesHistory((value) => !value)}
            onCreateProject={() => {
              if (!lead) { showNotice("请先人工确认保存客户与销售线索"); return; }
              setTab("conversion");
            }}
            onCopyReply={(reply) => {
              void navigator.clipboard.writeText(reply);
              showNotice("销售建议回复已复制，请人工审核后发送");
            }}
          />
          <div className="reply-section-divider"><span>回复草稿</span><small>原有三条草稿与人工发送保持独立</small></div>
          <header><span><Brain size={18} weight="duotone" />三条 AI 草稿</span><small>{detail.ai_task?.status === "running" ? "生成中" : `${detail.drafts.length} 条可选`}</small></header>
          <div className="reply-provider-switch" aria-label="草稿生成模型">
            {providers.filter((item) => item.provider === "deepseek" || item.provider === "codex_cli").map((item) => <button type="button" className={replyProvider === item.provider ? "active" : ""} disabled={!item.configured || Boolean(working)} onClick={() => setReplyProvider(item.provider)} key={item.provider}><span>{item.label}</span><small>{item.configured ? item.last_latency_seconds ? `最近 ${item.last_latency_seconds}s` : item.model || "已就绪" : "未配置"}</small></button>)}
          </div>
          {detail.ai_task && <div className={`active-provider-line status-${detail.ai_task.status}`}><i /><span>实际生成：{detail.ai_task.provider === "deepseek" ? "DeepSeek 快速" : "Codex 深度"}{detail.ai_task.model ? ` · ${detail.ai_task.model}` : ""}</span><b>{detail.ai_task.status === "completed" ? `已完成${detail.ai_task.duration_seconds ? ` · ${detail.ai_task.duration_seconds}s` : ""}` : detail.ai_task.status === "failed" ? "生成失败" : detail.ai_task.status === "running" ? "生成中" : "排队中"}</b></div>}
          {detail.drafts.length ? <>
            <div className="draft-options">{detail.drafts.map((draft, index) => <button className={draftIndex === index ? "active" : ""} onClick={() => { setDraftIndex(index); setDraftText(draft.content); }} key={draft.id}>{draft.style}</button>)}</div>
            <textarea aria-label="编辑回复草稿" value={draftText} onChange={(event) => setDraftText(event.target.value)} rows={6} />
            {riskFlags.length > 0 && <div className="risk-box"><WarningCircle size={17} weight="fill" /><div><strong>需要人工核对</strong>{riskFlags.map((flag) => <p key={flag}>{flag}</p>)}</div></div>}
            <div className="draft-secondary-actions">
              <button type="button" onClick={() => { void navigator.clipboard.writeText(draftText); showNotice("草稿已复制"); }}><Copy size={15} />复制</button>
              <button type="button" title="用当前模型重新生成" aria-label="用当前模型重新生成" disabled={!detail.pending_message_id || Boolean(working) || !providers.find((item) => item.provider === replyProvider)?.configured} onClick={generateDrafts}><ArrowClockwise size={15} />重新生成</button>
              <button type="button" disabled={!detail.pending_message_id || Boolean(working)} onClick={() => detail.pending_message_id && void doWork("ignore", () => localPlatformService.ignore(detail.pending_message_id!), "本轮咨询已忽略")}><X size={15} />忽略</button>
            </div>
            <button className="send-confirmed" disabled={!detail.pending_message_id || !draftText.trim() || Boolean(working)} onClick={() => {
              if (!detail.pending_message_id || !window.confirm("确认使用当前内容人工发送？高风险内容请先逐项核对。")) return;
              void doWork("send", () => localPlatformService.send(detail.pending_message_id!, draftText.trim()), "消息已通过渠道发送");
            }}><PaperPlaneTilt size={17} weight="fill" />确认并发送</button>
          </> : <div className="inspector-empty"><Clock size={24} /><p>{detail.ai_task?.status === "running" ? `${detail.ai_task.provider === "deepseek" ? "DeepSeek" : "Codex"} 正在生成三条草稿` : detail.ai_task?.status === "failed" ? detail.ai_task.error_message || "当前模型生成失败" : "当前没有待处理草稿"}</p>{detail.pending_message_id && <button disabled={!providers.find((item) => item.provider === replyProvider)?.configured} onClick={generateDrafts}>{detail.ai_task?.status === "failed" ? `重试${replyProvider === "deepseek" ? " DeepSeek" : " Codex"}` : "生成草稿"}</button>}</div>}
        </section>}

        {tab === "requirements" && detail && <section className="requirements-panel" id="conversation-export-panel">
          <header><span><FileText size={18} weight="duotone" />手动 GPT 需求分析</span><small>不会自动调用 GPT</small></header>
          <div className="requirement-usage-note"><ShieldCheck size={18} weight="fill" /><div><strong>客户需求基本明确后再使用</strong><p>只有点击下方导出按钮时才生成材料；系统不会自动分析、自动创建需求或自动发送消息。</p></div></div>
          <ol className="requirement-import-steps"><li className={exportBundle ? "done" : "active"}><i>1</i><span><b>导出需求分析文档</b><small>包含脱敏对话、固定提示词和输出结构</small></span></li><li className={jsonInput.trim() ? "done" : ""}><i>2</i><span><b>上传文档给 GPT</b><small>让 GPT 按文档要求只返回 JSON</small></span></li><li className={importPreview ? "active" : ""}><i>3</i><span><b>导入客户需求</b><small>校验预览并由你确认保存</small></span></li></ol>
          <div className="requirement-export-actions"><button className="primary" disabled={Boolean(working)} onClick={() => void downloadRequirementAnalysisDocument()}><DownloadSimple size={15} />下载分析文档 .md</button><button disabled={Boolean(working)} onClick={() => void copyRequirementAnalysisDocument()}><Copy size={15} />复制完整分析材料</button></div>
          {exportBundle && <p className="redaction-note"><ShieldCheck size={15} weight="fill" />已隐藏 {exportBundle.redaction_count} 处手机号、邮箱或微信号；Cookie、消息 ID 与内部日志不会导出。</p>}
          <p className="gpt-upload-instruction"><Sparkle size={15} />上传文档后对 GPT 发送：<b>请严格按照附件中的固定提示词完成需求分析，只返回 JSON。</b></p>
          <div className="requirement-section-title"><span>导入 GPT 分析结果</span><small>支持选择 JSON 文件或直接粘贴</small></div>
          <div className={`requirement-binding-card ${detail.linked_customer_id ? "is-linked" : "is-pending"}`}>
            <span><UserCircle size={17} weight="duotone" /><small>需求客户</small><b>{selectedCustomer?.name || "请选择并确认客户"}</b><em>{detail.linked_customer_id ? "已由渠道身份确认" : "保存蓝图时建立客户关系"}</em></span>
            <ArrowRight size={16} />
            <span><Storefront size={17} weight="duotone" /><small>对应商品</small><b>{detail.item?.title || "当前会话未关联商品"}</b><em>{detail.item ? `闲鱼商品 ${detail.item.external_id}` : "不会按标题猜测商品"}</em></span>
          </div>
          <div className="requirement-target-fields"><label>保存到客户<select value={selectedCustomerId} disabled={Boolean(detail.linked_customer_id)} onChange={(event) => { setSelectedCustomerId(event.target.value); setSelectedCaseId(""); setImportPreview(null); }}><option value="">请选择客户</option>{customers.map((customer) => <option value={customer.id} key={customer.id}>{customer.name}</option>)}</select></label><label>需求案例<select value={selectedCaseId} onChange={(event) => { setSelectedCaseId(event.target.value); setImportPreview(null); }}><option value="">为当前商品新建案例</option>{compatibleCustomerCases.map((item) => <option value={item.id} key={item.id}>添加到：{item.title}{item.item_title ? ` · ${item.item_title}` : ""}</option>)}</select></label>{!selectedCaseId && <label className="case-title-field">案例名称<input value={caseTitle} onChange={(event) => setCaseTitle(event.target.value)} placeholder="例如：闲鱼经营助手升级" /></label>}</div>
          <label className="requirement-json-file"><UploadSimple size={15} /><span><b>选择 GPT 返回的 JSON 文件</b><small>文件只在当前页面读取，确认前不会保存</small></span><input type="file" accept=".json,application/json,text/plain" onChange={(event) => void loadRequirementJsonFile(event)} /></label>
          <textarea className="requirement-json-input" aria-label="粘贴 GPT 返回的 JSON" value={jsonInput} onChange={(event) => { setJsonInput(event.target.value); setImportPreview(null); }} rows={8} placeholder={'粘贴 GPT 返回的完整 JSON，例如：\n{"schema_version":"2.0", ...}'} />
          {!importPreview ? <button className="panel-primary" disabled={Boolean(working) || !jsonInput.trim() || !selectedCustomerId || (detail.channel === "xianyu" && !detail.item)} onClick={() => void previewRequirement()}><Sparkle size={16} />校验并生成可视化预览</button> : <article className="requirement-preview-card"><header><span>V{importPreview.target_version}</span><div><b>{importPreview.case_title}</b><small>{importPreview.estimated_hours} 小时 · {importPreview.document.stages.length} 个实施阶段</small><em>{selectedCustomer?.name || "未选择客户"} · {importPreview.item_title || "未关联商品"}</em></div></header><div>{importPreview.changes.map((item) => <p key={item}><CheckCircle size={14} />{item}</p>)}{importPreview.warnings.map((item) => <p className="warning" key={item}><WarningCircle size={14} />{item}</p>)}</div><button disabled={Boolean(working)} onClick={() => void commitRequirement()}><CheckCircle size={16} weight="fill" />人工确认绑定客户、商品并保存蓝图</button></article>}
          {requirements?.latest && <div className="legacy-requirement-link"><span>当前会话已有 V{requirements.latest.version}</span><small>{requirements.latest.title} · 报价将采用最新确认版本</small></div>}
        </section>}

        {tab === "conversion" && detail && <section className="conversion-panel">
          <header><span><Funnel size={18} weight="duotone" />线索到项目</span><small>{lead ? lead.status : "尚未写入"}</small></header>
          <ol className="conversion-steps">
            <li className={lead ? "done" : salesAnalysis?.result ? "active" : ""}><i>{lead ? <Check size={14} /> : "1"}</i><div><strong>Sales Agent 分析客户</strong><small>{lead ? "客户、线索与销售记忆已人工确认" : salesAnalysis?.result ? "分析完成，等待人工确认保存" : "只读分析，不写入经营数据"}</small></div></li>
            <li className={requirements?.latest ? "done" : ""}><i>{requirements?.latest ? <Check size={14} /> : "2"}</i><div><strong>确认需求版本</strong><small>{requirements?.latest ? `采用 V${requirements.latest.version}` : "请先导入 GPT 需求蓝图"}</small></div></li>
            <li className={quotes.length ? "done" : ""}><i>{quotes.length ? <Check size={14} /> : "3"}</i><div><strong>生成规则报价</strong><small>蓝图工时 × 目标时薪 × 风险缓冲，几秒内完成</small></div></li>
            <li className={lead?.converted_project_id ? "done" : ""}><i>{lead?.converted_project_id ? <Check size={14} /> : "4"}</i><div><strong>人工确认转项目</strong><small>一次创建客户、任务和付款节点</small></div></li>
          </ol>
          {!lead && !salesAnalysis?.result && <button className="panel-primary" disabled={Boolean(working)} onClick={() => void analyzeSales(Boolean(salesAnalysis))}><Sparkle size={16} />{salesAnalysis?.status === "failed" ? "重试 AI 销售分析" : "生成客户销售分析"}</button>}
          {!lead && salesAnalysis?.result && <article className="lead-analysis-card"><header><span className={salesAnalysis.result.purchase_probability >= 60 ? "positive" : "neutral"}>{salesAnalysis.result.customer_type}</span><b>{salesAnalysis.result.purchase_probability}%</b></header><h3>{salesAnalysis.result.need_type}</h3><p>{salesAnalysis.result.sales_strategy}</p><div>{salesAnalysis.result.need_signals.map((item) => <span key={item}><CheckCircle size={13} />{item}</span>)}</div><footer><button onClick={() => void analyzeSales(true)} disabled={Boolean(working)}><ArrowClockwise size={14} />重新分析</button><button className="confirm" onClick={() => void confirmSales()} disabled={Boolean(working)}><CheckCircle size={14} weight="fill" />保存客户与线索</button></footer></article>}
          {lead && !quotes.length && <button className="panel-primary" disabled={!requirements?.latest || Boolean(working)} onClick={() => void doWork("quote", async () => { const activeLead = await ensureLead(); if (!activeLead) return; const quote = await localPlatformService.generateQuote(activeLead.id); setQuotes([quote]); }, "报价建议已生成，等待人工确认")}>生成报价建议</button>}
          {quotes[0] && <article className="quote-summary">
            <span>报价 V{quotes[0].version} · {quotes[0].status === "confirmed" ? "已确认" : "草稿"}</span>
            <strong>{money.format(quotes[0].total_amount)}</strong>
            <p>{quotes[0].estimated_hours} 小时 × {money.format(quotes[0].hourly_rate)}/小时 · 风险缓冲 {Math.round(quotes[0].risk_buffer * 100)}%</p>
            <div>{quotes[0].payment_plan.map((node) => <small key={String(node.type)}>{String(node.label)} {money.format(Number(node.amount || 0))}</small>)}</div>
          </article>}
          {quotes[0] && !lead?.converted_project_id && <button className="convert-project" disabled={Boolean(working)} onClick={() => {
            if (!lead || !window.confirm("确认采用当前需求与报价，并创建客户、项目、阶段任务和三笔付款节点？")) return;
            void doWork("convert", async () => {
              const result = await localPlatformService.convertLead(lead.id, quotes[0].id, requirements?.latest?.title);
              onProjectCreated?.(result.project_id);
            }, "已转为项目，经营数据已同步");
          }}><CheckCircle size={17} weight="fill" />人工确认并转项目</button>}
          {lead?.converted_project_id && <div className="converted-notice"><CheckCircle size={20} weight="fill" /><div><strong>已经转为经营项目</strong><small>项目、阶段任务和付款计划已进入统一数据底座</small></div></div>}
        </section>}
      </aside>
    </section>
    {notice && <div className="messages-notice" role="status"><CheckCircle size={17} weight="fill" />{notice}</div>}
  </div>;
}

function MessagesToolbar({ filter, onFilter, status, providers, onRefresh }: { filter: ChannelFilter; onFilter: (filter: ChannelFilter) => void; status: PlatformStatus | null; providers: AIProviderStatus[]; onRefresh: () => void }) {
  const deepseek = providers.find((item) => item.provider === "deepseek");
  return <header className="messages-toolbar">
    <div className="message-filters" aria-label="渠道筛选">
      {(["all", "xianyu", "wechat"] as ChannelFilter[]).map((value) => <button className={filter === value ? "active" : ""} onClick={() => onFilter(value)} key={value}>{value === "all" ? "全部渠道" : value === "xianyu" ? "闲鱼" : "微信"}</button>)}
    </div>
    <div className="connection-pills">
      <span className={status?.listener === "connected" ? "ok" : "warn"}><i />闲鱼 {status?.listener === "connected" ? "监听中" : "未连接"}</span>
      <span className={status?.model === "connected" ? "ok" : "warn"}><i />Codex {status?.model === "connected" ? "已就绪" : "需检查"}</span>
      <span className={deepseek?.configured && deepseek.status !== "error" ? "ok" : "muted"}><i />DeepSeek {deepseek?.configured ? deepseek.status === "error" ? "需检查" : "已配置" : "未配置"}</span>
      <span className={status?.wechat_status === "connected" ? "ok" : "muted"}><i />微信 {status?.wechat_provider === "wecom" ? "企业客服" : "Mock"}</span>
      <button aria-label="刷新客户消息" onClick={onRefresh}><ArrowClockwise size={17} /></button>
    </div>
  </header>;
}
