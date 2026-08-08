import {
  ArrowClockwise,
  BellRinging,
  CalendarCheck,
  CaretRight,
  ChartLineUp,
  CheckCircle,
  Clock,
  Eye,
  EyeSlash,
  Gauge,
  Lightbulb,
  MagnifyingGlass,
  Megaphone,
  Package,
  PauseCircle,
  Plus,
  ShieldCheck,
  Sparkle,
  Storefront,
  Target,
  TrendUp,
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
  type ProductRecommendationView,
  type ProductView,
} from "../data/localPlatformService";
import "./product-intelligence.css";


const integer = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
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
  return formatter.format(new Date(value)) === formatter.format(new Date());
}

function collectionState(product: ProductView) {
  if (product.ownership_status === "excluded") return { key: "excluded", label: "已排除" };
  if (product.ownership_status === "pending") return { key: "pending", label: "等待验证" };
  if (product.last_collection_status === "failed") return { key: "failed", label: isTodayInBeijing(product.last_attempt_at) ? "今日失败" : "最近失败" };
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
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : dateTime.format(parsed);
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
      <span><b>等待第二个数据点</b><small>每日一次采集后，这里会展示真实趋势。</small></span>
    </div>;
  }
  return <div className="product-trend-chart" aria-label={`${product.title}浏览趋势`}>
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
        <Tooltip formatter={(value) => [`${value} 次`, "累计浏览"]} />
        <Area type="monotone" dataKey="browse_count" stroke="#6544f4" strokeWidth={2.5} fill="url(#productBrowseArea)" />
      </AreaChart>
    </ResponsiveContainer>
  </div>;
}

