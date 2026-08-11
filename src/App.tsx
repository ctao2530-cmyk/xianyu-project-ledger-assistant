import {
  ArrowRight,
  Bell,
  Brain,
  Briefcase,
  CalendarBlank,
  CaretDown,
  CaretRight,
  ChartBar,
  ChartLineUp,
  ChatCircleDots,
  CheckCircle,
  CheckSquare,
  ClipboardText,
  Coins,
  CurrencyCircleDollar,
  ForkKnife,
  GearSix,
  HandWaving,
  HandCoins,
  House,
  HourglassMedium,
  Lightbulb,
  List,
  MagnifyingGlass,
  Money,
  Plus,
  Receipt,
  RocketLaunch,
  ShoppingBag,
  Sparkle,
  Target,
  Timer,
  TrendUp,
  UserCircle,
  UsersThree,
  Wallet,
  WarningCircle,
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
import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { mockLedgerService } from "./data/mockService";
import { isClientProject } from "./data/projectKinds";
import {
  connectPlatformEvents,
  localPlatformService,
  type OperationsSummary,
  type ProductIntelligenceView,
} from "./data/localPlatformService";
import { getBusinessSummary, getProjectFinancials } from "./data/businessMetrics";
import {
  hasTerminalSettlementIssue,
  latestSettlementIssue,
  settlementIssueLabels,
} from "./data/settlementIssues";
import { OtherPages, type OtherPageName, type SettingsSectionName } from "./pages/OtherPages";
import type { ProjectDetailTab, ProjectPageRoute, ProjectRouteMode } from "./pages/BusinessAssistantPages";
import {
  PaymentConfirmationModal,
  type PaymentConfirmationTarget,
} from "./pages/PaymentConfirmationModal";
import {
  ProjectChangeOrderModal,
  type ProjectChangeOrderTarget,
} from "./pages/ProjectChangeOrderModal";
import {
  SettlementIssueModal,
  type SettlementIssueTarget,
} from "./pages/SettlementIssueModal";
import { runPageTransition } from "./utils/pageTransition";
import type {
  Customer,
  LedgerSnapshot,
  Payment,
  PaymentConfirmationValue,
  PaymentType,
  Project,
  ProjectChangeOrderValue,
  QuickAccountingFormValue,
  SettlementIssueValue,
} from "./types";

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
});

const compactCurrency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
});

const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const reminderTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const paymentLabels: Record<PaymentType, string> = {
  deposit: "定金",
  milestone: "阶段款",
  final: "尾款",
  full: "全款",
};

type HeaderReminderKind = "customer" | "collection" | "market" | "launch" | "traffic" | "experiment" | "strategy";

interface HeaderReminder {
  id: string;
  kind: HeaderReminderKind;
  label: string;
  title: string;
  description: string;
  meta: string;
  actionLabel: string;
  targetPage: "客户消息" | "商品经营";
  targetHash: string;
}

function reminderRouteHash(...segments: Array<string | number>) {
  return `#${encodeURIComponent(segments.map(String).join("/"))}`;
}

const headerReminderIcons: Record<HeaderReminderKind, PhosphorIcon> = {
  customer: ChatCircleDots,
  collection: ShoppingBag,
  market: MagnifyingGlass,
  launch: RocketLaunch,
  traffic: TrendUp,
  experiment: ClipboardText,
  strategy: Lightbulb,
};

const navItems: Array<{ label: string; icon: PhosphorIcon; displayLabel?: string }> = [
  { label: "首页概览", icon: House },
  { label: "客户消息", icon: ChatCircleDots },
  { label: "商品经营", icon: ShoppingBag },
  { label: "项目管理", icon: Briefcase },
  { label: "收入记录", icon: CurrencyCircleDollar },
  { label: "支出记录", icon: Receipt },
  { label: "客户管理", icon: UsersThree },
  { label: "数据统计", icon: ChartBar },
  { label: "目标计划", icon: Target },
  { label: "AI经营助手", displayLabel: "小策 · 今日判断", icon: Brain },
  { label: "设置中心", icon: GearSix },
];

const pageMeta: Record<string, { title: string; subtitle: string; placeholder: string }> = {
  首页概览: { title: "早安，开发者！", subtitle: "今天又是认真接单的一天，加油！", placeholder: "搜索项目、客户或订单..." },
  客户消息: { title: "客户消息", subtitle: "统一处理闲鱼与微信咨询，从回复、需求到报价和项目转化", placeholder: "在会话中查找客户与消息..." },
  商品经营: { title: "商品经营", subtitle: "每天一次读取商品信号，判断该观察、优化还是进行人工流量测试", placeholder: "搜索商品名称或商品 ID..." },
  项目管理: { title: "项目管理", subtitle: "统一管理个人与接单项目、任务节奏和交付进度", placeholder: "搜索项目名称、客户、编号..." },
  收入记录: { title: "收入记录", subtitle: "管理到账记录、定金、尾款与项目收款，清晰每一笔进账", placeholder: "搜索项目、客户或订单..." },
  支出记录: { title: "支出记录", subtitle: "全面追踪工具成本、外包成本、退款与日常支出", placeholder: "搜索项目、客户或订单..." },
  客户管理: { title: "客户管理", subtitle: "管理客户资料、来源、成交记录与跟进状态", placeholder: "搜索客户名称、联系人、标签..." },
  数据统计: { title: "数据统计", subtitle: "跨商品、跨周期判断哪些增长真正带来咨询与成交", placeholder: "当前页面无需搜索" },
  目标计划: { title: "目标计划", subtitle: "设定收入目标、交付计划与个人成长安排，让每一步都朝着目标前进", placeholder: "搜索项目、客户或订单..." },
  AI经营助手: { title: "小策 · AI 技术与商业合伙人", subtitle: "让每个经营判断都有事实、反证和清晰的下一步", placeholder: "搜索项目、客户、知识与规则..." },
  设置中心: { title: "设置中心", subtitle: "管理账号信息、界面风格、运营日期、提醒与数据同步", placeholder: "搜索项目、客户或订单..." },
};

const settingsSections: SettingsSectionName[] = ["个人资料", "账号设置", "记账设置", "项目默认值", "提醒通知", "渠道连接", "商品采集", "AI与回复", "报价参数", "数据迁移", "数据与同步", "界面主题"];
const projectDetailTabs: ProjectDetailTab[] = ["overview", "tasks", "gantt", "immersive", "communication", "quote", "logs", "files"];

function sameProjectRoute(left: ProjectPageRoute | null, right: ProjectPageRoute | null) {
  return left?.projectId === right?.projectId && left?.tab === right?.tab;
}

function projectRouteHash(route: ProjectPageRoute | null) {
  const value = route ? `项目管理/${route.projectId}/${route.tab}` : "项目管理";
  return `#${encodeURIComponent(value)}`;
}

export interface CustomerRequirementRoute {
  customerId: string;
  caseId: string | null;
}

function sameCustomerRoute(left: CustomerRequirementRoute | null, right: CustomerRequirementRoute | null) {
  return left?.customerId === right?.customerId && left?.caseId === right?.caseId;
}

function customerRouteHash(route: CustomerRequirementRoute | null) {
  const value = route
    ? `客户管理/${route.customerId}/requirements${route.caseId ? `/${route.caseId}` : ""}`
    : "客户管理";
  return `#${encodeURIComponent(value)}`;
}

