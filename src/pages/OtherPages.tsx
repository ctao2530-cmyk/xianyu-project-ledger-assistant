import {
  ArrowClockwise,
  Bell,
  CalendarBlank,
  CaretDown,
  CaretRight,
  ChartBar,
  CheckCircle,
  CheckSquare,
  CloudArrowUp,
  Database,
  DesktopTower,
  DownloadSimple,
  DotsThreeVertical,
  Envelope,
  Eye,
  GearSix,
  Lock,
  MagnifyingGlass,
  Palette,
  PencilSimple,
  Plus,
  RocketLaunch,
  ShieldCheck,
  SquaresFour,
  Star,
  Student,
  Table,
  Target,
  Trash,
  TrendUp,
  Trophy,
  User,
  UserPlus,
  Warning,
  X,
  type Icon as PhosphorIcon,
} from "@phosphor-icons/react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { type FormEvent, type ReactNode, useMemo, useState } from "react";
import type { LedgerSnapshot } from "../types";
import "./other-pages.css";

export type OtherPageName =
  | "项目管理"
  | "收入记录"
  | "支出记录"
  | "客户管理"
  | "数据统计"
  | "目标计划"
  | "设置中心";

type ActionKind = "project" | "expense" | "customer";

interface OtherPagesProps {
  page: OtherPageName;
  snapshot: LedgerSnapshot;
  onQuickAdd: () => void;
}

interface Column {
  key: string;
  label: string;
  width?: string;
}

interface MetricData {
  title: string;
  value: string;
  detail: ReactNode;
  tone: "purple" | "green" | "blue" | "orange" | "red";
  image?: string;
  icon?: PhosphorIcon;
  chart?: "line" | "bar";
}

const lineData = [
  { name: "一", value: 12 },
  { name: "二", value: 24 },
  { name: "三", value: 18 },
  { name: "四", value: 36 },
  { name: "五", value: 25 },
  { name: "六", value: 20 },
  { name: "日", value: 42 },
];

const barData = [14, 25, 18, 31, 22, 37, 29, 42, 34].map((value, index) => ({ index, value }));

const projectRows = [
  ["校园二手交易平台开发", "郑同学", "¥24,000.00", "开发中", "2025-04-20", "2025-05-22", 70, "2天", "进行中"],
  ["餐饮点餐小程序开发", "李老板", "¥16,800.00", "测试中", "2025-05-05", "2025-05-20", 40, "0天", "待验收"],
  ["数据可视化后台系统", "王同学", "¥12,000.00", "开发中", "2025-05-19", "2025-06-15", 90, "26天", "进行中"],
  ["个人博客系统开发", "陈同学", "¥9,600.00", "设计中", "2025-05-18", "2025-06-01", 30, "12天", "进行中"],
  ["电商后台管理系统", "张总", "¥32,000.00", "已完成", "2025-03-10", "2025-04-25", 100, "-", "已完成"],
  ["健身房预约小程序", "刘女士", "¥8,800.00", "已完成", "2025-03-28", "2025-04-10", 100, "-", "已完成"],
  ["在线教育平台开发", "赵老师", "¥28,000.00", "逾期", "2025-04-01", "2025-05-10", 85, "-10天", "逾期"],
  ["活动报名小程序", "孙同学", "¥6,400.00", "待开始", "2025-05-25", "2025-06-10", 0, "21天", "待开始"],
];

const incomeRows = [
  ["校园二手交易平台", "郑同学", "定金", "¥2,400.00", "2025-05-20 14:30", "已确认", "项目启动定金"],
  ["餐饮点餐小程序开发", "李老板", "阶段款", "¥5,000.00", "2025-05-20 10:20", "已确认", "UI设计阶段款"],
  ["数据可视化后台系统", "王同学", "尾款", "¥4,800.00", "2025-05-19 16:45", "已确认", "项目尾款"],
  ["个人博客系统开发", "陈同学", "全款", "¥9,600.00", "2025-05-18 11:12", "已确认", "一次性付清"],
  ["电商后台管理系统", "张总", "阶段款", "¥6,400.00", "2025-05-15 09:30", "待确认", "功能开发阶段款"],
  ["健身房预约小程序", "刘女士", "定金", "¥2,800.00", "2025-05-12 15:20", "已确认", "项目定金"],
  ["在线教育平台开发", "赵老师", "阶段款", "¥5,600.00", "2025-05-10 11:00", "待确认", "第一阶段开发款"],
  ["活动报名小程序", "孙同学", "尾款", "¥2,600.00", "2025-05-08 14:50", "已确认", "验收后尾款"],
  ["企业官网定制开发", "周先生", "全款", "¥3,800.00", "2025-05-05 10:30", "已确认", "官网开发全款"],
  ["小程序性能优化", "吴同学", "定金", "¥1,600.00", "2025-05-03 09:15", "已确认", "优化项目定金"],
];

const expenseRows = [
  ["Canva Pro 订阅费", "软件订阅", "¥120.00", "2025-05-27 10:30", "支付宝", "校园二手交易平台", "已支付", "月度订阅"],
  ["UI 设计外包费", "外包设计", "¥2,400.00", "2025-05-26 16:20", "微信支付", "数据可视化后台", "已支付", "首页+图表页设计"],
  ["阿里云服务器", "服务器", "¥368.00", "2025-05-25 09:15", "支付宝", "电商后台管理系统", "已支付", "ECS 1核2G"],
  ["插件购买 - Mockplus", "软件订阅", "¥239.00", "2025-05-24 14:08", "支付宝", "个人博客系统开发", "已支付", "年度订阅"],
  ["退款 - 设计需求取消", "退款", "-¥800.00", "2025-05-23 11:45", "微信支付", "餐饮点餐小程序", "已退款", "客户取消订单"],
  ["域名续费（.com）", "服务器", "¥79.00", "2025-05-22 08:50", "支付宝", "校园二手交易平台", "已支付", "域名续费1年"],
  ["外包开发费用", "外包设计", "¥3,600.00", "2025-05-20 18:32", "银行转账", "电商后台管理系统", "已支付", "后端开发"],
  ["Office 365 订阅", "软件订阅", "¥99.00", "2025-05-18 10:12", "支付宝", "团队协作", "已支付", "团队使用"],
  ["客服外包费", "外包设计", "¥600.00", "2025-05-16 15:40", "微信支付", "餐饮点餐小程序", "已支付", "客服支持"],
  ["办公用品采购", "办公支出", "¥135.00", "2025-05-15 09:30", "支付宝", "团队协作", "已支付", "文具采购"],
];

function SectionCard({ className = "", id, children }: { className?: string; id?: string; children: ReactNode }) {
  return <section id={id} className={`page-card ${className}`}>{children}</section>;
}

function PanelHeader({ title, action }: { title: string; action?: ReactNode }) {
  return <div className="panel-header"><h2>{title}</h2>{action}</div>;
}

function TinyMetricChart({ kind, tone }: { kind: "line" | "bar"; tone: string }) {
  return <div className="page-mini-chart" aria-hidden="true"><ResponsiveContainer width="100%" height="100%">
    {kind === "line" ? <AreaChart data={lineData}><Area isAnimationActive={false} type="monotone" dataKey="value" stroke={tone} fill={tone} fillOpacity={0.08} strokeWidth={2.2} dot={{ r: 2.2, fill: tone, strokeWidth: 0 }} /></AreaChart>
      : <BarChart data={barData}><Bar isAnimationActive={false} dataKey="value" fill={tone} opacity={0.72} radius={[4, 4, 0, 0]} /></BarChart>}
  </ResponsiveContainer></div>;
}

