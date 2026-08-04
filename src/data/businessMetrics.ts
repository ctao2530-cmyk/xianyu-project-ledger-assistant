import type { LedgerSnapshot, Project } from "../types";

const isSameMonth = (value: string, target = new Date()) => {
  const date = new Date(value);
  return date.getFullYear() === target.getFullYear() && date.getMonth() === target.getMonth();
};

const isSameYear = (value: string, target = new Date()) =>
  new Date(value).getFullYear() === target.getFullYear();

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
  income: number;
  expenses: number;
  profit: number;
  outstanding: number;
  paymentProgress: number;
  actualHours: number;
  hourlyIncome: number;
}

export const getProjectFinancials = (snapshot: LedgerSnapshot): ProjectFinancial[] =>
  snapshot.projects.map((project) => {
    const income = snapshot.payments
      .filter((payment) => payment.projectId === project.id && payment.status === "confirmed")
      .reduce((sum, payment) => sum + payment.amount, 0);
    const expenses = snapshot.expenses
      .filter((expense) => expense.projectId === project.id)
      .reduce((sum, expense) => sum + expense.amount, 0);
    const actualHours = snapshot.tasks
      .filter((task) => task.projectId === project.id)
      .reduce((sum, task) => sum + task.actualHours, 0);
    const outstanding = Math.max(0, project.totalAmount - income);
    return {
      project,
      income,
      expenses,
      profit: income - expenses,
      outstanding,
      paymentProgress: project.totalAmount ? Math.min(100, (income / project.totalAmount) * 100) : 0,
      actualHours,
      hourlyIncome: actualHours ? (income - expenses) / actualHours : 0,
    };
  });

export const getBusinessSummary = (snapshot: LedgerSnapshot) => {
  const confirmedPayments = snapshot.payments.filter((payment) => payment.status === "confirmed");
  const totalIncome = confirmedPayments.reduce((sum, payment) => sum + payment.amount, 0);
  const totalExpenses = snapshot.expenses.reduce((sum, expense) => sum + expense.amount, 0);
  const actualHours = snapshot.tasks.reduce((sum, task) => sum + task.actualHours, 0);
  const projectFinancials = getProjectFinancials(snapshot);
  const outstanding = projectFinancials.reduce((sum, item) => sum + item.outstanding, 0);
  const pendingPayments = snapshot.payments.filter((payment) => payment.status === "pending");
  const pendingAmount = pendingPayments.reduce((sum, payment) => sum + payment.amount, 0);
  const monthlyIncome = confirmedPayments
    .filter((payment) => isSameMonth(payment.paidAt))
    .reduce((sum, payment) => sum + payment.amount, 0);
  const monthlyExpenses = snapshot.expenses
    .filter((expense) => isSameMonth(expense.paidAt))
    .reduce((sum, expense) => sum + expense.amount, 0);
  const yearlyIncome = confirmedPayments
    .filter((payment) => isSameYear(payment.paidAt))
    .reduce((sum, payment) => sum + payment.amount, 0);
  const yearlyExpenses = snapshot.expenses
    .filter((expense) => isSameYear(expense.paidAt))
    .reduce((sum, expense) => sum + expense.amount, 0);

  return {
    totalIncome,
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
    actualHours,
    averageHourlyIncome: actualHours ? (totalIncome - totalExpenses) / actualHours : 0,
    projectFinancials,
  };
};

export const getCustomerBusiness = (snapshot: LedgerSnapshot, customerId: string) => {
  const projects = snapshot.projects.filter((project) => project.customerId === customerId);
  const projectIds = new Set(projects.map((project) => project.id));
  const payments = snapshot.payments.filter(
    (payment) => projectIds.has(payment.projectId) && payment.status === "confirmed",
  );
  return {
    projects,
    orderCount: projects.length,
    totalSpend: payments.reduce((sum, payment) => sum + payment.amount, 0),
  };
};
