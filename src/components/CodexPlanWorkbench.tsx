import {
  ArrowClockwise,
  Check,
  CheckCircle,
  Clock,
  Code,
  FloppyDisk,
  FolderOpen,
  GitBranch,
  ShieldCheck,
  Sparkle,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import {
  localPlatformService,
  type CodexDevelopmentPlan,
  type CodexPlanDocument,
  type CodexRepositoryBinding,
  type RequirementCaseDetail,
} from "../data/localPlatformService";
import { acceptMigratedLedger, getLedgerRevision, mockLedgerService } from "../data/mockService";
import type { LedgerSnapshot } from "../types";
import "./codex-plan-workbench.css";


function requestId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

export function CodexPlanWorkbench({
  detail,
  historical,
  onSnapshotChange,
}: {
  detail: RequirementCaseDetail;
  historical: boolean;
  onSnapshotChange: (snapshot: LedgerSnapshot) => void;
}) {
  const [bindings, setBindings] = useState<CodexRepositoryBinding[]>([]);
  const [bindingId, setBindingId] = useState<string>("");
  const [repositoryPath, setRepositoryPath] = useState("");
  const [plan, setPlan] = useState<CodexDevelopmentPlan | null>(null);
  const [draft, setDraft] = useState<CodexPlanDocument | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [confirmedIntent, setConfirmedIntent] = useState(false);

  useEffect(() => {
    let active = true;
    setError("");
    void Promise.all([
      localPlatformService.codexBindings(detail.id),
      localPlatformService.latestCodexPlanForCase(detail.id),
    ]).then(([bindingRows, latest]) => {
      if (!active) return;
      setBindings(bindingRows);
      setBindingId(bindingRows[0]?.id || "");
      setPlan(latest);
      setDraft(latest ? structuredClone(latest.document) : null);
    }).catch((reason) => active && setError(reason instanceof Error ? reason.message : "开发计划读取失败"));
    return () => { active = false; };
  }, [detail.id]);

  const selectedTasks = useMemo(
    () => draft?.tasks.filter((task) => task.included) || [],
    [draft],
  );
  const selectedHours = useMemo(
    () => selectedTasks.reduce((sum, task) => sum + Number(task.estimated_hours || 0), 0),
    [selectedTasks],
  );

  const bindRepository = async () => {
    if (!repositoryPath.trim()) return;
    setLoading(true);
    setError("");
    try {
      const binding = await localPlatformService.bindCodexRepository({
        request_id: requestId("codex-bind"),
        requirement_case_id: detail.id,
        project_id: detail.project_id,
        repository_path: repositoryPath.trim(),
      });
      setBindings((rows) => [binding, ...rows.filter((row) => row.id !== binding.id)]);
      setBindingId(binding.id);
      setRepositoryPath("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "仓库绑定失败");
    } finally {
      setLoading(false);
    }
  };

  const generate = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await localPlatformService.generateCodexPlan({
        request_id: requestId("codex-plan"),
        requirement_case_id: detail.id,
        expected_requirement_version: detail.current_version,
        binding_id: bindingId || null,
      });
      setPlan(result);
      setDraft(structuredClone(result.document));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Codex 开发计划生成失败");
    } finally {
      setLoading(false);
    }
  };

  const patchTask = (index: number, patch: Partial<CodexPlanDocument["tasks"][number]>) => {
    setDraft((current) => {
      if (!current) return current;
      const tasks = [...current.tasks];
      tasks[index] = { ...tasks[index], ...patch };
      return { ...current, tasks };
    });
  };

  const save = async () => {
    if (!plan || !draft) return;
    setLoading(true);
    setError("");
    try {
      const result = await localPlatformService.updateCodexPlan(plan.id, {
        request_id: requestId("codex-plan-edit"),
        expected_updated_at: plan.updated_at,
        document: draft,
      });
      setPlan(result);
      setDraft(structuredClone(result.document));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "开发计划保存失败");
    } finally {
      setLoading(false);
    }
  };

  const confirm = async () => {
    if (!plan || !confirmedIntent) return;
    const revision = getLedgerRevision();
    if (revision === null) {
      setError("经营数据尚未连接 SQLite，请刷新页面后再确认导入");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await localPlatformService.confirmCodexPlan(plan.id, {
        request_id: requestId("codex-plan-confirm"),
        expected_updated_at: plan.updated_at,
        expected_requirement_version: detail.current_version,
        expected_revision: revision,
        confirmed: true,
      });
      acceptMigratedLedger(result.revision);
      const snapshot = await mockLedgerService.getDashboard();
      onSnapshotChange(snapshot);
      setPlan(result.plan);
      setDraft(structuredClone(result.plan.document));
      setConfirming(false);
      setConfirmedIntent(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "计划导入失败");
    } finally {
      setLoading(false);
    }
  };

  return <section className="codex-plan-workbench" aria-label="Codex 开发计划">
    <header>
      <div><span><Code size={17} />CODEX DEVELOPMENT PLAN</span><h3>开发计划与项目任务同步</h3><p>Codex 只读分析需求和已授权仓库；确认前不会创建项目、任务或修改客户代码。</p></div>
      <div className="codex-plan-safety"><ShieldCheck size={22} weight="duotone" /><span><b>人工闸门</b><small>预览、修订、确认后才导入</small></span></div>
    </header>

    {historical && <div className="codex-plan-notice"><WarningCircle size={18} />当前正在查看历史需求版本。请切回最新版本后生成或确认计划。</div>}
    {error && <div className="codex-plan-error"><WarningCircle size={18} />{error}</div>}

    <div className="codex-plan-source">
      <label><span>只读分析范围</span><select value={bindingId} onChange={(event) => setBindingId(event.target.value)} disabled={historical || loading}>
        <option value="">仅分析确认需求（不读取仓库）</option>
        {bindings.map((binding) => <option key={binding.id} value={binding.id}>{binding.repository_name} · {binding.default_branch} · {binding.current_head_sha.slice(0, 8)}</option>)}
      </select></label>
      <label className="codex-repo-path"><span>绑定本地 Git 仓库根目录</span><div><FolderOpen size={18} /><input value={repositoryPath} onChange={(event) => setRepositoryPath(event.target.value)} placeholder="/Users/你/Projects/customer-app" disabled={historical || loading} /><button onClick={bindRepository} disabled={!repositoryPath.trim() || historical || loading}>验证并绑定</button></div></label>
      <button className="codex-generate" onClick={generate} disabled={historical || loading}>
        {loading ? <ArrowClockwise className="spin" size={18} /> : <Sparkle size={18} weight="fill" />}{plan ? "生成新版本" : "生成 Codex 开发计划"}
      </button>
    </div>

    {plan && draft ? <div className="codex-plan-body">
      <div className="codex-plan-summary">
        <div><span>PLAN V{plan.version}</span><h4>{draft.title}</h4><p>{draft.summary}</p></div>
        <div className="codex-estimate"><Clock size={21} /><span><small>预计工时区间</small><b>{draft.estimate.low_hours}–{draft.estimate.high_hours}h</b><em>期望 {draft.estimate.expected_hours}h · {draft.estimate.confidence}</em></span></div>
        <div className="codex-repository-snapshot"><GitBranch size={18} /><span>{plan.repository_mode === "repository" ? `${plan.repository_name} · ${plan.repository_branch}` : "仅需求模式"}<small>{plan.repository_head_sha ? `${plan.repository_head_sha.slice(0, 10)}${plan.repository_dirty ? " · 生成时有未提交改动" : " · 干净快照"}` : "未读取任何代码仓库"}</small></span></div>
      </div>

      <div className="codex-plan-columns">
        <section><h5>交付清单 <b>{draft.deliverables.length}</b></h5>{draft.deliverables.map((item) => <article key={item.deliverable_key}><span>{item.deliverable_key}</span><b>{item.title}</b><p>{item.description}</p><small>{item.acceptance_criteria.join(" · ")}</small></article>)}</section>
        <section className="codex-plan-risks"><h5>假设与风险 <b>{draft.assumptions.length + draft.risks.length}</b></h5>{draft.assumptions.map((item) => <p key={`a-${item}`}><CheckCircle size={15} />{item}</p>)}{draft.risks.map((item) => <p key={`r-${item}`} className="risk"><WarningCircle size={15} />{item}</p>)}</section>
      </div>

      <div className="codex-task-editor">
        <header><div><h5>任务与验收点</h5><p>稳定 task_key 用于更新同一任务，不按标题猜测。</p></div><strong>{selectedTasks.length} 项 · {selectedHours.toFixed(1)}h</strong></header>
        {draft.tasks.map((task, index) => <article key={task.task_key} className={task.included ? "" : "excluded"}>
          <label className="task-toggle"><input type="checkbox" checked={task.included} onChange={(event) => patchTask(index, { included: event.target.checked })} disabled={plan.status !== "draft"} /><i><Check size={13} weight="bold" /></i></label>
          <div className="task-copy"><span>{task.task_key} · {task.stage_key}</span><input value={task.title} onChange={(event) => patchTask(index, { title: event.target.value })} disabled={plan.status !== "draft"} /><textarea rows={2} value={task.description} onChange={(event) => patchTask(index, { description: event.target.value })} disabled={plan.status !== "draft"} /><div className="task-acceptance">{task.acceptance_points.map((point, pointIndex) => <label key={point.point_key}><CheckCircle size={14} /><input value={point.title} disabled={plan.status !== "draft"} onChange={(event) => patchTask(index, { acceptance_points: task.acceptance_points.map((current, currentIndex) => currentIndex === pointIndex ? { ...current, title: event.target.value } : current) })} /></label>)}</div>{task.test_commands.length > 0 && <code>{task.test_commands.join(" · ")}</code>}</div>
          <label className="task-hours"><span>预计工时</span><input type="number" min="0.5" step="0.5" value={task.estimated_hours} onChange={(event) => patchTask(index, { estimated_hours: Number(event.target.value) })} disabled={plan.status !== "draft"} /><small>小时</small></label>
        </article>)}
      </div>

      <footer className="codex-plan-actions">
        <span>{plan.status === "confirmed" ? <><CheckCircle size={18} weight="fill" />已确认并同步至项目 {plan.project_id}</> : <>原始 Codex 输出已保留；当前修改只影响人工确认版本。</>}</span>
        {plan.status === "draft" && <div><button onClick={save} disabled={loading}><FloppyDisk size={18} />保存修订</button><button className="primary" onClick={() => setConfirming(true)} disabled={loading || selectedTasks.length === 0}><CheckCircle size={18} />确认并导入项目</button></div>}
      </footer>
    </div> : <div className="codex-plan-empty"><Sparkle size={27} /><div><b>还没有开发计划</b><p>可先仅根据需求生成，也可以绑定客户代码仓库后进行只读分析。</p></div></div>}

    {confirming && plan && <div className="codex-confirm-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setConfirming(false)}><section role="dialog" aria-modal="true" aria-labelledby="codex-confirm-title">
      <button className="close" onClick={() => setConfirming(false)} aria-label="关闭"><X size={20} /></button>
      <ShieldCheck size={34} weight="duotone" />
      <h3 id="codex-confirm-title">确认导入开发计划</h3>
      <p>将把 {selectedTasks.length} 个任务同步到{detail.project_id ? "现有项目" : "一个新建项目"}，项目预计工时按已选择任务汇总为 {selectedHours.toFixed(1)} 小时。</p>
      <ul><li>不会启动 Codex 开发或修改仓库</li><li>不会覆盖已有任务的人工状态和实际工时</li><li>同一 task_key 重复确认不会创建重复任务</li></ul>
      <label className="confirm-intent"><input type="checkbox" checked={confirmedIntent} onChange={(event) => setConfirmedIntent(event.target.checked)} /><span>我已检查任务、工时、交付物和验收点，确认导入。</span></label>
      <footer><button onClick={() => setConfirming(false)}>返回修改</button><button className="primary" disabled={!confirmedIntent || loading} onClick={confirm}>{loading ? <ArrowClockwise className="spin" size={18} /> : <CheckCircle size={18} />}确认导入</button></footer>
    </section></div>}
  </section>;
}