function PageMetric({ metric }: { metric: MetricData }) {
  const tone = metric.tone === "green" ? "#17c978" : metric.tone === "blue" ? "#2f75f5" : metric.tone === "orange" ? "#ff7a13" : metric.tone === "red" ? "#f15358" : "#6544f4";
  const Icon = metric.icon;
  return <SectionCard className={`page-metric page-metric-${metric.tone}`}>
    <h3>{metric.title}</h3>
    <strong style={{ color: tone }}>{metric.value}</strong>
    <div className="page-metric-detail">{metric.detail}</div>
    {metric.image && <img src={metric.image} alt="" />}
    {Icon && <span className="page-metric-icon" style={{ color: tone }}><Icon size={38} weight="duotone" /></span>}
    {metric.chart && <TinyMetricChart kind={metric.chart} tone={tone} />}
  </SectionCard>;
}

function MetricsRow({ metrics }: { metrics: MetricData[] }) {
  return <section className="page-metrics-row">{metrics.map((metric) => <PageMetric key={metric.title} metric={metric} />)}</section>;
}

function SearchField({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="page-search"><MagnifyingGlass size={17} /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function SelectButton({ children }: { children: ReactNode }) {
  return <button className="page-select">{children}<CaretDown size={14} /></button>;
}

function PrimaryButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <button className="page-primary" onClick={onClick}><Plus size={18} weight="bold" />{children}</button>;
}

function FilterBar({ children }: { children: ReactNode }) {
  return <SectionCard className="filter-bar">{children}</SectionCard>;
}

function StatusPill({ children, tone = "blue" }: { children: ReactNode; tone?: string }) {
  return <span className={`status-pill status-${tone}`}>{children}</span>;
}

function Progress({ value, tone = "blue" }: { value: number; tone?: string }) {
  return <div className="table-progress"><span>{value}%</span><div><i className={`progress-${tone}`} style={{ width: `${value}%` }} /></div></div>;
}

function DataTable({ columns, rows, empty = "暂无匹配记录" }: { columns: Column[]; rows: Array<Record<string, ReactNode>>; empty?: string }) {
  return <div className="generic-table" role="table">
    <div className="generic-table-head" role="row" style={{ gridTemplateColumns: columns.map((column) => column.width || "1fr").join(" ") }}>
      {columns.map((column) => <span key={column.key}>{column.label}</span>)}
    </div>
    {rows.length ? rows.map((row, index) => <div className="generic-table-row" role="row" key={String(row.id || index)} style={{ gridTemplateColumns: columns.map((column) => column.width || "1fr").join(" ") }}>
      {columns.map((column) => <span key={column.key} data-label={column.label}>{row[column.key]}</span>)}
    </div>) : <div className="table-empty">{empty}</div>}
  </div>;
}

function TableFooter({ total }: { total: number }) {
  return <div className="generic-table-footer"><span>共 {total} 条记录</span><div><button disabled>‹</button><button className="active">1</button><button>2</button><button>3</button><button>›</button></div><SelectButton>10 条/页</SelectButton></div>;
}

function Donut({ data, center, sub }: { data: Array<{ name: string; value: number; color: string }>; center: string; sub: string }) {
  return <div className="page-donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie isAnimationActive={false} data={data} dataKey="value" innerRadius={43} outerRadius={60} startAngle={90} endAngle={-270} stroke="none">{data.map((item) => <Cell key={item.name} fill={item.color} />)}</Pie></PieChart></ResponsiveContainer><div><strong>{center}</strong><span>{sub}</span></div></div>;
}

function DonutLegend({ data }: { data: Array<{ name: string; value: number; color: string; detail?: string }> }) {
  const total = data.reduce((sum, item) => sum + item.value, 0);
  return <div className="page-donut-legend">{data.map((item) => <p key={item.name}><i style={{ background: item.color }} /><span>{item.name}</span><strong>{item.value}</strong><small>{item.detail || `${((item.value / total) * 100).toFixed(1)}%`}</small></p>)}</div>;
}

function CrudModal({ kind, onClose, onCreated }: { kind: ActionKind; onClose: () => void; onCreated: (kind: ActionKind, value: { name: string; amount: string }) => void }) {
  const labels = kind === "project" ? { title: "新建项目", name: "项目名称", amount: "项目预算" } : kind === "expense" ? { title: "记录支出", name: "支出项目", amount: "支出金额" } : { title: "新增客户", name: "客户名称", amount: "联系电话" };
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !amount.trim()) { setError("请完整填写必要信息"); return; }
    onCreated(kind, { name: name.trim(), amount: amount.trim() });
  };
  return <div className="page-modal-layer"><button className="page-modal-backdrop" aria-label="关闭弹窗" onClick={onClose} /><form className="page-modal" onSubmit={submit} role="dialog" aria-modal="true" aria-label={labels.title}>
    <div className="page-modal-head"><div><span>快速录入</span><h2>{labels.title}</h2></div><button type="button" aria-label="关闭" onClick={onClose}><X size={20} /></button></div>
    <label><span>{labels.name}</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder={`请输入${labels.name}`} autoFocus /></label>
    <label><span>{labels.amount}</span><input value={amount} onChange={(event) => setAmount(event.target.value)} placeholder={`请输入${labels.amount}`} /></label>
    <label><span>备注</span><textarea rows={4} placeholder="补充说明（可选）" /></label>
    {error && <p className="page-modal-error"><Warning size={15} />{error}</p>}
    <button className="page-modal-submit" type="submit"><CheckCircle size={19} weight="fill" />保存记录</button>
  </form></div>;
}

function TableActions() {
  return <span className="table-actions"><button aria-label="查看"><Eye size={15} /></button><button aria-label="编辑"><PencilSimple size={15} /></button><button aria-label="更多"><DotsThreeVertical size={16} /></button></span>;
}

