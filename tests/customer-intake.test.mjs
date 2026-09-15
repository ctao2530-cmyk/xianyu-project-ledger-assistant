import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


const dialogPath = new URL("../src/components/CustomerCreateDialog.tsx", import.meta.url);
const dialogStylesPath = new URL("../src/components/customer-create-dialog.css", import.meta.url);
const pagesPath = new URL("../src/pages/OtherPages.tsx", import.meta.url);
const customerPagePath = new URL("../src/pages/BusinessAssistantPages.tsx", import.meta.url);
const servicePath = new URL("../src/data/localPlatformService.ts", import.meta.url);
const backendServicePath = new URL("../backend/app/services/customer_intake.py", import.meta.url);
const migrationPath = new URL("../migrations/versions/20260820_0036_customer_intake.py", import.meta.url);


test("customer management uses the dedicated revision-protected intake dialog", async () => {
  const [dialog, pages, service] = await Promise.all([
    readFile(dialogPath, "utf8"),
    readFile(pagesPath, "utf8"),
    readFile(servicePath, "utf8"),
  ]);

  assert.match(pages, /import \{ CustomerCreateDialog \}/);
  assert.match(pages, /onCreateCustomer=\{\(\) => \{ setIntakeConversation\(undefined\); setCustomerCreateOpen\(true\); \}\}/);
  assert.match(pages, /<CustomerCreateDialog[\s\S]*onPersistedSnapshot\(next\)/);
  assert.doesNotMatch(pages, /if \(kind === "customer"\) next\.customers\.unshift/);
  assert.doesNotMatch(pages, /kind === "customer" && !amount\.trim/);
  assert.match(dialog, /从客户消息选择/);
  assert.match(dialog, /手动录入/);
  assert.match(dialog, /customerIntakeCandidates\(\)/);
  assert.match(dialog, /expected_revision: revision/);
  assert.match(dialog, /request_id: requestId\(\)/);
  assert.match(dialog, /conversation_id: mode === "conversation"/);
  assert.match(dialog, /已加入客户列表或关系冲突的会话自动隐藏/);
  assert.match(dialog, /存在同名客户，不会自动合并/);
  assert.match(service, /"\/api\/customers\/intake-candidates"/);
  assert.match(service, /createCustomer: \(payload: CustomerCreatePayload\)/);
});


test("customer intake preserves editable operating fields without inventing a customer", async () => {
  const [dialog, customerPage] = await Promise.all([
    readFile(dialogPath, "utf8"),
    readFile(customerPagePath, "utf8"),
  ]);

  for (const label of ["当前需求", "价格类型", "下一步行动", "补充备注"]) {
    assert.match(dialog, new RegExp(label));
    assert.match(customerPage, new RegExp(label));
  }
  assert.match(customerPage, /currentNeed: draft\.currentNeed\.trim\(\)/);
  assert.match(customerPage, /priceType: draft\.priceType/);
  assert.match(customerPage, /priceAmount/);
  assert.match(customerPage, /nextAction: draft\.nextAction\.trim\(\)/);
  assert.match(customerPage, /notes: draft\.notes\.trim\(\)/);
  assert.match(dialog, /确认后只创建客户资料，不创建报价、项目或任务/);
});


test("mobile customer intake keeps every eligible conversation selectable", async () => {
  const styles = await readFile(dialogStylesPath, "utf8");

  assert.match(styles, /@media\(max-width:680px\)[\s\S]*\.customer-create-candidate-list\{display:flex;[\s\S]*overflow-x:auto/);
  assert.doesNotMatch(styles, /customer-create-candidate-list>button:not\(\.active\)\{display:none\}/);
  assert.match(styles, /min-height:44px/);
  assert.match(styles, /@media\(prefers-reduced-motion:reduce\)/);
});


test("backend intake filters durable relationships and migration 0036 follows 0035", async () => {
  const [service, migration] = await Promise.all([
    readFile(backendServicePath, "utf8"),
    readFile(migrationPath, "utf8"),
  ]);

  assert.match(service, /linked_customer_ids\(session, conversation\)/);
  assert.match(service, /LedgerMutationRequest/);
  assert.match(service, /payload_hash/);
  assert.match(service, /if revision != expected_revision/);
  assert.match(service, /CustomerChannelIdentity/);
  assert.doesNotMatch(service, /customer_name.*==.*BusinessCustomer\.name/);
  assert.match(migration, /revision = "20260820_0036"/);
  assert.match(migration, /down_revision = "20260819_0035"/);
  assert.match(migration, /customer intake schema is partial/);
});
