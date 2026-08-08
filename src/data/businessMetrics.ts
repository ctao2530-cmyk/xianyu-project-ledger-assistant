import type { LedgerSnapshot, Project, ProjectSettlementIssue } from "../types";
import { isClientProject } from "./projectKinds";

const isSameMonth = (value: string, target = new Date()) => {
  const date = new Date(value);
  return date.getFullYear() === target.getFullYear() && date.getMonth() === target.getMonth();
};

const isSameYear = (value: string, target = new Date()) =>
  new Date(value).getFullYear() === target.getFullYear();

const isSameDay = (value: string, target = new Date()) => {
  const date = new Date(value);
  return date.getFullYear() === target.getFullYear()
    && date.getMonth() === target.getMonth()
    && date.getDate() === target.getDate();
};

const sumIssues = (
  issues: ProjectSettlementIssue[],
  field: "receivableImpact" | "refundAmount",
) => issues.reduce((sum, issue) => sum + issue[field], 0);

export const daysBetween = (startDate: string, dueDate: string) => {
  const start = new Date(`${startDate}T00:00:00`).getTime();
  const due = new Date(`${dueDate}T00:00:00`).getTime();
  return Math.max(1, Math.ceil((due - start) / 86_400_000) + 1);
};

export const daysUntil = (dateValue: string) => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(`${dateValue.slice(0, 10)}T00:00:00`);
  return Math.ceil((target.getTime() - today.getTime()) / 86_400_000);
};

export interface ProjectFinancial {
  project: Project;
  /** Net cash retained after payment refunds and settlement-issue refunds. */
  income: number;
  grossIncome: number;
  refundedAmount: number;
  availableRefund: number;
  uncollectible: number;
  settlementIssues: ProjectSettlementIssue[];
  issueCount: number;
  expenses: number;
  profit: number;
  /** Contract balance that can still realistically be collected. */
  outstanding: number;
  /** Net cash retained as a percentage of contract value. */
  paymentProgress: number;
  /** Portion of the contract either received or explicitly written off. */
  settlementProgress: number;
  actualHours: number;
  hourlyIncome: number;
}

export const getProjectFinancials = (snapshot: LedgerSnapshot): ProjectFinancial[] =>
  snapshot.projects.map((project) => {
    const projectPayments = snapshot.payments.filter((payment) => payment.projectId === project.id);
    const projectIssues = (snapshot.settlementIssues || []).filter((issue) => issue.projectId === project.id);
    const grossIncome = projectPayments
      .filter((payment) => payment.status === "confirmed" || payment.status === "refunded")
      .reduce((sum, payment) => sum + payment.amount, 0);
    const legacyRefunds = projectPayments
      .filter((payment) => payment.status === "refunded")
      .reduce((sum, payment) => sum + payment.amount, 0);
    const issueRefunds = sumIssues(projectIssues, "refundAmount");
    const refundedAmount = legacyRefunds + issueRefunds;
    const income = grossIncome - refundedAmount;
    const uncollectible = sumIssues(projectIssues, "receivableImpact");
    const expenses = snapshot.expenses
      .filter((expense) => expense.projectId === project.id)
      .reduce((sum, expense) => sum + expense.amount, 0);
    const actualHours = snapshot.tasks
      .filter((task) => task.projectId === project.id)
      .reduce((sum, task) => sum + task.actualHours, 0);
    const outstanding = Math.max(0, project.totalAmount - grossIncome - uncollectible);
    const profit = income - expenses;
    return {
      project,
      income,
      grossIncome,
      refundedAmount,
      availableRefund: Math.max(0, grossIncome - refundedAmount),
      uncollectible,
      settlementIssues: projectIssues,
      issueCount: projectIssues.length,
      expenses,
      profit,
      outstanding,
      paymentProgress: project.totalAmount
        ? Math.min(100, Math.max(0, (income / project.totalAmount) * 100))
        : 0,
      settlementProgress: project.totalAmount
        ? Math.min(100, Math.max(0, ((grossIncome + uncollectible) / project.totalAmount) * 100))
        : 0,
      actualHours,
      hourlyIncome: actualHours ? profit / actualHours : 0,
    };
  });

