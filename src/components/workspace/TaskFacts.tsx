import type {ProjectTask} from '../../types';
export function TaskFacts({task}:{task:ProjectTask}) {
  return <div className="workspace-task-facts"><span><small>工作区</small>{task.workspaceKey||'未指定'}</span><span><small>预计 / 实际</small>{task.estimatedHours}h / {task.actualHours}h</span><span><small>客户验收</small>未记录验收结果</span>{Boolean(task.stage?.acceptance_criteria?.length)&&<details><summary>验收标准</summary><ul>{task.stage!.acceptance_criteria!.map((c,i)=><li key={i}>{c}</li>)}</ul></details>}</div>;
}
