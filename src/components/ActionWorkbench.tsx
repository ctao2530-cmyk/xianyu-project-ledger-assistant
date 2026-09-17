import { useWorkbenchActions, type WorkbenchAction as Action } from './workbench/useWorkbenchActions';
import { useState } from 'react';
import type { LedgerSnapshot } from '../types';
import { projectActions as buildProjectActions, sortActions, categories } from '../features/workbench/domain';
import { ChatCircleDots, FileText, Paperclip, Flag, CurrencyCny, Warning, User, Folder, HandWaving, CaretRight, ChartBar } from '@phosphor-icons/react';
import './action-workbench.css';
import { buildRecords } from '../data/operatingRecords';
import { ledgerDateKey, summarizeCashflow } from '../data/ledgerPeriod';
import { CashflowTrend } from './workspace/CashflowTrend';
import { CashflowOverview, cashMoney } from './workspace/CashflowOverview';

const hash = (path: string) => `#${encodeURIComponent(path)}`;

const actionGuidance: Record<string,string> = {
  客户消息:'查看未读内容，核对需要回复的问题。',
  待确认需求:'查看需求版本或提案，确认后再写入。',
  待补资料:'核对尚未明确的问题，补充需求依据。',
  已逾期:'核对延期原因与交付安排，记录实际进展。',
  临近交付:'核对交付物与验收项，确认交付安排。',
  待回款:'核对实际到账情况，再确认收款。',
  异常事项:'查看已记录的异常，核对处理情况。',
};
const categoryIcons = [ChatCircleDots, FileText, Paperclip, Warning, Flag, CurrencyCny, Warning];
export function ActionWorkbench({ snapshot, onConfirmPayment, connectionActions = [] }: {
  snapshot: LedgerSnapshot;
  onConfirmPayment: (projectId: string) => void;
  connectionActions?: Array<{ id: string; title: string; description: string; targetHash: string }>;
}) {
  const { remote, state, refresh, hasMore, loadMore } = useWorkbenchActions(snapshot);
  const [category, setCategory] = useState('全部');
  const [sort, setSort] = useState('category');
  const projectActions = buildProjectActions(snapshot);
  const actions: Action[] = [...remote,...projectActions,...connectionActions.map(a=>({id:a.id,category:'异常事项',title:a.title,detail:a.description,href:a.targetHash}))];
  const shown = sortActions(category==='全部'?actions:actions.filter(a=>a.category===category), sort);
  const today = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const dueToday = snapshot.projects.filter(project=>project.dueDate===today&&!['delivered','completed'].includes(project.status));
  const month = today.slice(0,7);
  const monthRecords = buildRecords(snapshot).filter(record=>ledgerDateKey(record.occurredAt).startsWith(month));
  const cashflow = summarizeCashflow(monthRecords);
  const pointDates = [...new Set(monthRecords.filter(r=>r.type!=='receivable').map(r=>ledgerDateKey(r.occurredAt)))].sort();
  const points = pointDates.map(date=>({date,...summarizeCashflow(monthRecords.filter(r=>ledgerDateKey(r.occurredAt)===date))}));
  const hour = Number(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',hourCycle:'h23'}).format(new Date()));
  const metrics = [
    {label:'待处理消息',value:state ? '—' : remote.filter(a=>a.category==='客户消息').length,icon:ChatCircleDots,tone:'blue',note:'有未读消息的会话',href:hash('客户消息')},
    {label:'客户总数',value:snapshot.customers.length,icon:User,tone:'green',note:'已建立的客户档案',href:hash('客户管理')},
    {label:'进行中项目',value:snapshot.projects.filter(p=>p.status==='in_progress').length,icon:Folder,tone:'purple',note:'当前正在推进',href:hash('项目管理')},
    {label:'本月收入',value:cashMoney.format(cashflow.income),icon:CurrencyCny,tone:'orange',note:'确认到账，已扣退款',href:hash('经营记录')},
  ];
  return <div className="reference-home">
    <section className="reference-welcome"><HandWaving size={44} weight="duotone"/><div><h1>{hour<12?'上午好':hour<18?'下午好':'晚上好'}，{snapshot.settings.profileName || '经营者'}</h1><p>今天是 {new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'}).format(new Date())}，一起让生意更有序地增长吧！</p></div><img src="/assets/xunying/reference-welcome-mountains.png" alt=""/><span>专注 · 高效 · 成长</span></section>
    <section className="reference-home-metrics" aria-label="工作台经营摘要">{metrics.map(({label,value,icon:Icon,tone,note,href})=><a href={href} className={`reference-home-metric tone-${tone}`} key={label}><i><Icon size={28} weight="duotone"/></i><span>{label}<strong>{value}</strong></span><small>{note}</small></a>)}</section>
    <div className="reference-workbench-grid"><section className="action-workbench">
    <header><div><h2>待处理事项</h2><p>{state || hasMore ? '当前已加载' : '共'} {actions.length} 条待处理事项</p></div><div className="workbench-header-actions"><select aria-label="待办排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="category">按事项类型</option><option value="recent">按最近更新</option><option value="due">按交付日期</option></select><button type="button" onClick={refresh}>刷新</button></div></header>
    <nav aria-label="待办分类">{categories.map(label=><button key={label} type="button" aria-current={category===label?'page':undefined} onClick={()=>setCategory(label)}>{label}<span>{label==='全部'?actions.length:actions.filter(a=>a.category===label).length}</span></button>)}</nav>
    {state&&<p role="status">{state}</p>}{hasMore&&<p role="status">客户待办尚有更多结果，分类和排序仅覆盖当前已加载事项。</p>}
    <div className="workbench-column-head" aria-hidden="true"><span>客户 / 标题</span><span>下一步</span><span>时间</span><span>操作</span></div>
    <div className="workbench-action-list">{shown.map(action=>{const KindIcon=categoryIcons[categories.indexOf(action.category)-1]||Warning;return <article key={action.id}><span className="workbench-object-cell"><i className={`workbench-category kind-${categories.indexOf(action.category)}`} title={action.category}><KindIcon size={22} weight="duotone"/></i><span className="workbench-action-object" title={action.title}>{action.title}</span></span><div><h2>{action.detail}</h2><p>{actionGuidance[action.category]}</p></div><time title={action.dueAt ? '交付日期' : '最近更新'}>{action.dueAt ? `交付 ${action.dueAt.slice(5).replace('-','/')}` : action.updatedAt && Number.isFinite(Date.parse(action.updatedAt)) ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(action.updatedAt)) : '更新时间未记录'}</time>{action.projectId?<button type="button" onClick={()=>onConfirmPayment(action.projectId!)}>确认到账</button>:<a href={action.href} aria-label={`处理${action.category}：${action.title}`}>处理</a>}</article>})}</div>
    {hasMore&&<button type="button" disabled={!!state} onClick={loadMore}>加载更多客户待办</button>}{!shown.length&&!state&&<div className="workbench-empty">当前分类没有已识别的待办。</div>}
    </section><aside className="workbench-context" aria-label="我的任务与收支概览">
      <section className="reference-my-tasks"><h2>我的任务</h2>{[['待我处理','全部',FileText],['待我确认','待确认需求',User],['即将到期','临近交付',Flag],['异常事项','异常事项',Warning]].map(([label,filter,Icon])=>{const KindIcon=Icon as typeof FileText;return <button key={String(label)} onClick={()=>setCategory(String(filter))}><KindIcon size={21}/><span>{String(label)}</span><b>{filter==='全部'?actions.length:actions.filter(a=>a.category===filter).length}</b></button>})}</section>
      <CashflowOverview income={cashflow.income} expenses={cashflow.expenses} period="本月" chart={points.length>1?<CashflowTrend points={points}/>:undefined}/>
      <a className="reference-analysis-link" href={hash('经营分析中心')}><ChartBar size={30} weight="duotone"/><span><b>经营分析</b><small>基于数据，发现问题，获得经营建议</small></span><CaretRight size={18}/></a>
      {dueToday.length>0&&<section><h2>今日安排</h2><ul className="workbench-schedule">{dueToday.map(project=><li key={project.id}><time>交付</time><a href={hash(`项目管理/${project.id}/overview?section=requirements`)}>{project.name}<small>核对需求与交付</small></a></li>)}</ul></section>}
    </aside></div></div>;
}
