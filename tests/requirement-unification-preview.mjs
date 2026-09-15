// Memory-only synthetic UI. Never connects to the real service.
import {createServer} from 'node:http';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {build}=createRequire(require.resolve('vite'))('esbuild');
const fixture=String.raw`
import React from 'react';import {createRoot} from 'react-dom/client';
import {ProjectDetail} from './src/pages/BusinessAssistantPages';
import {RequirementProposalReview} from './src/components/RequirementProposalReview';
import './src/styles.css';import './src/pages/business-assistant.css';
const snapshot={projects:[{id:'synthetic-project',name:'合成验收项目',customerId:'synthetic-customer',projectKind:'client',totalAmount:4000,startDate:'2026-09-01',dueDate:'2026-09-20',progress:0,status:'in_progress',type:'定制开发',estimatedHours:20,accent:'blue',notes:'仅用于隔离验收。',itemExternalId:'synthetic-item'}],customers:[{id:'synthetic-customer',name:'合成客户',level:'A',followUpStatus:'contacted',source:'xianyu'}],payments:[],tasks:[],logs:[],attachments:[],changeOrders:[],settlementIssues:[],expenses:[],settings:{},completedOrderCount:0};
window.__qa={errors:[],calls:[],empty:location.search.includes('empty'),fail:location.search.includes('fail'),confirmed:false};
addEventListener('error',e=>window.__qa.errors.push(String(e.message)));addEventListener('unhandledrejection',e=>window.__qa.errors.push(String(e.reason)));
window.fetch=async(url,opts)=>{window.__qa.calls.push({url:String(url),method:opts?.method||'GET'});let data=[];
if(window.__qa.fail)return new Response(JSON.stringify({detail:'合成连接失败'}),{status:503});
if(String(url).includes('requirement-proposals/confirm')){const p=JSON.parse(opts.body);if(!p.confirmed||p.review_token!=='synthetic-local-token')return new Response('{}',{status:403});window.__qa.confirmed=true;data={case_id:'synthetic-case',version:1};}
else if(String(url).includes('requirement-proposals'))data=[{id:'synthetic-proposal',request_id:'synthetic-request',review_token:'synthetic-local-token',expected_version:0,document:{title:'合成正式需求',change_summary:'新增导出能力',objectives:[],capabilities:[],stages:[],acceptance_gates:[],evidence_refs:[]},diff:{capabilities:{added:[{id:'cap-export',before:null,after:{title:'导出能力'}}],modified:[],removal_proposed:[],unchanged:[]}}}];
if(String(url).includes('requirement-blueprints'))data=window.__qa.empty?[]:[{id:3,project_id:'synthetic-project',case_id:'synthetic-case',customer_id:'synthetic-customer',version:3,schema_version:'2.0',title:'正式需求蓝图',readiness:'approved',source_label:'GPT 提案 · 人工确认',source_type:'gpt_confirmed',change_summary:'新增：Excel 导出；调整：会员下载权限',metrics:{capabilities:8,stages:4,deliverables:6,criteria:12,questions:1},diff:{}}];
return new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});};
const noop=()=>{};createRoot(document.getElementById('root')).render(<main style={{padding:24}}><p>隔离验收 · 合成数据</p>{location.search.includes('review')?<RequirementProposalReview customerId='synthetic-customer' onConfirmed={id=>{window.__qa.confirmedCase=id;}}/>:<ProjectDetail snapshot={snapshot} projectId='synthetic-project' tab='overview' onBack={noop} onEdit={noop} onTabChange={noop} onCreatePaymentPlan={noop} onCreateChangeOrder={noop} onConfirmPayment={noop} onRecordSettlementIssue={noop} onSnapshotChange={noop}/>}</main>);
`;
const result=await build({stdin:{contents:fixture,resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,outdir:'synthetic-memory',format:'iife',jsx:'automatic',loader:{'.png':'dataurl','.svg':'dataurl','.woff2':'dataurl'},define:{'process.env.NODE_ENV':'"test"'},logLevel:'silent'});
const js=result.outputFiles.find(f=>f.path.endsWith('.js')).text,css=result.outputFiles.find(f=>f.path.endsWith('.css'))?.text||'';
const html='<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>';
const server=createServer((req,res)=>{res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src data:; connect-src 'none'");const route=req.url.split('?')[0];res.setHeader('Content-Type',route==='/app.js'?'text/javascript':route==='/style.css'?'text/css':'text/html');res.end(route==='/app.js'?js:route==='/style.css'?css:html);});
server.listen(18880,'127.0.0.1',()=>console.log('Synthetic preview http://127.0.0.1:18880'));
setTimeout(()=>server.close(),3600000).unref();
