import { apiRequest } from "@/lib/api/client";
import { authHeaders } from "@/lib/owner/auth";
import type {
  BusinessDashboard,
  BusinessLaunchStatus,
  BusinessSetupStatus,
  CustomerSummary,
  GoogleBusinessAccountOption,
  GoogleBusinessLocationOption,
  GoogleBusinessStatus,
  Paginated,
  RetentionSegment,
  RetentionSettings,
  RetentionSummary,
  WebsiteManagementStatus,
  WhatsAppConnectionStatus,
  WhatsAppInboundMessage,
  WhatsAppTemplate,
} from "@/lib/api/types";

export function getBusinessSetup(
  businessId: string,
  token: string,
  locationId?: string | null,
  signal?: AbortSignal,
) {
  return apiRequest<BusinessSetupStatus>(
    `/api/v1/businesses/${businessId}/setup/`,
    {
      headers: authHeaders(token),
      query: locationId ? { location_id: locationId } : undefined,
      signal,
      cache: "no-store",
    },
  );
}

export function getBusinessDashboard(
  businessId: string,
  token: string,
  locationId?: string | null,
  signal?: AbortSignal,
) {
  return apiRequest<BusinessDashboard>(
    `/api/v1/businesses/${businessId}/dashboard/`,
    {
      headers: authHeaders(token),
      query: locationId ? { location_id: locationId } : undefined,
      signal,
      cache: "no-store",
    },
  );
}

export function getBusinessLaunchProfile(
  businessId: string,
  token: string,
  locationId?: string | null,
  signal?: AbortSignal,
) {
  return apiRequest<BusinessLaunchStatus>(
    `/api/v1/businesses/${businessId}/launch-profile/`,
    {
      headers: authHeaders(token),
      query: locationId ? { location_id: locationId } : undefined,
      signal,
      cache: "no-store",
    },
  );
}

export function updateBusinessLaunchProfile(
  businessId: string,
  token: string,
  body: Record<string, unknown>,
  locationId?: string | null,
) {
  return apiRequest<{
    profile: BusinessLaunchStatus["profile"];
    launch: BusinessLaunchStatus;
  }>(`/api/v1/businesses/${businessId}/launch-profile/`, {
    method: "PATCH",
    headers: authHeaders(token),
    query: locationId ? { location_id: locationId } : undefined,
    body,
    cache: "no-store",
  });
}

export function listBusinesses(token: string, signal?: AbortSignal) {
  return apiRequest<Paginated<{ id: string; name: string; vertical: string }>>(
    "/api/v1/businesses/",
    {
      headers: authHeaders(token),
      query: { limit: 50 },
      signal,
      cache: "no-store",
    },
  );
}

export function listLocations(
  businessId: string,
  token: string,
  signal?: AbortSignal,
) {
  return apiRequest<
    Paginated<{
      id: string;
      name: string;
      slug: string;
      timezone: string;
      is_primary: boolean;
    }>
  >(`/api/v1/businesses/${businessId}/locations/`, {
    headers: authHeaders(token),
    query: { limit: 50 },
    signal,
    cache: "no-store",
  });
}

export function getWebsitePreview(
  businessId: string,
  token: string,
  locationId?: string | null,
  signal?: AbortSignal,
) {
  return apiRequest<import("@/lib/api/types").PublicSalonSite>(
    `/api/v1/businesses/${businessId}/website/preview/`,
    {
      headers: authHeaders(token),
      query: locationId ? { location_id: locationId } : undefined,
      signal,
      cache: "no-store",
    },
  );
}

export function getWebsiteStatus(
  businessId: string,
  token: string,
  locationId?: string | null,
  signal?: AbortSignal,
) {
  return apiRequest<WebsiteManagementStatus>(`/api/v1/businesses/${businessId}/website/`, {
    headers: authHeaders(token),
    query: locationId ? { location_id: locationId } : undefined,
    signal,
    cache: "no-store",
  });
}

export function publishWebsite(
  businessId: string,
  token: string,
  locationId?: string | null,
) {
  return apiRequest<WebsiteManagementStatus>(
    `/api/v1/businesses/${businessId}/website/publish/`,
    {
      method: "POST",
      headers: authHeaders(token),
      query: locationId ? { location_id: locationId } : undefined,
      body: {},
      cache: "no-store",
    },
  );
}

