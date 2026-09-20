import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/components/workspace/AppShell.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('AppShell.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const functions = ast.statements.filter(node => ts.isFunctionDeclaration(node) && ['readPreference', 'currentMode'].includes(node.name?.text));
assert.equal(functions.length, 2);
const js = ts.transpileModule(functions.map(node => node.getText(ast)).join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText;
function mode(search = '', saved = null, unavailable = false) {
  const context = vm.createContext({ URLSearchParams, location: { search }, localStorage: {
    getItem(key) { assert.equal(key, 'xunying.visual-mode'); if (unavailable) throw Error('Storage unavailable'); return saved; },
  } });
  return vm.runInContext(`${js}\ncurrentMode()`, context);
}

test('real-service entry defaults to Aurora with missing, invalid or unavailable browser storage', () => {
  assert.equal(mode(), 'aurora');
  assert.equal(mode('?ui=unknown', 'unknown'), 'aurora');
  assert.equal(mode('', null, true), 'aurora');
});

test('explicit legacy rollback and saved preferences remain available without a database change', () => {
  assert.equal(mode('', 'legacy'), 'legacy');
  assert.equal(mode('', 'aurora'), 'aurora');
  assert.equal(mode('?ui=legacy', 'aurora'), 'legacy');
  assert.equal(mode('?ui=aurora', 'legacy'), 'aurora');
  assert.equal(mode('?ui=unknown', 'legacy'), 'legacy');
});
