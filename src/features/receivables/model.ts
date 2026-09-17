import type { LedgerSnapshot } from '../../types';
import { getProjectFinancials } from '../../data/businessMetrics';
import { isClientProject } from '../../data/projectKinds';
import { hasTerminalSettlementIssue } from '../../data/settlementIssues';
import { businessDate, daysToBusinessDate } from '../../shared/time/businessDate';

export const agingBuckets = [
  { id: 'future', label: '未到期 / 今日到期' },
  { id: 'overdue30', label: '逾期 1–30 天' },
  { id: 'overdue60', label: '逾期 31–60 天' },
  { id: 'overdue61', label: '逾期 61 天以上' },
  { id: 'undated', label: '未约定日期' },
  { id: 'review', label: '计划待核对' },
] as const;
export type AgingBucket = typeof agingBuckets[number]['id'];
export type ReceivableRow = {
  id: string; projectId: string; projectName: string; customerName: string;
  paymentId?: string; amount: number; bucket: AgingBucket; dueDate?: string;
  overdueDays: number; terminal: boolean; reason: string;
};
const cents = (value: number) => Math.round((value + Number.EPSILON) * 100);
/** Read-only current balances. Never substitute a delivery date for an agreed payment date. */
export function buildReceivableAging(snapshot: LedgerSnapshot, now = new Date()): ReceivableRow[] {
  const customers = new Map(snapshot.customers.map(c => [c.id, c.name]));
  const rows: ReceivableRow[] = [];
  for (const financial of getProjectFinancials(snapshot)) {
    const { project } = financial;
    const outstanding = cents(financial.outstanding);
    if (!isClientProject(project) || outstanding <= 0) continue;
    const base = { projectId: project.id, projectName: project.name, customerName: customers.get(project.customerId) || '未关联客户', terminal: hasTerminalSettlementIssue(financial.settlementIssues) };
    const pending = snapshot.payments.filter(p => p.projectId === project.id && p.status === 'pending');
    const planned = pending.reduce((sum, p) => sum + cents(p.amount), 0);
    const invalid = pending.some(p => !Number.isFinite(p.amount) || cents(p.amount) <= 0 || p.customerId !== project.customerId);
    if (invalid || planned > outstanding) {
      rows.push({ ...base, id: `review-${project.id}`, amount: outstanding / 100, bucket: 'review', overdueDays: 0, reason: invalid ? '付款节点金额或客户归属异常，请核对原记录' : '未收节点合计超过项目待收余额，暂不分配账龄' });
      continue;
    }
    for (const payment of pending) {
      const date = businessDate(payment.dueAt);
      const days = daysToBusinessDate(payment.dueAt, now);
      const bucket: AgingBucket = !Number.isFinite(days) ? 'undated' : days >= 0 ? 'future' : days >= -30 ? 'overdue30' : days >= -60 ? 'overdue60' : 'overdue61';
      rows.push({ ...base, id: `payment-${payment.id}`, paymentId: payment.id, amount: cents(payment.amount) / 100, bucket, dueDate: date === 'unknown' ? undefined : date, overdueDays: Number.isFinite(days) ? Math.max(0, -days) : 0, reason: date === 'unknown' ? '付款节点未填写有效到期日' : days === 0 ? '今日到期' : days > 0 ? `${days} 天后到期` : `已逾期 ${-days} 天` });
    }
    if (outstanding > planned) rows.push({ ...base, id: `unplanned-${project.id}`, amount: (outstanding - planned) / 100, bucket: 'undated', overdueDays: 0, reason: '待收余额尚未安排收款节点' });
  }
  const order: Record<AgingBucket, number> = { review: 0, overdue61: 1, overdue60: 2, overdue30: 3, undated: 4, future: 5 };
  return rows.sort((a, b) => order[a.bucket] - order[b.bucket] || b.overdueDays - a.overdueDays || (a.dueDate || '').localeCompare(b.dueDate || '') || a.id.localeCompare(b.id));
}
export function sumReceivables(rows: ReceivableRow[]): number {
  return rows.reduce((sum, row) => sum + cents(row.amount), 0) / 100;
}
