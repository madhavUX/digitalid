import { apiRequest } from "./client";
import type { PublicQuickCard } from "./types";

export function getPublicQuickCard(slug: string, signal?: AbortSignal) {
  return apiRequest<PublicQuickCard>(
    `/api/v1/public/quickcards/${encodeURIComponent(slug)}/`,
    { signal, cache: "force-cache", next: { revalidate: 60 } },
  );
}
