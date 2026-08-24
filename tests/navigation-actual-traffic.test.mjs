import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const product = readFileSync(
  new URL("../src/pages/ProductIntelligencePage.tsx", import.meta.url),
  "utf8",
);
const customer = readFileSync(
  new URL("../src/pages/CustomerMessagesPage.tsx", import.meta.url),
  "utf8",
);

test("商品经营和客户消息使用左侧二级导航", () => {
  assert.match(app, /const secondaryNavItems/);
  assert.match(app, /route: "商品经营\/exposure"/);
  assert.match(app, /route: "客户消息\/images"/);
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
  assert.match(product, /legacyTrafficPlanningVisible: boolean = false/);
  assert.match(product, /实时采集整批 T0/);
  assert.match(product, /整批成功后才创建批次和费用/);
  assert.doesNotMatch(product, /尝试使用最近 30 分钟内已有的完整商品快照作为 T0/);
});
