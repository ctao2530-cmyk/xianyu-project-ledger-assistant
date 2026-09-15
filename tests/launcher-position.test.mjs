import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/components/GlobalAgentLauncher.tsx', import.meta.url), 'utf8');
const code = ts.transpileModule(source.slice(source.indexOf('interface Point'), source.indexOf('function overlaps')), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText;

function restore(saved, width = 390, height = 844) {
  const context = vm.createContext({
    window: { innerWidth: width, innerHeight: height, matchMedia: () => ({ matches: width <= 680 }) },
    localStorage: { getItem: () => JSON.stringify(saved) },
  });
  return JSON.parse(JSON.stringify(vm.runInContext(`${code}\nreadPosition()`, context)));
}

test('48px mobile launcher keeps its saved vertical position across repeated restores', () => {
  let saved = { x: 326, y: 692, viewportWidth: 390, viewportHeight: 844, size: 48 };
  for (let i = 0; i < 5; i++) {
    const next = restore(saved);
    assert.deepEqual(next, { x: 326, y: 692 });
    saved = { ...saved, ...next };
  }
});

test('legacy 58px mobile position retains its bottom gap when migrated to 48px', () => {
  assert.equal(restore({ x: 316, y: 692, viewportWidth: 390, viewportHeight: 844 }).y, 702);
});

test('desktop launcher retains 64px geometry and corrupt storage uses a bounded default', () => {
  assert.deepEqual(restore({ x: 1492, y: 767, viewportWidth: 1586, viewportHeight: 943, size: 64 }, 1586, 943), { x: 1492, y: 767 });
  assert.deepEqual(restore({ x: 'invalid' }), { x: 326, y: 702 });
});
