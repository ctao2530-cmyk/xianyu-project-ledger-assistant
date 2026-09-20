// S06 uses the real App with synthetic data and a network-denied browser fixture.
import { readFileSync, writeFileSync, existsSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
const cwd=realpathSync(process.cwd());
if(!cwd.startsWith(realpathSync(tmpdir())+'/')||existsSync('.env')||existsSync('data'))throw Error('S06 requires an isolated temporary source copy');
const original=readFileSync('tests/information-architecture-preview.mjs','utf8');
const target="createRoot(document.getElementById('root')).render(location.search.includes('shell=1')?<FullApp/>:<App/>);";
if(!original.includes(target))throw Error('Baseline fixture changed');
const states=String.raw`
window.__financeAuroraTest={time:location.search.includes('motion=1')?undefined:8};
const OriginalDate=Date;const fixedNow=OriginalDate.parse('2026-09-17T04:00:00Z');window.Date=class extends OriginalDate{constructor(...args){super(...(args.length?args:[fixedNow]))}static now(){return fixedNow}};
const caseName=new URLSearchParams(location.search).get('case')||'normal';
window.__financeQa={caseName,fail:caseName==='error',pending:[],console:[],longTasks:[]};
for(const key of ['error','warn']){const previous=console[key];console[key]=(...args)=>{window.__financeQa.console.push({level:key,message:args.map(String).join(' ').slice(0,500)});previous.apply(console,args)}}
new PerformanceObserver(list=>window.__financeQa.longTasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true});
const previousFetch=window.fetch;
const ledger=financeFixture(caseName);
mockLedgerService.getDashboard=async()=>{if(caseName==='loading')await new Promise(resolve=>window.__financeQa.pending.push(resolve));if(window.__financeQa.fail)throw Error('合成账本读取失败');return structuredClone(ledger)};
mockLedgerService.refreshDashboard=mockLedgerService.getDashboard;
window.fetch=async(url,opts)=>{
 const u=String(url),path=new URL(u,location.origin).pathname;
 if(opts?.method&&opts.method!=='GET')return previousFetch(url,opts);
 if(path==='/api/ledger/snapshot'){window.__qa.calls.push({url:u,method:'GET'});return new Response(JSON.stringify({revision:1,snapshot:ledger}),{headers:{'Content-Type':'application/json'}})}
 return previousFetch(url,opts);
};
createRoot(document.getElementById('root')).render(<React.StrictMode><FullApp/></React.StrictMode>);
`;
const plugin=`plugins:[{name:'s06-frozen-background',setup(build){build.onLoad({filter:/[\\/]src[\\/]App\\.tsx$/},args=>({contents:readFileSync(args.path,'utf8').replace('<AppShell>','<AppShell backgroundTest={(window as any).__financeAuroraTest}>'),loader:'tsx'}));}}],`;
const fixture=original.replace("import {referenceProductFixture}","import {financeFixture} from './tests/aurora-finance-fixture';\nimport {referenceProductFixture}").replace(target,states).replace('const bundle=await build({','const bundle=await build({'+plugin);
const output=resolve('tests/.aurora-finance-preview-generated.mjs');writeFileSync(output,fixture);await import(output);
