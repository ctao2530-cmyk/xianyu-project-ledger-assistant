import { useLayoutEffect, type RefObject } from 'react';

/** Follow the latest message after an explicit selection, until the operator reads upward. */
export function followLatestMessage(element: HTMLElement) {
  let following = true;
  let frame = 0;
  const bottom = () => {
    if (!following) return;
    element.scrollTop = element.scrollHeight;
  };
  const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(bottom); };
  const stop = () => { following = false; };
  const wheel = (event: WheelEvent) => { if (event.deltaY < 0) stop(); };
  const key = (event: KeyboardEvent) => { if (['ArrowUp', 'PageUp', 'Home'].includes(event.key)) stop(); };
  const resize = new ResizeObserver(schedule);
  const observe = () => {
    resize.disconnect();
    resize.observe(element);
    for (const child of element.children) resize.observe(child);
    schedule();
  };
  const mutation = new MutationObserver(observe);
  mutation.observe(element, { childList: true, subtree: true });
  element.addEventListener('load', schedule, true);
  element.addEventListener('wheel', wheel, { passive: true });
  element.addEventListener('touchstart', stop, { passive: true });
  element.addEventListener('pointerdown', stop);
  element.addEventListener('keydown', key);
  bottom();
  observe();
  return () => {
    following = false;
    cancelAnimationFrame(frame);
    resize.disconnect();
    mutation.disconnect();
    element.removeEventListener('load', schedule, true);
    element.removeEventListener('wheel', wheel);
    element.removeEventListener('touchstart', stop);
    element.removeEventListener('pointerdown', stop);
    element.removeEventListener('keydown', key);
  };
}

export function useLatestMessageScroll(ref: RefObject<HTMLElement | null>, identity: string | number | null, request: number, ready: boolean) {
  useLayoutEffect(() => {
    if (ready && ref.current) return followLatestMessage(ref.current);
  }, [ref, identity, request, ready]);
}
