import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const customerPagePath = new URL("../src/pages/CustomerMessagesPage.tsx", import.meta.url);
const blueprintPagePath = new URL("../src/pages/CustomerRequirementBlueprintPage.tsx", import.meta.url);
const productPagePath = new URL("../src/pages/ProductIntelligencePage.tsx", import.meta.url);
const servicePath = new URL("../src/data/localPlatformService.ts", import.meta.url);
const customerStylesPath = new URL("../src/pages/customer-messages.css", import.meta.url);
const productStylesPath = new URL("../src/pages/product-intelligence.css", import.meta.url);

test("customer conversations no longer expose the retired requirement workbench", async () => {
  const page = await readFile(customerPagePath, "utf8");

  assert.match(page, /消息只读/);
  assert.match(page, /CustomerImageLibrary/);
  assert.match(page, /HistoryImportDialog/);
  assert.doesNotMatch(page, /RequirementExportWorkbench|requirementCustomer|previewRequirementImport|commitRequirementImport/);
});

test("formal requirement empty state points to Xiaoce without promising automatic persistence", async () => {
  const page = await readFile(blueprintPagePath, "utf8");

  assert.match(page, /全局“小策”对话框/);
  assert.match(page, /聊天结果不会自动保存为正式需求案例/);
  assert.match(page, /小策中的新蓝图不会自动覆盖正式需求案例/);
});

test("product intake offers account discovery and mobile share parsing", async () => {
  const page = await readFile(productPagePath, "utf8");

  assert.match(page, /从我的在售商品选择/);
  assert.match(page, /粘贴手机分享内容/);
  assert.match(page, /discoverOwnedListings\(\)/);
  assert.match(page, /resolveProductReference\(registerReference\.trim\(\)\)/);
  assert.match(page, /commitProductRegistration/);
  assert.match(page, /preview\.items\.filter\(\(item\) => item\.can_register\)/);
  assert.match(page, /只有当前账号本人且仍在售的商品可以加入采集/);
  assert.match(page, /不会发布、修改、下架或购买曝光/);
});

test("product management shows only enabled owned listings in the workspace-centered modal", async () => {
  const page = await readFile(productPagePath, "utf8");
  const styles = await readFile(productStylesPath, "utf8");

  assert.match(page, /const managedProducts = data\.products\.filter\([\s\S]*product\.ownership_status === "owned" && product\.monitoring_enabled/);
  assert.match(page, /<b>我的商品<\/b>/);
  assert.match(page, /managedProducts\.map\(\(product\)/);
  assert.match(page, /移出采集/);
  assert.match(page, /全部移出采集/);
  assert.match(page, /确认全部移出/);
  assert.match(page, /历史快照、曝光记录和项目关系都会保留/);
  assert.match(page, /removeRegistrationMonitor\(item\.external_id\)/);
  assert.match(page, /将\$\{item\.title\}移出采集/);
  assert.match(page, /if \(event\.key === "Escape"\)[\s\S]*setManagementOpen\(false\)/);
  assert.match(page, /managementTriggerRef\.current\?\.focus\(\)/);
  assert.doesNotMatch(page, /managementTab|product-management-tabs/);
  assert.doesNotMatch(page, /\["pending", "待确认"\]|\["excluded", "已排除"\]/);
  assert.match(styles, /\.product-management-summary/);
  assert.match(styles, /@media \(min-width: 1321px\)[\s\S]*\.product-management-backdrop \{ padding-left: 292px; \}/);
  assert.match(styles, /@media \(min-width: 1101px\) and \(max-width: 1320px\)[\s\S]*\.product-management-backdrop \{ padding-left: 254px; \}/);
  assert.match(styles, /@media \(max-width: 520px\)[\s\S]*\.product-modal-backdrop \{ align-items: end; padding: 0; \}/);
  assert.match(styles, /@media \(max-width: 520px\)[\s\S]*\.product-management-actions button \{[^}]*min-height: 44px/);
  assert.match(styles, /@media \(max-width: 520px\)[\s\S]*body:has\(\.product-management-backdrop\) \.global-agent-root \{ visibility: hidden; pointer-events: none; \}/);
});

test("new intake APIs are local-only and support idempotent multi-select", async () => {
  const service = await readFile(servicePath, "utf8");
  const styles = await readFile(productStylesPath, "utf8");

  assert.match(service, /\/api\/products\/owned-listings\/discover/);
  assert.match(service, /\/api\/products\/references\/resolve/);
  assert.match(service, /\/api\/products\/register\/batch/);
  assert.match(service, /\/api\/products\/monitors\/disable-batch/);
  assert.doesNotMatch(service, /registerProduct:|\/api\/products\/register",/);
  assert.match(service, /"X-Yuda-Desktop": "1"/);
  assert.match(service, /external_ids: string\[\]/);
  assert.match(service, /monitoring_enabled: boolean/);
  assert.match(service, /can_register: boolean/);
  assert.match(service, /blocked_reason: string \| null/);
  assert.match(styles, /\.product-registration-tabs/);
  assert.match(styles, /@media \(max-width: 560px\)[\s\S]*\.product-registration-tabs \{ grid-template-columns: 1fr/);
});
