import { useState, type ReactNode } from 'react';
import type { ConversationSummary } from '../../data/localPlatformService';
import type { Customer } from '../../types';
import { EmptyState } from './EmptyState';
import { MagnifyingGlass, UserCircle } from '@phosphor-icons/react';
import { customerListTime } from './customerListTime';
import { Button } from '@appica/ui-react/button';
import { Chip } from '@appica/ui-react/chip';
import '../../vendor/appica-scoped.css';

export function MasterList({ rows, customers, selectedId, onSelect, selectedCustomerId, onSelectCustomer, toolbar }: {rows: ConversationSummary[]; customers: Customer[]; selectedId: number|null; onSelect:(id:number)=>void; selectedCustomerId?:string|null; onSelectCustomer?:(id:string)=>void; toolbar?:ReactNode}) {
  const [query,setQuery]=useState(()=>sessionStorage.getItem('xunying-master-search')||'');
  const [scope,setScopeState]=useState(()=>sessionStorage.getItem('xunying-master-scope')||'all');
  const setScope=(value:string)=>{setScopeState(value);sessionStorage.setItem('xunying-master-scope',value)};
  const linked=new Set(customers.flatMap(c=>(c.channelIdentities||[]).flatMap(i=>i.conversationId?[i.conversationId]:[])));
  // Only an explicitly saved conversation link can supply a profile name.
  const nameOf=(row:ConversationSummary)=>customers.find(c=>(c.channelIdentities||[]).some(i=>i.conversationId===row.id))?.name || row.customer_name;
  const matchingProfiles=customers.filter(c=>!(c.channelIdentities||[]).some(i=>rows.some(r=>r.id===i.conversationId))&&c.name.toLowerCase().includes(query.toLowerCase()));
  const profiles=scope==='all'?matchingProfiles:[];
  const matchingRows=rows.filter(r=>`${nameOf(r)} ${r.last_message||''}`.toLowerCase().includes(query.toLowerCase()));
  const counts:Record<string,number>={all:matchingRows.length+matchingProfiles.length,pending:matchingRows.filter(r=>r.unread_count>0).length,unlinked:matchingRows.filter(r=>!linked.has(r.id)).length};
  const visible=matchingRows.filter(r=>(scope!=='pending'||r.unread_count>0)&&(scope!=='unlinked'||!linked.has(r.id)));
  return <aside className="conversation-list workspace-master" aria-label="客户会话列表">
    <div className="customer-master-heading"><h2 className="customer-list-title">客户</h2>{toolbar}</div>
    <header className="customer-master-search"><label><MagnifyingGlass size={17} aria-hidden="true"/><span className="sr-only">搜索客户或会话</span><input aria-label="搜索客户或会话" placeholder="搜索客户或会话" value={query} onChange={e=>{setQuery(e.target.value);sessionStorage.setItem('xunying-master-search',e.target.value)}}/></label></header>
    <nav aria-label="会话范围">{[['all','全部'],['pending','待处理'],['unlinked','未关联']].map(([key,label])=><Button className="customer-appica-button" variant={scope===key?'soft':'ghost'} type="button" key={key} aria-pressed={scope===key} onClick={()=>setScope(key)}>{label}<span className="master-scope-count">{counts[key]}</span></Button>)}</nav>
    {scope==='unlinked'&&<p className="master-hint">按客户档案已保存的会话关联筛选。</p>}
    <div className="workspace-master-rows">{visible.map(r=><button type="button" key={r.id} className={r.id===selectedId?'active':''} aria-current={r.id===selectedId?'true':undefined} onClick={()=>onSelect(r.id)}><UserCircle className="customer-list-avatar" size={42} weight="duotone" aria-hidden="true"/><strong title={nameOf(r)}>{nameOf(r)}</strong><time dateTime={r.last_message_at} title={r.last_message_at}>{customerListTime(r.last_message_at)}</time><small>{r.last_message||'暂无消息'}</small>{r.unread_count>0&&<Chip render={<span />} tabIndex={undefined} variant="destructive" size="sm" className="customer-unread-badge" aria-label={`${r.unread_count} 条未读`}>{r.unread_count>99?'99+':r.unread_count}</Chip>}</button>)}</div>
    {Boolean(profiles.length)&&<div className="workspace-master-rows"><p className="master-hint">客户档案 · 无可见关联会话</p>{profiles.map(c=><button type="button" key={c.id} className={selectedCustomerId===c.id?'active':''} aria-current={selectedCustomerId===c.id?'true':undefined} onClick={()=>onSelectCustomer?.(c.id)}><strong>{c.name}</strong><small>查看资料、需求与项目</small></button>)}</div>}
    {!visible.length&&!profiles.length&&<EmptyState>没有符合条件的客户或会话。</EmptyState>}
  </aside>;
}
