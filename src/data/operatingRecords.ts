import type { LedgerSnapshot, PaymentType } from "../types";
import { getBusinessSummary } from "./businessMetrics";
import { isClientProject } from "./projectKinds";

export type OperatingRecordType = "income" | "refund" | "expense" | "receivable";
export type TrackLane = "income" | "expense" | "receivable";

export interface OperatingRecord {
  id: string;
  type: OperatingRecordType;
  lane: TrackLane;
  title: string;
  detail: string;
  amount: number;
  occurredAt: string;
  projectId?: string;
  paymentId?: string;
  expenseId?: string;
  status: string;
}

const paymentTypeLabels: Record<PaymentType, string> = {
  deposit: "定金",
  milestone: "阶段款",
  final: "尾款",
  full: "全款",
};

const expenseCategoryLabels: Record<string, string> = {
  software: "软件订阅",
  outsourcing: "外包服务",
  server: "服务器",
  office: "办公支出",
  traffic: "流量曝光",
  refund: "退款记录",
  other: "其他支出",
};

export function validDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function buildRecords(snapshot: LedgerSnapshot): OperatingRecord[] {
  const projects = new Map(snapshot.projects.map((project) => [project.id, project]));
  const customers = new Map(snapshot.customers.map((customer) => [customer.id, customer]));
  const records: OperatingRecord[] = [];

  snapshot.payments.forEach((payment) => {
    const project = projects.get(payment.projectId);
    const customer = customers.get(payment.customerId);
    const detail = `${paymentTypeLabels[payment.type]} · ${customer?.name || "未关联客户"}`;
    if (payment.status === "confirmed" || payment.status === "refunded") {
      records.push({
        id: `payment-income-${payment.id}`,
        type: "income",
        lane: "income",
        title: project?.name || "未关联项目收款",
        detail,
        amount: payment.amount,
        occurredAt: payment.paidAt,
        projectId: payment.projectId,
        paymentId: payment.id,
        status: payment.status === "refunded" ? "曾到账" : "已到账",
      });
    }
    if (payment.status === "refunded") {
      records.push({
        id: `payment-refund-${payment.id}`,
        type: "refund",
        lane: "income",
        title: `${project?.name || "项目"}退款`,
        detail: `${detail} · 原收款已退回`,
        amount: -payment.amount,
        occurredAt: payment.paidAt,
        projectId: payment.projectId,
        paymentId: payment.id,
        status: "已退款",
      });
    }
  });

  (snapshot.settlementIssues || []).forEach((issue) => {
    if (issue.refundAmount <= 0) return;
    const project = projects.get(issue.projectId);
    records.push({
      id: `settlement-refund-${issue.id}`,
      type: "refund",
      lane: "income",
      title: `${project?.name || "项目"}结算退款`,
      detail: issue.reason,
      amount: -issue.refundAmount,
      occurredAt: issue.occurredAt,
      projectId: issue.projectId,
      status: "已退款",
    });
  });

  snapshot.expenses.forEach((expense) => {
    const project = expense.projectId ? projects.get(expense.projectId) : null;
    records.push({
      id: `expense-${expense.id}`,
      type: "expense",
      lane: "expense",
      title: expense.name,
      detail: `${expenseCategoryLabels[expense.category] || "其他支出"} · ${project?.name || "未关联项目"}`,
      amount: -expense.amount,
      occurredAt: expense.paidAt,
      projectId: expense.projectId,
      expenseId: expense.id,
      status: expense.category === "refund" ? "已记录退款" : "已支付",
    });
  });

  const summary = getBusinessSummary(snapshot);
  summary.projectFinancials
    .filter(({ project, outstanding }) => isClientProject(project) && outstanding > 0)
    .forEach((financial) => {
      const pendingPayment = snapshot.payments
        .filter((payment) => payment.projectId === financial.project.id && payment.status === "pending")
        .sort((left, right) => new Date(left.dueAt).getTime() - new Date(right.dueAt).getTime())[0];
      records.push({
        id: `receivable-${financial.project.id}`,
        type: "receivable",
        lane: "receivable",
        title: financial.project.name,
        detail: pendingPayment ? `${paymentTypeLabels[pendingPayment.type]} · 待确认到账` : "合同余额 · 尚未建立收款节点",
        amount: financial.outstanding,
        occurredAt: pendingPayment?.dueAt || financial.project.dueDate,
        projectId: financial.project.id,
        paymentId: pendingPayment?.id,
        status: "待收款",
      });
    });

  return records.sort((left, right) => {
    const timeDifference = (validDate(right.occurredAt)?.getTime() || 0) - (validDate(left.occurredAt)?.getTime() || 0);
    return timeDifference || left.id.localeCompare(right.id);
  });
}

