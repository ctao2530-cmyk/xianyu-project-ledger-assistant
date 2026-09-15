import { useEffect, useRef, useState } from 'react';
import { localApi } from '../data/localApi';
import type { CustomerImageArchiveView, ConversationMessage } from '../data/localPlatformService';
import { CustomerWorkflowDialog } from './CustomerWorkflowDialog';
import { ImageLightbox, OriginalPreview } from './CustomerImageLibrary';
import { MessageTimelineEntry } from './workspace/MessageTimelineEntry';
import { messageTime } from './workspace/messageTimeline';

type Hit = { id: number; conversation_id: number; snippet: string; received_at: string; direction: string };
type Page = { items: Hit[]; total: number; has_more: boolean; next_before_message_id: number | null };
type Context = { message_id: number; conversation_id: number; messages: ConversationMessage[] };
function Highlight({text, query}: {text:string;query:string}) {
  const index = text.toLowerCase().indexOf(query.toLowerCase());
  return query && index >= 0 ? <>{text.slice(0,index)}<mark>{text.slice(index,index+query.length)}</mark>{text.slice(index+query.length)}</> : <>{text}</>;
}
export function CustomerMessageSearch({ customerId, conversationId, customerName, initialConversationIds, onClose }: {
  customerId?: string; conversationId: number; customerName: string; initialConversationIds?: number[]; onClose: () => void;
}) {
  const [members,setMembers] = useState<Array<{id:number;item_title:string|null}>>([]);
  const [selected,setSelected] = useState(initialConversationIds || [conversationId]);
  const [query,setQuery] = useState('');
  const [dates,setDates] = useState({from:'',to:''});
  const [page,setPage] = useState<Page|null>(null);
  const [context,setContext] = useState<Context|null>(null);
  const [image,setImage] = useState<CustomerImageArchiveView|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [memberError,setMemberError] = useState('');
  const request = useRef(0);
  useEffect(() => { let live=true; if(customerId) void localApi<{conversations:Array<{id:number;item_title:string|null}>}>(`/api/customers/${encodeURIComponent(customerId)}/conversation-group-candidates`).then(data=>{if(live)setMembers(data.conversations)}).catch(()=>{if(live)setMemberError('关联会话暂不可用，仍可搜索当前选定范围。')}); return()=>{live=false;request.current++;}; },[customerId]);
  const scope = () => { const params=new URLSearchParams(); if(customerId){params.set('customer_id',customerId);selected.forEach(id=>params.append('conversation_ids',String(id)));}else params.set('conversation_id',String(conversationId));return params; };
  const invalidate = () => { request.current++;setBusy(false);setPage(null);setContext(null);setError(''); };
  const search = async (more=false) => {
    const seq=++request.current;setBusy(true);setError('');setContext(null);
    const params=scope();params.set('query',query.trim());params.set('limit','30');if(dates.from)params.set('date_from',dates.from);if(dates.to)params.set('date_to',dates.to);if(more&&page?.next_before_message_id)params.set('before_message_id',String(page.next_before_message_id));
    try {const data=await localApi<Page>(`/api/customer-message-search?${params}`);if(seq===request.current)setPage(previous=>more&&previous?{...data,items:[...previous.items,...data.items]}:data);}catch(e){if(seq===request.current)setError(e instanceof Error?e.message:'搜索失败，请重试');}finally{if(seq===request.current)setBusy(false);}
  };
  const showContext = async (hit:Hit) => {
    const seq=++request.current;setBusy(true);setError('');const params=scope();params.set('message_id',String(hit.id));
    try{const data=await localApi<Context>(`/api/customer-message-search/context?${params}`);if(seq===request.current)setContext(data);}catch(e){if(seq===request.current)setError(e instanceof Error?e.message:'上下文读取失败');}finally{if(seq===request.current)setBusy(false);}
  };
  return <CustomerWorkflowDialog title={`搜索消息 · ${customerName}`} className="message-search-dialog" onClose={onClose} suspended={Boolean(image)}>
    <div className="message-search-content">
      <p className="reading-note">仅搜索所选客户已保存到本机的消息；未同步的平台历史不在结果中。</p>
      <form className="message-search-form" onSubmit={event=>{event.preventDefault();void search();}}>
        <label className="message-keyword">消息关键词<input autoFocus value={query} maxLength={200} placeholder="输入要查找的消息内容" onChange={event=>{invalidate();setQuery(event.target.value);}}/></label>
        <label>开始日期<input type="date" value={dates.from} onChange={event=>{invalidate();setDates({...dates,from:event.target.value});}}/></label><label>结束日期<input type="date" value={dates.to} onChange={event=>{invalidate();setDates({...dates,to:event.target.value});}}/></label>
        <button className="primary" type="submit" disabled={busy||!query.trim()||!selected.length}>搜索</button>
      </form>
      {customerId&&<details className="message-search-members"><summary>搜索范围 · 已选 {selected.length} 条会话 · 日期按北京时间</summary>{memberError&&<p role="status">{memberError}</p>}{members.map(member=><label key={member.id}><input type="checkbox" checked={selected.includes(member.id)} onChange={event=>{invalidate();setSelected(current=>event.target.checked?[...current,member.id]:current.filter(id=>id!==member.id));}}/>会话 #{member.id} · {member.item_title||'商品来源未知'}</label>)}</details>}
      {error&&<p role="alert" className="customer-workflow-error">{error}</p>}{busy&&<p role="status">正在读取本机消息…</p>}
      {context ? <section className="message-search-context"><button type="button" onClick={()=>setContext(null)}>返回搜索结果</button><p>原会话 #{context.conversation_id} · 命中消息及前后各最多 5 条</p><div className="search-context-messages">{context.messages.map((message,i)=><div className={message.id===context.message_id?'search-message-hit':''} key={message.id}><MessageTimelineEntry receivedAt={message.received_at} previousAt={context.messages[i-1]?.received_at} direction={message.direction} media={(message.images||message.customer_images||[]).length>0?<div className="message-image-grid">{(message.images||message.customer_images||[]).map(item=><button key={item.id} type="button" onClick={()=>setImage(item)} aria-label="查看搜索消息图片"><OriginalPreview image={item} compact/></button>)}</div>:undefined}>{message.content&&message.content!=='[图片]'?<p><Highlight text={message.content} query={query}/></p>:null}</MessageTimelineEntry></div>)}</div></section> : page ? <section className="message-search-results" aria-label="消息搜索结果"><p role="status">共 {page.total} 条匹配消息</p>{page.items.map(hit=><button type="button" key={hit.id} onClick={()=>void showContext(hit)}><span><time>{messageTime(hit.received_at,true)}</time> · 会话 #{hit.conversation_id} · {hit.direction==='outbound'?'我方':'客户'}</span><p><Highlight text={hit.snippet} query={query}/></p><small>查看前后文 →</small></button>)}{!page.items.length&&<p>没有匹配消息，可调整关键词、日期或会话范围。</p>}{page.has_more&&<button type="button" disabled={busy} onClick={()=>void search(true)}>加载更多结果</button>}</section>:!busy&&<p className="reading-note">输入关键词后搜索，不会修改消息或未读状态。</p>}
    </div>
    <ImageLightbox image={image} onClose={()=>setImage(null)} onDeleted={id=>{setImage(null);setContext(current=>current?{...current,messages:current.messages.map(message=>({...message,images:(message.images||message.customer_images||[]).map(item=>item.id===id?{...item,capture_status:'deleted'}:item)}))}:null);}} onOpenConversation={id=>{onClose();window.location.hash=encodeURIComponent(`客户消息/conversation/${id}`);}}/>
  </CustomerWorkflowDialog>;
}
