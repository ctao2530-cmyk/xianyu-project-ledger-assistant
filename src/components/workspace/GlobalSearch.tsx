import { useEffect, useRef, useState } from 'react';
import { MagnifyingGlass } from '@phosphor-icons/react';
import type { LedgerSnapshot } from '../../types';
import { localPlatformService } from '../../data/localPlatformService';

type Result = { id:string; title:string; kind:string; href:string };
const route=(path:string)=>`#${encodeURIComponent(path)}`;
export function GlobalSearch({snapshot,onOpen,dismiss}:{snapshot:LedgerSnapshot;onOpen:()=>void;dismiss:boolean}) {
  const [query,setQuery]=useState(''); const [open,setOpen]=useState(false);
  const [remote,setRemote]=useState<Result[]>([]); const [status,setStatus]=useState('');
  const root=useRef<HTMLDivElement>(null);
  const focusTimer=useRef<number|undefined>(undefined);
  useEffect(()=>()=>window.clearTimeout(focusTimer.current),[]);
  const openCallback=useRef(onOpen); openCallback.current=onOpen;
  useEffect(()=>{if(dismiss){window.clearTimeout(focusTimer.current);setOpen(false)}},[dismiss]);
  useEffect(()=>{
    const shortcut=(event:KeyboardEvent)=>{
      if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){
        event.preventDefault();openCallback.current();setOpen(true);
        window.requestAnimationFrame(()=>root.current?.querySelector('input')?.focus());
      }
    };
    window.addEventListener('keydown',shortcut);
    return()=>window.removeEventListener('keydown',shortcut);
  },[]);
  useEffect(()=>{const close=(e:PointerEvent)=>{if(!root.current?.contains(e.target as Node))setOpen(false)};document.addEventListener('pointerdown',close);return()=>document.removeEventListener('pointerdown',close)},[]);
  useEffect(()=>{
    let live=true;setRemote([]);setStatus('');
    if(!open||query.trim().length<2)return;
    const timer=setTimeout(()=>{void(async()=>{
      setStatus('正在检索本机会话与正式需求…'); const rows:Result[]=[];let failed=false;
      try {const conversations=await localPlatformService.conversations('all');rows.push(...conversations.map(c=>({id:`conversation-${c.id}`,kind:'会话',title:c.customer_name,href:route(`客户消息/conversation/${c.id}`)})))}catch{failed=true}
      let next=0;
      await Promise.all(Array.from({length:Math.min(3,snapshot.customers.length)},async()=>{while(live&&next<snapshot.customers.length){const c=snapshot.customers[next++];try{const cases=await localPlatformService.customerRequirements(c.id);rows.push(...cases.map(r=>({id:`case-${r.id}`,kind:'正式需求',title:r.title,href:route(`客户管理/${c.id}/requirements/${r.id}`)})))}catch{failed=true}}}));
      if(live){setRemote(rows);setStatus(failed?'部分会话或需求未能读取；下方结果可能不完整。':'')}
    })()},300);return()=>{live=false;clearTimeout(timer)};
  },[query,snapshot.customers,open]);
  const needle=query.trim().toLowerCase();
  const results:Result[]=[...snapshot.customers.map(c=>({id:`customer-${c.id}`,title:c.name,kind:'客户',href:route(`客户消息/customer/${c.id}?view=requirements`)})),...snapshot.projects.map(p=>({id:`project-${p.id}`,title:p.name,kind:'项目',href:route(`项目管理/${p.id}/overview`)})),...remote];
  const matches=results.filter(r=>r.title.toLowerCase().includes(needle));
  return <div className={`workspace-search compact-global-search ${open?'is-open':''}`} ref={root} onKeyDown={e=>{if(e.key==='Escape'){window.clearTimeout(focusTimer.current);root.current?.querySelector<HTMLElement>('.workspace-search-toggle')?.focus();setOpen(false)}if(e.key==='ArrowDown'&&e.target===root.current?.querySelector('input')){e.preventDefault();root.current?.querySelector('a')?.focus()}}}>
    <button className="workspace-search-toggle" aria-label="打开全局搜索" aria-expanded={open} onClick={()=>{if(!open)onOpen();setOpen(value=>!value);focusTimer.current=window.setTimeout(()=>root.current?.querySelector('input')?.focus(),0)}}><MagnifyingGlass size={18}/><span>搜索客户、项目、需求…</span><kbd>⌘K</kbd></button>
    <label className="search-box"><MagnifyingGlass size={20} aria-hidden="true"/><input aria-label="全局搜索客户、需求、项目" aria-keyshortcuts="Meta+K Control+K" placeholder="搜索客户、会话、需求、项目" value={query} onFocus={()=>setOpen(true)} onChange={e=>{setQuery(e.target.value);setOpen(true)}} aria-expanded={open&&!!needle} aria-controls="workspace-search-results"/><kbd className="workspace-search-shortcut" aria-hidden="true">⌘ K</kbd></label>
    {open&&needle&&<section id="workspace-search-results" className="workspace-search-results" aria-label="全局搜索结果"><p role="status">{needle.length<2?'输入至少两个字可继续搜索会话与需求。':status||`找到 ${matches.length} 项`}</p>{matches.map(r=><a key={r.id} href={r.href} onClick={()=>setOpen(false)}><small>{r.kind}</small><span>{r.title}</span></a>)}{!matches.length&&!status&&<p>未找到匹配对象，请调整关键词。</p>}</section>}
  </div>;
}
