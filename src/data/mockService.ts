import type {
  Customer,
  Expense,
  LedgerSnapshot,
  Payment,
  Project,
  ProjectAttachment,
  ProjectLog,
  ProjectTask,
  QuickAccountingFormValue,
} from "../types";

const dateAtOffset = (days: number, hour = 10, minute = 20) => {
  const date = new Date();
  date.setHours(hour, minute, 0, 0);
  date.setDate(date.getDate() + days);
  return date.toISOString();
};

const dateOnlyAtOffset = (days: number) => dateAtOffset(days).slice(0, 10);

const customers: Customer[] = [
  { id: "c1", name: "郑同学", source: "xianyu", phone: "138****6273", followUpStatus: "won", lastContactAt: dateAtOffset(-1), level: "A", tags: ["老客户", "高校"] },
  { id: "c2", name: "李老板", source: "referral", phone: "139****8812", followUpStatus: "proposal", lastContactAt: dateAtOffset(0, 9, 40), level: "A", tags: ["高意向", "餐饮"] },
  { id: "c3", name: "王同学", source: "xianyu", phone: "137****7745", followUpStatus: "contacted", lastContactAt: dateAtOffset(-2), level: "B", tags: ["数据", "复购潜力"] },
  { id: "c4", name: "陈同学", source: "wechat", phone: "136****5599", followUpStatus: "won", lastContactAt: dateAtOffset(-6), level: "B", tags: ["个人开发者"] },
  { id: "c5", name: "周女士", source: "other", phone: "158****1230", followUpStatus: "new", lastContactAt: dateAtOffset(-3), level: "C", tags: ["品牌升级"] },
];

const projects: Project[] = [
  {
    id: "p1",
    name: "校园二手交易平台",
    customerId: "c1",
    totalAmount: 24000,
    startDate: dateOnlyAtOffset(-5),
    dueDate: dateOnlyAtOffset(2),
    progress: 70,
    status: "in_progress",
    accent: "blue",
    notes: "完成支付联调与上线检查",
    type: "Web 全栈开发",
    estimatedHours: 96,
  },
  {
    id: "p2",
    name: "餐饮点餐小程序",
    customerId: "c2",
    totalAmount: 16800,
    startDate: dateOnlyAtOffset(-4),
    dueDate: dateOnlyAtOffset(6),
    progress: 40,
    status: "in_progress",
    accent: "green",
    type: "微信小程序",
    estimatedHours: 72,
  },
  {
    id: "p3",
    name: "数据可视化后台",
    customerId: "c3",
    totalAmount: 12000,
    startDate: dateOnlyAtOffset(-4),
    dueDate: dateOnlyAtOffset(1),
    progress: 90,
    status: "in_progress",
    accent: "purple",
    type: "数据可视化",
    estimatedHours: 54,
  },
  {
    id: "p4",
    name: "个人博客系统开发",
    customerId: "c4",
    totalAmount: 9600,
    startDate: dateOnlyAtOffset(-12),
    dueDate: dateOnlyAtOffset(-2),
    progress: 100,
    status: "completed",
    accent: "orange",
    type: "内容型网站",
    estimatedHours: 42,
  },
  {
    id: "p5",
    name: "品牌官网视觉升级",
    customerId: "c5",
    totalAmount: 8800,
    startDate: dateOnlyAtOffset(-2),
    dueDate: dateOnlyAtOffset(10),
    progress: 20,
    status: "in_progress",
    accent: "blue",
    type: "品牌官网",
    estimatedHours: 48,
  },
];

