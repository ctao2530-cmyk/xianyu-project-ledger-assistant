import {
  ArrowLeft,
  ArrowRight,
  BracketsCurly,
  CheckCircle,
  Clock,
  FileText,
  Flag,
  FlowArrow,
  LinkSimple,
  ListChecks,
  Question,
  Sparkle,
  Target,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  localPlatformService,
  type RequirementBlueprint,
  type RequirementCaseDetail,
  type RequirementCaseSummary,
} from "../data/localPlatformService";
import type { Customer } from "../types";
import type { CustomerRequirementRoute } from "../App";
import type { ProjectRouteMode } from "./BusinessAssistantPages";
import "./customer-requirement-blueprint.css";


type LayerKey = "objectives" | "capabilities" | "stages" | "acceptance";

interface VisualNode {
  id: string;
  layer: LayerKey;
  title: string;
  description: string;
  eyebrow: string;
  meta?: string;
  raw: Record<string, unknown>;
}

interface VisualEdge {
  from: string;
  to: string;
}

interface VisualBlueprint {
  nodes: Record<LayerKey, VisualNode[]>;
  edges: VisualEdge[];
  isLegacy: boolean;
}

const layerMeta: Record<LayerKey, { label: string; hint: string; icon: typeof Target }> = {
  objectives: { label: "项目目标", hint: "为什么要做", icon: Target },
  capabilities: { label: "功能能力", hint: "需要实现什么", icon: BracketsCurly },
  stages: { label: "实施阶段", hint: "具体怎么实现", icon: FlowArrow },
  acceptance: { label: "交付验收", hint: "怎样算完成", icon: ListChecks },
};

