import type { LedgerSnapshot } from '../../types';
import { getProjectFinancials } from '../../data/businessMetrics';
import { daysToBusinessDate } from '../../shared/time/businessDate';
export const categories = ['全部','客户消息','待确认需求','待补资料','已逾期','临近交付','待回款','异常事项'];
export interface WorkbenchAction { id: string; category: string; title: string; detail: string; href: string; projectId?: string; updatedAt?: string | null; dueAt?: string; }
export interface WorkbenchPage { items: WorkbenchAction[]; total: number; offset: number; hasMore: boolean; asOf: string; }
export const objectHash = (path: string) => `#${encodeURIComponent(path)}`;
export function projectActions(snapshot: LedgerSnapshot, now = new Date()): WorkbenchAction[] {
  return getProjectFinancials(snapshot).flatMap(financial => {
    const { project } = financial;
    const actions: WorkbenchAction[] = [];
    const href = (section: string) => objectHash(`项目管理/${project.id}/overview?section=${section}`);
    const days = daysToBusinessDate(project.dueDate, now);
    const terminal = (snapshot.settlementIssues || []).some(issue => issue.projectId === project.id && ['project_cancelled', 'cooperation_terminated'].includes(issue.type));
    if (!terminal && !['delivered','completed'].includes(project.status) && days <= 7) {
      actions.push({ id: `delivery-${project.id}`, category: days < 0 ? '已逾期' : '临近交付', title: project.name,
        detail: `${days < 0 ? `已逾期 ${-days} 天 · ` : ''}交付日期 ${project.dueDate}`, dueAt: project.dueDate,
        updatedAt: project.updatedAt, href: href('requirements') });
    }
    if (financial.outstanding > 0) actions.push({ id: `payment-${project.id}`, category: '待回款', title: project.name,
      detail: `待回款 ¥${financial.outstanding.toLocaleString('zh-CN')}`, updatedAt: project.updatedAt, href: href('payments'), projectId: project.id });
    if (financial.issueCount) actions.push({ id: `issue-${project.id}`, category: '异常事项', title: project.name,
      detail: `${financial.issueCount} 条已记录异常，请核对处理情况`, updatedAt: project.updatedAt, href: href('records') });
    return actions;
  });
}
const timestamp = (value?: string | null) => value && Number.isFinite(Date.parse(value)) ? Date.parse(value) : -Infinity;
export function sortActions(actions: WorkbenchAction[], sort: string): WorkbenchAction[] {
  return actions.slice().sort((a,b) => {
    const difference = sort === 'recent' ? timestamp(b.updatedAt)-timestamp(a.updatedAt) :
      sort === 'due' ? timestamp(a.dueAt || undefined)-timestamp(b.dueAt || undefined) : categories.indexOf(a.category)-categories.indexOf(b.category);
    if (sort === 'due' && (!a.dueAt || !b.dueAt)) return Number(!a.dueAt)-Number(!b.dueAt) || a.id.localeCompare(b.id);
    return (Number.isNaN(difference) ? 0 : difference) || a.id.localeCompare(b.id);
  });
}
