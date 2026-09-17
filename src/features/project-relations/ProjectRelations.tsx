import type { LedgerSnapshot } from '../../types';
import type { ProjectRequirementBlueprintView } from '../../data/localPlatformService';
import { projectRelations } from './model';
import './relations.css';

export function ProjectRelations({ snapshot, projectId, formal, requirementState }: {
  snapshot: LedgerSnapshot; projectId: string; formal: ProjectRequirementBlueprintView | null;
  requirementState: 'loading' | 'ready' | 'error';
}) {
  const nodes = projectRelations(snapshot, projectId, formal, requirementState);
  return <details className="project-relations" key={projectId}>
    <summary><span>业务关联图</span><small>客户 · 沟通 · 需求 · 交付 · 回款</small></summary>
    <div className="project-relations-body">
      <p>仅展示当前项目的已记录关联。点击节点查看原始记录；虚线标记尚未记录的关联。</p>
      <div className="project-relations-hub">当前项目<span>关联对象</span></div>
      <ul aria-label="当前项目的业务关联">{nodes.map(node => <li key={node.id} className={node.missing ? 'is-missing' : ''}>
        {node.href ? <a href={node.href}><b>{node.label}<span aria-hidden="true">↗</span></b><small>{node.detail}</small></a> : <div><b>{node.label}</b><small>{node.detail}</small></div>}
      </li>)}</ul>
      <p className="project-relations-note">连线表示项目归属，不表示先后完成。需求、开发进度、客户验收与到账分别核对。</p>
    </div>
  </details>;
}
