import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/components/workspace/useLatestMessageScroll.ts', import.meta.url), 'utf8');
function setup() {
  const frames = new Map(), observers = [];
  let sequence = 0;
  class Observer { constructor(callback) { this.callback=callback; observers.push(this); } observe() {} disconnect() {} }
  const scope=vm.createContext({exports:{},require:()=>({}),ResizeObserver:Observer,MutationObserver:Observer,
    requestAnimationFrame:callback=>{frames.set(++sequence,callback);return sequence;},cancelAnimationFrame:id=>frames.delete(id)});
  vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,scope);
  const events=new Map();let top=0;
  const element={scrollHeight:2400,clientHeight:600,children:[{}],get scrollTop(){return top},set scrollTop(value){top=Math.max(0,Math.min(value,this.scrollHeight-this.clientHeight))},
    addEventListener(name,fn){events.set(name,fn)},removeEventListener(name){events.delete(name)}};
  const flush=()=>{for(const callback of [...frames.values()]){frames.clear();callback()}};
  return {element,events,observers,flush,follow:()=>scope.exports.followLatestMessage(element)};
}
test('first loaded conversation lands on the latest message',()=>{const s=setup();s.follow();assert.equal(s.element.scrollTop,1800)});
test('reselecting the same customer explicitly returns to bottom',()=>{const s=setup();const stop=s.follow();s.events.get('wheel')({deltaY:-100});s.element.scrollTop=0;stop();s.follow();assert.equal(s.element.scrollTop,1800)});
test('late image growth stays pinned before manual reading',()=>{const s=setup();s.follow();s.element.scrollHeight+=500;s.observers[0].callback();s.flush();assert.equal(s.element.scrollTop,2300)});
test('manual upward scroll prevents resize and new records from pulling the reader down',()=>{const s=setup();s.follow();s.events.get('wheel')({deltaY:-100});s.element.scrollTop=300;s.element.scrollHeight+=500;s.observers[0].callback();s.flush();assert.equal(s.element.scrollTop,300)});
test('history prepending can retain its anchor without competing auto scroll',()=>{const s=setup();s.follow();s.events.get('pointerdown')();s.element.scrollTop=0;s.element.scrollHeight+=400;s.element.scrollTop=400;s.observers[1].callback();s.flush();assert.equal(s.element.scrollTop,400)});
test('browser layout clamping is not mistaken for operator scrolling',()=>{const s=setup();s.follow();s.element.clientHeight=660;s.element.scrollTop=1740;s.observers[0].callback();s.flush();s.element.clientHeight=600;s.observers[0].callback();s.flush();assert.equal(s.element.scrollTop,1800)});
test('cleanup cancels stale work when changing customers',()=>{const s=setup();const stop=s.follow();s.element.scrollHeight=5000;s.observers[0].callback();stop();s.flush();assert.equal(s.element.scrollTop,1800);assert.equal(s.events.size,0)});
test('empty and short conversations are valid bottom positions',()=>{const s=setup();s.element.scrollHeight=100;s.follow();assert.equal(s.element.scrollTop,0)});
