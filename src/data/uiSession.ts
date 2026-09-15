/** UI-only values. Never store messages, credentials, grants or business records here. */
export function readUiSession(key: string, fallback = '') {
  try { return sessionStorage.getItem(`xunying:ui:${key}`) ?? fallback; } catch { return fallback; }
}
export function writeUiSession(key: string, value: string) {
  try { sessionStorage.setItem(`xunying:ui:${key}`, value); } catch { /* Storage may be disabled. */ }
}
