import { ActionMenu } from '../components/workspace/ActionMenu';
import { EmptyState } from '../components/workspace/EmptyState';
import { MasterList } from '../components/workspace/MasterList';
import { Button } from '@appica/ui-react/button';
import { MessageTimelineEntry } from '../components/workspace/MessageTimelineEntry';
import { useLatestMessageScroll } from '../components/workspace/useLatestMessageScroll';
import { CustomerListResize, useCustomerListWidth } from '../components/workspace/CustomerListResize';
import { CustomerProfileWorkspace } from '../components/workspace/CustomerProfileWorkspace';
import { CustomerContextPanel } from '../components/workspace/CustomerContextPanel';
import { CustomerMessageSearch } from '../components/CustomerMessageSearch';
import {
  ArrowClockwise,
  ChatCircleDots,
  Check,
  CheckCircle,
  ClipboardText,
  DownloadSimple,
  ImageSquare,
  LinkSimple,
  FileText,
  MagnifyingGlass,
  ShieldCheck,
  Storefront,
  UserCircle,
  WarningCircle,
  WechatLogo,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  localPlatformService,
  type ConversationDetail,
  type ConversationHistoryCommitResult,
  type ConversationHistoryPreview,
  type ConversationHistorySearchItem,
  type ConversationSummary,
  type CustomerImageArchiveView,
} from "../data/localPlatformService";
import { CustomerImageLibrary, ImageLightbox, OriginalPreview } from "../components/CustomerImageLibrary";
import { ChatGPTConversationAccessCard } from "../components/ChatGPTConversationAccessCard";
import { CustomerWorkflowDialog } from "../components/CustomerWorkflowDialog";
import { ConversationGroupDialog } from "../components/ConversationGroupDialog";
import { ConversationGroupTimeline } from "../components/ConversationGroupTimeline";
import { subscribeCustomerEvents } from "../data/customerEvents";
import { readUiSession, writeUiSession } from '../data/uiSession';
import { readCustomerSelection, customerImagesHash } from "../data/customerSelection";
import type { ConversationGroup } from "../data/customerConversationClient";
import { PhraseLibraryDrawer } from "../components/PhraseLibraryDrawer";
import type { Customer, LedgerSnapshot } from "../types";
import { CustomerRequirementBlueprintPage } from "./CustomerRequirementBlueprintPage";
import "./customer-hub.css";
import "./customer-messages.css";


type ChannelFilter = "all" | "xianyu" | "wechat";
type CustomerMessagesPrimaryView = "conversations" | "images";
type HistoryImportDays = 7 | 30 | 90 | 365;
type HistoryImportScope = "full" | "recent" | "page";

