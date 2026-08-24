import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/pages/BusinessAssistantPages.tsx", import.meta.url), "utf8");
const component = readFileSync(new URL("../src/components/CodexVerificationWorkbench.tsx", import.meta.url), "utf8");
const service = readFileSync(new URL("../src/data/localPlatformService.ts", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/components/codex-verification-workbench.css", import.meta.url), "utf8");

test("project detail uses verified delivery as the visible project progress", () => {
  assert.match(page, /const verifiedProgress = verificationView\?\.progress\.verified_delivery\.percent \?\? 0/);
  assert.match(page, /<small>已验证交付进度<\/small><b>\{verifiedProgress\}%<\/b>/);
  assert.match(page, /CodexVerificationWorkbench projectId=\{project\.id\}/);
  assert.match(page, /\["verification", "交付核验", ShieldCheck\]/);
  assert.match(page, /const persistTasks = \(nextTasks: ProjectTask\[\]\) => \{[\s\S]*tasks: nextTasks,[\s\S]*\};/);
  assert.doesNotMatch(page, /const persistTasks[\s\S]{0,800}projects: snapshot\.projects\.map/);
});

test("verification workbench keeps the three progress meanings separate", () => {
  assert.match(component, /label="Codex 执行进度"/);
  assert.match(component, /label="已实现进度"/);
  assert.match(component, /label="已验证交付进度"/);
  assert.match(component, /implemented 不等于 verified/);
  assert.match(component, /测试通过也不会替代人工验收/);
  assert.match(component, /历史手工进度/);
});

test("acceptance decisions and confirmed tests use revision guarded APIs", () => {
  assert.match(service, /\/api\/acceptance-points\/\$\{encodeURIComponent\(pointId\)\}\/decision/);
  assert.match(service, /\/api\/projects\/\$\{encodeURIComponent\(projectId\)\}\/tests\/run/);
  assert.match(component, /expected_revision: revision/);
  assert.match(component, /status === "waived" && waivedCounts/);
  assert.match(component, /confirmed: true/);
  assert.match(component, /只允许计划中的命令/);
  assert.match(component, /测试通过只进入 test_passed，不会自动 verified/);
});

test("workbench exposes audited time, Git and delivery checklist controls", () => {
  assert.match(component, /记录人工工时/);
  assert.match(component, /暂停与等待审批不计入 Codex 活跃工时/);
  assert.match(component, /关联 Commit/);
  assert.match(component, /实时交付清单/);
  assert.match(service, /\/time-entries/);
  assert.match(service, /\/git-links/);
});

test("empty state is factual and detail drawer adapts to narrow screens", () => {
  assert.match(component, /还没有可核验的 Acceptance Point/);
  assert.match(component, /不会根据旧任务标题猜测交付物或验收点/);
  assert.match(component, /role="dialog" aria-modal="true"/);
  assert.match(component, /createPortal/);
  assert.match(component, /document\.body/);
  assert.match(component, /event\.key === "Escape"/);
  assert.match(css, /\.codex-point-drawer \{[\s\S]*width: min\(500px, 94vw\)/);
  assert.match(css, /@media \(max-width: 680px\)[\s\S]*\.codex-point-drawer \{[^}]*border-radius: 22px 22px 0 0/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
});

test("historical projects use explicit manual acceptance scope without AI guessing", () => {
  assert.match(component, /人工建立验收清单/);
  assert.match(component, /请选择真实任务并填写稳定 key/);
  assert.match(component, /不会从任务标题、legacy 进度或聊天内容猜测验收标准/);
  assert.match(component, /manual_historical/);
  assert.match(component, /退役误建验收点（保留历史）/);
  assert.match(service, /\/manual-acceptance-points/);
  assert.match(service, /\/acceptance-points\/\$\{encodeURIComponent\(pointId\)\}\/retire/);
});

test("sample readiness requires human confirmations and exposes immutable freeze history", () => {
  assert.match(component, /人工验收清单 → 证据核验 → 工时确认 → 不可变结果冻结/);
  assert.match(component, /我确认验收范围完整/);
  assert.match(component, /我确认工时记录完整/);
  assert.match(component, /追加新冻结版本/);
  assert.match(component, /冻结历史/);
  assert.match(service, /\/outcome-freezes/);
  assert.match(service, /confirmed_scope_complete: true/);
  assert.match(service, /confirmed_time_complete: true/);
  assert.match(css, /\.codex-sample-steps/);
  assert.match(css, /min-height: 44px/);
});
