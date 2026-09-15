import { connectPlatformEvents } from "./localPlatformService";

export const CUSTOMER_REFRESH_EVENTS = new Set([
  "new_message", "message_received", "new_reply", "conversation_updated", "customer_context_updated",
  "conversation_history_imported", "customer_image_updated", "customer_image_archived",
  "customer_image_failed", "customer_image_deleted", "conversation_group_updated",
]);

/** Coalesce archive bursts; no AI event is required to refresh customer views. */
export function subscribeCustomerEvents(refresh: () => void) {
  let timer: number | undefined;
  const disconnect = connectPlatformEvents((event) => {
    if (!CUSTOMER_REFRESH_EVENTS.has(String(event.type))) return;
    if (timer !== undefined) return;
    timer = window.setTimeout(() => { timer = undefined; refresh(); }, 120);
  });
  return () => { if (timer !== undefined) window.clearTimeout(timer); disconnect(); };
}