function ProjectManagementPage({ onAction, extraRows }: { onAction: (kind: ActionKind) => void; extraRows: string[][] }) {
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("全部");
  const rows = [...extraRows, ...projectRows].filter((row) => `${row[0]} ${row[1]} ${row[8]}`.includes(search) && (tab === "全部" || row[8] === tab));
  const metrics: MetricData[] = [
    { title: "全部项目", value: "28", detail: <>总预算 <b>¥246,800.00</b></>, tone: "blue", image: "/assets/pages/project-folder-blue.png" },
    { title: "进行中", value: "12", detail: <>预算 <b>¥126,800.00</b></>, tone: "green", image: "/assets/pages/project-folder-green.png" },
    { title: "本周交付", value: "4", detail: <>金额 <b>¥38,600.00</b></>, tone: "purple", image: "/assets/pages/project-calendar.png" },
    { title: "已完成", value: "9", detail: <>收入 <b>¥87,200.00</b></>, tone: "green", image: "/assets/goal-trophy.png" },
    { title: "逾期项目", value: "3", detail: <>金额 <b>¥12,800.00</b></>, tone: "orange", image: "/assets/pages/project-clock.png" },
  ];
  const columns: Column[] = [
    { key: "name", label: "项目名称", width: "1.7fr" }, { key: "customer", label: "客户", width: ".72fr" }, { key: "amount", label: "预算/金额", width: ".85fr" }, { key: "stage", label: "阶段", width: ".72fr" }, { key: "start", label: "开始日期", width: ".86fr" }, { key: "due", label: "截止日期", width: ".86fr" }, { key: "progress", label: "进度", width: ".92fr" }, { key: "days", label: "剩余天数", width: ".62fr" }, { key: "status", label: "状态", width: ".72fr" }, { key: "actions", label: "", width: ".25fr" },
  ];
  const tableRows = rows.map((row, index) => ({
    id: `${row[0]}-${index}`,
    name: <span className="table-name"><i className={`row-icon color-${index % 4}`}><ChartBar size={15} weight="duotone" /></i><b>{row[0]}</b></span>, customer: row[1], amount: row[2], stage: <StatusPill tone={row[3] === "逾期" ? "red" : row[3] === "已完成" ? "green" : "blue"}>{row[3]}</StatusPill>, start: row[4], due: row[5], progress: <Progress value={Number(row[6])} tone={row[8] === "逾期" ? "orange" : row[8] === "已完成" ? "green" : "blue"} />, days: <b className={String(row[7]).includes("-") || row[7] === "0天" ? "danger-text" : ""}>{row[7]}</b>, status: <StatusPill tone={row[8] === "逾期" ? "red" : row[8] === "已完成" ? "green" : row[8] === "待验收" ? "orange" : "blue"}>{row[8]}</StatusPill>, actions: <TableActions />,
  }));
  const donut = [{ name: "进行中", value: 12, color: "#4d8ff8" }, { name: "待开始", value: 6, color: "#f4b51b" }, { name: "已完成", value: 9, color: "#28c979" }, { name: "已逾期", value: 3, color: "#ff654e" }];
  return <div className="other-page project-page">
    <div className="page-content-grid with-right-rail"><div><div className="project-summary-shell"><FilterBar><SearchField value={search} onChange={setSearch} placeholder="搜索项目或客户" /><SelectButton>项目阶段</SelectButton><SelectButton>全部客户</SelectButton><SelectButton>排序：截止日期(近→远)</SelectButton><PrimaryButton onClick={() => onAction("project")}>新建项目</PrimaryButton></FilterBar><MetricsRow metrics={metrics} /></div><SectionCard className="page-table-card">
      <div className="table-tabs">{[["全部", 28], ["进行中", 12], ["待开始", 6], ["已完成", 9], ["逾期", 3]].map(([label, count]) => <button className={tab === label ? "active" : ""} onClick={() => setTab(String(label))} key={label}>{label}（{count}）</button>)}</div>
      <DataTable columns={columns} rows={tableRows} /><TableFooter total={28 + extraRows.length} />
    </SectionCard></div><aside className="page-right-rail"><SectionCard><PanelHeader title="项目看板" action={<button className="panel-link">查看全部 <CaretRight size={13} /></button>} /><div className="donut-panel"><Donut data={donut} center="28" sub="总项目" /><DonutLegend data={donut} /></div></SectionCard><SectionCard><PanelHeader title="本周交付" action={<button className="panel-link">查看全部 <CaretRight size={13} /></button>} /><ul className="side-list">{["餐饮点餐小程序", "校园二手交易平台", "个人博客系统开发", "数据可视化后台系统"].map((item, index) => <li key={item}><i className={`dot-${index}`} /><span>{item}</span><time>05-{20 + index * 2}</time><StatusPill tone={index === 0 ? "green" : "blue"}>剩余{index * 2}天</StatusPill></li>)}</ul></SectionCard><SectionCard className="calendar-card"><PanelHeader title="交付日历" action={<span>2025年5月 <CaretRight size={13} /></span>} /><div className="mini-calendar">{["日", "一", "二", "三", "四", "五", "六", ...Array.from({ length: 28 }, (_, i) => String(i + 1))].map((value, index) => <span className={[20, 22, 25].includes(Number(value)) ? "marked" : ""} key={`${value}-${index}`}>{value}</span>)}</div></SectionCard><SectionCard><PanelHeader title="里程碑提醒" /><ul className="milestone-list"><li>测试完成节点 <time>今天</time></li><li>UI设计评审 <time>05-23</time></li><li>第一版功能交付 <time>05-25</time></li></ul></SectionCard></aside></div>
  </div>;
}

function IncomeRecordsPage({ onQuickAdd }: { onQuickAdd: () => void }) {
  const [search, setSearch] = useState("");
  const rows = incomeRows.filter((row) => `${row[0]} ${row[1]} ${row[2]} ${row[5]}`.includes(search));
  const metrics: MetricData[] = [
    { title: "累计到账（元）", value: "¥128,600.00", detail: <>较上月 <b>↑32.6%</b></>, tone: "purple", image: "/assets/metric-wallet-purple.png", chart: "line" },
    { title: "本月到账（元）", value: "¥12,860.00", detail: <>较上月 <b>↑18.7%</b></>, tone: "green", image: "/assets/metric-wallet-green.png", chart: "bar" },
    { title: "今日到账（元）", value: "¥2,680.00", detail: <>较昨日 <b>↑86.0%</b></>, tone: "blue", image: "/assets/metric-card-blue.png", chart: "bar" },
    { title: "待确认收款（笔）", value: "6", detail: <>金额<br /><b>¥8,900.00</b></>, tone: "purple", image: "/assets/pages/income-pending.png" },
    { title: "平均客单价（元）", value: "¥3,218.33", detail: <>较上月 <b>↑12.4%</b></>, tone: "orange", image: "/assets/pages/income-bag.png" },
  ];
  const columns: Column[] = [{ key: "name", label: "项目名称", width: "1.55fr" }, { key: "customer", label: "客户", width: ".65fr" }, { key: "type", label: "收款类型", width: ".72fr" }, { key: "amount", label: "金额（元）", width: ".85fr" }, { key: "date", label: "收款时间", width: "1.05fr" }, { key: "status", label: "收款状态", width: ".72fr" }, { key: "note", label: "备注", width: "1.1fr" }, { key: "actions", label: "操作", width: ".72fr" }];
  const tableRows = rows.map((row, index) => ({ id: `${row[0]}-${index}`, name: <span className="table-name"><i className={`row-icon color-${index % 4}`}><ChartBar size={15} /></i><b>{row[0]}</b></span>, customer: row[1], type: <StatusPill tone="neutral">{row[2]}</StatusPill>, amount: <b className="money-green">{row[3]}</b>, date: row[4], status: <StatusPill tone={row[5] === "待确认" ? "orange" : "green"}>{row[5]}</StatusPill>, note: row[6], actions: <TableActions /> }));
  const typeDonut = [{ name: "定金", value: 3268, color: "#4a92f5", detail: "25.6%" }, { name: "阶段款", value: 5000, color: "#39cb83", detail: "38.9%" }, { name: "尾款", value: 2865, color: "#f1544f", detail: "22.3%" }, { name: "全款", value: 1707, color: "#ffb51b", detail: "13.2%" }];
  return <div className="other-page"><MetricsRow metrics={metrics} /><div className="page-content-grid with-right-rail"><div><FilterBar><span className="range-field"><CalendarBlank size={16} />2025-04-01 ~ 2025-05-20</span><SelectButton>全部类型</SelectButton><SelectButton>全部来源</SelectButton><SelectButton>全部状态</SelectButton><button className="page-secondary"><DownloadSimple size={17} />导出</button><PrimaryButton onClick={onQuickAdd}>记录收款</PrimaryButton></FilterBar><SectionCard className="page-table-card"><PanelHeader title="收入记录明细" /><DataTable columns={columns} rows={tableRows} /><TableFooter total={86} /></SectionCard></div><aside className="page-right-rail"><SectionCard><PanelHeader title="本周到账趋势" action={<SelectButton>本周</SelectButton>} /><div className="side-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={lineData}><CartesianGrid vertical={false} stroke="#edf0f7" strokeDasharray="3 3" /><XAxis dataKey="name" tickLine={false} axisLine={false} /><Tooltip /><Area type="monotone" dataKey="value" stroke="#6544f4" strokeWidth={2.6} fill="#6f53f6" fillOpacity={0.12} dot={{ r: 3, fill: "#6544f4" }} /></AreaChart></ResponsiveContainer></div></SectionCard><SectionCard><PanelHeader title="收款类型占比（本月）" /><div className="donut-panel"><Donut data={typeDonut} center="¥12,860" sub="总金额" /><DonutLegend data={typeDonut} /></div></SectionCard><SectionCard><PanelHeader title="最近待确认收款" /><ul className="side-list"><li><span>电商后台管理系统</span><b>¥6,400.00</b><time>05-15</time></li><li><span>在线教育平台开发</span><b>¥5,600.00</b><time>05-10</time></li><li><span>设计素材交易平台</span><b>¥2,900.00</b><time>05-08</time></li></ul></SectionCard><SectionCard className="reminder-visual"><PanelHeader title="到账提醒" /><p>开启收款提醒，不错过每一笔到账</p><img src="/assets/pages/income-bell.png" alt="金色到账提醒铃铛" /><button>去开启提醒</button></SectionCard></aside></div></div>;
}

