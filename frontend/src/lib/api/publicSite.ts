import { apiRequest } from "@/lib/api/client";
import type { PublicSalonSite } from "@/lib/api/types";

export function getPublicSite(slug: string, signal?: AbortSignal) {
  return apiRequest<PublicSalonSite>(`/api/v1/public/sites/${encodeURIComponent(slug)}/`, {
    signal,
    cache: "no-store",
  });
}
