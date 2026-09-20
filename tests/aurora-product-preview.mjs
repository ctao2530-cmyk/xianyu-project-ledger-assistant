// S05 uses the real App with synthetic data and a network-denied browser fixture.
import { readFileSync, writeFileSync, existsSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
const cwd=realpathSync(process.cwd());
if(!cwd.startsWith(realpathSync(tmpdir())+'/')||existsSync('.env')||existsSync('data'))throw Error('S05 requires an isolated temporary source copy');
const original=readFileSync('tests/information-architecture-preview.mjs','utf8');
const target="createRoot(document.getElementById('root')).render(location.search.includes('shell=1')?<FullApp/>:<App/>);";
if(!original.includes(target))throw Error('Baseline fixture changed');
const states=String.raw`
window.__productAuroraTest={time:location.search.includes('motion=1')?undefined:8};
const caseName=new URLSearchParams(location.search).get('case')||'normal';
window.__productQa={caseName,fail:caseName==='error',pending:[],console:[],longTasks:[]};
for(const key of ['error','warn']){const previous=console[key];console[key]=(...args)=>{window.__productQa.console.push({level:key,message:args.map(String).join(' ').slice(0,500)});previous.apply(console,args)}}
new PerformanceObserver(list=>window.__productQa.longTasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true});
const previousFetch=window.fetch;
window.fetch=async(url,opts)=>{
 const u=String(url),path=new URL(u,location.origin).pathname;
 if(opts?.method&&opts.method!=='GET')return previousFetch(url,opts);
 if(path==='/api/products/intelligence'){
  window.__qa.calls.push({url:u,method:'GET'});
  if(caseName==='loading')await new Promise(resolve=>window.__productQa.pending.push(resolve));
  if(window.__productQa.fail)return new Response(JSON.stringify({detail:'合成商品读取失败'}),{status:503});
  return new Response(JSON.stringify(productFixture(caseName)),{headers:{'Content-Type':'application/json'}});
 }
 if(path==='/api/products/traffic-batches')return new Response(JSON.stringify({items:[],has_more:false,next_cursor:null}),{headers:{'Content-Type':'application/json'}});
 return previousFetch(url,opts);
};
createRoot(document.getElementById('root')).render(<React.StrictMode><FullApp/></React.StrictMode>);
`;
const plugin=`plugins:[{name:'s05-frozen-background',setup(build){build.onLoad({filter:/[\\/]src[\\/]App\\.tsx$/},args=>({contents:readFileSync(args.path,'utf8').replace('<AppShell>','<AppShell backgroundTest={(window as any).__productAuroraTest}>'),loader:'tsx'}));}}],`;
const fixture=original.replace("import {referenceProductFixture}","import {productFixture} from './tests/aurora-product-fixture';\nimport {referenceProductFixture}").replace(target,states).replace('const bundle=await build({','const bundle=await build({'+plugin);
const output=resolve('tests/.aurora-product-preview-generated.mjs');writeFileSync(output,fixture);await import(output);
