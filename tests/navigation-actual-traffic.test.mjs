import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8") + readFileSync(new URL("../src/components/workspace/Sidebar.tsx", import.meta.url), "utf8");
const product = readFileSync(
  new URL("../src/pages/ProductIntelligencePage.tsx", import.meta.url),
  "utf8",
);
const localService = [
  new URL("../src/data/localPlatformService.ts", import.meta.url),
  new URL("../src/data/productIntelligenceClient.ts", import.meta.url),
].map((path) => readFileSync(path, "utf8")).join("\n");
const localServiceShell = readFileSync(
  new URL("../src/data/localPlatformService.ts", import.meta.url),
  "utf8",
);
const productClient = readFileSync(
  new URL("../src/data/productIntelligenceClient.ts", import.meta.url),
  "utf8",
);
const customer = readFileSync(
  new URL("../src/pages/CustomerMessagesPage.tsx", import.meta.url),
  "utf8",
);

test("商品保留左侧二级导航，客户内容收拢到当前客户页", () => {
  assert.match(app, /const secondaryNavItems/);
  assert.match(app, /route: "商品经营\/exposure"/);
  assert.match(customer, /className="customer-hub-tabs"/);
  assert.match(customer, /全部图片库/);
  assert.match(app, /aria-expanded=\{children \? expanded/);
  assert.match(app, /onSecondaryNavigate\(label, child\.route\)/);
  assert.doesNotMatch(product, /<nav className="product-workspace-tabs"/);
  assert.doesNotMatch(customer, /CustomerMessagesPrimaryTabs/);
});

test("深层 Hash 保持对应二级导航选中且不让父级根路由抢先匹配", () => {
  assert.match(app, /const exactChild = children\.find\(\(item\) => item\.route === route\)/);
  assert.match(app, /sort\(\(left, right\) => right\.route\.length - left\.route\.length\)/);
  assert.match(app, /route\.startsWith\(`\$\{item\.route\}\/`\)/);
});

test("新投流入口使用实际时间 48h 协议且不绑定计划", () => {
  assert.match(product, /记录刚完成的真实投流/);
  assert.match(product, /localPlatformService\.recordTrafficBatch/);
  assert.match(product, /plan_slot_id: null/);
  assert.match(product, /confirmed_already_purchased: true/);
  assert.match(product, /\+1h \/ \+6h \/ \+24h \/ \+48h/);
  assert.match(product, /batch\.checkpoint_sequence\.map/);
  assert.match(product, /exposureDeltaStagesForBatch/);
  assert.match(product, /checkpointShortLabels\[activeObservationBatch\.terminal_checkpoint\]/);
  assert.match(product, /batch\.is_legacy_protocol && <span>历史 72h 批次仅供查看<\/span>/);
  assert.match(product, /记录这组真实投流/);
  assert.match(product, />记录真实投流<\/button>/);
  assert.match(product, /legacyTrafficPlanningVisible: boolean = false/);
  assert.match(product, /实时采集整批 T0/);
  assert.match(product, /先保存真实投流与唯一批次费用/);
  assert.match(product, /失败则仅保留事实/);
  assert.doesNotMatch(localService, /createTrafficBatch/);
  assert.doesNotMatch(product, /尝试使用最近 30 分钟内已有的完整商品快照作为 T0/);
  assert.doesNotMatch(product, /<ReferenceArea x1="\+24h" x2="\+72h"/);
  assert.doesNotMatch(product, /开始批次后自动计入流量曝光支出/);
});

test("商品经营拆分保持工作台组合、统一 client 和公开 API 契约", () => {
  assert.match(product, /import \{ ExposureAnalytics \} from "\.\/ProductExposureWorkbench"/);
  assert.match(product, /import \{ MarketReferenceWorkbench \} from "\.\/ProductMarketWorkbench"/);
  assert.match(product, /import \{ ProductLaunchWorkbench \} from "\.\/ProductLaunchWorkbench"/);
  assert.match(product, /<ExposureAnalytics/);
  assert.match(product, /<MarketReferenceWorkbench/);
  assert.match(product, /<ProductLaunchWorkbench/);

  assert.match(localServiceShell, /import \{ productIntelligenceClient \} from "\.\/productIntelligenceClient"/);
  assert.match(localServiceShell, /\.\.\.productIntelligenceClient/);
  assert.match(productClient, /"\/api\/products\/intelligence"/);
  assert.match(productClient, /"\/api\/products\/traffic-batches\/recorded"/);
  assert.match(productClient, /"\/api\/products\/market-reference"/);
  assert.match(productClient, /"\/api\/products\/launch-plans"/);
  assert.doesNotMatch(localServiceShell, /createTrafficBatch/);
  assert.doesNotMatch(productClient, /createTrafficBatch/);
});
