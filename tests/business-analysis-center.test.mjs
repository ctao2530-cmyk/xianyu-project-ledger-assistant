import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const pagePath = new URL("../src/pages/BusinessAnalysisPage.tsx", import.meta.url);
const servicePath = new URL("../src/data/businessAnalysisService.ts", import.meta.url);
const stylesPath = new URL("../src/pages/business-analysis.css", import.meta.url);

test("AI经营分析中心 remains after data statistics without a standalone goal route", async () => {
  const app = await readFile(appPath, "utf8");
  const statisticsIndex = app.indexOf('{ label: "数据统计", icon: ChartBar }');
  const analysisIndex = app.indexOf('{ label: "经营分析中心", icon: ChartLineUp }');

  assert.ok(statisticsIndex >= 0);
  assert.ok(analysisIndex > statisticsIndex);
  assert.doesNotMatch(app, /\{ label: "目标计划", icon: Target \}/);
  assert.match(app, /经营分析中心: \{ title: "AI经营分析中心"/);
});

test("analysis client uses explicit read, run, history, and lifecycle feedback APIs", async () => {
  const source = await readFile(servicePath, "utf8");

  assert.match(source, /latest: \(\) => request<BusinessAnalysisOverview>\("\/api\/business-analysis"\)/);
  assert.match(source, /overview: \(\) => request<BusinessAnalysisOverview>\("\/api\/business-analysis\/overview"\)/);
  assert.match(source, /"\/api\/business-analysis\/runs"[\s\S]*method: "POST"/);
  assert.match(source, /\/api\/business-analysis\/history\?limit=/);
  assert.match(source, /\/api\/business-analysis\/recommendations\/\$\{encodeURIComponent\(recommendationId\)\}/);
  assert.match(source, /expected_version: number/);
  assert.match(source, /request_id: string/);
  assert.match(source, /method: "PATCH"/);
  assert.match(source, /recommendations: \(\) => request<BusinessAnalysisRecommendationQueueResponse>/);
  assert.match(source, /\/recommendations\/\$\{encodeURIComponent\(recommendationId\)\}\/start/);
  assert.match(source, /\/recommendations\/\$\{encodeURIComponent\(recommendationId\)\}\/complete/);
  assert.match(source, /RecommendationUpdateStatus = "pending" \| "accepted" \| "ignored"/);
  assert.match(source, /RecommendationOutcome = "positive" \| "negative" \| "inconclusive"/);
});

test("evidence chain keeps metrics, findings, and manual recommendations connected", async () => {
  const source = await readFile(pagePath, "utf8");

  assert.match(source, /业务指标 → AI发现 → 行动建议/);
  assert.match(source, /evidenceSummary\(analysis, recommendation\)/);
  assert.match(source, /insightForRecommendation\(recommendation, analysis\.insights\)/);
  assert.match(source, /recommendation\.data_source\.join/);
  assert.match(source, /recommendation\.evidence_refs\.map/);
  assert.match(source, /confidenceValues\[recommendation\.confidence\]/);
  assert.match(source, /observePeriodLabel\(recommendation\.observe_period\)/);
  assert.match(source, /采纳/);
  assert.match(source, /忽略/);
  assert.match(source, /查看依据/);
  assert.match(source, /不会自动修改商品、发布内容、发送客户消息、变更项目或购买推广/);
  assert.doesNotMatch(source, /李老板|王同学|校园二手交易平台/);
});

test("page exposes loading, empty, selected-model fallback, API error, stale, and history states", async () => {
  const source = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");

  assert.match(source, /正在建立经营事实基线/);
  assert.match(source, /暂时无法读取经营分析/);
  assert.match(source, /当前没有无依据的建议/);
  assert.match(source, /所选模型未完成推理，规则结果已保留/);
  assert.match(source, /没有切换其他模型/);
  assert.match(source, /经营事实已经变化/);
  assert.match(source, /历史分析记录/);
  assert.match(source, /还没有历史分析/);
  assert.match(source, /businessAnalysisService\.historyDetail/);
  assert.match(source, /historyPeriodLabel\(item\.snapshot_time\)/);
  assert.match(source, /item\.insight_count/);
  assert.match(service, /insight_count: number/);
});

test("execution queue separates acceptance, observation, due review, and completed outcome", async () => {
  const source = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");

  assert.match(source, /执行与复盘/);
  assert.match(source, /已采纳 · 未开始/);
  assert.match(source, /观察中/);
  assert.match(source, /待复盘 · 已到期/);
  assert.match(source, /开始观察/);
  assert.match(source, /保存结果复盘/);
  assert.match(source, /分析已过期/);
  assert.match(source, /recommendation\.can_accept/);
  assert.match(source, /businessAnalysisService\.startRecommendation/);
  assert.match(source, /businessAnalysisService\.completeRecommendation/);
  assert.match(source, /baseline_metrics/);
  assert.match(source, /result_metrics/);
  assert.match(source, /product_modification_experiment/);
  assert.match(service, /lifecycle_status: RecommendationLifecycleStatus/);
  assert.match(service, /source_snapshot_hash: string/);
});

test("result review uses a desktop side drawer and a narrow-screen bottom sheet", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /\.analysis-review-backdrop \{ place-items: stretch end/);
  assert.match(styles, /\.analysis-review-drawer \{[\s\S]*height: 100%/);
  assert.match(styles, /@media \(max-width: 620px\)[\s\S]*\.analysis-review-backdrop \{[\s\S]*place-items: end stretch/);
  assert.match(styles, /@media \(max-width: 620px\)[\s\S]*\.analysis-review-drawer \{[\s\S]*border-radius: 22px 22px 0 0/);
  assert.match(styles, /\.analysis-review-metric-row/);
  assert.match(styles, /\.analysis-outcome-options/);
});

test("model selection defaults to GPT and records the explicit provider and model", async () => {
  const source = await readFile(pagePath, "utf8");
  const service = await readFile(servicePath, "utf8");

  assert.match(source, /useState<BusinessAnalysisProvider>\("codex_cli"\)/);
  assert.match(source, /GPT 深度分析/);
  assert.match(source, /DeepSeek 快速/);
  assert.match(source, /经营分析具体模型/);
  assert.match(source, /实际 provider 与 model 会写入历史/);
  assert.match(service, /provider: selection\.provider/);
  assert.match(service, /model: selection\.model/);
});

test("confirmed evidence-chain layout is responsive and keeps practical touch targets", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /\.analysis-chain-row \{[\s\S]*grid-template-columns: minmax\(0, 1fr\) 28px minmax\(0, \.95fr\) 28px minmax\(0, 1\.08fr\)/);
  assert.match(styles, /@media \(max-width: 980px\)[\s\S]*\.analysis-chain-row \{[\s\S]*grid-template-columns: 1fr/);
  assert.match(styles, /@media \(max-width: 620px\)[\s\S]*\.analysis-action-primary,[\s\S]*min-height: 44px/);
  assert.match(styles, /@media \(max-width: 620px\)[\s\S]*\.analysis-model-field select \{ min-height: 44px; \}/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.analysis-spin/);
});
