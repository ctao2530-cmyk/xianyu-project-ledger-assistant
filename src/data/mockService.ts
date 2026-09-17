import type {
  LedgerSnapshot,
  CustomerRelationPreview,
  CustomerUpdateValue,
  PaymentConfirmationValue,
  ProjectChangeOrderValue,
  ProjectProductPreview,
  QuickAccountingFormValue,
  SettlementIssueValue,
} from "../types";
import { isClientProject, projectKindOf } from "./projectKinds";

export const LEGACY_STORAGE_KEY = "xianyu-ledger-snapshot-v1";
let backendRevision: number | null = null;
let backendConnected = false;

export class LedgerRevisionConflictError extends Error {
  revision: number | null;

  constructor(message: string, revision: number | null = null) {
    super(message);
    this.name = "LedgerRevisionConflictError";
    this.revision = revision;
  }
}

export class LedgerBackendRequiredError extends Error {
  constructor(message = "确认到账需要连接本机经营服务，离线状态不会写入收款数据") {
    super(message);
    this.name = "LedgerBackendRequiredError";
  }
}

const initialSnapshot: LedgerSnapshot = {
  projects: [],
  changeOrders: [],
  payments: [],
  settlementIssues: [],
  expenses: [],
  customers: [],
  tasks: [],
  logs: [],
  attachments: [],
  settings: {
    xianyuStartedAt: "2026-05-28",
    monthlyIncomeGoal: 0,
    profileName: "",
    profileRole: "个人开发者",
    profilePhone: "",
    profileBio: "专注把每个接单项目做成可复用的长期能力。",
    accountEmail: "",
    accountPlan: "",
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

const cloneSnapshot = (snapshot = initialSnapshot): LedgerSnapshot => {
  const cloned = JSON.parse(JSON.stringify(snapshot)) as LedgerSnapshot;
  cloned.changeOrders = Array.isArray(cloned.changeOrders) ? cloned.changeOrders : [];
  cloned.settlementIssues = Array.isArray(cloned.settlementIssues) ? cloned.settlementIssues : [];
  cloned.projects = cloned.projects.map((project) => ({
    ...project,
    projectKind: projectKindOf(project),
  }));
  return cloned;
};

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
    const stored = window.localStorage.getItem(LEGACY_STORAGE_KEY);
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
    window.localStorage.setItem(LEGACY_STORAGE_KEY, JSON.stringify(snapshot));
  } catch {
    // Storage may be unavailable in privacy mode; the current session still works.
  }
};

