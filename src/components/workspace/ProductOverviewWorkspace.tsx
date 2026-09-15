import { useState, type ReactNode } from 'react';
import { ContextPanel } from './AppShell';
import { MagnifyingGlass, Plus } from '@phosphor-icons/react';
export function ProductOverviewWorkspace({products,selectedId,onSelect,children,context,management,overview,onAdd}:{products:Array<{external_id:string;title:string;status?:string;monitoring_enabled?:boolean;last_collected_at?:string|null}>;selectedId:string;onSelect:(id:string)=>void;children:ReactNode;context:ReactNode;management?:ReactNode;overview?:ReactNode;onAdd?:()=>void}) {
  const [query,setQuery]=useState(()=>sessionStorage.getItem('xunying-product-query')||'');
  const [scope,setScope]=useState('all');
  const matching=products.filter(p=>p.title.toLowerCase().includes(query.toLowerCase()));
  const counts:Record<string,number>={all:matching.length,monitoring:matching.filter(p=>p.monitoring_enabled).length,paused:matching.filter(p=>!p.monitoring_enabled).length};
  const visible=matching.filter(p=>scope==='all'||(scope==='monitoring'?p.monitoring_enabled:!p.monitoring_enabled));
  const selected=products.find(p=>p.external_id===selectedId);
  return <section className="product-object-workspace" aria-label="当前商品工作区">
    <aside className="product-master">
      <header className="product-master-heading"><h2>商品列表</h2>{onAdd&&<button type="button" className="product-primary-button" onClick={onAdd}><Plus size={16}/>添加商品</button>}</header>
      <label className="product-master-search"><MagnifyingGlass size={17} aria-hidden="true"/><input aria-label="搜索商品" placeholder="搜索商品名称或关键词…" value={query} onChange={e=>{setQuery(e.target.value);sessionStorage.setItem('xunying-product-query',e.target.value)}}/></label>
      <div className="product-master-filters" role="group" aria-label="商品监测筛选">{[['all','全部'],['monitoring','监测中'],['paused','已暂停']].map(([key,label])=><button key={key} aria-pressed={scope===key} onClick={()=>setScope(key)}>{label}<span>{counts[key]}</span></button>)}</div>
      <nav aria-label="选择当前商品">{visible.map(p=><button key={p.external_id} aria-current={p.external_id===selectedId?'true':undefined} onClick={()=>onSelect(p.external_id)}><strong>{p.title}</strong><small className={p.monitoring_enabled?'is-monitoring':'is-paused'}>{p.monitoring_enabled?'监测中':'已暂停监测'}</small></button>)}</nav>
      {!visible.length&&<p>没有匹配的商品，请调整关键词。</p>}
      {overview}
    </aside>
    <div className="product-object-detail">{children}</div><ContextPanel title="商品上下文"><dl className="product-context-facts"><dt>商品 ID</dt><dd>{selectedId}</dd><dt>监测状态</dt><dd>{selected?.monitoring_enabled?'监测中':'已暂停'}</dd><dt>最近采集</dt><dd>{selected?.last_collected_at?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'medium',timeStyle:'short'}).format(new Date(selected.last_collected_at)):'暂无采集记录'}</dd></dl>{context}{management}</ContextPanel>
  </section>;
}
