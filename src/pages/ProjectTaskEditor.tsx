import {
  CalendarBlank,
  CheckCircle,
  Clock,
  ListChecks,
  PencilSimple,
  Plus,
  Trash,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Project, ProjectTask, TaskStatus } from "../types";

const statusOptions: Array<{ value: TaskStatus; label: string }> = [
  { value: "todo", label: "待开始" },
  { value: "in_progress", label: "进行中" },
  { value: "done", label: "已完成" },
];

function todayValue() {
  const date = new Date();
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 10);
}

function taskId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `task-${crypto.randomUUID()}`;
  }
  return `task-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function ProjectTaskEditor({
  project,
  task,
  onClose,
  onDelete,
  onSave,
}: {
  project: Project;
  task: ProjectTask | null;
  onClose: () => void;
  onDelete: (taskId: string) => void;
  onSave: (task: ProjectTask) => void;
}) {
  const initialStartDate = task?.startDate || todayValue();
  const [title, setTitle] = useState(task?.title || "");
  const [status, setStatus] = useState<TaskStatus>(task?.status || "todo");
  const [startDate, setStartDate] = useState(initialStartDate);
  const [dueDate, setDueDate] = useState(
    task?.dueDate || (project.dueDate >= initialStartDate ? project.dueDate : initialStartDate),
  );
  const [estimatedHours, setEstimatedHours] = useState(String(task?.estimatedHours ?? 4));
  const [actualHours, setActualHours] = useState(String(task?.actualHours ?? 0));
  const [error, setError] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const newTaskId = useRef(taskId()).current;
  const titleInput = useRef<HTMLInputElement>(null);
  const confirmDeleteButton = useRef<HTMLButtonElement>(null);
  const editing = Boolean(task);

  const dismiss = () => {
    if (confirmingDelete) {
      setConfirmingDelete(false);
      window.requestAnimationFrame(() => titleInput.current?.focus({ preventScroll: true }));
      return;
    }
    onClose();
  };

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(
      () => titleInput.current?.focus({ preventScroll: true }),
      60,
    );
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [confirmingDelete, onClose]);

  useEffect(() => {
    if (!confirmingDelete) return;
    const frame = window.requestAnimationFrame(() => confirmDeleteButton.current?.focus({ preventScroll: true }));
    return () => window.cancelAnimationFrame(frame);
  }, [confirmingDelete]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError("");
    const cleanTitle = title.trim();
    const estimated = Number(estimatedHours);
    const actual = Number(actualHours);
    if (!cleanTitle) {
      setError("请填写任务名称");
      return;
    }
    if (!startDate || !dueDate) {
      setError("请选择完整的开始日期和截止日期");
      return;
    }
    if (dueDate < startDate) {
      setError("截止日期不能早于开始日期");
      return;
    }
    if (!Number.isFinite(estimated) || estimated <= 0) {
      setError("预计工时必须大于 0");
      return;
    }
    if (!Number.isFinite(actual) || actual < 0) {
      setError("实际工时不能小于 0");
      return;
    }
    onSave({
      ...(task || {}),
      id: task?.id || newTaskId,
      projectId: project.id,
      title: cleanTitle,
      status,
      startDate,
      dueDate,
      estimatedHours: estimated,
      actualHours: actual,
    });
  };

  return createPortal(<div className="task-editor-layer" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) dismiss();
  }}>
    {confirmingDelete && task ? <section className="task-editor-modal task-delete-confirm" role="alertdialog" aria-modal="true" aria-labelledby="task-delete-title" aria-describedby="task-delete-description">
      <header>
        <i><Trash size={24} weight="duotone" /></i>
        <span><small>DELETE TASK</small><h2 id="task-delete-title">确认删除任务？</h2></span>
        <button type="button" aria-label="返回任务编辑" onClick={dismiss}><X size={19} /></button>
      </header>
      <p id="task-delete-description">“{task.title}”将从项目中永久移除。</p>
      <div className="task-delete-warning"><WarningCircle size={20} weight="fill" /><span>删除后将重新计算任务进度、实际工时和项目状态；此操作无法撤销。</span></div>
      <dl><dt>所属项目：</dt><dd>{project.name}</dd></dl>
      <footer><button type="button" onClick={dismiss}>返回编辑</button><button ref={confirmDeleteButton} className="task-delete-confirm-button" type="button" onClick={() => onDelete(task.id)}><Trash size={18} weight="bold" />确认删除</button></footer>
    </section> : <section className="task-editor-modal" role="dialog" aria-modal="true" aria-labelledby="task-editor-title" aria-describedby="task-editor-description">
      <header>
        <i>{editing ? <PencilSimple size={24} weight="duotone" /> : <Plus size={24} weight="duotone" />}</i>
        <span><small>PROJECT TASK</small><h2 id="task-editor-title">{editing ? "编辑任务" : "新增任务"}</h2><p id="task-editor-description">保存后会同步更新任务轨道、项目进度与工时统计。</p></span>
        <button type="button" aria-label="关闭任务编辑器" onClick={dismiss}><X size={19} /></button>
      </header>

      <div className="task-editor-project"><ListChecks size={20} weight="duotone" /><span><small>所属项目</small><b>{project.name}</b></span><em>{editing ? "修改已有任务" : "创建新任务"}</em></div>

      <form onSubmit={submit} noValidate>
        <label className="task-editor-title-field"><span>任务名称 <em>必填</em></span><input ref={titleInput} value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} placeholder="例如：完成登录模块与验收测试" /></label>

        <fieldset className="task-editor-status"><legend>任务状态</legend><div>{statusOptions.map((option) => <button type="button" className={status === option.value ? `active status-${option.value}` : ""} aria-pressed={status === option.value} onClick={() => setStatus(option.value)} key={option.value}><i>{option.value === "done" ? <CheckCircle size={15} weight="fill" /> : <Clock size={15} />}</i>{option.label}</button>)}</div></fieldset>

        <div className="task-editor-form-grid">
          <label><span>开始日期</span><div><CalendarBlank size={17} /><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></div></label>
          <label><span>截止日期</span><div><CalendarBlank size={17} /><input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></div></label>
          <label><span>预计工时</span><div><Clock size={17} /><input type="number" min="0.5" step="0.5" value={estimatedHours} onChange={(event) => setEstimatedHours(event.target.value)} /><em>小时</em></div></label>
          <label><span>实际工时</span><div><Clock size={17} /><input type="number" min="0" step="0.5" value={actualHours} onChange={(event) => setActualHours(event.target.value)} /><em>小时</em></div></label>
        </div>

        {error && <p className="task-editor-error" role="alert"><WarningCircle size={16} weight="fill" />{error}</p>}
        <p className="task-editor-note"><CheckCircle size={16} weight="duotone" />任务状态与工时会参与完成度、风险和项目整体进度计算。</p>

        <footer className={editing ? "has-delete" : undefined}>{editing && <button className="task-editor-delete" type="button" onClick={() => setConfirmingDelete(true)}><Trash size={17} weight="bold" />删除任务</button>}<button type="button" onClick={dismiss}>取消</button><button className="task-editor-save" type="submit">{editing ? <PencilSimple size={17} weight="bold" /> : <Plus size={17} weight="bold" />}{editing ? "保存修改" : "创建任务"}</button></footer>
      </form>
    </section>}
  </div>, document.body);
}
