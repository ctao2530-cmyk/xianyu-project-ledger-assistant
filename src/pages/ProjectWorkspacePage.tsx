import {
  ArrowLeft,
  ArrowRight,
  BellRinging,
  Briefcase,
  CalendarBlank,
  CheckCircle,
  Clock,
  Code,
  Coins,
  FolderSimple,
  Gauge,
  ListChecks,
  MagnifyingGlass,
  Plus,
  Sparkle,
  Target,
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
import { daysBetween, daysUntil, getProjectFinancials } from "../data/businessMetrics";
import { projectKindOf } from "../data/projectKinds";
import {
  latestSettlementIssue,
  latestTerminalSettlementIssue,
  settlementIssueLabels,
} from "../data/settlementIssues";
import type { LedgerSnapshot, ProjectKind } from "../types";
import {
  ProjectDetail,
  type ProjectPageRoute,
  type ProjectRouteMode,
} from "./BusinessAssistantPages";

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
});

const shortDate = (value: string) =>
  new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(`${value.slice(0, 10)}T00:00:00`));

const statusLabels = {
  pending: "待开始",
  in_progress: "进行中",
  delivered: "已交付",
  completed: "已完成",
  overdue: "已逾期",
} as const;

type PortfolioStatus = "current" | "pending" | "in_progress" | "finished" | "overdue" | "terminated";
type ProjectFinancial = ReturnType<typeof getProjectFinancials>[number];
type ProjectOrbitEntry =
  | { kind: "project"; id: string; item: ProjectFinancial }
  | { kind: "placeholder"; id: string; slot: number };

const projectOrbitWindowSize = 5;

function projectOrbitGeometry(slotOffset: number) {
  const depth = Math.abs(slotOffset);
  const direction = Math.sign(slotOffset);
  const x = direction === 0
    ? 0
    : direction * (depth <= 1 ? 168 * depth : 168 + (depth - 1) * 97);
  return {
    depth,
    x,
    y: 6 + depth * 8,
    z: -8 - depth * 60,
    rotateY: direction === 0 ? 0 : direction * -Math.min(14, 4 + depth * 6),
    scale: Math.max(.8, .98 - depth * .07),
    opacity: Math.max(.5, 1 - depth * .16),
    order: 78 - Math.round(depth * 5),
  };
}

interface ProjectWorkspacePageProps {
  snapshot: LedgerSnapshot;
  onCreateProject: (kind?: ProjectKind) => void;
  onCreatePaymentPlan: (projectId: string) => void;
  onCreateChangeOrder: (projectId: string) => void;
  onConfirmPayment: (projectId: string, paymentId?: string) => void;
  onRecordSettlementIssue: (projectId: string) => void;
  onSnapshotChange: (snapshot: LedgerSnapshot) => void;
  globalSearch: string;
  projectRoute: ProjectPageRoute | null;
  onProjectRouteChange: (route: ProjectPageRoute | null, mode?: ProjectRouteMode) => void;
}

function categoryMatchesStatus(status: string, filter: PortfolioStatus, terminated: boolean) {
  if (filter === "current") return !terminated;
  if (filter === "terminated") return terminated;
  if (terminated) return false;
  if (filter === "finished") return status === "completed" || status === "delivered";
  return status === filter;
}

function projectRisk(item: ProjectFinancial, remaining: number) {
  const latestIssue = latestSettlementIssue(item.settlementIssues);
  if (latestIssue) {
    return {
      tone: "danger",
      title: `${settlementIssueLabels[latestIssue.type]} · 已记录 ${item.issueCount} 条异常`,
      detail: latestIssue.reason,
    } as const;
  }
  if (item.project.status === "overdue" || remaining < 0) {
    return {
      tone: "danger",
      title: `项目已超期 ${Math.max(1, Math.abs(remaining))} 天`,
      detail: "建议先收敛最小验收范围，并同步更新交付预期。",
    } as const;
  }
  if (item.project.status === "delivered" && item.outstanding > 0) {
    return {
      tone: "warning",
      title: `已交付，仍有 ${money.format(item.outstanding)} 待回款`,
      detail: "交付状态与回款状态相互独立，可直接确认到账。",
    } as const;
  }
  if (remaining <= 3 && item.project.status !== "completed") {
    return {
      tone: "warning",
      title: `距离交付仅 ${Math.max(0, remaining)} 天`,
      detail: "优先完成验收必需项，并确认依赖资料是否齐全。",
    } as const;
  }
  return {
    tone: "stable",
    title: "当前节奏可控",
    detail: "任务、日期和回款暂未出现需要立即处理的异常。",
  } as const;
}

