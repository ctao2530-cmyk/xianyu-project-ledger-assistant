// S02 synthetic states on the existing App; no database, channel or model access.
import { readFileSync, writeFileSync, existsSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
const cwd = realpathSync(process.cwd());
if (!cwd.startsWith(realpathSync(tmpdir()) + '/') || existsSync('.env') || existsSync('data')) throw Error('S02 requires an isolated temporary source copy');
const original = readFileSync('tests/information-architecture-preview.mjs', 'utf8');
const target = "createRoot(document.getElementById('root')).render(location.search.includes('shell=1')?<FullApp/>:<App/>);";
if (!original.includes(target)) throw Error('Baseline fixture changed; review adapter');
const states = String.raw`
const homeCase=new URLSearchParams(location.search).get('case')||'normal';
window.__homeAuroraTest={time:location.search.includes('motion=1')?undefined:8};
if(homeCase==='empty') for(const key of ['customers','projects','payments','expenses','tasks','logs','settlementIssues','attachments']) snapshot[key]=[];
if(homeCase==='zero') {snapshot.payments=[];snapshot.expenses=[];snapshot.projects.forEach(p=>p.totalAmount=0);}
if(homeCase==='long') {snapshot.settings.profileName='合成超长账户名称用于验证标题折行与布局安全';snapshot.projects[0].name='合成企业客户需求交付与多渠道经营管理系统升级项目'.repeat(3);}
snapshot.settings.notificationsEnabled=homeCase==='reminders';
window.__homeQa={case:homeCase,fail:homeCase==='error',pending:[],snapshot};
const previousFetch=window.fetch;
window.fetch=async(url,opts)=>{
  const u=String(url);
  if(opts?.method&&opts.method!=='GET')return previousFetch(url,opts);
  if(u.startsWith('/api/workbench/actions')) {
    if(homeCase==='loading') await new Promise(resolve=>window.__homeQa.pending.push(resolve));
    if(window.__homeQa.fail){window.__qa.calls.push({url:u,method:'GET'});return new Response('{}',{status:503});}
    const response=await previousFetch(url,opts);const data=await response.json();
    if(homeCase==='empty'||homeCase==='zero')data.items=[];
    if(homeCase==='long')data.items.forEach(x=>{x.title='合成超长客户与需求名称用于验证中文以及UnbrokenEnglishTextWithoutSpaces'.repeat(3)});
    if(homeCase==='many'){
      const offset=Number(new URL(u,location.origin).searchParams.get('offset')||0);
      data.items=Array.from({length:Math.min(100,105-offset)},(_,i)=>({id:'qa-more-'+(offset+i),category:'客户消息',title:'合成分页会话 '+(offset+i+1),detail:'合成未读消息',updatedAt:'2026-09-09T10:00:00Z',href:'#'+encodeURIComponent('客户消息/conversation/1')}));
      Object.assign(data,{offset,total:105,hasMore:offset+100<105});
    }else Object.assign(data,{total:data.items.length,hasMore:false});
    return new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
  }
  // Customer-reminder case: keep the known incomplete product fixture unavailable.
  if(homeCase==='reminders'&&u==='/api/products/intelligence'){window.__qa.calls.push({url:u,method:'GET'});return new Response('{}',{status:503});}
  if(homeCase==='reminders'&&u==='/api/operations/summary'){
    window.__qa.calls.push({url:u,method:'GET'});
    return new Response(JSON.stringify({unread:3,unread_conversations:2,pending_replies:1,first_pending_conversation_id:1}),{headers:{'Content-Type':'application/json'}});
  }
  return previousFetch(url,opts);
};
createRoot(document.getElementById('root')).render(<React.StrictMode><FullApp/></React.StrictMode>);
`;
// Instrument only the compiled fixture. Production App/Shell have no QA time entry.
const plugin = `plugins:[{name:'s02-frozen-background',setup(build){build.onLoad({filter:/[\\/]src[\\/]App\\.tsx$/},args=>({contents:readFileSync(args.path,'utf8').replace('<AppShell>','<AppShell backgroundTest={(window as any).__homeAuroraTest}>'),loader:'tsx'}));}}],`;
const fixture = original.replace(target, states).replace('const bundle=await build({', 'const bundle=await build({' + plugin);
const output = resolve('tests/.aurora-workbench-preview-generated.mjs');
writeFileSync(output, fixture);
await import(output);
