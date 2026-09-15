import type { Customer, Project } from '../../types';
import type { ReactNode, Ref } from 'react';
import { X } from '@phosphor-icons/react';
export function CustomerContextPanel({customer,projects,pane,media,onViewProjects,onClose,closeButtonRef}:{customer?:Customer;projects:Project[];pane:string;media?:ReactNode;onViewProjects:()=>void;onClose:()=>void;closeButtonRef?:Ref<HTMLButtonElement>}) {
  return <aside id="customer-context-panel" className="workspace-context" aria-label="客户信息" onKeyDown={event=>{if(event.key==='Escape'&&!event.defaultPrevented){event.stopPropagation();onClose();}}}><header className="customer-context-heading"><span>客户信息</span><button ref={closeButtonRef} type="button" className="customer-context-close" aria-label="关闭客户资料" onClick={onClose}><X size={20}/></button></header><div className="customer-context-sections">{customer?<>
    <section><dl><dt>客户名称</dt><dd>{customer.name}</dd><dt>来源渠道</dt><dd>{customer.source==='xianyu'?'闲鱼':customer.source||'未记录'}</dd><dt>客户级别</dt><dd>{customer.level||'未记录'}</dd><dt>联系方式</dt><dd>{customer.phone||'尚未补充'}</dd></dl><h3>近期标签</h3><div className="customer-context-tags">{customer.tags?.length?customer.tags.map(tag=><span key={tag}>{tag}</span>):<small>暂无标签</small>}</div></section>
    {pane!=='requirements'&&<section><h3>当前需求摘要</h3><p>{customer.currentNeed||'尚未记录需求摘要'}</p></section>}
    {pane!=='projects'&&<section className="customer-context-projects"><header><h3>关联项目</h3>{projects.length>3&&<button type="button" onClick={onViewProjects}>查看全部（{projects.length}）</button>}</header>{projects.length?projects.slice(0,3).map(p=><a className="customer-context-project" key={p.id} href={`#${encodeURIComponent(`项目管理/${p.id}/overview`)}`}><span>{p.name}</span><small>{p.dueDate||'未设置交付日期'}</small></a>):<p>暂无关联项目</p>}</section>}
    <section><h3>下一步</h3><p>{customer.nextAction||'尚未记录下一步行动'}</p></section>
  </>:<section><p>尚未关联客户档案。请在会话“更多”中确认建档，系统不会按昵称推断身份。</p></section>}
    {media}
  </div></aside>;
}