function ExpenseRecordsPage({ onAction, extraRows }: { onAction: (kind: ActionKind) => void; extraRows: string[][] }) {
  const [search, setSearch] = useState("");
  const rows = [...extraRows, ...expenseRows].filter((row) => `${row[0]} ${row[1]} ${row[5]}`.includes(search));
  const metrics: MetricData[] = [
    { title: "累计支出（元）", value: "¥48,520.00", detail: <>较上月 <b>↑28.4%</b></>, tone: "purple", image: "/assets/metric-wallet-purple.png", chart: "line" },
    { title: "本月支出（元）", value: "¥8,760.00", detail: <>较上月 <b>↓12.6%</b></>, tone: "green", image: "/assets/metric-wallet-green.png", chart: "bar" },
    { title: "今日支出（元）", value: "¥360.00", detail: <>较昨日 <b>↑100%</b></>, tone: "blue", image: "/assets/metric-card-blue.png", chart: "bar" },
    { title: "本月利润（元）", value: "¥3,280.00", detail: <>较上月 <b>↓5.2%</b></>, tone: "purple", image: "/assets/goal-trophy.png", chart: "line" },
    { title: "成本占收入比", value: "38.6%", detail: <>较上月 <b>↓4.1%</b></>, tone: "orange", icon: ChartBar },
  ];
  const columns: Column[] = [{ key: "name", label: "支出项目", width: "1.5fr" }, { key: "category", label: "类别", width: ".75fr" }, { key: "amount", label: "金额（元）", width: ".82fr" }, { key: "date", label: "支出时间", width: "1.08fr" }, { key: "method", label: "支付方式", width: ".85fr" }, { key: "project", label: "关联项目", width: "1.24fr" }, { key: "status", label: "状态", width: ".72fr" }, { key: "note", label: "备注", width: ".9fr" }, { key: "actions", label: "", width: ".25fr" }];
  const tableRows = rows.map((row, index) => ({ id: `${row[0]}-${index}`, name: <span className="table-name"><i className={`row-icon color-${index % 4}`}><Database size={15} /></i><b>{row[0]}</b></span>, category: <StatusPill tone={row[1] === "退款" ? "red" : "blue"}>{row[1]}</StatusPill>, amount: <b className={String(row[2]).startsWith("-") ? "danger-text" : "money-green"}>{row[2]}</b>, date: row[3], method: row[4], project: row[5], status: <StatusPill tone={row[6] === "已退款" ? "blue" : "green"}>{row[6]}</StatusPill>, note: row[7], actions: <TableActions /> }));
  const expenseDonut = [{ name: "软件订阅", value: 35.4, color: "#4d8ff8" }, { name: "外包设计", value: 31.5, color: "#28c979" }, { name: "服务器", value: 15.7, color: "#ffb51b" }, { name: "办公支出", value: 9.8, color: "#9b67ef" }, { name: "其他", value: 7.6, color: "#fb785c" }];
  return <div className="other-page"><MetricsRow metrics={metrics} /><div className="page-content-grid with-right-rail"><div><FilterBar><SearchField value={search} onChange={setSearch} placeholder="搜索支出项目或关联项目" /><SelectButton>全部类别</SelectButton><span className="range-field"><CalendarBlank size={16} />2025-05-01 ~ 2025-05-31</span><SelectButton>全部方式</SelectButton><SelectButton>全部状态</SelectButton><PrimaryButton onClick={() => onAction("expense")}>记录支出</PrimaryButton></FilterBar><SectionCard className="page-table-card"><PanelHeader title="支出记录明细" /><DataTable columns={columns} rows={tableRows} /><TableFooter total={56 + extraRows.length} /></SectionCard></div><aside className="page-right-rail"><SectionCard><PanelHeader title="支出分类占比" action={<button className="panel-link">查看全部 <CaretRight size={13} /></button>} /><div className="donut-panel"><Donut data={expenseDonut} center="¥8,760" sub="本月支出" /><DonutLegend data={expenseDonut} /></div></SectionCard><SectionCard><PanelHeader title="本月利润对比" /><div className="profit-grid"><p><span>本月收入</span><b className="money-green">¥12,040.00</b></p><p><span>本月支出</span><b className="danger-text">¥8,760.00</b></p><p><span>本月利润</span><b>¥3,280.00</b></p><p><span>利润率</span><b>27.2%</b></p></div></SectionCard><SectionCard><PanelHeader title="高成本项目 TOP5" /><ol className="ranking-list">{["电商后台管理系统", "数据可视化后台", "校园二手交易平台", "个人博客系统开发", "餐饮点餐小程序"].map((item, index) => <li key={item}><span>{item}</span><b>¥{[4860, 1980, 1199, 859, 602][index]}.00</b></li>)}</ol></SectionCard><SectionCard><PanelHeader title="预算预警" /><div className="budget-alert"><Warning size={23} weight="fill" /><span>电商后台管理系统<br /><b>预算已使用 92%</b></span><i /></div><div className="budget-alert"><Warning size={23} weight="fill" /><span>数据可视化后台<br /><b>预算已使用 85%</b></span><i /></div></SectionCard></aside></div></div>;
}

const customerRows = [
  ["郑同学", "咸鱼", "138****6273", "校园二手交易平台", "¥24,000.00", "已成交", "2025-05-22", "老客户,高校"],
  ["李老板", "微信", "139****8812", "餐饮点餐小程序", "¥16,800.00", "跟进中", "2025-05-20", "高意向,餐饮"],
  ["王同学", "老客户介绍", "137****7745", "数据可视化后台", "¥12,000.00", "跟进中", "2025-05-19", "老客户,数据"],
  ["陈同学", "咸鱼", "136****5599", "个人博客系统开发", "¥9,600.00", "已成交", "2025-05-18", "已成交,个人"],
  ["张总", "微信", "150****2299", "电商后台管理系统", "¥32,000.00", "已成交", "2025-05-10", "高价值,电商"],
  ["刘女士", "老客户介绍", "158****1230", "健身房预约小程序", "¥8,800.00", "跟进中", "2025-05-09", "高意向,健身"],
  ["赵老师", "线下活动", "156****6677", "在线教育平台开发", "¥28,000.00", "洽谈中", "2025-05-04", "教育,高价值"],
  ["孙同学", "咸鱼", "135****9988", "活动报名小程序", "¥6,400.00", "跟进中", "2025-05-02", "小程序,活动"],
  ["周同学", "微信", "132****4455", "课程预约小程序", "¥7,200.00", "跟进中", "2025-04-28", "教育,小程序"],
  ["吴先生", "朋友推荐", "188****3344", "企业官网建设", "¥5,600.00", "初步沟通", "2025-04-26", "官网,企业"],
];

