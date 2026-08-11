import {
  ArrowLeft,
  ArrowRight,
  BellRinging,
  BookOpenText,
  Brain,
  Briefcase,
  CalendarBlank,
  CaretRight,
  ChartLineUp,
  ChatCircleDots,
  CheckCircle,
  CircleNotch,
  Clock,
  Code,
  Coins,
  File,
  FileArchive,
  FileText,
  FolderSimple,
  FolderOpen,
  Gauge,
  House,
  Lightbulb,
  ListChecks,
  MagicWand,
  MagnifyingGlass,
  NotePencil,
  Paperclip,
  PencilSimple,
  Plus,
  Robot,
  ShieldCheck,
  Sparkle,
  Stack,
  Target,
  Timer,
  TrendUp,
  UploadSimple,
  UserCircle,
  UsersThree,
  WarningCircle,
  Wallet,
  X,
  type Icon as PhosphorIcon,
} from "@phosphor-icons/react";
import { type ChangeEvent, type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  daysBetween,
  daysUntil,
  getBusinessSummary,
  getCustomerBusiness,
  getProjectFinancials,
} from "../data/businessMetrics";
import { localPlatformService, type BusinessQuote, type BusinessRequirementAnalysis, type BusinessReview } from "../data/localPlatformService";
import { projectKindOf } from "../data/projectKinds";
import { hasTerminalSettlementIssue, latestSettlementIssue, settlementIssueLabels } from "../data/settlementIssues";
import type {
  CustomerFollowUpStatus,
  LedgerSnapshot,
  PaymentType,
  Project,
  ProjectAttachment,
  ProjectKind,
  ProjectLog,
  ProjectTask,
  TaskStatus,
} from "../types";
import { ImmersiveTaskFlow } from "./ImmersiveTaskFlow";
import { ProjectTaskEditor } from "./ProjectTaskEditor";
import "./business-assistant.css";
import "./customer-classification.css";

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
});

const shortDate = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "待联系"
    : new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(date);
};

const paymentLabel: Record<PaymentType, string> = {
  deposit: "定金",
  milestone: "阶段款",
  final: "尾款",
  full: "全款",
};

const taskLabel: Record<TaskStatus, string> = {
  todo: "待开始",
  in_progress: "进行中",
  done: "已完成",
};

const projectKindLabel: Record<ProjectKind, string> = {
  personal: "个人项目",
  client: "接单项目",
};

const projectStatusLabel: Record<Project["status"], string> = {
  pending: "待开始",
  in_progress: "进行中",
  delivered: "已交付",
  completed: "已完成",
  overdue: "已逾期",
};

export type ProjectDetailTab = "overview" | "tasks" | "gantt" | "immersive" | "communication" | "quote" | "logs" | "files";

export interface ProjectPageRoute {
  projectId: string;
  tab: ProjectDetailTab;
}

export type ProjectRouteMode = "push" | "replace" | "back";

const followLabel: Record<CustomerFollowUpStatus, string> = {
  new: "新线索",
  contacted: "已联系",
  proposal: "报价中",
  won: "已成交",
  inactive: "暂缓跟进",
};

function Surface({ className = "", children }: { className?: string; children: ReactNode }) {
  return <section className={`business-surface ${className}`}>{children}</section>;
}

function SurfaceTitle({
  title,
  eyebrow,
  action,
}: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
}) {
  return <header className="business-surface-title"><div>{eyebrow && <span>{eyebrow}</span>}<h2>{title}</h2></div>{action}</header>;
}

function BusinessMetric({
  label,
  value,
  detail,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "purple" | "blue" | "green" | "orange";
  icon: PhosphorIcon;
}) {
  return <Surface className={`business-metric business-${tone}`}><span className="business-metric-icon"><Icon size={24} weight="duotone" /></span><small>{label}</small><strong>{value}</strong><p>{detail}</p></Surface>;
}

function ProjectKindSwitch({
  value,
  counts,
  onChange,
}: {
  value: ProjectKind;
  counts: Record<ProjectKind, number>;
  onChange: (kind: ProjectKind) => void;
}) {
  return <div className="project-kind-switch" role="group" aria-label="项目分类">
    <button type="button" className={value === "personal" ? "active" : ""} aria-pressed={value === "personal"} onClick={() => onChange("personal")}><Code size={18} weight="duotone" /><span><b>个人项目</b><small>{counts.personal} 个项目</small></span></button>
    <button type="button" className={value === "client" ? "active" : ""} aria-pressed={value === "client"} onClick={() => onChange("client")}><Briefcase size={18} weight="duotone" /><span><b>接单项目</b><small>{counts.client} 个项目</small></span></button>
  </div>;
}

function WorkspaceMetric({ icon: Icon, label, value, detail, tone, action }: { icon: PhosphorIcon; label: string; value: string; detail: string; tone: "purple" | "blue" | "green" | "orange"; action?: ReactNode }) {
  return <article className={`project-workspace-metric workspace-${tone}`}><i><Icon size={20} weight="duotone" /></i><span><small>{label}</small><strong>{value}</strong><em>{detail}</em></span>{action && <div className="workspace-metric-action">{action}</div>}</article>;
}

function BusinessEmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: PhosphorIcon;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return <Surface className="business-empty-state"><i><Icon size={42} weight="duotone" /></i><h3>{title}</h3><p>{description}</p>{action}</Surface>;
}

function BarProgress({ value, tone = "purple" }: { value: number; tone?: string }) {
  return <div className="business-progress"><i className={`business-progress-${tone}`} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} /></div>;
}