export function unpublishWebsite(
  businessId: string,
  token: string,
  locationId?: string | null,
) {
  return apiRequest<WebsiteManagementStatus>(
    `/api/v1/businesses/${businessId}/website/unpublish/`,
    {
      method: "POST",
      headers: authHeaders(token),
      query: locationId ? { location_id: locationId } : undefined,
      body: {},
      cache: "no-store",
    },
  );
}

export function getGoogleBusinessStatus(
  businessId: string,
  locationId: string,
  token: string,
  signal?: AbortSignal,
) {
  return apiRequest<GoogleBusinessStatus>(
    `/api/v1/businesses/${businessId}/locations/${locationId}/google/`,
    {
      headers: authHeaders(token),
      signal,
      cache: "no-store",
    },
  );
}

export function startGoogleBusinessConnect(
  businessId: string,
  locationId: string,
  token: string,
) {
  return apiRequest<GoogleBusinessStatus>(
    `/api/v1/businesses/${businessId}/locations/${locationId}/google/`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: {},
      cache: "no-store",
    },
  );
}

export function disconnectGoogleBusiness(
  businessId: string,
  locationId: string,
  token: string,
) {
  return apiRequest<GoogleBusinessStatus>(
    `/api/v1/businesses/${businessId}/locations/${locationId}/google/disconnect/`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: {},
      cache: "no-store",
    },
  );
}

export function getGoogleBusinessAccounts(
  businessId: string,
  locationId: string,
  token: string,
) {
  return apiRequest<{
    accounts: GoogleBusinessAccountOption[];
    count: number;
    selected_account_name: string | null;
    account_selection_required: boolean;
    auto_selected: boolean;
    connection: GoogleBusinessStatus;
  }>(`/api/v1/businesses/${businessId}/locations/${locationId}/google/accounts/`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
}

export function selectGoogleBusinessAccount(
  businessId: string,
  locationId: string,
  token: string,
  googleAccountName: string,
) {
  return apiRequest<{
    selected_account: GoogleBusinessAccountOption;
    connection: GoogleBusinessStatus;
  }>(`/api/v1/businesses/${businessId}/locations/${locationId}/google/accounts/`, {
    method: "POST",
    headers: authHeaders(token),
    body: { google_account_name: googleAccountName },
    cache: "no-store",
  });
}

export function getGoogleBusinessLocations(
  businessId: string,
  locationId: string,
  token: string,
  accountName?: string,
) {
  const query = accountName
    ? `?account_name=${encodeURIComponent(accountName)}`
    : "";
  return apiRequest<{
    account_name: string;
    locations: GoogleBusinessLocationOption[];
    count: number;
    selected_location_id: string | null;
    location_selection_required: boolean;
    connection: GoogleBusinessStatus;
  }>(
    `/api/v1/businesses/${businessId}/locations/${locationId}/google/locations/${query}`,
    {
      headers: authHeaders(token),
      cache: "no-store",
    },
  );
}

export function selectGoogleBusinessLocation(
  businessId: string,
  locationId: string,
  token: string,
  body: { google_location_id: string; google_account_name?: string },
) {
  return apiRequest<{
    selected_location: GoogleBusinessLocationOption;
    connection: GoogleBusinessStatus;
  }>(
    `/api/v1/businesses/${businessId}/locations/${locationId}/google/select-location/`,
    {
      method: "POST",
      headers: authHeaders(token),
      body,
      cache: "no-store",
    },
  );
}

export function syncGoogleBookingUrl(
  businessId: string,
  locationId: string,
  token: string,
) {
  return apiRequest<{
    success: boolean;
    status: string;
    url: string | null;
    message: string;
    connection?: GoogleBusinessStatus;
  }>(`/api/v1/businesses/${businessId}/locations/${locationId}/google/sync-url/`, {
    method: "POST",
    headers: authHeaders(token),
    body: {},
    cache: "no-store",
  });
}

export function getWhatsAppConnection(businessId: string, token: string) {
  return apiRequest<WhatsAppConnectionStatus>(
    `/api/v1/businesses/${businessId}/whatsapp/`,
    { headers: authHeaders(token), cache: "no-store" },
  );
}

export function connectWhatsApp(
  businessId: string,
  token: string,
  body: {
    access_token: string;
    phone_number_id: string;
    business_account_id: string;
    display_phone_number?: string;
  },
) {
  return apiRequest<WhatsAppConnectionStatus>(
    `/api/v1/businesses/${businessId}/whatsapp/connect/`,
    { method: "POST", headers: authHeaders(token), body, cache: "no-store" },
  );
}

export function disconnectWhatsApp(businessId: string, token: string) {
  return apiRequest<WhatsAppConnectionStatus>(
    `/api/v1/businesses/${businessId}/whatsapp/disconnect/`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: {},
      cache: "no-store",
    },
  );
}

