import { compareProjectUpdates } from "../data/projectOrdering";
import {
  ArrowLeft,
  ArrowRight,
  Briefcase,
  CheckCircle,
  Code,
  Coins,
  ListChecks,
  MagnifyingGlass,
  PencilSimple,
  Plus,
  ShieldCheck,
  Storefront,
  Timer,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { daysUntil, getProjectFinancials } from "../data/businessMetrics";
import { readUiSession, writeUiSession } from '../data/uiSession';
import { localPlatformService, type ProductView } from "../data/localPlatformService";
import { mockLedgerService } from "../data/mockService";
import { projectKindOf } from "../data/projectKinds";
import { latestTerminalSettlementIssue } from "../data/settlementIssues";
import type { CustomerRelationPreview, LedgerSnapshot, Project, ProjectKind, ProjectProductPreview } from "../types";
import { ProjectDetail, type ProjectPageRoute, type ProjectRouteMode } from "./BusinessAssistantPages";
import { ProjectListContext } from '../components/workspace/ProjectListContext';

const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 });
const shortDate = (value: string) => new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(`${value.slice(0, 10)}T00:00:00`));

const statusLabels: Record<Project["status"], string> = {
  pending: "待开始",
  in_progress: "进行中",
  delivered: "已交付",
  completed: "已完成",
  overdue: "已逾期",
};

type ListStatus = "all" | "in_progress" | "attention" | "finished" | "terminated";
type RelationDialog = { kind: "customer" | "product"; projectId: string } | null;

interface ProjectWorkspacePageProps {
  snapshot: LedgerSnapshot;
  onCreateProject: (kind?: ProjectKind) => void;
  onCreatePaymentPlan: (projectId: string) => void;
  onCreateChangeOrder: (projectId: string) => void;
  onConfirmPayment: (projectId: string, paymentId?: string) => void;
  onRecordSettlementIssue: (projectId: string) => void;
  onSnapshotChange: (snapshot: LedgerSnapshot) => void;
  onPersistedSnapshot: (snapshot: LedgerSnapshot) => void;
  onNavigate: (page: string) => void;
  globalSearch: string;
  projectRoute: ProjectPageRoute | null;
  onProjectRouteChange: (route: ProjectPageRoute | null, mode?: ProjectRouteMode) => void;
}

function ProjectMetric({ icon, label, value, detail, tone }: { icon: ReactNode; label: string; value: string; detail: string; tone: "purple" | "blue" | "green" | "orange" }) {
  return <article className={`project-hub-metric is-${tone}`}><i>{icon}</i><span><small>{label}</small><strong>{value}</strong><em>{detail}</em></span></article>;
}

