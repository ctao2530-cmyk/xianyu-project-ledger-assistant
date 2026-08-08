import {
  BellRinging,
  CheckCircle,
  Gauge,
  Plus,
  TrendUp,
  Wallet,
  WarningCircle,
} from "@phosphor-icons/react";
import { type ReactNode, useState } from "react";
import { daysUntil, getBusinessSummary } from "../data/businessMetrics";
import { projectKindOf } from "../data/projectKinds";
import { latestSettlementIssue, settlementIssueLabels } from "../data/settlementIssues";
import type { LedgerSnapshot, PaymentStatus, PaymentType, Project } from "../types";

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
});

const paymentLabel: Record<PaymentType, string> = {
  deposit: "定金",
  milestone: "阶段款",
  final: "尾款",
  full: "全款",
};

const paymentStatusLabel: Record<PaymentStatus, string> = {
  pending: "待收款",
  confirmed: "已到账",
  refunded: "已退款",
  written_off: "已核销",
};

const projectStatusLabel: Record<Project["status"], string> = {
  pending: "待开始",
  in_progress: "进行中",
  delivered: "已交付",
  completed: "已完成",
  overdue: "已逾期",
};

const shortDate = (value: string) => new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
}).format(new Date(value));

function Surface({ className = "", children }: { className?: string; children: ReactNode }) {
  return <section className={`business-surface ${className}`}>{children}</section>;
}

function SurfaceTitle({ title, eyebrow, action }: { title: string; eyebrow?: string; action?: ReactNode }) {
  return <header className="business-surface-title"><div>{eyebrow && <span>{eyebrow}</span>}<h2>{title}</h2></div>{action}</header>;
}

function Metric({ label, value, detail, tone, icon: Icon }: { label: string; value: string; detail: string; tone: string; icon: typeof Wallet }) {
  return <Surface className={`business-metric business-${tone}`}><span className="business-metric-icon"><Icon size={24} weight="duotone" /></span><small>{label}</small><strong>{value}</strong><p>{detail}</p></Surface>;
}

function Progress({ value }: { value: number }) {
  return <div className="business-progress"><i className="business-progress-green" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} /></div>;
}

