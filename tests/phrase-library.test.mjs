import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


const pagePath = new URL("../src/pages/CustomerMessagesPage.tsx", import.meta.url);
const drawerPath = new URL("../src/components/PhraseLibraryDrawer.tsx", import.meta.url);
const stylesPath = new URL("../src/components/phrase-library-drawer.css", import.meta.url);
const servicePath = new URL("../src/data/localPlatformService.ts", import.meta.url);
const modelsPath = new URL("../backend/app/models.py", import.meta.url);
const apiPath = new URL("../backend/app/phrase_library_api.py", import.meta.url);
const clipboardPath = new URL("../src/utils/phraseClipboard.ts", import.meta.url);


test("customer conversation header opens the approved global phrase drawer", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(page, /import \{ PhraseLibraryDrawer \} from "\.\.\/components\/PhraseLibraryDrawer"/);
  assert.match(page, /className="phrase-library-trigger"/);
  assert.match(page, /aria-haspopup="dialog"/);
  assert.match(page, /aria-expanded=\{phraseLibraryOpen\}/);
  assert.match(page, /<PhraseLibraryDrawer open=\{phraseLibraryOpen\}/);
  assert.doesNotMatch(page, /话术库[\s\S]{0,120}onNavigate|route: "话术库"/);
});


test("the library is manual plain text with revision protected management", async () => {
  const drawer = await readFile(drawerPath, "utf8");
  const service = await readFile(servicePath, "utf8");
  const models = await readFile(modelsPath, "utf8");
  const api = await readFile(apiPath, "utf8");

  assert.match(drawer, /纯文本 · 不支持变量或自动发送/);
  assert.match(drawer, /createPhraseCategory/);
  assert.match(drawer, /createPhrase\(/);
  assert.match(drawer, /updatePhrase\(/);
  assert.match(drawer, /reorderPhrases\(/);
  assert.match(drawer, /setPhraseActivation\(/);
  assert.match(drawer, /expected_revision: library\.revision/);
  assert.match(drawer, /停用，原记录仍保留/);
  assert.match(service, /"\/api\/phrase-library"/);
  assert.match(service, /"\/api\/phrase-library\/categories"/);
  assert.match(service, /"\/api\/phrase-library\/phrases\/reorder"/);
  assert.match(models, /class PhraseLibraryMutationRequest/);
  assert.match(api, /phrase_library_router = APIRouter\(prefix="\/api\/phrase-library"/);
});


test("copy writes only to the browser clipboard and never sends or records usage", async () => {
  const drawer = await readFile(drawerPath, "utf8");
  const { copyPlainTextToClipboard } = await import(clipboardPath);
  const writes = [];
  const copied = await copyPlainTextToClipboard("第一行\n第二行", {
    writeText: async (content) => { writes.push(content); },
  });
  const rejected = await copyPlainTextToClipboard("不会写入", {
    writeText: async () => { throw new Error("permission denied"); },
  });
  const unavailable = await copyPlainTextToClipboard("不会写入", undefined);
  const copyFunction = drawer.slice(
    drawer.indexOf("const copyPhrase"),
    drawer.indexOf("if (!open) return null"),
  );

  assert.equal(copied, true);
  assert.deepEqual(writes, ["第一行\n第二行"]);
  assert.equal(rejected, false);
  assert.equal(unavailable, false);
  assert.match(copyFunction, /copyPlainTextToClipboard/);
  assert.match(copyFunction, /已复制，不会自动发送/);
  assert.match(copyFunction, /复制失败，请手动选择文本/);
  assert.doesNotMatch(copyFunction, /localPlatformService|fetch\(|XMLHttpRequest|send/);
  assert.doesNotMatch(drawer, /readText|clipboard history|使用次数|usage_count|小策|Codex|DeepSeek/);
});


test("drawer preserves focus, practical targets, mobile bottom sheet and reduced motion", async () => {
  const drawer = await readFile(drawerPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(drawer, /role="dialog" aria-modal="true"/);
  assert.match(drawer, /event\.key === "Escape"/);
  assert.match(drawer, /event\.key !== "Tab"/);
  assert.match(drawer, /triggerRef\.current\?\.focus\(\)/);
  assert.match(drawer, /className="phrase-library-backdrop"[\s\S]*onClick=\{onClose\}/);
  assert.match(styles, /\.phrase-library-drawer \{[\s\S]*width: min\(474px, 94vw\);[\s\S]*height: 100%/);
  assert.match(styles, /min-width: 44px;[\s\S]*min-height: 44px/);
  assert.match(styles, /@media \(max-width: 680px\)[\s\S]*\.phrase-library-drawer \{[\s\S]*inset: auto 0 0;[\s\S]*border-radius: 24px 24px 0 0/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation: none/);
});


test("production UI starts from factual empty categories and contains no sample phrases", async () => {
  const drawer = await readFile(drawerPath, "utf8");

  assert.match(drawer, /当前分类暂无话术/);
  assert.match(drawer, /不会自动生成内容，请由你手工添加真实话术/);
  assert.doesNotMatch(drawer, /感谢您的咨询|请描述一下您的需求|欢迎再次光临|示例话术/);
});
