import { apiRequest } from "./client";
import type { Paginated, PublicService } from "./types";

export async function listPublicServices(slug: string, signal?: AbortSignal) {
  const data = await apiRequest<Paginated<PublicService>>(
    `/api/v1/public/locations/${encodeURIComponent(slug)}/services/`,
    {
      query: { limit: 100, offset: 0 },
      signal,
      cache: "force-cache",
    },
  );
  return data.results;
}
