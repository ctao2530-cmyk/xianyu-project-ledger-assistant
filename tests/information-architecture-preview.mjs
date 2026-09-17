// Isolated frontend-only browser QA. No real database, channel, or model calls.
import {createServer} from 'node:http';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url);
const {build}=createRequire(require.resolve('vite'))('esbuild');
const entry=String.raw`
import React from 'react';import {createRoot} from 'react-dom/client';
import {CustomerMessagesPage} from './src/pages/CustomerMessagesPage';
import {CustomerCreateDialog} from './src/components/CustomerCreateDialog';
import {ActionWorkbench} from './src/components/ActionWorkbench';
import {ProjectDetail} from './src/pages/BusinessAssistantPages';
import {App as FullApp} from './src/App';
import {referenceProductFixture} from './tests/reference-product-fixture';
import {mockLedgerService} from './src/data/mockService';
import './src/styles.css';
import './src/desktop-workspace.css';
import './src/components/workspace/retained-workspace-layout.css';
import './src/components/workspace/page-controls.css';
import './src/components/workspace/customer-controls.css';
import './src/components/workspace/reading-workspace.css';
import './src/design/tokens.css';
import './src/design/workspace.css';
const customer={id:'qa-customer',name:'合成验收客户',source:'xianyu',level:'C',followUpStatus:'contacted'};
const testImageUrl=(width,height)=>'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="'+width+'" height="'+height+'"><rect width="100%" height="100%" fill="#e8eef8"/><rect x="12" y="12" width="'+(width-24)+'" height="'+(height-24)+'" fill="none" stroke="#2563eb" stroke-width="8"/><text x="40" y="90" font-size="42" fill="#172033">TOP / SYNTHETIC</text><path d="M40 130 L'+(width-40)+' '+(height-130)+'" stroke="#93a6cd" stroke-width="8"/><text x="40" y="'+(height-50)+'" font-size="42" fill="#172033">BOTTOM / COMPLETE</text></svg>');
const syntheticImage={id:'synthetic-image',conversation_id:1,message_id:3,channel:'xianyu',customer_name:'合成会话 1',received_at:'2026-09-09T10:01:00Z',captured_at:'2026-09-09T10:01:05Z',mime_type:'image/png',original_name:'synthetic-orbit.png',file_size:1000,width:128,height:128,integrity_verified:false,content_url:'/assets/xunying/orbit-mark.png',preview_url:'/assets/xunying/orbit-mark.png',download_url:'/assets/xunying/orbit-mark.png',capture_status:'stored',media_index:0};
if(location.search.includes('long=1'))Object.assign(syntheticImage,{width:800,height:3200,original_name:'synthetic-long.svg',mime_type:'image/svg+xml',content_url:testImageUrl(800,3200),preview_url:testImageUrl(800,3200),download_url:testImageUrl(800,3200)});
const wideImage={...syntheticImage,id:'synthetic-wide',width:2400,height:800,original_name:'synthetic-wide.svg',content_url:testImageUrl(2400,800),preview_url:testImageUrl(2400,800),download_url:testImageUrl(2400,800)};
const snapshot={customers:[customer],projects:[{id:'qa-project',name:'合成关联项目',customerId:customer.id,totalAmount:1000,startDate:'2026-09-01',dueDate:'2026-09-15',status:'in_progress',progress:0,accent:'purple',estimatedHours:10}],changeOrders:[],settlementIssues:[],completedOrderCount:0,attachments:[],tasks:[],payments:[],logs:[],expenses:[],settings:{}};
if(location.search.includes('dense=1')||location.search.includes('reference=1'))snapshot.projects.push(...Array.from({length:location.search.includes('reference=1')?4:11},(_,i)=>({...snapshot.projects[0],id:'qa-project-'+(i+2),name:'合成项目 '+(i+2)+' · 需求与交付',status:i%3===0?'completed':'in_progress',totalAmount:1000+(i+1)*100,dueDate:'2026-09-'+String(16+i).padStart(2,'0')})));
if(location.search.includes('linked=1'))snapshot.projects[0].conversationId=1;
customer.channelIdentities=[{channel:'xianyu',externalCustomerId:'synthetic',conversationId:1},{channel:'xianyu',externalCustomerId:'synthetic',conversationId:2}];
snapshot.customers.push({...customer,id:'qa-orphan',name:'无会话合成客户',channelIdentities:[]});
snapshot.tasks.push({id:'qa-task',projectId:'qa-project',title:'合成开发任务',status:'done',startDate:'2026-09-01',dueDate:'2026-09-15',estimatedHours:2,actualHours:3,workspaceKey:'frontend',stage:{acceptance_criteria:['390px 无溢出']}});
if(location.search.includes('populated=1')){
  customer.currentNeed='合成需求：调整资料分类与筛选，保留原始记录。';
  customer.nextAction='核对需求范围与交付清单';
  customer.tags=['页面优化','待确认'];
  snapshot.projects[0].totalAmount=6000;
  snapshot.payments.push(...Array.from({length:3},(_,i)=>({id:'qa-payment-'+i,projectId:'qa-project',customerId:customer.id,amount:500+i*200,type:'milestone',status:'confirmed',paidAt:'2026-09-0'+(9-i)+'T10:30:00+08:00',dueAt:'2026-09-0'+(9-i),notes:'合成阶段款 '+(i+1)})));
  snapshot.expenses.push(...Array.from({length:3},(_,i)=>({id:'qa-expense-'+i,projectId:'qa-project',name:'合成工具费用 '+(i+1),amount:100+i*50,category:'software',paidAt:'2026-09-0'+(9-i)+'T09:00:00+08:00',notes:'仅用于隔离验收'})));
}
if(location.search.includes('aging=1')){
  snapshot.projects=[];snapshot.payments=[];snapshot.tasks=[];snapshot.expenses=[];
  const due=(days)=>new Date(Date.now()+days*86400000).toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});
  const cases=[['长账龄项目',-70,800],['阶段交付项目',-40,600],['近期回款项目',-7,400],['今日到期项目',0,500],['下月回款项目',20,900],['未约定收款项目',null,300],['计划冲突项目',-5,200],['终止待结算项目',-15,150]];
  cases.push(...Array.from({length:7},(_,i)=>['合成跟进项目 '+(i+1),-3,100]));
  cases.forEach(([name,days,amount],i)=>{const id=i===0?'qa-project':'qa-aging-'+i;snapshot.projects.push({id,name,customerId:customer.id,totalAmount:amount,startDate:due(-90),dueDate:due(-2),status:'in_progress',progress:0,accent:'purple',estimatedHours:1});if(days!==null)snapshot.payments.push({id:'aging-payment-'+i,projectId:id,customerId:customer.id,amount:i===6?amount+50:i===0?500:amount,status:'pending',type:'final',paidAt:'',dueAt:due(days)});if(i===0)snapshot.payments.push({id:'aging-second',projectId:id,customerId:customer.id,amount:300,status:'pending',type:'milestone',paidAt:'',dueAt:due(10)});if(i===7)snapshot.settlementIssues.push({id:'qa-terminal',projectId:id,type:'project_cancelled',reason:'合成终止记录',occurredAt:due(-10),refundAmount:0,receivableImpact:0});});
}
window.__qa={calls:[],errors:[],created:0};addEventListener('error',e=>window.__qa.errors.push(e.message));addEventListener('unhandledrejection',e=>window.__qa.errors.push(String(e.reason)));
snapshot.settings={xianyuStartedAt:'2026-09-01',monthlyIncomeGoal:1000,profileName:'合成验收账户',notificationsEnabled:false};
mockLedgerService.getDashboard=async()=>snapshot;
mockLedgerService.refreshDashboard=async()=>snapshot;
mockLedgerService.saveSnapshot=async()=>{throw Error('隔离验收禁止写入')};
window.EventSource=class{addEventListener(){}removeEventListener(){}close(){}};
window.WebSocket=class{static OPEN=1;readyState=3;addEventListener(){}removeEventListener(){}close(){}send(){throw Error('QA blocks WebSocket sends')}};
const formalDocument={schema_version:'2.0',title:'合成正式需求',project_type:'web',readiness:'approved',change_summary:'新增合成筛选需求',objectives:[{id:'o1',title:'提升信息查找效率',description:'隔离测试目标',evidence_refs:[]}],capabilities:[{id:'c1',title:'分类方式调整',description:'改成横向选择，保留原筛选逻辑',objective_ids:['o1'],priority:'must',evidence_refs:[]}],stages:[{id:'s1',title:'页面调整',objective:'保留原逻辑',implementation:'调整前端布局',estimated_hours:2,capability_ids:['c1'],dependency_ids:[],work_items:['调整布局'],deliverables:['修改页面','源码'],evidence_refs:[]}],acceptance_gates:[{id:'a1',title:'交付验收',description:'人工检查',stage_ids:['s1'],criteria:['筛选结果保持一致','390px无横向溢出'],evidence_refs:[]}],out_of_scope:['不改业务规则'],assumptions:[],open_questions:['需要客户确认移动端顺序'],risks:[],evidence_refs:[]};
const formalVersion={id:1,version:1,schema_version:'2.0',source_type:'gpt_confirmed',source_label:'合成提案',title:'合成正式需求',readiness:'approved',change_summary:'新增合成筛选需求',created_at:'2026-09-09T00:00:00Z',imported_at:null};
const formalCase={id:'qa-case',customer_id:'qa-customer',title:'合成正式需求',status:'approved',current_version:1,source_count:1,estimated_hours:2,open_question_count:1,updated_at:'2026-09-09T00:00:00Z',project_id:'qa-project',versions:[formalVersion],selected_version:formalVersion,document:formalDocument,sources:[]};
if(location.search.includes('versions=1')){const v2={...formalVersion,id:2,version:2,change_summary:'V2 合成调整'};Object.assign(formalCase,{current_version:2,versions:[v2,formalVersion],selected_version:v2});}
const syntheticRecommendations=Array.from({length:4},(_,i)=>({id:'qa-recommendation-'+i,analysis_id:'synthetic-analysis',analysis_snapshot_time:'2026-09-09T00:00:00Z',source_key:'qa-'+i,domain:'projects',entity_type:'project',entity_id:'qa-project',entity_label:'合成关联项目',target_scope:'entity',priority:i<2?'high':'medium',title:['核对需求范围','补充交付材料','检查阶段回款','复盘交付记录'][i],problem:'合成验收状态',action:'人工核对合成记录，不触发真实操作',reason:'仅用于界面密度验收',data_source:['合成项目记录'],confidence:'low',observe_period:'7d',observe_days:7,status:'pending',lifecycle_status:'pending',version:1,user_note:'',target_page:'项目管理',execution_mode:'manual',evidence_refs:[],accepted_at:null,started_at:null,observe_until:null,completed_at:null,baseline_metrics:null,result_metrics:null,outcome:null,actual_cost:null,actual_hours:null,user_conclusion:'',execution_ref_type:null,execution_ref_id:null,stale:false,can_accept:true,can_ignore:true,can_start:false,can_complete:false}));
window.fetch=async(url,opts)=>{const u=String(url);window.__qa.calls.push({url:u,method:opts?.method||'GET'});let data=[];
if(opts?.method&&opts.method!=='GET')return new Response('{}',{status:403});
if(u.startsWith('/api/workbench/actions')) {
 const items=[1,2].map(id=>({id:'conversation-'+id,category:'客户消息',title:'合成会话 '+id,detail:id+' 条未读消息',updatedAt:'2026-09-09T10:00:00Z',href:'#'+encodeURIComponent('客户消息/conversation/'+id)}));
 items.push({id:'questions-qa-case',category:'待补资料',title:'合成正式需求',detail:'1 项待确认问题',updatedAt:'2026-09-09T00:00:00Z',href:'#'+encodeURIComponent('客户管理/qa-customer/requirements/qa-case')},{id:'requirement-qa-case-ready',category:'待确认需求',title:'合成待确认需求',detail:'正式需求尚未确认',updatedAt:'2026-09-09T00:00:00Z',href:'#'+encodeURIComponent('客户管理/qa-customer/requirements/qa-case-ready')});
 data={items,total:items.length,offset:0,hasMore:false,asOf:'2026-09-16T00:00:00Z'};
}
else if(u.startsWith('/api/projects/')&&u.includes('/acceptance'))data={revision:1,items:[],has_more:false};
else if(u==='/api/maintenance/readiness')data={status:'ready',database:'readable',schema_revision:'synthetic'};
else if(u==='/api/maintenance/analysis-usage')data={date:'2026-09-16',attempts:0,daily_limit:100,admission_paused:false,completed_artifacts:0,artifacts_with_usage:0,reported_tokens:null,scope:'合成用量，不代表真实模型调用'};
else if(u==='/api/business-analysis')data={analysis_id:'synthetic-analysis',summary:'合成验收：当前没有已确认收入，待回款需要人工核对。',generated_at:'2026-09-09T00:00:00Z',snapshot_time:'2026-09-09T00:00:00Z',record_status:'completed',ai_status:'not_requested',is_stale:false,provider:null,model:null,period:{current_month_start:'2026-09-01',current_month_end:'2026-09-30'},metrics:{finance:{income:{current:0},expenses:{current:0},profit:{current:0}},projects:{active_projects:1,completed_projects:0,total:1,outstanding_receivables:1000},customers:{total:2,stale_or_missing_contact_30d:0,active_last_30d:1},products:{owned_products:0,active_products:0,monitored_products:0,snapshot_coverage_percent:0}},recommendations:[],insights:[],data_sources:[],data_gaps:[],predictions:[]};
else if(u.startsWith('/api/business-analysis/history'))data={items:[],total:0};
else if(u==='/api/business-analysis/recommendations')data={items:location.search.includes('populated=1')?syntheticRecommendations:[],counts:{total:location.search.includes('populated=1')?4:0,pending:location.search.includes('populated=1')?4:0,accepted:0,observing:0,review_due:0,completed:0,ignored:0}};
else if(u==='/api/ai/providers')data=[{provider:'codex_cli',configured:false,status:'unavailable',model:null},{provider:'deepseek',configured:false,status:'unavailable',model:null}];
else if(u==='/api/ai/models')data={provider:'codex_cli',selected_model:null,models:[]};
else if(u==='/api/products/intelligence')data=referenceProductFixture;
else if(location.search.includes('formal=1')&&u.includes('/requirement-blueprints'))data=[{...formalVersion,project_id:'qa-project',customer_id:'qa-customer',case_id:'qa-case',metrics:{capabilities:1,stages:1,deliverables:2,criteria:2,questions:1}}];
else if(location.search.includes('formal=1')&&/^\/api\/requirement-cases\/qa-case(?:\?|$)/.test(u)){const v=new URL(u,location.origin).searchParams.get('version');data=v==='1'?{...formalCase,selected_version:formalVersion,document:{...formalDocument,title:'V1 合成历史需求',change_summary:'V1 历史保留'}}:formalCase;}
else if(location.search.includes('formal=1')&&u.endsWith('/customers/qa-customer/requirements'))data=[formalCase];
else if(u.endsWith('/codex-bindings'))data=[];
else if(u.endsWith('/codex-plan'))data=null;
else if(u.startsWith('/api/conversations?'))data=(location.search.includes('populated=1')?[1,2,3,4,5,6,7,8]:[1,2]).map(id=>({id,channel:'xianyu',customer_name:'合成会话 '+id,item_title:'合成商品 '+id,unread_count:location.search.includes('populated=1')&&id<3?id:0,last_message:'合成消息，不来自真实客户',last_message_at:'2026-09-09T10:00:00Z'}));
else if(/^\/api\/conversations\/[1-8]$/.test(u)){const id=Number(u.split('/').pop());data={id,channel:'xianyu',customer_name:'合成会话 '+id,linked_customer_id:customer.id,item:{title:'合成商品 '+id},messages:[{id,content:'合成消息，不来自真实客户',direction:'inbound',received_at:'2026-09-09T10:00:00Z'}],has_older_messages:false};}
else if(u.includes('conversation-group-candidates'))data={conversations:[1,2].map(id=>({id,item_title:'合成商品 '+id})),groups:[]};
else if(u.startsWith('/api/customer-message-search/context')){const p=new URL(u,location.origin).searchParams,id=Number(p.get('message_id'));data={message_id:id,conversation_id:1,messages:[{id:id-1,content:'命中之前的合成消息',received_at:'2026-09-09T09:59:00Z',direction:'inbound'},{id,content:'合成筛选需求，保留原始数据',received_at:'2026-09-09T10:00:00Z',direction:'inbound',images:[syntheticImage]},{id:id+1,content:'之后的合成回复',received_at:'2026-09-09T10:00:30Z',direction:'outbound'}]};}
else if(u.startsWith('/api/customer-message-search?')){const p=new URL(u,location.origin).searchParams,q=p.get('query');if(q==='失败')return new Response(JSON.stringify({detail:'合成搜索失败，请重试'}),{status:503});const more=p.has('before_message_id'),empty=q==='不存在';data={items:empty?[]:Array.from({length:more?5:30},(_,i)=>({id:(more?100:130)-i,conversation_id:1,received_at:'2026-09-09T10:00:00Z',direction:'inbound',snippet:'合成筛选需求 '+i+'，保留原始数据'})),total:empty?0:35,has_more:!empty&&!more,next_before_message_id:more?null:101};}
else if(u==='/api/customer-images/status')data={state:'healthy',stored_count:location.search.includes('media=1')?1:0,attention_count:0,failed_count:0,pending_count:0,missing_count:0,candidate_count:0,channel_counts:{xianyu:location.search.includes('media=1')?1:0},last_captured_at:syntheticImage.captured_at,message:'隔离归档状态'};
else if(u==='/api/customer-images/filters')data={channels:['xianyu'],conversations:[{id:1,customer_name:'合成会话 1',channel:'xianyu',image_count:location.search.includes('media=1')?1:0}],items:[]};
else if(u.startsWith('/api/customer-images?')){
  const params=new URL(u,location.origin).searchParams;
  const matched=(location.search.includes('media=1')?(location.search.includes('long=1')?[syntheticImage,wideImage]:[syntheticImage]):[]).filter(image=>(!params.get('conversation_id')||Number(params.get('conversation_id'))===image.conversation_id)&&(!params.get('channel')||params.get('channel')===image.channel)&&(!params.get('search')||(image.original_name+' '+image.customer_name).includes(params.get('search'))));
  const offset=Number(params.get('offset')||0),limit=Number(params.get('limit')||100);
  data={items:matched.slice(offset,offset+limit),total:matched.length,has_more:offset+limit<matched.length};
}
else if(u.includes('intake'))data={revision:1,candidates:[{conversation_id:2,customer_name:'合成会话 2',customer_source:'xianyu',channel:'xianyu'}]};
else if(location.search.includes('populated=1')&&u.endsWith('/customers/qa-customer/requirements'))data=[{...formalCase,status:'clarifying',open_question_count:1},{...formalCase,id:'qa-case-ready',title:'合成待确认需求',status:'ready',open_question_count:0}];
else if(!u.includes('/requirements')&&!u.includes('requirement-proposals')&&!u.includes('requirement-blueprints'))return new Response(JSON.stringify({detail:'合成接口暂不可用，用于失败状态验收'}),{status:503,headers:{'Content-Type':'application/json'}});
if(location.search.includes('media=1')&&u==='/api/conversations/1'){data.messages.push({id:2,content:'合成回复：请核对图片与交付范围。',direction:'outbound',received_at:'2026-09-09T10:00:30Z'},{id:3,content:'[图片]',direction:'inbound',received_at:syntheticImage.received_at,images:[syntheticImage]},{id:4,content:'合成失败状态',direction:'inbound',received_at:'2026-09-09T10:02:00Z',images:[{...syntheticImage,id:'synthetic-failed',capture_status:'failed',error_message:'隔离测试下载超时'}]});}
if(location.search.includes('reference=1')&&u==='/api/conversations/1')data.messages=Array.from({length:7},(_,i)=>({id:50+i,content:['这次先确认页面布局和使用流程。','客户列表保留搜索、渠道筛选和未读提示；不同客户之间的数据仍然分开。','项目页面需要清楚显示交付时间和当前状态。','历史记录保留，方便后续核对。','已收到，会先核对现有组件，再调整页面。','手机上也要能查看客户会话。','好的，按确认的范围继续。'][i],direction:i===4?'outbound':'inbound',sender_name:i===4?'经营者':'合成客户',received_at:'2026-09-09T10:'+String(i).padStart(2,'0')+':00Z',images:[]}));
return new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}})};
function App(){const [open,setOpen]=React.useState(false);const [hash,setHash]=React.useState(location.hash);React.useEffect(()=>{const sync=()=>setHash(location.hash);addEventListener('hashchange',sync);return()=>removeEventListener('hashchange',sync)},[]);return <><h1 style={{fontSize:14,padding:12}}>隔离前端验收 · 全部为合成数据</h1>{decodeURIComponent(hash).includes('工作台')?<ActionWorkbench snapshot={snapshot} onConfirmPayment={()=>{window.__qa.confirmTarget='qa-project'}}/>:decodeURIComponent(hash).includes('项目管理/')?<ProjectDetail snapshot={snapshot} projectId="qa-project" tab="overview" onBack={()=>history.back()} onEdit={()=>{}} onTabChange={()=>{}} onCreatePaymentPlan={()=>{}} onCreateChangeOrder={()=>{}} onConfirmPayment={()=>{}} onRecordSettlementIssue={()=>{}} onSnapshotChange={()=>{}}/>:<CustomerMessagesPage customers={[customer]} snapshot={snapshot} onSnapshotChange={()=>{}} onCreateCustomer={()=>setOpen(true)}/>}{open&&<CustomerCreateDialog initialConversationId={2} onClose={()=>setOpen(false)} onCreated={()=>{window.__qa.created++}}/>}</>};createRoot(document.getElementById('root')).render(location.search.includes('shell=1')?<FullApp/>:<App/>);
`;
const bundle=await build({stdin:{contents:entry,resolveDir:process.cwd(),loader:'tsx'},bundle:true,external:['/assets/*'],write:false,outdir:'in-memory',format:'iife',jsx:'automatic',loader:{'.png':'dataurl','.svg':'dataurl','.woff2':'dataurl'},define:{'process.env.NODE_ENV':'"test"'},logLevel:'silent'});
// Browser-only safety prelude for testing the unchanged production bundle.
// Served by this isolated preview, never included in the production build.
const fixtureBundle=await build({stdin:{contents:"import {referenceProductFixture} from './tests/reference-product-fixture';window.__referenceProductFixture=referenceProductFixture;",resolveDir:process.cwd(),loader:'ts'},bundle:true,write:false,format:'iife',logLevel:'silent'});
const qaPrelude=`(()=>{if(location.hostname!=='127.0.0.1'||!['18880','8877'].includes(location.port))throw Error('QA prelude is local-only');
const storage=new WeakMap();Storage.prototype.getItem=function(k){return storage.get(this)?.get(String(k))??null};Storage.prototype.setItem=function(k,v){if(!storage.has(this))storage.set(this,new Map());storage.get(this).set(String(k),String(v))};Storage.prototype.removeItem=function(k){storage.get(this)?.delete(String(k))};Storage.prototype.clear=function(){storage.delete(this)};
window.XMLHttpRequest=class{constructor(){throw Error('QA blocks XMLHttpRequest')}};window.WebSocket=class{static OPEN=1;readyState=3;addEventListener(){}removeEventListener(){}close(){}send(){throw Error('QA blocks WebSocket sends')}};navigator.sendBeacon=()=>false;
${fixtureBundle.outputFiles[0].text}
const referenceProductFixture=window.__referenceProductFixture;
${entry.slice(entry.indexOf('const customer='),entry.indexOf('function App(){')).replace(/^mockLedgerService\..*$/gm,'').replace("if(u==='/api/business-analysis')", "if(u==='/api/ledger/snapshot')data={revision:1,snapshot};else if(u==='/api/business-analysis')")}
})();`;
const server=createServer((req,res)=>{const p=req.url.split('?')[0];if(process.env.XUNYING_QA_BUILD_DIR&&p!=='/qa-prelude.js'){if(p.includes('..')||p.startsWith('/api/')){res.writeHead(403);res.end();return;}try{const extension=p.split('.').pop();const file=p==='/'?'/index.html':p;const bytes=readFileSync(process.env.XUNYING_QA_BUILD_DIR+file);res.setHeader('Content-Type',({'js':'text/javascript','css':'text/css','html':'text/html','png':'image/png','svg':'image/svg+xml','webp':'image/webp'})[extension]||(p==='/'?'text/html':'application/octet-stream'));res.end(bytes);return;}catch{res.writeHead(404);res.end();return;}}if(p==='/qa-prelude.js'){res.setHeader('Content-Type','text/javascript');res.end(qaPrelude);return;}if(p.startsWith('/assets/')&&!p.includes('..')&&/\.(png|webp|jpg|svg)$/.test(p)){try{res.setHeader('Content-Type',p.endsWith('.svg')?'image/svg+xml':p.endsWith('.webp')?'image/webp':'image/png');res.end(readFileSync(new URL('../public'+p,import.meta.url)));return;}catch{res.statusCode=404;res.end();return;}}res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src data:; connect-src 'none'");res.setHeader('Content-Type',p==='/app.js'?'text/javascript':p==='/app.css'?'text/css':'text/html');res.end(p==='/app.js'?bundle.outputFiles.find(f=>f.path.endsWith('.js')).text:p==='/app.css'?bundle.outputFiles.find(f=>f.path.endsWith('.css'))?.text:'<!doctype html><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><div id="root"></div><script src="/app.js"></script>')});
server.listen(18880,'127.0.0.1',()=>console.log('Isolated frontend QA http://127.0.0.1:18880'));
