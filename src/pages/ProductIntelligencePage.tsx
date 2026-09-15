import { ProductOverviewWorkspace } from '../components/workspace/ProductOverviewWorkspace';
import { ProductMetricSummary } from '../components/workspace/ProductMetricSummary';
import { ProductLinkedProjects } from '../components/workspace/ProductLinkedProjects';
import {
  ArrowClockwise,
  ArrowCounterClockwise,
  ArrowRight,
  BellRinging,
  CalendarCheck,
  CaretLeft,
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
  LinkSimple,
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
  ShieldWarning,
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
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { type FormEvent, type KeyboardEvent as ReactKeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  connectPlatformEvents,
  localPlatformService,
  type ProductIntelligenceView,
  type ProductCollectionAttemptView,
  type ProductModificationExperimentView,
  type ProductModificationSuggestionView,
  type ProductRegistrationPreview,
  type ProductOperatingPlanView,
  type ProductOperatingPlanSlotView,
  type ProductRecommendationView,
  type ProductTrafficReplanPreviewView,
  type ProductTrafficStartPreviewView,
  type ProductTrafficBatchItemView,
  type ProductTrafficBatchView,
  type TrafficCommercialAttributionView,
  type TrafficExperimentView,
  type TrafficGrowthOverviewView,
  type ProductView,
} from "../data/localPlatformService";
import { TrafficGrowthWorkbench } from "../components/TrafficGrowthWorkbench";
import { ExposureAnalytics } from "./ProductExposureWorkbench";
import { MarketReferenceWorkbench } from "./ProductMarketWorkbench";
import { ProductLaunchWorkbench } from "./ProductLaunchWorkbench";
import {
  formatTrafficDateTime,
  formatTrafficPlanDate,
  formatTrafficPlanSlotDateTime,
} from "../utils/trafficDateTime";
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
  h48: "+48 小时",
  h72: "+72 小时",
};

const checkpointShortLabels: Record<string, string> = {
  h1: "+1h",
  h6: "+6h",
  h24: "+24h",
  h48: "+48h",
  h72: "+72h",
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
  late_capture: "采集延迟 · 仅作观察",
  confounded: "批次重叠",
  invalidated: "基线无效 · 已终止",
};

const trafficBatchStatusLabels: Record<string, string> = {
  planned: "计划中",
  running: "套餐进行中",
  observing: "观察中",
  closed: "观察完成",
  invalidated: "基线无效 · 已终止",
  cancelled: "已取消",
};

const trafficBatchCreatedDay = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "long",
  day: "numeric",
  weekday: "short",
});

function batchCreatedDayLabel(value: string) {
  return trafficBatchCreatedDay.format(parsePlatformDate(value));
}

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

function todayBeijingKey() {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function defaultOperatingPlanSlotId(plan: ProductOperatingPlanView) {
  return plan.slots.find((slot) => slot.date === todayBeijingKey())?.id
    || plan.slots[0]?.id
    || null;
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
  return formatTrafficPlanDate(value);
}

function formatPlanSlotDateTime(date: string, time: string) {
  return formatTrafficPlanSlotDateTime(date, time);
}

function observationPlanTitle(batch: ProductTrafficBatchView) {
  if (!batch.due_checkpoint) return "继续观察当前批次";
  const checkpoint = checkpointShortLabels[batch.due_checkpoint];
  if (batch.due_ready) {
    return `补录 ${formatTrafficDateTime(batch.started_at)} 批次 ${checkpoint}`;
  }
  return `继续观察，${checkpoint} 将于 ${formatTrafficDateTime(batch.due_at)} 到期`;
}

function checkpointOptionState(
  batch: ProductTrafficBatchView,
  checkpoint: "h1" | "h6" | "h24" | "h48" | "h72",
) {
  if (batch.completed_checkpoints.includes(checkpoint)) {
    return { enabled: true, detail: "已记录，可修正" };
  }
  if (batch.due_checkpoint === checkpoint) {
    return {
      enabled: batch.due_ready,
      detail: batch.due_ready ? "已到期，可补录" : `最早 ${formatTrafficDateTime(batch.due_at)}（北京时间）`,
    };
  }
  return { enabled: false, detail: "请按顺序完成前一检查点" };
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
        : `最近一次采集有 ${run.failed_count} 个商品触发访问验证；这条记录产生于批次熔断升级前。新版保护已启用：以后首件触发即停止，其余商品标记为保护性跳过。请先在现有 Ego Lite 完成人工验证，更新本机连接并重启服务，再从单件采集开始。`,
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
    return "这条失败记录产生于批次熔断升级前。新版保护已启用：以后首件触发访问验证即停止，其余商品不会继续请求。请先在现有 Ego Lite 完成人工验证，更新本机连接并重启服务，再从单件采集开始。";
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
            <stop offset="0%" stopColor="#1670ff" stopOpacity={0.22} />
            <stop offset="100%" stopColor="#1670ff" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="#e9eaf4" strokeDasharray="3 3" />
        <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "#8c91a5" }} />
        <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "#8c91a5" }} />
        <Tooltip formatter={(value) => [`${value} 次`, "经营浏览"]} />
        <Area type="monotone" dataKey="browse_count" stroke="#1670ff" strokeWidth={2.5} fill="url(#productBrowseArea)" />
      </AreaChart>
    </ResponsiveContainer>
  </div>;
}

type ExposureDeltaMetric = "browse" | "want" | "collect" | "inquiry";

interface ExposureDeltaMetricConfig {
  key: ExposureDeltaMetric;
  label: string;
  baselineKey: "baseline_browse_count" | "baseline_want_count" | "baseline_collect_count" | "baseline_inquiry_count";
  checkpointValueKey: "browse_count" | "want_count" | "collect_count" | "inquiry_count";
  checkpointDeltaKey: "browse_delta" | "want_delta" | "collect_delta" | "inquiry_delta";
}

const exposureDeltaMetrics: ExposureDeltaMetricConfig[] = [
  { key: "browse", label: "浏览", baselineKey: "baseline_browse_count", checkpointValueKey: "browse_count", checkpointDeltaKey: "browse_delta" },
  { key: "want", label: "想要", baselineKey: "baseline_want_count", checkpointValueKey: "want_count", checkpointDeltaKey: "want_delta" },
  { key: "collect", label: "收藏", baselineKey: "baseline_collect_count", checkpointValueKey: "collect_count", checkpointDeltaKey: "collect_delta" },
  { key: "inquiry", label: "咨询", baselineKey: "baseline_inquiry_count", checkpointValueKey: "inquiry_count", checkpointDeltaKey: "inquiry_delta" },
];

function exposureDeltaStagesForBatch(batch: ProductTrafficBatchView) {
  return [
    { key: "t0", label: "T0" },
    ...batch.checkpoint_sequence.map((checkpoint) => ({
      key: checkpoint,
      label: checkpointShortLabels[checkpoint] || compactCheckpointLabel(checkpoint),
    })),
  ];
}

const exposureLineColors = ["#5f3df5", "#2f89ed", "#3fb562", "#f26b18", "#8a63f5"];

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => (
    typeof window !== "undefined" && window.matchMedia(query).matches
  ));

  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);

  return matches;
}

function compactCheckpointLabel(value: string | null) {
  if (!value) return "T0";
  return `+${value.replace(/^h/, "")}h`;
}

function productMetricDelta(
  product: ProductTrafficBatchItemView,
  checkpoint: string | null,
  metric: ExposureDeltaMetricConfig,
) {
  if (!checkpoint) return 0;
  return (product.checkpoints || []).find((value) => value.checkpoint === checkpoint)?.[metric.checkpointDeltaKey] ?? 0;
}

function signedInteger(value: number) {
  return `${value > 0 ? "+" : ""}${integer.format(value)}`;
}

function exploratoryMetricChange(
  point: ProductTrafficBatchView["exploratory_points"][number],
  metric: ExposureDeltaMetricConfig,
) {
  const key = `${metric.key}_change` as "browse_change" | "want_change" | "collect_change" | "inquiry_change";
  return point[key];
}

function productExploratoryMetricChange(
  product: ProductTrafficBatchItemView,
  metric: ExposureDeltaMetricConfig,
) {
  const latest = product.exploratory_points[product.exploratory_points.length - 1];
  return latest ? exploratoryMetricChange(latest, metric) : 0;
}

function ExposureDeltaTooltip({
  active,
  label,
  batch,
  metric,
  selectedProductId,
  compact,
}: {
  active?: boolean;
  label: string;
  batch: ProductTrafficBatchView;
  metric: ExposureDeltaMetricConfig;
  selectedProductId: string | null;
  compact: boolean;
}) {
  if (!active) return null;
  const stage = exposureDeltaStagesForBatch(batch).find((value) => value.label === label);
  if (!stage) return null;
  const products = compact && selectedProductId
    ? batch.products.filter((product) => product.external_id === selectedProductId)
    : batch.products;
  const rows = products.flatMap((product) => {
    if (stage.key === "t0") {
      return [{
        product,
        total: product[metric.baselineKey],
        delta: 0,
        recordedAt: product.baseline_captured_at,
      }];
    }
    const checkpoint = (product.checkpoints || []).find((value) => value.checkpoint === stage.key);
    if (!checkpoint) return [];
    return [{
      product,
      total: checkpoint[metric.checkpointValueKey],
      delta: checkpoint[metric.checkpointDeltaKey],
      recordedAt: checkpoint.recorded_at,
    }];
  });

  return <div className="exposure-delta-tooltip">
    <strong>{label} · {metric.label}</strong>
    {rows.length ? rows.map((row) => <div key={row.product.external_id}>
      <i style={{ backgroundColor: exposureLineColors[batch.products.indexOf(row.product) % exposureLineColors.length] }} />
      <span><b>{row.product.title}</b><small>累计 {integer.format(row.total)} · 较 T0 +{integer.format(row.delta)}</small></span>
      <time>{row.recordedAt ? formatDate(row.recordedAt) : "时间未记录"}</time>
    </div>) : <small>这个检查点还没有真实记录</small>}
  </div>;
}

