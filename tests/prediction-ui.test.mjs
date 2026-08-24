import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const analysisPath = new URL("../src/pages/BusinessAnalysisPage.tsx", import.meta.url);
const projectPath = new URL("../src/pages/ProjectWorkspacePage.tsx", import.meta.url);
const customerPath = new URL("../src/pages/BusinessAssistantPages.tsx", import.meta.url);
const incomePath = new URL("../src/pages/IncomeRecordsPage.tsx", import.meta.url);
const settingsPath = new URL("../src/pages/OtherPages.tsx", import.meta.url);
const servicePath = new URL("../src/data/predictionService.ts", import.meta.url);
const summaryPath = new URL("../src/components/PredictionSummaryStrip.tsx", import.meta.url);
const globalStylesPath = new URL("../src/styles.css", import.meta.url);
const analysisStylesPath = new URL("../src/pages/business-analysis.css", import.meta.url);
const assistantStylesPath = new URL("../src/pages/business-assistant.css", import.meta.url);

test("prediction client separates read-only forecasts from explicit calibration writes", async () => {
  const source = await readFile(servicePath, "utf8");

  assert.match(source, /latest: \(\) => request<PredictionLatestView>\("\/api\/predictions"\)/);
  assert.match(source, /target: \(target: PredictionTarget\).*\/api\/predictions\/targets/);
  assert.match(source, /project: \(projectId: string\).*\/api\/predictions\/projects/);
  assert.match(source, /customer: \(customerId: string\).*\/api\/predictions\/customers/);
  assert.match(source, /calibration: \(\) => request<CalibrationSummaryView>\("\/api\/predictions\/calibration"\)/);
  assert.match(source, /runCalibration: \(requestId: string\)[\s\S]*method: "POST"/);
  assert.match(source, /projectCalibration: \(projectId: string\)/);
  assert.match(source, /decideCalibration:[\s\S]*expected_revision: number[\s\S]*action: "adopt" \| "reject"/);
});

test("future window workbench separates facts predictions and manual advice", async () => {
  const source = await readFile(analysisPath, "utf8");
  const styles = await readFile(analysisStylesPath, "utf8");

  assert.match(source, /未来窗口编排台/);
  assert.match(source, /未来 14 天经营跑道/);
  assert.match(source, /今天只做什么/);
  assert.match(source, /未来 30 天 · 现金流/);
  assert.match(source, /事实/);
  assert.match(source, /预测/);
  assert.match(source, /建议/);
  assert.match(source, /规则评分 ≠ 概率/);
  assert.match(source, /所有建议均为人工执行/);
  assert.match(source, /predictionService\.latest\(\)/);
  assert.match(source, /latestPredictions\?\.run\.results/);
  assert.match(styles, /\.prediction-window-shell/);
  assert.match(styles, /@media \(max-width: 720px\)/);
});

test("home customer and finance retain prediction summaries while the simplified project list stays direct", async () => {
  const [app, project, customer, income, summary] = await Promise.all([
    readFile(appPath, "utf8"),
    readFile(projectPath, "utf8"),
    readFile(customerPath, "utf8"),
    readFile(incomePath, "utf8"),
    readFile(summaryPath, "utf8"),
  ]);

  assert.match(app, /PredictionSummaryStrip context="home"/);
  assert.doesNotMatch(project, /PredictionSummaryStrip context="projects"/);
  assert.match(project, /所有项目，一眼掌握/);
  assert.match(project, /project-hub-list/);
  assert.match(customer, /PredictionSummaryStrip context="customers"/);
  assert.match(customer, /今日跟进优先级/);
  assert.match(customer, /规则评分不是成交概率/);
  assert.match(income, /PredictionSummaryStrip context="finance"/);
  assert.match(summary, /规则评分不是概率，预测不会自动执行经营动作/);
});

test("daily capacity setting feeds prediction baseline without auto execution", async () => {
  const source = await readFile(settingsPath, "utf8");

  assert.match(source, /title="每日可用工时"/);
  assert.match(source, /aria-label="每日可用工时"/);
  assert.match(source, /min="1" max="24"/);
  assert.match(source, /defaultDailyAvailableHours/);
  assert.match(source, /重新生成预测才形成新快照/);
});

test("prediction summaries are responsive accessible and reduced-motion safe", async () => {
  const styles = await readFile(globalStylesPath, "utf8");

  assert.match(styles, /\.prediction-summary-focus > button \{[\s\S]*min-height: 44px/);
  assert.match(styles, /@media \(max-width: 1100px\)[\s\S]*\.prediction-summary-items \{ grid-template-columns: repeat\(2/);
  assert.match(styles, /@media \(max-width: 640px\)[\s\S]*\.prediction-summary-items \{ grid-template-columns: 1fr/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.prediction-summary-strip\.is-loading/);
});

test("estimate calibration workbench keeps truthful sample thresholds and explicit persistence", async () => {
  const [source, styles] = await Promise.all([
    readFile(analysisPath, "utf8"),
    readFile(analysisStylesPath, "utf8"),
  ]);

  assert.match(source, /0–2 · 仅收集/);
  assert.match(source, /3–4 · 探索性展示/);
  assert.match(source, /5\+ · 可供人工采用/);
  assert.match(source, /还没有满足条件的真实结果样本/);
  assert.match(source, /样本不足，不计算 MAE/);
  assert.match(source, /implemented 不能替代验收/);
  assert.match(source, /predictionService\.calibration\(\)/);
  assert.match(source, /window\.confirm\("确认冻结当前估算校准快照/);
  assert.match(source, /predictionService\.runCalibration\(`/);
  assert.match(source, /打开页面和普通读取不会写入数据库/);
  assert.match(styles, /\.estimate-calibration-grid > aside > button \{[\s\S]*min-height: 44px/);
  assert.match(styles, /@media \(max-width: 640px\)[\s\S]*\.estimate-calibration-conditions \{ grid-template-columns: 1fr/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.estimate-calibration-shell\.is-loading/);
});

test("project quote tab separates original suggestion and adopted hours without mutating quotes", async () => {
  const [source, styles] = await Promise.all([
    readFile(customerPath, "utf8"),
    readFile(assistantStylesPath, "utf8"),
  ]);

  assert.match(source, /01 · 原始估算/);
  assert.match(source, /02 · 校准建议/);
  assert.match(source, /03 · 人工采用值/);
  assert.match(source, /原始估算和决策审计均保留/);
  assert.match(source, /<b>\{value\.formula\}<\/b>/);
  assert.match(source, /不修改交付日期/);
  assert.match(source, /predictionService\.projectCalibration\(projectId\)/);
  assert.match(source, /window\.confirm\(`确认\$\{verb\}/);
  assert.match(source, /expected_revision: estimateCalibration\.suggestion_revision/);
  assert.match(source, /request_id: `calibration-decision-ui:/);
  assert.match(source, /predictionService\.decideCalibration/);
  assert.match(source, /不会创建或修改 QuoteProposal、项目、任务、交付日期或客户消息/);
  assert.doesNotMatch(source, /decideEstimateCalibration[\s\S]{0,1800}onSnapshotChange/);
  assert.match(styles, /\.project-estimate-decision input \{[\s\S]*min-height: 44px/);
  assert.match(styles, /\.project-estimate-decision > button \{[\s\S]*min-height: 44px/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.project-estimate-calibration\.is-loading/);
});
