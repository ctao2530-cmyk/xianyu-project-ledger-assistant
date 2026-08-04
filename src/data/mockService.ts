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
    return isLedgerSnapshot(parsed) ? cloneSnapshot(parsed) : cloneSnapshot();
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

    persistSnapshot(next);
    return next;
  },
};
