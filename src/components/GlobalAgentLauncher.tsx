import { ChatCircleDots } from "@phosphor-icons/react";
import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import type { GlobalAgentTargetPage } from "../data/localPlatformService";
import { GlobalAgentPanel } from "./GlobalAgentPanel";


interface Point { x: number; y: number; viewportWidth?: number; viewportHeight?: number; size?: number }
const POSITION_KEY = "xunying.global-agent.launcher.v1";

function launcherSize() {
  return window.matchMedia("(max-width: 680px)").matches ? 48 : 64;
}

function defaultPosition(): Point {
  const size = launcherSize();
  const mobile = window.matchMedia("(max-width: 680px)").matches;
  return {
    x: window.innerWidth - size - (mobile ? 16 : 30),
    y: window.innerHeight - size - (mobile ? 94 : 112),
  };
}

function clampPosition(point: Point): Point {
  const size = launcherSize();
  const mobile = window.matchMedia("(max-width: 680px)").matches;
  const bottomReserve = mobile ? 84 : 12;
  return {
    x: Math.min(window.innerWidth - size - 12, Math.max(12, point.x)),
    y: Math.min(window.innerHeight - size - bottomReserve, Math.max(72, point.y)),
  };
}

function readPosition(): Point {
  try {
    const parsed = JSON.parse(localStorage.getItem(POSITION_KEY) || "null") as Point | null;
    if (parsed && Number.isFinite(parsed.x) && Number.isFinite(parsed.y)) {
      const size = launcherSize();
      const leftEdge = window.matchMedia("(max-width: 680px)").matches ? 16 : 30;
      const rightEdge = window.innerWidth - size - leftEdge;
      const staleAbsolutePosition = parsed.x > 48 && parsed.x < window.innerWidth - size - 48;
      const wasOnRight = Number.isFinite(parsed.viewportWidth) && (parsed.viewportWidth as number) > 0
        ? parsed.x + size / 2 >= (parsed.viewportWidth as number) / 2
        : staleAbsolutePosition && parsed.x > 160;
      const previousSize = parsed.size === 48 || parsed.size === 64 ? parsed.size : (parsed.viewportWidth as number) <= 680 ? 58 : 64;
      const previousBottomGap = Number.isFinite(parsed.viewportHeight)
        ? (parsed.viewportHeight as number) - parsed.y - previousSize
        : null;
      const nextY = previousBottomGap === null
        ? (staleAbsolutePosition ? defaultPosition().y : parsed.y)
        : window.innerHeight - size - Math.max(12, previousBottomGap);
      return clampPosition({ x: staleAbsolutePosition ? (wasOnRight ? rightEdge : leftEdge) : parsed.x, y: nextY });
    }
  } catch {
    // Device-only launcher position is optional.
  }
  return clampPosition(defaultPosition());
}

function overlaps(left: DOMRect, right: DOMRect, gap = 8) {
  return left.left < right.right + gap && left.right > right.left - gap && left.top < right.bottom + gap && left.bottom > right.top - gap;
}

function avoidFixedControls(point: Point): Point {
  const size = launcherSize();
  const mobile = window.matchMedia("(max-width: 680px)").matches;
  let next = clampPosition(point);
  const keyMetrics = mobile ? document.querySelector<HTMLElement>(".liquid-home-metrics") : null;
  if (keyMetrics) {
    const launcher = new DOMRect(next.x, next.y, size, size);
    if (overlaps(launcher, keyMetrics.getBoundingClientRect(), 12)) next = clampPosition(defaultPosition());
  }
  const selectors = [".floating-add", ".xunying-mobile-nav"];
  for (const selector of selectors) {
    const element = document.querySelector<HTMLElement>(selector);
    if (!element) continue;
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") continue;
    const control = element.getBoundingClientRect();
    const launcher = new DOMRect(next.x, next.y, size, size);
    if (overlaps(launcher, control, 12)) next = clampPosition({ ...next, y: control.top - size - 14 });
  }
  return next;
}

const blockingOverlaySelector = [
  ".drawer-layer.is-open",
  ".payment-modal-layer",
  ".page-modal-layer",
  ".connection-recovery-layer",
  ".blueprint-drawer-layer",
  ".blueprint-modal-layer",
  ".task-editor-layer",
  ".product-plan-modal-layer",
  ".history-import-layer",
].join(",");