export function listWhatsAppTemplates(businessId: string, token: string) {
  return apiRequest<Paginated<WhatsAppTemplate>>(
    `/api/v1/businesses/${businessId}/whatsapp/templates/`,
    { headers: authHeaders(token), cache: "no-store" },
  );
}

export function listWhatsAppInboundMessages(
  businessId: string,
  token: string,
  query: {
    limit?: number;
    offset?: number;
    phone?: string;
    message_type?: string;
    processing_status?: string;
  } = {},
) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<Paginated<WhatsAppInboundMessage>>(
    `/api/v1/businesses/${businessId}/whatsapp/inbound/${suffix}`,
    { headers: authHeaders(token), cache: "no-store" },
  );
}

export function syncWhatsAppTemplates(businessId: string, token: string) {
  return apiRequest<{ created: number; updated: number }>(
    `/api/v1/businesses/${businessId}/whatsapp/templates/sync/`,
    { method: "POST", headers: authHeaders(token), body: {}, cache: "no-store" },
  );
}

export function createWhatsAppTemplate(
  businessId: string,
  token: string,
  body: {
    name: string;
    language: string;
    category: string;
    purpose?: string;
    body: string;
    status?: string;
    variables?: string[];
  },
) {
  return apiRequest<WhatsAppTemplate>(
    `/api/v1/businesses/${businessId}/whatsapp/templates/`,
    { method: "POST", headers: authHeaders(token), body, cache: "no-store" },
  );
}

export function deleteWhatsAppTemplate(
  businessId: string,
  token: string,
  templateId: string,
) {
  return apiRequest<void>(
    `/api/v1/businesses/${businessId}/whatsapp/templates/${templateId}/`,
    {
      method: "DELETE",
      headers: authHeaders(token),
      cache: "no-store",
    },
  );
}

export function listCustomers(
  businessId: string,
  token: string,
  options?: {
    segment?: RetentionSegment | "";
    signal?: AbortSignal;
  },
) {
  const segment = options?.segment || undefined;
  return apiRequest<Paginated<CustomerSummary>>(
    `/api/v1/businesses/${businessId}/customers/`,
    {
      headers: authHeaders(token),
      query: { limit: 50, segment: segment || undefined },
      signal: options?.signal,
      cache: "no-store",
    },
  );
}

export function getCustomerRetentionSummary(
  businessId: string,
  customerId: string,
  token: string,
  signal?: AbortSignal,
) {
  return apiRequest<RetentionSummary>(
    `/api/v1/businesses/${businessId}/customers/${customerId}/retention-summary/`,
    {
      headers: authHeaders(token),
      signal,
      cache: "no-store",
    },
  );
}

export function getRetentionSettings(
  businessId: string,
  token: string,
  signal?: AbortSignal,
) {
  return apiRequest<RetentionSettings>(
    `/api/v1/businesses/${businessId}/retention-settings/`,
    {
      headers: authHeaders(token),
      signal,
      cache: "no-store",
    },
  );
}

export function updateRetentionSettings(
  businessId: string,
  token: string,
  body: {
    return_after_days?: number;
    inactive_after_days?: number;
    due_message_delay_hours?: number;
    enabled?: boolean;
  },
) {
  return apiRequest<RetentionSettings>(
    `/api/v1/businesses/${businessId}/retention-settings/`,
    {
      method: "PATCH",
      headers: authHeaders(token),
      body,
      cache: "no-store",
    },
  );
}

export function getOwnerMe(token: string, signal?: AbortSignal) {
  return apiRequest<{
    membership: { role: string; is_active: boolean } | null;
  }>("/api/v1/auth/me/", {
    headers: authHeaders(token),
    signal,
    cache: "no-store",
  });
}