function asStringArray(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function normalizeBlueprint(document: RequirementCaseDetail["document"]): VisualBlueprint {
  const empty: Record<LayerKey, VisualNode[]> = { objectives: [], capabilities: [], stages: [], acceptance: [] };
  if (!document || typeof document !== "object") return { nodes: empty, edges: [], isLegacy: false };
  const raw = document as Record<string, unknown>;
  if (raw.schema_version === "2.0") {
    const blueprint = document as RequirementBlueprint;
    const nodes: Record<LayerKey, VisualNode[]> = {
      objectives: blueprint.objectives.map((node) => ({ id: node.id, layer: "objectives", title: node.title, description: node.description, eyebrow: "OBJECTIVE", raw: node as unknown as Record<string, unknown> })),
      capabilities: blueprint.capabilities.map((node) => ({ id: node.id, layer: "capabilities", title: node.title, description: node.description, eyebrow: node.priority.toUpperCase(), meta: node.priority === "must" ? "核心能力" : node.priority === "should" ? "建议能力" : "可选能力", raw: node as unknown as Record<string, unknown> })),
      stages: blueprint.stages.map((node, index) => ({ id: node.id, layer: "stages", title: node.title, description: node.implementation, eyebrow: `STAGE ${String(index + 1).padStart(2, "0")}`, meta: `${node.estimated_hours} 小时`, raw: node as unknown as Record<string, unknown> })),
      acceptance: blueprint.acceptance_gates.map((node) => ({ id: node.id, layer: "acceptance", title: node.title, description: node.description, eyebrow: "ACCEPTANCE", meta: `${node.criteria.length} 项准则`, raw: node as unknown as Record<string, unknown> })),
    };
    const edges: VisualEdge[] = [
      ...blueprint.capabilities.flatMap((node) => node.objective_ids.map((id) => ({ from: id, to: node.id }))),
      ...blueprint.stages.flatMap((node) => node.capability_ids.map((id) => ({ from: id, to: node.id }))),
      ...blueprint.acceptance_gates.flatMap((node) => node.stage_ids.map((id) => ({ from: id, to: node.id }))),
    ];
    return { nodes, edges, isLegacy: false };
  }

  const confirmed = asStringArray(raw.confirmed_requirements);
  const scopes = asStringArray(raw.scope_items);
  const stages = Array.isArray(raw.stages) ? raw.stages.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [];
  const criteria = asStringArray(raw.acceptance_criteria);
  const objectives = (confirmed.length ? confirmed : [String(raw.executive_summary || "历史需求目标")]).map((value, index) => ({ id: `legacy-objective-${index}`, layer: "objectives" as const, title: value, description: "来自旧版 Codex 需求文档", eyebrow: "LEGACY OBJECTIVE", raw: { description: value } }));
  const capabilities = (scopes.length ? scopes : confirmed).map((value, index) => ({ id: `legacy-capability-${index}`, layer: "capabilities" as const, title: value, description: "旧版范围项，待在新版蓝图中补充引用关系", eyebrow: "LEGACY SCOPE", raw: { description: value } }));
  const stageNodes = stages.map((stage, index) => ({ id: `legacy-stage-${index}`, layer: "stages" as const, title: String(stage.title || `阶段 ${index + 1}`), description: String(stage.objective || "旧版实施阶段"), eyebrow: `STAGE ${String(index + 1).padStart(2, "0")}`, meta: "待补工时", raw: stage }));
  const acceptance = criteria.map((value, index) => ({ id: `legacy-acceptance-${index}`, layer: "acceptance" as const, title: value, description: "旧版全局验收标准", eyebrow: "LEGACY GATE", raw: { criteria: [value] } }));
  const edges: VisualEdge[] = [];
  capabilities.forEach((node, index) => objectives[index % Math.max(objectives.length, 1)] && edges.push({ from: objectives[index % objectives.length].id, to: node.id }));
  stageNodes.forEach((node, index) => capabilities[index % Math.max(capabilities.length, 1)] && edges.push({ from: capabilities[index % capabilities.length].id, to: node.id }));
  acceptance.forEach((node, index) => stageNodes[index % Math.max(stageNodes.length, 1)] && edges.push({ from: stageNodes[index % stageNodes.length].id, to: node.id }));
  return { nodes: { objectives, capabilities, stages: stageNodes, acceptance }, edges, isLegacy: true };
}

function statusLabel(value: string) {
  return value === "approved" ? "已确认" : value === "ready" ? "可报价" : value === "discovery" ? "探索中" : value === "needs_clarification" ? "待澄清" : "澄清中";
}

export function CustomerRequirementBlueprintPage({
  customer,
  route,
  onRouteChange,
}: {
  customer: Customer;
  route: CustomerRequirementRoute;
  onRouteChange: (route: CustomerRequirementRoute | null, mode?: ProjectRouteMode) => void;
}) {
  const [cases, setCases] = useState<RequirementCaseSummary[]>([]);
  const [detail, setDetail] = useState<RequirementCaseDetail | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const routeChangeRef = useRef(onRouteChange);

  useEffect(() => {
    routeChangeRef.current = onRouteChange;
  }, [onRouteChange]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void localPlatformService.customerRequirements(customer.id)
      .then((rows) => {
        if (!active) return;
        setCases(rows);
        if (route.caseId && !rows.some((item) => item.id === route.caseId)) {
          routeChangeRef.current({ customerId: customer.id, caseId: null }, "replace");
        }
      })
      .catch((reason) => active && setError(reason instanceof Error ? reason.message : "需求案例加载失败"))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [customer.id, route.caseId]);

  useEffect(() => {
    if (!route.caseId) {
      setDetail(null);
      setSelectedVersion(null);
      return;
    }
    let active = true;
    setLoading(true);
    void localPlatformService.requirementCase(route.caseId, selectedVersion || undefined)
      .then((value) => active && setDetail(value))
      .catch((reason) => active && setError(reason instanceof Error ? reason.message : "蓝图加载失败"))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [route.caseId, selectedVersion]);

  if (!route.caseId) {
    return <div className="requirement-center-page">
      <header className="requirement-center-hero">
        <button className="blueprint-back" onClick={() => onRouteChange(null, "back")}><ArrowLeft size={16} />返回客户列表</button>
        <div><span>REQUIREMENT CENTER</span><h2>{customer.name}的需求蓝图</h2><p>每个业务诉求独立建档，保留来源会话、版本演进和后续项目关联。</p></div>
        <aside><strong>{cases.length}</strong><small>个需求案例</small></aside>
      </header>
      {loading ? <div className="blueprint-loading"><Sparkle className="spin" size={22} />正在读取需求案例…</div> : error ? <div className="blueprint-empty error"><WarningCircle size={30} /><h3>无法读取需求案例</h3><p>{error}</p></div> : cases.length ? <section className="requirement-case-grid">
        {cases.map((item, index) => <button key={item.id} onClick={() => onRouteChange({ customerId: customer.id, caseId: item.id }, "push")}>
          <i>{String(index + 1).padStart(2, "0")}</i>
          <span className={`case-status status-${item.status}`}>{statusLabel(item.status)}</span>
          <h3>{item.title}</h3>
          <p><FileText size={15} />V{item.current_version} · {item.source_count} 个来源会话</p>
          <footer><span><Clock size={15} />{item.estimated_hours || "待补"} 小时</span><span className={item.open_question_count ? "warn" : "ok"}><Question size={15} />{item.open_question_count} 个待确认</span><ArrowRight size={18} /></footer>
        </button>)}
      </section> : <div className="blueprint-empty"><FileText size={34} /><h3>还没有需求案例</h3><p>请从“客户消息 → 需求分析”手动导出分析文档，上传给 GPT 后，再把 GPT 返回的结构化 JSON 导入系统。</p></div>}
    </div>;
  }

  if (loading && !detail) return <div className="blueprint-loading"><Sparkle className="spin" size={22} />正在构建需求蓝图…</div>;
  if (!detail) return <div className="blueprint-empty error"><WarningCircle size={30} /><h3>蓝图无法打开</h3><p>{error || "需求案例不存在"}</p><button onClick={() => onRouteChange({ customerId: customer.id, caseId: null }, "replace")}>返回需求中心</button></div>;

  return <RequirementBlueprintDetail
    customer={customer}
    detail={detail}
    selectedVersion={selectedVersion}
    onVersion={setSelectedVersion}
    onBack={() => onRouteChange({ customerId: customer.id, caseId: null }, "back")}
  />;
}

function RequirementBlueprintDetail({ customer, detail, selectedVersion, onVersion, onBack }: { customer: Customer; detail: RequirementCaseDetail; selectedVersion: number | null; onVersion: (version: number | null) => void; onBack: () => void }) {
  const visual = useMemo(() => normalizeBlueprint(detail.document), [detail.document]);
  const allNodes = useMemo(() => Object.values(visual.nodes).flat(), [visual.nodes]);
  const defaultNode = visual.nodes.stages[0] || allNodes[0];
  const [selectedId, setSelectedId] = useState(defaultNode?.id || "");
  const selectedNode = allNodes.find((node) => node.id === selectedId) || defaultNode;
  const [positions, setPositions] = useState<Record<string, { x: number; y: number; width: number; height: number }>>({});
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const nodeRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => { setSelectedId(defaultNode?.id || ""); }, [defaultNode?.id]);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const measure = () => {
      const root = canvas.getBoundingClientRect();
      const next: Record<string, { x: number; y: number; width: number; height: number }> = {};
      Object.entries(nodeRefs.current).forEach(([id, element]) => {
        if (!element) return;
        const box = element.getBoundingClientRect();
        next[id] = { x: box.left - root.left, y: box.top - root.top, width: box.width, height: box.height };
      });
      setPositions(next);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(canvas);
    Object.values(nodeRefs.current).forEach((node) => node && observer.observe(node));
    measure();
    return () => observer.disconnect();
  }, [visual]);

  const related = useMemo(() => {
    if (!selectedId) return new Set<string>();
    const adjacency = new Map<string, Set<string>>();
    visual.edges.forEach(({ from, to }) => {
      if (!adjacency.has(from)) adjacency.set(from, new Set());
      if (!adjacency.has(to)) adjacency.set(to, new Set());
      adjacency.get(from)!.add(to);
      adjacency.get(to)!.add(from);
    });
    const found = new Set([selectedId]);
    const queue = [selectedId];
    while (queue.length) {
      const current = queue.shift()!;
      adjacency.get(current)?.forEach((next) => {
        if (!found.has(next)) { found.add(next); queue.push(next); }
      });
    }
    return found;
  }, [selectedId, visual.edges]);

  const moveFocus = (event: React.KeyboardEvent<HTMLButtonElement>, node: VisualNode) => {
    const layers = Object.keys(layerMeta) as LayerKey[];
    const layerIndex = layers.indexOf(node.layer);
    const index = visual.nodes[node.layer].findIndex((item) => item.id === node.id);
    let next: VisualNode | undefined;
    if (event.key === "ArrowDown") next = visual.nodes[node.layer][Math.min(index + 1, visual.nodes[node.layer].length - 1)];
    if (event.key === "ArrowUp") next = visual.nodes[node.layer][Math.max(index - 1, 0)];
    if (event.key === "ArrowRight" && layerIndex < layers.length - 1) next = visual.nodes[layers[layerIndex + 1]][Math.min(index, visual.nodes[layers[layerIndex + 1]].length - 1)];
    if (event.key === "ArrowLeft" && layerIndex > 0) next = visual.nodes[layers[layerIndex - 1]][Math.min(index, visual.nodes[layers[layerIndex - 1]].length - 1)];
    if (!next) return;
    event.preventDefault();
    setSelectedId(next.id);
    nodeRefs.current[next.id]?.focus();
  };

  const blueprint = detail.document && (detail.document as Record<string, unknown>).schema_version === "2.0" ? detail.document as RequirementBlueprint : null;
  const evidence = blueprint?.evidence_refs.filter((item) => asStringArray(selectedNode?.raw.evidence_refs).includes(item.id)) || [];
  const totalHours = blueprint?.stages.reduce((sum, stage) => sum + stage.estimated_hours, 0) || detail.estimated_hours;

  return <div className="requirement-blueprint-page">
    <header className="blueprint-command-bar">
      <button className="blueprint-back" onClick={onBack}><ArrowLeft size={16} />需求中心</button>
      <div className="blueprint-title"><span>REQUIREMENT BLUEPRINT</span><h2>{detail.title}</h2><p>{customer.name} · {blueprint?.project_type || "历史需求文档"}</p></div>
      <div className="blueprint-command-actions">
        <span className={`blueprint-status status-${detail.status}`}><i />{statusLabel(detail.status)}</span>
        <label>版本<select value={selectedVersion || detail.selected_version?.version || detail.current_version} onChange={(event) => onVersion(Number(event.target.value))}>{detail.versions.map((version) => <option value={version.version} key={version.id}>V{version.version} · {version.source_label}</option>)}</select></label>
      </div>
    </header>

    <section className="blueprint-summary-strip">
      <span><FileText size={19} weight="duotone" /><small>当前版本</small><b>V{detail.selected_version?.version || detail.current_version}</b></span>
      <span><LinkSimple size={19} weight="duotone" /><small>来源会话</small><b>{detail.source_count}</b></span>
      <span><Clock size={19} weight="duotone" /><small>预计工时</small><b>{totalHours || "待补"}{totalHours ? "h" : ""}</b></span>
      <span className={detail.open_question_count ? "warning" : "success"}><Question size={19} weight="duotone" /><small>待确认问题</small><b>{detail.open_question_count}</b></span>
      <p>{detail.selected_version?.change_summary || "需求蓝图已保存"}</p>
    </section>

    {visual.isLegacy && <div className="legacy-blueprint-notice"><WarningCircle size={17} /><span><b>旧版需求只读适配</b>该版本缺少稳定节点引用与阶段工时；从客户消息导入 GPT 蓝图 V2 后即可使用完整报价与关系追踪。</span></div>}

    <section className="blueprint-workspace">
      <div className="blueprint-scroll-shell">
        <div className="blueprint-canvas" ref={canvasRef}>
          <svg className="blueprint-connectors" aria-hidden="true">
            <defs><linearGradient id="blueprint-link" x1="0" x2="1"><stop offset="0" stopColor="#8a74ff" /><stop offset="0.52" stopColor="#6591ff" /><stop offset="1" stopColor="#45c78c" /></linearGradient></defs>
            {visual.edges.map((edge) => {
              const from = positions[edge.from]; const to = positions[edge.to];
              if (!from || !to) return null;
              const x1 = from.x + from.width; const y1 = from.y + from.height / 2; const x2 = to.x; const y2 = to.y + to.height / 2; const bend = Math.max(28, (x2 - x1) * .45);
              const active = !selectedId || (related.has(edge.from) && related.has(edge.to));
              return <path className={active ? "active" : "dimmed"} d={`M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`} key={`${edge.from}-${edge.to}`} />;
            })}
          </svg>
          {(Object.keys(layerMeta) as LayerKey[]).map((layer) => {
            const meta = layerMeta[layer]; const Icon = meta.icon;
            return <section className={`blueprint-layer layer-${layer}`} key={layer}>
              <header><i><Icon size={18} weight="duotone" /></i><span><b>{meta.label}</b><small>{meta.hint}</small></span><em>{visual.nodes[layer].length}</em></header>
              <div>{visual.nodes[layer].map((node) => <button
                ref={(element) => { nodeRefs.current[node.id] = element; }}
                type="button"
                className={`${selectedId === node.id ? "selected" : ""} ${selectedId && !related.has(node.id) ? "unrelated" : ""}`}
                aria-current={selectedId === node.id ? "true" : undefined}
                onClick={() => setSelectedId(node.id)}
                onKeyDown={(event) => moveFocus(event, node)}
                key={node.id}
              ><small>{node.eyebrow}</small><h3>{node.title}</h3><p>{node.description}</p>{node.meta && <em>{node.meta}</em>}<ArrowRight className="node-arrow" size={15} /></button>)}</div>
            </section>;
          })}
        </div>
      </div>

      <aside className="blueprint-inspector" key={selectedNode?.id}>
        {selectedNode ? <>
          <header><span>{layerMeta[selectedNode.layer].label}</span><h3>{selectedNode.title}</h3><p>{selectedNode.description}</p></header>
          {typeof selectedNode.raw.implementation === "string" && <InspectorSection title="实现说明" items={[selectedNode.raw.implementation]} />}
          <InspectorSection title="工作项" items={asStringArray(selectedNode.raw.work_items)} />
          <InspectorSection title="交付物" items={asStringArray(selectedNode.raw.deliverables)} />
          <InspectorSection title="验收细则" items={asStringArray(selectedNode.raw.criteria)} />
          <InspectorSection title="依赖关系" items={[...asStringArray(selectedNode.raw.dependency_ids), ...asStringArray(selectedNode.raw.capability_ids), ...asStringArray(selectedNode.raw.objective_ids)]} empty="当前节点无前置依赖" />
          {evidence.length > 0 && <section className="inspector-evidence"><h4>对话证据</h4>{evidence.map((item) => <blockquote key={item.id}><span>消息 #{item.message_number}</span>{item.quote}</blockquote>)}</section>}
          {selectedNode.layer === "stages" && typeof selectedNode.raw.estimated_hours === "number" && <div className="inspector-hours"><Clock size={18} /><span><small>阶段预计工时</small><b>{String(selectedNode.raw.estimated_hours)} 小时</b></span></div>}
        </> : <div className="inspector-empty"><Sparkle size={26} /><p>选择任一节点查看实现、证据与验收细节。</p></div>}
      </aside>
    </section>

    {blueprint && <section className="blueprint-bottom-grid">
      <article className="blueprint-timeline"><header><span><FlowArrow size={18} />实施时间线</span><b>{totalHours} 小时</b></header><div>{blueprint.stages.map((stage, index) => <button onClick={() => setSelectedId(stage.id)} key={stage.id}><i>{index + 1}</i><span><b>{stage.title}</b><small>{stage.estimated_hours}h · {stage.deliverables.length} 项交付</small></span><em style={{ flexGrow: Math.max(stage.estimated_hours, 1) }} /></button>)}</div></article>
      <article className="blueprint-checklist"><header><span><CheckCircle size={18} />交付 Checklist</span><b>{blueprint.acceptance_gates.reduce((sum, gate) => sum + gate.criteria.length, 0)} 项</b></header>{blueprint.acceptance_gates.flatMap((gate) => gate.criteria.map((criterion) => <p key={`${gate.id}-${criterion}`}><CheckCircle size={16} weight="duotone" /><span>{criterion}</span><small>{gate.title}</small></p>))}</article>
    </section>}
  </div>;
}

function InspectorSection({ title, items, empty }: { title: string; items: string[]; empty?: string }) {
  if (!items.length && !empty) return null;
  return <section className="inspector-section"><h4>{title}</h4>{items.length ? <ul>{items.map((item) => <li key={item}><i />{item}</li>)}</ul> : <p>{empty}</p>}</section>;
}
