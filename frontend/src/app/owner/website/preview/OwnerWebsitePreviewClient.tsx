"use client";

import { OwnerApiError, OwnerShell, useOwnerToken } from "@/components/owner/OwnerShell";
import { WebsiteTemplateRenderer } from "@/components/website/WebsiteTemplates";
import "@/components/website/website.css";
import {
  getWebsitePreview,
  listBusinesses,
  listLocations,
} from "@/lib/api/ownerApi";
import type { PublicSalonSite } from "@/lib/api/types";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

export function OwnerWebsitePreviewClient() {
  const token = useOwnerToken();
  const search = useSearchParams();
  const [businessId, setBusinessId] = useState(search.get("business_id") || "");
  const [locationId, setLocationId] = useState(search.get("location_id") || "");
  const [data, setData] = useState<PublicSalonSite | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [businessName, setBusinessName] = useState("");

  const load = useCallback(async () => {
    if (!token) return;
    try {
      let biz = businessId;
      if (!biz) {
        const list = await listBusinesses(token);
        biz = list.results?.[0]?.id || "";
        setBusinessId(biz);
        setBusinessName(list.results?.[0]?.name || "");
      }
      if (!biz) return;
      const locs = await listLocations(biz, token);
      const loc = locationId || locs.results?.[0]?.id || "";
      if (!locationId && loc) setLocationId(loc);
      if (!loc) return;
      const preview = await getWebsitePreview(biz, token, loc);
      setData(preview);
    } catch (err) {
      setError(err);
    }
  }, [token, businessId, locationId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <OwnerShell title="Website preview" businessName={businessName || data?.business.name}>
      {error ? <OwnerApiError error={error} /> : null}
      <p className="muted">
        Preview uses your live business data.{" "}
        <Link href="/owner/website">Manage website</Link>
      </p>
      {!data ? <p className="muted">Loading preview…</p> : null}
      {data ? <WebsiteTemplateRenderer data={data} preview /> : null}
    </OwnerShell>
  );
}
