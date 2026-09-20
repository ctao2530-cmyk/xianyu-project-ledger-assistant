import { useEffect, useRef } from 'react';

/** Presentation-only focus containment for the retained finance dialogs. */
export function useDialogFocus<T extends HTMLElement>(onEscape: () => void, initialFocus: string, enabled = true) {
  const dialog = useRef<T>(null);
  const opener = useRef<HTMLElement | null>(typeof document === 'undefined' ? null : document.activeElement as HTMLElement);
  const escape = useRef(onEscape);
  escape.current = onEscape;
  useEffect(() => {
    if (!enabled) return;
    const root = dialog.current;
    if (!root) return;
    const focusable = () => Array.from(root.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href],summary,[tabindex]:not([tabindex="-1"])')).filter(element => element.getClientRects().length > 0);
    const topmost = () => Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')).filter(element => element.getClientRects().length > 0).at(-1) === root;
    const frame = requestAnimationFrame(() => {
      if (!root.contains(document.activeElement)) root.querySelector<HTMLElement>(initialFocus)?.focus({ preventScroll: true });
    });
    const keydown = (event: KeyboardEvent) => {
      if (!topmost()) return;
      if (event.key === 'Escape') { event.preventDefault(); escape.current(); return; }
      if (event.key !== 'Tab') return;
      const controls = focusable(), first = controls[0], last = controls.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    const focusin = (event: FocusEvent) => {
      if (topmost() && !root.contains(event.target as Node)) focusable()[0]?.focus({ preventScroll: true });
    };
    document.addEventListener('keydown', keydown);
    document.addEventListener('focusin', focusin);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('keydown', keydown);
      document.removeEventListener('focusin', focusin);
      if (opener.current?.isConnected) opener.current.focus({ preventScroll: true });
    };
  }, [enabled, initialFocus]);
  return dialog;
}
