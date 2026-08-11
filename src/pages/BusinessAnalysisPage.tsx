import {
  ArrowClockwise,
  ArrowRight,
  Brain,
  Briefcase,
  CalendarBlank,
  CaretDown,
  CaretRight,
  ChartLineUp,
  CheckCircle,
  CurrencyCircleDollar,
  Database,
  Eye,
  Info,
  Lightning,
  ShieldCheck,
  Sparkle,
  Storefront,
  TrendDown,
  TrendUp,
  UsersThree,
  WarningCircle,
  X,
  type Icon as PhosphorIcon,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import {
  BusinessAnalysisApiError,
  businessAnalysisRequestId,
  businessAnalysisService,
  type BusinessAnalysisDomain,
  type BusinessAnalysisHistoryItem,
  type BusinessAnalysisInsight,
  type BusinessAnalysisOverview,
  type BusinessAnalysisPeriodMetric,
  type BusinessAnalysisModelSettings,
  type BusinessAnalysisProvider,
  type BusinessAnalysisProviderStatus,
  type BusinessAnalysisRecommendation,
  type RecommendationStatus,
} from "../data/businessAnalysisService";
import "./business-analysis.css";

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const integer = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });

const domainLabels: Record<BusinessAnalysisDomain, string> = {
  portfolio: "经营组合",
  products: "商品经营",
  customers: "客户关系",
  projects: "项目交付",
  finance: "收入 / 财务",
  data: "数据基础",
};

const statusLabels: Record<RecommendationStatus, string> = {
  pending: "待处理",
  accepted: "已采纳",
  ignored: "已忽略",
  completed: "已完成",
};

const confidenceLabels = {
  low: "低",
  medium: "中",
  high: "高",
} as const;

const confidenceValues = {
  low: 38,
  medium: 68,
  high: 88,
} as const;

const navigablePages = new Set([
  "客户消息",
  "商品经营",
  "项目管理",
  "收入记录",
  "支出记录",
  "客户管理",
  "数据统计",
  "目标计划",
  "设置中心",
]);

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "经营分析暂时无法读取";
}

function formatAnalysisTime(value: string | null | undefined) {
  if (!value) return "尚未生成";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDate(value: string) {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function historyPeriodLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "快照月份未知";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    timeZone: "Asia/Shanghai",
  }).formatToParts(date);
  const year = parts.find((part) => part.type === "year")?.value;
  const month = parts.find((part) => part.type === "month")?.value;
  return year && month ? `${year} 年 ${month} 月` : "快照月份未知";
}

function observePeriodLabel(value: string) {
  if (value === "current month") return "本月";
  const days = value.match(/\d+/)?.[0];
  return days ? `${days} 天` : value;
}

function periodComparison(metric: BusinessAnalysisPeriodMetric, subject: string) {
  if (metric.change_percent === null) return `${subject}缺少上月可比基线`;
  if (metric.direction === "flat") return `${subject}与上月持平`;
  return `${subject}较上月${metric.direction === "up" ? "增加" : "减少"} ${Math.abs(metric.change_percent).toFixed(1)}%`;
}

function insightForRecommendation(
  recommendation: BusinessAnalysisRecommendation,
  insights: BusinessAnalysisInsight[],
) {
  const recommendationEvidence = new Set(recommendation.evidence_refs);
  return insights.reduce<BusinessAnalysisInsight | null>((best, candidate) => {
    const score = candidate.evidence_refs.filter((reference) => recommendationEvidence.has(reference)).length * 3
      + (candidate.domain === recommendation.domain ? 2 : 0)
      + (["critical", "warning"].includes(candidate.severity) ? 1 : 0);
    if (!best) return candidate;
    const bestScore = best.evidence_refs.filter((reference) => recommendationEvidence.has(reference)).length * 3
      + (best.domain === recommendation.domain ? 2 : 0)
      + (["critical", "warning"].includes(best.severity) ? 1 : 0);
    return score > bestScore ? candidate : best;
  }, null);
}

interface EvidenceSummary {
  primary: string;
  comparison: string;
  detail: string;
}

