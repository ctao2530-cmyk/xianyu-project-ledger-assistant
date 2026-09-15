import {
  ArrowsLeftRight,
  CaretDown,
  Check,
  CheckCircle,
  FileText,
  FunnelSimple,
  MagnifyingGlass,
  PlusCircle,
  ShieldCheck,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ProjectTaskDraftClassification, ProjectTaskDraftPreviewView } from "../data/localPlatformService";
import "./project-task-draft-drawer.css";

const labels: Record<ProjectTaskDraftClassification, string> = {
  new: "新增",
  update_allowed: "内容变化",
  unchanged: "保持不变",
  protected: "受保护",
  conflict: "冲突",
};

const summaryItems: Array<[ProjectTaskDraftClassification, typeof PlusCircle]> = [
  ["new", PlusCircle],
  ["update_allowed", FileText],
  ["unchanged", ArrowsLeftRight],
  ["protected", ShieldCheck],
  ["conflict", WarningCircle],
];

const pretty = (value: unknown) => {
  if (Array.isArray(value)) return value.length ? value.join("、") : "—";
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return `${value}`;
  return String(value);
};

const fieldLabels: Record<string, string> = {
  title: "任务标题",
  description: "任务描述",
  estimated_hours: "预计工时",
  acceptance_criteria: "验收标准",
  dependency_task_keys: "依赖关系",
  deliverables: "交付物",
  workspace_key: "工作区",
  stage_key: "阶段标识",
};

