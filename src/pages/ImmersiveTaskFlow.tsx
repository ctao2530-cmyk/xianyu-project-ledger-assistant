import {
  ArrowLeft,
  ArrowRight,
  CalendarBlank,
  CheckCircle,
  CircleNotch,
  Clock,
  Gauge,
  PencilSimple,
  Plus,
  Sparkle,
  Timer,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Project, ProjectTask, TaskStatus } from "../types";

const DAY = 86_400_000;

const taskStatusLabel: Record<TaskStatus, string> = {
  todo: "待开始",
  in_progress: "进行中",
  done: "已完成",
};

type TaskUrgency = "high" | "medium" | "normal";

type TaskViewModel = ProjectTask & {
  completion: number;
  overdueDays: number;
  remainingDays: number;
  urgency: TaskUrgency;
};

interface ImmersiveTaskFlowProps {
  project: Project;
  tasks: ProjectTask[];
  onCreateTask: () => void;
  onEditTask: (taskId: string) => void;
  onAdvanceTask: (taskId: string) => void;
}

function startOfToday() {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

function dateValue(value: string) {
  return new Date(`${value}T00:00:00`).getTime();
}

function formatShortDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(`${value}T00:00:00`));
}

function formatTimelineDate(value: number) {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date(value));
}

function deriveTask(task: ProjectTask, today: number): TaskViewModel {
  const dueAt = dateValue(task.dueDate);
  const remainingDays = Math.ceil((dueAt - today) / DAY);
  const overdueDays = task.status !== "done" && dueAt < today ? Math.max(1, Math.ceil((today - dueAt) / DAY)) : 0;
  const urgency: TaskUrgency = overdueDays > 0 || remainingDays <= 3
    ? "high"
    : remainingDays <= 7
      ? "medium"
      : "normal";
  const effortCompletion = Math.round(task.actualHours / Math.max(task.estimatedHours, 1) * 100);
  const completion = task.status === "done"
    ? 100
    : task.status === "todo"
      ? 0
      : Math.min(95, Math.max(20, effortCompletion));

  return { ...task, completion, overdueDays, remainingDays, urgency };
}

function preferredTaskId(tasks: TaskViewModel[]) {
  return tasks.find((task) => task.overdueDays > 0)?.id
    || tasks.find((task) => task.status === "in_progress")?.id
    || tasks.find((task) => task.status === "todo")?.id
    || tasks[0]?.id
    || "";
}

function taskRisk(task: TaskViewModel) {
  if (task.overdueDays > 0) {
    return {
      tone: "danger",
      title: `已经逾期 ${task.overdueDays} 天`,
      detail: "交付风险已升高，建议先确认剩余范围并同步客户新的完成时间。",
    } as const;
  }
  if (task.actualHours > task.estimatedHours) {
    const extra = Math.round((task.actualHours / Math.max(task.estimatedHours, 1) - 1) * 100);
    return {
      tone: "danger",
      title: `工时超出估算 ${extra}%`,
      detail: "继续投入会压缩项目利润，建议拆分新增工作并进入下一期报价。",
    } as const;
  }
  if (task.status !== "done" && task.remainingDays <= 3) {
    return {
      tone: "warning",
      title: task.remainingDays < 0 ? "任务已超过计划日期" : `距离截止仅 ${Math.max(0, task.remainingDays)} 天`,
      detail: "建议冻结非必要需求，把验收标准和交付清单一次确认完整。",
    } as const;
  }
  return {
    tone: "stable",
    title: "当前排期可控",
    detail: "任务进度与计划工时暂未出现明显偏差，可按当前节奏继续推进。",
  } as const;
}

