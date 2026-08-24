import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../src/pages/ProductIntelligencePage.tsx", import.meta.url);
const servicePath = new URL("../src/data/localPlatformService.ts", import.meta.url);
const stylesPath = new URL("../src/pages/product-intelligence.css", import.meta.url);
const appPath = new URL("../src/App.tsx", import.meta.url);
const trafficDateTimePath = new URL("../src/utils/trafficDateTime.ts", import.meta.url);
const growthWorkbenchPath = new URL("../src/components/TrafficGrowthWorkbench.tsx", import.meta.url);

test("v2.4 start flow keeps T0 preparation, human purchase, and actual server time separate", async () => {
  const page = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");

  assert.match(page, /trafficStartPreview\(batch\.id\)/);
  assert.match(page, /prepareTrafficBaseline/);
  assert.match(page, /远程刷新整批 T0/);
  assert.match(page, /人工填写整批 T0/);
  assert.match(page, /已在闲鱼投放，开始计时/);
  assert.match(page, /点击确认时由服务端写入/);
  assert.match(page, /expected_baseline_captured_at/);
  assert.match(page, /baselineRequestIds: Record<"remote_refresh" \| "manual", string>/);
  assert.match(page, /startRequestId: string/);
  assert.doesNotMatch(page, /completed_at: new Date\(\)\.toISOString\(\)/);
  assert.doesNotMatch(page, /recorded_at: new Date\(\)\.toISOString\(\)/);
  assert.match(service, /trafficStartPreview/);
  assert.match(service, /mode: "remote_refresh" \| "manual"/);
  assert.match(service, /expected_updated_at: string/);
});

