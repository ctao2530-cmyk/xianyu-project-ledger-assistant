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

  if (!startViewTransition || prefersReducedMotion()) {
    update();
    return;
  }

  activeTransition?.skipTransition();

  try {
    const transition = startViewTransition.call(document, () => {
      flushSync(update);
    });
    activeTransition = transition;
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
