import { apiRequest } from "./client";
import type { Paginated, PublicStaff } from "./types";

export async function listPublicStaff(slug: string, signal?: AbortSignal) {
  const data = await apiRequest<Paginated<PublicStaff>>(
    `/api/v1/public/locations/${encodeURIComponent(slug)}/staff/`,
    {
      query: { limit: 100, offset: 0 },
      signal,
      cache: "force-cache",
    },
  );
  return data.results;
}
