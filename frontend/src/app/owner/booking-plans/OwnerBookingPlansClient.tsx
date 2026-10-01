"use client";

import { OwnerApiError, OwnerShell, useOwnerToken } from "@/components/owner/OwnerShell";
import { apiRequest } from "@/lib/api/client";
import { listBusinesses, listLocations } from "@/lib/api/ownerApi";
import { authHeaders } from "@/lib/owner/auth";
import { useCallback, useEffect, useState } from "react";

type PlanRow = {
  customer_name: string;
  service_name: string;
  frequency_label: string;
  staff_name: string | null;
  status: string;
  needs_action: boolean;
  next_appointment: { date: string; time: string } | null;
};

export function OwnerBookingPlansClient() {
  const token = useOwnerToken();
  const [businessId, setBusinessId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([]);
  const [businessName, setBusinessName] = useState("");
  const [rows, setRows] = useState<PlanRow[]>([]);
  const [error, setError] = useState<unknown>(null);

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
      const data = await apiRequest<{ results: PlanRow[] }>(
        `/api/v1/businesses/${biz}/booking-plans/`,
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

  return (
    <OwnerShell
      title="Regular bookings"
      businessName={businessName}
      locations={locations}
      locationId={locationId}
      onLocationChange={setLocationId}
    >
      {error ? <OwnerApiError error={error} /> : null}
      {rows.length === 0 ? (
        <p className="muted">No regular bookings yet.</p>
      ) : (
        <ul className="owner-simple-list">
          {rows.map((row, index) => (
            <li key={`${row.customer_name}-${row.service_name}-${index}`}>
              <span>
                <strong>{row.customer_name}</strong> · {row.service_name}
                <br />
                {row.frequency_label} · {row.staff_name || "Any staff"}
                <br />
                {row.next_appointment
                  ? `Next ${row.next_appointment.date} ${row.next_appointment.time}`
                  : "No next visit scheduled"}
              </span>
              <span className="owner-status">
                {row.status}
                {row.needs_action ? " · Needs action" : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </OwnerShell>
  );
}
