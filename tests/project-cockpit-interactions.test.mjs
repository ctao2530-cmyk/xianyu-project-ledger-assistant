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

test("project management uses a direct list with explicit detail and edit routes", async () => {
  const [source, detail, app, styles] = await Promise.all([
    readFile(projectWorkspacePath, "utf8"),
    readFile(projectDetailPath, "utf8"),
    readFile(appPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(source, /所有项目，一眼掌握/);
  assert.match(source, /className="project-hub-list"/);
  assert.match(source, /openProject = \(projectId: string\) => onProjectRouteChange\(\{ projectId, tab: "overview" \}/);
  assert.match(source, /editProject = \(projectId: string\) => onProjectRouteChange\(\{ projectId, tab: "edit" \}/);
  assert.doesNotMatch(source, /projectStackGeometry|project-stack-scene|onScenePointerMove|handleWheel/);
  assert.match(detail, /\["overview", "总览", Gauge\]/);
  assert.doesNotMatch(detail, /\["immersive", "沉浸任务流", Stack\]/);
  assert.match(app, /rawProjectTab as ProjectDetailTab\) \? rawProjectTab as ProjectDetailTab : "overview" as const/);
  assert.match(styles, /\.project-hub-list > header,\.project-hub-list > article/);
  assert.match(styles, /@media \(max-width:560px\)[\s\S]*grid-template-areas:"main badge"/);
});

test("verified progress never falls back to legacy project progress", async () => {
  const [source, detail] = await Promise.all([
    readFile(projectWorkspacePath, "utf8"),
    readFile(projectDetailPath, "utf8"),
  ]);

  assert.match(source, /view\?\.progress\.verified_delivery\.percent \?\? 0/);
  assert.match(detail, /verificationView\?\.progress\.verified_delivery\.percent \?\? 0/);
  assert.doesNotMatch(detail, /verified_delivery\.percent \?\? project\.progress/);
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
  assert.match(source, /selected\.linked_projects\.map/);
  assert.match(styles, /\.product-profit-detail \{[^}]*grid-template-columns/);
});
