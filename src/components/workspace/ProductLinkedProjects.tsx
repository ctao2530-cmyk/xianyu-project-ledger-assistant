import { Fragment, useState } from 'react';
import { CaretDown, CaretRight, LinkSimple } from '@phosphor-icons/react';
import type { ProductView } from '../../data/localPlatformService';

const money = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 });
const date = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'short' });

export function ProductLinkedProjects({ projects }: { projects: ProductView['linked_projects'] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return <section className="product-linked-projects product-project-table">
    <header><h4>关联项目 / 实际利润 <span>{projects.length}</span></h4></header>
    {projects.length ? <table aria-label="当前商品关联项目与实际利润">
      <thead><tr><th scope="col">关联项目</th><th scope="col">净到账</th><th scope="col">实际利润</th><th scope="col"><span className="sr-only">明细</span></th></tr></thead>
      <tbody>{projects.map(project => {
        const open = expanded === project.project_id;
        return <Fragment key={project.project_id}>
          <tr>
            <th scope="row"><a href={`#${encodeURIComponent(`项目管理/${project.project_id}/overview`)}`}>{project.project_name}</a></th>
            <td>{money.format(project.net_confirmed_total)}</td>
            <td>{money.format(project.profit_total)}</td>
            <td><button type="button" aria-label={`${open ? '收起' : '展开'}${project.project_name}收支明细`} aria-expanded={open} onClick={() => setExpanded(open ? null : project.project_id)}>{open ? <CaretDown size={16}/> : <CaretRight size={16}/>}</button></td>
          </tr>
          {open && <tr className="product-project-breakdown"><td colSpan={4}>
            <dl><div><dt>项目支出</dt><dd>{money.format(project.expense_total)}</dd></div><div><dt>退款</dt><dd>{money.format(project.refund_total)}</dd></div></dl>
            <p>{project.relation_source === 'project_binding' ? '项目绑定' : '会话兼容归属'} · {project.latest_confirmed_at ? `最近到账 ${date.format(new Date(project.latest_confirmed_at))}` : '暂无确认到账'}</p>
          </td></tr>}
        </Fragment>;
      })}</tbody>
    </table> : <div className="product-profit-empty"><LinkSimple size={22}/><span><b>尚未关联项目</b><small>在项目详情中管理来源商品关系。</small></span></div>}
  </section>;
}
