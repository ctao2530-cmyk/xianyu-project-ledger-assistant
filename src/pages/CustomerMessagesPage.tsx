import {
  ArrowClockwise,
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
  Question,
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
  type LeadAnalysis,
  type LeadView,
  type PlatformStatus,
  type QuoteView,
  type RequirementWorkspace,
  type RequirementExport,
  type RequirementImportPreview,
  type RequirementCaseSummary,
} from "../data/localPlatformService";
import type { Customer } from "../types";
import "./customer-messages.css";


type ChannelFilter = "all" | "xianyu" | "wechat";
type WorkbenchTab = "reply" | "requirements" | "conversion";

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

export function CustomerMessagesPage({ customers, onProjectCreated, onOpenRequirement }: { customers: Customer[]; onProjectCreated?: (projectId: string) => void; onOpenRequirement?: (customerId: string, caseId: string) => void }) {
  const [filter, setFilter] = useState<ChannelFilter>("all");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [requirements, setRequirements] = useState<RequirementWorkspace | null>(null);
  const [lead, setLead] = useState<LeadView | null>(null);
  const [leadAnalysis, setLeadAnalysis] = useState<LeadAnalysis | null>(null);
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
  const [selectedCustomerId, setSelectedCustomerId] = useState(customers[0]?.id || "");
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
      const [nextDetail, nextRequirements, nextLead] = await Promise.all([
        localPlatformService.conversation(conversationId),
        localPlatformService.requirements(conversationId),
        localPlatformService.getLead(conversationId).catch(() => null),
      ]);
      setDetail(nextDetail);
      setRequirements(nextRequirements);
      setDraftIndex(0);
      setDraftText(nextDetail.drafts[0]?.content || "");
      setLead(nextLead);
      setLeadAnalysis(null);
      setQuotes(nextLead ? await localPlatformService.quotes(nextLead.id).catch(() => []) : []);
      setExportBundle(null);
      setJsonInput("");
      setImportPreview(null);
      setCaseTitle(nextDetail.item?.title || `${nextDetail.customer_name}需求`);
      setConversations((rows) => rows.map((row) => row.id === conversationId ? { ...row, unread_count: 0 } : row));
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "会话加载失败");
    }
  };

  useEffect(() => { void loadList(selectedId); }, [filter]);
  useEffect(() => {
    if (selectedId !== null) void loadConversation(selectedId);
  }, [selectedId]);
  useEffect(() => connectPlatformEvents((event) => {
    if (["new_reply", "requirement_completed", "requirement_imported", "customer_requirement_updated", "lead_updated", "quote_completed", "project_created"].includes(String(event.type))) {
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
    if (!customers.some((item) => item.id === selectedCustomerId)) {
      setSelectedCustomerId(customers[0]?.id || "");
    }
  }, [customers, selectedCustomerId]);

  const selectedDraft = detail?.drafts[draftIndex];
  const riskFlags = useMemo(() => Array.from(new Set([
    ...(selectedDraft?.risk_flags || []),
    ...(detail?.ai_task?.risk_reasons || []),
  ])), [detail?.ai_task?.risk_reasons, selectedDraft?.risk_flags]);
  const deepseekStatus = providers.find((item) => item.provider === "deepseek");

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

  const analyzeLead = async (refresh = false) => {
    if (!detail) return;
    setWorking("lead-analysis");
    try {
      const result = await localPlatformService.analyzeLead(detail.id, refresh);
      setLeadAnalysis(result);
      showNotice("DeepSeek 线索分析完成，尚未写入经营数据");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "线索分析失败");
    } finally {
      setWorking("");
    }
  };

  const confirmLead = async () => {
    if (!detail || !leadAnalysis || !window.confirm("确认把本次分析保存为销售线索？这不会自动报价或创建项目。")) return;
    setWorking("lead-confirm");
    try {
      const nextLead = await localPlatformService.confirmLead(detail.id, leadAnalysis.id);
      setLead(nextLead);
      setLeadAnalysis({ ...leadAnalysis, confirmed_at: new Date().toISOString() });
      showNotice("线索已人工确认保存");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "线索保存失败");
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
          onClick={() => setSelectedId(conversation.id)}
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
          <div className="requirement-target-fields"><label>保存到客户<select value={selectedCustomerId} onChange={(event) => { setSelectedCustomerId(event.target.value); setSelectedCaseId(""); setImportPreview(null); }}><option value="">请选择客户</option>{customers.map((customer) => <option value={customer.id} key={customer.id}>{customer.name}</option>)}</select></label><label>需求案例<select value={selectedCaseId} onChange={(event) => { setSelectedCaseId(event.target.value); setImportPreview(null); }}><option value="">新建独立案例</option>{customerCases.map((item) => <option value={item.id} key={item.id}>添加到：{item.title}</option>)}</select></label>{!selectedCaseId && <label className="case-title-field">案例名称<input value={caseTitle} onChange={(event) => setCaseTitle(event.target.value)} placeholder="例如：闲鱼经营助手升级" /></label>}</div>
          <label className="requirement-json-file"><UploadSimple size={15} /><span><b>选择 GPT 返回的 JSON 文件</b><small>文件只在当前页面读取，确认前不会保存</small></span><input type="file" accept=".json,application/json,text/plain" onChange={(event) => void loadRequirementJsonFile(event)} /></label>
          <textarea className="requirement-json-input" aria-label="粘贴 GPT 返回的 JSON" value={jsonInput} onChange={(event) => { setJsonInput(event.target.value); setImportPreview(null); }} rows={8} placeholder={'粘贴 GPT 返回的完整 JSON，例如：\n{"schema_version":"2.0", ...}'} />
          {!importPreview ? <button className="panel-primary" disabled={Boolean(working) || !jsonInput.trim() || !selectedCustomerId} onClick={() => void previewRequirement()}><Sparkle size={16} />校验并生成可视化预览</button> : <article className="requirement-preview-card"><header><span>V{importPreview.target_version}</span><div><b>{importPreview.case_title}</b><small>{importPreview.estimated_hours} 小时 · {importPreview.document.stages.length} 个实施阶段</small></div></header><div>{importPreview.changes.map((item) => <p key={item}><CheckCircle size={14} />{item}</p>)}{importPreview.warnings.map((item) => <p className="warning" key={item}><WarningCircle size={14} />{item}</p>)}</div><button disabled={Boolean(working)} onClick={() => void commitRequirement()}><CheckCircle size={16} weight="fill" />人工确认保存并打开蓝图</button></article>}
          {requirements?.latest && <div className="legacy-requirement-link"><span>当前会话已有 V{requirements.latest.version}</span><small>{requirements.latest.title} · 报价将采用最新确认版本</small></div>}
        </section>}

        {tab === "conversion" && detail && <section className="conversion-panel">
          <header><span><Funnel size={18} weight="duotone" />线索到项目</span><small>{lead ? lead.status : "尚未写入"}</small></header>
          <ol className="conversion-steps">
            <li className={lead ? "done" : leadAnalysis ? "active" : ""}><i>{lead ? <Check size={14} /> : "1"}</i><div><strong>DeepSeek 识别线索</strong><small>{lead ? "已人工确认写入" : leadAnalysis ? "分析完成，等待人工确认" : "只分析，不写入经营数据"}</small></div></li>
            <li className={requirements?.latest ? "done" : ""}><i>{requirements?.latest ? <Check size={14} /> : "2"}</i><div><strong>确认需求版本</strong><small>{requirements?.latest ? `采用 V${requirements.latest.version}` : "请先导入 GPT 需求蓝图"}</small></div></li>
            <li className={quotes.length ? "done" : ""}><i>{quotes.length ? <Check size={14} /> : "3"}</i><div><strong>生成规则报价</strong><small>蓝图工时 × 目标时薪 × 风险缓冲，几秒内完成</small></div></li>
            <li className={lead?.converted_project_id ? "done" : ""}><i>{lead?.converted_project_id ? <Check size={14} /> : "4"}</i><div><strong>人工确认转项目</strong><small>一次创建客户、任务和付款节点</small></div></li>
          </ol>
          {!lead && !leadAnalysis && <button className="panel-primary" disabled={!deepseekStatus?.configured || Boolean(working)} onClick={() => void analyzeLead()}><Sparkle size={16} />{deepseekStatus?.configured ? "用 DeepSeek 分析线索" : "请先配置 DeepSeek API"}</button>}
          {!lead && leadAnalysis && <article className="lead-analysis-card"><header><span className={leadAnalysis.result.has_project_need ? "positive" : "neutral"}>{leadAnalysis.result.has_project_need ? "有效项目需求" : "暂不构成明确项目"}</span><b>{Math.round(leadAnalysis.result.confidence * 100)}%</b></header><h3>{leadAnalysis.result.suggested_title}</h3><p>{leadAnalysis.result.project_type} · {leadAnalysis.result.conversion_advice}</p><div>{leadAnalysis.result.confirmed_signals.map((item) => <span key={item}><CheckCircle size={13} />{item}</span>)}</div>{leadAnalysis.result.open_questions.length > 0 && <ul>{leadAnalysis.result.open_questions.map((item) => <li key={item}><Question size={13} />{item}</li>)}</ul>}<footer><button onClick={() => void analyzeLead(true)} disabled={Boolean(working)}><ArrowClockwise size={14} />重新分析</button><button className="confirm" onClick={() => void confirmLead()} disabled={Boolean(working)}><CheckCircle size={14} weight="fill" />确认保存为线索</button></footer></article>}
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