export function ProjectDetail({
  snapshot,
  projectId,
  tab,
  onBack,
  onTabChange,
  onCreatePaymentPlan,
  onCreateChangeOrder,
  onConfirmPayment,
  onRecordSettlementIssue,
  onSnapshotChange,
}: {
  snapshot: LedgerSnapshot;
  projectId: string;
  tab: ProjectDetailTab;
  onBack: () => void;
  onTabChange: (tab: ProjectDetailTab) => void;
  onCreatePaymentPlan: (projectId: string) => void;
  onCreateChangeOrder: (projectId: string) => void;
  onConfirmPayment: (projectId: string, paymentId?: string) => void;
  onRecordSettlementIssue: (projectId: string) => void;
  onSnapshotChange: (snapshot: LedgerSnapshot) => void;
}) {
  const project = snapshot.projects.find((item) => item.id === projectId)!;
  const customer = snapshot.customers.find((item) => item.id === project.customerId);
  const financial = getProjectFinancials(snapshot).find((item) => item.project.id === project.id)!;
  const projectIssues = financial.settlementIssues.slice().sort((left, right) => right.occurredAt.localeCompare(left.occurredAt));
  const projectTerminated = hasTerminalSettlementIssue(projectIssues);
  const latestIssue = latestSettlementIssue(projectIssues);
  const projectPayments = snapshot.payments.filter((item) => item.projectId === project.id);
  const projectChangeOrders = snapshot.changeOrders
    .filter((item) => item.projectId === project.id && item.status === "confirmed")
    .sort((left, right) => left.confirmedAt.localeCompare(right.confirmedAt));
  const changeOrderTotal = projectChangeOrders.reduce((sum, item) => sum + item.amount, 0);
  const baseContractAmount = Math.max(0, project.totalAmount - changeOrderTotal);
  const paymentGroups = [
    {
      id: "base-contract",
      title: "原合同",
      detail: `原合同金额 ${money.format(baseContractAmount)}`,
      amount: baseContractAmount,
      payments: projectPayments.filter((item) => !item.changeOrderId),
    },
    ...projectChangeOrders.map((order, index) => ({
      id: order.id,
      title: `追加订单 #${index + 1} · ${order.title}`,
      detail: `${shortDate(order.confirmedAt)} 客户确认`,
      amount: order.amount,
      payments: projectPayments.filter((item) => item.changeOrderId === order.id),
    })),
  ].filter((group) => group.payments.length > 0);
  const pendingPayments = projectPayments.filter((item) => item.status === "pending");
  const tasks = snapshot.tasks.filter((item) => item.projectId === project.id);
  const logs = snapshot.logs.filter((item) => item.projectId === project.id);
  const files = snapshot.attachments.filter((item) => item.projectId === project.id);
  const [logText, setLogText] = useState("");
  const [taskEditor, setTaskEditor] = useState<
    { mode: "create" } | { mode: "edit"; task: ProjectTask } | null
  >(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const duration = daysBetween(project.startDate, project.dueDate);
  const projectKind = projectKindOf(project);
  const isPersonal = projectKind === "personal";
  const taskCompletion = tasks.length ? Math.round(tasks.filter((item) => item.status === "done").length / tasks.length * 100) : 0;
  const remainingDays = Math.max(0, daysUntil(project.dueDate));
  const overdueTasks = tasks.filter((item) => item.status !== "done" && daysUntil(item.dueDate) < 0).length;
  const healthScore = Math.max(28, Math.min(98, 92 - overdueTasks * 14 - (project.status === "overdue" ? 18 : 0) - projectIssues.length * 18));
  const totalTimeline = Math.max(1, new Date(`${project.dueDate}T00:00:00`).getTime() - new Date(`${project.startDate}T00:00:00`).getTime());
  const persistTasks = (nextTasks: ProjectTask[]) => {
    const projectTasks = nextTasks.filter((item) => item.projectId === project.id);
    const progress = projectTasks.length
      ? Math.round(projectTasks.filter((item) => item.status === "done").length / projectTasks.length * 100)
      : 0;
    const dueAt = new Date(`${project.dueDate}T23:59:59`).getTime();
    const nextStatus: Project["status"] = progress === 100
      ? project.status === "completed" ? "completed" : "delivered"
      : dueAt < Date.now()
        ? "overdue"
        : progress > 0
          ? "in_progress"
          : "pending";
    onSnapshotChange({
      ...snapshot,
      tasks: nextTasks,
      projects: snapshot.projects.map((item) => item.id === project.id
        ? { ...item, progress, status: nextStatus }
        : item),
    });
  };
  const updateTask = (taskId: string) => {
    const nextTasks: ProjectTask[] = snapshot.tasks.map((item) => {
      if (item.id !== taskId) return item;
      const status: TaskStatus = item.status === "todo" ? "in_progress" : item.status === "in_progress" ? "done" : "todo";
      return { ...item, status, actualHours: status === "done" && item.actualHours === 0 ? item.estimatedHours : item.actualHours };
    });
    persistTasks(nextTasks);
  };
  const addTask = () => setTaskEditor({ mode: "create" });
  const editTask = (taskId: string) => {
    const task = tasks.find((item) => item.id === taskId);
    if (task) setTaskEditor({ mode: "edit", task });
  };
  const saveTask = (task: ProjectTask) => {
    const exists = snapshot.tasks.some((item) => item.id === task.id);
    const nextTasks = exists
      ? snapshot.tasks.map((item) => item.id === task.id ? task : item)
      : [...snapshot.tasks, task];
    persistTasks(nextTasks);
    setTaskEditor(null);
  };
  const deleteTask = (taskId: string) => {
    persistTasks(snapshot.tasks.filter((item) => item.id !== taskId));
    setTaskEditor(null);
  };
  const addLog = (event: FormEvent) => {
    event.preventDefault();
    if (!logText.trim()) return;
    const log: ProjectLog = { id: `log-${Date.now()}`, projectId: project.id, createdAt: new Date().toISOString(), content: logText.trim(), hours: 1, category: "development" };
    onSnapshotChange({ ...snapshot, logs: [log, ...snapshot.logs] });
    setLogText("");
  };
  const addFile = () => fileInput.current?.click();
  const storeFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files || []);
    if (!selected.length) return;
    const attachments = await Promise.all(selected.map(async (file, index) => {
      const dataUrl = file.size <= 1_500_000 ? await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => resolve("");
        reader.readAsDataURL(file);
      }) : undefined;
      const extension = file.name.split(".").pop()?.toLowerCase();
      return { id: `file-${Date.now()}-${index}`, projectId: project.id, name: file.name, size: file.size < 1_000_000 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1_000_000).toFixed(1)} MB`, type: extension === "zip" || extension === "rar" ? "archive" as const : ["png", "jpg", "jpeg", "fig", "sketch"].includes(extension || "") ? "design" as const : "document" as const, uploadedAt: new Date().toISOString(), dataUrl };
    }));
    onSnapshotChange({ ...snapshot, attachments: [...attachments, ...snapshot.attachments] });
    event.target.value = "";
  };
  const tabs = [
    ["overview", "经营总览", Gauge], ["tasks", "任务列表", ListChecks], ["gantt", "甘特图", ChartLineUp],
    ["immersive", "沉浸任务流", Stack],
    ["communication", "客户沟通", ChatCircleDots], ["quote", "需求报价", FileText],
    ["logs", "开发日志", NotePencil], ["files", "项目附件", Paperclip],
  ] as const;
  const visibleTabs = tabs.filter(([key]) => !isPersonal || (key !== "communication" && key !== "quote"));

  useEffect(() => {
    if (isPersonal && (tab === "communication" || tab === "quote")) onTabChange("immersive");
  }, [isPersonal, onTabChange, tab]);

  useEffect(() => setTaskEditor(null), [projectId]);

  return <div className="business-page project-detail-page">
    <section className="project-workspace-shell project-detail-workspace">
      <header className="project-detail-workspace-head">
        <button className="business-back" onClick={onBack}><ArrowLeft size={17} />返回项目列表</button>
        <span className={`project-kind-badge kind-${projectKind}`}>{isPersonal ? <Code size={15} /> : <Briefcase size={15} />}{projectKindLabel[projectKind]}</span>
      </header>
      <div className="project-detail-hero">
        <div className="project-detail-heading"><span className={`project-avatar project-${project.accent}`}>{isPersonal ? <Code size={27} weight="duotone" /> : <Briefcase size={27} weight="duotone" />}</span><div><small>{project.type || (isPersonal ? "个人开发" : "定制开发")}{!isPersonal && customer ? ` · ${customer.name}` : ""}</small><h2>{project.name}</h2><p>{project.notes || (isPersonal ? "聚焦个人产品、开源计划与长期能力沉淀。" : "围绕交付目标推进开发、验收与回款。")}</p></div><span className="project-health"><i />项目健康度 {healthScore}</span></div>
        <div className="project-detail-summary"><span><small>自动工期</small><b>{duration} 天</b></span><span><small>计划进度</small><b>{project.progress}%</b></span><span><small>实际投入</small><b>{financial.actualHours} 小时</b></span><span><small>{isPersonal ? "距离里程碑" : "距离交付"}</small><b>{remainingDays} 天</b></span></div>
      </div>
      <section className="project-detail-kpis" aria-label="项目核心数据">
        {isPersonal ? <>
          <WorkspaceMetric icon={Target} label="任务完成" value={`${taskCompletion}%`} detail={`${tasks.filter((item) => item.status === "done").length}/${tasks.length} 项已完成`} tone="purple" />
          <WorkspaceMetric icon={Timer} label="计划工时" value={`${project.estimatedHours || 0}h`} detail="个人投入预算" tone="blue" />
          <WorkspaceMetric icon={Clock} label="实际工时" value={`${financial.actualHours}h`} detail="来自任务记录" tone="green" />
          <WorkspaceMetric icon={WarningCircle} label="风险任务" value={`${overdueTasks}`} detail={overdueTasks ? "需要优先收敛" : "当前节奏可控"} tone="orange" />
        </> : <>
          <WorkspaceMetric icon={Wallet} label="合同金额" value={money.format(project.totalAmount)} detail={projectChangeOrders.length ? `原合同 ${money.format(baseContractAmount)} + ${projectChangeOrders.length} 次追加 ${money.format(changeOrderTotal)}` : "项目原合同金额"} tone="purple" action={<div className="workspace-financial-actions">{projectTerminated ? <span className="is-terminated"><WarningCircle size={14} weight="fill" />已终止，请新建项目</span> : <button type="button" onClick={() => onCreateChangeOrder(project.id)}><Plus size={14} />新增追加订单</button>}</div>} />
          <WorkspaceMetric icon={Coins} label="净到账 / 可收" value={`${money.format(financial.income)} / ${money.format(financial.outstanding)}`} detail={financial.issueCount ? `已退款 ${money.format(financial.refundedAmount)} · 已核销 ${money.format(financial.uncollectible)}` : `净回款率 ${financial.paymentProgress.toFixed(0)}%`} tone="blue" action={<div className="workspace-financial-actions">{financial.outstanding > 0 ? <button type="button" onClick={() => onConfirmPayment(project.id)}><Wallet size={14} weight="duotone" />确认到账</button> : <span><CheckCircle size={14} weight="fill" />可收余额已结清</span>}<button type="button" className="is-exception" onClick={() => onRecordSettlementIssue(project.id)}><WarningCircle size={14} weight="duotone" />记录异常</button></div>} />
          <WorkspaceMetric icon={TrendUp} label="实际利润" value={money.format(financial.profit)} detail={`已扣除成本 ${money.format(financial.expenses)}`} tone="green" />
          <WorkspaceMetric icon={Timer} label="平均小时收益" value={money.format(financial.hourlyIncome)} detail="按已投入工时计算" tone="orange" />
        </>}
      </section>
      {!isPersonal && project.status === "delivered" && financial.outstanding > 0 && <section className="delivered-receivable-alert"><WarningCircle size={18} weight="fill" /><span><b>项目已交付，仍有 {money.format(financial.outstanding)} 待回款</b><small>到账后可直接在这里确认，不需要先建立付款节点。</small></span><button type="button" onClick={() => onConfirmPayment(project.id)}>确认到账 <ArrowRight size={14} /></button></section>}
      {!isPersonal && latestIssue && <section className="project-settlement-alert"><WarningCircle size={19} weight="fill" /><span><b>{settlementIssueLabels[latestIssue.type]} · 已记录 {projectIssues.length} 条异常</b><small>{latestIssue.reason}{financial.refundedAmount > 0 || financial.uncollectible > 0 ? ` · 已退款 ${money.format(financial.refundedAmount)}，已核销 ${money.format(financial.uncollectible)}` : " · 金额影响待确认"}</small></span><button type="button" onClick={() => onRecordSettlementIssue(project.id)}>继续记录 <ArrowRight size={14} /></button></section>}
      <nav className="project-detail-tabs" aria-label="项目详情模块">{visibleTabs.map(([key, label, Icon]) => <button type="button" aria-current={tab === key ? "page" : undefined} className={tab === key ? "active" : ""} onClick={() => onTabChange(key)} key={key}><Icon size={17} />{label}</button>)}</nav>
      <div className="project-detail-content">

    {tab === "overview" && (isPersonal ? <section className="project-detail-grid personal-project-overview">
      <Surface><SurfaceTitle eyebrow="PROJECT PULSE" title="个人项目执行脉搏" /><div className="project-pulse"><div><span>开发进度</span><b>{project.progress}%</b><BarProgress value={project.progress} tone="purple" /></div><div><span>任务完成</span><b>{taskCompletion}%</b><BarProgress value={taskCompletion} tone="green" /></div><div><span>工时消耗</span><b>{project.estimatedHours ? Math.round(financial.actualHours / project.estimatedHours * 100) : 0}%</b><BarProgress value={project.estimatedHours ? financial.actualHours / project.estimatedHours * 100 : 0} tone="orange" /></div></div></Surface>
      <Surface><SurfaceTitle eyebrow="MILESTONES" title="里程碑概览" /><div className="personal-milestone-list"><span><i><FolderSimple size={19} weight="duotone" /></i><b>{tasks.length} 项任务</b><small>{tasks.filter((item) => item.status === "in_progress").length} 项正在推进</small></span><span><i><CalendarBlank size={19} weight="duotone" /></i><b>{shortDate(project.dueDate)} 里程碑</b><small>还有 {remainingDays} 天</small></span><span><i><Clock size={19} weight="duotone" /></i><b>{financial.actualHours}h 已投入</b><small>计划 {project.estimatedHours || 0}h</small></span></div></Surface>
      <Surface className="project-next-action"><SurfaceTitle eyebrow="NEXT ACTION" title="本地规则建议" /><div><Sparkle size={25} weight="fill" /><span><b>{overdueTasks ? `先处理 ${overdueTasks} 项逾期任务` : "保持当前交付节奏"}</b><p>{overdueTasks ? "建议收敛功能边界，把最小可验收成果作为下一个里程碑。" : "当前任务、工时和日期未出现明显风险，完成后记录可复用的开发结论。"}</p></span></div><button onClick={() => onTabChange("tasks")}>查看任务安排 <ArrowRight size={15} /></button></Surface>
    </section> : <section className="project-detail-grid">
      <Surface>
        <SurfaceTitle eyebrow="PAYMENT PLAN" title="付款计划与回款进度" action={<div className="payment-plan-title-actions"><button className="payment-plan-title-action is-change-order" type="button" disabled={projectTerminated} title={projectTerminated ? "已取消或终止合作的项目需要新建项目" : undefined} onClick={() => onCreateChangeOrder(project.id)}><Plus size={14} />{projectTerminated ? "已终止，请新建项目" : "新增追加订单"}</button>{financial.outstanding > 0 && <button className="payment-plan-title-action" type="button" onClick={() => onConfirmPayment(project.id)}><Wallet size={14} />确认到账</button>}<button className="payment-plan-title-action is-exception" type="button" onClick={() => onRecordSettlementIssue(project.id)}><WarningCircle size={14} />记录异常</button></div>} />
        {projectPayments.length ? <div className="payment-contract-groups">{paymentGroups.map((group) => <section className={`payment-contract-group ${group.id === "base-contract" ? "is-base" : "is-change-order"}`} key={group.id}>
          <header><span><small>{group.id === "base-contract" ? "BASE CONTRACT" : "CHANGE ORDER"}</small><b>{group.title}</b><em>{group.detail}</em></span><strong>{money.format(group.amount)}</strong></header>
          <div className="payment-node-list">{group.payments.map((payment, index) => <article className={payment.status === "confirmed" ? "done" : payment.status === "written_off" ? "written-off" : payment.status === "refunded" ? "refunded" : ""} key={payment.id}><i>{payment.status === "confirmed" ? <CheckCircle size={19} weight="fill" /> : payment.status === "written_off" || payment.status === "refunded" ? <WarningCircle size={19} weight="fill" /> : index + 1}</i><span><b>{payment.changeOrderId ? `追加款 · ${paymentLabel[payment.type]}` : paymentLabel[payment.type]}</b><small>{payment.notes || (payment.status === "confirmed" ? "已确认到账" : payment.status === "written_off" ? "已因项目异常核销" : payment.status === "refunded" ? "已退款" : "等待收款")}</small></span><strong>{money.format(payment.amount)}</strong><time>{payment.status === "confirmed" ? `已到账 ${shortDate(payment.paidAt)}` : payment.status === "written_off" ? "已核销，不再催收" : payment.status === "refunded" ? "已退款" : `${shortDate(payment.dueAt)} 应收`}</time>{payment.status === "pending" && <button className="payment-node-confirm" type="button" onClick={() => onConfirmPayment(project.id, payment.id)}>到账</button>}</article>)}</div>
        </section>)}</div> : <div className="payment-plan-empty"><i><Wallet size={29} weight="duotone" /></i><span><b>{projectTerminated ? "原合作已经终止" : financial.outstanding > 0 ? "合同余额尚未拆分为付款节点" : "当前合同已结清"}</b><small>{projectTerminated ? "如客户重新提出付费需求，请新建项目，避免把新合作混入已完成核销的原合同。" : financial.outstanding > 0 ? `当前仍有 ${money.format(financial.outstanding)} 可收，可确认到账、记录异常或先建立收款计划。` : "客户再次付费追加修改时，请新增追加订单；原合同和收款历史会完整保留。"}</small></span><div>{!projectTerminated && <button className="business-primary" type="button" onClick={() => onCreateChangeOrder(project.id)}><Plus size={15} />新增追加订单</button>}{financial.outstanding > 0 && <button type="button" onClick={() => onConfirmPayment(project.id)}><CheckCircle size={15} />确认已到账</button>}{financial.outstanding > 0 && <button type="button" onClick={() => onCreatePaymentPlan(project.id)}><Plus size={15} />建立收款计划</button>}<button type="button" className="is-exception" onClick={() => onRecordSettlementIssue(project.id)}><WarningCircle size={15} />记录异常</button></div></div>}
      </Surface>
      <Surface><SurfaceTitle eyebrow="PROJECT PULSE" title="项目执行脉搏" /><div className="project-pulse"><div><span>开发进度</span><b>{project.progress}%</b><BarProgress value={project.progress} tone="purple" /></div><div><span>任务完成</span><b>{taskCompletion}%</b><BarProgress value={taskCompletion} tone="green" /></div><div><span>工时消耗</span><b>{project.estimatedHours ? Math.round(financial.actualHours / project.estimatedHours * 100) : 0}%</b><BarProgress value={project.estimatedHours ? financial.actualHours / project.estimatedHours * 100 : 0} tone="orange" /></div></div><div className="project-customer-brief"><UserCircle size={38} weight="duotone" /><span><small>关联客户</small><b>{customer?.name}</b><em>{customer?.phone}</em></span><span><small>客户等级</small><b>{customer?.level} 级客户</b><em>{followLabel[customer?.followUpStatus || "new"]}</em></span></div></Surface>
      <Surface className="project-next-action"><SurfaceTitle eyebrow="NEXT ACTION" title="本地经营建议" /><div><Sparkle size={25} weight="fill" /><span><b>{latestIssue ? "先确认异常处理边界" : "优先检查临近交付任务"}</b><p>{latestIssue ? `已记录“${settlementIssueLabels[latestIssue.type]}”。建议保留沟通证据，明确退款、核销和仍可收金额后再继续催收。` : `当前工时已使用 ${project.estimatedHours ? Math.round(financial.actualHours / project.estimatedHours * 100) : 0}%，建议冻结新增需求，并在验收前主动发送阶段款提醒。`}</p></span></div><button onClick={() => latestIssue ? onRecordSettlementIssue(project.id) : onTabChange("tasks")}>{latestIssue ? "更新异常记录" : "查看任务安排"} <ArrowRight size={15} /></button></Surface>
      <Surface className="project-settlement-history"><SurfaceTitle eyebrow="EXCEPTION HISTORY" title={`项目异常记录 · ${projectIssues.length}`} action={<button type="button" onClick={() => onRecordSettlementIssue(project.id)}><Plus size={14} />记录异常</button>} />{projectIssues.length ? <div>{projectIssues.map((issue) => <article key={issue.id}><i><WarningCircle size={18} weight="duotone" /></i><span><small>{shortDate(issue.occurredAt)} · {settlementIssueLabels[issue.type]}</small><b>{issue.reason}</b>{issue.notes && <em>{issue.notes}</em>}</span><dl><div><dt>无法收回</dt><dd>{money.format(issue.receivableImpact)}</dd></div><div><dt>实际退款</dt><dd>{money.format(issue.refundAmount)}</dd></div></dl></article>)}</div> : <div className="project-settlement-empty"><CheckCircle size={23} weight="duotone" /><span><b>暂无客户或回款异常</b><small>客户不满意、退款、取消合作或拒付时，可从这里留下原因和金额影响。</small></span></div>}</Surface>
    </section>)}

    {tab === "tasks" && <Surface className="project-module"><SurfaceTitle eyebrow="TASKS" title={`项目任务列表 · ${tasks.filter((item) => item.status === "done").length}/${tasks.length} 已完成`} action={<button className="business-primary" onClick={addTask}><Plus size={16} />新增任务</button>} /><div className="project-task-table"><div className="project-task-head"><span>任务</span><span>状态</span><span>计划日期</span><span>预计 / 实际</span><span>操作</span></div>{tasks.map((task) => <article key={task.id}><span><button className={`task-check task-${task.status}`} onClick={() => updateTask(task.id)} aria-label={`切换${task.title}状态`}>{task.status === "done" && <CheckCircle size={18} weight="fill" />}</button><b>{task.title}</b></span><em className={`task-status task-${task.status}`}>{taskLabel[task.status]}</em><time>{shortDate(task.startDate)} — {shortDate(task.dueDate)}</time><small>{task.estimatedHours}h / {task.actualHours}h</small><span className="task-row-actions"><button type="button" onClick={() => editTask(task.id)} aria-label={`编辑任务 ${task.title}`}><PencilSimple size={13} />编辑</button><button type="button" onClick={() => updateTask(task.id)}>推进 <CaretRight size={13} /></button></span></article>)}</div></Surface>}

    {tab === "gantt" && <Surface className="project-module"><SurfaceTitle eyebrow="TIMELINE" title="项目甘特图" action={<span className="auto-duration"><Clock size={15} />工期自动计算：{duration} 天</span>} /><div className="gantt-calendar"><div className="gantt-scale"><span>任务</span>{Array.from({ length: duration }, (_, index) => <time key={index}>{index + 1}日</time>)}</div>{tasks.map((task, index) => { const left = Math.max(0, (new Date(`${task.startDate}T00:00:00`).getTime() - new Date(`${project.startDate}T00:00:00`).getTime()) / totalTimeline * 100); const width = Math.max(8, (new Date(`${task.dueDate}T00:00:00`).getTime() - new Date(`${task.startDate}T00:00:00`).getTime() + 86_400_000) / (totalTimeline + 86_400_000) * 100); return <article key={task.id}><b>{task.title}</b><div><i className={`gantt-tone-${index % 4}`} style={{ left: `${left}%`, width: `${Math.min(100 - left, width)}%` }}><span>{task.status === "done" ? "已完成" : task.status === "in_progress" ? `${Math.max(20, Math.round(task.actualHours / Math.max(task.estimatedHours, 1) * 100))}%` : "待开始"}</span></i></div></article>; })}</div></Surface>}

    {tab === "immersive" && <ImmersiveTaskFlow project={project} tasks={tasks} onCreateTask={addTask} onEditTask={editTask} onAdvanceTask={updateTask} />}

    {tab === "communication" && <section className="project-detail-grid"><Surface className="project-module"><SurfaceTitle eyebrow="CUSTOMER CONVERSATION" title="客户沟通记录" /><div className="project-link-panel"><i><ChatCircleDots size={34} weight="duotone" /></i><span><small>来源会话</small><b>{project.conversationId ? `会话 #${project.conversationId}` : "当前项目未关联客户会话"}</b><p>{project.conversationId ? "项目由客户消息工作台人工确认转化，可返回原会话继续跟进需求与交付。" : "从客户消息完成“人工确认并转项目”后，这里会保留原会话关联。"}</p></span></div>{project.conversationId && <button className="business-primary" onClick={() => { window.location.hash = encodeURIComponent("客户消息"); }}>返回客户消息</button>}</Surface><Surface><SurfaceTitle eyebrow="CUSTOMER" title="关联客户" /><div className="project-customer-brief"><UserCircle size={38} weight="duotone" /><span><small>客户名称</small><b>{customer?.name || "未关联"}</b><em>{customer?.source === "wechat" ? "微信客户" : customer?.source === "xianyu" ? "闲鱼客户" : "经营客户"}</em></span><span><small>最近联系</small><b>{customer?.lastContactAt ? shortDate(customer.lastContactAt) : "暂无"}</b><em>{customer ? followLabel[customer.followUpStatus] : "待补充"}</em></span></div></Surface></section>}

    {tab === "quote" && <section className="project-detail-grid"><Surface className="project-module"><SurfaceTitle eyebrow="REQUIREMENT VERSION" title="采用的需求与报价" /><div className="project-source-links"><article><FileText size={24} weight="duotone" /><span><small>需求版本</small><b>{project.requirementVersionId ? `需求文档 #${project.requirementVersionId}` : "未关联需求版本"}</b></span></article><article><Coins size={24} weight="duotone" /><span><small>报价版本</small><b>{project.quoteId || "未关联报价版本"}</b></span></article><article><Target size={24} weight="duotone" /><span><small>成交金额</small><b>{money.format(project.totalAmount)}</b></span></article></div><p className="business-note">从会话转化的项目会固定保存采用的需求和报价版本，后续变更不会覆盖历史确认依据。</p></Surface><Surface><SurfaceTitle eyebrow="PAYMENT PLAN" title="已生成付款节点" /><div className="payment-node-list">{snapshot.payments.filter((item) => item.projectId === project.id).map((payment, index) => <article className={payment.status === "confirmed" ? "done" : ""} key={payment.id}><i>{payment.status === "confirmed" ? <CheckCircle size={19} weight="fill" /> : index + 1}</i><span><b>{paymentLabel[payment.type]}</b><small>{payment.notes}</small></span><strong>{money.format(payment.amount)}</strong><time>{payment.dueAt ? `${shortDate(payment.dueAt)} 应收` : "待排期"}</time></article>)}</div></Surface></section>}

    {tab === "logs" && <section className="project-detail-grid"><Surface className="project-module"><SurfaceTitle eyebrow="DAILY LOG" title="开发日志" /><form className="log-composer" onSubmit={addLog}><textarea value={logText} onChange={(event) => setLogText(event.target.value)} placeholder="记录今天完成的功能、客户沟通或风险变化…" rows={3} /><button className="business-primary" type="submit"><NotePencil size={16} />发布日志</button></form><div className="dev-log-list">{logs.map((log) => <article key={log.id}><i><NotePencil size={17} /></i><span><b>{log.content}</b><small>{new Date(log.createdAt).toLocaleString("zh-CN")} · {log.hours} 小时 · {log.category === "development" ? "开发" : log.category === "communication" ? "沟通" : "交付"}</small></span></article>)}</div></Surface><Surface className="log-insight"><Lightbulb size={31} weight="duotone" /><h3>本周投入 {logs.reduce((sum, item) => sum + item.hours, 0)} 小时</h3><p>沟通记录和开发日志完整，当前最大风险是验收前新增需求。建议所有变更进入下期报价。</p></Surface></section>}

    {tab === "files" && <Surface className="project-module"><input ref={fileInput} hidden type="file" multiple onChange={storeFiles} /><SurfaceTitle eyebrow="FILES" title={`项目附件 · ${files.length}`} action={<button className="business-primary" onClick={addFile}><UploadSimple size={16} />上传附件</button>} /><div className="attachment-grid">{files.map((file) => { const Icon = file.type === "archive" ? FileArchive : file.type === "design" ? FolderOpen : FileText; return <article key={file.id}><i><Icon size={27} weight="duotone" /></i><span><b>{file.name}</b><small>{file.size} · {shortDate(file.uploadedAt)} 上传</small></span>{file.dataUrl ? <a href={file.dataUrl} target="_blank" rel="noreferrer">查看</a> : <button disabled title="旧附件只保存了文件信息">仅信息</button>}</article>; })}<button className="attachment-drop" onClick={addFile}><UploadSimple size={28} /><b>上传项目文件</b><small>1.5 MB 内文件可在当前设备打开</small></button></div></Surface>}
      </div>
    </section>
    {taskEditor && <ProjectTaskEditor project={project} task={taskEditor.mode === "edit" ? taskEditor.task : null} onClose={() => setTaskEditor(null)} onDelete={deleteTask} onSave={saveTask} />}
  </div>;
}

