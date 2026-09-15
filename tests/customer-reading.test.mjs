import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import * as Icons from '@phosphor-icons/react';
import {renderToStaticMarkup} from 'react-dom/server';
import postcss from 'postcss';

const require=createRequire(import.meta.url);
const root=path.resolve(import.meta.dirname,'..');
function load(relative){
  const file=path.resolve(root,relative);
  const source=ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const module={exports:{}};
  vm.runInNewContext(source,{exports:module.exports,module,require:name=>{
    if(name==='@phosphor-icons/react')return Icons;
    if(!name.startsWith('.'))return require(name);
    const base=path.resolve(path.dirname(file),name),target=['.tsx','.ts'].map(ext=>base+ext).find(existsSync);
    return load(target);
  },Intl,Date,console});
  return module.exports;
}
const {MessageTimelineEntry}=load('src/components/workspace/MessageTimelineEntry.tsx');
const {RequirementReadingView}=load('src/components/RequirementReadingView.tsx');
const {ImageViewport}=load('src/components/ImageViewport.tsx');
const render=(component,props)=>renderToStaticMarkup(React.createElement(component,props));
test('pure image renders without a text bubble and retains exact timestamp',()=>{
  const html=render(MessageTimelineEntry,{receivedAt:'2026-09-10T10:53:17Z',direction:'inbound',media:React.createElement('img',{src:'/synthetic.png'})});
  assert.doesNotMatch(html,/class="chat-message-bubble"/);
  assert.match(html,/chat-message-media/);assert.match(html,/18:53:17/);assert.match(html,/2026-09-10T10:53:17Z/);
});
test('mixed message keeps text before media and source provenance',()=>{
  const html=render(MessageTimelineEntry,{receivedAt:'2026-09-10T10:00:00Z',previousAt:'2026-09-10T09:59:00Z',direction:'inbound',children:'合成文字',media:React.createElement('span',null,'合成图片'),provenance:'原会话 #1'});
  assert.ok(html.indexOf('合成文字')<html.indexOf('合成图片'));assert.match(html,/原会话 #1/);assert.doesNotMatch(html,/message-time-divider/);
});
const node={id:'n1',title:'合成节点',description:'客户原始 <script> 只作文字',evidence_refs:['e1']};
const blueprint={objectives:[node],capabilities:[{...node,objective_ids:['n1'],priority:'must'}],stages:[{...node,implementation:'保留原逻辑',estimated_hours:2,task_key:'ui.reading',workspace_key:'frontend',dependency_ids:['prior'],deliverables:['修改页面','源码']}],acceptance_gates:[{...node,criteria:['原图完整','原图不变'],stage_ids:['n1']}],evidence_refs:[{id:'e1',archive_id:'image-1',conversation_id:1,quote:'合成证据'}],out_of_scope:['不改合同'],assumptions:[],open_questions:['确认范围'],risks:[{id:'r1',title:'格式风险',description:'合成说明',severity:'low',mitigation:'保留下载'}]};
test('vertical reading retains all four layers, task identifiers and delivery criteria',()=>{
  const html=render(RequirementReadingView,{blueprint});
  for(const value of ['项目目标','功能能力','实施阶段','交付验收','ui.reading','frontend','prior','原图完整','不改合同','确认范围','格式风险','合成证据','图片 #image-1'])assert.ok(html.includes(value),value);
  assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));
});
test('empty formal layers have explicit states and never imply accepted delivery',()=>{
  const html=render(RequirementReadingView,{blueprint:{...blueprint,objectives:[],capabilities:[],stages:[],acceptance_gates:[]}});
  assert.match(html,/当前版本尚未填写/);assert.match(html,/不表示客户已验收/);
});
test('shared image viewport exposes fit, zoom and keyboard scroll controls',()=>{
  const html=render(ImageViewport,{children:React.createElement('img',{src:'/synthetic.png'})});
  for(const value of ['适应窗口','100%','放大图片','缩小图片','tabindex="0"'])assert.ok(html.includes(value),value);
});
test('reading styles are valid and keep complete images and narrow dialogs',()=>{
  const css=readFileSync(path.join(root,'src/components/workspace/reading-workspace.css'),'utf8');
  assert.doesNotThrow(()=>postcss.parse(css));
  assert.match(css,/\.image-viewer-surface img\s*\{[^}]*object-fit:contain/);
  assert.match(css,/\.image-viewer-viewport\s*\{[^}]*overflow:auto/);
  assert.match(css,/@media\(max-width:700px\)/);assert.match(css,/prefers-reduced-motion/);
});