function evidenceSummary(
  overview: BusinessAnalysisOverview,
  recommendation: BusinessAnalysisRecommendation,
): EvidenceSummary {
  const references = recommendation.evidence_refs.join(" ");
  const { metrics } = overview;
  if (recommendation.domain === "finance") {
    if (references.includes("expenses")) {
      return {
        primary: `本月支出 ${money.format(metrics.finance.expenses.current)}`,
        comparison: periodComparison(metrics.finance.expenses, "支出"),
        detail: `${metrics.finance.expense_count} 笔支出记录`,
      };
    }
    if (references.includes("profit")) {
      return {
        primary: `本月利润 ${money.format(metrics.finance.profit.current)}`,
        comparison: periodComparison(metrics.finance.profit, "利润"),
        detail: `累计利润 ${money.format(metrics.finance.all_time_profit)}`,
      };
    }
    return {
      primary: `本月确认收入 ${money.format(metrics.finance.income.current)}`,
      comparison: periodComparison(metrics.finance.income, "收入"),
      detail: `${metrics.finance.confirmed_payment_count} 笔确认收款`,
    };
  }
  if (recommendation.domain === "projects") {
    return {
      primary: `进行中 ${metrics.projects.active_projects} 个 · 已完成 ${metrics.projects.completed_projects} 个`,
      comparison: metrics.projects.overdue_projects > 0
        ? `${metrics.projects.overdue_projects} 个项目已逾期`
        : "当前没有逾期项目",
      detail: `待回款 ${money.format(metrics.projects.outstanding_receivables)}`,
    };
  }
  if (recommendation.domain === "customers") {
    return {
      primary: `经营客户 ${metrics.customers.total} 个`,
      comparison: `${metrics.customers.stale_or_missing_contact_30d} 个超过 30 天未联系或缺少记录`,
      detail: `近 30 天活跃 ${metrics.customers.active_last_30d} 个`,
    };
  }
  if (recommendation.domain === "products") {
    const exposure = metrics.products.exposure;
    return {
      primary: `本人商品 ${metrics.products.owned_products} 个`,
      comparison: exposure.available
        ? `7 天曝光变化 ${exposure.delta_7d === null ? "暂无可比基线" : `${exposure.delta_7d >= 0 ? "+" : ""}${integer.format(exposure.delta_7d)}`}`
        : "曝光趋势仍缺少可比较快照",
      detail: `快照覆盖 ${metrics.products.snapshot_coverage_percent.toFixed(0)}% · ${metrics.products.snapshot_days} 个样本日`,
    };
  }
  if (recommendation.domain === "data") {
    const available = overview.data_sources.filter((source) => source.available).length;
    return {
      primary: `${available} / ${overview.data_sources.length} 类数据源可用`,
      comparison: `${overview.data_gaps.length} 个数据缺口待补齐`,
      detail: `${overview.future_fields.length} 项已标记为未来扩展字段`,
    };
  }
  return {
    primary: `本月利润 ${money.format(metrics.finance.profit.current)}`,
    comparison: `${metrics.projects.active_projects} 个进行中项目 · ${metrics.customers.total} 个客户`,
    detail: `${metrics.products.owned_products} 个本人商品纳入经营组合`,
  };
}

function MetricCard({
  icon: Icon,
  tone,
  label,
  value,
  secondaryValue,
  secondaryLabel,
  footer,
}: {
  icon: PhosphorIcon;
  tone: "purple" | "green" | "orange" | "blue";
  label: string;
  value: string;
  secondaryValue: string;
  secondaryLabel: string;
  footer: string;
}) {
  return <article className={`analysis-metric-card tone-${tone}`}>
    <header><i><Icon size={22} weight="duotone" /></i><span><b>{label}</b><small>当前经营事实</small></span></header>
    <div><span><strong>{value}</strong><small>{label}</small></span><span><strong>{secondaryValue}</strong><small>{secondaryLabel}</small></span></div>
    <footer>{footer}</footer>
  </article>;
}

function AnalysisStateBadge({ overview }: { overview: BusinessAnalysisOverview }) {
  const label = overview.ai_status === "succeeded"
    ? "AI分析完成"
    : overview.ai_status === "failed"
      ? "规则分析已保留"
      : "实时规则分析";
  return <span className={`analysis-state-badge ai-${overview.ai_status}`}>
    {overview.ai_status === "failed" ? <WarningCircle size={14} /> : <CheckCircle size={14} weight="fill" />}
    {label}
  </span>;
}

