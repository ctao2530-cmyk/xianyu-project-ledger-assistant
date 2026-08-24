import {
  ArrowClockwise,
  CheckCircle,
  CircleNotch,
  ClipboardText,
  Clock,
  Code,
  FileCode,
  GitBranch,
  ListChecks,
  Play,
  ShieldCheck,
  Timer,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  localPlatformService,
  type CodexAcceptancePoint,
  type CodexAcceptanceStatus,
  type CodexManagedProjectView,
  type CodexProjectVerificationView,
} from "../data/localPlatformService";
import "./codex-verification-workbench.css";

const statusCopy: Record<CodexAcceptanceStatus, { label: string; detail: string }> = {
  pending: { label: "待实现", detail: "还没有可核验的实现或证据" },
  implemented: { label: "已实现", detail: "Codex 已声明实现，尚未完成验收" },
  test_passed: { label: "测试通过", detail: "自动测试通过，仍需满足最终验收条件" },
  verified: { label: "已验收", detail: "已通过人工最终验收" },
  failed: { label: "验收失败", detail: "测试或人工验收未通过" },
  waived: { label: "已放弃", detail: "用户明确放弃，并保留原因" },
};

const evidenceCopy: Record<string, string> = {
  file_change: "文件变更",
  automated_test: "自动测试",
  manual_check: "人工核验",
  git_commit: "Git Commit",
  screenshot: "截图",
  customer_confirmation: "客户确认",
};

const categoryCopy = {
  development: "人工开发",
  testing: "测试",
  fixing: "修复",
  communication: "沟通",
} as const;

const requestId = (scope: string) => {
  const value = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `verification-${scope}:${value}`;
};

const hours = (value: number) => `${Number(value.toFixed(2))}h`;
const shortSha = (value: string) => value ? value.slice(0, 10) : "—";
const dateTime = (value: string | null) => value
  ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value))
  : "尚未形成";

function ProgressCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: number;
  detail: string;
  tone: "execution" | "implemented" | "verified";
}) {
  return <article className={`codex-verification-progress progress-${tone}`}>
    <header><span>{label}</span><strong>{value}%</strong></header>
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}><i style={{ width: `${value}%` }} /></div>
    <small>{detail}</small>
  </article>;
}

