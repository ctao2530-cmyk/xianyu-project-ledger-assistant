import {
  ArrowLeft,
  ArrowRight,
  BellRinging,
  Brain,
  Briefcase,
  CalendarBlank,
  CaretRight,
  ChartLineUp,
  CheckCircle,
  CircleNotch,
  Clock,
  Coins,
  File,
  FileArchive,
  FileText,
  FolderOpen,
  Gauge,
  Lightbulb,
  ListChecks,
  MagicWand,
  MagnifyingGlass,
  NotePencil,
  Paperclip,
  Plus,
  Robot,
  Sparkle,
  Target,
  Timer,
  TrendUp,
  UploadSimple,
  UserCircle,
  UsersThree,
  WarningCircle,
  Wallet,
  type Icon as PhosphorIcon,
} from "@phosphor-icons/react";
import { type ChangeEvent, type FormEvent, type ReactNode, useMemo, useRef, useState } from "react";
import {
  daysBetween,
  daysUntil,
  getBusinessSummary,
  getCustomerBusiness,
  getProjectFinancials,
} from "../data/businessMetrics";
import type {
  CustomerFollowUpStatus,
  LedgerSnapshot,
  PaymentType,
  ProjectAttachment,
  ProjectLog,
  ProjectTask,
  TaskStatus,
} from "../types";
import "./business-assistant.css";

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
});

const shortDate = (value: string) =>
  new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(value));

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

