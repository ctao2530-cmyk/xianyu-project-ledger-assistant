const dayFormat = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' });
const clockFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

function calendarDay(date: Date) {
  const parts = dayFormat.formatToParts(date);
  const value = (type: string) => parts.find(part => part.type === type)!.value;
  const year = value('year'), month = value('month'), day = value('day');
  return { year, month, day, ordinal: Date.UTC(Number(year), Number(month) - 1, Number(day)) / 86400000 };
}

/** Display only: never changes the stored platform timestamp. */
export function customerListTime(value: string, now = new Date()): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '时间未知';
  const messageDay = calendarDay(date), today = calendarDay(now);
  const age = today.ordinal - messageDay.ordinal;
  if (age === 0) return clockFormat.format(date);
  if (age === 1) return `昨天 ${clockFormat.format(date)}`;
  return `${messageDay.year === today.year ? '' : `${messageDay.year}/`}${messageDay.month}/${messageDay.day}`;
}