export function ProjectWorkspacePage({
  snapshot,
  onCreateProject,
  onCreatePaymentPlan,
  onCreateChangeOrder,
  onConfirmPayment,
  onRecordSettlementIssue,
  onSnapshotChange,
  globalSearch,
  projectRoute,
  onProjectRouteChange,
}: ProjectWorkspacePageProps) {
  const routedProject = projectRoute
    ? snapshot.projects.find((project) => project.id === projectRoute.projectId)
    : undefined;
  const [projectKind, setProjectKind] = useState<ProjectKind>(() => routedProject ? projectKindOf(routedProject) : "client");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<PortfolioStatus>("current");
  const [sort, setSort] = useState<"due" | "progress" | "amount">("due");
  const [selectedByKind, setSelectedByKind] = useState<Record<ProjectKind, string>>({ personal: "", client: "" });
  const [extractedByKind, setExtractedByKind] = useState<Record<ProjectKind, string>>({ personal: "", client: "" });
  const [orbitWindowStartByKind, setOrbitWindowStartByKind] = useState<Record<ProjectKind, number>>({ personal: 0, client: 0 });
  const sceneRef = useRef<HTMLDivElement>(null);
  const dragStartX = useRef<number | null>(null);
  const dragged = useRef(false);
  const wheelAmount = useRef(0);
  const parallaxFrame = useRef<number | null>(null);
  const financials = useMemo(() => getProjectFinancials(snapshot), [snapshot]);

  useEffect(() => {
    if (routedProject) setProjectKind(projectKindOf(routedProject));
  }, [routedProject]);

  useEffect(() => () => {
    if (parallaxFrame.current !== null) window.cancelAnimationFrame(parallaxFrame.current);
  }, []);

  const categoryFinancials = financials.filter(({ project }) => projectKindOf(project) === projectKind);
  const currentCategoryFinancials = categoryFinancials.filter(
    (item) => !latestTerminalSettlementIssue(item.settlementIssues),
  );
  const terminatedCategoryFinancials = categoryFinancials.filter(
    (item) => Boolean(latestTerminalSettlementIssue(item.settlementIssues)),
  );
  const categoryProjects = currentCategoryFinancials.map(({ project }) => project);
  const query = (globalSearch || search).trim().toLowerCase();
  const visible = categoryFinancials
    .filter((item) => {
      const { project } = item;
      const customer = snapshot.customers.find((item) => item.id === project.customerId);
      const haystack = `${project.name} ${project.type || ""} ${customer?.name || ""} ${project.notes || ""}`.toLowerCase();
      const terminated = Boolean(latestTerminalSettlementIssue(item.settlementIssues));
      return haystack.includes(query) && categoryMatchesStatus(project.status, status, terminated);
    })
    .sort((left, right) => {
      if (sort === "amount") return right.project.totalAmount - left.project.totalAmount;
      if (sort === "progress") return right.project.progress - left.project.progress;
      return left.project.dueDate.localeCompare(right.project.dueDate);
    });
  const categoryTasks = snapshot.tasks.filter((task) => categoryProjects.some((project) => project.id === task.projectId));
  const completedTasks = categoryTasks.filter((task) => task.status === "done").length;
  const taskCompletion = categoryTasks.length ? Math.round(completedTasks / categoryTasks.length * 100) : 0;
  const activeProjects = categoryProjects.filter((project) => project.status === "in_progress");
  const averageProgress = categoryProjects.length
    ? Math.round(categoryProjects.reduce((sum, project) => sum + project.progress, 0) / categoryProjects.length)
    : 0;
  const averageDuration = categoryProjects.length
    ? categoryProjects.reduce((sum, project) => sum + daysBetween(project.startDate, project.dueDate), 0) / categoryProjects.length
    : 0;
  const totalContract = categoryProjects.reduce((sum, project) => sum + project.totalAmount, 0);
  const outstanding = currentCategoryFinancials.reduce((sum, item) => sum + item.outstanding, 0);
  const actualHours = currentCategoryFinancials.reduce((sum, item) => sum + item.actualHours, 0);
  const counts: Record<ProjectKind, number> = {
    personal: financials.filter((item) => projectKindOf(item.project) === "personal" && !latestTerminalSettlementIssue(item.settlementIssues)).length,
    client: financials.filter((item) => projectKindOf(item.project) === "client" && !latestTerminalSettlementIssue(item.settlementIssues)).length,
  };
  const terminatedCounts: Record<ProjectKind, number> = {
    personal: financials.filter((item) => projectKindOf(item.project) === "personal" && Boolean(latestTerminalSettlementIssue(item.settlementIssues))).length,
    client: financials.filter((item) => projectKindOf(item.project) === "client" && Boolean(latestTerminalSettlementIssue(item.settlementIssues))).length,
  };
  const statusOptions: Array<{ key: PortfolioStatus; label: string; icon: typeof Briefcase; count: number }> = [
    { key: "current", label: "当前合作", icon: FolderSimple, count: categoryProjects.length },
    { key: "pending", label: "待开始", icon: Clock, count: categoryProjects.filter((project) => project.status === "pending").length },
    { key: "in_progress", label: "进行中", icon: ListChecks, count: activeProjects.length },
    { key: "finished", label: "已完成", icon: CheckCircle, count: categoryProjects.filter((project) => project.status === "completed" || project.status === "delivered").length },
    { key: "overdue", label: "需关注", icon: WarningCircle, count: categoryProjects.filter((project) => project.status === "overdue").length },
    { key: "terminated", label: "已终止", icon: WarningCircle, count: terminatedCategoryFinancials.length },
  ];

  const rememberedSelection = selectedByKind[projectKind];
  const selectedProjectId = visible.some(({ project }) => project.id === rememberedSelection)
    ? rememberedSelection
    : visible[0]?.project.id || "";
  const selectedIndex = Math.max(0, visible.findIndex(({ project }) => project.id === selectedProjectId));
  const showProjectPlaceholders = status === "current" && !query;
  const placeholderCount = showProjectPlaceholders ? Math.max(0, 3 - visible.length) : 0;
  const projectOrbitEntries: ProjectOrbitEntry[] = visible.map((item) => ({
    kind: "project",
    id: item.project.id,
    item,
  }));
  const placeholderOrbitEntries: ProjectOrbitEntry[] = Array.from(
    { length: placeholderCount },
    (_, slot) => ({ kind: "placeholder", id: `project-placeholder-${projectKind}-${slot}`, slot }),
  );
  const orbitEntries: ProjectOrbitEntry[] = (() => {
    if (!placeholderCount) return projectOrbitEntries;
    if (!projectOrbitEntries.length) return placeholderOrbitEntries;
    if (projectOrbitEntries.length === 1) {
      return [placeholderOrbitEntries[0], projectOrbitEntries[0], placeholderOrbitEntries[1]];
    }
    if (projectOrbitEntries.length === 2) {
      return [placeholderOrbitEntries[0], ...projectOrbitEntries];
    }
    return [...projectOrbitEntries, ...placeholderOrbitEntries];
  })();
  const orbitWindowCount = Math.min(projectOrbitWindowSize, orbitEntries.length);
  const maxOrbitWindowStart = Math.max(0, orbitEntries.length - orbitWindowCount);
  const orbitWindowStart = Math.min(orbitWindowStartByKind[projectKind], maxOrbitWindowStart);
  const orbitWindowEnd = orbitWindowStart + orbitWindowCount;
  const orbitWindowCenter = orbitWindowStart + Math.max(0, orbitWindowCount - 1) / 2;
  const extractedProjectId = visible.some(({ project }) => project.id === extractedByKind[projectKind])
    ? extractedByKind[projectKind]
    : "";
  const extractedOrbitIndex = extractedProjectId
    ? orbitEntries.findIndex((entry) => entry.kind === "project" && entry.item.project.id === extractedProjectId)
    : -1;
  const extractedGeometry = extractedOrbitIndex >= orbitWindowStart && extractedOrbitIndex < orbitWindowEnd
    ? projectOrbitGeometry(extractedOrbitIndex - orbitWindowCenter)
    : null;
  const selectedFinancial = visible[selectedIndex];
  const selectedProject = selectedFinancial?.project;
  const selectedCustomer = selectedProject
    ? snapshot.customers.find((customer) => customer.id === selectedProject.customerId)
    : undefined;
  const selectedTasks = selectedProject
    ? snapshot.tasks.filter((task) => task.projectId === selectedProject.id)
    : [];
  const selectedDoneTasks = selectedTasks.filter((task) => task.status === "done").length;
  const selectedRemaining = selectedProject ? daysUntil(selectedProject.dueDate) : 0;
  const selectedRisk = selectedFinancial ? projectRisk(selectedFinancial, selectedRemaining) : null;
  const selectedTerminalIssue = selectedFinancial
    ? latestTerminalSettlementIssue(selectedFinancial.settlementIssues)
    : undefined;
  const visibleProjectIds = visible.map(({ project }) => project.id).join("|");
  const orbitEntryIds = orbitEntries.map((entry) => entry.id).join("|");

  useEffect(() => {
    if (!selectedProjectId || selectedByKind[projectKind] === selectedProjectId) return;
    setSelectedByKind((current) => ({ ...current, [projectKind]: selectedProjectId }));
  }, [projectKind, selectedByKind, selectedProjectId]);

  useEffect(() => {
    if (!extractedByKind[projectKind] || extractedProjectId) return;
    setExtractedByKind((current) => ({ ...current, [projectKind]: "" }));
  }, [extractedByKind, extractedProjectId, projectKind, visibleProjectIds]);

  useEffect(() => {
    const selectedOrbitIndex = orbitEntries.findIndex(
      (entry) => entry.kind === "project" && entry.item.project.id === selectedProjectId,
    );
    if (selectedOrbitIndex < 0) return;
    let nextStart = orbitWindowStart;
    if (selectedOrbitIndex < orbitWindowStart) nextStart = selectedOrbitIndex;
    else if (selectedOrbitIndex >= orbitWindowEnd) nextStart = selectedOrbitIndex - orbitWindowCount + 1;
    nextStart = Math.min(maxOrbitWindowStart, Math.max(0, nextStart));
    if (nextStart === orbitWindowStartByKind[projectKind]) return;
    setOrbitWindowStartByKind((current) => ({ ...current, [projectKind]: nextStart }));
  }, [maxOrbitWindowStart, orbitEntries, orbitEntryIds, orbitWindowCount, orbitWindowEnd, orbitWindowStart, orbitWindowStartByKind, projectKind, selectedProjectId]);

  const selectProject = (projectId: string, mode: "select" | "extract" = "select") => {
    setSelectedByKind((current) => ({ ...current, [projectKind]: projectId }));
    setExtractedByKind((current) => ({ ...current, [projectKind]: mode === "extract" ? projectId : "" }));
  };
  const selectRelative = (direction: -1 | 1) => {
    const nextIndex = Math.min(visible.length - 1, Math.max(0, selectedIndex + direction));
    const nextProject = visible[nextIndex]?.project;
    if (nextProject) selectProject(nextProject.id);
  };
  const openProject = (projectId: string) => onProjectRouteChange({ projectId, tab: "immersive" }, "push");
  const switchKind = (kind: ProjectKind) => {
    setExtractedByKind((current) => ({ ...current, [kind]: "" }));
    setProjectKind(kind);
    setStatus("current");
    setSort("due");
  };
  const resetScenePosition = () => {
    const scene = sceneRef.current;
    if (!scene) return;
    scene.style.setProperty("--scene-shift-x", "0px");
    scene.style.setProperty("--scene-shift-y", "0px");
    scene.style.setProperty("--scene-tilt-x", "0deg");
    scene.style.setProperty("--scene-tilt-y", "0deg");
  };
  const onScenePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType && event.pointerType !== "mouse") return;
    if (window.matchMedia("(max-width: 820px), (pointer: coarse), (prefers-reduced-motion: reduce)").matches) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.max(-1, Math.min(1, (event.clientX - rect.left) / Math.max(rect.width, 1) * 2 - 1));
    const y = Math.max(-1, Math.min(1, (event.clientY - rect.top) / Math.max(rect.height, 1) * 2 - 1));
    if (parallaxFrame.current !== null) window.cancelAnimationFrame(parallaxFrame.current);
    parallaxFrame.current = window.requestAnimationFrame(() => {
      const scene = sceneRef.current;
      if (!scene) return;
      scene.style.setProperty("--scene-shift-x", `${(x * 5).toFixed(2)}px`);
      scene.style.setProperty("--scene-shift-y", `${(y * 4).toFixed(2)}px`);
      scene.style.setProperty("--scene-tilt-x", `${(-y * 1.5).toFixed(2)}deg`);
      scene.style.setProperty("--scene-tilt-y", `${(x * 1.5).toFixed(2)}deg`);
    });
  };
  const onScenePointerLeave = () => {
    resetScenePosition();
  };
  const onSceneKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!visible.length) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      selectRelative(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      selectRelative(1);
    } else if (event.key === "Home") {
      event.preventDefault();
      selectProject(visible[0].project.id);
    } else if (event.key === "End") {
      event.preventDefault();
      selectProject(visible[visible.length - 1].project.id);
    }
  };
  const onScenePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest("[data-project-action]")) return;
    dragStartX.current = event.clientX;
    dragged.current = false;
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onScenePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (dragStartX.current === null) return;
    const distance = event.clientX - dragStartX.current;
    dragStartX.current = null;
    if (Math.abs(distance) >= 44) {
      dragged.current = true;
      selectRelative(distance < 0 ? 1 : -1);
      window.setTimeout(() => { dragged.current = false; }, 0);
    }
  };

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    const handleWheel = (event: globalThis.WheelEvent) => {
      const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
      if (!delta || !visible.length) return;
      const direction: -1 | 1 = delta > 0 ? 1 : -1;
      const canMove = direction > 0 ? selectedIndex < visible.length - 1 : selectedIndex > 0;
      if (!canMove) {
        wheelAmount.current = 0;
        return;
      }
      event.preventDefault();
      wheelAmount.current += delta;
      if (Math.abs(wheelAmount.current) >= 36) {
        selectRelative(direction);
        wheelAmount.current = 0;
      }
    };
    scene.addEventListener("wheel", handleWheel, { passive: false });
    return () => scene.removeEventListener("wheel", handleWheel);
  }, [projectKind, selectedIndex, visibleProjectIds]);

  if (routedProject && projectRoute) {
    return <ProjectDetail
      snapshot={snapshot}
      projectId={routedProject.id}
      tab={projectRoute.tab}
      onBack={() => onProjectRouteChange(null, "back")}
      onTabChange={(tab) => onProjectRouteChange({ projectId: routedProject.id, tab }, "replace")}
      onCreatePaymentPlan={onCreatePaymentPlan}
      onCreateChangeOrder={onCreateChangeOrder}
      onConfirmPayment={onConfirmPayment}
      onRecordSettlementIssue={onRecordSettlementIssue}
      onSnapshotChange={onSnapshotChange}
    />;
  }

  return <div className="business-page enhanced-project-page">
    <section className="project-workspace-shell portfolio-workspace project-cockpit-workspace">
      <header className="project-workspace-header">
        <div className="project-workspace-heading"><span>PROJECT COCKPIT</span><h2>项目驾驶舱</h2><p>聚焦当前项目，在同一个空间里掌握任务、交付与回款。</p></div>
        <div className="project-kind-switch" role="group" aria-label="项目分类">
          <button type="button" className={projectKind === "personal" ? "active" : ""} aria-pressed={projectKind === "personal"} onClick={() => switchKind("personal")}><Code size={19} weight="duotone" /><span><b>个人项目</b><small>{counts.personal} 个当前{terminatedCounts.personal ? ` · ${terminatedCounts.personal} 已终止` : ""}</small></span></button>
          <button type="button" className={projectKind === "client" ? "active" : ""} aria-pressed={projectKind === "client"} onClick={() => switchKind("client")}><Briefcase size={19} weight="duotone" /><span><b>接单项目</b><small>{counts.client} 个当前{terminatedCounts.client ? ` · ${terminatedCounts.client} 已终止` : ""}</small></span></button>
        </div>
        <button className="business-primary project-create-button" onClick={() => onCreateProject(projectKind)}><Plus size={16} />新建{projectKind === "personal" ? "个人" : "接单"}项目</button>
      </header>

      <section className="project-workspace-metrics project-cockpit-metrics" aria-label={`${projectKind === "personal" ? "个人" : "接单"}项目指标`}>
        <article className="project-workspace-metric workspace-purple"><i>{projectKind === "personal" ? <Code size={20} weight="duotone" /> : <Briefcase size={20} weight="duotone" />}</i><span><small>当前{projectKind === "personal" ? "项目" : "合作"}</small><strong>{categoryProjects.length} 个</strong><em>{terminatedCategoryFinancials.length ? `${terminatedCategoryFinancials.length} 个已终止单独归档` : `平均进度 ${averageProgress}%`}</em></span></article>
        <article className="project-workspace-metric workspace-blue"><i><ListChecks size={20} weight="duotone" /></i><span><small>进行中</small><strong>{activeProjects.length} 个</strong><em>{categoryTasks.length} 项任务在计划内</em></span></article>
        {projectKind === "personal" ? <>
          <article className="project-workspace-metric workspace-green"><i><Target size={20} weight="duotone" /></i><span><small>任务完成</small><strong>{taskCompletion}%</strong><em>{completedTasks}/{categoryTasks.length} 项已完成</em></span></article>
          <article className="project-workspace-metric workspace-orange"><i><Timer size={20} weight="duotone" /></i><span><small>累计投入</small><strong>{actualHours}h</strong><em>平均工期 {averageDuration.toFixed(1)} 天</em></span></article>
        </> : <>
          <article className="project-workspace-metric workspace-green"><i><Coins size={20} weight="duotone" /></i><span><small>合同总额</small><strong>{money.format(totalContract)}</strong><em>任务完成 {taskCompletion}%</em></span></article>
          <article className="project-workspace-metric workspace-orange"><i><BellRinging size={20} weight="duotone" /></i><span><small>待回款</small><strong>{money.format(outstanding)}</strong><em>平均工期 {averageDuration.toFixed(1)} 天</em></span></article>
        </>}
      </section>

      <section className="project-cockpit-layout">
        <aside className="portfolio-stages project-cockpit-stages" aria-label="项目状态筛选">
          <header><span>项目阶段</span><small>{categoryProjects.length} 个当前</small></header>
          <div>{statusOptions.map(({ key, label, icon: Icon, count }) => <button type="button" key={key} className={status === key ? "active" : ""} aria-pressed={status === key} onClick={() => setStatus(key)}><i><Icon size={17} weight="duotone" /></i><span><b>{label}</b><small>{key === "current" ? "不含异常终止项目" : key === "terminated" ? "查看终止合作历史" : `筛选${label}项目`}</small></span><em>{count}</em></button>)}</div>
          <section className="portfolio-progress-summary"><span><Gauge size={18} weight="duotone" />组合完成度</span><strong>{averageProgress}%</strong><div><i style={{ width: `${averageProgress}%` }} /></div><small>根据当前分类全部项目计算</small></section>
        </aside>

        <section className="project-cockpit-stage">
          <header className="project-cockpit-tools">
            <label><MagnifyingGlass size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={globalSearch ? `顶部搜索：${globalSearch}` : "搜索项目、客户或备注"} disabled={Boolean(globalSearch)} /></label>
            <select aria-label="项目排序" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}><option value="due">按时间排序</option><option value="progress">按进度排序</option>{projectKind === "client" && <option value="amount">按合同金额排序</option>}</select>
          </header>

          {orbitEntries.length ? <div
            className="project-orbit-scene"
            ref={sceneRef}
            style={{ "--scene-active-x": `${extractedGeometry?.x || 0}px` } as CSSProperties}
            tabIndex={0}
            aria-label="项目空间卡组，点击真实项目从原卡位抽出，空卡位可新建项目"
            onKeyDown={onSceneKeyDown}
            onPointerMove={onScenePointerMove}
            onPointerLeave={onScenePointerLeave}
            onPointerDown={onScenePointerDown}
            onPointerUp={onScenePointerUp}
            onPointerCancel={() => { dragStartX.current = null; resetScenePosition(); }}
            data-extracted={extractedProjectId ? "true" : undefined}
          >
            <div className="project-scene-light" aria-hidden="true" />
            <header className="project-orbit-label"><span><Sparkle size={14} weight="fill" />PROJECT ORBIT</span><small>{placeholderCount ? `${visible.length} 个真实项目 · ${placeholderCount} 个待启用卡位 · 点击项目原位抽出` : "点击项目原位抽出 · 拖动、滚轮或键盘选择"}</small></header>
            <div className="project-orbit-deck" key={projectKind} data-project-kind={projectKind} aria-live="polite">
              {extractedGeometry && <span
                className="project-extraction-shadow"
                style={{ "--project-shadow-x": `${extractedGeometry.x}px` } as CSSProperties}
                aria-hidden="true"
              />}
              {orbitEntries.map((entry, index) => {
                const slotOffset = index - orbitWindowCenter;
                const geometry = projectOrbitGeometry(slotOffset);
                const hidden = index < orbitWindowStart || index >= orbitWindowEnd;
                const extracted = entry.kind === "project" && entry.item.project.id === extractedProjectId;
                const dimmedByExtraction = Boolean(extractedProjectId) && !extracted;
                const style = {
                  "--project-x": `${geometry.x}px`,
                  "--project-y": `${extracted ? geometry.y - 22 : geometry.y}px`,
                  "--project-z": `${extracted ? geometry.z + 150 : geometry.z}px`,
                  "--project-rotate-y": `${extracted ? geometry.rotateY * .28 : geometry.rotateY}deg`,
                  "--project-scale": extracted ? 1.045 : geometry.scale,
                  "--project-opacity": hidden ? 0 : extracted ? 1 : dimmedByExtraction ? Math.max(.38, geometry.opacity * .7) : geometry.opacity,
                  "--project-order": extracted ? 108 : geometry.order,
                } as CSSProperties;
                if (entry.kind === "placeholder") {
                  return <button
                    type="button"
                    className="project-glass-card project-placeholder-card"
                    style={style}
                    key={entry.id}
                    data-orbit-id={entry.id}
                    data-project-action
                    data-slot-offset={slotOffset.toFixed(2)}
                    data-hidden={hidden ? "true" : undefined}
                    tabIndex={hidden ? -1 : 0}
                    aria-label={`新建${projectKind === "personal" ? "个人" : "接单"}项目，空项目卡位 ${entry.slot + 1}`}
                    onClick={() => {
                      if (dragged.current) return;
                      setExtractedByKind((current) => ({ ...current, [projectKind]: "" }));
                      onCreateProject(projectKind);
                    }}
                  >
                    <span className="project-placeholder-icon"><Plus size={24} weight="light" /></span>
                    <span className="project-placeholder-copy">
                      <small>{projectKind === "personal" ? "PERSONAL PROJECT" : "CLIENT PROJECT"} · EMPTY SLOT</small>
                      <strong>等待新项目</strong>
                      <span>创建后自动占用这个卡位，不计入当前经营数据。</span>
                    </span>
                    <span className="project-placeholder-action">点击新建 <ArrowRight size={14} /></span>
                  </button>;
                }
                const { item } = entry;
                const { project, income, outstanding: due, profit, paymentProgress } = item;
                const locked = project.id === selectedProjectId;
                const projectTasks = snapshot.tasks.filter((task) => task.projectId === project.id);
                const doneTasks = projectTasks.filter((task) => task.status === "done").length;
                const customer = snapshot.customers.find((item) => item.id === project.customerId);
                const isPersonal = projectKindOf(project) === "personal";
                const terminalIssue = latestTerminalSettlementIssue(item.settlementIssues);
                const statusLabel = terminalIssue ? "已终止" : statusLabels[project.status];
                const remaining = daysUntil(project.dueDate);
                return <article
                  className={`project-glass-card project-card-${project.accent} ${locked ? "locked" : ""} ${extracted ? "extracted" : ""}`}
                  style={style}
                  key={project.id}
                  data-orbit-id={entry.id}
                  data-project-id={project.id}
                  data-slot-offset={slotOffset.toFixed(2)}
                  data-extracted={extracted ? "true" : undefined}
                  data-hidden={hidden ? "true" : undefined}
                  onClick={(event) => {
                    if (!dragged.current && !(event.target as HTMLElement).closest("[data-project-action]")) selectProject(project.id, "extract");
                  }}
                >
                  <button
                    type="button"
                    className="project-glass-select"
                    aria-pressed={extracted}
                    aria-current={locked ? "true" : undefined}
                    aria-label={`${extracted ? "已抽出" : "选择并抽出"}${project.name}，${statusLabel}，进度 ${project.progress}%`}
                    tabIndex={hidden ? -1 : 0}
                  >
                    <span className="project-glass-head"><i>{isPersonal ? <Code size={20} weight="duotone" /> : <Briefcase size={20} weight="duotone" />}</i><span><small>{project.type || (isPersonal ? "个人开发" : "定制开发")}{!isPersonal && customer ? ` · ${customer.name}` : ""}</small><b>{project.name}</b></span><em className={`portfolio-status ${terminalIssue ? "status-terminated" : `status-${project.status}`}`}>{statusLabel}</em></span>
                    <p>{project.notes || (isPersonal ? "聚焦一个可持续推进的个人里程碑。" : "围绕客户目标推进需求、交付与回款。")}</p>
                    <span className="project-glass-progress"><span><small>项目进度</small><b>{project.progress}%</b></span><i><em style={{ width: `${project.progress}%` }} /></i></span>
                    <span className="project-glass-stats">
                      <span><small>任务</small><b>{doneTasks}/{projectTasks.length}</b></span>
                      <span><small>{isPersonal ? "里程碑" : "交付日"}</small><b>{shortDate(project.dueDate)}</b></span>
                      <span><small>{isPersonal ? "投入工时" : "已收 / 未收"}</small><b>{isPersonal ? `${projectTasks.reduce((sum, task) => sum + task.actualHours, 0)}h` : `${money.format(income)} / ${money.format(due)}`}</b></span>
                    </span>
                    <span className="project-glass-foot"><small>{terminalIssue ? `${settlementIssueLabels[terminalIssue.type]} · 已移出当前合作` : item.issueCount ? `异常 ${item.issueCount} 条 · ${settlementIssueLabels[latestSettlementIssue(item.settlementIssues)!.type]}` : remaining < 0 ? `已超期 ${Math.abs(remaining)} 天` : project.status === "delivered" && due > 0 ? `已交付 · 待回款 ${money.format(due)}` : `剩余 ${remaining} 天`}</small>{!isPersonal && <b>利润 {money.format(profit)} · 净回款 {paymentProgress.toFixed(0)}%</b>}</span>
                  </button>
                  <div className="project-glass-actions" aria-hidden={!extracted}>
                    <button type="button" data-project-action tabIndex={extracted ? 0 : -1} onClick={() => openProject(project.id)}>进入项目 <ArrowRight size={14} /></button>
                    {!isPersonal && !terminalIssue && due > 0 && <button type="button" data-project-action tabIndex={extracted ? 0 : -1} className={project.status === "delivered" ? "is-urgent" : ""} onClick={() => onConfirmPayment(project.id)}><Coins size={14} weight="duotone" />确认到账</button>}
                    {!isPersonal && <button type="button" data-project-action tabIndex={extracted ? 0 : -1} className="is-exception" onClick={() => onRecordSettlementIssue(project.id)}><WarningCircle size={14} weight="duotone" />记录异常</button>}
                  </div>
                </article>;
              })}
            </div>
            <nav className="project-orbit-controls" aria-label="项目轨道控制">
              <button type="button" onClick={() => selectRelative(-1)} disabled={!visible.length || selectedIndex === 0} aria-label="上一个项目"><ArrowLeft size={16} /></button>
              <span>{visible.length ? `${selectedIndex + 1} / ${visible.length} 个项目` : "0 个项目"}{placeholderCount ? ` · ${placeholderCount} 个空位` : ""}</span>
              <button type="button" onClick={() => selectRelative(1)} disabled={!visible.length || selectedIndex === visible.length - 1} aria-label="下一个项目"><ArrowRight size={16} /></button>
            </nav>
          </div> : <div className="portfolio-empty project-cockpit-empty"><i>{projectKind === "personal" ? <Code size={35} weight="duotone" /> : <Briefcase size={35} weight="duotone" />}</i><h3>{query || status !== "current" ? "没有匹配的项目" : `还没有${projectKind === "personal" ? "当前个人" : "当前合作"}项目`}</h3><p>{query || status !== "current" ? "重置搜索或阶段筛选后再试。" : projectKind === "personal" ? "创建个人项目，用任务与里程碑管理自己的产品和成长计划。" : "异常终止项目已移入“已终止”，新的合作会显示在这里。"}</p>{query || status !== "current" ? <button className="business-primary" onClick={() => { setSearch(""); setStatus("current"); }}>重置筛选</button> : <button className="business-primary" onClick={() => onCreateProject(projectKind)}><Plus size={16} />新建项目</button>}</div>}
        </section>

        {selectedProject && selectedFinancial && selectedRisk && <aside className="project-cockpit-inspector" key={selectedProject.id} aria-label={selectedTerminalIssue ? "已终止项目详情" : "当前项目详情"}>
          <header><span><Sparkle size={16} weight="fill" />{selectedTerminalIssue ? "已终止合作" : "当前项目"}</span><small>{selectedTerminalIssue ? "历史可追溯" : "本地数据"}</small></header>
          <div className="project-inspector-heading"><i className={`project-${selectedProject.accent}`}>{projectKind === "personal" ? <Code size={24} weight="duotone" /> : <Briefcase size={24} weight="duotone" />}</i><span><small>{selectedProject.type || (projectKind === "personal" ? "个人开发" : selectedCustomer?.name || "接单项目")}</small><h3>{selectedProject.name}</h3><em className={`portfolio-status ${selectedTerminalIssue ? "status-terminated" : `status-${selectedProject.status}`}`}>{selectedTerminalIssue ? "已终止" : statusLabels[selectedProject.status]}</em></span></div>
          <dl className="project-inspector-facts">
            <div><dt>项目进度</dt><dd>{selectedProject.progress}%</dd></div>
            <div><dt>任务完成</dt><dd>{selectedDoneTasks}/{selectedTasks.length}</dd></div>
            <div><dt>{projectKind === "personal" ? "里程碑" : "交付日期"}</dt><dd>{shortDate(selectedProject.dueDate)}</dd></div>
            {projectKind === "client" && <><div><dt>合同金额</dt><dd>{money.format(selectedProject.totalAmount)}</dd></div><div><dt>净到账</dt><dd>{money.format(selectedFinancial.income)}</dd></div><div className={selectedFinancial.outstanding > 0 ? "is-outstanding" : ""}><dt>可收余额</dt><dd>{money.format(selectedFinancial.outstanding)}</dd></div>{selectedFinancial.issueCount > 0 && <div className="is-exception"><dt>异常影响</dt><dd>退款 {money.format(selectedFinancial.refundedAmount)} · 核销 {money.format(selectedFinancial.uncollectible)}</dd></div>}</>}
          </dl>
          <section className={`project-inspector-risk risk-${selectedRisk.tone}`}><span>{selectedRisk.tone === "stable" ? <CheckCircle size={18} weight="duotone" /> : <WarningCircle size={18} weight="duotone" />}<b>{selectedRisk.title}</b></span><p>{selectedRisk.detail}</p></section>
          <div className="project-inspector-actions">
            <button className="business-primary" type="button" onClick={() => openProject(selectedProject.id)}>进入项目 <ArrowRight size={15} /></button>
            {projectKind === "client" && !selectedTerminalIssue && selectedFinancial.outstanding > 0 && <button type="button" className={selectedProject.status === "delivered" ? "is-urgent" : ""} onClick={() => onConfirmPayment(selectedProject.id)}><Coins size={15} weight="duotone" />确认到账</button>}
            {projectKind === "client" && <button type="button" className="is-exception" onClick={() => onRecordSettlementIssue(selectedProject.id)}><WarningCircle size={15} weight="duotone" />记录客户或回款异常</button>}
          </div>
        </aside>}

        <section className="project-cockpit-timeline" aria-label="项目时间线">
          <header><span><CalendarBlank size={17} />交付与回款时间线</span><small>点击节点同步聚焦项目</small></header>
          <div>{visible.length ? visible.map((item) => {
            const { project, outstanding: due } = item;
            const terminalIssue = latestTerminalSettlementIssue(item.settlementIssues);
            return <button type="button" className={project.id === selectedProjectId ? "active" : ""} aria-current={project.id === selectedProjectId ? "true" : undefined} key={project.id} onClick={() => selectProject(project.id)}><span><time>{shortDate(project.dueDate)}</time><b>{project.name}</b><small>{terminalIssue ? "已终止合作" : statusLabels[project.status]}{!terminalIssue && due > 0 && projectKind === "client" ? ` · 待回款 ${money.format(due)}` : ""}</small></span><i><em style={{ width: `${project.progress}%` }} /></i><strong>{project.progress}%</strong></button>;
          }) : <p>当前筛选下没有可显示的项目节点。</p>}</div>
        </section>
      </section>
    </section>
  </div>;
}
