import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import {recordsHistorySnapshot as snapshot} from './records-history-fixture.mjs';
const require=createRequire(import.meta.url);
const {buildSync}=createRequire(require.resolve('vite/package.json'))('esbuild');
const built=buildSync({stdin:{contents:"export * from './src/features/project-relations/model';",resolveDir:fileURLToPath(new URL('..',import.meta.url))},bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent'});
const scope=vm.createContext({module:{exports:{}},require});vm.runInContext(built.outputFiles[0].text,scope);
const {projectRelations}=scope.module.exports;
const formal={case_id:'case-one',project_id:'qa-project',customer_id:'qa-customer',version:3};
test('uses explicit identity only and never borrows another customer conversation',()=>{
 const s=structuredClone(snapshot);s.customers[0].channelIdentities=[{conversationId:999}];
 let rows=projectRelations(s,'qa-project',formal,'ready');
 assert.equal(rows.find(r=>r.id==='conversation').href,undefined);
 s.projects[0].conversationId=7;
 rows=projectRelations(s,'qa-project',formal,'ready');
 assert.equal(decodeURIComponent(rows.find(r=>r.id==='conversation').href),'#客户消息/conversation/7');
 assert.equal(decodeURIComponent(rows.find(r=>r.id==='customer').href),'#客户消息/customer/qa-customer?view=projects');
});
test('rejects foreign formal relationships and distinguishes unavailable from absent',()=>{
 assert.match(projectRelations(snapshot,'qa-project',formal,'ready')[2].detail,/V3/);
 for(const wrong of [{...formal,project_id:'other'},{...formal,customer_id:'other'}])assert.equal(projectRelations(snapshot,'qa-project',wrong,'ready')[2].missing,true);
 assert.equal(projectRelations(snapshot,'qa-project',null,'error')[2].missing,false);
 assert.match(projectRelations(snapshot,'qa-project',null,'error')[2].detail,/读取失败/);
 assert.match(projectRelations(snapshot,'qa-project',null,'loading')[2].detail,/正在核对/);
});
test('scopes task counts, retains unscheduled receivables, never changes ledger or implies acceptance',()=>{
 const s=structuredClone(snapshot);s.payments=[];s.tasks=[{projectId:'qa-project',status:'done'},{projectId:'other',status:'done'}];
 const before=JSON.stringify(s);const rows=projectRelations(s,'qa-project',null,'ready');
 assert.match(rows.find(r=>r.id==='tasks').detail,/1 \/ 1 已完成 · 不代表客户验收/);
 assert.match(rows.find(r=>r.id==='payments').detail,/待收 ¥10,000/);
 assert.equal(JSON.stringify(s),before);assert.equal(projectRelations(s,'missing',null,'ready').length,0);
});