function PointDrawer({
  projectId,
  point,
  commands,
  revision,
  busy,
  error,
  onClose,
  onApply,
}: {
  projectId: string;
  point: CodexAcceptancePoint;
  commands: string[];
  revision: number;
  busy: boolean;
  error: string;
  onClose: () => void;
  onApply: (promise: Promise<CodexProjectVerificationView>) => Promise<void>;
}) {
  const drawerRef = useRef<HTMLElement>(null);
  const [reason, setReason] = useState(point.waiver_reason || "");
  const [waivedCounts, setWaivedCounts] = useState(point.waived_counts);
  const [selectedCommand, setSelectedCommand] = useState(commands[0] || "");

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => drawerRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
      if (event.key !== "Tab" || !drawerRef.current) return;
      const controls = Array.from(drawerRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])"));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [busy, onClose]);

  const decide = (status: "pending" | "verified" | "failed" | "waived") => {
    if ((status === "failed" || status === "waived") && reason.trim().length < 2) return;
    void onApply(localPlatformService.decideAcceptancePoint(point.id, {
      request_id: requestId(`point-${status}`),
      expected_revision: revision,
      status,
      reason: reason.trim(),
      waived_counts: status === "waived" && waivedCounts,
    }));
  };

  const runTest = () => {
    if (!selectedCommand) return;
    void onApply(localPlatformService.runProjectVerificationTest(projectId, {
      request_id: requestId("test"),
      expected_revision: revision,
      point_id: point.id,
      command: selectedCommand,
      timeout_seconds: 300,
      confirmed: true,
    }));
  };

  return createPortal(<div className="codex-point-layer" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <aside className="codex-point-drawer" ref={drawerRef} role="dialog" aria-modal="true" aria-labelledby="codex-point-title" tabIndex={-1}>
      <header><div><small>ACCEPTANCE DETAIL</small><h3 id="codex-point-title">核验详情</h3></div><button type="button" aria-label="关闭核验详情" disabled={busy} onClick={onClose}><X size={18} /></button></header>
      <section className="codex-point-identity"><span className={`point-status status-${point.status}`}>{statusCopy[point.status].label}</span><small>{point.point_key}</small><h4>{point.title}</h4><p>{point.task_title}{point.task_key ? ` · ${point.task_key}` : " · 无稳定 task_key"}</p></section>
      <dl className="codex-point-facts"><div><dt>核验方式</dt><dd>{point.verification_type || "人工核验"}</dd></div><div><dt>范围来源</dt><dd>{point.source === "manual_historical" ? "历史项目人工录入" : "已确认 Codex 计划"}</dd></div><div><dt>当前状态</dt><dd>{statusCopy[point.status].detail}</dd></div><div><dt>权重</dt><dd>{point.point_weight === null ? "按任务内平均" : point.point_weight}</dd></div><div><dt>证据数量</dt><dd>{point.evidence.length}</dd></div></dl>
      <section className="codex-point-evidence"><header><h4>不可变证据</h4><span>{point.evidence.length} 条</span></header>{point.evidence.length ? point.evidence.map((item) => <article key={item.id}><i className={item.exit_code === null || item.exit_code === 0 ? "is-pass" : "is-fail"}>{item.evidence_type === "automated_test" ? <Play size={15} weight="fill" /> : item.evidence_type === "git_commit" ? <GitBranch size={16} /> : <FileCode size={16} />}</i><span><b>{evidenceCopy[item.evidence_type] || item.evidence_type}</b><small>{item.test_summary || item.manual_note || item.commit_sha || item.file_paths.join("、") || "已保存证据"}</small></span>{item.exit_code !== null && <em>exit {item.exit_code}</em>}</article>) : <div className="codex-point-evidence-empty">当前没有测试、文件、Commit 或人工验收证据。</div>}</section>
      {commands.length > 0 && <section className="codex-point-test"><header><h4>执行已确认测试</h4><span>只允许计划中的命令</span></header><select aria-label="选择已确认测试命令" value={selectedCommand} onChange={(event) => setSelectedCommand(event.target.value)}>{commands.map((command) => <option value={command} key={command}>{command}</option>)}</select><code>{selectedCommand}</code><button type="button" disabled={busy || !selectedCommand} onClick={runTest}>{busy ? <CircleNotch className="spin" /> : <Play weight="fill" />}确认并运行</button><small>在受管 Worktree 中运行，测试通过只进入 test_passed，不会自动 verified。</small></section>}
      <section className="codex-point-decision"><header><h4>人工验收</h4><span>每次变更都会审计</span></header><textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="填写验收说明；失败、放弃或退役时必填原因" rows={3} /><label><input type="checkbox" checked={waivedCounts} onChange={(event) => setWaivedCounts(event.target.checked)} />放弃项计入已验证交付进度（必须保留原因）</label>{error && <p className="codex-verification-error"><WarningCircle weight="fill" />{error}</p>}<footer><button type="button" disabled={busy} onClick={() => decide("pending")}>重新打开</button><button type="button" disabled={busy || reason.trim().length < 2} onClick={() => decide("failed")}>驳回</button><button type="button" disabled={busy || reason.trim().length < 2} onClick={() => decide("waived")}>明确放弃</button><button className="primary" type="button" disabled={busy} onClick={() => decide("verified")}><ShieldCheck weight="fill" />人工确认验收</button>{point.source === "manual_historical" && <button className="retire" type="button" disabled={busy || reason.trim().length < 2} onClick={() => void onApply(localPlatformService.retireManualAcceptancePoint(point.id, { request_id: requestId("retire-point"), expected_revision: revision, reason: reason.trim() }))}>退役误建验收点（保留历史）</button>}</footer></section>
    </aside>
  </div>, document.body);
}