function CustomerManagementPage({ onAction, extraRows }: { onAction: (kind: ActionKind) => void; extraRows: string[][] }) {
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"table" | "cards">("table");
  const rows = [...extraRows, ...customerRows].filter((row) => `${row[0]} ${row[1]} ${row[3]} ${row[7]}`.includes(search));
  const metrics: MetricData[] = [
    { title: "客户总数", value: "186", detail: <>较上月 <b>↑18.2%</b></>, tone: "purple", image: "/assets/pages/customer-users.png" },
    { title: "本月新增客户", value: "23", detail: <>较上月 <b>↑43.8%</b></>, tone: "green", image: "/assets/pages/customer-add.png" },
    { title: "成交客户", value: "42", detail: <>较上月 <b>↑21.4%</b></>, tone: "purple", image: "/assets/goal-trophy.png" },
    { title: "跟进中客户", value: "68", detail: <>较上月 <b>↑12.6%</b></>, tone: "blue", image: "/assets/pages/customer-chat.png" },
    { title: "复购率", value: "32.6%", detail: <>较上月 <b>↑6.7%</b></>, tone: "purple", image: "/assets/pages/income-bag.png" },
  ];
  const columns: Column[] = [{ key: "name", label: "客户名称", width: "1.1fr" }, { key: "source", label: "来源", width: ".65fr" }, { key: "phone", label: "联系方式", width: ".9fr" }, { key: "project", label: "最近项目", width: "1.3fr" }, { key: "amount", label: "累计成交额", width: ".9fr" }, { key: "status", label: "跟进状态", width: ".75fr" }, { key: "recent", label: "最近联系", width: ".82fr" }, { key: "tags", label: "标签", width: "1.08fr" }, { key: "actions", label: "操作", width: ".38fr" }];
  const tableRows = rows.map((row, index) => ({ id: `${row[0]}-${index}`, name: <span className="table-name"><i className={`avatar-letter avatar-${index % 5}`}>{String(row[0]).slice(0, 1)}</i><b>{row[0]}</b></span>, source: <StatusPill tone={row[1] === "微信" ? "green" : row[1] === "咸鱼" ? "orange" : "neutral"}>{row[1]}</StatusPill>, phone: row[2], project: row[3], amount: <b>{row[4]}</b>, status: <StatusPill tone={row[5] === "已成交" ? "green" : row[5] === "洽谈中" ? "orange" : "blue"}>{row[5]}</StatusPill>, recent: row[6], tags: <span className="tag-cloud">{String(row[7]).split(",").map((tag) => <i key={tag}>{tag}</i>)}</span>, actions: <TableActions /> }));
  const sources = [{ name: "咸鱼", value: 68, color: "#4d8ff8" }, { name: "微信", value: 52, color: "#28c979" }, { name: "老客户介绍", value: 34, color: "#9c65ef" }, { name: "线下活动", value: 18, color: "#ffb20d" }, { name: "其他", value: 14, color: "#fa6350" }];
  return <div className="other-page"><MetricsRow metrics={metrics} /><div className="page-content-grid with-right-rail"><div><FilterBar><SearchField value={search} onChange={setSearch} placeholder="搜索客户名称、联系人、手机..." /><SelectButton>全部来源</SelectButton><SelectButton>全部状态</SelectButton><SelectButton>更多筛选</SelectButton><button className="page-secondary" onClick={() => setSearch("")}>重置</button><PrimaryButton onClick={() => onAction("customer")}>新增客户</PrimaryButton></FilterBar><div className="view-switch"><button className={view === "table" ? "active" : ""} onClick={() => setView("table")}><Table size={16} />表格视图</button><button className={view === "cards" ? "active" : ""} onClick={() => setView("cards")}><SquaresFour size={16} />卡片视图</button></div>{view === "table" ? <SectionCard className="page-table-card customer-table"><DataTable columns={columns} rows={tableRows} /><TableFooter total={186 + extraRows.length} /></SectionCard> : <div className="customer-card-grid">{rows.slice(0, 9).map((row, index) => <SectionCard className="customer-card" key={String(row[0])}><div><i className={`avatar-letter avatar-${index % 5}`}>{String(row[0]).slice(0, 1)}</i><span><b>{row[0]}</b><small>{row[2]}</small></span><TableActions /></div><h3>{row[3]}</h3><p><StatusPill tone="green">{row[1]}</StatusPill><StatusPill tone="blue">{row[5]}</StatusPill></p><strong>{row[4]}</strong><small>最近联系 {row[6]}</small></SectionCard>)}</div>}</div><aside className="page-right-rail"><SectionCard><PanelHeader title="客户来源分析" action={<button className="panel-link">查看全部 <CaretRight size={13} /></button>} /><div className="donut-panel"><Donut data={sources} center="186" sub="客户总数" /><DonutLegend data={sources} /></div></SectionCard><SectionCard><PanelHeader title="最近跟进提醒" action={<button className="panel-link">查看全部 <CaretRight size={13} /></button>} /><ul className="follow-list">{["李老板", "王同学", "张总", "刘女士"].map((name, index) => <li key={name}><i className={`avatar-letter avatar-${index}`}>{name[0]}</i><span><b>{name}</b><small>{["餐饮点餐小程序", "数据可视化后台", "电商后台管理系统", "健身房预约小程序"][index]}</small></span><time>{index < 2 ? "今天" : "05-27"}</time></li>)}</ul></SectionCard><SectionCard><PanelHeader title="高价值客户榜" /><ol className="ranking-list customer-rank">{["张总", "郑同学", "赵老师", "李老板", "王同学"].map((name, index) => <li key={name}><span><i>{index + 1}</i>{name}</span><b>¥{[32000, 24000, 28000, 16800, 12000][index].toLocaleString()}.00</b></li>)}</ol></SectionCard><SectionCard><PanelHeader title="客户活跃度" action={<SelectButton>近30天</SelectButton>} /><div className="activity-score"><b>78.6%</b><span>↑12.4%</span><small>活跃客户占比</small></div><TinyMetricChart kind="line" tone="#6047f2" /></SectionCard></aside></div></div>;
}

const revenueTrend = [
  { month: "2024/12", income: 5000, expense: 2600 }, { month: "2025/01", income: 12000, expense: 7200 },
  { month: "02", income: 7600, expense: 5400 }, { month: "03", income: 18800, expense: 9600 },
  { month: "04", income: 10400, expense: 7800 }, { month: "05", income: 28600, expense: 12320 },
];

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number; color: string; name: string }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return <div className="chart-tooltip"><b>{label}</b>{payload.map((item) => <span key={item.name} style={{ color: item.color }}>{item.name}：¥{item.value.toLocaleString()}</span>)}</div>;
}

