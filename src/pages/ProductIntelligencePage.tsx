import {
  ArrowClockwise,
  ArrowCounterClockwise,
  ArrowRight,
  BellRinging,
  CalendarCheck,
  CaretRight,
  ChartLineUp,
  ChatCircleDots,
  CheckCircle,
  ClipboardText,
  Clock,
  Coins,
  Eye,
  EyeSlash,
  Flask,
  FolderOpen,
  Gauge,
  Info,
  ListChecks,
  Lightbulb,
  LockSimple,
  LockSimpleOpen,
  MagnifyingGlass,
  Megaphone,
  Package,
  PauseCircle,
  PencilSimple,
  Play,
  Plus,
  ShieldCheck,
  Sparkle,
  Storefront,
  Target,
  Timer,
  TrendUp,
  UploadSimple,
  Warning,
  X,
} from "@phosphor-icons/react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import {
  connectPlatformEvents,
  localPlatformService,
  type ProductIntelligenceView,
  type ProductCollectionAttemptView,
  type ProductModificationExperimentView,
  type ProductModificationSuggestionView,
  type ProductOperatingPlanSlotView,
  type ProductRecommendationView,
  type ProductTrafficBatchView,
  type ProductView,
} from "../data/localPlatformService";
import "./product-intelligence.css";


const integer = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
});
const moneyExact = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});
const dateTime = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Shanghai",
});

const actionLabels: Record<string, string> = {
  title: "修改标题",
  cover: "修改首图",
  description: "修改描述",
  price: "调整价格",
  republish: "重新发布",
  traffic: "人工投流测试",
  hold: "暂时保持",
  other: "其他经营动作",
};

const statusLabels: Record<string, string> = {
  success: "今日采集完成",
  partial: "今日部分完成",
  failed: "今日采集失败",
  running: "正在只读采集",
};

const confidenceLabels: Record<string, string> = {
  high: "高置信",
  medium: "中等置信",
  low: "低置信",
};

const launchActionLabels: Record<string, string> = {
  launch: "建议上新",
  modify_existing: "优先修改现有商品",
  observe: "继续观察",
};

const planActionLabels: Record<string, string> = {
  traffic: "安排多商品曝光",
  measure: "观察长尾效果",
  optimize: "先优化商品表达",
  delivery_guard: "保护交付容量",
  rest: "预算休息日",
  observe: "观察自然流量",
  prepare: "准备下一批次",
};

const checkpointLabels: Record<string, string> = {
  h1: "+1 小时",
  h6: "+6 小时",
  h24: "+24 小时",
  h72: "+72 小时",
};

const analysisStageLabels: Record<string, string> = {
  baseline_learning: "基线学习",
  controlled_learning: "对照学习",
  explore_exploit: "探索与利用",
};

const trafficDataQualityLabels: Record<string, string> = {
  planned: "等待开始",
  baseline: "仅有 T0",
  early: "早期观察",
  mature: "可比较成熟",
  missing_baseline: "缺少基线",
  stale_baseline: "基线过旧",
  inconsistent: "累计值异常",
  confounded: "批次重叠",
};

const ownershipLabels: Record<string, string> = {
  owned: "我的商品",
  pending: "等待验证",
  excluded: "已排除",
};

function isTodayInBeijing(value: string | null | undefined) {
  if (!value) return false;
  const formatter = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return formatter.format(parsePlatformDate(value)) === formatter.format(new Date());
}

function beijingDayKey(value: string) {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(parsePlatformDate(value));
}

function parsePlatformDate(value: string) {
  const hasTimezone = /(?:z|[+-]\d{2}:\d{2})$/i.test(value);
  const isDateTime = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value);
  return new Date(isDateTime && !hasTimezone ? `${value}Z` : value);
}

function collectionState(product: ProductView) {
  if (product.ownership_status === "excluded") return { key: "excluded", label: "已排除" };
  if (product.ownership_status === "pending") return { key: "pending", label: "等待验证" };
  if (product.last_collection_status === "failed") {
    const today = isTodayInBeijing(product.last_attempt_at);
    if (product.last_error_code === "access_verification") {
      return { key: "failed", label: today ? "今日未取得数据" : "最近未取得数据" };
    }
    return { key: "failed", label: today ? "今日失败" : "最近失败" };
  }
  if (product.last_collection_status === "success") return { key: "success", label: isTodayInBeijing(product.last_attempt_at) ? "今日成功" : "最近成功" };
  if (product.last_collection_status === "skipped") return { key: "skipped", label: "本次跳过" };
  return { key: "waiting", label: product.monitoring_enabled ? "等待采集" : "已暂停" };
}

function ProductCollectionBadge({ product }: { product: ProductView }) {
  const state = collectionState(product);
  return <em className={`product-collection-badge state-${state.key}`}>{state.label}</em>;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "尚未采集";
  const parsed = parsePlatformDate(value);
  return Number.isNaN(parsed.getTime()) ? value : dateTime.format(parsed);
}

function formatPlanDate(value: string) {
  const parsed = new Date(`${value}T00:00:00+08:00`);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    weekday: "short",
    timeZone: "Asia/Shanghai",
  }).format(parsed);
}

function toApiDateTime(value: string) {
  return new Date(`${value}:00+08:00`).toISOString();
}

function beijingLocalInput(value = new Date()) {
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(value);
  return parts.replace(" ", "T");
}

function collectionRunPresentation(data: ProductIntelligenceView) {
  const run = data.collection.latest_attempt || data.collection.last_run;
  if (!run) return null;
  if ("trigger" in run && run.trigger === "manual_single") {
    return {
      label: run.status === "success" ? "指定商品手动采集成功" : "指定商品手动采集未完成",
      detail: run.detail,
    };
  }
  if ("trigger" in run && run.trigger === "manual_all") {
    return {
      label: run.status === "success" ? "全部商品手动采集成功" : statusLabels[run.status] || run.status,
      detail: run.detail,
    };
  }
  const attemptedToday = [...data.products, ...data.candidates].filter(
    (product) => product.last_collection_status === "failed" && isTodayInBeijing(product.last_attempt_at),
  );
  const verificationCount = attemptedToday.filter(
    (product) => product.last_error_code === "access_verification",
  ).length;
  if (run.failed_count > 0 && verificationCount === run.failed_count) {
    const protectedBatch = run.detail.includes("为保护账号而跳过");
    return {
      label: "已停止采集以保护账号",
      detail: protectedBatch
        ? run.detail
        : `最近一次采集有 ${run.failed_count} 个商品触发访问验证；这条记录产生于批次熔断升级前。新版保护已启用：以后首件触发即停止，其余商品标记为保护性跳过。请先在现有 Edge 完成人工验证，更新本机连接并重启服务，再从单件采集开始。`,
    };
  }
  return {
    label: statusLabels[run.status] || run.status,
    detail: run.detail,
  };
}

const collectionTriggerLabels: Record<string, string> = {
  scheduled: "计划采集",
  manual: "计划采集",
  manual_all: "手动采集全部",
  manual_single: "指定商品手动采集",
};

function CollectionAttemptLog({ attempt }: { attempt: ProductCollectionAttemptView }) {
  const completedAt = attempt.finished_at || attempt.started_at;
  return <article className={`collection-attempt collection-attempt-${attempt.status}`}>
    <header>
      <i>{attempt.status === "success" ? <CheckCircle size={16} weight="fill" /> : <Warning size={16} weight="fill" />}</i>
      <span><b>{collectionTriggerLabels[attempt.trigger] || attempt.trigger}</b><small>{formatDate(completedAt)} · 北京时间</small></span>
      <em>{attempt.collected_count} 成功{attempt.failed_count ? ` · ${attempt.failed_count} 失败` : ""}{attempt.skipped_count ? ` · ${attempt.skipped_count} 跳过` : ""}</em>
    </header>
    <p>{attempt.detail}</p>
    {attempt.items.length > 0 && <ul>{attempt.items.map((item) => <li className={`state-${item.status}`} key={`${attempt.id}-${item.external_id}`}>
      <span><b>{item.title}</b><small>{item.detail}</small></span><em>{item.status === "success" ? "成功" : item.status === "skipped" ? "保护跳过" : item.status === "failed" ? "失败" : "等待"}</em>
    </li>)}</ul>}
  </article>;
}

function productDiagnosticDetail(product: ProductView) {
  if (
    product.last_error_code === "access_verification"
    && !product.last_error_detail?.includes("本批次已停止后续请求")
  ) {
    return "这条失败记录产生于批次熔断升级前。新版保护已启用：以后首件触发访问验证即停止，其余商品不会继续请求。请先在现有 Edge 完成人工验证，更新本机连接并重启服务，再从单件采集开始。";
  }
  return product.last_error_detail;
}

function ProductMetric({
  icon: Icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: typeof Package;
  label: string;
  value: string;
  detail: string;
  tone: string;
}) {
  return <article className={`product-metric product-tone-${tone}`}>
    <i><Icon size={22} weight="duotone" /></i>
    <span><small>{label}</small><strong>{value}</strong><em>{detail}</em></span>
  </article>;
}

function AttentionBadge({ value }: { value: string }) {
  const label = value === "high" ? "优先处理" : value === "medium" ? "建议关注" : "持续观察";
  return <span className={`product-attention product-attention-${value}`}>{label}</span>;
}

function ProductTrend({ product }: { product: ProductView }) {
  if (product.history.length < 2) {
    return <div className="product-trend-empty">
      <ChartLineUp size={34} weight="duotone" />
      <span><b>等待第二个数据点</b><small>自动或手动采集都会更新当天数据；每天仍只保留一个趋势点。</small></span>
    </div>;
  }
  return <div className="product-trend-chart" aria-label={`${product.title}经营浏览趋势`}>
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={product.history} margin={{ top: 12, right: 8, left: -22, bottom: 0 }}>
        <defs>
          <linearGradient id="productBrowseArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#684df4" stopOpacity={0.22} />
            <stop offset="100%" stopColor="#684df4" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="#e9eaf4" strokeDasharray="3 3" />
        <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "#8c91a5" }} />
        <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "#8c91a5" }} />
        <Tooltip formatter={(value) => [`${value} 次`, "经营浏览"]} />
        <Area type="monotone" dataKey="browse_count" stroke="#6544f4" strokeWidth={2.5} fill="url(#productBrowseArea)" />
      </AreaChart>
    </ResponsiveContainer>
  </div>;
}

