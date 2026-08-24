const beijingTimeZone = "Asia/Shanghai";

function parseTrafficDateTime(value: string) {
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(value);
  const isDateTime = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value);
  return new Date(isDateTime && !hasTimezone ? `${value}Z` : value);
}

function numericPart(
  parts: Intl.DateTimeFormatPart[],
  type: Intl.DateTimeFormatPartTypes,
) {
  return Number(parts.find((part) => part.type === type)?.value || 0);
}

/** Exposure-specific Beijing time, for example `8月13日16时20分`. */
export function formatTrafficDateTime(
  value: string | null | undefined,
  fallback = "时间未记录",
) {
  if (!value) return fallback;
  const parsed = parseTrafficDateTime(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: beijingTimeZone,
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(parsed);
  const minute = String(numericPart(parts, "minute")).padStart(2, "0");
  return `${numericPart(parts, "month")}月${numericPart(parts, "day")}日${numericPart(parts, "hour")}时${minute}分`;
}

/** Compact Beijing calendar label used by the seven-day plan. */
export function formatTrafficPlanDate(value: string) {
  const parsed = new Date(`${value}T00:00:00+08:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: beijingTimeZone,
    month: "numeric",
    day: "numeric",
  }).formatToParts(parsed);
  return `${numericPart(parts, "month")}月${numericPart(parts, "day")}日`;
}

/** A plan action with a concrete time always uses the full traffic format. */
export function formatTrafficPlanSlotDateTime(date: string, time: string) {
  if (!/^\d{2}:\d{2}$/.test(time)) return `${formatTrafficPlanDate(date)} ${time}`;
  return formatTrafficDateTime(`${date}T${time}:00+08:00`);
}
