import type { RequirementBlueprint } from '../data/localPlatformService';

const layers = [['objectives', '项目目标'], ['capabilities', '功能能力'], ['stages', '实施阶段'], ['acceptance_gates', '交付验收']] as const;
const fields = [['implementation','实现说明'], ['work_items','工作项'], ['deliverables','交付物'], ['criteria','验收 Checklist'], ['task_key','任务标识'], ['workspace_key','工作区'], ['dependency_ids','前置依赖'], ['objective_ids','所属目标'], ['capability_ids','关联能力'], ['stage_ids','关联阶段'], ['process_tests','过程测试']] as const;
export function RequirementReadingView({ blueprint }: { blueprint: RequirementBlueprint }) {
  return <section className="requirement-reading" aria-label="四层正式需求">
    {layers.map(([key,label]) => <details className="requirement-reading-layer" open key={key}>
      <summary>{label}<span>{blueprint[key].length} 项</span></summary>
      {blueprint[key].map(node => {
        const raw = node as unknown as Record<string, unknown>;
        const refs = blueprint.evidence_refs.filter(ref => node.evidence_refs.includes(ref.id));
        return <article key={node.id}>
          <h3>{node.title}</h3>{typeof raw.description === 'string' && <p>{raw.description}</p>}
          {typeof raw.objective === 'string' && <p>{raw.objective}</p>}
          <div className="reading-node-meta"><span>{node.id}</span>{typeof raw.priority === 'string' && <span>优先级：{({must:'必须',should:'建议',could:'可选'} as Record<string,string>)[raw.priority] || raw.priority}</span>}{typeof raw.estimated_hours === 'number' && <span>预计 {raw.estimated_hours} 小时</span>}</div>
          {fields.map(([field,title]) => { const value = raw[field]; const items = Array.isArray(value) ? value.filter((v):v is string => typeof v === 'string') : typeof value === 'string' && value ? [value] : []; return items.length ? <div className="reading-node-field" key={field}><h4>{title}</h4><ul>{items.map((item,index) => <li key={index}>{item}</li>)}</ul></div> : null; })}
          {refs.length > 0 && <details><summary>来源证据 · {refs.length}</summary>{refs.map(ref => <blockquote key={ref.id}><small>{ref.archive_id ? `图片 #${ref.archive_id}` : `消息 #${ref.message_id || ref.message_number || '未知'}`}{ref.conversation_id ? ` · 会话 ${ref.conversation_id}` : ''}</small><p>{ref.quote}</p></blockquote>)}</details>}
        </article>;
      })}
      {!blueprint[key].length && <p>当前版本尚未填写。</p>}
      {key === 'acceptance_gates' && <p className="reading-note">以上为验收标准，不表示客户已验收；任务完成与客户验收分开记录。</p>}
    </details>)}
    {([['out_of_scope','不做什么'],['assumptions','假设'],['open_questions','待确认问题']] as const).map(([key,label]) => <details className="requirement-reading-layer" key={key} open={key === 'open_questions' && blueprint[key].length > 0}><summary>{label}<span>{blueprint[key].length} 项</span></summary><ul>{blueprint[key].map((text,i) => <li key={i}>{text}</li>)}</ul>{!blueprint[key].length && <p>当前版本无记录。</p>}</details>)}
    <details className="requirement-reading-layer"><summary>风险<span>{blueprint.risks.length} 项</span></summary>{blueprint.risks.map(risk=><article key={risk.id}><h3>{risk.title}</h3><p>{risk.description}</p><p>风险级别：{({low:'低',medium:'中',high:'高'})[risk.severity]}</p><p>应对：{risk.mitigation}</p></article>)}{!blueprint.risks.length&&<p>当前版本无记录。</p>}</details>
  </section>;
}