function DataStatisticsPage({ snapshot }: { snapshot: LedgerSnapshot }) {
  const totalIncome = snapshot.payments.filter((payment) => payment.status === "confirmed").reduce((sum, payment) => sum + payment.amount, 0);
  const displayIncome = Math.max(totalIncome, 128860).toLocaleString("zh-CN", { minimumFractionDigits: 2 });
  const metrics: MetricData[] = [
    { title: "累计收入（元）", value: `¥${displayIncome}`, detail: <>较上月 <b>↑32.6%</b></>, tone: "purple", image: "/assets/metric-wallet-purple.png", chart: "line" },
    { title: "净利润（元）", value: "¥56,280.00", detail: <>利润率 <b>43.7%</b><br />较上月 <b>↑26.4%</b></>, tone: "green", image: "/assets/pages/analytics-calendar.png", chart: "bar" },
    { title: "成交率", value: "68.5%", detail: <>较上月 <b>↑8.2%</b></>, tone: "blue", image: "/assets/pages/analytics-funnel.png", chart: "bar" },
    { title: "平均工期（天）", value: "18.6", detail: <>较上月 <b className="danger-text">↓1.8天</b></>, tone: "purple", image: "/assets/pages/income-pending.png", chart: "bar" },
    { title: "复购率", value: "42.3%", detail: <>较上月 <b>↑6.7%</b></>, tone: "orange", image: "/assets/pages/analytics-bag.png", chart: "bar" },
  ];
  const status = [{ name: "进行中", value: 12, color: "#4d8ff8" }, { name: "待开始", value: 6, color: "#9d6af0" }, { name: "已完成", value: 9, color: "#2eca7d" }, { name: "已逾期", value: 3, color: "#fc7d58" }];
  const sources = [{ name: "老客户介绍", value: 45900, color: "#4d8ff8" }, { name: "线上平台", value: 36980, color: "#29ca7b" }, { name: "朋友推荐", value: 25930, color: "#9f67ef" }, { name: "线下拓展", value: 13290, color: "#ffb414" }, { name: "其他渠道", value: 6760, color: "#f85c53" }];
  return <div className="other-page analytics-page"><MetricsRow metrics={metrics} /><section className="analytics-grid top"><SectionCard><PanelHeader title="收入趋势（元）" action={<SelectButton>近6个月</SelectButton>} /><div className="large-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={revenueTrend}><defs><linearGradient id="incomeArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6447f3" stopOpacity={0.24} /><stop offset="100%" stopColor="#6447f3" stopOpacity={0.02} /></linearGradient></defs><CartesianGrid vertical={false} stroke="#e9edf5" strokeDasharray="3 3" /><XAxis dataKey="month" tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} /><Tooltip content={<ChartTooltip />} /><Area name="收入" type="monotone" dataKey="income" stroke="#6447f3" strokeWidth={3} fill="url(#incomeArea)" dot={{ fill: "#6447f3", r: 4 }} /></AreaChart></ResponsiveContainer></div></SectionCard><SectionCard><PanelHeader title="收入 vs 支出对比（元）" action={<SelectButton>近6个月</SelectButton>} /><div className="large-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={revenueTrend} barGap={8}><CartesianGrid vertical={false} stroke="#e9edf5" strokeDasharray="3 3" /><XAxis dataKey="month" tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} /><Tooltip content={<ChartTooltip />} /><Bar name="收入" dataKey="income" fill="#4d88f5" radius={[5, 5, 0, 0]} /><Bar name="支出" dataKey="expense" fill="#ff744d" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div></SectionCard><SectionCard><PanelHeader title="项目状态分布" /><div className="donut-panel tall"><Donut data={status} center="28" sub="总项目" /><DonutLegend data={status} /></div><button className="panel-bottom-link">查看项目管理 <CaretRight size={14} /></button></SectionCard></section><section className="analytics-grid bottom"><SectionCard><PanelHeader title="客户来源分析" /><div className="donut-panel tall"><Donut data={sources} center="¥128,860" sub="总收入" /><DonutLegend data={sources} /></div></SectionCard><SectionCard><PanelHeader title="项目收入排行榜（TOP 5）" /><ol className="project-ranking">{["校园二手交易平台", "餐饮点餐小程序开发", "数据可视化后台系统", "个人博客系统开发", "电商后台管理系统"].map((name, index) => <li key={name}><i>{index + 1}</i><span>{name}</span><b>¥{[24800, 16800, 12000, 9600, 8800][index].toLocaleString()}</b><small>{[19.2, 13, 9.3, 7.4, 6.8][index]}%</small></li>)}</ol></SectionCard><SectionCard><PanelHeader title="环比数据对比" action={<SelectButton>近3个月</SelectButton>} /><div className="comparison-list"><p><span>收入（元）</span><b>28,600.00</b><small>上月 22,300.00</small><em>↑ 28.3%</em></p><p><span>支出（元）</span><b className="danger-text">12,320.00</b><small>上月 9,860.00</small><em>↑ 25.0%</em></p><p><span>净利润（元）</span><b className="money-green">16,280.00</b><small>上月 12,440.00</small><em>↑ 30.9%</em></p></div></SectionCard></section><SectionCard className="efficiency-card"><div className="efficiency-title"><span>运营效率指数</span><small>综合项目交付效率、客户满意度与财务健康度评估</small><strong>86<em>优秀</em></strong></div>{[["准时交付率", "92%"], ["客户满意度", "4.7 / 5"], ["收入增长率", "28.3%"], ["成本控制率", "78%"], ["应收回款率", "85%"]].map(([label, value], index) => <div className="efficiency-item" key={label}><i className={`eff-icon eff-${index}`}><TrendUp size={23} /></i><span>{label}<b>{value}</b><small>较上月 ↑{index + 3}%</small></span></div>)}<img src="/assets/pages/analytics-report.png" alt="运营数据报告插画" /></SectionCard></div>;
}

