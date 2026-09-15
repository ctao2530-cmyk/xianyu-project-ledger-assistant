export const MESSAGE_TIME_GAP_MS = 5 * 60 * 1000;

const day = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' });
const full = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
const label = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

export function showMessageTime(current: string, previous?: string): boolean {
  if (!previous) return true;
  const now = new Date(current), before = new Date(previous);
  if (!Number.isFinite(now.getTime()) || !Number.isFinite(before.getTime())) return true;
  return day.format(now) !== day.format(before) || Math.abs(now.getTime() - before.getTime()) > MESSAGE_TIME_GAP_MS;
}

export function messageTime(value: string, precise = false): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? (precise ? full : label).format(date) : '时间未知';
}
