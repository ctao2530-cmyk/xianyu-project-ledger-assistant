import {
  ChatCircleDots,
  Clock,
  FolderOpen,
  ListChecks,
  PencilSimple,
  Plus,
  Storefront,
  Target,
  Timer,
} from "@phosphor-icons/react";
import type { ProductIntelligenceView } from "../data/localPlatformService";


const confidenceLabels: Record<string, string> = {
  high: "高置信",
  medium: "中等置信",
  low: "低置信",
};
const launchActionLabels: Record<string, string> = {
  launch: "建议上新",
  modify_existing: "优先修改现有商品",
  observe: "继续观察",
};

export function ProductLaunchWorkbench({
  data,
  busy,
  onCreateLaunchPlan,
  onCompleteLaunchPlan,
  onShowModification,
}: {
  data: ProductIntelligenceView;
  busy: boolean;
  onCreateLaunchPlan: () => Promise<void>;
  onCompleteLaunchPlan: (planId: string) => Promise<void>;
  onShowModification: () => void;
}) {
  const recommendation = data.launch_recommendation;
  const matchingPlanExists = data.launch_plans.some(
    (plan) => plan.keyword === recommendation.keyword
      && ["proposed", "planned"].includes(plan.status),
  );

  return <section className="product-launch-radar-card" id="product-launch-recommendation">
    <header><span><small>LAUNCH RADAR</small><h3>上新雷达</h3></span><em className={`confidence-${recommendation.confidence}`}>{confidenceLabels[recommendation.confidence] || recommendation.confidence}</em></header>
    <div className="launch-radar-hero">
      <span className="launch-radar-icon"><Target size={28} weight="duotone" /></span>
      <div><em className={`launch-action-pill action-${recommendation.recommended_action}`}>{launchActionLabels[recommendation.recommended_action] || recommendation.recommended_action}</em><h2>{recommendation.recommended_action === "launch" ? "证据已达到上新阈值" : recommendation.recommended_action === "modify_existing" ? "已有同类商品，先优化再决定" : "先补市场证据，再确认上新"}</h2><p>{recommendation.rationale[recommendation.rationale.length - 1]}</p></div>
    </div>
    <div className="launch-signal-strip">
      <span><ChatCircleDots size={21} weight="duotone" /><small>近 90 天</small><b>{recommendation.demand_conversations} 个相关咨询</b></span>
      <span><Storefront size={21} weight="duotone" /><small>供给覆盖</small><b>{recommendation.theme} · {recommendation.matching_product_count} 个商品</b></span>
      <span><ListChecks size={21} weight="duotone" /><small>高可见市场基准</small><b>{recommendation.benchmark.sample_days ? `${recommendation.benchmark.sample_days} 天 · ${recommendation.benchmark.high_visibility_result_count} 条` : "参考待导入"}</b></span>
    </div>
    <div className="launch-decision-grid">
      <article><small>建议商品类型</small><b>{recommendation.suggested_product_type}</b><em>来自需求主题与供给缺口</em></article>
      <article><small>标题方向</small><b>{recommendation.title_direction}</b><em>只提取通用词，不复制竞品标题</em></article>
      <article><small>公开价格参考</small><b>{recommendation.price_reference}</b><em>最终报价仍由工时与风险决定</em></article>
      <article><small>差异化重点</small><b>{recommendation.market_differentiation}</b><em>强调交付、验收和边界</em></article>
    </div>
    <div className="launch-recommendation-row">
      <Clock size={24} weight="duotone" />
      <span><small>建议发布窗口</small><b>{recommendation.recommended_window}</b><em>{recommendation.timing_basis}</em></span>
      {recommendation.recommended_action === "launch"
        ? <button type="button" className="product-primary-button" disabled={busy || !recommendation.keyword || matchingPlanExists} onClick={() => void onCreateLaunchPlan()}><Plus size={17} />{matchingPlanExists ? "方案已建立" : "建立上新方案"}</button>
        : recommendation.recommended_action === "modify_existing"
          ? <button type="button" className="product-outline-button" onClick={onShowModification}><PencilSimple size={17} />查看修改建议</button>
          : <button type="button" className="product-outline-button" disabled><Timer size={17} />继续积累证据</button>}
    </div>
    {data.launch_plans.length > 0 && <div className="launch-plan-list"><h4>我的手动上新方案</h4>{data.launch_plans.slice(0, 3).map((plan) => <article id={`product-launch-plan-${plan.id}`} key={plan.id}><i><FolderOpen size={17} /></i><span><b>{plan.title}</b><small>{plan.keyword} · {plan.recommended_window}</small></span><em>{plan.status === "planned" ? "待手动发布" : plan.status === "completed" ? "已完成" : plan.status === "cancelled" ? "已取消" : "待规划"}</em>{plan.status === "planned" && <button type="button" disabled={busy} onClick={() => void onCompleteLaunchPlan(plan.id)}>标记完成</button>}</article>)}</div>}
  </section>;
}
