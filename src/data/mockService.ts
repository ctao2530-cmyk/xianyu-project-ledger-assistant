import type {
  LedgerSnapshot,
  QuickAccountingFormValue,
} from "../types";

const STORAGE_KEY = "xianyu-ledger-snapshot-v1";

const initialSnapshot: LedgerSnapshot = {
  projects: [],
  payments: [],
  expenses: [],
  customers: [],
  tasks: [],
  logs: [],
  attachments: [],
  settings: {
    xianyuStartedAt: "2026-05-28",
    monthlyIncomeGoal: 0,
    profileName: "张同学",
    profileRole: "个人开发者",
    profilePhone: "",
    profileBio: "专注把每个接单项目做成可复用的长期能力。",
    accountEmail: "",
    accountPlan: "高级版",
    defaultDurationDays: 30,
    defaultPaymentType: "full",
    reminderDays: 3,
    decimalPlaces: 2,
    notificationsEnabled: true,
    paymentRemindersEnabled: true,
    goalRemindersEnabled: true,
    autoBackupEnabled: true,
    backupTime: "23:30",
    themeColor: "#6544f4",
    colorMode: "light",
  },
  completedOrderCount: 0,
};

const cloneSnapshot = (snapshot = initialSnapshot): LedgerSnapshot =>
  JSON.parse(JSON.stringify(snapshot)) as LedgerSnapshot;

const isLedgerSnapshot = (value: unknown): value is LedgerSnapshot => {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<LedgerSnapshot>;
  return [
    candidate.projects,
    candidate.payments,
    candidate.expenses,
    candidate.customers,
    candidate.tasks,
    candidate.logs,
    candidate.attachments,
  ].every(Array.isArray) && Boolean(candidate.settings?.xianyuStartedAt);
};

const readStoredSnapshot = () => {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) return cloneSnapshot();
    const parsed = JSON.parse(stored) as unknown;
    if (!isLedgerSnapshot(parsed)) return cloneSnapshot();
    const snapshot = cloneSnapshot(parsed);
    snapshot.settings = { ...initialSnapshot.settings, ...snapshot.settings };
    return snapshot;
  } catch {
    return cloneSnapshot();
  }
};

const persistSnapshot = (snapshot: LedgerSnapshot) => {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
  } catch {
    // Storage may be unavailable in privacy mode; the current session still works.
  }
};

export const mockLedgerService = {
  async getDashboard(): Promise<LedgerSnapshot> {
    await new Promise((resolve) => window.setTimeout(resolve, 320));
    return readStoredSnapshot();
  },

  async addConfirmedPayment(
    snapshot: LedgerSnapshot,
    value: QuickAccountingFormValue,
  ): Promise<LedgerSnapshot> {
    await new Promise((resolve) => window.setTimeout(resolve, 420));

    const next = cloneSnapshot(snapshot);
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

    if (project) {
      const linkedCustomer = next.customers.find((item) => item.id === project?.customerId);
      if (linkedCustomer) customer = linkedCustomer;
      const plannedTotal = next.payments
        .filter((item) => item.projectId === project?.id && item.status !== "refunded")
        .reduce((sum, item) => sum + item.amount, 0) + value.amount;
      project.totalAmount = Math.max(project.totalAmount, value.contractTotal || 0, plannedTotal);
    }

    if (!project) {
      const start = new Date(value.paidAt);
      const due = new Date(start);
      due.setDate(due.getDate() + value.durationDays);
      project = {
        id: `p-${Date.now()}`,
        name: value.projectName.trim(),
        customerId: customer.id,
        totalAmount: Math.max(value.amount, value.contractTotal || value.amount),
        startDate: start.toISOString().slice(0, 10),
        dueDate: due.toISOString().slice(0, 10),
        progress: value.type === "full" && value.status !== "pending" ? 100 : 12,
        status: value.type === "full" && value.status !== "pending" ? "completed" : "in_progress",
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
      status: value.status || "confirmed",
      paidAt: new Date(value.paidAt).toISOString(),
      dueAt: value.dueAt || new Date(value.paidAt).toISOString().slice(0, 10),
      notes: value.notes || (value.status === "pending" ? "待收款" : "已确认到账"),
    });

    if (value.type === "full" && value.status !== "pending" && project.status !== "completed") {
      project.status = "completed";
      project.progress = 100;
      next.completedOrderCount += 1;
    }

    persistSnapshot(next);
    return next;
  },

  async saveSnapshot(snapshot: LedgerSnapshot): Promise<LedgerSnapshot> {
    const next = cloneSnapshot(snapshot);
    persistSnapshot(next);
    return next;
  },
};
