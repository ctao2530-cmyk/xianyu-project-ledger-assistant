import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Minus, Plus } from '@phosphor-icons/react';

/** Zooms display pixels only. The immutable image/archive is never modified. */
export function ImageViewport({ children }: { children: ReactNode }) {
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [natural, setNatural] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState<number | null>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setSize({ width: element.clientWidth, height: element.clientHeight }));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const fit = natural.width && size.width ? Math.min(1, (size.width - 24) / natural.width, (size.height - 24) / natural.height) : 1;
  const scale = zoom ?? Math.max(.001, fit);
  const zoomBy = (factor: number) => setZoom(Math.min(4, Math.max(Math.min(fit, .1), scale * factor)));
  return <section className="image-viewer">
    <div className="image-viewer-controls" role="group" aria-label="图片缩放">
      <button type="button" aria-label="缩小图片" disabled={!natural.width} onClick={() => zoomBy(1 / 1.25)}><Minus size={18}/></button>
      <output aria-live="polite">{natural.width ? `${Math.round(scale * 100)}%` : '预览'}</output>
      <button type="button" aria-label="放大图片" disabled={!natural.width} onClick={() => zoomBy(1.25)}><Plus size={18}/></button>
      <button type="button" aria-pressed={zoom === 1} disabled={!natural.width} onClick={() => setZoom(1)}>100%</button>
      <button type="button" aria-pressed={zoom === null} onClick={() => setZoom(null)}>适应窗口</button>
    </div>
    <div className={`image-viewer-viewport ${zoom !== null ? 'is-zoomed' : ''}`} ref={viewport} tabIndex={0} aria-label="完整图片，放大后可滚动或拖动查看"
      onLoadCapture={event => { const img = event.target; if (img instanceof HTMLImageElement) setNatural({ width: img.naturalWidth, height: img.naturalHeight }); }}
      onPointerDown={event => { if (zoom === null || event.button !== 0) return; const el = event.currentTarget; drag.current = { x: event.clientX, y: event.clientY, left: el.scrollLeft, top: el.scrollTop }; el.setPointerCapture(event.pointerId); }}
      onPointerMove={event => { if (!drag.current) return; event.currentTarget.scrollLeft = drag.current.left + drag.current.x - event.clientX; event.currentTarget.scrollTop = drag.current.top + drag.current.y - event.clientY; }}
      onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onDragStart={event => event.preventDefault()}>
      <div className="image-viewer-canvas"><div className="image-viewer-surface" style={natural.width ? { width: natural.width * scale, height: natural.height * scale } : undefined}>{children}</div></div>
    </div>
  </section>;
}
