import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
const require=createRequire(import.meta.url);
const {buildSync}=createRequire(require.resolve('vite/package.json'))('esbuild');
const built=buildSync({entryPoints:[fileURLToPath(new URL('./aurora-product-fixture.ts',import.meta.url))],bundle:true,write:false,format:'cjs',platform:'node',logLevel:'silent'});
const context=vm.createContext({module:{exports:{}},structuredClone,Date});vm.runInContext(built.outputFiles[0].text,context);
const {productFixture}=context.module.exports;
test('S05 valid market and launch fixtures cover the missing S00 contract fields',()=>{
 for(const state of ['normal','empty','long','pending','paused','failed','sample']){
  const f=productFixture(state);assert.ok(Array.isArray(f.launch_recommendation.rationale));assert.ok(f.market_reference.stability.status);assert.ok(Array.isArray(f.market_reference.benchmark.common_title_terms));assert.ok(Array.isArray(f.exposure_analytics.checkpoints));
  for(const p of f.products)assert.equal(p.profit_total,p.revenue_total-p.project_expense_total-p.project_refund_total);
 }
});
test('synthetic exposure charts contain only recorded checkpoints and retain both protocols',()=>{
 for(const name of ['batch','legacy-batch']){
  const batch=productFixture(name).traffic_batches[0];assert.equal(batch.actual_cost,6);assert.equal(batch.products.reduce((sum,p)=>sum+p.browse_delta,0),batch.browse_delta);
  assert.equal(batch.checkpoint_sequence.at(-1),name==='batch'?'h48':'h72');
  assert.ok(batch.products.every(p=>p.checkpoints.length===3&&!p.checkpoints.some(c=>c.checkpoint===batch.terminal_checkpoint)));
  assert.equal(batch.checkpoint_metrics.at(-1).browse_delta,75);
 }
});
test('invalid baseline preserves the factual batch cost without decision eligibility',()=>{
 const b=productFixture('invalid-batch').traffic_batches[0];assert.equal(b.actual_cost,6);assert.equal(b.has_reliable_baseline,false);assert.equal(b.analysis_eligible,false);assert.equal(b.analysis_tier,'fact_only');
});
