import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { AuroraBackground, type AuroraTestControls } from '../aurora/AuroraBackground';

type VisualMode = 'legacy' | 'aurora';
type MotionMode = 'auto' | 'off';
const VisualContext = createContext({ mode: 'aurora' as VisualMode, motion: 'auto' as MotionMode,
  setMode: (_mode: VisualMode) => {}, setMotion: (_motion: MotionMode) => {} });
export const useVisualMode = () => useContext(VisualContext);
function readPreference(key: string) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function currentMode(): VisualMode {
  const query = new URLSearchParams(location.search).get('ui');
  if (query === 'aurora' || query === 'legacy') return query;
  const saved = readPreference('xunying.visual-mode');
  return saved === 'legacy' ? 'legacy' : 'aurora';
}

export function VisualPreferences() {
  const { mode, motion, setMode, setMotion } = useVisualMode();
  return <div className="visual-preferences" aria-label="本机外观">
    <label>界面样式<select aria-label="界面样式" value={mode} onChange={e => setMode(e.target.value as VisualMode)}><option value="legacy">经典界面</option><option value="aurora">极光工作台</option></select></label>
    <label>背景动效<select aria-label="背景动效" value={motion} onChange={e => setMotion(e.target.value as MotionMode)}><option value="auto">自动</option><option value="off">关闭</option></select></label>
  </div>;
}

export function AppShell({ children, backgroundTest }: { children: ReactNode; backgroundTest?: AuroraTestControls }) {
  const [mode, updateMode] = useState(currentMode);
  const [motion, updateMotion] = useState<MotionMode>(() => readPreference('xunying.aurora-motion') === 'off' ? 'off' : 'auto');
  useEffect(() => { const sync = () => updateMode(currentMode()); window.addEventListener('popstate', sync); return () => window.removeEventListener('popstate', sync); }, []);
  useEffect(() => {
    // Portals mounted under body share the selected presentation, never business state.
    const previous = document.body.dataset.xunyingVisual;
    document.body.dataset.xunyingVisual = mode;
    return () => {
      if (previous === undefined) delete document.body.dataset.xunyingVisual;
      else document.body.dataset.xunyingVisual = previous;
    };
  }, [mode]);
  const setMode = (value: VisualMode) => {
    // Presentation only: preserve the hash, query parameters and mounted business forms.
    const url = new URL(location.href); url.searchParams.set('ui', value);
    history.replaceState(history.state, '', `${url.pathname}${url.search}${url.hash}`);
    try { localStorage.setItem('xunying.visual-mode', value); } catch { /* Private storage may be unavailable. */ }
    updateMode(value);
  };
  const setMotion = (value: MotionMode) => {
    try { localStorage.setItem('xunying.aurora-motion', value); } catch { /* UI remains usable. */ }
    updateMotion(value);
  };
  return <VisualContext.Provider value={{ mode, motion, setMode, setMotion }}>
    <div className="app-shell retained-workspace-layout reference-workspace studio-workspace" data-visual={mode}>
      {mode === 'aurora' && <AuroraBackground motion={motion} testControls={backgroundTest} />}
      {children}
    </div>
  </VisualContext.Provider>;
}

export function ContextPanel({ title, children }: { title: string; children: ReactNode }) {
  const [open,setOpen]=useState(()=>typeof window!=='undefined'&&window.matchMedia('(min-width: 1101px)').matches);
  useEffect(()=>{const media=window.matchMedia('(min-width: 1101px)');const change=()=>setOpen(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change)},[]);
  return <details className="workspace-context" open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary>{title}<span aria-hidden="true">⌄</span></summary><div>{children}</div></details>;
}

export function DetailWorkspace({ children, context }: { children: ReactNode; context?: ReactNode }) {
  return <div className="detail-workspace"><div className="detail-workspace-main">{children}</div>{context}</div>;
}
