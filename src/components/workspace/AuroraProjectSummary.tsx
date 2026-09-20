import { ArrowRight, X } from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { LedgerSnapshot } from '../../types';
import type { getProjectFinancials } from '../../data/businessMetrics';
import { projectKindOf } from '../../data/projectKinds';
import { latestTerminalSettlementIssue } from '../../data/settlementIssues';
import { localPlatformService, type ProjectRequirementBlueprintView } from '../../data/localPlatformService';

type Item = ReturnType<typeof getProjectFinancials>[number];
const money = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 });
const statusLabels = { pending: '待开始', in_progress: '进行中', delivered: '已交付', completed: '已完成', overdue: '已逾期' };

/** A read-only selection preview. Mutations remain in the original explicit workflows. */
export function AuroraProjectSummary({ item, snapshot, open, onClose, onOpen, onEdit, onChangeOrder, onPayment }: {
  item?: Item; snapshot: LedgerSnapshot; open: boolean; onClose: () => void;
  onOpen: (id: string) => void; onEdit: (id: string) => void;
  onChangeOrder: (id: string) => void; onPayment: (id: string) => void;
}) {
  const [wide, setWide] = useState(() => window.matchMedia('(min-width:1440px)').matches);
  const [tab, setTab] = useState('overview');
  const [formal, setFormal] = useState<ProjectRequirementBlueprintView | null>(null);
  const [readState, setReadState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [reload, setReload] = useState(0);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const closeAction = useRef(onClose); closeAction.current = onClose;
  const project = item?.project;
  useEffect(() => {
    const media = window.matchMedia('(min-width:1440px)');
    const sync = () => setWide(media.matches);
    media.addEventListener('change', sync); return () => media.removeEventListener('change', sync);
  }, []);
  useEffect(() => { setTab('overview'); }, [project?.id]);
  useEffect(() => {
    if (!project || (!wide && !open)) return;
    let active = true; setFormal(null); setReadState('loading');
    void localPlatformService.projectRequirementBlueprints(project.id).then(rows => {
      if (active) { setFormal(rows.find(row => row.case_id) || null); setReadState('ready'); }
    }).catch(() => { if (active) setReadState('error'); });
    return () => { active = false; };
  }, [project?.id, wide, open, reload]);
  useEffect(() => {
    if (wide || !open || !project) return;
    const dialog = dialogRef.current;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.showModal(); closeRef.current?.focus();
    return () => { dialog?.close(); if (opener.current?.isConnected) opener.current.focus(); };
  }, [wide, open, project?.id]);
  if (!project || !item) return <aside className="aurora-panel aurora-project-summary aurora-project-summary-empty"><p>选择项目，查看需求、任务与交付摘要。</p></aside>;
  const personal = projectKindOf(project) === 'personal';
  const terminal = Boolean(latestTerminalSettlementIssue(item.settlementIssues));
  const customer = snapshot.customers.find(row => row.id === project.customerId);
  const tasks = snapshot.tasks.filter(row => row.projectId === project.id);
  const files = snapshot.attachments.filter(row => row.projectId === project.id);
  const sectionHref = (section: string) => '#' + encodeURIComponent(`项目管理/${project.id}/overview?section=${section}`);
  const content = <>
    <header><span className={`project-hub-badge status-${terminal ? 'terminated' : project.status}`}>{terminal ? '已终止' : statusLabels[project.status]}</span>{!wide && <button ref={closeRef} type="button" aria-label="关闭项目摘要" onClick={onClose}><X size={20} /></button>}</header>
    <h2 id="aurora-project-summary-title">{project.name}</h2>
    <p>{personal ? '个人项目' : customer?.name || '未关联客户'} · {project.type || '定制开发'}</p>
    <p className="aurora-project-notes">{project.notes || '暂无项目说明。'}</p>
    <nav aria-label="选中项目摘要">{[['overview', '概况'], ['tasks', `任务 ${tasks.length}`], ['files', `附件 ${files.length}`]].map(([key, label]) => <button type="button" key={key} aria-current={tab === key ? 'page' : undefined} onClick={() => setTab(key)}>{label}</button>)}</nav>
    {tab === 'overview' && <>
      <dl><div><dt>交付日期</dt><dd>{project.dueDate}</dd></div><div><dt>任务完成</dt><dd>{tasks.filter(task => task.status === 'done').length} / {tasks.length}</dd></div></dl>
      <section className="aurora-project-version"><h3>正式需求</h3>{readState === 'loading' ? <p role="status">正在读取正式需求…</p> : readState === 'error' ? <div role="alert"><p>正式需求读取失败，原记录保留。</p><button type="button" onClick={() => setReload(value => value + 1)}>重新读取</button></div> : formal ? <><strong>V{formal.version} · {formal.title}</strong><a href={sectionHref('requirements')}>需求、交付物与实际验收记录 <ArrowRight size={15} /></a></> : <p>尚未关联正式需求。<a href={sectionHref('requirements')}>查看需求入口</a></p>}</section>
      {!personal && <section className="aurora-project-finance"><h3>合同与回款</h3><dl><div><dt>合同总额</dt><dd>{money.format(project.totalAmount)}</dd></div><div><dt>确认已收</dt><dd>{money.format(item.income)}</dd></div><div><dt>待回款</dt><dd className="is-warning">{money.format(item.outstanding)}</dd></div></dl></section>}
      <p className="aurora-project-boundary">任务完成、项目交付、客户验收和确认收款分别记录。</p>
    </>}
    {tab === 'tasks' && <section className="aurora-project-preview-list"><h3>开发任务</h3>{tasks.length ? tasks.slice(0, 6).map(task => <article key={task.id}><span>{task.title}</span><small>{{todo:'待开始',in_progress:'进行中',done:'已完成',blocked:'受阻'}[task.status] || task.status}</small></article>) : <p>尚无开发任务。</p>}<a href={sectionHref('tasks')}>查看全部任务 <ArrowRight size={15} /></a><p>任务完成不代表客户已验收。</p></section>}
    {tab === 'files' && <section className="aurora-project-preview-list"><h3>附件记录</h3>{files.length ? files.slice(0, 6).map(file => <article key={file.id}><span>{file.name}</span></article>) : <p>尚无附件记录。</p>}<a href={sectionHref('records')}>查看附件与历史记录 <ArrowRight size={15} /></a></section>}
    <footer><button type="button" className="aurora-button primary" onClick={() => onOpen(project.id)}>查看详情 <ArrowRight size={15}/></button><button type="button" className="aurora-button" onClick={() => onEdit(project.id)}>编辑项目</button>{!personal && !terminal && <button type="button" className="aurora-button" onClick={() => onChangeOrder(project.id)}>追加订单</button>}{!personal && item.outstanding > 0 && <button type="button" className="aurora-button" onClick={() => onPayment(project.id)}>确认收款</button>}</footer>
  </>;
  if (wide) return <aside className="aurora-panel aurora-project-summary" aria-label="选中项目摘要">{content}</aside>;
  return open ? createPortal(<dialog ref={dialogRef} className="aurora-theme aurora-project-summary aurora-project-drawer" aria-labelledby="aurora-project-summary-title" onCancel={event => { event.preventDefault(); closeAction.current(); }} onClick={event => { if (event.target !== event.currentTarget) return; const box = event.currentTarget.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onClose(); }}>{content}</dialog>, document.body) : null;
}