function ProjectDetail({
  snapshot,
  projectId,
  onBack,
  onSnapshotChange,
}: {
  snapshot: LedgerSnapshot;
  projectId: string;
  onBack: () => void;
  onSnapshotChange: (snapshot: LedgerSnapshot) => void;
}) {
  const project = snapshot.projects.find((item) => item.id === projectId) || snapshot.projects[0];
  const customer = snapshot.customers.find((item) => item.id === project.customerId);
  const financial = getProjectFinancials(snapshot).find((item) => item.project.id === project.id)!;
  const [tab, setTab] = useState<"overview" | "tasks" | "gantt" | "logs" | "files">("overview");
  const tasks = snapshot.tasks.filter((item) => item.projectId === project.id);
  const logs = snapshot.logs.filter((item) => item.projectId === project.id);
  const files = snapshot.attachments.filter((item) => item.projectId === project.id);
  const [logText, setLogText] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const duration = daysBetween(project.startDate, project.dueDate);
  const totalTimeline = Math.max(1, new Date(`${project.dueDate}T00:00:00`).getTime() - new Date(`${project.startDate}T00:00:00`).getTime());
  const updateTask = (taskId: string) => {
    const nextTasks = snapshot.tasks.map((item) => {
      if (item.id !== taskId) return item;
      const status: TaskStatus = item.status === "todo" ? "in_progress" : item.status === "in_progress" ? "done" : "todo";
      return { ...item, status, actualHours: status === "done" && item.actualHours === 0 ? item.estimatedHours : item.actualHours };
    });
    const projectTasks = nextTasks.filter((item) => item.projectId === project.id);
    const progress = projectTasks.length ? Math.round(projectTasks.filter((item) => item.status === "done").length / projectTasks.length * 100) : project.progress;
    const next = { ...snapshot, tasks: nextTasks, projects: snapshot.projects.map((item) => item.id === project.id ? { ...item, progress, status: progress === 100 ? "delivered" as const : progress > 0 ? "in_progress" as const : item.status } : item) };
    onSnapshotChange(next);
  };
  const addTask = () => {
    const index = tasks.length + 1;
    const task: ProjectTask = { id: `task-${Date.now()}`, projectId: project.id, title: `交付检查任务 ${index}`, status: "todo", startDate: new Date().toISOString().slice(0, 10), dueDate: project.dueDate, estimatedHours: 4, actualHours: 0 };
    onSnapshotChange({ ...snapshot, tasks: [...snapshot.tasks, task] });
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
    ["logs", "开发日志", NotePencil], ["files", "项目附件", Paperclip],
  ] as const;

  return <div className="business-page project-detail-page">
    <div className="project-detail-hero">
      <button className="business-back" onClick={onBack}><ArrowLeft size={17} />返回项目列表</button>
      <div className="project-detail-heading"><span className={`project-avatar project-${project.accent}`}><Briefcase size={27} weight="duotone" /></span><div><small>{project.type || "定制开发"} · {customer?.name}</small><h2>{project.name}</h2><p>{project.notes || "围绕交付目标推进开发、验收与回款。"}</p></div><span className="project-health"><i />项目健康度 86</span></div>
      <div className="project-detail-summary"><span><small>自动工期</small><b>{duration} 天</b></span><span><small>计划进度</small><b>{project.progress}%</b></span><span><small>实际投入</small><b>{financial.actualHours} 小时</b></span><span><small>距离交付</small><b>{Math.max(0, daysUntil(project.dueDate))} 天</b></span></div>
    </div>
    <section className="business-metrics-grid project-finance-metrics">
      <BusinessMetric label="合同金额" value={money.format(project.totalAmount)} detail="项目总报价" tone="purple" icon={Wallet} />
      <BusinessMetric label="已收 / 未收" value={`${money.format(financial.income)} / ${money.format(financial.outstanding)}`} detail={`回款进度 ${financial.paymentProgress.toFixed(0)}%`} tone="blue" icon={Coins} />
      <BusinessMetric label="实际利润" value={money.format(financial.profit)} detail={`已扣除成本 ${money.format(financial.expenses)}`} tone="green" icon={TrendUp} />
      <BusinessMetric label="平均小时收益" value={money.format(financial.hourlyIncome)} detail="按已投入工时计算" tone="orange" icon={Timer} />
    </section>
    <nav className="project-detail-tabs" aria-label="项目详情模块">{tabs.map(([key, label, Icon]) => <button className={tab === key ? "active" : ""} onClick={() => setTab(key)} key={key}><Icon size={17} />{label}</button>)}</nav>

    {tab === "overview" && <section className="project-detail-grid">
      <Surface><SurfaceTitle eyebrow="PAYMENT PLAN" title="付款计划与回款进度" /><div className="payment-node-list">{snapshot.payments.filter((item) => item.projectId === project.id).map((payment, index) => <article className={payment.status === "confirmed" ? "done" : ""} key={payment.id}><i>{payment.status === "confirmed" ? <CheckCircle size={19} weight="fill" /> : index + 1}</i><span><b>{paymentLabel[payment.type]}</b><small>{payment.notes}</small></span><strong>{money.format(payment.amount)}</strong><time>{payment.status === "confirmed" ? `已到账 ${shortDate(payment.paidAt)}` : `${shortDate(payment.dueAt)} 应收`}</time></article>)}</div></Surface>
      <Surface><SurfaceTitle eyebrow="PROJECT PULSE" title="项目执行脉搏" /><div className="project-pulse"><div><span>开发进度</span><b>{project.progress}%</b><BarProgress value={project.progress} tone="purple" /></div><div><span>任务完成</span><b>{tasks.length ? Math.round(tasks.filter((item) => item.status === "done").length / tasks.length * 100) : 0}%</b><BarProgress value={tasks.length ? tasks.filter((item) => item.status === "done").length / tasks.length * 100 : 0} tone="green" /></div><div><span>工时消耗</span><b>{project.estimatedHours ? Math.round(financial.actualHours / project.estimatedHours * 100) : 0}%</b><BarProgress value={project.estimatedHours ? financial.actualHours / project.estimatedHours * 100 : 0} tone="orange" /></div></div><div className="project-customer-brief"><UserCircle size={38} weight="duotone" /><span><small>关联客户</small><b>{customer?.name}</b><em>{customer?.phone}</em></span><span><small>客户等级</small><b>{customer?.level} 级客户</b><em>{followLabel[customer?.followUpStatus || "new"]}</em></span></div></Surface>
      <Surface className="project-next-action"><SurfaceTitle eyebrow="NEXT ACTION" title="AI 建议的下一步" /><div><Sparkle size={25} weight="fill" /><span><b>今天完成支付异常场景回归</b><p>当前工时已使用 {project.estimatedHours ? Math.round(financial.actualHours / project.estimatedHours * 100) : 0}%，建议冻结新增需求，并在验收前主动发送阶段款提醒。</p></span></div><button onClick={() => setTab("tasks")}>查看任务安排 <ArrowRight size={15} /></button></Surface>
    </section>}

    {tab === "tasks" && <Surface className="project-module"><SurfaceTitle eyebrow="TASKS" title={`项目任务列表 · ${tasks.filter((item) => item.status === "done").length}/${tasks.length} 已完成`} action={<button className="business-primary" onClick={addTask}><Plus size={16} />新增任务</button>} /><div className="project-task-table"><div className="project-task-head"><span>任务</span><span>状态</span><span>计划日期</span><span>预计 / 实际</span><span>操作</span></div>{tasks.map((task) => <article key={task.id}><span><button className={`task-check task-${task.status}`} onClick={() => updateTask(task.id)} aria-label={`切换${task.title}状态`}>{task.status === "done" && <CheckCircle size={18} weight="fill" />}</button><b>{task.title}</b></span><em className={`task-status task-${task.status}`}>{taskLabel[task.status]}</em><time>{shortDate(task.startDate)} — {shortDate(task.dueDate)}</time><small>{task.estimatedHours}h / {task.actualHours}h</small><button onClick={() => updateTask(task.id)}>推进状态 <CaretRight size={13} /></button></article>)}</div></Surface>}

    {tab === "gantt" && <Surface className="project-module"><SurfaceTitle eyebrow="TIMELINE" title="项目甘特图" action={<span className="auto-duration"><Clock size={15} />工期自动计算：{duration} 天</span>} /><div className="gantt-calendar"><div className="gantt-scale"><span>任务</span>{Array.from({ length: duration }, (_, index) => <time key={index}>{index + 1}日</time>)}</div>{tasks.map((task, index) => { const left = Math.max(0, (new Date(`${task.startDate}T00:00:00`).getTime() - new Date(`${project.startDate}T00:00:00`).getTime()) / totalTimeline * 100); const width = Math.max(8, (new Date(`${task.dueDate}T00:00:00`).getTime() - new Date(`${task.startDate}T00:00:00`).getTime() + 86_400_000) / (totalTimeline + 86_400_000) * 100); return <article key={task.id}><b>{task.title}</b><div><i className={`gantt-tone-${index % 4}`} style={{ left: `${left}%`, width: `${Math.min(100 - left, width)}%` }}><span>{task.status === "done" ? "已完成" : task.status === "in_progress" ? `${Math.max(20, Math.round(task.actualHours / Math.max(task.estimatedHours, 1) * 100))}%` : "待开始"}</span></i></div></article>; })}</div></Surface>}

    {tab === "logs" && <section className="project-detail-grid"><Surface className="project-module"><SurfaceTitle eyebrow="DAILY LOG" title="开发日志" /><form className="log-composer" onSubmit={addLog}><textarea value={logText} onChange={(event) => setLogText(event.target.value)} placeholder="记录今天完成的功能、客户沟通或风险变化…" rows={3} /><button className="business-primary" type="submit"><NotePencil size={16} />发布日志</button></form><div className="dev-log-list">{logs.map((log) => <article key={log.id}><i><NotePencil size={17} /></i><span><b>{log.content}</b><small>{new Date(log.createdAt).toLocaleString("zh-CN")} · {log.hours} 小时 · {log.category === "development" ? "开发" : log.category === "communication" ? "沟通" : "交付"}</small></span></article>)}</div></Surface><Surface className="log-insight"><Lightbulb size={31} weight="duotone" /><h3>本周投入 {logs.reduce((sum, item) => sum + item.hours, 0)} 小时</h3><p>沟通记录和开发日志完整，当前最大风险是验收前新增需求。建议所有变更进入下期报价。</p></Surface></section>}

    {tab === "files" && <Surface className="project-module"><input ref={fileInput} hidden type="file" multiple onChange={storeFiles} /><SurfaceTitle eyebrow="FILES" title={`项目附件 · ${files.length}`} action={<button className="business-primary" onClick={addFile}><UploadSimple size={16} />上传附件</button>} /><div className="attachment-grid">{files.map((file) => { const Icon = file.type === "archive" ? FileArchive : file.type === "design" ? FolderOpen : FileText; return <article key={file.id}><i><Icon size={27} weight="duotone" /></i><span><b>{file.name}</b><small>{file.size} · {shortDate(file.uploadedAt)} 上传</small></span>{file.dataUrl ? <a href={file.dataUrl} target="_blank" rel="noreferrer">查看</a> : <button disabled title="旧附件只保存了文件信息">仅信息</button>}</article>; })}<button className="attachment-drop" onClick={addFile}><UploadSimple size={28} /><b>上传项目文件</b><small>1.5 MB 内文件可在当前设备打开</small></button></div></Surface>}
  </div>;
}

