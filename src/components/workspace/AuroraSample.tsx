import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Button } from '@appica/ui-react/button';
import { Chip } from '@appica/ui-react/chip';
import { ArrowUpRight, Check, CheckCircle, Clock, Coins, FolderSimple, Plus, WarningCircle, X } from '@phosphor-icons/react';

/** Synthetic UI specimens. Imported only by the isolated S01 fixture, never by the business App. */
export function AuroraSample() {
  const [tab, setTab] = useState('全部');
  const [name, setName] = useState('合成界面调整');
  const [notice, setNotice] = useState('');
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const [overlay] = useState(() => { const node = document.createElement('div'); node.className = 'aurora-theme aurora-overlays'; return node; });
  useEffect(() => { document.body.appendChild(overlay); return () => overlay.remove(); }, [overlay]);
  useEffect(() => {
    if (!open || !dialog.current) return;
    const opener = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    node.showModal();
    return () => { node.close(); opener?.focus(); };
  }, [open]);
  const rows = [
    { title: '合成界面调整', detail: '需求范围与交付清单', state: '进行中', date: '09 / 18', kind: 'success' },
    { title: '合成资料整理', detail: '补充必要的图片说明', state: '待确认', date: '09 / 19', kind: 'warning' },
    { title: '合成历史记录', detail: '保留原始信息与版本', state: '已完成', date: '09 / 16', kind: 'neutral' },
  ];
  const tabs = ['全部', '进行中', '已完成'];
  return <div className="aurora-theme aurora-sample">
    <section className="aurora-sample-heading">
      <div><p className="aurora-eyebrow"><span />组件样板 · 合成数据</p><h1>经营工作台</h1><p>清晰的信息、安静的光，让手头的工作井然有序。</p>
        <div className="aurora-actions"><Button className="aurora-button primary" onClick={() => setOpen(true)}><Plus size={18} />预览弹层</Button><Button className="aurora-button" onClick={() => document.getElementById('aurora-form-name')?.focus()}>试用表单<ArrowUpRight size={16} /></Button></div>
      </div><aside><strong>S01 · 全局视觉</strong><p>仅用于外观与交互确认<br />全部内容为隔离样本</p><i /></aside>
    </section>
    <section className="aurora-metrics" aria-label="合成指标样板">
      {[{ label: '已确认收入', value: '¥2,100', note: '合成记录 · 3 笔', icon: Coins }, { label: '当前待回款', value: '¥3,900', note: '合同金额减去已确认收入', icon: Clock }, { label: '进行中项目', value: '1', note: '任务完成不代表客户验收', icon: FolderSimple }].map(({ label, value, note, icon: Icon }) => <article className="aurora-panel aurora-metric" key={label}><div><p>{label}</p><strong>{value}</strong><small>{note}</small></div><span><Icon size={25} /></span></article>)}
    </section>
    <div className="aurora-sample-grid">
      <section className="aurora-panel aurora-records"><header><div><h2>列表与状态</h2><p>密度适中的行，保留明确的操作入口</p></div><span className="aurora-small-label">合成样本</span></header>
        <div className="aurora-tabs" role="tablist" aria-label="样板列表状态">{tabs.map((value, index) => <button role="tab" id={`aurora-tab-${index}`} aria-selected={tab === value} aria-controls="aurora-row-panel" tabIndex={tab === value ? 0 : -1} key={value} onClick={() => setTab(value)} onKeyDown={e => { const next = e.key === 'ArrowRight' ? (index + 1) % tabs.length : e.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : -1; if (next >= 0) { e.preventDefault(); setTab(tabs[next]); document.getElementById(`aurora-tab-${next}`)?.focus(); } }}>{value}</button>)}</div>
        <div id="aurora-row-panel" role="tabpanel" aria-labelledby={`aurora-tab-${tabs.indexOf(tab)}`} tabIndex={0}><table className="aurora-table"><thead><tr><th>事项</th><th>状态</th><th>日期</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{rows.filter(row => tab === '全部' || row.state === tab).map(row => <tr key={row.title}><td><strong>{row.title}</strong><small>{row.detail}</small></td><td><Chip render={<span />} className={`aurora-chip ${row.kind}`}>{row.state}</Chip></td><td className="aurora-numeric">{row.date}</td><td><button className="aurora-text-button" onClick={() => { setName(row.title); setOpen(true); }}>查看<ArrowUpRight size={14} /></button></td></tr>)}</tbody></table></div>
        <footer><CheckCircle size={17} /><span>文字与颜色共同区分状态，样板操作不会保存业务记录。</span></footer>
      </section>
      <section className="aurora-panel aurora-form"><header><div><h2>表单与反馈</h2><p>输入、选择与确认保持熟悉的使用方式</p></div></header>
        <form onSubmit={event => { event.preventDefault(); setNotice(name.trim() ? '样板已确认。本次没有写入业务数据。' : '请填写事项名称。'); }}>
          <label htmlFor="aurora-form-name">事项名称 <span>必填</span></label><input id="aurora-form-name" value={name} onChange={e => setName(e.target.value)} aria-invalid={notice === '请填写事项名称。'} aria-describedby="aurora-form-feedback" placeholder="填写一个样板名称" />
          <label htmlFor="aurora-form-status">当前状态</label><select id="aurora-form-status" defaultValue="待确认"><option>待确认</option><option>进行中</option><option>已完成</option></select>
          <label className="aurora-check"><input type="checkbox" defaultChecked />我已核对这份合成样本</label>
          <Button className="aurora-button primary" type="submit"><Check size={17} />确认样板</Button><p id="aurora-form-feedback" className="aurora-feedback" role="status">{notice || '仅改变本页的样板状态。'}</p>
        </form>
      </section>
      <section className="aurora-panel aurora-states"><header><div><h2>按钮与标签</h2><p>主操作明确，次要操作克制</p></div></header><div className="aurora-actions"><Button className="aurora-button primary" onClick={() => setOpen(true)}>主要操作</Button><Button className="aurora-button" onClick={() => setNotice('已触发样板次要操作。')}>次要操作</Button><Button className="aurora-button" disabled>不可用</Button></div><div className="aurora-tags"><Chip render={<span />} className="aurora-chip success">进行中</Chip><Chip render={<span />} className="aurora-chip warning">待确认</Chip><Chip render={<span />} className="aurora-chip danger">读取失败</Chip><Chip render={<span />} className="aurora-chip neutral">已归档</Chip></div></section>
      <section className="aurora-panel aurora-states"><header><div><h2>错误与恢复</h2><p>告诉用户发生了什么，以及下一步能做什么</p></div></header><div className="aurora-error" role="note"><WarningCircle size={23} /><div><strong>样板数据暂未读取</strong><p>这是合成错误状态，你可以试用重试反馈。</p></div><button className="aurora-text-button" onClick={() => setNotice('样板重试完成，未发出网络请求。')}>重试</button></div></section>
    </div>
    <p className="aurora-sample-footnote">当前仅确认壳层与组件。客户、项目、收支等业务页面保留原有功能与样式。</p>
    {open && createPortal(<dialog className="aurora-dialog" ref={dialog} aria-labelledby="aurora-dialog-title" onKeyDown={event => {
      if (event.key !== 'Tab') return;
      const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]),input,select,textarea,[tabindex="0"]')];
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }} onCancel={() => setOpen(false)} onClose={() => setOpen(false)} onClick={e => { if (e.target === e.currentTarget) { const box = e.currentTarget.getBoundingClientRect(); if (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom) setOpen(false); } }}><header><div><span className="aurora-eyebrow">弹层样板</span><h2 id="aurora-dialog-title">核对事项</h2></div><button className="aurora-icon-button" aria-label="关闭样板弹层" onClick={() => setOpen(false)} autoFocus><X size={20} /></button></header><p>这是一个独立浮层，内容保持清晰，不受卡片裁切影响。</p><div className="aurora-dialog-detail"><small>事项名称</small><strong>{name || '尚未填写'}</strong><Chip render={<span />} className="aurora-chip warning">待人工确认</Chip></div><footer><Button className="aurora-button" onClick={() => setOpen(false)}>返回</Button><Button className="aurora-button primary" onClick={() => { setNotice('样板弹层已确认，未保存业务数据。'); setOpen(false); }}>确认样板</Button></footer></dialog>, overlay)}
  </div>;
}