function LegacyEnhancedProjectManagementPage({ snapshot, onCreateProject, onSnapshotChange, globalSearch, projectRoute, onProjectRouteChange }: { snapshot: LedgerSnapshot; onCreateProject: () => void; onSnapshotChange: (snapshot: LedgerSnapshot) => void; globalSearch: string; projectRoute: ProjectPageRoute | null; onProjectRouteChange: (route: ProjectPageRoute | null, mode?: ProjectRouteMode) => void }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState("due");
  const financials = useMemo(() => getProjectFinancials(snapshot), [snapshot]);
  const query = (globalSearch || search).trim().toLowerCase();
  const filtered = financials.filter(({ project }) => {
    const customer = snapshot.customers.find((item) => item.id === project.customerId);
    return `${project.name} ${customer?.name || ""}`.toLowerCase().includes(query) && (status === "all" || project.status === status);
  }).sort((a, b) => sort === "amount" ? b.project.totalAmount - a.project.totalAmount : a.project.dueDate.localeCompare(b.project.dueDate));
  const selectedProject = projectRoute && snapshot.projects.some((item) => item.id === projectRoute.projectId) ? projectRoute.projectId : null;
  if (selectedProject) return <ProjectDetail snapshot={snapshot} projectId={selectedProject} tab={projectRoute!.tab} onBack={() => onProjectRouteChange(null, "back")} onTabChange={(tab) => onProjectRouteChange({ projectId: selectedProject, tab }, "replace")} onCreatePaymentPlan={() => {}} onCreateChangeOrder={() => {}} onConfirmPayment={() => {}} onRecordSettlementIssue={() => {}} onSnapshotChange={onSnapshotChange} />;
  const active = snapshot.projects.filter((item) => item.status === "in_progress");
  const averageDuration = snapshot.projects.length
    ? snapshot.projects.reduce((sum, item) => sum + daysBetween(item.startDate, item.dueDate), 0) / snapshot.projects.length
    : 0;
  const outstanding = financials.reduce((sum, item) => sum + item.outstanding, 0);
  return <div className="business-page enhanced-project-page">
    <section className="business-metrics-grid">
      <BusinessMetric label="全部项目" value={`${snapshot.projects.length} 个`} detail={`合同总额 ${money.format(snapshot.projects.reduce((sum, item) => sum + item.totalAmount, 0))}`} tone="purple" icon={Briefcase} />
      <BusinessMetric label="进行中" value={`${active.length} 个`} detail="统一追踪任务、工期和交付" tone="blue" icon={ListChecks} />
      <BusinessMetric label="待回款" value={money.format(outstanding)} detail="来自所有未结清付款节点" tone="orange" icon={BellRinging} />
      <BusinessMetric label="平均工期" value={`${averageDuration.toFixed(1)} 天`} detail="根据开始与交付日期自动计算" tone="green" icon={Clock} />
    </section>
    <div className="project-list-layout"><main><Surface className="project-list-toolbar"><label><MagnifyingGlass size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={globalSearch ? `顶部搜索：${globalSearch}` : "搜索项目或客户"} disabled={Boolean(globalSearch)} /></label><select aria-label="项目状态" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">全部状态</option><option value="pending">待开始</option><option value="in_progress">进行中</option><option value="delivered">已交付</option><option value="completed">已完成</option><option value="overdue">已逾期</option></select><select aria-label="项目排序" value={sort} onChange={(event) => setSort(event.target.value)}><option value="due">按交付时间排序</option><option value="amount">按合同金额排序</option></select><button className="business-primary" onClick={onCreateProject}><Plus size={16} />新建项目</button></Surface><div className="enhanced-project-list">{filtered.length ? filtered.map(({ project, income, outstanding: due, paymentProgress, profit }) => { const customer = snapshot.customers.find((item) => item.id === project.customerId); const projectTasks = snapshot.tasks.filter((task) => task.projectId === project.id); const openProject = () => onProjectRouteChange({ projectId: project.id, tab: "immersive" }, "push"); return <Surface className="enhanced-project-row" key={project.id}><div className={`project-avatar project-${project.accent}`}><Briefcase size={24} weight="duotone" /></div><div className="enhanced-project-main"><span><small>{project.type || "定制开发"} · {customer?.name}</small><h3>{project.name}</h3></span><div className="enhanced-progress-copy"><span>开发进度 <b>{project.progress}%</b></span><BarProgress value={project.progress} tone={project.accent} /></div></div><div className="project-row-stat"><small>合同 / 已收</small><b>{money.format(project.totalAmount)} / {money.format(income)}</b><em>未收 {money.format(due)}</em></div><div className="project-row-stat"><small>任务 / 自动工期</small><b>{projectTasks.filter((item) => item.status === "done").length}/{projectTasks.length} · {daysBetween(project.startDate, project.dueDate)}天</b><em>{Math.max(0, daysUntil(project.dueDate))} 天后交付</em></div><div className="project-row-stat"><small>利润 / 回款</small><b className="positive">{money.format(profit)}</b><em>{paymentProgress.toFixed(0)}%</em></div><button type="button" className="project-detail-button" onClick={openProject}>项目详情 <ArrowRight size={14} /></button></Surface>; }) : <BusinessEmptyState icon={Briefcase} title="没有匹配的项目" description={snapshot.projects.length ? "请调整搜索或筛选条件。" : "示例项目已经清空，可录入自己的第一个项目。"} action={!snapshot.projects.length ? <button className="business-primary" onClick={onCreateProject}><Plus size={16} />录入我的第一个项目</button> : undefined} />}</div></main><aside><Surface><SurfaceTitle eyebrow="AUTO SCHEDULE" title="工期自动计算" /><div className="schedule-illustration"><CalendarBlank size={42} weight="duotone" /><strong>{averageDuration.toFixed(1)}<small> 天</small></strong><span>平均项目工期</span></div><p className="business-note">工期由项目开始日、任务排期和交付日自动计算；任务变更后可实时评估延期风险。</p></Surface><Surface><SurfaceTitle eyebrow="UPCOMING" title="近期交付" /><div className="upcoming-list">{active.length ? active.slice().sort((a, b) => daysUntil(a.dueDate) - daysUntil(b.dueDate)).map((project) => <button type="button" key={project.id} onClick={() => onProjectRouteChange({ projectId: project.id, tab: "immersive" }, "push")}><i className={`project-${project.accent}`}><Clock size={16} /></i><span><b>{project.name}</b><small>{shortDate(project.dueDate)} 交付</small></span><em>{Math.max(0, daysUntil(project.dueDate))}天</em></button>) : <p className="business-note">暂无近期交付项目</p>}</div></Surface></aside></div>
  </div>;
}