function ManualScopeDrawer({
  view,
  busy,
  error,
  onClose,
  onCreate,
}: {
  view: CodexProjectVerificationView;
  busy: boolean;
  error: string;
  onClose: () => void;
  onCreate: (payload: Parameters<typeof localPlatformService.createManualAcceptancePoints>[1]) => Promise<void>;
}) {
  const drawerRef = useRef<HTMLElement>(null);
  const [draft, setDraft] = useState({
    taskId: view.delivery.tasks[0]?.task_id || "",
    pointKey: "",
    title: "",
    verificationType: "manual_test" as "automated_test" | "manual_test" | "visual_review" | "document_review",
    reason: "",
  });
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => drawerRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
      if (event.key !== "Tab" || !drawerRef.current) return;
      const controls = Array.from(drawerRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])"));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { window.cancelAnimationFrame(frame); document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", onKeyDown); };
  }, [busy, onClose]);
  const valid = draft.taskId && /^[A-Za-z0-9][A-Za-z0-9._:-]+$/.test(draft.pointKey) && draft.title.trim().length >= 2 && draft.reason.trim().length >= 2;
  return createPortal(<div className="codex-point-layer" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <aside className="codex-point-drawer codex-sample-drawer" ref={drawerRef} role="dialog" aria-modal="true" aria-labelledby="manual-scope-title" tabIndex={-1}>
      <header><div><small>MANUAL ACCEPTANCE SCOPE</small><h3 id="manual-scope-title">人工建立验收清单</h3></div><button type="button" aria-label="关闭人工验收清单" disabled={busy} onClick={onClose}><X size={18} /></button></header>
      <p className="codex-sample-intro">只为没有确认 Codex 计划的历史项目逐项录入。请选择真实任务并填写稳定 key；系统不会从任务标题、legacy 进度或聊天内容猜测验收标准。</p>
      <div className="codex-sample-form">
        <label><span>真实 BusinessTask</span><select value={draft.taskId} onChange={(event) => setDraft((current) => ({ ...current, taskId: event.target.value }))}>{view.delivery.tasks.map((task) => <option key={task.task_id} value={task.task_id}>{task.task_key ? `${task.task_key} · ` : ""}{task.title}</option>)}</select></label>
        <label><span>稳定 point_key</span><input value={draft.pointKey} onChange={(event) => setDraft((current) => ({ ...current, pointKey: event.target.value }))} placeholder="例如 HIST-AC-001" /></label>
        <label><span>验收点标题</span><input value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} placeholder="填写真实、可核验的验收标准" /></label>
        <label><span>验证类型</span><select value={draft.verificationType} onChange={(event) => setDraft((current) => ({ ...current, verificationType: event.target.value as typeof draft.verificationType }))}><option value="manual_test">人工测试</option><option value="visual_review">视觉核验</option><option value="document_review">文档核验</option><option value="automated_test">自动测试</option></select></label>
        <label><span>建立原因</span><textarea rows={3} value={draft.reason} onChange={(event) => setDraft((current) => ({ ...current, reason: event.target.value }))} placeholder="说明历史范围来源与录入依据" /></label>
      </div>
      {error && <p className="codex-verification-error inline"><WarningCircle weight="fill" />{error}</p>}
      <footer className="codex-sample-actions"><button type="button" onClick={onClose} disabled={busy}>取消</button><button className="primary" type="button" disabled={busy || !valid} onClick={() => void onCreate({ request_id: requestId("manual-scope"), expected_revision: view.revision, reason: draft.reason.trim(), points: [{ task_id: draft.taskId, point_key: draft.pointKey.trim(), title: draft.title.trim(), verification_type: draft.verificationType }] })}>{busy ? <CircleNotch className="spin" /> : <ListChecks />}保存一条人工验收点</button></footer>
    </aside>
  </div>, document.body);
}