test("growth workbench exposes the approved clean time matrix and manual-only budget ladder", async () => {
  const page = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");
  const workbench = await readFile(growthWorkbenchPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(page, /<TrafficGrowthWorkbench/);
  assert.match(page, /!trafficGrowth\?\.active_experiment && <section className="product-plan-shell"/);
  assert.match(page, /!trafficGrowth\?\.active_experiment && <ExposureAnalytics/);
  assert.match(service, /trafficGrowth: \(\) => api<TrafficGrowthOverviewView>/);
  assert.match(service, /createTrafficExperiment/);
  assert.match(service, /refreshTrafficAttributions/);
  assert.match(service, /applyTrafficBudgetDecision/);
  assert.match(workbench, /"12": Sun/);
  assert.match(workbench, /"16": SunHorizon/);
  assert.match(workbench, /"20": Clock/);
  assert.match(workbench, /\{window\.time_range\}/);
  assert.match(workbench, /探索 \{experiment\.valid_exploration_batches\}\/\{experiment\.required_exploration_batches\}/);
  assert.match(workbench, /确认 \{experiment\.valid_confirmation_batches\}\/\{experiment\.required_confirmation_batches\}/);
  assert.match(workbench, /咨询均值领先次优时段每批 ≥0\.5 次/);
  assert.match(workbench, /浏览不低于次优时段 70%/);
  assert.doesNotMatch(workbench, /差异 ≥10%/);
  assert.match(workbench, /T0.*S1.*S2.*S3/s);
  assert.match(workbench, /24.*24.*36.*48/s);
  assert.match(workbench, /不会自动购买曝光/);
  assert.match(styles, /\.traffic-growth-workbench/);
  assert.match(styles, /@container product-intelligence-workspace \(max-width: 560px\)/);
  assert.match(styles, /\.traffic-window-table \{ display: none; \}/);
  assert.match(styles, /\.traffic-window-mobile-detail \{ display: block/);
});

test("commercial attribution review is a focus-trapped responsive manual drawer", async () => {
  const workbench = await readFile(growthWorkbenchPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(workbench, /role="dialog" aria-modal="true"/);
  assert.match(workbench, /event\.key === "Escape"/);
  assert.match(workbench, /event\.key !== "Tab"/);
  assert.match(workbench, /drawerTriggerRef\.current\?\.focus\(\)/);
  assert.match(workbench, /曝光后关联，不等同于平台因果增量/);
  assert.match(workbench, /必须先把精确对话绑定到项目/);
  assert.match(workbench, /onDecideAttribution\(experiment, attribution, "confirm"\)/);
  assert.match(workbench, /onDecideAttribution\(experiment, attribution, "reject"\)/);
  assert.match(styles, /\.traffic-attribution-layer/);
  assert.match(styles, /height: min\(82vh, 720px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.traffic-attribution-drawer \{ animation: none/);
});

test("v2.4 plan binding and replan remain explicit and confirmation gated", async () => {
  const page = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");

  assert.match(page, /activePlanSlot\.source_batch_id === activeObservationBatch\.id/);
  assert.match(page, /slot\.source_batch_id === activeObservationBatch\.id/);
  assert.doesNotMatch(page, /slot\.products\.some\(\(product\) => activeObservationBatch\.products\.some/);
  assert.match(page, /trafficReplanPreview\(batch\.id\)/);
  assert.match(page, /确认按预览重排/);
  assert.match(page, /总费用保持/);
  assert.match(page, /batchReplan\.batchCost/);
  assert.match(page, /原批次 ID、总费用和审计记录均保留/);
  assert.match(service, /preview_hash: string/);
  assert.match(service, /replanTrafficBatch/);
});

test("every real started batch can show true checkpoints without future interpolation", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(page, /function ExposureBatchMiniChart/);
  assert.match(page, /尚未开始，没有真实曲线/);
  assert.match(page, /function batchAggregateSeries/);
  assert.match(page, /checkpoint_metrics\.find/);
  assert.match(page, /checkpoint \? checkpoint\[selectedMetric\.checkpointDeltaKey\] : null/);
  assert.match(page, /connectNulls=\{false\}/);
  assert.match(page, /isAnimationActive=\{false\}/);
  assert.match(page, /展开完整曲线/);
  assert.match(page, /ExposureProductDelta batches=\{\[batch\]\}/);
});

test("exposure layout uses the workspace container instead of squeezing by browser width", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /container-name: product-intelligence-workspace/);
  assert.match(styles, /container-type: inline-size/);
  assert.match(styles, /\.product-intelligence-page > \* \{\s*min-width: 0;/);
  assert.match(styles, /@container product-intelligence-workspace \(min-width: 1180px\)/);
  assert.match(styles, /@container product-intelligence-workspace \(min-width: 760px\) and \(max-width: 1179px\)/);
  assert.match(styles, /@container product-intelligence-workspace \(max-width: 759px\)/);
  assert.match(styles, /\.exposure-early-observation[\s\S]*grid-column: 1 \/ -1/);
  assert.match(styles, /@media \(max-width: 560px\)[\s\S]*\.product-batch-mini-chart/);
});

test("batch history is fully searchable, date grouped, and only one batch is rendered", async () => {
  const page = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");

  assert.match(page, /trafficBatches\(\{[\s\S]*cursor,[\s\S]*limit: 100/);
  assert.match(page, /do \{[\s\S]*cursor = page\.has_more \? page\.next_cursor : null;[\s\S]*\} while \(cursor\)/);
  assert.doesNotMatch(page, /loadMoreBatches/);
  assert.match(page, /const \[selectedBatchId, setSelectedBatchId\] = useState<string \| null>\(null\)/);
  assert.match(page, /const \[batchSearch, setBatchSearch\] = useState\(""\)/);
  assert.match(page, /batchCreatedDayLabel\(batch\.created_at\)/);
  assert.match(page, /groupedBatchHistory\.map/);
  assert.match(page, /placeholder="搜索日期、商品或状态"/);
  assert.match(page, /handleTrackedBatchActivation/);
  assert.match(page, /event\.key !== "Enter" && event\.key !== " "/);
  assert.match(page, /className="product-batch-list is-single">\{\[selectedBatch\]\.map/);
  assert.match(page, /尚未开始/);
  assert.match(page, /planned_actual_delta_label/);
  assert.match(page, /所有检查点从实际开始/);
  assert.match(service, /next_cursor: string \| null/);
  assert.match(service, /has_more: boolean/);
});

test("new batch creation records an already completed purchase at server time", async () => {
  const page = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(page, /const recorded = await localPlatformService\.recordTrafficBatch\(\{/);
  assert.match(page, /plan_slot_id: null/);
  assert.match(page, /confirmed_already_purchased: true/);
  assert.match(page, /记录刚完成的真实投流/);
  assert.match(page, /确认记录真实投流/);
  assert.match(page, /服务端记录当前北京时间/);
  assert.match(page, /真实投流已按服务端北京时间记录，48 小时观察已开始/);
  assert.doesNotMatch(page, /planned = await localPlatformService\.createTrafficBatch/);
  assert.doesNotMatch(page, /plannedLocal/);
  assert.doesNotMatch(page, /保存批次计划/);
  assert.match(service, /recordTrafficBatch/);
  assert.match(styles, /@media \(max-width: 560px\)[\s\S]*\.product-batch-picker-popover/);
});

test("executed plan slots show the real batch and cannot be scheduled twice", async () => {
  const page = await readFile(pagePath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(page, /const activePlanExecutedBatch = activePlanSlot\?\.status === "executed"/);
  assert.match(page, /已执行多商品曝光/);
  assert.match(page, /今日已执行/);
  assert.match(page, /已投入 \$\{moneyExact\.format\(activePlanExecutedBatch\.actual_cost\)\}/);
  assert.match(page, /执行事实已冻结/);
  assert.match(page, /查看已执行批次/);
  assert.match(page, /navigateWorkspace\("exposure", "batch", activePlanExecutedBatch\.id\)/);
  assert.match(page, /重新评估不会改写今日执行事实/);
  assert.match(page, /低置信探索，不进入时段或预算/);
  assert.match(styles, /\.plan-slot-state\.is-executed/);
  assert.match(styles, /\.product-plan-focus\.is-executed/);
});

test("checkpoint collection exposes automatic and manual modes with safe recovery", async () => {
  const page = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(page, /检查点采集方式/);
  assert.match(page, /自动采集（推荐）/);
  assert.match(page, /到点提醒，我手动记录/);
  assert.match(page, /恢复连接并补采/);
  assert.match(page, /改为人工补齐/);
  assert.match(page, /不会自动重复读取成功商品/);
  assert.match(page, /checkpoint_collection_mode: batchDraft\.checkpointCollectionMode/);
  assert.match(page, /batchDraftDialogRef/);
  assert.match(page, /batchDraftCloseRef/);
  assert.match(page, /batchDraftTriggerRef/);
  assert.match(page, /event\.key === "Escape"/);
  assert.match(page, /event\.key !== "Tab"/);
  assert.match(page, /window\.setTimeout\(\(\) => previousFocus\?\.focus\(\), 0\)/);
  assert.match(service, /checkpoint_collection_mode\?: "auto" \| "manual"/);
  assert.match(service, /updateTrafficCheckpointCollectionMode/);
  assert.match(service, /retryTrafficCheckpointCollection/);
  assert.match(styles, /\.traffic-collection-control/);
  assert.match(styles, /\.traffic-collection-alert/);
  assert.match(styles, /@media \(max-width: 560px\)[\s\S]*\.traffic-collection-mode-tabs/);
});

test("compact exposure layout keeps the default page short and the current batch chart collapsed", async () => {
  const page = await readFile(pagePath, "utf8");
  const styles = await readFile(stylesPath, "utf8");
  const currentBatchSection = page.slice(
    page.indexOf('className="exposure-current-batch"'),
    page.indexOf('className="exposure-future-plan"'),
  );

  assert.doesNotMatch(currentBatchSection, /<ExposureProductDelta/);
  assert.match(page, /const \[expandedBatchId, setExpandedBatchId\] = useState<string \| null>\(null\)/);
  assert.match(page, /aria-expanded=\{expandedBatchId === batch\.id\}/);
  assert.match(page, /expandedBatchId === batch\.id && batch\.started_at && \(batch\.status !== "invalidated" \|\| batch\.exploratory_available\) && <ExposureProductDelta/);
  assert.match(page, /product-exposure-analytics is-compact/);
  assert.match(styles, /\.exposure-plan-overview-grid[\s\S]*align-items:\s*start/);
  assert.match(styles, /@container product-intelligence-workspace \(min-width: 1180px\)[\s\S]*minmax\(320px, 4fr\)[\s\S]*minmax\(0, 8fr\)/);
  assert.match(styles, /\.exposure-future-plan \.product-week-plan > button \{ min-height: 102px/);
});

test("the seven-day plan exposes products, exact stability semantics, and day actions", async () => {
  const page = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(service, /lock_mode: "none" \| "stability" \| "manual" \| string/);
  assert.match(service, /cooldown_conflict_count: number/);
  assert.match(service, /cooldown_until: string \| null/);
  assert.match(page, /slot\.lock_label/);
  assert.match(page, /24h内计划固定/);
  assert.match(page, /当前组合没有 72 小时冷却冲突/);
  assert.match(page, /activePlanSlot\.products\.map/);
  assert.match(page, /product\.reason/);
  assert.match(page, /product\.role/);
  assert.match(page, /按这 \{activePlanSlot\.products\.length\} 件建立批次/);
  assert.match(page, /查看 \{activePlanSlot\.products\.length\} 件商品修改建议/);
  assert.match(page, /navigateWorkspace\("launch", "product"/);
  assert.match(page, /当前无观察中批次/);
  assert.match(page, /不是冷却，也不是禁用/);
  assert.doesNotMatch(page, /\{slot\.locked && <LockSimple/);
  assert.match(styles, /\.exposure-last-batch-strip/);
  assert.match(styles, /\.product-plan-product-list/);
  assert.match(styles, /\.product-plan-cooldown-note/);
  assert.match(styles, /\.product-plan-legend/);
});

test("actual overlap dialog is explicit, focus trapped, and never presented as a clean batch", async () => {
  const page = await readFile(pagePath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(page, /actualOverlapDialogRef/);
  assert.match(page, /actualOverlapCloseRef/);
  assert.match(page, /event\.key === "Escape"/);
  assert.match(page, /event\.key !== "Tab"/);
  assert.match(page, /previousFocus\?\.focus\(\)/);
  assert.match(page, /我确认这批曝光已经在闲鱼实际购买/);
  assert.match(page, /永久标记为“归因重叠”/);
  assert.match(page, /没有可靠 T0（推荐）/);
  assert.match(page, /点击确认时由服务端记录当前北京时间/);
  assert.match(page, /立即终止观察，不再产生检查点提醒/);
  assert.doesNotMatch(page, /actualLocal/);
  assert.doesNotMatch(page, /actual_started_at:/);
  assert.doesNotMatch(page, /实际开始时间（北京时间）/);
  assert.match(styles, /\.product-actual-overlap-modal/);
  assert.match(styles, /\.actual-overlap-confirm/);
  assert.match(styles, /@media \(max-width: 560px\)[\s\S]*\.product-actual-overlap-modal > footer > button[\s\S]*min-height: 44px/);
});

test("long overview and modification lists are progressively disclosed without hiding routed targets", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(page, /const \[priorityExpanded, setPriorityExpanded\] = useState\(false\)/);
  assert.match(page, /const \[inventoryExpanded, setInventoryExpanded\] = useState\(false\)/);
  assert.match(page, /const \[modificationExpanded, setModificationExpanded\] = useState\(false\)/);
  assert.match(page, /priorityExpanded \? 5 : 3/);
  assert.match(page, /展开前 5 条优先策略/);
  assert.match(page, /inventoryLimitEnabled = !normalizedSearch && !focusedProductId && !inventoryExpanded/);
  assert.match(page, /products\.slice\(0, 8\)/);
  assert.match(page, /modificationSuggestions\.slice\(0, 6\)/);
  assert.match(page, /展开全部 \$\{products\.length\} 件商品/);
  assert.match(page, /展开全部 \$\{data\.modification_suggestions\.length\} 条建议/);
});

test("observation plan copy distinguishes a due checkpoint from one still waiting", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(page, /function observationPlanTitle\(batch: ProductTrafficBatchView\)/);
  assert.match(page, /if \(batch\.due_ready\)/);
  assert.match(page, /补录 \$\{formatTrafficDateTime\(batch\.started_at\)\} 批次 \$\{checkpoint\}/);
  assert.match(page, /继续观察，\$\{checkpoint\} 将于 \$\{formatTrafficDateTime\(batch\.due_at\)\} 到期/);
  assert.match(page, /selectedSlotTitle[\s\S]*observationPlanTitle\(activeObservationBatch\)/);
});

test("invalid baseline batches are terminal history and traffic time uses one Chinese formatter", async () => {
  const page = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");
  const app = await readFile(appPath, "utf8");
  const trafficDateTime = await readFile(trafficDateTimePath, "utf8");

  assert.match(page, /formatTrafficDateTime/);
  assert.match(page, /function formatPlanSlotDateTime/);
  assert.match(page, /formatPlanSlotDateTime\(activePlanSlot\.date, activePlanSlot\.scheduled_time\)/);
  assert.match(trafficDateTime, /hourCycle: "h23"/);
  assert.match(trafficDateTime, /月\$\{numericPart\(parts, "day"\)\}日/);
  assert.match(trafficDateTime, /分`/);
  assert.match(page, /batch\.status === "invalidated" \? "基线无效 · 仅保留投流事实"/);
  assert.match(page, /历史事实已保留，暂时没有可比较序列/);
  assert.match(page, /实测变化 · 探索性分析/);
  assert.match(page, /不是曝光贡献值/);
  assert.match(page, /不进入预算、时段、复投或商品优先级结论/);
  assert.match(page, /已终止批次无需继续补录/);
  assert.doesNotMatch(page, /补录 \+72h 数据后再看报告/);
  assert.match(page, /batch\.status !== "invalidated" \|\| batch\.exploratory_available/);
  assert.match(page, /batch\.status === "invalidated" \? "已终止"/);
  assert.match(service, /"invalidated"/);
  assert.match(service, /invalidation_reason/);
  assert.match(app, /batch\.status !== "invalidated"/);
  assert.match(app, /formatTrafficReminderTime\(batch\.due_at\)/);
  assert.match(app, /return formatTrafficDateTime\(value, "当前"\)/);
});

test("the hidden quick accounting drawer does not expose dialog semantics", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /role=\{open \? "dialog" : undefined\}/);
  assert.match(app, /aria-modal=\{open \? "true" : undefined\}/);
  assert.match(app, /aria-labelledby=\{open \? "drawer-title" : undefined\}/);
});
