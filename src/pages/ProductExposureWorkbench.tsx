import {
  ChartLineUp,
  ChatCircleDots,
  ClipboardText,
  Clock,
  Coins,
  Eye,
  Flask,
  Gauge,
  ShieldCheck,
  ShieldWarning,
  Timer,
  TrendUp,
} from "@phosphor-icons/react";
import { useState } from "react";
import type { ProductIntelligenceView } from "../data/localPlatformService";
import { formatTrafficDateTime } from "../utils/trafficDateTime";
import "./product-exposure-workbench.css";


const integer = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
const moneyExact = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});
const confidenceLabels: Record<string, string> = {
  high: "高置信",
  medium: "中等置信",
  low: "低置信",
};
const checkpointLabels: Record<string, string> = {
  h1: "+1 小时",
  h6: "+6 小时",
  h24: "+24 小时",
  h48: "+48 小时",
  h72: "+72 小时",
};

function signedInteger(value: number) {
  return `${value > 0 ? "+" : ""}${integer.format(value)}`;
}

export function ExposureAnalytics({ data }: { data: ProductIntelligenceView }) {
  const analytics = data.exposure_analytics;
  const [expanded, setExpanded] = useState(false);
  const maxCheckpointBrowse = Math.max(
    1,
    ...analytics.checkpoints.map((checkpoint) => checkpoint.average_browse_delta),
  );
  const recent = data.traffic_batches
    .filter((batch) => batch.started_at)
    .slice(0, 3);
  const hasObservedData = analytics.eligible_batch_count > 0;
  const invalidatedBatchCount = data.traffic_batches.filter((batch) => batch.status === "invalidated").length;
  const exploratoryBatches = data.traffic_batches.filter((batch) => batch.exploratory_available);
  const compactNextStep = data.traffic_summary.observation_batch_count > 0
    ? "按实际开始时间完成当前观察"
    : invalidatedBatchCount > 0
      ? "下次投放前准备可靠 T0"
      : "建立带可靠 T0 的新批次";
  const compactNextStepDetail = invalidatedBatchCount > 0
    ? "已终止批次无需继续补录"
    : "不使用旧快照作为投放基线";
  const recordedButExcludedCheckpoints = new Set(
    recent
      .filter((batch) => !batch.analysis_eligible)
      .flatMap((batch) => batch.completed_checkpoints),
  );

  if (!hasObservedData) {
    return <section className="product-exposure-analytics is-compact" aria-labelledby="exposure-analytics-title">
      <header className="product-exposure-head">
        <div><span className="product-eyebrow"><ChartLineUp size={14} weight="fill" /> EXPOSURE PERFORMANCE</span><h3 id="exposure-analytics-title">曝光效果分析</h3></div>
        <span className={`confidence-${analytics.confidence}`}><ShieldCheck size={14} weight="fill" />{confidenceLabels[analytics.confidence] || "低置信"} · 近 {analytics.window_days} 天</span>
      </header>
      <div className="product-exposure-compact-status">
        <span><i><Clock size={18} /></i><small>成熟有效批次（≥+24h）</small><b>{analytics.eligible_batch_count}</b><em>暂无可用</em></span>
        <span><i><Flask size={18} /></i><small>可做探索分析</small><b>{exploratoryBatches.length}</b><em>展示实测变化 · 不作因果归因</em></span>
        <span><i><ShieldWarning size={18} /></i><small>决策级已排除</small><b>{analytics.excluded_batch_count}</b><em>不进入预算 / 时段 / 复投</em></span>
        <span><i><ClipboardText size={18} /></i><small>下一步建议</small><b>{compactNextStep}</b><em>{compactNextStepDetail}</em></span>
      </div>
      {exploratoryBatches.length > 0 && <div className="product-exposure-exploratory-summary"><Flask size={18} weight="duotone" /><span><b>仍有真实分析数据</b><small>{exploratoryBatches.map((batch) => `${formatTrafficDateTime(batch.started_at)}：浏览 ${signedInteger(batch.observed_browse_change)}、咨询 ${signedInteger(batch.observed_inquiry_change)}`).join("；")}。展开下方批次可查看真实曲线、自然增长范围和失效条件。</small></span></div>}
    </section>;
  }

  return <section className={`product-exposure-analytics ${expanded ? "is-expanded" : ""}`} aria-labelledby="exposure-analytics-title">
    <header className="product-exposure-head">
      <div>
        <span className="product-eyebrow"><ChartLineUp size={14} weight="fill" /> EXPOSURE PERFORMANCE</span>
        <h3 id="exposure-analytics-title">曝光效果分析</h3>
        <p>{analytics.summary}</p>
      </div>
      <span className="product-exposure-head-actions"><em className={`confidence-${analytics.confidence}`}><ShieldCheck size={14} weight="fill" />{confidenceLabels[analytics.confidence] || "低置信"} · 近 {analytics.window_days} 天</em><button type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? "收起成熟分析" : "展开成熟分析"}</button></span>
    </header>

    {expanded && <><div className="product-exposure-kpis">
      <article><i><Coins size={18} weight="duotone" /></i><span><small>累计真实投入</small><b>{moneyExact.format(analytics.total_spent)}</b><em>开始批次后自动进入支出</em></span></article>
      <article><i><Eye size={18} weight="duotone" /></i><span><small>成熟浏览增量</small><b>+{integer.format(analytics.browse_delta)}</b><em>平均每批 +{integer.format(analytics.average_browse_delta)}</em></span></article>
      <article><i><ChatCircleDots size={18} weight="duotone" /></i><span><small>成熟咨询增量</small><b>+{integer.format(analytics.inquiry_delta)}</b><em>平均每批 +{analytics.average_inquiry_delta}</em></span></article>
      <article><i><TrendUp size={18} weight="duotone" /></i><span><small>浏览 → 咨询</small><b>{analytics.inquiry_conversion_rate === null ? "—" : `${analytics.inquiry_conversion_rate}%`}</b><em>仅统计可比较成熟批次</em></span></article>
      <article><i><Gauge size={18} weight="duotone" /></i><span><small>每新增咨询成本</small><b>{analytics.cost_per_inquiry === null ? "—" : moneyExact.format(analytics.cost_per_inquiry)}</b><em>{analytics.cost_per_browse === null ? "暂无浏览成本" : `每浏览 ${moneyExact.format(analytics.cost_per_browse)}`}</em></span></article>
      <article><i><Clock size={18} weight="duotone" /></i><span><small>当前优先时段</small><b>{analytics.best_time_bucket || "样本不足"}</b><em>{analytics.eligible_batch_count} 批纳入 · {analytics.excluded_batch_count} 批排除</em></span></article>
    </div>

    <div className="product-exposure-body">
      <section className="exposure-checkpoint-card" aria-labelledby="checkpoint-growth-title">
        <header><span><small>LONG-TAIL GROWTH</small><h4 id="checkpoint-growth-title">套餐结束后的增长轨迹</h4></span><em>不同检查点按各自有效批次数求平均</em></header>
        <div className="exposure-checkpoint-list">
          {(["h1", "h6", "h24", "h72"] as const).map((checkpointName) => {
            const checkpoint = analytics.checkpoints.find((value) => value.checkpoint === checkpointName);
            const width = checkpoint ? Math.max(5, checkpoint.average_browse_delta / maxCheckpointBrowse * 100) : 0;
            return <article className={checkpointName === "h24" || checkpointName === "h72" ? "mature" : ""} key={checkpointName}>
              <span><b>{checkpointLabels[checkpointName]}</b><small>{checkpoint
                ? `${checkpoint.batch_count} 个有效数据点`
                : recordedButExcludedCheckpoints.has(checkpointName)
                  ? "已有记录 · 因 T0 或归因质量未纳入"
                  : "等待记录"}</small></span>
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
    </div></>}

  </section>;
}