export function EnhancedIncomeRecordsPage({ snapshot, onQuickAdd, onSnapshotChange, globalSearch }: { snapshot: LedgerSnapshot; onQuickAdd: () => void; onSnapshotChange: (snapshot: LedgerSnapshot) => void; globalSearch: string }) {
  const summary = getBusinessSummary(snapshot);
  const clientProjects = snapshot.projects.filter((project) => projectKindOf(project) === "client");
  const [selected, setSelected] = useState(clientProjects[0]?.id || "");
  const [reminded, setReminded] = useState<string | null>(null);
  const selectedId = clientProjects.some((item) => item.id === selected) ? selected : clientProjects[0]?.id || "";
  const selectedProject = clientProjects.find((item) => item.id === selectedId);
  const selectedFinancial = summary.projectFinancials.find((item) => item.project.id === selectedId);
  const projectPayments = snapshot.payments.filter((item) => item.projectId === selectedId);
  const pending = snapshot.settings.paymentRemindersEnabled === false ? [] : snapshot.payments.filter((item) => item.status === "pending").sort((a, b) => a.dueAt.localeCompare(b.dueAt));
  const matchingPayments = snapshot.payments.filter((payment) => { const project = snapshot.projects.find((item) => item.id === payment.projectId); const customer = snapshot.customers.find((item) => item.id === payment.customerId); return `${project?.name || ""} ${customer?.name || ""} ${paymentLabel[payment.type]}`.toLowerCase().includes(globalSearch.trim().toLowerCase()); });
  const remindCustomer = (paymentId: string) => {
    const payment = snapshot.payments.find((item) => item.id === paymentId);
    if (!payment) return;
    onSnapshotChange({ ...snapshot, customers: snapshot.customers.map((customer) => customer.id === payment.customerId ? { ...customer, lastContactAt: new Date().toISOString(), followUpStatus: customer.followUpStatus === "new" ? "contacted" : customer.followUpStatus } : customer) });
    setReminded(paymentId);
  };
  const totalContract = clientProjects.reduce((sum, item) => sum + item.totalAmount, 0);
  const overdueCount = pending.filter((payment) => daysUntil(payment.dueAt) <= 0).length;
  const nearDueCount = pending.filter((payment) => daysUntil(payment.dueAt) <= 7).length;
  const healthScore = Math.max(0, 100 - overdueCount * 20 - Math.max(0, nearDueCount - overdueCount) * 6);
  if (!selectedProject || !selectedFinancial) return <div className="business-page enhanced-income-page"><section className="business-metrics-grid"><BusinessMetric label="累计到账" value={money.format(0)} detail="已确认的项目收款" tone="purple" icon={Wallet} /><BusinessMetric label="未收金额" value={money.format(0)} detail="0 个付款节点待处理" tone="orange" icon={BellRinging} /><BusinessMetric label="本月到账" value={money.format(0)} detail="本月利润 ¥0" tone="green" icon={TrendUp} /><BusinessMetric label="整体回款率" value="0%" detail="按合同总金额计算" tone="blue" icon={Gauge} /></section><BusinessEmptyState icon={Wallet} title="还没有收款记录" description="定金、阶段款、尾款和全款都已清空，可以从第一笔真实收款开始。" action={<button className="business-primary" onClick={onQuickAdd}><Plus size={16} />记录第一笔收款</button>} /></div>;
  return <div className="business-page enhanced-income-page">
    <section className="business-metrics-grid">
      <BusinessMetric label="累计到账" value={money.format(summary.totalIncome)} detail="已确认的项目收款" tone="purple" icon={Wallet} />
      <BusinessMetric label="未收金额" value={money.format(summary.outstanding)} detail={`${summary.pendingCount} 个付款节点待处理`} tone="orange" icon={BellRinging} />
      <BusinessMetric label="本月到账" value={money.format(summary.monthlyIncome)} detail={`本月利润 ${money.format(summary.monthlyProfit)}`} tone="green" icon={TrendUp} />
      <BusinessMetric label="整体回款率" value={`${totalContract ? Math.round(summary.totalIncome / totalContract * 100) : 0}%`} detail="按合同总金额计算" tone="blue" icon={Gauge} />
    </section>
    <section className="income-workspace"><main><Surface><SurfaceTitle eyebrow="PROJECT PAYMENT" title="项目付款节点" action={<div className="income-actions"><select value={selectedId} onChange={(event) => setSelected(event.target.value)}>{clientProjects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select><button className="business-primary" onClick={onQuickAdd}><Plus size={16} />记录收款</button></div>} /><div className="collection-overview"><div><small>{selectedProject.name}</small><strong>{money.format(selectedFinancial.income)} <span>/ {money.format(selectedProject.totalAmount)}</span></strong><BarProgress value={selectedFinancial.paymentProgress} tone="green" /><p><span>收款进度 {selectedFinancial.paymentProgress.toFixed(0)}%</span><b>未收 {money.format(selectedFinancial.outstanding)}</b></p></div><i><Wallet size={43} weight="duotone" /></i></div><div className="payment-timeline">{projectPayments.map((payment, index) => <article className={payment.status === "confirmed" ? "paid" : ""} key={payment.id}><div><i>{payment.status === "confirmed" ? <CheckCircle size={18} weight="fill" /> : index + 1}</i><span /></div><small>{paymentLabel[payment.type]}</small><strong>{money.format(payment.amount)}</strong><time>{shortDate(payment.dueAt)}</time><em>{payment.status === "confirmed" ? "已到账" : daysUntil(payment.dueAt) <= 1 ? "即将到期" : "待收款"}</em></article>)}</div></Surface><Surface><SurfaceTitle eyebrow="ALL NODES" title={globalSearch ? `搜索结果 · ${matchingPayments.length}` : "全部收款节点"} /><div className="income-node-table"><div><span>项目 / 客户</span><span>类型</span><span>金额</span><span>计划日期</span><span>状态</span><span>收款进度</span></div>{matchingPayments.map((payment) => { const project = snapshot.projects.find((item) => item.id === payment.projectId)!; const customer = snapshot.customers.find((item) => item.id === payment.customerId)!; const financial = summary.projectFinancials.find((item) => item.project.id === project.id)!; return <article key={payment.id}><span><b>{project.name}</b><small>{customer.name}</small></span><em>{paymentLabel[payment.type]}</em><strong>{money.format(payment.amount)}</strong><time>{shortDate(payment.dueAt)}</time><i className={`payment-status-${payment.status}`}>{payment.status === "confirmed" ? "已到账" : payment.status === "refunded" ? "已退款" : "待收款"}</i><span><BarProgress value={financial.paymentProgress} tone="green" /><small>{financial.paymentProgress.toFixed(0)}%</small></span></article>; })}</div></Surface></main><aside><Surface><SurfaceTitle eyebrow="REMINDERS" title="收款提醒" action={<span className="reminder-count">{pending.length}</span>} /><div className="collection-reminders">{pending.slice(0, 5).map((payment) => { const project = snapshot.projects.find((item) => item.id === payment.projectId)!; const remaining = daysUntil(payment.dueAt); return <article className={remaining <= 1 ? "urgent" : ""} key={payment.id}><i><BellRinging size={18} weight="duotone" /></i><span><b>{project.name}</b><small>{paymentLabel[payment.type]} · {money.format(payment.amount)}</small></span><em>{remaining <= 0 ? "今天到期" : `${remaining}天后`}</em><button onClick={() => remindCustomer(payment.id)} disabled={reminded === payment.id}>{reminded === payment.id ? "已记录提醒" : "提醒客户"}</button></article>; })}</div></Surface><Surface className="collection-health"><SurfaceTitle eyebrow="CASH FLOW" title="回款健康度" /><div className="health-score"><strong>{healthScore}</strong><span><b>{healthScore >= 80 ? "健康" : healthScore >= 60 ? "需关注" : "有风险"}</b><small>{pending.length ? `${nearDueCount} 个节点在 7 天内到期` : "暂无待收节点"}</small></span></div><ul><li><CheckCircle size={16} weight="fill" />已确认到账 {snapshot.payments.filter((item) => item.status === "confirmed").length} 个节点</li><li><WarningCircle size={16} weight="fill" />{overdueCount} 个节点已到期</li></ul></Surface></aside></section>
  </div>;
}

export function ProfitAnalysisPage({ snapshot }: { snapshot: LedgerSnapshot }) {
  const summary = getBusinessSummary(snapshot);
  const ranking = summary.projectFinancials.slice().sort((a, b) => b.profit - a.profit);
  const rankingPageSize = 5;
  const [rankingPage, setRankingPage] = useState(0);
  const rankingPageCount = Math.max(1, Math.ceil(ranking.length / rankingPageSize));
  const safeRankingPage = Math.min(rankingPage, rankingPageCount - 1);
  const visibleRanking = ranking.slice(
    safeRankingPage * rankingPageSize,
    (safeRankingPage + 1) * rankingPageSize,
  );
  const maxProfit = Math.max(...ranking.map((item) => Math.max(0, item.profit)), 1);
  const profitMargin = summary.totalIncome
    ? Math.round((summary.actualProfit / summary.totalIncome) * 100)
    : 0;
  const topProject = ranking[0];
  const hasProfitStructure = [
    summary.monthlyIncome,
    summary.monthlyExpenses,
    summary.yearlyIncome,
    summary.yearlyExpenses,
  ].some((value) => value !== 0);
  const structureItems = [
    { id: "month-income", period: "本月", label: "收入", value: summary.monthlyIncome, tone: "income" },
    { id: "month-expense", period: "本月", label: "支出", value: summary.monthlyExpenses, tone: "expense" },
    { id: "year-income", period: "本年", label: "收入", value: summary.yearlyIncome, tone: "income" },
    { id: "year-expense", period: "本年", label: "支出", value: summary.yearlyExpenses, tone: "expense" },
  ];
  const structureMax = Math.max(...structureItems.map((item) => item.value), 1);
  const costItems = [
    { category: "outsourcing", label: "外包", icon: UsersThree, tone: "purple" },
    { category: "software", label: "软件订阅", icon: Stack, tone: "blue" },
    { category: "server", label: "服务器", icon: Gauge, tone: "green" },
    { category: "other", label: "其他", icon: Coins, tone: "orange" },
  ].map((item) => ({
    ...item,
    amount: snapshot.expenses
      .filter((expense) => expense.category === item.category)
      .reduce((sum, expense) => sum + expense.amount, 0),
  }));

  return <div className="business-page profit-analysis-page">
    <section className="business-metrics-grid" aria-label="利润核心指标">
      <BusinessMetric label="实际利润" value={money.format(summary.actualProfit)} detail={`${money.format(summary.totalIncome)} 收入 - ${money.format(summary.totalExpenses)} 支出`} tone="green" icon={TrendUp} />
      <BusinessMetric label="本月利润" value={money.format(summary.monthlyProfit)} detail={`${money.format(summary.monthlyIncome)} 收入 - ${money.format(summary.monthlyExpenses)} 支出`} tone="purple" icon={CalendarBlank} />
      <BusinessMetric label="年度利润" value={money.format(summary.yearlyProfit)} detail="按本年度已确认流水计算" tone="blue" icon={ChartLineUp} />
      <BusinessMetric label="平均小时收益" value={`${money.format(summary.averageHourlyIncome)}/h`} detail={`累计有效投入 ${summary.actualHours} 小时`} tone="orange" icon={Timer} />
    </section>

    <Surface className="profit-command-strip">
      <div className="profit-insight-summary">
        <header><span>经营洞察</span><Sparkle size={22} weight="fill" aria-hidden="true" /></header>
        <h2>{topProject?.profit > 0 ? "高价值项目正在形成" : "等待真实经营数据"}</h2>
        <p>{topProject?.profit > 0
          ? `「${topProject.project.name}」当前贡献最高利润，小时收益为 ${money.format(topProject.hourlyIncome)}。建议把同类项目报价提高 12%–18%。`
          : "录入自己的项目、收入、支出与工时后，这里会生成针对你的利润洞察。"}</p>
      </div>
      <div className="profit-margin-summary" aria-label={`当前利润率 ${profitMargin}%`}>
        <small>利润率</small>
        <strong className={profitMargin < 0 ? "is-negative" : ""}>{profitMargin}%</strong>
      </div>
      <div className="profit-cost-summary">
        <header><span>成本结构</span><small>按真实支出分类</small></header>
        <div>{costItems.map((item) => { const Icon = item.icon; return <span key={item.category} className={`cost-summary-${item.tone}`}><i><Icon size={18} weight="duotone" aria-hidden="true" /></i><small>{item.label}</small><b>{money.format(item.amount)}</b></span>; })}</div>
      </div>
    </Surface>

    <section className="profit-compact-grid">
      <Surface className="profit-ranking-panel">
        <SurfaceTitle eyebrow="PROJECT PROFIT" title="项目收益排行" action={<div className="profit-ranking-head-actions"><span className="profit-formula">收入 - 支出 = 实际利润</span><small>每页最多 5 项</small></div>} />
        {ranking.length ? <div className="profit-ranking-table" role="table" aria-label="项目收益排行">
          <div className="profit-ranking-table-head" role="row">
            <span role="columnheader">排名</span><span role="columnheader">项目</span><span role="columnheader">收入</span><span role="columnheader">支出</span><span role="columnheader">耗时</span><span role="columnheader">利润</span><span role="columnheader">每小时收益</span>
          </div>
          {visibleRanking.map((item, index) => {
            const rank = safeRankingPage * rankingPageSize + index;
            const customer = snapshot.customers.find((entry) => entry.id === item.project.customerId);
            return <article className="profit-ranking-row" role="row" key={item.project.id}>
              <i className="profit-rank" role="cell">{rank + 1}</i>
              <span className="profit-project-cell" role="cell"><b>{item.project.name}</b><small>{[item.project.type, customer?.name].filter(Boolean).join(" · ") || projectKindLabel[projectKindOf(item.project)]}</small><BarProgress value={item.profit > 0 ? item.profit / maxProfit * 100 : 0} tone={rank === 0 ? "green" : "purple"} /></span>
              <span className="profit-value-cell profit-income-cell" role="cell"><small>收入</small><b>{money.format(item.income)}</b></span>
              <span className="profit-value-cell profit-expense-cell" role="cell"><small>支出</small><b>{money.format(item.expenses)}</b></span>
              <span className="profit-value-cell profit-hours-cell" role="cell"><small>耗时</small><b>{item.actualHours}h</b></span>
              <span className={`profit-value-cell profit-profit-cell ${item.profit < 0 ? "is-negative" : ""}`} role="cell"><small>利润</small><b>{money.format(item.profit)}</b></span>
              <span className={`profit-value-cell profit-hourly-cell ${item.hourlyIncome < 0 ? "is-negative" : ""}`} role="cell"><small>每小时收益</small><b>{money.format(item.hourlyIncome)}/h</b></span>
            </article>;
          })}
        </div> : <div className="profit-ranking-empty"><i><ChartLineUp size={30} weight="duotone" /></i><span><b>暂无收益排行</b><small>导入项目、收入和支出后，这里会自动计算真实利润。</small></span></div>}
        {ranking.length > 0 && <footer className="profit-ranking-pagination"><span>显示 {safeRankingPage * rankingPageSize + 1}–{Math.min((safeRankingPage + 1) * rankingPageSize, ranking.length)} / 共 {ranking.length} 个项目</span><nav aria-label="项目收益排行分页"><button type="button" aria-label="上一页" disabled={safeRankingPage === 0} onClick={() => setRankingPage((page) => Math.max(0, page - 1))}><ArrowLeft size={14} /></button><strong>{safeRankingPage + 1} / {rankingPageCount}</strong><button type="button" aria-label="下一页" disabled={safeRankingPage >= rankingPageCount - 1} onClick={() => setRankingPage((page) => Math.min(rankingPageCount - 1, page + 1))}><ArrowRight size={14} /></button></nav></footer>}
      </Surface>

      <Surface className="profit-structure-panel">
        <SurfaceTitle eyebrow="PROFIT STRUCTURE" title="月度与年度利润结构" action={<div className="profit-structure-legend"><span><i className="income" />收入</span><span><i className="expense" />支出</span></div>} />
        {hasProfitStructure ? <div className="profit-structure-chart" role="img" aria-label={`本月收入 ${money.format(summary.monthlyIncome)}，本月支出 ${money.format(summary.monthlyExpenses)}，本年收入 ${money.format(summary.yearlyIncome)}，本年支出 ${money.format(summary.yearlyExpenses)}`}>
          {structureItems.map((item) => <article className={`profit-structure-${item.tone}`} key={item.id}><div><b>{money.format(item.value)}</b><i className={item.value ? undefined : "is-zero"} aria-hidden="true" style={{ height: `${item.value ? Math.max(34, item.value / structureMax * 288) : 4}px` }} /></div><span>{item.period}{item.label}</span></article>)}
        </div> : <div className="profit-zero-state"><i><ChartLineUp size={28} weight="duotone" /></i><span><b>暂无利润结构数据</b><small>录入收入与支出后，将自动展示月度和年度对比。</small></span></div>}
      </Surface>
    </section>
  </div>;
}

export function EnhancedCustomerManagementPage({ snapshot, onCreateCustomer, onSnapshotChange, globalSearch, onOpenRequirements }: { snapshot: LedgerSnapshot; onCreateCustomer: () => void; onSnapshotChange: (snapshot: LedgerSnapshot) => void; globalSearch: string; onOpenRequirements: (customerId: string) => void }) {
  const [selected, setSelected] = useState(snapshot.customers[0]?.id || "");
  const [lifecycle, setLifecycle] = useState<"following" | "won" | "lost">("following");
  const [channel, setChannel] = useState<"all" | "xianyu" | "wechat">("all");
  const [requirementCount, setRequirementCount] = useState(0);
  const customerRows = useMemo(() => snapshot.customers.map((item) => {
    const business = getCustomerBusiness(snapshot, item.id);
    const lifecycleValue: "following" | "won" | "lost" = item.followUpStatus === "inactive"
      ? "lost"
      : business.orderCount > 0 || business.totalSpend > 0 || item.followUpStatus === "won"
      ? "won"
      : "following";
    const channels = new Set([item.source, ...(item.channelIdentities || []).map((identity) => identity.channel)]);
    return { item, business, lifecycle: lifecycleValue, channels };
  }), [snapshot]);
  const lifecycleCounts = {
    following: customerRows.filter((row) => row.lifecycle === "following").length,
    won: customerRows.filter((row) => row.lifecycle === "won").length,
    lost: customerRows.filter((row) => row.lifecycle === "lost").length,
  };
  const visibleRows = customerRows.filter((row) => row.lifecycle === lifecycle)
    .filter((row) => channel === "all" || row.channels.has(channel))
    .filter((row) => `${row.item.name} ${row.item.phone} ${(row.item.tags || []).join(" ")}`.toLowerCase().includes(globalSearch.trim().toLowerCase()));
  const selectedId = visibleRows.some((row) => row.item.id === selected) ? selected : visibleRows[0]?.item.id || "";
  const customer = snapshot.customers.find((item) => item.id === selectedId);
  useEffect(() => {
    if (!selectedId) { setRequirementCount(0); return; }
    let active = true;
    void localPlatformService.customerRequirements(selectedId)
      .then((rows) => { if (active) setRequirementCount(rows.length); })
      .catch(() => { if (active) setRequirementCount(0); });
    return () => { active = false; };
  }, [selectedId]);
  const selectedBusiness = getCustomerBusiness(snapshot, selectedId);
  const nextStatus = () => {
    if (!customer) return;
    const flow: CustomerFollowUpStatus[] = ["new", "contacted", "proposal", "won"];
    const current = customer.followUpStatus;
    const index = flow.indexOf(current);
    const followUpStatus = current === "inactive" ? "contacted" : flow[Math.min(flow.length - 1, Math.max(0, index + 1))];
    onSnapshotChange({ ...snapshot, customers: snapshot.customers.map((item) => item.id === customer.id ? { ...item, followUpStatus, lastContactAt: new Date().toISOString() } : item) });
  };
  const totalSpend = snapshot.customers.reduce((sum, item) => sum + getCustomerBusiness(snapshot, item.id).totalSpend, 0);
  if (!snapshot.customers.length) return <div className="business-page enhanced-crm-page"><section className="business-metrics-grid"><BusinessMetric label="客户总数" value="0 位" detail="项目、订单与联系记录已关联" tone="purple" icon={UsersThree} /><BusinessMetric label="累计消费" value={money.format(0)} detail="按退款后的净到账统计" tone="green" icon={Wallet} /><BusinessMetric label="A级客户" value="0 位" detail="高价值与高复购潜力" tone="orange" icon={Sparkle} /><BusinessMetric label="跟进中" value="0 位" detail="需要继续联系的客户" tone="blue" icon={BellRinging} /></section><BusinessEmptyState icon={UsersThree} title="还没有客户资料" description="客户示例数据已经清空，可以录入自己的第一位客户。" action={<button className="business-primary" onClick={onCreateCustomer}><Plus size={16} />新增客户</button>} /></div>;
  return <div className="business-page enhanced-crm-page"><section className="business-metrics-grid">
    <BusinessMetric label="客户总数" value={`${snapshot.customers.length} 位`} detail="项目、订单与联系记录已关联" tone="purple" icon={UsersThree} />
    <BusinessMetric label="累计消费" value={money.format(totalSpend)} detail="按退款后的净到账统计" tone="green" icon={Wallet} />
    <BusinessMetric label="A级客户" value={`${snapshot.customers.filter((item) => item.level === "A").length} 位`} detail="高价值与高复购潜力" tone="orange" icon={Sparkle} />
    <BusinessMetric label="跟进中" value={`${lifecycleCounts.following} 位`} detail="尚未形成真实成交的客户" tone="blue" icon={BellRinging} />
  </section><section className="crm-layout"><main><Surface>
    <SurfaceTitle eyebrow="CUSTOMER PIPELINE" title={globalSearch ? `客户搜索结果 · ${visibleRows.length}` : "客户经营列表"} action={<button className="business-primary" onClick={onCreateCustomer}><Plus size={16} />新增客户</button>} />
    <div className="crm-classification" aria-label="客户生命周期分类">
      <div role="tablist">{([ ["following", "跟进中"], ["won", "已成交"], ["lost", "已流失"] ] as const).map(([value, label]) => <button type="button" role="tab" aria-selected={lifecycle === value} className={lifecycle === value ? "active" : ""} onClick={() => setLifecycle(value)} key={value}>{label}<b>{lifecycleCounts[value]}</b></button>)}</div>
      <nav aria-label="客户渠道筛选">{([ ["all", "全部"], ["xianyu", "闲鱼"], ["wechat", "微信"] ] as const).map(([value, label]) => <button type="button" aria-pressed={channel === value} className={channel === value ? "active" : ""} onClick={() => setChannel(value)} key={value}>{label}</button>)}</nav>
    </div>
    {visibleRows.length ? <div className="crm-table"><div><span>客户</span><span>跟进状态</span><span>最近联系</span><span>历史订单</span><span>消费金额</span><span>客户等级</span></div>{visibleRows.map(({ item, business }) => { const status = item.followUpStatus; return <button className={selectedId === item.id ? "active" : ""} onClick={() => setSelected(item.id)} key={item.id}><span><i>{item.name.slice(0, 1)}</i><b>{item.name}<small>{item.phone || (item.source === "xianyu" ? "闲鱼客户" : "暂无联系方式")}</small></b></span><em className={`follow-${status}`}>{followLabel[status]}</em><time>{shortDate(item.lastContactAt)}</time><strong>{business.orderCount} 单</strong><strong>{money.format(business.totalSpend)}</strong><i className={`customer-level level-${item.level}`}>{item.level}</i></button>; })}</div> : <div className="crm-filter-empty"><MagnifyingGlass size={28} weight="duotone" /><b>当前分类没有客户</b><small>{globalSearch ? "尝试清除搜索词或切换分类、渠道。" : "切换生命周期或渠道查看其他客户。"}</small></div>}
  </Surface></main>{customer ? <aside><Surface className="customer-profile"><div className="customer-profile-head"><i>{customer.name.slice(0, 1)}</i><span><small>{customer.source === "xianyu" ? "闲鱼客户" : customer.source === "wechat" ? "微信客户" : customer.source === "referral" ? "转介绍" : "其他来源"}</small><h3>{customer.name}</h3><p>{customer.phone || "暂无联系方式"}</p></span><b className={`customer-level level-${customer.level}`}>{customer.level}</b></div><div className="customer-profile-stats"><span><small>历史订单</small><b>{selectedBusiness.orderCount}</b></span><span><small>累计消费</small><b>{money.format(selectedBusiness.totalSpend)}</b></span><span><small>最近联系</small><b>{shortDate(customer.lastContactAt)}</b></span></div><div className="customer-tags">{customer.tags?.map((tag) => <i key={tag}>{tag}</i>)}</div><button className="customer-blueprint-entry" onClick={() => onOpenRequirements(customer.id)}><FileText size={17} weight="duotone" /><span><b>需求蓝图</b><small>{requirementCount ? `${requirementCount} 个需求案例` : "查看或导入客户需求"}</small></span><ArrowRight size={15} /></button><button className="business-primary wide" onClick={nextStatus}><NotePencil size={16} />{customer.followUpStatus === "inactive" ? "重新开始跟进" : "记录本次跟进"}</button></Surface><Surface><SurfaceTitle eyebrow="ORDER HISTORY" title="历史订单" /><div className="customer-order-list">{selectedBusiness.projects.length ? selectedBusiness.projects.map((project) => { const financial = getProjectFinancials(snapshot).find((item) => item.project.id === project.id)!; return <article key={project.id}><i><Briefcase size={17} /></i><span><b>{project.name}</b><small>{shortDate(project.startDate)} · {project.status === "completed" ? "已完成" : "进行中"}</small></span><strong>{money.format(project.totalAmount)}<small>净到账 {money.format(financial.income)}</small></strong></article>; }) : <div className="customer-order-empty">暂无成交项目，需求蓝图可在成交前独立存在。</div>}</div></Surface></aside> : null}</section></div>;
}

interface RequirementResult {
  type: string;
  features: string[];
  days: number;
  price: [number, number];
  risks: string[];
  estimatedHours: number;
  pricingBlocked: boolean;
  raw: BusinessRequirementAnalysis;
}

function analyzeRequirement(content: string): RequirementResult {
  const isMini = /小程序|微信/.test(content);
  const days = isMini ? 16 : 20;
  const raw: BusinessRequirementAnalysis = {
    project_type: isMini ? "微信小程序定制开发" : "Web 定制应用",
    features: ["核心业务流程", "管理后台", "部署与交付"],
    estimated_days_min: days,
    estimated_days_max: days + 4,
    estimated_hours: days * 5,
    risks: ["需求边界需要确认"],
    scope_notes: [],
    quote_min: null,
    quote_max: null,
    hourly_rate: null,
    pricing_blocked: true,
  };
  return { type: raw.project_type, features: raw.features, days, price: [0, 0], risks: raw.risks, estimatedHours: raw.estimated_hours, pricingBlocked: true, raw };
}

function LegacyAIWorkspacePage({ snapshot }: { snapshot: LedgerSnapshot }) {
  const [tool, setTool] = useState<"requirements" | "quote" | "review">("requirements");
  const [content, setContent] = useState("");
  const [requirement, setRequirement] = useState<RequirementResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [quoteReady, setQuoteReady] = useState(false);
  const [serverQuote, setServerQuote] = useState<BusinessQuote | null>(null);
  const [complexity, setComplexity] = useState<"standard" | "advanced" | "complex">("advanced");
  const [reviewProject, setReviewProject] = useState(snapshot.projects[0]?.id || "");
  const [reviewReady, setReviewReady] = useState(false);
  const [reviewInsight, setReviewInsight] = useState<BusinessReview | null>(null);
  const [aiError, setAiError] = useState("");
  const run = async (callback: () => Promise<void> | void) => {
    setBusy(true);
    setAiError("");
    try {
      await callback();
    } catch (error) {
      setAiError(error instanceof Error ? error.message : "本机 AI 任务失败");
    } finally {
      setBusy(false);
    }
  };
  const review = getProjectFinancials(snapshot).find((item) => item.project.id === reviewProject) || {
    project: { id: "", name: "尚未导入项目", customerId: "", totalAmount: 0, startDate: "2026-05-28", dueDate: "2026-05-28", progress: 0, status: "pending" as const, accent: "blue" as const, type: "等待项目数据" },
    income: 0,
    expenses: 0,
    profit: 0,
    outstanding: 0,
    paymentProgress: 0,
    actualHours: 0,
    hourlyIncome: 0,
  };
  const tools = [["requirements", "AI 需求分析", Brain, "把聊天内容变成可执行方案"], ["quote", "AI 报价生成", FileText, "生成报价单、付款计划与交付说明"], ["review", "AI 项目复盘", ChartLineUp, "分析收益、时间成本与定价空间"]] as const;
  const quoteTotal = serverQuote?.total_amount || 0;
  const exportQuote = () => {
    const content = [`${requirement?.type || "Web 定制应用"}项目报价单`, `建议总报价：${money.format(quoteTotal)}`, `预计工时：${serverQuote?.estimated_hours || 0} 小时`, `目标时薪：${money.format(serverQuote?.hourly_rate || 0)}/小时`, `复杂度：${complexity === "standard" ? "标准" : complexity === "advanced" ? "进阶" : "复杂"}`, "付款计划：30% 定金 / 40% 阶段款 / 30% 尾款", `交付：${serverQuote?.delivery_note || "等待服务端生成"}`].join("\n");
    const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `项目报价单-${new Date().toISOString().slice(0, 10)}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return <div className="business-page ai-workspace-page"><section className="ai-hero"><div><span><Sparkle size={15} weight="fill" /> PERSONAL BUSINESS COPILOT</span><h2>AI 经营助手</h2><p>从客户聊天到项目报价，再到交付后的利润复盘，把经验沉淀成下一次更好的经营决策。</p></div><i><Robot size={76} weight="duotone" /></i></section><section className="ai-layout"><nav>{tools.map(([key, label, Icon, description]) => <button className={tool === key ? "active" : ""} onClick={() => setTool(key)} key={key}><i><Icon size={22} weight="duotone" /></i><span><b>{label}</b><small>{description}</small></span><CaretRight size={16} /></button>)}<div className="ai-privacy"><CheckCircle size={18} weight="fill" /><span><b>独立工作区</b><small>分析结果只用于当前经营决策</small></span></div></nav><main>
    {tool === "requirements" && <><Surface className="ai-input-card"><SurfaceTitle eyebrow="01 / REQUIREMENT" title="粘贴客户聊天内容" /><textarea value={content} onChange={(event) => setContent(event.target.value)} rows={7} placeholder="粘贴客户的聊天记录、需求描述或语音转文字内容…" /><div><span>{content.length} 字 · 内容越完整，分析越准确</span><button className="ai-run-button" disabled={busy || !content.trim()} onClick={() => run(() => setRequirement(analyzeRequirement(content)))}>{busy ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}开始智能分析</button></div></Surface>{requirement && <div className="ai-result-grid"><Surface><SurfaceTitle eyebrow="PROJECT TYPE" title="项目类型" /><strong className="ai-result-primary">{requirement.type}</strong><p>匹配度 92% · 建议采用敏捷里程碑交付</p></Surface><Surface><SurfaceTitle eyebrow="ESTIMATE" title="工期与报价" /><div className="ai-estimate"><span><small>工期预测</small><b>{requirement.days}–{requirement.days + 4} 天</b></span><span><small>报价建议</small><b>{money.format(requirement.price[0])}–{money.format(requirement.price[1])}</b></span></div></Surface><Surface className="ai-feature-result"><SurfaceTitle eyebrow="SCOPE" title="功能列表" /><ul>{requirement.features.map((feature) => <li key={feature}><CheckCircle size={16} weight="fill" />{feature}</li>)}</ul></Surface><Surface className="ai-risk-result"><SurfaceTitle eyebrow="RISKS" title="风险提醒" /><ul>{requirement.risks.map((risk) => <li key={risk}><WarningCircle size={16} weight="fill" />{risk}</li>)}</ul></Surface><button className="ai-next-step" onClick={() => { setTool("quote"); setQuoteReady(false); }}>使用本次分析生成报价 <ArrowRight size={16} /></button></div>}</>}
    {tool === "quote" && <section className="quote-workspace"><Surface className="quote-settings"><SurfaceTitle eyebrow="02 / QUOTE" title="AI 报价配置" /><label><span>项目类型</span><input value={requirement?.type || "Web 定制应用"} readOnly /></label><label><span>复杂度</span><div className="complexity-options"><button className={complexity === "standard" ? "active" : ""} onClick={() => { setComplexity("standard"); setQuoteReady(false); }}>标准</button><button className={complexity === "advanced" ? "active" : ""} onClick={() => { setComplexity("advanced"); setQuoteReady(false); }}>进阶</button><button className={complexity === "complex" ? "active" : ""} onClick={() => { setComplexity("complex"); setQuoteReady(false); }}>复杂</button></div></label><label><span>预计工期</span><input value={`${requirement?.days || 18}–${(requirement?.days || 18) + 4} 天`} readOnly /></label><button className="ai-run-button wide" disabled={busy} onClick={() => run(() => setQuoteReady(true))}>{busy ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}生成完整报价方案</button></Surface>{quoteReady ? <Surface className="quote-document"><div className="quote-document-head"><span><small>报价单编号</small><b>XY-{new Date().getFullYear()}-081</b></span><div><h3>{requirement?.type || "Web 定制应用"}项目报价单</h3><p>有效期 7 天 · 含税前服务报价</p></div><i><FileText size={42} weight="duotone" /></i></div><div className="quote-items">{[["需求与原型", quoteTotal * .12], ["UI 与前端开发", quoteTotal * .31], ["核心功能与接口", quoteTotal * .45], ["测试、部署与交付", quoteTotal * .12]].map(([name, price]) => <p key={String(name)}><span>{name}</span><b>{money.format(Number(price))}</b></p>)}</div><div className="quote-total"><span>建议总报价<small>已包含复杂度与风险缓冲</small></span><strong>{money.format(quoteTotal)}</strong></div><h4>付款计划</h4><div className="quote-payment-plan"><span><b>30%</b><small>定金 · 项目启动</small></span><span><b>40%</b><small>阶段款 · 核心功能完成</small></span><span><b>30%</b><small>尾款 · 验收上线</small></span></div><div className="delivery-note"><b>交付说明</b><p>交付源代码、部署包、操作说明与 30 天缺陷维护。新增需求经双方确认后单独评估报价与工期。</p></div><button className="business-primary wide" onClick={exportQuote}>导出报价单</button></Surface> : <Surface className="quote-empty"><FileText size={55} weight="duotone" /><h3>等待生成报价单</h3><p>AI 将结合项目类型、功能范围、工期与风险缓冲生成付款计划和交付说明。</p></Surface>}</section>}
    {tool === "review" && <section className="review-workspace"><Surface><SurfaceTitle eyebrow="03 / RETROSPECT" title="选择已进行项目" /><select value={reviewProject} onChange={(event) => { setReviewProject(event.target.value); setReviewReady(false); }}>{snapshot.projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select><div className="review-project-preview"><Briefcase size={31} weight="duotone" /><span><b>{review.project.name}</b><small>{review.project.type} · 当前进度 {review.project.progress}%</small></span><em>{money.format(review.project.totalAmount)}</em></div><button className="ai-run-button wide" disabled={busy} onClick={() => run(() => setReviewReady(true))}>{busy ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}开始 AI 项目复盘</button></Surface>{reviewReady ? <div className="review-results"><Surface><small>实际收益</small><strong>{money.format(review.profit)}</strong><p>已收 {money.format(review.income)} - 成本 {money.format(review.expenses)}</p></Surface><Surface><small>时间成本</small><strong>{review.actualHours} 小时</strong><p>小时收益 {money.format(review.hourlyIncome)}</p></Surface><Surface><small>回款状态</small><strong>{review.paymentProgress.toFixed(0)}%</strong><p>仍有 {money.format(review.outstanding)} 待收</p></Surface><Surface className="pricing-advice"><Sparkle size={25} weight="fill" /><span><small>AI 定价建议</small><h3>{review.hourlyIncome < 220 ? "下一单建议提高报价 18%" : "当前报价健康，可上调 8%–12%"}</h3><p>该项目实际工时与沟通成本高于计划。建议拆分需求确认费，并把超出两轮的修改纳入变更报价。</p></span></Surface></div> : <Surface className="quote-empty"><ChartLineUp size={55} weight="duotone" /><h3>等待生成经营复盘</h3><p>AI 会结合项目收入、关联支出、任务工时和回款进度判断是否需要提高报价。</p></Surface>}</section>}
  </main></section></div>;
}

type XunyingEvidenceFact = {
  id: string;
  label: string;
  value: string;
  detail: string;
  complete: boolean;
  targetPage: string;
};

export function buildXunyingDecision(snapshot: LedgerSnapshot) {
  const summary = getBusinessSummary(snapshot);
  const deliveredProjects = snapshot.projects.filter((project) => project.status === "delivered" || project.status === "completed").length;
  const completedSamples = Math.max(snapshot.completedOrderCount || 0, deliveredProjects);
  const confirmedPayments = snapshot.payments.filter((payment) => payment.status === "confirmed" || payment.status === "refunded").length;
  const deliveryEvidence = snapshot.logs.length + snapshot.attachments.length;
  const facts: XunyingEvidenceFact[] = [
    {
      id: "projects",
      label: "项目样本",
      value: `${snapshot.projects.length} 个真实项目`,
      detail: `${completedSamples} 个已交付或完成样本`,
      complete: completedSamples >= 2,
      targetPage: "项目管理",
    },
    {
      id: "cashflow",
      label: "收支记录",
      value: `${confirmedPayments} 笔确认收款 · ${snapshot.expenses.length} 笔支出`,
      detail: confirmedPayments > 0 && snapshot.expenses.length > 0 ? "已有真实现金流记录" : "需要同时具备确认收款与支出",
      complete: confirmedPayments > 0 && snapshot.expenses.length > 0,
      targetPage: confirmedPayments > 0 ? "支出记录" : "收入记录",
    },
    {
      id: "hours",
      label: "工时证据",
      value: `${summary.actualHours} 小时实际工时`,
      detail: summary.actualHours > 0 ? "来自项目任务实际工时" : "尚未记录实际工时",
      complete: summary.actualHours > 0,
      targetPage: "项目管理",
    },
    {
      id: "delivery",
      label: "交付证据",
      value: `${snapshot.logs.length} 条日志 · ${snapshot.attachments.length} 个附件`,
      detail: deliveryEvidence > 0 ? "已有可回查的交付记录" : "尚无日志或交付附件",
      complete: deliveryEvidence > 0,
      targetPage: "项目管理",
    },
  ];
  const missingFacts = facts.filter((fact) => !fact.complete);
  const baselineReady = missingFacts.length === 0;
  const targetHourlyRate = snapshot.settings.targetHourlyRate || 0;
  const belowTarget = targetHourlyRate > 0 && summary.averageHourlyIncome < targetHourlyRate;
  const profitable = summary.actualProfit > 0 && !belowTarget;
  const headline = !baselineReady
    ? "当前证据不足，先补齐经营基线，再决定是否扩大投入"
    : profitable
      ? "经营基线已经形成，优先复用高收益交付方式"
      : "经营基线已经形成，先修复利润与工时结构，再扩大投入";
  const reason = !baselineReady
    ? `当前已有 ${snapshot.projects.length} 个项目、${confirmedPayments} 笔确认收款和 ${summary.actualHours} 小时实际工时，但${missingFacts.map((fact) => fact.label).join("、")}尚未形成可复用基线。`
    : profitable
      ? "收支、工时与交付证据已经形成闭环，现有数据支持先复用已验证的交付方式。"
      : "证据已经形成闭环，但利润或单位工时收益尚未达到当前经营目标。";

  return {
    facts,
    missingFacts,
    baselineReady,
    headline,
    reason,
    confidence: baselineReady ? "中" : completedSamples > 0 ? "待验证" : "低",
    confidenceDetail: baselineReady ? "事实链完整，仍需持续复验" : "关键样本未闭环，暂不输出确定结论",
    counterargument: "样本不足不等于方向错误；近期成交、线下沟通或未回填工时可能尚未进入当前账本。",
    failureCondition: "补齐已完成项目的收支、工时和交付证据后，如单位时间利润与回款保持稳定，本判断应被推翻并重新计算。",
    nextEvidencePage: missingFacts[0]?.targetPage || "项目管理",
  };
}

export function AIWorkspacePage({ snapshot, onNavigate }: { snapshot: LedgerSnapshot; onNavigate: (page: string) => void }) {
  const [tool, setTool] = useState<"requirements" | "quote" | "review">("requirements");
  const [workflowExpanded, setWorkflowExpanded] = useState(false);
  const [content, setContent] = useState("");
  const [analysis, setAnalysis] = useState<BusinessRequirementAnalysis | null>(null);
  const [quote, setQuote] = useState<BusinessQuote | null>(null);
  const [complexity, setComplexity] = useState<"standard" | "advanced" | "complex">("advanced");
  const [reviewProject, setReviewProject] = useState(snapshot.projects[0]?.id || "");
  const [reviewInsight, setReviewInsight] = useState<BusinessReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [challengeOpen, setChallengeOpen] = useState(false);
  const evidenceDrawerRef = useRef<HTMLElement>(null);
  const evidenceTriggerRef = useRef<HTMLButtonElement | null>(null);
  const workflowRef = useRef<HTMLElement>(null);
  const financials = getProjectFinancials(snapshot);
  const review = financials.find((item) => item.project.id === reviewProject) || financials[0];
  const decision = useMemo(() => buildXunyingDecision(snapshot), [snapshot]);
  const tools = [
    ["requirements", "需求分析", Brain, "把真实客户材料拆成可交付范围"],
    ["quote", "规则报价", FileText, "AI 拆工时，服务端规则计算金额"],
    ["review", "项目复盘", ChartLineUp, "读取真实收支、工时与回款"],
  ] as const;

  const openEvidence = (trigger: HTMLButtonElement, challenge = false) => {
    evidenceTriggerRef.current = trigger;
    setChallengeOpen(challenge);
    setEvidenceOpen(true);
  };

  const closeEvidence = () => {
    setEvidenceOpen(false);
    setChallengeOpen(false);
    window.requestAnimationFrame(() => evidenceTriggerRef.current?.focus());
  };

  const openWorkflow = (nextTool: "requirements" | "quote" | "review") => {
    setTool(nextTool);
    setWorkflowExpanded(true);
    setError("");
    window.requestAnimationFrame(() => workflowRef.current?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "start",
    }));
  };

  useEffect(() => {
    if (!evidenceOpen) return;
    const drawer = evidenceDrawerRef.current;
    const frame = window.requestAnimationFrame(() => drawer?.focus());
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeEvidence();
        return;
      }
      if (event.key !== "Tab" || !drawer) return;
      const focusable = Array.from(drawer.querySelectorAll<HTMLElement>(
        "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
      )).filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) {
        event.preventDefault();
        drawer.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (document.activeElement === drawer) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!drawer.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [evidenceOpen]);

  const run = async (task: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "本机 AI 任务失败");
    } finally {
      setBusy(false);
    }
  };

  const analyze = () => run(async () => {
    const result = await localPlatformService.analyzeBusinessRequirement(content.trim());
    setAnalysis(result);
    setQuote(null);
  });

  const generateQuote = () => {
    if (!analysis) {
      setError("请先完成需求分析");
      return;
    }
    void run(async () => {
      setQuote(await localPlatformService.createBusinessQuote(analysis, complexity, snapshot.settings.quoteRiskBuffer ?? 0.15));
    });
  };

  const generateReview = () => {
    if (!review) {
      setError("请先导入一个真实项目");
      return;
    }
    void run(async () => {
      setReviewInsight(await localPlatformService.reviewBusinessProject({
        project: review.project,
        income: review.income,
        expenses: review.expenses,
        profit: review.profit,
        actual_hours: review.actualHours,
        hourly_income: review.hourlyIncome,
        outstanding: review.outstanding,
        payment_progress: review.paymentProgress,
      }));
    });
  };

  const exportQuote = () => {
    if (!quote || !analysis) return;
    const lines = [
      `${analysis.project_type}项目报价单`,
      `建议总报价：${money.format(quote.total_amount)}`,
      `预计工时：${quote.estimated_hours} 小时`,
      `目标时薪：${money.format(quote.hourly_rate)}/小时`,
      `风险缓冲：${Math.round(quote.risk_buffer * 100)}%`,
      ...quote.items.map((item) => `${item.name}：${money.format(item.amount)}`),
      `付款计划：${quote.payment_plan.map((item) => `${item.label} ${Math.round(item.ratio * 100)}%`).join(" / ")}`,
      `交付说明：${quote.delivery_note}`,
    ];
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `项目报价单-${new Date().toISOString().slice(0, 10)}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return <div className="business-page ai-workspace-page xunying-workbench">
    <section className="xunying-page-heading" aria-labelledby="xunying-today-title">
      <div>
        <img src="/assets/xunying/xiaoce-avatar.png" alt="" aria-hidden="true" />
        <span><small>循营 · 一人经营台</small><h2 id="xunying-today-title">小策 · 今日判断</h2></span>
      </div>
      <p>先看事实，再看反方条件，最后只决定一个清晰的下一步。</p>
    </section>

    <section className="xunying-decision-grid" aria-label="今日经营判断">
      <section className="xunying-evidence-panel xunying-facts-panel">
        <header><span><FileText size={19} weight="duotone" />事实来源</span><small>{decision.facts.filter((fact) => fact.complete).length}/{decision.facts.length} 项形成基线</small></header>
        <div className="xunying-fact-list">
          {decision.facts.map((fact) => <article className={fact.complete ? "is-ready" : "is-missing"} key={fact.id}><i><CheckCircle size={15} weight={fact.complete ? "fill" : "regular"} /></i><span><b>{fact.label}</b><strong>{fact.value}</strong><small>{fact.detail}</small></span></article>)}
        </div>
        <button type="button" className="xunying-panel-link" onClick={(event) => openEvidence(event.currentTarget)}>查看证据清单 <ArrowRight size={15} /></button>
      </section>

      <article className="xunying-judgment-panel">
        <span className="xunying-judgment-eyebrow"><Sparkle size={16} weight="fill" />本次关键判断</span>
        <h3>{decision.headline}</h3>
        <div className="xunying-reasoning"><Lightbulb size={22} weight="duotone" /><span><b>判断依据</b><p>{decision.reason}</p></span></div>
      </article>

      <section className="xunying-evidence-panel xunying-knowledge-panel">
        <header><span><BookOpenText size={19} weight="duotone" />知识引用</span><small>可追溯来源</small></header>
        <div className="xunying-knowledge-empty"><BookOpenText size={42} weight="duotone" /><b>暂无匹配知识引用</b><p>当前判断只使用本机经营账本，不把通用经验伪装成你的历史知识。</p></div>
        <button type="button" className="xunying-panel-link" onClick={(event) => openEvidence(event.currentTarget)}>查看引用边界 <ArrowRight size={15} /></button>
      </section>
    </section>

    <section className="xunying-audit-band" aria-label="判断审计信息">
      <article><i className="is-confidence"><ShieldCheck size={25} weight="duotone" /></i><span><small>置信度</small><b>{decision.confidence}</b><p>{decision.confidenceDetail}</p></span></article>
      <article><i className="is-counter"><WarningCircle size={25} weight="duotone" /></i><span><small>反方意见</small><b>保留另一种解释</b><p>{decision.counterargument}</p></span></article>
      <article><i className="is-failure"><Target size={25} weight="duotone" /></i><span><small>失败条件</small><b>何时推翻当前判断</b><p>{decision.failureCondition}</p></span></article>
    </section>

    <section className="xunying-next-step" aria-label="建议下一步">
      <div><small>下一步</small><strong>{decision.baselineReady ? "用真实项目复盘验证判断" : `优先补齐：${decision.missingFacts.map((fact) => fact.label).join("、")}`}</strong></div>
      <button type="button" className="xunying-primary-action" onClick={(event) => openEvidence(event.currentTarget)}><Target size={20} weight="duotone" />补齐经营基线 <ArrowRight size={18} /></button>
      <button type="button" className="xunying-secondary-action" onClick={(event) => openEvidence(event.currentTarget)}><NotePencil size={18} />记录可验证证据</button>
      <button type="button" className="xunying-secondary-action" onClick={(event) => openEvidence(event.currentTarget, true)}><ShieldCheck size={18} />挑战当前判断</button>
    </section>

    <section ref={workflowRef} className="xunying-workflow" aria-labelledby="xunying-workflow-title">
      <header><div><span>已保留的真实能力</span><h3 id="xunying-workflow-title">接单工作流</h3><p>从材料梳理到报价与复盘，所有真实写入和对外动作仍保留人工确认边界。</p></div><small><ShieldCheck size={16} weight="fill" />本机安全执行</small></header>
      <nav className="xunying-workflow-tabs" role="tablist" aria-label="接单工作流工具">
        {tools.map(([key, label, Icon, description], index) => <button type="button" role="tab" aria-selected={workflowExpanded && tool === key} aria-expanded={workflowExpanded && tool === key} aria-controls="xunying-workflow-panel" className={workflowExpanded && tool === key ? "active" : ""} onClick={() => openWorkflow(key)} key={key}><i><Icon size={21} weight="duotone" /></i><span><em>{index + 1}</em><b>{label}</b><small>{description}</small></span><CaretRight size={16} /></button>)}
      </nav>
      {workflowExpanded && <main id="xunying-workflow-panel" className="xunying-workflow-content" role="tabpanel" aria-label={tools.find(([key]) => key === tool)?.[1]}>
        {error && <div className="ai-backend-error" role="alert"><WarningCircle size={18} weight="fill" /><span><b>任务未完成</b><small>{error}</small></span></div>}
        {tool === "requirements" && <>
          <Surface className="ai-input-card"><SurfaceTitle eyebrow="01 / REQUIREMENT" title="粘贴客户聊天内容" /><textarea value={content} onChange={(event) => setContent(event.target.value)} rows={7} placeholder="粘贴客户的聊天记录、需求描述或语音转文字内容…" /><div><span>{content.length} 字 · 内容只传给本机 Codex 进程</span><button className="ai-run-button" disabled={busy || content.trim().length < 10} onClick={() => void analyze()}>{busy ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}开始真实分析</button></div></Surface>
          {analysis && <div className="ai-result-grid">
            <Surface><SurfaceTitle eyebrow="PROJECT TYPE" title="项目类型" /><strong className="ai-result-primary">{analysis.project_type}</strong><p>预计投入 {analysis.estimated_hours} 小时 · 建议里程碑交付</p></Surface>
            <Surface><SurfaceTitle eyebrow="ESTIMATE" title="工期与规则报价" /><div className="ai-estimate"><span><small>工期预测</small><b>{analysis.estimated_days_min}–{analysis.estimated_days_max} 天</b></span><span><small>报价建议</small><b>{analysis.pricing_blocked ? "请先设置目标时薪" : `${money.format(analysis.quote_min || 0)}–${money.format(analysis.quote_max || 0)}`}</b></span></div></Surface>
            <Surface className="ai-feature-result"><SurfaceTitle eyebrow="SCOPE" title="功能列表" /><ul>{analysis.features.map((feature) => <li key={feature}><CheckCircle size={16} weight="fill" />{feature}</li>)}</ul></Surface>
            <Surface className="ai-risk-result"><SurfaceTitle eyebrow="RISKS" title="风险提醒" /><ul>{analysis.risks.map((risk) => <li key={risk}><WarningCircle size={16} weight="fill" />{risk}</li>)}</ul></Surface>
            <button className="ai-next-step" onClick={() => { setTool("quote"); setQuote(null); }}>使用本次分析生成规则报价 <ArrowRight size={16} /></button>
          </div>}
        </>}

        {tool === "quote" && <section className="quote-workspace">
          <Surface className="quote-settings"><SurfaceTitle eyebrow="02 / QUOTE" title="报价规则配置" /><label><span>项目类型</span><input value={analysis?.project_type || "等待需求分析"} readOnly /></label><label><span>复杂度</span><div className="complexity-options">{(["standard", "advanced", "complex"] as const).map((value) => <button className={complexity === value ? "active" : ""} onClick={() => { setComplexity(value); setQuote(null); }} key={value}>{value === "standard" ? "标准" : value === "advanced" ? "进阶" : "复杂"}</button>)}</div></label><label><span>AI 预计工时</span><input value={analysis ? `${analysis.estimated_hours} 小时` : "等待需求分析"} readOnly /></label><button className="ai-run-button wide" disabled={busy || !analysis} onClick={generateQuote}>{busy ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}按目标时薪生成报价</button></Surface>
          {quote ? <Surface className="quote-document"><div className="quote-document-head"><span><small>报价状态</small><b>等待人工确认</b></span><div><h3>{analysis?.project_type}项目报价单</h3><p>{quote.estimated_hours} 小时 · 风险缓冲 {Math.round(quote.risk_buffer * 100)}%</p></div><i><FileText size={42} weight="duotone" /></i></div><div className="quote-items">{quote.items.map((item) => <p key={item.name}><span>{item.name}</span><b>{money.format(item.amount)}</b></p>)}</div><div className="quote-total"><span>建议总报价<small>{money.format(quote.hourly_rate)}/小时 · 按百元取整</small></span><strong>{money.format(quote.total_amount)}</strong></div><h4>付款计划</h4><div className="quote-payment-plan">{quote.payment_plan.map((item) => <span key={item.type}><b>{Math.round(item.ratio * 100)}%</b><small>{item.label} · {money.format(item.amount)}</small></span>)}</div><div className="delivery-note"><b>交付说明</b><p>{quote.delivery_note}</p></div><button className="business-primary wide" onClick={exportQuote}>导出待确认报价单</button></Surface> : <Surface className="quote-empty"><FileText size={55} weight="duotone" /><h3>等待生成报价单</h3><p>{analysis ? "金额由阶段工时、目标时薪和风险缓冲确定，不由 AI 直接拍价。" : "请先在需求分析中生成结构化范围和工时。"}</p></Surface>}
        </section>}

        {tool === "review" && <section className="review-workspace">
          <Surface><SurfaceTitle eyebrow="03 / RETROSPECT" title="选择真实项目" /><select value={review?.project.id || ""} onChange={(event) => { setReviewProject(event.target.value); setReviewInsight(null); }}>{snapshot.projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select>{review ? <div className="review-project-preview"><Briefcase size={31} weight="duotone" /><span><b>{review.project.name}</b><small>{review.project.type} · 当前进度 {review.project.progress}%</small></span><em>{money.format(review.project.totalAmount)}</em></div> : <div className="review-project-preview"><Briefcase size={31} weight="duotone" /><span><b>尚未导入项目</b><small>复盘不会使用演示数据</small></span></div>}<button className="ai-run-button wide" disabled={busy || !review} onClick={generateReview}>{busy ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}读取真实经营数据并复盘</button></Surface>
          {review && reviewInsight ? <div className="review-results"><Surface><small>实际收益</small><strong>{money.format(review.profit)}</strong><p>已收 {money.format(review.income)} - 成本 {money.format(review.expenses)}</p></Surface><Surface><small>时间成本</small><strong>{review.actualHours} 小时</strong><p>小时收益 {money.format(review.hourlyIncome)}</p></Surface><Surface><small>回款状态</small><strong>{review.paymentProgress.toFixed(0)}%</strong><p>仍有 {money.format(review.outstanding)} 待收</p></Surface><Surface className="pricing-advice"><Sparkle size={25} weight="fill" /><span><small>Codex 定价建议</small><h3>{reviewInsight.pricing_advice}</h3><p>{reviewInsight.summary}</p><ul>{reviewInsight.improvements.map((item) => <li key={item}>{item}</li>)}</ul></span></Surface></div> : <Surface className="quote-empty"><ChartLineUp size={55} weight="duotone" /><h3>等待生成经营复盘</h3><p>Codex 会读取所选项目的真实收入、关联支出、任务工时与回款进度。</p></Surface>}
        </section>}
      </main>}
    </section>

    {evidenceOpen && <>
      <button type="button" className="xunying-drawer-backdrop" aria-label="关闭判断证据" onClick={closeEvidence} tabIndex={-1} />
      <aside ref={evidenceDrawerRef} id="xunying-evidence-drawer" className="xunying-evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="xunying-evidence-title" tabIndex={-1}>
        <header><div><span>本次关键判断</span><h2 id="xunying-evidence-title">判断证据</h2></div><button type="button" aria-label="关闭判断证据" onClick={closeEvidence}><X size={21} /></button></header>
        <div className="xunying-drawer-body">
          <p className="xunying-drawer-judgment">{decision.headline}</p>
          <section><h3><FileText size={19} weight="duotone" />事实来源</h3><div className="xunying-drawer-facts">{decision.facts.map((fact) => <article key={fact.id}><i className={fact.complete ? "is-ready" : "is-missing"}><CheckCircle size={16} weight={fact.complete ? "fill" : "regular"} /></i><span><b>{fact.label}</b><strong>{fact.value}</strong><small>{fact.detail}</small></span><em>{fact.complete ? "已记录" : "待补齐"}</em></article>)}</div><p className="xunying-source-note"><ShieldCheck size={16} weight="fill" />仅使用当前经营台已授权数据</p></section>
          <section><h3><BookOpenText size={19} weight="duotone" />知识引用</h3><div className="xunying-drawer-empty"><b>暂无匹配知识引用</b><p>知识中心尚未提供可追溯条目，本次不会自动补写经验。</p></div></section>
          <section><h3><ShieldCheck size={19} weight="duotone" />推断边界</h3><p>事实、推断与建议分开呈现。小策不会把缺失信息当作事实。</p></section>
          <section className={`xunying-challenge-section ${challengeOpen ? "is-open" : ""}`}><h3><WarningCircle size={19} weight="duotone" />反方意见与失败条件</h3><p>{decision.counterargument}</p><div hidden={!challengeOpen}><b>挑战当前判断时，请先核对：</b><ul><li>是否有尚未录入的成交、回款或支出？</li><li>实际工时和交付证据是否已经回填？</li><li>是否存在能推翻当前结论的新样本？</li></ul><small>{decision.failureCondition}</small></div></section>
        </div>
        <footer><button type="button" className="xunying-drawer-primary" onClick={() => { closeEvidence(); onNavigate(decision.nextEvidencePage); }}><NotePencil size={18} />记录可验证证据</button><button type="button" className="xunying-drawer-secondary" aria-expanded={challengeOpen} onClick={() => setChallengeOpen((value) => !value)}><ShieldCheck size={18} />{challengeOpen ? "收起挑战清单" : "挑战当前判断"}</button></footer>
      </aside>
    </>}

    <nav className="xunying-mobile-nav" aria-label="小策移动导航">
      <button type="button" className="active" onClick={() => onNavigate("AI经营助手")}><House size={22} weight="fill" /><span>首页</span></button>
      <button type="button" onClick={() => onNavigate("客户消息")}><ChatCircleDots size={22} /><span>消息</span></button>
      <button type="button" onClick={() => onNavigate("项目管理")}><Briefcase size={22} /><span>项目</span></button>
      <button type="button" onClick={() => onNavigate("设置中心")}><UserCircle size={22} /><span>我的</span></button>
    </nav>
  </div>;
}
