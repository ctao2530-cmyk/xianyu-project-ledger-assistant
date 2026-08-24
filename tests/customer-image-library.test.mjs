import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../src/pages/CustomerMessagesPage.tsx", import.meta.url);
const appPath = new URL("../src/App.tsx", import.meta.url);
const libraryPath = new URL("../src/components/CustomerImageLibrary.tsx", import.meta.url);
const stylesPath = new URL("../src/components/customer-image-library.css", import.meta.url);
const servicePath = new URL("../src/data/localPlatformService.ts", import.meta.url);
const backendPath = new URL("../backend/app/services/customer_images.py", import.meta.url);
const gitignorePath = new URL("../.gitignore", import.meta.url);

test("customer messages exposes a stable conversation and image-library route", async () => {
  const page = await readFile(pagePath, "utf8");
  const app = await readFile(appPath, "utf8");

  assert.match(page, /type CustomerMessagesPrimaryView = "conversations" \| "images"/);
  assert.match(page, /kind === "images" \? "images" : "conversations"/);
  assert.match(app, /\{ key: "conversations", label: "会话", route: "客户消息" \}/);
  assert.match(app, /\{ key: "images", label: "图片库", route: "客户消息\/images" \}/);
  assert.doesNotMatch(page, /CustomerMessagesPrimaryTabs/);
  assert.match(page, /客户消息\/conversation\/\$\{conversationId\}/);
  assert.match(page, /<CustomerImageLibrary onOpenConversation=/);
});

test("image library uses only real archive APIs and keeps recovery user-triggered", async () => {
  const library = await readFile(libraryPath, "utf8");
  const service = await readFile(servicePath, "utf8");

  assert.match(library, /localPlatformService\.customerImages/);
  assert.match(library, /历史图片自动恢复/);
  assert.match(library, /自动恢复 \$\{preview\.candidate_count\} 张/);
  assert.match(library, /不会读取无本地占位的其他会话，不发送消息、不调用 AI/);
  assert.match(library, /先恢复闲鱼连接/);
  assert.doesNotMatch(library, /选择原图|type="file"|uploadCustomerImageOriginal/);
  assert.match(library, /确认删除这张原图的本地副本/);
  assert.match(library, /当前浏览器无法直接预览，请下载原图查看/);
  assert.match(library, /正在串行检查/);
  assert.match(library, /conversation_history_imported/);
  assert.doesNotMatch(library, /聊天正文|message\.content|conversation\.messages/);
  assert.match(service, /\/api\/customer-images\/history-recover/);
  assert.doesNotMatch(service, /\/api\/customer-images\/messages\/\$\{messageId\}\/upload/);
  assert.match(service, /"X-Yuda-Desktop": "1"/);
});

test("image library preserves responsive two-column mobile layout and accessible dialogs", async () => {
  const library = await readFile(libraryPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(library, /role="dialog" aria-modal="true"/);
  assert.match(library, /event\.key === "Escape"/);
  assert.match(library, /event\.key !== "Tab"/);
  assert.match(styles, /@media \(max-width: 560px\)[\s\S]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(styles, /min-height: 44px/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
});

test("backend stores immutable originals outside the requirement attachment pipeline", async () => {
  const backend = await readFile(backendPath, "utf8");
  const gitignore = await readFile(gitignorePath, "utf8");

  assert.match(backend, /ROOT_RELATIVE = Path\("data\/customer-images"\)/);
  assert.match(backend, /TEMP_RELATIVE = Path\("data\/private\/customer-image-tmp"\)/);
  assert.match(backend, /os\.replace\(temporary, target\)/);
  assert.match(backend, /hashlib\.sha256/);
  assert.match(backend, /event\.direction != "inbound"/);
  assert.match(backend, /_history_recovery_lock = asyncio\.Lock\(\)/);
  assert.match(backend, /CustomerImageHistoryRecoveryRun/);
  assert.match(backend, /event\.platform_message_id in allowed_keys/);
  assert.match(backend, /except AdapterAccessVerificationError/);
  assert.match(backend, /"pending_count": len\(pending_messages\)/);
  assert.match(backend, /"capture_interrupted"/);
  assert.doesNotMatch(backend, /OCR|DeepSeek|Codex|GPT/);
  assert.match(gitignore, /^data\/customer-images\/$/m);
});
