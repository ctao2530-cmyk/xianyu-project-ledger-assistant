import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../src/pages/BusinessAssistantPages.tsx", import.meta.url);
const servicePath = new URL("../src/data/localPlatformService.ts", import.meta.url);
const drawerPath = new URL("../src/components/ProjectTaskDraftDrawer.tsx", import.meta.url);
const stylesPath = new URL("../src/components/project-task-draft-drawer.css", import.meta.url);

test("project requirement import remains preview-first and manually confirmed", async () => {
  const [page, service] = await Promise.all([readFile(pagePath, "utf8"), readFile(servicePath, "utf8")]);

  assert.match(page, /previewProjectRequirementImport/);
  assert.match(page, /commitProjectRequirementImport/);
  assert.match(page, /只校验并预览，不会创建任务或启动 Codex/);
  assert.match(service, /\/requirement-blueprints\/preview/);
  assert.match(service, /\/requirement-blueprints\/commit/);
});

test("task draft drawer exposes diff classifications and protected fields", async () => {
  const [drawer, styles] = await Promise.all([readFile(drawerPath, "utf8"), readFile(stylesPath, "utf8")]);

  for (const label of ["新增", "内容变化", "保持不变", "受保护", "冲突"]) {
    assert.match(drawer, new RegExp(label));
  }
  assert.match(drawer, /状态、实际工时与验收证据为受保护数据/);
  assert.match(drawer, /仅应用允许更新的字段/);
  assert.match(drawer, /若蓝图版本或项目 revision 变化，将自动拒绝写入/);
  assert.match(styles, /@media\(max-width:820px\)/);
  assert.match(styles, /align-items:flex-end/);
  assert.match(styles, /@media\(prefers-reduced-motion:reduce\)/);
});

test("confirmation carries revision token task keys and explicit human note", async () => {
  const [page, service] = await Promise.all([readFile(pagePath, "utf8"), readFile(servicePath, "utf8")]);

  assert.match(page, /expected_revision: taskDraftPreview\.project_revision/);
  assert.match(page, /preview_token: taskDraftPreview\.preview_token/);
  assert.match(page, /selected_task_keys: taskKeys/);
  assert.match(page, /验收来源 · 需求蓝图 V/);
  assert.match(page, /apply_allowed_updates_only: true/);
  assert.match(page, /人工确认按需求蓝图写入允许更新的任务字段/);
  assert.match(service, /\/task-drafts\/confirm/);
});
