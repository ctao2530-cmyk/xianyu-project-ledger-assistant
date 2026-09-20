import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url);
const {buildSync}=createRequire(require.resolve('vite/package.json'))('esbuild');
const built=buildSync({stdin:{contents:"export {AuroraProjectSummary} from './src/components/workspace/AuroraProjectSummary';",resolveDir:fileURLToPath(new URL('..',import.meta.url))},bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime','react-dom'],mainFields:['module','main'],logLevel:'silent'});
const context=vm.createContext({module:{exports:{}},require,Intl,Date,URL,URLSearchParams,window:{matchMedia:()=>({matches:true})},fetch:()=>{throw Error('render must not send or write')}});vm.runInContext(built.outputFiles[0].text,context);
const {AuroraProjectSummary}=context.module.exports;
const project={id:'project / 精确',name:'真实传入项目',customerId:'customer',totalAmount:6000,status:'delivered',dueDate:'2026-09-20'};
function render({personal=false,terminal=false,income=2100,outstanding=3900}={}){
 const p={...project,...(personal?{projectKind:'personal'}:{})};
 return renderToStaticMarkup(React.createElement(AuroraProjectSummary,{item:{project:p,income,outstanding,settlementIssues:terminal?[{type:'project_cancelled',occurredAt:'2026-09-17'}]:[]},snapshot:{customers:[{id:'customer',name:'独立客户'}],tasks:[{id:'task',projectId:p.id,title:'已完成任务',status:'done'}],attachments:[]},open:false,onClose(){},onOpen(){},onEdit(){},onPayment(){},onChangeOrder(){}}));
}
test('summary keeps supplied financial facts and exact routes without equating delivery or tasks with acceptance',()=>{
 const html=render();for(const text of ['真实传入项目','独立客户','¥6,000','¥2,100','¥3,900','已交付','1 / 1','任务完成、项目交付、客户验收和确认收款分别记录'])assert.ok(html.includes(text),text);
 assert.doesNotMatch(html,/客户验收通过|100%|8,200|林墨/);
});
test('terminal projects retain receivables but cannot offer a change-order shortcut',()=>{
 const html=render({terminal:true});assert.match(html,/已终止/);assert.match(html,/确认收款/);assert.doesNotMatch(html,/追加订单/);
});
test('personal projects do not show client financial actions; zero outstanding does not offer receipt',()=>{
 const html=render({personal:true});assert.match(html,/个人项目/);assert.doesNotMatch(html,/合同总额|>追加订单<|>确认收款</);assert.doesNotMatch(render({outstanding:0,income:6000}),/>确认收款</);
});
