import {
  ArrowClockwise,
  ChatCircleDots,
  Check,
  CheckCircle,
  ClipboardText,
  DownloadSimple,
  FileText,
  MagnifyingGlass,
  ShieldCheck,
  Storefront,
  UserCircle,
  WarningCircle,
  WechatLogo,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  connectPlatformEvents,
  localPlatformService,
  type ConversationDetail,
  type ConversationHistoryCommitResult,
  type ConversationHistoryPreview,
  type ConversationHistorySearchItem,
  type ConversationSummary,
} from "../data/localPlatformService";
import { CustomerImageLibrary } from "../components/CustomerImageLibrary";
import { PhraseLibraryDrawer } from "../components/PhraseLibraryDrawer";
import type { Customer } from "../types";
import "./customer-messages.css";


type ChannelFilter = "all" | "xianyu" | "wechat";
type CustomerMessagesPrimaryView = "conversations" | "images";
type HistoryImportDays = 7 | 30 | 90 | 365;

function readCustomerMessagesPrimaryView(): CustomerMessagesPrimaryView {
  try {
    const [page, kind] = decodeURIComponent(window.location.hash.replace(/^#/, "")).split("/");
    return page === "客户消息" && kind === "images" ? "images" : "conversations";
  } catch {
    return "conversations";
  }
}

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

function requestId(prefix: string) {
  const id = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}_${id.replace(/-/g, "_")}`;
}

const dateTime = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function channelLabel(channel: string) {
  return channel === "wechat" ? "微信" : "闲鱼";
}

function ChannelIcon({ channel }: { channel: string }) {
  return channel === "wechat"
    ? <WechatLogo size={16} weight="fill" />
    : <Storefront size={16} weight="fill" />;
}

function EmptyMessages({ offline, onImportHistory }: {
  offline: boolean;
  onImportHistory?: () => void;
}) {
  return <section className="messages-empty">
    <span><ChatCircleDots size={34} weight="duotone" /></span>
    <h2>{offline ? "需要连接本机经营服务" : "暂时没有客户会话"}</h2>
    <p>{offline
      ? "客户消息和渠道监听只在本机统一服务运行时可用；静态站点不会读取 Cookie。"
      : "闲鱼或微信收到新咨询后，会话会自动出现在这里。"}</p>
    {!offline && onImportHistory && <button type="button" className="empty-history-import" onClick={onImportHistory}><DownloadSimple size={16} />导入监听时段外的闲鱼对话</button>}
  </section>;
}

function HistoryImportDialog({ open, onClose, onImported }: {
  open: boolean;
  onClose: () => void;
  onImported: (result: ConversationHistoryCommitResult) => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const commitRequestIdRef = useRef("");
  const [query, setQuery] = useState("");
  const [days, setDays] = useState<HistoryImportDays>(30);
  const [results, setResults] = useState<ConversationHistorySearchItem[]>([]);
  const [selectedExternalId, setSelectedExternalId] = useState("");
  const [preview, setPreview] = useState<ConversationHistoryPreview | null>(null);
  const [phase, setPhase] = useState<"idle" | "searching" | "previewing" | "committing">("idle");
  const [error, setError] = useState("");
  const [hasSearched, setHasSearched] = useState(false);

  const loadPreview = async (externalId: string) => {
    setSelectedExternalId(externalId);
    setPreview(null);
    setError("");
    commitRequestIdRef.current = "";
    setPhase("previewing");
    try {
      setPreview(await localPlatformService.previewConversationHistory(externalId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "历史消息预览失败");
    } finally {
      setPhase("idle");
    }
  };

  const search = async () => {
    setPhase("searching");
    setError("");
    setPreview(null);
    try {
      const rows = await localPlatformService.searchConversationHistory({ query: query.trim(), days });
      setResults(rows);
      setHasSearched(true);
      const nextId = rows.some((row) => row.external_conversation_id === selectedExternalId)
        ? selectedExternalId
        : rows[0]?.external_conversation_id || "";
      setSelectedExternalId(nextId);
      if (nextId) await loadPreview(nextId);
    } catch (reason) {
      setResults([]);
      setSelectedExternalId("");
      setError(reason instanceof Error ? reason.message : "闲鱼历史会话读取失败");
    } finally {
      setPhase((current) => current === "searching" ? "idle" : current);
    }
  };

  const commit = async () => {
    if (!preview || preview.new_count <= 0) return;
    setPhase("committing");
    setError("");
    try {
      const stableRequestId = commitRequestIdRef.current || requestId("history_import");
      commitRequestIdRef.current = stableRequestId;
      onImported(await localPlatformService.commitConversationHistory({
        request_id: stableRequestId,
        preview_token: preview.token,
        mark_latest_pending: false,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "历史会话导入失败");
    } finally {
      setPhase("idle");
    }
  };

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const controls = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    document.body.classList.add("history-import-open");
    window.setTimeout(() => closeRef.current?.focus(), 0);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.classList.remove("history-import-open");
      previousFocus?.focus();
    };
  }, [onClose, open]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setDays(30);
    setResults([]);
    setSelectedExternalId("");
    setPreview(null);
    setError("");
    setHasSearched(false);
    setPhase("idle");
    commitRequestIdRef.current = "";
  }, [open]);

  if (!open) return null;
  const busy = phase !== "idle";
  const previewStart = preview?.messages[0];
  const previewEnd = preview?.messages.at(-1);
  return createPortal(<div className="history-import-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget && !busy) onClose();
  }}>
    <div className="history-import-dialog" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="history-import-title" aria-describedby="history-import-boundary">
      <header className="history-import-heading">
        <div><small>READ-ONLY IMPORT</small><h2 id="history-import-title">导入闲鱼历史对话</h2><p>把监听时段之外的真实会话补充到客户消息中</p></div>
        <button ref={closeRef} type="button" aria-label="关闭历史对话导入" disabled={busy} onClick={onClose}><X size={20} /></button>
      </header>
      <div className="history-import-boundary" id="history-import-boundary"><ShieldCheck size={17} weight="fill" /><span><b>只读查询</b> · 不发送 · 不标记已读 · 确认前不写入</span></div>
      <div className="history-import-grid">
        <section className="history-import-browser" aria-label="选择闲鱼历史会话">
          <div className="history-import-search-row">
            <label><MagnifyingGlass size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} placeholder="搜索客户昵称、商品或消息" /></label>
            <select value={days} onChange={(event) => setDays(Number(event.target.value) as HistoryImportDays)} aria-label="历史时间范围"><option value={7}>最近 7 天</option><option value={30}>最近 30 天</option><option value={90}>最近 90 天</option><option value={365}>最近一年</option></select>
            <button type="button" disabled={busy} onClick={() => void search()}>{phase === "searching" ? <ArrowClockwise size={16} className="spin" /> : <MagnifyingGlass size={16} />}查询</button>
          </div>
          <div className="history-import-section-label"><span>历史会话</span><b>{results.length}</b></div>
          <div className="history-import-results">
            {!hasSearched && <div className="history-import-empty"><MagnifyingGlass size={26} weight="duotone" /><b>先读取闲鱼历史会话</b><p>输入关键词可缩小范围；留空将查看所选时间内的最近会话。</p><button type="button" disabled={busy} onClick={() => void search()}>开始查询</button></div>}
            {hasSearched && !results.length && !error && <div className="history-import-empty compact"><ChatCircleDots size={24} weight="duotone" /><b>没有找到匹配会话</b><p>可扩大时间范围或清空搜索词重试。</p></div>}
            {results.map((row) => <button type="button" className={selectedExternalId === row.external_conversation_id ? "selected" : ""} aria-current={selectedExternalId === row.external_conversation_id ? "true" : undefined} onClick={() => void loadPreview(row.external_conversation_id)} key={row.external_conversation_id}>
              <span className="history-result-choice">{selectedExternalId === row.external_conversation_id ? <Check size={14} weight="bold" /> : null}</span>
              <span className="history-result-channel"><Storefront size={17} weight="fill" /></span>
              <span><b>{row.customer_name}</b><small>{row.item_title || "未读取商品信息"}</small><em>{row.last_message}</em></span>
              <time>{dateTime.format(new Date(row.last_message_at))}</time>
              {row.known_message_count > 0 && <i>已存 {row.known_message_count}</i>}
            </button>)}
          </div>
        </section>
        <section className="history-import-preview" aria-label="历史消息导入预览">
          {phase === "previewing" && <div className="history-import-empty"><ArrowClockwise size={24} className="spin" /><b>正在读取完整历史</b><p>仅从现有闲鱼连接查询，不会标记平台消息已读。</p></div>}
          {!preview && phase !== "previewing" && <div className="history-import-empty"><FileText size={26} weight="duotone" /><b>选择一条会话查看差异</b><p>右侧将显示平台消息、已存在消息和本次新增数量。</p></div>}
          {preview && <>
            <header><div><small>预览：{preview.customer_name}</small><h3>{preview.item?.title || "未关联商品"}</h3>{previewStart && previewEnd && <p>{preview.item?.price ? `${preview.item.price} · ` : ""}{dateTime.format(new Date(previewStart.received_at))} ～ {dateTime.format(new Date(previewEnd.received_at))}</p>}{preview.item_warning && <p className="history-import-item-warning">{preview.item_warning}</p>}</div><span><Storefront size={18} weight="fill" />闲鱼</span></header>
            <div className="history-import-stats"><span><small>平台共</small><b>{preview.platform_message_count} 条</b></span><span><small>已存在</small><b>{preview.existing_count} 条</b></span><span className="new"><small>将新增</small><b>{preview.new_count} 条</b></span></div>
            <div className="history-import-message-list">{preview.messages.map((message) => <article className={`${message.direction} ${message.import_status}`} key={message.platform_message_id}><span>{message.direction === "inbound" ? <UserCircle size={17} /> : <ChatCircleDots size={17} weight="duotone" />}</span><div><b>{message.direction === "inbound" ? "客户消息" : "卖家回复"}<em>{message.import_status === "existing" ? "已存在" : message.import_status === "unsupported" ? "占位" : "新增"}</em></b><p>{message.content}</p></div><time>{dateTime.format(new Date(message.received_at))}</time></article>)}</div>
          </>}
        </section>
      </div>
      {error && <div className="history-import-error" role="alert"><WarningCircle size={17} weight="fill" /><span>{error}</span></div>}
      <div className="history-import-rules" aria-label="导入规则"><span><Check size={14} weight="bold" />按平台消息 ID 去重</span><span><Check size={14} weight="bold" />确认后自动保存客户入站原图</span><span><Check size={14} weight="bold" />仅归档消息与原图</span></div>
      <footer className="history-import-footer">
        <p className="history-import-readonly-note"><ShieldCheck size={16} weight="fill" /><span><b>只补充真实消息与客户入站原图</b><small>不会触发 AI 分析或任何业务写入。</small></span></p>
        <div><button type="button" disabled={busy} onClick={onClose}>取消</button><button type="button" className="primary" disabled={busy || !preview || preview.new_count <= 0} onClick={() => void commit()}>{phase === "committing" ? <ArrowClockwise size={16} className="spin" /> : <CheckCircle size={16} weight="fill" />}{preview?.new_count ? `确认导入 ${preview.new_count} 条` : "没有可新增消息"}</button></div>
      </footer>
    </div>
  </div>, document.body);
}

export function CustomerMessagesPage(_props: {
  customers: Customer[];
  onProjectCreated?: (projectId: string) => void;
  onOpenRequirement?: (customerId: string, caseId: string) => void;
}) {
  const [primaryView, setPrimaryView] = useState<CustomerMessagesPrimaryView>(() => readCustomerMessagesPrimaryView());
  const [filter, setFilter] = useState<ChannelFilter>("all");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(() => readConversationRouteId());
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);
  const [notice, setNotice] = useState("");
  const [historyImportOpen, setHistoryImportOpen] = useState(false);
  const [phraseLibraryOpen, setPhraseLibraryOpen] = useState(false);
  const phraseLibraryTriggerRef = useRef<HTMLButtonElement>(null);
  const closePhraseLibrary = useCallback(() => setPhraseLibraryOpen(false), []);

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 2600);
  };

  const loadList = async (preferredId?: number | null) => {
    try {
      const rows = await localPlatformService.conversations(filter);
      setConversations(rows);
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
      const nextDetail = await localPlatformService.conversation(conversationId);
      setDetail(nextDetail);
      setConversations((rows) => rows.map((row) => row.id === conversationId ? { ...row, unread_count: 0 } : row));
    } catch (reason) {
      showNotice(reason instanceof Error ? reason.message : "会话加载失败");
    }
  };

  const refreshCurrent = async () => {
    await loadList(selectedId);
    if (selectedId !== null) await loadConversation(selectedId);
  };

  const openConversationFromLibrary = (conversationId: number) => {
    setPrimaryView("conversations");
    setSelectedId(conversationId);
    window.history.pushState(window.history.state, "", conversationRouteHash(conversationId));
  };

  useEffect(() => { void loadList(selectedId); }, [filter]);
  useEffect(() => {
    if (selectedId === null) setDetail(null);
    else void loadConversation(selectedId);
  }, [selectedId]);
  useEffect(() => {
    const syncRoute = () => {
      setPrimaryView(readCustomerMessagesPrimaryView());
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
  useEffect(() => connectPlatformEvents((event) => {
    if (["new_reply", "conversation_history_imported", "customer_image_archived"].includes(String(event.type))) {
      void loadList(selectedId);
      if (selectedId !== null) void loadConversation(selectedId);
    }
  }), [filter, selectedId]);

  const historyImportDialog = <HistoryImportDialog
    open={historyImportOpen}
    onClose={() => setHistoryImportOpen(false)}
    onImported={(result) => {
      setHistoryImportOpen(false);
      window.history.pushState(window.history.state, "", conversationRouteHash(result.conversation_id));
      setSelectedId(result.conversation_id);
      void loadList(result.conversation_id);
      const imageSummary = result.image_candidate_count
        ? `，原图成功 ${result.image_stored_count} 张${result.image_failed_count ? `、失败 ${result.image_failed_count} 张` : ""}`
        : "，该会话没有可归档的客户入站原图";
      showNotice(`已导入 ${result.imported_count} 条历史消息${imageSummary}`);
    }}
  />;

  if (primaryView === "images") return <div className="customer-messages-page image-library-open">
    <CustomerImageLibrary onOpenConversation={openConversationFromLibrary} />
    {notice && <div className="messages-notice" role="status"><CheckCircle size={17} weight="fill" />{notice}</div>}
  </div>;

  if (loading) return <div className="customer-messages-page"><div className="messages-loading"><ArrowClockwise size={22} className="spin" />正在连接本机客户消息…</div></div>;

  return <div className="customer-messages-page">
    <MessagesToolbar filter={filter} onFilter={setFilter} onRefresh={() => void refreshCurrent()} />
    {!conversations.length
      ? <EmptyMessages offline={offline} onImportHistory={() => setHistoryImportOpen(true)} />
      : <section className="messages-workbench">
        <aside className="conversation-list" aria-label="客户会话列表">
          <header><span>会话</span><b>{conversations.length}</b><button type="button" className="conversation-history-trigger" onClick={() => setHistoryImportOpen(true)}><DownloadSimple size={14} />导入历史</button></header>
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
          {detail ? <>
            <header className="thread-header">
              <span className={`channel-avatar large ${detail.channel}`}><ChannelIcon channel={detail.channel} /></span>
              <div className="thread-header-copy"><h2>{detail.customer_name}</h2><p>{channelLabel(detail.channel)} · {detail.item?.title || "未关联商品"}</p></div>
              <button ref={phraseLibraryTriggerRef} type="button" className="phrase-library-trigger" aria-label="打开话术库" aria-haspopup="dialog" aria-expanded={phraseLibraryOpen} onClick={() => {
                setHistoryImportOpen(false);
                setPhraseLibraryOpen(true);
              }}><ClipboardText size={16} /><span>话术库</span></button>
              <span className="message-readonly"><ShieldCheck size={15} weight="fill" />消息只读</span>
            </header>
            <div className="thread-messages" aria-live="polite">
              {detail.messages.map((message) => <article className={message.direction === "outbound" ? "outbound" : "inbound"} key={message.id}>
                <div><p>{message.content}</p><time>{dateTime.format(new Date(message.received_at))}</time></div>
              </article>)}
            </div>
          </> : <div className="message-thread-empty"><ChatCircleDots size={28} weight="duotone" /><p>选择一条会话查看消息记录</p></div>}
        </main>
      </section>}
    {historyImportDialog}
    <PhraseLibraryDrawer open={phraseLibraryOpen} onClose={closePhraseLibrary} triggerRef={phraseLibraryTriggerRef} />
    {notice && <div className="messages-notice" role="status"><CheckCircle size={17} weight="fill" />{notice}</div>}
  </div>;
}

function MessagesToolbar({ filter, onFilter, onRefresh }: {
  filter: ChannelFilter;
  onFilter: (filter: ChannelFilter) => void;
  onRefresh: () => void;
}) {
  return <header className="messages-toolbar">
    <div className="message-filters" aria-label="渠道筛选">
      {(["all", "xianyu", "wechat"] as ChannelFilter[]).map((value) => <button type="button" className={filter === value ? "active" : ""} onClick={() => onFilter(value)} key={value}>{value === "all" ? "全部渠道" : value === "xianyu" ? "闲鱼" : "微信"}</button>)}
    </div>
    <button type="button" className="messages-refresh" aria-label="刷新客户消息" onClick={onRefresh}><ArrowClockwise size={17} /><span>刷新消息</span></button>
  </header>;
}
