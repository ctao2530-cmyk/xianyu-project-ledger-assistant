/** Synthetic, memory-only UI server. No backend, proxy, .env, or production data. */
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
const require=createRequire(import.meta.url);
const {build}=createRequire(require.resolve('vite'))('esbuild');

const fixture = String.raw`
import React from 'react';
import {createRoot} from 'react-dom/client';
import {CustomerMessagesPage} from './src/pages/CustomerMessagesPage';
import './src/styles.css';
import './src/liquid-glass-system.css';
import './src/pages/other-pages.css';
const now='2026-09-07T08:00:00Z';
const conversations=[1,2,3].map((id)=>({id,channel:id===3?'wechat':'xianyu',customer_name:id===3?'合成客户乙':'合成客户甲',item_title:'合成商品'+id,unread_count:0,last_message:id===3?'[图片]':'合成验收消息 '+id,last_message_at:now}));
const image={id:'synthetic-image',conversation_id:1,message_id:101,channel:'xianyu',customer_name:'合成客户甲',received_at:now,captured_at:now,mime_type:'image/png',original_name:'synthetic.png',file_size:700,width:400,height:260,integrity_verified:true,content_url:'/synthetic.svg',preview_url:'/synthetic.svg',download_url:'/synthetic.svg',capture_status:'stored'};
window.__qa={calls:[],errors:[],events:[],fail:null,delay:{},images:[image],conversations,groups:[]};
window.addEventListener('error',e=>window.__qa.errors.push(String(e.message)));
window.addEventListener('unhandledrejection',e=>window.__qa.errors.push(String(e.reason)));
window.fetch=async(input,opts)=>{
 const url=new URL(typeof input==='string'?input:input.url,location.href), path=url.pathname;
 window.__qa.calls.push({path,query:url.search,method:opts?.method||'GET',body:opts?.body?JSON.parse(opts.body):undefined});
 if(window.__qa.delay[path]) await new Promise(r=>setTimeout(r,window.__qa.delay[path]));
 if(window.__qa.fail===path) return new Response(JSON.stringify({detail:'合成失败：归档读取暂不可用'}),{status:503});
 let body;
 if(path==='/api/conversations') body=window.__qa.conversations;
 else if(/^\/api\/conversations\/\d+$/.test(path)) {const id=Number(path.split('/').pop()),c=conversations.find(x=>x.id===id);body={...c,external_id:'synthetic-'+id,customer_id:id===3?'synthetic-b':'synthetic-a',linked_customer_id:id===3?'qa-b':'qa-a',item:{external_id:'synthetic-item-'+id,title:c.item_title},messages:[{id:id*100,sender_name:c.customer_name,direction:'inbound',content:id===3?'[图片]':'这是合成验收文字，不包含客户数据。',received_at:now,status:'new',risk_flags:[],message_type:id===3?'image':'text',images:[]},{id:id*100+1,sender_name:c.customer_name,direction:'inbound',content:'[图片]',received_at:now,status:'new',risk_flags:[],message_type:'image',images:[{...image,conversation_id:id,message_id:id*100+1}]}],has_older_messages:false,drafts:[],ai_task:null,pending_message_id:null};}
 else if(path==='/api/customer-images') {const q=(url.searchParams.get('q')||url.searchParams.get('search')||'').toLowerCase(),items=window.__qa.images.filter(x=>!q||x.original_name.toLowerCase().includes(q)),offset=Number(url.searchParams.get('offset')||0),limit=Number(url.searchParams.get('limit')||100);body={items:items.slice(offset,offset+limit),total:items.length,has_more:offset+limit<items.length};}
 else if(path==='/api/conversations/history-import/search') body=conversations.slice(0,2).map(c=>({external_conversation_id:'synthetic-'+c.id,customer_name:c.customer_name,item_title:c.item_title,last_message:c.last_message,last_message_at:now,direction:'inbound',existing_conversation_id:c.id,known_message_count:2}));
 else if(path==='/api/conversations/history-import/preview') {const p=JSON.parse(opts.body);window.__qa.historyPreview=p;body={token:'synthetic-history-preview',expires_at:'2099-01-01T00:00:00Z',external_conversation_id:p.external_conversation_id,customer_name:'合成客户甲',item:{external_id:'synthetic-item-1',title:'合成商品1'},item_warning:null,messages:[{platform_message_id:'qa-history',sender_name:'合成客户甲',direction:'inbound',message_type:'image',content:'[图片]',received_at:now,import_status:'new'}],platform_message_count:1,existing_count:0,new_count:1,image_candidate_count:3,unsupported_count:0,history_scope:p.history_scope,has_more:p.history_scope==='page'&&!p.continuation_token,next_continuation_token:p.continuation_token?null:'synthetic-page-2',history_complete:!!p.continuation_token||p.history_scope==='full'};}
 else if(path==='/api/conversations/history-import/commit') {const p=JSON.parse(opts.body);if(p.preview_token!=='synthetic-history-preview'||p.mark_latest_pending!==false)return new Response('{}',{status:409});body={conversation_id:1,created_conversation:false,platform_message_count:1,imported_count:1,existing_count:0,pending_message_id:null,draft_task_queued:false,draft_task_id:null,image_candidate_count:3,image_stored_count:2,image_failed_count:1,idempotent:false,has_more:window.__qa.historyPreview.history_scope==='page'&&!window.__qa.historyPreview.continuation_token,next_continuation_token:window.__qa.historyPreview.continuation_token?null:'synthetic-page-2',history_complete:!!window.__qa.historyPreview.continuation_token};}
 else if(path==='/api/customer-images/status') body={state:'healthy',stored_count:1,attention_count:0,failed_count:0,pending_count:0,missing_count:0,candidate_count:0,channel_counts:{xianyu:1},last_captured_at:now,message:'合成原图已归档'};
 else if(path==='/api/customer-images/filters') body={channels:['xianyu','wechat'],conversations:conversations.map(c=>({...c,image_count:1})),items:[]};
 else if(path==='/api/conversation-groups/candidates') body={customer_id:'qa-a',groups:[],candidates:conversations.slice(0,2).map(x=>({...x,identity_basis:'confirmed_identity',source_unknown:false})),revision:0};
 else if(path==='/api/customers/qa-a/conversation-group-candidates') body={conversations:conversations.slice(0,2).map(x=>({...x,conversation_id:x.id,item_id:x.id})),groups:window.__qa.groups};
 else if(path==='/api/customers/qa-a/conversation-groups/preview') {const p=JSON.parse(opts.body);window.__qa.preview=p;const previous=window.__qa.groups.find(x=>x.id===p.group_id)?.conversation_ids||[];body={...p,preview_token:'synthetic-preview',revision:p.expected_revision,members:conversations.filter(x=>p.conversation_ids.includes(x.id)),effects:{added:p.conversation_ids.filter(x=>!previous.includes(x)),removed:previous.filter(x=>!p.conversation_ids.includes(x)),originals_unchanged:true,new_members_not_auto_authorized:true,previously_sent_content_not_retractable:true}};}
 else if(path==='/api/customers/qa-a/conversation-groups') {const p=JSON.parse(opts.body);if(!p.confirmed||p.request_id!==window.__qa.preview?.request_id||p.preview_token!=='synthetic-preview')return new Response(JSON.stringify({detail:'Invalid synthetic preview contract'}),{status:409});body={id:p.group_id||'qa-group',title:'合并会话',active:p.conversation_ids.length>0,status:p.conversation_ids.length?'active':'disbanded',customer_id:'qa-a',revision:p.expected_revision+1,conversation_ids:p.conversation_ids};window.__qa.groups=[body];}
 else if(path==='/api/conversation-groups/qa-group/timeline') {const g=window.__qa.groups[0];body={messages:g.conversation_ids.map(id=>({id:id*100+1,conversation_id:id,sender_name:'合成客户甲',direction:'inbound',content:'合成跨商品消息 '+id,message_type:'image',source_item_external_id:null,source_status:'unknown',received_at:now,images:[{...image,id:'synthetic-group-'+id,conversation_id:id}]})),images:[],total_count:g.conversation_ids.length,has_more:false,revision:g.revision,conversation_ids:g.conversation_ids};}
 else if(path==='/api/global-agent/customer-context-options') body=conversations.map(x=>({...x,conversation_id:x.id,customer_id:x.id===3?'qa-b':'qa-a',external_customer_id:'synthetic-'+x.id,text_message_count:x.id===3?0:1,image_message_count:1}));
 else if(path==='/api/customer-context/thread-bindings') body={bindings:[],legacy_grant:null,configured:true,auth_mode:'tunnel_binding'};
 else if(/^\/api\/customer-context\/conversations\/\d+\/access$/.test(path)) body={conversation_id:Number(path.split('/')[4]),revision:0,latest_grant:null};
 else {window.__qa.errors.push('Unhandled mock route: '+path);return new Response(JSON.stringify({detail:'未声明的合成接口被拒绝'}),{status:501});}
 return new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}});
};
class MockSocket extends EventTarget {static OPEN=1;readyState=1;constructor(){super();window.__qa.events.push(this);setTimeout(()=>this.dispatchEvent(new Event('open')),0);}close(){this.readyState=3;}}
window.WebSocket=MockSocket;
window.__qa.emit=(event)=>window.__qa.events.forEach(socket=>socket.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(event)})));
createRoot(document.getElementById('root')).render(<main style={{padding:24,maxWidth:1440,margin:'0 auto'}}><p style={{fontSize:12,color:'#625b80'}}>隔离验收 · 全部为合成数据 · 无真实后端连接</p><CustomerMessagesPage customers={[]}/></main>);
`;
const result=await build({stdin:{contents:fixture,resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,outdir:'synthetic-memory',format:'iife',jsx:'automatic',plugins:[{name:'public-only',setup(b){b.onResolve({filter:/^\/assets\//},a=>({path:process.cwd()+'/public'+a.path}));}}],loader:{'.png':'dataurl','.woff2':'dataurl','.svg':'dataurl'},define:{'process.env.NODE_ENV':'"test"'},logLevel:'silent'});
const js=result.outputFiles.find(x=>x.path.endsWith('.js')).text;
const css=result.outputFiles.find(x=>x.path.endsWith('.css'))?.text||'';
const html='<!doctype html><html lang="zh-CN"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>循营客户工作流 · 合成隔离验收</title><link rel="stylesheet" href="/bundle.css"></head><body><div id="root"></div><script src="/bundle.js"></script></body></html>';
const server=createServer((req,res)=>{
 res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; base-uri 'none'; form-action 'none'");
 const routes={'/':[html,'text/html; charset=utf-8'],'/bundle.js':[js,'text/javascript'],'/bundle.css':[css,'text/css'],'/synthetic.svg':['<svg xmlns="http://www.w3.org/2000/svg" width="400" height="260"><rect width="400" height="260" fill="#ddd4fb"/><circle cx="200" cy="110" r="65" fill="#7655ca"/><text x="95" y="225" font-size="24">Synthetic QA Image</text></svg>','image/svg+xml']};
 const entry=routes[new URL(req.url,'http://localhost').pathname];
 if(!entry){res.writeHead(404);res.end('Synthetic route unavailable');return;}
 res.setHeader('Content-Type',entry[1]);res.end(entry[0]);
});
server.listen(18879,'127.0.0.1',()=>console.log('Synthetic memory-only frontend: http://127.0.0.1:18879; no proxy/backend/network; stops after 60 minutes'));
setTimeout(()=>server.close(),60*60*1000).unref();
process.on('SIGTERM',()=>server.close());
