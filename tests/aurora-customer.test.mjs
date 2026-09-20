import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require=createRequire(import.meta.url);
const {buildSync}=createRequire(require.resolve('vite/package.json'))('esbuild');
const built=buildSync({stdin:{contents:"export {clampCustomerListWidth,clampAuroraCustomerListWidth} from './src/components/workspace/CustomerListResize'; export {CustomerContextPanel} from './src/components/workspace/CustomerContextPanel';",resolveDir:fileURLToPath(new URL('..',import.meta.url))},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react/jsx-runtime','react-dom'],mainFields:['module','main'],logLevel:'silent'});
const scope=vm.createContext({module:{exports:{}},require});vm.runInContext(built.outputFiles[0].text,scope);
const {clampCustomerListWidth:legacy,clampAuroraCustomerListWidth:aurora,CustomerContextPanel}=scope.module.exports;
const flatten=n=>React.isValidElement(n)?[n,...React.Children.toArray(n.props.children).flatMap(flatten)]:[];
test('list widths bound corrupt preferences and reserve readable conversation space',()=>{
 for(const [input,available,expected] of [[NaN,1200,400],[Infinity,1200,400],[-10,1200,300],[900,1200,480],[480,900,420],[400,600,300]])assert.equal(aurora(input,available),expected);
 for(const [input,available,expected] of [[NaN,1000,280],[Infinity,1000,280],[-10,1000,260],[900,1000,360],[360,860,300]])assert.equal(legacy(input,available),expected);
});
test('customer context uses explicit supplied identity and exact project routes',()=>{
 let events=[];const props={aurora:true,customer:{id:'stable-a',name:'合成客户',source:'xianyu',tags:['合成标签'],currentNeed:'原需求摘要'},projects:[{id:'exact-project-a',name:'合成项目'}],pane:'conversation',onClose:()=>events.push('close'),onViewProjects:()=>events.push('projects'),onViewRequirements:()=>events.push('requirements')};
 const html=renderToStaticMarkup(React.createElement(CustomerContextPanel,props));assert.match(html,/原需求摘要/);assert.ok(html.includes(encodeURIComponent('项目管理/exact-project-a/overview')));assert.deepEqual(events,[]);
 flatten(CustomerContextPanel(props)).find(n=>n.type==='button'&&String(n.props.children).includes('查看需求')).props.onClick();assert.deepEqual(events,['requirements']);
});
test('unlinked context stays empty without inferring a customer or requirements',()=>{
 const html=renderToStaticMarkup(React.createElement(CustomerContextPanel,{aurora:true,projects:[],pane:'conversation',onClose(){},onViewProjects(){},onViewRequirements(){throw Error('must not call')}}));assert.match(html,/尚未关联客户档案/);assert.doesNotMatch(html,/查看需求与版本|aurora-customer-identity/);
});
test('closing the original 小策 dialog returns to a visible customer header opener',()=>{
 const source=readFileSync(new URL('../src/components/GlobalAgentLauncher.tsx',import.meta.url),'utf8');const ts=require('typescript');const code=ts.transpileModule(source.slice(source.indexOf('  const close = () =>'),source.indexOf('  const panelGeometry')),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
 let frame,focused=[];const opener={isConnected:true,getClientRects:()=>[{}],focus:()=>focused.push('customer')};const c=vm.createContext({homeEntry:false,homeOpenerRef:{current:opener},buttonRef:{current:{isConnected:true,getClientRects:()=>[],focus:()=>focused.push('hidden')}},setOpen(){},window:{requestAnimationFrame:fn=>frame=fn},document:{querySelector:()=>null}});vm.runInContext(code+'\nclose();',c);frame();assert.deepEqual(focused,['customer']);
});
