import {
  ArrowClockwise,
  CalendarBlank,
  CheckCircle,
  WarningCircle,
  Wallet,
  X,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { getProjectFinancials } from "../data/businessMetrics";
import { LedgerRevisionConflictError } from "../data/mockService";
import { useDialogFocus } from '../components/workspace/useDialogFocus';
import type {
  LedgerSnapshot,
  PaymentConfirmationValue,
  PaymentType,
} from "../types";

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
});

const paymentLabels: Record<PaymentType, string> = {
  deposit: "定金",
  milestone: "阶段款",
  final: "尾款",
  full: "全款",
};

function localDateTimeValue() {
  const date = new Date();
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function requestId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `receipt-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

export interface PaymentConfirmationTarget {
  projectId: string;
  paymentId?: string;
}

export function PaymentConfirmationModal({
  snapshot,
  target,
  onClose,
  onSubmit,
  onRefresh,
}: {
  snapshot: LedgerSnapshot;
  target: PaymentConfirmationTarget;
  onClose: () => void;
  onSubmit: (value: PaymentConfirmationValue) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const project = snapshot.projects.find((item) => item.id === target.projectId);
  const customer = snapshot.customers.find((item) => item.id === project?.customerId);
  const financial = getProjectFinancials(snapshot).find((item) => item.project.id === target.projectId);
  const pendingNodes = useMemo(
    () => snapshot.payments
      .filter((item) => item.projectId === target.projectId && item.status === "pending")
      .sort((left, right) => left.dueAt.localeCompare(right.dueAt)),
    [snapshot.payments, target.projectId],
  );
  const initialNode = pendingNodes.find((item) => item.id === target.paymentId)
    || (pendingNodes.length === 1 ? pendingNodes[0] : undefined);
  const [paymentId, setPaymentId] = useState(initialNode?.id || "");
  const selectedNode = pendingNodes.find((item) => item.id === paymentId);
  // Payment sequencing follows money that has actually arrived. A later refund
  // lowers net income, but it must not make the next receipt look like a first
  // payment again.
  const priorIncome = financial?.grossIncome || 0;
  const [amount, setAmount] = useState(
    initialNode
      ? String(initialNode.amount)
      : pendingNodes.length > 1
        ? ""
        : String(financial?.outstanding || ""),
  );
  const [type, setType] = useState<PaymentType>(
    initialNode?.type || (priorIncome > 0 ? "final" : "full"),
  );
  const [paidAt, setPaidAt] = useState(localDateTimeValue);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const stableRequestId = useRef(requestId()).current;
  const dialogRef = useDialogFocus<HTMLElement>(() => { if (!submitting) onClose(); }, '.payment-money-input input');
  const maxAmount = Math.min(
    financial?.outstanding || 0,
    selectedNode?.amount ?? financial?.outstanding ?? 0,
  );

  useEffect(() => {
    if (!selectedNode) return;
    setAmount(String(Math.min(selectedNode.amount, financial?.outstanding || selectedNode.amount)));
    setType(selectedNode.type);
  }, [financial?.outstanding, selectedNode]);

  const chooseNode = (value: string) => {
    setPaymentId(value);
    setError("");
    const node = pendingNodes.find((item) => item.id === value);
    if (node) {
      setAmount(String(Math.min(node.amount, financial?.outstanding || node.amount)));
      setType(node.type);
    } else if (pendingNodes.length > 1) {
      setAmount("");
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setConflict(false);
    const numericAmount = Number(amount);
    if (!project || !financial) {
      setError("项目不存在或已被删除，请关闭后刷新页面");
      return;
    }
    if (pendingNodes.length > 1 && !paymentId) {
      setError("请先选择本次到账对应的收款节点");
      return;
    }
    if (!Number.isFinite(numericAmount) || numericAmount <= 0) {
      setError("请输入大于 0 的到账金额");
      return;
    }
    if (numericAmount > maxAmount + 0.005) {
      setError(`本次到账不能超过 ${money.format(maxAmount)}`);
      return;
    }
    if (!paidAt) {
      setError("请选择到账时间");
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit({
        requestId: stableRequestId,
        projectId: project.id,
        paymentId: paymentId || undefined,
        amount: numericAmount,
        paidAt,
        type,
        notes: notes.trim() || undefined,
      });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "到账确认失败，请稍后重试";
      setError(message);
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

  return <div className="payment-confirmation-layer" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget && !submitting) onClose();
  }}>
    <section ref={dialogRef} className="payment-confirmation-modal" role="dialog" aria-modal="true" aria-labelledby="payment-confirmation-title">
      <header>
        <i><Wallet size={24} weight="duotone" /></i>
        <div><span>RECEIPT CONFIRMATION</span><h2 id="payment-confirmation-title">确认项目到账</h2></div>
        <button type="button" aria-label="关闭确认到账" onClick={onClose} disabled={submitting}><X size={20} /></button>
      </header>

      {project && financial ? <>
        <div className="payment-confirmation-project">
          <div><small>项目</small><strong>{project.name}</strong><span>{customer?.name || "未关联客户"}</span></div>
          <div><small>当前未收</small><strong>{money.format(financial.outstanding)}</strong><span>合同额 {money.format(project.totalAmount)}</span></div>
        </div>

        {project.status === "delivered" && financial.outstanding > 0 && <div className="payment-delivered-note"><WarningCircle size={17} weight="fill" /><span><b>项目已交付，仍有回款未确认</b><small>确认本次到账只更新财务数据，不会改变项目交付状态。</small></span></div>}

        <form onSubmit={submit} noValidate>
          {pendingNodes.length > 1 && <label className="payment-node-select"><span>对应收款节点</span><select value={paymentId} onChange={(event) => chooseNode(event.target.value)}><option value="">请选择定金、阶段款或尾款</option>{pendingNodes.map((node) => <option value={node.id} key={node.id}>{paymentLabels[node.type]} · {money.format(node.amount)} · {node.dueAt.slice(0, 10)}</option>)}</select></label>}
          {pendingNodes.length === 1 && <div className="payment-selected-node"><CheckCircle size={16} weight="fill" /><span>已匹配 {paymentLabels[pendingNodes[0].type]}节点 · {money.format(pendingNodes[0].amount)}</span></div>}
          {pendingNodes.length === 0 && <div className="payment-selected-node is-new"><CalendarBlank size={16} weight="duotone" /><span>当前未建立付款节点，将直接按本次到账生成记录。</span></div>}

          <div className="payment-form-row">
            <label><span>到账金额</span><div className="payment-money-input"><b>¥</b><input type="number" min="0.01" max={maxAmount || undefined} step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0.00" /></div><small>最多可确认 {money.format(maxAmount)}</small></label>
            <label><span>收款类型</span><select value={type} onChange={(event) => setType(event.target.value as PaymentType)}>{Object.entries(paymentLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          </div>
          <label><span>到账时间</span><input type="datetime-local" value={paidAt} onChange={(event) => setPaidAt(event.target.value)} /></label>
          <label><span>备注 <em>选填</em></span><textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="例如：客户已支付尾款，金额已核对" /></label>

          {error && <div className={`payment-confirmation-error ${conflict ? "is-conflict" : ""}`} role="alert"><WarningCircle size={17} weight="fill" /><span>{error}</span>{conflict && <button type="button" onClick={() => void refresh()} disabled={refreshing}>{refreshing ? <ArrowClockwise className="spin" size={15} /> : <ArrowClockwise size={15} />}刷新最新数据</button>}</div>}

          <footer><button type="button" onClick={onClose} disabled={submitting}>取消</button><button className="payment-confirm-primary" type="submit" disabled={submitting || !project || !financial || financial.outstanding <= 0}>{submitting ? <><span className="spinner" />正在确认…</> : <><CheckCircle size={18} weight="fill" />确认到账</>}</button></footer>
        </form>
      </> : <div className="payment-confirmation-missing"><WarningCircle size={32} weight="duotone" /><h3>项目已不可用</h3><p>请关闭窗口并刷新经营数据。</p></div>}
    </section>
  </div>;
}
