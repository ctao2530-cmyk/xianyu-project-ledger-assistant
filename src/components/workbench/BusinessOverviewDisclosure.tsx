import { useState, type ReactNode } from 'react';

/** Keep reporting reachable without mounting hidden charts on the action screen. */
export function BusinessOverviewDisclosure({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <details className="workbench-business-overview" open={open}
    onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>经营概览与统计</summary>
    {open && children}
  </details>;
}
