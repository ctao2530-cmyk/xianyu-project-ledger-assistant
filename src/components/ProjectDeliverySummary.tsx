import { AcceptancePanel } from '../features/delivery/AcceptancePanel';
import '../features/delivery/acceptance.css';
import { useEffect, useState } from 'react';
import { localPlatformService, type RequirementBlueprint } from '../data/localPlatformService';

/** Read the formal version; task status is never interpreted as customer acceptance. */
export function ProjectDeliverySummary({ caseId, version, projectId }: { caseId: string; version: number; projectId?: string }) {
  const [document, setDocument] = useState<RequirementBlueprint | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setDocument(null); setError(''); setLoading(true);
    void localPlatformService.requirementCase(caseId, version).then(detail => {
      if (!active) return;
      if (detail.document?.schema_version !== '2.0') { setError('历史结构请在完整蓝图中查看。'); return; }
      setDocument(detail.document as RequirementBlueprint);
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : '需求读取失败'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [caseId, version]);
  if (loading) return <p role="status">正在读取正式需求清单…</p>;
  if (error) return <p role="alert">{error}</p>;
  if (!document) return null;
  return <div className="project-delivery-summary">
    {document.open_questions.length > 0 && <details><summary>待确认问题 · {document.open_questions.length}</summary><ul>{document.open_questions.map((q,i)=><li key={i}>{q}</li>)}</ul></details>}
    <p>开发任务完成不代表客户验收完成；验收结果以正式交付记录为准。</p>
    <div className="project-delivery-table"><table><thead><tr><th>需求项</th><th>修改目标</th><th>交付物</th><th>验收标准 / 状态</th></tr></thead><tbody>
      {document.capabilities.map(capability => {
        const stages = document.stages.filter(stage => stage.capability_ids.includes(capability.id));
        const gates = document.acceptance_gates.filter(gate => gate.stage_ids.some(id => stages.some(stage => stage.id === id)));
        return <tr key={capability.id}><th scope="row">{capability.title}</th><td>{capability.description || '待补充'}</td><td>{[...new Set(stages.flatMap(stage => stage.deliverables))].join('、') || '待明确交付物'}</td><td>{gates.flatMap(gate=>gate.criteria).map((criterion,i)=><div key={i}>{criterion}</div>)}<small>版本验收结论见下方记录</small></td></tr>;
      })}
    </tbody></table></div>
    {projectId && <AcceptancePanel projectId={projectId} caseId={caseId} version={version}/>}
    {!document.capabilities.length && <p>此版本尚未记录具体需求项。</p>}
  </div>;
}
