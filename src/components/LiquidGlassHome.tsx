import {
  ArrowRight,
  Briefcase,
  ChartLineDown,
  CheckCircle,
  ClockCountdown,
  Coins,
  FileText,
  Package,
  Receipt,
  ShieldCheck,
  UsersThree,
  Wallet,
  WarningCircle,
  type Icon as PhosphorIcon,
} from "@phosphor-icons/react";
import { useMemo } from "react";
import { getBusinessSummary } from "../data/businessMetrics";
import type { LedgerSnapshot, Project } from "../types";
import "./liquid-glass-home.css";

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const eventTime = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const fullDate = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  weekday: "short",
});

const projectStatus: Record<Project["status"], string> = {
  pending: "待开始",
  in_progress: "进行中",
  delivered: "已交付",
  completed: "已完成",
  overdue: "已逾期",
};

type TimelineTone = "blue" | "violet" | "coral" | "slate";

interface TimelineEntry {
  id: string;
  eyebrow: string;
  title: string;
  description: string;
  value: string;
  valueLabel: string;
  tone: TimelineTone;
  icon: PhosphorIcon;
  action: () => void;
}

interface LiquidGlassHomeProps {
  snapshot: LedgerSnapshot;
  onNavigate: (page: string) => void;
  onOpenProject: (projectId: string) => void;
  onOpenAgent: () => void;
}

function latestBy<T>(rows: T[], select: (row: T) => string) {
  return [...rows].sort((left, right) => select(right).localeCompare(select(left)))[0];
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "negative" | "primary" }) {
  return <div className={`liquid-home-metric ${tone ? `is-${tone}` : ""}`}><span>{label}</span><strong>{value}</strong></div>;
}

