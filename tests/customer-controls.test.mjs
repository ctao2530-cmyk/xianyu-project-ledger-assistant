import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import ts from 'typescript';

const source=await readFile(new URL('../src/components/workspace/CustomerListResize.tsx',import.meta.url),'utf8');
const scope=vm.createContext({exports:{},require:()=>({})});
vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,scope);
const clamp=scope.exports.clampCustomerListWidth;
test('list cannot collapse or grow without bound',()=>{
  assert.equal(clamp(-500,1200),260);
  assert.equal(clamp(9999,1200),360);
  assert.equal(clamp(340,1200),340);
});
test('reserve the thread width on narrow desktop and handle corrupt preferences',()=>{
  assert.equal(clamp(440,750),260);
  assert.equal(clamp(NaN,1000),280);
  assert.equal(clamp(Infinity,1000),280);
});