const readBackendSnapshot = async (): Promise<LedgerSnapshot> => {
  const response = await fetch("/api/ledger/snapshot", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = await response.json() as { revision: number; snapshot: LedgerSnapshot };
  backendRevision = payload.revision;
  backendConnected = true;
  return cloneSnapshot(payload.snapshot);
};

const responseMessage = async (response: Response, fallback: string) => {
  const body = await response.json().catch(() => null) as {
    detail?: string | { message?: string; revision?: number };
  } | null;
  const detail = body?.detail;
  return {
    message: typeof detail === "string" ? detail : detail?.message || fallback,
    revision: typeof detail === "object" && typeof detail?.revision === "number" ? detail.revision : null,
  };
};

export const mockLedgerService = {
  async getDashboard(): Promise<LedgerSnapshot> {
    try {
      return await readBackendSnapshot();
    } catch {
      backendRevision = null;
      backendConnected = false;
      return readStoredSnapshot();
    }
  },

  async refreshDashboard(): Promise<LedgerSnapshot> {
    try {
      return await readBackendSnapshot();
    } catch {
      backendRevision = null;
      backendConnected = false;
      throw new LedgerBackendRequiredError("无法刷新本机经营数据，请确认 8877 服务已经连接");
    }
  },

  async updateCustomer(
    customerId: string,
    value: CustomerUpdateValue,
  ): Promise<LedgerSnapshot> {
    if (!backendConnected || backendRevision === null) {
      throw new LedgerBackendRequiredError("编辑客户需要连接本机经营服务，离线状态不会写入客户资料");
    }
    let response: Response;
    try {
      response = await fetch(`/api/ledger/customers/${encodeURIComponent(customerId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: value.requestId,
          expected_revision: backendRevision,
          name: value.name,
          source: value.source,
          phone: value.phone,
          follow_up_status: value.followUpStatus,
          last_contact_at: value.lastContactAt,
          level: value.level,
          tags: value.tags,
          current_need: value.currentNeed,
          price_type: value.priceType,
          price_amount: value.priceAmount,
          next_action: value.nextAction,
          notes: value.notes,
        }),
      });
    } catch {
      throw new LedgerBackendRequiredError("本机经营服务暂时无法连接，本次客户编辑没有写入");
    }
    if (response.status === 409) {
      const detail = await responseMessage(response, "经营数据已经变化，请刷新后重新编辑客户");
      throw new LedgerRevisionConflictError(detail.message, detail.revision);
    }
    if (!response.ok) {
      const detail = await responseMessage(response, `客户编辑失败（${response.status}）`);
      throw new Error(detail.message);
    }
    const payload = await response.json() as { revision: number; snapshot: LedgerSnapshot };
    backendRevision = payload.revision;
    backendConnected = true;
    return cloneSnapshot(payload.snapshot);
  },

  async previewCustomerRelation(
    projectId: string,
    currentCustomerId: string,
    targetCustomerId: string,
  ): Promise<CustomerRelationPreview> {
    if (!backendConnected || backendRevision === null) {
      throw new LedgerBackendRequiredError("关系影响预览需要连接本机经营服务，离线状态不会执行修正");
    }
    let response: Response;
    try {
      response = await fetch("/api/ledger/customer-relations/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: backendRevision,
          project_id: projectId,
          current_customer_id: currentCustomerId,
          target_customer_id: targetCustomerId,
        }),
      });
    } catch {
      throw new LedgerBackendRequiredError("本机经营服务暂时无法连接，无法预览关系影响");
    }
    if (response.status === 409) {
      const detail = await responseMessage(response, "经营数据已经变化，请刷新后重新预览关系影响");
      throw new LedgerRevisionConflictError(detail.message, detail.revision);
    }
    if (!response.ok) {
      const detail = await responseMessage(response, `关系影响预览失败（${response.status}）`);
      throw new Error(detail.message);
    }
    return response.json() as Promise<CustomerRelationPreview>;
  },

  async rebindCustomerRelation(
    preview: CustomerRelationPreview,
    requestId: string,
  ): Promise<LedgerSnapshot> {
    if (!backendConnected || backendRevision === null) {
      throw new LedgerBackendRequiredError("确认关系修正需要连接本机经营服务，离线状态不会修改订单归属");
    }
    let response: Response;
    try {
      response = await fetch("/api/ledger/customer-relations/rebind", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: requestId,
          expected_revision: preview.revision,
          preview_token: preview.preview_token,
          project_id: preview.project_id,
          current_customer_id: preview.current_customer_id,
          target_customer_id: preview.target_customer_id,
        }),
      });
    } catch {
      throw new LedgerBackendRequiredError("本机经营服务暂时无法连接，本次关系修正没有执行");
    }
    if (response.status === 409) {
      const detail = await responseMessage(response, "关系预览已经失效，请刷新后重新确认");
      throw new LedgerRevisionConflictError(detail.message, detail.revision);
    }
    if (!response.ok) {
      const detail = await responseMessage(response, `关系修正失败（${response.status}）`);
      throw new Error(detail.message);
    }
    const payload = await response.json() as { revision: number; snapshot: LedgerSnapshot };
    backendRevision = payload.revision;
    backendConnected = true;
    return cloneSnapshot(payload.snapshot);
  },

  async previewProjectProduct(
    projectId: string,
    targetItemExternalId: string | null,
  ): Promise<ProjectProductPreview> {
    if (!backendConnected || backendRevision === null) {
      throw new LedgerBackendRequiredError("利润归属预览需要连接本机经营服务");
    }
    let response: Response;
    try {
      response = await fetch("/api/ledger/project-products/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: backendRevision,
          project_id: projectId,
          target_item_external_id: targetItemExternalId,
        }),
      });
    } catch {
      throw new LedgerBackendRequiredError("本机经营服务暂时无法连接，无法预览利润归属");
    }
    if (response.status === 409) {
      const detail = await responseMessage(response, "经营数据已经变化，请刷新后重新预览利润归属");
      throw new LedgerRevisionConflictError(detail.message, detail.revision);
    }
    if (!response.ok) {
      const detail = await responseMessage(response, `利润归属预览失败（${response.status}）`);
      throw new Error(detail.message);
    }
    return response.json() as Promise<ProjectProductPreview>;
  },

  async commitProjectProduct(
    preview: ProjectProductPreview,
    requestId: string,
  ): Promise<LedgerSnapshot> {
    if (!backendConnected || backendRevision === null) {
      throw new LedgerBackendRequiredError("确认利润归属需要连接本机经营服务");
    }
    let response: Response;
    try {
      response = await fetch("/api/ledger/project-products/commit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: requestId,
          expected_revision: preview.revision,
          preview_token: preview.preview_token,
          project_id: preview.project_id,
          target_item_external_id: preview.target_item_external_id,
        }),
      });
    } catch {
      throw new LedgerBackendRequiredError("本机经营服务暂时无法连接，本次利润归属没有修改");
    }
    if (response.status === 409) {
      const detail = await responseMessage(response, "利润归属预览已经失效，请刷新后重试");
      throw new LedgerRevisionConflictError(detail.message, detail.revision);
    }
    if (!response.ok) {
      const detail = await responseMessage(response, `利润归属修改失败（${response.status}）`);
      throw new Error(detail.message);
    }
    const payload = await response.json() as { revision: number; snapshot: LedgerSnapshot };
    backendRevision = payload.revision;
    backendConnected = true;
    return cloneSnapshot(payload.snapshot);
  },

  async createProjectChangeOrder(
    _snapshot: LedgerSnapshot,
    value: ProjectChangeOrderValue,
  ): Promise<LedgerSnapshot> {
    if (!backendConnected || backendRevision === null) {
      throw new LedgerBackendRequiredError("新增追加订单需要连接本机经营服务，离线状态不会修改合同或收款数据");
    }
    let response: Response;
    try {
      response = await fetch("/api/ledger/change-orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: value.requestId,
          expected_revision: backendRevision,
          project_id: value.projectId,
          title: value.title,
          amount: value.amount,
          confirmed_at: value.confirmedAt,
          notes: value.notes || "",
          payment_plan: value.paymentPlan.map((item) => ({
            amount: item.amount,
            type: item.type,
            status: item.status,
            paid_at: item.paidAt ? new Date(item.paidAt).toISOString() : null,
            due_at: item.dueAt || null,
            notes: item.notes || "",
          })),
        }),
      });
    } catch {
      throw new LedgerBackendRequiredError("本机经营服务暂时无法连接，本次追加订单没有写入，请稍后重试");
    }
    if (response.status === 409) {
      const detail = await responseMessage(response, "经营数据已在其他浏览器更新，请刷新后重新新增追加订单");
      throw new LedgerRevisionConflictError(detail.message, detail.revision);
    }
    if (!response.ok) {
      const detail = await responseMessage(response, `追加订单保存失败（${response.status}）`);
      throw new Error(detail.message);
    }
    const payload = await response.json() as {
      revision: number;
      snapshot: LedgerSnapshot;
    };
    backendRevision = payload.revision;
    backendConnected = true;
    return cloneSnapshot(payload.snapshot);
  },

  async confirmPayment(
    _snapshot: LedgerSnapshot,
    value: PaymentConfirmationValue,
  ): Promise<LedgerSnapshot> {
    if (!backendConnected || backendRevision === null) {
      throw new LedgerBackendRequiredError();
    }
    let response: Response;
    try {
      response = await fetch("/api/ledger/payments/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: value.requestId,
          expected_revision: backendRevision,
          project_id: value.projectId,
          payment_id: value.paymentId || null,
          amount: value.amount,
          paid_at: new Date(value.paidAt).toISOString(),
          type: value.type,
          notes: value.notes || "",
        }),
      });
    } catch {
      throw new LedgerBackendRequiredError("本机经营服务暂时无法连接，本次到账没有写入，请稍后重试");
    }
    if (response.status === 409) {
      const detail = await responseMessage(response, "经营数据已在其他浏览器更新，请刷新后重新确认");
      throw new LedgerRevisionConflictError(detail.message, detail.revision);
    }
    if (!response.ok) {
      const detail = await responseMessage(response, `到账确认失败（${response.status}）`);
      throw new Error(detail.message);
    }
    const payload = await response.json() as {
      revision: number;
      snapshot: LedgerSnapshot;
    };
    backendRevision = payload.revision;
    backendConnected = true;
    return cloneSnapshot(payload.snapshot);
  },

  async recordSettlementIssue(
    _snapshot: LedgerSnapshot,
    value: SettlementIssueValue,
  ): Promise<LedgerSnapshot> {
    if (!backendConnected || backendRevision === null) {
      throw new LedgerBackendRequiredError("记录项目异常需要连接本机经营服务，离线状态不会写入财务数据");
    }
    let response: Response;
    try {
      response = await fetch("/api/ledger/settlement-issues", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: value.requestId,
          expected_revision: backendRevision,
          project_id: value.projectId,
          type: value.type,
          receivable_impact: value.receivableImpact,
          refund_amount: value.refundAmount,
          occurred_at: new Date(value.occurredAt).toISOString(),
          reason: value.reason,
          notes: value.notes || "",
        }),
      });
    } catch {
      throw new LedgerBackendRequiredError("本机经营服务暂时无法连接，本次异常没有写入，请稍后重试");
    }
    if (response.status === 409) {
      const detail = await responseMessage(response, "经营数据已在其他浏览器更新，请刷新后重新记录异常");
      throw new LedgerRevisionConflictError(detail.message, detail.revision);
    }
    if (!response.ok) {
      const detail = await responseMessage(response, `项目异常保存失败（${response.status}）`);
      throw new Error(detail.message);
    }
    const payload = await response.json() as {
      revision: number;
      snapshot: LedgerSnapshot;
    };
    backendRevision = payload.revision;
    backendConnected = true;
    return cloneSnapshot(payload.snapshot);
  },

  async addConfirmedPayment(
    snapshot: LedgerSnapshot,
    value: QuickAccountingFormValue,
  ): Promise<LedgerSnapshot> {
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
      (item) => isClientProject(item) && item.name.trim() === value.projectName.trim(),
    );

    if (project) {
      const linkedCustomer = next.customers.find((item) => item.id === project?.customerId);
      if (linkedCustomer) customer = linkedCustomer;
      const plannedTotal = next.payments
        .filter((item) => item.projectId === project?.id && item.status !== "written_off")
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
        projectKind: "client",
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

    return mockLedgerService.saveSnapshot(next);
  },

  async saveSnapshot(snapshot: LedgerSnapshot): Promise<LedgerSnapshot> {
    const next = cloneSnapshot(snapshot);
    if (!backendConnected || backendRevision === null) {
      persistSnapshot(next);
      return next;
    }
    try {
      const response = await fetch("/api/ledger/snapshot", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: backendRevision, snapshot: next }),
      });
      if (response.status === 409) {
        window.dispatchEvent(new CustomEvent("ledger-conflict"));
        const latest = await fetch("/api/ledger/snapshot");
        if (!latest.ok) throw new Error("无法刷新最新经营数据");
        const payload = await latest.json() as { revision: number; snapshot: LedgerSnapshot };
        backendRevision = payload.revision;
        return cloneSnapshot(payload.snapshot);
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json() as { revision: number; snapshot: LedgerSnapshot };
      backendRevision = payload.revision;
      return cloneSnapshot(payload.snapshot);
    } catch {
      backendConnected = false;
      backendRevision = null;
      persistSnapshot(next);
      window.dispatchEvent(new CustomEvent("ledger-backend-offline"));
      return next;
    }
  },
};

export function getLegacyLedgerSnapshot(): LedgerSnapshot | null {
  try {
    const stored = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!stored) return null;
    const parsed = JSON.parse(stored) as unknown;
    return isLedgerSnapshot(parsed) ? cloneSnapshot(parsed) : null;
  } catch {
    return null;
  }
}

export function isLedgerBackendConnected() {
  return backendConnected;
}

export function getLedgerRevision() {
  return backendRevision;
}

export function acceptMigratedLedger(revision: number) {
  backendRevision = revision;
  backendConnected = true;
}
