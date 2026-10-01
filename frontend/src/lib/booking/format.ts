export function formatMoney(amount: string, currency: string): string {
  const value = Number(amount);
  if (Number.isNaN(value)) return `${currency} ${amount}`;
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: currency || "INR",
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${amount}`;
  }
}

export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  if (rem === 0) return hours === 1 ? "1 hr" : `${hours} hrs`;
  return `${hours}h ${rem}m`;
}

/** Format an ISO datetime in the given IANA timezone. */
export function formatInTimezone(
  iso: string,
  timeZone: string,
  options: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat("en-IN", { timeZone, ...options }).format(
    new Date(iso),
  );
}

export function localDateKey(timeZone: string, date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function addDaysToDateKey(dateKey: string, days: number): string {
  const [y, m, d] = dateKey.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

export function buildDateOptions(timeZone: string, days = 21): string[] {
  const start = localDateKey(timeZone);
  return Array.from({ length: days }, (_, i) => addDaysToDateKey(start, i));
}

export function formatDateLabel(dateKey: string, timeZone: string): string {
  const iso = `${dateKey}T12:00:00`;
  return formatInTimezone(iso, timeZone, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

export function formatAddress(parts: {
  line1: string;
  line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
}): string {
  return [parts.line1, parts.line2, parts.city, parts.state, parts.postal_code]
    .map((p) => p?.trim())
    .filter(Boolean)
    .join(", ");
}

/** Normalize phone for API: keep digits; leave E.164/+91 handling to Django. */
export function normalizePhoneInput(value: string): string {
  const trimmed = value.trim().replace(/[\s-]/g, "");
  if (trimmed.startsWith("+")) {
    return `+${trimmed.slice(1).replace(/\D/g, "")}`;
  }
  return trimmed.replace(/\D/g, "");
}
