// S07: real App, synthetic-only in-memory adapter. No real API, model, or database.
import { readFileSync, writeFileSync, existsSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
const cwd=realpathSync(process.cwd());
if(!cwd.startsWith(realpathSync(tmpdir())+'/')||existsSync('.env')||existsSync('data'))throw Error('S07 requires an isolated temporary source copy');
const original=readFileSync('tests/information-architecture-preview.mjs','utf8');
const target="createRoot(document.getElementById('root')).render(location.search.includes('shell=1')?<FullApp/>:<App/>);";
if(!original.includes(target))throw Error('Baseline fixture changed');
const states=String.raw`
// Normal preview plays live; only an explicit screenshot fixture freezes time.
window.__analysisAuroraTest={time:new URLSearchParams(location.search).get('still')==='1'?8:undefined};
const OriginalDate=Date;const fixedNow=OriginalDate.parse(analysisTestTime);window.Date=class extends OriginalDate{constructor(...args){super(...(args.length?args:[fixedNow]))}static now(){return fixedNow}};
const state=new URLSearchParams(location.search).get('case')||'normal';
const sample=analysisFixture(state);const report=sample.overview;
const qa=window.__analysisQa={state,fail:state==='error',hold:false,modelFail:false,conflict:false,pending:[],console:[],longTasks:[],modelCalls:0,blockedWrites:0,requests:[]};
for(const key of ['error','warn']){const old=console[key];console[key]=(...args)=>{qa.console.push({level:key,message:args.map(String).join(' ').slice(0,500)});old.apply(console,args)}}
new PerformanceObserver(list=>qa.longTasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true});
mockLedgerService.getDashboard=async()=>structuredClone(sample.ledger);mockLedgerService.refreshDashboard=mockLedgerService.getDashboard;
const profile={id:'qa-profile',provider:'codex_cli',model:'synthetic-model',reasoning_effort:'medium',label:'隔离模拟模型',enabled:true,is_default:true,configured:state!=='unconfigured',revision:1,created_at:analysisTestTime,updated_at:analysisTestTime};
const contexts=[1,2].map(id=>({conversation_id:id,customer_id:id===1?'qa-customer':'qa-orphan',channel:'xianyu',customer_name:'合成上下文 '+id,item_title:null,text_message_count:2,image_message_count:0,latest_text_message_id:id*10,latest_message_at:analysisTestTime,summary_version:null,summarized_through_message_id:null,new_message_count:2,context_updated:false}));
const thread={id:'qa-thread',title:'合成经营问题',profile_id:profile.id,provider:'codex_cli',model:profile.model,reasoning_effort:'medium',context_scope:'general_business',customer_context:null,status:'active',revision:1,created_at:analysisTestTime,updated_at:analysisTestTime,messages:[],active_run:null,latest_run:null};
const run={id:'qa-run',request_id:'synthetic-run',thread_id:thread.id,user_message_id:'qa-user',assistant_message_id:null,provider:'codex_cli',model:profile.model,reasoning_effort:'medium',status:'running',error_code:null,error_message:null,started_at:analysisTestTime,completed_at:null,created_at:analysisTestTime};
const trace=()=>({run_id:run.id,thread_id:thread.id,provider:run.provider,model:run.model,status:run.status,completed_steps:run.status==='completed'?2:1,total_steps:2,tool_count:1,elapsed_ms:2300,decision_summary:'合成账本已读取；请人工核对回款。',legacy:false,error_code:run.error_code,error_message:run.error_message,started_at:analysisTestTime,completed_at:run.completed_at,steps:[{id:'qa-step',position:1,node_name:'read',label:'读取经营事实',phase:'evidence',status:'completed',summary:'已读取合成账本',duration_ms:200,started_at:analysisTestTime,completed_at:analysisTestTime}],tools:[{id:'qa-tool',position:1,name:'ledger',label:'读取账本',status:'completed',summary:'2 笔确认收款',duration_ms:20,source:'canonical_ledger',observed_at:analysisTestTime,revision:1,read_only:true,sensitivity:'synthetic',created_at:analysisTestTime}]});
qa.finishRun=(status='completed')=>{run.status=status;run.completed_at=analysisTestTime;thread.active_run=null;thread.latest_run={...run};if(status==='completed')thread.messages.push({id:'qa-answer',thread_id:thread.id,role:'assistant',content:'合成回答：本月确认收入 8,000 元。请按合同核对待回款；这里没有平台实时采集或真实模型调用。',status:'completed',run_id:run.id,run_elapsed_ms:2300,answer:{conclusion:'合成回答：本月确认收入 8,000 元，待回款需人工核对。',confidence:'medium',observation_period:'当前合成快照',facts:[{text:'已确认收入 8,000 元',evidence_refs:['qa-tool']}],causes:['依据当前账本确认记录'],next_step:'按原合同检查待回款节点。',target_page:'',limitations:['仅合成数据；未调用真实模型或采集平台'],requirement_analysis:null,requirement_blueprint:null,execution_plan:null,customer_create_proposal:null},citations:[],tool_references:trace().tools,created_at:analysisTestTime});else{run.error_message='模拟模型任务失败';thread.latest_run={...run}}};
const historyRow=id=>({id,snapshot_time:analysisTestTime,created_at:analysisTestTime,provider:null,model:null,ai_status:'not_requested',fallback_used:false,status:'completed',summary:report.summary,insight_count:1,recommendation_count:sample.recommendations.length,pending_recommendation_count:1});
const previousFetch=window.fetch;const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
window.fetch=async(url,opts)=>{
 const u=String(url),path=new URL(u,location.origin).pathname,method=opts?.method||'GET';
 const supported=path.startsWith('/api/business-analysis')||path.startsWith('/api/global-agent/')||path.startsWith('/api/customer-context/threads/')||path.startsWith('/api/predictions')||path.startsWith('/api/estimation-calibration')||['/api/ledger/snapshot','/api/ai/providers','/api/ai/models','/api/products/intelligence'].includes(path);
 if(!supported)return previousFetch(url,opts);
 window.__qa.calls.push({url:u,method});
 const body=opts?.body?JSON.parse(opts.body):{};if(method!=='GET')qa.requests.push({path,method,request_id:body.request_id,expected_version:body.expected_version,expected_revision:body.expected_revision,provider:body.provider,model:body.model});
 if(method!=='GET'&&state!=='interactive'){qa.blockedWrites++;return json({detail:'S07 只读夹具阻断写入'},403)}
 if(path==='/api/ledger/snapshot')return json({revision:1,snapshot:sample.ledger});
 if(path==='/api/products/intelligence')return json({...referenceProductFixture,items:[],products:[],summary:{...referenceProductFixture.summary,total_products:0,owned_products:0}});
 if(path==='/api/ai/providers')return json(['codex_cli','deepseek'].map(provider=>({provider,label:provider,configured:state!=='unconfigured'&&provider==='codex_cli',status:state==='unconfigured'?'login_required':'ready',detail:null,model:profile.model,lead_model:profile.model})));
 if(path==='/api/ai/models')return json({provider:'codex_cli',selected_model:profile.model,selected_reasoning_effort:'medium',models:[{model:profile.model,display_name:profile.label,default_reasoning_effort:'medium',supported_reasoning_efforts:['medium']}]});
 if(path==='/api/business-analysis'){
  if(state==='loading')await new Promise(resolve=>qa.pending.push(resolve));
  if(qa.fail)return json({detail:'合成经营分析读取失败'},503);
  if(state==='denied')return json({detail:'合成只读权限不足'},403);
  return json(report);
 }
 if(path==='/api/business-analysis/runs'){
  qa.modelCalls++;if(qa.hold)await new Promise(resolve=>qa.pending.push(resolve));
  if(qa.modelFail)return json({detail:'模拟模型调用失败；没有切换提供者'},503);
  return json({...report,provider:body.provider,model:body.model,ai_status:'succeeded'});
 }
 if(path==='/api/business-analysis/history')return json({items:state==='empty'?[]:[historyRow('qa-analysis'),historyRow('qa-history')],total:state==='empty'?0:2,offset:0,limit:20});
 if(path.startsWith('/api/business-analysis/history/'))return json({...report,analysis_id:'qa-history',is_stale:true});
 if(path==='/api/business-analysis/recommendations'){const counts={total:sample.recommendations.length,pending:0,accepted:0,observing:0,review_due:0,completed:0,ignored:0};for(const r of sample.recommendations)counts[r.lifecycle_status]++;return json({items:sample.recommendations,counts,generated_at:analysisTestTime})}
 if(path.startsWith('/api/business-analysis/recommendations/')){
  const id=path.split('/')[4],r=sample.recommendations.find(r=>r.id===id);if(!r)return json({detail:'unknown synthetic recommendation'},404);
  if(qa.hold)await new Promise(resolve=>qa.pending.push(resolve));
  if(qa.conflict||body.expected_version!==r.version)return json({detail:{code:'revision_conflict',message:'合成版本冲突',current_version:r.version}},409);
  if(path.endsWith('/start')){r.status='observing';r.lifecycle_status='observing';r.can_start=false;r.can_complete=true;r.started_at=analysisTestTime;r.observe_until='2026-09-25T04:00:00Z'}
  else if(path.endsWith('/complete')){r.status='completed';r.lifecycle_status='completed';r.can_complete=false;r.outcome=body.outcome;r.user_conclusion=body.user_conclusion;r.completed_at=analysisTestTime}
  else{r.status=body.status;r.lifecycle_status=body.status;r.can_accept=false;r.can_start=body.status==='accepted';r.baseline_metrics={captured_at:analysisTestTime,snapshot_hash:'synthetic',values:[]}}
  r.version++;return json(r);
 }
 if(path==='/api/global-agent/bootstrap')return json({profiles:[profile],threads:[thread],knowledge:{root:'synthetic',approved_directories:[],active_documents:0,inactive_documents:0,chunks:0,last_indexed_at:null}});
 if(path==='/api/global-agent/customer-context-options')return json(contexts);
 if(path.startsWith('/api/customer-context/threads/')&&path.endsWith('/analysis'))return json(null);
 if(path==='/api/global-agent/threads'||path==='/api/global-agent/threads/qa-thread')return json(thread);
 if(path.endsWith('/context')){thread.context_scope=body.context_scope;thread.customer_context=contexts.find(c=>c.conversation_id===body.conversation_id)||null;thread.revision++;return json(thread)}
 if(path.endsWith('/messages')){qa.modelCalls++;thread.messages.push({id:'qa-user',thread_id:thread.id,role:'user',content:body.content,status:'completed',run_id:null,run_elapsed_ms:null,answer:null,citations:[],tool_references:[],created_at:analysisTestTime});thread.active_run={...run};thread.revision++;return json(run)}
 if(path.endsWith('/trace'))return json(trace());
 if(path.endsWith('/cancel')){qa.finishRun('cancelled');return json(run)}
 if((path==='/api/predictions/latest'||path==='/api/predictions'))return json({run:{id:null,results:[],generated_at:analysisTestTime,is_stale:false},workload:null,cashflow:null,high_risk_projects:[],priority_customers:[]});
 if(path.includes('calibration'))return json({run_id:null,record_status:'live',cutoff_at:analysisTestTime,input_snapshot_hash:'synthetic',sample_count:0,sufficiency:'insufficient',thresholds:{exploratory_min:3,actionable_min:5},algorithm_version:'synthetic',metrics:{signed_bias_hours:null,mae_hours:null,overrun_rate:null,interval_coverage:null,multiplier_median:null,multiplier_lower:null,multiplier_upper:null},sample_start_at:null,sample_end_at:null,candidates:[],is_stale:false});
 return json({detail:'S07 fixture endpoint not implemented'},503);
};
createRoot(document.getElementById('root')).render(<React.StrictMode><FullApp/></React.StrictMode>);
`;
const plugin=`plugins:[{name:'s07-frozen-background',setup(build){build.onLoad({filter:/[\\/]src[\\/]App\\.tsx$/},args=>({contents:readFileSync(args.path,'utf8').replace('<AppShell>','<AppShell backgroundTest={(window as any).__analysisAuroraTest}>'),loader:'tsx'}));}}],`;
const fixture=original.replace("import {referenceProductFixture}","import {analysisFixture,analysisTestTime} from './tests/aurora-analysis-fixture';\nimport {referenceProductFixture}").replace(target,states).replace('const bundle=await build({','const bundle=await build({'+plugin);
const output=resolve('tests/.aurora-analysis-preview-generated.mjs');writeFileSync(output,fixture);await import(output);
