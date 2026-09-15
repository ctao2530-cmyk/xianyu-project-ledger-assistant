import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "@phosphor-icons/react";
import "./customer-workflow.css";

export function CustomerWorkflowDialog({ title, onClose, children, className = '', suspended = false }: { title: string; onClose: () => void; children: ReactNode; className?: string; suspended?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const suspendedRef = useRef(suspended);
  suspendedRef.current = suspended;
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const key = (event: KeyboardEvent) => {
      if (suspendedRef.current || event.defaultPrevented) return;
      if (Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"]')).at(-1) !== ref.current) return;
      if (event.key === "Escape") { event.preventDefault(); onCloseRef.current(); return; }
      if (event.key !== "Tab") return;
      const controls = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex="0"]') || []).filter(element => element.getClientRects().length > 0);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); previous?.focus(); };
  }, []);
  return createPortal(<div className={`customer-workflow-backdrop ${className}`} onMouseDown={(event) => { if (!suspended && event.target === event.currentTarget) onClose(); }}><div className="customer-workflow-dialog" role="dialog" aria-modal="true" aria-label={title} ref={ref}><header><h2>{title}</h2><button type="button" aria-label={`关闭${title}`} onClick={onClose}><X size={20} /></button></header>{children}</div></div>, document.body);
}