function readAppRoute() {
  let requested = "";
  try {
    requested = decodeURIComponent(window.location.hash.replace(/^#/, ""));
  } catch {
    requested = "";
  }
  const [page, rawSection, rawProjectTab, rawCaseId] = requested.split("/");
  const resolvedPage = navItems.some((item) => item.label === page) ? page : "首页概览";
  const projectRoute = resolvedPage === "项目管理" && rawSection
    ? {
        projectId: rawSection,
        tab: projectDetailTabs.includes(rawProjectTab as ProjectDetailTab) ? rawProjectTab as ProjectDetailTab : "immersive" as const,
      }
    : null;
  const customerRoute = resolvedPage === "客户管理" && rawSection && rawProjectTab === "requirements"
    ? { customerId: rawSection, caseId: rawCaseId || null }
    : null;
  return {
    page: resolvedPage,
    settingsSection: settingsSections.includes(rawSection as SettingsSectionName) ? rawSection as SettingsSectionName : "个人资料" as SettingsSectionName,
    projectRoute,
    customerRoute,
  };
}

const miniLineData = [
  { value: 18 },
  { value: 32 },
  { value: 28 },
  { value: 52 },
  { value: 34 },
  { value: 61 },
  { value: 46 },
  { value: 76 },
  { value: 63 },
  { value: 88 },
];

const miniBars = [
  { value: 16 },
  { value: 22 },
  { value: 31 },
  { value: 50 },
  { value: 29 },
  { value: 69 },
  { value: 42 },
  { value: 80 },
  { value: 62 },
  { value: 88 },
];

function isSameLocalDay(value: string, target = new Date()) {
  const date = new Date(value);
  return (
    date.getFullYear() === target.getFullYear() &&
    date.getMonth() === target.getMonth() &&
    date.getDate() === target.getDate()
  );
}

function diffInDays(from: string, to = new Date()) {
  const start = new Date(`${from}T00:00:00`);
  const end = new Date(to);
  end.setHours(0, 0, 0, 0);
  return Math.max(0, Math.ceil((end.getTime() - start.getTime()) / 86_400_000));
}

function calendarDaysUntil(dueDate: string) {
  const due = new Date(`${dueDate}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((due.getTime() - today.getTime()) / 86_400_000);
}

function remainingDays(dueDate: string) {
  return Math.max(0, calendarDaysUntil(dueDate));
}

function parsePlatformDateTime(value: string | null) {
  if (!value) return null;
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(value);
  const date = new Date(hasTimezone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatReminderTime(value: string | null) {
  const date = parsePlatformDateTime(value);
  return date ? reminderTimeFormatter.format(date) : "当前";
}

function buildHeaderReminders(
  operations: OperationsSummary | null,
  intelligence: ProductIntelligenceView | null,
): HeaderReminder[] {
  const result: HeaderReminder[] = [];

  if (operations && (operations.unread > 0 || operations.pending_replies > 0)) {
    const title = operations.unread > 0
      ? `${operations.unread} 条客户消息待查看`
      : `${operations.pending_replies} 个会话等待回复`;
    const description = operations.pending_replies > 0
      ? `${operations.pending_replies} 个会话仍需人工确认回复`
      : "查看新咨询并判断是否需要继续跟进";
    result.push({
      id: "customer-messages",
      kind: "customer",
      label: "客户消息",
      title,
      description,
      meta: "当前",
      actionLabel: "去回复",
      targetPage: "客户消息",
      targetHash: operations.first_pending_conversation_id
        ? reminderRouteHash("客户消息", "conversation", operations.first_pending_conversation_id)
        : reminderRouteHash("客户消息"),
    });
  }

  if (!intelligence) return result;

  const today = intelligence.market_reference.date;
  const ownedProducts = intelligence.products.filter((product) => (
    product.ownership_status === "owned" && product.monitoring_enabled
  ));
  const failedProducts = ownedProducts.filter((product) => product.last_collection_status === "failed");
  const productsUpdatedToday = new Set(
    ownedProducts
      .filter((product) => product.history.some((snapshot) => snapshot.date === today))
      .map((product) => product.external_id),
  );
  const missingToday = ownedProducts.filter((product) => !productsUpdatedToday.has(product.external_id));
  const nextCollection = parsePlatformDateTime(intelligence.collection.next_collection_at);
  const collectionIsDue = intelligence.collection.last_run?.run_date === today
    || Boolean(nextCollection && nextCollection.getTime() <= Date.now());

  if (failedProducts.length > 0) {
    const first = failedProducts[0];
    result.push({
      id: "product-collection-failed",
      kind: "collection",
      label: "商品数据",
      title: failedProducts.length === 1 ? `${first.title} 采集失败` : `${failedProducts.length} 个商品最新采集失败`,
      description: failedProducts.length === 1
        ? first.last_error_detail || "查看该商品的安全采集诊断"
        : `${first.title} 等 · ${first.last_error_detail || "请查看逐商品采集诊断"}`,
      meta: `最近 ${formatReminderTime(first.last_attempt_at)}`,
      actionLabel: "看诊断",
      targetPage: "商品经营",
      targetHash: reminderRouteHash("商品经营", "overview", "product", first.external_id),
    });
  } else if (collectionIsDue && missingToday.length > 0) {
    result.push({
      id: "product-collection-missing",
      kind: "collection",
      label: "商品更新",
      title: `${missingToday.length} 个本人商品今日尚未更新`,
      description: "可在商品经营中手动采集；系统不会自动修改、发布或投流",
      meta: "今日待更新",
      actionLabel: "去更新",
      targetPage: "商品经营",
      targetHash: reminderRouteHash("商品经营", "overview", "collection"),
    });
  }

  const dueBatches = intelligence.traffic_batches.filter((batch) => Boolean(batch.due_checkpoint));
  if (intelligence.traffic_summary.due_checkpoint_count > 0 || dueBatches.length > 0) {
    const batch = dueBatches[0];
    const checkpoint = batch?.due_checkpoint ? `+${batch.due_checkpoint.slice(1)}h` : "到期";
    result.push({
      id: "traffic-checkpoint-due",
      kind: "traffic",
      label: "曝光复盘",
      title: `${Math.max(intelligence.traffic_summary.due_checkpoint_count, dueBatches.length)} 个曝光观察节点待记录`,
      description: batch
        ? `${batch.products.length} 个商品的批次需要补充 ${checkpoint} 浏览与咨询数据`
        : "补充到期检查点，才能判断曝光后的延迟浏览与咨询变化",
      meta: batch?.due_at ? `${formatReminderTime(batch.due_at)} 到期` : "当前到期",
      actionLabel: "去记录",
      targetPage: "商品经营",
      targetHash: batch
        ? reminderRouteHash("商品经营", "exposure", "batch", batch.id)
        : reminderRouteHash("商品经营", "exposure"),
    });
  }

  const market = intelligence.market_reference;
  if (
    !market.update_completed
    && market.reminder.due
    && !["skipped", "completed"].includes(market.reminder.status)
  ) {
    result.push({
      id: "market-reference-due",
      kind: "market",
      label: "市场更新",
      title: "今日市场关键词尚未更新",
      description: `在现有 Edge 中搜索“${market.selected_keyword}”并导入一份真实结果`,
      meta: `${formatReminderTime(market.reminder.scheduled_for)} 到期`,
      actionLabel: "去更新",
      targetPage: "商品经营",
      targetHash: reminderRouteHash("商品经营", "market", "update"),
    });
  }

  const pendingLaunchPlans = intelligence.launch_plans.filter((plan) => ["proposed", "planned"].includes(plan.status));
  if (pendingLaunchPlans.length > 0) {
    const plan = pendingLaunchPlans[0];
    result.push({
      id: `launch-plan-${plan.id}`,
      kind: "launch",
      label: "上新计划",
      title: pendingLaunchPlans.length === 1 ? plan.title : `${pendingLaunchPlans.length} 个上新方案等待确认`,
      description: "方案只提供标题与时机建议，仍由你在闲鱼人工编辑和发布",
      meta: plan.recommended_window || "待确认",
      actionLabel: "看方案",
      targetPage: "商品经营",
      targetHash: reminderRouteHash("商品经营", "launch", "plan", plan.id),
    });
  } else if (intelligence.launch_recommendation.ready) {
    const recommendation = intelligence.launch_recommendation;
    result.push({
      id: "launch-recommendation-ready",
      kind: "launch",
      label: "建议上新",
      title: `“${recommendation.keyword}”已达到上新判断阈值`,
      description: `${recommendation.suggested_product_type} · 发布前仍需人工确认`,
      meta: recommendation.recommended_window,
      actionLabel: "看建议",
      targetPage: "商品经营",
      targetHash: reminderRouteHash("商品经营", "launch", "recommendation"),
    });
  }

  const dueExperiments = intelligence.modification_experiments.filter((experiment) => (
    experiment.status === "observing" && experiment.can_evaluate
  ));
  if (dueExperiments.length > 0) {
    const experiment = dueExperiments[0];
    const variableLabels = { title: "标题", cover: "首图", description: "描述", price: "价格" } as const;
    result.push({
      id: `experiment-${experiment.id}`,
      kind: "experiment",
      label: "优化复盘",
      title: `${experiment.item_title} 的修改实验待判断`,
      description: `对照基线复核${variableLabels[experiment.variable]}变化，再决定保留、回滚或继续观察`,
      meta: "观察已到期",
      actionLabel: "去复盘",
      targetPage: "商品经营",
      targetHash: reminderRouteHash("商品经营", "launch", "experiment", experiment.id),
    });
  }

  const activeStrategies = intelligence.recommendations
    .filter((recommendation) => recommendation.status === "active" && ["high", "medium"].includes(recommendation.attention))
    .sort((left, right) => right.priority_score - left.priority_score);
  if (activeStrategies.length > 0) {
    const recommendation = activeStrategies[0];
    result.push({
      id: "product-strategy-attention",
      kind: "strategy",
      label: "经营建议",
      title: recommendation.item_title,
      description: `${activeStrategies.length} 个商品值得复核 · ${recommendation.title}`,
      meta: "今日建议",
      actionLabel: "看建议",
      targetPage: "商品经营",
      targetHash: reminderRouteHash("商品经营", "overview", "product", recommendation.item_external_id),
    });
  }

  return result;
}

function formatDateOnly(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
    .format(new Date(`${value}T00:00:00`))
    .replaceAll("/", "-");
}

function useAnimatedNumber(value: number, duration = 820) {
  const [display, setDisplay] = useState(value);
  const previous = useRef(value);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDisplay(value);
      previous.current = value;
      return;
    }

    const startValue = previous.current;
    const difference = value - startValue;
    const startTime = performance.now();
    let frame = 0;

    const tick = (now: number) => {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(startValue + difference * eased);
      if (progress < 1) frame = requestAnimationFrame(tick);
      else previous.current = value;
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [duration, value]);

  return display;
}

function Card({
  className = "",
  id,
  children,
}: {
  className?: string;
  id?: string;
  children: ReactNode;
}) {
  return <section id={id} className={`card ${className}`}>{children}</section>;
}

function CardHeader({
  title,
  action,
}: {
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="card-header">
      <h2>{title}</h2>
      {action}
    </div>
  );
}

function Sidebar({
  active,
  onActiveChange,
  onQuickAdd,
  open,
  onClose,
  projects,
}: {
  active: string;
  onActiveChange: (value: string) => void;
  onQuickAdd: () => void;
  open: boolean;
  onClose: () => void;
  projects: Project[];
}) {
  const activeProjects = projects.filter((project) => project.status === "in_progress");
  const furthestDelivery = Math.max(
    0,
    ...activeProjects.map((project) => remainingDays(project.dueDate)),
  );

  return (
    <>
      <button
        className={`sidebar-scrim ${open ? "is-open" : ""}`}
        aria-label="关闭导航"
        onClick={onClose}
      />
      <aside className={`sidebar ${open ? "is-open" : ""}`}>
        <div className="brand xunying-brand">
          <img src="/assets/xunying/orbit-mark.png" alt="" aria-hidden="true" draggable={false} />
          <div>
            <strong>循营</strong>
            <span>一人经营台</span>
          </div>
          <button className="mobile-close" aria-label="关闭导航" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <nav aria-label="主导航">
          {navItems.map(({ label, displayLabel, icon: Icon }) => (
            <button
              key={label}
              className={active === label ? "active" : ""}
              onClick={() => {
                onActiveChange(label);
                onClose();
              }}
            >
              <Icon size={22} weight={active === label ? "fill" : "regular"} />
              <span>{displayLabel || label}</span>
              {active === label && <Sparkle className="nav-sparkle" size={17} weight="fill" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-spacer" />

        <div className="sidebar-promo xiaoce-sidebar-card">
          <div>
            <small>小策 · AI 技术与商业合伙人</small>
            <strong>把不确定，<br />变成可验证行动</strong>
            <button onClick={() => { onActiveChange("AI经营助手"); onClose(); }}>
              查看今日判断 <ArrowRight size={15} weight="bold" />
            </button>
          </div>
          <div className="sidebar-promo-artwork" aria-hidden="true">
            <img src="/assets/xunying/xiaoce-avatar.png" alt="" draggable={false} />
          </div>
        </div>

        <div className="sidebar-countdown">
          <div className="eyebrow"><HourglassMedium size={18} weight="fill" /> 本月工期倒计时</div>
          <strong>{furthestDelivery}<small>天</small></strong>
          <span>{activeProjects.length} 个项目待交付</span>
          <div className="countdown-bar"><i style={{ width: `${Math.min(100, furthestDelivery * 7)}%` }} /></div>
          <div className="sidebar-countdown-artwork" aria-hidden="true">
            <img src="/assets/chrome-v2/delivery-hourglass.png" alt="" draggable={false} />
          </div>
        </div>

        <footer>© {new Date().getFullYear()} 循营 · 一人经营台<br />Local-first business OS.</footer>
      </aside>
    </>
  );
}

function TopHeader({
  search,
  onSearch,
  onMenu,
  activePage,
  reminders,
  onReminderAction,
  onViewAllReminders,
  onRefreshReminders,
  onOpenSettings,
  profileName,
  profilePlan,
}: {
  search: string;
  onSearch: (value: string) => void;
  onMenu: () => void;
  activePage: string;
  reminders: HeaderReminder[];
  onReminderAction: (reminder: HeaderReminder) => void;
  onViewAllReminders: () => void;
  onRefreshReminders: () => void;
  onOpenSettings: (section: SettingsSectionName) => void;
  profileName: string;
  profilePlan: string;
}) {
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const notificationAnchorRef = useRef<HTMLDivElement>(null);
  const notificationButtonRef = useRef<HTMLButtonElement>(null);
  const notificationPanelRef = useRef<HTMLElement>(null);
  const profileAnchorRef = useRef<HTMLDivElement>(null);
  const profileButtonRef = useRef<HTMLButtonElement>(null);
  const meta = pageMeta[activePage] || pageMeta["首页概览"];
  const searchable = ["首页概览", "项目管理", "收入记录", "支出记录", "客户管理"].includes(activePage);
  const visibleReminders = reminders.slice(0, 4);

  useEffect(() => {
    if (!notificationsOpen && !profileOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (notificationsOpen && !notificationAnchorRef.current?.contains(target)) setNotificationsOpen(false);
      if (profileOpen && !profileAnchorRef.current?.contains(target)) setProfileOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [notificationsOpen, profileOpen]);

  useEffect(() => {
    if (!notificationsOpen) return;
    const panel = notificationPanelRef.current;
    const frame = window.requestAnimationFrame(() => panel?.focus());
    const mobile = window.matchMedia("(max-width: 560px)").matches;
    const previousOverflow = document.body.style.overflow;
    if (mobile) document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setNotificationsOpen(false);
        window.requestAnimationFrame(() => notificationButtonRef.current?.focus());
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(
        "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
      )).filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (document.activeElement === panel) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!panel.contains(document.activeElement)) {
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
  }, [notificationsOpen]);

  useEffect(() => {
    if (!profileOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setProfileOpen(false);
      window.requestAnimationFrame(() => profileButtonRef.current?.focus());
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [profileOpen]);

  const closeNotifications = () => setNotificationsOpen(false);

  return (
    <header className={`top-header ${activePage === "AI经营助手" ? "top-header-partner" : ""}`}>
      <button className={`menu-button ${activePage === "AI经营助手" ? "partner-brand-menu" : ""}`} aria-label="打开导航" onClick={onMenu}>
        {activePage === "AI经营助手" ? <><img src="/assets/xunying/orbit-mark.png" alt="" aria-hidden="true" /><span>循营</span></> : <List size={24} />}
      </button>
      <div className="greeting">
        <h1>{meta.title}{activePage === "数据统计" && <em className="page-context-tag">商品增长复盘</em>}{activePage === "首页概览" && <span aria-hidden="true"><HandWaving size={25} weight="duotone" /></span>}</h1>
        <p>{meta.subtitle}</p>
      </div>
      <img className={`header-planet ${activePage === "AI经营助手" ? "header-partner-avatar" : ""}`} src={activePage === "AI经营助手" ? "/assets/xunying/xiaoce-avatar.png" : "/assets/chrome-v2/header-planet.png"} alt="" aria-hidden="true" draggable={false} />
      <label className="search-box">
        <MagnifyingGlass size={23} />
        <input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder={searchable ? meta.placeholder : "当前页面无需搜索"}
          aria-label="搜索项目、客户或订单"
          disabled={!searchable}
        />
      </label>
      <div className="header-actions">
        <div className="popover-anchor" ref={notificationAnchorRef}>
          <button
            ref={notificationButtonRef}
            className="round-button"
            aria-label={`查看智能提醒，${reminders.length} 项待处理`}
            aria-expanded={notificationsOpen}
            aria-controls="smart-reminder-panel"
            aria-haspopup="dialog"
            onClick={() => {
              setProfileOpen(false);
              if (!notificationsOpen) onRefreshReminders();
              setNotificationsOpen((value) => !value);
            }}
          >
            <Bell size={23} />
            {reminders.length > 0 && <b>{reminders.length}</b>}
          </button>
          {notificationsOpen && (
            <>
              <button className="notification-backdrop" aria-label="关闭智能提醒" onClick={closeNotifications} tabIndex={-1} />
              <section
                ref={notificationPanelRef}
                id="smart-reminder-panel"
                className="header-popover notification-popover"
                role="dialog"
                aria-modal="true"
                aria-labelledby="smart-reminder-title"
                tabIndex={-1}
              >
                <span className="notification-drawer-handle" aria-hidden="true" />
                <header className="notification-heading">
                  <span className="notification-heading-icon"><Bell size={21} weight="duotone" /></span>
                  <span className="notification-heading-copy">
                    <strong id="smart-reminder-title">智能提醒</strong>
                    <small>客户消息、商品更新与经营建议</small>
                  </span>
                  <span className="notification-status">{reminders.length > 0 ? `${reminders.length} 项待处理` : "当前已清空"}</span>
                  <button className="notification-close" aria-label="关闭智能提醒" onClick={closeNotifications}><X size={19} /></button>
                </header>

                {visibleReminders.length > 0 ? (
                  <ul className="notification-list" aria-label="待处理客户与商品经营事项">
                    {visibleReminders.map((reminder) => {
                      const ReminderIcon = headerReminderIcons[reminder.kind];
                      return (
                        <li key={reminder.id}>
                          <button
                            className={`notification-item is-${reminder.kind}`}
                            onClick={() => {
                              closeNotifications();
                              onReminderAction(reminder);
                            }}
                          >
                            <span className="notification-item-icon"><ReminderIcon size={21} weight="duotone" /></span>
                            <span className="notification-item-copy">
                              <small>{reminder.label}</small>
                              <strong>{reminder.title}</strong>
                              <span>{reminder.description}</span>
                            </span>
                            <span className="notification-item-side">
                              <time>{reminder.meta}</time>
                              <span>{reminder.actionLabel}<ArrowRight size={14} /></span>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <div className="notification-empty">
                    <span><CheckCircle size={25} weight="duotone" /></span>
                    <strong>当前事项已处理完成</strong>
                    <p>新的客户消息、商品更新或经营建议会显示在这里。</p>
                  </div>
                )}

                <footer className="notification-footer">
                  <button onClick={() => { closeNotifications(); onViewAllReminders(); }}>
                    查看全部提醒 <ArrowRight size={15} />
                  </button>
                  <button onClick={() => { closeNotifications(); onOpenSettings("提醒通知"); }}>
                    <GearSix size={16} />提醒设置
                  </button>
                </footer>
              </section>
            </>
          )}
        </div>
        <div className="popover-anchor" ref={profileAnchorRef}>
          <button
            ref={profileButtonRef}
            className="profile-button"
            aria-label="打开个人与账户设置"
            aria-expanded={profileOpen}
            onClick={() => {
              setNotificationsOpen(false);
              setProfileOpen((value) => !value);
            }}
          >
            <span className="avatar"><UserCircle size={33} weight="duotone" /></span>
            <span><strong>{profileName}</strong><small>{profilePlan}</small></span>
            <CaretDown size={16} />
          </button>
          {profileOpen && (
            <div className="header-popover profile-popover">
              <button onClick={() => { onOpenSettings("个人资料"); setProfileOpen(false); }}>个人资料</button>
              <button onClick={() => { onOpenSettings("账号设置"); setProfileOpen(false); }}>账号设置</button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

function MiniChart({ type, color, empty = false }: { type: "line" | "bar"; color: string; empty?: boolean }) {
  const chartData = (type === "line" ? miniLineData : miniBars).map((item) => ({ value: empty ? 0 : item.value }));
  return (
    <div className="mini-chart" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        {type === "line" ? (
          <AreaChart data={chartData} margin={{ top: 8, right: 2, bottom: 0, left: 2 }}>
            <Area
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2.4}
              fill={color}
              fillOpacity={0.09}
              dot={{ r: 2.4, fill: color, strokeWidth: 0 }}
            />
          </AreaChart>
        ) : (
          <BarChart data={chartData} margin={{ top: 8, right: 2, bottom: 0, left: 2 }}>
            <Bar dataKey="value" fill={color} radius={[4, 4, 0, 0]} opacity={0.72} />
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

function MetricCard({
  title,
  value,
  prefix = "",
  suffix = "",
  precision = 0,
  comparison,
  tone,
  image,
  chart,
  index,
}: {
  title: string;
  value: number;
  prefix?: string;
  suffix?: string;
  precision?: number;
  comparison: ReactNode;
  tone: "purple" | "green" | "blue" | "indigo" | "orange";
  image: string;
  chart?: "line" | "bar";
  index: number;
}) {
  const animated = useAnimatedNumber(value);

  return (
    <Card className={`metric-card tone-${tone}`}>
      <div className="metric-content">
        <div className="metric-topline">
          <h2>{title}</h2>
          <div className="metric-artwork" aria-hidden="true">
            <img className="metric-image" src={image} alt="" draggable={false} />
          </div>
        </div>
        <strong className="metric-value">
          {prefix}{animated.toLocaleString("zh-CN", {
            minimumFractionDigits: precision,
            maximumFractionDigits: precision,
          })}<small>{suffix}</small>
        </strong>
        <p>{comparison}</p>
      </div>
      {chart && <MiniChart type={chart} empty={value === 0} color={tone === "green" ? "#16c77a" : tone === "blue" ? "#3978ff" : "#6646f5"} />}
      <span className="metric-index">0{index + 1}</span>
    </Card>
  );
}

function IncomeTrendCard({ snapshot }: { snapshot: LedgerSnapshot }) {
  const monthlyTotal = getBusinessSummary(snapshot).monthlyIncome;

  const data = useMemo(() => {
    const netEvents = [
      ...snapshot.payments
        .filter((payment) => payment.status === "confirmed")
        .map((payment) => ({ occurredAt: payment.paidAt, amount: payment.amount })),
      ...snapshot.settlementIssues
        .filter((issue) => issue.refundAmount > 0)
        .map((issue) => ({ occurredAt: issue.occurredAt, amount: -issue.refundAmount })),
    ];
    const last30Days = Array.from({ length: 8 }, (_, index) => {
      const date = new Date();
      date.setDate(date.getDate() - (7 - index) * 4);
      const bucketStart = new Date(date);
      bucketStart.setDate(bucketStart.getDate() - 3);
      bucketStart.setHours(0, 0, 0, 0);
      const bucketEnd = new Date(date);
      bucketEnd.setHours(23, 59, 59, 999);
      return {
        date: `${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`,
        value: netEvents.filter((event) => { const occurredAt = new Date(event.occurredAt); return occurredAt >= bucketStart && occurredAt <= bucketEnd; }).reduce((sum, event) => sum + event.amount, 0),
      };
    });
    return last30Days;
  }, [snapshot.payments, snapshot.settlementIssues]);

  return (
    <Card className="trend-card">
      <CardHeader
        title="净收入趋势"
        action={<span className="subtle-select" aria-label="统计周期：近30天">近30天</span>}
      />
      <span className="chart-unit">单位：元</span>
      <div className="trend-chart" aria-label="近 30 天收入趋势图">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 20, right: 12, left: -16, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="#edf0f7" strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fill: "#68718a", fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fill: "#68718a", fontSize: 11 }} tickLine={false} axisLine={false} width={54} />
            <Tooltip
              cursor={{ stroke: "#d9d3ff", strokeDasharray: "3 3" }}
              contentStyle={{ border: 0, borderRadius: 12, boxShadow: "0 10px 32px rgba(75, 59, 170, .18)" }}
              formatter={(value) => [currency.format(Number(value)), "净收入"]}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke="#6246f3"
              strokeWidth={3}
              fill="#6f53f6"
              fillOpacity={0.12}
              dot={{ r: 4, fill: "#6645f2", stroke: "white", strokeWidth: 2 }}
              activeDot={{ r: 6, fill: "#6645f2", stroke: "white", strokeWidth: 3 }}
            />
          </AreaChart>
        </ResponsiveContainer>
        <div className="chart-value-badge">{compactCurrency.format(monthlyTotal)}</div>
      </div>
    </Card>
  );
}

const projectIcons: Record<Project["accent"], PhosphorIcon> = {
  blue: ShoppingBag,
  green: ForkKnife,
  purple: ChartLineUp,
  orange: ClipboardText,
};

function ActiveProjectsCard({
  snapshot,
  projects,
  onNavigate,
  onOpenProject,
}: {
  snapshot: LedgerSnapshot;
  projects: Project[];
  onNavigate: () => void;
  onOpenProject: (projectId: string) => void;
}) {
  const financialByProject = new Map(getProjectFinancials(snapshot).map((item) => [item.project.id, item]));
  const statusRank: Record<Project["status"], number> = {
    overdue: 0,
    delivered: 1,
    in_progress: 2,
    pending: 3,
    completed: 4,
  };
  const active = projects
    .filter((project) => {
      const financial = financialByProject.get(project.id);
      if (hasTerminalSettlementIssue(financial?.settlementIssues || [])) return false;
      const outstanding = financial?.outstanding || 0;
      return project.status === "pending"
        || project.status === "in_progress"
        || project.status === "overdue"
        || (project.status === "delivered" && outstanding > 0);
    })
    .sort((left, right) => statusRank[left.status] - statusRank[right.status] || left.dueDate.localeCompare(right.dueDate))
    .slice(0, 3);

  return (
    <Card className="projects-card" id="active-projects">
      <CardHeader title="当前项目" action={<button className="text-button" onClick={onNavigate}>查看全部 <CaretRight size={14} /></button>} />
      <div className="project-list">
        {active.length ? active.map((project) => {
          const Icon = projectIcons[project.accent];
          const duration = Math.max(1, diffInDays(project.startDate, new Date(`${project.dueDate}T00:00:00`)));
          const financial = financialByProject.get(project.id);
          const outstanding = financial?.outstanding || 0;
          const latestIssue = latestSettlementIssue(financial?.settlementIssues || []);
          const dueDays = remainingDays(project.dueDate);
          const statusCopy = project.status === "overdue"
            ? `已超期 ${Math.max(1, Math.abs(dueDays))} 天`
            : project.status === "delivered" && outstanding > 0
              ? `待回款 ${compactCurrency.format(outstanding)}`
              : project.status === "pending"
                ? dueDays >= 0 ? `待开始 · 距交付 ${dueDays} 天` : "待开始 · 已到交付日"
                : dueDays >= 0 ? `剩余 ${dueDays} 天` : `已到期 ${Math.abs(dueDays)} 天`;
          return (
            <button type="button" className="project-row project-row-button" key={project.id} onClick={() => onOpenProject(project.id)} aria-label={`打开${project.name}的沉浸任务流`}>
              <span className={`project-icon ${project.accent}`}><Icon size={24} weight="duotone" /></span>
              <div className="project-details">
                <strong>{project.name}</strong>
                <span>{latestIssue ? `异常：${settlementIssueLabels[latestIssue.type]}` : project.status === "delivered" && outstanding > 0 ? "已交付 · 等待回款" : `工期：${duration}天`}</span>
                <div className="project-progress-line">
                  <div><i style={{ width: `${project.progress}%` }} /></div>
                  <small>{project.progress}%</small>
                </div>
              </div>
              <span className={`days-pill ${project.status === "overdue" ? "is-overdue" : project.status === "delivered" && outstanding > 0 ? "is-receivable" : ""}`}>{statusCopy}</span>
            </button>
          );
        }) : <div className="dashboard-empty"><Briefcase size={34} weight="duotone" /><strong>暂无当前项目</strong><span>待开始、进行中、逾期或待回款项目会显示在这里；已终止合作不会进入当前项目</span></div>}
      </div>
    </Card>
  );
}

function OperationDurationCard({ startedAt }: { startedAt: string }) {
  const days = diffInDays(startedAt);
  const animated = useAnimatedNumber(days, 620);

  return (
    <Card className="operation-card">
      <h2>运营时长</h2>
      <strong>{Math.round(animated)}<small>天</small></strong>
      <p>自 {formatDateOnly(startedAt)} 起</p>
      <div className="operation-artwork" aria-hidden="true">
        <img src="/assets/dashboard-v2/operation-calendar.png" alt="" draggable={false} />
      </div>
      <RocketLaunch className="operation-rocket" size={28} weight="duotone" />
      <Sparkle className="operation-spark one" size={16} weight="fill" />
      <Sparkle className="operation-spark two" size={20} weight="fill" />
    </Card>
  );
}

function PaymentTable({
  payments,
  projects,
  customers,
  onNavigate,
}: {
  payments: Payment[];
  projects: Project[];
  customers: Customer[];
  onNavigate: () => void;
}) {
  const getProject = (id: string) => projects.find((project) => project.id === id);
  const getCustomer = (id: string) => customers.find((customer) => customer.id === id);

  return (
    <Card className="payments-card" id="payment-records">
      <CardHeader title="最新收款记录" action={<button className="text-button" onClick={onNavigate}>查看全部 <CaretRight size={14} /></button>} />
      <div className="payment-table" role="table" aria-label="最新收款记录">
        <div className="payment-table-head" role="row">
          <span>项目名称</span><span>客户</span><span>金额（元）</span><span>收款时间</span><span>备注</span>
        </div>
        {payments.length ? payments.slice(0, 4).map((payment) => {
          const project = getProject(payment.projectId);
          const customer = getCustomer(payment.customerId);
          const accent = project?.accent || "blue";
          const Icon = projectIcons[accent];
          return (
            <div className="payment-table-row" role="row" key={payment.id}>
              <span className="payment-project"><i className={accent}><Icon size={16} weight="duotone" /></i><b>{project?.name || "未命名项目"}</b></span>
              <span data-label="客户">{customer?.name || "新客户"}</span>
              <span className="payment-amount" data-label="金额">{payment.amount.toFixed(2)}</span>
              <span data-label="收款时间">{dateTimeFormatter.format(new Date(payment.paidAt))}</span>
              <span data-label="备注">{payment.notes || paymentLabels[payment.type]}</span>
            </div>
          );
        }) : <div className="payment-table-empty"><Wallet size={30} weight="duotone" /><span>暂无收款记录，请录入自己的第一笔收入</span></div>}
      </div>
      <div className="table-footer">已全部加载，共 {payments.length} 条记录</div>
    </Card>
  );
}

function DailyBalanceCard({ todayIncome, todayExpense }: { todayIncome: number; todayExpense: number }) {
  const todayProfit = todayIncome - todayExpense;
  const positiveIncome = Math.max(0, todayIncome);
  const refundImpact = Math.max(0, -todayIncome);
  const total = Math.max(1, positiveIncome + refundImpact + todayExpense);
  const pie = [
    { name: "净收入", value: positiveIncome / total * 100, color: "#3b82f6" },
    { name: "支出", value: todayExpense / total * 100, color: "#ff7359" },
    ...(refundImpact > 0 ? [{ name: "退款净额", value: refundImpact / total * 100, color: "#f59e0b" }] : []),
  ];
  return (
    <Card className="balance-card">
      <CardHeader title="今日收支情况" />
      <div className="balance-content">
        <div className="donut-wrap">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={pie} dataKey="value" innerRadius={42} outerRadius={58} startAngle={90} endAngle={-270} stroke="none">
                {pie.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div><span>净利润</span><strong>{compactCurrency.format(todayProfit)}</strong></div>
        </div>
        <div className="balance-legend">
          <p><i className="blue" />净收入 <strong>{compactCurrency.format(todayIncome)}</strong></p>
          <p><i className="red" />支出 <strong>{compactCurrency.format(todayExpense)}</strong></p>
          {refundImpact > 0 && <p><i className="orange" />退款净额 <strong>{compactCurrency.format(refundImpact)}</strong></p>}
        </div>
      </div>
    </Card>
  );
}

function OperatingInsightStrip({
  snapshot,
  onNavigate,
}: {
  snapshot: LedgerSnapshot;
  onNavigate: (page: string) => void;
}) {
  const summary = getBusinessSummary(snapshot);
  const bestProject = summary.projectFinancials.slice().sort((a, b) => b.profit - a.profit)[0];
  const dueSoon = snapshot.payments.filter((payment) => payment.status === "pending" && remainingDays(payment.dueAt) <= 3).length;
  const unsettledCount = summary.projectFinancials.filter(({ project, outstanding }) => isClientProject(project) && outstanding > 0).length;
  return <Card className="operating-insight-strip">
    <div className="insight-heading"><span><Sparkle size={16} weight="fill" />经营洞察</span><strong>把流水变成下一步行动</strong></div>
    <div className="insight-item profit"><i><TrendUp size={22} weight="duotone" /></i><span><small>实际利润</small><b>{compactCurrency.format(summary.actualProfit)}</b><em>利润率 {summary.totalIncome ? Math.round(summary.actualProfit / summary.totalIncome * 100) : 0}%</em></span></div>
    <div className="insight-item collection"><i><Bell size={22} weight="duotone" /></i><span><small>回款风险</small><b>{compactCurrency.format(summary.outstanding)} 待收</b><em>{unsettledCount} 个项目未结清{dueSoon ? ` · ${dueSoon} 个节点临期` : ""}</em></span></div>
    <div className="insight-item value"><i><Lightbulb size={22} weight="duotone" /></i><span><small>定价建议</small><b>{bestProject?.project.name || "暂无项目"}</b><em>小时收益 {compactCurrency.format(bestProject?.hourlyIncome || 0)}</em></span></div>
    <div className="insight-actions"><button onClick={() => onNavigate("数据统计")}>查看增长统计</button><button className="primary" onClick={() => onNavigate("AI经营助手")}><Brain size={15} />询问 AI 助手</button></div>
  </Card>;
}

function CustomerPipelineStrip({ onNavigate }: { onNavigate: (page: string) => void }) {
  const [summary, setSummary] = useState<{ unread: number; pending_replies: number; open_leads: number; quoted_leads: number; converted_leads: number } | null>(null);
  useEffect(() => {
    let active = true;
    void localPlatformService.operationsSummary().then((value) => { if (active) setSummary(value); }).catch(() => { if (active) setSummary(null); });
    return () => { active = false; };
  }, []);
  if (!summary) return null;
  return <Card className="customer-pipeline-strip">
    <div className="pipeline-title"><span><ChatCircleDots size={17} weight="fill" />客户经营漏斗</span><small>闲鱼与微信实时汇总</small></div>
    <div><strong>{summary.unread}</strong><small>未读消息</small></div>
    <div><strong>{summary.pending_replies}</strong><small>待回复会话</small></div>
    <div><strong>{summary.open_leads}</strong><small>待转化线索</small></div>
    <div><strong>{summary.quoted_leads}</strong><small>报价中</small></div>
    <button onClick={() => onNavigate("客户消息")}>进入客户消息 <ArrowRight size={14} /></button>
  </Card>;
}

function ProductStrategyStrip({ onNavigate }: { onNavigate: (page: string) => void }) {
  const [insight, setInsight] = useState<ProductIntelligenceView | null>(null);
  useEffect(() => {
    let active = true;
    void localPlatformService.productIntelligence().then((value) => { if (active) setInsight(value); }).catch(() => { if (active) setInsight(null); });
    return () => { active = false; };
  }, []);
  if (!insight) return null;
  const top = insight.recommendations[0];
  return <Card className="product-strategy-strip">
    <div className="product-strip-title"><span><ShoppingBag size={17} weight="fill" />商品经营雷达</span><small>每日最多一次只读采集</small></div>
    <div><strong>{insight.summary.monitored_products}</strong><small>监测商品</small></div>
    <div><strong>{insight.summary.needs_attention}</strong><small>需要关注</small></div>
    <div><strong>{insight.summary.traffic_candidates}</strong><small>人工投流候选</small></div>
    <div className="product-strip-advice"><small>今日首要建议</small><strong>{top?.title || "继续积累商品快照"}</strong></div>
    <button onClick={() => onNavigate("商品经营")}>查看经营策略 <ArrowRight size={14} /></button>
  </Card>;
}

function ReminderCard({ reminders, onOpen }: { reminders: HeaderReminder[]; onOpen: (reminder: HeaderReminder) => void }) {
  return (
    <Card id="smart-reminders" className="reminder-card">
      <CardHeader title="智能提醒" action={<span className="reminder-badge">{reminders.length} 条经营提醒</span>} />
      <ul>
        {reminders.slice(0, 3).map((reminder) => (
          <li key={reminder.id} className={`is-${reminder.kind}`}>
            <i />
            <span><b>{reminder.label}</b>{reminder.title}</span>
            <time>{reminder.meta}</time>
            <button onClick={() => onOpen(reminder)}>{reminder.actionLabel}</button>
          </li>
        ))}
        {reminders.length === 0 && <li className="reminder-empty"><CheckCircle size={17} weight="fill" /><span>客户消息与商品经营暂无待处理事项</span></li>}
      </ul>
    </Card>
  );
}

function MonthlyGoalCard({ current, goal, onEdit }: { current: number; goal: number; onEdit: () => void }) {
  const progress = goal > 0 ? Math.min(100, (current / goal) * 100) : 0;
  return (
    <Card className="goal-card">
      <CardHeader title="本月目标" action={<button className="text-button" onClick={onEdit}>编辑目标 <CaretRight size={14} /></button>} />
      <div className="goal-copy">
        <span>月收入目标</span>
        <strong>{compactCurrency.format(current)} <small>/ {goal > 0 ? goal.toLocaleString("zh-CN") : "未设置"}</small></strong>
        <div className="goal-progress"><i style={{ width: `${progress}%` }} /></div>
        <p>{goal > 0 ? <>还差 <b>{compactCurrency.format(Math.max(0, goal - current))}</b> 元可达成目标！</> : "设置你的首个月度目标后开始追踪"}</p>
      </div>
      <div className="goal-artwork" aria-hidden="true">
        <img src="/assets/dashboard-v2/goal-trophy.png" alt="" draggable={false} />
      </div>
    </Card>
  );
}

function CustomerSourceCard({ customers, onNavigate }: { customers: Customer[]; onNavigate: () => void }) {
  const data = [
    { name: "咸鱼平台", value: customers.filter((item) => item.source === "xianyu").length, color: "#4ea0ff" },
    { name: "老客户介绍", value: customers.filter((item) => item.source === "referral").length, color: "#5a4ef4" },
    { name: "其他渠道", value: customers.filter((item) => !["xianyu", "referral"].includes(item.source)).length, color: "#ffb51b" },
  ];
  const total = customers.length;
  return (
    <Card className="source-card">
      <CardHeader title="客户来源分析（本月）" action={<button className="text-button" onClick={onNavigate}>查看详情 <CaretRight size={14} /></button>} />
      <div className="source-content">
        <div className="source-donut">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} dataKey="value" innerRadius={36} outerRadius={50} startAngle={90} endAngle={-270} paddingAngle={2} stroke="none">
                {data.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div><span>总客户</span><strong>{total}</strong></div>
        </div>
        <div className="source-legend">
          {data.map((item) => (
            <p key={item.name}><i style={{ background: item.color }} /><span>{item.name}</span><strong>{item.value}</strong><small>({(total ? item.value / total * 100 : 0).toFixed(1)}%)</small></p>
          ))}
        </div>
      </div>
    </Card>
  );
}

function DeliveryCountdownCard({ projects, onNavigate }: { projects: Project[]; onNavigate: () => void }) {
  const active = projects.filter((project) => project.status === "in_progress");
  const days = Math.max(0, ...active.map((project) => remainingDays(project.dueDate)));
  return (
    <Card className="delivery-card">
      <CardHeader title="发货倒计时" />
      <strong>{days}<small>天</small></strong>
      <span>{active.length} 个项目待交付</span>
      <button onClick={onNavigate}>
        去看项目 <ArrowRight size={15} weight="bold" />
      </button>
    </Card>
  );
}

function QuickAccountingDrawer({
  open,
  projects,
  customers,
  settings,
  initialProjectId,
  onClose,
  onSubmit,
}: {
  open: boolean;
  projects: Project[];
  customers: Customer[];
  settings: LedgerSnapshot["settings"];
  initialProjectId?: string | null;
  onClose: () => void;
  onSubmit: (value: QuickAccountingFormValue) => Promise<void>;
}) {
  const initialDate = () => {
    const date = new Date();
    date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
    return date.toISOString().slice(0, 16);
  };
  const [projectName, setProjectName] = useState(projects[0]?.name || "");
  const [customerName, setCustomerName] = useState(customers[0]?.name || "");
  const [amount, setAmount] = useState("");
  const [type, setType] = useState<PaymentType>(settings.defaultPaymentType || "deposit");
  const [paidAt, setPaidAt] = useState(initialDate);
  const [durationDays, setDurationDays] = useState(String(settings.defaultDurationDays || 30));
  const [contractTotal, setContractTotal] = useState("");
  const [recordStatus, setRecordStatus] = useState<"confirmed" | "pending">("confirmed");
  const [dueAt, setDueAt] = useState(() => new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const projectInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setType(settings.defaultPaymentType || "deposit");
    setDurationDays(String(settings.defaultDurationDays || 30));
    const project = projects.find((item) => item.id === initialProjectId);
    if (project) {
      setProjectName(project.name);
      const customer = customers.find((item) => item.id === project.customerId);
      if (customer) setCustomerName(customer.name);
      setContractTotal(String(project.totalAmount || ""));
      setRecordStatus("pending");
      setDueAt(project.dueDate.slice(0, 10));
    } else {
      setRecordStatus("confirmed");
      setContractTotal("");
    }
  }, [customers, initialProjectId, open, projects, settings.defaultDurationDays, settings.defaultPaymentType]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => projectInput.current?.focus({ preventScroll: true }), 120);
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", handleKey);
    };
  }, [onClose, open]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const nextErrors: Record<string, string> = {};
    if (!projectName.trim()) nextErrors.projectName = "请输入项目名称";
    if (!customerName.trim()) nextErrors.customerName = "请输入客户名称";
    if (!amount || Number(amount) <= 0) nextErrors.amount = "请输入大于 0 的收款金额";
    if (!paidAt) nextErrors.paidAt = "请选择收款时间";
    if (!durationDays || Number(durationDays) < 1) nextErrors.durationDays = "预计工期至少为 1 天";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    setSubmitting(true);
    await onSubmit({
      projectName: projectName.trim(),
      customerName: customerName.trim(),
      amount: Number(amount),
      type,
      paidAt,
      durationDays: Number(durationDays),
      contractTotal: contractTotal ? Number(contractTotal) : undefined,
      status: recordStatus,
      dueAt,
      notes: notes.trim() || undefined,
    });
    setSubmitting(false);
    setAmount("");
    setNotes("");
    setContractTotal("");
    setPaidAt(initialDate());
    setErrors({});
  };

  return (
    <div className={`drawer-layer ${open ? "is-open" : ""}`} aria-hidden={!open}>
      <button className="drawer-backdrop" aria-label="关闭快速记账" onClick={onClose} tabIndex={open ? 0 : -1} />
      <aside className="quick-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
        <div className="drawer-header">
          <div><span>快速记账</span><h2 id="drawer-title">{recordStatus === "confirmed" ? "记录一笔确认到账" : "新增一个待收节点"}</h2></div>
          <button aria-label="关闭" onClick={onClose}><X size={22} /></button>
        </div>
        <form onSubmit={submit} noValidate>
          <label>
            <span>项目名称</span>
            <input ref={projectInput} list="project-options" value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="选择或新建项目" />
            <datalist id="project-options">{projects.map((project) => <option key={project.id} value={project.name} />)}</datalist>
            {errors.projectName && <small className="field-error"><WarningCircle size={14} />{errors.projectName}</small>}
          </label>
          <label>
            <span>客户</span>
            <input list="customer-options" value={customerName} onChange={(event) => setCustomerName(event.target.value)} placeholder="选择或输入客户名称" />
            <datalist id="customer-options">{customers.map((customer) => <option key={customer.id} value={customer.name} />)}</datalist>
            {errors.customerName && <small className="field-error"><WarningCircle size={14} />{errors.customerName}</small>}
          </label>
          <div className="form-row">
            <label>
              <span>收款金额（元）</span>
              <input type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0.00" />
              {errors.amount && <small className="field-error"><WarningCircle size={14} />{errors.amount}</small>}
            </label>
            <label>
              <span>收款类型</span>
              <select value={type} onChange={(event) => setType(event.target.value as PaymentType)}>
                {Object.entries(paymentLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          </div>
          <div className="form-row">
            <label>
              <span>记录状态</span>
              <select value={recordStatus} onChange={(event) => setRecordStatus(event.target.value as "confirmed" | "pending")}>
                <option value="confirmed">已确认到账</option>
                <option value="pending">计划待收款</option>
              </select>
            </label>
            <label>
              <span>应收日期</span>
              <input type="date" value={dueAt} onChange={(event) => setDueAt(event.target.value)} />
            </label>
          </div>
          <label>
            <span>合同总额（新项目）</span>
            <input type="number" min="0" step="0.01" value={contractTotal} onChange={(event) => setContractTotal(event.target.value)} placeholder="不填则使用本次金额" />
          </label>
          <label>
            <span>收款时间</span>
            <input type="datetime-local" value={paidAt} onChange={(event) => setPaidAt(event.target.value)} />
            {errors.paidAt && <small className="field-error"><WarningCircle size={14} />{errors.paidAt}</small>}
          </label>
          <label>
            <span>预计工期（天）</span>
            <input type="number" min="1" max="365" value={durationDays} onChange={(event) => setDurationDays(event.target.value)} />
            {errors.durationDays && <small className="field-error"><WarningCircle size={14} />{errors.durationDays}</small>}
          </label>
          <label>
            <span>备注</span>
            <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="补充本次收款说明（可选）" rows={4} />
          </label>
          <div className="drawer-tip"><Lightbulb size={19} weight="duotone" />待收节点会进入回款提醒；只有确认到账才计入收入。</div>
          <button className="submit-payment" type="submit" disabled={submitting}>
            {submitting ? <><span className="spinner" />正在保存...</> : <><CheckCircle size={20} weight="fill" />{recordStatus === "confirmed" ? "确认到账并保存" : "保存待收节点"}</>}
          </button>
        </form>
      </aside>
    </div>
  );
}

function LoadingDashboard() {
  return (
    <div className="loading-dashboard" aria-label="正在加载经营数据">
      <div className="loading-header" />
      <div className="loading-metrics">{Array.from({ length: 5 }, (_, index) => <div key={index} />)}</div>
      <div className="loading-grid"><div /><div /><div /></div>
    </div>
  );
}

function DashboardLayout({
  snapshot,
  onSnapshotChange,
  onPersistedSnapshot,
  liveSignalVersion,
}: {
  snapshot: LedgerSnapshot;
  onSnapshotChange: (snapshot: LedgerSnapshot) => void;
  onPersistedSnapshot: (snapshot: LedgerSnapshot) => void;
  liveSignalVersion: number;
}) {
  const initialRoute = useRef(readAppRoute()).current;
  const [activeNav, setActiveNav] = useState(initialRoute.page);
  const [settingsSection, setSettingsSection] = useState<SettingsSectionName>(initialRoute.settingsSection);
  const [projectRoute, setProjectRoute] = useState<ProjectPageRoute | null>(initialRoute.projectRoute);
  const [customerRoute, setCustomerRoute] = useState<CustomerRequirementRoute | null>(initialRoute.customerRoute);
  const [search, setSearch] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerProjectId, setDrawerProjectId] = useState<string | null>(null);
  const [receiptTarget, setReceiptTarget] = useState<PaymentConfirmationTarget | null>(null);
  const [changeOrderTarget, setChangeOrderTarget] = useState<ProjectChangeOrderTarget | null>(null);
  const [settlementIssueTarget, setSettlementIssueTarget] = useState<SettlementIssueTarget | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [success, setSuccess] = useState<{ amount: number; status: "pending" | "confirmed" | "change_order" } | null>(null);
  const [reminderOperations, setReminderOperations] = useState<OperationsSummary | null>(null);
  const [reminderIntelligence, setReminderIntelligence] = useState<ProductIntelligenceView | null>(null);
  const [reminderRefreshVersion, setReminderRefreshVersion] = useState(0);
  const routeRef = useRef({ page: activeNav, settingsSection, projectRoute, customerRoute });

  useEffect(() => {
    let active = true;
    void Promise.allSettled([
      localPlatformService.operationsSummary(),
      localPlatformService.productIntelligence(),
    ]).then(([operations, intelligence]) => {
      if (!active) return;
      if (operations.status === "fulfilled") setReminderOperations(operations.value);
      if (intelligence.status === "fulfilled") setReminderIntelligence(intelligence.value);
    });
    return () => { active = false; };
  }, [liveSignalVersion, reminderRefreshVersion]);

  useLayoutEffect(() => {
    const scrollingElement = document.scrollingElement;
    if (scrollingElement) scrollingElement.scrollTop = 0;
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }, [activeNav]);

  const changePage = (value: string) => {
    const nextSettingsSection = value === "设置中心" ? "个人资料" : settingsSection;
    if (value === activeNav && nextSettingsSection === settingsSection && projectRoute === null && customerRoute === null) return;
    routeRef.current = { page: value, settingsSection: nextSettingsSection, projectRoute: null, customerRoute: null };
    runPageTransition(() => {
      setActiveNav(value);
      setSettingsSection(nextSettingsSection);
      setProjectRoute(null);
      setCustomerRoute(null);
      setSearch("");
      window.history.replaceState(null, "", value === "首页概览" ? window.location.pathname : `#${encodeURIComponent(value)}`);
    });
  };

  const openSettings = (section: SettingsSectionName) => {
    if (activeNav === "设置中心" && settingsSection === section && projectRoute === null && customerRoute === null) return;
    routeRef.current = { page: "设置中心", settingsSection: section, projectRoute: null, customerRoute: null };
    runPageTransition(() => {
      setActiveNav("设置中心");
      setSettingsSection(section);
      setProjectRoute(null);
      setCustomerRoute(null);
      setSearch("");
      window.history.replaceState(null, "", `#${encodeURIComponent(`设置中心/${section}`)}`);
    });
  };

  const changeProjectRoute = (nextRoute: ProjectPageRoute | null, mode: ProjectRouteMode = "replace") => {
    if (mode === "back" && window.history.state?.xianyuProjectFromList) {
      window.history.back();
      return;
    }
    const resolvedRoute = nextRoute && snapshot.projects.some((project) => project.id === nextRoute.projectId) ? nextRoute : null;
    if (sameProjectRoute(projectRoute, resolvedRoute)) return;
    routeRef.current = { page: "项目管理", settingsSection, projectRoute: resolvedRoute, customerRoute: null };
    runPageTransition(() => {
      setActiveNav("项目管理");
      setProjectRoute(resolvedRoute);
      setCustomerRoute(null);
      setSearch("");
      const nextState = mode === "push"
        ? { ...(window.history.state || {}), xianyuProjectFromList: true }
        : window.history.state;
      const historyMode = mode === "push" ? "pushState" : "replaceState";
      window.history[historyMode](nextState, "", projectRouteHash(resolvedRoute));
    });
  };

  const changeCustomerRoute = (nextRoute: CustomerRequirementRoute | null, mode: ProjectRouteMode = "replace") => {
    if (mode === "back" && window.history.state?.xianyuCustomerFromList) {
      window.history.back();
      return;
    }
    const resolvedRoute = nextRoute && snapshot.customers.some((customer) => customer.id === nextRoute.customerId) ? nextRoute : null;
    if (sameCustomerRoute(customerRoute, resolvedRoute)) return;
    routeRef.current = { page: "客户管理", settingsSection, projectRoute: null, customerRoute: resolvedRoute };
    runPageTransition(() => {
      setActiveNav("客户管理");
      setProjectRoute(null);
      setCustomerRoute(resolvedRoute);
      setSearch("");
      const nextState = mode === "push"
        ? { ...(window.history.state || {}), xianyuCustomerFromList: true }
        : window.history.state;
      const historyMode = mode === "push" ? "pushState" : "replaceState";
      window.history[historyMode](nextState, "", customerRouteHash(resolvedRoute));
    });
  };

  useEffect(() => {
    const syncHash = () => {
      const route = readAppRoute();
      if (route.page === routeRef.current.page && route.settingsSection === routeRef.current.settingsSection && sameProjectRoute(route.projectRoute, routeRef.current.projectRoute) && sameCustomerRoute(route.customerRoute, routeRef.current.customerRoute)) return;
      routeRef.current = route;
      runPageTransition(() => {
        setActiveNav(route.page);
        setSettingsSection(route.settingsSection);
        setProjectRoute(route.projectRoute);
        setCustomerRoute(route.customerRoute);
        setSearch("");
      });
    };
    window.addEventListener("hashchange", syncHash);
    window.addEventListener("popstate", syncHash);
    return () => {
      window.removeEventListener("hashchange", syncHash);
      window.removeEventListener("popstate", syncHash);
    };
  }, []);

  useEffect(() => {
    if (activeNav !== "项目管理" || !projectRoute) return;
    if (!snapshot.projects.some((project) => project.id === projectRoute.projectId)) {
      routeRef.current = { page: "项目管理", settingsSection, projectRoute: null, customerRoute: null };
      setProjectRoute(null);
      window.history.replaceState(null, "", projectRouteHash(null));
      return;
    }
    const expectedHash = projectRouteHash(projectRoute);
    if (window.location.hash !== expectedHash) window.history.replaceState(window.history.state, "", expectedHash);
  }, [activeNav, projectRoute, settingsSection, snapshot.projects]);

  useEffect(() => {
    if (activeNav !== "客户管理" || !customerRoute) return;
    if (!snapshot.customers.some((customer) => customer.id === customerRoute.customerId)) {
      routeRef.current = { page: "客户管理", settingsSection, projectRoute: null, customerRoute: null };
      setCustomerRoute(null);
      window.history.replaceState(null, "", customerRouteHash(null));
      return;
    }
    const expectedHash = customerRouteHash(customerRoute);
    if (window.location.hash !== expectedHash) window.history.replaceState(window.history.state, "", expectedHash);
  }, [activeNav, customerRoute, settingsSection, snapshot.customers]);

  const confirmedPayments = snapshot.payments.filter((payment) => payment.status === "confirmed");
  const todayExpense = snapshot.expenses
    .filter((expense) => isSameLocalDay(expense.paidAt))
    .reduce((sum, expense) => sum + expense.amount, 0);
  const operationDays = diffInDays(snapshot.settings.xianyuStartedAt);
  const businessSummary = getBusinessSummary(snapshot);
  const totalIncome = businessSummary.totalIncome;
  const monthlyIncome = businessSummary.monthlyIncome;
  const todayIncome = businessSummary.todayIncome;
  const unsettledProjects = businessSummary.projectFinancials.filter(
    ({ project, outstanding }) => isClientProject(project) && outstanding > 0,
  );
  const headerReminders = useMemo<HeaderReminder[]>(() => {
    if (snapshot.settings.notificationsEnabled === false) return [];
    return buildHeaderReminders(reminderOperations, reminderIntelligence);
  }, [reminderIntelligence, reminderOperations, snapshot.settings.notificationsEnabled]);

  const normalizedSearch = search.trim().toLowerCase();
  const filteredProjects = normalizedSearch
    ? snapshot.projects.filter((project) => {
        const customer = snapshot.customers.find((item) => item.id === project.customerId);
        return `${project.name} ${customer?.name || ""}`.toLowerCase().includes(normalizedSearch);
      })
    : snapshot.projects;
  const filteredPayments = normalizedSearch
    ? confirmedPayments.filter((payment) => {
        const project = snapshot.projects.find((item) => item.id === payment.projectId);
        const customer = snapshot.customers.find((item) => item.id === payment.customerId);
        return `${project?.name || ""} ${customer?.name || ""}`.toLowerCase().includes(normalizedSearch);
      })
    : confirmedPayments;

  const openHeaderReminder = (reminder: HeaderReminder) => {
    const nextState = {
      ...(window.history.state || {}),
      xianyuReminderTarget: reminder.id,
    };
    routeRef.current = {
      page: reminder.targetPage,
      settingsSection,
      projectRoute: null,
      customerRoute: null,
    };
    runPageTransition(() => {
      setActiveNav(reminder.targetPage);
      setProjectRoute(null);
      setCustomerRoute(null);
      setSearch("");
      const historyMode = window.location.hash === reminder.targetHash ? "replaceState" : "pushState";
      window.history[historyMode](nextState, "", reminder.targetHash);
      window.dispatchEvent(new CustomEvent("xianyu:route-focus"));
    });
  };

  const viewAllReminders = () => {
    changePage("首页概览");
    window.setTimeout(() => {
      document.getElementById("smart-reminders")?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "center",
      });
    }, 260);
  };

  const addPayment = async (value: QuickAccountingFormValue) => {
    const next = await mockLedgerService.addConfirmedPayment(snapshot, value);
    onPersistedSnapshot(next);
    setDrawerOpen(false);
    setDrawerProjectId(null);
    setSuccess({ amount: value.amount, status: value.status || "confirmed" });
    window.setTimeout(() => setSuccess(null), 2700);
  };

  const confirmReceipt = async (value: PaymentConfirmationValue) => {
    const next = await mockLedgerService.confirmPayment(snapshot, value);
    onPersistedSnapshot(next);
    setReceiptTarget(null);
    setSuccess({ amount: value.amount, status: "confirmed" });
    window.setTimeout(() => setSuccess(null), 2700);
  };

  const createProjectChangeOrder = async (value: ProjectChangeOrderValue) => {
    const next = await mockLedgerService.createProjectChangeOrder(snapshot, value);
    onPersistedSnapshot(next);
    setChangeOrderTarget(null);
    setSuccess({ amount: value.amount, status: "change_order" });
    window.setTimeout(() => setSuccess(null), 2700);
  };

  const recordSettlementIssue = async (value: SettlementIssueValue) => {
    const next = await mockLedgerService.recordSettlementIssue(snapshot, value);
    onPersistedSnapshot(next);
    setSettlementIssueTarget(null);
  };

  const refreshReceiptData = async () => {
    onPersistedSnapshot(await mockLedgerService.refreshDashboard());
  };

  const openQuickAccounting = (projectId?: string) => {
    setDrawerProjectId(projectId || null);
    setDrawerOpen(true);
  };

  const metrics = [
    {
      title: "累计净收入（元）",
      value: totalIncome,
      prefix: "¥",
      precision: 2,
      comparison: totalIncome > 0 || businessSummary.totalRefunded > 0 ? <>累计入账 {compactCurrency.format(businessSummary.totalGrossIncome)}{businessSummary.totalRefunded > 0 && <> · 已退款 <b>{compactCurrency.format(businessSummary.totalRefunded)}</b></>}</> : <>等待导入 <b>收入数据</b></>,
      tone: "purple" as const,
      image: "/assets/metrics-v2/income-wallet-3d.png",
      chart: "line" as const,
    },
    {
      title: "实际利润（元）",
      value: businessSummary.actualProfit,
      prefix: "¥",
      precision: 2,
      comparison: totalIncome || businessSummary.totalExpenses ? <>净收入 - 支出 <b>利润率 {totalIncome ? Math.round(businessSummary.actualProfit / totalIncome * 100) : 0}%</b></> : <>等待导入 <b>收支数据</b></>,
      tone: "green" as const,
      image: "/assets/metrics-v2/profit-wallet-3d.png",
      chart: "bar" as const,
    },
    {
      title: "待回款（元）",
      value: businessSummary.outstanding,
      prefix: "¥",
      precision: 2,
      comparison: unsettledProjects.length > 0 ? <>{unsettledProjects.length} 个项目 <b>尚未结清</b></> : <>全部项目 <b>已结清</b></>,
      tone: "blue" as const,
      image: "/assets/metrics-v2/receivable-checklist-3d.png",
      chart: "bar" as const,
    },
    {
      title: "平均小时收益",
      value: businessSummary.averageHourlyIncome,
      prefix: "¥",
      precision: 2,
      comparison: businessSummary.actualHours > 0 ? <>累计投入 <b>{businessSummary.actualHours} 小时</b></> : <>等待导入 <b>工时数据</b></>,
      tone: "indigo" as const,
      image: "/assets/metrics-v2/hourly-clipboard-3d.png",
      chart: "bar" as const,
    },
    {
      title: "进行中项目",
      value: snapshot.projects.filter((project) => project.status === "in_progress").length,
      suffix: "个",
      comparison: <><span>运营第 {operationDays} 天</span><br />{formatDateOnly(snapshot.settings.xianyuStartedAt)} 起</>,
      tone: "orange" as const,
      image: "/assets/metrics-v2/active-project-calendar-3d.png",
    },
  ];

  return (
    <div className="app-shell">
      <Sidebar
        active={activeNav}
        onActiveChange={changePage}
        onQuickAdd={() => openQuickAccounting()}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        projects={snapshot.projects}
      />
      <main className="dashboard-main">
        <TopHeader search={search} onSearch={setSearch} onMenu={() => setSidebarOpen(true)} activePage={activeNav} reminders={headerReminders} onReminderAction={openHeaderReminder} onViewAllReminders={viewAllReminders} onRefreshReminders={() => setReminderRefreshVersion((value) => value + 1)} onOpenSettings={openSettings} profileName={snapshot.settings.profileName || "张同学"} profilePlan={snapshot.settings.accountPlan || "高级版"} />
        <div className="page-route-view" key={`${activeNav}-${settingsSection}-${projectRoute?.projectId || ""}-${customerRoute?.caseId || customerRoute?.customerId || ""}`}>
          {activeNav === "首页概览" && normalizedSearch && (
            <div className="search-status">
              <MagnifyingGlass size={16} />“{search}” 找到 {filteredProjects.length} 个项目、{filteredPayments.length} 笔收款
              <button onClick={() => setSearch("")}>清除</button>
            </div>
          )}
          {activeNav === "首页概览" ? <>
            <section className="metrics-grid" aria-label="经营核心指标">
              {metrics.map((metric, index) => <MetricCard key={metric.title} {...metric} index={index} />)}
            </section>
            <OperatingInsightStrip snapshot={snapshot} onNavigate={changePage} />
            <CustomerPipelineStrip onNavigate={changePage} />
            <ProductStrategyStrip onNavigate={changePage} />
            <section className="main-grid">
              <IncomeTrendCard snapshot={snapshot} />
              <ActiveProjectsCard snapshot={snapshot} projects={filteredProjects} onNavigate={() => changePage("项目管理")} onOpenProject={(projectId) => changeProjectRoute({ projectId, tab: "immersive" }, "push")} />
              <OperationDurationCard startedAt={snapshot.settings.xianyuStartedAt} />
            </section>
            <section className="bottom-grid">
              <PaymentTable payments={filteredPayments} projects={snapshot.projects} customers={snapshot.customers} onNavigate={() => changePage("收入记录")} />
              <div className="bottom-stack center-stack">
                <DailyBalanceCard todayIncome={todayIncome} todayExpense={todayExpense} />
                <ReminderCard reminders={headerReminders} onOpen={openHeaderReminder} />
              </div>
              <div className="bottom-stack right-stack">
                <MonthlyGoalCard current={monthlyIncome} goal={snapshot.settings.monthlyIncomeGoal} onEdit={() => openSettings("记账设置")} />
                <div className="source-countdown-row">
                  <CustomerSourceCard customers={snapshot.customers} onNavigate={() => changePage("客户管理")} />
                  <DeliveryCountdownCard projects={snapshot.projects} onNavigate={() => changePage("项目管理")} />
                </div>
              </div>
            </section>
          </> : <OtherPages page={activeNav as OtherPageName} snapshot={snapshot} onQuickAdd={() => openQuickAccounting()} onCreatePaymentPlan={(projectId) => openQuickAccounting(projectId)} onCreateChangeOrder={(projectId) => setChangeOrderTarget({ projectId })} onConfirmPayment={(projectId, paymentId) => setReceiptTarget({ projectId, paymentId })} onRecordSettlementIssue={(projectId) => setSettlementIssueTarget({ projectId })} onSnapshotChange={onSnapshotChange} onNavigate={changePage} globalSearch={search} initialSettingsSection={settingsSection} projectRoute={projectRoute} onProjectRouteChange={changeProjectRoute} customerRoute={customerRoute} onCustomerRouteChange={changeCustomerRoute} />}
        </div>
      </main>

      <button className={`floating-add ${activeNav === "AI经营助手" ? "is-hidden-on-partner" : ""}`} onClick={() => openQuickAccounting()} aria-label="立即记账">
        <Plus size={24} weight="bold" /><span>立即记账</span>
      </button>

      <QuickAccountingDrawer
        open={drawerOpen}
        projects={snapshot.projects.filter(isClientProject)}
        customers={snapshot.customers}
        settings={snapshot.settings}
        initialProjectId={drawerProjectId}
        onClose={() => { setDrawerOpen(false); setDrawerProjectId(null); }}
        onSubmit={addPayment}
      />

      {receiptTarget && <PaymentConfirmationModal
        snapshot={snapshot}
        target={receiptTarget}
        onClose={() => setReceiptTarget(null)}
        onSubmit={confirmReceipt}
        onRefresh={refreshReceiptData}
      />}

      {changeOrderTarget && <ProjectChangeOrderModal
        snapshot={snapshot}
        target={changeOrderTarget}
        onClose={() => setChangeOrderTarget(null)}
        onSubmit={createProjectChangeOrder}
        onRefresh={refreshReceiptData}
      />}

      {settlementIssueTarget && <SettlementIssueModal
        snapshot={snapshot}
        target={settlementIssueTarget}
        onClose={() => setSettlementIssueTarget(null)}
        onSubmit={recordSettlementIssue}
        onRefresh={refreshReceiptData}
      />}

      {success !== null && (
        <div className="success-toast" role="status">
          <CheckCircle size={28} weight="fill" />
          <span><strong>{compactCurrency.format(success.amount)} {success.status === "change_order" ? "追加订单已保存" : success.status === "confirmed" ? "已确认到账" : "已加入待收计划"}</strong><small>{success.status === "change_order" ? "合同总额与对应收款安排已同步更新" : success.status === "confirmed" ? "核心指标与收款记录已同步更新" : "回款提醒与项目进度已同步更新"}</small></span>
          {[0, 1, 2, 3, 4].map((item) => <Sparkle key={item} className={`success-spark s${item}`} size={14 + item} weight="fill" />)}
        </div>
      )}
    </div>
  );
}

