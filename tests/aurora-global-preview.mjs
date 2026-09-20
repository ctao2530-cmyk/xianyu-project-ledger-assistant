// S08/S09 global UI adapter. All writes below are synthetic in-memory UI scenarios.
// Reuses S07 isolation guard, real App, production styles and deny-all network CSP.
import {readFileSync,writeFileSync,realpathSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
if(!realpathSync(process.cwd()).startsWith(realpathSync(tmpdir())+'/')||existsSync('.env')||existsSync('data'))throw Error('Global QA requires an isolated temporary copy');
let source=readFileSync('tests/aurora-analysis-preview.mjs','utf8');
const extra=String.raw`
// Complete synthetic statistics contract; no production values or calculations changed.
referenceProductFixture.products.forEach((product,index)=>{product.history=Array.from({length:7},(_,i)=>({date:'2026-09-'+String(12+i).padStart(2,'0'),browse_count:30+i*(15-index*3),want_count:2+i,inquiry_count:1+i,converted_project_count:i<4?0:1,revenue_total:i<4?0:100,raw_browse_count:31+i*(15-index*3),collection_views_excluded:1}));});
const globalQA=window.__globalQa={fail:false,requests:[],bindings:[],revision:1,errors:[]};
addEventListener('error',e=>globalQA.errors.push(e.message));addEventListener('unhandledrejection',e=>globalQA.errors.push(String(e.reason)));
const inheritedFetch=window.fetch;
window.fetch=async(url,opts)=>{
 const path=new URL(String(url),location.origin).pathname,method=opts?.method||'GET',body=opts?.body?JSON.parse(opts.body):{};
 const supported=path.startsWith('/api/customer-context/thread-bindings')||/^\/api\/customer-context\/conversations\/\d+\/access$/.test(path)||path==='/api/products/intelligence'||path==='/api/platform/status'||path.startsWith('/api/maintenance/');
 if(!supported)return inheritedFetch(url,opts);
 window.__qa.calls.push({url:String(url),method});
 if(method!=='GET'){globalQA.requests.push({path,method,body});if(state!=='interactive')return json({detail:'Global UI readonly fixture'},403);}
 if(globalQA.fail)return json({detail:'合成读取或保存失败，请重试'},503);
 if(path==='/api/products/intelligence')return json(referenceProductFixture);
 if(path==='/api/platform/status')return json({status:'ready',xianyu:{status:'disconnected',configured:false},wechat:{status:'unconfigured',configured:false}});
 if(path.startsWith('/api/maintenance/'))return inheritedFetch(url,opts);
 if(path.endsWith('/access'))return json({conversation_id:Number(path.split('/')[4]),revision:globalQA.revision,latest_grant:null});
 if(path==='/api/customer-context/thread-bindings'&&method==='GET')return json({configured:true,revision:globalQA.revision,legacy_binding_active:false,bindings:globalQA.bindings});
 if(method==='POST'&&path.endsWith('/revoke')){const item=globalQA.bindings.find(x=>path.includes(x.id));if(!item)return json({detail:'unknown fixture binding'},404);item.active=false;item.revision++;return json(item);}
 if(method==='POST'){
  if(!body.confirmed||body.expected_conversation_revision!==globalQA.revision)return json({detail:'合成授权版本冲突'},409);
  const binding={id:'qa-binding-'+globalQA.requests.length,active:true,revision:1,context_key_hint:'SYNTHETIC-ONLY',context_key:'synthetic-invalid-test-key',expires_at:new OriginalDate(fixedNow+body.expires_in_seconds*1000).toISOString(),grant:{conversation_id:body.conversation_id,allow_text:body.allow_text,allow_images:body.allow_images}};
  globalQA.bindings.push(binding);globalQA.revision++;return json(binding);
 }
 return json({detail:'Unsupported synthetic method'},405);
};
`;
const marker="createRoot(document.getElementById('root')).render(<React.StrictMode><FullApp/></React.StrictMode>);";
if(!source.includes(marker))throw Error('S07 adapter marker changed');
source=source.replace(marker,extra+'\n'+marker).replace('tests/.aurora-analysis-preview-generated.mjs','tests/.aurora-global-inner-generated.mjs');
const output=resolve('tests/.aurora-global-preview-generated.mjs');writeFileSync(output,source);await import(output);
