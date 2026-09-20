import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('typescript');
const source=ts.transpileModule(readFileSync(new URL('../src/utils/pageTransition.ts',import.meta.url),'utf8').replace('import { flushSync } from "react-dom";','const flushSync = (fn: () => void) => fn();').replace('export function','function'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;
function setup(){let starts=0,updates=0,reduced=false;const document={body:{dataset:{xunyingVisual:'aurora'}},documentElement:{classList:{toggle(){}}},startViewTransition(fn){starts++;fn();return {ready:Promise.resolve(),updateCallbackDone:Promise.resolve(),finished:Promise.resolve(),skipTransition(){throw Error('already completed')}}}};const context=vm.createContext({document,window:{matchMedia:()=>({matches:reduced})}});vm.runInContext(source,context);return {document,run(){context.runPageTransition(()=>updates++);},count:()=>({starts,updates}),reduce(){reduced=true;}};}
test('Aurora transitions update once without capturing the live WebGL tree',()=>{const s=setup();for(let i=0;i<20;i++)s.run();assert.deepEqual(s.count(),{starts:0,updates:20});});
test('legacy native transition, reduced-motion and switch races retain updates',()=>{const s=setup();s.document.body.dataset.xunyingVisual='legacy';s.run();s.document.body.dataset.xunyingVisual='aurora';s.run();assert.deepEqual(s.count(),{starts:1,updates:2});s.document.body.dataset.xunyingVisual='legacy';s.reduce();s.run();assert.deepEqual(s.count(),{starts:1,updates:3});});
