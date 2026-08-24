import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


const page = readFileSync(new URL("../src/pages/BusinessAssistantPages.tsx", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const component = readFileSync(new URL("../src/components/CodexSyncWorkbench.tsx", import.meta.url), "utf8");
const service = readFileSync(new URL("../src/data/localPlatformService.ts", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/components/codex-sync-workbench.css", import.meta.url), "utf8");


test("project detail exposes a separate restorable Codex sync tab", () => {
  assert.match(page, /\["codex", "Codex 同步", Code\]/);
  assert.match(page, /tab === "codex"[\s\S]*CodexSyncWorkbench projectId=\{project\.id\}/);
  assert.match(app, /"codex", "verification", "communication"/);
  assert.doesNotMatch(page, /\["immersive", "沉浸任务流", Stack\]/);
});

test("timeline reloads committed history instead of trusting WebSocket replay", () => {
  assert.match(component, /localPlatformService\.codexProjectSync\(projectId\)/);
  assert.match(component, /event\.type === "codex_event_committed"/);
  assert.match(component, /void refresh\(\)/);
  assert.match(service, /socket\.addEventListener\("close"/);
  assert.match(service, /window\.setTimeout\(connect, delay\)/);
});

test("workbench manages isolated runs and separates implemented from verified", () => {
  assert.match(component, /开始开发/);
  assert.match(component, /pauseCodexManagedRun/);
  assert.match(component, /cancelCodexManagedRun/);
  assert.match(component, /查看当前 Diff/);
  assert.match(component, /高风险操作审批/);
  assert.match(component, /单次批准/);
  assert.match(component, /Codex 已实现，等待验收/);
  assert.match(component, /implemented 与 verified 分离/);
  assert.match(component, /无 task_key 的事件不能修改任务/);
  assert.match(service, /workspace-write/);
  assert.match(service, /acknowledge_dirty_repository/);
});

test("layout has narrow-screen and reduced-motion fallbacks", () => {
  assert.match(css, /@media \(max-width: 680px\)/);
  assert.match(css, /grid-template-columns: 1fr/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
});
