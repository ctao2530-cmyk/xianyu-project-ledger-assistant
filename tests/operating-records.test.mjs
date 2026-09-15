import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const pagesPath = new URL("../src/pages/OtherPages.tsx", import.meta.url);
const recordsPath = new URL("../src/pages/OperatingRecordsPage.tsx", import.meta.url);
const changeOrderPath = new URL("../src/pages/ProjectChangeOrderModal.tsx", import.meta.url);
const stylesPath = new URL("../src/pages/operating-records.css", import.meta.url);

test("income and expense navigation converge on one operating-record workspace", async () => {
  const [app, pages] = await Promise.all([readFile(appPath, "utf8"), readFile(pagesPath, "utf8")]);

  assert.match(app, /\{ label: "经营记录", displayLabel: "收支", icon: Wallet \}/);
  assert.doesNotMatch(app, /\{ label: "收入记录"/);
  assert.doesNotMatch(app, /\{ label: "支出记录"/);
  assert.match(app, /page === "收入记录" \|\| page === "支出记录" \? "经营记录"/);
  assert.match(pages, /page === "经营记录" \|\| page === "收入记录" \|\| page === "支出记录"/);
  assert.match(pages, /<OperatingRecordsPage/);
});

test("operating records derive real cashflow and preserve the existing write paths", async () => {
  const source = await readFile(recordsPath, "utf8");

  assert.match(source, /getBusinessSummary\(snapshot\)/);
  assert.match(source, /snapshot\.payments\.forEach/);
  assert.match(source, /snapshot\.expenses\.forEach/);
  assert.match(source, /snapshot\.settlementIssues/);
  assert.match(source, /payment\.status === "refunded"/);
  assert.match(source, /type: "refund"/);
  assert.match(source, /onConfirmPayment\(record\.projectId!, record\.paymentId\)/);
  assert.match(source, /onRecordExpense/);
  assert.doesNotMatch(source, /projectName|customerName|contractTotal/);
});

test("the selected monthly-track design has a vertical mobile fallback and accessible controls", async () => {
  const [source, styles] = await Promise.all([readFile(recordsPath, "utf8"), readFile(stylesPath, "utf8")]);

  assert.match(source, /月收支轨道/);
  assert.match(source, /operating-mobile-ledger/);
  assert.match(source, /aria-label="记录时间范围"/);
  assert.match(source, /aria-label="记录类型"/);
  assert.match(source, /aria-label="关联项目"/);
  assert.match(source, /event\.key === "Escape"/);
  assert.match(styles, /@media \(max-width: 820px\)[\s\S]*\.operating-track-axis,[\s\S]*display: none/);
  assert.match(styles, /\.record-actions button \{[\s\S]*min-width: 36px;[\s\S]*min-height: 36px/);
  assert.match(styles, /@media \(max-width: 820px\)[\s\S]*\.record-actions button \{ min-width: 44px; min-height: 44px/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
});

test("change-order autofocus runs once and does not reclaim focus after user interaction", async () => {
  const source = await readFile(changeOrderPath, "utf8");

  assert.match(source, /requestAnimationFrame\(\(\) => \{/);
  assert.match(source, /dialog\?\.contains\(activeElement\)/);
  assert.match(source, /cancelAnimationFrame\(frame\);\s*\}, \[\]\);/);
  assert.doesNotMatch(source, /setTimeout\(\(\) => titleInput\.current\?\.focus/);
});
