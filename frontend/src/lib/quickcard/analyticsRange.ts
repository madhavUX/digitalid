export type AnalyticsPreset = "7" | "30" | "90" | "custom";

export type AnalyticsDateQuery = {
  dateFrom: string;
  dateTo: string;
};

export function utcISODate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Inclusive UTC calendar days ending today. Last 7 days is today and the six days before it. */
export function presetAnalyticsRange(
  days: 7 | 30 | 90,
  now: Date = new Date(),
): AnalyticsDateQuery {
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - (days - 1));
  return { dateFrom: utcISODate(start), dateTo: utcISODate(end) };
}

export function customAnalyticsRange(start: string, end: string): AnalyticsDateQuery | null {
  if (!start || !end || start > end) return null;
  return { dateFrom: start, dateTo: end };
}

export function customRangeMessage(start: string, end: string): string | null {
  if (!start) return "Choose a start date.";
  if (!end) return "Choose an end date.";
  if (start > end) return "Start date must be on or before the end date.";
  return null;
}

export function formatAnalyticsDay(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return isoDate;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}
