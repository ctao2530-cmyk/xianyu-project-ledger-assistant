import {
  CaretRight,
  ChartLineUp,
  ChatCircleDots,
  CheckCircle,
  Clock,
  Coins,
  Info,
  LockSimple,
  MagnifyingGlass,
  PauseCircle,
  ShieldCheck,
  Sparkle,
  Sun,
  SunHorizon,
  TrendUp,
  Warning,
  X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  ProductOperatingPlanSlotView,
  TrafficCommercialAttributionView,
  TrafficExperimentCellView,
  TrafficExperimentView,
  TrafficGrowthOverviewView,
} from "../data/localPlatformService";
import { formatTrafficDateTime } from "../utils/trafficDateTime";

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 2,
});

const windowIcons = {
  "12": Sun,
  "16": SunHorizon,
  "20": Clock,
};

const recommendationLabels = {
  scale: "提高一档",
  hold: "保持",
  reduce: "降低一档",
  pause: "暂停",
};

const stageRows = [
  { key: "T0", title: "干净时段探索", budget: 24, frequency: "约每 72 小时 1 次" },
  { key: "S1", title: "时段验证扩展", budget: 24, frequency: "约每周 3 次" },
  { key: "S2", title: "稳定放量", budget: 36, frequency: "约每周 5 次" },
  { key: "S3", title: "高频放量", budget: 48, frequency: "约每周 7 次" },
] as const;

function stageIndex(stage: string) {
  const value = stageRows.findIndex((row) => row.key === stage);
  return value < 0 ? 0 : value;
}

function cellLabel(cell: TrafficExperimentCellView | undefined) {
  if (!cell) return { label: "未安排", tone: "empty" };
  if (cell.analysis_eligible) return { label: "有效完成", tone: "done" };
  if (cell.status === "bound") return { label: "批次已建立", tone: "active" };
  if (cell.status === "excluded") return { label: "已排除", tone: "warning" };
  if (cell.batch_id) return { label: "观察中", tone: "active" };
  return { label: "未执行", tone: "empty" };
}

function attributionStatus(value: TrafficCommercialAttributionView) {
  if (value.status === "confirmed") return "已确认";
  if (value.status === "rejected") return "已排除";
  return "待确认";
}

interface TrafficGrowthWorkbenchProps {
  overview: TrafficGrowthOverviewView;
  nextPlanSlot: ProductOperatingPlanSlotView | null;
  busy: boolean;
  onCreateExperiment: (externalId: string) => Promise<void>;
  onCreateNextBatch: (slot: ProductOperatingPlanSlotView) => void;
  onAdvanceExperiment: (experiment: TrafficExperimentView) => Promise<void>;
  onRefreshAttributions: (experiment: TrafficExperimentView) => Promise<void>;
  onDecideAttribution: (
    experiment: TrafficExperimentView,
    attribution: TrafficCommercialAttributionView,
    decision: "confirm" | "reject",
  ) => Promise<void>;
  onRefreshBudget: (experiment: TrafficExperimentView) => Promise<void>;
  onApplyBudget: (experiment: TrafficExperimentView) => Promise<void>;
  onCreateCohort: (experiment: TrafficExperimentView, stage: "S1" | "S2" | "S3") => Promise<void>;
}

