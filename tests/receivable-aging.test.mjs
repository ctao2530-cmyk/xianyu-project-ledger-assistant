import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
const require=createRequire(import.meta.url);
const {buildSync}=createRequire(require.resolve('vite/package.json'))('esbuild');
const built=buildSync({stdin:{contents:"export * from './src/features/receivables/model';export {getProjectFinancials} from './src/data/businessMetrics';",resolveDir:fileURLToPath(new URL('..',import.meta.url))},bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent'});
const scope=vm.createContext({module:{exports:{}},require});vm.runInContext(built.outputFiles[0].text,scope);
const {buildReceivableAging:aging,sumReceivables,getProjectFinancials}=scope.module.exports;
const now=new Date('2026-09-15T16:00:00Z');
const empty=()=>({customers:[{id:'c',name:'Synthetic'}],projects:[{id:'p',customerId:'c',name:'Synthetic Project',totalAmount:1000,dueDate:'2000-01-01'}],payments:[],expenses:[],tasks:[],settlementIssues:[],changeOrders:[],attachments:[],logs:[],settings:{}});
const payment=(id,amount,dueAt,status='pending')=>({id,projectId:'p',customerId:'c',amount,dueAt,status,paidAt:'2026-09-01'});
test('Beijing due-date boundaries are independent of delivery dates and confirmation times',()=>{
 const s=empty();s.payments=[payment('today',100,'2026-09-15T16:00:00Z'),payment('yesterday',100,'2026-09-15T15:59:59Z'),payment('30',100,'2026-08-17'),payment('31',100,'2026-08-16'),payment('60',100,'2026-07-18'),payment('61',100,'2026-07-17'),payment('future',100,'2026-10-01')];
 const rows=aging(s,now);const bucket=id=>rows.find(r=>r.paymentId===id).bucket;
 assert.equal(bucket('today'),'future');assert.equal(bucket('yesterday'),'overdue30');assert.equal(bucket('30'),'overdue30');assert.equal(bucket('31'),'overdue60');assert.equal(bucket('60'),'overdue60');assert.equal(bucket('61'),'overdue61');assert.equal(bucket('future'),'future');assert.equal(sumReceivables(rows),1000);
 assert.equal(rows.find(r=>r.id==='unplanned-p').amount,300);
});
test('no schedule and invalid dates remain undated; no invented payment id',()=>{
 const s=empty();let rows=aging(s,now);assert.equal(rows.length,1);assert.equal(rows[0].bucket,'undated');assert.equal(rows[0].paymentId,undefined);assert.equal(rows[0].dueDate,undefined);
 s.payments=[payment('invalid',1000,'2026-02-30')];rows=aging(s,now);assert.equal(rows[0].bucket,'undated');assert.equal(rows[0].paymentId,'invalid');
});
test('oversubscribed or invalid plans preserve the balance once without guessed aging',()=>{
 for(const p of [payment('over',1001,'2020-01-01'),payment('negative',-10,'2020-01-01'),{...payment('wrong-customer',100,'2020-01-01'),customerId:'other'}]){
  const s=empty();s.payments=[p];const rows=aging(s,now);assert.equal(rows.length,1);assert.equal(rows[0].bucket,'review');assert.equal(rows[0].amount,1000);assert.equal(rows[0].paymentId,undefined);
 }
});
test('uses canonical refund and settlement balances, includes terminated projects, excludes personal',()=>{
 const s=empty();s.payments=[payment('receipt',200,'','confirmed'),payment('refund',100,'','refunded'),payment('later',400,'2026-10-01')];
 s.settlementIssues=[{projectId:'p',type:'project_cancelled',occurredAt:'2026-09-01',refundAmount:10,receivableImpact:100}];
 s.projects.push({id:'personal',projectKind:'personal',totalAmount:9999,customerId:'c'});
 const before=JSON.stringify(s);const rows=aging(s,now);assert.equal(sumReceivables(rows),getProjectFinancials(s).find(r=>r.project.id==='p').outstanding);assert.equal(sumReceivables(rows),600);assert.equal(rows.every(r=>r.terminal),true);assert.equal(rows.some(r=>r.projectId==='personal'),false);assert.equal(JSON.stringify(s),before);
});
test('cent arithmetic conserves totals and zero balances do not remain as collectible',()=>{
 const s=empty();s.projects[0].totalAmount=0.3;s.payments=[payment('a',0.1,'2026-10-01'),payment('b',0.2,'2026-10-01')];assert.equal(sumReceivables(aging(s,now)),0.3);assert.equal(aging(s,now).some(r=>r.bucket==='review'),false);
 s.payments.push(payment('paid',0.3,'','confirmed'));assert.equal(aging(s,now).length,0);
});
