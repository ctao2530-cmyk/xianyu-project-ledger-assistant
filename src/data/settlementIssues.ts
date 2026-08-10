import type { ProjectSettlementIssue, SettlementIssueType } from "../types";

export const settlementIssueLabels: Record<SettlementIssueType, string> = {
  customer_dissatisfied: "客户不满意",
  refund: "退款处理",
  project_cancelled: "项目取消",
  payment_refused: "客户拒付",
  cooperation_terminated: "终止合作",
  scope_dispute: "需求范围争议",
  other: "其他异常",
};

export const settlementIssueOptions = Object.entries(settlementIssueLabels) as Array<
  [SettlementIssueType, string]
>;

export const terminalSettlementIssueTypes = new Set<SettlementIssueType>([
  "project_cancelled",
  "cooperation_terminated",
]);

export const latestSettlementIssue = (issues: ProjectSettlementIssue[]) =>
  issues.slice().sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))[0];

export const latestTerminalSettlementIssue = (issues: ProjectSettlementIssue[]) =>
  issues
    .filter((issue) => terminalSettlementIssueTypes.has(issue.type))
    .sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))[0];

export const hasTerminalSettlementIssue = (issues: ProjectSettlementIssue[]) =>
  Boolean(latestTerminalSettlementIssue(issues));
