import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  status: number;
  code?: string;
  body: unknown;

  constructor(status: number, body: unknown) {
    const parsed = body as ApiErrorBody | null;
    const message =
      formatErrorMessage(parsed?.error) || `Request failed (${status})`;
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = parsed?.code;
    this.body = body;
  }
}

function formatErrorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (Array.isArray(error)) return error.map(formatErrorMessage).join(" ");
  if (error && typeof error === "object") {
    return Object.values(error as Record<string, unknown>)
      .map(formatErrorMessage)
      .filter(Boolean)
      .join(" ");
  }
  return "";
}

export function friendlyApiMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "Something went wrong. Please try again.";
  }
  if (error.status === 404) {
    return "We couldn’t find that page or booking.";
  }
  if (error.status === 409 || error.code === "SLOT_UNAVAILABLE") {
    return "That time was just booked. Please choose another available time.";
  }
  if (error.status === 429) {
    return "Too many requests. Please wait a moment and try again.";
  }
  if (error.status >= 500) {
    return "Our servers are having trouble. Please try again shortly.";
  }
  if (error.code === "INVALID_CUSTOMER") {
    return "Please check your name and phone number.";
  }
  return error.message || "Please check your details and try again.";
}

function apiBaseUrl(): string {
  if (typeof window === "undefined") {
    return (
      process.env.DJANGO_API_URL?.replace(/\/$/, "") ||
      "http://127.0.0.1:8000"
    );
  }
  return process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "/backend";
}

type RequestOptions = {
  method?: string;
  query?: Record<string, string | number | null | undefined>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  cache?: RequestCache;
  next?: { revalidate?: number };
};

function buildUrl(
  path: string,
  query?: RequestOptions["query"],
): string {
  const base = apiBaseUrl();
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  if (base.startsWith("http://") || base.startsWith("https://")) {
    const url = new URL(`${base}${normalizedPath}`);
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value === undefined || value === null || value === "") continue;
        url.searchParams.set(key, String(value));
      }
    }
    return url.toString();
  }

  const params = new URLSearchParams();
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return `${base}${normalizedPath}${qs ? `?${qs}` : ""}`;
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const response = await fetch(buildUrl(path, options.query), {
    method: options.method || "GET",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
    cache: options.cache ?? "no-store",
    next: options.next,
  });

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: text, status_code: response.status };
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, data);
  }
  return data as T;
}
