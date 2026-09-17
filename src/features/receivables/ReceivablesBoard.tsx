import { useEffect, useMemo, useState } from 'react';
import type { LedgerSnapshot } from '../../types';
import { businessDate } from '../../shared/time/businessDate';
import { agingBuckets, buildReceivableAging, sumReceivables, type AgingBucket } from './model';
import './receivables.css';
const money = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' });

export function ReceivablesBoard({ snapshot, onConfirmPayment, onCreatePaymentPlan }: {
  snapshot: LedgerSnapshot; onConfirmPayment: (projectId: string, paymentId?: string) => void;
  onCreatePaymentPlan: (projectId: string) => void;
}) {
  const [today, setToday] = useState(() => businessDate());
  const [bucket, setBucket] = useState<AgingBucket | 'all'>('all');
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(10);
  useEffect(() => {
    const update = () => setToday(businessDate());
    const timer = window.setInterval(update, 60000);
    window.addEventListener('focus', update); document.addEventListener('visibilitychange', update);
    return () => { window.clearInterval(timer); window.removeEventListener('focus', update); document.removeEventListener('visibilitychange', update); };
  }, []);
  const rows = useMemo(() => buildReceivableAging(snapshot, new Date(`${today}T12:00:00+08:00`)), [snapshot, today]);
  const total = sumReceivables(rows);
  const filtered = rows.filter(row => (bucket === 'all' || row.bucket === bucket) && `${row.projectName} ${row.customerName}`.toLowerCase().includes(search.trim().toLowerCase()));
  useEffect(() => setLimit(10), [bucket, search]);
  return <section className="receivables-board" aria-labelledby="receivables-title">
    <header><div><h2 id="receivables-title">回款跟进</h2><p>截至北京日期 {today} · 当前接单项目余额，含已终止项目的剩余待收。</p></div><button type="button" aria-pressed={bucket === 'all'} onClick={() => setBucket('all')}>全部待收 <strong>{money.format(total)}</strong></button></header>
    <div className="receivables-buckets" role="group" aria-label="按回款账龄筛选">{agingBuckets.map(item => {
      const members = rows.filter(row => row.bucket === item.id); const amount = sumReceivables(members);
      return <button type="button" key={item.id} aria-pressed={bucket === item.id} className={`bucket-${item.id}`} onClick={() => setBucket(item.id)}>
        <span>{item.label}</span><strong>{money.format(amount)}</strong><small>{members.length} 项 · {new Set(members.map(row => row.projectId)).size} 个项目</small>
        <span className="receivables-bar" aria-hidden="true"><i style={{ width: `${total > 0 ? Math.min(100, amount / total * 100) : 0}%` }}/></span>
      </button>;
    })}</div>
    <p className="receivables-scope">按已约定收款日期分层，不以项目交付日期代替；本看板不受上方月份或收支明细筛选影响。</p>
    <div className="receivables-toolbar"><label>查找项目或客户<input value={search} onChange={e => setSearch(e.target.value)} placeholder="输入名称筛选" /></label><span role="status">{bucket === 'all' ? '全部账龄' : agingBuckets.find(item => item.id === bucket)?.label} · {filtered.length} 项 · {money.format(sumReceivables(filtered))}</span>{(search || bucket !== 'all') && <button type="button" onClick={() => { setSearch(''); setBucket('all'); }}>清空筛选</button>}</div>
    <ul className="receivables-rows" aria-label="待回款明细">{filtered.slice(0, limit).map(row => <li key={row.id}>
      <div className="receivables-object"><b>{row.projectName}</b><small>{row.customerName}{row.terminal ? ' · 已终止，保留结算' : ''}</small></div>
      <div className={`receivables-due bucket-${row.bucket}`}><b>{row.dueDate || (row.bucket === 'review' ? '请核对收款计划' : '日期待约定')}</b><small>{row.reason}</small></div>
      <strong className="receivables-amount">{money.format(row.amount)}</strong>
      <div className="receivables-actions"><a href={`#${encodeURIComponent(`项目管理/${row.projectId}/overview?section=payments`)}`}>查看项目</a>{row.bucket === 'review' ? null : <button type="button" onClick={() => onConfirmPayment(row.projectId, row.paymentId)}>确认到账</button>}{!row.paymentId && row.bucket === 'undated' && !row.terminal && <button type="button" onClick={() => onCreatePaymentPlan(row.projectId)}>安排收款</button>}</div>
    </li>)}</ul>
    {!filtered.length && <div className="receivables-empty">{rows.length ? '当前筛选没有待回款，可清空筛选查看全部。' : '当前没有接单项目待回款。'}</div>}
    {filtered.length > limit && <button type="button" className="receivables-more" onClick={() => setLimit(value => value + 10)}>再显示 10 项 · 剩余 {filtered.length - limit} 项</button>}
    <details className="receivables-method"><summary>查看统计口径</summary><p>余额复用统一账本的已收、退款及结算规则。一个项目可分布于多个账龄；分组金额合计等于当前接单待收余额。未收节点金额超出余额或归属异常时，整个项目放入“计划待核对”，不猜测分摊。看板不计作收入，确认到账仍需在原有表单中明确提交。</p></details>
  </section>;
}
