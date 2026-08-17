import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const component = readFileSync(new URL("../src/components/CodexPlanWorkbench.tsx", import.meta.url), "utf8");
const service = readFileSync(new URL("../src/data/localPlatformService.ts", import.meta.url), "utf8");

test("Codex plan workbench keeps repository analysis and import behind explicit local controls", () => {
  assert.match(component, /仅分析确认需求（不读取仓库）/);
  assert.match(component, /验证并绑定/);
  assert.match(component, /我已检查任务、工时、交付物和验收点，确认导入/);
  assert.match(component, /confirmedIntent/);
  assert.match(component, /expected_requirement_version/);
  assert.match(component, /expected_revision/);
});

test("Codex plan APIs send the desktop-only header and synchronize by structured task data", () => {
  assert.match(service, /X-Yuda-Desktop/);
  assert.match(service, /CodexPlanDocument/);
  assert.match(service, /confirmCodexPlan/);
  assert.match(component, /稳定 task_key 用于更新同一任务，不按标题猜测/);
  assert.match(component, /不会覆盖已有任务的人工状态和实际工时/);
});
