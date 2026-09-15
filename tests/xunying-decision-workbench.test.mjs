import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const assistantPath = new URL("../src/pages/BusinessAssistantPages.tsx", import.meta.url);
const assistantStylesPath = new URL("../src/pages/business-assistant.css", import.meta.url);

test("循营 brand shell uses project-owned transparent assets and keeps the route compatible", async () => {
  const app = await readFile(appPath, "utf8") + await readFile(new URL("../src/components/workspace/Sidebar.tsx", import.meta.url), "utf8") + await readFile(new URL("../src/components/GlobalAgentLauncher.tsx", import.meta.url), "utf8");

  assert.match(app, /displayLabel: "小策 · 今日判断"/);
  assert.match(app, /\/assets\/xunying\/orbit-mark-reference\.png/);
  assert.match(app, /\/assets\/xunying\/xiaoce-avatar\.png/);
  assert.match(app, /<strong>循营<\/strong>/);
  assert.match(app, /<strong>循营<\/strong>/);
  assert.doesNotMatch(app, /duck-logo\.png|duck-laptop\.png/);
  await access(new URL("../public/assets/xunying/orbit-mark.png", import.meta.url));
  await access(new URL("../public/assets/xunying/orbit-mark-reference.png", import.meta.url));
  await access(new URL("../public/assets/xunying/xiaoce-avatar.png", import.meta.url));
});

test("today judgment is derived from the real ledger snapshot rather than sample business data", async () => {
  const source = await readFile(assistantPath, "utf8");
  const workbenchSource = source.slice(source.indexOf("export function buildXunyingDecision"));

  assert.match(workbenchSource, /export function buildXunyingDecision\(snapshot: LedgerSnapshot\)/);
  assert.match(workbenchSource, /snapshot\.projects\.length/);
  assert.match(workbenchSource, /snapshot\.payments\.filter/);
  assert.match(workbenchSource, /snapshot\.expenses\.length/);
  assert.match(workbenchSource, /summary\.actualHours/);
  assert.match(workbenchSource, /snapshot\.logs\.length \+ snapshot\.attachments\.length/);
  assert.match(workbenchSource, /暂无匹配知识引用/);
  assert.match(workbenchSource, /不会把缺失信息当作事实/);
  assert.doesNotMatch(workbenchSource, /VinCherish|1063554920903|匹配度 92%/);
});

test("evidence drawer supports dismissal, focus containment, challenge state, and focus return", async () => {
  const source = await readFile(assistantPath, "utf8");
  const styles = await readFile(assistantStylesPath, "utf8");

  assert.match(source, /role="dialog" aria-modal="true" aria-labelledby="xunying-evidence-title"/);
  assert.match(source, /if \(event\.key === "Escape"\)/);
  assert.match(source, /event\.key !== "Tab"/);
  assert.match(source, /evidenceTriggerRef\.current\?\.focus\(\)/);
  assert.match(source, /xunying-drawer-backdrop[\s\S]*onClick=\{closeEvidence\}/);
  assert.match(source, /aria-expanded=\{challengeOpen\}/);
  assert.match(styles, /\.xunying-evidence-drawer \{[\s\S]*width: min\(480px, 100vw\)/);
  assert.match(styles, /@media \(max-width: 720px\)[\s\S]*\.xunying-evidence-drawer \{[^}]*inset: auto 0 0/);
  assert.match(styles, /\.xunying-drawer-primary,[\s\S]*min-height: 48px/);
});

test("existing requirement, quote, and review workflows remain connected to real services", async () => {
  const source = await readFile(assistantPath, "utf8");

  assert.match(source, /const \[workflowExpanded, setWorkflowExpanded\] = useState\(false\)/);
  assert.match(source, /setWorkflowExpanded\(true\)/);
  assert.match(source, /aria-expanded=\{workflowExpanded && tool === key\}/);
  assert.match(source, /\{workflowExpanded && <main id="xunying-workflow-panel"/);
  assert.match(source, /"requirements", "需求分析"/);
  assert.match(source, /"quote", "规则报价"/);
  assert.match(source, /"review", "项目复盘"/);
  assert.match(source, /localPlatformService\.analyzeBusinessRequirement/);
  assert.match(source, /localPlatformService\.createBusinessQuote/);
  assert.match(source, /localPlatformService\.reviewBusinessProject/);
  assert.match(source, /所有真实写入和对外动作仍保留人工确认边界/);
});

test("mobile evidence workbench keeps practical navigation and reduced-motion behavior", async () => {
  const source = await readFile(assistantPath, "utf8");
  const styles = await readFile(assistantStylesPath, "utf8");

  assert.match(source, /className="xunying-mobile-nav"/);
  assert.match(source, /onNavigate\("客户消息"\)/);
  assert.match(source, /onNavigate\("项目管理"\)/);
  assert.match(source, /onNavigate\("设置中心"\)/);
  assert.match(styles, /@media \(max-width: 720px\)[\s\S]*\.xunying-mobile-nav \{/);
  assert.match(styles, /\.xunying-workbench \{[\s\S]*animation: xunying-workbench-enter 220ms ease both;/);
  assert.match(styles, /@keyframes xunying-workbench-enter \{ from \{ opacity: 0; \} to \{ opacity: 1; \} \}/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.xunying-evidence-drawer \{ animation: none; \}/);
});
