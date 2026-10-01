"use client";

import { OwnerApiError, OwnerShell, useOwnerToken } from "@/components/owner/OwnerShell";
import { apiRequest } from "@/lib/api/client";
import { listBusinesses, listLocations } from "@/lib/api/ownerApi";
import { authHeaders } from "@/lib/owner/auth";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

type StaffRow = {
  id: string;
  display_name: string;
  title: string;
  is_active: boolean;
  is_bookable: boolean;
};

export function OwnerStaffClient() {
  const token = useOwnerToken();
  const [businessId, setBusinessId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([]);
  const [businessName, setBusinessName] = useState("");
  const [rows, setRows] = useState<StaffRow[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [form, setForm] = useState({ display_name: "", title: "" });

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
      setLocations(locs.results || []);
      const loc = locationId || locs.results?.[0]?.id || "";
      if (!locationId && loc) setLocationId(loc);
      const data = await apiRequest<{ results: StaffRow[] }>(
        `/api/v1/businesses/${biz}/staff/`,
        {
          headers: authHeaders(token),
          query: { limit: 50, location_id: loc || undefined },
        },
      );
      setRows(data.results || []);
    } catch (err) {
      setError(err);
    }
  }, [token, businessId, locationId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function addStaff() {
    if (!token || !businessId || !locationId || !form.display_name.trim()) return;
    await apiRequest(`/api/v1/businesses/${businessId}/staff/`, {
      method: "POST",
      headers: authHeaders(token),
      body: {
        display_name: form.display_name.trim(),
        title: form.title,
        location_id: locationId,
        is_active: true,
        is_bookable: true,
      },
    });
    setForm({ display_name: "", title: "" });
    await load();
  }

  return (
    <OwnerShell
      title="Staff"
      businessName={businessName}
      locations={locations}
      locationId={locationId}
      onLocationChange={setLocationId}
    >
      {error ? <OwnerApiError error={error} /> : null}
      <ul className="owner-simple-list">
        {rows.map((row) => (
          <li key={row.id}>
            <span>
              <strong>{row.display_name}</strong>
              {row.title ? ` · ${row.title}` : ""} ·{" "}
              {row.is_active ? "Active" : "Inactive"}
            </span>
          </li>
        ))}
      </ul>
      {rows.length === 0 ? (
        <p className="muted">
          Add staff and availability before accepting bookings.{" "}
          <Link href="/owner/onboarding">Continue setup</Link>
        </p>
      ) : null}
      <section className="owner-card">
        <h2>Add staff</h2>
        <label>
          Name
          <input
            value={form.display_name}
            onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
          />
        </label>
        <label>
          Title
          <input
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
          />
        </label>
        <button type="button" className="primary" onClick={() => void addStaff()}>
          + Add staff
        </button>
        <p className="muted">
          Configure hours in <Link href="/owner/onboarding">Setup → Availability</Link>.
        </p>
      </section>
    </OwnerShell>
  );
}