const netIncomeForPeriod = (
  snapshot: LedgerSnapshot,
  predicate: (value: string) => boolean,
) => {
  const gross = snapshot.payments
    .filter((payment) => (payment.status === "confirmed" || payment.status === "refunded") && predicate(payment.paidAt))
    .reduce((sum, payment) => sum + payment.amount, 0);
  const legacyRefunds = snapshot.payments
    .filter((payment) => payment.status === "refunded" && predicate(payment.paidAt))
    .reduce((sum, payment) => sum + payment.amount, 0);
  const issueRefunds = (snapshot.settlementIssues || [])
    .filter((issue) => predicate(issue.occurredAt))
    .reduce((sum, issue) => sum + issue.refundAmount, 0);
  return gross - legacyRefunds - issueRefunds;
};

export const getBusinessSummary = (snapshot: LedgerSnapshot) => {
  const projectFinancials = getProjectFinancials(snapshot);
  const totalIncome = projectFinancials.reduce((sum, item) => sum + item.income, 0);
  const totalGrossIncome = projectFinancials.reduce((sum, item) => sum + item.grossIncome, 0);
  const totalRefunded = projectFinancials.reduce((sum, item) => sum + item.refundedAmount, 0);
  const totalUncollectible = projectFinancials.reduce((sum, item) => sum + item.uncollectible, 0);
  const totalExpenses = snapshot.expenses.reduce((sum, expense) => sum + expense.amount, 0);
  const actualHours = snapshot.tasks.reduce((sum, task) => sum + task.actualHours, 0);
  const outstanding = projectFinancials.reduce((sum, item) => sum + item.outstanding, 0);
  const pendingPayments = snapshot.payments.filter((payment) => payment.status === "pending");
  const pendingAmount = pendingPayments.reduce((sum, payment) => sum + payment.amount, 0);
  const monthlyIncome = netIncomeForPeriod(snapshot, (value) => isSameMonth(value));
  const monthlyExpenses = snapshot.expenses
    .filter((expense) => isSameMonth(expense.paidAt))
    .reduce((sum, expense) => sum + expense.amount, 0);
  const yearlyIncome = netIncomeForPeriod(snapshot, (value) => isSameYear(value));
  const yearlyExpenses = snapshot.expenses
    .filter((expense) => isSameYear(expense.paidAt))
    .reduce((sum, expense) => sum + expense.amount, 0);
  const todayIncome = netIncomeForPeriod(snapshot, (value) => isSameDay(value));

  return {
    totalIncome,
    totalGrossIncome,
    totalRefunded,
    totalUncollectible,
    settlementIssueCount: (snapshot.settlementIssues || []).length,
    totalExpenses,
    actualProfit: totalIncome - totalExpenses,
    outstanding,
    pendingAmount,
    pendingCount: pendingPayments.length,
    monthlyIncome,
    monthlyExpenses,
    monthlyProfit: monthlyIncome - monthlyExpenses,
    yearlyIncome,
    yearlyExpenses,
    yearlyProfit: yearlyIncome - yearlyExpenses,
    todayIncome,
    actualHours,
    averageHourlyIncome: actualHours ? (totalIncome - totalExpenses) / actualHours : 0,
    projectFinancials,
  };
};

export const getCustomerBusiness = (snapshot: LedgerSnapshot, customerId: string) => {
  const projects = snapshot.projects.filter(
    (project) => isClientProject(project) && project.customerId === customerId,
  );
  const projectIds = new Set(projects.map((project) => project.id));
  const financials = getProjectFinancials(snapshot).filter((item) => projectIds.has(item.project.id));
  return {
    projects,
    orderCount: projects.length,
    totalSpend: financials.reduce((sum, item) => sum + item.income, 0),
  };
};
