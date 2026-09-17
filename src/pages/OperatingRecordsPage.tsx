import { ReceivablesBoard } from '../features/receivables/ReceivablesBoard';
import { buildRecords, validDate, type OperatingRecord, type OperatingRecordType, type TrackLane } from "../data/operatingRecords";
export { buildRecords } from "../data/operatingRecords";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Briefcase,
  CalendarBlank,
  CheckCircle,
  Clock,
  Coins,
  PencilSimple,
  Receipt,
  Trash,
  Wallet,
  X,
} from "@phosphor-icons/react";
import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { getBusinessSummary } from "../data/businessMetrics";
import type { LedgerSnapshot } from "../types";
import "./operating-records.css";
import { CashflowOverview } from "../components/workspace/CashflowOverview";
import { readUiSession, writeUiSession } from '../data/uiSession';
import { inLedgerPeriod, ledgerDateKey, ledgerMonthLabel, restoreRecordsPeriod, summarizeCashflow, validLedgerMonth } from './operatingRecordsPeriod';

interface OperatingRecordsPageProps {
  snapshot: LedgerSnapshot;
  globalSearch: string;
  onRecordExpense: () => void;
  onConfirmPayment: (projectId: string, paymentId?: string) => void;
  onCreatePaymentPlan: (projectId: string) => void;
  onNavigateProject: (projectId?: string) => void;
  onEditExpense: (expenseId: string) => void;
  onDeleteExpense: (expenseId: string) => void;
}

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
});

const dateKey = ledgerDateKey;

function formatDate(value: string) {
  const key = dateKey(value);
  return key === 'unknown' ? '日期待补充' : key.split('-').map(Number).join('/');
}

function formatShortDate(value: string) {
  const key = dateKey(value);
  return key === 'unknown' ? '--/--' : key.slice(5).split('-').map(Number).join('/');
}

function trackPosition(value: string, startDay: number, endDay: number) {
  const key = dateKey(value);
  if (key === 'unknown' || endDay <= startDay) return 50;
  return Math.min(92, Math.max(8, ((Number(key.slice(8)) - startDay) / (endDay - startDay)) * 100));
}

function buildAxisDays(startDay: number, endDay: number) {
  const length = endDay - startDay + 1;
  if (length <= 9) return Array.from({ length }, (_, index) => startDay + index);
  return Array.from(new Set(Array.from({ length: 8 }, (_, index) => Math.round(startDay + ((endDay - startDay) * index) / 7))));
}

function buildTrackHighlights(records: OperatingRecord[], limit = 4) {
  const groups = records.reduce<Array<{ key: string; records: OperatingRecord[] }>>((result, record) => {
    const key = dateKey(record.occurredAt);
    const existing = result.find((group) => group.key === key);
    if (existing) existing.records.push(record);
    else result.push({ key, records: [record] });
    return result;
  }, []).sort((left, right) => (validDate(left.records[0].occurredAt)?.getTime() || 0) - (validDate(right.records[0].occurredAt)?.getTime() || 0));

  const selected = groups.length <= limit
    ? groups
    : Array.from(new Set(Array.from({ length: limit }, (_, index) => Math.round(((groups.length - 1) * index) / (limit - 1))))).map((index) => groups[index]);

  return selected.map((group) => {
    const first = group.records[0];
    const amount = group.records.reduce((sum, record) => sum + record.amount, 0);
    const typeLabel = first.lane === "income" ? "收入" : first.lane === "expense" ? "支出" : "待回款";
    return {
      ...first,
      id: `track-${first.lane}-${group.key}`,
      title: group.records.length === 1 ? first.title : `${group.records.length} 笔${typeLabel}`,
      amount,
    };
  });
}

