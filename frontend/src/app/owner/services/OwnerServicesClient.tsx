"use client";

import { OwnerApiError, OwnerShell, useOwnerToken } from "@/components/owner/OwnerShell";
import { apiRequest } from "@/lib/api/client";
import { listBusinesses, listLocations } from "@/lib/api/ownerApi";
import { authHeaders } from "@/lib/owner/auth";
import { useCallback, useEffect, useState } from "react";

type ServiceRow = {
  id: string;
  name: string;
  duration_minutes: number;
  price: string;
  currency: string;
  is_active: boolean;
};

export function OwnerServicesClient() {
  const token = useOwnerToken();
  const [businessId, setBusinessId] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [locationId, setLocationId] = useState("");
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([]);
  const [rows, setRows] = useState<ServiceRow[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState("");
  const [form, setForm] = useState({
    name: "",
    duration_minutes: "30",
    price: "400",
  });

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
      const data = await apiRequest<{ results: ServiceRow[] }>(
        `/api/v1/businesses/${biz}/services/`,
        { headers: authHeaders(token), query: { limit: 50 } },
      );
      setRows(data.results || []);
    } catch (err) {
      setError(err);
    }
  }, [token, businessId, locationId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function addService() {
    if (!token || !businessId || !locationId || !form.name.trim()) return;
    setError(null);
    try {
      const created = await apiRequest<{ id: string }>(
        `/api/v1/businesses/${businessId}/services/`,
        {
          method: "POST",
          headers: authHeaders(token),
          body: {
            name: form.name.trim(),
            duration_minutes: Number(form.duration_minutes),
            price: form.price,
            is_active: true,
            is_bookable_online: true,
          },
        },
      );
      await apiRequest(
        `/api/v1/businesses/${businessId}/services/${created.id}/service-locations/`,
        {
          method: "POST",
          headers: authHeaders(token),
          body: { location_id: locationId },
        },
      );
      setForm({ name: "", duration_minutes: "30", price: "400" });
      setMessage("Service added");
      await load();
    } catch (err) {
      setError(err);
    }
  }

  async function toggleActive(row: ServiceRow) {
    if (!token || !businessId) return;
    setError(null);
    try {
      await apiRequest(`/api/v1/businesses/${businessId}/services/${row.id}/`, {
        method: "PATCH",
        headers: authHeaders(token),
        body: { is_active: !row.is_active },
      });
      await load();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <OwnerShell
      title="Services"
      businessName={businessName}
      locations={locations}
      locationId={locationId}
      onLocationChange={setLocationId}
    >
      {error ? <OwnerApiError error={error} /> : null}
      {message ? (
        <p className="muted" aria-live="polite">
          {message}
        </p>
      ) : null}
      <ul className="owner-simple-list">
        {rows.map((row) => (
          <li key={row.id}>
            <span>
              <strong>{row.name}</strong> · ₹{row.price} · {row.duration_minutes} min ·{" "}
              {row.is_active ? "Active" : "Inactive"}
            </span>
            <button type="button" className="ghost" onClick={() => void toggleActive(row)}>
              {row.is_active ? "Deactivate" : "Activate"}
            </button>
          </li>
        ))}
      </ul>
      {rows.length === 0 ? (
        <p className="muted">Add your first service to start accepting bookings.</p>
      ) : null}
      <section className="owner-card">
        <h2>Add service</h2>
        <label>
          Name
          <input
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
        </label>
        <label>
          Duration (minutes)
          <input
            value={form.duration_minutes}
            onChange={(e) => setForm((f) => ({ ...f, duration_minutes: e.target.value }))}
          />
        </label>
        <label>
          Price
          <input
            value={form.price}
            onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))}
          />
        </label>
        <button type="button" className="primary" onClick={() => void addService()}>
          + Add service
        </button>
      </section>
    </OwnerShell>
  );
}
