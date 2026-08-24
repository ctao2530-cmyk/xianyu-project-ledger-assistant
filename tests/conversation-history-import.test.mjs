import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../src/pages/CustomerMessagesPage.tsx", import.meta.url);
const servicePath = new URL("../src/data/localPlatformService.ts", import.meta.url);
const stylesPath = new URL("../src/pages/customer-messages.css", import.meta.url);

test("customer messages exposes a compact history-import entrance and confirmed modal flow", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(page, /import \{ createPortal \} from "react-dom"/);
  assert.match(page, /return createPortal\(<div className="history-import-backdrop"[\s\S]*document\.body\);/);
  assert.match(page, /conversation-history-trigger/);
  assert.match(page, /导入闲鱼历史对话/);
  assert.match(page, /只读查询/);
  assert.match(page, /不发送 · 不标记已读 · 确认前不写入/);
  assert.match(page, /确认导入/);
  assert.match(page, /按平台消息 ID 去重/);
  assert.match(page, /确认后自动保存客户入站原图/);
  assert.match(page, /原图成功/);
  assert.match(page, /image_failed_count/);
});

test("history imports are permanently archival and cannot request hidden AI work", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(page, /该会话没有可归档的客户入站原图/);
  assert.match(page, /仅归档消息与原图/);
  assert.match(page, /不会触发 AI 分析或任何业务写入/);
  assert.match(page, /mark_latest_pending: false/);
  assert.doesNotMatch(page, /markLatestPending|待回复并生成草稿/);
});

test("local service keeps search, preview, and commit behind local desktop APIs", async () => {
  const service = await readFile(servicePath, "utf8");

  assert.match(service, /\/api\/conversations\/history-import\/search/);
  assert.match(service, /\/api\/conversations\/history-import\/preview/);
  assert.match(service, /\/api\/conversations\/history-import\/commit/);
  assert.match(service, /"X-Yuda-Desktop": "1"/);
  assert.match(service, /request_id: string/);
  assert.match(service, /preview_token: string/);
  assert.match(service, /item_warning: string \| null/);
  assert.match(service, /image_candidate_count: number/);
});

test("latest light-glass modal uses responsive single-column and reduced-motion fallbacks", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /\.history-import-dialog \{[\s\S]*border: 1px solid rgba\(126, 124, 149, \.23\)/);
  assert.match(styles, /backdrop-filter: blur\(26px\) saturate\(124%\)/);
  assert.match(styles, /\.history-import-results > button\.selected \{[\s\S]*#5b9cf6/);
  assert.match(styles, /@media \(max-width: 820px\)[\s\S]*\.history-import-grid \{[\s\S]*grid-template-columns: 1fr/);
  assert.match(styles, /@media \(max-width: 560px\)[\s\S]*\.history-import-footer button,[\s\S]*min-height: 46px/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.history-import-dialog/);
});

test("retired sales and draft timeout logic is absent from customer conversations", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.doesNotMatch(page, /legacyCodexFastTimeout|当前重试将使用 Codex 独立长时限/);
  assert.doesNotMatch(page, /analyzeSales|regenerateDrafts/);
});
