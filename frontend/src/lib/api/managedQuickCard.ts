import { apiRequest } from "./client";
import type { ManagedQuickCard, QuickCardAnalytics } from "./types";

function authHeaders(accessToken: string) {
  return { Authorization: `Bearer ${accessToken}` };
}

export function getManagedQuickCard(
  businessId: string,
  locationId: string,
  accessToken: string,
  signal?: AbortSignal,
) {
  return apiRequest<ManagedQuickCard>(
    `/api/v1/businesses/${businessId}/locations/${locationId}/quickcard/`,
    { headers: authHeaders(accessToken), signal, cache: "no-store" },
  );
}

export function createManagedQuickCard(
  businessId: string,
  locationId: string,
  accessToken: string,
  body: Partial<ManagedQuickCard> & { slug?: string; is_published?: boolean },
) {
  return apiRequest<ManagedQuickCard>(
    `/api/v1/businesses/${businessId}/locations/${locationId}/quickcard/`,
    {
      method: "POST",
      body,
      headers: authHeaders(accessToken),
      cache: "no-store",
    },
  );
}

export function updateManagedQuickCard(
  businessId: string,
  locationId: string,
  accessToken: string,
  body: Partial<ManagedQuickCard>,
) {
  return apiRequest<ManagedQuickCard>(
    `/api/v1/businesses/${businessId}/locations/${locationId}/quickcard/`,
    {
      method: "PATCH",
      body,
      headers: authHeaders(accessToken),
      cache: "no-store",
    },
  );
}

export function publishManagedQuickCard(
  businessId: string,
  locationId: string,
  accessToken: string,
) {
  return apiRequest<ManagedQuickCard>(
    `/api/v1/businesses/${businessId}/locations/${locationId}/quickcard/publish/`,
    { method: "POST", headers: authHeaders(accessToken), cache: "no-store" },
  );
}

export function unpublishManagedQuickCard(
  businessId: string,
  locationId: string,
  accessToken: string,
) {
  return apiRequest<ManagedQuickCard>(
    `/api/v1/businesses/${businessId}/locations/${locationId}/quickcard/unpublish/`,
    { method: "POST", headers: authHeaders(accessToken), cache: "no-store" },
  );
}

export type QuickCardAnalyticsQuery = {
  locationId?: string;
  dateFrom?: string;
  dateTo?: string;
};

export function getQuickCardAnalytics(
  businessId: string,
  accessToken: string,
  query: QuickCardAnalyticsQuery = {},
) {
  return apiRequest<QuickCardAnalytics>(
    `/api/v1/businesses/${businessId}/quickcard/analytics/`,
    {
      headers: authHeaders(accessToken),
      cache: "no-store",
      query: {
        location_id: query.locationId,
        date_from: query.dateFrom,
        date_to: query.dateTo,
      },
    },
  );
}

export function managedQuickCardQrUrl(
  businessId: string,
  locationId: string,
): string {
  const base =
    (typeof window !== "undefined"
      ? process.env.NEXT_PUBLIC_API_BASE_URL
      : process.env.DJANGO_API_URL) || "/backend";
  return `${base.replace(/\/$/, "")}/api/v1/businesses/${businessId}/locations/${locationId}/quickcard/qr/`;
}
