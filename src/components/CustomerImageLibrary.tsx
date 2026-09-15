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
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { createPortal } from "react-dom";
import {
  localPlatformService,
  type CustomerImageArchiveStatus,
  type CustomerImageArchiveView,
  type CustomerImageFilters,
} from "../data/localPlatformService";
import { subscribeCustomerEvents } from "../data/customerEvents";
import { customerImageError } from "../data/customerImageErrors";
import "./customer-image-library.css";
import { ImageViewport } from './ImageViewport';


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

export function OriginalPreview({
  image,
  compact = false,
}: {
  image: CustomerImageArchiveView;
  compact?: boolean;
}) {
  const [unavailable, setUnavailable] = useState(false);
  const [failureReason, setFailureReason] = useState("");
  const state = image.capture_status || image.status || "stored";
  useEffect(() => { setUnavailable(false); setFailureReason(""); }, [image.id, image.preview_url]);
  if (state !== "stored" && state !== "completed") return <span className="customer-image-format-fallback"><FileImage size={26} /><b>{state === "pending" || state === "capturing" ? "图片正在归档" : state === "deleted" ? "图片已由用户删除" : "图片归档失败"}</b><small>{customerImageError(image.error_code, image.error_message)}</small></span>;
  if (unavailable) {
    return <span className={`customer-image-format-fallback ${compact ? "is-compact" : ""}`}>
      <FileImage size={compact ? 26 : 38} weight="duotone" />
      <b>{formatLabel(image.mime_type, image.original_name)} 原图</b>
      <small>{failureReason || "预览读取失败，可下载原图；原文件缺失或格式问题请查看归档状态"}</small>
    </span>;
  }
  return <img
    src={image.preview_url || image.content_url}
    loading={compact ? "lazy" : "eager"}
    alt={image.preview_url ? "客户图片兼容预览（原图保持不变）" : "客户发送的原图"}
    onError={() => { setUnavailable(true); if (image.preview_url) void fetch(image.preview_url).then(async (response) => { if (response.ok) return; const data = await response.json().catch(() => null); setFailureReason(data?.detail?.message || data?.detail?.code || `预览读取失败（${response.status}）`); }).catch(() => setFailureReason("本地预览连接失败")); }}
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
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), summary, [tabindex]:not([tabindex='-1'])")).filter(el => el.checkVisibility());
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

export function ImageLightbox({
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
          <div><h2 id="customer-image-lightbox-title">图片查看</h2></div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="关闭原图预览"><X size={22} /></button>
        </header>
        <div className="customer-image-lightbox-body">
          <ImageViewport key={image.id}><OriginalPreview image={image} /></ImageViewport>
          <details className="image-viewer-info">
            <summary>图片信息 · {formatLabel(image.mime_type, image.original_name)} · {fileSize(image.file_size)}</summary>
            <dl>
              <div><dt>渠道来源</dt><dd>{channelLabel(image.channel)}</dd></div>
              <div><dt>接收时间</dt><dd>{fullTime.format(new Date(image.received_at))}</dd></div>
              <div><dt>原始格式</dt><dd>{formatLabel(image.mime_type, image.original_name)}</dd></div>
              <div><dt>像素尺寸</dt><dd>{image.width && image.height ? `${image.width} × ${image.height}` : "原格式未提供"}</dd></div>
              <div><dt>文件大小</dt><dd>{fileSize(image.file_size)}</dd></div>
              <div><dt>归档状态</dt><dd>{image.capture_status === "failed" ? customerImageError(image.error_code, image.error_message) : image.capture_status === "pending" ? "等待归档" : "已归档"}</dd></div>
            </dl>
            <div className="customer-image-integrity"><ShieldCheck size={19} weight="fill" /><span><b>{image.integrity_verified ? "SHA-256 已校验" : "等待完整性核验"}</b><small>{image.preview_url ? "展示兼容副本；下载文件仍为原图" : "原图保存，不压缩、不识别"}</small></span></div>
          </details>
        </div>
        <footer>
          <div>
            {(!image.capture_status || image.capture_status === "stored") && <a className="primary" href={image.download_url}><DownloadSimple size={18} />下载原图</a>}
            <button type="button" onClick={() => onOpenConversation(image.conversation_id)}><ArrowLeft size={17} />返回对应会话</button>
          </div>
          <details className="image-viewer-more"><summary>更多</summary><button type="button" className="danger" disabled={deleting} onClick={() => void remove()}><Trash size={17} />{deleting ? "正在删除" : "删除本地副本"}</button></details>
        </footer>
      </div>
    </div>,
    document.body,
  );
}

