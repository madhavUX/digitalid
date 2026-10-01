import { apiRequest } from "./client";
import type { PublicLocation } from "./types";

export function getPublicLocation(slug: string, signal?: AbortSignal) {
  return apiRequest<PublicLocation>(`/api/v1/public/locations/${encodeURIComponent(slug)}/`, {
    signal,
    cache: "force-cache",
  });
}