function taskAdvice(task: TaskViewModel) {
  if (task.status === "done") return "归档交付物并补充开发日志，把本次做法沉淀为下一次可复用的检查清单。";
  if (task.overdueDays > 0) return "先完成最小可验收范围，再向客户发送明确的剩余项、责任边界和更新时间。";
  if (task.actualHours >= task.estimatedHours * .8) return "预计工时已接近上限，优先完成验收必需项，暂缓接受新的范围变更。";
  if (task.status === "todo" && task.remainingDays <= 3) return "今天启动该任务，并在开始前确认依赖资料是否齐全，避免等待造成进一步延期。";
  if (task.status === "todo") return "在开始前拆出一个两小时内可完成的首个动作，降低任务启动阻力。";
  return "保持当前推进节奏，完成后立即更新实际工时和交付证据，方便项目复盘。";
}

function statusCount(tasks: TaskViewModel[], status: TaskStatus) {
  return tasks.filter((task) => task.status === status).length;
}

export function ImmersiveTaskFlow({ project, tasks, onCreateTask, onEditTask, onAdvanceTask }: ImmersiveTaskFlowProps) {
  const today = startOfToday();
  const viewTasks = useMemo(() => tasks.map((task) => deriveTask(task, today)), [tasks, today]);
  const [selectedTaskId, setSelectedTaskId] = useState(() => preferredTaskId(viewTasks));
  const dragStartX = useRef<number | null>(null);
  const dragged = useRef(false);
  const wheelAmount = useRef(0);
  const railRef = useRef<HTMLDivElement>(null);
  const orbitRef = useRef<HTMLDivElement>(null);
  const taskCardRefs = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    if (!viewTasks.some((task) => task.id === selectedTaskId)) {
      setSelectedTaskId(preferredTaskId(viewTasks));
    }
  }, [selectedTaskId, viewTasks]);

  const selectedIndex = Math.max(0, viewTasks.findIndex((task) => task.id === selectedTaskId));
  const selectedTask = viewTasks[selectedIndex];
  const risk = selectedTask ? taskRisk(selectedTask) : null;
  const groups = [
    { status: "todo" as const, label: "待开始", count: statusCount(viewTasks, "todo") },
    { status: "in_progress" as const, label: "进行中", count: statusCount(viewTasks, "in_progress") },
    { status: "done" as const, label: "已完成", count: statusCount(viewTasks, "done") },
  ];
  const overdueCount = viewTasks.filter((task) => task.overdueDays > 0).length;

  useEffect(() => {
    if (!window.matchMedia("(max-width: 820px)").matches) return;
    const orbit = orbitRef.current;
    const selectedCard = taskCardRefs.current.get(selectedTaskId);
    if (!orbit || !selectedCard) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const centeredLeft = selectedCard.offsetLeft - (orbit.clientWidth - selectedCard.offsetWidth) / 2;
    orbit.scrollTo({ left: Math.max(0, centeredLeft), behavior: reducedMotion ? "auto" : "smooth" });
  }, [selectedTaskId]);

  const timelineStart = Math.min(dateValue(project.startDate), ...viewTasks.map((task) => dateValue(task.startDate)));
  const timelineEnd = Math.max(dateValue(project.dueDate), ...viewTasks.map((task) => dateValue(task.dueDate)));
  const timelineDuration = Math.max(DAY, timelineEnd - timelineStart + DAY);
  const timelineTicks = Array.from({ length: 7 }, (_, index) => timelineStart + timelineDuration * index / 6);

  const selectRelative = (direction: -1 | 1) => {
    const nextIndex = Math.min(viewTasks.length - 1, Math.max(0, selectedIndex + direction));
    if (viewTasks[nextIndex]) setSelectedTaskId(viewTasks[nextIndex].id);
  };

  const onRailKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!viewTasks.length) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      selectRelative(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      selectRelative(1);
    } else if (event.key === "Home") {
      event.preventDefault();
      setSelectedTaskId(viewTasks[0].id);
    } else if (event.key === "End") {
      event.preventDefault();
      setSelectedTaskId(viewTasks[viewTasks.length - 1].id);
    }
  };

  const startPointerDrag = (event: PointerEvent<HTMLElement>) => {
    dragStartX.current = event.clientX;
    dragged.current = false;
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const finishPointerDrag = (clientX: number) => {
    if (dragStartX.current === null) return;
    const distance = clientX - dragStartX.current;
    dragStartX.current = null;
    if (Math.abs(distance) >= 42) {
      dragged.current = true;
      selectRelative(distance < 0 ? 1 : -1);
      window.setTimeout(() => { dragged.current = false; }, 0);
    }
  };
  const cancelPointerDrag = () => {
    dragStartX.current = null;
    dragged.current = false;
  };
  const onRailPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest("[data-immersive-action]")) return;
    startPointerDrag(event);
  };
  const onRailPointerUp = (event: PointerEvent<HTMLDivElement>) => finishPointerDrag(event.clientX);
  const onTaskCardPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    startPointerDrag(event);
  };
  const onTaskCardPointerUp = (event: PointerEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    finishPointerDrag(event.clientX);
  };

  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    const handleWheel = (event: globalThis.WheelEvent) => {
      const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
      if (!delta || !viewTasks.length) return;
      const direction: -1 | 1 = delta > 0 ? 1 : -1;
      const canMove = direction > 0 ? selectedIndex < viewTasks.length - 1 : selectedIndex > 0;
      if (!canMove) {
        wheelAmount.current = 0;
        return;
      }
      event.preventDefault();
      wheelAmount.current += delta;
      if (Math.abs(wheelAmount.current) >= 32) {
        selectRelative(direction);
        wheelAmount.current = 0;
      }
    };
    rail.addEventListener("wheel", handleWheel, { passive: false });
    return () => rail.removeEventListener("wheel", handleWheel);
  }, [selectedIndex, viewTasks.length]);

  if (!viewTasks.length) {
    return <section className="immersive-task-flow immersive-empty" aria-label="沉浸式任务流">
      <div className="immersive-empty-orbit" aria-hidden="true"><Gauge size={44} weight="duotone" /></div>
      <span>IMMERSIVE WORKFLOW</span>
      <h2>项目驾驶舱等待第一项任务</h2>
      <p>新增任务后，这里会自动生成任务阶段、空间轨道、风险提示和项目时间线。</p>
      <button className="immersive-primary" onClick={onCreateTask}><Plus size={17} weight="bold" />新增第一项任务</button>
    </section>;
  }

  return <section className="immersive-task-flow" aria-label="沉浸式任务流">
    <header className="immersive-toolbar">
      <span><Sparkle size={17} weight="fill" />IMMERSIVE WORKFLOW</span>
      <div><h2>项目任务驾驶舱</h2><p>用空间化视图聚焦当前任务，所有指标均来自本地项目数据。</p></div>
      <div className="immersive-toolbar-actions"><small><i /> 本地规则驱动</small><button onClick={onCreateTask}><Plus size={14} weight="bold" />新增任务</button></div>
    </header>

    <section className="immersive-metrics" aria-label="任务状态指标">
      <article><i className="metric-todo"><Clock size={19} weight="duotone" /></i><span><small>待开始</small><strong>{statusCount(viewTasks, "todo")}</strong><em>项任务</em></span></article>
      <article><i className="metric-progress"><CircleNotch size={19} weight="duotone" /></i><span><small>进行中</small><strong>{statusCount(viewTasks, "in_progress")}</strong><em>项任务</em></span></article>
      <article><i className="metric-done"><CheckCircle size={19} weight="duotone" /></i><span><small>已完成</small><strong>{statusCount(viewTasks, "done")}</strong><em>项任务</em></span></article>
      <article><i className="metric-overdue"><WarningCircle size={19} weight="duotone" /></i><span><small>已逾期</small><strong>{overdueCount}</strong><em>项任务</em></span></article>
    </section>

    <aside className="immersive-stages" aria-label="任务阶段">
      <header><span>任务阶段</span><small>{viewTasks.length} 项</small></header>
      {groups.map((group) => <section className={`immersive-stage stage-${group.status}`} key={group.status}>
        <h3><span><i />{group.label}</span><em>{group.count}</em></h3>
        <div>{viewTasks.filter((task) => task.status === group.status).map((task) => <button
          className={task.id === selectedTaskId ? "active" : ""}
          key={task.id}
          onClick={() => setSelectedTaskId(task.id)}
          aria-current={task.id === selectedTaskId ? "true" : undefined}
        ><span><b>{task.title}</b><small>{formatShortDate(task.dueDate)} 截止</small></span>{task.overdueDays > 0 ? <em className="task-late">逾期</em> : <em>{task.completion}%</em>}</button>)}</div>
      </section>)}
    </aside>

    <div
      ref={railRef}
      className="immersive-rail"
      tabIndex={0}
      aria-label="空间任务轨道，使用左右方向键切换任务"
      onKeyDown={onRailKeyDown}
      onPointerDown={onRailPointerDown}
      onPointerUp={onRailPointerUp}
      onPointerCancel={cancelPointerDrag}
    >
      <header><span>任务焦点</span><small>点击、滚轮或拖动切换</small></header>
      <div ref={orbitRef} className="immersive-orbit" aria-live="polite">
        {viewTasks.map((task, index) => {
          const distance = index - selectedIndex;
          const depth = Math.abs(distance);
          const hidden = depth > 5;
          const active = distance === 0;
          const direction = Math.sign(distance);
          const style = {
            "--task-x": active ? "0px" : `${direction * (118 + Math.max(0, depth - 1) * 82)}px`,
            "--task-y": active ? "-7px" : `${Math.max(0, depth - 1) * 4}px`,
            "--task-z": active ? "52px" : `${-38 - Math.max(0, depth - 1) * 34}px`,
            "--task-rotate": active ? "0deg" : `${direction * -(8 + Math.max(0, depth - 1) * 3)}deg`,
            "--task-scale": active ? 1.03 : Math.max(.72, .94 - Math.max(0, depth - 1) * .055),
            "--task-opacity": hidden ? 0 : Math.max(.2, 1 - depth * .13),
            "--task-order": 50 - depth,
          } as CSSProperties;
          return <button
            className={`immersive-task-card task-${task.status} ${task.id === selectedTaskId ? "active" : ""}`}
            style={style}
            key={task.id}
            ref={(node) => {
              if (node) taskCardRefs.current.set(task.id, node);
              else taskCardRefs.current.delete(task.id);
            }}
            aria-current={task.id === selectedTaskId ? "true" : undefined}
            aria-label={`${task.title}，${taskStatusLabel[task.status]}，完成度 ${task.completion}%`}
            tabIndex={task.id === selectedTaskId ? 0 : -1}
            data-task-id={task.id}
            data-immersive-action
            onPointerDown={onTaskCardPointerDown}
            onPointerUp={onTaskCardPointerUp}
            onPointerCancel={cancelPointerDrag}
            onClick={() => { if (!dragged.current) setSelectedTaskId(task.id); }}
            data-hidden={hidden ? "true" : undefined}
          >
            <span className="task-card-code">TASK-{String(index + 1).padStart(2, "0")}<em>{taskStatusLabel[task.status]}</em></span>
            <i className="task-card-icon"><Gauge size={24} weight="duotone" /></i>
            <strong>{task.completion}<small>%</small></strong>
            <b>{task.title}</b>
            <span className="task-card-date"><CalendarBlank size={13} />{formatShortDate(task.startDate)} — {formatShortDate(task.dueDate)}</span>
            <span className="task-card-progress"><i style={{ width: `${task.completion}%` }} /></span>
          </button>;
        })}
      </div>
      <nav className="immersive-orbit-controls" aria-label="任务轨道控制">
        <button type="button" data-immersive-action onClick={() => selectRelative(-1)} disabled={selectedIndex === 0} aria-label="上一个任务"><ArrowLeft size={19} /></button>
        <span aria-live="polite">{selectedIndex + 1} / {viewTasks.length}</span>
        <button type="button" data-immersive-action onClick={() => selectRelative(1)} disabled={selectedIndex === viewTasks.length - 1} aria-label="下一个任务"><ArrowRight size={19} /></button>
      </nav>
    </div>

    {selectedTask && risk && <aside className="immersive-inspector" aria-label="当前任务详情">
      <header><span><Sparkle size={16} weight="fill" />智能详情</span><small>规则推导</small></header>
      <div className="inspector-task-heading">
        <span>TASK-{String(selectedIndex + 1).padStart(2, "0")}</span>
        <h3>{selectedTask.title}</h3>
        <em className={`urgency-${selectedTask.urgency}`}>{selectedTask.urgency === "high" ? "高优先级" : selectedTask.urgency === "medium" ? "中优先级" : "常规优先级"}</em>
        <p>{taskStatusLabel[selectedTask.status]} · 完成度 {selectedTask.completion}%</p>
      </div>
      <dl className="inspector-facts">
        <div><dt><CalendarBlank size={15} />计划时间</dt><dd>{formatShortDate(selectedTask.startDate)} — {formatShortDate(selectedTask.dueDate)}</dd></div>
        <div><dt><Timer size={15} />投入工时</dt><dd>{selectedTask.actualHours}h / {selectedTask.estimatedHours}h</dd></div>
        <div><dt><Gauge size={15} />任务状态</dt><dd>{taskStatusLabel[selectedTask.status]}</dd></div>
      </dl>
      <section className={`inspector-risk risk-${risk.tone}`}>
        {risk.tone === "stable" ? <CheckCircle size={18} weight="duotone" /> : <WarningCircle size={18} weight="duotone" />}
        <span><b>{risk.title}</b><p>{risk.detail}</p></span>
      </section>
      <section className="inspector-advice">
        <span><Sparkle size={17} weight="fill" />智能建议</span>
        <p>{taskAdvice(selectedTask)}</p>
        <small>根据日期、状态与工时在本地生成</small>
      </section>
      <div className="inspector-actions">
        <button onClick={() => selectRelative(-1)} disabled={selectedIndex === 0} aria-label="上一个任务"><ArrowLeft size={15} /></button>
        <button className="immersive-edit" onClick={() => onEditTask(selectedTask.id)} aria-label={`编辑任务 ${selectedTask.title}`}><PencilSimple size={15} />编辑任务</button>
        <button className="immersive-primary" onClick={() => onAdvanceTask(selectedTask.id)}>{selectedTask.status === "done" ? "重新开始" : "推进状态"}<ArrowRight size={15} /></button>
        <button onClick={() => selectRelative(1)} disabled={selectedIndex === viewTasks.length - 1} aria-label="下一个任务"><ArrowRight size={15} /></button>
      </div>
    </aside>}

    <section className="immersive-timeline" aria-label="项目任务时间线">
      <header><span><CalendarBlank size={16} />项目时间线</span><small>{formatShortDate(project.startDate)} — {formatShortDate(project.dueDate)}</small></header>
      <div className="timeline-scale"><span>任务</span><div>{timelineTicks.map((tick, index) => <time key={index}>{formatTimelineDate(tick)}</time>)}</div></div>
      <div className="timeline-rows">{viewTasks.map((task) => {
        const left = Math.max(0, (dateValue(task.startDate) - timelineStart) / timelineDuration * 100);
        const width = Math.max(4, (dateValue(task.dueDate) - dateValue(task.startDate) + DAY) / timelineDuration * 100);
        return <button className={task.id === selectedTaskId ? "active" : ""} key={task.id} onClick={() => setSelectedTaskId(task.id)}>
          <b>{task.title}</b>
          <span><i className={`timeline-${task.status}`} style={{ left: `${left}%`, width: `${Math.min(100 - left, width)}%` }}><em>{task.completion}%</em></i></span>
        </button>;
      })}</div>
    </section>
  </section>;
}
