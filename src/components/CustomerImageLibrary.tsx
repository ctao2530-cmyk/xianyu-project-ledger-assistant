import {
  ArrowClockwise,
  ArrowLeft,
  CalendarBlank,
  CheckCircle,
  DownloadSimple,
  FileImage,
  Funnel,
  ImageSquare,
  ShieldCheck,
  Trash,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { createPortal } from "react-dom";
import {
  connectPlatformEvents,
  localPlatformService,
  type CustomerImageArchiveStatus,
  type CustomerImageArchiveView,
  type CustomerImageAttentionItem,
  type CustomerImageFilters,
  type CustomerImageHistoryPreview,
  type CustomerImageHistoryResult,
} from "../data/localPlatformService";
import "./customer-image-library.css";


const imageTime = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const fullTime = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "long",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function channelLabel(channel: string) {
  return channel === "wechat" ? "微信" : "闲鱼";
}

function fileSize(bytes: number) {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function formatLabel(mime: string, name: string) {
  const suffix = name.split(".").pop()?.toUpperCase();
  if (suffix && suffix.length <= 5) return suffix;
  return mime.split("/").pop()?.toUpperCase() || "IMAGE";
}

function requestId(prefix: string) {
  const random = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}_${random}`;
}

function OriginalPreview({
  image,
  compact = false,
}: {
  image: CustomerImageArchiveView;
  compact?: boolean;
}) {
  const [unavailable, setUnavailable] = useState(false);
  if (unavailable) {
    return <span className={`customer-image-format-fallback ${compact ? "is-compact" : ""}`}>
      <FileImage size={compact ? 26 : 38} weight="duotone" />
      <b>{formatLabel(image.mime_type, image.original_name)} 原图</b>
      <small>当前浏览器无法直接预览，请下载原图查看</small>
    </span>;
  }
  return <img
    src={image.content_url}
    loading={compact ? "lazy" : "eager"}
    alt="客户发送的原图"
    onError={() => setUnavailable(true)}
  />;
}

function useDialogFocus(open: boolean, onClose: () => void) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    const first = dialog?.querySelector<HTMLElement>("button, a, input, select");
    window.setTimeout(() => first?.focus(), 0);
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex='-1'])"));
      if (!focusable.length) return;
      const firstItem = focusable[0];
      const lastItem = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [onClose, open]);
  return dialogRef;
}

function ImageLightbox({
  image,
  onClose,
  onOpenConversation,
  onDeleted,
}: {
  image: CustomerImageArchiveView | null;
  onClose: () => void;
  onOpenConversation: (conversationId: number) => void;
  onDeleted: (archiveId: string) => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const dialogRef = useDialogFocus(Boolean(image), onClose);
  if (!image) return null;

  const remove = async () => {
    if (!window.confirm("确认删除这张原图的本地副本？聊天消息和平台记录不会被删除。")) return;
    setDeleting(true);
    try {
      await localPlatformService.deleteCustomerImage(image.id);
      onDeleted(image.id);
      onClose();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "本地副本删除失败");
    } finally {
      setDeleting(false);
    }
  };

  return createPortal(
    <div className="customer-image-lightbox-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="customer-image-lightbox" role="dialog" aria-modal="true" aria-labelledby="customer-image-lightbox-title" ref={dialogRef}>
        <header>
          <div><small>ORIGINAL IMAGE</small><h2 id="customer-image-lightbox-title">原图预览</h2></div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="关闭原图预览"><X size={22} /></button>
        </header>
        <div className="customer-image-lightbox-body">
          <figure><OriginalPreview image={image} /></figure>
          <aside>
            <h3>原始文件</h3>
            <dl>
              <div><dt>渠道来源</dt><dd>{channelLabel(image.channel)}</dd></div>
              <div><dt>接收时间</dt><dd>{fullTime.format(new Date(image.received_at))}</dd></div>
              <div><dt>原始格式</dt><dd>{formatLabel(image.mime_type, image.original_name)}</dd></div>
              <div><dt>像素尺寸</dt><dd>{image.width && image.height ? `${image.width} × ${image.height}` : "原格式未提供"}</dd></div>
              <div><dt>文件大小</dt><dd>{fileSize(image.file_size)}</dd></div>
              <div><dt>归档状态</dt><dd>已归档</dd></div>
            </dl>
            <div className="customer-image-integrity"><ShieldCheck size={19} weight="fill" /><span><b>SHA-256 已校验</b><small>原图保存，不压缩、不识别</small></span></div>
          </aside>
        </div>
        <footer>
          <div>
            <a className="primary" href={image.download_url}><DownloadSimple size={18} />下载原图</a>
            <button type="button" onClick={() => onOpenConversation(image.conversation_id)}><ArrowLeft size={17} />返回对应会话</button>
          </div>
          <button type="button" className="danger" disabled={deleting} onClick={() => void remove()}><Trash size={17} />{deleting ? "正在删除" : "删除本地副本"}</button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}

function HistoryRecoveryDialog({
  open,
  onClose,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged: (message: string) => void;
}) {
  const [preview, setPreview] = useState<CustomerImageHistoryPreview | null>(null);
  const [attention, setAttention] = useState<CustomerImageAttentionItem[]>([]);
  const [archiveStatus, setArchiveStatus] = useState<CustomerImageArchiveStatus | null>(null);
  const [lastResult, setLastResult] = useState<CustomerImageHistoryResult | null>(null);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const dialogRef = useDialogFocus(open, onClose);

  const load = useCallback(async () => {
    try {
      const [nextPreview, nextAttention, nextStatus] = await Promise.all([
        localPlatformService.previewCustomerImageHistory(),
        localPlatformService.customerImageAttention(),
        localPlatformService.customerImageStatus(),
      ]);
      setPreview(nextPreview);
      setAttention(nextAttention);
      setArchiveStatus(nextStatus);
      setError("");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "历史图片状态读取失败");
    }
  }, []);

  useEffect(() => { if (open) void load(); }, [load, open]);
  if (!open) return null;

  const recover = async () => {
    if (!preview?.candidate_count || !preview.can_recover) return;
    setWorking("recover");
    setError("");
    try {
      const result = await localPlatformService.recoverCustomerImageHistory(requestId("customer_image"));
      setLastResult(result);
      await load();
      onChanged(result.stored_count ? `已恢复 ${result.stored_count} 张客户原图` : result.action_hint);
    } catch (recoverError) {
      setError(recoverError instanceof Error ? recoverError.message : "历史图片恢复失败");
    } finally {
      setWorking("");
    }
  };

  const groups = Array.from(attention.reduce((map, item) => {
    const current = map.get(item.conversation_id);
    if (current) {
      current.count += 1;
      if (new Date(item.received_at) > new Date(current.received_at)) current.received_at = item.received_at;
    } else {
      map.set(item.conversation_id, { ...item, count: 1 });
    }
    return map;
  }, new Map<number, CustomerImageAttentionItem & { count: number }>()).values());

  const openConnectionSettings = () => {
    onClose();
    window.location.hash = encodeURIComponent("设置中心/渠道连接");
  };

  return createPortal(
    <div className="customer-image-history-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="customer-image-history-dialog" role="dialog" aria-modal="true" aria-labelledby="customer-image-history-title" ref={dialogRef}>
        <header>
          <div><small>AUTOMATIC RECOVERY</small><h2 id="customer-image-history-title">历史图片自动恢复</h2><p>用户点击后，只匹配本地已有的客户图片占位</p></div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="关闭历史图片自动恢复"><X size={21} /></button>
        </header>
        <div className={`customer-image-connection-state ${preview?.can_recover ? "is-ready" : "is-offline"}`}>
          {preview?.can_recover ? <CheckCircle size={24} weight="fill" /> : <WarningCircle size={24} weight="fill" />}
          <span><small>{preview?.can_recover ? "闲鱼连接已恢复" : "闲鱼连接尚未恢复"}</small><b>{preview?.can_recover ? `可读取 ${preview.related_conversation_count} 个相关会话` : "自动恢复当前不可用"}</b><p>不会读取无本地占位的其他会话，不发送消息、不调用 AI。</p></span>
          <em>{preview?.connection_status || "unknown"}</em>
        </div>
        <div className="customer-image-history-summary">
          <FileImage size={27} weight="duotone" />
          <span><b>{preview?.candidate_count ?? "—"} 张客户原图等待自动恢复</b><small>每个相关会话最多读取最近 200 条平台消息</small></span>
          <div className="customer-image-history-stats"><span><small>相关会话</small><b>{preview?.related_conversation_count ?? "—"}</b></span><span><small>已有原图</small><b>{archiveStatus?.stored_count ?? "—"}</b></span><span><small>待匹配</small><b>{preview?.candidate_count ?? "—"}</b></span></div>
          {preview?.can_recover ? <button type="button" disabled={Boolean(working) || !preview?.candidate_count} onClick={() => void recover()}><ArrowClockwise size={17} className={working === "recover" ? "spin" : ""} />{working === "recover" ? "正在按会话恢复" : `自动恢复 ${preview.candidate_count} 张`}</button> : <button type="button" onClick={openConnectionSettings}>先恢复闲鱼连接</button>}
        </div>
        <p className="customer-image-history-boundary">未连接时只跳转设置中心，不自动修复连接；连接恢复后仍需点击本页按钮才会采集。</p>
        {error && <div className="customer-image-history-error" role="alert"><WarningCircle size={17} weight="fill" />{error}</div>}
        {lastResult && <div className={`customer-image-history-result ${lastResult.stopped_early ? "is-stopped" : ""}`} role="status"><b>{lastResult.action_hint}</b><small>已检查 {lastResult.checked_conversation_count}/{lastResult.conversation_count} 个会话 · 恢复 {lastResult.stored_count} 张 · 未匹配 {lastResult.unmatched_count} 张</small></div>}
        <div className="customer-image-attention-list" aria-label="等待自动恢复的客户图片会话">
          <header><b>待处理会话</b><small>不再要求逐张选择本地文件</small></header>
          {groups.map((item) => <article key={item.conversation_id}>
            <span className={`channel-dot ${item.channel}`}><ImageSquare size={18} weight="duotone" /></span>
            <div><b>{item.customer_name}</b><small>{channelLabel(item.channel)} · {fullTime.format(new Date(item.received_at))}</small></div>
            <em>{item.count} 张待恢复</em>
            <strong>{working === "recover" ? "正在串行检查" : "等待采集"}</strong>
          </article>)}
          {!attention.length && preview && <div className="customer-image-history-empty"><CheckCircle size={26} weight="duotone" /><b>没有待恢复的客户图片</b><small>后续收到的入站图片会自动保存原图。</small></div>}
        </div>
        <footer><span><ShieldCheck size={16} weight="fill" />原始字节归档，不压缩、不旋转、不 OCR、不进入 Agent</span><small>遇到登录、验证或连接错误立即停止，不自动重试</small></footer>
      </div>
    </div>,
    document.body,
  );
}

export function CustomerImageLibrary({
  onOpenConversation,
}: {
  onOpenConversation: (conversationId: number) => void;
}) {
  const [images, setImages] = useState<CustomerImageArchiveView[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [status, setStatus] = useState<CustomerImageArchiveStatus | null>(null);
  const [filters, setFilters] = useState<CustomerImageFilters>({ channels: [], conversations: [] });
  const [channel, setChannel] = useState("all");
  const [conversationId, setConversationId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<CustomerImageArchiveView | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const loadedCountRef = useRef(0);
  const dateDetailsRef = useRef<HTMLDetailsElement>(null);

  const showNotice = useCallback((message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3200);
  }, []);

  const load = useCallback(async (append = false) => {
    append ? setLoadingMore(true) : setLoading(true);
    try {
      const offset = append ? loadedCountRef.current : 0;
      const [result, nextStatus, nextFilters] = await Promise.all([
        localPlatformService.customerImages({
          channel,
          conversationId: conversationId ? Number(conversationId) : null,
          dateFrom,
          dateTo,
          limit: 100,
          offset,
        }),
        localPlatformService.customerImageStatus(),
        localPlatformService.customerImageFilters(),
      ]);
      setImages((current) => append ? [...current, ...result.items] : result.items);
      loadedCountRef.current = append
        ? loadedCountRef.current + result.items.length
        : result.items.length;
      setTotal(result.total);
      setHasMore(result.has_more);
      setStatus(nextStatus);
      setFilters(nextFilters);
      setError("");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "图片库读取失败");
      if (!append) setImages([]);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [channel, conversationId, dateFrom, dateTo]);

  useEffect(() => { void load(false); }, [load]);
  useEffect(() => connectPlatformEvents((event) => {
    if (["new_reply", "customer_image_archived", "customer_image_deleted", "conversation_history_imported"].includes(String(event.type))) void load(false);
  }), [load]);
  useEffect(() => {
    const closeDateFilter = (event: MouseEvent | globalThis.KeyboardEvent) => {
      const details = dateDetailsRef.current;
      if (!details?.open) return;
      if (event instanceof globalThis.KeyboardEvent) {
        if (event.key !== "Escape") return;
      } else if (event.target instanceof Node && details.contains(event.target)) {
        return;
      }
      details.removeAttribute("open");
      if (event instanceof globalThis.KeyboardEvent) details.querySelector<HTMLElement>("summary")?.focus();
    };
    document.addEventListener("mousedown", closeDateFilter);
    document.addEventListener("keydown", closeDateFilter);
    return () => {
      document.removeEventListener("mousedown", closeDateFilter);
      document.removeEventListener("keydown", closeDateFilter);
    };
  }, []);

  const visibleImages = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("zh-CN");
    if (!query) return images;
    return images.filter((image) => `${image.customer_name} ${image.original_name} ${channelLabel(image.channel)}`.toLocaleLowerCase("zh-CN").includes(query));
  }, [images, search]);

  const openFromKeyboard = (event: ReactKeyboardEvent<HTMLButtonElement>, image: CustomerImageArchiveView) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setSelected(image);
    }
  };

  return <section className="customer-image-library" aria-label="客户图片库">
    <div className={`customer-image-archive-status ${status?.state || "loading"}`}>
      {status?.state === "needs_attention" ? <WarningCircle size={18} weight="fill" /> : <ShieldCheck size={18} weight="fill" />}
      <span><b>{status?.state === "needs_attention" ? status.message : "自动归档正常"}</b><small>原图保存，不压缩、不识别、不进入 AI 分析</small></span>
      <button type="button" onClick={() => void load(false)} aria-label="刷新图片归档状态"><ArrowClockwise size={17} /></button>
    </div>

    <header className="customer-image-toolbar">
      <label className="customer-image-search"><ImageSquare size={18} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索图片" aria-label="搜索图片" /></label>
      <select value={channel} onChange={(event) => { setChannel(event.target.value); setConversationId(""); }} aria-label="按渠道筛选">
        <option value="all">全部渠道</option><option value="xianyu">闲鱼</option><option value="wechat">微信</option>
      </select>
      <select value={conversationId} onChange={(event) => setConversationId(event.target.value)} aria-label="按客户筛选">
        <option value="">全部客户</option>
        {filters.conversations.filter((item) => channel === "all" || item.channel === channel).map((item) => <option value={item.id} key={item.id}>{item.customer_name} · {item.image_count} 张</option>)}
      </select>
      <details className="customer-image-date-filter" ref={dateDetailsRef}>
        <summary aria-label="按日期筛选客户图片"><CalendarBlank size={17} /><span>{dateFrom || dateTo ? `${dateFrom || "起始"} 至 ${dateTo || "今天"}` : "全部日期"}</span></summary>
        <div className="customer-image-date-popover">
          <label><span>开始日期</span><input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} aria-label="开始日期" /></label>
          <label><span>结束日期</span><input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} aria-label="结束日期" /></label>
          <footer>
            <button type="button" onClick={() => { setDateFrom(""); setDateTo(""); }}>清除日期</button>
            <button type="button" className="primary" onClick={(event) => event.currentTarget.closest("details")?.removeAttribute("open")}>完成</button>
          </footer>
        </div>
      </details>
      <button type="button" className="customer-image-history-button" onClick={() => setHistoryOpen(true)}><ArrowClockwise size={17} />历史图片自动恢复{status?.attention_count ? <i>{status.attention_count}</i> : null}</button>
    </header>

    {error && <div className="customer-image-library-error" role="alert"><WarningCircle size={18} weight="fill" /><span>{error}</span><button type="button" onClick={() => void load(false)}>重试</button></div>}
    {!error && loading && <div className="customer-image-library-loading"><ArrowClockwise size={22} className="spin" />正在读取本地原图…</div>}
    {!error && !loading && !visibleImages.length && <div className="customer-image-library-empty">
      <span><ImageSquare size={35} weight="duotone" /></span>
      <h2>{images.length ? "没有符合筛选条件的图片" : "图片库还没有原图"}</h2>
      <p>{images.length ? "调整搜索、渠道、客户或日期后再查看。" : "后续客户发来的图片会自动保存在独立原图目录；连接恢复后可点击自动匹配历史占位。"}</p>
      {images.length ? <button type="button" onClick={() => { setSearch(""); setChannel("all"); setConversationId(""); setDateFrom(""); setDateTo(""); }}><Funnel size={16} />清除筛选</button> : <button type="button" onClick={() => setHistoryOpen(true)}><ArrowClockwise size={16} />历史图片自动恢复</button>}
    </div>}

    {!loading && visibleImages.length > 0 && <>
      <div className="customer-image-grid" aria-label={`共 ${total} 张客户原图`}>
        {visibleImages.map((image) => <button type="button" className="customer-image-card" onClick={() => setSelected(image)} onKeyDown={(event) => openFromKeyboard(event, image)} key={image.id}>
          <span className="customer-image-frame"><OriginalPreview image={image} compact /></span>
          <span className="customer-image-meta"><time>{imageTime.format(new Date(image.received_at))}</time><em className={image.channel}>{channelLabel(image.channel)}</em></span>
        </button>)}
      </div>
      {hasMore && <button type="button" className="customer-image-load-more" disabled={loadingMore} onClick={() => void load(true)}>{loadingMore ? <ArrowClockwise size={17} className="spin" /> : <ImageSquare size={17} />}{loadingMore ? "正在载入" : "查看更多原图"}</button>}
      <button type="button" className="customer-image-history-button-mobile" onClick={() => setHistoryOpen(true)}><ArrowClockwise size={19} />历史图片自动恢复{status?.attention_count ? <i>{status.attention_count}</i> : null}</button>
    </>}

    <ImageLightbox image={selected} onClose={() => setSelected(null)} onOpenConversation={(id) => { setSelected(null); onOpenConversation(id); }} onDeleted={(id) => { setImages((current) => current.filter((image) => image.id !== id)); loadedCountRef.current = Math.max(0, loadedCountRef.current - 1); setTotal((value) => Math.max(0, value - 1)); showNotice("本地原图副本已删除，聊天消息仍保留"); }} />
    <HistoryRecoveryDialog open={historyOpen} onClose={() => setHistoryOpen(false)} onChanged={(message) => { showNotice(message); void load(false); }} />
    {notice && <div className="customer-image-notice" role="status"><CheckCircle size={18} weight="fill" />{notice}</div>}
  </section>;
}
