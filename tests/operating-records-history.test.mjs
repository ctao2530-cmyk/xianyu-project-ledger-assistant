import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { recordsHistorySnapshot as snapshot } from './records-history-fixture.mjs';

// Use Vite's existing compiler; do not add a dependency for this isolated test.
const require = createRequire(import.meta.url);
const { buildSync } = createRequire(require.resolve('vite/package.json'))('esbuild');

const built = buildSync({
  stdin: { contents: `export {OperatingRecordsPage} from './src/pages/OperatingRecordsPage'; export * from './src/pages/operatingRecordsPeriod';`, resolveDir: fileURLToPath(new URL('..', import.meta.url)) },
  bundle: true, write: false, platform: 'node', format: 'cjs', loader: { '.css': 'empty' },
  external: ['react', 'react-dom/server'], mainFields: ['module', 'main'], logLevel: 'silent',
});
const session = new Map();
class FixedDate extends Date { constructor(...args) { super(...(args.length ? args : ['2026-09-10T10:00:00Z'])); } }
const scope = vm.createContext({ module: { exports: {} }, require: createRequire(import.meta.url), Date: FixedDate, Intl,
  sessionStorage: { getItem: key => session.get(key) ?? null },
});
vm.runInContext(built.outputFiles[0].text, scope);
const { OperatingRecordsPage, ledgerDateKey, inLedgerPeriod, validLedgerMonth, restoreRecordsPeriod, summarizeCashflow } = scope.module.exports;
function render(values = {}, data = snapshot) {
  session.clear();
  for (const [key, value] of Object.entries(values)) session.set(`xunying:ui:records-${key}`, value);
  return renderToStaticMarkup(React.createElement(OperatingRecordsPage, { snapshot: data, globalSearch: '', onRecordExpense() {}, onConfirmPayment() {}, onCreatePaymentPlan() {}, onNavigateProject() {}, onEditExpense() {}, onDeleteExpense() {} }));
}
const summary = html => html.match(/<section class="operating-summary-strip"[\s\S]*?<\/section>/)[0];
const details = html => html.match(/<section class="operating-record-list"[\s\S]*?<aside class="reference-records-context"/)[0];

test('new session defaults to all history; explicitly chosen old filters remain compatible', () => {
  assert.equal(restoreRecordsPeriod(''), 'all');
  assert.equal(restoreRecordsPeriod('invalid'), 'all');
  assert.equal(restoreRecordsPeriod('month'), 'month');
  const html = render();
  assert.match(html, /aria-pressed="true">全部时间/);
  assert.match(details(html), /合成往年费用/);
  assert.match(details(html), /合成八月费用/);
  assert.match(summary(html), /¥645\.00/);
  assert.match(summary(html), /¥60\.00/);
});
test('monthly totals and details use the same Beijing range, not UTC calendar month', () => {
  const html = render({period: 'month'});
  assert.match(summary(html), /2026年9月经营摘要/);
  assert.match(summary(html), /¥340\.00/);
  assert.match(summary(html), /¥30\.00/);
  assert.doesNotMatch(details(html), /合成往年费用|合成八月费用/);
  assert.match(details(html), /00:00/);
});
test('previous month includes both refund paths without counting them as expenses', () => {
  const html = render({ period: 'history', month: '2026-08' });
  assert.match(summary(html), /¥205\.00/);
  assert.match(summary(html), /¥20\.00/);
  assert.match(details(html), /合成八月费用/);
  assert.doesNotMatch(details(html), /合成九月费用|合成往年费用/);
  assert.match(html, /2026年8月收支轨道/);
});
test('cross-year history and empty months are accessible without resetting data', () => {
  const old = render({ period: 'history', month: '2025-12' });
  assert.match(summary(old), /¥100\.00/);
  assert.match(details(old), /合成往年费用/);
  const empty = render({ period: 'history', month: '2024-01' });
  assert.match(summary(empty), /¥0\.00/);
  assert.match(empty, /当前筛选下没有经营记录/);
  assert.match(empty, /查看全部时间/);
});
test('outstanding remains current and unchanged across date filters; pending is not income', () => {
  for (const period of ['all', 'month', 'history']) {
    const html = summary(render({ period, month: '2025-12' }));
    assert.match(html, /当前待回款/);
    assert.match(html, /¥9,280\.00/);
  }
});
test('type, project and search still combine with the historical range', () => {
  const html = render({ period: 'history', month: '2026-08', type: 'expense', project: 'qa-project', search: '八月' });
  assert.match(details(html), /合成八月费用/);
  assert.doesNotMatch(details(html), /payment-income|合成九月费用|曾到账/);
  assert.match(summary(html), /¥205\.00/); // summary is the range, not the detail-only filters
  assert.match(html, /下方筛选仅影响明细/);
});
test('invalid saved month falls back safely; empty ledger and invalid dates do not crash', () => {
  assert.equal(validLedgerMonth('2026-13'), false);
  assert.equal(validLedgerMonth(''), false);
  assert.match(render({ period: 'history', month: 'corrupt' }), /2026年9月经营摘要/);
  assert.equal(ledgerDateKey('bad'), 'unknown');
  assert.equal(ledgerDateKey('2026-02-30'), 'unknown');
  assert.equal(inLedgerPeriod('bad', null), true);
  assert.equal(inLedgerPeriod('bad', '2026-09'), false);
  assert.match(render({}, {...snapshot, projects: [], payments: [], expenses: [], settlementIssues: []}), /当前筛选下没有经营记录/);
});
for (const zone of ['UTC', 'America/Los_Angeles', 'Asia/Shanghai']) {
  test(`Beijing month boundaries and date-only fields remain stable in ${zone}`, () => {
    const previous = process.env.TZ;
    try {
      process.env.TZ = zone;
      assert.equal(ledgerDateKey('2026-08-31T15:59:59Z'), '2026-08-31');
      assert.equal(ledgerDateKey('2026-08-31T16:00:00Z'), '2026-09-01');
      assert.equal(ledgerDateKey('2026-09-01T00:00:00+08:00'), '2026-09-01');
      assert.equal(ledgerDateKey('2025-12-31T16:00:00Z'), '2026-01-01');
      assert.equal(ledgerDateKey('2026-09-01'), '2026-09-01');
    } finally { if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous; }
  });
}
test('cashflow reducer does not mutate records and ignores pending receivables', () => {
  const rows = Object.freeze([Object.freeze({type: 'income', amount: 100}), Object.freeze({type: 'refund', amount: -25}), Object.freeze({type: 'expense', amount: -10}), Object.freeze({type: 'receivable', amount: 900})]);
  const result = summarizeCashflow(rows);
  assert.equal(result.income, 75); assert.equal(result.expenses, 10);
});