function ExposureProductDelta({
  batches,
  embedded = false,
}: {
  batches: ProductTrafficBatchView[];
  initialBatchId?: string | null;
  embedded?: boolean;
}) {
  const compact = useMediaQuery("(max-width: 560px)");
  const reduceMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const [selectedMetricKey, setSelectedMetricKey] = useState<ExposureDeltaMetric>("browse");
  const [selectedProductId, setSelectedProductId] = useState<string | null>(batches[0]?.products[0]?.external_id || null);
  const selectedBatch = batches[0];
  const selectedMetric = exposureDeltaMetrics.find((metric) => metric.key === selectedMetricKey) || exposureDeltaMetrics[0];

  useEffect(() => {
    if (!selectedBatch) {
      setSelectedProductId(null);
      return;
    }
    if (!selectedBatch.products.some((product) => product.external_id === selectedProductId)) {
      setSelectedProductId(selectedBatch.products[0]?.external_id || null);
    }
  }, [selectedBatch, selectedProductId]);

  if (!selectedBatch) return null;
  const exposureDeltaStages = exposureDeltaStagesForBatch(selectedBatch);

  if (!selectedBatch.has_reliable_baseline && !selectedBatch.exploratory_available) {
    return <section className={`exposure-delta-card ${embedded ? "is-embedded" : ""} exposure-delta-unavailable`}>
      <ShieldWarning size={28} weight="duotone" />
      <span><small>FACT RECORD</small><h4>只有事实记录，暂时无法比较变化</h4><p>这笔投放没有可靠 T0，也没有两组可比较的真实记录。费用、实际时间和累计事实仍然保留，系统不会把 0 当作基线。</p></span>
    </section>;
  }

  if (!selectedBatch.has_reliable_baseline) {
    const exploratoryRanking = [...selectedBatch.products]
      .map((product, index) => ({
        product,
        color: exposureLineColors[index % exposureLineColors.length],
        change: productExploratoryMetricChange(product, selectedMetric),
      }))
      .sort((left, right) => right.change - left.change);
    const selectedProductIndex = Math.max(0, selectedBatch.products.findIndex((product) => product.external_id === selectedProductId));
    const chartData = selectedBatch.exploratory_points.map((point) => ({
      stage: point.label,
      value: exploratoryMetricChange(point, selectedMetric),
    }));
    const selectedProduct = selectedBatch.products[selectedProductIndex];
    const selectedProductData = (selectedProduct?.exploratory_points || []).map((point) => ({
      stage: point.label,
      value: exploratoryMetricChange(point, selectedMetric),
    }));
    const naturalRange = selectedBatch.natural_browse_low !== null && selectedBatch.natural_browse_high !== null
      ? `+${integer.format(selectedBatch.natural_browse_low)}～+${integer.format(selectedBatch.natural_browse_high)}`
      : "样本不足";

    const selectRelativeProduct = (offset: number) => {
      const nextIndex = Math.min(
        selectedBatch.products.length - 1,
        Math.max(0, selectedProductIndex + offset),
      );
      setSelectedProductId(selectedBatch.products[nextIndex]?.external_id || null);
    };

    return <section className={`exposure-delta-card is-exploratory ${embedded ? "is-embedded" : ""}`} aria-labelledby={`exploratory-title-${selectedBatch.id}`}>
      <header className="exposure-delta-head">
        <span><small>EXPLORATORY OBSERVATION</small><h4 id={`exploratory-title-${selectedBatch.id}`}>实测变化 · 探索性分析</h4><p>{selectedBatch.exploratory_summary}</p></span>
        <em className="exposure-analysis-tier is-exploratory"><Flask size={14} />{selectedBatch.analysis_tier_label} · 低置信</em>
      </header>
      <div className="exposure-exploratory-warning"><ShieldWarning size={17} weight="duotone" /><span><b>不是曝光贡献值</b><small>无可靠 T0；这条曲线只描述参考记录之后实际发生的变化，不进入预算、时段、复投或商品优先级结论。</small></span></div>
      <div className="exposure-delta-controls">
        <div className="exposure-metric-tabs" role="tablist" aria-label="选择探索性变化指标">
          {exposureDeltaMetrics.map((metric) => <button
            aria-selected={selectedMetric.key === metric.key}
            className={selectedMetric.key === metric.key ? "active" : ""}
            key={metric.key}
            onClick={() => setSelectedMetricKey(metric.key)}
            role="tab"
            type="button"
          >{metric.label}</button>)}
        </div>
        <span className="exposure-delta-scope-note">参考：{selectedBatch.exploratory_reference_label}</span>
      </div>
      {compact && selectedProduct && <div className="exposure-product-switcher" aria-label="切换商品">
        <button aria-label="上一件商品" disabled={selectedProductIndex === 0} onClick={() => selectRelativeProduct(-1)} type="button"><CaretLeft size={18} /></button>
        <strong><i style={{ backgroundColor: exposureLineColors[selectedProductIndex % exposureLineColors.length] }} />{selectedProduct.title}<em>{signedInteger(productExploratoryMetricChange(selectedProduct, selectedMetric))}</em></strong>
        <span>{selectedProductIndex + 1} / {selectedBatch.products.length}</span>
        <button aria-label="下一件商品" disabled={selectedProductIndex >= selectedBatch.products.length - 1} onClick={() => selectRelativeProduct(1)} type="button"><CaretRight size={18} /></button>
      </div>}
      <div className="exposure-delta-layout">
        <div className="exposure-delta-chart-column">
          <div className="exposure-delta-chart" aria-label={`${selectedMetric.label}实测变化曲线`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={compact ? selectedProductData : chartData} margin={{ top: 18, right: 18, left: -14, bottom: 2 }}>
                <CartesianGrid vertical={false} stroke="#ece9f4" strokeDasharray="4 4" />
                <XAxis dataKey="stage" axisLine={{ stroke: "#dfe1eb" }} tickLine={false} tick={{ fontSize: 11, fill: "#777e96", fontWeight: 650 }} />
                <YAxis allowDecimals={false} axisLine={false} tickFormatter={(value) => signedInteger(Number(value))} tickLine={false} tick={{ fontSize: 10, fill: "#8b90a5" }} width={42} />
                <Tooltip formatter={(value) => [signedInteger(Number(value)), `${selectedMetric.label}实测变化`]} labelFormatter={(label) => `${label} · 相对观察参考`} />
                <Line connectNulls={false} dataKey="value" dot={{ r: 4, strokeWidth: 2, fill: "#fff" }} isAnimationActive={!reduceMotion} stroke="#7654e8" strokeWidth={2.8} type="linear" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="exposure-delta-legend" aria-label="商品探索排名">
            {selectedBatch.products.map((product, index) => <button aria-current={product.external_id === selectedProductId ? "true" : undefined} key={product.external_id} onClick={() => setSelectedProductId(product.external_id)} type="button"><i style={{ backgroundColor: exposureLineColors[index % exposureLineColors.length] }} />{product.title}</button>)}
          </div>
          <p>参考记录：{selectedBatch.exploratory_reference_label} {formatTrafficDateTime(selectedBatch.exploratory_reference_at)} → {selectedBatch.exploratory_through_label} {formatTrafficDateTime(selectedBatch.exploratory_through_at)}。</p>
        </div>
        <aside className="exposure-delta-ranking exploratory-ranking">
          <h5>当前实测变化排名</h5>
          <p>只用于批内方向判断，不生成复投资格</p>
          <div>{exploratoryRanking.map((row, index) => <button aria-current={row.product.external_id === selectedProductId ? "true" : undefined} className={row.product.external_id === selectedProductId ? "active" : ""} key={row.product.external_id} onClick={() => setSelectedProductId(row.product.external_id)} type="button"><i style={{ backgroundColor: row.color }} /><b>{index + 1}</b><span>{row.product.title}</span><em /><strong>{signedInteger(row.change)}</strong></button>)}</div>
          <footer><span>批次合计</span><strong>{signedInteger(selectedMetric.key === "browse" ? selectedBatch.observed_browse_change : selectedMetric.key === "want" ? selectedBatch.observed_want_change : selectedMetric.key === "collect" ? selectedBatch.observed_collect_change : selectedBatch.observed_inquiry_change)}</strong></footer>
        </aside>
      </div>
      <div className="exposure-exploratory-evidence">
        <span><small>历史自然浏览范围</small><b>{naturalRange}</b><em>{selectedBatch.natural_sample_size} 段 · {selectedBatch.natural_item_count} 件</em></span>
        <span><small>同期未投放对照</small><b>{selectedBatch.control_browse_expected === null ? "不可用" : `预计 +${selectedBatch.control_browse_expected}`}</b><em>{selectedBatch.control_item_count} 件可比较</em></span>
        <span><small>方向性区间</small><b>{selectedBatch.directional_browse_low === null || selectedBatch.directional_browse_high === null ? "不可估" : `${signedInteger(selectedBatch.directional_browse_low)}～${signedInteger(selectedBatch.directional_browse_high)}`}</b><em>观察变化减自然范围</em></span>
      </div>
      <details className="exposure-analysis-limitations"><summary>查看前提与失效条件</summary><ul>{selectedBatch.analysis_limitations.map((line) => <li key={line}>{line}</li>)}</ul></details>
    </section>;
  }

  const currentCheckpoint = selectedBatch.observation_checkpoint
    || selectedBatch.completed_checkpoints[selectedBatch.completed_checkpoints.length - 1]
    || null;
  const excludedFromBusinessConclusion = !selectedBatch.analysis_eligible;
  const ranking = [...selectedBatch.products]
    .map((product, index) => ({
      product,
      color: exposureLineColors[index % exposureLineColors.length],
      delta: productMetricDelta(product, currentCheckpoint, selectedMetric),
    }))
    .sort((left, right) => right.delta - left.delta);
  const maxRankingDelta = Math.max(1, ...ranking.map((value) => value.delta));
  const batchTotal = ranking.reduce((sum, value) => sum + value.delta, 0);
  const selectedProductIndex = Math.max(0, selectedBatch.products.findIndex((product) => product.external_id === selectedProductId));
  const chartData = exposureDeltaStages.map((stage) => {
    const row: Record<string, string | number | null> = { stage: stage.label };
    selectedBatch.products.forEach((product) => {
      if (stage.key === "t0") {
        row[product.external_id] = 0;
        return;
      }
      const checkpoint = (product.checkpoints || []).find((value) => value.checkpoint === stage.key);
      row[product.external_id] = checkpoint ? checkpoint[selectedMetric.checkpointDeltaKey] : null;
    });
    return row;
  });

  const selectRelativeProduct = (offset: number) => {
    const nextIndex = Math.min(
      selectedBatch.products.length - 1,
      Math.max(0, selectedProductIndex + offset),
    );
    setSelectedProductId(selectedBatch.products[nextIndex]?.external_id || null);
  };

  const titleId = embedded ? `exposure-delta-title-${selectedBatch.id}` : "exposure-delta-title";

  return <section className={`exposure-delta-card ${embedded ? "is-embedded" : ""}`} aria-labelledby={titleId}>
    <header className="exposure-delta-head">
      <span><small>SINGLE-LISTING DELTA</small><h4 id={titleId}>{embedded ? "本批次逐商品曲线" : "单品增量轨迹"}</h4><p>同一次曝光批次内，对比每件商品相对 T0 的真实变化</p></span>
    </header>

    <div className="exposure-delta-controls">
      <div className="exposure-metric-tabs" role="tablist" aria-label="选择单品变化指标">
        {exposureDeltaMetrics.map((metric) => <button
          aria-selected={selectedMetric.key === metric.key}
          className={selectedMetric.key === metric.key ? "active" : ""}
          key={metric.key}
          onClick={() => setSelectedMetricKey(metric.key)}
          role="tab"
          type="button"
        >{metric.label}</button>)}
      </div>
      <span className="exposure-delta-scope-note">只绘制真实检查点</span>
    </div>

    {compact && <div className="exposure-product-switcher" aria-label="切换商品">
      <button aria-label="上一件商品" disabled={selectedProductIndex === 0} onClick={() => selectRelativeProduct(-1)} type="button"><CaretLeft size={18} /></button>
      <strong><i style={{ backgroundColor: exposureLineColors[selectedProductIndex % exposureLineColors.length] }} />{selectedBatch.products[selectedProductIndex]?.title}<em>+{productMetricDelta(selectedBatch.products[selectedProductIndex], currentCheckpoint, selectedMetric)}</em></strong>
      <span>{selectedProductIndex + 1} / {selectedBatch.products.length}</span>
      <button aria-label="下一件商品" disabled={selectedProductIndex >= selectedBatch.products.length - 1} onClick={() => selectRelativeProduct(1)} type="button"><CaretRight size={18} /></button>
    </div>}

    <div className="exposure-delta-layout">
      <div className="exposure-delta-chart-column">
        <div className="exposure-delta-zone-labels" aria-hidden="true"><span>早期信号</span><span>经营结论</span></div>
        <div className="exposure-delta-chart" aria-label={`${selectedMetric.label}相对 T0 的逐商品变化曲线`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 18, right: 18, left: -14, bottom: 2 }}>
              <ReferenceArea x1="T0" x2="+6h" fill="#f2efff" fillOpacity={0.64} stroke="none" />
              <ReferenceArea x1="+24h" x2={checkpointShortLabels[selectedBatch.terminal_checkpoint] || compactCheckpointLabel(selectedBatch.terminal_checkpoint)} fill="#f7f8fc" fillOpacity={0.88} stroke="none" />
              <CartesianGrid vertical={false} stroke="#e8e9f2" strokeDasharray="4 4" />
              <XAxis dataKey="stage" axisLine={{ stroke: "#dfe1eb" }} tickLine={false} tick={{ fontSize: 11, fill: "#777e96", fontWeight: 650 }} />
              <YAxis allowDecimals={false} axisLine={false} tickFormatter={(value) => value === 0 ? "0" : `+${value}`} tickLine={false} tick={{ fontSize: 10, fill: "#8b90a5" }} width={42} />
              <Tooltip
                content={(props) => <ExposureDeltaTooltip
                  active={props.active}
                  batch={selectedBatch}
                  compact={compact}
                  label={String(props.label || "")}
                  metric={selectedMetric}
                  selectedProductId={selectedProductId}
                />}
                cursor={{ stroke: "#c8c2e8", strokeDasharray: "3 3" }}
              />
              {selectedBatch.products.map((product, index) => {
                const isSelected = product.external_id === selectedProductId;
                if (compact && !isSelected) return null;
                return <Line
                  activeDot={{ r: isSelected ? 5 : 4, strokeWidth: 2, fill: "#ffffff" }}
                  connectNulls={false}
                  dataKey={product.external_id}
                  dot={{ r: isSelected ? 4 : 3, strokeWidth: 2, fill: "#ffffff" }}
                  isAnimationActive={!reduceMotion}
                  key={product.external_id}
                  name={product.title}
                  stroke={exposureLineColors[index % exposureLineColors.length]}
                  strokeOpacity={selectedProductId && !isSelected ? 0.72 : 1}
                  strokeWidth={isSelected ? 3 : 2.2}
                  type="linear"
                />;
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="exposure-delta-stage-status" aria-label="检查点记录状态">
          {exposureDeltaStages.map((stage) => {
            const recorded = stage.key === "t0" || selectedBatch.completed_checkpoints.includes(stage.key);
            return <span key={stage.key}>{recorded
              ? stage.key !== "t0" && excludedFromBusinessConclusion
                ? "已记录 · 未纳入"
                : "已记录"
              : "等待记录"}</span>;
          })}
        </div>
        <div className="exposure-delta-legend" aria-label="商品图例">
          {selectedBatch.products.map((product, index) => <button
            aria-current={product.external_id === selectedProductId ? "true" : undefined}
            key={product.external_id}
            onClick={() => setSelectedProductId(product.external_id)}
            type="button"
          ><i style={{ backgroundColor: exposureLineColors[index % exposureLineColors.length] }} />{product.title}</button>)}
        </div>
        <p>{excludedFromBusinessConclusion
          ? `${selectedBatch.baseline_quality_label}：真实检查点继续展示，但只作批次内观察，不进入时段、预算或商品优先级结论。`
          : `1h / 6h 仅作早期观察；24h / ${selectedBatch.observation_window_hours}h 才进入经营判断。曲线表示观察增量，不等同于平台因果归因。`}</p>
      </div>

      <aside className="exposure-delta-ranking" aria-labelledby="exposure-ranking-title">
        <h5 id="exposure-ranking-title">当前 {compactCheckpointLabel(currentCheckpoint)} 排名</h5>
        <p>{excludedFromBusinessConclusion ? "批次内观察，不进入时段 / 预算 / 商品优先级结论" : "仅比较当前批次内的真实增量"}</p>
        <div>
          {ranking.map((row, index) => <button
            aria-current={row.product.external_id === selectedProductId ? "true" : undefined}
            className={row.product.external_id === selectedProductId ? "active" : ""}
            key={row.product.external_id}
            onClick={() => setSelectedProductId(row.product.external_id)}
            type="button"
          >
            <i style={{ backgroundColor: row.color }} />
            <b>{index + 1}</b>
            <span>{row.product.title}</span>
            <em><u style={{ backgroundColor: row.color, width: `${Math.max(row.delta ? 12 : 0, row.delta / maxRankingDelta * 100)}%` }} /></em>
            <strong>+{integer.format(row.delta)}</strong>
          </button>)}
        </div>
        <footer><span>批次合计</span><strong>+{integer.format(batchTotal)}</strong></footer>
      </aside>
    </div>
  </section>;
}

function batchAggregateSeries(batch: ProductTrafficBatchView) {
  return exposureDeltaStagesForBatch(batch).map((stage) => ({
    stage: stage.label,
    browse: stage.key === "t0"
      ? 0
      : batch.checkpoint_metrics.find((value) => value.checkpoint === stage.key)?.browse_delta ?? null,
  }));
}

function ExposureBatchMiniChart({ batch }: { batch: ProductTrafficBatchView }) {
  if (!batch.started_at) {
    return <div className="product-batch-no-chart"><ChartLineUp size={18} weight="duotone" /><span><b>尚未开始，没有真实曲线</b><small>完成整批 T0 并人工投放后，才会按实际开始时间绘制。</small></span></div>;
  }
  if (!batch.has_reliable_baseline && batch.exploratory_available) {
    const series = batch.exploratory_points.map((point) => ({
      stage: point.label,
      browse: point.browse_change,
    }));
    return <div className="product-batch-mini-chart is-exploratory" aria-label={`${formatTrafficDateTime(batch.started_at)} 批次实测变化曲线`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 7, right: 8, bottom: 3, left: 8 }}>
          <XAxis dataKey="stage" axisLine={false} tickLine={false} tick={{ fontSize: 8, fill: "#9397a8" }} />
          <YAxis hide domain={["auto", "auto"]} />
          <Line connectNulls={false} dataKey="browse" dot={{ r: 2.5, fill: "#fff", strokeWidth: 1.5 }} isAnimationActive={false} stroke="#8b64db" strokeDasharray="5 3" strokeWidth={2.2} type="linear" />
        </LineChart>
      </ResponsiveContainer>
      <span className="product-batch-inquiry-badge"><Flask size={13} />实测浏览 {signedInteger(batch.observed_browse_change)}</span>
    </div>;
  }
  if (!batch.has_reliable_baseline) {
    return <div className="product-batch-no-chart is-missing-baseline"><ShieldWarning size={18} weight="duotone" /><span><b>缺少可靠 T0，无法计算增量</b><small>仍可记录后续累计值；不会用零值冒充真实基线。</small></span></div>;
  }
  return <div className="product-batch-mini-chart" aria-label={`${formatTrafficDateTime(batch.started_at)} 批次聚合浏览增量曲线`}>
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={batchAggregateSeries(batch)} margin={{ top: 7, right: 8, bottom: 3, left: 8 }}>
        <XAxis dataKey="stage" axisLine={false} tickLine={false} tick={{ fontSize: 8, fill: "#9397a8" }} />
        <YAxis hide domain={["auto", "auto"]} />
        <Line connectNulls={false} dataKey="browse" dot={{ r: 2.5, fill: "#fff", strokeWidth: 1.5 }} isAnimationActive={false} stroke="#6544f4" strokeWidth={2.2} type="linear" />
      </LineChart>
    </ResponsiveContainer>
    <span className="product-batch-inquiry-badge"><ChatCircleDots size={13} />咨询 +{integer.format(batch.inquiry_delta)}</span>
  </div>;
}

interface BatchDraftState {
  requestId: string;
  selectedIds: string[];
  cost: string;
  note: string;
  checkpointCollectionMode: "auto" | "manual";
  confirmedAlreadyPurchased: boolean;
}

interface BatchOperationState {
  batch: ProductTrafficBatchView;
  mode: "complete" | "checkpoint";
  checkpoint: "h1" | "h6" | "h24" | "h48" | "h72";
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

interface BatchStartState {
  preview: ProductTrafficStartPreviewView;
  step: "preview" | "manual" | "confirm";
  rows: BatchOperationState["rows"];
  baselineRequestIds: Record<"remote_refresh" | "manual", string>;
  startRequestId: string;
}

interface BatchReplanState {
  preview: ProductTrafficReplanPreviewView;
  batchCost: number;
  requestId: string;
}

interface ActualOverlapState {
  preview: ProductTrafficStartPreviewView;
  baselineMode: "missing" | "manual";
  confirmed: boolean;
  rows: BatchOperationState["rows"];
  requestId: string;
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

type RegistrationMode = "account" | "share";

export function ProductIntelligencePage({ globalSearch = "" }: { globalSearch?: string }) {
  const initialRoute = readProductWorkspaceRoute();
  const [data, setData] = useState<ProductIntelligenceView | null>(null);
  const [trafficGrowth, setTrafficGrowth] = useState<TrafficGrowthOverviewView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [collectionLogOpen, setCollectionLogOpen] = useState(false);
  const [collectingScope, setCollectingScope] = useState<"all" | string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [managementOpen, setManagementOpen] = useState(false);
  const [managementBulkConfirm, setManagementBulkConfirm] = useState(false);
  const [registerReference, setRegisterReference] = useState("");
  const [registrationMode, setRegistrationMode] = useState<RegistrationMode>("account");
  const [registrationPreview, setRegistrationPreview] = useState<ProductRegistrationPreview | null>(null);
  const [registrationSelection, setRegistrationSelection] = useState<string[]>([]);
  const [registrationLoading, setRegistrationLoading] = useState(false);
  const [registrationError, setRegistrationError] = useState("");
  const registrationRequestIdRef = useRef("");
  const [actionTarget, setActionTarget] = useState<{ product: ProductView; recommendation: ProductRecommendationView | null } | null>(null);
  const [actionType, setActionType] = useState("title");
  const [actionNote, setActionNote] = useState("");
  const [actionCost, setActionCost] = useState("");
  const [activePlanSlotId, setActivePlanSlotId] = useState<string | null>(null);
  const [batchDraft, setBatchDraft] = useState<BatchDraftState | null>(null);
  const [batchOperation, setBatchOperation] = useState<BatchOperationState | null>(null);
  const [batchStart, setBatchStart] = useState<BatchStartState | null>(null);
  const [batchReplan, setBatchReplan] = useState<BatchReplanState | null>(null);
  const [actualOverlap, setActualOverlap] = useState<ActualOverlapState | null>(null);
  const [expandedBatchId, setExpandedBatchId] = useState<string | null>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [batchPickerOpen, setBatchPickerOpen] = useState(false);
  const [batchSearch, setBatchSearch] = useState("");
  const [priorityExpanded, setPriorityExpanded] = useState(false);
  const [inventoryExpanded, setInventoryExpanded] = useState(false);
  const [modificationExpanded, setModificationExpanded] = useState(false);
  const [expandedModificationEvidenceId, setExpandedModificationEvidenceId] = useState<string | null>(null);
  const [batchHistory, setBatchHistory] = useState<ProductTrafficBatchView[]>([]);
  const [batchHistoryLoading, setBatchHistoryLoading] = useState(false);
  const [batchHistoryInitialized, setBatchHistoryInitialized] = useState(false);
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
  const batchDraftDialogRef = useRef<HTMLFormElement | null>(null);
  const batchDraftCloseRef = useRef<HTMLButtonElement | null>(null);
  const batchDraftTriggerRef = useRef<HTMLElement | null>(null);
  const managementDialogRef = useRef<HTMLElement | null>(null);
  const managementTriggerRef = useRef<HTMLElement | null>(null);
  const managementShouldRestoreFocusRef = useRef(true);
  const managementBulkTriggerRef = useRef<HTMLButtonElement | null>(null);
  const managementBulkConfirmRef = useRef<HTMLButtonElement | null>(null);
  const actualOverlapDialogRef = useRef<HTMLFormElement | null>(null);
  const actualOverlapCloseRef = useRef<HTMLButtonElement | null>(null);
  const actualOverlapTriggerRef = useRef<HTMLElement | null>(null);
  const batchPickerRef = useRef<HTMLDivElement | null>(null);
  const batchPickerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const batchSearchRef = useRef<HTMLInputElement | null>(null);

  const navigateWorkspace = (
    view: ProductWorkspaceTab,
    focus: ProductRouteFocus | null = null,
    targetId: string | null = null,
  ) => {
    const route = { view, focus, targetId };
    setActiveView(view);
    setRouteTarget(route);
    window.history.replaceState(window.history.state, "", productWorkspaceHash(route));
    window.dispatchEvent(new CustomEvent("xianyu:route-focus"));
  };

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2800);
  };

  const load = async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const [next, nextGrowth] = await Promise.all([
        localPlatformService.productIntelligence(),
        localPlatformService.trafficGrowth().catch(() => null),
      ]);
      setData(next);
      setTrafficGrowth(nextGrowth);
      setBatchHistory((current) => {
        const merged = new Map(current.map((batch) => [batch.id, batch]));
        next.traffic_batches.forEach((batch) => merged.set(batch.id, batch));
        return [...merged.values()].sort(
          (left, right) => parsePlatformDate(right.created_at).getTime() - parsePlatformDate(left.created_at).getTime(),
        );
      });
      setKeywordMode(next.market_reference.mode);
      setCustomKeyword(next.market_reference.custom_keyword);
      setSaveCommonKeyword(
        next.market_reference.common_keywords.includes(next.market_reference.custom_keyword),
      );
      setActivePlanSlotId((current) => {
        if (current && next.operating_plan.slots.some((slot) => slot.id === current)) return current;
        return defaultOperatingPlanSlotId(next.operating_plan);
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
        const eventType = String(event.type || "");
        if (eventType.startsWith("product_") || eventType === "ledger_updated") void load(true);
      });
    } catch {
      // The static Sites build intentionally has no local event service.
    }
    return disconnect;
  }, []);

  useEffect(() => {
    if (activeView !== "exposure" || batchHistoryInitialized) return;
    setBatchHistoryInitialized(true);
    setBatchHistoryLoading(true);
    void (async () => {
      const all: ProductTrafficBatchView[] = [];
      let cursor: string | null = null;
      do {
        const page = await localPlatformService.trafficBatches({
          cursor,
          limit: 100,
        });
        for (const batch of page.items) {
          if (!all.some((existing) => existing.id === batch.id)) all.push(batch);
        }
        cursor = page.has_more ? page.next_cursor : null;
      } while (cursor);
      setBatchHistory(all.sort(
        (left, right) => parsePlatformDate(right.created_at).getTime() - parsePlatformDate(left.created_at).getTime(),
      ));
    })()
      .catch((caught) => notify(caught instanceof Error ? caught.message : "历史批次加载失败"))
      .finally(() => setBatchHistoryLoading(false));
  }, [activeView, batchHistoryInitialized]);

  const availableBatchHistory = useMemo(() => {
    const source = batchHistory.length ? batchHistory : data?.traffic_batches || [];
    return [...source].sort(
      (left, right) => parsePlatformDate(right.created_at).getTime() - parsePlatformDate(left.created_at).getTime(),
    );
  }, [batchHistory, data?.traffic_batches]);
  const normalizedBatchSearch = batchSearch.trim().toLowerCase();
  const searchedBatchHistory = useMemo(() => availableBatchHistory.filter((batch) => {
    if (!normalizedBatchSearch) return true;
    const searchable = [
      batch.id,
      batchCreatedDayLabel(batch.created_at),
      formatTrafficDateTime(batch.created_at),
      formatTrafficDateTime(batch.started_at),
      trafficBatchStatusLabels[batch.status] || batch.status,
      ...batch.products.map((product) => product.title),
    ].join(" ").toLowerCase();
    return searchable.includes(normalizedBatchSearch);
  }), [availableBatchHistory, normalizedBatchSearch]);
  const groupedBatchHistory = useMemo(() => {
    const groups = new Map<string, ProductTrafficBatchView[]>();
    searchedBatchHistory.forEach((batch) => {
      const label = batchCreatedDayLabel(batch.created_at);
      groups.set(label, [...(groups.get(label) || []), batch]);
    });
    return [...groups.entries()];
  }, [searchedBatchHistory]);
  const selectedBatch = availableBatchHistory.find((batch) => batch.id === selectedBatchId)
    || availableBatchHistory[0]
    || null;

  useEffect(() => {
    const routedId = routeTarget.focus === "batch" ? routeTarget.targetId : null;
    setSelectedBatchId((current) => {
      if (routedId && availableBatchHistory.some((batch) => batch.id === routedId)) {
        return routedId;
      }
      if (current && availableBatchHistory.some((batch) => batch.id === current)) {
        return current;
      }
      return availableBatchHistory[0]?.id || null;
    });
    if (routedId && availableBatchHistory.some((batch) => batch.id === routedId)) {
      setExpandedBatchId(routedId);
    }
  }, [availableBatchHistory, routeTarget.focus, routeTarget.targetId]);

  useEffect(() => {
    if (!batchPickerOpen) return;
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : batchPickerTriggerRef.current;
    const onPointerDown = (event: MouseEvent) => {
      if (!batchPickerRef.current?.contains(event.target as Node)) {
        setBatchPickerOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setBatchPickerOpen(false);
      window.setTimeout(() => batchPickerTriggerRef.current?.focus(), 0);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    window.setTimeout(() => batchSearchRef.current?.focus(), 0);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      if (previousFocus && !document.body.contains(document.activeElement)) {
        window.setTimeout(() => previousFocus.focus(), 0);
      }
    };
  }, [batchPickerOpen]);

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
      if (routeTarget.view === "launch" && data.modification_suggestions.some((item) => item.external_id === routeTarget.targetId)) {
        setExpandedModificationEvidenceId(routeTarget.targetId);
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
    if (routeTarget.focus === "batch" && routeTarget.targetId) {
      setExpandedBatchId(routeTarget.targetId);
    }
    const timer = window.setTimeout(() => {
      const elementId = routeTarget.focus === "collection"
        ? "product-collection"
        : routeTarget.focus === "product"
          ? routeTarget.view === "launch" && routeTarget.targetId
            ? `product-modification-${routeTarget.targetId}`
            : "product-detail"
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

  useEffect(() => {
    if (!actualOverlap) return;
    const previousFocus = actualOverlapTriggerRef.current
      || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setActualOverlap(null);
        return;
      }
      if (event.key !== "Tab" || !actualOverlapDialogRef.current) return;
      const controls = Array.from(actualOverlapDialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.hasAttribute("hidden"));
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
    window.setTimeout(() => actualOverlapCloseRef.current?.focus(), 0);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.setTimeout(() => previousFocus?.focus(), 0);
    };
  }, [actualOverlap?.preview.batch.id]);

  useEffect(() => {
    if (!batchDraft) return;
    const previousFocus = batchDraftTriggerRef.current
      || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setBatchDraft(null);
        return;
      }
      if (event.key !== "Tab" || !batchDraftDialogRef.current) return;
      const controls = Array.from(batchDraftDialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.hasAttribute("hidden"));
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
    window.setTimeout(() => batchDraftCloseRef.current?.focus(), 0);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.setTimeout(() => previousFocus?.focus(), 0);
    };
  }, [Boolean(batchDraft)]);

  useEffect(() => {
    if (!managementOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setManagementOpen(false);
        return;
      }
      if (event.key !== "Tab" || !managementDialogRef.current) return;
      const controls = Array.from(managementDialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.hasAttribute("hidden"));
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
    window.setTimeout(() => managementDialogRef.current?.querySelector<HTMLElement>('button[aria-label="关闭"]')?.focus(), 0);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (managementShouldRestoreFocusRef.current) {
        window.setTimeout(() => managementTriggerRef.current?.focus(), 0);
      }
    };
  }, [managementOpen]);

  const normalizedSearch = globalSearch.trim().toLowerCase();
  const products = useMemo(() => {
    if (!data) return [];
    return normalizedSearch
      ? data.products.filter((product) => `${product.title} ${product.external_id}`.toLowerCase().includes(normalizedSearch))
      : data.products;
  }, [data, normalizedSearch]);
  const selected = data?.products.find((product) => product.external_id === selectedId) || products[0] || null;
  const focusedProductId = routeTarget.focus === "product" ? routeTarget.targetId : null;
  const inventoryLimitEnabled = !normalizedSearch && !focusedProductId && !inventoryExpanded;
  const visibleProducts = inventoryLimitEnabled ? products.slice(0, 8) : products;
  const focusedExperiment = routeTarget.focus === "experiment" ? routeTarget.targetId : null;
  const focusedModificationProduct = routeTarget.view === "launch" && routeTarget.focus === "product"
    ? routeTarget.targetId
    : null;
  const modificationSuggestions = data?.modification_suggestions || [];
  const modificationLimitEnabled = !focusedExperiment && !focusedModificationProduct && !modificationExpanded;
  const visibleModificationSuggestions = modificationLimitEnabled
    ? modificationSuggestions.slice(0, 6)
    : modificationSuggestions;
  const visiblePriorityRecommendations = data?.recommendations.slice(
    0,
    priorityExpanded ? 5 : 3,
  ) || [];
  const activePlanSlot = data?.operating_plan.slots.find((slot) => slot.id === activePlanSlotId)
    || data?.operating_plan.slots[0]
    || null;
  const growthPlanSlot = data?.operating_plan.slots.find((slot) => {
    if (!trafficGrowth?.active_experiment || slot.action_type !== "traffic" || slot.status === "executed") return false;
    return String(slot.rotation_summary.experiment_id || "") === trafficGrowth.active_experiment.id;
  }) || null;

  const openBatchDraft = (_slot?: ProductOperatingPlanSlotView | null, seedIds: string[] = []) => {
    if (!data) return;
    batchDraftTriggerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const plannedIds = seedIds;
    const fallbackIds = data.products
      .filter((product) => product.monitoring_enabled)
      .slice(0, 3)
      .map((product) => product.external_id);
    setBatchDraft({
      requestId: crypto.randomUUID(),
      selectedIds: plannedIds.length ? plannedIds : fallbackIds,
      cost: "5.9",
      note: "",
      checkpointCollectionMode: "auto",
      confirmedAlreadyPurchased: false,
    });
  };

  const createTrafficGrowthExperiment = async (externalId: string) => {
    setBusy(true);
    try {
      await localPlatformService.createTrafficExperiment({
        request_id: crypto.randomUUID(),
        item_external_id: externalId,
        target_windows: ["12", "16", "20"],
        baseline_weekly_budget: 24,
        hard_weekly_cap: 48,
      });
      await localPlatformService.refreshOperatingPlan();
      notify("已建立 8 批干净时段实验；所有投放仍由你人工确认");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "增长实验建立失败");
    } finally {
      setBusy(false);
    }
  };

  const advanceTrafficGrowthExperiment = async (experiment: TrafficExperimentView) => {
    setBusy(true);
    try {
      await localPlatformService.advanceTrafficExperiment(experiment.id, {
        request_id: crypto.randomUUID(),
        expected_updated_at: experiment.updated_at,
      });
      await localPlatformService.refreshOperatingPlan();
      notify("已进入优胜与次优时段确认阶段");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "实验阶段推进失败");
    } finally {
      setBusy(false);
    }
  };

  const refreshTrafficAttributions = async (experiment: TrafficExperimentView) => {
    setBusy(true);
    try {
      const updated = await localPlatformService.refreshTrafficAttributions(experiment.id, crypto.randomUUID());
      setTrafficGrowth((current) => current ? { ...current, active_experiment: updated } : current);
      notify("已按精确对话链路刷新商业归因候选");
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "商业归因刷新失败");
    } finally {
      setBusy(false);
    }
  };

  const decideTrafficAttribution = async (
    experiment: TrafficExperimentView,
    attribution: TrafficCommercialAttributionView,
    decision: "confirm" | "reject",
  ) => {
    setBusy(true);
    try {
      const payload = {
        request_id: crypto.randomUUID(),
        expected_updated_at: attribution.updated_at,
        project_id: attribution.project_id,
        reason: decision === "reject" ? "人工审查后排除" : "人工确认精确对话与项目证据链",
      };
      const updated = decision === "confirm" && attribution.project_id
        ? await localPlatformService.confirmTrafficAttribution(attribution.id, { ...payload, project_id: attribution.project_id })
        : await localPlatformService.rejectTrafficAttribution(attribution.id, payload);
      setTrafficGrowth((current) => current ? { ...current, active_experiment: updated } : current);
      notify(decision === "confirm" ? "商业归因已人工确认" : "候选证据已排除");
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "商业归因审查失败");
    } finally {
      setBusy(false);
    }
  };

  const refreshTrafficBudget = async (experiment: TrafficExperimentView) => {
    setBusy(true);
    try {
      const updated = await localPlatformService.refreshTrafficBudgetDecision(experiment.id, crypto.randomUUID());
      setTrafficGrowth((current) => current ? { ...current, active_experiment: updated } : current);
      notify("预算判断已使用最新付款、项目、利润和交付负载重新核验");
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "预算判断刷新失败");
    } finally {
      setBusy(false);
    }
  };

  const applyTrafficBudget = async (experiment: TrafficExperimentView) => {
    const decision = experiment.budget_decision;
    if (!decision.id) return;
    setBusy(true);
    try {
      await localPlatformService.applyTrafficBudgetDecision(decision.id, {
        request_id: crypto.randomUUID(),
        expected_experiment_updated_at: experiment.updated_at,
      });
      await localPlatformService.refreshOperatingPlan();
      notify("预算档位建议已人工应用到未来经营计划");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "预算档位应用失败");
    } finally {
      setBusy(false);
    }
  };

  const createTrafficScaleCohort = async (
    experiment: TrafficExperimentView,
    stage: "S1" | "S2" | "S3",
  ) => {
    setBusy(true);
    try {
      await localPlatformService.createTrafficScaleCohort(experiment.id, {
        request_id: crypto.randomUUID(),
        stage,
        no_other_promotion_confirmed: true,
        listing_unchanged_confirmed: true,
      });
      await localPlatformService.refreshOperatingPlan();
      notify(`已建立 ${stage} 的 14 天整体观察队列；仍不会自动购买曝光`);
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "扩量队列建立失败");
    } finally {
      setBusy(false);
    }
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
      if (!batchDraft.confirmedAlreadyPurchased) {
        notify("请先确认已经在闲鱼完成真实投流");
        return;
      }
      const recorded = await localPlatformService.recordTrafficBatch({
        request_id: batchDraft.requestId,
        item_external_ids: batchDraft.selectedIds,
        actual_cost: Math.max(0, Number(batchDraft.cost) || 0),
        plan_slot_id: null,
        note: batchDraft.note.trim(),
        checkpoint_collection_mode: batchDraft.checkpointCollectionMode,
        confirmed_already_purchased: true,
      });
      setBatchDraft(null);
      setSelectedBatchId(recorded.id);
      setExpandedBatchId(null);
      navigateWorkspace("exposure", "batch", recorded.id);
      notify(recorded.status === "invalidated" ? "真实投流与批次费用已记录；T0 证据不足，仅保留事实，不生成检查点或经营结论" : "真实投流已按服务端北京时间记录，48 小时观察已开始");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "真实投流记录失败");
    } finally {
      setBusy(false);
    }
  };

  const selectTrackedBatch = (batch: ProductTrafficBatchView) => {
    setSelectedBatchId(batch.id);
    setExpandedBatchId(null);
    setBatchPickerOpen(false);
    setBatchSearch("");
    navigateWorkspace("exposure", "batch", batch.id);
    window.setTimeout(() => batchPickerTriggerRef.current?.focus(), 0);
  };

  const handleBatchPickerNavigation = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const options = Array.from(
      batchPickerRef.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') || [],
    );
    if (!options.length) return;
    event.preventDefault();
    const currentIndex = options.findIndex((option) => option === document.activeElement);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? options.length - 1
        : event.key === "ArrowUp"
          ? Math.max(0, currentIndex < 0 ? options.length - 1 : currentIndex - 1)
          : Math.min(options.length - 1, currentIndex + 1);
    options[nextIndex]?.focus();
  };

  const handleTrackedBatchActivation = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    batch: ProductTrafficBatchView,
  ) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    selectTrackedBatch(batch);
  };

  const baselineRows = (batch: ProductTrafficBatchView): BatchOperationState["rows"] => Object.fromEntries(
    batch.products.map((product) => {
      const known = data?.products.find((item) => item.external_id === product.external_id);
      return [product.external_id, {
        browse_count: String(Math.max(product.latest_browse_count, known?.browse_count || 0)),
        collect_count: String(Math.max(product.latest_collect_count, known?.collect_count || 0)),
        want_count: String(Math.max(product.latest_want_count, known?.want_count || 0)),
        inquiry_count: String(Math.max(product.latest_inquiry_count, known?.inquiry_count || 0)),
      }];
    }),
  );

  const openStartBatch = async (batch: ProductTrafficBatchView) => {
    setBusy(true);
    try {
      const preview = await localPlatformService.trafficStartPreview(batch.id);
      setBatchStart({
        preview,
        step: preview.can_start ? "confirm" : "preview",
        rows: baselineRows(preview.batch),
        baselineRequestIds: {
          remote_refresh: crypto.randomUUID(),
          manual: crypto.randomUUID(),
        },
        startRequestId: crypto.randomUUID(),
      });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "开始准备读取失败");
    } finally {
      setBusy(false);
    }
  };

  const openActualOverlap = async (batch: ProductTrafficBatchView, trigger?: HTMLElement | null) => {
    actualOverlapTriggerRef.current = trigger || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setBusy(true);
    try {
      const preview = await localPlatformService.trafficStartPreview(batch.id);
      if (!preview.can_record_actual) {
        notify("当前批次不满足真实重叠补录条件；请刷新后选择正常开始或等待冷却");
        return;
      }
      setActualOverlap({
        preview,
        baselineMode: "missing",
        confirmed: false,
        rows: baselineRows(preview.batch),
        requestId: crypto.randomUUID(),
      });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "重叠补录预览读取失败");
    } finally {
      setBusy(false);
    }
  };

  const confirmActualOverlap = async (event: FormEvent) => {
    event.preventDefault();
    if (!actualOverlap || !actualOverlap.confirmed) return;
    setBusy(true);
    try {
      const recorded = await localPlatformService.recordActualTrafficStart(actualOverlap.preview.batch.id, {
        request_id: actualOverlap.requestId,
        expected_updated_at: actualOverlap.preview.batch.updated_at,
        confirmed_already_purchased: true,
        items: actualOverlap.baselineMode === "manual"
          ? actualOverlap.preview.batch.products.map((product) => {
            const row = actualOverlap.rows[product.external_id];
            return {
              external_id: product.external_id,
              browse_count: Math.max(0, Number(row.browse_count) || 0),
              collect_count: Math.max(0, Number(row.collect_count) || 0),
              want_count: Math.max(0, Number(row.want_count) || 0),
              inquiry_count: Math.max(0, Number(row.inquiry_count) || 0),
            };
          })
          : [],
      });
      setActualOverlap(null);
      notify(recorded.status === "invalidated"
        ? `已按 ${formatTrafficDateTime(recorded.started_at)} 保存真实投放，并因缺少可靠 T0 终止后续观察`
        : `已按 ${formatTrafficDateTime(recorded.started_at)} 补记；该批次永久排除经营归因`);
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "真实投放补记失败");
    } finally {
      setBusy(false);
    }
  };

  const prepareBatchBaseline = async (mode: "remote_refresh" | "manual") => {
    if (!batchStart) return;
    setBusy(true);
    try {
      const prepared = await localPlatformService.prepareTrafficBaseline(batchStart.preview.batch.id, {
        request_id: batchStart.baselineRequestIds[mode],
        expected_updated_at: batchStart.preview.batch.updated_at,
        mode,
        items: mode === "manual"
          ? batchStart.preview.batch.products.map((product) => {
            const row = batchStart.rows[product.external_id];
            return {
              external_id: product.external_id,
              browse_count: Math.max(0, Number(row.browse_count) || 0),
              collect_count: Math.max(0, Number(row.collect_count) || 0),
              want_count: Math.max(0, Number(row.want_count) || 0),
              inquiry_count: Math.max(0, Number(row.inquiry_count) || 0),
            };
          })
          : [],
      });
      const preview = await localPlatformService.trafficStartPreview(prepared.id);
      setBatchStart({
        preview,
        step: preview.can_start ? "confirm" : "preview",
        rows: baselineRows(preview.batch),
        baselineRequestIds: {
          remote_refresh: crypto.randomUUID(),
          manual: crypto.randomUUID(),
        },
        startRequestId: crypto.randomUUID(),
      });
      notify(mode === "manual" ? "整批人工 T0 已保存，30 分钟内可开始" : "整批远程 T0 已刷新，30 分钟内可开始");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "整批 T0 准备失败");
    } finally {
      setBusy(false);
    }
  };

  const confirmBatchStart = async () => {
    if (!batchStart || !batchStart.preview.can_start || !batchStart.preview.batch.baseline_prepared_at) return;
    setBusy(true);
    try {
      const started = await localPlatformService.startTrafficBatch(batchStart.preview.batch.id, {
        request_id: batchStart.startRequestId,
        expected_updated_at: batchStart.preview.batch.updated_at,
        expected_baseline_captured_at: batchStart.preview.batch.baseline_prepared_at,
      });
      setBatchStart(null);
      notify(`批次已按实际操作时间 ${formatTrafficDateTime(started.started_at)} 开始，曝光支出已记录`);
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "批次未能开始");
    } finally {
      setBusy(false);
    }
  };

  const openReplan = async (batch: ProductTrafficBatchView) => {
    setBusy(true);
    try {
      const preview = await localPlatformService.trafficReplanPreview(batch.id);
      setBatchReplan({ preview, batchCost: batch.actual_cost, requestId: crypto.randomUUID() });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "重排预览生成失败");
    } finally {
      setBusy(false);
    }
  };

  const confirmReplan = async () => {
    if (!batchReplan || !batchReplan.preview.can_replan) return;
    setBusy(true);
    try {
      await localPlatformService.replanTrafficBatch(batchReplan.preview.batch_id, {
        request_id: batchReplan.requestId,
        expected_updated_at: batchReplan.preview.updated_at,
        preview_hash: batchReplan.preview.preview_hash,
      });
      setBatchReplan(null);
      notify("批次已按预览重排；原批次 ID、总费用和审计记录均保留");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "批次重排失败");
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

  const openBatchOperation = (batch: ProductTrafficBatchView, mode: "complete" | "checkpoint", requestedCheckpoint?: "h1" | "h6" | "h24" | "h48" | "h72") => {
    const nextCheckpoint = requestedCheckpoint || batch.due_checkpoint
      || (batch.checkpoint_sequence as Array<"h1" | "h6" | "h24" | "h48" | "h72">).find((value) => batch.completed_checkpoints.includes(value))
      || "h1";
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
    if (
      batchOperation.mode === "checkpoint"
      && !checkpointOptionState(batchOperation.batch, batchOperation.checkpoint).enabled
    ) {
      notify(checkpointOptionState(batchOperation.batch, batchOperation.checkpoint).detail);
      return;
    }
    setBusy(true);
    try {
      if (batchOperation.mode === "complete") {
        await localPlatformService.completeTrafficBatch(batchOperation.batch.id, {
          actual_cost: Math.max(0, Number(batchOperation.cost) || 0),
          total_exposure: batchOperation.totalExposure ? Math.max(0, Number(batchOperation.totalExposure) || 0) : null,
          note: batchOperation.note.trim(),
        });
        notify(`套餐完成信息已记录；后续浏览和咨询仍会归入 ${batchOperation.batch.observation_window_hours}h 观察`);
      } else {
        await localPlatformService.recordTrafficCheckpoint(batchOperation.batch.id, {
          checkpoint: batchOperation.checkpoint,
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

  const updateCheckpointCollectionMode = async (
    batch: ProductTrafficBatchView,
    mode: "auto" | "manual",
  ) => {
    if (batch.checkpoint_collection_mode === mode) return;
    setBusy(true);
    try {
      await localPlatformService.updateTrafficCheckpointCollectionMode(batch.id, {
        request_id: crypto.randomUUID(),
        expected_updated_at: batch.updated_at,
        mode,
      });
      notify(mode === "auto" ? "已切换为自动采集；到点后只读采集一次" : "已切换为到点提醒；由你手动填写检查点");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "采集方式更新失败");
    } finally {
      setBusy(false);
    }
  };

  const retryCheckpointCollection = async (
    batch: ProductTrafficBatchView,
    checkpoint: "h1" | "h6" | "h24" | "h48" | "h72",
  ) => {
    setBusy(true);
    try {
      await localPlatformService.retryTrafficCheckpointCollection(batch.id, checkpoint, {
        request_id: crypto.randomUUID(),
        expected_updated_at: batch.updated_at,
      });
      notify("已仅补采缺失商品；此前成功记录不会重复读取");
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "恢复补采失败");
    } finally {
      setBusy(false);
    }
  };

  const openManualCheckpointCompletion = async (
    batch: ProductTrafficBatchView,
    checkpoint: "h1" | "h6" | "h24" | "h48" | "h72",
  ) => {
    setBusy(true);
    try {
      const updated = batch.checkpoint_collection_mode === "manual"
        ? batch
        : await localPlatformService.updateTrafficCheckpointCollectionMode(batch.id, {
          request_id: crypto.randomUUID(),
          expected_updated_at: batch.updated_at,
          mode: "manual",
        });
      openBatchOperation(updated, "checkpoint", checkpoint);
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "切换人工补齐失败");
    } finally {
      setBusy(false);
    }
  };

  const refreshPlan = async () => {
    setBusy(true);
    try {
      const plan = await localPlatformService.refreshOperatingPlan();
      setActivePlanSlotId(defaultOperatingPlanSlotId(plan));
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

  const openRegistration = () => {
    setRegisterOpen(true);
    setRegistrationMode("account");
    setRegistrationPreview(null);
    setRegistrationSelection([]);
    setRegisterReference("");
    setRegistrationError("");
    registrationRequestIdRef.current = "";
    window.setTimeout(() => void discoverRegistrationProducts(), 0);
  };

  const openManagement = () => {
    managementTriggerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    managementShouldRestoreFocusRef.current = true;
    setManagementBulkConfirm(false);
    setManagementOpen(true);
  };

  const discoverRegistrationProducts = async () => {
    setRegistrationLoading(true);
    setRegistrationError("");
    try {
      const preview = await localPlatformService.discoverOwnedListings();
      setRegistrationPreview(preview);
      setRegistrationSelection(preview.items.filter((item) => item.can_register).map((item) => item.external_id));
    } catch (caught) {
      setRegistrationPreview(null);
      setRegistrationSelection([]);
      setRegistrationError(caught instanceof Error ? caught.message : "在售商品读取失败");
    } finally {
      setRegistrationLoading(false);
    }
  };

  const resolveRegistrationProduct = async () => {
    if (!registerReference.trim()) return;
    setRegistrationLoading(true);
    setRegistrationError("");
    try {
      const preview = await localPlatformService.resolveProductReference(registerReference.trim());
      setRegistrationPreview(preview);
      setRegistrationSelection(preview.items.filter((item) => item.can_register).map((item) => item.external_id));
      registrationRequestIdRef.current = "";
    } catch (caught) {
      setRegistrationPreview(null);
      setRegistrationSelection([]);
      setRegistrationError(caught instanceof Error ? caught.message : "分享内容识别失败");
    } finally {
      setRegistrationLoading(false);
    }
  };

  const register = async (event: FormEvent) => {
    event.preventDefault();
    if (!registrationPreview || registrationSelection.length === 0) return;
    setBusy(true);
    setRegistrationError("");
    try {
      const stableRequestId = registrationRequestIdRef.current || `product_registration_${crypto.randomUUID()}`;
      registrationRequestIdRef.current = stableRequestId;
      const result = await localPlatformService.commitProductRegistration({
        request_id: stableRequestId,
        preview_token: registrationPreview.token,
        external_ids: registrationSelection,
      });
      setRegisterOpen(false);
      setRegisterReference("");
      setRegistrationPreview(null);
      setRegistrationSelection([]);
      registrationRequestIdRef.current = "";
      setSelectedId(result.products.find((product) => product.ownership_status === "owned")?.external_id || result.products[0]?.external_id || null);
      notify(result.idempotent ? "所选商品已经加入采集目标" : `已处理 ${result.products.length} 件商品，其中新加入 ${result.registered_count} 件`);
      await load(true);
    } catch (caught) {
      setRegistrationError(caught instanceof Error ? caught.message : "添加商品失败");
    } finally {
      setBusy(false);
    }
  };

  const toggleRegistrationSelection = (externalId: string) => {
    setRegistrationSelection((current) => current.includes(externalId)
      ? current.filter((value) => value !== externalId)
      : [...current, externalId]);
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

  const removeRegistrationMonitor = async (externalId: string) => {
    setBusy(true);
    setRegistrationError("");
    try {
      await localPlatformService.updateProductMonitor(externalId, false);
      notify("已移出采集，历史数据继续保留");
      await load(true);
      await discoverRegistrationProducts();
    } catch (caught) {
      setRegistrationError(caught instanceof Error ? caught.message : "移出采集失败");
    } finally {
      setBusy(false);
    }
  };

  const disableAllManagedProducts = async () => {
    if (!managedProducts.length) return;
    setBusy(true);
    try {
      const result = await localPlatformService.disableProductMonitors(
        managedProducts.map((product) => product.external_id),
      );
      setManagementBulkConfirm(false);
      notify(`已移出 ${result.disabled_count} 件商品，历史数据继续保留`);
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "批量移出采集失败");
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
      notify("今天的 Ego Lite 市场参考已导入，提醒已自动清除");
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
  const managedProducts = data.products.filter(
    (product) => product.ownership_status === "owned" && product.monitoring_enabled,
  );
  const verifiedOwnedProducts = data.products.filter(
    (product) => product.ownership_status === "owned",
  );
  const inactiveOwnedProducts = verifiedOwnedProducts.filter(
    (product) => !product.monitoring_enabled,
  );
  // Kept only for historical API/audit compatibility. New exposure records
  // are actual-time-only, so the plan/recommended-time workspace is not shown.
  const legacyTrafficPlanningVisible: boolean = false;

  const runPresentation = collectionRunPresentation(data);
  const activeObservationBatch = [...data.traffic_batches]
    .filter((batch) => ["running", "observing"].includes(batch.status) && batch.started_at)
    .sort((left, right) => parsePlatformDate(right.started_at || right.planned_at).getTime() - parsePlatformDate(left.started_at || left.planned_at).getTime())[0]
    || null;
  const activePlanExecutedBatch = activePlanSlot?.status === "executed" && activePlanSlot.batch_id
    ? data.traffic_batches.find((batch) => batch.id === activePlanSlot.batch_id) || null
    : null;
  const latestStartedBatch = [...data.traffic_batches]
    .filter((batch) => Boolean(batch.started_at) && batch.status !== "cancelled")
    .sort((left, right) => parsePlatformDate(right.started_at || right.planned_at).getTime() - parsePlatformDate(left.started_at || left.planned_at).getTime())[0]
    || null;
  const activeCheckpointJob = activeObservationBatch?.checkpoint_jobs.find(
    (job) => !["completed", "missed"].includes(job.status),
  ) || (activeObservationBatch?.checkpoint_jobs.length
    ? activeObservationBatch.checkpoint_jobs[activeObservationBatch.checkpoint_jobs.length - 1]
    : null);
  const checkpointNeedsAttention = Boolean(
    activeCheckpointJob
    && ["waiting_connection", "partial", "waiting_manual", "circuit_open"].includes(activeCheckpointJob.status),
  );
  const selectedSlotIsObservation = Boolean(
    activeObservationBatch
    && activePlanSlot
    && activePlanSlot.action_type === "measure"
    && activePlanSlot.source_batch_id === activeObservationBatch.id,
  );
  const observationActionReady = Boolean(
    activeObservationBatch?.due_checkpoint && activeObservationBatch.due_ready,
  );
  const observationLatestCheckpoint = activeObservationBatch?.observation_checkpoint || null;
  const observationCheckpointLabel = activeObservationBatch?.due_checkpoint
    ? checkpointShortLabels[activeObservationBatch.due_checkpoint]
    : "观察完成";
  const selectedSlotTitle = activePlanExecutedBatch
    ? "已执行多商品曝光"
    : selectedSlotIsObservation && activeObservationBatch?.due_checkpoint
      ? observationPlanTitle(activeObservationBatch)
      : planActionLabels[activePlanSlot?.action_type || ""] || activePlanSlot?.action_type || "等待经营安排";
  const selectedSlotEvidence = activePlanSlot
    ? Array.from(new Set([
      ...activePlanSlot.products.map((product) => product.reason),
      ...activePlanSlot.change_factors,
      ...activePlanSlot.evidence.filter((line) => !line.startsWith("规则版本")),
    ].filter(Boolean))).slice(0, 3)
    : [];
  const nextTrafficPlanSlot = activePlanSlot
    ? data.operating_plan.slots.find(
      (slot) => slot.date > activePlanSlot.date && slot.action_type === "traffic",
    ) || null
    : null;
  const observationBatchCount = data.traffic_summary.observation_batch_count;
  const plannedBatchCount = data.traffic_summary.planned_batch_count;
  const trafficBatchStatusLabel = [
    observationBatchCount ? `${observationBatchCount} 个观察中` : "",
    plannedBatchCount ? `${plannedBatchCount} 个待开始` : "",
  ].filter(Boolean).join(" · ") || "当前无待处理批次";

  const renderMarketReference = (expanded = false) => <MarketReferenceWorkbench
    busy={busy}
    chooseRecommendedKeyword={chooseRecommendedKeyword}
    customKeyword={customKeyword}
    data={data}
    expanded={expanded}
    keywordMode={keywordMode}
    returnToRecommendedKeyword={returnToRecommendedKeyword}
    saveCommonKeyword={saveCommonKeyword}
    setCustomKeyword={setCustomKeyword}
    setKeywordMode={setKeywordMode}
    setMarketImportOpen={setMarketImportOpen}
    setSaveCommonKeyword={setSaveCommonKeyword}
    skipMarketReminder={skipMarketReminder}
    snoozeMarketReminder={snoozeMarketReminder}
    useCustomMarketKeyword={useCustomMarketKeyword}
  />;


  const overviewControls = <details className="product-command-card reference-product-controls"><summary>商品管理与采集设置</summary>
      <details className="product-command-copy"><summary>采集安全说明</summary>
        <div className="product-safety-note"><ShieldCheck size={18} weight="fill" /><span><b>只读安全边界</b>{data.collection.safety_note}</span></div>
      </details>
      <div className="product-collection-panel" id="product-collection">
        <div><small>采集计划 · 北京时间</small><strong>{data.collection.schedule}</strong><span>{data.collection.configured ? `下次计划 ${formatDate(data.collection.next_collection_at)}（北京时间）` : "等待配置闲鱼连接"}</span></div>
        {(data.collection.latest_attempt || data.collection.last_run) && runPresentation && <p className={`collection-result collection-${(data.collection.latest_attempt || data.collection.last_run)!.status}`}><CheckCircle size={16} weight="fill" />{runPresentation.label}<small>{runPresentation.detail}</small></p>}
        {data.collection.attempts.length > 0 && <div className="collection-log-shell">
          <button type="button" className="collection-log-toggle" aria-expanded={collectionLogOpen} onClick={() => setCollectionLogOpen((value) => !value)}><span><Clock size={15} />采集日志</span><small>{data.collection.attempts.length} 次记录</small><CaretRight className={collectionLogOpen ? "expanded" : ""} size={14} /></button>
          {collectionLogOpen && <div className="collection-log-list">{data.collection.attempts.map((attempt) => <CollectionAttemptLog attempt={attempt} key={attempt.id} />)}</div>}
        </div>}
        <div className="product-command-actions">
          <button className="product-outline-button" onClick={openManagement}><Package size={16} />商品管理</button>
          {!selected && <button className="product-outline-button" onClick={openRegistration}><Plus size={16} />添加商品</button>}
          <button className="product-primary-button" disabled={busy || !data.collection.configured} onClick={() => void collectManually()}>{collectingScope === "all" ? <ArrowClockwise className="spin" size={16} /> : <ArrowClockwise size={16} />}{data.collection.configured ? "手动采集全部" : "等待渠道配置"}</button>
        </div>
      </div>
    </details>;

  const overviewFacts = <details className="product-overview-facts"><summary>经营概况 · {managedProducts.length} 个启用商品</summary><section className="product-metrics-grid product-metrics-first" aria-label="商品经营指标">
      <ProductMetric icon={Package} label="已验证本人商品" value={`${verifiedOwnedProducts.length}`} detail={`${managedProducts.length} 个启用 · ${inactiveOwnedProducts.length} 个历史停用 · ${data.summary.pending_products} 个待确认 · ${data.summary.excluded_products} 个他人排除`} tone="purple" />
      <ProductMetric icon={BellRinging} label="待补全信息" value={`${data.products.filter((product) => product.data_gaps.length > 0).length}`} detail="商品快照、咨询与实验基线" tone="orange" />
      <ProductMetric icon={Coins} label="本周曝光投入" value={moneyExact.format(data.traffic_summary.spent_this_week)} detail={`初始周上限 ${moneyExact.format(data.operating_plan.weekly_budget)}`} tone="green" />
      <ProductMetric icon={CalendarCheck} label="有效批次" value={`${data.traffic_summary.effective_batch_count}`} detail={`${data.summary.snapshot_days} 个快照日 · ${analysisStageLabels[data.traffic_summary.analysis_stage] || "学习中"}`} tone="blue" />
      <ProductMetric icon={Gauge} label="交付负载" value={`${data.summary.active_projects}/${data.summary.delivery_capacity}`} detail="满载时自动建议收缩流量" tone="red" />
    </section></details>;

  return <div className="product-intelligence-page">
    {activeView === 'overview' && !selected && <>{overviewFacts}{overviewControls}</>}

    {activeView === "exposure" && <section className="actual-traffic-observation-hero" aria-labelledby="actual-traffic-observation-title">
      <div>
        <span><Clock size={16} weight="duotone" />ACTUAL TIME ANCHOR</span>
        <h2 id="actual-traffic-observation-title">真实投流后的 48 小时观察</h2>
        <p>以服务端确认的北京时间为唯一锚点，依次记录 T0、+1h、+6h、+24h、+48h。这里只展示投流后的观察结果，不宣称平台因果增量。</p>
      </div>
      <button type="button" className="product-primary-button" onClick={() => openBatchDraft()}><Plus size={17} />记录刚完成的真实投流</button>
      <ul>
        <li><b>不创建未来计划</b><span>只记录已经发生的人工投流</span></li>
        <li><b>不推荐投流时间</b><span>结论按你实际投流的时刻命名</span></li>
        <li><b>历史协议保留</b><span>旧批次继续按原 72h 检查点审计</span></li>
      </ul>
    </section>}

    {activeView === "exposure" && <section className={`traffic-collection-control ${checkpointNeedsAttention ? "needs-attention" : ""}`} aria-labelledby="traffic-collection-mode-title">
      <div className="traffic-collection-control-main">
        <div className="traffic-collection-mode-copy"><b id="traffic-collection-mode-title">检查点采集方式</b><Info size={14} /></div>
        <div className="traffic-collection-mode-tabs" role="radiogroup" aria-label="检查点采集方式">
          <button type="button" role="radio" aria-checked={(activeObservationBatch?.checkpoint_collection_mode || "auto") === "auto"} className={(activeObservationBatch?.checkpoint_collection_mode || "auto") === "auto" ? "active" : ""} disabled={busy || !activeObservationBatch} onClick={() => activeObservationBatch && void updateCheckpointCollectionMode(activeObservationBatch, "auto")}><CheckCircle size={15} weight={(activeObservationBatch?.checkpoint_collection_mode || "auto") === "auto" ? "fill" : "regular"} />投放后自动采集（推荐）</button>
          <button type="button" role="radio" aria-checked={activeObservationBatch?.checkpoint_collection_mode === "manual"} className={activeObservationBatch?.checkpoint_collection_mode === "manual" ? "active" : ""} disabled={busy || !activeObservationBatch} onClick={() => activeObservationBatch && void updateCheckpointCollectionMode(activeObservationBatch, "manual")}><Clock size={15} />到点提醒，我手动记录</button>
        </div>
        <div className="traffic-collection-channel">
          <i className={checkpointNeedsAttention ? "warning" : "healthy"} />
          <span><small>商品采集通道</small><b>{!activeObservationBatch ? "新批次默认自动采集" : activeCheckpointJob?.status === "collecting" ? "正在自动采集" : activeCheckpointJob?.status === "waiting_connection" ? "等待采集凭证恢复" : ["partial", "waiting_manual", "circuit_open"].includes(activeCheckpointJob?.status || "") ? `已采集 ${activeCheckpointJob?.collected_count || 0}/${activeCheckpointJob?.total_count || activeObservationBatch.products.length} 件` : "自动任务已保留"}</b></span>
        </div>
        <div className="traffic-collection-next">
          <small>下一检查点</small>
          <b>{activeCheckpointJob ? `${checkpointShortLabels[activeCheckpointJob.checkpoint]} · ${formatTrafficDateTime(activeCheckpointJob.scheduled_for)}` : "等待新批次"}</b>
        </div>
        <div className="traffic-collection-schedule" aria-label="四阶段采集计划">
          {(activeObservationBatch?.checkpoint_jobs || []).map((job) => <span className={job.status === "completed" ? "done" : job.checkpoint === activeCheckpointJob?.checkpoint ? "current" : ""} key={job.checkpoint}><b>{checkpointShortLabels[job.checkpoint]}</b><small>{formatTrafficDateTime(job.scheduled_for)}</small></span>)}
          {!activeObservationBatch && <span className="empty"><b>+1h · +6h · +24h · +48h</b><small>均从服务端确认的实际投流时间计算</small></span>}
        </div>
      </div>
      {checkpointNeedsAttention && activeObservationBatch && activeCheckpointJob && <div className="traffic-collection-alert" role="status">
        <ShieldWarning size={22} weight="duotone" />
        <span><b>{activeCheckpointJob.status === "circuit_open" ? "访问验证已触发，剩余请求已停止" : activeCheckpointJob.status === "waiting_connection" ? "采集连接尚未恢复，检查点任务已保留" : "本次自动采集未完整完成"}</b><small>{activeCheckpointJob.last_error_detail || `已采集 ${activeCheckpointJob.collected_count}/${activeCheckpointJob.total_count} 件；不会自动重复读取成功商品。`}</small></span>
        {activeCheckpointJob.can_retry_auto && <button className="primary" type="button" disabled={busy} onClick={() => void retryCheckpointCollection(activeObservationBatch, activeCheckpointJob.checkpoint as "h1" | "h6" | "h24" | "h48" | "h72")}><ArrowClockwise size={15} />恢复连接并补采</button>}
        {activeCheckpointJob.can_complete_manually && <button type="button" disabled={busy} onClick={() => void openManualCheckpointCompletion(activeObservationBatch, activeCheckpointJob.checkpoint as "h1" | "h6" | "h24" | "h48" | "h72")}><ClipboardText size={15} />改为人工补齐</button>}
        <button type="button" onClick={() => { setSelectedBatchId(activeObservationBatch.id); navigateWorkspace("exposure", "batch", activeObservationBatch.id); document.getElementById(`product-batch-${activeObservationBatch.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }); }}><ShieldCheck size={15} />查看安全诊断</button>
      </div>}
    </section>}


    {activeView === "exposure" && legacyTrafficPlanningVisible && trafficGrowth && <TrafficGrowthWorkbench
      overview={trafficGrowth}
      nextPlanSlot={growthPlanSlot}
      busy={busy}
      onCreateExperiment={createTrafficGrowthExperiment}
      onCreateNextBatch={(slot) => openBatchDraft(slot)}
      onAdvanceExperiment={advanceTrafficGrowthExperiment}
      onRefreshAttributions={refreshTrafficAttributions}
      onDecideAttribution={decideTrafficAttribution}
      onRefreshBudget={refreshTrafficBudget}
      onApplyBudget={applyTrafficBudget}
      onCreateCohort={createTrafficScaleCohort}
    />}

    {activeView === "exposure" && legacyTrafficPlanningVisible && !trafficGrowth?.active_experiment && <section className="product-plan-shell" aria-labelledby="product-plan-title">
      <header className="product-plan-head">
        <div>
          <span className="product-eyebrow"><Sparkle size={14} weight="fill" /> ROLLING OPERATING PLAN</span>
          <h3 id="product-plan-title">未来 7 天商品经营方案</h3>
          <p>当前真实批次、未来建议和成熟结论分开呈现；计划随真实检查点变化，相同结论不增加噪声版本。</p>
        </div>
        <div className="product-plan-head-actions">
          <span><small>规则 {data.operating_plan.rules_version}</small><b>第 {data.operating_plan.version} 版</b></span>
          <button className="product-outline-button" disabled={busy} onClick={() => void refreshPlan()}><ArrowClockwise className={busy ? "spin" : ""} size={16} />重新评估</button>
          {activeObservationBatch?.due_checkpoint
            ? <button
              className="product-primary-button"
              disabled={busy || !observationActionReady}
              title={observationActionReady ? `补录 ${checkpointLabels[activeObservationBatch.due_checkpoint]}` : `最早 ${formatTrafficDateTime(activeObservationBatch.due_at)}（北京时间）`}
              onClick={() => openBatchOperation(activeObservationBatch, "checkpoint")}
            ><ClipboardText size={16} />{observationActionReady ? `记录 ${observationCheckpointLabel}` : `${observationCheckpointLabel} 未到期`}</button>
            : <button className="product-primary-button" disabled={!data.products.length} onClick={() => openBatchDraft(activePlanSlot)}><Plus size={16} />新建多商品批次</button>}
        </div>
      </header>

      {!activeObservationBatch && <div className="exposure-last-batch-strip" aria-label="最近一次实际曝光状态">
        <i><ArrowRight size={18} weight="bold" /></i>
        {latestStartedBatch ? <span>
          <b>上次实际投放：{formatTrafficDateTime(latestStartedBatch.started_at)} · {latestStartedBatch.products.length} 件商品 · {moneyExact.format(latestStartedBatch.actual_cost)}</b>
          <small>{latestStartedBatch.status === "invalidated" ? `${latestStartedBatch.invalidation_label || "基线无效 · 已终止观察"}；投放事实和同商品 72 小时冷却仍保留。` : "该批次已结束当前观察，历史事实和冷却状态继续保留。"}</small>
        </span> : <span><b>尚无实际曝光记录</b><small>经营计划只提供建议，建立批次仍需要你人工确认。</small></span>}
        <em>当前无观察中批次</em>
      </div>}

      <div className={`exposure-plan-overview-grid ${activeObservationBatch ? "" : "no-active-batch"}`}>
        {activeObservationBatch && <article className="exposure-current-batch" aria-labelledby="current-exposure-batch-title">
          <header><span><small>CURRENT BATCH</small><h4 id="current-exposure-batch-title">当前进行中的批次</h4></span><em className={`baseline-${activeObservationBatch.baseline_quality}`}>{activeObservationBatch.baseline_quality_label}</em></header>
          <>
            <div className="exposure-current-batch-summary">
              <i><CalendarCheck size={19} weight="duotone" /></i>
              <span><small>当前批次 · 跟进 {observationCheckpointLabel}</small><b>实际投放 {formatTrafficDateTime(activeObservationBatch.started_at)}</b><em>计划 {formatTrafficDateTime(activeObservationBatch.planned_at)} · {activeObservationBatch.planned_actual_delta_label || "实际时间已作为唯一锚点"}</em></span>
            </div>
            <div className="exposure-current-batch-facts">
              <span><small>商品组合</small><b>{activeObservationBatch.products.length} 件</b></span>
              <span><small>批次总费用</small><b>{moneyExact.format(activeObservationBatch.actual_cost)}</b></span>
              <span><small>套餐曝光 / 成熟度</small><b>{activeObservationBatch.total_exposure === null ? "待记录" : integer.format(activeObservationBatch.total_exposure)} · {activeObservationBatch.checkpoint_progress}/4</b></span>
            </div>
            <p className="exposure-baseline-detail"><Info size={14} />{activeObservationBatch.baseline_quality_detail}</p>
            <div className="exposure-current-checkpoints" aria-label="当前批次检查点">
              <span className="done"><CheckCircle size={15} weight="fill" /><b>T0</b><small>已记录</small></span>
              {(["h1", "h6", "h24", "h72"] as const).map((checkpoint) => {
                const completed = activeObservationBatch.completed_checkpoints.includes(checkpoint);
                const next = activeObservationBatch.due_checkpoint === checkpoint;
                return <span className={completed ? "done" : next ? "next" : ""} key={checkpoint}>
                  {completed ? <CheckCircle size={15} weight="fill" /> : next ? <Clock size={15} /> : <Eye size={15} />}
                  <b>{checkpointShortLabels[checkpoint]}</b>
                  <small>{completed ? "已记录" : next ? activeObservationBatch.due_ready ? "待补录" : formatTrafficDateTime(activeObservationBatch.due_at) : "待观察"}</small>
                </span>;
              })}
            </div>
            <div className="exposure-current-actions">
              <span>所有检查点从实际开始 {formatTrafficDateTime(activeObservationBatch.started_at)} 计算</span>
              {activeObservationBatch.status === "running" && <button className="product-primary-button" disabled={busy} onClick={() => openBatchOperation(activeObservationBatch, "complete")}><CheckCircle size={15} />记录套餐完成</button>}
              {activeObservationBatch.due_checkpoint && <button className="product-primary-button" disabled={busy || !activeObservationBatch.due_ready} title={activeObservationBatch.due_ready ? undefined : `最早 ${formatTrafficDateTime(activeObservationBatch.due_at)}（北京时间）`} onClick={() => openBatchOperation(activeObservationBatch, "checkpoint")}><ClipboardText size={15} />{activeObservationBatch.due_ready ? `记录 ${observationCheckpointLabel}` : `${observationCheckpointLabel} 未到期`}</button>}
            </div>
          </>
        </article>}

        <section className="exposure-future-plan" aria-labelledby="future-exposure-plan-title">
          <header><span><small>NEXT 7 DAYS</small><h4 id="future-exposure-plan-title">未来经营计划</h4></span><em>{data.operating_plan.cadence}</em></header>
          <div className="product-week-plan" role="list" aria-label="未来七天经营安排">
            {data.operating_plan.slots.map((slot, index) => {
              const executedBatch = slot.status === "executed" && slot.batch_id
                ? data.traffic_batches.find((batch) => batch.id === slot.batch_id) || null
                : null;
              const slotTracksObservation = Boolean(
                activeObservationBatch
                && slot.action_type === "measure"
                && slot.source_batch_id === activeObservationBatch.id,
              );
              const title = executedBatch
                ? "已执行多商品曝光"
                : slotTracksObservation
                ? activeObservationBatch
                  ? observationPlanTitle(activeObservationBatch)
                  : "继续观察当前批次"
                : planActionLabels[slot.action_type] || slot.action_type;
              const slotMeta = executedBatch
                ? `${executedBatch.products.length} 件 · ${moneyExact.format(executedBatch.actual_cost)}`
                : slotTracksObservation
                ? "跟进观察"
                : slot.action_type === "traffic"
                  ? `${slot.products.length} 件 · ${moneyExact.format(slot.planned_cost)}`
                  : slot.products.length
                    ? `${slot.products.length} 件 · 不投放`
                    : "不产生新费用";
              return <button type="button" role="listitem" aria-pressed={slot.id === activePlanSlot?.id} className={`${slot.id === activePlanSlot?.id ? "active" : ""} slot-${slot.action_type} ${slot.status === "executed" ? "is-executed" : ""}`} onClick={() => setActivePlanSlotId(slot.id)} key={slot.id}>
                <span><small>{index === 0 ? "今天" : slot.weekday}</small><b>{formatPlanDate(slot.date)}</b></span>
                <i>{slotTracksObservation || slot.action_type === "measure" ? <Timer size={17} weight="duotone" /> : slot.action_type === "traffic" ? <Megaphone size={17} weight="duotone" /> : slot.action_type === "optimize" ? <Lightbulb size={17} weight="duotone" /> : <PauseCircle size={17} weight="duotone" />}</i>
                <strong>{title}</strong>
                <em>{slotMeta}</em>
                {slot.status === "executed"
                  ? <small className="plan-slot-state is-executed">今日已执行</small>
                  : slot.cooldown_conflict_count > 0
                  ? <small className="plan-slot-state is-cooling">商品冷却中</small>
                  : slot.lock_label && <small className={`plan-slot-state is-${slot.lock_mode}`}>{slot.lock_label}</small>}
              </button>;
            })}
          </div>
          <p><Info size={14} />72h 用于同一商品的冷却与归因；完全轮换的新商品组可独立开始，只有真正标为“安排多商品曝光”的日期才会建议建立新批次。</p>
        </section>

        {activeObservationBatch && <aside className="exposure-early-observation" aria-labelledby="early-observation-title">
          <header><small>EARLY SIGNALS</small><h4 id="early-observation-title">早期观察</h4></header>
          <div><Clock size={19} weight="duotone" /><span><small>下一检查点</small><b>{activeObservationBatch?.due_checkpoint ? `${observationCheckpointLabel}${activeObservationBatch.due_ready ? " · 已到期" : " · 未到期"}` : "暂无进行中批次"}</b>{activeObservationBatch?.due_at && <em>{formatTrafficDateTime(activeObservationBatch.due_at)}（北京时间）</em>}</span></div>
          <div><Gauge size={19} weight="duotone" /><span><small>成熟度</small><b>{activeObservationBatch ? `${activeObservationBatch.checkpoint_progress}/4` : "0/4"}</b><em>+1h / +6h 仅作过程观察</em></span></div>
          <div className="is-warning"><Warning size={19} weight="duotone" /><span><small>当前结论边界</small><b>{activeObservationBatch.attribution_status === "exploratory" ? "低置信探索，不进入时段或预算" : "不能用于时段或预算结论"}</b><em>{activeObservationBatch.attribution_status === "exploratory" ? "早间参考只支持方向性变化，永久排除复投和正式商品优先级" : `+24h / ${checkpointShortLabels[activeObservationBatch.terminal_checkpoint]} 且 T0 合格后才进入比较`}</em></span></div>
          <div><ShieldCheck size={19} weight="duotone" /><span><small>成熟有效批次</small><b>{data.operating_plan.effective_batch_count} 个</b><em>不会用旧 T0 或重叠批次排名</em></span></div>
        </aside>}
      </div>

      {activePlanSlot && <div className="product-plan-focus-grid">
        <article className={`product-plan-focus plan-action-${activePlanSlot.action_type} ${activePlanExecutedBatch ? "is-executed" : ""}`} aria-labelledby="selected-plan-slot-title">
          <header className="product-plan-focus-top">
            <span><small>{activePlanSlot.weekday.toUpperCase()} · {activePlanSlot.action_type === "traffic" ? "EXPOSURE" : activePlanSlot.action_type === "optimize" ? "OPTIMIZE" : "PLAN"}</small><b id="selected-plan-slot-title">{activePlanSlot.action_type === "traffic" ? formatPlanSlotDateTime(activePlanSlot.date, activePlanSlot.scheduled_time) : formatPlanDate(activePlanSlot.date)} · {selectedSlotTitle}</b></span>
            <div className="product-plan-focus-badges">
              <em>{activePlanSlot.products.length} 件商品</em>
              <em className={activePlanExecutedBatch || activePlanSlot.is_new_spend ? "is-spend" : "is-free"}>{activePlanExecutedBatch ? `已投入 ${moneyExact.format(activePlanExecutedBatch.actual_cost)}` : activePlanSlot.is_new_spend ? `批次 ${moneyExact.format(activePlanSlot.planned_cost)}` : "费用 ¥0"}</em>
              {activePlanExecutedBatch && <em className="is-executed">今日已执行</em>}
              <em className={activePlanSlot.cooldown_conflict_count > 0 ? "is-warning" : "is-safe"}>{activePlanSlot.cooldown_conflict_count > 0 ? `${activePlanSlot.cooldown_conflict_count} 件冷却中` : "无冷却冲突"}</em>
            </div>
          </header>
          <p>{activePlanSlot.reason}</p>
          <div className="product-plan-product-list" aria-label={`${formatPlanDate(activePlanSlot.date)}商品安排`}>
            {activePlanSlot.products.map((product, index) => <article key={product.external_id}>
              <i>{String(index + 1).padStart(2, "0")}</i>
              <span><b>{product.title}</b><small>{product.reason}</small></span>
              <em>{product.role}</em>
            </article>)}
            {!activePlanSlot.products.length && <div className="product-plan-no-products"><PauseCircle size={16} />当天不安排具体商品，继续观察真实数据。</div>}
          </div>
          <footer className="product-plan-focus-actions">
            <span><small>{activePlanExecutedBatch ? `实际开始 ${formatTrafficDateTime(activePlanExecutedBatch.started_at)}；重新评估不会改写今日执行事实` : activePlanSlot.action_type === "traffic" ? "计划时间仅作提醒；真实开始时间以建立并确认批次为准" : "当天不创建曝光批次，也不会产生新的曝光支出"}</small><b>{activePlanExecutedBatch ? `${activePlanExecutedBatch.baseline_quality_label} · ${activePlanExecutedBatch.analysis_tier_label}` : activePlanSlot.action_type === "traffic" ? `预计本周曝光投入：${moneyExact.format(data.operating_plan.spent_this_week)} + ${moneyExact.format(data.operating_plan.planned_this_week)}` : `下一次建议投放：${nextTrafficPlanSlot ? formatPlanSlotDateTime(nextTrafficPlanSlot.date, nextTrafficPlanSlot.scheduled_time) : "等待下一次评估"}`}</b></span>
            {activePlanExecutedBatch
              ? <button type="button" className="product-outline-button" disabled><CheckCircle size={15} weight="fill" />执行事实已冻结</button>
              : activePlanSlot.lock_mode === "stability"
              ? <button type="button" className="product-outline-button" disabled><ShieldCheck size={15} />24h内计划固定</button>
              : <button type="button" className="product-outline-button" disabled={busy} onClick={() => void togglePlanLock(activePlanSlot)}>{activePlanSlot.locked ? <><LockSimpleOpen size={15} />取消手动固定</> : <><LockSimple size={15} />手动固定</>}</button>}
            {activePlanExecutedBatch
              ? <button type="button" className="product-primary-button" onClick={() => navigateWorkspace("exposure", "batch", activePlanExecutedBatch.id)}><Eye size={15} />查看已执行批次</button>
              : activePlanSlot.action_type === "traffic"
              ? <button type="button" className="product-primary-button" disabled={busy || !activePlanSlot.products.length} onClick={() => openBatchDraft(activePlanSlot)}><Plus size={15} />按这 {activePlanSlot.products.length} 件建立批次</button>
              : activePlanSlot.action_type === "optimize"
                ? <button type="button" className="product-primary-button" disabled={!activePlanSlot.products.length} onClick={() => activePlanSlot.products[0] ? navigateWorkspace("launch", "product", activePlanSlot.products[0].external_id) : navigateWorkspace("launch")}><PencilSimple size={15} />查看 {activePlanSlot.products.length} 件商品修改建议</button>
                : <button type="button" className="product-outline-button" onClick={() => navigateWorkspace("overview")}><Eye size={15} />查看经营总览</button>}
          </footer>
        </article>

        <aside className="product-plan-rule-card" aria-label="当天计划依据">
          <div><i><Sparkle size={18} weight="duotone" /></i><span><small>WHY THIS PLAN</small><b>{activePlanSlot.action_type === "traffic" ? "为什么推荐这组商品" : activePlanSlot.action_type === "optimize" ? "为什么不是连续投放" : "为什么这样安排"}</b></span></div>
          <ol>{selectedSlotEvidence.map((line, index) => <li key={line}><i>{index + 1}</i><span>{line}</span></li>)}</ol>
          <div className={`product-plan-cooldown-note ${activePlanSlot.cooldown_conflict_count > 0 ? "is-warning" : "is-safe"}`}>
            {activePlanSlot.cooldown_conflict_count > 0 ? <Warning size={18} weight="fill" /> : <CheckCircle size={18} weight="fill" />}
            <span><b>{activePlanExecutedBatch ? "今日投流已经成为不可改写的执行事实" : activePlanSlot.cooldown_conflict_count > 0 ? `${activePlanSlot.cooldown_conflict_count} 件商品仍在 72 小时冷却中` : activePlanSlot.action_type === "traffic" ? "当前组合没有 72 小时冷却冲突" : "日期状态已与固定语义分开"}</b><small>{activePlanExecutedBatch ? "基线质量只决定分析置信度，不会把已完成任务重新改成优化或再次投放。" : activePlanSlot.cooldown_conflict_count > 0 && activePlanSlot.cooldown_until ? `最早可用：${formatTrafficDateTime(activePlanSlot.cooldown_until)}` : activePlanSlot.lock_mode === "stability" ? "“计划固定”只表示未来24小时内重新评估不改动，并不会阻止你按计划建立批次。" : "只有真正标为“多商品曝光”的日期才会建议新建批次并产生费用。"}</small></span>
          </div>
        </aside>
      </div>}

      <footer className="product-plan-legend" aria-label="经营计划图例">
        <span><i className="is-traffic" />多商品曝光：会产生整批费用</span>
        <span><i className="is-optimize" />优化商品表达：不产生费用</span>
        <span><i className="is-stable" />24h 计划固定：不是冷却，也不是禁用</span>
      </footer>
    </section>}

    {activeView === "exposure" && legacyTrafficPlanningVisible && !trafficGrowth?.active_experiment && <ExposureAnalytics data={data} />}

    {activeView === "launch" && <>
      <section className="product-launch-layout">
        <ProductLaunchWorkbench
          busy={busy}
          data={data}
          onCompleteLaunchPlan={async (planId) => {
            try {
              await localPlatformService.updateLaunchPlan(planId, "completed");
              await load(true);
            } catch (caught) {
              notify(caught instanceof Error ? caught.message : "状态更新失败");
            }
          }}
          onCreateLaunchPlan={createLaunchPlan}
          onShowModification={() => document.getElementById("product-modification-lab")?.scrollIntoView({ behavior: "smooth", block: "start" })}
        />

        {renderMarketReference(false)}
      </section>

      <section className="product-modification-lab" id="product-modification-lab">
        <header><span><small>CONTROLLED EXPERIMENTS</small><h3>商品修改实验</h3></span><p><Flask size={16} />基于真实曝光与咨询数据，一次只改变一个变量</p></header>
        <div className="modification-table" role="table" aria-label="商品修改实验建议">
          <div className="modification-table-head" role="row"><span>商品与置信度</span><span>当前建议与依据</span><span>实验流程</span><span>操作</span></div>
          {visibleModificationSuggestions.map((suggestion, index) => {
            const product = data.products.find((value) => value.external_id === suggestion.external_id);
            const experiment = data.modification_experiments.find((value) => value.item_external_id === suggestion.external_id && value.status === "observing");
            const evidenceExpanded = expandedModificationEvidenceId === suggestion.external_id;
            const experimentBlocked = Boolean(suggestion.blocked_reason || !suggestion.variable);
            const openEvidence = () => {
              if (evidenceExpanded) {
                setExpandedModificationEvidenceId(null);
                navigateWorkspace("launch");
                return;
              }
              setExpandedModificationEvidenceId(suggestion.external_id);
              navigateWorkspace("launch", "product", suggestion.external_id);
            };
            return <article role="row" id={`product-modification-${suggestion.external_id}`} className={evidenceExpanded ? "is-evidence-open" : ""} key={suggestion.external_id}>
              <span className="modification-product"><i>{String(index + 1).padStart(2, "0")}</i><b>{suggestion.title}<small>{integer.format(product?.browse_count || 0)} 经营浏览 · {product?.inquiry_count || 0} 咨询</small></b><em className={`confidence-${suggestion.confidence}`}>{confidenceLabels[suggestion.confidence] || suggestion.confidence}</em></span>
              <span className="modification-advice" title={suggestion.confidence_basis.join("；")}>
                <span className="modification-source-tags">{suggestion.evidence_sources.map((source) => <i className={source === "高可见市场参考" ? "market" : "internal"} key={source}>{source}</i>)}</span>
                <b>{experiment ? `正在观察${actionLabels[experiment.variable] || experiment.variable}` : suggestion.blocked_reason || (suggestion.variable ? actionLabels[suggestion.variable] : "先补齐可比较数据")}</b>
                <small>{experiment ? `观察至 ${formatDate(experiment.observation_until)}` : suggestion.reason}</small>
                {!experiment && <em>{suggestion.suggested_change}</em>}
                {!experiment && suggestion.market_gap && <mark>{suggestion.benchmark_keyword} · {suggestion.market_gap}{suggestion.reference_price_range ? ` · 参考 ${suggestion.reference_price_range}` : ""}</mark>}
              </span>
              <span className="modification-flow"><i className={experiment ? "done" : ""}><Gauge size={15} />选择变量</i><ArrowRight size={13} /><i className={experiment ? "done" : ""}><PencilSimple size={15} />记录修改</i><ArrowRight size={13} /><i className={experiment ? "active" : ""}><CalendarCheck size={15} />观察 7 天</i><ArrowRight size={13} /><i><ShieldCheck size={15} />保留 / 回退</i></span>
              <span className="modification-actions">
                <button
                  type="button"
                  className="modification-evidence-action"
                  aria-expanded={evidenceExpanded}
                  aria-controls={`product-modification-evidence-${suggestion.external_id}`}
                  onClick={openEvidence}
                >
                  <Eye size={14} />查看证据
                </button>
                {experiment
                  ? <button type="button" className="modification-primary-action" onClick={() => { setExperimentDecision(experiment); setExperimentNote(""); }}><Flask size={14} />{experiment.can_evaluate ? "评估结果" : "查看实验"}</button>
                  : <button type="button" className="modification-primary-action" disabled={experimentBlocked} title={experimentBlocked ? suggestion.blocked_reason || "当前缺少可执行的单变量建议" : undefined} onClick={() => openModificationExperiment(suggestion)}><Flask size={14} />建立实验</button>}
              </span>
              {evidenceExpanded && <div className="modification-evidence-detail" id={`product-modification-evidence-${suggestion.external_id}`}>
                <span><small>判断依据</small><b>{suggestion.confidence_basis.length ? suggestion.confidence_basis.join("；") : suggestion.reason}</b></span>
                <span><small>建议动作</small><b>{suggestion.suggested_change || suggestion.blocked_reason || "继续积累可比较数据"}</b></span>
                <span><small>市场参考</small><b>{suggestion.market_evidence.length ? suggestion.market_evidence.join("；") : suggestion.market_gap || "尚无稳定市场参考"}</b></span>
              </div>}
            </article>;
          })}
          {data.modification_suggestions.length === 0 && <div className="product-empty-state"><Flask size={34} weight="duotone" /><h4>还没有可实验的本人商品</h4><p>先在商品管理中完成归属验证和数据采集。</p></div>}
        </div>
        {data.modification_suggestions.length > 6 && !focusedExperiment && <button type="button" className="product-section-expand" aria-expanded={modificationExpanded} onClick={() => setModificationExpanded((value) => !value)}>{modificationExpanded ? "收起修改建议" : `展开全部 ${data.modification_suggestions.length} 条建议`}<CaretRight className={modificationExpanded ? "expanded" : ""} size={15} /></button>}
      </section>
    </>}

    {activeView === "market" && <section className="product-market-page">{renderMarketReference(true)}</section>}

    {activeView === "overview" && selected && <ProductOverviewWorkspace management={overviewControls} overview={overviewFacts} onAdd={openRegistration} products={products} selectedId={selected.external_id} onSelect={id=>navigateWorkspace("overview", "product", id)} context={<>        <div className="product-strategy-evidence"><h4>当前建议与证据</h4><div className="product-window-summary"><span className={`quality-${selected.data_quality}`}>{confidenceLabels[selected.data_quality] || selected.data_quality}</span>{selected.recent_windows.map((window) => <small key={window.days}>{window.days === 1 ? "24h" : `${window.days}d`}：{window.browse_delta === null ? "待积累" : `+${window.browse_delta} 浏览 / +${window.inquiry_delta || 0} 咨询`}</small>)}</div>{selected.recommendation && selected.recommendation.status !== "dismissed" ? <><p><AttentionBadge value={selected.recommendation.attention} /><b>{selected.recommendation.title}</b></p><ul>{selected.recommendation.actions.map((action) => <li key={action}><CheckCircle size={15} />{action}</li>)}</ul></> : <div className="compact-empty"><PauseCircle size={26} /><span><b>{selected.recommendation?.status === "dismissed" ? "今日建议已暂不处理" : selected.snapshot_count > 0 ? "当前暂无待处理建议" : "等待首个快照"}</b><small>{selected.recommendation?.status === "dismissed" ? "明日数据变化后会重新评估。" : selected.snapshot_count > 0 ? "可继续查看现有采集记录与经营趋势。" : "系统不会在没有数据时生成策略。"}</small></span></div>}</div>      {selected.actions.length > 0 && <div className="product-action-history"><h4>最近人工动作</h4>{selected.actions.slice(0, 5).map((action) => <p key={action.id}><i><CheckCircle size={15} weight="fill" /></i><span><b>{actionLabels[action.action_type] || action.action_type}</b><small>{action.note || "未填写备注"}</small></span><time>{formatDate(action.happened_at)}{action.cost > 0 && ` · ${money.format(action.cost)}`}</time></p>)}</div>}</>}><section className="product-panel product-detail-panel" id="product-detail">
      <header className="product-detail-head"><div><span><Storefront size={20} weight="duotone" /></span><div className="product-detail-title"><small>SELECTED PRODUCT</small><h3>{selected.title}</h3><ProductCollectionBadge product={selected} /></div></div><div><button className="product-outline-button" disabled={busy} onClick={() => void collectManually(selected.external_id)}>{collectingScope === selected.external_id ? <ArrowClockwise className="spin" size={16} /> : <ArrowClockwise size={16} />}采集此商品</button><button className="product-outline-button" disabled={busy} onClick={() => void toggleMonitor(selected)}>{selected.monitoring_enabled ? <EyeSlash size={16} /> : <Eye size={16} />}{selected.monitoring_enabled ? "暂停监测" : "恢复监测"}</button><button className="product-outline-button" onClick={() => openBatchDraft(activePlanSlot, [selected.external_id])}><Megaphone size={16} />记录真实投流</button><button className="product-primary-button" onClick={() => openAction(selected, selected.recommendation)}><CheckCircle size={16} />记录商品修改</button></div></header>
      {selected.last_error_detail && <div className="product-item-diagnostic"><Warning size={17} weight="fill" /><span><b>{selected.last_error_code === "access_verification" ? "今日正式采集未取得数据" : selected.last_error_code === "item_unavailable" ? "商品详情不可读取" : "最近一次采集未完成"}</b><small>{productDiagnosticDetail(selected)}</small><em>最近尝试 {formatDate(selected.last_attempt_at)}（北京时间） · 当前展示 {selected.last_collected_at ? `${formatDate(selected.last_collected_at)} 的历史快照` : "的不是今日商品数据"}</em></span></div>}
      <ProductMetricSummary product={selected}/>
      <div className="product-detail-grid">
        <div className="product-detail-trend"><h4>经营浏览趋势</h4><ProductTrend product={selected} /></div>
        <div className="product-funnel"><h4>从经营浏览到成交</h4><div><span><small>经营浏览</small><b>{integer.format(selected.browse_count)}</b><em>原始 {integer.format(selected.raw_browse_count)}</em></span><CaretRight size={17} /><span><small>咨询</small><b>{selected.inquiry_count}</b><em>{selected.inquiry_rate === null ? "—" : `${selected.inquiry_rate}%`}</em></span><CaretRight size={17} /><span><small>项目</small><b>{selected.converted_project_count}</b><em>{selected.deal_rate === null ? "—" : `${selected.deal_rate}%`}</em></span></div></div>

      </div>
      <section className="product-profit-detail" aria-label="商品实际利润构成">
        <details className="product-profit-formula">
          <summary><span>实际利润构成</span><b>{money.format(selected.profit_total)}</b><small>{selected.profit_is_realtime ? "统一账本实时派生" : "商品快照口径"}</small></summary>
          <div><span><small>净确认到账</small><b>{money.format(selected.revenue_total)}</b></span><i>−</i><span><small>项目支出</small><b>{money.format(selected.project_expense_total)}</b></span><i>−</i><span><small>退款</small><b>{money.format(selected.project_refund_total)}</b></span><i>=</i><span className="profit-total"><small>实际利润</small><b>{money.format(selected.profit_total)}</b></span></div>
          <p><Info size={15} />当前利润会随项目确认到账实时更新；下方历史商品快照仍保留采集当时的数据，不追溯改写。</p>
        </details>
        <ProductLinkedProjects projects={selected.linked_projects}/>
      </section>

    </section></ProductOverviewWorkspace>}

    {(activeView === "overview" || activeView === "exposure") && <section className={`product-workspace-grid workspace-${activeView}`}>
      <main className="product-main-column">
        {activeView === "exposure" && <section className="product-panel product-batch-panel">
          <header><span><small>ACTUAL EXPOSURE OBSERVATIONS</small><h3>真实投流观察记录</h3></span><div><em>{trafficBatchStatusLabel} · 共 {data.traffic_summary.batch_count} 个批次</em><button type="button" onClick={() => openBatchDraft()}><Plus size={14} />记录刚完成的真实投流</button></div></header>
          {selectedBatch ? <>
            <div className={`product-batch-picker-shell ${batchPickerOpen ? "is-open" : ""}`} ref={batchPickerRef}>
              <button
                aria-controls="product-batch-picker-list"
                aria-expanded={batchPickerOpen}
                aria-haspopup="listbox"
                className="product-batch-picker-trigger"
                onClick={() => setBatchPickerOpen((current) => !current)}
                ref={batchPickerTriggerRef}
                type="button"
              >
                <i><MagnifyingGlass size={18} /></i>
                <span><small>{selectedBatch.observation_title}</small><b>{selectedBatch.products.map((product) => product.title).join("、")}</b><em>{selectedBatch.is_legacy_protocol ? "历史 72h 协议" : "实际时间 48h 协议"} · {selectedBatch.products.length} 件 · {moneyExact.format(selectedBatch.actual_cost)}</em></span>
                <CaretRight className={batchPickerOpen ? "is-open" : ""} size={18} />
              </button>
              {batchPickerOpen && <div className="product-batch-picker-popover" id="product-batch-picker-list" onKeyDown={handleBatchPickerNavigation}>
                <header><span><small>SELECT BATCH</small><b>选择一个曝光批次</b><em>按建立日期分组，只替换下方详情</em></span><button aria-label="关闭批次选择" onClick={() => { setBatchPickerOpen(false); batchPickerTriggerRef.current?.focus(); }} type="button"><X size={18} /></button></header>
                <label className="product-batch-search"><MagnifyingGlass size={17} /><input aria-label="搜索曝光批次" onChange={(event) => setBatchSearch(event.target.value)} onKeyDown={handleBatchPickerNavigation} placeholder="搜索日期、商品或状态" ref={batchSearchRef} type="search" value={batchSearch} />{batchSearch && <button aria-label="清除批次搜索" onClick={() => setBatchSearch("")} type="button"><X size={15} /></button>}</label>
                <div className="product-batch-picker-groups" role="listbox" aria-label="曝光批次">
                  {groupedBatchHistory.map(([dayLabel, batches]) => <section aria-label={dayLabel} key={dayLabel} role="group"><h4>{dayLabel}<small>{batches.length} 批</small></h4>{batches.map((batch) => <button aria-selected={batch.id === selectedBatch.id} className={batch.id === selectedBatch.id ? "is-selected" : ""} key={batch.id} onClick={() => selectTrackedBatch(batch)} onKeyDown={(event) => handleTrackedBatchActivation(event, batch)} role="option" type="button"><i><Megaphone size={17} weight="duotone" /></i><span><b>建立 {formatTrafficDateTime(batch.created_at)}</b><small>{batch.products.map((product) => product.title).join("、")}</small><em>{trafficBatchStatusLabels[batch.status] || batch.status} · {batch.started_at ? `实际 ${formatTrafficDateTime(batch.started_at)}` : "尚未开始"}</em></span><strong>{moneyExact.format(batch.actual_cost)}<small>{batch.products.length} 件</small></strong>{batch.id === selectedBatch.id && <CheckCircle size={17} weight="fill" />}</button>)}</section>)}
                  {!groupedBatchHistory.length && <div className="product-batch-picker-empty"><MagnifyingGlass size={24} /><b>没有匹配批次</b><small>可换一个商品名称、日期或状态搜索。</small></div>}
                </div>
              </div>}
            </div>
            <div className="product-batch-list is-single">{[selectedBatch].map((batch) => <article id={`product-batch-${batch.id}`} key={batch.id} className={`batch-status-${batch.status} ${expandedBatchId === batch.id ? "is-expanded" : ""}`}>
            <div className="product-batch-summary">
              <i><Megaphone size={19} weight="duotone" /></i>
              <span><small>{batch.observation_title} · {batch.products.length} 件商品</small><b>{batch.products.map((product) => product.title).join("、")}</b><em>{batch.status === "invalidated" ? "基线无效 · 仅保留投流事实" : batch.status === "planned" ? "历史计划批次 · 尚未实际投流" : batch.status === "running" ? `实际投流已记录 · 等待 ${batch.observation_window_hours}h 观察` : batch.status === "observing" ? `观察中 · 终点 ${checkpointShortLabels[batch.terminal_checkpoint]}` : batch.status === "closed" ? `${batch.observation_window_hours} 小时观察已完成` : "批次已取消"} · {batch.is_legacy_protocol ? "历史 72h 协议" : "48h 协议"}</em></span>
              <strong><small>批次总费用</small>{moneyExact.format(batch.actual_cost)}</strong>
            </div>
            {batch.status === "planned" && <div className={`product-batch-readiness baseline-${batch.baseline_status}`}><Timer size={15} /><span><b>{batch.baseline_status_label}</b><small>{batch.baseline_quality_detail}</small></span>{batch.needs_replan && <em>需要重排</em>}</div>}
            {batch.overlap_warning && <p className="product-batch-warning"><Warning size={14} />{batch.overlap_warning}</p>}
            {batch.start_blocked && batch.start_blocked_reason && <p className="product-batch-warning is-blocked"><ShieldWarning size={14} />{batch.start_blocked_reason}</p>}
            {batch.started_at && <div className={`product-batch-quality baseline-${batch.baseline_quality}`}><Info size={15} /><span><b>{batch.baseline_quality_label}{batch.status === "invalidated" ? "" : ` · 成熟度 ${batch.checkpoint_progress}/4`}</b><small>{batch.baseline_quality_detail}</small></span></div>}
            {batch.status !== "invalidated" && batch.observation_checkpoint && batch.has_reliable_baseline && <div className="product-batch-effect" aria-label="当前批次效果">
              <span><small>{checkpointLabels[batch.observation_checkpoint]} 浏览</small><b>+{integer.format(batch.browse_delta)}</b></span>
              <span><small>想要 / 收藏</small><b>+{integer.format(batch.want_delta)} / +{integer.format(batch.collect_delta)}</b></span>
              <span><small>咨询增量</small><b>+{integer.format(batch.inquiry_delta)}</b></span>
              <span><small>每咨询成本</small><b>{batch.cost_per_inquiry === null ? "—" : moneyExact.format(batch.cost_per_inquiry)}</b></span>
              <em className={`quality-${batch.data_quality}`}>{trafficDataQualityLabels[batch.data_quality] || batch.data_quality}</em>
            </div>}
            {batch.status === "invalidated" && !batch.exploratory_available
              ? <div className="product-batch-no-chart is-invalidated"><ShieldWarning size={18} weight="duotone" /><span><b>历史事实已保留，暂时没有可比较序列</b><small>费用、实际时间和已有累计记录仍可审计；无效 T0 不会作为曲线起点。</small></span></div>
              : <ExposureBatchMiniChart batch={batch} />}
            <div className="product-checkpoint-track" aria-label="批次检查点">
              <span className={batch.status === "invalidated" ? "missing" : batch.started_at && !batch.has_reliable_baseline ? "missing" : batch.started_at || batch.baseline_status === "ready" ? "done" : "next"}><i>T0</i><small>{batch.status === "invalidated" ? "基线无效" : batch.started_at ? batch.has_reliable_baseline ? "已用于投放" : "未可靠记录" : batch.baseline_status === "ready" ? "30 分钟内有效" : "待准备"}</small></span>
              {batch.checkpoint_sequence.map((checkpoint) => <span className={batch.completed_checkpoints.includes(checkpoint) ? "done" : batch.status === "invalidated" ? "stopped" : batch.due_checkpoint === checkpoint ? "next" : ""} key={checkpoint}><i>{checkpointLabels[checkpoint]?.replace(" 小时", "h") || checkpoint}</i><small>{batch.completed_checkpoints.includes(checkpoint) ? batch.status === "invalidated" ? "历史已记录" : "已记录" : batch.status === "invalidated" ? "已终止" : batch.due_checkpoint === checkpoint ? formatTrafficDateTime(batch.due_at) : "待观察"}</small></span>)}
            </div>
            <div className="product-batch-actions">
              {batch.total_exposure !== null && <span>套餐总曝光 <b>{integer.format(batch.total_exposure)}</b></span>}
              {batch.started_at && (batch.status !== "invalidated" || batch.exploratory_available) && <button type="button" aria-expanded={expandedBatchId === batch.id} onClick={() => setExpandedBatchId((current) => current === batch.id ? null : batch.id)}>{expandedBatchId === batch.id ? "收起分析" : batch.analysis_tier === "exploratory" ? "展开探索分析" : "展开完整曲线"}</button>}
              {batch.is_legacy_protocol && <span>历史 72h 批次仅供查看</span>}
              {!batch.is_legacy_protocol && batch.status === "running" && <button type="button" className="primary" disabled={busy} onClick={() => openBatchOperation(batch, "complete")}><CheckCircle size={14} />记录套餐完成</button>}
              {!batch.is_legacy_protocol && ["observing", "closed"].includes(batch.status) && batch.due_checkpoint && <button type="button" className="primary" disabled={busy || !batch.due_ready} title={batch.due_ready ? undefined : `最早 ${formatTrafficDateTime(batch.due_at)}（北京时间）`} onClick={() => openBatchOperation(batch, "checkpoint")}><ClipboardText size={14} />{batch.due_ready ? `记录 ${checkpointLabels[batch.due_checkpoint]}` : `${checkpointShortLabels[batch.due_checkpoint]} 未到期`}</button>}
            </div>
            {expandedBatchId === batch.id && batch.started_at && (batch.status !== "invalidated" || batch.exploratory_available) && <ExposureProductDelta batches={[batch]} initialBatchId={batch.id} embedded />}
          </article>)}</div>
          </> : batchHistoryLoading ? <div className="product-batch-history-loading"><ArrowClockwise className="spin" size={20} />正在读取完整批次历史…</div> : <div className="product-empty-state product-batch-empty"><Megaphone size={38} weight="duotone" /><h4>还没有真实投流记录</h4><p>完成闲鱼人工投流后再来记录；系统以确认分钟开始 48 小时观察并记入批次总费用。</p><button onClick={() => openBatchDraft()}><Plus size={16} />记录第一笔真实投流</button></div>}
        </section>}

        {activeView === "overview" && <><details className="workspace-secondary"><summary>全部商品建议与经营明细</summary><section className="product-panel product-priority-panel">
          <header><span><small>DAILY PRIORITIES</small><h3>今日优先策略</h3></span><em>{data.recommendations.length} 条有依据的建议</em></header>
          {data.recommendations.length ? <div className="product-priority-list">
            {visiblePriorityRecommendations.map((recommendation, index) => {
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
                  {product && (recommendation.strategy_code === "scale_candidate" ? <button className="priority-primary" onClick={() => openBatchDraft(activePlanSlot, [product.external_id])}>记录这组真实投流</button> : <button className="priority-primary" onClick={() => openAction(product, recommendation)}>记录商品修改</button>)}
                  <button className="priority-dismiss" disabled={busy} onClick={() => void dismissRecommendation(recommendation)}>暂不处理</button>
                </div>
              </article>;
            })}
          </div> : <div className="product-empty-state"><CheckCircle size={40} weight="duotone" /><h4>今天没有待处理建议</h4><p>系统不会为了显得智能而填充没有证据的策略。</p></div>}
          {data.recommendations.length > 3 && <button type="button" className="product-section-expand" aria-expanded={priorityExpanded} onClick={() => setPriorityExpanded((value) => !value)}>{priorityExpanded ? "收起优先策略" : data.recommendations.length > 5 ? "展开前 5 条优先策略" : `展开全部 ${data.recommendations.length} 条优先策略`}<CaretRight className={priorityExpanded ? "expanded" : ""} size={15} /></button>}
        </section>

        <section className="product-panel product-inventory-panel">
          <header><span><small>PRODUCT RADAR</small><h3>商品经营雷达</h3></span><em>{normalizedSearch ? `筛选出 ${products.length} 个` : "点击商品查看证据"}</em></header>
          {products.length ? <div className="product-table" role="table" aria-label="商品经营列表">
            <div className="product-table-head" role="row"><span>商品</span><span>经营浏览变化</span><span>想要 / 收藏</span><span>咨询 / 成交</span><span>利润</span><span>当前策略</span></div>
            {visibleProducts.map((product) => <button type="button" role="row" className={selected?.external_id === product.external_id ? "selected" : ""} onClick={() => navigateWorkspace("overview", "product", product.external_id)} key={product.external_id}>
              <span className="product-name-cell"><i><Storefront size={18} weight="duotone" /></i><b>{product.title}<small>ID {product.external_id}</small></b><ProductCollectionBadge product={product} /></span>
              <span className="product-browse-cell"><strong>{integer.format(product.browse_count)}</strong><small>{product.browse_delta === null ? "建立基线" : `+${integer.format(product.browse_delta)}`}</small><em>平台原始 {integer.format(product.raw_browse_count)} · 已排除 {product.collection_views_excluded}</em></span>
              <span><strong>{product.want_count} / {product.collect_count}</strong><small>累计互动</small></span>
              <span><strong>{product.inquiry_count} / {product.converted_project_count}</strong><small>{product.deal_rate === null ? "暂无成交率" : `成交率 ${product.deal_rate}%`}</small></span>
              <span><strong>{money.format(product.profit_total)}</strong><small>{product.linked_projects.length} 个关联项目 · {product.profit_is_realtime ? "实时账本" : "快照口径"}</small></span>
              <span>{product.recommendation && ["active", "in_progress"].includes(product.recommendation.status) ? <AttentionBadge value={product.recommendation.attention} /> : <em className="product-waiting">{product.recommendation?.status === "dismissed" ? "今日已忽略" : "等待数据"}</em>}<CaretRight size={15} /></span>
            </button>)}
          </div> : <div className="product-empty-state"><MagnifyingGlass size={40} weight="duotone" /><h4>{normalizedSearch ? "没有匹配的商品" : "还没有监测商品"}</h4><p>{normalizedSearch ? "可以调整顶部搜索关键词。" : "添加闲鱼商品 ID 或链接，系统会在下一次每日采集中读取数据。"}</p>{!normalizedSearch && <button onClick={() => setRegisterOpen(true)}><Plus size={16} />添加第一个商品</button>}</div>}
          {products.length > 8 && !normalizedSearch && !focusedProductId && <button type="button" className="product-section-expand" aria-expanded={inventoryExpanded} onClick={() => setInventoryExpanded((value) => !value)}>{inventoryExpanded ? "收起商品列表" : `展开全部 ${products.length} 件商品`}<CaretRight className={inventoryExpanded ? "expanded" : ""} size={15} /></button>}
        </section></details></>}
      </main>

      {activeView === "overview" && <details className="workspace-secondary"><summary>全局经营依据与市场机会</summary><aside className="product-insight-column">
        <section className="product-panel product-rule-engine-card">
          <header><span><small>LOCAL RULE ENGINE</small><h3>决策依据</h3></span><ShieldCheck size={22} weight="duotone" /></header>
          <div className="product-rule-stage"><i><Gauge size={18} /></i><span><small>当前阶段</small><b>{analysisStageLabels[data.traffic_summary.analysis_stage] || data.traffic_summary.analysis_stage}</b></span><em>{confidenceLabels[data.operating_plan.data_quality] || "低置信"}</em></div>
          <ul>
            <li><b>一次一批</b><span>约 ¥5.9～¥6 可包含 3–5 件商品</span></li>
            <li><b>长尾观察</b><span>新记录持续观察到 48h，旧 72h 批次只读保留</span></li>
            <li><b>时段排序</b><span>只用成熟批次比较北京时间 2 小时窗口</span></li>
            <li><b>防止重叠</b><span>同一商品尽量间隔 72 小时</span></li>
            <li><b>真实成本</b><span>确认已完成真实投流后计入唯一批次支出</span></li>
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
      </aside></details>}
    </section>}


    {managementOpen && <div className="product-modal-backdrop product-management-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) { setManagementBulkConfirm(false); setManagementOpen(false); } }}><section ref={managementDialogRef} className={`product-modal product-management-modal ${managementBulkConfirm ? "has-bulk-confirm" : ""}`} role="dialog" aria-modal="true" aria-labelledby="product-management-title">
      <header><span><Package size={20} /></span><div><h3 id="product-management-title">商品管理</h3><p>这里只显示当前正在采集的本人商品。</p></div><button type="button" aria-label="关闭" onClick={() => { setManagementBulkConfirm(false); setManagementOpen(false); }}><X size={18} /></button></header>
      <div className="product-management-summary"><span><Storefront size={18} weight="duotone" /><span><b>我的商品</b><small>当前账号已验证并启用采集</small></span></span><div><strong>{managedProducts.length}</strong><button ref={managementBulkTriggerRef} type="button" disabled={busy || managedProducts.length === 0} onClick={() => { setManagementBulkConfirm(true); window.setTimeout(() => managementBulkConfirmRef.current?.focus(), 0); }}><EyeSlash size={15} />全部移出采集</button></div></div>
      {managementBulkConfirm && <div className="product-management-bulk-confirm" role="alert"><Warning size={20} weight="fill" /><span><b>确认移出全部 {managedProducts.length} 件商品？</b><small>只会停止后续采集，历史快照、曝光记录和项目关系都会保留，之后仍可重新加入。</small></span><div><button type="button" disabled={busy} onClick={() => { setManagementBulkConfirm(false); window.setTimeout(() => managementBulkTriggerRef.current?.focus(), 0); }}>取消</button><button ref={managementBulkConfirmRef} type="button" disabled={busy} onClick={() => void disableAllManagedProducts()}>{busy ? <ArrowClockwise className="spin" size={15} /> : <EyeSlash size={15} />}确认全部移出</button></div></div>}
      <div className="product-management-list">{managedProducts.map((product) => {
        const state = collectionState(product);
        return <article key={product.external_id}>
          <i><Storefront size={19} weight="duotone" /></i>
          <span><small>本人商品 · ID {product.external_id}</small><b>{product.title}</b><em>{product.last_error_detail || `最近采集：${formatDate(product.last_attempt_at)}`}</em></span>
          <div className="product-management-state"><ProductCollectionBadge product={product} /><small>{state.key === "failed" ? formatDate(product.last_attempt_at) : "采集已启用"}</small></div>
          <div className="product-management-actions">
            <button type="button" disabled={busy} title="只读采集此商品" onClick={() => void collectManually(product.external_id)}>{collectingScope === product.external_id ? <ArrowClockwise className="spin" size={15} /> : <ArrowClockwise size={15} />}采集</button>
            <button type="button" disabled={busy} onClick={() => void toggleMonitor(product)}><EyeSlash size={15} />移出采集</button>
          </div>
        </article>;
      })}{managedProducts.length === 0 && <div className="product-management-empty"><CheckCircle size={28} weight="duotone" /><span><b>当前没有正在采集的商品</b><small>添加商品时只会显示当前闲鱼账号中仍在售的本人商品。</small></span></div>}</div>
      <footer><button type="button" onClick={() => { setManagementBulkConfirm(false); setManagementOpen(false); }}>关闭</button><button type="button" className="product-primary-button" onClick={() => { managementShouldRestoreFocusRef.current = false; setManagementBulkConfirm(false); setManagementOpen(false); openRegistration(); }}><Plus size={16} />添加商品</button></footer>
    </section></div>}

    {registerOpen && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy && !registrationLoading) setRegisterOpen(false); }}><form className="product-modal product-registration-modal" onSubmit={register} role="dialog" aria-modal="true" aria-labelledby="product-registration-title">
      <header><span><Plus size={20} /></span><div><h3 id="product-registration-title">添加采集商品</h3><p>优先从当前闲鱼账号的在售商品多选；手机分享内容可作为备用入口。</p></div><button type="button" aria-label="关闭" disabled={busy || registrationLoading} onClick={() => setRegisterOpen(false)}><X size={18} /></button></header>
      <nav className="product-registration-tabs" aria-label="添加商品方式"><button type="button" className={registrationMode === "account" ? "active" : ""} onClick={() => { setRegistrationMode("account"); setRegistrationError(""); if (!registrationPreview || registrationPreview.source !== "account_listing") void discoverRegistrationProducts(); }}><Storefront size={16} />从我的在售商品选择</button><button type="button" className={registrationMode === "share" ? "active" : ""} onClick={() => { setRegistrationMode("share"); setRegistrationPreview(null); setRegistrationSelection([]); setRegistrationError(""); }}><ClipboardText size={16} />粘贴手机分享内容</button></nav>
      {registrationMode === "account" ? <section className="product-registration-account">
        <div className="product-registration-summary"><span><b>当前账号在售商品</b><small>只读获取，不影响每日趋势采集次数</small></span><button type="button" disabled={registrationLoading} onClick={() => void discoverRegistrationProducts()}><ArrowClockwise className={registrationLoading ? "spin" : ""} size={15} />重新读取</button></div>
        {registrationLoading ? <div className="product-registration-loading"><ArrowClockwise className="spin" size={21} />正在读取当前账号的在售商品…</div> : registrationPreview?.source === "account_listing" && registrationPreview.items.length ? <div className="product-registration-list">{registrationPreview.items.map((item) => { const checked = registrationSelection.includes(item.external_id); const blocked = !item.can_register; return <div className="product-registration-row" key={item.external_id}><label className={`${checked ? "selected" : ""} ${blocked ? "registered" : ""}`}><input type="checkbox" checked={checked} disabled={blocked} onChange={() => toggleRegistrationSelection(item.external_id)} /><i><Storefront size={18} weight="duotone" /></i><span><b>{item.title}</b><small>ID {item.external_id} · {item.price === null ? "价格待同步" : moneyExact.format(item.price)}</small></span>{!item.monitoring_enabled && <em>{blocked ? item.blocked_reason : item.already_registered ? checked ? <CheckCircle size={18} weight="fill" /> : "重新加入" : checked ? <CheckCircle size={18} weight="fill" /> : <Plus size={17} />}</em>}</label>{item.monitoring_enabled && <button type="button" disabled={busy || registrationLoading} aria-label={`将${item.title}移出采集`} onClick={() => void removeRegistrationMonitor(item.external_id)}><EyeSlash size={15} />移出采集</button>}</div>; })}</div> : !registrationError && <div className="product-registration-empty"><Package size={26} weight="duotone" /><span><b>当前没有可选择的在售商品</b><small>可切换到“粘贴手机分享内容”识别单件商品。</small></span></div>}
      </section> : <section className="product-registration-share">
        <label><span>手机版闲鱼复制的完整分享内容</span><textarea autoFocus rows={5} value={registerReference} onChange={(event) => { setRegisterReference(event.target.value); setRegistrationPreview(null); setRegistrationSelection([]); setRegistrationError(""); }} placeholder={'可以直接粘贴整段文字，例如：\n「商品标题」复制这段内容打开闲鱼 https://m.tb.cn/…'} /></label>
        <button type="button" className="product-recognize-button" disabled={registrationLoading || !registerReference.trim()} onClick={() => void resolveRegistrationProduct()}>{registrationLoading ? <ArrowClockwise className="spin" size={16} /> : <MagnifyingGlass size={16} />}识别并验证商品</button>
        {registrationPreview?.source === "shared_reference" && registrationPreview.items.map((item) => <article className={`product-registration-result ownership-${item.can_register ? "owned" : "excluded"}`} key={item.external_id}><i><Storefront size={20} weight="duotone" /></i><span><small>{item.can_register ? "已验证为本人在售商品" : item.blocked_reason || "当前商品不能加入采集"}</small><b>{item.title}</b><em>ID {item.external_id} · {item.price === null ? "价格待同步" : moneyExact.format(item.price)}</em></span>{item.can_register ? <CheckCircle size={20} weight="fill" /> : <Warning size={20} weight="fill" />}</article>)}
      </section>}
      {registrationError && <div className="product-registration-error" role="alert"><Warning size={17} weight="fill" /><span>{registrationError}</span></div>}
      {registrationPreview?.warnings.map((warning) => <div className="product-registration-warning" key={warning}><Info size={16} /><span>{warning}</span></div>)}
      <div className="product-modal-note"><ShieldCheck size={17} /><span>系统只读取商品并验证卖家归属与在售状态。只有当前账号本人且仍在售的商品可以加入采集；状态未知时不会放行。不会发布、修改、下架或购买曝光。</span></div>
      <footer><button type="button" disabled={busy || registrationLoading} onClick={() => setRegisterOpen(false)}>取消</button><button className="product-primary-button" disabled={busy || registrationLoading || !registrationPreview || registrationSelection.length === 0}>{busy ? <ArrowClockwise className="spin" size={16} /> : <Plus size={16} />}{registrationMode === "account" ? `加入 ${registrationSelection.length} 件商品` : "加入采集目标"}</button></footer>
    </form></div>}

    {batchDraft && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setBatchDraft(null); }}><form ref={batchDraftDialogRef} className="product-modal product-batch-modal" onSubmit={createBatch} role="dialog" aria-modal="true" aria-labelledby="traffic-batch-dialog-title">
      <header><span><Megaphone size={20} /></span><div><h3 id="traffic-batch-dialog-title">记录刚完成的真实投流</h3><p>只记录已经在闲鱼人工完成的投流；约 ¥5.9～¥6 是整个批次的总费用。</p></div><button ref={batchDraftCloseRef} type="button" aria-label="关闭" onClick={() => setBatchDraft(null)}><X size={18} /></button></header>
      <div className="product-batch-record-time"><Timer size={20} weight="duotone" /><span><small>实际时间锚点</small><b>提交成功时由服务端记录当前北京时间</b><em>不会接受未来时间、计划日期或推荐时段</em></span></div>
      <div className="product-batch-form-grid is-cost-only">
        <label><span>批次实际总费用</span><input type="number" min="0" step="0.1" value={batchDraft.cost} onChange={(event) => setBatchDraft({ ...batchDraft, cost: event.target.value })} /></label>
      </div>
      <fieldset className="traffic-batch-mode-fieldset"><legend>投流后检查点采集</legend><label className={batchDraft.checkpointCollectionMode === "auto" ? "selected" : ""}><input type="radio" name="new-batch-checkpoint-mode" checked={batchDraft.checkpointCollectionMode === "auto"} onChange={() => setBatchDraft({ ...batchDraft, checkpointCollectionMode: "auto" })} /><span><b>投流后自动采集（推荐）</b><small>到 +1h / +6h / +24h / +48h 时各只读采集一次</small></span></label><label className={batchDraft.checkpointCollectionMode === "manual" ? "selected" : ""}><input type="radio" name="new-batch-checkpoint-mode" checked={batchDraft.checkpointCollectionMode === "manual"} onChange={() => setBatchDraft({ ...batchDraft, checkpointCollectionMode: "manual" })} /><span><b>到点提醒，我手动记录</b><small>系统只提醒，不访问商品详情</small></span></label></fieldset>
      <fieldset className="product-batch-picker"><legend>选择商品 <small>建议 3–5 件，已选 {batchDraft.selectedIds.length}/5</small></legend><div>{data.products.filter((product) => product.monitoring_enabled).map((product) => {
        const checked = batchDraft.selectedIds.includes(product.external_id);
        return <label className={checked ? "selected" : ""} key={product.external_id}><input type="checkbox" checked={checked} onChange={() => toggleBatchProduct(product.external_id)} /><i><Storefront size={16} weight="duotone" /></i><span><b>{product.title}</b><small>{product.data_quality === "low" ? "探索数据" : `${confidenceLabels[product.data_quality] || product.data_quality} · ${product.browse_count} 浏览`}</small></span><em>{checked ? <CheckCircle size={17} weight="fill" /> : <Plus size={16} />}</em></label>;
      })}</div></fieldset>
      <label><span>可选备注</span><textarea rows={3} value={batchDraft.note} onChange={(event) => setBatchDraft({ ...batchDraft, note: event.target.value })} placeholder="例如：本批次轮换测试数据库、前端和小程序服务商品" /></label>
      <label className="actual-traffic-confirm"><input type="checkbox" checked={batchDraft.confirmedAlreadyPurchased} onChange={(event) => setBatchDraft({ ...batchDraft, confirmedAlreadyPurchased: event.target.checked })} /><span><b>我确认已经在闲鱼完成这批真实投流</b><small>系统不会代买曝光；确认后先保存真实投流与唯一批次费用，再尝试实时采集整批 T0。</small></span></label>
      <div className="product-modal-note"><ShieldCheck size={17} /><span>整批 T0 全部可靠才开始 48 小时观察；失败则仅保留事实和费用，标记为证据不足，不生成检查点或经营结论，也不会自动重试。</span></div>
      <div className="product-modal-note warning"><Warning size={17} /><span>套餐曝光量只记录批次总数，不会虚构分摊到每件商品；单品效果看后续浏览、想要和咨询变化。</span></div>
      <footer><button type="button" onClick={() => setBatchDraft(null)}>取消</button><button className="product-primary-button" disabled={busy || batchDraft.selectedIds.length === 0 || !batchDraft.confirmedAlreadyPurchased}>{busy ? <ArrowClockwise className="spin" size={16} /> : <CheckCircle size={16} />}确认记录真实投流</button></footer>
    </form></div>}

    {batchStart && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setBatchStart(null); }}><section className="product-modal product-batch-start-modal" role="dialog" aria-modal="true" aria-labelledby="traffic-start-dialog-title">
      <header><span><Play size={20} weight="fill" /></span><div><h3 id="traffic-start-dialog-title">{batchStart.step === "manual" ? "人工填写整批 T0" : batchStart.step === "confirm" ? "确认已投放并开始计时" : "开始曝光批次"}</h3><p>{batchStart.preview.batch.products.length} 件商品 · 计划 {formatTrafficDateTime(batchStart.preview.batch.planned_at)}（北京时间）</p></div><button type="button" aria-label="关闭" onClick={() => setBatchStart(null)}><X size={18} /></button></header>
      {batchStart.preview.blocked_reasons.length > 0 && <div className="product-start-blockers" role="alert"><ShieldWarning size={18} /><span><b>当前还不能开始</b>{batchStart.preview.blocked_reasons.map((reason) => <small key={reason}>{reason}</small>)}</span></div>}
      {batchStart.step === "preview" && <>
        <div className="product-start-steps" aria-label="曝光开始流程"><span className="active"><i>1</i><b>准备整批 T0</b><small>远程刷新或人工填写</small></span><ArrowRight size={16} /><span><i>2</i><b>闲鱼人工投放</b><small>系统不会代买</small></span><ArrowRight size={16} /><span><i>3</i><b>点击开始计时</b><small>服务端写入实际时间</small></span></div>
        <div className={`product-baseline-readiness baseline-${batchStart.preview.baseline_status}`}><Timer size={20} /><span><small>整批 T0 状态</small><b>{batchStart.preview.batch.baseline_status_label}</b><em>{batchStart.preview.batch.baseline_quality_detail}</em></span>{batchStart.preview.baseline_expires_at && <time>有效至 {formatTrafficDateTime(batchStart.preview.baseline_expires_at)}</time>}</div>
        <div className="product-modal-note"><ShieldCheck size={17} /><span>远程刷新会串行只读采集全部商品；不自动重试，首个访问验证会立即熔断。只有全部成功才形成可开始的整批 T0。</span></div>
        <div className="product-modal-note warning"><Warning size={17} /><span>准备 T0 不等于已购买曝光，也不会产生支出。只有你在闲鱼人工购买后点击最终确认，才按服务端当前时间开始并记录唯一批次费用。</span></div>
      </>}
      {batchStart.step === "manual" && <>
        <div className="product-checkpoint-editor product-baseline-editor"><div className="checkpoint-editor-head"><span>商品</span><span>累计浏览</span><span>累计想要</span><span>累计收藏</span><span>累计咨询</span></div>{batchStart.preview.batch.products.map((product) => {
          const row = batchStart.rows[product.external_id];
          return <div className="checkpoint-editor-row" key={product.external_id}><span><b>{product.title}</b><small>不得低于最近已知累计值</small></span>{(["browse_count", "want_count", "collect_count", "inquiry_count"] as const).map((field) => <input key={field} aria-label={`${product.title}人工T0${field}`} type="number" min="0" step="1" value={row[field]} onChange={(event) => setBatchStart({ ...batchStart, rows: { ...batchStart.rows, [product.external_id]: { ...row, [field]: event.target.value } } })} />)}</div>;
        })}</div>
        <div className="product-modal-note warning"><Info size={17} /><span>人工 T0 必须一次填写本批全部商品。保存后 30 分钟内有效，超过后需要重新填写或远程刷新。</span></div>
      </>}
      {batchStart.step === "confirm" && <>
        <div className="product-start-confirm-summary"><span><small>T0 准备时间</small><b>{formatTrafficDateTime(batchStart.preview.batch.baseline_prepared_at)}</b><em>{batchStart.preview.batch.baseline_status_label}</em></span><ArrowRight size={18} /><span><small>实际开始时间</small><b>点击确认时由服务端写入</b><em>不沿用计划时间，也不接受浏览器自填时间</em></span></div>
        <div className="product-modal-note"><Timer size={17} /><span>这是历史计划批次；当前版本仅允许查看，不再支持从计划启动投流。</span></div>
        <div className="product-modal-note warning"><Coins size={17} /><span>确认会创建或更新唯一批次级曝光支出 {moneyExact.format(batchStart.preview.batch.actual_cost)}；不会拆分到单件商品，也不会自动修改或投放商品。</span></div>
      </>}
      <footer>
        <button type="button" disabled={busy} onClick={() => batchStart.step === "preview" ? setBatchStart(null) : setBatchStart({ ...batchStart, step: "preview" })}>{batchStart.step === "preview" ? "取消" : "返回"}</button>
        {batchStart.step === "preview" && <><button type="button" disabled={busy || batchStart.preview.batch.start_blocked} onClick={() => setBatchStart({ ...batchStart, step: "manual" })}>人工填写整批 T0</button><button type="button" className="product-primary-button" disabled={busy || batchStart.preview.batch.start_blocked} onClick={() => void prepareBatchBaseline("remote_refresh")}>{busy ? <ArrowClockwise className="spin" size={16} /> : <ArrowClockwise size={16} />}远程刷新整批 T0</button></>}
        {batchStart.step === "manual" && <button type="button" className="product-primary-button" disabled={busy} onClick={() => void prepareBatchBaseline("manual")}>{busy ? <ArrowClockwise className="spin" size={16} /> : <CheckCircle size={16} />}保存全部 T0</button>}
        {batchStart.step === "confirm" && <button type="button" className="product-primary-button" disabled={busy || !batchStart.preview.can_start} onClick={() => void confirmBatchStart()}>{busy ? <ArrowClockwise className="spin" size={16} /> : <Play size={16} weight="fill" />}已在闲鱼投放，开始计时</button>}
      </footer>
    </section></div>}

    {batchReplan && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setBatchReplan(null); }}><section className="product-modal product-batch-replan-modal" role="dialog" aria-modal="true" aria-labelledby="traffic-replan-dialog-title">
      <header><span><ArrowClockwise size={20} /></span><div><h3 id="traffic-replan-dialog-title">待开始批次重排预览</h3><p>原批次保持不变，只有确认后才替换商品与计划时间。</p></div><button type="button" aria-label="关闭" onClick={() => setBatchReplan(null)}><X size={18} /></button></header>
      <div className="product-replan-time"><Clock size={19} /><span><small>建议新计划时间</small><b>{formatTrafficDateTime(batchReplan.preview.proposed_planned_at)}</b><em>{batchReplan.preview.availability_at ? `冷却可用 ${formatTrafficDateTime(batchReplan.preview.availability_at)}` : "当前没有额外冷却等待"}</em></span><strong>{batchReplan.preview.is_new_spend ? `新付费批次 · 总费用保持 ${moneyExact.format(batchReplan.batchCost)}（增量 ${moneyExact.format(batchReplan.preview.fee_impact)}）` : "继续观察 · 不产生新费用"}</strong></div>
      <div className="product-replan-columns">
        <section><header><small>RETAINED</small><b>保留 {batchReplan.preview.retained_products.length} 件</b></header>{batchReplan.preview.retained_products.length ? batchReplan.preview.retained_products.map((product) => <span key={product.external_id}><CheckCircle size={15} /><b>{product.title}</b><small>{product.reason}</small></span>) : <p>本轮没有足够强正向证据保留上一批商品。</p>}</section>
        <section><header><small>REMOVED</small><b>移出 {batchReplan.preview.removed_products.length} 件</b></header>{batchReplan.preview.removed_products.map((product) => <span key={product.external_id}><X size={15} /><b>{product.title}</b><small>{product.reason}</small></span>)}</section>
        <section><header><small>ADDED</small><b>加入 {batchReplan.preview.added_products.length} 件</b></header>{batchReplan.preview.added_products.map((product) => <span key={product.external_id}><Plus size={15} /><b>{product.title}</b><small>{product.reason}</small></span>)}</section>
      </div>
      <ul className="product-replan-reasons">{batchReplan.preview.reasons.map((reason) => <li key={reason}><Info size={14} />{reason}</li>)}</ul>
      {batchReplan.preview.warnings.map((warning) => <div className="product-modal-note warning" key={warning}><Warning size={17} /><span>{warning}</span></div>)}
      <div className="product-modal-note"><ShieldCheck size={17} /><span>确认后保留原批次 ID、总费用和审计历史；旧的未开始 T0 会清空。系统仍不会购买曝光。</span></div>
      <footer><button type="button" disabled={busy} onClick={() => setBatchReplan(null)}>取消</button><button type="button" className="product-primary-button" disabled={busy || !batchReplan.preview.can_replan || batchReplan.preview.proposed_products.length < 3} onClick={() => void confirmReplan()}>{busy ? <ArrowClockwise className="spin" size={16} /> : <CheckCircle size={16} />}确认按预览重排</button></footer>
    </section></div>}

    {actualOverlap && <div className="product-modal-backdrop product-overlap-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setActualOverlap(null); }}><form ref={actualOverlapDialogRef} className="product-modal product-actual-overlap-modal" onSubmit={confirmActualOverlap} role="dialog" aria-modal="true" aria-labelledby="actual-overlap-title" aria-describedby="actual-overlap-description">
      <header><span><Warning size={20} /></span><div><h3 id="actual-overlap-title">补记已发生的曝光投放</h3><p id="actual-overlap-description">只记录已经在闲鱼真实购买的事实，不用于正常投放建议。</p></div><button ref={actualOverlapCloseRef} type="button" aria-label="关闭" onClick={() => setActualOverlap(null)}><X size={18} /></button></header>
      <div className="actual-overlap-alert"><Warning size={22} weight="duotone" /><span><b>检测到 {actualOverlap.preview.overlap_items.length} 件商品仍在约 72 小时归因窗口内</b><small>{actualOverlap.preview.analysis_impact}</small></span></div>
      <section className="actual-overlap-items" aria-label="受影响的重复商品">
        <header><b>受影响的商品（{actualOverlap.preview.overlap_items.length} 件）</b><span>来源批次（实际开始）</span><span>冷却剩余时间</span></header>
        {actualOverlap.preview.overlap_items.map((item) => <article key={`${item.source_batch_id}-${item.external_id}`}><b>{item.title}</b><span>{formatTrafficDateTime(item.source_started_at)} 的批次</span><em>至 {formatTrafficDateTime(item.cooldown_until)}</em></article>)}
      </section>
      <div className="actual-overlap-impact"><h4>补记后的处理与影响</h4><ul><li><CheckCircle size={15} weight="fill" />批次费用 {moneyExact.format(actualOverlap.preview.batch.actual_cost)} 与实际开始时间会被记录，并只生成一笔批次级支出。</li><li><CheckCircle size={15} weight="fill" />本批次永久标记为“归因重叠”，时段、预算、商品优先级与复投建议均排除。</li><li><CheckCircle size={15} weight="fill" />{actualOverlap.preview.safety_notice}</li></ul></div>
      <div className="actual-overlap-form-grid">
        <div className="actual-overlap-server-time"><Clock size={18} /><span><small>实际投放时间</small><b>点击确认时由服务端记录当前北京时间</b><em>精确到分钟，并作为检查点、冷却和支出的唯一时间锚点</em></span></div>
        <fieldset><legend>T0 可靠性</legend><label><input type="radio" name="overlap-baseline" checked={actualOverlap.baselineMode === "manual"} onChange={() => setActualOverlap({ ...actualOverlap, baselineMode: "manual" })} /><span><b>有完整投放前 T0</b><small>填写全批商品累计值，可继续记录批内事实</small></span></label><label><input type="radio" name="overlap-baseline" checked={actualOverlap.baselineMode === "missing"} onChange={() => setActualOverlap({ ...actualOverlap, baselineMode: "missing" })} /><span><b>没有可靠 T0（推荐）</b><small>保存费用与投放事实后立即终止观察，不再产生检查点提醒</small></span></label></fieldset>
      </div>
      {actualOverlap.baselineMode === "manual" && <div className="product-checkpoint-editor product-baseline-editor actual-overlap-baseline-editor"><div className="checkpoint-editor-head"><span>商品</span><span>累计浏览</span><span>累计想要</span><span>累计收藏</span><span>累计咨询</span></div>{actualOverlap.preview.batch.products.map((product) => { const row = actualOverlap.rows[product.external_id]; return <div className="checkpoint-editor-row" key={product.external_id}><span><b>{product.title}</b><small>必须覆盖整批，且不低于最近已知累计值</small></span>{(["browse_count", "want_count", "collect_count", "inquiry_count"] as const).map((field) => <input key={field} aria-label={`${product.title}重叠补录T0${field}`} type="number" min="0" step="1" value={row[field]} onChange={(event) => setActualOverlap({ ...actualOverlap, rows: { ...actualOverlap.rows, [product.external_id]: { ...row, [field]: event.target.value } } })} />)}</div>; })}</div>}
      <label className="actual-overlap-confirm"><input type="checkbox" checked={actualOverlap.confirmed} onChange={(event) => setActualOverlap({ ...actualOverlap, confirmed: event.target.checked })} /><span><b>我确认这批曝光已经在闲鱼实际购买</b><small>补记后将永久标记为“归因重叠”，无法恢复为正常批次。</small></span></label>
      <footer><button type="button" disabled={busy} onClick={() => setActualOverlap(null)}>返回安全处理</button><button type="button" disabled={busy} onClick={() => { const batch = actualOverlap.preview.batch; setActualOverlap(null); void openReplan(batch); }}>预览重排</button><button className="product-primary-button" disabled={busy || !actualOverlap.confirmed}>{busy ? <ArrowClockwise className="spin" size={16} /> : <CheckCircle size={16} />}确认补记已发生投放</button></footer>
    </form></div>}

    {batchOperation && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setBatchOperation(null); }}><form className="product-modal product-batch-operation-modal" onSubmit={saveBatchOperation} role="dialog" aria-modal="true" aria-labelledby="traffic-operation-dialog-title">
      <header><span>{batchOperation.mode === "complete" ? <CheckCircle size={20} /> : <ClipboardText size={20} />}</span><div><h3 id="traffic-operation-dialog-title">{batchOperation.mode === "complete" ? "记录曝光套餐完成" : `记录 ${checkpointLabels[batchOperation.checkpoint]} 检查点`}</h3><p>{batchOperation.batch.products.length} 件商品 · 批次总费用，不做单品费用分摊</p></div><button type="button" aria-label="关闭" onClick={() => setBatchOperation(null)}><X size={18} /></button></header>
      {batchOperation.mode === "complete" ? <>
        <div className="product-batch-form-grid"><label><span>批次实际总费用</span><input type="number" min="0" step="0.1" value={batchOperation.cost} onChange={(event) => setBatchOperation({ ...batchOperation, cost: event.target.value })} /></label><label><span>套餐总曝光量（可选）</span><input type="number" min="0" step="1" value={batchOperation.totalExposure} onChange={(event) => setBatchOperation({ ...batchOperation, totalExposure: event.target.value })} placeholder="只填批次总数" /></label></div>
        <div className="product-modal-note"><Timer size={17} /><span>即使套餐在 1 小时内完成，也不能立即判定效果结束。系统会继续提醒 24h 和 72h 的浏览、咨询长尾。</span></div>
      </> : <>
        <label><span>本次检查点</span><select value={batchOperation.checkpoint} onChange={(event) => setBatchOperation({ ...batchOperation, checkpoint: event.target.value as BatchOperationState["checkpoint"] })}>{(batchOperation.batch.checkpoint_sequence as BatchOperationState["checkpoint"][]).map((checkpoint) => {
          const state = checkpointOptionState(batchOperation.batch, checkpoint);
          return <option disabled={!state.enabled} value={checkpoint} key={checkpoint}>{checkpointLabels[checkpoint]}（{state.detail}）</option>;
        })}</select></label>
        <div className={`product-modal-note ${checkpointOptionState(batchOperation.batch, batchOperation.checkpoint).enabled ? "" : "warning"}`}>
          {checkpointOptionState(batchOperation.batch, batchOperation.checkpoint).enabled ? <CheckCircle size={17} /> : <Clock size={17} />}
          <span>{checkpointOptionState(batchOperation.batch, batchOperation.checkpoint).detail}</span>
        </div>
        <div className="product-checkpoint-editor"><div className="checkpoint-editor-head"><span>商品</span><span>累计浏览</span><span>累计想要</span><span>累计收藏</span><span>累计咨询</span></div>{batchOperation.batch.products.map((product) => {
          const row = batchOperation.rows[product.external_id];
          return <div className="checkpoint-editor-row" key={product.external_id}><span><b>{product.title}</b><small>T0 浏览 {product.baseline_browse_count} · 咨询 {product.baseline_inquiry_count}</small></span>{(["browse_count", "want_count", "collect_count", "inquiry_count"] as const).map((field) => <input key={field} aria-label={`${product.title}${field}`} type="number" min="0" step="1" value={row[field]} onChange={(event) => setBatchOperation({ ...batchOperation, rows: { ...batchOperation.rows, [product.external_id]: { ...row, [field]: event.target.value } } })} />)}</div>;
        })}</div>
      </>}
      <label><span>可选备注</span><textarea rows={3} value={batchOperation.note} onChange={(event) => setBatchOperation({ ...batchOperation, note: event.target.value })} placeholder="记录当时是否改过商品、回复是否及时或其他外部变化" /></label>
      <div className="product-modal-note warning"><Warning size={17} /><span>1h 数据可以不增长；正式观察结论以该批次的 {batchOperation.batch.observation_window_hours} 小时终点为准，并识别不同协议窗口之间的重叠。</span></div>
      <footer><button type="button" onClick={() => setBatchOperation(null)}>取消</button><button className="product-primary-button" disabled={busy || (batchOperation.mode === "checkpoint" && !checkpointOptionState(batchOperation.batch, batchOperation.checkpoint).enabled)}>{busy ? <ArrowClockwise className="spin" size={16} /> : <CheckCircle size={16} />}{batchOperation.mode === "complete" ? "保存并开始长尾观察" : "保存检查点"}</button></footer>
    </form></div>}

    {actionTarget && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setActionTarget(null); }}><form className="product-modal product-action-modal" onSubmit={saveAction}>
      <header><span><CheckCircle size={20} /></span><div><h3>记录我已执行的商品修改</h3><p>{actionTarget.product.title}</p></div><button type="button" aria-label="关闭" onClick={() => setActionTarget(null)}><X size={18} /></button></header>
      <label><span>人工完成的动作</span><select value={actionType} onChange={(event) => setActionType(event.target.value)}>{Object.entries(actionLabels).filter(([value]) => value !== "traffic").map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label><span>备注</span><textarea rows={4} value={actionNote} onChange={(event) => setActionNote(event.target.value)} placeholder="例如：将标题第一句改为客户常用表达，其他内容不变" /></label>
      <div className="product-modal-note warning"><Warning size={17} /><span>这里不会替你修改、发布或投流，只记录你已经在闲鱼手动完成的动作。</span></div>
      <footer><button type="button" onClick={() => setActionTarget(null)}>取消</button><button className="product-primary-button" disabled={busy}>{busy ? <ArrowClockwise className="spin" size={16} /> : <CheckCircle size={16} />}保存并开始观察</button></footer>
    </form></div>}

    {marketImportOpen && <div className="product-modal-backdrop" role="presentation" onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setMarketImportOpen(false); } }} onMouseDown={(event) => { if (event.target === event.currentTarget) setMarketImportOpen(false); }}><form className="product-modal market-import-modal" onSubmit={importMarketReference} role="dialog" aria-modal="true" aria-labelledby="market-import-title">
      <header><span><UploadSimple size={20} /></span><div><h3 id="market-import-title">导入现有 Ego Lite 搜索参考</h3><p>当前关键词：{data.market_reference.selected_keyword}</p></div><button type="button" aria-label="关闭" onClick={() => setMarketImportOpen(false)}><X size={18} /></button></header>
      <ol className="market-import-steps"><li><i>1</i><span><b>在已登录的 Ego Lite 中搜索</b><small>不要新开第二个闲鱼网站，也不要自动翻页抓取。</small></span></li><li><i>2</i><span><b>让 Codex 整理公开字段</b><small>只保留位置、标题、价格和公开标签。</small></span></li><li><i>3</i><span><b>粘贴 JSON 并确认导入</b><small>有效导入会完成今天的更新并清除提醒。</small></span></li></ol>
      <div className="market-import-schema"><small>接受的结构</small><code>{`{"results":[{"position":1,"title":"公开标题","price":99,"tags":["公开标签"]}]}`}</code></div>
      <label><span>Codex 整理后的 JSON</span><textarea autoFocus rows={10} value={marketImportText} onChange={(event) => setMarketImportText(event.target.value)} placeholder='粘贴包含 results 数组的 JSON；不要包含 Cookie、卖家 ID、商品平台 ID 或 HTML' /></label>
      <label><span>可选说明</span><input value={marketImportNote} onChange={(event) => setMarketImportNote(event.target.value)} maxLength={500} placeholder="例如：Ego Lite 默认排序，未翻页" /></label>
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