export function ProjectTaskDraftDrawer({
  preview,
  busy,
  error,
  onClose,
  onConfirm,
}: {
  preview: ProjectTaskDraftPreviewView;
  busy: boolean;
  error: string;
  onClose: () => void;
  onConfirm: (taskKeys: string[]) => void;
}) {
  const [filter, setFilter] = useState<"all" | "action" | "protected" | "conflict">("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(() => new Set(preview.items.filter((item) => item.selected).map((item) => item.task_key)));
  const [activeKey, setActiveKey] = useState(preview.items[0]?.task_key || "");
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), [tabindex='0']")];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const visible = useMemo(() => preview.items.filter((item) => {
    const matchesQuery = !query.trim() || item.task_key.toLowerCase().includes(query.trim().toLowerCase());
    const matchesFilter = filter === "all"
      || (filter === "action" && ["new", "update_allowed"].includes(item.classification))
      || (filter === "protected" && item.classification === "protected")
      || (filter === "conflict" && item.classification === "conflict");
    return matchesQuery && matchesFilter;
  }), [filter, preview.items, query]);

  const active = preview.items.find((item) => item.task_key === activeKey) || visible[0] || preview.items[0];
  const groups = useMemo(() => {
    const grouped = new Map<string, typeof visible>();
    visible.forEach((item) => {
      const key = item.workspace_key || "未分配工作区";
      grouped.set(key, [...(grouped.get(key) || []), item]);
    });
    return [...grouped.entries()];
  }, [visible]);
  const allowedCount = preview.items.filter((item) => ["new", "update_allowed"].includes(item.classification)).length;
  const selectedCreate = preview.items.filter((item) => selected.has(item.task_key) && item.classification === "new").length;
  const selectedUpdate = preview.items.filter((item) => selected.has(item.task_key) && item.classification === "update_allowed").length;

  const toggle = (taskKey: string) => {
    const item = preview.items.find((candidate) => candidate.task_key === taskKey);
    if (!item || !["new", "update_allowed"].includes(item.classification)) return;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(taskKey)) next.delete(taskKey); else next.add(taskKey);
      return next;
    });
  };

  return createPortal(<div className="task-draft-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} className="task-draft-drawer" role="dialog" aria-modal="true" aria-labelledby="task-draft-title">
      <header className="task-draft-head">
        <div><h2 id="task-draft-title">蓝图任务差异</h2><p>当前项目任务 <ArrowsLeftRight size={12} /> 需求蓝图 V{preview.requirement_version}</p></div>
        <span>预览未写入</span>
        <button ref={closeRef} type="button" onClick={onClose} aria-label="关闭蓝图任务差异"><X size={20} /></button>
      </header>

      <div className="task-draft-summary">
        {summaryItems.map(([key, Icon]) => <article key={key} className={`tone-${key}`}><i><Icon size={18} weight="duotone" /></i><span><small>{labels[key]}</small><strong>{preview.summary[key] || 0}</strong></span></article>)}
      </div>

      <div className="task-draft-toolbar">
        <div>{([['all', '全部'], ['action', '需处理'], ['protected', '受保护'], ['conflict', '冲突']] as const).map(([key, label]) => <button key={key} type="button" className={filter === key ? "active" : ""} onClick={() => setFilter(key)}>{label}</button>)}</div>
        <label><MagnifyingGlass size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 task_key" /></label>
        <button type="button" aria-label="筛选任务"><FunnelSimple size={17} /></button>
      </div>

      <div className="task-draft-body">
        <section className="task-draft-queue">
          <header><b>差异任务清单（{preview.items.length}）</b><span>按工作区分组 <CaretDown size={12} /></span></header>
          <div>
            {groups.map(([workspace, items]) => <section key={workspace} className="task-draft-group">
              <h3><CaretDown size={13} />{workspace} <small>({items.length})</small></h3>
              {items.map((item) => {
                const selectable = ["new", "update_allowed"].includes(item.classification);
                return <button type="button" key={item.id} className={`task-draft-row ${active?.task_key === item.task_key ? "active" : ""}`} onClick={() => setActiveKey(item.task_key)}>
                  <span role="checkbox" aria-checked={selected.has(item.task_key)} tabIndex={selectable ? 0 : -1} className={`task-draft-check ${selected.has(item.task_key) ? "checked" : ""} ${selectable ? "" : "disabled"}`} onClick={(event) => { event.stopPropagation(); toggle(item.task_key); }} onKeyDown={(event) => { if (event.key === " " || event.key === "Enter") { event.preventDefault(); toggle(item.task_key); } }}>{selected.has(item.task_key) && <Check size={12} weight="bold" />}</span>
                  <i className={`dot-${item.classification}`} />
                  <span><small>{item.task_key}</small><b>{pretty(item.proposed.title || item.current.title)}</b></span>
                  <em className={`status-${item.classification}`}>{labels[item.classification]}</em>
                  <small>{pretty(item.current.estimated_hours)}h <ArrowsLeftRight size={10} /> {pretty(item.proposed.estimated_hours)}h</small>
                </button>;
              })}
            </section>)}
            {!visible.length && <p className="task-draft-empty">当前筛选下没有任务差异。</p>}
          </div>
        </section>

        <section className="task-draft-compare">
          {active ? <>
            <header><span><i /><b>已选择：{active.task_key}</b><small>· {pretty(active.proposed.title || active.current.title)}</small></span></header>
            {(active.classification === "protected" || active.protected_fields.length > 0) && <div className="task-draft-protected"><ShieldCheck size={19} weight="duotone" /><span><b>受保护说明</b><small>任务的状态、实际工时与验收证据为受保护数据，不会被蓝图覆盖。</small></span></div>}
            {active.classification === "conflict" && <div className="task-draft-conflict"><WarningCircle size={19} /><span><b>存在冲突</b><small>{active.conflict_reason}</small></span></div>}
            <div className="task-draft-compare-columns">
              <article><h3>项目当前值</h3>{Object.keys(fieldLabels).map((key) => <div key={key}><small>{fieldLabels[key]}</small><p>{pretty(active.current[key])}</p></div>)}</article>
              <article className="is-blueprint"><h3>蓝图建议值</h3>{Object.keys(fieldLabels).map((key) => {
                const changed = pretty(active.current[key]) !== pretty(active.proposed[key]);
                return <div key={key} className={changed ? "changed" : ""}><small>{fieldLabels[key]}</small><p>{pretty(active.proposed[key])}</p>{changed && <em>已变化</em>}</div>;
              })}</article>
            </div>
            <label className="task-draft-safe-option"><span className="checked"><Check size={12} weight="bold" /></span><b>仅应用允许更新的字段</b><small>已为你过滤受保护内容</small></label>
          </> : <p className="task-draft-empty">选择左侧任务查看字段差异。</p>}
        </section>
      </div>

      <footer className="task-draft-footer">
        <div><b>已选择 {selected.size} 项</b><span>· 新增 {selectedCreate} / 更新 {selectedUpdate}</span>{error && <small>{error}</small>}</div>
        <button type="button" onClick={onClose}>返回蓝图</button>
        <button type="button" className="is-primary" disabled={busy || selected.size === 0 || selected.size > allowedCount} onClick={() => onConfirm([...selected])}>{busy ? "正在写入…" : `确认并写入 ${selected.size} 项`}</button>
        <small>当前为预览数据；若蓝图版本或项目 revision 变化，将自动拒绝写入以保障数据安全。</small>
      </footer>
    </section>
  </div>, document.body);
}