function ReceivablePicker({
  open,
  records,
  onClose,
  onConfirmPayment,
  onCreatePaymentPlan,
}: {
  open: boolean;
  records: OperatingRecord[];
  onClose: () => void;
  onConfirmPayment: (projectId: string, paymentId?: string) => void;
  onCreatePaymentPlan: (projectId: string) => void;
}) {
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => panelRef.current?.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
      )).filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, open]);

  if (!open) return null;
  return <div className="operating-receivable-layer">
    <button type="button" className="operating-receivable-scrim" aria-label="关闭待回款项目选择" onClick={onClose} />
    <aside ref={panelRef} className="operating-receivable-picker" role="dialog" aria-modal="true" aria-labelledby="receivable-picker-title" tabIndex={-1}>
      <header>
        <span><Wallet size={22} weight="duotone" /></span>
        <div><small>记录收入</small><h2 id="receivable-picker-title">选择真实待回款项目</h2><p>到账确认继续使用原有账本校验，不会新建虚构项目或金额。</p></div>
        <button type="button" aria-label="关闭" onClick={onClose}><X size={21} /></button>
      </header>
      <div className="operating-receivable-list">
        {records.map((record) => <article key={record.id}>
          <i><Briefcase size={20} weight="duotone" /></i>
          <span><b>{record.title}</b><small>{record.detail} · {formatDate(record.occurredAt)}</small></span>
          <strong>{money.format(record.amount)}</strong>
          <div>
            <button type="button" className="operating-secondary-action" onClick={() => { onCreatePaymentPlan(record.projectId!); onClose(); }}>收款计划</button>
            <button type="button" className="operating-primary-action" onClick={() => { onConfirmPayment(record.projectId!, record.paymentId); onClose(); }}>确认到账</button>
          </div>
        </article>)}
      </div>
      <footer><CheckCircle size={16} weight="fill" />只有完成确认的真实付款才会计入收入。</footer>
    </aside>
  </div>;
}

