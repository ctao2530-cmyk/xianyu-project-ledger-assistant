import type { ReactNode } from 'react';
import { ArrowRight, CalendarBlank, ChatCircleDots, CurrencyCny, FileText, Flag, Plus, Warning, type Icon } from '@phosphor-icons/react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { LedgerSnapshot, Project } from '../../types';
import type { WorkbenchAction } from './useWorkbenchActions';
import { cashMoney } from '../workspace/CashflowOverview';

export interface AuroraHomeContent {
  outstanding: number;
  outstandingCount: number;
  onProjects: () => void;
  onQuickAccounting: () => void;
  onAnalysis: () => void;
  reminders: ReactNode;
  projects: ReactNode;
  recent: ReactNode;
}
type Metric = { label: string; value: string | number; icon: Icon; note: string; href: string };
type Point = { date: string; income: number; expenses: number };
const quickFilters = [
  { label: '待我处理', filter: '全部', icon: FileText },
  { label: '待我确认', filter: '待确认需求', icon: ChatCircleDots },
  { label: '即将到期', filter: '临近交付', icon: Flag },
  { label: '异常事项', filter: '异常事项', icon: Warning },
];

/** Presentation only. Values, query state and callbacks belong to the existing home controller. */
export function AuroraWorkbench({ content, taskList, cashflow, points, metrics, actions, state,
  hasMore, dueToday, category, onCategoryChange }: {
  snapshot: LedgerSnapshot;
  content: AuroraHomeContent;
  taskList: ReactNode;
  cashflow: { income: number; expenses: number };
  points: Point[];
  metrics: Metric[];
  actions: WorkbenchAction[];
  state: string;
  hasMore: boolean;
  dueToday: Project[];
  category: string;
  onCategoryChange: (category: string) => void;
  hour: number;
}) {
  const summaries: Metric[] = [metrics[3],
    { label: '待回款', value: cashMoney.format(content.outstanding), icon: CurrencyCny,
      note: `${content.outstandingCount} 个项目尚未结清 · 当前余额`, href: '#' + encodeURIComponent('经营记录') },
    metrics[2],
  ];
  const openAgent = () => window.dispatchEvent(new Event('xunying:global-agent-open'));
  const filter = (value: string) => {
    onCategoryChange(value);
    document.querySelector('.aurora-home .action-workbench')?.scrollIntoView({ block: 'nearest' });
  };
  return <div className="aurora-theme aurora-home">
    <div className="aurora-home-grid">
      <nav className="aurora-panel aurora-home-shortcuts" aria-label="工作台快捷操作">
        <button type="button" className="aurora-button primary" onClick={content.onProjects}><Plus size={18} />项目管理 / 新建</button>
        <button type="button" className="aurora-button" onClick={content.onQuickAccounting}><CurrencyCny size={18} />记录一笔收款</button>
      </nav>
      <div className="aurora-home-summary" aria-label="工作台经营摘要">
        {summaries.map(({ label, value, icon: MetricIcon, note, href }) => <a className="aurora-panel aurora-home-metric" href={href} key={label}>
          <div><span>{label}<ArrowRight size={14} /></span><strong>{value}</strong><small>{note}</small></div><i><MetricIcon size={27} weight="duotone" /></i>
        </a>)}
      </div>
      <div className="aurora-home-tasks">{taskList}</div>
      <div className="aurora-home-reminders">{content.reminders}
        <div className="aurora-home-quick-filters" aria-label="我的任务">
          {quickFilters.map(({ label, filter: value, icon: FilterIcon }) => <button type="button" key={value} aria-pressed={category === value} onClick={() => filter(value)}><FilterIcon size={18} /><span>{label}</span><b>{state || hasMore ? '已加载 ' : ''}{value === '全部' ? actions.length : actions.filter(action => action.category === value).length}</b></button>)}
        </div>
        {dueToday.length > 0 && <section className="aurora-today-delivery"><h3><CalendarBlank size={18} />今日交付</h3>{dueToday.map(project => <a key={project.id} href={'#' + encodeURIComponent(`项目管理/${project.id}/overview?section=requirements`)}>{project.name}<ArrowRight size={16} /></a>)}</section>}
      </div>
      <aside className="aurora-panel aurora-home-partner" aria-label="小策与任务快捷入口">
        <header><h2>小策</h2><span className="aurora-chip neutral">AI 合伙人</span></header>
        <div className="aurora-partner-mark" aria-hidden="true"><img src="/assets/xunying/xiaoce-avatar.png" alt="" /></div>
        <h3>理清下一步，再行动。</h3><p>带着具体问题，与小策一起梳理需求、核对事实和讨论方案。</p>
        <button type="button" className="aurora-button" onClick={openAgent}>打开小策对话<ArrowRight size={16} /></button>
        <div className="aurora-home-context-links">{metrics.slice(0, 2).map(metric => <a href={metric.href} key={metric.label}><span>{metric.label}</span><strong>{metric.value}</strong></a>)}</div>
        <button type="button" className="aurora-home-analysis" onClick={content.onAnalysis}>查看经营分析<ArrowRight size={16} /></button>
      </aside>
      <div className="aurora-home-lower">
      <div className="aurora-home-recent">{content.recent}</div>
      <section className="aurora-panel aurora-home-trend">
        <header><h2>本月收支趋势</h2><span>已记录日期</span></header>
        <div className="aurora-home-trend-values"><span>收入<strong>{cashMoney.format(cashflow.income)}</strong></span><span>支出<strong>{cashMoney.format(cashflow.expenses)}</strong></span></div>
        {points.length ? <div className="aurora-home-chart" role="img" aria-label="本月已记录日期的确认收入与支出，收入已扣退款">
          <ResponsiveContainer width="100%" height="100%"><BarChart data={points} margin={{ top: 12, right: 0, left: -18, bottom: 0 }} barGap={4}>
            <CartesianGrid vertical={false} stroke="rgba(190,237,210,.12)" /><XAxis dataKey="date" tickFormatter={value => value.slice(5).replace('-', '/')} tick={{ fill: '#b9cdc2', fontSize: 12 }} axisLine={false} tickLine={false} minTickGap={20} />
            <YAxis tick={{ fill: '#b9cdc2', fontSize: 12 }} axisLine={false} tickLine={false} width={56} />
            <Tooltip cursor={{ fill: 'rgba(65,223,146,.06)' }} contentStyle={{ background: '#0d1a16', border: '1px solid #668373', borderRadius: 8, color: '#edf5f0' }} formatter={value => cashMoney.format(Number(value))} />
            <Bar dataKey="income" name="收入（已扣退款）" fill="#41df92" radius={[3, 3, 0, 0]} maxBarSize={28} isAnimationActive={false} />
            <Bar dataKey="expenses" name="支出" fill="#f3ba83" radius={[3, 3, 0, 0]} maxBarSize={28} isAnimationActive={false} />
          </BarChart></ResponsiveContainer>
        </div> : <p className="aurora-home-empty">本月暂无已记录收支。确认到账或记录支出后显示。</p>}
        <p className="aurora-home-chart-note">北京时间 · 收入已扣退款<span><i />收入<i />支出</span></p>
      </section>
      <div className="aurora-home-projects">{content.projects}</div>
      </div>
    </div>
  </div>;
}
