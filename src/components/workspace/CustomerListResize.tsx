import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';

const storageKey = 'xunying-customer-list-width';
export const clampCustomerListWidth = (width: number, available: number) =>
  Math.round(Math.max(260, Math.min(Number.isFinite(width) ? width : 280, 360, Math.max(260, available - 560))));

export function useCustomerListWidth(contextVisible: boolean) {
  const container = useRef<HTMLElement>(null);
  const [element, setElement] = useState<HTMLElement | null>(null);
  const attach = useCallback((node: HTMLElement | null) => { container.current = node; setElement(node); }, []);
  const [width, setWidth] = useState(() => {
    try { return clampCustomerListWidth(Number(localStorage.getItem(storageKey)) || 280, 1000); } catch { return 280; }
  });
  const [available, setAvailable] = useState(1000);
  useEffect(() => {
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setAvailable(entry.contentRect.width - (contextVisible && window.innerWidth > 1250 ? 280 : 0)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [contextVisible, element]);
  const update = (value: number) => {
    const next = clampCustomerListWidth(value, available);
    setWidth(next);
    try { localStorage.setItem(storageKey, String(next)); } catch { /* UI preference is optional. */ }
  };
  return { container, attach, width: clampCustomerListWidth(width, available), update, maximum: clampCustomerListWidth(360, available) };
}

export function CustomerListResize({ container, width, maximum, onChange }: {
  container: RefObject<HTMLElement | null>; width: number; maximum: number; onChange: (width: number) => void;
}) {
  const [dragging, setDragging] = useState(false);
  return <div className={`customer-list-resize${dragging ? ' is-dragging' : ''}`} role="separator" tabIndex={0}
    aria-label="调整客户列表宽度" aria-orientation="vertical" aria-valuemin={260} aria-valuemax={maximum} aria-valuenow={width}
    title="拖动调整宽度，方向键微调，双击恢复"
    onDoubleClick={() => onChange(280)}
    onKeyDown={event => {
      const next = event.key === 'ArrowLeft' ? width - 16 : event.key === 'ArrowRight' ? width + 16 : event.key === 'Home' ? 260 : event.key === 'End' ? maximum : null;
      if (next !== null) { event.preventDefault(); onChange(next); }
    }}
    onPointerDown={event => { if (event.button !== 0) return; event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); setDragging(true); }}
    onPointerMove={event => { if (dragging && container.current) onChange(event.clientX - container.current.getBoundingClientRect().left); }}
    onPointerUp={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); setDragging(false); }}
    onPointerCancel={() => setDragging(false)} onLostPointerCapture={() => setDragging(false)} />;
}
