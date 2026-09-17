import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { recordsHistorySnapshot as snapshot } from "./records-history-fixture.mjs";

const require = createRequire(import.meta.url);
const { buildSync } = createRequire(require.resolve("vite/package.json"))("esbuild");
const built = buildSync({
  entryPoints: [fileURLToPath(new URL("../src/data/operatingRecords.ts", import.meta.url))],
  bundle: true, write: false, platform: "node", format: "cjs", logLevel: "silent",
});
const scope = vm.createContext({ module: { exports: {} }, require });
vm.runInContext(built.outputFiles[0].text, scope);
const { buildRecords } = scope.module.exports;

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

  const records = buildRecords(snapshot);
  assert.equal(records.filter(row => row.lane === "income").reduce((sum, row) => sum + row.amount, 0), 645);
  assert.equal(records.filter(row => row.type === "expense").reduce((sum, row) => sum + row.amount, 0), -60);
  assert.equal(records.find(row => row.id === "payment-refund-legacy-refund").amount, -50);
  assert.equal(records.find(row => row.id === "settlement-refund-issue-refund").amount, -25);
  assert.equal(records.some(row => row.type === "income" && row.paymentId === "pending"), false);
  assert.equal(records.find(row => row.type === "receivable").amount, 9280);
  const withoutPlan = buildRecords({ ...snapshot, payments: snapshot.payments.filter(row => row.status !== "pending") });
  assert.equal(withoutPlan.find(row => row.type === "receivable").amount, 9280);
  assert.equal(withoutPlan.find(row => row.type === "receivable").paymentId, undefined);
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