function OutcomeFreezeDrawer({
  view,
  evidenceCount,
  busy,
  error,
  onClose,
  onFreeze,
}: {
  view: CodexProjectVerificationView;
  evidenceCount: number;
  busy: boolean;
  error: string;
  onClose: () => void;
  onFreeze: (payload: Parameters<typeof localPlatformService.freezeProjectOutcome>[1]) => Promise<void>;
}) {
  const drawerRef = useRef<HTMLElement>(null);
  const [scopeConfirmed, setScopeConfirmed] = useState(false);
  const [timeConfirmed, setTimeConfirmed] = useState(false);
  const [note, setNote] = useState("");
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => drawerRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
      if (event.key !== "Tab" || !drawerRef.current) return;
      const controls = Array.from(drawerRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), textarea:not([disabled])"));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { window.cancelAnimationFrame(frame); document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", onKeyDown); };
  }, [busy, onClose]);
  const readiness = view.sample_readiness;
  const valid = readiness.can_freeze && scopeConfirmed && timeConfirmed && note.trim().length >= 4;
  return createPortal(<div className="codex-point-layer" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <aside className="codex-point-drawer codex-sample-drawer" ref={drawerRef} role="dialog" aria-modal="true" aria-labelledby="freeze-outcome-title" tabIndex={-1}>
      <header><div><small>IMMUTABLE OUTCOME</small><h3 id="freeze-outcome-title">核验并冻结项目结果</h3></div><button type="button" aria-label="关闭结果冻结" disabled={busy} onClick={onClose}><X size={18} /></button></header>
      <p className="codex-sample-intro">冻结会追加一份不可变结果快照，不覆盖旧版本，也不会修改报价、项目状态或交付日期。底层事实变化后旧版本会明确标记 stale。</p>
      <dl className="codex-freeze-preview"><div><dt>原始预计工时</dt><dd>{hours(readiness.estimated_hours)}</dd></div><div><dt>实际工时</dt><dd>{hours(readiness.actual_hours)}</dd></div><div><dt>verified 验收点</dt><dd>{readiness.verified_point_count}/{readiness.active_point_count}</dd></div><div><dt>waiver</dt><dd>{readiness.waived_point_count}</dd></div><div><dt>完成时间</dt><dd>{dateTime(view.outcome.actual_completed_at)}</dd></div><div><dt>证据来源</dt><dd>{evidenceCount} 条证据 · {view.git_links.length} 个 Commit</dd></div></dl>
      {readiness.blockers.length > 0 && <div className="codex-freeze-blockers">{readiness.blockers.map((blocker) => <p key={blocker.code}><WarningCircle weight="fill" /><span><b>{blocker.message}</b><small>{blocker.action}</small></span></p>)}</div>}
      <div className="codex-freeze-confirmations"><label><input type="checkbox" checked={scopeConfirmed} onChange={(event) => setScopeConfirmed(event.target.checked)} /><span><b>我确认验收范围完整</b><small>所有有效任务都有真实验收范围，未遗漏已交付内容。</small></span></label><label><input type="checkbox" checked={timeConfirmed} onChange={(event) => setTimeConfirmed(event.target.checked)} /><span><b>我确认工时记录完整</b><small>预计工时与实际工时均已核对，包含必要返工和人工记录。</small></span></label><textarea rows={4} value={note} onChange={(event) => setNote(event.target.value)} placeholder="填写人工核验说明（至少 4 个字符）" /></div>
      {error && <p className="codex-verification-error inline"><WarningCircle weight="fill" />{error}</p>}
      <footer className="codex-sample-actions"><button type="button" onClick={onClose} disabled={busy}>取消</button><button className="primary" type="button" disabled={busy || !valid} onClick={() => void onFreeze({ request_id: requestId("outcome-freeze"), expected_revision: view.revision, confirmed_scope_complete: true, confirmed_time_complete: true, confirmation_note: note.trim() })}>{busy ? <CircleNotch className="spin" /> : <ShieldCheck weight="fill" />}{readiness.latest_freeze?.is_stale ? "追加新冻结版本" : "确认冻结结果"}</button></footer>
    </aside>
  </div>, document.body);
}

