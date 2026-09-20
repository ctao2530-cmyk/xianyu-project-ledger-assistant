import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { BusinessAnalysisOverview } from '../../data/businessAnalysisService';

/** Read-only presentation of the two calendar periods already returned by the analysis API. */
export function AnalysisFacts({ overview }: { overview: BusinessAnalysisOverview }) {
  const { finance } = overview.metrics;
  const data = [
    { period: overview.period.previous_month_start.slice(0, 7), income: finance.income.previous, expenses: finance.expenses.previous },
    { period: overview.period.current_month_start.slice(0, 7), income: finance.income.current, expenses: finance.expenses.current },
  ];
  const chartReady = data.every(row => Number.isFinite(row.income) && Number.isFinite(row.expenses));
  return <section className="aurora-analysis-facts" aria-label="经营事实与来源">
    <header><div><h2>月度收支对比</h2><p>北京时间 · 当前分析快照</p></div><span>上月 / 本月</span></header>
    {chartReady ? <>
      <div className="aurora-analysis-chart" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <BarChart data={data} accessibilityLayer={false} margin={{ top: 16, right: 12, left: 0, bottom: 0 }} barGap={12}>
            <CartesianGrid stroke="#30463b" vertical={false} strokeDasharray="3 5" />
            <XAxis dataKey="period" stroke="#b9cdc2" tickLine={false} axisLine={false} fontSize={12} />
            <YAxis stroke="#b9cdc2" tickLine={false} axisLine={false} fontSize={12} width={52} />
            <Tooltip cursor={{ fill: '#193328' }} contentStyle={{ background: '#0d1a16', border: '1px solid #668373', borderRadius: 8, color: '#edf5f0' }} />
            <Bar dataKey="income" name="确认收入（元）" fill="#41df92" maxBarSize={44} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            <Bar dataKey="expenses" name="支出（元）" fill="#e6b878" maxBarSize={44} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="aurora-analysis-chart-key"><span><i />确认收入</span><span><i />支出</span><small>单位：元</small></div>
      <details className="aurora-analysis-source-details"><summary>数值与数据来源</summary>
        <table><caption className="sr-only">月度收支原始数值，单位元</caption><thead><tr><th>月份</th><th>确认收入</th><th>支出</th></tr></thead><tbody>{data.map(row => <tr key={row.period}><th>{row.period}</th><td>{row.income.toLocaleString('zh-CN')}</td><td>{row.expenses.toLocaleString('zh-CN')}</td></tr>)}</tbody></table>
        {overview.data_sources.map(source => <p key={source.id}><b>{source.label} · {source.available ? `${source.record_count} 条` : '缺失'}</b><span>{source.note}</span></p>)}
      </details>
    </> : <p className="aurora-analysis-chart-empty">缺少可比较的月度金额，暂不绘图。</p>}
    {overview.data_gaps.length > 0 && <aside className="aurora-analysis-gaps"><b>数据缺口</b><ul>{overview.data_gaps.map(gap => <li key={gap}>{gap}</li>)}</ul></aside>}
  </section>;
}
