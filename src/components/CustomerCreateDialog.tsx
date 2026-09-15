import {
  CheckCircle,
  ChatCircleDots,
  MagnifyingGlass,
  ShieldCheck,
  UserPlus,
  Warning,
  X,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { acceptMigratedLedger } from "../data/mockService";
import {
  localPlatformService,
  type CustomerIntakeCandidate,
} from "../data/localPlatformService";
import type { CustomerLevel, LedgerSnapshot } from "../types";
import "./customer-create-dialog.css";


type PriceType = "" | "customer_budget" | "operator_quote" | "agreed_price";
type Mode = "conversation" | "manual";

function requestId() {
  return `customer-create:${crypto.randomUUID()}`;
}

function channelLabel(channel: string) {
  return channel === "xianyu" ? "闲鱼" : channel === "wechat" ? "微信" : channel;
}

export function CustomerCreateDialog({
  onClose,
  onCreated,
  initialConversationId,
}: {
  onClose: () => void;
  onCreated: (snapshot: LedgerSnapshot, customerName: string) => void;
  initialConversationId?: number;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const busyRef = useRef(false);
  const onCloseRef = useRef(onClose);
  const [mode, setMode] = useState<Mode>("conversation");
  const [moreFields, setMoreFields] = useState(false);
  const [revision, setRevision] = useState<number | null>(null);
  const [candidates, setCandidates] = useState<CustomerIntakeCandidate[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [name, setName] = useState("");
  const [source, setSource] = useState<"xianyu" | "wechat" | "referral" | "other">("xianyu");
  const [phone, setPhone] = useState("");
  const [level, setLevel] = useState<CustomerLevel>("C");
  const [currentNeed, setCurrentNeed] = useState("");
  const [priceType, setPriceType] = useState<PriceType>("");
  const [priceAmount, setPriceAmount] = useState("");
  const [nextAction, setNextAction] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  busyRef.current = busy;
  onCloseRef.current = onClose;

  const selected = candidates.find((item) => item.conversation_id === selectedConversationId) || null;
  const visibleCandidates = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return candidates;
    return candidates.filter((item) => `${item.customer_name} ${item.last_text_preview}`.toLowerCase().includes(query));
  }, [candidates, search]);

  useEffect(() => {
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => dialogRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) onCloseRef.current();
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])")].filter(e=>e.getClientRects().length>0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
      window.requestAnimationFrame(() => previousFocusRef.current?.focus({ preventScroll: true }));
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    void localPlatformService.customerIntakeCandidates()
      .then((value) => {
        if (!active) return;
        setRevision(value.revision);
        setCandidates(value.candidates);
        const first = initialConversationId ? value.candidates.find(c=>c.conversation_id===initialConversationId) : value.candidates[0];
        if (first) {
          setSelectedConversationId(first.conversation_id);
          setName(first.customer_name);
          setSource(first.customer_source);
        }
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : "无法读取客户消息候选");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const selectCandidate = (candidate: CustomerIntakeCandidate) => {
    setSelectedConversationId(candidate.conversation_id);
    setName(candidate.customer_name);
    setSource(candidate.customer_source);
    setError("");
  };

  const changeMode = (next: Mode) => {
    setMode(next);
    setError("");
    if (next === "manual") {
      setSelectedConversationId(null);
      setName("");
      setSource("xianyu");
    } else {
      const first = candidates[0];
      setSelectedConversationId(first?.conversation_id || null);
      setName(first?.customer_name || "");
      setSource(first?.customer_source || "xianyu");
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (revision === null) { setError("尚未取得经营数据修订号，请关闭后重试"); return; }
    if (mode === "conversation" && selectedConversationId === null) { setError("请选择一位尚未加入客户列表的会话客户"); return; }
    if (!name.trim()) { setError("请填写客户名称"); return; }
    const amount = priceAmount.trim() ? Number(priceAmount) : null;
    if (amount !== null && (!Number.isFinite(amount) || amount <= 0)) { setError("价格金额必须大于 0"); return; }
    if (amount !== null && !priceType) { setError("填写金额时请选择价格类型"); return; }
    setBusy(true);
    setError("");
    try {
      const result = await localPlatformService.createCustomer({
        request_id: requestId(),
        expected_revision: revision,
        confirmed: true,
        conversation_id: mode === "conversation" ? selectedConversationId : null,
        name: name.trim(),
        source,
        phone: phone.trim(),
        level,
        current_need: currentNeed.trim(),
        price_type: priceType,
        price_amount: amount,
        next_action: nextAction.trim(),
        notes: notes.trim(),
      });
      acceptMigratedLedger(result.revision);
      onCreated(result.snapshot, name.trim());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "客户新增失败，本次没有写入");
    } finally {
      setBusy(false);
    }
  };

  return createPortal(<div className="customer-create-layer">
    <button className="customer-create-backdrop" type="button" aria-label="关闭新增客户" disabled={busy} onClick={onClose} />
    <section ref={dialogRef} className="customer-create-dialog" role="dialog" aria-modal="true" aria-labelledby="customer-create-title" tabIndex={-1}>
      <header className="customer-create-head"><div><small>客户资料录入</small><h2 id="customer-create-title">新增客户</h2></div><button type="button" aria-label="关闭" disabled={busy} onClick={onClose}><X size={20} /></button></header>
      <div className="customer-create-tabs" role="tablist" aria-label="客户录入方式"><button type="button" role="tab" aria-selected={mode === "conversation"} className={mode === "conversation" ? "active" : ""} onClick={() => changeMode("conversation")}><ChatCircleDots size={17} />从客户消息选择</button><button type="button" role="tab" aria-selected={mode === "manual"} className={mode === "manual" ? "active" : ""} onClick={() => changeMode("manual")}><UserPlus size={17} />手动录入</button></div>
      <form className={`customer-create-body mode-${mode}`} onSubmit={(event) => void submit(event)}>
        {mode === "conversation" && <aside className="customer-create-candidates"><header><b>选择未加入客户</b><small>已加入客户列表或关系冲突的会话自动隐藏。</small></header><label className="customer-create-search"><MagnifyingGlass size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索会话昵称或最近文字" aria-label="搜索可新增客户会话" /></label><div className="customer-create-candidate-list">{loading ? <p className="customer-create-empty">正在读取客户消息…</p> : visibleCandidates.length ? visibleCandidates.map((candidate) => <button type="button" className={selectedConversationId === candidate.conversation_id ? "active" : ""} onClick={() => selectCandidate(candidate)} key={candidate.conversation_id}><i>{candidate.customer_name.slice(0, 1)}</i><span><b>{candidate.customer_name}</b><small>{channelLabel(candidate.channel)} · {candidate.last_message_at ? new Date(candidate.last_message_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "暂无时间"}</small><em>{candidate.last_text_preview || "暂无可显示的文字消息"}</em>{candidate.same_name_exists && <strong>存在同名客户，不会自动合并</strong>}</span>{selectedConversationId === candidate.conversation_id && <CheckCircle size={18} weight="fill" />}</button>) : <p className="customer-create-empty">没有尚未加入客户列表的会话客户。</p>}</div></aside>}
        <main className={`customer-create-fields ${moreFields?'':'is-quick-intake'}`}>
          <p>先确认客户名称、来源和关联会话。其他资料可稍后补充。</p>
          <button type="button" className="customer-intake-more" aria-expanded={moreFields} onClick={()=>setMoreFields(v=>!v)}>{moreFields?'收起更多资料':'更多资料（选填）'}</button>
          {mode === "conversation" && selected && <div className="customer-create-mobile-selection"><i>{selected.customer_name.slice(0, 1)}</i><span><b>{selected.customer_name}</b><small>{channelLabel(selected.channel)} · 已选择</small></span><button type="button" onClick={() => dialogRef.current?.querySelector<HTMLElement>(".customer-create-candidates")?.scrollIntoView({ behavior: "smooth" })}>更换会话</button></div>}
          <div className="customer-create-grid"><label><span>客户名称</span><input autoFocus={mode === "manual"} value={name} maxLength={255} onChange={(event) => setName(event.target.value)} /></label><label><span>联系电话 <em>（选填）</em></span><input value={phone} maxLength={100} placeholder="暂未提供" onChange={(event) => setPhone(event.target.value)} /></label><label className="wide"><span>当前需求</span><textarea rows={3} value={currentNeed} maxLength={4000} placeholder="只填写已确认或需要继续核对的需求" onChange={(event) => setCurrentNeed(event.target.value)} /></label><label><span>价格类型</span><select value={priceType} onChange={(event) => setPriceType(event.target.value as PriceType)}><option value="">暂未记录</option><option value="customer_budget">客户预算</option><option value="operator_quote">我的报价</option><option value="agreed_price">双方确认价</option></select></label><label><span>金额 <em>（选填）</em></span><input type="number" min="0.01" step="0.01" value={priceAmount} placeholder="0.00" onChange={(event) => setPriceAmount(event.target.value)} /></label><label><span>客户来源</span><select disabled={mode === "conversation"} value={source} onChange={(event) => setSource(event.target.value as typeof source)}><option value="xianyu">闲鱼</option><option value="wechat">微信</option><option value="referral">转介绍</option><option value="other">其他</option></select></label><label><span>客户等级</span><select value={level} onChange={(event) => setLevel(event.target.value as CustomerLevel)}><option value="A">A 级</option><option value="B">B 级</option><option value="C">C 级</option></select></label><label className="wide"><span>下一步行动</span><input value={nextAction} maxLength={2000} placeholder="例如：确认域名、范围或付款节点" onChange={(event) => setNextAction(event.target.value)} /></label><label className="wide"><span>补充备注 <em>（选填）</em></span><textarea rows={2} value={notes} maxLength={4000} placeholder="仅记录需要长期保留的信息" onChange={(event) => setNotes(event.target.value)} /></label></div>
        </main>
        {error && <p className="customer-create-error" role="alert"><Warning size={16} />{error}</p>}
        <footer className="customer-create-actions"><p><ShieldCheck size={15} />{mode === "conversation" ? "确认后创建客户并绑定此会话，防止重复新增。" : "确认后只创建客户资料，不创建报价、项目或任务。"}</p><div><button type="button" disabled={busy} onClick={onClose}>取消</button><button className="primary" type="submit" disabled={busy || revision === null || (mode === "conversation" && !selected)}>{busy ? "正在确认…" : "确认加入客户列表"}</button></div></footer>
      </form>
    </section>
  </div>, document.body);
}