export function EnhancedProjectManagementPage({ snapshot, onCreateProject, onSnapshotChange, globalSearch }: { snapshot: LedgerSnapshot; onCreateProject: () => void; onSnapshotChange: (snapshot: LedgerSnapshot) => void; globalSearch: string }) {
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState("due");
  const financials = useMemo(() => getProjectFinancials(snapshot), [snapshot]);
  const query = (globalSearch || search).trim().toLowerCase();
  const filtered = financials.filter(({ project }) => {
    const customer = snapshot.customers.find((item) => item.id === project.customerId);
    return `${project.name} ${customer?.name || ""}`.toLowerCase().includes(query) && (status === "all" || project.status === status);
  }).sort((a, b) => sort === "amount" ? b.project.totalAmount - a.project.totalAmount : a.project.dueDate.localeCompare(b.project.dueDate));
  if (selectedProject && snapshot.projects.some((item) => item.id === selectedProject)) return <ProjectDetail snapshot={snapshot} projectId={selectedProject} onBack={() => setSelectedProject(null)} onSnapshotChange={onSnapshotChange} />;
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
    <div className="project-list-layout"><main><Surface className="project-list-toolbar"><label><MagnifyingGlass size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={globalSearch ? `顶部搜索：${globalSearch}` : "搜索项目或客户"} disabled={Boolean(globalSearch)} /></label><select aria-label="项目状态" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">全部状态</option><option value="pending">待开始</option><option value="in_progress">进行中</option><option value="delivered">已交付</option><option value="completed">已完成</option><option value="overdue">已逾期</option></select><select aria-label="项目排序" value={sort} onChange={(event) => setSort(event.target.value)}><option value="due">按交付时间排序</option><option value="amount">按合同金额排序</option></select><button className="business-primary" onClick={onCreateProject}><Plus size={16} />新建项目</button></Surface><div className="enhanced-project-list">{filtered.length ? filtered.map(({ project, income, outstanding: due, paymentProgress, profit }) => { const customer = snapshot.customers.find((item) => item.id === project.customerId); const projectTasks = snapshot.tasks.filter((task) => task.projectId === project.id); return <Surface className="enhanced-project-row" key={project.id}><div className={`project-avatar project-${project.accent}`}><Briefcase size={24} weight="duotone" /></div><div className="enhanced-project-main"><span><small>{project.type || "定制开发"} · {customer?.name}</small><h3>{project.name}</h3></span><div className="enhanced-progress-copy"><span>开发进度 <b>{project.progress}%</b></span><BarProgress value={project.progress} tone={project.accent} /></div></div><div className="project-row-stat"><small>合同 / 已收</small><b>{money.format(project.totalAmount)} / {money.format(income)}</b><em>未收 {money.format(due)}</em></div><div className="project-row-stat"><small>任务 / 自动工期</small><b>{projectTasks.filter((item) => item.status === "done").length}/{projectTasks.length} · {daysBetween(project.startDate, project.dueDate)}天</b><em>{Math.max(0, daysUntil(project.dueDate))} 天后交付</em></div><div className="project-row-stat"><small>利润 / 回款</small><b className="positive">{money.format(profit)}</b><em>{paymentProgress.toFixed(0)}%</em></div><button className="project-detail-button" onClick={() => setSelectedProject(project.id)}>项目详情 <ArrowRight size={14} /></button></Surface>; }) : <BusinessEmptyState icon={Briefcase} title="没有匹配的项目" description={snapshot.projects.length ? "请调整搜索或筛选条件。" : "示例项目已经清空，可录入自己的第一个项目。"} action={!snapshot.projects.length ? <button className="business-primary" onClick={onCreateProject}><Plus size={16} />录入我的第一个项目</button> : undefined} />}</div></main><aside><Surface><SurfaceTitle eyebrow="AUTO SCHEDULE" title="工期自动计算" /><div className="schedule-illustration"><CalendarBlank size={42} weight="duotone" /><strong>{averageDuration.toFixed(1)}<small> 天</small></strong><span>平均项目工期</span></div><p className="business-note">工期由项目开始日、任务排期和交付日自动计算；任务变更后可实时评估延期风险。</p></Surface><Surface><SurfaceTitle eyebrow="UPCOMING" title="近期交付" /><div className="upcoming-list">{active.length ? active.slice().sort((a, b) => daysUntil(a.dueDate) - daysUntil(b.dueDate)).map((project) => <button key={project.id} onClick={() => setSelectedProject(project.id)}><i className={`project-${project.accent}`}><Clock size={16} /></i><span><b>{project.name}</b><small>{shortDate(project.dueDate)} 交付</small></span><em>{Math.max(0, daysUntil(project.dueDate))}天</em></button>) : <p className="business-note">暂无近期交付项目</p>}</div></Surface></aside></div>
  </div>;
}