export function OperatingRecordsPage({
  snapshot,
  globalSearch,
  onRecordExpense,
  onConfirmPayment,
  onCreatePaymentPlan,
  onNavigateProject,
  onEditExpense,
  onDeleteExpense,
}: OperatingRecordsPageProps) {
  const currentMonth = dateKey(new Date().toISOString()).slice(0, 7);
  const [period, setPeriod] = useState(()=>restoreRecordsPeriod(readUiSession('records-period')));
  const [selectedMonth, setSelectedMonth] = useState(() => {
    const saved = readUiSession('records-month');
    return validLedgerMonth(saved) ? saved : currentMonth;
  });
  useEffect(() => writeUiSession('records-month', selectedMonth), [selectedMonth]);
  const [type, setType] = useState<"all" | OperatingRecordType>(()=>{
    const value=readUiSession('records-type');return ['income','expense','refund','receivable'].includes(value)?value as OperatingRecordType:'all';
  });
  const [projectId, setProjectId] = useState(()=>{const id=readUiSession('records-project');return snapshot.projects.some(p=>p.id===id)?id:'all';});
  useEffect(()=>{writeUiSession('records-period',period);writeUiSession('records-type',type);writeUiSession('records-project',projectId);},[period,type,projectId]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [analysisView, setAnalysisView] = useState(false);
  const [workspaceView, setWorkspaceView] = useState<'records' | 'receivables'>(() => readUiSession('records-view') === 'receivables' ? 'receivables' : 'records');
  useEffect(() => writeUiSession('records-view', workspaceView), [workspaceView]);
  const [search, setSearch] = useState(()=>readUiSession('records-search'));
  useEffect(()=>writeUiSession('records-search',search),[search]);
  const incomeButtonRef = useRef<HTMLButtonElement>(null);
  const summary = useMemo(() => getBusinessSummary(snapshot), [snapshot]);
  const records = useMemo(() => buildRecords(snapshot), [snapshot]);
  const receivables = records.filter((record) => record.type === "receivable");
  const rangeMonth = period === 'all' ? null : period === 'month' ? currentMonth : selectedMonth;
  const periodLabel = rangeMonth ? ledgerMonthLabel(rangeMonth) : '全部时间';
  const periodRecords = records.filter(record => inLedgerPeriod(record.occurredAt, rangeMonth));
  const cashflow = summarizeCashflow(periodRecords);
  const trackMonth = rangeMonth || selectedMonth;
  const trackRecords = records.filter(record => inLedgerPeriod(record.occurredAt, trackMonth) && (record.type !== 'refund' || record.amount !== 0));
  const currentDays = trackRecords.map(record => Number(dateKey(record.occurredAt).slice(8)));
  const monthLastDay = new Date(Date.UTC(Number(trackMonth.slice(0, 4)), Number(trackMonth.slice(5)), 0)).getUTCDate();
  const today = Number(dateKey(new Date().toISOString()).slice(8));
  const startDay = currentDays.length ? Math.min(...currentDays) : 1;
  const endDay = currentDays.length ? Math.max(...currentDays) : monthLastDay;
  const clampedEndDay = Math.min(monthLastDay, endDay);
  const axisDays = buildAxisDays(startDay, clampedEndDay);
  const query = (globalSearch || search).trim().toLowerCase();
  const filteredRecords = periodRecords.filter((record) => {
    if (type !== "all" && record.type !== type) return false;
    if (projectId !== "all" && record.projectId !== projectId) return false;
    if (query && !`${record.title} ${record.detail} ${record.status}`.toLowerCase().includes(query)) return false;
    return true;
  });
  const groupedRecords = filteredRecords.reduce<Array<{ key: string; label: string; records: OperatingRecord[] }>>((groups, record) => {
    const key = dateKey(record.occurredAt);
    const existing = groups.find((group) => group.key === key);
    if (existing) existing.records.push(record);
    else groups.push({ key, label: formatDate(record.occurredAt), records: [record] });
    return groups;
  }, []);

  const closePicker = () => {
    setPickerOpen(false);
    window.requestAnimationFrame(() => incomeButtonRef.current?.focus());
  };

  const laneRows: Array<{ lane: TrackLane; label: string }> = [
    { lane: "income", label: "收入" },
    { lane: "expense", label: "支出" },
    { lane: "receivable", label: "待回款" },
  ];

  return <div className="operating-records-page">
    <section className="operating-period-overview">
      <div className="operating-period-toolbar">
        <div className="operating-period-options" role="group" aria-label="记录时间范围">
          <button type="button" aria-pressed={period === 'all'} onClick={() => setPeriod('all')}>全部时间</button>
          <button type="button" aria-pressed={period === 'month'} onClick={() => setPeriod('month')}>本月</button>
          <button type="button" aria-pressed={period === 'history'} onClick={() => setPeriod('history')}>按月份</button>
        </div>
        {period === 'history' && <label className="operating-month-input">查看月份<input type="month" aria-label="查看月份" value={selectedMonth} onChange={event => { if (validLedgerMonth(event.target.value)) setSelectedMonth(event.target.value); }} /></label>}
        <span className="operating-period-label" aria-live="polite">{periodLabel} · {periodRecords.filter(record => record.type !== 'receivable').length} 笔收支</span>
      </div>
    <section className="operating-summary-strip" aria-label={`${periodLabel}经营摘要`}>
      <span><i className="record-summary-icon income" aria-hidden="true"><Receipt size={26} weight="fill"/></i><small>确认收入</small><b className="income">{money.format(cashflow.income)}</b></span>
      <i aria-hidden="true" />
      <span><i className="record-summary-icon expense" aria-hidden="true"><Wallet size={26} weight="fill"/></i><small>支出</small><b className="expense">{money.format(cashflow.expenses)}</b></span>
      <i aria-hidden="true" />
      <span><i className="record-summary-icon receivable" aria-hidden="true"><Clock size={26} weight="fill"/></i><small className="record-summary-heading">当前待回款<button type="button" aria-label="查看回款跟进" onClick={() => setWorkspaceView('receivables')}><ArrowRight size={18} /></button></small><b className="receivable">{money.format(summary.outstanding)}</b></span>
    </section>
      <p className="operating-period-note">汇总按所选时间计算，收入已扣退款；待回款为当前余额。下方筛选仅影响明细。</p>
    </section>

    <section className="operating-track-card">
      <nav className="operating-view-switch" aria-label="收支工作视图"><button type="button" aria-pressed={workspaceView === 'records'} onClick={() => setWorkspaceView('records')}>收支明细</button><button type="button" aria-pressed={workspaceView === 'receivables'} onClick={() => setWorkspaceView('receivables')}>回款跟进</button></nav>
      {workspaceView === 'receivables' ? <ReceivablesBoard snapshot={snapshot} onConfirmPayment={onConfirmPayment} onCreatePaymentPlan={onCreatePaymentPlan} /> : <>

      <details className="operating-track-optional" open={analysisView} onToggle={e=>setAnalysisView(e.currentTarget.open)}><summary>{analysisView?'返回收支明细':'切换分析视图 · 月收支轨道'}</summary>
      <header className="operating-history-track-heading"><h2>{ledgerMonthLabel(trackMonth)}收支轨道</h2>{period === 'all' && <label className="operating-month-input"><CalendarBlank size={16} />轨道月份<input type="month" aria-label="轨道月份" value={selectedMonth} onChange={event => { if (validLedgerMonth(event.target.value)) setSelectedMonth(event.target.value); }} /></label>}</header>
      <p className="operating-period-note">按月查看全部类型及项目；待回款按当前计划到期日展示，不代表该月历史余额。</p>
      <div className="operating-track-axis" aria-hidden="true">
        <span />
        <div>{axisDays.map((day) => <b key={day} style={{ left: `${trackPosition(`${trackMonth}-${String(day).padStart(2, '0')}`, startDay, clampedEndDay)}%` }}>{Number(trackMonth.slice(5))}/{day}{trackMonth === currentMonth && day === today ? <em>今天</em> : null}</b>)}</div>
      </div>
      <div className="operating-track-lanes">
        {laneRows.map(({ lane, label }) => {
          const laneRecords = buildTrackHighlights(trackRecords.filter((record) => record.lane === lane), lane === "receivable" ? 3 : 4);
          return <div className={`operating-track-lane lane-${lane}`} key={lane}>
            <strong>{label}</strong>
            <div className="operating-track-line">
              {axisDays.map((day) => <i key={day} style={{ left: `${trackPosition(`${trackMonth}-${String(day).padStart(2, '0')}`, startDay, clampedEndDay)}%` }} />)}
              {laneRecords.map((record) => {
                const position = trackPosition(record.occurredAt, startDay, clampedEndDay);
                return <article className={`track-event event-${record.type}`} key={record.id} style={{ "--record-position": `${position}%` } as CSSProperties}>
                  <span />
                  <div><b>{record.title}</b><small>{record.amount > 0 && record.type === "income" ? "+" : ""}{money.format(record.amount)}</small></div>
                </article>;
              })}
            </div>
          </div>;
        })}
      </div>
      <div className="operating-mobile-ledger" aria-label="所选月份经营轨道移动端列表">
        {trackRecords.map(record => <section key={record.id}><time>{formatDate(record.occurredAt)}</time><article className={`mobile-event event-${record.type}`}><i>{record.type === "income" ? <Coins size={18} /> : record.type === "expense" ? <Receipt size={18} /> : record.type === "refund" ? <ArrowDown size={18} /> : <Clock size={18} />}</i><span><b>{record.title}</b><small>{record.detail}</small></span><strong>{record.amount > 0 && record.type === "income" ? "+" : ""}{money.format(record.amount)}</strong></article></section>)}
      </div>
      {!trackRecords.length && <p className="operating-record-empty">该月暂无记录，可切换月份或返回全部时间。</p>}

      </details>
      <section className="operating-record-list" hidden={analysisView}>
        <header>
          <div><small>RECORDS</small><h3>记录明细 <span>· {filteredRecords.length} 条</span></h3></div>
          <div>
            <select aria-label="记录类型" value={type} onChange={(event) => setType(event.target.value as "all" | OperatingRecordType)}><option value="all">全部类型</option><option value="income">收入</option><option value="expense">支出</option><option value="receivable">待回款</option><option value="refund">退款</option></select>
            <select aria-label="关联项目" value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="all">全部项目</option>{snapshot.projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select>
            <input aria-label="搜索收支记录" placeholder="搜索收支记录…" value={globalSearch||search} disabled={Boolean(globalSearch)} onChange={e=>setSearch(e.target.value)}/>
            <button type="button" className="record-analysis-switch" onClick={()=>setAnalysisView(true)}>分析视图</button>
          </div>
        </header>
        {groupedRecords.length ? <div className="operating-record-groups"><div className="records-column-head" aria-hidden="true"><span>时间</span><span>收支事项</span><span>类型</span><span>关联项目</span><span>金额</span><span>状态</span><span>操作</span></div>{groupedRecords.map((group) => <section key={group.key}>
          <time>{group.label}</time>
          {group.records.map((record) => <article className={`operating-record-row event-${record.type}`} key={record.id}>
            <time className="record-clock" dateTime={record.occurredAt}>{record.occurredAt.includes('T')&&Number.isFinite(Date.parse(record.occurredAt))?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(record.occurredAt)):'—'}</time>
            <span><b>{record.title}</b><small>{record.detail}</small></span>
            <em>{record.type === "income" ? "收入" : record.type === "expense" ? "支出" : record.type === "refund" ? "退款" : "待回款"}</em>
            <span className="record-project">{record.projectId ? snapshot.projects.find((project) => project.id === record.projectId)?.name || "项目已归档" : "未关联项目"}</span>
            <strong>{record.amount > 0 && record.type === "income" ? "+" : ""}{money.format(record.amount)}</strong>
            <span className="record-status">{record.status}</span>
            <div className="record-actions">
              {record.projectId && record.type!=='receivable' && <button type="button" onClick={()=>onNavigateProject(record.projectId!)}>查看项目</button>}
              {record.type === "receivable" && record.projectId && <button type="button" className="settle-action" onClick={() => onConfirmPayment(record.projectId!, record.paymentId)}>去结算</button>}
              {record.type === "expense" && record.expenseId && <ActionMenu iconOnly label={`更多：${record.title}`}><button type="button" aria-label={`编辑 ${record.title}`} onClick={() => onEditExpense(record.expenseId!)}><PencilSimple size={17} />编辑支出</button><button type="button" aria-label={`删除 ${record.title}`} onClick={() => onDeleteExpense(record.expenseId!)}><Trash size={17} />删除支出</button></ActionMenu>}
            </div>
          </article>)}
        </section>)}</div> : <div className="operating-record-empty"><Wallet size={28} weight="duotone" /><b>当前筛选下没有经营记录</b><small>{globalSearch ? "可以清除顶部搜索或调整筛选条件。" : "可切换月份、查看全部时间，或调整类型与项目筛选。"}</small>{period !== 'all' && <button type="button" className="record-analysis-switch" onClick={() => setPeriod('all')}>查看全部时间</button>}</div>}
      </section>
      </>}
    </section>

    <aside className="reference-records-context" aria-label="收支操作与回款提醒">
      <div className="operating-record-actions" aria-label="经营记录操作"><h3>快速操作</h3>
        <button ref={incomeButtonRef} type="button" className="record-income-button" disabled={!receivables.length} title={receivables.length ? "从真实待回款项目中确认收入" : "当前没有待回款项目"} onClick={() => setPickerOpen(true)}><ArrowUp size={18} />记录收入</button>
        <button type="button" className="record-expense-button" onClick={onRecordExpense}><ArrowDown size={18} />记录支出</button>
      </div>

      <CashflowOverview income={cashflow.income} expenses={cashflow.expenses} period={periodLabel}/><section className="records-accounting-note"><Receipt size={24}/><p>收入以确认到账为准，<br/>待回款不计入已收收入。</p></section>
    </aside>
    <ReceivablePicker open={pickerOpen} records={receivables} onClose={closePicker} onConfirmPayment={onConfirmPayment} onCreatePaymentPlan={onCreatePaymentPlan} />
  </div>;
}
import { ActionMenu } from '../components/workspace/ActionMenu';
