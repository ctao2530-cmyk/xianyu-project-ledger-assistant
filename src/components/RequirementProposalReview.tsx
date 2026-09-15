import {useEffect, useState} from 'react';
import {localPlatformService, type RequirementProposalView} from '../data/localPlatformService';

export function RequirementProposalReview({customerId, onConfirmed}: {customerId:string; onConfirmed:(caseId:string)=>void}) {
  const [rows,setRows]=useState<RequirementProposalView[]>([]);
  const [checked,setChecked]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{let active=true;setRows([]);setChecked(null);
    localPlatformService.requirementProposals(customerId).then(r=>{if(active)setRows(r);}).catch(e=>{if(active)setError(String(e.message));});
    return()=>{active=false;};},[customerId]);
  async function confirm(row:RequirementProposalView){setBusy(true);setError('');try{
    const result=await localPlatformService.confirmRequirementProposal({request_id:row.request_id,review_token:row.review_token,expected_version:row.expected_version,confirmed:true});
    setRows(r=>r.filter(v=>v.id!==row.id));setChecked(null);onConfirmed(result.case_id);
  }catch(e){setError(e instanceof Error?e.message:'确认失败');}finally{setBusy(false);}}
  return <section className="requirement-proposal-review" aria-label="GPT 拟写入需求">
    {rows.map(row=><article key={row.id}><h3>GPT 拟写入：{row.document.title} · V{row.expected_version+1}</h3><p>{row.document.change_summary}</p>
      <p>这是待确认提案，尚未写入正式需求。不会修改金额、客户关系、项目状态或任务完成状态。</p>
      <details><summary>查看完整蓝图与版本差异</summary>
        {Object.entries(row.diff).map(([kind,groups])=><section key={kind}><h4>{{objectives:'项目目标',capabilities:'功能能力',stages:'实施阶段',acceptance_gates:'交付验收',risks:'风险'}[kind]||kind}</h4>{Object.entries(groups).map(([status,nodes])=><div key={status}><b>{{added:'新增',modified:'修改',removal_proposed:'删除建议',unchanged:'未变化'}[status]||status} · {nodes.length}</b>{nodes.map(n=><p key={n.id}>{n.id}：{String(n.before?.title||'')} → {String(n.after?.title||'删除建议')}</p>)}</div>)}</section>)}
        <pre>{JSON.stringify(row.document,null,2)}</pre>
      </details>
      <label><input type="checkbox" checked={checked===row.id} onChange={e=>setChecked(e.target.checked?row.id:null)}/>我已核对完整内容、来源证据及删除建议，确认写入正式新版本</label>
      <button type="button" disabled={busy||checked!==row.id} onClick={()=>void confirm(row)}>{busy?'正在保存…':'确认写入正式需求'}</button>
    </article>)}
    {error&&<p role="alert">{error}</p>}
  </section>;
}
