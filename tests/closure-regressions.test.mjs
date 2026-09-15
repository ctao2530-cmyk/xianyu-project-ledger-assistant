import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const appStylesPath = new URL("../src/styles.css", import.meta.url);
const projectPath = new URL("../src/pages/ProjectWorkspacePage.tsx", import.meta.url);
const productPath = new URL("../src/pages/ProductIntelligencePage.tsx", import.meta.url);
const productStylesPath = new URL("../src/pages/product-intelligence.css", import.meta.url);
const settingsPath = new URL("../src/pages/OtherPages.tsx", import.meta.url);
const settingsStylesPath = new URL("../src/pages/other-pages.css", import.meta.url);

test("closed mobile navigation leaves no hidden controls in the accessibility tree", async () => {
  const [app, styles] = await Promise.all([
    readFile(new URL("../src/components/workspace/Sidebar.tsx", import.meta.url), "utf8"),
    readFile(appStylesPath, "utf8"),
  ]);

  assert.match(app, /mobile && open && <button/);
  assert.match(app, /aria-hidden=\{mobile && !open \? true : undefined\}/);
  assert.match(app, /inert=\{mobile && !open \? true : undefined\}/);
  assert.match(app, /mobile && <button aria-label="关闭导航"/);
  assert.match(styles, /@media \(max-width: 560px\)[\s\S]*\.menu-button \{ width: 44px; height: 44px; \}/);
});

test("finished projects no longer masquerade as currently overdue", async () => {
  const project = await readFile(projectPath, "utf8");

  assert.match(project, /finished \? "交付日期未确认"/);
  assert.match(project, /!finished[\s\S]*item\.project\.status === "overdue"/);
  assert.match(project, /className=\{dueTone\}>\{dueStatus\}/);
});

test("product counts use explicit ownership and monitoring semantics", async () => {
  const [product, styles] = await Promise.all([
    readFile(productPath, "utf8"),
    readFile(productStylesPath, "utf8"),
  ]);

  assert.match(product, /label="已验证本人商品"/);
  assert.match(product, /个启用 · .*个历史停用 · .*个待确认 · .*个他人排除/);
  assert.match(styles, /@media \(max-width: 520px\)[\s\S]*\.product-metrics-grid \{ grid-template-columns: repeat\(2/);
  assert.match(styles, /\.product-metric:last-child \{ grid-column: 1 \/ -1; \}/);
});

test("AI settings stay within the approved boundary and wrap long local paths", async () => {
  const [settings, styles] = await Promise.all([
    readFile(settingsPath, "utf8"),
    readFile(settingsStylesPath, "utf8"),
  ]);

  assert.doesNotMatch(settings, /GPT 需求导入/);
  assert.match(settings, /deepseekConfigLabel/);
  assert.match(settings, /config_file\.split\("\/"\)/);
  assert.match(styles, /\.deepseek-path-list code \{[^}]*overflow-wrap: anywhere;[^}]*word-break: break-word;/);
  assert.match(styles, /\.deepseek-setup-actions \{[^}]*flex-wrap: wrap;/);
});
