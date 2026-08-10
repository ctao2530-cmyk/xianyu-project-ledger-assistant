import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const projectWorkspacePath = new URL("../src/pages/ProjectWorkspacePage.tsx", import.meta.url);
const immersiveFlowPath = new URL("../src/pages/ImmersiveTaskFlow.tsx", import.meta.url);
const cockpitStylesPath = new URL("../src/pages/business-assistant.css", import.meta.url);

test("project card click extracts once and automatically enters immersive detail", async () => {
  const source = await readFile(projectWorkspacePath, "utf8");

  assert.match(source, /const projectEntryTransitionMs = 220;/);
  assert.match(source, /selectProject\(projectId, "extract"\);[\s\S]*window\.setTimeout\([\s\S]*openProject\(projectId\)/);
  assert.match(source, /reducedMotion \? 0 : projectEntryTransitionMs/);
  assert.match(source, /onClick=\{\(event\) => \{[\s\S]*enterProjectFromCard\(project\.id\)/);
  assert.doesNotMatch(source, /className="project-glass-actions"/);
});

test("task cards and orbit arrows own their pointer interactions", async () => {
  const source = await readFile(immersiveFlowPath, "utf8");
  const styles = await readFile(cockpitStylesPath, "utf8");

  assert.match(source, /onTaskCardPointerDown/);
  assert.match(source, /data-task-id=\{task\.id\}[\s\S]*data-immersive-action[\s\S]*onPointerDown=\{onTaskCardPointerDown\}/);
  assert.match(source, /data-immersive-action onClick=\{\(\) => selectRelative\(-1\)\}/);
  assert.match(source, /data-immersive-action onClick=\{\(\) => selectRelative\(1\)\}/);
  assert.match(styles, /\.immersive-orbit-controls button \{[^}]*width: 46px;[^}]*height: 46px;/);
});

test("narrow task rails snap the selected card to the center", async () => {
  const source = await readFile(immersiveFlowPath, "utf8");
  const styles = await readFile(cockpitStylesPath, "utf8");

  assert.match(source, /const centeredLeft = selectedCard\.offsetLeft - \(orbit\.clientWidth - selectedCard\.offsetWidth\) \/ 2;/);
  assert.match(source, /orbit\.scrollTo\(\{ left: Math\.max\(0, centeredLeft\), behavior: reducedMotion \? "auto" : "smooth" \}\)/);
  assert.doesNotMatch(source, /selectedCard\.scrollIntoView/);
  assert.match(styles, /scroll-snap-type: x mandatory/);
  assert.match(styles, /scroll-snap-align: center/);
  assert.match(styles, /@media \(max-width: 560px\)[\s\S]*\.immersive-orbit-controls \{ display: flex; \}/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.immersive-task-card \{ transition: opacity 80ms linear/);
});
