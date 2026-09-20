import { useEffect, useRef, useState } from 'react';
import { CaretDown, GearSix, List, X, type Icon } from '@phosphor-icons/react';

type NavProps = {
  active: string;
  items: Array<{ label: string; displayLabel?: string; icon: Icon; hidden?: boolean }>;
  secondary: Record<string, Array<{ key: string; label: string; route: string }>>;
  selectedChild: (parent: string) => string;
  onActiveChange: (value: string) => void;
  onSecondaryNavigate: (parent: string, route: string) => void;
};
const displayNames: Record<string, string> = { 商品经营: '服务商品', 经营记录: '收支经营' };

export function AuroraTopNav({ active, items, secondary, selectedChild, onActiveChange, onSecondaryNavigate }: NavProps) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [, refresh] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const close = () => { setExpanded(null); setMobileOpen(false); refresh(n => n + 1); };
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) close(); };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (expanded) { root.current?.querySelector<HTMLButtonElement>('[aria-expanded="true"]:not(.aurora-menu-toggle)')?.focus(); setExpanded(null); }
      else if (mobileOpen) { setMobileOpen(false); trigger.current?.focus(); }
    };
    const events = ['hashchange', 'popstate', 'xianyu:route-focus'];
    events.forEach(e => window.addEventListener(e, close)); document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape);
    return () => { events.forEach(e => window.removeEventListener(e, close)); document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [expanded, mobileOpen]);
  const navigate = (value: string) => { onActiveChange(value); setMobileOpen(false); setExpanded(null); };
  return <div className="aurora-navigation" ref={root}>
    <button className="aurora-menu-toggle" ref={trigger} aria-label={mobileOpen ? '关闭顶部导航' : '打开顶部导航'} aria-controls="aurora-primary-nav" aria-expanded={mobileOpen} onClick={() => setMobileOpen(v => !v)}>{mobileOpen ? <X size={21} /> : <List size={21} />}</button>
    <nav id="aurora-primary-nav" className={mobileOpen ? 'is-open' : ''} aria-label="主导航">
      {items.filter(item => !item.hidden && item.label !== '设置中心').map(item => {
        const selected = active === item.label || (item.label === '客户消息' && active === '客户管理') || (item.label === '经营分析中心' && ['数据统计', 'AI经营助手'].includes(active));
        const children = secondary[item.label];
        return <div className="aurora-nav-group" key={item.label}>
          <button aria-current={selected ? 'page' : undefined} aria-expanded={children ? expanded === item.label : undefined} aria-controls={children ? 'aurora-product-nav' : undefined} onClick={() => {
            if (children) setExpanded(expanded === item.label ? null : item.label);
            else navigate(item.label);
          }}>{displayNames[item.label] || item.displayLabel || item.label}{children && <CaretDown size={12} />}</button>
          {children && expanded === item.label && <div className="aurora-subnav" id="aurora-product-nav" aria-label={`${item.label}二级导航`}>{children.map(child => <button key={child.key} aria-current={selected && selectedChild(item.label) === child.key ? 'page' : undefined} onClick={() => { onSecondaryNavigate(item.label, child.route); setExpanded(null); setMobileOpen(false); }}>{child.label}</button>)}</div>}
        </div>;
      })}
      <div className="aurora-nav-utilities"><button aria-label="打开小策对话" aria-haspopup="dialog" onClick={() => { setMobileOpen(false); setExpanded(null); window.dispatchEvent(new CustomEvent('xunying:global-agent-open')); }}><img src="/assets/xunying/xiaoce-avatar.png" alt="" />小策</button><button aria-label="设置中心" onClick={() => navigate('设置中心')}><GearSix size={20} /><span>设置</span></button></div>
    </nav>
  </div>;
}