export function App() {
  const [snapshot, setSnapshot] = useState<LedgerSnapshot | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [liveSignalVersion, setLiveSignalVersion] = useState(0);

  const loadDashboard = async () => {
    setLoadError(false);
    try {
      setSnapshot(await mockLedgerService.getDashboard());
    } catch {
      setLoadError(true);
    }
  };

  useEffect(() => {
    if (!("scrollRestoration" in window.history)) return;
    const previous = window.history.scrollRestoration;
    window.history.scrollRestoration = "manual";
    return () => {
      window.history.scrollRestoration = previous;
    };
  }, []);

  useEffect(() => {
    void loadDashboard();
    let disconnect = () => {};
    try {
      disconnect = connectPlatformEvents((event) => {
        if (event.type === "ledger_updated") void loadDashboard();
        setLiveSignalVersion((value) => value + 1);
      });
    } catch {
      // The static Sites build intentionally has no local event service.
    }
    return disconnect;
  }, []);

  if (loadError) {
    return (
      <main className="load-error">
        <WarningCircle size={38} weight="duotone" />
        <h1>经营数据加载失败</h1>
        <p>请检查网络后再试一次。</p>
        <button onClick={() => void loadDashboard()}>重新加载</button>
      </main>
    );
  }

  if (!snapshot) return <LoadingDashboard />;

  const saveSnapshot = async (next: LedgerSnapshot) => {
    setSnapshot(await mockLedgerService.saveSnapshot(next));
  };

  return <DashboardLayout
    snapshot={snapshot}
    onSnapshotChange={(next) => { void saveSnapshot(next); }}
    onPersistedSnapshot={setSnapshot}
    liveSignalVersion={liveSignalVersion}
  />;
}
