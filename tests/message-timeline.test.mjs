import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import postcss from 'postcss';

const source=readFileSync(new URL('../src/components/workspace/messageTimeline.ts',import.meta.url),'utf8');
const scope=vm.createContext({exports:{},Intl,Date});
vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,scope);
const {showMessageTime:show,messageTime:format}=scope.exports;
test('first message gets a separator; messages within five minutes do not',()=>{
  assert.equal(show('2026-09-10T10:00:00Z'),true);
  assert.equal(show('2026-09-10T10:00:30Z','2026-09-10T10:00:00Z'),false);
  assert.equal(show('2026-09-10T10:05:00Z','2026-09-10T10:00:00Z'),false);
  assert.equal(show('2026-09-10T10:05:01Z','2026-09-10T10:00:00Z'),true);
});
test('Beijing midnight always starts a new section',()=>{
  assert.equal(show('2026-09-10T16:00:00Z','2026-09-10T15:59:30Z'),true);
  assert.match(format('2026-09-10T16:30:00Z'),/09\/11.*00:30/);
  assert.match(format('2026-09-10T10:53:00Z'),/18:53/);
  assert.equal(format('2026-09-10T10:53:00Z'),format('2026-09-10T18:53:00+08:00'));
});
test('exact per-message timestamps survive grouping and invalid values do not crash',()=>{
  assert.match(format('2026-09-10T10:00:31Z',true),/18:00:31/);
  assert.equal(format('invalid'),'时间未知');
  assert.equal(show('invalid','2026-09-10T10:00:00Z'),true);
  const entry=readFileSync(new URL('../src/components/workspace/MessageTimelineEntry.tsx',import.meta.url),'utf8');
  assert.match(entry,/data-message-time=\{receivedAt\}/);
  assert.match(entry,/className="sr-only" dateTime=\{receivedAt\}/);
});
test('prepending older messages recomputes time groups without losing records',()=>{
  const messages=['2026-09-10T09:59:00Z','2026-09-10T10:00:00Z','2026-09-10T10:01:00Z','2026-09-10T10:12:00Z'];
  assert.deepEqual(messages.map((m,i)=>show(m,messages[i-1])),[true,false,false,true]);
  assert.equal(messages.length,4);
});
test('official Appica imports are used and preflight does not escape the customer page',()=>{
  const master=readFileSync(new URL('../src/components/workspace/MasterList.tsx',import.meta.url),'utf8');
  assert.match(master,/@appica\/ui-react\/button/);assert.match(master,/@appica\/ui-react\/chip/);
  const css=postcss.parse(readFileSync(new URL('../src/vendor/appica-scoped.css',import.meta.url),'utf8'));
  css.walkAtRules('layer',rule=>assert.notEqual(rule.params,'base'));
  css.walkRules(rule=>{
    let p=rule.parent;while(p){if(p.type==='atrule'&&/keyframes$/.test(p.name))return;p=p.parent;}
    for(const selector of rule.selectors)assert.ok(selector.includes('.customer-focus'),selector);
  });
});