function GoalPlanPage() {
  const goalData = [{ day: "05/01", value: 500 }, { day: "05/06", value: 3800 }, { day: "05/11", value: 7200 }, { day: "05/16", value: 8800 }, { day: "05/21", value: 10400 }, { day: "05/26", value: 9200 }, { day: "05/31", value: 12000 }];
  const metrics: MetricData[] = [
    { title: "本月收入目标", value: "¥12,000.00", detail: <>目标 <b>¥15,000</b><Progress value={80} /></>, tone: "purple", image: "/assets/metric-wallet-purple.png" },
    { title: "已完成比例", value: "80%", detail: <>已完成 <b>¥12,000</b><Progress value={80} tone="green" /></>, tone: "green", image: "/assets/pages/goal-ring.png" },
    { title: "本周交付目标", value: "5 个项目", detail: <>已完成 <b>3 个</b><Progress value={60} /></>, tone: "blue", image: "/assets/pages/project-calendar.png" },
    { title: "学习成长计划", value: "进行中 3 项", detail: <>已完成 <b>1 项</b><Progress value={33} tone="purple" /></>, tone: "purple", image: "/assets/pages/goal-book.png" },
    { title: "重点项目数", value: "4 个", detail: <>进行中项目</>, tone: "orange", image: "/assets/pages/goal-folder.png" },
  ];
  const taskGroups = [{ title: "待开始（2）", tone: "blue", items: [["校园二手交易平台", "UI设计稿", "05-21 截止"], ["数据可视化后台", "接口联调", "05-22 截止"]] }, { title: "进行中（3）", tone: "purple", items: [["餐饮点餐小程序", "功能开发中", "进度 40%"], ["个人博客系统开发", "页面开发中", "进度 30%"], ["电商后台管理系统", "测试与优化", "进度 60%"]] }, { title: "已完成（3）", tone: "green", items: [["活动报名小程序", "已完成并交付", "05-18 完成"], ["在线教育平台开发", "已完成并交付", "05-15 完成"], ["数据可视化后台", "已完成并交付", "05-14 完成"]] }];
  return <div className="other-page goal-page"><MetricsRow metrics={metrics} /><section className="goal-top-grid"><SectionCard><PanelHeader title="收入目标进度（本月）" /><div className="goal-chart-copy"><span>● 实际收入　⌁ 目标收入</span><b>¥12,000 <small>/ ¥15,000</small></b></div><div className="goal-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={goalData}><CartesianGrid vertical={false} stroke="#e9edf5" strokeDasharray="3 3" /><XAxis dataKey="day" tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} /><Tooltip /><Area type="monotone" dataKey="value" stroke="#6646f3" fill="#6b4bf3" fillOpacity={0.12} strokeWidth={3} dot={{ fill: "#6544f4", r: 4 }} /></AreaChart></ResponsiveContainer></div><div className="milestone-track"><b>里程碑节点</b>{[3000, 6000, 9000, 12000, 15000].map((value, index) => <p key={value} className={index < 4 ? "done" : ""}><i /><span>¥{value.toLocaleString()}<small>5月{5 + index * 7}日前</small></span><CheckCircle size={15} weight={index < 3 ? "fill" : "regular"} /></p>)}</div></SectionCard><SectionCard className="task-board-card"><PanelHeader title="本周任务看板" action={<button className="panel-link">查看全部 <CaretRight size={13} /></button>} /><div className="task-board">{taskGroups.map((group) => <div key={group.title}><h3>{group.title}</h3>{group.items.map((item, index) => <article key={item[0]}><b>{item[0]}</b><span>{item[1]}</span><small>{item[2]}</small>{group.title.includes("进行中") && <Progress value={[40, 30, 60][index]} />}</article>)}{group.title.includes("待开始") && <button><Plus size={14} />新建任务</button>}</div>)}</div></SectionCard><SectionCard className="achievement-card"><PanelHeader title="成就奖杯" /><img src="/assets/goal-trophy.png" alt="本月成就奖杯" /><h3>本月已达成 3 项成就</h3><ul><li>收入突破 ¥10,000</li><li>连续 7 天按时打卡</li><li>完成 3 个项目交付</li></ul><button>查看全部成就 <CaretRight size={14} /></button></SectionCard></section><section className="goal-mid-grid"><SectionCard><PanelHeader title="项目路线图（未来计划）" /><div className="roadmap"><div className="roadmap-months"><span>5月（进行中）</span><span>6月（规划中）</span><span>7月（规划中）</span></div>{["校园二手交易平台", "餐饮点餐小程序", "个人博客系统开发", "电商后台管理系统"].map((name, index) => <p key={name}><b>{name}</b><span><i className={`road-${index}`} /><i className={`road-${index}`} /><i className={`road-${index}`} /></span></p>)}</div></SectionCard><SectionCard><PanelHeader title="即将到期" /><ul className="due-list">{[["校园二手交易平台", "UI设计稿", "2 天后截止"], ["餐饮点餐小程序", "功能开发", "5 天后截止"], ["数据可视化后台", "接口联调", "6 天后截止"], ["个人博客系统开发", "页面开发", "12 天后截止"]].map((item, index) => <li key={item[0]}><i className={`row-icon color-${index}`}><CalendarBlank size={15} /></i><span><b>{item[0]}</b><small>{item[1]}</small></span><em>{item[2]}</em></li>)}</ul></SectionCard><aside className="goal-side-stack"><SectionCard><PanelHeader title="本周重点" /><ul className="focus-list">{["校园二手交易平台", "餐饮点餐小程序", "个人博客系统开发", "电商后台管理系统"].map((item, index) => <li key={item}><i className={`row-icon color-${index}`}><Target size={15} /></i><span>{item}<small>工期：剩余 {2 + index * 4} 天</small></span><StatusPill tone={index === 0 ? "purple" : index === 1 ? "orange" : "blue"}>{["高优先级", "中优先级", "中优先级", "低优先级"][index]}</StatusPill></li>)}</ul></SectionCard><SectionCard><PanelHeader title="提醒清单" /><ul className="check-list">{["更新项目进度", "跟进客户需求", "学习新技能", "复盘本周工作"].map((item, index) => <li key={item}><CheckSquare size={17} weight={index < 2 ? "fill" : "regular"} /><span>{item}</span><time>{index < 2 ? "今天" : index === 2 ? "明天" : "周日"}</time></li>)}</ul></SectionCard></aside></section><SectionCard className="growth-card"><PanelHeader title="学习成长计划（提升接单效率）" /><div className="growth-progress"><div className="round-progress">33%</div><span><b>本月学习进度</b><small>已完成 1/3 项</small></span></div>{[["Master UI设计提升课", 60, "05-30"], ["微信小程序实战开发", 20, "06-15"], ["高效沟通与需求管理", 0, "06-25"]].map(([name, progress, date]) => <article key={String(name)}><b>{name}</b><Progress value={Number(progress)} /><small>预计 {date} 完成</small></article>)}<button><Plus size={16} />添加学习计划</button></SectionCard></div>;
}

interface SettingRowProps { icon: PhosphorIcon; title: string; description: string; control: ReactNode; tone?: string }
function SettingRow({ icon: Icon, title, description, control, tone = "purple" }: SettingRowProps) {
  return <div className="setting-row"><i className={`setting-icon setting-${tone}`}><Icon size={18} weight="duotone" /></i><span><b>{title}</b><small>{description}</small></span>{control}</div>;
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: () => void; label: string }) {
  return <button type="button" aria-label={label} aria-pressed={checked} className={`toggle ${checked ? "on" : ""}`} onClick={onChange}><i /></button>;
}