export function ProductIntelligencePage({ globalSearch = "" }: { globalSearch?: string }) {
  const [data, setData] = useState<ProductIntelligenceView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [managementOpen, setManagementOpen] = useState(false);
  const [managementTab, setManagementTab] = useState<"owned" | "pending" | "excluded">("owned");
  const [registerReference, setRegisterReference] = useState("");
  const [actionTarget, setActionTarget] = useState<{ product: ProductView; recommendation: ProductRecommendationView | null } | null>(null);
  const [actionType, setActionType] = useState("title");
  const [actionNote, setActionNote] = useState("");
  const [actionCost, setActionCost] = useState("");
  const [toast, setToast] = useState("");

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

  const normalizedSearch = globalSearch.trim().toLowerCase();
  const products = useMemo(() => {
    if (!data) return [];
    return normalizedSearch
      ? data.products.filter((product) => `${product.title} ${product.external_id}`.toLowerCase().includes(normalizedSearch))
      : data.products;
  }, [data, normalizedSearch]);
  const selected = data?.products.find((product) => product.external_id === selectedId) || products[0] || null;

  const collect = async () => {
    setBusy(true);
    try {
      const result = await localPlatformService.collectProducts();
      notify(result.detail);
      await load(true);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "今日采集失败");
    } finally {
      setBusy(false);
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
      notify("商品已添加，等待下一次每日采集验证卖家");
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
    setActionType(recommendation?.strategy_code === "scale_candidate" ? "traffic" : recommendation?.strategy_code === "healthy" ? "hold" : "title");
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

  return <div className="product-intelligence-page">
    <section className="product-command-card">
      <div className="product-command-copy">
        <span className="product-eyebrow"><Sparkle size={14} weight="fill" /> PRODUCT INTELLIGENCE</span>
        <h2>今天只做最值得做的商品动作</h2>
        <p>系统每天读取一次商品与经营数据，优先告诉你该观察、修改还是进行人工小预算测试。</p>
        <div className="product-safety-note"><ShieldCheck size={18} weight="fill" /><span><b>只读安全边界</b>{data.collection.safety_note}</span></div>
      </div>
      <div className="product-collection-panel">
        <div><small>采集计划 · 北京时间</small><strong>{data.collection.schedule}</strong><span>{data.collection.configured ? `下次计划 ${formatDate(data.collection.next_collection_at)}（北京时间）` : "等待配置闲鱼连接"}</span></div>
        {data.collection.last_run && <p className={`collection-result collection-${data.collection.last_run.status}`}><CheckCircle size={16} weight="fill" />{statusLabels[data.collection.last_run.status] || data.collection.last_run.status}<small>{data.collection.last_run.detail}</small></p>}
        <div className="product-command-actions">
          <button className="product-outline-button" onClick={() => setManagementOpen(true)}><Package size={16} />商品管理</button>
          <button className="product-outline-button" onClick={() => setRegisterOpen(true)}><Plus size={16} />添加商品</button>
          <button className="product-primary-button" disabled={busy || !data.collection.can_collect_today} onClick={() => void collect()}>{busy ? <ArrowClockwise className="spin" size={16} /> : <ArrowClockwise size={16} />}{data.collection.can_collect_today ? "执行今日采集" : data.collection.configured ? "今日已采集" : "等待渠道配置"}</button>
        </div>
      </div>
    </section>

    <section className="product-metrics-grid" aria-label="商品经营指标">
      <ProductMetric icon={Package} label="我的商品" value={`${data.summary.monitored_products}`} detail={`${data.summary.active_products} 个可经营 · ${data.summary.excluded_products} 个已排除`} tone="purple" />
      <ProductMetric icon={BellRinging} label="需要关注" value={`${data.summary.needs_attention}`} detail="按证据与优先级排序" tone="orange" />
      <ProductMetric icon={Megaphone} label="投流候选" value={`${data.summary.traffic_candidates}`} detail="仅建议，不会自动花费" tone="green" />
      <ProductMetric icon={CalendarCheck} label="趋势积累" value={`${data.summary.snapshot_days} 天`} detail="每日最多一个数据点" tone="blue" />
      <ProductMetric icon={Gauge} label="交付负载" value={`${data.summary.active_projects}/${data.summary.delivery_capacity}`} detail="满载时自动建议收缩流量" tone="red" />
    </section>

    <section className="product-workspace-grid">
      <main className="product-main-column">
        <section className="product-panel product-priority-panel">
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
                  <button onClick={() => { setSelectedId(recommendation.item_external_id); document.getElementById("product-detail")?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>查看商品 <CaretRight size={14} /></button>
                  {product && <button className="priority-primary" onClick={() => openAction(product, recommendation)}>记录我已执行</button>}
                  <button className="priority-dismiss" disabled={busy} onClick={() => void dismissRecommendation(recommendation)}>暂不处理</button>
                </div>
              </article>;
            })}
          </div> : <div className="product-empty-state"><CheckCircle size={40} weight="duotone" /><h4>今天没有待处理建议</h4><p>系统不会为了显得智能而填充没有证据的策略。</p></div>}
        </section>

        <section className="product-panel product-inventory-panel">
          <header><span><small>PRODUCT RADAR</small><h3>商品经营雷达</h3></span><em>{normalizedSearch ? `筛选出 ${products.length} 个` : "点击商品查看证据"}</em></header>
          {products.length ? <div className="product-table" role="table" aria-label="商品经营列表">
            <div className="product-table-head" role="row"><span>商品</span><span>浏览变化</span><span>想要 / 收藏</span><span>咨询 / 成交</span><span>利润</span><span>当前策略</span></div>
            {products.map((product) => <button type="button" role="row" className={selected?.external_id === product.external_id ? "selected" : ""} onClick={() => setSelectedId(product.external_id)} key={product.external_id}>
              <span className="product-name-cell"><i><Storefront size={18} weight="duotone" /></i><b>{product.title}<small>ID {product.external_id}</small></b><ProductCollectionBadge product={product} /></span>
              <span><strong>{integer.format(product.browse_count)}</strong><small>{product.browse_delta === null ? "建立基线" : `+${integer.format(product.browse_delta)}`}</small></span>
              <span><strong>{product.want_count} / {product.collect_count}</strong><small>累计互动</small></span>
              <span><strong>{product.inquiry_count} / {product.converted_project_count}</strong><small>{product.deal_rate === null ? "暂无成交率" : `成交率 ${product.deal_rate}%`}</small></span>
              <span><strong>{money.format(product.profit_total)}</strong><small>关联实际利润</small></span>
              <span>{product.recommendation && ["active", "in_progress"].includes(product.recommendation.status) ? <AttentionBadge value={product.recommendation.attention} /> : <em className="product-waiting">{product.recommendation?.status === "dismissed" ? "今日已忽略" : "等待数据"}</em>}<CaretRight size={15} /></span>
            </button>)}
          </div> : <div className="product-empty-state"><MagnifyingGlass size={40} weight="duotone" /><h4>{normalizedSearch ? "没有匹配的商品" : "还没有监测商品"}</h4><p>{normalizedSearch ? "可以调整顶部搜索关键词。" : "添加闲鱼商品 ID 或链接，系统会在下一次每日采集中读取数据。"}</p>{!normalizedSearch && <button onClick={() => setRegisterOpen(true)}><Plus size={16} />添加第一个商品</button>}</div>}
        </section>
      </main>

      <aside className="product-insight-column">
        <section className="product-panel publish-timing-card">
          <header><span><small>PUBLISH TIMING</small><h3>发布时间建议</h3></span><Clock size={22} weight="duotone" /></header>
          <p>{data.publish_timing.summary}</p>
          <div className="timing-confidence"><span className={`confidence-${data.publish_timing.confidence}`}>{confidenceLabels[data.publish_timing.confidence] || data.publish_timing.confidence}</span><small>{data.publish_timing.sample_size} 条近 90 天咨询</small></div>
          {data.publish_timing.windows.map((window, index) => <div className="publish-window" key={`${window.weekday}-${window.time_range}`}><i>{index + 1}</i><span><b>{window.weekday}</b><small>{window.time_range}</small></span><strong>{window.share}%<small>{window.inquiry_count} 条咨询</small></strong></div>)}
        </section>

        <section className="product-panel demand-card">
          <header><span><small>DEMAND GAPS</small><h3>可以发布什么</h3></span><Lightbulb size={22} weight="duotone" /></header>
          {data.demand_opportunities.length ? <div className="demand-list">{data.demand_opportunities.map((opportunity) => <article key={opportunity.theme}><i className={opportunity.posture === "已验证" ? "verified" : opportunity.posture === "供给缺口" ? "gap" : "observe"}><Target size={17} /></i><span><p><b>{opportunity.theme}</b><em>{opportunity.posture}</em></p><small>{opportunity.suggestion}</small><strong>{opportunity.conversation_count} 个会话 · {opportunity.converted_project_count} 个项目</strong></span></article>)}</div> : <div className="compact-empty"><Lightbulb size={28} /><span><b>等待需求信号</b><small>系统只从真实客户咨询中发现机会。</small></span></div>}
        </section>
      </aside>
    </section>

    {selected && <section className="product-panel product-detail-panel" id="product-detail">
      <header className="product-detail-head"><div><span><Storefront size={20} weight="duotone" /></span><div className="product-detail-title"><small>SELECTED PRODUCT</small><h3>{selected.title}</h3><em>商品 ID {selected.external_id} · 最近数据 {formatDate(selected.last_collected_at)}</em><ProductCollectionBadge product={selected} /></div></div><div><button className="product-outline-button" disabled={busy} onClick={() => void toggleMonitor(selected)}>{selected.monitoring_enabled ? <EyeSlash size={16} /> : <Eye size={16} />}{selected.monitoring_enabled ? "暂停监测" : "恢复监测"}</button><button className="product-primary-button" onClick={() => openAction(selected, selected.recommendation)}><CheckCircle size={16} />记录人工动作</button></div></header>
      {selected.last_error_detail && <div className="product-item-diagnostic"><Warning size={17} weight="fill" /><span><b>{selected.last_error_code === "item_unavailable" ? "商品详情不可读取" : "最近一次采集未完成"}</b><small>{selected.last_error_detail}</small><em>最近尝试 {formatDate(selected.last_attempt_at)}（北京时间）</em></span></div>}
      <div className="product-detail-grid">
        <div className="product-detail-trend"><h4>累计浏览趋势</h4><ProductTrend product={selected} /></div>
        <div className="product-funnel"><h4>从浏览到成交</h4><div><span><small>浏览</small><b>{integer.format(selected.browse_count)}</b></span><CaretRight size={17} /><span><small>咨询</small><b>{selected.inquiry_count}</b><em>{selected.inquiry_rate === null ? "—" : `${selected.inquiry_rate}%`}</em></span><CaretRight size={17} /><span><small>项目</small><b>{selected.converted_project_count}</b><em>{selected.deal_rate === null ? "—" : `${selected.deal_rate}%`}</em></span></div><p><TrendUp size={16} />关联收入 {money.format(selected.revenue_total)} · 实际利润 {money.format(selected.profit_total)}</p></div>
        <div className="product-strategy-evidence"><h4>当前建议与证据</h4>{selected.recommendation && selected.recommendation.status !== "dismissed" ? <><p><AttentionBadge value={selected.recommendation.attention} /><b>{selected.recommendation.title}</b></p><ul>{selected.recommendation.actions.map((action) => <li key={action}><CheckCircle size={15} />{action}</li>)}</ul></> : <div className="compact-empty"><PauseCircle size={26} /><span><b>{selected.recommendation?.status === "dismissed" ? "今日建议已暂不处理" : "等待首个快照"}</b><small>{selected.recommendation?.status === "dismissed" ? "明日数据变化后会重新评估。" : "系统不会在没有数据时生成策略。"}</small></span></div>}</div>
      </div>
      {selected.actions.length > 0 && <div className="product-action-history"><h4>最近人工动作</h4>{selected.actions.slice(0, 5).map((action) => <p key={action.id}><i><CheckCircle size={15} weight="fill" /></i><span><b>{actionLabels[action.action_type] || action.action_type}</b><small>{action.note || "未填写备注"}</small></span><time>{formatDate(action.happened_at)}{action.cost > 0 && ` · ${money.format(action.cost)}`}</time></p>)}</div>}
    </section>}

    {managementOpen && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setManagementOpen(false); }}><section className="product-modal product-management-modal" role="dialog" aria-modal="true" aria-labelledby="product-management-title">
      <header><span><Package size={20} /></span><div><h3 id="product-management-title">商品管理</h3><p>只有当前闲鱼账号本人商品会进入经营统计与每日采集。</p></div><button type="button" aria-label="关闭" onClick={() => setManagementOpen(false)}><X size={18} /></button></header>
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
          <span><small>{ownershipLabels[product.ownership_status] || product.ownership_status} · ID {product.external_id}</small><b>{product.title}</b><em>{product.last_error_detail || (product.ownership_status === "owned" ? `最近采集：${formatDate(product.last_attempt_at)}` : product.ownership_status === "pending" ? "将在下一次每日采集中核对卖家" : "卖家与当前登录账号不一致，历史仍然保留")}</em></span>
          <div><ProductCollectionBadge product={product} /><small>{state.key === "failed" ? formatDate(product.last_attempt_at) : product.monitoring_enabled ? "监测已启用" : "不参与统计"}</small></div>
          {product.ownership_status === "owned" ? <button type="button" disabled={busy} onClick={() => void toggleMonitor(product)}>{product.monitoring_enabled ? <EyeSlash size={15} /> : <Eye size={15} />}{product.monitoring_enabled ? "暂停" : "恢复"}</button> : <button type="button" disabled title={product.ownership_status === "excluded" ? "非当前账号商品不能恢复监测" : "等待下一次每日采集验证卖家"}><EyeSlash size={15} />{product.ownership_status === "excluded" ? "非当前账号" : "等待验证"}</button>}
        </article>;
      })}{(managementTab === "owned" ? data.products : data.candidates.filter((product) => product.ownership_status === managementTab)).length === 0 && <div className="product-management-empty"><CheckCircle size={28} weight="duotone" /><span><b>{managementTab === "owned" ? "还没有确认属于你的商品" : managementTab === "pending" ? "没有待确认商品" : "没有被排除的商品"}</b><small>{managementTab === "owned" ? "添加商品后会在下一次每日采集中验证卖家。" : "商品归属变化会自动更新到这里。"}</small></span></div>}</div>
      <footer><button type="button" onClick={() => setManagementOpen(false)}>关闭</button><button type="button" className="product-primary-button" onClick={() => { setManagementOpen(false); setRegisterOpen(true); }}><Plus size={16} />添加商品</button></footer>
    </section></div>}

    {registerOpen && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setRegisterOpen(false); }}><form className="product-modal" onSubmit={register}>
      <header><span><Plus size={20} /></span><div><h3>添加监测商品</h3><p>只保存商品 ID，等下一次每日采集时再读取详情。</p></div><button type="button" aria-label="关闭" onClick={() => setRegisterOpen(false)}><X size={18} /></button></header>
      <label><span>闲鱼商品 ID 或商品链接</span><input autoFocus value={registerReference} onChange={(event) => setRegisterReference(event.target.value)} placeholder="粘贴商品链接，或输入 itemId" /></label>
      <div className="product-modal-note"><ShieldCheck size={17} /><span>添加操作不会访问闲鱼，也不会修改商品。远程读取仍受每天一次的采集限制。</span></div>
      <footer><button type="button" onClick={() => setRegisterOpen(false)}>取消</button><button className="product-primary-button" disabled={busy || !registerReference.trim()}>{busy ? <ArrowClockwise className="spin" size={16} /> : <Plus size={16} />}加入监测</button></footer>
    </form></div>}

    {actionTarget && <div className="product-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setActionTarget(null); }}><form className="product-modal product-action-modal" onSubmit={saveAction}>
      <header><span><CheckCircle size={20} /></span><div><h3>记录我已执行的动作</h3><p>{actionTarget.product.title}</p></div><button type="button" aria-label="关闭" onClick={() => setActionTarget(null)}><X size={18} /></button></header>
      <label><span>人工完成的动作</span><select value={actionType} onChange={(event) => setActionType(event.target.value)}>{Object.entries(actionLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      {actionType === "traffic" && <label><span>人工投入金额</span><input type="number" min="0" step="1" value={actionCost} onChange={(event) => setActionCost(event.target.value)} placeholder="仅记录，不会发起付款" /></label>}
      <label><span>备注</span><textarea rows={4} value={actionNote} onChange={(event) => setActionNote(event.target.value)} placeholder="例如：将标题第一句改为客户常用表达，其他内容不变" /></label>
      <div className="product-modal-note warning"><Warning size={17} /><span>这里不会替你修改、发布或投流，只记录你已经在闲鱼手动完成的动作。</span></div>
      <footer><button type="button" onClick={() => setActionTarget(null)}>取消</button><button className="product-primary-button" disabled={busy}>{busy ? <ArrowClockwise className="spin" size={16} /> : <CheckCircle size={16} />}保存并开始观察</button></footer>
    </form></div>}

    {toast && <div className="product-toast" role="status"><CheckCircle size={19} weight="fill" />{toast}</div>}
  </div>;
}
