import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const projectWorkspacePath = new URL("../src/pages/ProjectWorkspacePage.tsx", import.meta.url);
const projectDetailPath = new URL("../src/pages/BusinessAssistantPages.tsx", import.meta.url);
const appPath = new URL("../src/App.tsx", import.meta.url);
const immersiveFlowPath = new URL("../src/pages/ImmersiveTaskFlow.tsx", import.meta.url);
const stylesPath = new URL("../src/pages/business-assistant.css", import.meta.url);
const productPagePath = new URL("../src/pages/ProductIntelligencePage.tsx", import.meta.url);
const productStylesPath = new URL("../src/pages/product-intelligence.css", import.meta.url);
const packagePath = new URL("../package.json", import.meta.url);

function projectDetailSection(source) {
  const start = source.indexOf("export function ProjectDetail");
  const end = source.indexOf("\nexport function ", start + 1);
  return source.slice(start, end === -1 ? source.length : end);
}

test("project management uses a direct list and the confirmed single-page detail", async () => {
  const [source, detailSource, app, styles, packageJson] = await Promise.all([
    readFile(projectWorkspacePath, "utf8"),
    readFile(projectDetailPath, "utf8"),
    readFile(appPath, "utf8"),
    readFile(stylesPath, "utf8"),
    readFile(packagePath, "utf8"),
  ]);
  const detail = projectDetailSection(detailSource);

  assert.match(source, /所有项目，一眼掌握/);
  assert.match(source, /className="project-hub-list"/);
  assert.match(source, /openProject = \(projectId: string\) => onProjectRouteChange\(\{ projectId, tab: "overview" \}/);
  assert.match(source, /editProject = \(projectId: string\) => onProjectRouteChange\(\{ projectId, tab: "edit" \}/);
  assert.doesNotMatch(source, /projectStackGeometry|project-stack-scene|onScenePointerMove|handleWheel/);
  assert.match(detail, /className="project-simple-grid"/);
  assert.match(detail, /<DetailWorkspace context=/);
  assert.match(detail, /需求与交付/);
  assert.match(detail, /project-simple-task-trace/);
  assert.match(detail, /需求 V\{task\.requirementVersionId/);
  assert.match(detail, /task_key · \{task\.taskKey\}/);
  assert.match(detail, /<TaskFacts task=\{task\}/);
  const facts = await readFile(new URL('../src/components/workspace/TaskFacts.tsx', import.meta.url), 'utf8');
  assert.match(facts, /task\.workspaceKey/);
  assert.match(facts, /未记录验收结果/);
  assert.match(detail, /依赖 · \{task\.dependencyTaskKeys/);
  assert.match(detail, /合同与回款/);
  assert.match(detail, /最近记录/);
  assert.doesNotMatch(detail, /title="客户与商品"|title="执行摘要"/);
  assert.match(detail, /onClick=\{onEdit\}[\s\S]*?编辑项目/);
  assert.doesNotMatch(detail, />管理关系<|>编辑基本信息</);
  assert.match(detail, /附件与异常/);
  assert.doesNotMatch(detail, /Codex 同步|交付核验|需求报价|已验证交付进度/);
  assert.match(app, /const projectDetailTabs: ProjectDetailTab\[\] = \["overview", "immersive", "edit"\]/);
  assert.match(app, /rawProjectTab as ProjectDetailTab\) \? rawProjectTab as ProjectDetailTab : "overview" as const/);
  assert.match(app, /const expectedProjectHash = projectSectionHash\(route\.projectRoute\)[\s\S]*window\.history\.replaceState\(window\.history\.state, "", expectedProjectHash\)/);
  assert.match(styles, /\.project-hub-list > header,\.project-hub-list > article/);
  assert.match(styles, /@media \(max-width:560px\)[\s\S]*grid-template-areas:"main badge"/);
  assert.doesNotMatch(packageJson, /codex-sync-workbench\.test|codex-verification-workbench\.test/);
});

test("project surfaces no longer request or display Codex verification state", async () => {
  const [source, detailSource] = await Promise.all([
    readFile(projectWorkspacePath, "utf8"),
    readFile(projectDetailPath, "utf8"),
  ]);
  const detail = projectDetailSection(detailSource);

  assert.doesNotMatch(source, /VERIFIED|projectVerification\(|CodexProjectVerificationView|VerifiedMeter/);
  assert.doesNotMatch(detail, /verified_delivery|verificationView|CodexSyncWorkbench|CodexVerificationWorkbench/);
  assert.match(detail, /const persistTasks = \(nextTasks: ProjectTask\[\]\) => onSnapshotChange\(\{ \.\.\.snapshot, tasks: nextTasks \}\)/);
});

test("project edit isolates basic fields from relation changes", async () => {
  const source = await readFile(projectWorkspacePath, "utf8");

  assert.match(source, /普通保存不会直接修改客户与商品关系/);
  assert.match(source, /projects: snapshot\.projects\.map\(\(item\) => item\.id === nextProject\.id \? nextProject : item\)/);
  assert.doesNotMatch(source, /onSave\([\s\S]{0,500}customerId:/);
  assert.match(source, /onChangeRelation\("customer"\)/);
  assert.match(source, /onChangeRelation\("product"\)/);
});

test("customer and owned-product relations preview before revision-safe commits", async () => {
  const [source, styles] = await Promise.all([
    readFile(projectWorkspacePath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(source, /product\.ownership_status === "owned"/);
  assert.match(source, /product\.monitoring_enabled/);
  assert.match(source, /mockLedgerService\.previewProjectProduct\(relationProject\.id, targetId\)/);
  assert.match(source, /mockLedgerService\.commitProjectProduct\(productPreview, crypto\.randomUUID\(\)\)/);
  assert.match(source, /mockLedgerService\.previewCustomerRelation\(relationProject\.id, relationProject\.customerId, targetId\)/);
  assert.match(source, /mockLedgerService\.rebindCustomerRelation\(customerPreview, crypto\.randomUUID\(\)\)/);
  assert.match(source, /role="dialog" aria-modal="true" aria-labelledby="project-relation-title"/);
  assert.match(source, /event\.key === "Escape"/);
  assert.match(source, /event\.key !== "Tab"/);
  assert.match(styles, /\.project-relation-dialog/);
  assert.match(styles, /@media \(max-width:560px\)[\s\S]*animation-name:project-relation-up/);
});

test("legacy immersive task cards retain accessible direct interaction", async () => {
  const [source, styles] = await Promise.all([
    readFile(immersiveFlowPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(source, /onTaskCardPointerDown/);
  assert.match(source, /data-task-id=\{task\.id\}[\s\S]*data-immersive-action[\s\S]*onPointerDown=\{onTaskCardPointerDown\}/);
  assert.match(source, /data-immersive-action onClick=\{\(\) => selectRelative\(-1\)\}/);
  assert.match(source, /data-immersive-action onClick=\{\(\) => selectRelative\(1\)\}/);
  assert.match(styles, /\.immersive-orbit-controls button \{[^}]*width: 46px;[^}]*height: 46px;/);
});

test("legacy immersive narrow task rails snap the selected card to the center", async () => {
  const [source, styles] = await Promise.all([
    readFile(immersiveFlowPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(source, /const centeredLeft = selectedCard\.offsetLeft - \(orbit\.clientWidth - selectedCard\.offsetWidth\) \/ 2;/);
  assert.match(source, /orbit\.scrollTo\(\{ left: Math\.max\(0, centeredLeft\), behavior: reducedMotion \? "auto" : "smooth" \}\)/);
  assert.doesNotMatch(source, /selectedCard\.scrollIntoView/);
  assert.match(styles, /scroll-snap-type: x mandatory/);
  assert.match(styles, /scroll-snap-align: center/);
});

test("product radar distinguishes realtime realized profit from immutable history", async () => {
  const [source, styles] = await Promise.all([
    readFile(productPagePath, "utf8"),
    readFile(productStylesPath, "utf8"),
  ]);

  assert.match(source, /product\.linked_projects\.length\} 个关联项目/);
  assert.match(source, /product\.profit_is_realtime \? "实时账本" : "快照口径"/);
  assert.match(source, /净确认到账[\s\S]*project_expense_total[\s\S]*project_refund_total[\s\S]*实际利润/);
  assert.match(source, /历史商品快照仍保留采集当时的数据，不追溯改写/);
  assert.match(source, /<ProductLinkedProjects projects=\{selected\.linked_projects\}/);
  const linked = await readFile(new URL('../src/components/workspace/ProductLinkedProjects.tsx', import.meta.url), 'utf8');
  assert.match(linked, /projects\.map/);
  assert.match(linked, /project\.net_confirmed_total/);
  assert.match(linked, /project\.profit_total/);
  assert.match(styles, /\.product-profit-detail \{[^}]*grid-template-columns/);
});