const payments: Payment[] = [
  {
    id: "pay1",
    projectId: "p1",
    customerId: "c1",
    amount: 4800,
    type: "deposit",
    status: "confirmed",
    paidAt: dateAtOffset(0, 14, 30),
    dueAt: dateOnlyAtOffset(-5),
    notes: "定金",
  },
  {
    id: "pay2",
    projectId: "p2",
    customerId: "c2",
    amount: 5000,
    type: "deposit",
    status: "confirmed",
    paidAt: dateAtOffset(-1, 10, 20),
    dueAt: dateOnlyAtOffset(-4),
    notes: "启动定金",
  },
  {
    id: "pay3",
    projectId: "p3",
    customerId: "c3",
    amount: 4800,
    type: "milestone",
    status: "confirmed",
    paidAt: dateAtOffset(-2, 16, 45),
    dueAt: dateOnlyAtOffset(-2),
    notes: "设计确认阶段款",
  },
  {
    id: "pay4",
    projectId: "p4",
    customerId: "c4",
    amount: 9600,
    type: "full",
    status: "confirmed",
    paidAt: dateAtOffset(-3, 11, 12),
    dueAt: dateOnlyAtOffset(-12),
    notes: "全款结清",
  },
  {
    id: "pay5",
    projectId: "p5",
    customerId: "c5",
    amount: 2640,
    type: "deposit",
    status: "confirmed",
    paidAt: dateAtOffset(-2, 9, 16),
    dueAt: dateOnlyAtOffset(-2),
    notes: "启动定金",
  },
  {
    id: "pay6",
    projectId: "p1",
    customerId: "c1",
    amount: 7200,
    type: "milestone",
    status: "confirmed",
    paidAt: dateAtOffset(-34, 15, 6),
    dueAt: dateOnlyAtOffset(-1),
    notes: "阶段款",
  },
  {
    id: "pay7",
    projectId: "p1",
    customerId: "c1",
    amount: 7200,
    type: "milestone",
    status: "pending",
    paidAt: dateAtOffset(1, 12, 0),
    dueAt: dateOnlyAtOffset(1),
    notes: "功能验收后收取",
  },
  {
    id: "pay8",
    projectId: "p1",
    customerId: "c1",
    amount: 4800,
    type: "final",
    status: "pending",
    paidAt: dateAtOffset(2, 18, 0),
    dueAt: dateOnlyAtOffset(2),
    notes: "上线交付尾款",
  },
  {
    id: "pay9",
    projectId: "p2",
    customerId: "c2",
    amount: 6800,
    type: "milestone",
    status: "pending",
    paidAt: dateAtOffset(3, 18, 0),
    dueAt: dateOnlyAtOffset(3),
    notes: "功能开发阶段款",
  },
  {
    id: "pay10",
    projectId: "p2",
    customerId: "c2",
    amount: 5000,
    type: "final",
    status: "pending",
    paidAt: dateAtOffset(6, 18, 0),
    dueAt: dateOnlyAtOffset(6),
    notes: "验收尾款",
  },
  {
    id: "pay11",
    projectId: "p3",
    customerId: "c3",
    amount: 7200,
    type: "final",
    status: "pending",
    paidAt: dateAtOffset(1, 18, 0),
    dueAt: dateOnlyAtOffset(1),
    notes: "交付尾款",
  },
  {
    id: "pay12",
    projectId: "p5",
    customerId: "c5",
    amount: 3520,
    type: "milestone",
    status: "pending",
    paidAt: dateAtOffset(5, 18, 0),
    dueAt: dateOnlyAtOffset(5),
    notes: "视觉定稿阶段款",
  },
  {
    id: "pay13",
    projectId: "p5",
    customerId: "c5",
    amount: 2640,
    type: "final",
    status: "pending",
    paidAt: dateAtOffset(10, 18, 0),
    dueAt: dateOnlyAtOffset(10),
    notes: "上线尾款",
  },
];

const expenses: Expense[] = [
  { id: "e1", projectId: "p1", name: "UI 组件授权", category: "software", amount: 680, paidAt: dateAtOffset(-4), notes: "项目专用组件库" },
  { id: "e2", projectId: "p1", name: "服务器与域名", category: "server", amount: 520, paidAt: dateAtOffset(-3) },
  { id: "e3", projectId: "p2", name: "小程序视觉外包", category: "outsourcing", amount: 2400, paidAt: dateAtOffset(-3) },
  { id: "e4", projectId: "p3", name: "图表组件授权", category: "software", amount: 860, paidAt: dateAtOffset(-2) },
  { id: "e5", projectId: "p4", name: "云服务器", category: "server", amount: 360, paidAt: dateAtOffset(-8) },
  { id: "e6", projectId: "p5", name: "品牌字体授权", category: "software", amount: 420, paidAt: dateAtOffset(-1) },
  { id: "e7", name: "开发工具订阅", category: "software", amount: 399, paidAt: dateAtOffset(-6), notes: "经营公共成本" },
];

const tasks: ProjectTask[] = [
  { id: "t1", projectId: "p1", title: "需求梳理与数据模型", status: "done", startDate: dateOnlyAtOffset(-5), dueDate: dateOnlyAtOffset(-4), estimatedHours: 12, actualHours: 11 },
  { id: "t2", projectId: "p1", title: "核心交易流程开发", status: "done", startDate: dateOnlyAtOffset(-4), dueDate: dateOnlyAtOffset(-1), estimatedHours: 36, actualHours: 39 },
  { id: "t3", projectId: "p1", title: "支付联调与异常处理", status: "in_progress", startDate: dateOnlyAtOffset(-1), dueDate: dateOnlyAtOffset(1), estimatedHours: 20, actualHours: 12 },
  { id: "t4", projectId: "p1", title: "上线验收与交付", status: "todo", startDate: dateOnlyAtOffset(1), dueDate: dateOnlyAtOffset(2), estimatedHours: 12, actualHours: 0 },
  { id: "t5", projectId: "p2", title: "菜单与购物车开发", status: "in_progress", startDate: dateOnlyAtOffset(-2), dueDate: dateOnlyAtOffset(2), estimatedHours: 30, actualHours: 17 },
  { id: "t6", projectId: "p2", title: "门店后台联调", status: "todo", startDate: dateOnlyAtOffset(2), dueDate: dateOnlyAtOffset(6), estimatedHours: 26, actualHours: 0 },
  { id: "t7", projectId: "p3", title: "可视化图表开发", status: "in_progress", startDate: dateOnlyAtOffset(-3), dueDate: dateOnlyAtOffset(1), estimatedHours: 38, actualHours: 34 },
  { id: "t8", projectId: "p4", title: "内容迁移与上线", status: "done", startDate: dateOnlyAtOffset(-8), dueDate: dateOnlyAtOffset(-2), estimatedHours: 38, actualHours: 36 },
  { id: "t9", projectId: "p5", title: "品牌视觉方向探索", status: "in_progress", startDate: dateOnlyAtOffset(-2), dueDate: dateOnlyAtOffset(3), estimatedHours: 22, actualHours: 9 },
];

