import { useEffect, useState } from 'react';
import { ArrowRight, CaretDown, X, type Icon } from '@phosphor-icons/react';

type NavItem = { label: string; displayLabel?: string; icon: Icon; hidden?: boolean };
type Child = { key: string; label: string; route: string };
export function Sidebar({ active, onActiveChange, onSecondaryNavigate, open, onClose, items, secondary, selectedChild }: {
  active: string; onActiveChange: (value: string) => void; onSecondaryNavigate: (parent: string, route: string) => void;
  open: boolean; onClose: () => void; items: NavItem[]; secondary: Record<string, Child[]>; selectedChild: (parent: string) => string;
}) {
  const [mobile, setMobile] = useState(() => matchMedia('(max-width: 1100px)').matches);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [, updateRoute] = useState(0);
  useEffect(() => {
    const media = matchMedia('(max-width: 1100px)'); const sync = () => setMobile(media.matches);
    media.addEventListener('change', sync); return () => media.removeEventListener('change', sync);
  }, []);
  useEffect(() => {
    const sync = () => updateRoute(n => n + 1);
    const events = ['hashchange', 'popstate', 'xianyu:route-focus'];
    events.forEach(e => window.addEventListener(e, sync)); return () => events.forEach(e => window.removeEventListener(e, sync));
  }, []);
  return <>
    {mobile && open && <button className="sidebar-scrim is-open" aria-label="关闭导航" onClick={onClose}/>}
    <aside className={`sidebar workspace-sidebar ${open ? 'is-open' : ''}`} aria-hidden={mobile && !open ? true : undefined} inert={mobile && !open ? true : undefined}>
      <div className="brand xunying-brand"><img src="/assets/xunying/orbit-mark.png" alt=""/><span className="reference-brand-copy"><strong>循营</strong><small>一人经营台</small></span>{mobile && <button aria-label="关闭导航" onClick={onClose}><X size={20}/></button>}</div>
      <nav aria-label="主导航">{items.filter(i => !i.hidden).map(({label,displayLabel,icon: Icon}) => {
        const selected = active === label || (label === '客户消息' && active === '客户管理') || (label === '经营分析中心' && ['数据统计','AI经营助手'].includes(active));
        const children = secondary[label];
        return <div key={label} className={`sidebar-nav-group ${label === '设置中心' ? 'workspace-settings-nav' : ''}`}>
          <button type="button" className={`sidebar-nav-parent ${selected ? 'active' : ''}`} aria-current={selected ? 'page' : undefined} aria-expanded={children ? expanded === label : undefined} onClick={() => {
            if (children) { setExpanded(expanded === label ? null : label); if (!selected) onSecondaryNavigate(label, children.find(child => child.key === selectedChild(label))?.route || children[0].route); }
            else {onActiveChange(label); onClose();}
          }}><Icon size={22} weight={selected ? 'fill' : 'regular'}/><span>{displayLabel || label}</span>{children && <CaretDown size={12}/>}</button>
          {children && expanded === label && <div className="sidebar-subnav" aria-label={`${label}二级导航`}>{children.map(child => <button type="button" key={child.key} aria-current={selected && selectedChild(label) === child.key ? 'page' : undefined} onClick={() => {onSecondaryNavigate(label, child.route);onClose();}}>{child.label}</button>)}</div>}
        </div>;
      })}</nav>
      <div className="sidebar-spacer" />
      <div className="sidebar-promo xiaoce-sidebar-card"><div><small>小策 · AI 技术与商业合伙人</small><strong>把不确定，<br/>变成可验证行动</strong><button onClick={()=>{onActiveChange('AI经营助手');onClose();}}>查看今日判断 <ArrowRight size={15} weight="bold"/></button></div><div className="sidebar-promo-artwork" aria-hidden="true"><img src="/assets/xunying/xiaoce-avatar.png" alt="" draggable={false}/></div></div>
    </aside>
  </>;
}
