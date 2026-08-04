import type {
  Customer,
  LedgerSnapshot,
  Payment,
  Project,
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
  { id: "c1", name: "郑同学", source: "xianyu" },
  { id: "c2", name: "李老板", source: "referral" },
  { id: "c3", name: "王同学", source: "xianyu" },
  { id: "c4", name: "陈同学", source: "wechat" },
  { id: "c5", name: "周女士", source: "other" },
];

const projects: Project[] = [
  {
    id: "p1",
    name: "校园二手交易平台",
    customerId: "c1",
    totalAmount: 4800,
    startDate: dateOnlyAtOffset(-5),
    dueDate: dateOnlyAtOffset(2),
    progress: 70,
    status: "in_progress",
    accent: "blue",
    notes: "完成支付联调与上线检查",
  },
  {
    id: "p2",
    name: "餐饮点餐小程序",
    customerId: "c2",
    totalAmount: 3600,
    startDate: dateOnlyAtOffset(-4),
    dueDate: dateOnlyAtOffset(6),
    progress: 40,
    status: "in_progress",
    accent: "green",
  },
  {
    id: "p3",
    name: "数据可视化后台",
    customerId: "c3",
    totalAmount: 2800,
    startDate: dateOnlyAtOffset(-4),
    dueDate: dateOnlyAtOffset(1),
    progress: 90,
    status: "in_progress",
    accent: "purple",
  },
  {
    id: "p4",
    name: "个人博客系统开发",
    customerId: "c4",
    totalAmount: 1680,
    startDate: dateOnlyAtOffset(-12),
    dueDate: dateOnlyAtOffset(-2),
    progress: 100,
    status: "completed",
    accent: "orange",
  },
  {
    id: "p5",
    name: "品牌官网视觉升级",
    customerId: "c5",
    totalAmount: 2100,
    startDate: dateOnlyAtOffset(-2),
    dueDate: dateOnlyAtOffset(10),
    progress: 20,
    status: "in_progress",
    accent: "blue",
  },
];

const payments: Payment[] = [
  {
    id: "pay1",
    projectId: "p1",
    customerId: "c1",
    amount: 860,
    type: "deposit",
    status: "confirmed",
    paidAt: dateAtOffset(0, 14, 30),
    notes: "定金",
  },
  {
    id: "pay2",
    projectId: "p2",
    customerId: "c2",
    amount: 1680,
    type: "final",
    status: "confirmed",
    paidAt: dateAtOffset(-1, 10, 20),
    notes: "尾款",
  },
  {
    id: "pay3",
    projectId: "p3",
    customerId: "c3",
    amount: 1200,
    type: "full",
    status: "confirmed",
    paidAt: dateAtOffset(-2, 16, 45),
    notes: "全款",
  },
  {
    id: "pay4",
    projectId: "p4",
    customerId: "c4",
    amount: 960,
    type: "deposit",
    status: "confirmed",
    paidAt: dateAtOffset(-3, 11, 12),
    notes: "定金",
  },
  {
    id: "pay5",
    projectId: "p5",
    customerId: "c5",
    amount: 980,
    type: "milestone",
    status: "confirmed",
    paidAt: dateAtOffset(-2, 9, 16),
    notes: "阶段款",
  },
  {
    id: "pay6",
    projectId: "p1",
    customerId: "c1",
    amount: 3400,
    type: "milestone",
    status: "confirmed",
    paidAt: dateAtOffset(-34, 15, 6),
    notes: "阶段款",
  },
  {
    id: "pay7",
    projectId: "p2",
    customerId: "c2",
    amount: 3780,
    type: "full",
    status: "confirmed",
    paidAt: dateAtOffset(-48, 12, 50),
    notes: "全款",
  },
];

const initialSnapshot: LedgerSnapshot = {
  projects,
  payments,
  customers,
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
