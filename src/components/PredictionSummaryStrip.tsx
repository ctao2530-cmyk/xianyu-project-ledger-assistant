import {
  ArrowRight,
  Briefcase,
  ClockCountdown,
  CurrencyCircleDollar,
  Gauge,
  ShieldCheck,
  UserFocus,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import {
  predictionFact,
  predictionRiskLabel,
  predictionService,
  predictionSufficiencyLabel,
  type PredictionLatestView,
  type PredictionResult,
} from "../data/predictionService";

type PredictionSummaryContext = "home" | "projects" | "customers" | "finance";

function numberValue(value: number | string | boolean | null, fallback = 0) {
  return typeof value === "number" ? value : fallback;
}

function score(result: PredictionResult | null | undefined) {
  return Math.round(result?.score ?? 0);
}

export function PredictionSummaryStrip({
  context,
  onNavigate,
}: {
  context: PredictionSummaryContext;
  onNavigate?: (page: string) => void;
}) {
  const [prediction, setPrediction] = useState<PredictionLatestView | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setFailed(false);
    void predictionService.latest()
      .then((value) => { if (active) setPrediction(value); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);

  const topProject = useMemo(
    () => prediction?.high_risk_projects.slice().sort((left, right) => score(right) - score(left))[0] || null,
    [prediction],
  );
  const topCustomer = useMemo(
    () => prediction?.priority_customers.slice().sort((left, right) => score(right) - score(left))[0] || null,
    [prediction],
  );

  if (failed) return null;
  if (!prediction) return <section className={`prediction-summary-strip context-${context} is-loading`} aria-label="正在读取经营预测" aria-busy="true"><span /><span /><span /></section>;

  const workload = prediction.workload;
  const cashflow = prediction.cashflow;
  const remainingHours = numberValue(predictionFact(workload, "remaining_hours"));
  const availableHours = numberValue(predictionFact(workload, "available_hours"));
  const knownInflow = numberValue(predictionFact(cashflow, "known_inflow"));
  const primary = context === "projects" ? topProject : context === "customers" ? topCustomer : context === "finance" ? cashflow : workload;

  return <section className={`prediction-summary-strip context-${context}`} aria-label="经营预测摘要">
    <header>
      <span><ClockCountdown size={17} weight="duotone" />经营预测</span>
      <small>本地规则 · 只读</small>
    </header>
    {context === "home" ? <div className="prediction-summary-items">
      <button type="button" onClick={() => onNavigate?.("经营分析中心")}>
        <i className="tone-green"><Gauge size={18} weight="duotone" /></i><span><small>未来 14 天负载</small><b>{workload?.prediction_value ?? 0}% · {predictionRiskLabel(workload?.risk_level || null)}</b><em>{remainingHours}h 待推进 / {availableHours}h 可用</em></span>
      </button>
      <button type="button" onClick={() => onNavigate?.("项目管理")}>
        <i className="tone-orange"><Briefcase size={18} weight="duotone" /></i><span><small>最高延期风险分</small><b>{topProject ? `${score(topProject)} / 100` : "暂无"}</b><em>{topProject?.entity_label || "当前没有纳入项目"}</em></span>
      </button>
      <button type="button" onClick={() => onNavigate?.("收入记录")}>
        <i className="tone-blue"><CurrencyCircleDollar size={18} weight="duotone" /></i><span><small>未来 30 天已知净现金流</small><b>¥{Math.round(cashflow?.prediction_value ?? 0)}</b><em>{cashflow?.data_sufficiency === "low" ? "历史不足 · 仅已知项" : `确定流入 ¥${Math.round(knownInflow)}`}</em></span>
      </button>
      <button type="button" onClick={() => onNavigate?.("客户管理")}>
        <i className="tone-purple"><UserFocus size={18} weight="duotone" /></i><span><small>今日优先跟进</small><b>{topCustomer ? `${score(topCustomer)} / 100` : "暂无"}</b><em>{topCustomer?.entity_label || "当前没有需优先跟进客户"}</em></span>
      </button>
    </div> : <div className="prediction-summary-focus">
      <i className={`tone-${context === "finance" ? "blue" : context === "customers" ? "purple" : "orange"}`}>
        {context === "finance" ? <CurrencyCircleDollar size={21} weight="duotone" /> : context === "customers" ? <UserFocus size={21} weight="duotone" /> : <WarningCircle size={21} weight="duotone" />}
      </i>
      <span>
        <small>{context === "finance" ? "未来 30 天现金流" : context === "customers" ? "今日跟进优先级" : "项目延期风险"}</small>
        <b>{context === "finance" ? `已知净现金流 ¥${Math.round(cashflow?.prediction_value ?? 0)}` : primary ? `${primary.entity_label || "当前对象"} · ${score(primary)} / 100` : "暂无可用预测"}</b>
        <em>{context === "finance" ? (cashflow?.data_sufficiency === "low" ? "历史不足，仅展示确定信息" : `确定性流入 ¥${Math.round(knownInflow)}`) : primary?.drivers[0]?.detail || "等待更多真实经营数据"}</em>
      </span>
      {primary && <strong className={`sufficiency-${primary.data_sufficiency}`}>数据充分度 {predictionSufficiencyLabel(primary.data_sufficiency)}</strong>}
      <button type="button" onClick={() => onNavigate?.("经营分析中心")}>查看依据 <ArrowRight size={14} /></button>
    </div>}
    <footer><ShieldCheck size={14} weight="fill" />规则评分不是概率，预测不会自动执行经营动作。</footer>
  </section>;
}