function SettingsCenterPage({ onToast }: { onToast: (message: string) => void }) {
  const [section, setSection] = useState("记账设置");
  const [toggles, setToggles] = useState({ days: true, message: true, payment: true, goal: true, backup: true });
  const [theme, setTheme] = useState("#6544f4");
  const flip = (key: keyof typeof toggles) => setToggles((current) => ({ ...current, [key]: !current[key] }));
  const menu = [["个人资料", User], ["记账设置", GearSix], ["项目默认值", SquaresFour], ["提醒通知", Bell], ["数据与同步", CloudArrowUp], ["界面主题", Palette]] as Array<[string, PhosphorIcon]>;
  return <div className="other-page settings-page"><div className="settings-layout"><SectionCard className="settings-nav">{menu.map(([label, Icon]) => <button className={section === label ? "active" : ""} onClick={() => { setSection(label); document.getElementById(`settings-${label}`)?.scrollIntoView({ behavior: "smooth", block: "start" }); }} key={label}><Icon size={18} />{label}</button>)}</SectionCard><main className="settings-main"><SectionCard id="settings-记账设置" className="settings-group"><PanelHeader title="记账与偏好设置" /><SettingRow icon={CalendarBlank} title="闲鱼开始运营日期" description="用于计算运营天数与阶段数据" control={<span className="setting-control">2025-03-13 <CalendarBlank size={15} /></span>} /><SettingRow icon={ArrowClockwise} title="默认工期" description="新建项目时的默认工期" control={<SelectButton>30 天</SelectButton>} tone="blue" /><SettingRow icon={Database} title="默认收款类型" description="新建项目收款方式的默认选项" control={<SelectButton>全款收取</SelectButton>} tone="green" /><SettingRow icon={Target} title="月度目标金额" description="设置每月收入目标，助力达成计划" control={<span className="setting-control">¥ 8,000.00</span>} tone="orange" /><SettingRow icon={ChartBar} title="自动计算运营天数" description="根据运营开始日期，自动计算运营天数" control={<Toggle checked={toggles.days} onChange={() => flip("days")} label="自动计算运营天数" />} /><SettingRow icon={ChartBar} title="显示数据小数位" description="金额与比例的小数位数" control={<SelectButton>2 位小数</SelectButton>} tone="blue" /></SectionCard><SectionCard id="settings-提醒通知" className="settings-group"><PanelHeader title="提醒与通知设置" /><SettingRow icon={Bell} title="消息提醒" description="开启后将接收站内消息提醒" control={<Toggle checked={toggles.message} onChange={() => flip("message")} label="消息提醒" />} tone="blue" /><SettingRow icon={Bell} title="项目到期提醒" description="项目即将到期或逾期时提醒" control={<SelectButton>提前 3 天</SelectButton>} tone="orange" /><SettingRow icon={Bell} title="收款提醒" description="有收款记录或到账时提醒" control={<Toggle checked={toggles.payment} onChange={() => flip("payment")} label="收款提醒" />} tone="green" /><SettingRow icon={Bell} title="月度目标进度提醒" description="每月进度达成 50%、80%、100% 时提醒" control={<Toggle checked={toggles.goal} onChange={() => flip("goal")} label="目标进度提醒" />} /></SectionCard><SectionCard id="settings-数据与同步" className="settings-group"><PanelHeader title="数据与备份设置" /><SettingRow icon={CloudArrowUp} title="自动备份" description="每日自动备份数据，保障数据安全" control={<Toggle checked={toggles.backup} onChange={() => flip("backup")} label="自动备份" />} tone="blue" /><SettingRow icon={ArrowClockwise} title="备份时间" description="选择每日自动备份的时间点" control={<SelectButton>23:30</SelectButton>} tone="orange" /><SettingRow icon={DownloadSimple} title="导出数据" description="将所有数据导出为 Excel 文件" control={<button className="outline-action" onClick={() => onToast("数据导出任务已创建")}>导出 Excel</button>} tone="green" /><SettingRow icon={Trash} title="清理缓存" description="清理本地缓存，释放空间" control={<button className="outline-action" onClick={() => onToast("缓存已清理")}>清理缓存</button>} tone="red" /></SectionCard><SectionCard id="settings-界面主题" className="theme-settings"><PanelHeader title="界面主题与外观" /><div className="mode-choice"><span><i />深浅主题<small>选择你喜欢的界面模式</small></span><button className="active">浅色模式</button><button>深色模式</button></div><div className="theme-colors"><span><b>主题色彩</b><small>自定义主题主色</small></span>{["#6544f4", "#4c8cf5", "#25c879", "#ffac18", "#f35b68", "#12b9cd"].map((color) => <button aria-label={`选择主题色 ${color}`} className={theme === color ? "active" : ""} style={{ background: color }} onClick={() => { setTheme(color); onToast("主题色已更新"); }} key={color} />)}<button className="rainbow" aria-label="自定义主题色" /></div></SectionCard></main><aside className="settings-right"><SectionCard className="security-card"><PanelHeader title="账户安全" /><img src="/assets/pages/settings-shield.png" alt="账户安全盾牌" /><h3><i />安全等级：高</h3><p>您的账户安全状态良好</p><Progress value={78} tone="green" /><SettingRow icon={Lock} title="登录密码" description="上次修改：2025-02-18" control={<button className="text-action">修改</button>} tone="green" /><SettingRow icon={DesktopTower} title="手机绑定" description="138****5678" control={<button className="text-action">修改</button>} tone="green" /><SettingRow icon={Envelope} title="邮箱绑定" description="zhangtx***@163.com" control={<button className="text-action">修改</button>} tone="green" /><SettingRow icon={DesktopTower} title="登录设备管理" description="当前在线设备：2 台" control={<button className="text-action">管理</button>} tone="green" /></SectionCard><SectionCard className="sync-card"><PanelHeader title="数据同步状态" /><img src="/assets/pages/settings-cloud.png" alt="云端同步插画" /><h3><CheckCircle size={16} weight="fill" />同步正常</h3><p>所有数据已同步至云端</p><ul><li><ArrowClockwise size={16} />最后同步时间 <time>2025-05-20 14:30:22</time></li><li><CloudArrowUp size={16} />同步来源 <time>Web 端</time></li><li><Database size={16} />云端数据量 <time>28 条记录</time></li><li><DesktopTower size={16} />本地缓存 <time>已启用</time></li></ul><button className="sync-now" onClick={() => onToast("数据同步完成")}><ArrowClockwise size={17} />立即同步</button></SectionCard></aside></div></div>;
}

export function OtherPages({ page, snapshot, onQuickAdd }: OtherPagesProps) {
  const [modal, setModal] = useState<ActionKind | null>(null);
  const [toast, setToast] = useState("");
  const [extraProjects, setExtraProjects] = useState<string[][]>([]);
  const [extraExpenses, setExtraExpenses] = useState<string[][]>([]);
  const [extraCustomers, setExtraCustomers] = useState<string[][]>([]);
  const created = (kind: ActionKind, value: { name: string; amount: string }) => {
    if (kind === "project") setExtraProjects((items) => [[value.name, "新客户", `¥${Number(value.amount || 0).toLocaleString()}.00`, "待开始", "2025-05-28", "2025-06-28", "0", "30天", "待开始"], ...items]);
    if (kind === "expense") setExtraExpenses((items) => [[value.name, "其他", `¥${Number(value.amount || 0).toLocaleString()}.00`, "2025-05-28 14:30", "支付宝", "未关联项目", "已支付", "新记录"], ...items]);
    if (kind === "customer") setExtraCustomers((items) => [[value.name, "手动新增", value.amount, "暂无项目", "¥0.00", "初步沟通", "2025-05-28", "新客户"], ...items]);
    setModal(null);
    setToast(`${value.name} 已保存`);
    window.setTimeout(() => setToast(""), 2200);
  };
  const content = useMemo(() => {
    if (page === "项目管理") return <ProjectManagementPage onAction={setModal} extraRows={extraProjects} />;
    if (page === "收入记录") return <IncomeRecordsPage onQuickAdd={onQuickAdd} />;
    if (page === "支出记录") return <ExpenseRecordsPage onAction={setModal} extraRows={extraExpenses} />;
    if (page === "客户管理") return <CustomerManagementPage onAction={setModal} extraRows={extraCustomers} />;
    if (page === "数据统计") return <DataStatisticsPage snapshot={snapshot} />;
    if (page === "目标计划") return <GoalPlanPage />;
    return <SettingsCenterPage onToast={(message) => { setToast(message); window.setTimeout(() => setToast(""), 2200); }} />;
  }, [extraCustomers, extraExpenses, extraProjects, onQuickAdd, page, snapshot]);
  return <>{content}{modal && <CrudModal kind={modal} onClose={() => setModal(null)} onCreated={created} />}{toast && <div className="page-toast"><CheckCircle size={18} weight="fill" />{toast}</div>}</>;
}
