import type { Customer, LedgerSnapshot } from '../../types';
import { CustomerRequirementBlueprintPage } from '../../pages/CustomerRequirementBlueprintPage';
import type { ReactNode } from 'react';

export function CustomerProfileWorkspace({ customer, snapshot, view, caseId, onView, onSnapshotChange, headerActions }: {
  customer: Customer; snapshot?: LedgerSnapshot; view: string; caseId: string | null;
  onView: (view: 'conversation'|'materials'|'requirements'|'projects', caseId?: string|null) => void;
  onSnapshotChange?: (snapshot: LedgerSnapshot) => void;
  headerActions?: ReactNode;
}) {
  const projects = snapshot?.projects.filter(p => p.customerId === customer.id) || [];
  return <main className="message-thread">
    <header className="thread-header"><div className="thread-header-copy"><h2>{customer.name}</h2><p>{customer.source} · {customer.level} 级 · 客户档案</p></div><div className="thread-header-actions">{headerActions}</div></header>
    <nav className="customer-hub-tabs" aria-label="当前客户内容">{(['conversation','materials','requirements','projects'] as const).map((key,i)=><button key={key} aria-current={view===key?'page':undefined} onClick={()=>onView(key)}>{['会话','资料','需求','项目'][i]}</button>)}</nav>
    <div className="customer-hub-content">
      {view==='conversation'&&((customer.channelIdentities||[]).some(i=>i.conversationId)?<div>{customer.channelIdentities?.filter(i=>i.conversationId).map(i=><p key={`${i.channel}-${i.conversationId}`}><a href={`#${encodeURIComponent(`客户消息/conversation/${i.conversationId}`)}`}>打开已关联{ i.channel==='xianyu'?'闲鱼':'微信'}会话 →</a></p>)}</div>:<p>该档案尚无可直接打开的已关联会话。已有会话请在原有客户管理入口中确认关联，不按昵称自动匹配。</p>)}
      {view==='materials'&&<>{snapshot?.attachments.filter(a=>projects.some(p=>p.id===a.projectId)).map(a=><p key={a.id}>{a.name} <a href={`#${encodeURIComponent(`项目管理/${a.projectId}/overview?section=records`)}`}>查看来源项目附件</a></p>)}<p>无关联会话时不展示其他客户的图片。</p></>}
      {view==='requirements'&&onSnapshotChange&&<CustomerRequirementBlueprintPage embedded customer={customer} route={{customerId:customer.id,caseId}} onRouteChange={r=>onView('requirements',r?.caseId||null)} onSnapshotChange={onSnapshotChange}/>}
      {view==='projects'&&(projects.length?projects.map(p=><p key={p.id}><a href={`#${encodeURIComponent(`项目管理/${p.id}/overview`)}`}>{p.name} →</a></p>):<p>当前客户尚无关联项目。</p>)}
    </div>
  </main>;
}