export function TrafficGrowthWorkbench({
  overview,
  nextPlanSlot,
  busy,
  onCreateExperiment,
  onCreateNextBatch,
  onAdvanceExperiment,
  onRefreshAttributions,
  onDecideAttribution,
  onRefreshBudget,
  onApplyBudget,
  onCreateCohort,
}: TrafficGrowthWorkbenchProps) {
  const experiment = overview.active_experiment;
  const [selectedWindow, setSelectedWindow] = useState("16");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerRef = useRef<HTMLElement | null>(null);
  const drawerTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (experiment?.next_cell?.window_bucket) {
      setSelectedWindow(experiment.next_cell.window_bucket);
    }
  }, [experiment?.id, experiment?.next_cell?.window_bucket]);

  useEffect(() => {
    if (!drawerOpen) return undefined;
    const drawer = drawerRef.current;
    const first = drawer?.querySelector<HTMLElement>("button:not([disabled]), select:not([disabled])");
    first?.focus();
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setDrawerOpen(false);
        window.setTimeout(() => drawerTriggerRef.current?.focus(), 0);
        return;
      }
      if (event.key !== "Tab" || !drawer) return;
      const focusable = Array.from(
        drawer.querySelectorAll<HTMLElement>("button:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex='-1'])"),
      );
      if (!focusable.length) return;
      const firstElement = focusable[0];
      const lastElement = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  const currentStage = useMemo(() => {
    if (!experiment) return "T0";
    const lastCohort = experiment.cohorts[experiment.cohorts.length - 1];
    if (lastCohort) return lastCohort.stage;
    if (experiment.budget_decision.applied_at) return experiment.budget_decision.to_stage;
    return "T0";
  }, [experiment]);

  if (!experiment) {
    const candidate = overview.recommended_candidate;
    return <section className="traffic-growth-empty" aria-labelledby="traffic-growth-title">
      <div className="traffic-growth-empty-icon"><ChartLineUp size={30} weight="duotone" /></div>
      <div>
        <span className="product-eyebrow"><Sparkle size={14} weight="fill" /> GROWTH EXPERIMENT</span>
        <h3 id="traffic-growth-title">建立第一个干净时段实验</h3>
        <p>固定同一重点商品，在中午、下午和晚间各完成两次干净复刻，再对前两名各确认一次。系统只安排建议，不会自动购买曝光。</p>
        {candidate && <div className="traffic-growth-candidate">
          <span><small>建议重点商品</small><b>{candidate.title}</b></span>
          <span><small>历史已实现利润</small><b>{currency.format(candidate.historical_realized_profit)}</b><em>仅用于选品，不归因给曝光</em></span>
        </div>}
      </div>
      <button type="button" className="product-primary-button" disabled={busy || !candidate} onClick={() => candidate && void onCreateExperiment(candidate.external_id)}>
        <Sparkle size={16} />建立 8 批时段实验
      </button>
    </section>;
  }

  const selectedResult = experiment.time_windows.find((value) => value.window_bucket === selectedWindow);
  const selectedCells = experiment.cells.filter(
    (cell) => cell.window_bucket === selectedWindow && cell.phase !== "off_matrix",
  );
  const explorationCells = selectedCells.filter((cell) => cell.phase === "exploration");
  const confirmationCell = selectedCells.find((cell) => cell.phase === "confirmation");
  const nextCell = experiment.next_cell;
  const latestCohort = experiment.cohorts[experiment.cohorts.length - 1] || null;
  const canAdvance = experiment.phase === "exploration"
    && experiment.valid_exploration_batches >= experiment.required_exploration_batches
    && Boolean(experiment.provisional_winner);
  const canCreateCohort = experiment.mode === "scale_cohort"
    && experiment.budget_decision.applied_at
    && experiment.budget_decision.to_stage !== "T0"
    && (!latestCohort || latestCohort.stage !== experiment.budget_decision.to_stage);
  const primaryAction = nextCell && nextPlanSlot
    ? { label: "按计划新建干净批次", action: () => onCreateNextBatch(nextPlanSlot) }
    : canAdvance
      ? { label: "进入优胜时段确认", action: () => void onAdvanceExperiment(experiment) }
      : experiment.budget_decision.can_apply
        ? { label: `应用建议：${recommendationLabels[experiment.budget_decision.recommendation]}`, action: () => void onApplyBudget(experiment) }
        : canCreateCohort
          ? { label: `确认条件并建立 ${experiment.budget_decision.to_stage} 队列`, action: () => void onCreateCohort(experiment, experiment.budget_decision.to_stage as "S1" | "S2" | "S3") }
          : null;

  return <>
    <section className="traffic-growth-workbench" aria-labelledby="traffic-growth-title">
      <div className="traffic-growth-main">
        <header className="traffic-growth-heading">
          <span><small>GROWTH EXPERIMENT WORKBENCH</small><h3 id="traffic-growth-title">增长实验工作台</h3></span>
          <em>{experiment.mode === "time_test" ? "干净时段探索" : "14 天扩量队列"}</em>
        </header>

        <article className="traffic-growth-hero">
          <div className="traffic-growth-product">
            <span className="traffic-growth-product-tag">当前高潜商品</span>
            <h4>{experiment.product.title}</h4>
            <div><em>{currentStage} · {experiment.mode === "time_test" ? "干净时段探索" : "队列整体观察"}</em><b>周上限 {currency.format(experiment.current_weekly_budget)}</b></div>
            <p><Info size={15} />历史 {currency.format(experiment.product.historical_realized_profit)} 利润仅作为候选商品证据，并非曝光归因利润。</p>
          </div>
          <div className="traffic-growth-next">
            <div className="traffic-growth-next-head"><span><small>下一次计划测试</small><b>{nextCell?.scheduled_for ? formatTrafficDateTime(nextCell.scheduled_for) : "等待当前阶段证据"}</b></span>{nextCell && <em>保持至少 72 小时间隔</em>}</div>
            {nextCell && <ul>
              <li>实际开始后按真实北京时间桶归类：{nextCell.time_range}</li>
              <li>只有可靠 T0、无重叠并完成 +24h / +72h 才进入时段结论</li>
            </ul>}
            {primaryAction
              ? <button type="button" className="product-primary-button" disabled={busy} onClick={primaryAction.action}><Sparkle size={17} />{primaryAction.label}</button>
              : <button type="button" className="product-outline-button" disabled><PauseCircle size={17} />等待下一项完整证据</button>}
          </div>
        </article>

        <div className="traffic-growth-progress-head">
          <span><b>北京时间 · 时段探索进度</b><em>探索 {experiment.valid_exploration_batches}/{experiment.required_exploration_batches} · 确认 {experiment.valid_confirmation_batches}/{experiment.required_confirmation_batches}</em></span>
          <small>实际开始时间决定时段</small>
        </div>
        <div className="traffic-window-tabs" role="tablist" aria-label="选择曝光测试时段">
          {experiment.time_windows.map((window) => {
            const Icon = windowIcons[window.window_bucket as keyof typeof windowIcons] || Clock;
            return <button key={window.window_bucket} type="button" role="tab" aria-selected={selectedWindow === window.window_bucket} onClick={() => setSelectedWindow(window.window_bucket)}>
              <Icon size={17} weight="duotone" />{window.time_range}
            </button>;
          })}
        </div>
        <div className="traffic-window-table" role="table" aria-label="三时段实验矩阵">
          {experiment.time_windows.map((window) => {
            const Icon = windowIcons[window.window_bucket as keyof typeof windowIcons] || Clock;
            const windowCells = experiment.cells.filter((cell) => cell.window_bucket === window.window_bucket && cell.phase !== "off_matrix");
            const explorations = windowCells.filter((cell) => cell.phase === "exploration");
            const confirmation = windowCells.find((cell) => cell.phase === "confirmation");
            return <div className={`traffic-window-row ${selectedWindow === window.window_bucket ? "is-selected" : ""}`} role="row" key={window.window_bucket}>
              <button type="button" className="traffic-window-name" onClick={() => setSelectedWindow(window.window_bucket)}><Icon size={22} weight="duotone" /><span><b>{window.time_range}</b><small>{window.window_bucket === "12" ? "中午" : window.window_bucket === "16" ? "下午" : "晚间"}</small></span></button>
              {explorations.map((cell, index) => {
                const status = cellLabel(cell);
                return <span className={`traffic-cell-status is-${status.tone}`} key={cell.id}><small>探索 {index + 1}</small><b>{status.label}</b></span>;
              })}
              {!explorations.length && [0, 1].map((index) => <span className="traffic-cell-status is-empty" key={index}><small>探索 {index + 1}</small><b>未安排</b></span>)}
              <span className={`traffic-cell-status is-${cellLabel(confirmation).tone}`}><small>确认</small><b>{cellLabel(confirmation).label}</b></span>
              <span className="traffic-window-metric"><small>咨询均值</small><b>{window.valid_batch_count ? window.average_inquiry_delta.toFixed(1) : "—"}</b></span>
              <span className="traffic-window-metric"><small>浏览均值</small><b>{window.valid_batch_count ? Math.round(window.average_browse_delta) : "—"}</b></span>
              <span className={`traffic-window-evidence ${window.confirmed_winner ? "is-winner" : window.provisional_winner ? "is-leading" : ""}`}><b>{window.confirmed_winner ? "稳定优胜" : window.provisional_winner ? "暂时领先" : window.valid_batch_count ? `${window.valid_batch_count} 批有效` : "无数据"}</b><small>{window.confirmed_winner ? "可进入预算验证" : "继续收集"}</small></span>
            </div>;
          })}
        </div>
        <div className="traffic-window-mobile-detail">
          <b>{selectedResult?.time_range} 桶详情</b>
          <div>
            {explorationCells.map((cell, index) => <span key={cell.id}><small>探索复刻 {index + 1}</small><b>{cellLabel(cell).label}</b></span>)}
            {!explorationCells.length && <><span><small>探索复刻 1</small><b>未执行</b></span><span><small>探索复刻 2</small><b>未执行</b></span></>}
            <span><small>确认批次</small><b>{cellLabel(confirmationCell).label}</b></span>
            <span><small>咨询均值</small><b>{selectedResult?.valid_batch_count ? selectedResult.average_inquiry_delta.toFixed(1) : "—"}</b></span>
            <span><small>浏览均值</small><b>{selectedResult?.valid_batch_count ? Math.round(selectedResult.average_browse_delta) : "—"}</b></span>
          </div>
        </div>
        <p className="traffic-growth-winner-rule"><Info size={15} />胜出标准：顶部时段至少 2 次咨询，咨询均值领先次优时段每批 ≥0.5 次；浏览不低于次优时段 70%，并在确认批次后保持稳定。</p>
      </div>

      <aside className="traffic-budget-ladder" aria-labelledby="traffic-budget-title">
        <header><span><small>BUDGET LADDER</small><h4 id="traffic-budget-title">预算阶梯</h4></span><em>周内迭代</em></header>
        <ol>
          {stageRows.map((stage, index) => {
            const current = stage.key === currentStage;
            const locked = index > stageIndex(currentStage);
            return <li className={current ? "is-current" : locked ? "is-locked" : "is-past"} key={stage.key}>
              <i>{current ? <CheckCircle size={18} weight="fill" /> : locked ? <LockSimple size={16} /> : <CheckCircle size={17} />}</i>
              <span><b>{stage.key}</b><strong>{stage.title}</strong><small>¥{stage.budget} / 周 · {stage.frequency}</small></span>
              {current && <em>当前</em>}
            </li>;
          })}
        </ol>
        <section className="traffic-budget-thresholds">
          <h5>决策门槛</h5>
          <p><CheckCircle size={15} />利润成本比 ≥ 5 且归因咨询 ≥ 3</p>
          <p><CheckCircle size={15} />已回款项目 ≥ 2</p>
          <p><CheckCircle size={15} />贡献利润 ≥ ¥120</p>
          <p><CheckCircle size={15} />当前交付负载 ≤ 2/4</p>
        </section>
        <div className={`traffic-budget-recommendation is-${experiment.budget_decision.recommendation}`}>
          <span><small>当前建议</small><b>{recommendationLabels[experiment.budget_decision.recommendation]}</b></span>
          <em>{experiment.budget_decision.metrics.observation_complete ? "观察期完整" : "继续积累证据"}</em>
        </div>
        <button type="button" className="traffic-budget-refresh" disabled={busy} onClick={() => void onRefreshBudget(experiment)}><ChartLineUp size={16} />重新核验预算证据</button>
        <p className="traffic-growth-safety"><ShieldCheck size={19} weight="duotone" /><span><b>安全说明（人工控制）</b><small>{overview.safety_notice}</small></span></p>
      </aside>

      <footer className="traffic-commercial-strip" aria-label="曝光关联商业证据">
        <span className="traffic-commercial-title"><small>商业证据</small><em>仅统计曝光关联，不声称平台因果增量</em></span>
        <span><Coins size={19} weight="duotone" /><small>关联投入</small><b>{currency.format(experiment.metrics.actual_cost)}</b></span>
        <span><ChatCircleDots size={19} weight="duotone" /><small>归因咨询</small><b>{experiment.metrics.attributed_inquiry_count}</b></span>
        <span><TrendUp size={19} weight="duotone" /><small>已回款项目</small><b>{experiment.metrics.paid_project_count}</b></span>
        <span><ChartLineUp size={19} weight="duotone" /><small>贡献利润</small><b>{currency.format(experiment.metrics.realized_contribution_profit)}</b></span>
        <span><ShieldCheck size={19} weight="duotone" /><small>利润成本比</small><b>{experiment.metrics.profit_to_cost_ratio === null ? "—" : experiment.metrics.profit_to_cost_ratio.toFixed(2)}</b></span>
        <button ref={drawerTriggerRef} type="button" onClick={() => setDrawerOpen(true)}>审查商业归因<CaretRight size={15} /></button>
      </footer>
    </section>

    {drawerOpen && <div className="traffic-attribution-layer" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) {
        setDrawerOpen(false);
        window.setTimeout(() => drawerTriggerRef.current?.focus(), 0);
      }
    }}>
      <aside ref={drawerRef} className="traffic-attribution-drawer" role="dialog" aria-modal="true" aria-labelledby="traffic-attribution-title">
        <header><div><span><small>COMMERCIAL ATTRIBUTION</small><h3 id="traffic-attribution-title">商业归因审查</h3></span><p>只确认“曝光范围 → 首次入站对话 → 精确绑定项目 → 已确认财务事实”的证据链。</p></div><button type="button" aria-label="关闭商业归因审查" onClick={() => { setDrawerOpen(false); window.setTimeout(() => drawerTriggerRef.current?.focus(), 0); }}><X size={20} /></button></header>
        <div className="traffic-attribution-scope"><span><small>审查范围</small><b>{experiment.mode === "time_test" ? "干净时段实验" : `${latestCohort?.stage || currentStage} 扩量队列`}</b></span><span><small>观察窗口</small><b>{latestCohort?.commercial_followup_ends_at ? `截至 ${formatTrafficDateTime(latestCohort.commercial_followup_ends_at)}` : "批次后 7 天长尾"}</b></span></div>
        <div className="traffic-attribution-warning"><Warning size={18} weight="fill" /><span><b>曝光后关联，不等同于平台因果增量</b><small>保存的是可审计关联证据；不会发送消息、修改商品、购买曝光或改写项目。</small></span></div>
        <div className="traffic-attribution-list">
          {!experiment.attributions.length && <div className="traffic-attribution-empty"><MagnifyingGlass size={26} /><b>尚无候选证据</b><small>刷新后，系统只读取符合精确链路的首次入站对话。</small></div>}
          {experiment.attributions.map((attribution, index) => <article key={attribution.id} className={`is-${attribution.status}`}>
            <header><span><small>候选 {index + 1}</small><b>{formatTrafficDateTime(attribution.first_inbound_at)} · 对话 #{attribution.conversation_id}</b></span><em>{attributionStatus(attribution)}</em></header>
            <ol>
              <li><i>1</i><span><small>曝光观察范围</small><b>{attribution.scope === "cohort" ? "14 天扩量队列" : "单次干净批次"}</b></span></li>
              <li><i>2</i><span><small>首次入站咨询</small><b>{formatTrafficDateTime(attribution.first_inbound_at)}</b></span></li>
              <li><i>3</i><span><small>精确项目绑定</small><b>{attribution.project_name || "尚未绑定精确项目"}</b></span></li>
              <li><i>4</i><span><small>已实现贡献利润</small><b>{attribution.project_id ? currency.format(attribution.realized_profit) : "—"}</b></span></li>
            </ol>
            {attribution.status === "candidate" && <footer><button type="button" disabled={busy || !attribution.project_id} title={!attribution.project_id ? "必须先把精确对话绑定到项目" : undefined} onClick={() => void onDecideAttribution(experiment, attribution, "confirm")}>确认归因</button><button type="button" disabled={busy} onClick={() => void onDecideAttribution(experiment, attribution, "reject")}>排除</button></footer>}
          </article>)}
        </div>
        <footer><span><b>本次人工审查汇总</b><small>{experiment.attributions.filter((value) => value.status === "confirmed").length} 个已确认项目 · {currency.format(experiment.metrics.realized_contribution_profit)} 曝光关联贡献</small></span><button type="button" disabled={busy} onClick={() => void onRefreshAttributions(experiment)}><MagnifyingGlass size={16} />刷新候选证据</button></footer>
      </aside>
    </div>}
  </>;
}
