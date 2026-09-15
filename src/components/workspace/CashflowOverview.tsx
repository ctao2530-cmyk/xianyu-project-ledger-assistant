import type { CSSProperties, ReactNode } from 'react';

export const cashMoney = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' });
export function CashflowOverview({ income, expenses, period, chart }: {
  income: number; expenses: number; period: string;
  chart?: ReactNode;
}) {
  const denominator = Math.max(0, income) + Math.max(0, expenses);
  const share = denominator ? Math.max(0, income) / denominator * 100 : 0;
  return <section className="reference-cashflow"><header><h3>收支概览</h3><span>{period}</span></header>
    <div className="reference-cashflow-values"><span>收入<strong>{cashMoney.format(income)}</strong></span><span>支出<strong>{cashMoney.format(expenses)}</strong></span></div>
    {chart ? chart : income < 0 ? <p className="reference-cashflow-legend">净收入为负，暂不计算收支占比。</p> : <><div className="reference-cashflow-ratio" data-empty={denominator === 0} style={{'--income-share': `${share}%`} as CSSProperties}><i/><i/></div><p className="reference-cashflow-legend"><span>收入 {share.toFixed(1)}%</span><span>支出 {denominator ? (100-share).toFixed(1) : '0.0'}%</span></p></>}
  </section>;
}
