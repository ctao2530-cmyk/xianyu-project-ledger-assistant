import {
  ArrowClockwise,
  CalendarBlank,
  CheckCircle,
  CurrencyCircleDollar,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { getProjectFinancials } from "../data/businessMetrics";
import { LedgerRevisionConflictError } from "../data/mockService";
import {
  settlementIssueOptions,
  terminalSettlementIssueTypes,
} from "../data/settlementIssues";
import type {
  LedgerSnapshot,
  SettlementIssueType,
  SettlementIssueValue,
} from "../types";

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
});

function localDateTimeValue() {
  const date = new Date();
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function requestId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `issue-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

export interface SettlementIssueTarget {
  projectId: string;
}

export function SettlementIssueModal({
  snapshot,
  target,
  onClose,
  onSubmit,
  onRefresh,
}: {
  snapshot: LedgerSnapshot;
  target: SettlementIssueTarget;
  onClose: () => void;
  onSubmit: (value: SettlementIssueValue) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const project = snapshot.projects.find((item) => item.id === target.projectId);
  const customer = snapshot.customers.find((item) => item.id === project?.customerId);
  const financial = getProjectFinancials(snapshot).find((item) => item.project.id === target.projectId);
  const [type, setType] = useState<SettlementIssueType>("customer_dissatisfied");
  const [receivableImpact, setReceivableImpact] = useState("0");
  const [refundAmount, setRefundAmount] = useState("0");
  const [occurredAt, setOccurredAt] = useState(localDateTimeValue);
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const stableRequestId = useRef(requestId()).current;
  const reasonInput = useRef<HTMLTextAreaElement>(null);
  const impact = Number(receivableImpact) || 0;
  const refund = Number(refundAmount) || 0;
  const terminalIssue = terminalSettlementIssueTypes.has(type);

  useEffect(() => {
    const timer = window.setTimeout(() => reasonInput.current?.focus({ preventScroll: true }), 80);
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [onClose, submitting]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setConflict(false);
    if (!project || !financial) {
      setError("项目不存在或已被删除，请关闭后刷新页面");
      return;
    }
    if (!reason.trim() || reason.trim().length < 2) {
      setError("请填写具体异常原因，便于后续追溯");
      return;
    }
    if (!Number.isFinite(impact) || impact < 0 || impact > financial.outstanding + 0.005) {
      setError(`确认无法收回的金额不能超过 ${money.format(financial.outstanding)}`);
      return;
    }
    if (!Number.isFinite(refund) || refund < 0 || refund > financial.availableRefund + 0.005) {
      setError(`实际退款不能超过 ${money.format(financial.availableRefund)}`);
      return;
    }
    if (!occurredAt) {
      setError("请选择异常发生时间");
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit({
        requestId: stableRequestId,
        projectId: project.id,
        type,
        receivableImpact: impact,
        refundAmount: refund,
        occurredAt,
        reason: reason.trim(),
        notes: notes.trim() || undefined,
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "项目异常保存失败，请稍后重试");
      setConflict(caught instanceof LedgerRevisionConflictError);
    } finally {
      setSubmitting(false);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    setError("");
    try {
      await onRefresh();
      setConflict(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "刷新经营数据失败");
    } finally {
      setRefreshing(false);
    }
  };

  return <div className="payment-confirmation-layer settlement-issue-layer" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget && !submitting) onClose();
  }}>
    <section className="payment-confirmation-modal settlement-issue-modal" role="dialog" aria-modal="true" aria-labelledby="settlement-issue-title" aria-describedby="settlement-issue-description">
      <header>
        <i><WarningCircle size={25} weight="duotone" /></i>
        <div><span>PROJECT EXCEPTION</span><h2 id="settlement-issue-title">记录项目异常</h2></div>
        <button type="button" aria-label="关闭项目异常" onClick={onClose} disabled={submitting}><X size={20} /></button>
      </header>

      {project && financial ? <>
        <div className="payment-confirmation-project settlement-issue-project">
          <div><small>接单项目</small><strong>{project.name}</strong><span>{customer?.name || "未关联客户"}</span></div>
          <div><small>净到账 / 可收余额</small><strong>{money.format(financial.income)} / {money.format(financial.outstanding)}</strong><span>可退款 {money.format(financial.availableRefund)}</span></div>
        </div>

        <p className="settlement-issue-guidance" id="settlement-issue-description"><WarningCircle size={17} weight="fill" />异常记录不会自动改变项目交付状态。“无法收回”会减少可收余额，“实际退款”会减少净到账与利润。</p>

        <form onSubmit={submit} noValidate>
          <label><span>异常类型</span><select value={type} onChange={(event) => {
            const nextType = event.target.value as SettlementIssueType;
            setType(nextType);
            if (terminalSettlementIssueTypes.has(nextType)) {
              setReceivableImpact(String(financial.outstanding));
            }
          }}>{settlementIssueOptions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>{terminalIssue && <small>项目取消或终止合作后，当前全部可收余额会核销，不再显示为待回款。</small>}</label>

          <div className="payment-form-row settlement-money-row">
            <label><span>确认无法收回 <em>{terminalIssue ? "自动核销全部" : "可为 0"}</em></span><div className="payment-money-input"><b>¥</b><input type="number" min="0" max={financial.outstanding} step="0.01" value={receivableImpact} readOnly={terminalIssue} onChange={(event) => setReceivableImpact(event.target.value)} /></div><small>{terminalIssue ? `终止类异常固定核销 ${money.format(financial.outstanding)}` : <>当前最多 {money.format(financial.outstanding)} <button type="button" onClick={() => setReceivableImpact(String(financial.outstanding))} disabled={financial.outstanding <= 0}>填入全部</button></>}</small></label>
            <label><span>实际退款 <em>可为 0</em></span><div className="payment-money-input"><b>¥</b><input type="number" min="0" max={financial.availableRefund} step="0.01" value={refundAmount} onChange={(event) => setRefundAmount(event.target.value)} /></div><small>当前最多 {money.format(financial.availableRefund)} <button type="button" onClick={() => setRefundAmount(String(financial.availableRefund))} disabled={financial.availableRefund <= 0}>填入全部</button></small></label>
          </div>

          <div className="settlement-impact-preview" aria-live="polite">
            <span><small>记录后净到账</small><b>{money.format(financial.income - refund)}</b></span>
            <span><small>记录后可收余额</small><b>{money.format(Math.max(0, financial.outstanding - impact))}</b></span>
            <span><small>记录后项目利润</small><b>{money.format(financial.profit - refund)}</b></span>
          </div>

          <label><span>异常发生时间</span><div className="settlement-date-field"><CalendarBlank size={17} /><input type="datetime-local" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} /></div></label>
          <label><span>异常原因 <em>必填</em></span><textarea ref={reasonInput} rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="例如：客户认为交付结果未达到预期，双方协商退回定金并终止合作" /></label>
          <label><span>处理备注 <em>选填</em></span><textarea rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="记录沟通结论、退款安排或后续动作" /></label>

          {impact === 0 && refund === 0 && <div className="settlement-risk-only"><CheckCircle size={16} weight="duotone" />本次只记录风险与原因，不改变财务金额。</div>}
          {error && <div className={`payment-confirmation-error ${conflict ? "is-conflict" : ""}`} role="alert"><WarningCircle size={17} weight="fill" /><span>{error}</span>{conflict && <button type="button" onClick={() => void refresh()} disabled={refreshing}>{refreshing ? <ArrowClockwise className="spin" size={15} /> : <ArrowClockwise size={15} />}刷新最新数据</button>}</div>}

          <footer><button type="button" onClick={onClose} disabled={submitting}>取消</button><button className="payment-confirm-primary settlement-confirm-primary" type="submit" disabled={submitting}>{submitting ? <><span className="spinner" />正在保存…</> : <><CurrencyCircleDollar size={18} weight="fill" />确认记录异常</>}</button></footer>
        </form>
      </> : <div className="payment-confirmation-missing"><WarningCircle size={32} weight="duotone" /><h3>项目已不可用</h3><p>请关闭窗口并刷新经营数据。</p></div>}
    </section>
  </div>;
}
