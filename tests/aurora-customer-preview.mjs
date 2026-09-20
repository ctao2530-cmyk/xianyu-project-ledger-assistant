// S03: synthetic read-only customer UI fixture. Never run against a business directory.
import { readFileSync, writeFileSync, existsSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
const cwd = realpathSync(process.cwd());
if (!cwd.startsWith(realpathSync(tmpdir()) + '/') || existsSync('.env') || existsSync('data')) throw Error('S03 requires an isolated temporary source copy');
const original = readFileSync('tests/information-architecture-preview.mjs', 'utf8');
const target = "createRoot(document.getElementById('root')).render(location.search.includes('shell=1')?<FullApp/>:<App/>);";
if (!original.includes(target)) throw Error('Baseline fixture changed; review adapter');
const states = String.raw`
window.__customerAuroraTest={time:location.search.includes('motion=1')?undefined:8};
const caseName=new URLSearchParams(location.search).get('case')||'normal';
window.__customerQa={caseName,fail:(caseName==='error'||caseName==='archive-error'),pending:[],errors:[],console:[],longTasks:[]};
addEventListener('error',e=>window.__customerQa.errors.push(e.message));
addEventListener('unhandledrejection',e=>window.__customerQa.errors.push(String(e.reason)));
for(const key of ['error','warn']){const fn=console[key];console[key]=(...args)=>{window.__customerQa.console.push({level:key,message:args.map(String).join(' ').slice(0,500)});fn.apply(console,args)}}
new PerformanceObserver(list=>window.__customerQa.longTasks.push(...list.getEntries().map(x=>({start:x.startTime,duration:x.duration})))).observe({type:'longtask',buffered:true});
snapshot.settings.notificationsEnabled=false;snapshot.settings.profileName='合成经营者';
Object.assign(customer,{channelIdentities:[{channel:'xianyu',conversationId:1}],tags:['页面重构','保留业务'],currentNeed:'调整客户工作区的布局和阅读层级，保留原始记录与人工确认。',nextAction:'核对需求版本与已有项目。'});
snapshot.customers.push({id:'qa-other',name:'合成客户乙',source:'wechat',level:'B',channelIdentities:[{channel:'wechat',conversationId:2}],tags:['移动适配'],currentNeed:'客户乙的独立需求，不属于客户甲。',followUpStatus:'contacted'},{id:'qa-unlinked',name:'合成未关联档案',source:'manual',level:'C',followUpStatus:'contacted'});
if(caseName==='group')customer.channelIdentities.push({channel:'xianyu',conversationId:3});
if(caseName==='empty'){snapshot.customers=[];snapshot.projects=[];}
if(caseName==='long')customer.name='合成长名称客户与企业数字化经营系统'.repeat(3);
const response=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
const previousFetch=window.fetch;
const message=(id,cid)=>({id,content:'合成会话 '+cid+' · 消息 '+id+'：核对布局、需求与交付范围，原记录保持独立。',sender_name:cid===1?'合成客户甲':'合成客户乙',direction:id%3===0?'outbound':'inbound',received_at:new Date(Date.UTC(2026,8,17,1,Math.floor(id/2))).toISOString(),images:[]});
window.fetch=async(url,opts)=>{
 const u=String(url),path=new URL(u,location.origin).pathname;
 if(opts?.method&&opts.method!=='GET')return previousFetch(url,opts);
 const log=()=>window.__qa.calls.push({url:u,method:'GET'});
 if(path==='/api/conversations'){
  log();if(caseName==='loading')await new Promise(resolve=>window.__customerQa.pending.push(resolve));
  if(caseName==='empty')return response([]);
  const channel=new URL(u,location.origin).searchParams.get('channel');
  return response(Array.from({length:caseName==='many'?120:8},(_,i)=>({id:i+1,channel:i===1?'wechat':'xianyu',customer_name:'合成会话 '+(i+1),item_title:'合成商品 '+(i+1),unread_count:i<2?i+1:0,last_message:'合成消息，用于检验阅读与客户隔离',last_message_at:'2026-09-17T02:00:00Z'})).filter(r=>!channel||channel==='all'||r.channel===channel));
 }
 if(path==='/api/phrase-library'){log();return response({revision:1,idempotent:false,categories:['初次咨询','开工前','完工后'].map((name,i)=>({id:'synthetic-category-'+i,category_key:'synthetic-'+i,name,source:'default',position:i,active:true,phrases:[],created_at:'2026-09-17T00:00:00Z',updated_at:'2026-09-17T00:00:00Z'}))});}
 if(path.endsWith('/conversation-group-candidates')){log();const own=path.includes('qa-customer');return response({conversations:(own?(caseName==='group'?[1,3]:[1]):[2]).map(id=>({id,channel:id===2?'wechat':'xianyu',customer_name:'合成会话 '+id,item_id:'synthetic-item-'+id,item_external_id:'synthetic-external-'+id,item_title:'合成商品 '+id})),groups:caseName==='group'&&own?[{id:'synthetic-group',title:'合成确认会话组',revision:1,active:true,conversation_ids:[1,3],customer_id:'qa-customer'}]:[]});}
 if(path==='/api/conversation-groups/synthetic-group/timeline'){log();const params=new URL(u,location.origin).searchParams,total=params.get('item_id')?65:130,offset=Number(params.get('offset')||0),limit=Number(params.get('limit')||100);return response({messages:Array.from({length:Math.min(limit,total-offset)},(_,i)=>{const n=offset+i+1,cid=params.get('item_id')==='synthetic-item-3'?3:params.get('item_id')?1:n%2?1:3;return {...message(n,cid),conversation_id:cid,source_item_external_id:'synthetic-external-'+cid};}),total_count:total,has_more:offset+limit<total});}
 if(path==='/api/customer-images'&&caseName==='archive-error'&&window.__customerQa.fail){log();return response({detail:'合成归档列表读取失败'},503);}
 const detail=/^\/api\/conversations\/(\d+)$/.exec(path);
 if(detail){
  log();const id=Number(detail[1]);if(caseName==='error'&&window.__customerQa.fail)return response({detail:'合成会话读取失败，请重试'},503);
  if(caseName==='loading-detail')await new Promise(resolve=>window.__customerQa.pending.push(resolve));
  const data={id,channel:id===2?'wechat':'xianyu',customer_name:'合成会话 '+id,linked_customer_id:id===1?'qa-customer':id===2?'qa-other':caseName==='group'&&id===3?'qa-customer':null,item:{title:'合成商品 '+id},messages:Array.from({length:caseName==='history'?30:7},(_,i)=>message(i+101,id)),has_older_messages:caseName==='history'};
  if(caseName==='long')data.messages[1].content='合成中文长内容与UnbrokenEnglishTextWithoutSpaces'.repeat(25);
  if(caseName==='images'&&id===1)data.messages=[message(101,id),{...message(102,id),content:'[图片]',images:[syntheticImage]},{...message(103,id),content:'[图片]',images:[{...syntheticImage,id:'synthetic-failed',capture_status:'failed',error_message:'隔离测试下载超时'}]}];
  return response(data);
 }
 if(/^\/api\/conversations\/\d+\/messages$/.test(path)){log();const id=Number(path.split('/')[3]);return response({messages:Array.from({length:30},(_,i)=>message(i+71,id)),has_more:false});}
 if(path==='/api/global-agent/customer-context-options'){log();return response([1,2].map(id=>({conversation_id:id,customer_id:id===1?'qa-customer':'qa-other',customer_name:id===1?'合成客户甲':'合成客户乙',channel:id===1?'xianyu':'wechat',item_title:'合成商品 '+id,text_message_count:7,image_message_count:id===1?1:0})));}
 if(path==='/api/customer-context/thread-bindings'){log();if(caseName==='auth-error')return response({detail:'合成授权状态不可用'},503);return response({configured:true,revision:1,legacy_binding_active:false,bindings:caseName==='expired'?[{id:'synthetic-expired',active:false,revision:1,context_key_hint:'synthetic-expired',expires_at:'2026-09-16T00:00:00Z',grant:{conversation_id:1}}]:[]});}
 if(/^\/api\/customer-context\/conversations\/\d+\/access$/.test(path)){log();return response({conversation_id:Number(path.split('/')[4]),revision:1,latest_grant:null});}
 return previousFetch(url,opts);
};
createRoot(document.getElementById('root')).render(<React.StrictMode><FullApp/></React.StrictMode>);
`;
const plugin = `plugins:[{name:'s03-frozen-background',setup(build){build.onLoad({filter:/[\\/]src[\\/]App\\.tsx$/},args=>({contents:readFileSync(args.path,'utf8').replace('<AppShell>','<AppShell backgroundTest={(window as any).__customerAuroraTest}>'),loader:'tsx'}));}}],`;
const fixture=original.replace(target,states).replace('const bundle=await build({','const bundle=await build({'+plugin);
const output=resolve('tests/.aurora-customer-preview-generated.mjs');writeFileSync(output,fixture);await import(output);
