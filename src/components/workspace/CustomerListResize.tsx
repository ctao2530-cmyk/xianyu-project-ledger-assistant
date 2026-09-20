import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';

const storageKey = 'xunying-customer-list-width';
export const clampCustomerListWidth = (width: number, available: number) =>
  Math.round(Math.max(260, Math.min(Number.isFinite(width) ? width : 280, 360, Math.max(260, available - 560))));
export const clampAuroraCustomerListWidth = (width: number, available: number) =>
  Math.round(Math.max(300, Math.min(Number.isFinite(width) ? width : 400, 480, Math.max(300, available - 480))));

export function useCustomerListWidth(contextVisible: boolean, aurora = false) {
  const container = useRef<HTMLElement>(null);
  const [element, setElement] = useState<HTMLElement | null>(null);
  const attach = useCallback((node: HTMLElement | null) => { container.current = node; setElement(node); }, []);
  const [width, setWidth] = useState(() => {
    try { return clampCustomerListWidth(Number(localStorage.getItem(storageKey)) || 280, 1000); } catch { return 280; }
  });
  const [auroraWidth, setAuroraWidth] = useState(() => {
    try { return clampAuroraCustomerListWidth(Number(localStorage.getItem('xunying-aurora-customer-list-width')) || 400, 1200); } catch { return 400; }
  });
  const [available, setAvailable] = useState(1000);
  useEffect(() => {
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setAvailable(entry.contentRect.width - (aurora ? (contextVisible && window.innerWidth >= 1500 ? 440 : 20) : (contextVisible && window.innerWidth > 1250 ? 280 : 0))));
    observer.observe(element);
    return () => observer.disconnect();
  }, [contextVisible, element, aurora]);
  const update = (value: number) => {
    if (aurora) {
      const next = clampAuroraCustomerListWidth(value, available);
      setAuroraWidth(next);
      try { localStorage.setItem('xunying-aurora-customer-list-width', String(next)); } catch { /* UI preference is optional. */ }
      return;
    }
    const next = clampCustomerListWidth(value, available);
    setWidth(next);
    try { localStorage.setItem(storageKey, String(next)); } catch { /* UI preference is optional. */ }
  };
  return { container, attach, width: aurora ? clampAuroraCustomerListWidth(auroraWidth, available) : clampCustomerListWidth(width, available), update, maximum: aurora ? clampAuroraCustomerListWidth(480, available) : clampCustomerListWidth(360, available), minimum: aurora ? 300 : 260, resetWidth: aurora ? 400 : 280 };
}

export function CustomerListResize({ container, width, maximum, minimum = 260, resetWidth = 280, trackPointerOffset = false, onChange }: {
  container: RefObject<HTMLElement | null>; width: number; maximum: number; minimum?: number; resetWidth?: number; trackPointerOffset?: boolean; onChange: (width: number) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const pointerOffset = useRef(0);
  return <div className={`customer-list-resize${dragging ? ' is-dragging' : ''}`} role="separator" tabIndex={0}
    aria-label="调整客户列表宽度" aria-orientation="vertical" aria-valuemin={minimum} aria-valuemax={maximum} aria-valuenow={width}
    title="拖动调整宽度，方向键微调，双击恢复"
    onDoubleClick={() => onChange(resetWidth)}
    onKeyDown={event => {
      const next = event.key === 'ArrowLeft' ? width - 16 : event.key === 'ArrowRight' ? width + 16 : event.key === 'Home' ? minimum : event.key === 'End' ? maximum : null;
      if (next !== null) { event.preventDefault(); onChange(next); }
    }}
    onPointerDown={event => { if (event.button !== 0) return; event.preventDefault(); pointerOffset.current = trackPointerOffset && container.current ? event.clientX - container.current.getBoundingClientRect().left - width : 0; event.currentTarget.setPointerCapture(event.pointerId); setDragging(true); }}
    onPointerMove={event => { if (dragging && container.current) onChange(event.clientX - container.current.getBoundingClientRect().left - pointerOffset.current); }}
    onPointerUp={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); setDragging(false); }}
    onPointerCancel={() => setDragging(false)} onLostPointerCapture={() => setDragging(false)} />;
}
