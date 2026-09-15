import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import ts from 'typescript';

const source=await readFile(new URL('../src/components/workspace/customerListTime.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const scope=vm.createContext({exports:{},Intl,Date});
vm.runInContext(compiled,scope);
const format=scope.exports.customerListTime;

test('customer list distinguishes Beijing today, yesterday and older dates',()=>{
  const now=new Date('2026-09-10T08:00:00Z');
  assert.equal(format('2026-09-10T10:53:00Z',now),'18:53');
  assert.equal(format('2026-09-09T16:30:00Z',now),'00:30');
  assert.equal(format('2026-09-09T10:53:00Z',now),'昨天 18:53');
  assert.equal(format('2026-09-08T10:53:00Z',now),'09/08');
});
test('explicit offsets, year boundaries and invalid timestamps remain unambiguous',()=>{
  const now=new Date('2026-09-10T08:00:00Z');
  assert.equal(format('2026-09-10T18:53:00+08:00',now),'18:53');
  assert.equal(format('2025-09-10T10:53:00Z',now),'2025/09/10');
  assert.equal(format('2025-12-31T10:53:00Z',new Date('2026-01-01T08:00:00Z')),'昨天 18:53');
  assert.equal(format('invalid',now),'时间未知');
});
