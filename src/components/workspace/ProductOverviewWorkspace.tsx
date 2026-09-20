import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { ContextPanel, useVisualMode } from './AppShell';
import { ArrowLeft, ArrowRight, MagnifyingGlass, Plus, Storefront } from '@phosphor-icons/react';
type ProductCard = {external_id:string;title:string;status?:string;monitoring_enabled?:boolean;last_collected_at?:string|null;price?:number|null;ownership_status?:string;last_collection_status?:string;browse_count?:number;inquiry_count?:number};
const price = new Intl.NumberFormat('zh-CN', {style:'currency',currency:'CNY',maximumFractionDigits:2});
function cardStatus(product: ProductCard) {
  if(product.ownership_status==='pending')return '归属待确认';
  if(product.ownership_status==='excluded')return '已排除';
  if(!product.monitoring_enabled)return '已暂停监测';
  if(product.last_collection_status==='failed')return '采集失败';
  return '监测中';
}
export function ProductOverviewWorkspace({products,selectedId,onSelect,children,context,management,overview,onAdd}:{products:ProductCard[];selectedId:string;onSelect:(id:string)=>void;children:ReactNode;context:ReactNode;management?:ReactNode;overview?:ReactNode;onAdd?:()=>void}) {
  const aurora=useVisualMode().mode==='aurora';
  const [narrow,setNarrow]=useState(()=>window.matchMedia('(max-width:700px)').matches);
  useEffect(()=>{const media=window.matchMedia('(max-width:700px)');const sync=()=>setNarrow(media.matches);media.addEventListener('change',sync);return()=>media.removeEventListener('change',sync)},[]);
  const [detailVisible,setDetailVisible]=useState(()=>decodeURIComponent(location.hash).includes('/product/'));
  const detailRef=useRef<HTMLDivElement>(null);
  const listRef=useRef<HTMLElement>(null);
  useEffect(()=>{const sync=()=>{if(decodeURIComponent(location.hash).includes('/product/'))setDetailVisible(true)};window.addEventListener('xianyu:route-focus',sync);window.addEventListener('hashchange',sync);return()=>{window.removeEventListener('xianyu:route-focus',sync);window.removeEventListener('hashchange',sync)}},[]);
  const select=(id:string)=>{onSelect(id);setDetailVisible(true);if(aurora)requestAnimationFrame(()=>{detailRef.current?.focus({preventScroll:true});detailRef.current?.scrollIntoView({block:'start',behavior:'instant'})});};
  const [query,setQuery]=useState(()=>sessionStorage.getItem('xunying-product-query')||'');
  const [scope,setScope]=useState('all');
  const matching=products.filter(p=>p.title.toLowerCase().includes(query.toLowerCase()));
  const counts:Record<string,number>={all:matching.length,monitoring:matching.filter(p=>p.monitoring_enabled).length,paused:matching.filter(p=>!p.monitoring_enabled).length};
  const visible=matching.filter(p=>scope==='all'||(scope==='monitoring'?p.monitoring_enabled:!p.monitoring_enabled));
  const [visiblePages,setVisiblePages]=useState(1);
  const pageSize=narrow?3:6;
  const shownProducts=aurora?visible.slice(0,visiblePages*pageSize):visible;
  const productListId=useId();
  const pendingListFocus=useRef<number|'selected'|null>(null);
  useLayoutEffect(()=>{
    if(pendingListFocus.current===null)return;
    const target=pendingListFocus.current==='selected'
      ?listRef.current?.querySelector<HTMLButtonElement>('[aria-current="true"]')
      :listRef.current?.querySelectorAll<HTMLButtonElement>('nav>button')[pendingListFocus.current];
    pendingListFocus.current=null;
    (target||listRef.current)?.focus({preventScroll:true});
    (target||listRef.current)?.scrollIntoView({block:'nearest',behavior:'instant'});
  },[visiblePages,detailVisible,shownProducts.length]);
  const showMore=()=>{
    pendingListFocus.current=shownProducts.length;
    setVisiblePages(pages=>pages+1);
  };
  const returnToList=()=>{
    pendingListFocus.current='selected';
    setDetailVisible(false);
    const selectedIndex=visible.findIndex(product=>product.external_id===selectedId);
    if(aurora&&selectedIndex>=0)setVisiblePages(pages=>Math.max(pages,Math.ceil((selectedIndex+1)/pageSize)));
  };
  const selected=products.find(p=>p.external_id===selectedId);
  return <section className={`product-object-workspace${aurora?' aurora-product-workspace':''}`} data-mobile-view={detailVisible?'detail':'list'} aria-label="当前商品工作区">
    {aurora&&overview}
    <aside className="product-master" ref={listRef} tabIndex={aurora?-1:undefined}>
      <header className="product-master-heading"><h2>商品列表</h2>{onAdd&&<button type="button" className="product-primary-button" onClick={onAdd}><Plus size={16}/>添加商品</button>}</header>
      <label className="product-master-search"><MagnifyingGlass size={17} aria-hidden="true"/><input aria-label="搜索商品" placeholder="搜索商品名称或关键词…" value={query} onChange={e=>{setQuery(e.target.value);setVisiblePages(1);sessionStorage.setItem('xunying-product-query',e.target.value)}}/></label>
      <div className="product-master-filters" role="group" aria-label="商品监测筛选">{[['all','全部'],['monitoring','监测中'],['paused','已暂停']].map(([key,label])=><button key={key} aria-pressed={scope===key} onClick={()=>{setScope(key);setVisiblePages(1)}}>{label}<span>{counts[key]}</span></button>)}</div>
      <nav id={aurora?productListId:undefined} aria-label="选择当前商品">{shownProducts.map(p=><button key={p.external_id} aria-current={p.external_id===selectedId?'true':undefined} onClick={()=>select(p.external_id)}>{aurora&&<span className="aurora-product-card-top"><Storefront size={24} aria-hidden="true"/><small className={cardStatus(p)==='监测中'?'is-monitoring':'is-paused'}>{cardStatus(p)}</small></span>}<strong>{p.title}</strong>{aurora?<><span className="aurora-product-price">{p.price===null||p.price===undefined?'价格未记录':price.format(p.price)}</span><span className="aurora-product-card-metrics"><span>经营浏览 <b>{p.browse_count??'—'}</b></span><span>咨询 <b>{p.inquiry_count??'—'}</b></span></span><span className="aurora-product-card-link">查看详情与证据<ArrowRight size={15} aria-hidden="true"/></span></>:<small className={p.monitoring_enabled?'is-monitoring':'is-paused'}>{p.monitoring_enabled?'监测中':'已暂停监测'}</small>}</button>)}</nav>
      {aurora&&visible.length>0&&<footer className="product-list-more"><span role="status" aria-live="polite">已显示 {shownProducts.length} / {visible.length} 件商品</span>{shownProducts.length<visible.length&&<button type="button" aria-controls={productListId} onClick={showMore}>更多商品</button>}</footer>}
      {!visible.length&&<p>没有匹配的商品，请调整关键词。</p>}
      {!aurora&&overview}
    </aside>
    <div className="product-object-detail" ref={detailRef} tabIndex={-1} aria-label="选中商品详情">{aurora&&<button type="button" className="aurora-product-back" onClick={returnToList}><ArrowLeft size={16}/>返回商品列表</button>}{(!aurora||!narrow||detailVisible)&&children}</div><ContextPanel title="商品上下文"><dl className="product-context-facts"><dt>商品 ID</dt><dd>{selectedId}</dd><dt>监测状态</dt><dd>{selected?.monitoring_enabled?'监测中':'已暂停'}</dd><dt>最近采集</dt><dd>{selected?.last_collected_at?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'medium',timeStyle:'short'}).format(new Date(selected.last_collected_at)):'暂无采集记录'}</dd></dl>{context}{management}</ContextPanel>
  </section>;
}
