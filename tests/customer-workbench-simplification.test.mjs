import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const productPagePath = new URL("../src/pages/ProductIntelligencePage.tsx", import.meta.url);
const productStylesPath = new URL("../src/pages/product-intelligence.css", import.meta.url);
const customerPagePath = new URL("../src/pages/BusinessAssistantPages.tsx", import.meta.url);
const messagePagePath = new URL("../src/pages/CustomerMessagesPage.tsx", import.meta.url);
const messageStylesPath = new URL("../src/pages/customer-messages.css", import.meta.url);
const configPath = new URL("../backend/app/config.py", import.meta.url);
const processorPath = new URL("../backend/app/services/processor.py", import.meta.url);

test("product modification evidence stays in launch and actions remain visible without horizontal scrolling", async () => {
  const page = await readFile(productPagePath, "utf8");
  const styles = await readFile(productStylesPath, "utf8");

  assert.match(page, /navigateWorkspace\("launch", "product", suggestion\.external_id\)/);
  assert.doesNotMatch(page, /navigateWorkspace\("overview", "product", suggestion\.external_id\)/);
  assert.match(page, /product-modification-\$\{suggestion\.external_id\}/);
  assert.match(page, /modification-evidence-detail/);
  assert.match(page, /商品与置信度/);
  assert.match(page, /const experimentBlocked = Boolean\(suggestion\.blocked_reason \|\| !suggestion\.variable\)/);
  assert.match(page, /className="modification-evidence-action"[\s\S]*<Eye size=\{14\} \/>查看证据/);
  assert.match(page, /className="modification-primary-action"[\s\S]*<Flask size=\{14\} \/>建立实验/);
  assert.match(page, /className="modification-primary-action" disabled=\{experimentBlocked\}/);
  assert.match(styles, /\.modification-table \{ min-width: 0; overflow: hidden; \}/);
  assert.match(styles, /grid-template-columns: minmax\(205px, \.95fr\) minmax\(260px, 1\.35fr\) minmax\(250px, 1\.08fr\) 104px/);
  assert.match(styles, /\.modification-table > article \{ min-height: 92px/);
  assert.match(styles, /\.modification-actions \{ display: grid; align-content: center; gap: 4px/);
  assert.match(styles, /\.modification-actions button \{ width: 100%; min-height: 32px/);
  assert.match(styles, /\.modification-actions \.modification-evidence-action/);
  assert.match(styles, /\.modification-actions \.modification-primary-action/);
  assert.doesNotMatch(styles, /\.modification-table-head,\s*\.modification-table > article\s*\{[^}]*min-width:\s*1040px/);
  assert.doesNotMatch(styles, /@media \(max-width: 1180px\)[\s\S]{0,1200}"product actions"/);
  assert.match(styles, /@media \(max-width: 980px\)[\s\S]*"product actions"[\s\S]*"advice advice"/);
  assert.match(styles, /@media \(max-width: 520px\)[\s\S]*\.modification-actions button \{ width: 100%; min-height: 44px/);
});

test("customer editing exposes only the three approved lifecycle choices while legacy values stay readable", async () => {
  const page = await readFile(customerPagePath, "utf8");

  assert.match(page, /\["contacted", "跟进中"\]/);
  assert.match(page, /\["won", "已成交"\]/);
  assert.match(page, /\["inactive", "已流失"\]/);
  assert.match(page, /new: "跟进中"/);
  assert.match(page, /proposal: "跟进中"/);
  assert.match(page, /原新线索、已联系、报价中统一归为跟进中/);
  assert.match(page, /customer\.followUpStatus === "inactive"[\s\S]*\? "contacted"[\s\S]*normalizeEditableFollowStatus/);
  assert.doesNotMatch(page, /const flow: CustomerFollowUpStatus\[\]/);
  assert.doesNotMatch(page, /business\.orderCount > 0 \|\| business\.totalSpend > 0/);
});

test("customer messages keep only conversation history while paused automation stays disabled", async () => {
  const page = await readFile(messagePagePath, "utf8");
  const styles = await readFile(messageStylesPath, "utf8");
  const config = await readFile(configPath, "utf8");
  const processor = await readFile(processorPath, "utf8");

  assert.match(page, /className="conversation-list"/);
  assert.match(page, /className="message-thread"/);
  assert.match(page, /消息只读/);
  assert.match(page, /mark_latest_pending: false/);
  assert.doesNotMatch(page, /WorkbenchTab|RequirementExportWorkbench|reply-inspector/);
  assert.doesNotMatch(page, /回复草稿|需求分析|报价转化|confirmRequirementCustomer|previewRequirementImport|analyzeSales/);
  assert.doesNotMatch(styles, /\.reply-inspector|\.requirements-panel|\.conversion-panel|\.sales-agent/);
  assert.match(config, /customer_reply_drafts_enabled: bool = False/);
  assert.match(config, /customer_quote_conversion_enabled: bool = False/);
  assert.match(processor, /if self\.reply_drafts_enabled:/);
  assert.match(processor, /if self\.sales_analysis_enabled and self\.sales_agent is not None:/);
  assert.match(processor, /if not self\.reply_drafts_enabled:[\s\S]*return None/);
});

test("customer messages uses a two-column desktop workspace and stacked mobile layout", async () => {
  const styles = await readFile(messageStylesPath, "utf8");

  assert.match(styles, /container-type: inline-size/);
  assert.match(styles, /container-name: customer-messages/);
  assert.match(styles, /grid-template-columns: minmax\(250px, \.72fr\) minmax\(0, 2\.3fr\)/);
  assert.match(styles, /@container customer-messages \(max-width: 759px\)[\s\S]*\.messages-workbench \{[\s\S]*max-height: none;[\s\S]*display: block;[\s\S]*overflow: hidden/);
  assert.match(styles, /@container customer-messages \(max-width: 759px\)[\s\S]*\.message-thread \{ height: 540px; min-height: 540px/);
  assert.doesNotMatch(styles, /reply-inspector|inspector-tabs|requirements-open/);
});