function readCustomerMessagesPrimaryView(): CustomerMessagesPrimaryView {
  try {
    const [page, kind] = decodeURIComponent(window.location.hash.replace(/^#/, "")).split("/");
    return page === "客户消息" && kind?.split("?")[0] === "images" ? "images" : "conversations";
  } catch {
    return "conversations";
  }
}

function readConversationRouteId() {
  try {
    const [page, kind, rawId] = decodeURIComponent(window.location.hash.replace(/^#/, "")).split("/");
    if (page !== "客户消息" || kind !== "conversation") return null;
    const value = Number(rawId?.split("?")[0]);
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
  timeZone: "Asia/Shanghai",
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

function HistoryImportDialog({ open, onClose, onImported, initialConversation }: {
  open: boolean;
  onClose: () => void;
  onImported: (result: ConversationHistoryCommitResult) => void;
  initialConversation?: ConversationDetail | null;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const commitRequestIdRef = useRef("");
  const [query, setQuery] = useState("");
  const [days, setDays] = useState<HistoryImportDays>(30);
  const [results, setResults] = useState<ConversationHistorySearchItem[]>([]);
  const [selectedExternalId, setSelectedExternalId] = useState("");
  const [historyScope, setHistoryScope] = useState<HistoryImportScope>("full");
  const [preview, setPreview] = useState<ConversationHistoryPreview | null>(null);
  const [phase, setPhase] = useState<"idle" | "searching" | "previewing" | "committing">("idle");
  const [error, setError] = useState("");
  const [hasSearched, setHasSearched] = useState(false);
  const [continuationToken, setContinuationToken] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ConversationHistoryCommitResult | null>(null);
  const previewVersion = useRef(0);
  const initialConversationRef = useRef(initialConversation);
  initialConversationRef.current = initialConversation;

  const loadPreview = async (externalId: string, continuation?: string) => {
    const version = ++previewVersion.current;
    if (!continuation) setContinuationToken(null);
    setSelectedExternalId(externalId);
    setPreview(null);
    setError("");
    commitRequestIdRef.current = "";
    setPhase("previewing");
    try {
      const next = await localPlatformService.previewConversationHistory(externalId, historyScope, historyScope === "page" ? 200 : 100, continuation);
      if (version !== previewVersion.current) return;
      setPreview(next);
      setReceipt(null);
    } catch (reason) {
      if (version === previewVersion.current) setError(reason instanceof Error ? reason.message : "历史消息预览失败");
    } finally {
      if (version === previewVersion.current) setPhase("idle");
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
    } catch (reason) {
      setResults([]);
      setSelectedExternalId("");
      setError(reason instanceof Error ? reason.message : "闲鱼历史会话读取失败");
    } finally {
      setPhase((current) => current === "searching" ? "idle" : current);
    }
  };

  const commit = async () => {
    if (!preview || (preview.new_count <= 0 && !preview.image_candidate_count)) return;
    setPhase("committing");
    setError("");
    try {
      const stableRequestId = commitRequestIdRef.current || requestId("history_import");
      commitRequestIdRef.current = stableRequestId;
      const result = await localPlatformService.commitConversationHistory({
        request_id: stableRequestId,
        preview_token: preview.token,
        mark_latest_pending: false,
      });
      setReceipt(result); setContinuationToken(result.next_continuation_token || null);
      onImported(result);
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
    setHistoryScope("full");
    setPreview(null);
    setError("");
    setHasSearched(false);
    setContinuationToken(null); setReceipt(null);
    setPhase("idle");
    commitRequestIdRef.current = "";
    const initial = initialConversationRef.current;
    const latest = initial?.messages.at(-1);
    if (initial?.channel === "xianyu" && initial.external_id && latest) {
      setQuery(initial.customer_name);
      setSelectedExternalId(initial.external_id);
      setHasSearched(true);
      setResults([{ external_conversation_id: initial.external_id, customer_name: initial.customer_name, item_title: initial.item?.title || null, last_message: latest.content, last_message_at: latest.received_at, direction: latest.direction, existing_conversation_id: initial.id, known_message_count: initial.has_older_messages ? 0 : initial.messages.length }]);
    }
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
        <div><small>HISTORY SYNC</small><h2 id="history-import-title">同步历史消息与图片</h2><p>一次确认范围，同时补充消息与客户入站原图</p></div>
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
          <div className="history-import-scope" role="radiogroup" aria-label="历史消息读取范围">
            <button type="button" role="radio" aria-checked={historyScope === "full"} className={historyScope === "full" ? "active" : ""} disabled={busy} onClick={() => {
              setHistoryScope("full");
              setReceipt(null); setContinuationToken(null);
              setPreview(null);
              setError("");
              commitRequestIdRef.current = "";
            }}><b>批量同步</b><small>最多 5000 条 · 可能不完整</small></button>
            <button type="button" role="radio" aria-checked={historyScope === "recent"} className={historyScope === "recent" ? "active" : ""} disabled={busy} onClick={() => {
              setHistoryScope("recent");
              setReceipt(null); setContinuationToken(null);
              setPreview(null);
              setError("");
              commitRequestIdRef.current = "";
            }}><b>最近 100 条</b><small>快速核对最近消息</small></button>
            <button type="button" role="radio" aria-checked={historyScope === "page"} className={historyScope === "page" ? "active" : ""} disabled={busy} onClick={() => { setHistoryScope("page"); setPreview(null); setReceipt(null); setContinuationToken(null); commitRequestIdRef.current = ""; }}><b>分页同步</b><small>每页最多 200 条 · 手动继续</small></button>
          </div>
          <div className="history-import-section-label"><span>历史会话</span><b>{results.length}</b></div>
          <div className="history-import-results">
            {!hasSearched && <div className="history-import-empty"><MagnifyingGlass size={26} weight="duotone" /><b>先读取闲鱼历史会话</b><p>输入关键词可缩小范围；留空将查看所选时间内的最近会话。</p><button type="button" disabled={busy} onClick={() => void search()}>开始查询</button></div>}
            {hasSearched && !results.length && !error && <div className="history-import-empty compact"><ChatCircleDots size={24} weight="duotone" /><b>没有找到匹配会话</b><p>可扩大时间范围或清空搜索词重试。</p></div>}
            {results.map((row) => <button type="button" disabled={busy} className={selectedExternalId === row.external_conversation_id ? "selected" : ""} aria-current={selectedExternalId === row.external_conversation_id ? "true" : undefined} onClick={() => void loadPreview(row.external_conversation_id)} key={row.external_conversation_id}>
              <span className="history-result-choice">{selectedExternalId === row.external_conversation_id ? <Check size={14} weight="bold" /> : null}</span>
              <span className="history-result-channel"><Storefront size={17} weight="fill" /></span>
              <span><b>{row.customer_name}</b><small>{row.item_title || "未读取商品信息"}</small><em>{row.last_message}</em></span>
              <time>{dateTime.format(new Date(row.last_message_at))}</time>
              {row.known_message_count > 0 && <i>已存 {row.known_message_count}</i>}
            </button>)}
          </div>
        </section>
        <section className="history-import-preview" aria-label="历史消息导入预览">
          {phase === "previewing" && <div className="history-import-empty"><ArrowClockwise size={24} className="spin" /><b>{historyScope === "full" ? "正在批量读取，最多 5000 条" : historyScope === "page" ? "正在读取本页最多 200 条" : "正在读取最近 100 条"}</b><p>仅从现有闲鱼连接查询；分页异常会停止且不生成可导入预览。</p></div>}
          {!preview && phase !== "previewing" && <div className="history-import-empty"><FileText size={26} weight="duotone" /><b>{selectedExternalId ? "点击左侧所选会话开始读取" : "选择一条会话查看差异"}</b><p>{historyScope === "full" ? "点击所选会话后批量读取最多 5000 条；结果可能不包含全部历史。" : historyScope === "page" ? "本页最多 200 条；同步后由你决定是否继续下一页。" : "将读取最近 100 条平台消息供你核对。"}</p></div>}
          {preview && <>
            <header><div><small>预览：{preview.customer_name} · {preview.history_scope === "full" ? "批量同步（最多 5000 条）" : preview.history_scope === "page" ? "本页最多 200 条" : "最近 100 条"}</small><h3>{preview.item?.title || "未关联商品"}</h3>{previewStart && previewEnd && <p>{preview.item?.price ? `${preview.item.price} · ` : ""}{dateTime.format(new Date(previewStart.received_at))} ～ {dateTime.format(new Date(previewEnd.received_at))}</p>}{preview.item_warning && <p className="history-import-item-warning">{preview.item_warning}</p>}</div><span><Storefront size={18} weight="fill" />闲鱼</span></header>
            <div className="history-import-stats"><span><small>{preview.history_scope === "full" ? "本次批量读取" : "本次读取"}</small><b>{preview.platform_message_count} 条</b></span><span><small>已存在</small><b>{preview.existing_count} 条</b></span><span className="new"><small>将新增</small><b>{preview.new_count} 条</b></span></div>
            <div className="history-import-message-list">{preview.messages.map((message) => <article className={`${message.direction} ${message.import_status}`} key={message.platform_message_id}><span>{message.direction === "inbound" ? <UserCircle size={17} /> : <ChatCircleDots size={17} weight="duotone" />}</span><div><b>{message.direction === "inbound" ? "客户消息" : "卖家回复"}<em>{message.import_status === "existing" ? "已存在" : message.import_status === "unsupported" ? "占位" : "新增"}</em></b><p>{message.content}</p></div><time>{dateTime.format(new Date(message.received_at))}</time></article>)}</div>
          </>}
        </section>
      </div>
      {error && <div className="history-import-error" role="alert"><WarningCircle size={17} weight="fill" /><span>{error}</span></div>}
      {receipt && <div className="history-import-boundary history-sync-receipt" role="status"><span>本页新增 {receipt.imported_count} 条消息，图片成功 {receipt.image_stored_count} / 失败 {receipt.image_failed_count}；{receipt.has_more ? "仍有后续历史，尚未全部同步。" : receipt.history_complete ? "平台确认已到历史末尾。" : "本次范围已同步，不代表完整历史。"}</span><div>{continuationToken && <button type="button" disabled={busy} onClick={() => void loadPreview(selectedExternalId, continuationToken)}>继续下一页</button>}<button type="button" disabled={busy} onClick={() => { window.location.hash = customerImagesHash(receipt.conversation_id); onClose(); }}>逐张查看图片结果与失败原因</button></div></div>}
      <div className="history-import-rules" aria-label="导入规则"><span><Check size={14} weight="bold" />按平台消息 ID 去重</span><span><Check size={14} weight="bold" />确认后自动保存客户入站原图</span><span><Check size={14} weight="bold" />仅归档消息与原图</span></div>
      <footer className="history-import-footer">
        <p className="history-import-readonly-note"><ShieldCheck size={16} weight="fill" /><span><b>只补充真实消息与客户入站原图</b><small>不会触发 AI 分析或任何业务写入。</small></span></p>
        <div><button type="button" disabled={busy} onClick={onClose}>取消</button><button type="button" className="primary" disabled={busy || !preview || (preview.new_count <= 0 && !preview.image_candidate_count)} onClick={() => void commit()}>{phase === "committing" ? <ArrowClockwise size={16} className="spin" /> : <CheckCircle size={16} weight="fill" />}{preview && (preview.new_count || preview.image_candidate_count) ? `确认同步 ${preview.new_count} 条消息 / ${preview.image_candidate_count || 0} 张候选图片` : "没有需要同步的内容"}</button></div>
      </footer>
    </div>
  </div>, document.body);
}

export function CustomerMessagesPage(_props: {
  customers: Customer[];
  snapshot?: LedgerSnapshot;
  onSnapshotChange?: (snapshot: LedgerSnapshot) => void;
  onCreateCustomer?: (conversationId: number) => void;
  onProjectCreated?: (projectId: string) => void;
  onOpenRequirement?: (customerId: string, caseId: string) => void;
}) {
  const [primaryView, setPrimaryView] = useState<CustomerMessagesPrimaryView>(() => readCustomerMessagesPrimaryView());
  const readPane = () => {
    const q = new URLSearchParams(decodeURIComponent(location.hash).split('?')[1] || '');
    const pane = q.get('view');
    return { view: (['materials', 'requirements', 'projects'].includes(pane || '') ? pane : 'conversation') as 'conversation' | 'materials' | 'requirements' | 'projects', caseId: q.get('case') };
  };
  const [pane, setPane] = useState(readPane);
  const readProfile = () => /^客户消息\/customer\/([^/?]+)/.exec(decodeURIComponent(location.hash.slice(1)))?.[1] || null;
  const [profileId,setProfileId] = useState(readProfile);
  const [contextVisible, setContextVisible] = useState(false);
  const customerList = useCustomerListWidth(contextVisible);
  const contextVisibilityChosen = useRef(false);
  const contextTriggerRef = useRef<HTMLButtonElement>(null);
  const contextCloseRef = useRef<HTMLButtonElement>(null);
  const contextFocusRequested = useRef(false);
  const changeContextVisibility = (visible: boolean) => {
    contextVisibilityChosen.current = true;
    contextFocusRequested.current = true;
    setContextVisible(visible);
  };
  useEffect(() => {
    if (!contextFocusRequested.current) return;
    contextFocusRequested.current = false;
    (contextVisible ? contextCloseRef : contextTriggerRef).current?.focus();
  }, [contextVisible]);
  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 1500px)');
    const sync = () => { if (!contextVisibilityChosen.current) setContextVisible(false); };
    desktop.addEventListener('change', sync);
    sync();
    return () => desktop.removeEventListener('change', sync);
  }, []);
  const [mobileList, setMobileList] = useState(() => !readConversationRouteId() && !readProfile());
  const profile = _props.customers.find(c=>c.id===profileId);
  const selectPane = (view: typeof pane.view, caseId: string | null = null) => {
    if (window.matchMedia('(max-width: 700px)').matches) setContextVisible(false);
    setPane({ view, caseId });
    const query = new URLSearchParams({ view });
    if (caseId) query.set('case', caseId);
    window.location.hash = encodeURIComponent(`客户消息/${profileId ? `customer/${profileId}` : `conversation/${selectedId}`}?${query}`);
  };
  const [filter, setFilter] = useState<ChannelFilter>(()=>{const saved=readUiSession('customer-channel');return saved==='xianyu'||saved==='wechat'?saved:'all'});
  useEffect(()=>writeUiSession('customer-channel',filter),[filter]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(() => readCustomerSelection());
  useEffect(()=>{if(selectedId)writeUiSession('last-conversation',String(selectedId));},[selectedId]);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const linkedCustomer = _props.customers.find(c => c.id === detail?.linked_customer_id);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);
  const [notice, setNotice] = useState("");
  const [historyImportOpen, setHistoryImportOpen] = useState(false);
  const [phraseLibraryOpen, setPhraseLibraryOpen] = useState(false);
  const [olderMessagesLoading, setOlderMessagesLoading] = useState(false);
  const [selectedImage, setSelectedImage] = useState<CustomerImageArchiveView | null>(null);
  const [messageSearchOpen, setMessageSearchOpen] = useState(false);
  useEffect(() => setMessageSearchOpen(false), [selectedId]);
  const [accessOpen, setAccessOpen] = useState(false);
  const [groupOpen, setGroupOpen] = useState(false);
  const [group, setGroup] = useState<ConversationGroup | null>(null);
  const [groups, setGroups] = useState<ConversationGroup[]>([]);
  const detailVersion = useRef(0);
  const listVersion = useRef(0);
  const currentSelectedId = useRef(selectedId);
  currentSelectedId.current = selectedId;
  const threadMessagesRef = useRef<HTMLDivElement>(null);
  const historyScroll = useRef<{ thread: HTMLDivElement; conversationId: number; height: number; top: number } | null>(null);
  useLayoutEffect(() => {
    const saved = historyScroll.current;
    historyScroll.current = null;
    if (saved && saved.thread === threadMessagesRef.current && saved.conversationId === detail?.id) {
      saved.thread.scrollTop = saved.top + saved.thread.scrollHeight - saved.height;
    }
  }, [detail]);
  const [latestMessageRequest, setLatestMessageRequest] = useState(0);
  useLatestMessageScroll(threadMessagesRef, selectedId, latestMessageRequest,
    !loading && detail?.id === selectedId && primaryView === 'conversations' && pane.view === 'conversation' && !profileId && !group && !(mobileList && window.matchMedia('(max-width:700px)').matches));
  const phraseLibraryTriggerRef = useRef<HTMLButtonElement>(null);
  const closePhraseLibrary = useCallback(() => setPhraseLibraryOpen(false), []);

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 2600);
  };

  const loadList = async (preferredId?: number | null) => {
    const version = ++listVersion.current;
    try {
      const rows = await localPlatformService.conversations(filter);
      if (version !== listVersion.current) return;
      setConversations(rows);
      setOffline(false);
      const wanted = currentSelectedId.current ?? preferredId ?? Number(readUiSession('last-conversation'));
      const nextId = wanted && rows.some((row) => row.id === wanted)
        ? wanted
        : rows[0]?.id ?? null;
      setSelectedId(nextId);
      if (preferredId && nextId !== preferredId) {
        const nextHash = nextId === null ? `#${encodeURIComponent("客户消息")}` : conversationRouteHash(nextId);
        window.history.replaceState(window.history.state, "", nextHash);
      }
    } catch {
      if (version !== listVersion.current) return;
      setOffline(true);
      setConversations([]);
      setSelectedId(null);
      setDetail(null);
    } finally {
      if (version === listVersion.current) setLoading(false);
    }
  };

  const loadConversation = async (conversationId: number) => {
    const version = ++detailVersion.current;
    setDetailLoading(true); setDetailError("");
    try {
      setOlderMessagesLoading(false);
      const nextDetail = await localPlatformService.conversation(conversationId);
      if (version !== detailVersion.current || currentSelectedId.current !== conversationId) return;
      setDetail(nextDetail);
      setConversations((rows) => rows.map((row) => row.id === conversationId ? { ...row, unread_count: 0 } : row));
    } catch (reason) {
      if (version !== detailVersion.current || currentSelectedId.current !== conversationId) return;
      setDetailError(reason instanceof Error ? reason.message : "会话加载失败");
    } finally {
      if (version === detailVersion.current && currentSelectedId.current === conversationId) setDetailLoading(false);
    }
  };

  const loadOlderMessages = async () => {
    if (!detail?.has_older_messages || !detail.messages.length || olderMessagesLoading) return;
    const thread = threadMessagesRef.current;
    const previousHeight = thread?.scrollHeight ?? 0;
    const previousTop = thread?.scrollTop ?? 0;
    setOlderMessagesLoading(true);
    try {
      const page = await localPlatformService.olderConversationMessages(
        detail.id,
        detail.messages[0].id,
      );
      if (currentSelectedId.current !== detail.id) return;
      if (thread) historyScroll.current = { thread, conversationId: detail.id, height: previousHeight, top: previousTop };
      setDetail((current) => {
        if (!current || current.id !== detail.id) return current;
        const knownIds = new Set(current.messages.map((message) => message.id));
        return {
          ...current,
          messages: [...page.messages.filter((message) => !knownIds.has(message.id)), ...current.messages],
          has_older_messages: page.has_more,
        };
      });
    } catch (reason) {
      showNotice(reason instanceof Error ? reason.message : "更早消息加载失败");
    } finally {
      setOlderMessagesLoading(false);
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
    setDetail(null); setGroup(null); setGroups([]); setAccessOpen(false); setGroupOpen(false);
    if (selectedId === null) { detailVersion.current += 1; setDetailLoading(false); setDetailError(""); return; }
    void loadConversation(selectedId);
    let live = true;
    void localPlatformService.conversationGroupCandidates(selectedId).then((value) => {
      if (!live) return;
      const active = value.groups.filter(item=>item.active);
      setGroups(active);
      setGroup(active.find(item=>item.id===readUiSession(`conversation-${selectedId}-group`)) || null);
    }).catch(() => {});
    return () => { live = false; detailVersion.current += 1; };
  }, [selectedId]);
  useEffect(() => {
    const syncRoute = () => {
      setPrimaryView(readCustomerMessagesPrimaryView());
      setPane(readPane());
      setProfileId(readProfile());
      setMobileList(!readConversationRouteId() && !readProfile());
      const requestedId = readCustomerSelection() || readConversationRouteId();
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
  useEffect(() => subscribeCustomerEvents(() => {
      void loadList(selectedId);
      if (selectedId !== null) void loadConversation(selectedId);
  }), [filter, selectedId]);
  useEffect(() => {
    const refreshBinding = () => { void refreshCurrent(); };
    window.addEventListener("xunying:customer-created", refreshBinding);
    return () => window.removeEventListener("xunying:customer-created", refreshBinding);
  }, [filter, selectedId]);

  const historyImportDialog = <HistoryImportDialog
    open={historyImportOpen}
    initialConversation={detail}
    onClose={() => setHistoryImportOpen(false)}
    onImported={(result) => {
      if (!result.has_more && !result.image_failed_count) {
        setHistoryImportOpen(false); setPrimaryView("conversations");
        window.history.pushState(window.history.state, "", conversationRouteHash(result.conversation_id));
        setSelectedId(result.conversation_id);
      }
      void loadList(result.conversation_id);
      const imageSummary = result.image_candidate_count
        ? `，原图成功 ${result.image_stored_count} 张${result.image_failed_count ? `、失败 ${result.image_failed_count} 张` : ""}`
        : "，该会话没有可归档的客户入站原图";
      showNotice(`已导入 ${result.imported_count} 条历史消息${imageSummary}`);
    }}
  />;

  if (primaryView === "images") return <div className="customer-messages-page image-library-open">
    <CustomerImageLibrary onOpenConversation={openConversationFromLibrary} initialConversationId={selectedId} onSyncHistory={() => setHistoryImportOpen(true)} />
    {historyImportDialog}
    {notice && <div className="messages-notice" role="status"><CheckCircle size={17} weight="fill" />{notice}</div>}
  </div>;

  if (loading) return <div className="customer-messages-page"><div className="messages-loading"><ArrowClockwise size={22} className="spin" />正在连接本机客户消息…</div></div>;

  const contextAction = !contextVisible && <Button ref={contextTriggerRef} type="button" variant="outline" className="customer-context-toggle customer-appica-button" aria-expanded={false} aria-controls="customer-context-panel" onClick={() => changeContextVisibility(true)}><UserCircle size={18}/><span>客户资料</span></Button>;

  return <div className={`customer-messages-page customer-focus airy-customer ${contextVisible ? 'context-visible' : ''} ${mobileList ? 'show-customer-list' : 'show-customer-detail'}`}>
    <button type="button" className="customer-list-back" onClick={() => {setContextVisible(false);setMobileList(true);window.location.hash=encodeURIComponent('客户消息');}}>← 客户列表</button>
    {!conversations.length && !_props.customers.length
      ? <><MessagesToolbar filter={filter} onFilter={setFilter} onRefresh={() => void refreshCurrent()} /><EmptyMessages offline={offline} onImportHistory={() => setHistoryImportOpen(true)} /></>
      : <section className="messages-workbench customer-resizable" ref={customerList.attach} style={{ '--customer-list-width': `${customerList.width}px` } as import('react').CSSProperties}>
        <CustomerListResize container={customerList.container} width={customerList.width} maximum={customerList.maximum} onChange={customerList.update}/>
        <MasterList toolbar={<MessagesToolbar filter={filter} onFilter={setFilter} onRefresh={() => void refreshCurrent()} />} rows={conversations} customers={_props.customers} selectedId={profileId?null:selectedId} selectedCustomerId={profileId} onSelectCustomer={id=>{setMobileList(false);window.location.hash=encodeURIComponent(`客户消息/customer/${id}?view=requirements`);}} onSelect={id=>{setLatestMessageRequest(value=>value+1);setMobileList(false);setProfileId(null);setSelectedId(id);setPane({view:'conversation',caseId:null});window.history.pushState(window.history.state,'',conversationRouteHash(id));}}/>
        {profile ? <CustomerProfileWorkspace key={profile.id} customer={profile} snapshot={_props.snapshot} view={pane.view} caseId={pane.caseId} onView={selectPane} onSnapshotChange={_props.onSnapshotChange} headerActions={contextAction}/> : profileId ? <main className="message-thread"><EmptyState>该客户档案不存在或尚未加载，请从左侧重新选择。</EmptyState></main> : <main className="message-thread">
          {detail ? <>
            <header className="thread-header">
              <span className={`channel-avatar large ${detail.channel}`}><ChannelIcon channel={detail.channel} /></span>
              <div className="thread-header-copy"><h2>{linkedCustomer?.name || detail.customer_name}</h2><div className="thread-header-meta"><p>{channelLabel(detail.channel)} · {detail.item?.title || "未关联商品"}</p><span className="message-readonly"><ShieldCheck size={15} weight="fill" />消息只读</span></div></div>
              <div className="thread-header-actions" role="group" aria-label="当前会话操作">
              {pane.view === 'conversation' && <Button type="button" variant="primary" className="conversation-history-trigger customer-appica-button" onClick={() => setHistoryImportOpen(true)}>同步历史</Button>}
              {pane.view === 'conversation' && <Button ref={phraseLibraryTriggerRef} type="button" variant="outline" className="phrase-library-trigger customer-appica-button" aria-label="打开话术库" aria-haspopup="dialog" aria-expanded={phraseLibraryOpen} onClick={() => {
                setHistoryImportOpen(false);
                setPhraseLibraryOpen(true);
              }}><ClipboardText size={16} /><span>话术库</span></Button>}
              <ActionMenu iconOnly label="更多会话操作"><button type="button" onClick={() => setAccessOpen(true)}><LinkSimple size={17} />GPT 授权</button><button type="button" onClick={() => setGroupOpen(true)}>合并会话</button>{!linkedCustomer&&_props.onCreateCustomer&&<button type="button" onClick={()=>_props.onCreateCustomer?.(detail.id)}>建立客户档案</button>}</ActionMenu>
              {contextAction}
              </div>
            </header>
            <nav className="customer-hub-tabs" aria-label="当前客户内容">{([['conversation','会话'],['materials','资料'],['requirements','需求'],['projects','项目']] as const).map(([key,label])=><button key={key} type="button" aria-current={pane.view===key?'page':undefined} onClick={()=>selectPane(key)}>{label}</button>)}{pane.view==='conversation'&&<button type="button" className="message-search-trigger" onClick={()=>setMessageSearchOpen(true)} aria-haspopup="dialog"><MagnifyingGlass size={18}/><span>搜索消息</span></button>}</nav>
            {pane.view === 'materials' ? <div className="customer-hub-content"><CustomerImageLibrary key={detail.id} scoped initialConversationId={detail.id} onOpenConversation={openConversationFromLibrary} onSyncHistory={()=>setHistoryImportOpen(true)}/><p>图片引用原始归档，不复制文件。来源会话：{detail.customer_name} · {detail.item?.title || '商品来源未知'}</p>{_props.snapshot&&linkedCustomer&&<div className="customer-hub-projects">{_props.snapshot.attachments.filter(a=>_props.snapshot!.projects.some(p=>p.customerId===linkedCustomer.id&&p.id===a.projectId)).map(a=><p key={a.id}>{a.name} <a href={`#${encodeURIComponent(`项目管理/${a.projectId}/overview`)}`}>查看来源项目附件</a></p>)}</div>}</div> :
            pane.view === 'requirements' ? linkedCustomer&&_props.onSnapshotChange ? <div className="customer-hub-content"><CustomerRequirementBlueprintPage embedded key={linkedCustomer.id} customer={linkedCustomer} route={{customerId:linkedCustomer.id,caseId:pane.caseId}} onRouteChange={r=>selectPane('requirements',r?.caseId||null)} onSnapshotChange={_props.onSnapshotChange}/></div> : <div className="customer-hub-empty"><p>此会话尚未关联正式客户档案，不能按昵称推断需求归属。</p><button type="button" onClick={()=>_props.onCreateCustomer?.(detail.id)}>建立客户档案</button></div> :
            pane.view === 'projects' ? <div className="customer-hub-content customer-hub-projects">{linkedCustomer&&_props.snapshot?.projects.filter(p=>p.customerId===linkedCustomer.id).length ? _props.snapshot.projects.filter(p=>p.customerId===linkedCustomer.id).map(p=><a key={p.id} href={`#${encodeURIComponent(`项目管理/${p.id}/overview`)}`}><strong>{p.name}</strong><span>查看此项目 →</span></a>) : <p>{linkedCustomer?'当前客户尚无关联项目。':'请先确认客户档案关联，再查看其项目。'}</p>}</div> : <>
            {groups.length > 0 && <div className="thread-group-switch"><label>查看范围<select value={group?.id || ""} onChange={(event) => { writeUiSession(`conversation-${selectedId}-group`,event.target.value); setGroup(groups.find((item) => item.id === event.target.value) || null); }}><option value="">当前单会话</option>{groups.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.conversation_ids.length} 条会话</option>)}</select></label></div>}
            {group ? <ConversationGroupTimeline group={group} latestMessageRequest={latestMessageRequest} /> :
            <div className="thread-messages" ref={threadMessagesRef} aria-live="polite">
              {detail.has_older_messages && <div className="thread-history-control"><button type="button" disabled={olderMessagesLoading} onClick={() => void loadOlderMessages()}>{olderMessagesLoading ? <ArrowClockwise size={15} className="spin" /> : <DownloadSimple size={15} />}{olderMessagesLoading ? "正在加载更早消息" : "加载更早消息"}</button></div>}
              {detail.messages.map((message, index) => <MessageTimelineEntry senderName={message.sender_name || (message.direction === "outbound" ? "我" : detail.customer_name)} key={message.id} receivedAt={message.received_at} previousAt={detail.messages[index - 1]?.received_at} direction={message.direction} media={(message.images || message.customer_images || []).length > 0 ? <div className="message-image-grid">{(message.images || message.customer_images || []).map((image) => <button type="button" aria-label={`查看第 ${(image.media_index || 0) + 1} 张客户图片`} key={image.id} onClick={() => setSelectedImage(image)}><OriginalPreview image={image} compact /></button>)}</div> : message.content === "[图片]" ? <p className="message-media-pending">图片等待归档；可同步历史补充</p> : null}>
                {message.content && message.content !== "[图片]" ? <p>{message.content}</p> : null}
              </MessageTimelineEntry>)}
            </div>}</>}
          </> : <div className="message-thread-empty" role={detailLoading ? "status" : detailError ? "alert" : undefined}>{detailLoading ? <ArrowClockwise size={28} className="spin" /> : <ChatCircleDots size={28} weight="duotone" />}<p>{detailLoading ? "正在加载会话…" : detailError || "选择一条会话查看消息记录"}</p>{detailError && selectedId && <button type="button" className="messages-refresh" onClick={() => void loadConversation(selectedId)}>重试加载</button>}</div>}
        </main>}
        {contextVisible&&(profile||(!profileId&&detail))&&<CustomerContextPanel onClose={()=>changeContextVisibility(false)} closeButtonRef={contextCloseRef} onViewProjects={()=>selectPane('projects')} customer={profile||linkedCustomer} projects={_props.snapshot?.projects.filter(p=>p.customerId===(profile||linkedCustomer)?.id)||[]} pane={pane.view} media={!profileId&&detail&&pane.view!=='materials'&&<section className="customer-context-media"><header><h3>当前会话图片</h3><button type="button" onClick={()=>selectPane('materials')}>查看全部</button></header><div>{detail.messages.flatMap(message=>message.images||message.customer_images||[]).slice(-3).map(image=><button key={image.id} type="button" aria-label="查看会话归档图片" onClick={()=>setSelectedImage(image)}><OriginalPreview image={image} compact/></button>)}</div><small>仅预览已加载消息；完整归档请查看资料。</small></section>}/>}
      </section>}
    {historyImportDialog}
    {accessOpen && detail && <CustomerWorkflowDialog title="GPT 会话读取授权" onClose={() => setAccessOpen(false)}><ChatGPTConversationAccessCard onToast={showNotice} initialConversationId={group?.conversation_ids[0] || detail.id} selectedGroup={group} /></CustomerWorkflowDialog>}
    {groupOpen && detail && <ConversationGroupDialog conversationId={detail.id} onClose={() => setGroupOpen(false)} onChanged={(next) => { setGroups((rows) => [...rows.filter((item) => item.id !== next.id), ...(next.active ? [next] : [])]); setGroup(next.active ? next : null); }} />}
    {messageSearchOpen&&detail&&<CustomerMessageSearch key={detail.id} customerId={detail.linked_customer_id||undefined} conversationId={detail.id} customerName={linkedCustomer?.name||detail.customer_name} initialConversationIds={group?.conversation_ids} onClose={()=>setMessageSearchOpen(false)}/>}
    <ImageLightbox image={selectedImage} onClose={() => setSelectedImage(null)} onOpenConversation={openConversationFromLibrary} onDeleted={() => { setSelectedImage(null); void refreshCurrent(); }} />
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
    <select aria-label="渠道筛选" value={filter} onChange={e=>onFilter(e.target.value as ChannelFilter)}>
      <option value="all">全部渠道</option><option value="xianyu">闲鱼</option><option value="wechat">微信</option>
    </select>
    <ActionMenu label="客户管理"><a href={`#${encodeURIComponent('客户管理')}`}>客户档案与快速建档</a><a href={customerImagesHash(null)}>全部图片库</a><button type="button" className="messages-refresh" aria-label="刷新客户消息" onClick={onRefresh}><ArrowClockwise size={17} /><span>刷新消息</span></button></ActionMenu>
  </header>;
}