function ExposureAnalytics({ data }: { data: ProductIntelligenceView }) {
  const analytics = data.exposure_analytics;
  const maxCheckpointBrowse = Math.max(
    1,
    ...analytics.checkpoints.map((checkpoint) => checkpoint.average_browse_delta),
  );
  const recent = data.traffic_batches
    .filter((batch) => batch.started_at)
    .slice(0, 3);
  const hasObservedData = analytics.checkpoints.length > 0 || recent.length > 0;

  return <section className="product-exposure-analytics" aria-labelledby="exposure-analytics-title">
    <header className="product-exposure-head">
      <div>
        <span className="product-eyebrow"><ChartLineUp size={14} weight="fill" /> EXPOSURE PERFORMANCE</span>
        <h3 id="exposure-analytics-title">曝光效果分析</h3>
        <p>{analytics.summary}</p>
      </div>
      <span className={`confidence-${analytics.confidence}`}><ShieldCheck size={14} weight="fill" />{confidenceLabels[analytics.confidence] || "低置信"} · 近 {analytics.window_days} 天</span>
    </header>

    <div className="product-exposure-kpis">
      <article><i><Coins size={18} weight="duotone" /></i><span><small>累计真实投入</small><b>{moneyExact.format(analytics.total_spent)}</b><em>开始批次后自动进入支出</em></span></article>
      <article><i><Eye size={18} weight="duotone" /></i><span><small>成熟浏览增量</small><b>+{integer.format(analytics.browse_delta)}</b><em>平均每批 +{integer.format(analytics.average_browse_delta)}</em></span></article>
      <article><i><ChatCircleDots size={18} weight="duotone" /></i><span><small>成熟咨询增量</small><b>+{integer.format(analytics.inquiry_delta)}</b><em>平均每批 +{analytics.average_inquiry_delta}</em></span></article>
      <article><i><TrendUp size={18} weight="duotone" /></i><span><small>浏览 → 咨询</small><b>{analytics.inquiry_conversion_rate === null ? "—" : `${analytics.inquiry_conversion_rate}%`}</b><em>仅统计可比较成熟批次</em></span></article>
      <article><i><Gauge size={18} weight="duotone" /></i><span><small>每新增咨询成本</small><b>{analytics.cost_per_inquiry === null ? "—" : moneyExact.format(analytics.cost_per_inquiry)}</b><em>{analytics.cost_per_browse === null ? "暂无浏览成本" : `每浏览 ${moneyExact.format(analytics.cost_per_browse)}`}</em></span></article>
      <article><i><Clock size={18} weight="duotone" /></i><span><small>当前优先时段</small><b>{analytics.best_time_bucket || "样本不足"}</b><em>{analytics.eligible_batch_count} 批纳入 · {analytics.excluded_batch_count} 批排除</em></span></article>
    </div>

    {hasObservedData ? <div className="product-exposure-body">
      <section className="exposure-checkpoint-card" aria-labelledby="checkpoint-growth-title">
        <header><span><small>LONG-TAIL GROWTH</small><h4 id="checkpoint-growth-title">套餐结束后的增长轨迹</h4></span><em>不同检查点按各自有效批次数求平均</em></header>
        <div className="exposure-checkpoint-list">
          {(["h1", "h6", "h24", "h72"] as const).map((checkpointName) => {
            const checkpoint = analytics.checkpoints.find((value) => value.checkpoint === checkpointName);
            const width = checkpoint ? Math.max(5, checkpoint.average_browse_delta / maxCheckpointBrowse * 100) : 0;
            return <article className={checkpointName === "h24" || checkpointName === "h72" ? "mature" : ""} key={checkpointName}>
              <span><b>{checkpointLabels[checkpointName]}</b><small>{checkpoint ? `${checkpoint.batch_count} 个有效数据点` : "等待记录"}</small></span>
              <div><i style={{ width: `${width}%` }} /></div>
              <strong>{checkpoint ? `+${integer.format(checkpoint.average_browse_delta)}` : "—"}<small>平均浏览</small></strong>
              <strong>{checkpoint ? `+${checkpoint.average_inquiry_delta}` : "—"}<small>平均咨询</small></strong>
            </article>;
          })}
        </div>
        <p><Timer size={15} weight="duotone" />1h / 6h 只看过程，24h / 72h 才进入经营结论；这些是 T0 后观察增量，不等同于平台因果归因，因此还会结合自然基线、重叠批次和样本量审查。</p>
      </section>

      <section className="exposure-time-card" aria-labelledby="time-comparison-title">
        <header><span><small>BEIJING TIME WINDOWS</small><h4 id="time-comparison-title">投放时段对比</h4></span><em>按开始时间归入 2 小时窗口</em></header>
        {analytics.time_buckets.length ? <div className="exposure-time-list">
          {analytics.time_buckets.slice(0, 5).map((bucket, index) => <article className={bucket.recommended ? "recommended" : ""} key={bucket.bucket}>
            <i>{index + 1}</i>
            <span><b>{bucket.time_range}{bucket.recommended && <em>当前优先</em>}</b><small>{bucket.batch_count} 批 · 投入 {moneyExact.format(bucket.total_cost)}</small></span>
            <strong>+{bucket.average_browse_delta}<small>平均浏览</small></strong>
            <strong>+{bucket.average_inquiry_delta}<small>平均咨询</small></strong>
            <strong>{bucket.cost_per_inquiry === null ? "—" : moneyExact.format(bucket.cost_per_inquiry)}<small>每咨询成本</small></strong>
          </article>)}
        </div> : <div className="exposure-time-empty"><Clock size={28} weight="duotone" /><span><b>还不能比较时段</b><small>至少需要 2 个无重叠且达到 24h / 72h 的批次；同一时段重复验证后才会标记优先。</small></span></div>}
      </section>
    </div> : <div className="product-exposure-empty">
      <ChartLineUp size={36} weight="duotone" />
      <span><b>开始真实批次后再分析</b><small>系统不会添加示例效果。开始投放会记录支出，补齐 1h、6h、24h、72h 后才形成自己的投入规律。</small></span>
    </div>}

    {recent.length > 0 && <div className="exposure-recent-batches" aria-label="最近曝光批次效果">
      <strong>最近批次</strong>
      {recent.map((batch) => <article key={batch.id}>
        <span><small>{formatDate(batch.started_at)} · {batch.products.length} 件</small><b>{batch.products.map((product) => product.title).join("、")}</b></span>
        <em className={`quality-${batch.data_quality}`}>{trafficDataQualityLabels[batch.data_quality] || batch.data_quality}</em>
        <strong>+{integer.format(batch.browse_delta)}<small>浏览</small></strong>
        <strong>+{integer.format(batch.inquiry_delta)}<small>咨询</small></strong>
        <strong>{batch.cost_per_inquiry === null ? "—" : moneyExact.format(batch.cost_per_inquiry)}<small>每咨询</small></strong>
      </article>)}
    </div>}
  </section>;
}

interface BatchDraftState {
  slotId: string | null;
  selectedIds: string[];
  plannedLocal: string;
  cost: string;
  note: string;
}

interface BatchOperationState {
  batch: ProductTrafficBatchView;
  mode: "complete" | "checkpoint";
  checkpoint: "h1" | "h6" | "h24" | "h72";
  cost: string;
  totalExposure: string;
  note: string;
  rows: Record<string, {
    browse_count: string;
    collect_count: string;
    want_count: string;
    inquiry_count: string;
  }>;
}

export type ProductWorkspaceTab = "overview" | "exposure" | "launch" | "market";
type ProductRouteFocus = "collection" | "product" | "batch" | "update" | "plan" | "recommendation" | "experiment";

interface ProductWorkspaceRoute {
  view: ProductWorkspaceTab;
  focus: ProductRouteFocus | null;
  targetId: string | null;
}

const productWorkspaceTabs: ProductWorkspaceTab[] = ["overview", "exposure", "launch", "market"];
const productRouteFocuses: ProductRouteFocus[] = ["collection", "product", "batch", "update", "plan", "recommendation", "experiment"];

