import {
  CheckCircle,
  CircleNotch,
  Code,
  FileCode,
  Flask,
  FolderOpen,
  Pause,
  PauseCircle,
  Play,
  Pulse,
  ShieldWarning,
  Stop,
  TerminalWindow,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from "react";
import {
  connectPlatformEvents,
  localPlatformService,
  type CodexConnectionStatus,
  type CodexManagedApproval,
  type CodexManagedDiff,
  type CodexManagedProjectView,
  type CodexProjectSyncView,
  type CodexSyncEventView,
} from "../data/localPlatformService";
import "./codex-sync-workbench.css";

const statusCopy: Record<CodexConnectionStatus, { label: string; detail: string }> = {
  not_connected: { label: "尚未连接", detail: "还没有收到这个项目的 Codex 事件" },
  idle: { label: "空闲", detail: "当前没有运行中的开发活动" },
  running: { label: "运行中", detail: "Codex 正在受管 Worktree 中开发" },
  blocked: { label: "存在阻塞", detail: "Codex 已上报需要人工处理的阻塞" },
  failed: { label: "运行失败", detail: "最近一次运行以失败结束" },
  completed: { label: "运行结束", detail: "Codex 已结束本轮，仍需人工验收" },
  disconnected: { label: "连接中断", detail: "历史可读取，实时通道正在重连" },
};

const eventCopy: Record<string, { label: string; icon: ComponentType<{ size?: number; weight?: "duotone" | "fill" }> }> = {
  session_start: { label: "外部会话开始", icon: Pulse },
  session_end: { label: "外部会话结束", icon: PauseCircle },
  run_started: { label: "托管运行开始", icon: Play },
  run_completed: { label: "本轮运行结束", icon: CheckCircle },
  run_failed: { label: "运行失败", icon: WarningCircle },
  run_interrupted: { label: "本轮已中断", icon: PauseCircle },
  plan_updated: { label: "计划更新", icon: Pulse },
  task_start: { label: "任务开始", icon: Code },
  task_started: { label: "任务开始", icon: Code },
  checkpoint: { label: "开发检查点", icon: Pulse },
  task_blocked: { label: "任务阻塞", icon: WarningCircle },
  test_result: { label: "测试结果", icon: Flask },
  test_reported: { label: "测试结果", icon: Flask },
  task_complete: { label: "声明实现完成", icon: CheckCircle },
  task_implemented: { label: "声明实现完成", icon: CheckCircle },
  file_change: { label: "文件变更", icon: FileCode },
  file_changed: { label: "文件变更", icon: FileCode },
  diff_updated: { label: "Diff 更新", icon: FileCode },
  command: { label: "命令执行", icon: TerminalWindow },
  command_started: { label: "命令开始", icon: TerminalWindow },
  command_completed: { label: "命令完成", icon: TerminalWindow },
  approval_requested: { label: "等待审批", icon: ShieldWarning },
  permission_request: { label: "权限请求", icon: WarningCircle },
};

const activeStatuses = new Set(["pending", "starting", "running", "waiting_approval", "blocked"]);
const visibleRunStatuses = new Set([...activeStatuses, "paused"]);
const requestId = () => crypto.randomUUID();

function formatTime(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
}

function eventDescription(event: CodexSyncEventView) {
  if (event.blocker) return event.blocker;
  if (event.summary) return event.summary;
  if (event.command) return event.command;
  if (event.files.length) return `记录 ${event.files.length} 个文件变更`;
  return event.task_key ? `关联任务 ${event.task_key}` : "项目级开发活动（未绑定任务）";
}

function ApprovalDrawer({ approval, busy, onClose, onDecision }: { approval: CodexManagedApproval; busy: boolean; onClose: () => void; onDecision: (decision: "approve_once" | "reject" | "cancel") => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return <div className="codex-approval-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <aside className="codex-approval-drawer" role="dialog" aria-modal="true" aria-labelledby="codex-approval-title">
      <header><span><small>HUMAN APPROVAL</small><h3 id="codex-approval-title">高风险操作审批</h3></span><button ref={closeRef} onClick={onClose} aria-label="关闭审批"><X size={20} /></button></header>
      <div className={`codex-risk-badge is-${approval.risk_level}`}><ShieldWarning size={20} weight="fill" />{approval.risk_level === "critical" ? "关键风险" : "高风险"} · 仅可单次批准</div>
      <dl>
        <div><dt>请求操作</dt><dd>{approval.approval_kind === "file_change" ? "修改文件" : "执行命令"}</dd></div>
        <div><dt>原因</dt><dd>{approval.reason || "Codex 请求额外权限"}</dd></div>
        <div><dt>命令</dt><dd><code>{approval.command || "未提供命令"}</code></dd></div>
        <div><dt>工作目录</dt><dd><code>{approval.cwd || "受管 Worktree"}</code></dd></div>
      </dl>
      <p>循营不会提供“本会话全部允许”。批准只绑定这一次 App Server 请求；拒绝会把明确结果返回 Codex。</p>
      <footer><button disabled={busy} onClick={() => onDecision("reject")}>拒绝</button><button disabled={busy} className="danger" onClick={() => onDecision("cancel")}>拒绝并取消</button><button disabled={busy} className="primary" onClick={() => onDecision("approve_once")}>{busy ? <CircleNotch className="spin" /> : <ShieldWarning />}单次批准</button></footer>
    </aside>
  </div>;
}

export function CodexSyncWorkbench({ projectId }: { projectId: string }) {
  const [sync, setSync] = useState<CodexProjectSyncView | null>(null);
  const [managed, setManaged] = useState<CodexManagedProjectView | null>(null);
  const [selectedTask, setSelectedTask] = useState("");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("high");
  const [ackDirty, setAckDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [diff, setDiff] = useState<CodexManagedDiff | null>(null);
  const [approval, setApproval] = useState<CodexManagedApproval | null>(null);
  const [liveState, setLiveState] = useState<"connecting" | "connected" | "disconnected">("connecting");

  const refresh = useCallback(async () => {
    try {
      const [nextSync, nextManaged] = await Promise.all([
        localPlatformService.codexProjectSync(projectId),
        localPlatformService.codexManagedProject(projectId),
      ]);
      setSync(nextSync);
      setManaged(nextManaged);
      setSelectedTask((current) => current || nextManaged.tasks[0]?.task_key || "");
      const pending = nextManaged.current_run?.approvals.find((item) => item.status === "pending") || null;
      if (pending) setApproval(pending);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Codex 运行状态读取失败");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    void refresh();
    return connectPlatformEvents(
      (event) => {
        if (event.type === "codex_event_committed" && event.project_id === projectId) void refresh();
      },
      (state) => {
        setLiveState(state);
        if (state === "connected") void refresh();
      },
    );
  }, [projectId, refresh]);

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try { await action(); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); }
    finally { setBusy(false); }
  };
  const run = managed?.current_run || null;
  const connection = sync?.connection_status || "not_connected";
  const status = statusCopy[connection];
  const implemented = sync?.current_task?.codex_execution_status === "implemented";
  const timeline = useMemo(() => sync?.events || [], [sync]);
  const canStart = Boolean(managed?.ready && selectedTask && managed.binding && !run?.status?.match(/^(pending|starting|running|waiting_approval|blocked)$/));

  const start = () => {
    if (!managed?.binding || !selectedTask) return;
    void act(() => localPlatformService.startCodexManagedRun({
      request_id: requestId(), project_id: projectId, task_key: selectedTask,
      binding_id: managed.binding!.id, model, reasoning_effort: effort,
      sandbox_mode: "workspace-write", approval_mode: "untrusted",
      acknowledge_dirty_repository: ackDirty,
    }));
  };
  const showDiff = () => run && void act(async () => setDiff(await localPlatformService.codexManagedDiff(run.id)));
  const decide = (decision: "approve_once" | "reject" | "cancel") => {
    if (!approval) return;
    void act(async () => {
      await localPlatformService.decideCodexApproval(approval.id, requestId(), decision);
      setApproval(null);
    });
  };

  return <section className="codex-sync-workbench" aria-label="Codex 托管开发与外部同步">
    <header className="codex-sync-heading">
      <div><small>MANAGED CODEX DEVELOPMENT</small><h3>Codex 同步</h3><p>在独立 Worktree 中启动和管理 Codex；外部事件同步继续保留。</p></div>
      <span className={`codex-live-state is-${liveState}`}><i />{liveState === "connected" ? "实时通道已连接" : liveState === "connecting" ? "实时通道连接中" : "实时通道重连中"}</span>
    </header>

    {error && <div className="codex-sync-error" role="alert"><WarningCircle size={19} weight="fill" /><span><b>Codex 操作未完成</b><small>{error}</small></span></div>}

    {!run || !visibleRunStatuses.has(run.status) ? <section className="codex-readiness">
      <header><span><small>RUN READINESS</small><h4>开始一次安全开发运行</h4></span><em>{managed?.ready ? "已满足启动条件" : "等待真实项目数据"}</em></header>
      <ol className="codex-readiness-steps">
        <li className={selectedTask ? "is-ready" : ""}><i>1</i><span><b>选择任务</b><small>仅显示稳定 task_key</small></span></li>
        <li className={managed?.binding ? "is-ready" : ""}><i>2</i><span><b>确认仓库</b><small>独立 Worktree，不含主工作区未提交内容</small></span></li>
        <li className={managed?.runtime.available ? "is-ready" : ""}><i>3</i><span><b>运行设置</b><small>workspace-write · untrusted</small></span></li>
        <li className={canStart ? "is-ready" : ""}><i>4</i><span><b>人工启动</b><small>不会自动提交、推送或合并</small></span></li>
      </ol>
      <div className="codex-run-form">
        <label><span>开发任务</span><select value={selectedTask} onChange={(event) => setSelectedTask(event.target.value)}><option value="">选择带 task_key 的任务</option>{managed?.tasks.map((task) => <option key={task.task_key} value={task.task_key}>{task.task_key} · {task.title}</option>)}</select></label>
        <label><span>模型</span><input value={model} onChange={(event) => setModel(event.target.value)} placeholder="使用 Codex 默认模型" /></label>
        <label><span>推理强度</span><select value={effort} onChange={(event) => setEffort(event.target.value)}><option value="medium">medium</option><option value="high">high</option><option value="xhigh">xhigh</option></select></label>
        <div className="codex-repository-fact"><small>已绑定仓库{managed?.binding?.repository_dirty ? " · 主工作区有未提交内容" : ""}</small><b>{managed?.binding?.repository_name || "尚未绑定"}</b><code>{managed?.binding?.actual_head_sha?.slice(0, 12) || managed?.binding?.current_head_sha?.slice(0, 12) || "—"}</code></div>
      </div>
      <label className="codex-dirty-ack"><input type="checkbox" checked={ackDirty} onChange={(event) => setAckDirty(event.target.checked)} /><span>如果主工作区存在未提交内容，我确认它们不会被复制到新 Worktree。</span></label>
      {!managed?.ready && <div className="codex-readiness-reasons">{managed?.readiness_reasons.map((reason) => <span key={reason}><WarningCircle />{reason}</span>)}</div>}
      <footer><button className="codex-primary-action" disabled={!canStart || busy} onClick={start}>{busy ? <CircleNotch className="spin" /> : <Play weight="fill" />}开始开发</button><small>启动只处理所选 task_key，且不会更新 verified。</small></footer>
    </section> : <section className="codex-running-panel">
      <header><span><small>ACTIVE MANAGED RUN</small><h4>{run.task_key} · {run.status}</h4><p>{run.branch}</p></span><div className="codex-run-controls">
        {run.status === "paused" ? <button disabled={busy} onClick={() => void act(() => localPlatformService.resumeCodexManagedRun(run.id, requestId()))}><Play />继续</button> : <button disabled={busy || run.status === "waiting_approval"} onClick={() => void act(() => localPlatformService.pauseCodexManagedRun(run.id, requestId()))}><Pause />暂停</button>}
        <button disabled={busy} className="danger" onClick={() => void act(() => localPlatformService.cancelCodexManagedRun(run.id, requestId()))}><Stop />取消</button>
        <button disabled={busy} onClick={() => void act(() => localPlatformService.openCodexWorktree(run.id))}><FolderOpen />打开 Worktree</button>
      </div></header>
      <div className="codex-run-facts"><span><small>Base</small><code>{run.base_commit_sha.slice(0, 12)}</code></span><span><small>Sandbox</small><b>{run.sandbox_mode}</b></span><span><small>审批</small><b>{run.approval_mode}</b></span><span><small>Thread</small><code>{run.thread_id || "正在创建"}</code></span></div>
    </section>}

    <div className="codex-sync-status-grid">
      <article className={`codex-sync-status status-${connection}`}><small>运行状态</small><b><i />{status.label}</b><span>{status.detail}</span></article>
      <article><small>当前运行</small><b>{run ? run.id.replace("codex-run-", "#").slice(0, 15) : sync?.current_run ? sync.current_run.id.replace("codex-run-", "#").slice(0, 15) : "—"}</b><span>{run ? `${run.runtime_type} · ${run.status}` : "等待启动或外部事件"}</span></article>
      <article><small>当前任务</small><b>{run?.task_key || sync?.current_task?.task_key || "—"}</b><span>{sync?.current_task?.title || "无 task_key 的事件不会修改任务"}</span></article>
      <article><small>最后同步</small><b>{formatTime(sync?.last_sync_at || null)}</b><span>重启后从 SQLite 恢复，运行不会自动续行</span></article>
    </div>

    <div className="codex-sync-main">
      <section className="codex-sync-timeline" aria-live="polite">
        <header><span><small>ACTIVITY TIMELINE</small><h4>计划、命令、文件与测试</h4></span><em>{timeline.length} 条持久化事件</em></header>
        {loading && !sync ? <div className="codex-sync-loading"><CircleNotch size={25} className="spin" />正在读取本地事件历史…</div> : timeline.length ? <div className="codex-sync-event-list">{timeline.map((event) => {
          const meta = eventCopy[event.event_type] || { label: event.event_type, icon: Code };
          const Icon = meta.icon;
          return <article className={`event-${event.event_type}`} key={event.event_id}><i><Icon size={19} weight={event.event_type.includes("blocked") ? "fill" : "duotone"} /></i><div><span><b>{meta.label}</b><time>{formatTime(event.occurred_at)}</time></span><p>{eventDescription(event)}</p><footer>{event.task_key ? <em className={event.task_mapped ? "is-mapped" : "is-unmapped"}>{event.task_key}{event.task_mapped ? " · 已映射" : " · 未映射"}</em> : <em>项目级活动</em>}{event.files.slice(0, 3).map((file) => <code key={file}>{file}</code>)}{event.exit_code !== null && <em className={event.exit_code === 0 ? "is-pass" : "is-fail"}>exit {event.exit_code}</em>}</footer></div></article>;
        })}</div> : <div className="codex-sync-empty"><Code size={34} weight="duotone" /><b>还没有 Codex 开发活动</b><p>满足真实任务、确认计划和仓库绑定后，可在上方创建独立 Worktree 并启动。</p></div>}
      </section>

      <aside className="codex-sync-summary">
        <header><small>RUN SUMMARY</small><h4>运行摘要</h4></header>
        <dl><div><dt>文件变更</dt><dd>{sync?.counts.files || 0}</dd></div><div><dt>命令执行</dt><dd>{sync?.counts.commands || 0}</dd></div><div><dt>测试结果</dt><dd>{sync?.counts.tests || 0}</dd></div><div><dt>阻塞事件</dt><dd>{sync?.counts.blockers || 0}</dd></div></dl>
        <button className="codex-diff-button" disabled={!run?.worktree_path || busy} onClick={showDiff}><FileCode />查看当前 Diff</button>
        {diff && <div className="codex-diff-preview"><header><b>{diff.branch}</b><button onClick={() => setDiff(null)} aria-label="关闭 Diff"><X /></button></header><pre>{diff.diff || "当前 Worktree 没有未提交 Diff"}</pre>{diff.truncated && <small>Diff 已按安全上限截断</small>}</div>}
        <div className={`codex-sync-verification ${implemented ? "is-implemented" : ""}`}>{implemented ? <CheckCircle size={24} weight="fill" /> : <PauseCircle size={24} weight="duotone" />}<span><b>{implemented ? "Codex 已实现，等待验收" : "implemented 与 verified 分离"}</b><small>运行结束不会改变人工任务状态、项目进度或交付验收。</small></span></div>
        <p className="codex-sync-safety">不自动提交、推送、合并或删除 Worktree。无 task_key 的事件不能修改任务。</p>
      </aside>
    </div>
    {approval && <ApprovalDrawer approval={approval} busy={busy} onClose={() => setApproval(null)} onDecision={decide} />}
  </section>;
}
