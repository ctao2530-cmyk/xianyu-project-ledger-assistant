import {
  ArrowClockwise,
  CalendarBlank,
  CheckCircle,
  Coins,
  Plus,
  Receipt,
  Trash,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { getProjectFinancials } from "../data/businessMetrics";
import { LedgerRevisionConflictError } from "../data/mockService";
import type {
  LedgerSnapshot,
  PaymentType,
  ProjectChangeOrderValue,
} from "../types";

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
});

type SettlementMode = "received" | "pending" | "installments";

interface InstallmentDraft {
  id: string;
  amount: string;
  dueAt: string;
  type: PaymentType;
}

function localDateValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function localDateTimeValue() {
  const date = new Date();
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function addDays(value: string, days: number) {
  const date = new Date(`${value || localDateValue()}T12:00:00`);
  date.setDate(date.getDate() + days);
  return localDateValue(date);
}

function requestId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `change-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

function installmentId() {
  return `row-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function splitAmount(amount: number) {
  if (!Number.isFinite(amount) || amount <= 0) return ["", ""];
  const first = Math.floor(amount * 50) / 100;
  return [first.toFixed(2), (amount - first).toFixed(2)];
}

export interface ProjectChangeOrderTarget {
  projectId: string;
}

export function ProjectChangeOrderModal({
  snapshot,
  target,
  onClose,
  onSubmit,
  onRefresh,
}: {
  snapshot: LedgerSnapshot;
  target: ProjectChangeOrderTarget;
  onClose: () => void;
  onSubmit: (value: ProjectChangeOrderValue) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const project = snapshot.projects.find((item) => item.id === target.projectId);
  const customer = snapshot.customers.find((item) => item.id === project?.customerId);
  const financial = getProjectFinancials(snapshot).find((item) => item.project.id === target.projectId);
  const projectOrders = useMemo(
    () => snapshot.changeOrders.filter((item) => item.projectId === target.projectId && item.status === "confirmed"),
    [snapshot.changeOrders, target.projectId],
  );
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [confirmedAt, setConfirmedAt] = useState(localDateValue);
  const [mode, setMode] = useState<SettlementMode>("pending");
  const [paidAt, setPaidAt] = useState(localDateTimeValue);
  const [dueAt, setDueAt] = useState(() => addDays(localDateValue(), 7));
  const [notes, setNotes] = useState("");
  const [installments, setInstallments] = useState<InstallmentDraft[]>(() => [
    { id: installmentId(), amount: "", dueAt: addDays(localDateValue(), 7), type: "milestone" },
    { id: installmentId(), amount: "", dueAt: addDays(localDateValue(), 14), type: "final" },
  ]);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const stableRequestId = useRef(requestId()).current;
  const titleInput = useRef<HTMLInputElement>(null);
  const numericAmount = Number(amount);
  const validAmount = Number.isFinite(numericAmount) && numericAmount > 0 ? numericAmount : 0;
  const installmentTotal = installments.reduce((sum, item) => sum + (Number(item.amount) || 0), 0);
  const immediateReceipt = mode === "received" ? validAmount : 0;
  const nextContract = (project?.totalAmount || 0) + validAmount;
  const nextGrossIncome = (financial?.grossIncome || 0) + immediateReceipt;
  const nextOutstanding = Math.max(0, (financial?.outstanding || 0) + validAmount - immediateReceipt);
  const additionTotal = projectOrders.reduce((sum, item) => sum + item.amount, 0);
  const baseContract = Math.max(0, (project?.totalAmount || 0) - additionTotal);

  useEffect(() => {
    const timer = window.setTimeout(() => titleInput.current?.focus({ preventScroll: true }), 80);
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [onClose, submitting]);

  const chooseMode = (nextMode: SettlementMode) => {
    setMode(nextMode);
    setError("");
    if (nextMode === "installments") {
      const [first, second] = splitAmount(validAmount);
      setInstallments((rows) => rows.map((row, index) => ({
        ...row,
        amount: index === 0 ? first : index === 1 ? second : "",
      })));
    }
  };

  const updateInstallment = (id: string, patch: Partial<InstallmentDraft>) => {
    setInstallments((rows) => rows.map((row) => row.id === id ? { ...row, ...patch } : row));
    setError("");
  };

  const addInstallment = () => {
    if (installments.length >= 6) return;
    setInstallments((rows) => [...rows, {
      id: installmentId(),
      amount: "",
      dueAt: addDays(confirmedAt, (rows.length + 1) * 7),
      type: rows.length >= 1 ? "final" : "milestone",
    }]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setConflict(false);
    if (!project || !financial) {
      setError("项目不存在或已被删除，请关闭后刷新页面");
      return;
    }
    if (title.trim().length < 2) {
      setError("请填写本次客户追加修改的具体内容");
      return;
    }
    if (!validAmount) {
      setError("请输入大于 0 的追加金额");
      return;
    }
    if (!confirmedAt) {
      setError("请选择客户确认日期");
      return;
    }
    if (mode === "received" && !paidAt) {
      setError("请选择到账时间");
      return;
    }
    if (mode === "pending" && !dueAt) {
      setError("请选择应收日期");
      return;
    }
    if (mode === "installments") {
      if (installments.length < 2 || installments.some((item) => !item.dueAt || Number(item.amount) <= 0)) {
        setError("分期计划至少需要两笔有效金额和应收日期");
        return;
      }
      if (Math.abs(installmentTotal - validAmount) > 0.005) {
        setError(`分期合计 ${money.format(installmentTotal)}，必须等于追加金额 ${money.format(validAmount)}`);
        return;
      }
    }
    const paymentPlan = mode === "received"
      ? [{ amount: validAmount, type: "milestone" as const, status: "confirmed" as const, paidAt, dueAt: paidAt.slice(0, 10), notes: `${title.trim()} · 追加款已到账` }]
      : mode === "pending"
        ? [{ amount: validAmount, type: "milestone" as const, status: "pending" as const, dueAt, notes: `${title.trim()} · 追加款待收` }]
        : installments.map((item) => ({
          amount: Number(item.amount),
          type: item.type,
          status: "pending" as const,
          dueAt: item.dueAt,
          notes: `${title.trim()} · 分期待收`,
        }));
    setSubmitting(true);
    try {
      await onSubmit({
        requestId: stableRequestId,
        projectId: project.id,
        title: title.trim(),
        amount: validAmount,
        confirmedAt,
        notes: notes.trim() || undefined,
        paymentPlan,
      });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "追加订单保存失败，请稍后重试";
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
    <section className="payment-confirmation-modal change-order-modal" role="dialog" aria-modal="true" aria-labelledby="change-order-title">
      <header>
        <i><Receipt size={24} weight="duotone" /></i>
        <div><span>PROJECT CHANGE ORDER</span><h2 id="change-order-title">新增追加订单</h2></div>
        <button type="button" aria-label="关闭追加订单" onClick={onClose} disabled={submitting}><X size={20} /></button>
      </header>

      {project && financial ? <>
        <div className="payment-confirmation-project change-order-project">
          <div><small>原项目</small><strong>{project.name}</strong><span>{customer?.name || "未关联客户"}</span></div>
          <div><small>当前合同构成</small><strong>{money.format(project.totalAmount)}</strong><span>原合同 {money.format(baseContract)}{projectOrders.length ? ` + ${projectOrders.length} 次追加 ${money.format(additionTotal)}` : " · 尚无追加"}</span></div>
        </div>

        <div className="change-order-boundary-note"><WarningCircle size={17} weight="fill" /><span><b>追加订单会增加合同金额</b><small>如果只是拆分现有未收余额，请使用“新增收款节点”；保存本单不会自动改变项目交付状态。</small></span></div>

        <form onSubmit={submit} noValidate>
          <div className="change-order-form-row">
            <label><span>追加修改内容</span><input ref={titleInput} value={title} maxLength={300} onChange={(event) => setTitle(event.target.value)} placeholder="例如：新增第三方登录与账号绑定" /></label>
            <label><span>追加金额</span><div className="payment-money-input"><b>¥</b><input type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0.00" /></div></label>
          </div>
          <label><span>客户确认日期</span><input type="date" value={confirmedAt} onChange={(event) => setConfirmedAt(event.target.value)} /></label>

          <fieldset className="change-order-mode"><legend>收款安排</legend><div>
            <button type="button" aria-pressed={mode === "received"} className={mode === "received" ? "active" : ""} onClick={() => chooseMode("received")}><CheckCircle size={18} weight="duotone" /><span><b>已到账</b><small>本次追加款已全部收到</small></span></button>
            <button type="button" aria-pressed={mode === "pending"} className={mode === "pending" ? "active" : ""} onClick={() => chooseMode("pending")}><CalendarBlank size={18} weight="duotone" /><span><b>单笔待收</b><small>建立一笔追加款应收</small></span></button>
            <button type="button" aria-pressed={mode === "installments"} className={mode === "installments" ? "active" : ""} onClick={() => chooseMode("installments")}><Coins size={18} weight="duotone" /><span><b>分期计划</b><small>拆成多笔待收节点</small></span></button>
          </div></fieldset>

          {mode === "received" && <label><span>到账时间</span><input type="datetime-local" value={paidAt} onChange={(event) => setPaidAt(event.target.value)} /></label>}
          {mode === "pending" && <label><span>应收日期</span><input type="date" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label>}
          {mode === "installments" && <section className="change-order-installments" aria-label="分期收款计划">
            <header><span><b>分期明细</b><small>合计 {money.format(installmentTotal)} / {money.format(validAmount)}</small></span><button type="button" onClick={addInstallment} disabled={installments.length >= 6}><Plus size={14} />增加一期</button></header>
            <div>{installments.map((item, index) => <article key={item.id}>
              <i>{index + 1}</i>
              <label><span>金额</span><input type="number" min="0.01" step="0.01" value={item.amount} onChange={(event) => updateInstallment(item.id, { amount: event.target.value })} placeholder="0.00" /></label>
              <label><span>应收日期</span><input type="date" value={item.dueAt} onChange={(event) => updateInstallment(item.id, { dueAt: event.target.value })} /></label>
              <label><span>类型</span><select value={item.type} onChange={(event) => updateInstallment(item.id, { type: event.target.value as PaymentType })}><option value="deposit">定金</option><option value="milestone">阶段款</option><option value="final">尾款</option><option value="full">全款</option></select></label>
              <button type="button" aria-label={`删除第 ${index + 1} 期`} disabled={installments.length <= 2} onClick={() => setInstallments((rows) => rows.filter((row) => row.id !== item.id))}><Trash size={15} /></button>
            </article>)}</div>
          </section>}

          <label><span>备注 <em>选填</em></span><textarea rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="例如：客户已在 8 月 10 日聊天中确认范围与价格" /></label>

          <section className="change-order-preview" aria-label="保存结果预览">
            <header><Receipt size={17} weight="duotone" /><b>保存后结果预览</b><small>项目数量不变 · 追加订单 +1</small></header>
            <div><span><small>合同总额</small><b>{money.format(project.totalAmount)} <em>→</em> {money.format(nextContract)}</b></span><span><small>已确认入账</small><b>{money.format(financial.grossIncome)} <em>→</em> {money.format(nextGrossIncome)}</b></span><span className={nextOutstanding > 0 ? "is-outstanding" : ""}><small>可收余额</small><b>{money.format(financial.outstanding)} <em>→</em> {money.format(nextOutstanding)}</b></span></div>
          </section>

          {error && <div className={`payment-confirmation-error ${conflict ? "is-conflict" : ""}`} role="alert"><WarningCircle size={17} weight="fill" /><span>{error}</span>{conflict && <button type="button" onClick={() => void refresh()} disabled={refreshing}>{refreshing ? <ArrowClockwise className="spin" size={15} /> : <ArrowClockwise size={15} />}刷新最新数据</button>}</div>}

          <footer><button type="button" onClick={onClose} disabled={submitting}>取消</button><button className="payment-confirm-primary" type="submit" disabled={submitting}>{submitting ? <><span className="spinner" />正在保存…</> : <><Plus size={18} weight="bold" />确认新增追加订单</>}</button></footer>
        </form>
      </> : <div className="payment-confirmation-missing"><WarningCircle size={32} weight="duotone" /><h3>项目已不可用</h3><p>请关闭窗口并刷新经营数据。</p></div>}
    </section>
  </div>;
}