function readProductWorkspaceRoute(): ProductWorkspaceRoute {
  let value = "";
  try {
    value = decodeURIComponent(window.location.hash.replace(/^#/, ""));
  } catch {
    value = "";
  }
  const [page, rawView, rawFocus, rawTargetId] = value.split("/");
  const view = page === "商品经营" && productWorkspaceTabs.includes(rawView as ProductWorkspaceTab)
    ? rawView as ProductWorkspaceTab
    : "overview";
  const focus = page === "商品经营" && productRouteFocuses.includes(rawFocus as ProductRouteFocus)
    ? rawFocus as ProductRouteFocus
    : null;
  return { view, focus, targetId: rawTargetId || null };
}

function productWorkspaceHash(route: ProductWorkspaceRoute) {
  const parts = ["商品经营", route.view];
  if (route.focus) parts.push(route.focus);
  if (route.targetId) parts.push(route.targetId);
  return `#${encodeURIComponent(parts.join("/"))}`;
}

interface ModificationDraftState {
  suggestion: ProductModificationSuggestionView;
  variable: "title" | "cover" | "description" | "price";
  beforeValue: string;
  afterValue: string;
}

export function ProductIntelligencePage({ globalSearch = "" }: { globalSearch?: string }) {
  const initialRoute = readProductWorkspaceRoute();
  const [data, setData] = useState<ProductIntelligenceView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [collectionLogOpen, setCollectionLogOpen] = useState(false);
  const [collectingScope, setCollectingScope] = useState<"all" | string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [managementOpen, setManagementOpen] = useState(false);
  const [managementTab, setManagementTab] = useState<"owned" | "pending" | "excluded">("owned");
  const [registerReference, setRegisterReference] = useState("");
  const [actionTarget, setActionTarget] = useState<{ product: ProductView; recommendation: ProductRecommendationView | null } | null>(null);
  const [actionType, setActionType] = useState("title");
  const [actionNote, setActionNote] = useState("");
  const [actionCost, setActionCost] = useState("");
  const [activePlanSlotId, setActivePlanSlotId] = useState<string | null>(null);
  const [batchDraft, setBatchDraft] = useState<BatchDraftState | null>(null);
  const [batchOperation, setBatchOperation] = useState<BatchOperationState | null>(null);
  const [toast, setToast] = useState("");
  const [activeView, setActiveView] = useState<ProductWorkspaceTab>(initialRoute.view);
  const [routeTarget, setRouteTarget] = useState<ProductWorkspaceRoute>(initialRoute);
  const [keywordMode, setKeywordMode] = useState<"recommended" | "custom">("recommended");
  const [customKeyword, setCustomKeyword] = useState("");
  const [saveCommonKeyword, setSaveCommonKeyword] = useState(false);
  const [marketImportOpen, setMarketImportOpen] = useState(false);
  const [marketImportText, setMarketImportText] = useState("");
  const [marketImportNote, setMarketImportNote] = useState("");
  const [modificationDraft, setModificationDraft] = useState<ModificationDraftState | null>(null);
  const [experimentDecision, setExperimentDecision] = useState<ProductModificationExperimentView | null>(null);
  const [experimentNote, setExperimentNote] = useState("");

  const navigateWorkspace = (
    view: ProductWorkspaceTab,
    focus: ProductRouteFocus | null = null,
    targetId: string | null = null,
  ) => {
    const route = { view, focus, targetId };
    setActiveView(view);
    setRouteTarget(route);
    window.history.replaceState(window.history.state, "", productWorkspaceHash(route));
  };

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2800);
  };

  const load = async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const next = await localPlatformService.productIntelligence();
      setData(next);
      setKeywordMode(next.market_reference.mode);
      setCustomKeyword(next.market_reference.custom_keyword);
      setSaveCommonKeyword(
        next.market_reference.common_keywords.includes(next.market_reference.custom_keyword),
      );
      setActivePlanSlotId((current) => {
        if (current && next.operating_plan.slots.some((slot) => slot.id === current)) return current;
        return next.operating_plan.slots.find((slot) => slot.action_type === "traffic")?.id
          || next.operating_plan.slots[0]?.id
          || null;
      });
      setSelectedId((current) => {
        if (current && next.products.some((product) => product.external_id === current)) return current;
        return next.products.find((product) => product.monitoring_enabled)?.external_id || next.products[0]?.external_id || null;
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "商品经营数据加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    let disconnect = () => {};
    try {
      disconnect = connectPlatformEvents((event) => {
        if (String(event.type || "").startsWith("product_")) void load(true);
      });
    } catch {
      // The static Sites build intentionally has no local event service.
    }
    return disconnect;
  }, []);

  useEffect(() => {
    const syncRoute = () => setRouteTarget(readProductWorkspaceRoute());
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
    setActiveView(routeTarget.view);
    if (!data || !routeTarget.focus) return;
    if (routeTarget.focus === "product" && routeTarget.targetId) {
      if (data.products.some((product) => product.external_id === routeTarget.targetId)) {
        setSelectedId(routeTarget.targetId);
      }
    }
    if (routeTarget.focus === "experiment" && routeTarget.targetId) {
      const experiment = data.modification_experiments.find((item) => item.id === routeTarget.targetId);
      if (experiment) {
        setExperimentDecision(experiment);
        setExperimentNote("");
      }
    }
    if (routeTarget.focus === "update") setMarketImportOpen(true);
    const timer = window.setTimeout(() => {
      const elementId = routeTarget.focus === "collection"
        ? "product-collection"
        : routeTarget.focus === "product"
          ? "product-detail"
          : routeTarget.focus === "batch" && routeTarget.targetId
            ? `product-batch-${routeTarget.targetId}`
            : routeTarget.focus === "plan" && routeTarget.targetId
              ? `product-launch-plan-${routeTarget.targetId}`
              : routeTarget.focus === "recommendation"
                ? "product-launch-recommendation"
                : routeTarget.focus === "experiment"
                  ? "product-modification-lab"
                  : routeTarget.focus === "update"
                    ? "product-market-reference"
                    : null;
      if (!elementId) return;
      document.getElementById(elementId)?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "center",
      });
    }, 90);
    return () => window.clearTimeout(timer);
  }, [data, routeTarget]);

  const normalizedSearch = globalSearch.trim().toLowerCase();
  const products = useMemo(() => {
    if (!data) return [];
    return normalizedSearch
      ? data.products.filter((product) => `${product.title} ${product.external_id}`.toLowerCase().includes(normalizedSearch))
      : data.products;
  }, [data, normalizedSearch]);
  const selected = data?.products.find((product) => product.external_id === selectedId) || products[0] || null;
  const activePlanSlot = data?.operating_plan.slots.find((slot) => slot.id === activePlanSlotId)
    || data?.operating_plan.slots[0]
    || null;

  const openBatchDraft = (slot?: ProductOperatingPlanSlotView | null, seedIds: string[] = []) => {
    if (!data) return;
    const plannedIds = slot?.products.map((product) => product.external_id) || seedIds;
    const fallbackIds = data.products
      .filter((product) => product.monitoring_enabled)
      .slice(0, 3)
      .map((product) => product.external_id);
    setBatchDraft({
      slotId: slot?.id || null,
      selectedIds: plannedIds.length ? plannedIds : fallbackIds,
      plannedLocal: slot ? `${slot.date}T${slot.scheduled_time}` : beijingLocalInput(),
      cost: String(slot?.planned_cost || 5.9),
      note: "",
    });
  };

  const toggleBatchProduct = (externalId: string) => {
    setBatchDraft((current) => {
      if (!current) return current;
      if (current.selectedIds.includes(externalId)) {
        return { ...current, selectedIds: current.selectedIds.filter((value) => value !== externalId) };
      }
      if (current.selectedIds.length >= 5) {
        notify("一个批次最多选择 5 件商品");
        return current;
      }
      return { ...current, selectedIds: [...current.selectedIds, externalId] };
    });
  };

  const createBatch = async (event: FormEvent) => {
    event.preventDefault();
    if (!batchDraft || batchDraft.selectedIds.length === 0) return;
    setBusy(true);
    try {
      await localPlatformService.createTrafficBatch({
        request_id: crypto.randomUUID(),
        item_external_ids: batchDraft.selectedIds,
        planned_at: toApiDateTime(batchDraft.plannedLocal),
        actual_cost: Math.max(0, Number(batchDraft.cost) || 0),
        plan_slot_id: batchDraft.slotId,
        note: batchDraft.note.trim(),
      });
      setBatchDraft(null);
      notify("多商品曝光批次已建立；系统只记录和提醒，不会自动购买曝光");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "曝光批次建立失败");
    } finally {
      setBusy(false);
    }
  };

  const startBatch = async (batch: ProductTrafficBatchView) => {
    setBusy(true);
    try {
      await localPlatformService.startTrafficBatch(batch.id);
      notify("T0 基线与曝光支出已记录；请在闲鱼人工完成本批次投放");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "批次未能开始");
    } finally {
      setBusy(false);
    }
  };

  const cancelBatch = async (batch: ProductTrafficBatchView) => {
    setBusy(true);
    try {
      await localPlatformService.cancelTrafficBatch(batch.id);
      notify("未开始的批次已取消，历史记录仍保留");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "批次取消失败");
    } finally {
      setBusy(false);
    }
  };

  const openBatchOperation = (batch: ProductTrafficBatchView, mode: "complete" | "checkpoint") => {
    const nextCheckpoint = batch.due_checkpoint || (["h1", "h6", "h24", "h72"] as const).find((value) => !batch.completed_checkpoints.includes(value)) || "h72";
    setBatchOperation({
      batch,
      mode,
      checkpoint: nextCheckpoint,
      cost: String(batch.actual_cost || 5.9),
      totalExposure: batch.total_exposure === null ? "" : String(batch.total_exposure),
      note: "",
      rows: Object.fromEntries(batch.products.map((product) => [product.external_id, {
        browse_count: String(product.latest_browse_count),
        collect_count: String(product.latest_collect_count),
        want_count: String(product.latest_want_count),
        inquiry_count: String(product.latest_inquiry_count),
      }])),
    });
  };

  const saveBatchOperation = async (event: FormEvent) => {
    event.preventDefault();
    if (!batchOperation) return;
    setBusy(true);
    try {
      if (batchOperation.mode === "complete") {
        await localPlatformService.completeTrafficBatch(batchOperation.batch.id, {
          completed_at: new Date().toISOString(),
          actual_cost: Math.max(0, Number(batchOperation.cost) || 0),
          total_exposure: batchOperation.totalExposure ? Math.max(0, Number(batchOperation.totalExposure) || 0) : null,
          note: batchOperation.note.trim(),
        });
        notify("套餐完成信息已记录；后续浏览和咨询仍会归入 24h / 72h 观察");
      } else {
        await localPlatformService.recordTrafficCheckpoint(batchOperation.batch.id, {
          checkpoint: batchOperation.checkpoint,
          recorded_at: new Date().toISOString(),
          items: batchOperation.batch.products.map((product) => {
            const row = batchOperation.rows[product.external_id];
            return {
              external_id: product.external_id,
              browse_count: Math.max(0, Number(row.browse_count) || 0),
              collect_count: Math.max(0, Number(row.collect_count) || 0),
              want_count: Math.max(0, Number(row.want_count) || 0),
              inquiry_count: Math.max(0, Number(row.inquiry_count) || 0),
            };
          }),
          note: batchOperation.note.trim(),
        });
        notify(`${checkpointLabels[batchOperation.checkpoint]} 检查点已保存，经营计划会按新数据重新评估`);
      }
      setBatchOperation(null);
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "批次数据保存失败");
    } finally {
      setBusy(false);
    }
  };

  const refreshPlan = async () => {
    setBusy(true);
    try {
      const plan = await localPlatformService.refreshOperatingPlan();
      setActivePlanSlotId(plan.slots.find((slot) => slot.action_type === "traffic")?.id || plan.slots[0]?.id || null);
      notify(plan.change_summary);
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "经营计划刷新失败");
    } finally {
      setBusy(false);
    }
  };

  const togglePlanLock = async (slot: ProductOperatingPlanSlotView) => {
    setBusy(true);
    try {
      await localPlatformService.updateOperatingPlanSlot(slot.id, !slot.locked);
      notify(slot.locked ? "该日期已恢复动态调整" : "该日期已锁定，后续计划刷新会保留安排");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "计划锁定状态更新失败");
    } finally {
      setBusy(false);
    }
  };

  const collectManually = async (externalId?: string) => {
    setBusy(true);
    setCollectingScope(externalId || "all");
    try {
      const result = await localPlatformService.collectProductsManual(externalId);
      if (externalId) setSelectedId(externalId);
      notify(result.detail);
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "手动采集未完成");
    } finally {
      setBusy(false);
      setCollectingScope(null);
    }
  };

  const register = async (event: FormEvent) => {
    event.preventDefault();
    if (!registerReference.trim()) return;
    setBusy(true);
    try {
      const product = await localPlatformService.registerProduct(registerReference.trim());
      setRegisterOpen(false);
      setRegisterReference("");
      setSelectedId(product.external_id);
      notify("商品已添加，可立即手动验证并采集");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "添加商品失败");
    } finally {
      setBusy(false);
    }
  };

  const toggleMonitor = async (product: ProductView) => {
    setBusy(true);
    try {
      await localPlatformService.updateProductMonitor(product.external_id, !product.monitoring_enabled);
      notify(product.monitoring_enabled ? "已暂停监测，不会删除历史数据" : "已恢复每日监测");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "监测状态更新失败");
    } finally {
      setBusy(false);
    }
  };

  const openAction = (product: ProductView, recommendation: ProductRecommendationView | null) => {
    setActionTarget({ product, recommendation });
    setActionType(recommendation?.strategy_code === "healthy" ? "hold" : "title");
    setActionNote("");
    setActionCost("");
  };

  const saveAction = async (event: FormEvent) => {
    event.preventDefault();
    if (!actionTarget) return;
    setBusy(true);
    try {
      await localPlatformService.recordProductAction(actionTarget.product.external_id, {
        action_type: actionType,
        status: "completed",
        note: actionNote.trim(),
        cost: actionType === "traffic" ? Math.max(0, Number(actionCost) || 0) : 0,
        recommendation_id: actionTarget.recommendation?.id || null,
        observation_days: actionType === "traffic" ? 3 : 7,
      });
      setActionTarget(null);
      notify("人工经营动作已记录，系统会在后续快照中观察效果");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "经营动作记录失败");
    } finally {
      setBusy(false);
    }
  };

  const dismissRecommendation = async (recommendation: ProductRecommendationView) => {
    setBusy(true);
    try {
      await localPlatformService.updateProductRecommendation(recommendation.id, "dismissed");
      notify("建议已暂不处理，明日数据变化后会重新评估");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "建议状态更新失败");
    } finally {
      setBusy(false);
    }
  };

  const chooseRecommendedKeyword = async (keyword: string) => {
    setBusy(true);
    try {
      await localPlatformService.updateMarketKeyword({
        mode: "recommended",
        keyword,
        save_as_common: false,
      });
      notify(`今天将验证“${keyword}”`);
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "关键词选择失败");
    } finally {
      setBusy(false);
    }
  };

  const useCustomMarketKeyword = async () => {
    if (!customKeyword.trim()) {
      notify("请先输入今天要验证的关键词");
      return;
    }
    setBusy(true);
    try {
      await localPlatformService.updateMarketKeyword({
        mode: "custom",
        keyword: customKeyword.trim(),
        save_as_common: saveCommonKeyword,
      });
      notify("今天已改用你的关键词；导入有效参考后完成今日更新");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "自定义关键词保存失败");
    } finally {
      setBusy(false);
    }
  };

  const returnToRecommendedKeyword = async () => {
    const keyword = data?.market_reference.recommendations[0]?.keyword;
    if (!keyword) return;
    await chooseRecommendedKeyword(keyword);
  };

  const importMarketReference = async (event: FormEvent) => {
    event.preventDefault();
    if (!data || !marketImportText.trim()) return;
    setBusy(true);
    try {
      const parsed = JSON.parse(marketImportText) as unknown;
      const object = parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? parsed as Record<string, unknown>
        : { results: parsed };
      if (!Array.isArray(object.results)) throw new Error("导入内容需要包含 results 数组");
      const results = object.results.map((entry, index) => {
        if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
          throw new Error(`第 ${index + 1} 条结果格式不正确`);
        }
        const row = entry as Record<string, unknown>;
        const position = Number(row.position);
        const title = String(row.title || "").trim();
        if (!Number.isInteger(position) || position < 1 || !title) {
          throw new Error(`第 ${index + 1} 条结果缺少有效的 position 或 title`);
        }
        const price = row.price === null || row.price === undefined || row.price === ""
          ? null
          : Number(row.price);
        if (price !== null && (!Number.isFinite(price) || price < 0)) {
          throw new Error(`第 ${index + 1} 条结果的 price 不正确`);
        }
        const tags = Array.isArray(row.tags)
          ? row.tags.map((tag) => String(tag).trim()).filter(Boolean)
          : [];
        return { position, title, price, tags };
      });
      await localPlatformService.importMarketReference({
        keyword: data.market_reference.selected_keyword,
        captured_at: new Date().toISOString(),
        results,
        note: marketImportNote.trim(),
      });
      setMarketImportOpen(false);
      setMarketImportText("");
      setMarketImportNote("");
      notify("今天的 Edge 市场参考已导入，提醒已自动清除");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "市场参考导入失败");
    } finally {
      setBusy(false);
    }
  };

  const snoozeMarketReminder = async () => {
    setBusy(true);
    try {
      await localPlatformService.snoozeMarketReminder(2);
      notify("今晚稍后提醒，默认延后 2 小时");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "提醒延后失败");
    } finally {
      setBusy(false);
    }
  };

  const skipMarketReminder = async () => {
    setBusy(true);
    try {
      await localPlatformService.skipMarketReminder();
      notify("今天不再提醒；明天会重新生成候选关键词");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "提醒状态更新失败");
    } finally {
      setBusy(false);
    }
  };

  const createLaunchPlan = async () => {
    if (!data) return;
    const recommendation = data.launch_recommendation;
    if (!recommendation.keyword) return;
    setBusy(true);
    try {
      await localPlatformService.createLaunchPlan({
        keyword: recommendation.keyword,
        title: recommendation.title,
      });
      notify("上新方案已建立；仍需你在闲鱼手动编辑和发布");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "上新方案建立失败");
    } finally {
      setBusy(false);
    }
  };

  const openModificationExperiment = (suggestion: ProductModificationSuggestionView) => {
    if (!data || !suggestion.variable || suggestion.blocked_reason) return;
    const product = data.products.find((value) => value.external_id === suggestion.external_id);
    const beforeValue = suggestion.variable === "title"
      ? product?.title || ""
      : suggestion.variable === "price"
        ? String(product?.price ?? "")
        : "";
    setModificationDraft({
      suggestion,
      variable: suggestion.variable,
      beforeValue,
      afterValue: "",
    });
  };

  const saveModificationExperiment = async (event: FormEvent) => {
    event.preventDefault();
    if (!modificationDraft) return;
    setBusy(true);
    try {
      await localPlatformService.createModificationExperiment(
        modificationDraft.suggestion.external_id,
        {
          variable: modificationDraft.variable,
          before_value: modificationDraft.beforeValue,
          after_value: modificationDraft.afterValue,
          observation_days: 7,
        },
      );
      setModificationDraft(null);
      notify("单变量实验已开始，系统将在约 7 天后提示保留或回退");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "修改实验建立失败");
    } finally {
      setBusy(false);
    }
  };

  const resolveExperiment = async (decision: "keep" | "rollback" | "continue") => {
    if (!experimentDecision) return;
    setBusy(true);
    try {
      await localPlatformService.updateModificationExperiment(experimentDecision.id, {
        decision,
        note: experimentNote.trim(),
      });
      setExperimentDecision(null);
      setExperimentNote("");
      notify(decision === "keep" ? "实验结果已保留" : decision === "rollback" ? "已记录回退决定" : "观察期已延长 3 天");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "实验状态更新失败");
    } finally {
      setBusy(false);
    }
  };

  if (loading && !data) {
    return <div className="product-intelligence-page product-loading">
      <ArrowClockwise className="spin" size={30} />
      <h2>正在整理商品经营信号</h2>
      <p>读取本机快照、咨询和成交数据，不会操作闲鱼商品。</p>
    </div>;
  }

  if (error && !data) {
    return <div className="product-intelligence-page product-offline">
      <Storefront size={52} weight="duotone" />
      <h2>需要连接本机经营服务</h2>
      <p>商品监测依赖本机 SQLite 与闲鱼只读连接；静态公开站点不会读取 Cookie，也不会显示失效的操作按钮。</p>
      <button onClick={() => void load()}><ArrowClockwise size={17} />重新连接</button>
    </div>;
  }

  if (!data) return null;

  const runPresentation = collectionRunPresentation(data);
  const activePlanBatch = activePlanSlot ? data.traffic_batches.find((batch) => {
    if (activePlanSlot.batch_id && batch.id === activePlanSlot.batch_id) return true;
    if (beijingDayKey(batch.planned_at) !== activePlanSlot.date) return false;
    const plannedIds = new Set(activePlanSlot.products.map((product) => product.external_id));
    return batch.products.some((product) => plannedIds.has(product.external_id));
  }) || null : null;

  const renderMarketReference = (expanded = false) => <section id={expanded ? "product-market-reference" : undefined} className={`product-market-reference-card ${expanded ? "is-expanded" : ""}`}>
    <header>
      <span><small>MARKET REFERENCE</small><h3>市场参考</h3></span>
      <em className={`market-stability status-${data.market_reference.stability.status}`}>{data.market_reference.stability.label}</em>
    </header>
    {!data.market_reference.update_completed && data.market_reference.reminder.status !== "skipped" && <div className="market-reminder-banner">
      <BellRinging size={23} weight="duotone" />
      <span><b>{data.market_reference.reminder.status === "snoozed" ? "提醒已延后" : "今日市场参考未更新"}</b><small>{data.market_reference.reminder.status === "snoozed" && data.market_reference.reminder.snoozed_until ? `将在 ${formatDate(data.market_reference.reminder.snoozed_until)} 再提醒` : "北京时间 20:00 检查；更新任一关键词后自动清除"}</small><em>只提醒，不会自动搜索或打开新网站</em></span>
      <div><button type="button" onClick={() => setMarketImportOpen(true)}>现在更新</button><button type="button" onClick={() => void snoozeMarketReminder()}>今晚稍后</button><button type="button" onClick={() => void skipMarketReminder()}>今日不再提醒</button></div>
    </div>}
    {data.market_reference.update_completed && <div className="market-reminder-banner is-complete"><CheckCircle size={23} weight="fill" /><span><b>今日市场参考已更新</b><small>{data.market_reference.current_sample?.result_count || 0} 条公开结果 · {formatDate(data.market_reference.last_updated_at)}</small><em>同一关键词同一天只保留一个样本</em></span></div>}

    <div className="market-keyword-tabs" role="tablist" aria-label="关键词来源">
      <button type="button" role="tab" aria-selected={keywordMode === "recommended"} className={keywordMode === "recommended" ? "active" : ""} onClick={() => setKeywordMode("recommended")}>系统推荐</button>
      <button type="button" role="tab" aria-selected={keywordMode === "custom"} className={keywordMode === "custom" ? "active" : ""} onClick={() => setKeywordMode("custom")}>我的关键词</button>
    </div>

    {keywordMode === "recommended" ? <div className="market-keyword-editor">
      <div className="market-editor-title"><span><b>今日推荐搜索词</b><small>根据咨询需求、商品缺口、历史参考和交付容量生成</small></span><Info size={17} /></div>
      <div className="market-keyword-options">
        {data.market_reference.recommendations.map((candidate) => {
          const selectedKeyword = data.market_reference.mode === "recommended" && data.market_reference.selected_keyword === candidate.keyword;
          return <button type="button" className={selectedKeyword ? "selected" : ""} aria-pressed={selectedKeyword} disabled={busy} onClick={() => void chooseRecommendedKeyword(candidate.keyword)} key={candidate.keyword}>
            <i>{selectedKeyword ? <CheckCircle size={18} weight="fill" /> : <span />}</i><span><b>{candidate.keyword}</b><small>{candidate.reason}</small></span><em>{confidenceLabels[candidate.confidence] || candidate.confidence}</em>
          </button>;
        })}
      </div>
      <div className="market-editor-actions"><button type="button" className="product-primary-button" disabled={busy || data.market_reference.mode !== "recommended"} onClick={() => setMarketImportOpen(true)}><MagnifyingGlass size={16} />使用选中关键词更新</button><button type="button" className="product-outline-button" onClick={() => setKeywordMode("custom")}>我有自己的关键词</button></div>
    </div> : <div className="market-keyword-editor custom-mode">
      <div className="market-editor-title"><span><b>今天用我的关键词</b><small>有明确方向时，可临时替代系统推荐</small></span><PencilSimple size={17} /></div>
      <input value={customKeyword} onChange={(event) => setCustomKeyword(event.target.value)} placeholder="例如：uni-app 页面修改" maxLength={80} />
      <label className="market-common-toggle"><input type="checkbox" checked={saveCommonKeyword} onChange={(event) => setSaveCommonKeyword(event.target.checked)} /><span>加入常用关键词</span><small>不勾选时仅本次验证</small></label>
      {data.market_reference.common_keywords.length > 0 && <div className="market-common-keywords">{data.market_reference.common_keywords.map((keyword) => <button type="button" onClick={() => setCustomKeyword(keyword)} key={keyword}>{keyword}</button>)}</div>}
      <div className="market-editor-actions"><button type="button" className="product-primary-button" disabled={busy || !customKeyword.trim()} onClick={() => void useCustomMarketKeyword()}>使用我的关键词更新</button><button type="button" className="product-outline-button" onClick={() => { setKeywordMode("recommended"); void returnToRecommendedKeyword(); }}>返回系统推荐</button></div>
    </div>}

    <div className="market-import-row">
      <FolderOpen size={24} weight="duotone" />
      <span><b>{data.market_reference.current_sample ? "已导入今天的市场参考" : "尚未导入市场参考"}</b><small>使用现有 Edge 搜索，由 Codex 整理公开字段后粘贴导入；不会打开第二个网站</small></span>
      <button type="button" onClick={() => setMarketImportOpen(true)}><UploadSimple size={16} />{data.market_reference.current_sample ? "修正导入" : "导入参考"}</button>
    </div>

    {expanded && <div className="market-sample-detail">
      <div className="market-sample-summary">
        <span><small>当前关键词</small><b>{data.market_reference.selected_keyword || "尚未选择"}</b></span>
        <span><small>近 30 天样本</small><b>{data.market_reference.benchmark.sample_days} 天</b></span>
        <span><small>前 10 位公开结果</small><b>{data.market_reference.benchmark.high_visibility_result_count} 条</b></span>
        <span><small>多日重复结构</small><b>{data.market_reference.benchmark.repeated_result_count} 个</b></span>
      </div>
      <div className="market-benchmark-panel">
        <header><span><TrendUp size={18} weight="duotone" /><b>高可见市场基准</b></span><em className={`confidence-${data.market_reference.benchmark.confidence}`}>{confidenceLabels[data.market_reference.benchmark.confidence] || data.market_reference.benchmark.confidence}</em></header>
        <div className="market-benchmark-grid">
          <span><small>公开标价中位数</small><b>{data.market_reference.benchmark.median_price === null ? "—" : moneyExact.format(data.market_reference.benchmark.median_price)}</b><em>{data.market_reference.benchmark.price_low === null || data.market_reference.benchmark.price_high === null ? "等待更多标价" : `${moneyExact.format(data.market_reference.benchmark.price_low)}–${moneyExact.format(data.market_reference.benchmark.price_high)}`}</em></span>
          <span><small>标题长度中位数</small><b>{data.market_reference.benchmark.median_title_length === null ? "—" : `${data.market_reference.benchmark.median_title_length} 字`}</b><em>只用于结构参考</em></span>
          <span><small>常见能力词</small><b>{data.market_reference.benchmark.common_title_terms.slice(0, 4).join(" · ") || "等待多日样本"}</b><em>不会复制完整标题</em></span>
          <span><small>常见公开标签</small><b>{data.market_reference.benchmark.common_tags.slice(0, 4).join(" · ") || "暂无稳定标签"}</b><em>仅来自人工导入字段</em></span>
        </div>
        <ul>{data.market_reference.benchmark.evidence.map((line) => <li key={line}>{line}</li>)}</ul>
      </div>
      {data.market_reference.current_sample ? <div className="market-result-table" role="table" aria-label="今天导入的公开搜索结果">
        <div role="row"><span>位置</span><span>标题</span><span>价格</span><span>公开标签</span></div>
        {data.market_reference.current_sample.results.map((result) => <div role="row" key={`${result.position}-${result.title}`}><span>#{result.position}</span><span>{result.title}</span><span>{result.price === null ? "—" : moneyExact.format(result.price)}</span><span>{result.tags.join("、") || "—"}</span></div>)}
      </div> : <div className="product-empty-state compact-market-empty"><MagnifyingGlass size={34} weight="duotone" /><h4>还没有今天的真实搜索参考</h4><p>先在已登录的 Edge 中搜索当前关键词，再把 Codex 整理出的 JSON 导入。</p></div>}
    </div>}
    <footer><Info size={14} />推荐词只用于搜索验证；连续多日稳定后才判断高可见，不会称为“闲鱼官方热门”。</footer>
  </section>;

  return <div className="product-intelligence-page">
    <section className="product-metrics-grid product-metrics-first" aria-label="商品经营指标">
      <ProductMetric icon={Package} label="我的商品" value={`${data.summary.monitored_products}`} detail={`${data.summary.active_products} 个可经营 · ${data.summary.excluded_products} 个已排除`} tone="purple" />
      <ProductMetric icon={BellRinging} label="待补全信息" value={`${data.products.filter((product) => product.data_gaps.length > 0).length}`} detail="商品快照、咨询与实验基线" tone="orange" />
      <ProductMetric icon={Coins} label="本周曝光投入" value={moneyExact.format(data.traffic_summary.spent_this_week)} detail={`初始周上限 ${moneyExact.format(data.operating_plan.weekly_budget)}`} tone="green" />
      <ProductMetric icon={CalendarCheck} label="有效批次" value={`${data.traffic_summary.effective_batch_count}`} detail={`${data.summary.snapshot_days} 个快照日 · ${analysisStageLabels[data.traffic_summary.analysis_stage] || "学习中"}`} tone="blue" />
      <ProductMetric icon={Gauge} label="交付负载" value={`${data.summary.active_projects}/${data.summary.delivery_capacity}`} detail="满载时自动建议收缩流量" tone="red" />
    </section>

    <nav className="product-workspace-tabs" aria-label="商品经营工作区">
      <div role="tablist">
        {([
          ["overview", "经营总览"],
          ["exposure", "曝光分析"],
          ["launch", "上新与修改"],
          ["market", "市场参考"],
        ] as const).map(([key, label]) => <button type="button" role="tab" aria-selected={activeView === key} className={activeView === key ? "active" : ""} onClick={() => navigateWorkspace(key)} key={key}>{label}</button>)}
      </div>
      <button type="button" className={`product-market-reminder-pill status-${data.market_reference.reminder.status}`} onClick={() => navigateWorkspace("market", "update")}>
        {data.market_reference.update_completed ? <CheckCircle size={16} weight="fill" /> : <BellRinging size={16} weight="fill" />}
        {data.market_reference.update_completed ? "今日市场参考已更新" : data.market_reference.reminder.status === "snoozed" ? "市场参考提醒已延后" : data.market_reference.reminder.status === "skipped" ? "今日不再提醒" : "今日市场参考待更新 · 20:00 提醒"}
      </button>
    </nav>

    {activeView === "overview" && <section className="product-command-card">
      <div className="product-command-copy">
        <span className="product-eyebrow"><Sparkle size={14} weight="fill" /> PRODUCT INTELLIGENCE</span>
        <h2>今天只做最值得做的商品动作</h2>
        <p>系统每天自动读取一次商品与经营数据，也支持你手动刷新全部或指定商品。</p>
        <div className="product-safety-note"><ShieldCheck size={18} weight="fill" /><span><b>只读安全边界</b>{data.collection.safety_note}</span></div>
      </div>
      <div className="product-collection-panel" id="product-collection">
        <div><small>采集计划 · 北京时间</small><strong>{data.collection.schedule}</strong><span>{data.collection.configured ? `下次计划 ${formatDate(data.collection.next_collection_at)}（北京时间）` : "等待配置闲鱼连接"}</span></div>
        {(data.collection.latest_attempt || data.collection.last_run) && runPresentation && <p className={`collection-result collection-${(data.collection.latest_attempt || data.collection.last_run)!.status}`}><CheckCircle size={16} weight="fill" />{runPresentation.label}<small>{runPresentation.detail}</small></p>}
        {data.collection.attempts.length > 0 && <div className="collection-log-shell">
          <button type="button" className="collection-log-toggle" aria-expanded={collectionLogOpen} onClick={() => setCollectionLogOpen((value) => !value)}><span><Clock size={15} />采集日志</span><small>{data.collection.attempts.length} 次记录</small><CaretRight className={collectionLogOpen ? "expanded" : ""} size={14} /></button>
          {collectionLogOpen && <div className="collection-log-list">{data.collection.attempts.map((attempt) => <CollectionAttemptLog attempt={attempt} key={attempt.id} />)}</div>}
        </div>}
        <div className="product-command-actions">
          <button className="product-outline-button" onClick={() => setManagementOpen(true)}><Package size={16} />商品管理</button>
          <button className="product-outline-button" onClick={() => setRegisterOpen(true)}><Plus size={16} />添加商品</button>
          <button className="product-primary-button" disabled={busy || !data.collection.configured} onClick={() => void collectManually()}>{collectingScope === "all" ? <ArrowClockwise className="spin" size={16} /> : <ArrowClockwise size={16} />}{data.collection.configured ? "手动采集全部" : "等待渠道配置"}</button>
        </div>
      </div>
    </section>}

    {activeView === "exposure" && <section className="product-plan-shell" aria-labelledby="product-plan-title">
      <header className="product-plan-head">
        <div>
          <span className="product-eyebrow"><Sparkle size={14} weight="fill" /> ROLLING OPERATING PLAN</span>
          <h3 id="product-plan-title">未来 7 天商品经营方案</h3>
          <p>本地规则每天根据新快照、72 小时长尾、交付容量和周预算调整未来安排；今天与未来 24 小时保持稳定。</p>
        </div>
        <div className="product-plan-head-actions">
          <span><small>规则 {data.operating_plan.rules_version}</small><b>第 {data.operating_plan.version} 版</b></span>
          <button className="product-outline-button" disabled={busy} onClick={() => void refreshPlan()}><ArrowClockwise className={busy ? "spin" : ""} size={16} />重新评估</button>
          <button className="product-primary-button" disabled={!data.products.length} onClick={() => openBatchDraft(activePlanSlot)}><Plus size={16} />新建多商品批次</button>
        </div>
      </header>

      {activePlanSlot && <div className="product-plan-focus-grid">
        <article className={`product-plan-focus plan-action-${activePlanSlot.action_type}`}>
          <div className="product-plan-focus-top">
            <span><small>{formatPlanDate(activePlanSlot.date)} · {activePlanSlot.scheduled_time}</small><b>{planActionLabels[activePlanSlot.action_type] || activePlanSlot.action_type}</b></span>
            <em className={`confidence-${activePlanSlot.confidence}`}>{confidenceLabels[activePlanSlot.confidence] || activePlanSlot.confidence}</em>
          </div>
          <p>{activePlanSlot.reason}</p>
          <div className="product-plan-product-chips">
            {activePlanSlot.products.length ? activePlanSlot.products.map((product) => <button type="button" key={product.external_id} onClick={() => navigateWorkspace("overview", "product", product.external_id)}>
              <i><Storefront size={15} weight="duotone" /></i><span><b>{product.title}</b><small>{product.role} · {product.score} 分</small></span>
            </button>) : <span className="product-plan-no-products"><PauseCircle size={18} />今天不安排曝光商品</span>}
          </div>
          <div className="product-plan-focus-actions">
            <span><small>本批总费用</small><b>{activePlanSlot.planned_cost ? `约 ${moneyExact.format(activePlanSlot.planned_cost)}` : "不产生费用"}</b></span>
            {activePlanBatch?.status === "planned" && <button className="product-primary-button" disabled={busy} onClick={() => void startBatch(activePlanBatch)}><Play size={16} weight="fill" />开始批次并记录 T0</button>}
            {activePlanBatch?.status === "running" && <button className="product-primary-button" disabled={busy} onClick={() => openBatchOperation(activePlanBatch, "complete")}><CheckCircle size={16} />记录套餐完成</button>}
            {activePlanBatch && ["observing", "closed"].includes(activePlanBatch.status) && activePlanBatch.due_checkpoint && <button className="product-primary-button" disabled={busy} onClick={() => openBatchOperation(activePlanBatch, "checkpoint")}><ClipboardText size={16} />记录 {checkpointLabels[activePlanBatch.due_checkpoint]}</button>}
            {!activePlanBatch && activePlanSlot.action_type === "traffic" && <button className="product-primary-button" disabled={busy} onClick={() => openBatchDraft(activePlanSlot)}><Plus size={16} />建立这一个批次</button>}
          </div>
        </article>

        <aside className="product-plan-rule-card">
          <div><i><Gauge size={20} weight="duotone" /></i><span><small>本地决策阶段</small><b>{analysisStageLabels[data.operating_plan.analysis_stage] || data.operating_plan.analysis_stage}</b></span></div>
          <p>{data.traffic_summary.analysis_summary}</p>
          <dl>
            <div><dt>有效批次</dt><dd>{data.operating_plan.effective_batch_count} 个</dd></div>
            <div><dt>本周已投</dt><dd>{moneyExact.format(data.operating_plan.spent_this_week)}</dd></div>
            <div><dt>本周计划</dt><dd>{moneyExact.format(data.operating_plan.planned_this_week)}</dd></div>
            <div><dt>剩余额度</dt><dd>{moneyExact.format(data.operating_plan.remaining_this_week)}</dd></div>
          </dl>
          <small><ShieldCheck size={14} weight="fill" />只提供提醒与记录，不会在闲鱼自动购买曝光</small>
        </aside>
      </div>}

      <div className="product-week-plan" role="list" aria-label="未来七天经营安排">
        {data.operating_plan.slots.map((slot, index) => <button type="button" role="listitem" aria-pressed={slot.id === activePlanSlot?.id} className={`${slot.id === activePlanSlot?.id ? "active" : ""} slot-${slot.action_type}`} onClick={() => setActivePlanSlotId(slot.id)} key={slot.id}>
          <span><small>{index === 0 ? "今天" : slot.weekday}</small><b>{slot.date.slice(5).replace("-", "/")}</b></span>
          <i>{slot.action_type === "traffic" ? <Megaphone size={17} weight="duotone" /> : slot.action_type === "measure" ? <Timer size={17} weight="duotone" /> : slot.action_type === "optimize" ? <Lightbulb size={17} weight="duotone" /> : <PauseCircle size={17} weight="duotone" />}</i>
          <strong>{planActionLabels[slot.action_type] || slot.action_type}</strong>
          <em>{slot.products.length ? `${slot.products.length} 件 · ${slot.scheduled_time}` : slot.scheduled_time}</em>
          {slot.locked && <LockSimple size={12} weight="fill" />}
        </button>)}
      </div>

      {activePlanSlot && <footer className="product-plan-explain">
        <div><span><ArrowRight size={16} /></span><p><b>这次为什么这样安排</b><small>{activePlanSlot.change_reason}</small></p></div>
        <ul>{activePlanSlot.evidence.map((line) => <li key={line}>{line}</li>)}</ul>
        {activePlanSlot.warnings.length > 0 && <ul className="product-plan-warnings">{activePlanSlot.warnings.map((line) => <li key={line}><Warning size={13} />{line}</li>)}</ul>}
        <button type="button" disabled={busy || data.operating_plan.slots.slice(0, 2).some((slot) => slot.id === activePlanSlot.id)} onClick={() => void togglePlanLock(activePlanSlot)}>{activePlanSlot.locked ? <><LockSimpleOpen size={15} />解除锁定</> : <><LockSimple size={15} />锁定这天</>}</button>
      </footer>}
    </section>}

    {activeView === "exposure" && <ExposureAnalytics data={data} />}

    {activeView === "launch" && <>
      <section className="product-launch-layout">
        <section className="product-launch-radar-card" id="product-launch-recommendation">
          <header><span><small>LAUNCH RADAR</small><h3>上新雷达</h3></span><em className={`confidence-${data.launch_recommendation.confidence}`}>{confidenceLabels[data.launch_recommendation.confidence] || data.launch_recommendation.confidence}</em></header>
          <div className="launch-radar-hero">
            <span className="launch-radar-icon"><Target size={28} weight="duotone" /></span>
            <div><em className={`launch-action-pill action-${data.launch_recommendation.recommended_action}`}>{launchActionLabels[data.launch_recommendation.recommended_action] || data.launch_recommendation.recommended_action}</em><h2>{data.launch_recommendation.recommended_action === "launch" ? "证据已达到上新阈值" : data.launch_recommendation.recommended_action === "modify_existing" ? "已有同类商品，先优化再决定" : "先补市场证据，再确认上新"}</h2><p>{data.launch_recommendation.rationale[data.launch_recommendation.rationale.length - 1]}</p></div>
          </div>
          <div className="launch-signal-strip">
            <span><ChatCircleDots size={21} weight="duotone" /><small>近 90 天</small><b>{data.launch_recommendation.demand_conversations} 个相关咨询</b></span>
            <span><Storefront size={21} weight="duotone" /><small>供给覆盖</small><b>{data.launch_recommendation.theme} · {data.launch_recommendation.matching_product_count} 个商品</b></span>
            <span><ListChecks size={21} weight="duotone" /><small>高可见市场基准</small><b>{data.launch_recommendation.benchmark.sample_days ? `${data.launch_recommendation.benchmark.sample_days} 天 · ${data.launch_recommendation.benchmark.high_visibility_result_count} 条` : "参考待导入"}</b></span>
          </div>
          <div className="launch-decision-grid">
            <article><small>建议商品类型</small><b>{data.launch_recommendation.suggested_product_type}</b><em>来自需求主题与供给缺口</em></article>
            <article><small>标题方向</small><b>{data.launch_recommendation.title_direction}</b><em>只提取通用词，不复制竞品标题</em></article>
            <article><small>公开价格参考</small><b>{data.launch_recommendation.price_reference}</b><em>最终报价仍由工时与风险决定</em></article>
            <article><small>差异化重点</small><b>{data.launch_recommendation.market_differentiation}</b><em>强调交付、验收和边界</em></article>
          </div>
          <div className="launch-recommendation-row">
            <Clock size={24} weight="duotone" />
            <span><small>建议发布窗口</small><b>{data.launch_recommendation.recommended_window}</b><em>{data.launch_recommendation.timing_basis}</em></span>
            {data.launch_recommendation.recommended_action === "launch" ? <button type="button" className="product-primary-button" disabled={busy || !data.launch_recommendation.keyword || data.launch_plans.some((plan) => plan.keyword === data.launch_recommendation.keyword && ["proposed", "planned"].includes(plan.status))} onClick={() => void createLaunchPlan()}><Plus size={17} />{data.launch_plans.some((plan) => plan.keyword === data.launch_recommendation.keyword && ["proposed", "planned"].includes(plan.status)) ? "方案已建立" : "建立上新方案"}</button> : data.launch_recommendation.recommended_action === "modify_existing" ? <button type="button" className="product-outline-button" onClick={() => document.getElementById("product-modification-lab")?.scrollIntoView({ behavior: "smooth", block: "start" })}><PencilSimple size={17} />查看修改建议</button> : <button type="button" className="product-outline-button" disabled><Timer size={17} />继续积累证据</button>}
          </div>
          {data.launch_plans.length > 0 && <div className="launch-plan-list"><h4>我的手动上新方案</h4>{data.launch_plans.slice(0, 3).map((plan) => <article id={`product-launch-plan-${plan.id}`} key={plan.id}><i><FolderOpen size={17} /></i><span><b>{plan.title}</b><small>{plan.keyword} · {plan.recommended_window}</small></span><em>{plan.status === "planned" ? "待手动发布" : plan.status === "completed" ? "已完成" : plan.status === "cancelled" ? "已取消" : "待规划"}</em>{plan.status === "planned" && <button type="button" disabled={busy} onClick={() => void localPlatformService.updateLaunchPlan(plan.id, "completed").then(() => load(true)).catch((caught) => notify(caught instanceof Error ? caught.message : "状态更新失败"))}>标记完成</button>}</article>)}</div>}
        </section>

        {renderMarketReference(false)}
      </section>

      <section className="product-modification-lab" id="product-modification-lab">
        <header><span><small>CONTROLLED EXPERIMENTS</small><h3>商品修改实验</h3></span><p><Flask size={16} />基于真实曝光与咨询数据，一次只改变一个变量</p></header>
        <div className="modification-table" role="table" aria-label="商品修改实验建议">
          <div className="modification-table-head" role="row"><span>商品与数据</span><span>置信度</span><span>当前建议与依据</span><span>实验流程</span><span>操作</span></div>
          {data.modification_suggestions.map((suggestion, index) => {
            const product = data.products.find((value) => value.external_id === suggestion.external_id);
            const experiment = data.modification_experiments.find((value) => value.item_external_id === suggestion.external_id && value.status === "observing");
            return <article role="row" key={suggestion.external_id}>
              <span className="modification-product"><i>{String(index + 1).padStart(2, "0")}</i><b>{suggestion.title}<small>{integer.format(product?.browse_count || 0)} 经营浏览 · {product?.inquiry_count || 0} 咨询</small></b></span>
              <span><em className={`confidence-${suggestion.confidence}`}>{confidenceLabels[suggestion.confidence] || suggestion.confidence}</em></span>
              <span className="modification-advice" title={suggestion.confidence_basis.join("；")}>
                <span className="modification-source-tags">{suggestion.evidence_sources.map((source) => <i className={source === "高可见市场参考" ? "market" : "internal"} key={source}>{source}</i>)}</span>
                <b>{experiment ? `正在观察${actionLabels[experiment.variable] || experiment.variable}` : suggestion.blocked_reason || (suggestion.variable ? actionLabels[suggestion.variable] : "先补齐可比较数据")}</b>
                <small>{experiment ? `观察至 ${formatDate(experiment.observation_until)}` : suggestion.reason}</small>
                {!experiment && <em>{suggestion.suggested_change}</em>}
                {!experiment && suggestion.market_gap && <mark>{suggestion.benchmark_keyword} · {suggestion.market_gap}{suggestion.reference_price_range ? ` · 参考 ${suggestion.reference_price_range}` : ""}</mark>}
              </span>
              <span className="modification-flow"><i className={experiment ? "done" : ""}><Gauge size={15} />选择变量</i><ArrowRight size={13} /><i className={experiment ? "done" : ""}><PencilSimple size={15} />记录修改</i><ArrowRight size={13} /><i className={experiment ? "active" : ""}><CalendarCheck size={15} />观察 7 天</i><ArrowRight size={13} /><i><ShieldCheck size={15} />保留 / 回退</i></span>
              <span>{experiment ? <button type="button" onClick={() => { setExperimentDecision(experiment); setExperimentNote(""); }}>{experiment.can_evaluate ? "评估结果" : "查看实验"}</button> : suggestion.blocked_reason || !suggestion.variable ? <button type="button" onClick={() => navigateWorkspace("overview", "product", suggestion.external_id)}>查看证据</button> : <button type="button" onClick={() => openModificationExperiment(suggestion)}>建立实验</button>}<CaretRight size={15} /></span>
            </article>;
          })}
          {data.modification_suggestions.length === 0 && <div className="product-empty-state"><Flask size={34} weight="duotone" /><h4>还没有可实验的本人商品</h4><p>先在商品管理中完成归属验证和数据采集。</p></div>}
        </div>
      </section>
    </>}

    {activeView === "market" && <section className="product-market-page">{renderMarketReference(true)}</section>}

    {(activeView === "overview" || activeView === "exposure") && <section className={`product-workspace-grid workspace-${activeView}`}>
      <main className="product-main-column">
        {activeView === "exposure" && <section className="product-panel product-batch-panel">
          <header><span><small>EXPOSURE BATCHES</small><h3>多商品批次追踪</h3></span><div><em>{data.traffic_summary.active_batch_count} 个进行中 · {data.traffic_summary.batch_count} 个历史批次</em><button type="button" onClick={() => openBatchDraft(activePlanSlot)}><Plus size={14} />新建批次</button></div></header>
          {data.traffic_batches.length ? <div className="product-batch-list">{data.traffic_batches.slice(0, 5).map((batch) => <article id={`product-batch-${batch.id}`} key={batch.id} className={`batch-status-${batch.status}`}>
            <div className="product-batch-summary">
              <i><Megaphone size={19} weight="duotone" /></i>
              <span><small>{formatDate(batch.planned_at)} · {batch.products.length} 件商品</small><b>{batch.products.map((product) => product.title).join("、")}</b><em>{batch.status === "planned" ? "等待你在闲鱼人工投放" : batch.status === "running" ? "套餐执行中" : batch.status === "observing" ? "观察后续浏览与咨询" : batch.status === "closed" ? "72 小时观察已完成" : "批次已取消"}</em></span>
              <strong><small>批次总费用</small>{moneyExact.format(batch.actual_cost)}</strong>
            </div>
            {batch.overlap_warning && <p className="product-batch-warning"><Warning size={14} />{batch.overlap_warning}</p>}
            {batch.observation_checkpoint && <div className="product-batch-effect" aria-label="当前批次效果">
              <span><small>{checkpointLabels[batch.observation_checkpoint]} 浏览</small><b>+{integer.format(batch.browse_delta)}</b></span>
              <span><small>想要 / 收藏</small><b>+{integer.format(batch.want_delta)} / +{integer.format(batch.collect_delta)}</b></span>
              <span><small>咨询增量</small><b>+{integer.format(batch.inquiry_delta)}</b></span>
              <span><small>每咨询成本</small><b>{batch.cost_per_inquiry === null ? "—" : moneyExact.format(batch.cost_per_inquiry)}</b></span>
              <em className={`quality-${batch.data_quality}`}>{trafficDataQualityLabels[batch.data_quality] || batch.data_quality}</em>
            </div>}
            <div className="product-checkpoint-track" aria-label="批次检查点">
              <span className={batch.started_at ? "done" : "next"}><i>T0</i><small>投放前</small></span>
              {(["h1", "h6", "h24", "h72"] as const).map((checkpoint) => <span className={batch.completed_checkpoints.includes(checkpoint) ? "done" : batch.due_checkpoint === checkpoint ? "next" : ""} key={checkpoint}><i>{checkpointLabels[checkpoint].replace(" 小时", "h")}</i><small>{batch.completed_checkpoints.includes(checkpoint) ? "已记录" : batch.due_checkpoint === checkpoint ? formatDate(batch.due_at) : "待观察"}</small></span>)}
            </div>
            <div className="product-batch-actions">
              {batch.total_exposure !== null && <span>套餐总曝光 <b>{integer.format(batch.total_exposure)}</b></span>}
              {batch.status === "planned" && <><button type="button" disabled={busy} onClick={() => void cancelBatch(batch)}>取消计划</button><button type="button" className="primary" disabled={busy} onClick={() => void startBatch(batch)}><Play size={14} weight="fill" />开始并记录 T0</button></>}
              {batch.status === "running" && <button type="button" className="primary" disabled={busy} onClick={() => openBatchOperation(batch, "complete")}><CheckCircle size={14} />记录套餐完成</button>}
              {["observing", "closed"].includes(batch.status) && batch.due_checkpoint && <button type="button" className="primary" disabled={busy} onClick={() => openBatchOperation(batch, "checkpoint")}><ClipboardText size={14} />记录 {checkpointLabels[batch.due_checkpoint]}</button>}
            </div>
          </article>)}</div> : <div className="product-empty-state product-batch-empty"><Megaphone size={38} weight="duotone" /><h4>还没有真实曝光批次</h4><p>建立批次后，系统会提醒 T0、1h、6h、24h 和 72h；一次费用对应整个商品组合。</p><button onClick={() => openBatchDraft(activePlanSlot)}><Plus size={16} />建立第一个批次</button></div>}
        </section>}

        {activeView === "overview" && <><section className="product-panel product-priority-panel">
          <header><span><small>DAILY PRIORITIES</small><h3>今日优先策略</h3></span><em>{data.recommendations.length} 条有依据的建议</em></header>
          {data.recommendations.length ? <div className="product-priority-list">
            {data.recommendations.slice(0, 5).map((recommendation, index) => {
              const product = data.products.find((item) => item.external_id === recommendation.item_external_id);
              return <article key={recommendation.id} className={`priority-${recommendation.attention}`}>
                <i className="priority-index">{String(index + 1).padStart(2, "0")}</i>
                <div className="priority-copy">
                  <p><AttentionBadge value={recommendation.attention} /><span>{confidenceLabels[recommendation.confidence] || recommendation.confidence}</span></p>
                  <h4>{recommendation.title}</h4>
                  <b>{recommendation.item_title}</b>
                  <small>{recommendation.summary}</small>
                  <ul>{recommendation.evidence.slice(0, 3).map((line) => <li key={line}>{line}</li>)}</ul>
                </div>
                <div className="priority-actions">
                  <strong>{recommendation.priority_score}<small>优先分</small></strong>
                  <button onClick={() => navigateWorkspace("overview", "product", recommendation.item_external_id)}>查看商品 <CaretRight size={14} /></button>
                  {product && (recommendation.strategy_code === "scale_candidate" ? <button className="priority-primary" onClick={() => openBatchDraft(activePlanSlot, [product.external_id])}>加入多商品批次</button> : <button className="priority-primary" onClick={() => openAction(product, recommendation)}>记录商品修改</button>)}
                  <button className="priority-dismiss" disabled={busy} onClick={() => void dismissRecommendation(recommendation)}>暂不处理</button>
                </div>
              </article>;
            })}
          </div> : <div className="product-empty-state"><CheckCircle size={40} weight="duotone" /><h4>今天没有待处理建议</h4><p>系统不会为了显得智能而填充没有证据的策略。</p></div>}
        </section>

        <section className="product-panel product-inventory-panel">
          <header><span><small>PRODUCT RADAR</small><h3>商品经营雷达</h3></span><em>{normalizedSearch ? `筛选出 ${products.length} 个` : "点击商品查看证据"}</em></header>
          {products.length ? <div className="product-table" role="table" aria-label="商品经营列表">
            <div className="product-table-head" role="row"><span>商品</span><span>经营浏览变化</span><span>想要 / 收藏</span><span>咨询 / 成交</span><span>利润</span><span>当前策略</span></div>
            {products.map((product) => <button type="button" role="row" className={selected?.external_id === product.external_id ? "selected" : ""} onClick={() => navigateWorkspace("overview", "product", product.external_id)} key={product.external_id}>
              <span className="product-name-cell"><i><Storefront size={18} weight="duotone" /></i><b>{product.title}<small>ID {product.external_id}</small></b><ProductCollectionBadge product={product} /></span>
              <span className="product-browse-cell"><strong>{integer.format(product.browse_count)}</strong><small>{product.browse_delta === null ? "建立基线" : `+${integer.format(product.browse_delta)}`}</small><em>平台原始 {integer.format(product.raw_browse_count)} · 已排除 {product.collection_views_excluded}</em></span>
              <span><strong>{product.want_count} / {product.collect_count}</strong><small>累计互动</small></span>
              <span><strong>{product.inquiry_count} / {product.converted_project_count}</strong><small>{product.deal_rate === null ? "暂无成交率" : `成交率 ${product.deal_rate}%`}</small></span>
              <span><strong>{money.format(product.profit_total)}</strong><small>关联实际利润</small></span>
              <span>{product.recommendation && ["active", "in_progress"].includes(product.recommendation.status) ? <AttentionBadge value={product.recommendation.attention} /> : <em className="product-waiting">{product.recommendation?.status === "dismissed" ? "今日已忽略" : "等待数据"}</em>}<CaretRight size={15} /></span>
            </button>)}
          </div> : <div className="product-empty-state"><MagnifyingGlass size={40} weight="duotone" /><h4>{normalizedSearch ? "没有匹配的商品" : "还没有监测商品"}</h4><p>{normalizedSearch ? "可以调整顶部搜索关键词。" : "添加闲鱼商品 ID 或链接，系统会在下一次每日采集中读取数据。"}</p>{!normalizedSearch && <button onClick={() => setRegisterOpen(true)}><Plus size={16} />添加第一个商品</button>}</div>}
        </section></>}
      </main>

      {activeView === "overview" && <aside className="product-insight-column">
        <section className="product-panel product-rule-engine-card">
          <header><span><small>LOCAL RULE ENGINE</small><h3>决策依据</h3></span><ShieldCheck size={22} weight="duotone" /></header>
          <div className="product-rule-stage"><i><Gauge size={18} /></i><span><small>当前阶段</small><b>{analysisStageLabels[data.traffic_summary.analysis_stage] || data.traffic_summary.analysis_stage}</b></span><em>{confidenceLabels[data.operating_plan.data_quality] || "低置信"}</em></div>
          <ul>
            <li><b>一次一批</b><span>约 ¥5.9～¥6 可包含 3–5 件商品</span></li>
            <li><b>长尾观察</b><span>1 小时套餐结束后继续看 24h / 72h</span></li>
            <li><b>时段排序</b><span>只用成熟批次比较北京时间 2 小时窗口</span></li>
            <li><b>防止重叠</b><span>同一商品尽量间隔 72 小时</span></li>
            <li><b>真实成本</b><span>开始批次后自动计入流量曝光支出</span></li>
            <li><b>全局保护</b><span>交付满载或预算用完时暂停全部新增曝光</span></li>
          </ul>
          <p>{data.operating_plan.change_summary}</p>
        </section>

        <section className="product-panel publish-timing-card">
          <header><span><small>PUBLISH TIMING</small><h3>发布时间建议</h3></span><Clock size={22} weight="duotone" /></header>
          <p>{data.publish_timing.summary}</p>
          <div className="timing-confidence"><span className={`confidence-${data.publish_timing.confidence}`}>{confidenceLabels[data.publish_timing.confidence] || data.publish_timing.confidence}</span><small>{data.publish_timing.sample_size} 个近 90 天首次咨询</small></div>
          {data.publish_timing.windows.map((window, index) => <div className="publish-window" key={`${window.weekday}-${window.time_range}`}><i>{index + 1}</i><span><b>{window.weekday}</b><small>{window.time_range}</small></span><strong>{window.share}%<small>{window.inquiry_count} 条咨询</small></strong></div>)}
        </section>

        <section className="product-panel demand-card">
          <header><span><small>DEMAND GAPS</small><h3>可以发布什么</h3></span><Lightbulb size={22} weight="duotone" /></header>
          {data.demand_opportunities.length ? <div className="demand-list">{data.demand_opportunities.map((opportunity) => <article key={opportunity.theme}><i className={opportunity.posture === "已验证" ? "verified" : opportunity.posture === "供给缺口" ? "gap" : "observe"}><Target size={17} /></i><span><p><b>{opportunity.theme}</b><em>{opportunity.posture}</em></p><small>{opportunity.suggestion}</small><strong>{opportunity.conversation_count} 个会话 · {opportunity.converted_project_count} 个项目</strong></span></article>)}</div> : <div className="compact-empty"><Lightbulb size={28} /><span><b>等待需求信号</b><small>系统只从真实客户咨询中发现机会。</small></span></div>}
        </section>
      </aside>}
    </section>}

    {activeView === "overview" && selected && <section className="product-panel product-detail-panel" id="product-detail">
      <header className="product-detail-head"><div><span><Storefront size={20} weight="duotone" /></span><div className="product-detail-title"><small>SELECTED PRODUCT</small><h3>{selected.title}</h3><em>商品 ID {selected.external_id} · 最近数据 {formatDate(selected.last_collected_at)}</em><ProductCollectionBadge product={selected} /></div></div><div><button className="product-outline-button" disabled={busy} onClick={() => void collectManually(selected.external_id)}>{collectingScope === selected.external_id ? <ArrowClockwise className="spin" size={16} /> : <ArrowClockwise size={16} />}采集此商品</button><button className="product-outline-button" disabled={busy} onClick={() => void toggleMonitor(selected)}>{selected.monitoring_enabled ? <EyeSlash size={16} /> : <Eye size={16} />}{selected.monitoring_enabled ? "暂停监测" : "恢复监测"}</button><button className="product-outline-button" onClick={() => openBatchDraft(activePlanSlot, [selected.external_id])}><Megaphone size={16} />加入曝光批次</button><button className="product-primary-button" onClick={() => openAction(selected, selected.recommendation)}><CheckCircle size={16} />记录商品修改</button></div></header>
      {selected.last_error_detail && <div className="product-item-diagnostic"><Warning size={17} weight="fill" /><span><b>{selected.last_error_code === "access_verification" ? "今日正式采集未取得数据" : selected.last_error_code === "item_unavailable" ? "商品详情不可读取" : "最近一次采集未完成"}</b><small>{productDiagnosticDetail(selected)}</small><em>最近尝试 {formatDate(selected.last_attempt_at)}（北京时间） · 当前展示 {selected.last_collected_at ? `${formatDate(selected.last_collected_at)} 的历史快照` : "的不是今日商品数据"}</em></span></div>}
      <div className="product-browse-accounting" aria-label="浏览量口径说明"><Eye size={18} weight="duotone" /><span><b>经营浏览 {integer.format(selected.browse_count)}</b><small>平台原始 {integer.format(selected.raw_browse_count)}，已排除 {selected.collection_views_excluded} 次成功采集自访问；经营策略只使用排除后的数据。</small></span></div>
      <div className="product-detail-grid">
        <div className="product-detail-trend"><h4>经营浏览趋势</h4><ProductTrend product={selected} /></div>
        <div className="product-funnel"><h4>从经营浏览到成交</h4><div><span><small>经营浏览</small><b>{integer.format(selected.browse_count)}</b><em>原始 {integer.format(selected.raw_browse_count)}</em></span><CaretRight size={17} /><span><small>咨询</small><b>{selected.inquiry_count}</b><em>{selected.inquiry_rate === null ? "—" : `${selected.inquiry_rate}%`}</em></span><CaretRight size={17} /><span><small>项目</small><b>{selected.converted_project_count}</b><em>{selected.deal_rate === null ? "—" : `${selected.deal_rate}%`}</em></span></div><p><TrendUp size={16} />关联收入 {money.format(selected.revenue_total)} · 实际利润 {money.format(selected.profit_total)}</p></div>
        <div className="product-strategy-evidence"><h4>当前建议与证据</h4><div className="product-window-summary"><span className={`quality-${selected.data_quality}`}>{confidenceLabels[selected.data_quality] || selected.data_quality}</span>{selected.recent_windows.map((window) => <small key={window.days}>{window.days === 1 ? "24h" : `${window.days}d`}：{window.browse_delta === null ? "待积累" : `+${window.browse_delta} 浏览 / +${window.inquiry_delta || 0} 咨询`}</small>)}</div>{selected.recommendation && selected.recommendation.status !== "dismissed" ? <><p><AttentionBadge value={selected.recommendation.attention} /><b>{selected.recommendation.title}</b></p><ul>{selected.recommendation.actions.map((action) => <li key={action}><CheckCircle size={15} />{action}</li>)}</ul></> : <div className="compact-empty"><PauseCircle size={26} /><span><b>{selected.recommendation?.status === "dismissed" ? "今日建议已暂不处理" : "等待首个快照"}</b><small>{selected.recommendation?.status === "dismissed" ? "明日数据变化后会重新评估。" : "系统不会在没有数据时生成策略。"}</small></span></div>}</div>
      </div>
      {selected.actions.length > 0 && <div className="product-action-history"><h4>最近人工动作</h4>{selected.actions.slice(0, 5).map((action) => <p key={action.id}><i><CheckCircle size={15} weight="fill" /></i><span><b>{actionLabels[action.action_type] || action.action_type}</b><small>{action.note || "未填写备注"}</small></span><time>{formatDate(action.happened_at)}{action.cost > 0 && ` · ${money.format(action.cost)}`}</time></p>)}</div>}
    </section>}

    {managementOpen && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setManagementOpen(false); }}><section className="product-modal product-management-modal" role="dialog" aria-modal="true" aria-labelledby="product-management-title">
      <header><span><Package size={20} /></span><div><h3 id="product-management-title">商品管理</h3><p>本人商品进入自动采集；你也可以在这里指定单个商品手动采集。</p></div><button type="button" aria-label="关闭" onClick={() => setManagementOpen(false)}><X size={18} /></button></header>
      <nav className="product-management-tabs" aria-label="商品归属分类">
        {([
          ["owned", "我的商品", data.products.length],
          ["pending", "待确认", data.summary.pending_products],
          ["excluded", "已排除", data.summary.excluded_products],
        ] as const).map(([key, label, count]) => <button type="button" className={managementTab === key ? "active" : ""} aria-pressed={managementTab === key} onClick={() => setManagementTab(key)} key={key}><span>{label}</span><b>{count}</b></button>)}
      </nav>
      <div className="product-management-list">{(managementTab === "owned" ? data.products : data.candidates.filter((product) => product.ownership_status === managementTab)).map((product) => {
        const state = collectionState(product);
        return <article key={product.external_id}>
          <i className={`ownership-${product.ownership_status}`}><Storefront size={19} weight="duotone" /></i>
          <span><small>{ownershipLabels[product.ownership_status] || product.ownership_status} · ID {product.external_id}</small><b>{product.title}</b><em>{product.last_error_detail || (product.ownership_status === "owned" ? `最近采集：${formatDate(product.last_attempt_at)}` : product.ownership_status === "pending" ? "可手动验证卖家，或等待下一次自动采集" : "卖家与当前登录账号不一致，历史仍然保留")}</em></span>
          <div className="product-management-state"><ProductCollectionBadge product={product} /><small>{state.key === "failed" ? formatDate(product.last_attempt_at) : product.monitoring_enabled ? "监测已启用" : "不参与统计"}</small></div>
          <div className="product-management-actions">
            <button type="button" disabled={busy || product.ownership_status === "excluded"} title={product.ownership_status === "excluded" ? "非当前账号商品不能采集" : "只读采集此商品"} onClick={() => void collectManually(product.external_id)}>{collectingScope === product.external_id ? <ArrowClockwise className="spin" size={15} /> : <ArrowClockwise size={15} />}{product.ownership_status === "pending" ? "验证并采集" : "采集"}</button>
            {product.ownership_status === "owned" && <button type="button" disabled={busy} onClick={() => void toggleMonitor(product)}>{product.monitoring_enabled ? <EyeSlash size={15} /> : <Eye size={15} />}{product.monitoring_enabled ? "暂停" : "恢复"}</button>}
          </div>
        </article>;
      })}{(managementTab === "owned" ? data.products : data.candidates.filter((product) => product.ownership_status === managementTab)).length === 0 && <div className="product-management-empty"><CheckCircle size={28} weight="duotone" /><span><b>{managementTab === "owned" ? "还没有确认属于你的商品" : managementTab === "pending" ? "没有待确认商品" : "没有被排除的商品"}</b><small>{managementTab === "owned" ? "添加商品后可手动验证，或等待下一次自动采集。" : "商品归属变化会自动更新到这里。"}</small></span></div>}</div>
      <footer><button type="button" onClick={() => setManagementOpen(false)}>关闭</button><button type="button" className="product-primary-button" onClick={() => { setManagementOpen(false); setRegisterOpen(true); }}><Plus size={16} />添加商品</button></footer>
    </section></div>}

    {registerOpen && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setRegisterOpen(false); }}><form className="product-modal" onSubmit={register}>
      <header><span><Plus size={20} /></span><div><h3>添加监测商品</h3><p>先保存商品 ID，随后可手动验证，或等待下一次自动采集。</p></div><button type="button" aria-label="关闭" onClick={() => setRegisterOpen(false)}><X size={18} /></button></header>
      <label><span>闲鱼商品 ID 或商品链接</span><input autoFocus value={registerReference} onChange={(event) => setRegisterReference(event.target.value)} placeholder="粘贴商品链接，或输入 itemId" /></label>
      <div className="product-modal-note"><ShieldCheck size={17} /><span>添加操作本身不会访问闲鱼。手动或自动采集都只读取数据，同一天只保留一个趋势点。</span></div>
      <footer><button type="button" onClick={() => setRegisterOpen(false)}>取消</button><button className="product-primary-button" disabled={busy || !registerReference.trim()}>{busy ? <ArrowClockwise className="spin" size={16} /> : <Plus size={16} />}加入监测</button></footer>
    </form></div>}

    {batchDraft && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setBatchDraft(null); }}><form className="product-modal product-batch-modal" onSubmit={createBatch} role="dialog" aria-modal="true" aria-labelledby="traffic-batch-dialog-title">
      <header><span><Megaphone size={20} /></span><div><h3 id="traffic-batch-dialog-title">建立多商品曝光批次</h3><p>一次选择多件商品，约 ¥5.9～¥6 是整个批次的总费用。</p></div><button type="button" aria-label="关闭" onClick={() => setBatchDraft(null)}><X size={18} /></button></header>
      <div className="product-batch-form-grid">
        <label><span>计划投放时间 · 北京时间</span><input type="datetime-local" value={batchDraft.plannedLocal} onChange={(event) => setBatchDraft({ ...batchDraft, plannedLocal: event.target.value })} /></label>
        <label><span>批次实际总费用</span><input type="number" min="0" step="0.1" value={batchDraft.cost} onChange={(event) => setBatchDraft({ ...batchDraft, cost: event.target.value })} /></label>
      </div>
      <fieldset className="product-batch-picker"><legend>选择商品 <small>建议 3–5 件，已选 {batchDraft.selectedIds.length}/5</small></legend><div>{data.products.filter((product) => product.monitoring_enabled).map((product) => {
        const checked = batchDraft.selectedIds.includes(product.external_id);
        return <label className={checked ? "selected" : ""} key={product.external_id}><input type="checkbox" checked={checked} onChange={() => toggleBatchProduct(product.external_id)} /><i><Storefront size={16} weight="duotone" /></i><span><b>{product.title}</b><small>{product.data_quality === "low" ? "探索数据" : `${confidenceLabels[product.data_quality] || product.data_quality} · ${product.browse_count} 浏览`}</small></span><em>{checked ? <CheckCircle size={17} weight="fill" /> : <Plus size={16} />}</em></label>;
      })}</div></fieldset>
      <label><span>可选备注</span><textarea rows={3} value={batchDraft.note} onChange={(event) => setBatchDraft({ ...batchDraft, note: event.target.value })} placeholder="例如：本批次轮换测试数据库、前端和小程序服务商品" /></label>
      <div className="product-modal-note"><ShieldCheck size={17} /><span>这里只建立计划和提醒。你仍需在闲鱼人工选择商品、确认套餐和付款；系统不会自动操作或花费。</span></div>
      <div className="product-modal-note warning"><Warning size={17} /><span>套餐曝光量只记录批次总数，不会虚构分摊到每件商品；单品效果看后续浏览、想要和咨询变化。</span></div>
      <footer><button type="button" onClick={() => setBatchDraft(null)}>取消</button><button className="product-primary-button" disabled={busy || batchDraft.selectedIds.length === 0 || !batchDraft.plannedLocal}>{busy ? <ArrowClockwise className="spin" size={16} /> : <Plus size={16} />}保存批次计划</button></footer>
    </form></div>}

    {batchOperation && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setBatchOperation(null); }}><form className="product-modal product-batch-operation-modal" onSubmit={saveBatchOperation} role="dialog" aria-modal="true" aria-labelledby="traffic-operation-dialog-title">
      <header><span>{batchOperation.mode === "complete" ? <CheckCircle size={20} /> : <ClipboardText size={20} />}</span><div><h3 id="traffic-operation-dialog-title">{batchOperation.mode === "complete" ? "记录曝光套餐完成" : `记录 ${checkpointLabels[batchOperation.checkpoint]} 检查点`}</h3><p>{batchOperation.batch.products.length} 件商品 · 批次总费用，不做单品费用分摊</p></div><button type="button" aria-label="关闭" onClick={() => setBatchOperation(null)}><X size={18} /></button></header>
      {batchOperation.mode === "complete" ? <>
        <div className="product-batch-form-grid"><label><span>批次实际总费用</span><input type="number" min="0" step="0.1" value={batchOperation.cost} onChange={(event) => setBatchOperation({ ...batchOperation, cost: event.target.value })} /></label><label><span>套餐总曝光量（可选）</span><input type="number" min="0" step="1" value={batchOperation.totalExposure} onChange={(event) => setBatchOperation({ ...batchOperation, totalExposure: event.target.value })} placeholder="只填批次总数" /></label></div>
        <div className="product-modal-note"><Timer size={17} /><span>即使套餐在 1 小时内完成，也不能立即判定效果结束。系统会继续提醒 24h 和 72h 的浏览、咨询长尾。</span></div>
      </> : <>
        <label><span>本次检查点</span><select value={batchOperation.checkpoint} onChange={(event) => setBatchOperation({ ...batchOperation, checkpoint: event.target.value as BatchOperationState["checkpoint"] })}>{(["h1", "h6", "h24", "h72"] as const).map((checkpoint) => <option value={checkpoint} key={checkpoint}>{checkpointLabels[checkpoint]}{batchOperation.batch.completed_checkpoints.includes(checkpoint) ? "（已记录，可修正）" : ""}</option>)}</select></label>
        <div className="product-checkpoint-editor"><div className="checkpoint-editor-head"><span>商品</span><span>累计浏览</span><span>累计想要</span><span>累计收藏</span><span>累计咨询</span></div>{batchOperation.batch.products.map((product) => {
          const row = batchOperation.rows[product.external_id];
          return <div className="checkpoint-editor-row" key={product.external_id}><span><b>{product.title}</b><small>T0 浏览 {product.baseline_browse_count} · 咨询 {product.baseline_inquiry_count}</small></span>{(["browse_count", "want_count", "collect_count", "inquiry_count"] as const).map((field) => <input key={field} aria-label={`${product.title}${field}`} type="number" min="0" step="1" value={row[field]} onChange={(event) => setBatchOperation({ ...batchOperation, rows: { ...batchOperation.rows, [product.external_id]: { ...row, [field]: event.target.value } } })} />)}</div>;
        })}</div>
      </>}
      <label><span>可选备注</span><textarea rows={3} value={batchOperation.note} onChange={(event) => setBatchOperation({ ...batchOperation, note: event.target.value })} placeholder="记录当时是否改过商品、回复是否及时或其他外部变化" /></label>
      <div className="product-modal-note warning"><Warning size={17} /><span>1h 数据可以不增长；真正判断会优先看 24h / 72h 浏览和咨询，并识别 72 小时内的重叠批次。</span></div>
      <footer><button type="button" onClick={() => setBatchOperation(null)}>取消</button><button className="product-primary-button" disabled={busy}>{busy ? <ArrowClockwise className="spin" size={16} /> : <CheckCircle size={16} />}{batchOperation.mode === "complete" ? "保存并开始长尾观察" : "保存检查点"}</button></footer>
    </form></div>}

    {actionTarget && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setActionTarget(null); }}><form className="product-modal product-action-modal" onSubmit={saveAction}>
      <header><span><CheckCircle size={20} /></span><div><h3>记录我已执行的商品修改</h3><p>{actionTarget.product.title}</p></div><button type="button" aria-label="关闭" onClick={() => setActionTarget(null)}><X size={18} /></button></header>
      <label><span>人工完成的动作</span><select value={actionType} onChange={(event) => setActionType(event.target.value)}>{Object.entries(actionLabels).filter(([value]) => value !== "traffic").map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label><span>备注</span><textarea rows={4} value={actionNote} onChange={(event) => setActionNote(event.target.value)} placeholder="例如：将标题第一句改为客户常用表达，其他内容不变" /></label>
      <div className="product-modal-note warning"><Warning size={17} /><span>这里不会替你修改、发布或投流，只记录你已经在闲鱼手动完成的动作。</span></div>
      <footer><button type="button" onClick={() => setActionTarget(null)}>取消</button><button className="product-primary-button" disabled={busy}>{busy ? <ArrowClockwise className="spin" size={16} /> : <CheckCircle size={16} />}保存并开始观察</button></footer>
    </form></div>}

    {marketImportOpen && <div className="product-modal-backdrop" role="presentation" onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setMarketImportOpen(false); } }} onMouseDown={(event) => { if (event.target === event.currentTarget) setMarketImportOpen(false); }}><form className="product-modal market-import-modal" onSubmit={importMarketReference} role="dialog" aria-modal="true" aria-labelledby="market-import-title">
      <header><span><UploadSimple size={20} /></span><div><h3 id="market-import-title">导入现有 Edge 搜索参考</h3><p>当前关键词：{data.market_reference.selected_keyword}</p></div><button type="button" aria-label="关闭" onClick={() => setMarketImportOpen(false)}><X size={18} /></button></header>
      <ol className="market-import-steps"><li><i>1</i><span><b>在已登录的 Edge 中搜索</b><small>不要新开第二个闲鱼网站，也不要自动翻页抓取。</small></span></li><li><i>2</i><span><b>让 Codex 整理公开字段</b><small>只保留位置、标题、价格和公开标签。</small></span></li><li><i>3</i><span><b>粘贴 JSON 并确认导入</b><small>有效导入会完成今天的更新并清除提醒。</small></span></li></ol>
      <div className="market-import-schema"><small>接受的结构</small><code>{`{"results":[{"position":1,"title":"公开标题","price":99,"tags":["公开标签"]}]}`}</code></div>
      <label><span>Codex 整理后的 JSON</span><textarea autoFocus rows={10} value={marketImportText} onChange={(event) => setMarketImportText(event.target.value)} placeholder='粘贴包含 results 数组的 JSON；不要包含 Cookie、卖家 ID、商品平台 ID 或 HTML' /></label>
      <label><span>可选说明</span><input value={marketImportNote} onChange={(event) => setMarketImportNote(event.target.value)} maxLength={500} placeholder="例如：Edge 默认排序，未翻页" /></label>
      <div className="product-modal-note"><ShieldCheck size={17} /><span>{data.market_reference.safety_note}</span></div>
      <footer><button type="button" onClick={() => setMarketImportOpen(false)}>取消</button><button className="product-primary-button" disabled={busy || !marketImportText.trim()}>{busy ? <ArrowClockwise className="spin" size={16} /> : <UploadSimple size={16} />}校验并导入</button></footer>
    </form></div>}

    {modificationDraft && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setModificationDraft(null); }}><form className="product-modal modification-experiment-modal" onSubmit={saveModificationExperiment} role="dialog" aria-modal="true" aria-labelledby="modification-experiment-title">
      <header><span><Flask size={20} /></span><div><h3 id="modification-experiment-title">建立单变量修改实验</h3><p>{modificationDraft.suggestion.title}</p></div><button type="button" aria-label="关闭" onClick={() => setModificationDraft(null)}><X size={18} /></button></header>
      <label><span>本次只改变</span><select value={modificationDraft.variable} onChange={(event) => setModificationDraft({ ...modificationDraft, variable: event.target.value as ModificationDraftState["variable"] })}><option value="title">标题</option><option value="cover">首图</option><option value="description">描述</option><option value="price">价格</option></select></label>
      <label><span>修改前</span><textarea rows={4} value={modificationDraft.beforeValue} onChange={(event) => setModificationDraft({ ...modificationDraft, beforeValue: event.target.value })} placeholder="填写当前值或当前表达" /></label>
      <label><span>修改后</span><textarea rows={4} value={modificationDraft.afterValue} onChange={(event) => setModificationDraft({ ...modificationDraft, afterValue: event.target.value })} placeholder="填写你将在闲鱼手动改成的值" /></label>
      <div className="product-modal-note warning"><Warning size={17} /><span>保存前请先在闲鱼人工完成这一次修改，并确保其他标题、首图、描述和价格保持不变。系统只记录与观察。</span></div>
      <footer><button type="button" onClick={() => setModificationDraft(null)}>取消</button><button className="product-primary-button" disabled={busy || !modificationDraft.beforeValue.trim() || !modificationDraft.afterValue.trim() || modificationDraft.beforeValue.trim() === modificationDraft.afterValue.trim()}>{busy ? <ArrowClockwise className="spin" size={16} /> : <Flask size={16} />}开始 7 天观察</button></footer>
    </form></div>}

    {experimentDecision && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setExperimentDecision(null); }}><section className="product-modal experiment-decision-modal" role="dialog" aria-modal="true" aria-labelledby="experiment-decision-title">
      <header><span><ListChecks size={20} /></span><div><h3 id="experiment-decision-title">修改实验结果</h3><p>{experimentDecision.item_title} · {actionLabels[experimentDecision.variable]}</p></div><button type="button" aria-label="关闭" onClick={() => setExperimentDecision(null)}><X size={18} /></button></header>
      <div className="experiment-change"><span><small>修改前</small><b>{experimentDecision.before_value}</b></span><ArrowRight size={18} /><span><small>修改后</small><b>{experimentDecision.after_value}</b></span></div>
      <dl className="experiment-result-metrics"><div><dt>浏览变化</dt><dd>+{Number(experimentDecision.result.browse_delta || 0)}</dd></div><div><dt>咨询变化</dt><dd>+{Number(experimentDecision.result.inquiry_delta || 0)}</dd></div><div><dt>观察截止</dt><dd>{formatDate(experimentDecision.observation_until)}</dd></div></dl>
      <label><span>判断说明（可选）</span><textarea rows={3} value={experimentNote} onChange={(event) => setExperimentNote(event.target.value)} placeholder="记录外部变化或判断依据" /></label>
      {!experimentDecision.can_evaluate && <div className="product-modal-note"><Timer size={17} /><span>观察期尚未结束，可继续观察或因明显负面影响提前回退；暂不能确认长期保留。</span></div>}
      <footer className="experiment-decision-actions"><button type="button" onClick={() => setExperimentDecision(null)}>关闭</button><button type="button" disabled={busy} onClick={() => void resolveExperiment("continue")}><Timer size={15} />再观察 3 天</button><button type="button" disabled={busy} onClick={() => void resolveExperiment("rollback")}><ArrowCounterClockwise size={15} />记录回退</button><button type="button" className="product-primary-button" disabled={busy || !experimentDecision.can_evaluate} onClick={() => void resolveExperiment("keep")}><CheckCircle size={15} />保留修改</button></footer>
    </section></div>}

    {toast && <div className="product-toast" role="status"><CheckCircle size={19} weight="fill" />{toast}</div>}
  </div>;
}
