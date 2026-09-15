import { useEffect, useState, type ReactNode } from 'react';

export function AppShell({ children }: { children: ReactNode }) {
  return <div className="app-shell retained-workspace-layout reference-workspace august-workspace">{children}</div>;
}

export function ContextPanel({ title, children }: { title: string; children: ReactNode }) {
  const [open,setOpen]=useState(()=>typeof window!=='undefined'&&window.matchMedia('(min-width: 1101px)').matches);
  useEffect(()=>{const media=window.matchMedia('(min-width: 1101px)');const change=()=>setOpen(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change)},[]);
  return <details className="workspace-context" open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary>{title}<span aria-hidden="true">⌄</span></summary><div>{children}</div></details>;
}

export function DetailWorkspace({ children, context }: { children: ReactNode; context?: ReactNode }) {
  return <div className="detail-workspace"><div className="detail-workspace-main">{children}</div>{context}</div>;
}