const logs: ProjectLog[] = [
  { id: "l1", projectId: "p1", createdAt: dateAtOffset(0, 18, 20), content: "完成支付回调幂等处理，补充超时订单恢复流程。", hours: 4.5, category: "development" },
  { id: "l2", projectId: "p1", createdAt: dateAtOffset(-1, 19, 10), content: "与客户确认验收范围，冻结本期新增需求。", hours: 1, category: "communication" },
  { id: "l3", projectId: "p1", createdAt: dateAtOffset(-2, 20, 15), content: "完成商品发布、搜索与收藏模块联调。", hours: 6, category: "development" },
  { id: "l4", projectId: "p2", createdAt: dateAtOffset(-1, 18, 40), content: "购物车交互完成，待接入门店优惠规则。", hours: 5.5, category: "development" },
];

const attachments: ProjectAttachment[] = [
  { id: "a1", projectId: "p1", name: "需求确认书-v3.pdf", size: "1.8 MB", type: "document", uploadedAt: dateAtOffset(-4) },
  { id: "a2", projectId: "p1", name: "交易流程原型.fig", size: "8.6 MB", type: "design", uploadedAt: dateAtOffset(-3) },
  { id: "a3", projectId: "p1", name: "上线交付清单.zip", size: "12.4 MB", type: "archive", uploadedAt: dateAtOffset(0) },
  { id: "a4", projectId: "p2", name: "小程序视觉稿.fig", size: "6.2 MB", type: "design", uploadedAt: dateAtOffset(-2) },
];

const initialSnapshot: LedgerSnapshot = {
  projects,
  payments,
  expenses,
  customers,
  tasks,
  logs,
  attachments,
  settings: {
    xianyuStartedAt: dateOnlyAtOffset(-68),
    monthlyIncomeGoal: 12000,
  },
  completedOrderCount: 26,
};

const cloneSnapshot = (): LedgerSnapshot =>
  JSON.parse(JSON.stringify(initialSnapshot)) as LedgerSnapshot;

export const mockLedgerService = {
  async getDashboard(): Promise<LedgerSnapshot> {
    await new Promise((resolve) => window.setTimeout(resolve, 520));
    return cloneSnapshot();
  },

  async addConfirmedPayment(
    snapshot: LedgerSnapshot,
    value: QuickAccountingFormValue,
  ): Promise<LedgerSnapshot> {
    await new Promise((resolve) => window.setTimeout(resolve, 620));

    const next = JSON.parse(JSON.stringify(snapshot)) as LedgerSnapshot;
    let customer = next.customers.find(
      (item) => item.name.trim() === value.customerName.trim(),
    );

    if (!customer) {
      customer = {
        id: `c-${Date.now()}`,
        name: value.customerName.trim(),
        source: "xianyu",
        phone: "待补充",
        followUpStatus: "won",
        lastContactAt: new Date().toISOString(),
        level: "C",
        tags: ["新客户"],
      };
      next.customers.unshift(customer);
    }

    let project = next.projects.find(
      (item) => item.name.trim() === value.projectName.trim(),
    );

    if (!project) {
      const start = new Date(value.paidAt);
      const due = new Date(start);
      due.setDate(due.getDate() + value.durationDays);
      project = {
        id: `p-${Date.now()}`,
        name: value.projectName.trim(),
        customerId: customer.id,
        totalAmount: value.amount,
        startDate: start.toISOString().slice(0, 10),
        dueDate: due.toISOString().slice(0, 10),
        progress: value.type === "full" ? 100 : 12,
        status: value.type === "full" ? "completed" : "in_progress",
        accent: "blue",
        notes: value.notes,
        type: "定制开发",
        estimatedHours: value.durationDays * 5,
      };
      next.projects.unshift(project);
    }

    next.payments.unshift({
      id: `pay-${Date.now()}`,
      projectId: project.id,
      customerId: customer.id,
      amount: value.amount,
      type: value.type,
      status: "confirmed",
      paidAt: new Date(value.paidAt).toISOString(),
      dueAt: new Date(value.paidAt).toISOString().slice(0, 10),
      notes: value.notes || "已确认到账",
    });

    if (value.type === "full" && project.status !== "completed") {
      project.status = "completed";
      project.progress = 100;
      next.completedOrderCount += 1;
    }

    return next;
  },
};