export function CodexVerificationWorkbench({ projectId, onProgressChange }: { projectId: string; onProgressChange?: (view: CodexProjectVerificationView) => void }) {
  const [view, setView] = useState<CodexProjectVerificationView | null>(null);
  const [runtime, setRuntime] = useState<CodexManagedProjectView | null>(null);
  const [selectedPointId, setSelectedPointId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showTimeForm, setShowTimeForm] = useState(false);
  const [showGitForm, setShowGitForm] = useState(false);
  const [showManualScope, setShowManualScope] = useState(false);
  const [showOutcomeFreeze, setShowOutcomeFreeze] = useState(false);
  const manualScopeTriggerRef = useRef<HTMLButtonElement>(null);
  const outcomeFreezeTriggerRef = useRef<HTMLButtonElement>(null);
  const [timeDraft, setTimeDraft] = useState({ taskId: "", category: "development" as keyof typeof categoryCopy, hours: "", note: "" });
  const [gitDraft, setGitDraft] = useState({ taskId: "", commitSha: "", note: "" });

  const acceptView = useCallback((next: CodexProjectVerificationView) => {
    setView(next);
    onProgressChange?.(next);
    setSelectedPointId((current) => current && next.points.some((point) => point.id === current) ? current : null);
  }, [onProgressChange]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextView, nextRuntime] = await Promise.all([
        localPlatformService.projectVerification(projectId),
        localPlatformService.codexManagedProject(projectId).catch(() => null),
      ]);
      acceptView(nextView);
      setRuntime(nextRuntime);
      const firstTask = nextView.delivery.tasks[0]?.task_id || "";
      setTimeDraft((current) => ({ ...current, taskId: current.taskId || firstTask }));
      setGitDraft((current) => ({ ...current, taskId: current.taskId || firstTask, commitSha: current.commitSha || nextView.git.current_commit || "" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "交付核验数据读取失败");
    } finally {
      setLoading(false);
    }
  }, [acceptView, projectId]);

  useEffect(() => { void load(); }, [load]);

  const apply = useCallback(async (promise: Promise<CodexProjectVerificationView>) => {
    setBusy(true);
    setError("");
    try {
      acceptView(await promise);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "核验操作失败，本次没有写入");
    } finally {
      setBusy(false);
    }
  }, [acceptView]);

  const selectedPoint = view?.points.find((point) => point.id === selectedPointId) || null;
  const taskCommands = useMemo(() => {
    if (!selectedPoint?.task_key) return [];
    return runtime?.tasks.find((task) => task.task_key === selectedPoint.task_key)?.test_commands || [];
  }, [runtime, selectedPoint]);
  const evidenceCount = view?.points.reduce((sum, point) => sum + point.evidence.length, 0) || 0;
  const passedTests = view?.points.reduce((sum, point) => sum + point.evidence.filter((evidence) => evidence.evidence_type === "automated_test" && evidence.exit_code === 0).length, 0) || 0;

  const addTime = () => {
    if (!view || !timeDraft.taskId || Number(timeDraft.hours) <= 0 || timeDraft.note.trim().length < 2) return;
    void apply(localPlatformService.addProjectTimeEntry(projectId, {
      request_id: requestId("time"),
      expected_revision: view.revision,
      task_id: timeDraft.taskId,
      category: timeDraft.category,
      hours: Number(timeDraft.hours),
      note: timeDraft.note.trim(),
    })).then(() => { setTimeDraft((current) => ({ ...current, hours: "", note: "" })); setShowTimeForm(false); });
  };

  const linkCommit = () => {
    if (!view || !gitDraft.taskId || !/^[0-9a-f]{7,64}$/i.test(gitDraft.commitSha.trim())) return;
    void apply(localPlatformService.linkProjectGitCommit(projectId, {
      request_id: requestId("git"),
      expected_revision: view.revision,
      task_id: gitDraft.taskId,
      point_id: selectedPoint?.task_id === gitDraft.taskId ? selectedPoint.id : null,
      commit_sha: gitDraft.commitSha.trim(),
      note: gitDraft.note.trim(),
    })).then(() => { setGitDraft((current) => ({ ...current, note: "" })); setShowGitForm(false); });
  };

  const createManualScope = async (payload: Parameters<typeof localPlatformService.createManualAcceptancePoints>[1]) => {
    setBusy(true);
    setError("");
    try {
      acceptView(await localPlatformService.createManualAcceptancePoints(projectId, payload));
      setShowManualScope(false);
      window.requestAnimationFrame(() => manualScopeTriggerRef.current?.focus());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "人工验收范围保存失败，本次没有写入");
    } finally {
      setBusy(false);
    }
  };

  const freezeOutcome = async (payload: Parameters<typeof localPlatformService.freezeProjectOutcome>[1]) => {
    setBusy(true);
    setError("");
    try {
      await localPlatformService.freezeProjectOutcome(projectId, payload);
      const next = await localPlatformService.projectVerification(projectId);
      acceptView(next);
      setShowOutcomeFreeze(false);
      window.requestAnimationFrame(() => outcomeFreezeTriggerRef.current?.focus());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "项目结果冻结失败，本次没有写入");
    } finally {
      setBusy(false);
    }
  };

  const closeManualScope = () => {
    setShowManualScope(false);
    window.requestAnimationFrame(() => manualScopeTriggerRef.current?.focus());
  };

  const closeOutcomeFreeze = () => {
    setShowOutcomeFreeze(false);
    window.requestAnimationFrame(() => outcomeFreezeTriggerRef.current?.focus());
  };

  return <section className="codex-verification-workbench" aria-label="Codex 交付核验">
    <header className="codex-verification-heading"><div><small>VERIFIED DELIVERY</small><h3>Codex 交付核验</h3><p>把开发声明、测试证据与人工验收拆开，项目进度只认已验证结果。</p></div><span>当前真实项目 · 实时更新</span></header>
    {error && !view && <div className="codex-verification-error"><WarningCircle size={19} weight="fill" /><span><b>交付核验暂不可用</b><small>{error}</small></span><button type="button" onClick={() => void load()}><ArrowClockwise />重试</button></div>}
    {loading && !view ? <div className="codex-verification-loading"><CircleNotch className="spin" size={28} />正在读取验收、工时与 Git 证据…</div> : view && <>
      <section className="codex-verification-progress-grid" aria-label="三种项目进度">
        <ProgressCard label="Codex 执行进度" value={view.progress.codex_execution.percent} detail={view.progress.warnings[0] || "按任务执行状态和预计工时加权"} tone="execution" />
        <ProgressCard label="已实现进度" value={view.progress.implemented.percent} detail="implemented 只代表已实现声明" tone="implemented" />
        <ProgressCard label="已验证交付进度" value={view.progress.verified_delivery.percent} detail="BusinessProject.progress 的唯一新口径" tone="verified" />
      </section>
      {view.legacy_progress !== null && <p className="codex-legacy-progress"><b>历史手工进度 {view.legacy_progress}%</b><span>已独立保留，不会冒充测试或人工验收证据。</span></p>}
      {view.progress.warnings.slice(1).map((warning) => <p className="codex-verification-warning" key={warning}><WarningCircle weight="fill" />{warning}</p>)}
      {error && <p className="codex-verification-error inline"><WarningCircle weight="fill" />{error}</p>}
      <section className={`codex-sample-readiness status-${view.sample_readiness.status}`} aria-label="项目样本准备度">
        <header><div><small>SAMPLE READINESS</small><h4>证据化样本形成闭环</h4><p>人工验收清单 → 证据核验 → 工时确认 → 不可变结果冻结</p></div><span>{view.sample_readiness.status === "frozen" ? `已冻结 v${view.sample_readiness.latest_freeze?.version}` : view.sample_readiness.status === "stale" ? "冻结已过期" : view.sample_readiness.can_freeze ? "可冻结" : "待补齐"}</span></header>
        <div className="codex-sample-steps">
          <article className={view.sample_readiness.active_task_count > 0 && view.sample_readiness.active_point_count > 0 ? "is-ready" : ""}><i>1</i><span><b>验收范围</b><small>{view.sample_readiness.active_point_count} 个有效验收点 · {view.sample_readiness.active_task_count} 个任务</small></span></article>
          <article className={view.sample_readiness.verified_progress === 100 && view.sample_readiness.waived_point_count === 0 ? "is-ready" : ""}><i>2</i><span><b>验收证据</b><small>{view.sample_readiness.verified_point_count}/{view.sample_readiness.active_point_count} verified · {evidenceCount} 条证据</small></span></article>
          <article className={view.sample_readiness.estimated_hours > 0 && view.sample_readiness.actual_hours > 0 ? "is-ready" : ""}><i>3</i><span><b>工时完整性</b><small>预计 {hours(view.sample_readiness.estimated_hours)} · 实际 {hours(view.sample_readiness.actual_hours)}</small></span></article>
          <article className={view.sample_readiness.calibration_eligible ? "is-ready" : ""}><i>4</i><span><b>结果冻结</b><small>{view.sample_readiness.latest_freeze ? `v${view.sample_readiness.latest_freeze.version} · ${view.sample_readiness.latest_freeze.is_stale ? "需要重冻结" : "可供校准"}` : "尚未冻结"}</small></span></article>
        </div>
        {view.sample_readiness.blockers.length > 0 && <div className="codex-sample-blocker-summary">{view.sample_readiness.blockers.slice(0, 3).map((blocker) => <span key={blocker.code}><WarningCircle weight="fill" /><b>{blocker.message}</b><small>{blocker.action}</small></span>)}</div>}
        <footer><div>{view.sample_readiness.latest_freeze && <span><b>冻结历史 {view.sample_readiness.freeze_history.length} 个版本</b><small>最新 v{view.sample_readiness.latest_freeze.version} · {dateTime(view.sample_readiness.latest_freeze.frozen_at)} · {view.sample_readiness.latest_freeze.is_stale ? "已过期" : "事实一致"}</small></span>}</div><div>{!view.delivery.plan_id && <button ref={manualScopeTriggerRef} type="button" disabled={busy || view.delivery.tasks.length === 0} onClick={() => setShowManualScope(true)}><ListChecks />人工建立验收清单</button>}<button ref={outcomeFreezeTriggerRef} className="primary" type="button" disabled={busy || !view.sample_readiness.can_freeze || Boolean(view.sample_readiness.latest_freeze && !view.sample_readiness.latest_freeze.is_stale)} onClick={() => setShowOutcomeFreeze(true)}><ShieldCheck weight="fill" />{view.sample_readiness.latest_freeze?.is_stale ? "重新核验并追加冻结" : view.sample_readiness.latest_freeze ? "结果已冻结" : "核验并冻结结果"}</button></div></footer>
      </section>
      <div className="codex-verification-main">
        <section className="codex-acceptance-panel"><header><h4>验收点与证据</h4><span>{view.points.length} 个验收点</span></header>{view.points.length ? <div className="codex-acceptance-list">{view.points.map((point) => <button type="button" key={point.id} className={`status-${point.status}`} onClick={() => setSelectedPointId(point.id)}><i>{point.status === "verified" ? <ShieldCheck weight="fill" /> : point.status === "failed" ? <WarningCircle weight="fill" /> : point.status === "test_passed" ? <CheckCircle weight="fill" /> : <Code />}</i><span><small>{point.task_key || "历史任务"} · {point.point_key} · {point.source === "manual_historical" ? "人工范围" : "计划范围"}</small><b>{point.title}</b><em>{point.task_title}</em></span><strong>{statusCopy[point.status].label}</strong></button>)}</div> : <div className="codex-acceptance-empty"><i>AC</i><b>还没有可核验的 Acceptance Point</b><p>{view.delivery.plan_id ? "已确认计划尚未形成有效验收点，请通过新的计划版本维护范围。" : "这是没有确认 Codex 计划的历史项目；可选择真实任务，逐项人工建立验收清单。系统不会根据旧任务标题、legacy 进度或聊天内容猜测标准。"}</p><div><span>现有任务 {view.delivery.tasks.length}</span><span>自动测试 {passedTests}</span><span>验收证据 {evidenceCount}</span></div>{!view.delivery.plan_id && <button type="button" onClick={() => setShowManualScope(true)}>人工建立验收清单</button>}</div>}</section>
        <aside className="codex-verification-overview"><header><h4>核验详情</h4><span>{view.points.length ? "选择验收点" : "等待计划"}</span></header><dl><div><dt>当前选择</dt><dd>{selectedPoint?.title || "项目级概览"}</dd></div><div><dt>验收状态</dt><dd>{selectedPoint ? statusCopy[selectedPoint.status].label : "无可验证验收点"}</dd></div><div><dt>计权规则</dt><dd>{view.progress.weight_basis}</dd></div><div><dt>放弃项</dt><dd>{view.progress.waived_counted}/{view.progress.waived_count} 计入</dd></div></dl><p><ShieldCheck weight="fill" />implemented 不等于 verified；测试通过也不会替代人工验收。</p></aside>
      </div>
      <section className="codex-verification-support-grid">
        <article className="codex-time-card"><header><span><Timer size={20} /><b>实际工时与偏差</b></span><button type="button" onClick={() => setShowTimeForm((value) => !value)}>{showTimeForm ? "收起" : "记录人工工时"}</button></header><dl><div><dt>预计</dt><dd>{hours(view.time.estimated_hours)}</dd></div><div><dt>实际</dt><dd>{hours(view.time.total_hours)}</dd></div><div><dt>Codex Run</dt><dd>{hours(view.time.codex_hours)}</dd></div><div><dt>偏差</dt><dd className={view.time.variance_hours > 0 ? "is-over" : ""}>{view.time.variance_hours > 0 ? "+" : ""}{hours(view.time.variance_hours)}</dd></div></dl>{showTimeForm && <div className="codex-support-form"><select aria-label="工时对应任务" value={timeDraft.taskId} onChange={(event) => setTimeDraft((current) => ({ ...current, taskId: event.target.value }))}>{view.delivery.tasks.map((task) => <option value={task.task_id} key={task.task_id}>{task.task_key ? `${task.task_key} · ` : ""}{task.title}</option>)}</select><select aria-label="工时类型" value={timeDraft.category} onChange={(event) => setTimeDraft((current) => ({ ...current, category: event.target.value as keyof typeof categoryCopy }))}>{Object.entries(categoryCopy).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select><input aria-label="工时小时数" type="number" min="0.01" step="0.25" value={timeDraft.hours} onChange={(event) => setTimeDraft((current) => ({ ...current, hours: event.target.value }))} placeholder="小时" /><input aria-label="工时说明" value={timeDraft.note} onChange={(event) => setTimeDraft((current) => ({ ...current, note: event.target.value }))} placeholder="说明（必填）" /><button type="button" disabled={busy || !timeDraft.taskId || Number(timeDraft.hours) <= 0 || timeDraft.note.trim().length < 2} onClick={addTime}>保存审计记录</button></div>}<footer><Clock size={15} />暂停与等待审批不计入 Codex 活跃工时；人工修正不会覆盖原记录。</footer></article>
        <article className="codex-git-card"><header><span><GitBranch size={20} /><b>Git 与测试证据</b></span><button type="button" disabled={!view.git.available} onClick={() => setShowGitForm((value) => !value)}>{showGitForm ? "收起" : "关联 Commit"}</button></header>{view.git.available ? <dl><div><dt>仓库 / 分支</dt><dd>{view.git.repository_name} · {view.git.branch}</dd></div><div><dt>当前 Commit</dt><dd><code>{shortSha(view.git.current_commit)}</code></dd></div><div><dt>工作区</dt><dd>{view.git.dirty ? `有 ${view.git.changed_files.length} 个变更文件` : "干净"}</dd></div><div><dt>已关联</dt><dd>{view.git_links.length} 个 Commit</dd></div></dl> : <div className="codex-support-empty"><FileCode size={23} /><span><b>尚未绑定可读取仓库</b><small>{view.git.error || "确认计划与本地仓库绑定后显示 Git 状态"}</small></span></div>}{showGitForm && view.git.available && <div className="codex-support-form codex-git-form"><select aria-label="Commit 对应任务" value={gitDraft.taskId} onChange={(event) => setGitDraft((current) => ({ ...current, taskId: event.target.value }))}>{view.delivery.tasks.map((task) => <option value={task.task_id} key={task.task_id}>{task.task_key ? `${task.task_key} · ` : ""}{task.title}</option>)}</select><input aria-label="Commit SHA" value={gitDraft.commitSha} onChange={(event) => setGitDraft((current) => ({ ...current, commitSha: event.target.value }))} placeholder="7–64 位 Commit SHA" /><input aria-label="Commit 关联说明" value={gitDraft.note} onChange={(event) => setGitDraft((current) => ({ ...current, note: event.target.value }))} placeholder="关联说明（可选）" /><button type="button" disabled={busy || !gitDraft.taskId || !/^[0-9a-f]{7,64}$/i.test(gitDraft.commitSha.trim())} onClick={linkCommit}>关联本地 Commit</button></div>}<footer><CheckCircle size={15} />{passedTests} 次测试通过 · 已验证、已提交、已推送和已合并分别显示。</footer></article>
        <article className="codex-delivery-card"><header><span><ClipboardText size={20} /><b>实时交付清单</b></span><em>{view.delivery.plan_id ? "已确认计划" : "等待计划"}</em></header>{view.delivery.deliverables.length || view.delivery.tasks.length ? <div className="codex-delivery-list">{view.delivery.deliverables.map((item) => <section key={item.deliverable_key}><span><small>{item.deliverable_key}</small><b>{item.title}</b></span><strong>{item.acceptance_verified}/{item.acceptance_total}</strong></section>)}{view.delivery.tasks.map((task) => <section key={task.task_id}><span><small>{task.task_key || "历史任务"}</small><b>{task.title}</b></span><strong>{task.acceptance_verified}/{task.acceptance_total}</strong></section>)}</div> : <div className="codex-support-empty"><ListChecks size={23} /><span><b>还没有交付清单</b><small>不会根据旧任务标题猜测交付物或验收点。</small></span></div>}<footer>{view.delivery.unresolved_issues.length ? <><WarningCircle size={15} weight="fill" />{view.delivery.unresolved_issues.length} 个待处理问题</> : <><CheckCircle size={15} />当前没有已记录的交付阻塞</>}</footer></article>
      </section>
    </>}
    {selectedPoint && view && <PointDrawer projectId={projectId} point={selectedPoint} commands={taskCommands} revision={view.revision} busy={busy} error={error} onClose={() => setSelectedPointId(null)} onApply={apply} />}
    {showManualScope && view && <ManualScopeDrawer view={view} busy={busy} error={error} onClose={closeManualScope} onCreate={createManualScope} />}
    {showOutcomeFreeze && view && <OutcomeFreezeDrawer view={view} evidenceCount={evidenceCount} busy={busy} error={error} onClose={closeOutcomeFreeze} onFreeze={freezeOutcome} />}
  </section>;
}
