import { useEffect, useState } from 'react';
import { localApi } from '../../data/localApi';
interface Outcome { request_id: string; case_id: string; version: number; decision: string; reviewer: string; evidence: string; recorded_at: string; }
interface History { revision: number; items: Outcome[]; has_more: boolean; }
const labels: Record<string,string> = { accepted:'客户验收通过', rejected:'客户验收未通过', resubmitted:'重新提交验收' };
export function AcceptancePanel({projectId,caseId,version}:{projectId:string;caseId:string;version:number}) {
  const [history,setHistory]=useState<History|null>(null); const [error,setError]=useState('');
  const [busy,setBusy]=useState(false); const [refresh,setRefresh]=useState(0); const [offset,setOffset]=useState(0);
  const [reviewer,setReviewer]=useState(''); const [evidence,setEvidence]=useState(''); const [decision,setDecision]=useState('accepted'); const [confirmed,setConfirmed]=useState(false);
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID());
  const headers={'X-Yuda-Desktop':'1'};
  useEffect(()=>{setOffset(0);setHistory(null);setConfirmed(false);setEvidence('');setReviewer('');setRequestId(crypto.randomUUID());},[projectId,caseId,version]);
  useEffect(()=>{const abort=new AbortController();setError('');
    localApi<History>(`/api/projects/${encodeURIComponent(projectId)}/acceptance?offset=${offset}`,{headers,signal:abort.signal}).then(next=>{if(!abort.signal.aborted){if(!Array.isArray(next.items)||!Number.isInteger(next.revision))throw Error('验收接口版本不兼容');setConfirmed(false);setRequestId(crypto.randomUUID());setHistory(previous=>offset?{...next,items:[...(previous?.items||[]),...next.items]}:next);}}).catch(()=>{if(!abort.signal.aborted)setError('验收记录读取失败，请重试。');});
    return()=>abort.abort();},[projectId,caseId,version,refresh,offset]);
  async function submit(event:React.FormEvent) {event.preventDefault();if(!history||!confirmed||busy)return;setBusy(true);setError('');
    try {await localApi(`/api/projects/${encodeURIComponent(projectId)}/acceptance`,{method:'POST',headers,body:JSON.stringify({request_id:requestId,expected_revision:history.revision,case_id:caseId,version,decision,reviewer,evidence,confirmed})});setConfirmed(false);setEvidence('');setRequestId(crypto.randomUUID());setOffset(0);setRefresh(v=>v+1);}
    catch(e){setError(e instanceof Error?e.message:'记录失败');}finally{setBusy(false);}
  }
  const change=()=>{setRequestId(crypto.randomUUID());setConfirmed(false);};
  return <section aria-label="客户验收记录" className="acceptance-panel"><h3>客户验收记录 · 需求 V{version}</h3>
    <p>记录操作者转录的客户结论与证据说明，不代表客户在线签署；不会修改项目状态或收款。</p>
    {error&&<p role="alert">{error} <button type="button" onClick={()=>{setOffset(0);setRefresh(v=>v+1);}}>重新读取</button></p>}
    {history?.items.length===0&&<p>尚无客户验收记录。</p>}
    {history?.items.map(item=><article key={item.request_id}><strong>{labels[item.decision]} · V{item.version}{item.case_id!==caseId?'（其他需求）':''}</strong><p>{item.reviewer} · {new Date(item.recorded_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</p><p className="acceptance-evidence">{item.evidence}</p></article>)}
    {history?.has_more&&<button type="button" onClick={()=>setOffset(v=>v+20)}>加载更早记录</button>}
    <details><summary>记录新的验收结论</summary><form onSubmit={submit}>
      <label>结论<select value={decision} onChange={e=>{setDecision(e.target.value);change();}}><option value="accepted">客户验收通过</option><option value="rejected">客户验收未通过</option><option value="resubmitted">重新提交验收</option></select></label>
      <label>验收人<input required maxLength={120} value={reviewer} onChange={e=>{setReviewer(e.target.value);change();}}/></label>
      <label>证据说明<textarea required minLength={5} maxLength={4000} value={evidence} placeholder="记录客户确认时间、沟通来源和结论依据" onChange={e=>{setEvidence(e.target.value);change();}}/></label>
      <label className="acceptance-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>我已核对需求版本与结论依据，确认记录</label>
      <button type="submit" disabled={!history||!!error||!confirmed||busy}>{busy?'正在记录…':'确认记录'}</button>
    </form></details></section>;
}
