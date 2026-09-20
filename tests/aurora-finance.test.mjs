import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
const require=createRequire(import.meta.url),{buildSync}=createRequire(require.resolve('vite/package.json'))('esbuild');
const built=buildSync({stdin:{contents:"export {financeFixture} from './tests/aurora-finance-fixture';export {buildRecords} from './src/data/operatingRecords';export {summarizeCashflow,inLedgerPeriod} from './src/data/ledgerPeriod';export {getBusinessSummary} from './src/data/businessMetrics';export {buildReceivableAging,sumReceivables} from './src/features/receivables/model';",resolveDir:fileURLToPath(new URL('..',import.meta.url))},bundle:true,write:false,format:'cjs',platform:'node',logLevel:'silent'});
const scope=vm.createContext({module:{exports:{}},Date,Intl,structuredClone});vm.runInContext(built.outputFiles[0].text,scope);
const {financeFixture,buildRecords,summarizeCashflow,inLedgerPeriod,getBusinessSummary,buildReceivableAging,sumReceivables}=scope.module.exports;
test('finance fixture retains independent net-income and current-receivable definitions',()=>{
 const s=financeFixture(),before=JSON.stringify(s),rows=buildRecords(s);
 for(const [month,income,expenses] of [[null,645,60],['2026-09',340,30],['2026-08',205,20],['2025-12',100,10]]){
  const totals=summarizeCashflow(rows.filter(r=>inLedgerPeriod(r.occurredAt,month)));assert.equal(totals.income,income);assert.equal(totals.expenses,expenses);
 }
 assert.equal(getBusinessSummary(s).outstanding,9280);assert.equal(JSON.stringify(s),before);
});
test('refund-heavy and undated fixtures retain facts without inventing month assignments',()=>{
 assert.equal(summarizeCashflow(buildRecords(financeFixture('negative'))).income,-80);
 const rows=buildRecords(financeFixture('undated'));
 assert.equal(rows.filter(r=>!r.occurredAt&&r.type==='income').length,1);
 assert.ok(!rows.filter(r=>inLedgerPeriod(r.occurredAt,'2026-09')).some(r=>!r.occurredAt));
});
test('aging pagination fixture covers all six buckets and preserves current total',()=>{
 const s=financeFixture('aging'),rows=buildReceivableAging(s,new Date('2026-09-17T12:00:00+08:00'));
 assert.equal(new Set(rows.map(r=>r.bucket)).size,6);assert.ok(rows.length>10);assert.equal(sumReceivables(rows),4550);
 assert.equal(sumReceivables(rows),getBusinessSummary(s).outstanding);
 assert.ok(rows.some(r=>r.terminal));assert.ok(rows.some(r=>r.bucket==='review'));
});