export function EnhancedIncomeRecordsPage({
  snapshot,
  onQuickAdd,
  onCreatePaymentPlan,
  onConfirmPayment,
  onRecordSettlementIssue,
  onSnapshotChange,
  globalSearch,
}: {
  snapshot: LedgerSnapshot;
  onQuickAdd: () => void;
  onCreatePaymentPlan: (projectId: string) => void;
  onConfirmPayment: (projectId: string, paymentId?: string) => void;
  onRecordSettlementIssue: (projectId: string) => void;
  onSnapshotChange: (snapshot: LedgerSnapshot) => void;
  globalSearch: string;
}) {
  const summary = getBusinessSummary(snapshot);
  const clientProjects = snapshot.projects.filter((project) => projectKindOf(project) === "client");
  const clientFinancials = summary.projectFinancials.filter(({ project }) => projectKindOf(project) === "client");
  const [selected, setSelected] = useState(clientProjects[0]?.id || "");
  const [reminded, setReminded] = useState<string | null>(null);
  const selectedId = clientProjects.some((item) => item.id === selected) ? selected : clientProjects[0]?.id || "";
  const selectedProject = clientProjects.find((item) => item.id === selectedId);
  const selectedFinancial = clientFinancials.find((item) => item.project.id === selectedId);
  const selectedIssues = selectedFinancial?.settlementIssues.slice().sort((left, right) => right.occurredAt.localeCompare(left.occurredAt)) || [];
  const latestSelectedIssue = latestSettlementIssue(selectedIssues);
  const projectPayments = snapshot.payments
    .filter((item) => item.projectId === selectedId)
    .sort((left, right) => left.dueAt.localeCompare(right.dueAt));
  const pendingNodes = snapshot.payments
    .filter((item) => item.status === "pending")
    .sort((left, right) => left.dueAt.localeCompare(right.dueAt));
  const unsettled = clientFinancials
    .filter((item) => item.outstanding > 0)
    .sort((left, right) => {
      const deliveredPriority = Number(right.project.status === "delivered") - Number(left.project.status === "delivered");
      if (deliveredPriority) return deliveredPriority;
      const dateOrder = left.project.dueDate.localeCompare(right.project.dueDate);
      return dateOrder || right.outstanding - left.outstanding;
    });
  const normalizedSearch = globalSearch.trim().toLowerCase();
  const visibleUnsettled = unsettled.filter(({ project }) => {
    const customer = snapshot.customers.find((item) => item.id === project.customerId);
    return `${project.name} ${customer?.name || ""}`.toLowerCase().includes(normalizedSearch);
  });
  const matchingPayments = snapshot.payments.filter((payment) => {
    const project = snapshot.projects.find((item) => item.id === payment.projectId);
    const customer = snapshot.customers.find((item) => item.id === payment.customerId);
    return `${project?.name || ""} ${customer?.name || ""} ${paymentLabel[payment.type]} ${paymentStatusLabel[payment.status]}`.toLowerCase().includes(normalizedSearch);
  });
  const totalContract = clientProjects.reduce((sum, item) => sum + item.totalAmount, 0);
  const clientNetIncome = clientFinancials.reduce((sum, item) => sum + item.income, 0);
  const clientRefunded = clientFinancials.reduce((sum, item) => sum + item.refundedAmount, 0);
  const clientUncollectible = clientFinancials.reduce((sum, item) => sum + item.uncollectible, 0);
  const clientOutstanding = clientFinancials.reduce((sum, item) => sum + item.outstanding, 0);
  const netCollectionRate = totalContract ? Math.min(100, Math.max(0, clientNetIncome / totalContract * 100)) : 0;
  const overdueCount = pendingNodes.filter((payment) => daysUntil(payment.dueAt) <= 0).length;
  const nearDueCount = pendingNodes.filter((payment) => daysUntil(payment.dueAt) <= 7).length;
  const deliveredUnpaid = unsettled.filter(({ project }) => project.status === "delivered").length;
  const unplannedCount = unsettled.filter(({ project }) => !snapshot.payments.some((payment) => payment.projectId === project.id && payment.status === "pending")).length;
  const recentCutoff = Date.now() - 30 * 86_400_000;
  const issueRiskProjects = clientFinancials.filter((financial) => financial.settlementIssues.some((issue) => (
    financial.outstanding > 0 || new Date(issue.occurredAt).getTime() >= recentCutoff
  )));
  const healthScore = unsettled.length === 0 && issueRiskProjects.length === 0
    ? 100
    : Math.max(0, 100
      - deliveredUnpaid * 24
      - overdueCount * 20
      - unplannedCount * 10
      - Math.max(0, nearDueCount - overdueCount) * 6
      - issueRiskProjects.length * 18);
  const healthNeedsAttention = healthScore < 80 || issueRiskProjects.length > 0;
  const healthLabel = issueRiskProjects.length > 0
    ? "需关注"
    : healthScore >= 80
      ? "健康"
      : healthScore >= 60
        ? "需关注"
        : "有风险";
  const latestClientIssue = clientFinancials
    .flatMap((financial) => financial.settlementIssues.map((issue) => ({ issue, financial })))
    .sort((left, right) => right.issue.occurredAt.localeCompare(left.issue.occurredAt))[0];
  const grossReceiptNodeCount = snapshot.payments.filter((item) => item.status === "confirmed" || item.status === "refunded").length;

  const remindCustomer = (projectId: string) => {
    const project = snapshot.projects.find((item) => item.id === projectId);
    if (!project) return;
    onSnapshotChange({
      ...snapshot,
      customers: snapshot.customers.map((customer) => customer.id === project.customerId ? {
        ...customer,
        lastContactAt: new Date().toISOString(),
        followUpStatus: customer.followUpStatus === "new" ? "contacted" : customer.followUpStatus,
      } : customer),
    });
    setReminded(projectId);
  };

  if (!selectedProject || !selectedFinancial) {
    return <div className="business-page enhanced-income-page">
      <section className="business-metrics-grid">
        <Metric label="净到账" value={money.format(0)} detail="扣除退款后的真实留存" tone="purple" icon={Wallet} />
        <Metric label="可收余额" value={money.format(0)} detail="0 个项目尚未结清" tone="orange" icon={BellRinging} />
        <Metric label="退款 / 核销" value={money.format(0)} detail="退款 ¥0 · 核销 ¥0" tone="green" icon={WarningCircle} />
        <Metric label="净回款率" value="0%" detail="按接单项目合同额计算" tone="blue" icon={Gauge} />
      </section>
      <Surface className="business-empty-state"><i><Wallet size={42} weight="duotone" /></i><h3>还没有接单项目</h3><p>先创建接单项目，之后即使没有付款节点，也可以直接确认真实到账。</p><button className="business-primary" onClick={onQuickAdd}><Plus size={16} />记录第一笔收款</button></Surface>
    </div>;
  }

  return <div className="business-page enhanced-income-page">
    <section className="business-metrics-grid">
      <Metric label="净到账" value={money.format(clientNetIncome)} detail={clientRefunded ? `累计退款 ${money.format(clientRefunded)}` : "扣除退款后的真实留存"} tone="purple" icon={Wallet} />
      <Metric label="可收余额" value={money.format(clientOutstanding)} detail={`${unsettled.length} 个项目尚未结清`} tone="orange" icon={BellRinging} />
      <Metric label="退款 / 核销" value={money.format(clientRefunded + clientUncollectible)} detail={`退款 ${money.format(clientRefunded)} · 核销 ${money.format(clientUncollectible)}`} tone="green" icon={WarningCircle} />
      <Metric label="净回款率" value={`${Math.round(netCollectionRate)}%`} detail="净到账 ÷ 接单合同总额" tone="blue" icon={Gauge} />
    </section>

    <Surface className="outstanding-projects-panel">
      <SurfaceTitle eyebrow="OUTSTANDING PROJECTS" title={globalSearch ? `待回款项目 · ${visibleUnsettled.length}` : "待回款项目"} action={<span className="outstanding-total">合计可收 {money.format(clientOutstanding)}</span>} />
      {visibleUnsettled.length ? <div className="outstanding-project-list">{visibleUnsettled.map((financial) => {
        const { project } = financial;
        const customer = snapshot.customers.find((item) => item.id === project.customerId);
        const nodes = snapshot.payments.filter((item) => item.projectId === project.id && item.status === "pending");
        const latestIssue = latestSettlementIssue(financial.settlementIssues);
        return <article className={`${project.status === "delivered" ? "is-delivered" : ""} ${latestIssue ? "has-settlement-issue" : ""}`} key={project.id}>
          <i><Wallet size={20} weight="duotone" /></i>
          <span><small>{customer?.name || "未关联客户"} · {projectStatusLabel[project.status]}</small><b>{project.name}</b><em className={latestIssue ? "is-exception" : ""}>{latestIssue ? settlementIssueLabels[latestIssue.type] : nodes.length ? `${nodes.length} 个待收节点` : "未建立付款节点"}</em></span>
          <div><small>合同额</small><b>{money.format(project.totalAmount)}</b></div>
          <div><small>净到账</small><b className="positive">{money.format(financial.income)}</b></div>
          <div><small>可收</small><b className="warning">{money.format(financial.outstanding)}</b></div>
          <div className="outstanding-row-actions"><button className="business-primary" type="button" onClick={() => onConfirmPayment(project.id)}><CheckCircle size={15} weight="fill" />确认到账</button><button className="business-secondary is-exception" type="button" onClick={() => onRecordSettlementIssue(project.id)}><WarningCircle size={15} weight="duotone" />记录异常</button></div>
        </article>;
      })}</div> : <div className="income-nodes-empty"><CheckCircle size={28} weight="duotone" /><span><b>{globalSearch ? "没有匹配的待回款项目" : "所有项目可收余额已经结清"}</b><small>{globalSearch ? "调整搜索词后再试。" : "已结清项目仍可在下方记录退款或客户争议。"}</small></span></div>}
    </Surface>

    <section className="income-workspace">
      <main>
        <Surface>
          <SurfaceTitle eyebrow="PROJECT PAYMENT" title="项目回款与结算" action={<div className="income-actions"><select value={selectedId} onChange={(event) => setSelected(event.target.value)}>{clientProjects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select>{selectedFinancial.outstanding > 0 && <button className="business-primary" onClick={() => onConfirmPayment(selectedProject.id)}><CheckCircle size={16} />确认到账</button>}<button className="business-secondary is-exception" type="button" onClick={() => onRecordSettlementIssue(selectedProject.id)}><WarningCircle size={16} />记录异常</button></div>} />
          {selectedProject.status === "delivered" && selectedFinancial.outstanding > 0 && <div className="income-delivered-alert"><WarningCircle size={17} weight="fill" /><span><b>已交付待回款 {money.format(selectedFinancial.outstanding)}</b><small>请在核对实际入账后确认，不会自动改变项目状态。</small></span></div>}
          {latestSelectedIssue && <div className="income-settlement-alert"><WarningCircle size={17} weight="fill" /><span><b>{settlementIssueLabels[latestSelectedIssue.type]} · 共 {selectedIssues.length} 条异常</b><small>{latestSelectedIssue.reason}</small></span><button type="button" onClick={() => onRecordSettlementIssue(selectedProject.id)}>继续记录</button></div>}
          <div className="collection-overview"><div><small>{selectedProject.name}</small><strong>{money.format(selectedFinancial.income)} <span>/ {money.format(selectedProject.totalAmount)}</span></strong><Progress value={selectedFinancial.paymentProgress} /><p><span>净回款率 {selectedFinancial.paymentProgress.toFixed(0)}%</span><b>可收 {money.format(selectedFinancial.outstanding)}</b></p></div><i><Wallet size={43} weight="duotone" /></i></div>
          <div className="collection-financial-breakdown">
            <span><small>累计入账</small><b>{money.format(selectedFinancial.grossIncome)}</b></span>
            <span><small>实际退款</small><b className={selectedFinancial.refundedAmount ? "negative" : ""}>{money.format(selectedFinancial.refundedAmount)}</b></span>
            <span><small>确认核销</small><b className={selectedFinancial.uncollectible ? "warning" : ""}>{money.format(selectedFinancial.uncollectible)}</b></span>
            <span><small>结算完成度</small><b>{selectedFinancial.settlementProgress.toFixed(0)}%</b></span>
          </div>
          {projectPayments.length ? <div className="payment-timeline">{projectPayments.map((payment, index) => <article className={payment.status === "confirmed" ? "paid" : payment.status === "refunded" ? "refunded" : payment.status === "written_off" ? "written-off" : ""} key={payment.id}><div><i>{payment.status === "confirmed" ? <CheckCircle size={18} weight="fill" /> : payment.status === "refunded" || payment.status === "written_off" ? <WarningCircle size={18} weight="fill" /> : index + 1}</i><span /></div><small>{paymentLabel[payment.type]}</small><strong>{money.format(payment.amount)}</strong><time>{shortDate(payment.dueAt)}</time><em>{payment.status === "pending" ? daysUntil(payment.dueAt) <= 1 ? "即将到期" : "待收款" : paymentStatusLabel[payment.status]}</em>{payment.status === "pending" && <button type="button" onClick={() => onConfirmPayment(selectedProject.id, payment.id)}>确认到账</button>}</article>)}</div> : <div className="payment-plan-inline-empty"><span><b>{selectedFinancial.outstanding > 0 ? "尚未建立付款节点" : "项目没有独立付款节点"}</b><small>{selectedFinancial.outstanding > 0 ? "可以直接确认已到账，系统会按合同余额创建收款记录；也可以先记录拒付或取消合作。" : "可收余额已完成结算，后续退款或客户争议仍可继续记录。"}</small></span><div>{selectedFinancial.outstanding > 0 && <button type="button" className="business-primary" onClick={() => onConfirmPayment(selectedProject.id)}>确认已到账</button>}{selectedFinancial.outstanding > 0 && <button type="button" onClick={() => onCreatePaymentPlan(selectedProject.id)}>建立收款计划</button>}<button type="button" className="is-exception" onClick={() => onRecordSettlementIssue(selectedProject.id)}>记录异常</button></div></div>}
        </Surface>

        <Surface className="income-settlement-history">
          <SurfaceTitle eyebrow="EXCEPTION HISTORY" title={`项目异常记录 · ${selectedIssues.length}`} action={<button className="business-secondary is-exception" type="button" onClick={() => onRecordSettlementIssue(selectedProject.id)}><Plus size={14} />记录异常</button>} />
          {selectedIssues.length ? <div>{selectedIssues.map((issue) => <article key={issue.id}><i><WarningCircle size={18} weight="duotone" /></i><span><small>{shortDate(issue.occurredAt)} · {settlementIssueLabels[issue.type]}</small><b>{issue.reason}</b>{issue.notes && <em>{issue.notes}</em>}</span><dl><div><dt>无法收回</dt><dd>{money.format(issue.receivableImpact)}</dd></div><div><dt>实际退款</dt><dd>{money.format(issue.refundAmount)}</dd></div></dl></article>)}</div> : <div className="project-settlement-empty"><CheckCircle size={23} weight="duotone" /><span><b>暂无客户或回款异常</b><small>客户不满意、退款、取消合作或拒付时，可在这里记录原因和金额影响。</small></span></div>}
        </Surface>

        <Surface>
          <SurfaceTitle eyebrow="ALL NODES" title={globalSearch ? `收款节点搜索结果 · ${matchingPayments.length}` : "全部收款节点"} />
          {matchingPayments.length ? <div className="income-node-table"><div><span>项目 / 客户</span><span>类型</span><span>金额</span><span>计划日期</span><span>状态</span><span>净回款率</span></div>{matchingPayments.map((payment) => {
            const project = snapshot.projects.find((item) => item.id === payment.projectId);
            const customer = snapshot.customers.find((item) => item.id === payment.customerId);
            const financial = clientFinancials.find((item) => item.project.id === project?.id);
            if (!project || !financial) return null;
            return <article key={payment.id}><span><b>{project.name}</b><small>{customer?.name || "未关联客户"}</small></span><em>{paymentLabel[payment.type]}</em><strong className={payment.status === "refunded" || payment.status === "written_off" ? "is-exception" : ""}>{money.format(payment.amount)}</strong><time>{shortDate(payment.dueAt)}</time><i className={`payment-status-${payment.status}`}>{paymentStatusLabel[payment.status]}</i><span><Progress value={financial.paymentProgress} /><small>{financial.paymentProgress.toFixed(0)}%</small></span></article>;
          })}</div> : <div className="income-nodes-empty"><Wallet size={28} weight="duotone" /><span><b>合同余额尚未拆分为付款节点</b><small>{unsettled.length ? "仍可从上方待回款项目直接确认到账，或先建立收款计划。" : "当前没有待处理的收款节点。"}</small></span>{unsettled[0] && <div><button type="button" className="business-primary" onClick={() => onConfirmPayment(unsettled[0].project.id)}>确认到账</button><button type="button" onClick={() => onCreatePaymentPlan(unsettled[0].project.id)}>建立收款计划</button><button type="button" className="is-exception" onClick={() => onRecordSettlementIssue(unsettled[0].project.id)}>记录异常</button></div>}</div>}
        </Surface>
      </main>

      <aside>
        <Surface>
          <SurfaceTitle eyebrow="REMINDERS" title="收款提醒" action={<span className="reminder-count">{unsettled.length + (latestClientIssue ? 1 : 0)}</span>} />
          <div className="collection-reminders">{latestClientIssue && <article className="exception" key={`issue-${latestClientIssue.issue.id}`}><i><WarningCircle size={18} weight="duotone" /></i><span><b>{latestClientIssue.financial.project.name}</b><small>{settlementIssueLabels[latestClientIssue.issue.type]} · {latestClientIssue.issue.reason}</small></span><em>{shortDate(latestClientIssue.issue.occurredAt)}</em><div><button className="confirm is-exception" type="button" onClick={() => { setSelected(latestClientIssue.financial.project.id); onRecordSettlementIssue(latestClientIssue.financial.project.id); }}>查看并记录</button></div></article>}{unsettled.slice(0, 5).map((financial) => {
            const { project } = financial;
            const urgent = project.status === "delivered" || daysUntil(project.dueDate) <= 1;
            return <article className={urgent ? "urgent" : ""} key={project.id}><i><BellRinging size={18} weight="duotone" /></i><span><b>{project.name}</b><small>{project.status === "delivered" ? "已交付待回款" : "合同余额待确认"} · {money.format(financial.outstanding)}</small></span><em>{project.status === "delivered" ? "优先处理" : `${Math.max(0, daysUntil(project.dueDate))}天后交付`}</em><div><button className="confirm" type="button" onClick={() => onConfirmPayment(project.id)}>确认到账</button><button type="button" onClick={() => remindCustomer(project.id)} disabled={reminded === project.id}>{reminded === project.id ? "已记录提醒" : "提醒客户"}</button></div></article>;
          })}{unsettled.length === 0 && !latestClientIssue && <div className="compact-collection-empty"><CheckCircle size={24} weight="duotone" /><span><b>暂无待处理结算事项</b><small>所有合同余额已经结清，且没有异常记录。</small></span></div>}</div>
        </Surface>
        <Surface className={`collection-health ${healthNeedsAttention ? "needs-attention" : ""}`}>
          <SurfaceTitle eyebrow="CASH FLOW" title="回款健康度" />
          <div className="health-score"><strong>{healthScore}</strong><span><b>{healthLabel}</b><small>{issueRiskProjects.length ? `${issueRiskProjects.length} 个项目有近期或未结异常` : unsettled.length ? `${unsettled.length} 个项目尚未结清` : "全部合同余额已结清"}</small></span></div>
          <ul><li><CheckCircle size={16} weight="fill" />累计实际入账 {grossReceiptNodeCount} 个节点</li><li><WarningCircle size={16} weight="fill" />{deliveredUnpaid} 个已交付项目仍未结清</li><li><WarningCircle size={16} weight="fill" />{unplannedCount} 个项目未建立待收节点</li><li className={issueRiskProjects.length ? "is-exception" : ""}><WarningCircle size={16} weight="fill" />{issueRiskProjects.length} 个项目有近期或未结异常</li></ul>
        </Surface>
      </aside>
    </section>
  </div>;
}
