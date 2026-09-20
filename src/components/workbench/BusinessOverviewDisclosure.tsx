import { useState, type ReactNode } from 'react';
import { useVisualMode } from '../workspace/AppShell';

/** Keep reporting reachable without mounting hidden charts on the action screen. */
export function BusinessOverviewDisclosure({ children }: { children: ReactNode }) {
  const { mode } = useVisualMode();
  const [open, setOpen] = useState(false);
  return <details className="workbench-business-overview" data-visual={mode} open={open}
    onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>经营概览与统计</summary>
    {open && (mode === 'aurora' ? <div className="workbench-historical-overview">{children}</div> : children)}
  </details>;
}

/** Promoted modules mount once: on Aurora's grid, or inside the legacy disclosure. */
export function LegacyOverviewContent({ children }: { children: ReactNode }) {
  return useVisualMode().mode === 'legacy' ? <>{children}</> : null;
}