function ProjectEditView({ project, snapshot, productTitle, onBack, onSave, onChangeRelation }: {
  project: Project;
  snapshot: LedgerSnapshot;
  productTitle: string;
  onBack: () => void;
  onSave: (project: Project) => void;
  onChangeRelation: (kind: "customer" | "product") => void;
}) {
  const [draft, setDraft] = useState(() => ({ name: project.name, type: project.type || "", status: project.status, startDate: project.startDate, dueDate: project.dueDate, estimatedHours: String(project.estimatedHours || 0), notes: project.notes || "" }));
  const [error, setError] = useState("");
  const customer = snapshot.customers.find((item) => item.id === project.customerId);
  const isPersonal = projectKindOf(project) === "personal";
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft.name.trim()) return setError("请填写项目名称");
    if (draft.dueDate < draft.startDate) return setError("交付日期不能早于开始日期");
    setError("");
    onSave({ ...project, name: draft.name.trim(), type: draft.type.trim(), status: draft.status, startDate: draft.startDate, dueDate: draft.dueDate, estimatedHours: Math.max(0, Number(draft.estimatedHours) || 0), notes: draft.notes.trim() });
  };
  return <div className="business-page project-edit-page"><form className="project-edit-shell" onSubmit={submit}>
    <header className="project-edit-head"><button type="button" className="business-back" onClick={onBack}><ArrowLeft size={17} />返回项目详情</button><div><small>PROJECT EDIT</small><h2>编辑项目</h2><p>普通保存不会直接修改客户与商品关系。</p></div><button type="submit" className="business-primary">保存修改</button></header>
    <section className="project-edit-section"><header><span>01</span><div><h3>基本信息</h3><p>调整项目自身的名称、类型和交付状态。</p></div></header><div className="project-edit-fields">
      <label className="is-wide"><span>项目名称</span><input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>
      <label><span>项目类型</span><input value={draft.type} onChange={(event) => setDraft((current) => ({ ...current, type: event.target.value }))} /></label>
      <label><span>状态</span><select value={draft.status} onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value as Project["status"] }))}>{Object.entries(statusLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label><span>开始日期</span><input type="date" value={draft.startDate} onChange={(event) => setDraft((current) => ({ ...current, startDate: event.target.value }))} /></label>
      <label><span>{isPersonal ? "里程碑日期" : "交付日期"}</span><input type="date" value={draft.dueDate} onChange={(event) => setDraft((current) => ({ ...current, dueDate: event.target.value }))} /></label>
      <label><span>预计工时</span><input type="number" min="0" step="0.5" value={draft.estimatedHours} onChange={(event) => setDraft((current) => ({ ...current, estimatedHours: event.target.value }))} /></label>
      <label className="is-wide"><span>项目说明</span><textarea rows={4} value={draft.notes} onChange={(event) => setDraft((current) => ({ ...current, notes: event.target.value }))} /></label>
    </div></section>
    {!isPersonal && <section className="project-edit-section"><header><span>02</span><div><h3>关系设置</h3><p>关系变更会先展示影响范围，再由你单独确认。</p></div></header><div className="project-edit-relations">
      <article><i><span>{customer?.name.slice(0, 1) || "客"}</span></i><div><small>客户关系</small><strong>{customer?.name || "未关联客户"}</strong><p>变更会同步项目、付款、追加订单与异常归属。</p></div><button type="button" onClick={() => onChangeRelation("customer")}>变更 <ArrowRight size={14} /></button></article>
      <article><i><Storefront size={21} weight="duotone" /></i><div><small>来源商品</small><strong>{productTitle}</strong><p>保留原利润历史，按预览结果更新实时归属。</p></div><button type="button" onClick={() => onChangeRelation("product")}>变更 <ArrowRight size={14} /></button></article>
    </div></section>}
    <section className="project-edit-safety"><ShieldCheck size={19} weight="fill" /><span><b>版本保护</b><small>基础资料使用账本 revision 保存；关系修正额外使用 preview token 与 request-id，避免重复和并发覆盖。</small></span></section>
    {error && <p className="project-edit-error" role="alert">{error}</p>}<footer><button type="button" onClick={onBack}>取消</button><button type="submit" className="business-primary">保存修改</button></footer>
  </form></div>;
}

export function ProjectWorkspacePage({ snapshot, onCreateProject, onCreatePaymentPlan, onCreateChangeOrder, onConfirmPayment, onRecordSettlementIssue, onSnapshotChange, onPersistedSnapshot, globalSearch, projectRoute, onProjectRouteChange }: ProjectWorkspacePageProps) {
  const routedProject = projectRoute ? snapshot.projects.find((project) => project.id === projectRoute.projectId) : undefined;
  const [projectKind, setProjectKind] = useState<ProjectKind>(() => routedProject ? projectKindOf(routedProject) : readUiSession('projects-kind')==='personal'?'personal':'client');
  const [search, setSearch] = useState(()=>readUiSession('projects-search'));
  const [customerFilter, setCustomerFilter] = useState(()=>readUiSession('projects-customer'));
  useEffect(()=>writeUiSession('projects-customer',customerFilter),[customerFilter]);
  const [page, setPage] = useState(()=>Math.max(1,Number(readUiSession('projects-page'))||1));
  const [pageSize, setPageSize] = useState(()=>readUiSession('projects-page-size')==='20'?20:10);
  useEffect(()=>{writeUiSession('projects-page',String(page));writeUiSession('projects-page-size',String(pageSize));},[page,pageSize]);
  useEffect(()=>writeUiSession('projects-search',search),[search]);
  const [status, setStatus] = useState<ListStatus>(()=>{const value=readUiSession('projects-status');return ['in_progress','attention','finished','terminated'].includes(value)?value as ListStatus:'all';});
  const [sort, setSort] = useState<"due" | "updated" | "amount">(()=>{const value=readUiSession('projects-sort');return value==='updated'||value==='amount'?value:'due';});
  useEffect(()=>{writeUiSession('projects-kind',projectKind);writeUiSession('projects-status',status);writeUiSession('projects-sort',sort);},[projectKind,status,sort]);
  const [products, setProducts] = useState<ProductView[]>([]);
  const [relationDialog, setRelationDialog] = useState<RelationDialog>(null);
  const [relationSearch, setRelationSearch] = useState("");
  const [relationBusy, setRelationBusy] = useState(false);
  const [relationError, setRelationError] = useState("");
  const [productPreview, setProductPreview] = useState<ProjectProductPreview | null>(null);
  const [customerPreview, setCustomerPreview] = useState<CustomerRelationPreview | null>(null);
  const relationCloseRef = useRef<HTMLButtonElement>(null);
  const relationReturnFocusRef = useRef<HTMLElement | null>(null);
  const financials = useMemo(() => getProjectFinancials(snapshot), [snapshot]);

  useEffect(() => { if (routedProject) setProjectKind(projectKindOf(routedProject)); }, [routedProject]);
  useEffect(() => { let active = true; void localPlatformService.productIntelligence().then((value) => { if (active) setProducts(value.products.filter((product) => product.ownership_status === "owned")); }).catch(() => { if (active) setProducts([]); }); return () => { active = false; }; }, []);

  const category = financials.filter(({ project }) => projectKindOf(project) === projectKind);
  const customerOptions = snapshot.customers.filter(customer => category.some(item => item.project.customerId === customer.id));
  const query = (globalSearch || search).trim().toLowerCase();
  const searched = category.filter((item) => {
    if (projectKind === 'client' && customerFilter && item.project.customerId !== customerFilter) return false;
    const customer = snapshot.customers.find((candidate) => candidate.id === item.project.customerId);
    const product = products.find((candidate) => candidate.external_id === item.project.itemExternalId);
    return `${item.project.name} ${item.project.type || ""} ${customer?.name || ""} ${product?.title || ""}`.toLowerCase().includes(query);
  });
  const matchesStatus = (item: (typeof category)[number], selectedStatus: ListStatus) => {
    const terminal = Boolean(latestTerminalSettlementIssue(item.settlementIssues));
    if (selectedStatus === "terminated") return terminal;
    if (terminal) return false;
    if (selectedStatus === "in_progress") return item.project.status === "in_progress";
    if (selectedStatus === "attention") {
      const finished = item.project.status === "completed" || item.project.status === "delivered";
      return !latestTerminalSettlementIssue(item.settlementIssues)
        && !finished
        && (item.project.status === "overdue" || daysUntil(item.project.dueDate) <= 3);
    }
    if (selectedStatus === "finished") return item.project.status === "completed" || item.project.status === "delivered";
    return true;
  };
  const visible = searched.filter(item => matchesStatus(item, status)).sort((left, right) => sort === "amount" ? right.project.totalAmount - left.project.totalAmount : sort === "updated" ? compareProjectUpdates(left.project, right.project) : left.project.dueDate.localeCompare(right.project.dueDate));
  const active = category.filter((item) => !latestTerminalSettlementIssue(item.settlementIssues));
  const pageCount=Math.max(1,Math.ceil(visible.length/pageSize));
  const currentPage=Math.min(page,pageCount);
  const pageRows=visible.slice((currentPage-1)*pageSize,currentPage*pageSize);
  const pageFilterKey=JSON.stringify([search,globalSearch,status,sort,projectKind,pageSize,customerFilter]);
  const previousPageFilter=useRef(pageFilterKey);
  useEffect(()=>{if(previousPageFilter.current!==pageFilterKey){previousPageFilter.current=pageFilterKey;setPage(1);}},[pageFilterKey]);
  useEffect(()=>{if(page>pageCount)setPage(pageCount);},[page,pageCount]);
  const activeProjects = active.filter((item) => item.project.status === "in_progress");
  const totalContract = active.reduce((sum, item) => sum + item.project.totalAmount, 0);
  const outstanding = active.reduce((sum, item) => sum + item.outstanding, 0);
  const projectTasks = snapshot.tasks.filter((task) => active.some((item) => item.project.id === task.projectId));
  const actualHours = projectTasks.reduce((sum, task) => sum + task.actualHours, 0);
  const openProject = (projectId: string) => onProjectRouteChange({ projectId, tab: "overview" }, "push");
  const editProject = (projectId: string) => onProjectRouteChange({ projectId, tab: "edit" }, "push");

  const relationProject = relationDialog ? snapshot.projects.find((item) => item.id === relationDialog.projectId) : undefined;
  const relationCustomer = relationProject ? snapshot.customers.find((item) => item.id === relationProject.customerId) : undefined;
  const currentProduct = relationProject?.itemExternalId ? products.find((item) => item.external_id === relationProject.itemExternalId) : undefined;
  const eligibleProducts = products.filter((product) => product.monitoring_enabled && `${product.title} ${product.external_id}`.toLowerCase().includes(relationSearch.toLowerCase()));
  const eligibleCustomers = snapshot.customers.filter((customer) => customer.id !== relationProject?.customerId && customer.name.toLowerCase().includes(relationSearch.toLowerCase()));
  const closeRelation = () => { setRelationDialog(null); setProductPreview(null); setCustomerPreview(null); setRelationSearch(""); setRelationError(""); window.setTimeout(() => relationReturnFocusRef.current?.focus(), 0); };
  const openRelation = (kind: "customer" | "product", projectId: string) => { relationReturnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setRelationDialog({ kind, projectId }); setRelationSearch(""); setRelationError(""); setProductPreview(null); setCustomerPreview(null); window.setTimeout(() => relationCloseRef.current?.focus(), 0); };

  useEffect(() => {
    if (!relationDialog) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRelation();
      if (event.key !== "Tab") return;
      const dialog = relationCloseRef.current?.closest<HTMLElement>("[role=dialog]");
      const focusable = dialog ? Array.from(dialog.querySelectorAll<HTMLElement>("button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled])")) : [];
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", handleKey); return () => window.removeEventListener("keydown", handleKey);
  }, [relationDialog]);

  const previewProduct = async (targetId: string | null) => { if (!relationProject || targetId === (relationProject.itemExternalId || null)) return setProductPreview(null); setRelationBusy(true); setRelationError(""); try { setProductPreview(await mockLedgerService.previewProjectProduct(relationProject.id, targetId)); } catch (error) { setProductPreview(null); setRelationError(error instanceof Error ? error.message : "来源商品影响预览失败"); } finally { setRelationBusy(false); } };
  const previewCustomer = async (targetId: string) => { if (!relationProject || targetId === relationProject.customerId) return setCustomerPreview(null); setRelationBusy(true); setRelationError(""); try { setCustomerPreview(await mockLedgerService.previewCustomerRelation(relationProject.id, relationProject.customerId, targetId)); } catch (error) { setCustomerPreview(null); setRelationError(error instanceof Error ? error.message : "客户关系影响预览失败"); } finally { setRelationBusy(false); } };
  const commitRelation = async () => { setRelationBusy(true); setRelationError(""); try { const next = relationDialog?.kind === "product" && productPreview ? await mockLedgerService.commitProjectProduct(productPreview, crypto.randomUUID()) : relationDialog?.kind === "customer" && customerPreview ? await mockLedgerService.rebindCustomerRelation(customerPreview, crypto.randomUUID()) : null; if (!next) return; onPersistedSnapshot(next); closeRelation(); } catch (error) { setRelationError(error instanceof Error ? error.message : "关系变更失败，本次没有写入经营数据"); } finally { setRelationBusy(false); } };

  if (routedProject && projectRoute?.tab === "edit") {
    const product = products.find((item) => item.external_id === routedProject.itemExternalId);
    return <><ProjectEditView project={routedProject} snapshot={snapshot} productTitle={product?.title || (routedProject.itemExternalId ? `商品 ${routedProject.itemExternalId}` : "未关联来源商品")} onBack={() => onProjectRouteChange({ projectId: routedProject.id, tab: "overview" }, "back")} onSave={(nextProject) => { onSnapshotChange({ ...snapshot, projects: snapshot.projects.map((item) => item.id === nextProject.id ? nextProject : item) }); onProjectRouteChange({ projectId: routedProject.id, tab: "overview" }, "replace"); }} onChangeRelation={(kind) => openRelation(kind, routedProject.id)} />{renderRelationDialog()}</>;
  }
  if (routedProject && projectRoute) return <ProjectDetail snapshot={snapshot} projectId={routedProject.id} tab={projectRoute.tab} onBack={() => onProjectRouteChange(null, "back")} onEdit={() => editProject(routedProject.id)} onTabChange={(tab) => onProjectRouteChange({ projectId: routedProject.id, tab }, "replace")} onCreatePaymentPlan={onCreatePaymentPlan} onCreateChangeOrder={onCreateChangeOrder} onConfirmPayment={onConfirmPayment} onRecordSettlementIssue={onRecordSettlementIssue} onSnapshotChange={onSnapshotChange} />;

  function renderRelationDialog() {
    if (!relationDialog || !relationProject) return null;
    return <div className="project-relation-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeRelation(); }}><aside className="project-relation-dialog" role="dialog" aria-modal="true" aria-labelledby="project-relation-title">
      <header><div><small>RELATION CHANGE</small><h2 id="project-relation-title">确认变更{relationDialog.kind === "product" ? "来源商品" : "客户关系"}</h2><p>先查看影响范围，再确认是否写入。</p></div><button ref={relationCloseRef} type="button" aria-label="关闭关系变更" onClick={closeRelation}><X size={19} /></button></header>
      <section className="project-relation-current"><small>当前{relationDialog.kind === "product" ? "商品" : "客户"}</small><b>{relationDialog.kind === "product" ? currentProduct?.title || "未关联来源商品" : relationCustomer?.name || "未关联客户"}</b><em>当前归属</em></section>
      <label className="project-relation-search"><MagnifyingGlass size={17} /><input value={relationSearch} onChange={(event) => setRelationSearch(event.target.value)} placeholder={`搜索${relationDialog.kind === "product" ? "正在上架的本人商品" : "客户"}`} /></label>
      <section className="project-relation-options" aria-label="可选关系">{relationDialog.kind === "product" ? <>{eligibleProducts.map((product) => <button type="button" className={productPreview?.target_item_external_id === product.external_id ? "selected" : ""} disabled={relationBusy || product.external_id === relationProject.itemExternalId} onClick={() => void previewProduct(product.external_id)} key={product.external_id}><Storefront size={17} weight="duotone" /><span><b>{product.title}</b><small>{product.linked_projects.length} 个关联项目 · 当前上架采集</small></span><em>{product.external_id === relationProject.itemExternalId ? "当前" : productPreview?.target_item_external_id === product.external_id ? "待确认" : "选择"}</em></button>)}{!eligibleProducts.length && <p>没有可选的正在上架本人商品。</p>}{relationProject.itemExternalId && <button type="button" className="is-unbind" disabled={relationBusy} onClick={() => void previewProduct(null)}>解除当前来源商品关联</button>}</> : <>{eligibleCustomers.map((customer) => <button type="button" className={customerPreview?.target_customer_id === customer.id ? "selected" : ""} disabled={relationBusy} onClick={() => void previewCustomer(customer.id)} key={customer.id}><span className="project-relation-avatar">{customer.name.slice(0, 1)}</span><span><b>{customer.name}</b><small>{customer.source === "xianyu" ? "闲鱼客户" : customer.source === "wechat" ? "微信客户" : "经营客户"}</small></span><em>{customerPreview?.target_customer_id === customer.id ? "待确认" : "选择"}</em></button>)}{!eligibleCustomers.length && <p>没有匹配的其他客户。</p>}</>}</section>
      <section className="project-relation-impact" aria-live="polite"><h3>影响预览</h3>{productPreview ? <><div className="project-relation-move"><span><small>当前归属</small><b>{productPreview.current_item_title || "未关联"}</b></span><ArrowRight size={18} /><span><small>目标商品</small><b>{productPreview.target_item_title || "解除关联"}</b></span></div><dl><div><dt>净确认到账</dt><dd>{money.format(productPreview.impact.project_net_confirmed)}</dd></div><div><dt>项目支出</dt><dd>{money.format(productPreview.impact.project_expenses)}</dd></div><div><dt>退款</dt><dd>{money.format(productPreview.impact.project_refunds)}</dd></div><div><dt>归入商品实际利润</dt><dd>{money.format(productPreview.impact.project_profit)}</dd></div></dl>{productPreview.warnings.map((warning) => <p key={warning}><WarningCircle size={14} />{warning}</p>)}</> : customerPreview ? <><div className="project-relation-move"><span><small>当前客户</small><b>{customerPreview.current_customer_name}</b></span><ArrowRight size={18} /><span><small>目标客户</small><b>{customerPreview.target_customer_name}</b></span></div><dl><div><dt>项目</dt><dd>{customerPreview.impact.project_count}</dd></div><div><dt>付款记录</dt><dd>{customerPreview.impact.payment_count}</dd></div><div><dt>追加订单</dt><dd>{customerPreview.impact.change_order_count}</dd></div><div><dt>异常记录</dt><dd>{customerPreview.impact.settlement_issue_count}</dd></div></dl>{customerPreview.warnings.map((warning) => <p key={warning}><WarningCircle size={14} />{warning}</p>)}</> : <p className="is-empty">选择新的关系后，这里会先展示影响；选择本身不会写入。</p>}</section>
      {relationError && <p className="project-relation-error" role="alert">{relationError}</p>}<footer><small>revision + request-id 将用于事务保护</small><div><button type="button" onClick={closeRelation}>取消</button><button type="button" className="business-primary" disabled={relationBusy || (!productPreview && !customerPreview)} onClick={() => void commitRelation()}>{relationBusy ? "处理中…" : "确认变更关系"}</button></div></footer>
    </aside></div>;
  }

  return <div className="business-page project-hub-page"><section className="project-hub-shell">
    <header className="project-hub-head"><div><small>PROJECTS</small><h2>所有项目，一眼掌握</h2><p>直接浏览项目全貌，需要时再进入详情或编辑。</p></div><div className="project-hub-kind" role="group" aria-label="项目分类"><button type="button" className={projectKind === "personal" ? "active" : ""} onClick={() => { setProjectKind("personal"); setStatus("all"); }}><Code size={17} />个人项目</button><button type="button" className={projectKind === "client" ? "active" : ""} onClick={() => { setProjectKind("client"); setStatus("all"); }}><Briefcase size={17} />接单项目</button></div><button type="button" className="business-primary project-hub-create" onClick={() => onCreateProject(projectKind)}><Plus size={16} />新建项目</button></header>
    <section className="project-hub-metrics" aria-label="项目概览"><ProjectMetric icon={<Briefcase size={20} weight="duotone" />} label="当前项目" value={`${active.length} 个`} detail={`${category.length - active.length} 个已终止单独归档`} tone="purple" /><ProjectMetric icon={<CheckCircle size={20} weight="duotone" />} label="进行中" value={`${activeProjects.length} 个`} detail={`${projectTasks.length} 项任务持续推进`} tone="green" />{projectKind === "client" ? <><ProjectMetric icon={<Coins size={20} weight="duotone" />} label="合同总额" value={money.format(totalContract)} detail="只统计当前合作项目" tone="blue" /><ProjectMetric icon={<WarningCircle size={20} weight="duotone" />} label="待回款" value={money.format(outstanding)} detail={`${active.filter((item) => item.outstanding > 0).length} 个项目尚未收齐`} tone="orange" /></> : <><ProjectMetric icon={<ListChecks size={20} weight="duotone" />} label="任务总数" value={`${projectTasks.length} 项`} detail={`${projectTasks.filter((task) => task.status === "done").length} 项已完成`} tone="blue" /><ProjectMetric icon={<Timer size={20} weight="duotone" />} label="累计投入" value={`${actualHours}h`} detail="来自真实任务工时" tone="orange" /></>}</section>
    <section className="project-hub-toolbar"><label><MagnifyingGlass size={17} /><input aria-label="搜索项目、客户或商品" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={globalSearch ? `顶部搜索：${globalSearch}` : "搜索项目、客户或商品"} disabled={Boolean(globalSearch)} /></label><div className="project-hub-status" role="group" aria-label="项目状态筛选">{([['all', '全部'], ['in_progress', '进行中'], ['attention', '需关注'], ['finished', '已完成'], ['terminated', '已终止']] as Array<[ListStatus, string]>).map(([value, label]) => <button type="button" className={status === value ? "active" : ""} onClick={() => setStatus(value)} key={value} aria-pressed={status === value}>{label}<span>{searched.filter(item => matchesStatus(item, value)).length}</span></button>)}</div>{projectKind === "client" && <select aria-label="按客户筛选项目" value={customerFilter} onChange={event => setCustomerFilter(event.target.value)}><option value="">全部客户</option>{customerFilter && !customerOptions.some(customer => customer.id === customerFilter) && <option value={customerFilter}>已选客户（暂无项目）</option>}{customerOptions.map(customer => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select>}<select aria-label="项目排序" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}><option value="due">按交付日期</option><option value="updated">最近更新优先</option>{projectKind === "client" && <option value="amount">按合同金额</option>}</select>{(search || customerFilter || status !== "all") && <button type="button" className="project-filter-reset" onClick={() => {setSearch("");setCustomerFilter("");setStatus("all");}}>清空筛选</button>}</section>
    {sort === "updated" && <p role="status">按服务端项目资料更新时间排序；未同步更新时间的项目排在最后。</p>}
    <section className="project-hub-list" aria-label="项目列表"><header><span>项目 / 类型</span><span>客户</span><span>来源商品</span><span>状态</span><span>交付 / 风险</span><span>{projectKind === "client" ? "合同 / 待收" : "任务 / 工时"}</span><span>操作</span></header>{visible.length ? pageRows.map((item) => {
      const { project } = item; const customer = snapshot.customers.find((candidate) => candidate.id === project.customerId); const product = products.find((candidate) => candidate.external_id === project.itemExternalId); const terminal = latestTerminalSettlementIssue(item.settlementIssues); const tasks = snapshot.tasks.filter((task) => task.projectId === project.id); const remaining = daysUntil(project.dueDate); const statusLabel = terminal ? "已终止" : statusLabels[project.status]; const finished = project.status === "delivered" || project.status === "completed"; const dueStatus = terminal ? "历史项目" : finished ? "交付日期未确认" : remaining < 0 ? `已超期 ${Math.abs(remaining)} 天` : `剩余 ${remaining} 天`; const dueTone = !terminal && !finished && remaining < 0 ? "is-danger" : !terminal && !finished && remaining <= 3 ? "is-warning" : "";
      return <article key={project.id}><button type="button" className="project-hub-main" onClick={() => openProject(project.id)}><i className={`project-${project.accent}`}>{projectKind === "personal" ? <Code size={18} weight="duotone" /> : <Briefcase size={18} weight="duotone" />}</i><span><b>{project.name}</b><small>{project.type || (projectKind === "personal" ? "个人开发" : "定制开发")}</small></span></button><span className="project-hub-customer"><b>{projectKind === "personal" ? "—" : customer?.name || "未关联"}</b><small>{projectKind === "personal" ? "个人项目" : customer?.source === "xianyu" ? "闲鱼客户" : customer?.source === "wechat" ? "微信客户" : "经营客户"}</small></span><span className="project-hub-product"><b>{projectKind === "personal" ? "—" : product?.title || (project.itemExternalId ? `商品 ${project.itemExternalId}` : "未关联")}</b>{project.itemExternalId && <small>已绑定</small>}</span><span><em className={`project-hub-badge status-${terminal ? "terminated" : project.status}`}>{statusLabel}</em></span><span className="project-hub-date"><b>{shortDate(project.dueDate)}</b><small className={dueTone}>{dueStatus}</small></span><span className="project-hub-finance"><b>{projectKind === "client" ? money.format(project.totalAmount) : `${tasks.filter((task) => task.status === "done").length}/${tasks.length} 项`}</b><small className={item.outstanding > 0 ? "is-warning" : ""}>{projectKind === "client" ? `待收 ${money.format(item.outstanding)}` : `${tasks.reduce((sum, task) => sum + task.actualHours, 0)}h 已投入`}</small></span><span className="project-hub-actions"><button type="button" onClick={() => openProject(project.id)}>详情</button><button type="button" onClick={() => editProject(project.id)}><PencilSimple size={13} />编辑</button></span></article>;
    }) : <div className="project-hub-empty"><Briefcase size={32} weight="duotone" /><h3>没有匹配的项目</h3><p>调整搜索或筛选条件，或创建新的{projectKind === "personal" ? "个人" : "接单"}项目。</p><button type="button" className="business-primary" onClick={() => onCreateProject(projectKind)}><Plus size={16} />新建项目</button></div>}</section>
    <footer className="project-list-pagination"><span>共 {visible.length} 个项目</span><nav aria-label="项目分页"><button disabled={currentPage===1} onClick={()=>setPage(currentPage-1)} aria-label="上一页">上一页</button><span aria-live="polite">{currentPage} / {pageCount}</span><button disabled={currentPage===pageCount} onClick={()=>setPage(currentPage+1)} aria-label="下一页">下一页</button><select aria-label="每页项目数" value={pageSize} onChange={e=>setPageSize(Number(e.target.value))}><option value={10}>10 条/页</option><option value={20}>20 条/页</option></select></nav></footer>
  </section><ProjectListContext items={active} snapshot={snapshot} onOpen={openProject} onPayment={onConfirmPayment}/>{renderRelationDialog()}</div>;
}
