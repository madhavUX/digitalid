"use client";

import { OwnerApiError, OwnerShell, useOwnerToken } from "@/components/owner/OwnerShell";
import { apiRequest } from "@/lib/api/client";
import { listBusinesses, listLocations } from "@/lib/api/ownerApi";
import { authHeaders } from "@/lib/owner/auth";
import { useCallback, useEffect, useState } from "react";

type AppointmentRow = {
  id: string;
  public_reference: string;
  starts_at: string;
  status: string;
  staff_profile: string;
  items: { service_name: string }[];
  customer: string;
};

const STATUS_ACTIONS: Record<string, { label: string; status?: string; cancel?: boolean }[]> = {
  PENDING: [
    { label: "Confirm", status: "CONFIRMED" },
    { label: "Cancel", cancel: true },
  ],
  CONFIRMED: [
    { label: "Check in", status: "CHECKED_IN" },
    { label: "Complete", status: "COMPLETED" },
    { label: "No-show", status: "NO_SHOW" },
    { label: "Cancel", cancel: true },
  ],
  CHECKED_IN: [
    { label: "Complete", status: "COMPLETED" },
    { label: "No-show", status: "NO_SHOW" },
    { label: "Cancel", cancel: true },
  ],
};

export function OwnerBookingsClient() {
  const token = useOwnerToken();
  const [businessId, setBusinessId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([]);
  const [businessName, setBusinessName] = useState("");
  const [rows, setRows] = useState<AppointmentRow[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState("");

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
      const data = await apiRequest<{ results: AppointmentRow[] }>(
        `/api/v1/businesses/${biz}/appointments/`,
        {
          headers: authHeaders(token),
          query: {
            limit: 50,
            location_id: loc || undefined,
            status: status || undefined,
            ordering: "starts_at",
          },
        },
      );
      setRows(data.results || []);
    } catch (err) {
      setError(err);
    }
  }, [token, businessId, locationId, status]);

  useEffect(() => {
    void load();
  }, [load]);

  async function applyAction(
    row: AppointmentRow,
    action: { status?: string; cancel?: boolean },
  ) {
    if (!token || !businessId) return;
    setBusyId(row.id);
    setError(null);
    try {
      if (action.cancel) {
        await apiRequest(`/api/v1/businesses/${businessId}/appointments/${row.id}/cancel/`, {
          method: "POST",
          headers: authHeaders(token),
          body: {},
        });
      } else if (action.status) {
        await apiRequest(`/api/v1/businesses/${businessId}/appointments/${row.id}/`, {
          method: "PATCH",
          headers: authHeaders(token),
          body: { status: action.status },
        });
      }
      setMessage("Appointment updated");
      await load();
    } catch (err) {
      setError(err);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <OwnerShell
      title="Bookings"
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
      <label>
        Status filter
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          <option value="PENDING">Pending</option>
          <option value="CONFIRMED">Confirmed</option>
          <option value="CHECKED_IN">Checked in</option>
          <option value="COMPLETED">Completed</option>
          <option value="CANCELLED">Cancelled</option>
          <option value="NO_SHOW">No-show</option>
        </select>
      </label>
      {rows.length === 0 ? (
        <p className="muted">No bookings for this filter.</p>
      ) : (
        <ul className="owner-appt-list">
          {rows.map((row) => (
            <li key={row.id}>
              <span>
                {new Date(row.starts_at).toLocaleString("en-IN", {
                  day: "numeric",
                  month: "short",
                  hour: "numeric",
                  minute: "2-digit",
                })}
              </span>
              <span>
                <strong>{row.items?.[0]?.service_name || "Service"}</strong>
                <br />
                Ref {row.public_reference}
              </span>
              <span className="owner-status">{row.status}</span>
              <div className="actions">
                {(STATUS_ACTIONS[row.status] || []).map((action) => (
                  <button
                    key={action.label}
                    type="button"
                    className="ghost"
                    disabled={busyId === row.id}
                    onClick={() => void applyAction(row, action)}
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </OwnerShell>
  );
}
