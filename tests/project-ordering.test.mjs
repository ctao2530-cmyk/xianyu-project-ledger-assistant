import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { build } = createRequire(require.resolve('vite'))('esbuild');
const output = await build({entryPoints:['src/data/projectOrdering.ts'],bundle:true,write:false,format:'cjs',platform:'node'});
const context=vm.createContext({module:{exports:{}},Date});
vm.runInContext(output.outputFiles[0].text,context);
const {compareProjectUpdates}=context.module.exports;
test('server timestamps determine order even when ids imply the opposite',()=>{
 const a={id:'z',updatedAt:'2026-01-01T00:00:00Z'},b={id:'a',updatedAt:'2026-02-01T00:00:00Z'};
 assert.deepEqual([a,b].sort(compareProjectUpdates).map(p=>p.id),['a','z']);
});
test('missing and invalid dates stay last with deterministic tie-breaking',()=>{
 const rows=[{id:'z'},{id:'c',updatedAt:'invalid'},{id:'b',updatedAt:'2026-01-01T00:00:00Z'},{id:'a',updatedAt:'2026-01-01T08:00:00+08:00'}];
 assert.deepEqual(rows.sort(compareProjectUpdates).map(p=>p.id),['a','b','c','z']);
});
