import { CaretRight, Sparkle } from '@phosphor-icons/react';
import { daysUntil, getProjectFinancials } from '../../data/businessMetrics';
import type { LedgerSnapshot } from '../../types';

export function ProjectListContext({items,snapshot,onOpen,onPayment}:{items:ReturnType<typeof getProjectFinancials>;snapshot:LedgerSnapshot;onOpen:(id:string)=>void;onPayment:(id:string)=>void}) {
  const deliveries=items.filter(({project})=>!['delivered','completed'].includes(project.status)).slice().sort((a,b)=>a.project.dueDate.localeCompare(b.project.dueDate)).slice(0,4);
  const receivables=items.filter(item=>item.outstanding>0).slice().sort((a,b)=>b.outstanding-a.outstanding).slice(0,3);
  const customer=(id:string)=>snapshot.customers.find(c=>c.id===id)?.name||'未关联客户';
  return <aside className="reference-project-context" aria-label="项目交付与回款提醒">
    <section><h3>交付提醒</h3>{deliveries.length?deliveries.map(({project})=>{const days=daysUntil(project.dueDate);return <button key={project.id} onClick={()=>onOpen(project.id)}><span><strong>{project.name}</strong><small>{customer(project.customerId)}</small></span><em className={days<=3?'is-danger':''}>{days<0?`已超期 ${-days} 天`:`${days} 天后交付`}</em></button>}):<p>暂无待交付项目</p>}</section>
    <section><h3>待回款</h3>{receivables.length?receivables.map(({project,outstanding})=><button key={project.id} onClick={()=>onPayment(project.id)}><span><strong>{project.name}</strong><small>{customer(project.customerId)}</small></span><span className="project-context-money"><strong>¥{outstanding.toLocaleString('zh-CN')}</strong><small>查看收款确认 <CaretRight size={12}/></small></span></button>):<p>暂无待回款项目</p>}</section>
    <div className="workbench-focus-note"><Sparkle size={28} weight="fill"/><p>按计划推进项目交付，<br/>让每一个合作都创造长期价值。</p></div>
  </aside>;
}
