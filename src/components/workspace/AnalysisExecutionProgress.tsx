export function AnalysisExecutionProgress({executing,reviewDue,completed}:{executing:number;reviewDue:number;completed:number}) {
  return <aside className="reference-execution-progress" aria-label="建议执行进度">
    <h2>执行进度</h2>
    <dl><div><dt>执行中</dt><dd>{executing}</dd></div><div className={reviewDue?'is-due':''}><dt>待复盘</dt><dd>{reviewDue}</dd></div><div><dt>已完成</dt><dd>{completed}</dd></div></dl>
    <p>建议经人工采纳、观察和复盘后更新；任务完成不代表客户验收。</p>
  </aside>;
}