function EvidenceDetails({
  overview,
  recommendation,
}: {
  overview: BusinessAnalysisOverview;
  recommendation: BusinessAnalysisRecommendation;
}) {
  const matchingSources = overview.data_sources.filter((source) =>
    recommendation.data_source.some((label) => label === source.label)
    || recommendation.evidence_refs.some((reference) => reference.startsWith(source.id)),
  );
  return <div className="analysis-evidence-details" id={`analysis-evidence-${recommendation.id}`}>
    <div>
      <b><Database size={15} />数据依据</b>
      <ul>{recommendation.data_source.map((source) => <li key={source}>{source}</li>)}</ul>
    </div>
    <div>
      <b><Eye size={15} />指标引用</b>
      <ul className="analysis-evidence-refs">{recommendation.evidence_refs.map((reference) => <li key={reference}>{reference}</li>)}</ul>
    </div>
    <div>
      <b><ShieldCheck size={15} />来源状态</b>
      {matchingSources.length > 0
        ? matchingSources.map((source) => <p key={source.id}><span className={source.available ? "is-ready" : "is-missing"}>{source.available ? "可用" : "缺失"}</span>{source.label} · {source.record_count} 条记录</p>)
        : <p><span className="is-ready">已校验</span>证据引用属于当前分析白名单</p>}
    </div>
    <p className="analysis-manual-note"><Info size={15} weight="fill" />此建议只保存人工反馈，不会自动修改商品、发送消息、变更项目或购买推广。</p>
  </div>;
}

function RecommendationActions({
  recommendation,
  persisted,
  busy,
  onUpdate,
}: {
  recommendation: BusinessAnalysisRecommendation;
  persisted: boolean;
  busy: boolean;
  onUpdate: (status: RecommendationStatus) => void;
}) {
  if (!persisted) return <button className="analysis-action-primary" type="button" disabled title="先生成并保存一次分析">生成后采纳</button>;
  if (recommendation.status === "completed") return <button className="analysis-action-complete" type="button" disabled><CheckCircle size={15} weight="fill" />已完成</button>;
  if (recommendation.status === "accepted") return <>
    <button className="analysis-action-primary" type="button" disabled={busy} onClick={() => onUpdate("completed")}><CheckCircle size={15} />标记完成</button>
    <button className="analysis-action-secondary" type="button" disabled={busy} onClick={() => onUpdate("ignored")}><X size={15} />忽略</button>
  </>;
  if (recommendation.status === "ignored") return <button className="analysis-action-primary" type="button" disabled={busy} onClick={() => onUpdate("accepted")}><CheckCircle size={15} />重新采纳</button>;
  return <>
    <button className="analysis-action-primary" type="button" disabled={busy} onClick={() => onUpdate("accepted")}><CheckCircle size={15} />采纳</button>
    <button className="analysis-action-secondary" type="button" disabled={busy} onClick={() => onUpdate("ignored")}><X size={15} />忽略</button>
  </>;
}

function HistoryStatus({ item, currentId }: { item: BusinessAnalysisHistoryItem; currentId: string | null }) {
  if (item.id === currentId) return <span className="history-current"><CheckCircle size={13} weight="fill" />当前查看</span>;
  if (item.pending_recommendation_count > 0) return <span className="history-pending">{item.pending_recommendation_count} 项待处理</span>;
  return <span className="history-finished">反馈已处理</span>;
}

