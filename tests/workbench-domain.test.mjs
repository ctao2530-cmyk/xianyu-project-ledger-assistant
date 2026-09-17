import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import {recordsHistorySnapshot as snapshot} from './records-history-fixture.mjs';
const require=createRequire(import.meta.url);
const {buildSync}=createRequire(require.resolve('vite/package.json'))('esbuild');
const built=buildSync({stdin:{contents:"export * from './src/features/workbench/domain';export * from './src/shared/time/businessDate';",resolveDir:fileURLToPath(new URL('..',import.meta.url))},bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent'});
const scope=vm.createContext({module:{exports:{}},require});vm.runInContext(built.outputFiles[0].text,scope);
const {projectActions,sortActions,businessDate,daysToBusinessDate}=scope.module.exports;
test('Beijing boundaries and invalid dates are explicit',()=>{
 assert.equal(businessDate('2026-09-15T16:00:00Z'),'2026-09-16');
 assert.equal(businessDate('2026-02-30'),'unknown');
 assert.equal(daysToBusinessDate('2026-09-16',new Date('2026-09-15T16:00:00Z')),0);
});
test('overdue and upcoming delivery do not imply acceptance or remove receivables',()=>{
 const before=JSON.stringify(snapshot);const rows=projectActions(snapshot,new Date('2026-09-16T00:00:00Z'));
 assert.equal(rows.find(x=>x.id.startsWith('delivery')).category,'已逾期');
 assert.equal(rows.find(x=>x.id.startsWith('payment')).detail,'待回款 ¥9,280');
 const closed={...snapshot,settlementIssues:[...snapshot.settlementIssues,{projectId:'qa-project',type:'project_cancelled',refundAmount:0,receivableImpact:0}]};
 assert.equal(projectActions(closed).some(x=>x.id.startsWith('delivery')),false);
 assert.equal(projectActions(closed).some(x=>x.id.startsWith('payment')),true);
 assert.equal(JSON.stringify(snapshot),before);
});
test('recent updates never sort by delivery date; missing timestamps are last',()=>{
 const rows=[{id:'a',category:'临近交付',updatedAt:'2026-09-01',dueAt:'2099-01-01'},{id:'b',category:'客户消息',updatedAt:'2026-09-15'},{id:'c',category:'待回款'}];
 assert.equal(sortActions(rows,'recent').map(x=>x.id).join(','),'b,a,c');
 assert.equal(sortActions(rows,'due')[0].id,'a');
});