export function CustomerImageLibrary({
  onOpenConversation,
  initialConversationId = null,
  scoped = false,
  onSyncHistory,
}: {
  onOpenConversation: (conversationId: number) => void;
  initialConversationId?: number | null;
  scoped?: boolean;
  onSyncHistory?: () => void;
}) {
  const [images, setImages] = useState<CustomerImageArchiveView[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [status, setStatus] = useState<CustomerImageArchiveStatus | null>(null);
  const [filters, setFilters] = useState<CustomerImageFilters>({ channels: [], conversations: [] });
  const [channel, setChannel] = useState("all");
  const [conversationId, setConversationId] = useState(initialConversationId ? String(initialConversationId) : "");
  const [itemId, setItemId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<CustomerImageArchiveView | null>(null);
  const [notice, setNotice] = useState("");
  const loadedCountRef = useRef(0);
  const dateDetailsRef = useRef<HTMLDetailsElement>(null);
  const loadVersion = useRef(0);
  const syncHistory = () => onSyncHistory ? onSyncHistory() : setNotice("请从客户会话的同步历史入口选择范围");

  const showNotice = useCallback((message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3200);
  }, []);

  const load = useCallback(async (append = false) => {
    const version = ++loadVersion.current;
    append ? setLoadingMore(true) : setLoading(true);
    try {
      const offset = append ? loadedCountRef.current : 0;
      const [result, nextStatus, nextFilters] = await Promise.all([
        localPlatformService.customerImages({
          channel,
          conversationId: scoped ? initialConversationId : conversationId ? Number(conversationId) : null,
          dateFrom,
          dateTo,
          limit: 100,
          offset,
          search,
          itemId,
        }),
        localPlatformService.customerImageStatus(),
        localPlatformService.customerImageFilters(),
      ]);
      if (version !== loadVersion.current) return;
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
      if (version !== loadVersion.current) return;
      setError(loadError instanceof Error ? loadError.message : "图片库读取失败");
      if (!append) setImages([]);
    } finally {
      if (version === loadVersion.current) { setLoading(false); setLoadingMore(false); }
    }
  }, [channel, conversationId, dateFrom, dateTo, search, itemId, scoped, initialConversationId]);

  useEffect(() => { void load(false); }, [load]);
  useEffect(() => subscribeCustomerEvents(() => void load(false)), [load]);
  useEffect(() => () => { loadVersion.current += 1; }, []);
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

  const visibleImages = images;

  const openFromKeyboard = (event: ReactKeyboardEvent<HTMLButtonElement>, image: CustomerImageArchiveView) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setSelected(image);
    }
  };

  return <section className={`customer-image-library${scoped ? ' is-scoped' : ''}`} aria-label="客户图片库">
    <div className={`customer-image-archive-status ${status?.state || "loading"}`}>
      {status?.state === "needs_attention" ? <WarningCircle size={18} weight="fill" /> : <ShieldCheck size={18} weight="fill" />}
      <span><b>{status ? status.message || (status.state === "healthy" ? "自动归档正常" : "归档需要处理") : "正在读取归档状态"}</b><small>原图保持不变 · 外部图片读取需单独授权</small></span>
      <button type="button" onClick={() => void load(false)} aria-label="刷新图片归档状态"><ArrowClockwise size={17} /></button>
    </div>

    <header className="customer-image-toolbar">
      <label className="customer-image-search"><ImageSquare size={18} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索图片" aria-label="搜索图片" /></label>
      {!scoped && <select value={channel} onChange={(event) => { setChannel(event.target.value); setConversationId(""); }} aria-label="按渠道筛选">
        <option value="all">全部渠道</option><option value="xianyu">闲鱼</option><option value="wechat">微信</option>
      </select>}
      {Boolean(filters.items?.length) && <select value={itemId} onChange={(event) => setItemId(event.target.value)} aria-label="按商品筛选"><option value="">全部商品</option>{filters.items?.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select>}
      {!scoped && <select value={conversationId} onChange={(event) => setConversationId(event.target.value)} aria-label="按客户筛选">
        <option value="">全部客户</option>
        {filters.conversations.filter((item) => channel === "all" || item.channel === channel).map((item) => <option value={item.id} key={item.id}>{item.customer_name} · {item.image_count} 张</option>)}
      </select>}
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
      {!scoped && <button type="button" className="customer-image-history-button" onClick={syncHistory}><ArrowClockwise size={17} />同步历史{status?.attention_count ? <i>{status.attention_count}</i> : null}</button>}
    </header>

    {error && <div className="customer-image-library-error" role="alert"><WarningCircle size={18} weight="fill" /><span>{error}</span><button type="button" onClick={() => void load(false)}>重试</button></div>}
    {!error && loading && <div className="customer-image-library-loading"><ArrowClockwise size={22} className="spin" />正在读取本地原图…</div>}
    {!error && !loading && !visibleImages.length && <div className="customer-image-library-empty">
      <span><ImageSquare size={35} weight="duotone" /></span>
      <h2>{search || conversationId || dateFrom || dateTo || itemId ? "没有符合筛选条件的图片" : "图片库还没有原图"}</h2>
      <p>搜索覆盖全部归档记录；可调整客户、商品、日期，或主动同步历史消息与图片。</p>
      <button type="button" onClick={() => { setSearch(""); setChannel("all"); setConversationId(""); setItemId(""); setDateFrom(""); setDateTo(""); }}><Funnel size={16} />清除筛选</button>{!scoped && <button type="button" onClick={syncHistory}><ArrowClockwise size={16} />同步历史</button>}
    </div>}

    {!loading && visibleImages.length > 0 && <>
      <div className="customer-image-grid" aria-label={`共 ${total} 张客户原图`}>
        {visibleImages.map((image) => <button type="button" className="customer-image-card" onClick={() => setSelected(image)} onKeyDown={(event) => openFromKeyboard(event, image)} key={image.id}>
          <span className="customer-image-frame"><OriginalPreview image={image} compact /></span>
          <span className="customer-image-meta"><time>{imageTime.format(new Date(image.received_at))}</time><em className={image.channel}>{channelLabel(image.channel)}</em></span>
        </button>)}
      </div>
      {hasMore && <button type="button" className="customer-image-load-more" disabled={loadingMore} onClick={() => void load(true)}>{loadingMore ? <ArrowClockwise size={17} className="spin" /> : <ImageSquare size={17} />}{loadingMore ? "正在载入" : "查看更多原图"}</button>}
      {!scoped && <button type="button" className="customer-image-history-button-mobile" onClick={syncHistory}><ArrowClockwise size={19} />同步历史{status?.attention_count ? <i>{status.attention_count}</i> : null}</button>}
    </>}

    <ImageLightbox image={selected} onClose={() => setSelected(null)} onOpenConversation={(id) => { setSelected(null); onOpenConversation(id); }} onDeleted={(id) => { setImages((current) => current.filter((image) => image.id !== id)); loadedCountRef.current = Math.max(0, loadedCountRef.current - 1); setTotal((value) => Math.max(0, value - 1)); showNotice("本地原图副本已删除，聊天消息仍保留"); }} />
    {notice && <div className="customer-image-notice" role="status"><CheckCircle size={18} weight="fill" />{notice}</div>}
  </section>;
}