export function GlobalAgentLauncher({ onNavigate }: {
  onNavigate: (target: GlobalAgentTargetPage) => void;
}) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; origin: Point } | null>(null);
  const suppressClickRef = useRef(false);
  const [position, setPosition] = useState<Point>(() => readPosition());
  const [open, setOpen] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [hasMobileNav, setHasMobileNav] = useState(false);

  const persist = (next: Point) => {
    const safe = { ...avoidFixedControls(next), viewportWidth: window.innerWidth, viewportHeight: window.innerHeight, size: launcherSize() };
    setPosition(safe);
    try {
      localStorage.setItem(POSITION_KEY, JSON.stringify(safe));
    } catch {
      // Position persistence must never block the Agent.
    }
  };

  useEffect(() => {
    const safe = { ...avoidFixedControls(position), viewportWidth: window.innerWidth, viewportHeight: window.innerHeight, size: launcherSize() };
    const changed = safe.x !== position.x || safe.y !== position.y || safe.viewportWidth !== position.viewportWidth || safe.viewportHeight !== position.viewportHeight;
    try {
      if (changed) localStorage.setItem(POSITION_KEY, JSON.stringify(safe));
    } catch {
      // Position persistence must never block the Agent.
    }
    if (changed) setPosition(safe);
  }, []);

  useEffect(() => {
    const reposition = () => persist(readPosition());
    window.addEventListener("resize", reposition);
    return () => window.removeEventListener("resize", reposition);
  }, [position.x, position.y]);

  useEffect(() => {
    const update = () => {
      setBlocked(Boolean(document.querySelector(blockingOverlaySelector)));
      setHasMobileNav(Boolean(document.querySelector(".xunying-mobile-nav")));
    };
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["class", "aria-hidden"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const openAgent = () => {
      if (document.querySelector(blockingOverlaySelector)) return;
      setOpen(true);
    };
    window.addEventListener("xunying:global-agent-open", openAgent);
    return () => window.removeEventListener("xunying:global-agent-open", openAgent);
  }, []);

  const pointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      origin: position,
    };
    suppressClickRef.current = false;
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const pointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (Math.hypot(dx, dy) > 5) suppressClickRef.current = true;
    if (!suppressClickRef.current) return;
    setPosition(clampPosition({ x: drag.origin.x + dx, y: drag.origin.y + dy }));
  };

  const pointerUp = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (!suppressClickRef.current) return;
    const size = launcherSize();
    const snapped = {
      x: position.x + size / 2 < window.innerWidth / 2 ? 14 : window.innerWidth - size - 14,
      y: position.y,
    };
    persist(snapped);
    // Pointer-up normally emits a trailing click that consumes this flag. Some
    // browser automation and cancelled drags do not, so clear it after that
    // immediate click window instead of swallowing the user's next real click.
    window.setTimeout(() => { suppressClickRef.current = false; }, 0);
  };

  const close = () => {
    setOpen(false);
    window.requestAnimationFrame(() => buttonRef.current?.focus({ preventScroll: true }));
  };

  const panelGeometry = (() => {
    const width = Math.min(760, window.innerWidth - 48);
    const height = Math.min(790, window.innerHeight - 48);
    const size = launcherSize();
    const placeRight = position.x + size / 2 < window.innerWidth / 2;
    const left = placeRight
      ? Math.min(window.innerWidth - width - 24, position.x + size + 14)
      : Math.max(24, position.x - width - 14);
    const top = Math.max(24, Math.min(window.innerHeight - height - 24, position.y - 118));
    return { left, top, width, height };
  })();

  const panelStyle = {
    "--agent-panel-left": `${panelGeometry.left}px`,
    "--agent-panel-top": `${panelGeometry.top}px`,
    "--agent-panel-width": `${panelGeometry.width}px`,
    "--agent-panel-height": `${panelGeometry.height}px`,
  } as CSSProperties;

  return <div className={`global-agent-root ${blocked && !open ? "is-blocked" : ""} ${hasMobileNav ? "has-mobile-nav" : ""}`}>
    <button
      ref={buttonRef}
      type="button"
      className={`global-agent-launcher ${open ? "is-open" : ""}`}
      style={{ transform: `translate3d(${position.x}px, ${position.y}px, 0)` }}
      aria-label="打开小策全局助手；可拖动位置"
      aria-haspopup="dialog"
      aria-expanded={open}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={pointerUp}
      onPointerCancel={() => { dragRef.current = null; suppressClickRef.current = false; }}
      onClick={() => {
        if (suppressClickRef.current) {
          suppressClickRef.current = false;
          return;
        }
        setOpen((value) => !value);
      }}
      onKeyDown={(event) => {
        const step = event.shiftKey ? 24 : 10;
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home"].includes(event.key)) event.preventDefault();
        if (event.key === "Home") persist(defaultPosition());
        if (event.key === "ArrowLeft") persist({ ...position, x: position.x - step });
        if (event.key === "ArrowRight") persist({ ...position, x: position.x + step });
        if (event.key === "ArrowUp") persist({ ...position, y: position.y - step });
        if (event.key === "ArrowDown") persist({ ...position, y: position.y + step });
      }}
    >
      <span className="global-agent-launcher-ring" aria-hidden="true" />
      <img src="/assets/xunying/xiaoce-avatar.png" alt="" draggable={false} />
      <i aria-hidden="true" />
      <b><ChatCircleDots size={13} weight="fill" /></b>
    </button>
    <GlobalAgentPanel open={open} style={panelStyle} onClose={close} onNavigate={(target) => { close(); onNavigate(target); }} />
  </div>;
}
