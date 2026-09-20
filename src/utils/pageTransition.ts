import { flushSync } from "react-dom";

let activeTransition: ViewTransition | null = null;
const hasNativeViewTransitions = typeof document.startViewTransition === "function";

document.documentElement.classList.toggle("view-transitions-enabled", hasNativeViewTransitions);

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function runPageTransition(update: () => void) {
  const startViewTransition = hasNativeViewTransitions
    ? document.startViewTransition.bind(document)
    : undefined;

  // A live WebGL background makes native full-document snapshots costly.
  // Aurora uses the existing CSS entrance transition on the same business tree.
  if (document.body.dataset.xunyingVisual === 'aurora') {
    try { activeTransition?.skipTransition(); } catch { /* Already finished. */ }
    activeTransition = null;
    update();
    return;
  }

  if (!startViewTransition || prefersReducedMotion()) {
    update();
    return;
  }

  if (activeTransition) {
    try {
      activeTransition.skipTransition();
    } catch {
      // A navigation or reload can finish the native transition between the
      // state check and skipTransition(). Treat that race as already settled.
      activeTransition = null;
    }
  }

  try {
    const transition = startViewTransition.call(document, () => {
      flushSync(update);
    });
    activeTransition = transition;

    // `skipTransition()` and a rapid hash navigation can reject `ready` even
    // though `finished` settles cleanly. Observe every native promise so that
    // an expected cancelled animation never leaks an unhandled
    // InvalidStateError into the browser console.
    void transition.ready.catch(() => undefined);
    void transition.updateCallbackDone.catch(() => undefined);
    void transition.finished.then(
      () => {
        if (activeTransition === transition) activeTransition = null;
      },
      () => {
        if (activeTransition === transition) activeTransition = null;
      },
    );
  } catch {
    activeTransition = null;
    update();
  }
}
