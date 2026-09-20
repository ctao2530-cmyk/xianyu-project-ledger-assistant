// S04: isolated full-App preview; synthetic records and read-only API stubs only.
import { readFileSync, writeFileSync, existsSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
const cwd=realpathSync(process.cwd());
if(!cwd.startsWith(realpathSync(tmpdir())+'/')||existsSync('.env')||existsSync('data'))throw Error('S04 requires an isolated temporary source copy');
const original=readFileSync('tests/information-architecture-preview.mjs','utf8');
const target="createRoot(document.getElementById('root')).render(location.search.includes('shell=1')?<FullApp/>:<App/>);";
if(!original.includes(target))throw Error('Baseline fixture changed');
const states=String.raw`
window.__projectAuroraTest={time:location.search.includes('motion=1')?undefined:8};
const caseName=new URLSearchParams(location.search).get('case')||'normal';
window.__projectQa={caseName,fail:caseName==='error',pending:[],errors:[],console:[],longTasks:[]};
addEventListener('error',e=>window.__projectQa.errors.push(e.message));addEventListener('unhandledrejection',e=>window.__projectQa.errors.push(String(e.reason)));
for(const key of ['error','warn']){const originalConsole=console[key];console[key]=(...args)=>{window.__projectQa.console.push({level:key,message:args.map(String).join(' ').slice(0,400)});originalConsole.apply(console,args)}}
new PerformanceObserver(list=>window.__projectQa.longTasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true});
const baseProject=snapshot.projects[0];
Object.assign(baseProject,{name:'合成客户工作台改造',updatedAt:'2026-09-17T03:00:00Z',requirementVersionId:2,notes:'保留客户消息、正式需求与交付记录，调整前端展示。'});
snapshot.projects=[baseProject];
snapshot.customers.push({...customer,id:'qa-customer-b',name:'合成客户乙',source:'wechat',channelIdentities:[]});
const total=caseName==='many'?105:12;
for(let i=1;i<total;i++)snapshot.projects.push({...baseProject,id:'qa-project-'+i,name:['合成订单交付系统','合成移动端适配','合成项目资料整理','合成数据看板'][i%4]+' '+i,customerId:i%2?'qa-customer-b':customer.id,totalAmount:1000+i*350,updatedAt:i===1?null:'2026-09-'+String(17-i%12).padStart(2,'0')+'T02:00:00Z',dueDate:'2026-09-'+String(18+i%12).padStart(2,'0'),status:['pending','in_progress','delivered','completed'][i%4],requirementVersionId:undefined,notes:'隔离测试项目，任务、验收和回款分别记录。'});
snapshot.projects.push({...baseProject,id:'qa-personal',name:'合成个人工具',projectKind:'personal',customerId:'',totalAmount:0});
snapshot.tasks.push({id:'qa-task-pending',projectId:'qa-project',title:'合成移动端验证',status:'in_progress',startDate:'2026-09-16',dueDate:'2026-09-20',estimatedHours:4,actualHours:1});
snapshot.attachments.push({id:'qa-attachment',projectId:'qa-project',name:'合成交付说明.txt',type:'document',size:'18 B',uploadedAt:'2026-09-17T02:00:00Z',dataUrl:'data:text/plain;charset=utf-8,Synthetic%20delivery'});
snapshot.settlementIssues.push({id:'qa-terminal',projectId:'qa-project-10',customerId:customer.id,type:'project_cancelled',reason:'合成终止测试',occurredAt:'2026-09-16',refundAmount:0,receivableImpact:0});
if(caseName==='empty'){snapshot.projects=[];snapshot.tasks=[];snapshot.payments=[];snapshot.expenses=[];snapshot.attachments=[];snapshot.settlementIssues=[];}
if(caseName==='long')baseProject.name='合成客户多端经营项目与交付记录'.repeat(5);
const previousFetch=window.fetch;
window.fetch=async(url,opts)=>{
 const u=String(url),path=new URL(u,location.origin).pathname;
 if(opts?.method&&opts.method!=='GET')return previousFetch(url,opts);
 if(path.includes('/requirement-blueprints')){
  window.__qa.calls.push({url:u,method:'GET'});
  if(caseName==='loading')await new Promise(resolve=>window.__projectQa.pending.push(resolve));
  if(window.__projectQa.fail)return new Response(JSON.stringify({detail:'合成正式需求读取失败'}),{status:503});
  const id=decodeURIComponent(path.split('/')[3]);
  return new Response(JSON.stringify(id==='qa-project'?[{...formalVersion,version:2,project_id:id,customer_id:customer.id,case_id:'qa-case',metrics:{capabilities:1,stages:1,deliverables:2,criteria:2,questions:1}}]:[]),{headers:{'Content-Type':'application/json'}});
 }
 if(path.endsWith('/acceptance')){
  window.__qa.calls.push({url:u,method:'GET'});
  return new Response(JSON.stringify({revision:1,items:[{request_id:'synthetic-rejected',case_id:'qa-case',version:2,decision:'rejected',reviewer:'合成验收人',evidence:'合成验收证据：仍需补充移动端截图。',recorded_at:'2026-09-17T06:00:00Z'}],has_more:false}),{headers:{'Content-Type':'application/json'}});
 }
 return previousFetch(url,opts);
};
createRoot(document.getElementById('root')).render(<React.StrictMode><FullApp/></React.StrictMode>);
`;
const plugin=`plugins:[{name:'s04-frozen-background',setup(build){build.onLoad({filter:/[\\/]src[\\/]App\\.tsx$/},args=>({contents:readFileSync(args.path,'utf8').replace('<AppShell>','<AppShell backgroundTest={(window as any).__projectAuroraTest}>'),loader:'tsx'}));}}],`;
const fixture=original.replace(target,states).replace('const bundle=await build({','const bundle=await build({'+plugin);
const output=resolve('tests/.aurora-project-preview-generated.mjs');writeFileSync(output,fixture);await import(output);