export function LiquidGlassHome({ snapshot, onNavigate, onOpenProject, onOpenAgent }: LiquidGlassHomeProps) {
  const summary = useMemo(() => getBusinessSummary(snapshot), [snapshot]);
  const latestPayment = latestBy(snapshot.payments.filter((payment) => payment.status === "confirmed"), (payment) => payment.paidAt);
  const latestExpense = latestBy(snapshot.expenses, (expense) => expense.paidAt);
  const outstandingProject = [...summary.projectFinancials]
    .filter((item) => item.outstanding > 0)
    .sort((left, right) => right.outstanding - left.outstanding)[0];
  const activeProjects = snapshot.projects.filter((project) => project.status === "in_progress");
  const relevantProjects = [...snapshot.projects]
    .sort((left, right) => right.dueDate.localeCompare(left.dueDate))
    .slice(0, 4);
  const linkedProductCount = new Set(snapshot.projects.map((project) => project.itemExternalId).filter(Boolean)).size;
  const actualHours = snapshot.tasks.reduce((sum, task) => sum + task.actualHours, 0);
  const evidenceChecks = [snapshot.payments.length > 0, snapshot.expenses.length > 0, actualHours > 0, snapshot.logs.length > 0 || snapshot.attachments.length > 0];
  const confidence = evidenceChecks.filter(Boolean).length * 25;
  const dateLabel = fullDate.format(new Date()).replaceAll("/", "-");
  const actualProfit = summary.actualProfit;

  const judgment = outstandingProject
    ? `先核对 ${money.format(outstandingProject.outstanding)} 待回款，再安排新的经营投入。`
    : actualProfit < 0
      ? "先核对成本与利润口径，再决定是否扩大投入。"
      : "先补齐客户、商品与交付证据，再推进下一项经营动作。";

  const timeline: TimelineEntry[] = [
    {
      id: "income",
      eyebrow: latestPayment ? eventTime.format(new Date(latestPayment.paidAt)) : "收入",
      title: latestPayment ? "最近一笔收入已入账" : "收入证据仍为空",
      description: latestPayment
        ? snapshot.projects.find((project) => project.id === latestPayment.projectId)?.name || "已确认收款"
        : "确认到账后才会进入经营汇总。",
      value: latestPayment ? money.format(latestPayment.amount) : "暂无",
      valueLabel: latestPayment ? "已确认" : "待补充",
      tone: "blue",
      icon: Wallet,
      action: () => onNavigate("经营记录"),
    },
    {
      id: "profit",
      eyebrow: "实时汇总",
      title: "实际利润已更新",
      description: `净收入 ${money.format(summary.totalIncome)} - 支出 ${money.format(summary.totalExpenses)}`,
      value: money.format(actualProfit),
      valueLabel: "待人工核对",
      tone: actualProfit < 0 ? "coral" : "blue",
      icon: ChartLineDown,
      action: () => onNavigate("经营记录"),
    },
    {
      id: "receivable",
      eyebrow: outstandingProject ? `交付 ${outstandingProject.project.dueDate.slice(5)}` : "待回款",
      title: outstandingProject ? "项目仍有待回款" : "当前项目已结清",
      description: outstandingProject?.project.name || "没有未结清的客户项目。",
      value: outstandingProject ? money.format(outstandingProject.outstanding) : money.format(0),
      valueLabel: outstandingProject ? "待核对" : "已结清",
      tone: outstandingProject ? "violet" : "slate",
      icon: Coins,
      action: () => outstandingProject ? onOpenProject(outstandingProject.project.id) : onNavigate("项目管理"),
    },
    {
      id: "delivery",
      eyebrow: "项目",
      title: "项目进度需要人工确认",
      description: `${activeProjects.length} 个进行中 · ${snapshot.tasks.filter((task) => task.status === "done").length}/${snapshot.tasks.length} 项任务完成`,
      value: `${activeProjects.length} 个`,
      valueLabel: "查看项目",
      tone: "violet",
      icon: Briefcase,
      action: () => onNavigate("项目管理"),
    },
    {
      id: "projects",
      eyebrow: "交付范围",
      title: `项目清单（${snapshot.projects.length} 个）`,
      description: relevantProjects.length ? relevantProjects.map((project) => `${project.name} · ${projectStatus[project.status]}`).join("；") : "暂无项目，请先建立真实项目。",
      value: `${actualHours}h`,
      valueLabel: "实际工时",
      tone: "slate",
      icon: FileText,
      action: () => onNavigate("项目管理"),
    },
    {
      id: "evidence",
      eyebrow: "关系证据",
      title: "客户与商品关系",
      description: `${snapshot.customers.length} 位客户 · ${linkedProductCount} 个项目来源商品；未关联内容不会自动推断。`,
      value: linkedProductCount ? `${linkedProductCount} 个` : "暂无",
      valueLabel: "来源商品",
      tone: "slate",
      icon: UsersThree,
      action: () => onNavigate(linkedProductCount ? "商品经营" : "客户管理"),
    },
  ];

  const primaryLabel = outstandingProject ? "去核对待回款" : actualProfit < 0 ? "核对经营记录" : "查看项目状态";
  const primaryAction = outstandingProject
    ? () => onOpenProject(outstandingProject.project.id)
    : actualProfit < 0
      ? () => onNavigate("经营记录")
      : () => onNavigate("项目管理");

  return <section className="liquid-home" aria-labelledby="liquid-home-title">
    <header className="liquid-home-intro">
      <div>
        <span>{dateLabel}</span>
        <h2 id="liquid-home-title">早安，{snapshot.settings.profileName || "开发者"}！</h2>
        <p>{judgment}</p>
      </div>
      <section className="liquid-home-metrics" aria-label="经营核心指标">
        <Metric label="累计净收入" value={money.format(summary.totalIncome)} tone="primary" />
        <Metric label="实际利润" value={money.format(actualProfit)} tone={actualProfit < 0 ? "negative" : "primary"} />
        <Metric label="待回款" value={money.format(summary.outstanding)} tone="primary" />
        <Metric label="进行中项目" value={`${activeProjects.length} 个`} tone="primary" />
      </section>
    </header>

    <div className="liquid-home-workspace">
      <section className="liquid-dayline-panel" aria-labelledby="liquid-dayline-title">
        <header>
          <div><span>OPERATING DAYLINE</span><h3 id="liquid-dayline-title">今天的经营时间线</h3></div>
          <button type="button" onClick={() => onNavigate("经营记录")}>查看完整记录 <ArrowRight size={16} /></button>
        </header>
        <div className="liquid-dayline-list">
          <img className="liquid-dayline-asset" src="/assets/liquid-glass/refractive-dayline.png" alt="" aria-hidden="true" />
          {timeline.map(({ id, eyebrow, title, description, value, valueLabel, tone, icon: Icon, action }, index) => <article className={`liquid-dayline-entry is-${tone}`} key={id}>
            <time>{eyebrow}</time>
            <span className="liquid-dayline-node" aria-hidden="true"><i /></span>
            <button type="button" onClick={action}>
              <i className="liquid-entry-icon"><Icon size={18} weight="duotone" /></i>
              <span><strong>{title}</strong><small>{description}</small></span>
              <em><b>{value}</b><small>{valueLabel}</small></em>
              {index !== 4 && <ArrowRight className="liquid-entry-arrow" size={15} />}
            </button>
          </article>)}
        </div>
      </section>

      <aside className="liquid-inspector" aria-labelledby="liquid-inspector-title">
        <header><span><ShieldCheck size={19} weight="duotone" />小策观察</span><button type="button" onClick={onOpenAgent}>询问小策</button></header>
        <section>
          <h3 id="liquid-inspector-title">既有事实</h3>
          <ul>
            <li><CheckCircle size={15} weight="fill" />净收入：{money.format(summary.totalIncome)}</li>
            <li><CheckCircle size={15} weight="fill" />实际利润：{money.format(actualProfit)}</li>
            <li><CheckCircle size={15} weight="fill" />待回款：{money.format(summary.outstanding)}</li>
            <li><CheckCircle size={15} weight="fill" />实际工时：{actualHours} 小时</li>
            <li><Package size={15} />商品关系：{linkedProductCount ? `${linkedProductCount} 个来源商品` : "暂无可用证据"}</li>
          </ul>
        </section>
        <section>
          <h3>反方观点</h3>
          <p>{outstandingProject ? "待回款不等于坏账；实际利润也可能受一次性成本影响，应先核对账本与交付状态。" : "当前账本可能仍缺少线下成本、退款或未登记工时，不能只按汇总值判断经营质量。"}</p>
        </section>
        <section>
          <h3>失效条件</h3>
          <ul className="is-warning">
            <li><WarningCircle size={15} />账本仍有未录入收支</li>
            <li><WarningCircle size={15} />项目状态或实际工时未更新</li>
            <li><WarningCircle size={15} />客户与商品关系缺少证据</li>
          </ul>
        </section>
        <section className="liquid-confidence">
          <span><small>判断置信度</small><strong>{confidence} / 100</strong></span>
          <div aria-label={`判断置信度 ${confidence} / 100`}><i style={{ width: `${confidence}%` }} /></div>
          <p>根据收款、支出、工时和交付证据完整度计算，不代表成交概率。</p>
        </section>
        <footer>
          <span><Receipt size={18} /><small>人工下一步</small><b>{primaryLabel}</b></span>
          <button type="button" onClick={primaryAction}>{primaryLabel} <ArrowRight size={16} /></button>
        </footer>
      </aside>
    </div>
    {latestExpense && <p className="liquid-home-footnote"><ClockCountdown size={15} />最近支出：{latestExpense.name} · {money.format(latestExpense.amount)} · {eventTime.format(new Date(latestExpense.paidAt))}</p>}
  </section>;
}
