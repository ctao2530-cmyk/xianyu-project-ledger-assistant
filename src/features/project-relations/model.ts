import type { LedgerSnapshot } from '../../types';
import type { ProjectRequirementBlueprintView } from '../../data/localPlatformService';
import { getProjectFinancials } from '../../data/businessMetrics';

export type RelationNode = { id: string; label: string; detail: string; href?: string; missing?: boolean };
const hash = (path: string) => `#${encodeURIComponent(path)}`;
const money = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' });
/** A projection of explicit ownership only. No nickname inference or business writes. */
export function projectRelations(snapshot: LedgerSnapshot, projectId: string, formal: ProjectRequirementBlueprintView | null, requirementState: 'loading' | 'ready' | 'error'): RelationNode[] {
  const project = snapshot.projects.find(p => p.id === projectId);
  if (!project) return [];
  const customer = snapshot.customers.find(c => c.id === project.customerId);
  const tasks = snapshot.tasks.filter(t => t.projectId === projectId);
  const finance = getProjectFinancials(snapshot).find(f => f.project.id === projectId)!;
  const linkedFormal = formal?.case_id && formal.project_id === projectId && formal.customer_id === project.customerId ? formal : null;
  return [
    { id: 'customer', label: '客户档案', detail: customer ? '已关联 · 查看资料与项目' : '未关联客户', missing: !customer, href: customer ? hash(`客户消息/customer/${customer.id}?view=projects`) : undefined },
    { id: 'conversation', label: '来源会话', detail: project.conversationId ? '已记录来源 · 查看原始沟通' : '未记录项目来源会话', missing: !project.conversationId, href: project.conversationId ? hash(`客户消息/conversation/${project.conversationId}`) : undefined },
    { id: 'requirement', label: '正式需求与验收', detail: requirementState === 'loading' ? '正在核对关联…' : requirementState === 'error' ? '读取失败 · 查看详情' : linkedFormal ? `正式需求 V${linkedFormal.version} · 查看验收记录` : '尚未关联正式需求', missing: requirementState === 'ready' && !linkedFormal, href: hash(`项目管理/${projectId}/overview?section=requirements`) },
    { id: 'tasks', label: '开发任务', detail: `${tasks.filter(t => t.status === 'done').length} / ${tasks.length} 已完成 · 不代表客户验收`, href: hash(`项目管理/${projectId}/overview?section=tasks`) },
    { id: 'payments', label: '合同回款', detail: `已收 ${money.format(finance.income)} · 待收 ${money.format(finance.outstanding)}`, href: hash(`项目管理/${projectId}/overview?section=payments`) },
  ];
}
