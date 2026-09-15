import { useEffect, useState } from 'react';
import type { LedgerSnapshot } from '../types';
import { daysUntil, getProjectFinancials } from '../data/businessMetrics';
import { localPlatformService } from '../data/localPlatformService';
import { subscribeCustomerEvents } from '../data/customerEvents';
import { ChatCircleDots, FileText, Paperclip, Flag, CurrencyCny, Warning, User, Folder, HandWaving, CaretRight, ChartBar } from '@phosphor-icons/react';
import './action-workbench.css';
import { buildRecords } from '../pages/OperatingRecordsPage';
import { ledgerDateKey, summarizeCashflow } from '../pages/operatingRecordsPeriod';
import { CashflowTrend } from './workspace/CashflowTrend';
import { CashflowOverview, cashMoney } from './workspace/CashflowOverview';

type Action = { id: string; category: string; title: string; detail: string; href: string; projectId?: string; time?:string };
const hash = (path: string) => `#${encodeURIComponent(path)}`;
const categories = ['全部','客户消息','待确认需求','待补资料','临近交付','待回款','异常事项'];
const actionGuidance: Record<string,string> = {
  客户消息:'查看未读内容，核对需要回复的问题。',
  待确认需求:'查看需求版本或提案，确认后再写入。',
  待补资料:'核对尚未明确的问题，补充需求依据。',
  临近交付:'核对交付物与验收项，确认交付安排。',
  待回款:'核对实际到账情况，再确认收款。',
  异常事项:'查看已记录的异常，核对处理情况。',
};
const categoryIcons = [ChatCircleDots, FileText, Paperclip, Flag, CurrencyCny, Warning, User, Folder, HandWaving, CaretRight, ChartBar];
export function ActionWorkbench({ snapshot, onConfirmPayment, connectionActions = [] }: {
  snapshot: LedgerSnapshot;
  onConfirmPayment: (projectId: string) => void;
  connectionActions?: Array<{ id: string; title: string; description: string; targetHash: string }>;
}) {
  const [remote, setRemote] = useState<Action[]>([]);
  const [state, setState] = useState('正在核对客户与需求待办…');
  const [category, setCategory] = useState('全部');
  const [refresh, setRefresh] = useState(0);
  const [sort, setSort] = useState('category');
  const customerIds = snapshot.customers.map(c=>c.id).join('|');
  useEffect(() => subscribeCustomerEvents(()=>setRefresh(v=>v+1)), []);
  useEffect(() => {
    let active = true;
    const rows: Action[] = [];
    setState('正在核对客户与需求待办…');
    let failures = 0;
    const load = async () => {
      try {
        const conversations = await localPlatformService.conversations('all');
        rows.push(...conversations.filter(c=>c.unread_count>0).map(c=>({id:`conversation-${c.id}`,category:'客户消息',time:c.last_message_at,title:c.customer_name,detail:`${c.unread_count} 条未读消息`,href:hash(`客户消息/conversation/${c.id}`)})));
      } catch { failures++; }
      // Bounded read-only requests; no model or platform collection is triggered.
      let index = 0;
      await Promise.all(Array.from({length:Math.min(3,snapshot.customers.length)},async()=>{
        while (active && index<snapshot.customers.length) {
          const customer = snapshot.customers[index++];
          const [cases, proposals] = await Promise.allSettled([localPlatformService.customerRequirements(customer.id),localPlatformService.requirementProposals(customer.id)]);
          if(cases.status==='fulfilled') for(const item of cases.value) {
            if(item.open_question_count>0) rows.push({id:`questions-${item.id}`,category:'待补资料',time:item.updated_at,title:item.title,detail:`${item.open_question_count} 项待确认问题`,href:hash(`客户管理/${customer.id}/requirements/${item.id}`)});
            else if(['discovery','clarifying','ready'].includes(item.status)) rows.push({id:`requirement-${item.id}`,category:'待确认需求',time:item.updated_at,title:item.title,detail:'正式需求尚未确认',href:hash(`客户管理/${customer.id}/requirements/${item.id}`)});
          } else failures++;
          if(proposals.status==='fulfilled' && proposals.value.length) rows.push({id:`proposals-${customer.id}`,category:'待确认需求',title:customer.name,detail:`${proposals.value.length} 份 GPT 拟写入提案`,href:hash(`客户管理/${customer.id}/requirements`)});
          else if(proposals.status==='rejected') failures++;
        }
      }));
      if(active){setRemote(rows);setState(failures?'部分客户或需求状态未能读取，请刷新重试。':'');}
    };
    void load(); return()=>{active=false;};
  }, [customerIds, refresh]);
  const projectActions: Action[] = getProjectFinancials(snapshot).flatMap(financial => {
    const {project} = financial;
    const actions: Action[] = [];
    const projectHref = (section:string)=>hash(`项目管理/${project.id}/overview?section=${section}`);
    if(!['delivered','completed'].includes(project.status) && daysUntil(project.dueDate)<=7) actions.push({id:`delivery-${project.id}`,category:'临近交付',time:project.dueDate,title:project.name,detail:`交付日期 ${project.dueDate}`,href:projectHref('requirements')});
    if(financial.outstanding>0) actions.push({id:`payment-${project.id}`,category:'待回款',title:project.name,detail:`待回款 ¥${financial.outstanding.toLocaleString('zh-CN')}`,href:projectHref('payments'),projectId:project.id});
    if(financial.issueCount) actions.push({id:`issue-${project.id}`,category:'异常事项',title:project.name,detail:`${financial.issueCount} 条已记录异常，请核对处理情况`,href:projectHref('records')});
    return actions;
  });
  const actions: Action[] = [...remote,...projectActions,...connectionActions.map(a=>({id:a.id,category:'异常事项',title:a.title,detail:a.description,href:a.targetHash}))];
  const shown = (category==='全部'?actions:actions.filter(a=>a.category===category)).slice().sort((a,b)=>sort==='recent' ? (Date.parse(b.time || '')||0)-(Date.parse(a.time || '')||0) : categories.indexOf(a.category)-categories.indexOf(b.category));
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
    <header><div><h2>最近消息</h2><p>共 {actions.length} 条待处理事项</p></div><div className="workbench-header-actions"><select aria-label="待办排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="category">按事项类型</option><option value="recent">按最近更新</option></select><button type="button" onClick={()=>setRefresh(v=>v+1)}>刷新</button></div></header>
    <nav aria-label="待办分类">{categories.map(label=><button key={label} type="button" aria-current={category===label?'page':undefined} onClick={()=>setCategory(label)}>{label}<span>{label==='全部'?actions.length:actions.filter(a=>a.category===label).length}</span></button>)}</nav>
    {state&&<p role="status">{state}</p>}
    <div className="workbench-column-head" aria-hidden="true"><span>客户 / 标题</span><span>最新消息</span><span>时间</span><span>操作</span></div>
    <div className="workbench-action-list">{shown.map(action=>{const KindIcon=categoryIcons[categories.indexOf(action.category)-1]||Warning;return <article key={action.id}><span className="workbench-object-cell"><i className={`workbench-category kind-${categories.indexOf(action.category)}`} title={action.category}><KindIcon size={22} weight="duotone"/></i><span className="workbench-action-object" title={action.title}>{action.title}</span></span><div><h2>{action.detail}</h2><p>{actionGuidance[action.category]}</p></div><time>{action.time && /^\d{4}-\d{2}-\d{2}$/.test(action.time) ? action.time.slice(5).replace('-','/') : action.time && Number.isFinite(Date.parse(action.time)) ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(action.time)) : '时间未记录'}</time>{action.projectId?<button type="button" onClick={()=>onConfirmPayment(action.projectId!)}>确认到账</button>:<a href={action.href} aria-label={`处理${action.category}：${action.title}`}>处理</a>}</article>})}</div>
    {!shown.length&&!state&&<div className="workbench-empty">当前分类没有已识别的待办。</div>}
    </section><aside className="workbench-context" aria-label="我的任务与收支概览">
      <section className="reference-my-tasks"><h2>我的任务</h2>{[['待我处理','全部',FileText],['待我确认','待确认需求',User],['即将到期','临近交付',Flag],['异常事项','异常事项',Warning]].map(([label,filter,Icon])=>{const KindIcon=Icon as typeof FileText;return <button key={String(label)} onClick={()=>setCategory(String(filter))}><KindIcon size={21}/><span>{String(label)}</span><b>{filter==='全部'?actions.length:actions.filter(a=>a.category===filter).length}</b></button>})}</section>
      <CashflowOverview income={cashflow.income} expenses={cashflow.expenses} period="本月" chart={points.length>1?<CashflowTrend points={points}/>:undefined}/>
      <a className="reference-analysis-link" href={hash('经营分析中心')}><ChartBar size={30} weight="duotone"/><span><b>经营分析</b><small>基于数据，发现问题，获得经营建议</small></span><CaretRight size={18}/></a>
      {dueToday.length>0&&<section><h2>今日安排</h2><ul className="workbench-schedule">{dueToday.map(project=><li key={project.id}><time>交付</time><a href={hash(`项目管理/${project.id}/overview?section=requirements`)}>{project.name}<small>核对需求与交付</small></a></li>)}</ul></section>}
    </aside></div></div>;
}