export function EnhancedIncomeRecordsPage({ snapshot, onQuickAdd, onSnapshotChange, globalSearch }: { snapshot: LedgerSnapshot; onQuickAdd: () => void; onSnapshotChange: (snapshot: LedgerSnapshot) => void; globalSearch: string }) {
  const summary = getBusinessSummary(snapshot);
  const [selected, setSelected] = useState(snapshot.projects[0]?.id || "");
  const [reminded, setReminded] = useState<string | null>(null);
  const selectedId = snapshot.projects.some((item) => item.id === selected) ? selected : snapshot.projects[0]?.id || "";
  const selectedProject = snapshot.projects.find((item) => item.id === selectedId);
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
  const totalContract = snapshot.projects.reduce((sum, item) => sum + item.totalAmount, 0);
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
    <section className="income-workspace"><main><Surface><SurfaceTitle eyebrow="PROJECT PAYMENT" title="项目付款节点" action={<div className="income-actions"><select value={selectedId} onChange={(event) => setSelected(event.target.value)}>{snapshot.projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select><button className="business-primary" onClick={onQuickAdd}><Plus size={16} />记录收款</button></div>} /><div className="collection-overview"><div><small>{selectedProject.name}</small><strong>{money.format(selectedFinancial.income)} <span>/ {money.format(selectedProject.totalAmount)}</span></strong><BarProgress value={selectedFinancial.paymentProgress} tone="green" /><p><span>收款进度 {selectedFinancial.paymentProgress.toFixed(0)}%</span><b>未收 {money.format(selectedFinancial.outstanding)}</b></p></div><i><Wallet size={43} weight="duotone" /></i></div><div className="payment-timeline">{projectPayments.map((payment, index) => <article className={payment.status === "confirmed" ? "paid" : ""} key={payment.id}><div><i>{payment.status === "confirmed" ? <CheckCircle size={18} weight="fill" /> : index + 1}</i><span /></div><small>{paymentLabel[payment.type]}</small><strong>{money.format(payment.amount)}</strong><time>{shortDate(payment.dueAt)}</time><em>{payment.status === "confirmed" ? "已到账" : daysUntil(payment.dueAt) <= 1 ? "即将到期" : "待收款"}</em></article>)}</div></Surface><Surface><SurfaceTitle eyebrow="ALL NODES" title={globalSearch ? `搜索结果 · ${matchingPayments.length}` : "全部收款节点"} /><div className="income-node-table"><div><span>项目 / 客户</span><span>类型</span><span>金额</span><span>计划日期</span><span>状态</span><span>收款进度</span></div>{matchingPayments.map((payment) => { const project = snapshot.projects.find((item) => item.id === payment.projectId)!; const customer = snapshot.customers.find((item) => item.id === payment.customerId)!; const financial = summary.projectFinancials.find((item) => item.project.id === project.id)!; return <article key={payment.id}><span><b>{project.name}</b><small>{customer.name}</small></span><em>{paymentLabel[payment.type]}</em><strong>{money.format(payment.amount)}</strong><time>{shortDate(payment.dueAt)}</time><i className={`payment-status-${payment.status}`}>{payment.status === "confirmed" ? "已到账" : payment.status === "refunded" ? "已退款" : "待收款"}</i><span><BarProgress value={financial.paymentProgress} tone="green" /><small>{financial.paymentProgress.toFixed(0)}%</small></span></article>; })}</div></Surface></main><aside><Surface><SurfaceTitle eyebrow="REMINDERS" title="收款提醒" action={<span className="reminder-count">{pending.length}</span>} /><div className="collection-reminders">{pending.slice(0, 5).map((payment) => { const project = snapshot.projects.find((item) => item.id === payment.projectId)!; const remaining = daysUntil(payment.dueAt); return <article className={remaining <= 1 ? "urgent" : ""} key={payment.id}><i><BellRinging size={18} weight="duotone" /></i><span><b>{project.name}</b><small>{paymentLabel[payment.type]} · {money.format(payment.amount)}</small></span><em>{remaining <= 0 ? "今天到期" : `${remaining}天后`}</em><button onClick={() => remindCustomer(payment.id)} disabled={reminded === payment.id}>{reminded === payment.id ? "已记录提醒" : "提醒客户"}</button></article>; })}</div></Surface><Surface className="collection-health"><SurfaceTitle eyebrow="CASH FLOW" title="回款健康度" /><div className="health-score"><strong>{healthScore}</strong><span><b>{healthScore >= 80 ? "健康" : healthScore >= 60 ? "需关注" : "有风险"}</b><small>{pending.length ? `${nearDueCount} 个节点在 7 天内到期` : "暂无待收节点"}</small></span></div><ul><li><CheckCircle size={16} weight="fill" />已确认到账 {snapshot.payments.filter((item) => item.status === "confirmed").length} 个节点</li><li><WarningCircle size={16} weight="fill" />{overdueCount} 个节点已到期</li></ul></Surface></aside></section>
  </div>;
}

export function ProfitAnalysisPage({ snapshot }: { snapshot: LedgerSnapshot }) {
  const summary = getBusinessSummary(snapshot);
  const ranking = summary.projectFinancials.slice().sort((a, b) => b.profit - a.profit);
  const maxProfit = Math.max(...ranking.map((item) => item.profit), 1);
  return <div className="business-page profit-analysis-page"><section className="business-metrics-grid">
    <BusinessMetric label="实际利润" value={money.format(summary.actualProfit)} detail={`${money.format(summary.totalIncome)} 收入 - ${money.format(summary.totalExpenses)} 支出`} tone="green" icon={TrendUp} />
    <BusinessMetric label="本月利润" value={money.format(summary.monthlyProfit)} detail={`${money.format(summary.monthlyIncome)} 收入 - ${money.format(summary.monthlyExpenses)} 支出`} tone="purple" icon={CalendarBlank} />
    <BusinessMetric label="年度利润" value={money.format(summary.yearlyProfit)} detail="按本年度已确认流水计算" tone="blue" icon={ChartLineUp} />
    <BusinessMetric label="平均小时收益" value={`${money.format(summary.averageHourlyIncome)}/h`} detail={`累计有效投入 ${summary.actualHours} 小时`} tone="orange" icon={Timer} />
  </section><section className="profit-layout"><main><Surface><SurfaceTitle eyebrow="PROJECT PROFIT" title="项目收益排行" action={<span className="profit-formula">收入 - 支出 = 实际利润</span>} /><div className="profit-ranking-chart">{ranking.length ? ranking.map((item, index) => <article key={item.project.id}><i>{index + 1}</i><span><b>{item.project.name}</b><small>收入 {money.format(item.income)} · 成本 {money.format(item.expenses)} · {item.actualHours}h</small><BarProgress value={item.profit / maxProfit * 100} tone={index === 0 ? "green" : "purple"} /></span><strong>{money.format(item.profit)}<small>{money.format(item.hourlyIncome)}/h</small></strong></article>) : <BusinessEmptyState icon={ChartLineUp} title="暂无收益排行" description="导入项目、收入和支出后，这里会自动计算真实利润。" />}</div></Surface><Surface><SurfaceTitle eyebrow="PROFIT STRUCTURE" title="月度与年度利润结构" /><div className="profit-compare"><article><span>本月</span><b>{money.format(summary.monthlyIncome)}</b><i style={{ height: `${summary.monthlyIncome ? Math.max(28, summary.monthlyIncome / Math.max(summary.monthlyIncome, summary.yearlyIncome) * 150) : 0}px` }} /><small>收入</small></article><article className="expense"><span>本月</span><b>{money.format(summary.monthlyExpenses)}</b><i style={{ height: `${summary.monthlyExpenses ? Math.max(18, summary.monthlyExpenses / Math.max(summary.monthlyIncome, 1) * 150) : 0}px` }} /><small>支出</small></article><article><span>本年</span><b>{money.format(summary.yearlyIncome)}</b><i style={{ height: summary.yearlyIncome ? "150px" : "0px" }} /><small>收入</small></article><article className="expense"><span>本年</span><b>{money.format(summary.yearlyExpenses)}</b><i style={{ height: `${summary.yearlyExpenses ? Math.max(18, summary.yearlyExpenses / Math.max(summary.yearlyIncome, 1) * 150) : 0}px` }} /><small>支出</small></article></div></Surface></main><aside><Surface className="profit-insight"><Sparkle size={28} weight="fill" /><SurfaceTitle eyebrow="SMART INSIGHT" title="经营洞察" /><h3>{ranking.length ? "高价值项目正在形成" : "等待真实经营数据"}</h3><p>{ranking.length ? `「${ranking[0].project.name}」当前贡献最高利润，小时收益为 ${money.format(ranking[0].hourlyIncome)}。建议把同类项目报价提高 12%–18%。` : "录入自己的项目、收入、支出与工时后，这里会生成针对你的利润洞察。"}</p><div><span>利润率</span><b>{summary.totalIncome ? Math.round(summary.actualProfit / summary.totalIncome * 100) : 0}%</b><BarProgress value={summary.totalIncome ? summary.actualProfit / summary.totalIncome * 100 : 0} tone="green" /></div></Surface><Surface><SurfaceTitle eyebrow="COST ALERT" title="成本结构" /><div className="cost-breakdown">{["outsourcing", "software", "server", "other"].map((category) => { const amount = snapshot.expenses.filter((item) => item.category === category).reduce((sum, item) => sum + item.amount, 0); return <p key={category}><span>{category === "outsourcing" ? "外包成本" : category === "software" ? "软件订阅" : category === "server" ? "服务器" : "其他成本"}</span><b>{money.format(amount)}</b></p>; })}</div></Surface></aside></section></div>;
}

export function EnhancedCustomerManagementPage({ snapshot, onCreateCustomer, onSnapshotChange, globalSearch }: { snapshot: LedgerSnapshot; onCreateCustomer: () => void; onSnapshotChange: (snapshot: LedgerSnapshot) => void; globalSearch: string }) {
  const [selected, setSelected] = useState(snapshot.customers[0]?.id || "");
  const selectedId = snapshot.customers.some((item) => item.id === selected) ? selected : snapshot.customers[0]?.id || "";
  const customer = snapshot.customers.find((item) => item.id === selectedId);
  const selectedBusiness = getCustomerBusiness(snapshot, selectedId);
  const nextStatus = () => {
    if (!customer) return;
    const flow: CustomerFollowUpStatus[] = ["new", "contacted", "proposal", "won"];
    const current = customer.followUpStatus;
    const index = flow.indexOf(current);
    const followUpStatus = flow[Math.min(flow.length - 1, Math.max(0, index + 1))];
    onSnapshotChange({ ...snapshot, customers: snapshot.customers.map((item) => item.id === customer.id ? { ...item, followUpStatus, lastContactAt: new Date().toISOString() } : item) });
  };
  const visibleCustomers = snapshot.customers.filter((item) => `${item.name} ${item.phone} ${(item.tags || []).join(" ")}`.toLowerCase().includes(globalSearch.trim().toLowerCase()));
  const totalSpend = snapshot.customers.reduce((sum, item) => sum + getCustomerBusiness(snapshot, item.id).totalSpend, 0);
  if (!customer) return <div className="business-page enhanced-crm-page"><section className="business-metrics-grid"><BusinessMetric label="客户总数" value="0 位" detail="项目、订单与联系记录已关联" tone="purple" icon={UsersThree} /><BusinessMetric label="累计消费" value={money.format(0)} detail="按已确认收款统计" tone="green" icon={Wallet} /><BusinessMetric label="A级客户" value="0 位" detail="高价值与高复购潜力" tone="orange" icon={Sparkle} /><BusinessMetric label="跟进中" value="0 位" detail="需要继续联系的客户" tone="blue" icon={BellRinging} /></section><BusinessEmptyState icon={UsersThree} title="还没有客户资料" description="客户示例数据已经清空，可以录入自己的第一位客户。" action={<button className="business-primary" onClick={onCreateCustomer}><Plus size={16} />新增客户</button>} /></div>;
  return <div className="business-page enhanced-crm-page"><section className="business-metrics-grid">
    <BusinessMetric label="客户总数" value={`${snapshot.customers.length} 位`} detail="项目、订单与联系记录已关联" tone="purple" icon={UsersThree} />
    <BusinessMetric label="累计消费" value={money.format(totalSpend)} detail="按已确认收款统计" tone="green" icon={Wallet} />
    <BusinessMetric label="A级客户" value={`${snapshot.customers.filter((item) => item.level === "A").length} 位`} detail="高价值与高复购潜力" tone="orange" icon={Sparkle} />
    <BusinessMetric label="跟进中" value={`${snapshot.customers.filter((item) => ["new", "contacted", "proposal"].includes(item.followUpStatus)).length} 位`} detail="需要在 7 天内继续联系" tone="blue" icon={BellRinging} />
  </section><section className="crm-layout"><main><Surface><SurfaceTitle eyebrow="CUSTOMER PIPELINE" title={globalSearch ? `客户搜索结果 · ${visibleCustomers.length}` : "客户经营列表"} action={<button className="business-primary" onClick={onCreateCustomer}><Plus size={16} />新增客户</button>} /><div className="crm-table"><div><span>客户</span><span>跟进状态</span><span>最近联系</span><span>历史订单</span><span>消费金额</span><span>客户等级</span></div>{visibleCustomers.map((item) => { const business = getCustomerBusiness(snapshot, item.id); const status = item.followUpStatus; return <button className={selectedId === item.id ? "active" : ""} onClick={() => setSelected(item.id)} key={item.id}><span><i>{item.name.slice(0, 1)}</i><b>{item.name}<small>{item.phone}</small></b></span><em className={`follow-${status}`}>{followLabel[status]}</em><time>{shortDate(item.lastContactAt)}</time><strong>{business.orderCount} 单</strong><strong>{money.format(business.totalSpend)}</strong><i className={`customer-level level-${item.level}`}>{item.level}</i></button>; })}</div></Surface></main><aside><Surface className="customer-profile"><div className="customer-profile-head"><i>{customer.name.slice(0, 1)}</i><span><small>{customer.source === "xianyu" ? "闲鱼客户" : customer.source === "wechat" ? "微信客户" : customer.source === "referral" ? "转介绍" : "其他来源"}</small><h3>{customer.name}</h3><p>{customer.phone}</p></span><b className={`customer-level level-${customer.level}`}>{customer.level}</b></div><div className="customer-profile-stats"><span><small>历史订单</small><b>{selectedBusiness.orderCount}</b></span><span><small>累计消费</small><b>{money.format(selectedBusiness.totalSpend)}</b></span><span><small>最近联系</small><b>{shortDate(customer.lastContactAt)}</b></span></div><div className="customer-tags">{customer.tags?.map((tag) => <i key={tag}>{tag}</i>)}</div><button className="business-primary wide" onClick={nextStatus}><NotePencil size={16} />记录本次跟进</button></Surface><Surface><SurfaceTitle eyebrow="ORDER HISTORY" title="历史订单" /><div className="customer-order-list">{selectedBusiness.projects.map((project) => { const financial = getProjectFinancials(snapshot).find((item) => item.project.id === project.id)!; return <article key={project.id}><i><Briefcase size={17} /></i><span><b>{project.name}</b><small>{shortDate(project.startDate)} · {project.status === "completed" ? "已完成" : "进行中"}</small></span><strong>{money.format(project.totalAmount)}<small>已收 {money.format(financial.income)}</small></strong></article>; })}</div></Surface></aside></section></div>;
}

interface RequirementResult {
  type: string;
  features: string[];
  days: number;
  price: [number, number];
  risks: string[];
}

function analyzeRequirement(content: string): RequirementResult {
  const isMini = /小程序|微信/.test(content);
  const isData = /数据|图表|报表|后台/.test(content);
  const hasPayment = /支付|订单|退款/.test(content);
  const hasAdmin = /后台|管理/.test(content);
  const features = ["用户与权限", hasAdmin ? "管理后台" : "内容管理", isData ? "数据看板与报表" : "核心业务流程", hasPayment ? "订单、支付与退款" : "消息与状态提醒", "部署上线与交付文档"];
  const base = isMini ? 14 : isData ? 18 : 12;
  const days = base + (hasPayment ? 5 : 0) + (hasAdmin ? 3 : 0);
  const min = days * 900;
  return { type: isMini ? "微信小程序定制开发" : isData ? "Web 数据管理平台" : "Web 定制应用", features, days, price: [min, Math.round(min * 1.35 / 100) * 100], risks: [hasPayment ? "支付与退款需要预留联调和审核时间" : "需求边界需在原型确认后冻结", "第三方接口稳定性可能影响交付", "新增需求建议进入二期报价，避免工期失控"] };
}

export function AIWorkspacePage({ snapshot }: { snapshot: LedgerSnapshot }) {
  const [tool, setTool] = useState<"requirements" | "quote" | "review">("requirements");
  const [content, setContent] = useState("");
  const [requirement, setRequirement] = useState<RequirementResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [quoteReady, setQuoteReady] = useState(false);
  const [complexity, setComplexity] = useState<"standard" | "advanced" | "complex">("advanced");
  const [reviewProject, setReviewProject] = useState(snapshot.projects[0]?.id || "");
  const [reviewReady, setReviewReady] = useState(false);
  const run = (callback: () => void) => {
    setBusy(true);
    window.setTimeout(() => { callback(); setBusy(false); }, 760);
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
  const quoteBase = requirement?.price[0] || 24000;
  const quoteTotal = Math.round(quoteBase * (complexity === "standard" ? 0.85 : complexity === "complex" ? 1.35 : 1.1) / 100) * 100;
  const exportQuote = () => {
    const content = [`${requirement?.type || "Web 定制应用"}项目报价单`, `建议总报价：${money.format(quoteTotal)}`, `复杂度：${complexity === "standard" ? "标准" : complexity === "advanced" ? "进阶" : "复杂"}`, "付款计划：30% 定金 / 40% 阶段款 / 30% 尾款", "交付：源代码、部署包、操作说明与 30 天缺陷维护"].join("\n");
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