export function BusinessAnalysisPage({ onNavigate }: { onNavigate: (page: string) => void }) {
  const [analysis, setAnalysis] = useState<BusinessAnalysisOverview | null>(null);
  const [history, setHistory] = useState<BusinessAnalysisHistoryItem[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadVersion, setReloadVersion] = useState(0);
  const [running, setRunning] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [historyLoadingId, setHistoryLoadingId] = useState<string | null>(null);
  const [viewingHistory, setViewingHistory] = useState(false);
  const [domainFilter, setDomainFilter] = useState<"all" | BusinessAnalysisDomain>("all");
  const [showAll, setShowAll] = useState(false);
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ message: string; tone: "success" | "error" } | null>(null);
  const [providers, setProviders] = useState<BusinessAnalysisProviderStatus[]>([]);
  const [modelSettings, setModelSettings] = useState<BusinessAnalysisModelSettings | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<BusinessAnalysisProvider>("codex_cli");
  const [selectedModel, setSelectedModel] = useState("");
  const [modelLoading, setModelLoading] = useState(true);
  const [modelError, setModelError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void Promise.all([businessAnalysisService.latest(), businessAnalysisService.history(20, 0)])
      .then(([overview, records]) => {
        if (!active) return;
        setAnalysis(overview);
        setHistory(records.items);
        setHistoryTotal(records.total);
        setViewingHistory(false);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setAnalysis(null);
        setError(errorMessage(reason));
        setLoading(false);
      });
    return () => { active = false; };
  }, [reloadVersion]);

  useEffect(() => {
    let active = true;
    setModelLoading(true);
    setModelError("");
    void Promise.all([businessAnalysisService.providers(), businessAnalysisService.models()])
      .then(([providerRows, settings]) => {
        if (!active) return;
        setProviders(providerRows);
        setModelSettings(settings);
        setSelectedProvider("codex_cli");
        setSelectedModel(settings.selected_model || settings.models[0]?.model || "");
        setModelLoading(false);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setModelError(errorMessage(reason));
        setModelLoading(false);
      });
    return () => { active = false; };
  }, [reloadVersion]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 3200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const recommendations = useMemo(() => {
    if (!analysis) return [];
    return domainFilter === "all"
      ? analysis.recommendations
      : analysis.recommendations.filter((recommendation) => recommendation.domain === domainFilter);
  }, [analysis, domainFilter]);

  const visibleRecommendations = showAll ? recommendations : recommendations.slice(0, 3);

  const activeProvider = providers.find((item) => item.provider === selectedProvider) || null;
  const deepseekModel = providers.find((item) => item.provider === "deepseek")?.lead_model
    || providers.find((item) => item.provider === "deepseek")?.model
    || "";
  const modelOptions = selectedProvider === "codex_cli"
    ? modelSettings?.models || []
    : deepseekModel
      ? [{ model: deepseekModel, display_name: deepseekModel, default_reasoning_effort: null, supported_reasoning_efforts: [] }]
      : [];
  const selectedModelOption = modelOptions.find((item) => item.model === selectedModel) || modelOptions[0] || null;
  const selectedReasoningEffort = selectedProvider === "codex_cli"
    ? selectedModelOption?.default_reasoning_effort || null
    : null;
  const selectionReady = Boolean(
    selectedModel
    && activeProvider?.configured
    && activeProvider.status !== "error"
    && activeProvider.status !== "not_installed"
    && activeProvider.status !== "login_required",
  );

  const chooseProvider = (provider: BusinessAnalysisProvider) => {
    setSelectedProvider(provider);
    if (provider === "codex_cli") {
      setSelectedModel(modelSettings?.selected_model || modelSettings?.models[0]?.model || "");
    } else {
      setSelectedModel(deepseekModel);
    }
  };

  const generateAnalysis = async () => {
    setRunning(true);
    setNotice(null);
    try {
      if (!selectionReady) {
        throw new Error(modelError || "所选分析模型当前不可用，请检查连接状态");
      }
      const result = await businessAnalysisService.run(
        businessAnalysisRequestId("analysis-run"),
        {
          provider: selectedProvider,
          model: selectedModel,
          reasoningEffort: selectedReasoningEffort,
        },
      );
      const records = await businessAnalysisService.history(20, 0);
      setAnalysis(result);
      setHistory(records.items);
      setHistoryTotal(records.total);
      setViewingHistory(false);
      setExpandedEvidence(null);
      setShowAll(false);
      setNotice({
        message: result.ai_status === "failed"
          ? `${selectedProvider === "codex_cli" ? "GPT" : "DeepSeek"} 未完成推理，系统已保存有证据的规则分析，没有切换其他模型。`
          : "新的经营分析已生成，建议仍需你人工决定。",
        tone: result.ai_status === "failed" ? "error" : "success",
      });
    } catch (reason: unknown) {
      setNotice({ message: errorMessage(reason), tone: "error" });
    } finally {
      setRunning(false);
    }
  };

  const openHistory = async (analysisId: string) => {
    if (analysisId === analysis?.analysis_id) return;
    setHistoryLoadingId(analysisId);
    setNotice(null);
    try {
      setAnalysis(await businessAnalysisService.historyDetail(analysisId));
      setViewingHistory(true);
      setExpandedEvidence(null);
      setShowAll(false);
      window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    } catch (reason: unknown) {
      setNotice({ message: errorMessage(reason), tone: "error" });
    } finally {
      setHistoryLoadingId(null);
    }
  };

  const returnToLatest = async () => {
    setHistoryLoadingId("latest");
    try {
      setAnalysis(await businessAnalysisService.latest());
      setViewingHistory(false);
      setExpandedEvidence(null);
    } catch (reason: unknown) {
      setNotice({ message: errorMessage(reason), tone: "error" });
    } finally {
      setHistoryLoadingId(null);
    }
  };

  const updateRecommendation = async (
    recommendation: BusinessAnalysisRecommendation,
    status: RecommendationStatus,
  ) => {
    if (!analysis?.analysis_id) return;
    setUpdatingId(recommendation.id);
    setNotice(null);
    try {
      const updated = await businessAnalysisService.updateRecommendation(recommendation.id, {
        status,
        expected_version: recommendation.version,
        request_id: businessAnalysisRequestId("recommendation-update"),
      });
      setAnalysis({
        ...analysis,
        recommendations: analysis.recommendations.map((item) => item.id === updated.id ? updated : item),
      });
      setHistory((items) => items.map((item) => item.id === analysis.analysis_id
        ? {
            ...item,
            pending_recommendation_count: item.pending_recommendation_count
              + (recommendation.status === "pending" && status !== "pending" ? -1 : 0)
              + (recommendation.status !== "pending" && status === "pending" ? 1 : 0),
          }
        : item));
      setNotice({ message: `建议已更新为“${statusLabels[updated.status]}”，不会自动执行任何业务操作。`, tone: "success" });
    } catch (reason: unknown) {
      if (reason instanceof BusinessAnalysisApiError && reason.status === 409 && analysis.analysis_id) {
        try {
          setAnalysis(await businessAnalysisService.historyDetail(analysis.analysis_id));
        } catch {
          // Preserve the visible snapshot if conflict refresh also fails.
        }
      }
      setNotice({ message: errorMessage(reason), tone: "error" });
    } finally {
      setUpdatingId(null);
    }
  };

  if (loading) return <div className="business-analysis-state" role="status">
    <ArrowClockwise className="analysis-spin" size={34} />
    <h2>正在建立经营事实基线</h2>
    <p>读取商品、客户、项目和收支数据，不会调用模型或写入业务记录。</p>
  </div>;

  if (error || !analysis) return <div className="business-analysis-state is-error">
    <WarningCircle size={38} weight="duotone" />
    <h2>暂时无法读取经营分析</h2>
    <p>{error || "经营分析服务暂时不可用"}</p>
    <button type="button" onClick={() => setReloadVersion((value) => value + 1)}><ArrowClockwise size={16} />重新连接</button>
  </div>;

  const { metrics } = analysis;
  const metricCards = [
    {
      icon: CurrencyCircleDollar,
      tone: "purple" as const,
      label: "本月确认收入",
      value: money.format(metrics.finance.income.current),
      secondaryValue: money.format(metrics.finance.expenses.current),
      secondaryLabel: "本月支出",
      footer: `本月利润 ${money.format(metrics.finance.profit.current)}`,
    },
    {
      icon: Briefcase,
      tone: "green" as const,
      label: "进行中项目",
      value: `${metrics.projects.active_projects}`,
      secondaryValue: `${metrics.projects.completed_projects}`,
      secondaryLabel: "已完成项目",
      footer: `项目总数 ${metrics.projects.total} · 待回款 ${money.format(metrics.projects.outstanding_receivables)}`,
    },
    {
      icon: UsersThree,
      tone: "orange" as const,
      label: "经营客户",
      value: `${metrics.customers.total}`,
      secondaryValue: `${metrics.customers.stale_or_missing_contact_30d}`,
      secondaryLabel: "待关注客户",
      footer: `近 30 天活跃 ${metrics.customers.active_last_30d} 个`,
    },
    {
      icon: Storefront,
      tone: "blue" as const,
      label: "本人商品",
      value: `${metrics.products.owned_products}`,
      secondaryValue: `${metrics.products.active_products}`,
      secondaryLabel: "活跃商品",
      footer: `已监测 ${metrics.products.monitored_products} 个 · 快照覆盖 ${metrics.products.snapshot_coverage_percent.toFixed(0)}%`,
    },
  ];

  return <div className="business-analysis-page">
    <section className="analysis-command-bar">
      <div className="analysis-command-copy">
        <span><ChartLineUp size={18} weight="duotone" />主动经营分析</span>
        <p>{analysis.summary}</p>
      </div>
      <div className="analysis-command-actions">
        <p>分析快照：<b>{formatAnalysisTime(analysis.snapshot_time || analysis.generated_at)}</b>{analysis.provider && <span className="analysis-used-model">{analysis.provider === "codex_cli" ? "GPT" : "DeepSeek"} · {analysis.model || "模型未知"}</span>}<AnalysisStateBadge overview={analysis} /></p>
        <div>
          {viewingHistory && <button className="analysis-return-latest" type="button" disabled={historyLoadingId === "latest"} onClick={() => void returnToLatest()}><ArrowClockwise size={15} />返回最新分析</button>}
          <button className="analysis-run-button" type="button" disabled={running || modelLoading || !selectionReady} onClick={() => void generateAnalysis()}>
            {running ? <><ArrowClockwise className="analysis-spin" size={17} />正在分析</> : <><Sparkle size={17} weight="fill" />使用{selectedProvider === "codex_cli" ? " GPT" : " DeepSeek"}生成</>}
          </button>
        </div>
      </div>
    </section>

    {(analysis.is_stale || analysis.ai_status === "failed") && <aside className={`analysis-alert ${analysis.ai_status === "failed" ? "is-ai-fallback" : "is-stale"}`} role="status">
      <WarningCircle size={19} weight="fill" />
      <span><b>{analysis.ai_status === "failed" ? "所选模型未完成推理，规则结果已保留" : "经营事实已经变化"}</b><small>{analysis.ai_status === "failed" ? `${analysis.ai_error?.message || "所选模型暂时不可用"}；页面保留确定性规则分析，没有切换其他模型。` : "当前记录仍可追溯，但建议重新生成分析后再作决定。"}</small></span>
    </aside>}

    <section className="analysis-overview-layout">
      <div className="analysis-metrics-grid" aria-label="经营概览">
        {metricCards.map((card) => <MetricCard key={card.label} {...card} />)}
      </div>
      <aside className="analysis-model-panel" aria-label="分析模型选择">
        <header><div><span>MODEL SELECTION</span><h2>选择分析模型</h2></div><small className={selectionReady ? "is-ready" : "is-attention"}>{modelLoading ? "读取中" : selectionReady ? "已连接" : "需检查"}</small></header>
        <div className="analysis-provider-options">
          {(["codex_cli", "deepseek"] as BusinessAnalysisProvider[]).map((provider) => {
            const status = providers.find((item) => item.provider === provider);
            const active = selectedProvider === provider;
            return <button type="button" aria-pressed={active} disabled={modelLoading || !status?.configured} onClick={() => chooseProvider(provider)} key={provider}>
              <i>{provider === "codex_cli" ? <Brain size={19} weight="duotone" /> : <Lightning size={19} weight="duotone" />}</i>
              <span><b>{provider === "codex_cli" ? "GPT 深度分析" : "DeepSeek 快速"}</b><small>{provider === "codex_cli" ? "适合复杂证据链，默认选择" : "适合快速重跑，不会自动接管失败任务"}</small></span>
              <em className={status?.configured ? "is-ready" : "is-attention"}>{provider === "codex_cli" ? "推荐" : status?.configured ? "已配置" : "未配置"}</em>
            </button>;
          })}
        </div>
        <label className="analysis-model-field"><span>具体模型</span><select aria-label="经营分析具体模型" value={selectedModel} disabled={modelLoading || modelOptions.length === 0} onChange={(event) => setSelectedModel(event.target.value)}>{modelOptions.map((option) => <option value={option.model} key={option.model}>{option.model}{option.model === modelSettings?.selected_model || option.model === deepseekModel ? " · 当前配置" : ""}</option>)}</select></label>
        <p className="analysis-model-policy"><ShieldCheck size={16} weight="fill" />实际 provider 与 model 会写入历史；失败直接显示，只保留规则结果，不切换模型。</p>
        {modelError && <p className="analysis-model-error"><WarningCircle size={15} />{modelError}</p>}
        <button className="analysis-model-run" type="button" disabled={running || modelLoading || !selectionReady} onClick={() => void generateAnalysis()}>{running ? <><ArrowClockwise className="analysis-spin" size={16} />正在分析</> : <><Sparkle size={16} weight="fill" />使用 {selectedProvider === "codex_cli" ? "GPT" : "DeepSeek"} · {selectedModel || "未选择"} 生成</>}</button>
      </aside>
    </section>

    <section className="analysis-chain-shell">
      <header className="analysis-chain-heading">
        <div><h2>证据链分析</h2><p>业务指标 → AI发现 → 行动建议；所有建议都必须能回到真实数据来源。</p></div>
        <div>
          <label><span className="sr-only">筛选经营领域</span><select value={domainFilter} onChange={(event) => { setDomainFilter(event.target.value as "all" | BusinessAnalysisDomain); setShowAll(false); }}><option value="all">全部领域</option>{(Object.entries(domainLabels) as Array<[BusinessAnalysisDomain, string]>).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select><CaretDown size={14} aria-hidden="true" /></label>
          <span className="analysis-period"><CalendarBlank size={15} />{formatDate(analysis.period.current_month_start)} – {formatDate(analysis.period.current_month_end)}</span>
        </div>
      </header>

      <div className="analysis-chain-labels" aria-hidden="true">
        <span>业务指标 / 证据来源<small>客观数据与事实</small></span><i /><span>AI发现（问题与原因）<small>基于证据链的判断</small></span><i /><span>行动建议（人工决策）<small>由你选择是否采纳</small></span>
      </div>

      {visibleRecommendations.length > 0 ? <div className="analysis-chain-list">
        {visibleRecommendations.map((recommendation) => {
          const evidence = evidenceSummary(analysis, recommendation);
          const insight = insightForRecommendation(recommendation, analysis.insights);
          const evidenceOpen = expandedEvidence === recommendation.id;
          return <article className={`analysis-chain-row priority-${recommendation.priority}`} key={recommendation.id}>
            <div className="analysis-chain-evidence">
              <em>{domainLabels[recommendation.domain]}</em>
              <h3>{evidence.primary}</h3>
              <p>{evidence.comparison}</p>
              <div><Database size={17} weight="duotone" /><span><small>证据来源</small><b>{recommendation.data_source.join("、") || "经营事实指标"}</b><small>{evidence.detail}</small></span></div>
            </div>
            <ArrowRight className="analysis-chain-arrow" size={24} aria-hidden="true" />
            <div className="analysis-chain-insight">
              <em className={`severity-${insight?.severity || "info"}`}>发现</em>
              <h3>{insight?.title || recommendation.problem}</h3>
              <small>原因</small>
              <p>{insight?.reason || recommendation.reason}</p>
              <div className="analysis-confidence"><span><small>置信度</small><i><b style={{ width: `${confidenceValues[recommendation.confidence]}%` }} /></i><strong>{confidenceLabels[recommendation.confidence]}</strong></span><span><small>观察周期</small><b>{observePeriodLabel(recommendation.observe_period)}</b></span></div>
            </div>
            <ArrowRight className="analysis-chain-arrow" size={24} aria-hidden="true" />
            <div className="analysis-chain-action">
              <em>建议</em>
              <h3>{recommendation.title}</h3>
              <small>建议动作</small>
              <p>{recommendation.action}</p>
              <div className="analysis-action-footer">
                <span className={`analysis-recommendation-status status-${recommendation.status}`}><i />{statusLabels[recommendation.status]}</span>
                <div><RecommendationActions recommendation={recommendation} persisted={analysis.record_status === "completed"} busy={updatingId === recommendation.id} onUpdate={(status) => void updateRecommendation(recommendation, status)} /></div>
              </div>
              <div className="analysis-action-links">
                <button type="button" aria-expanded={evidenceOpen} aria-controls={`analysis-evidence-${recommendation.id}`} onClick={() => setExpandedEvidence(evidenceOpen ? null : recommendation.id)}><Eye size={14} />{evidenceOpen ? "收起依据" : "查看依据"}</button>
                {recommendation.status === "accepted" && navigablePages.has(recommendation.target_page) && <button type="button" onClick={() => onNavigate(recommendation.target_page)}>前往人工处理 <CaretRight size={13} /></button>}
              </div>
            </div>
            {evidenceOpen && <EvidenceDetails overview={analysis} recommendation={recommendation} />}
          </article>;
        })}
      </div> : <div className="analysis-empty-recommendations">
        <CheckCircle size={36} weight="duotone" />
        <h3>{domainFilter === "all" ? "当前没有无依据的建议" : `${domainLabels[domainFilter]}暂无可验证建议`}</h3>
        <p>系统不会为了显得智能而补入没有业务证据的行动。</p>
      </div>}

      {recommendations.length > 3 && <button className="analysis-show-all" type="button" onClick={() => setShowAll((value) => !value)}>{showAll ? "收起次要建议" : `展开其余 ${recommendations.length - 3} 条建议`}<CaretDown className={showAll ? "is-open" : ""} size={15} /></button>}
    </section>

    <section className="analysis-history-shell">
      <header><div><h2>历史分析记录</h2><p>保存每次分析快照与建议反馈，不把建议直接沉淀为永久规则。</p></div><span>共 {historyTotal} 次</span></header>
      {history.length > 0 ? <div className="analysis-history-table-wrap"><table>
        <thead><tr><th>分析时间</th><th>观察周期</th><th>规则校验</th><th>AI分析状态</th><th>问题数</th><th>建议数</th><th>状态</th><th aria-label="操作" /></tr></thead>
        <tbody>{history.slice(0, 8).map((item) => <tr key={item.id} className={item.id === analysis.analysis_id ? "is-active" : ""}>
          <td data-label="分析时间">{formatAnalysisTime(item.snapshot_time)}</td>
          <td data-label="观察周期">{historyPeriodLabel(item.snapshot_time)}</td>
          <td data-label="规则校验"><span className="history-rule-ok"><CheckCircle size={13} weight="fill" />通过</span></td>
          <td data-label="AI分析状态"><span className={`history-ai ai-${item.ai_status}`}>{item.ai_status === "succeeded" ? "完成" : item.ai_status === "failed" ? "规则保留" : "未请求"}</span>{item.provider && <small className="history-model-used">{item.provider === "codex_cli" ? "GPT" : "DeepSeek"} · {item.model || "模型未知"}</small>}</td>
          <td data-label="问题数">{item.insight_count}</td>
          <td data-label="建议数">{item.recommendation_count}</td>
          <td data-label="状态"><HistoryStatus item={item} currentId={analysis.analysis_id} /></td>
          <td><button type="button" disabled={historyLoadingId === item.id || item.id === analysis.analysis_id} onClick={() => void openHistory(item.id)}>{historyLoadingId === item.id ? "读取中" : item.id === analysis.analysis_id ? "正在查看" : "查看详情"}<CaretRight size={13} /></button></td>
        </tr>)}</tbody>
      </table></div> : <div className="analysis-history-empty"><Database size={30} weight="duotone" /><span><b>还没有历史分析</b><small>点击“生成新分析”后，规则结果与 AI 状态会一起保存。</small></span></div>}
    </section>

    <aside className="analysis-safety-boundary"><ShieldCheck size={18} weight="fill" /><span><b>人工执行边界</b><small>AI只分析、解释和排序建议；不会自动修改商品、发布内容、发送客户消息、变更项目或购买推广。</small></span></aside>

    {notice && <div className={`analysis-toast is-${notice.tone}`} role="status">{notice.tone === "success" ? <CheckCircle size={18} weight="fill" /> : <WarningCircle size={18} weight="fill" />}{notice.message}</div>}
  </div>;
}
