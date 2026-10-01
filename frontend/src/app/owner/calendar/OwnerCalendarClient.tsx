"use client";

import { OwnerApiError, OwnerShell, useOwnerToken } from "@/components/owner/OwnerShell";
import { apiRequest } from "@/lib/api/client";
import { listBusinesses, listLocations } from "@/lib/api/ownerApi";
import { authHeaders } from "@/lib/owner/auth";
import { useCallback, useEffect, useMemo, useState } from "react";

type AppointmentRow = {
  id: string;
  public_reference: string;
  starts_at: string;
  status: string;
  items: { service_name: string }[];
};

export function OwnerCalendarClient() {
  const token = useOwnerToken();
  const [businessId, setBusinessId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([]);
  const [businessName, setBusinessName] = useState("");
  const [anchor, setAnchor] = useState(() => new Date());
  const [mode, setMode] = useState<"day" | "week">("day");
  const [rows, setRows] = useState<AppointmentRow[]>([]);
  const [error, setError] = useState<unknown>(null);

  const range = useMemo(() => {
    const start = new Date(anchor);
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    if (mode === "week") end.setDate(end.getDate() + 7);
    else end.setDate(end.getDate() + 1);
    return { start, end };
  }, [anchor, mode]);

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
            limit: 100,
            location_id: loc || undefined,
            starts_at_after: range.start.toISOString(),
            starts_at_before: range.end.toISOString(),
            ordering: "starts_at",
          },
        },
      );
      setRows(data.results || []);
    } catch (err) {
      setError(err);
    }
  }, [token, businessId, locationId, range]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <OwnerShell
      title="Calendar"
      businessName={businessName}
      locations={locations}
      locationId={locationId}
      onLocationChange={setLocationId}
    >
      {error ? <OwnerApiError error={error} /> : null}
      <div className="actions">
        <button
          type="button"
          className="ghost"
          onClick={() =>
            setAnchor((d) => {
              const next = new Date(d);
              next.setDate(next.getDate() - (mode === "week" ? 7 : 1));
              return next;
            })
          }
        >
          Previous
        </button>
        <button type="button" className="ghost" onClick={() => setAnchor(new Date())}>
          Today
        </button>
        <button
          type="button"
          className="ghost"
          onClick={() =>
            setAnchor((d) => {
              const next = new Date(d);
              next.setDate(next.getDate() + (mode === "week" ? 7 : 1));
              return next;
            })
          }
        >
          Next
        </button>
        <button
          type="button"
          className={mode === "day" ? "primary" : "ghost"}
          onClick={() => setMode("day")}
        >
          Day
        </button>
        <button
          type="button"
          className={mode === "week" ? "primary" : "ghost"}
          onClick={() => setMode("week")}
        >
          Week
        </button>
      </div>
      <p className="muted">{anchor.toDateString()}</p>
      <ul className="owner-appt-list">
        {rows.map((row) => (
          <li key={row.id}>
            <span>
              {new Date(row.starts_at).toLocaleString("en-IN", {
                weekday: "short",
                hour: "numeric",
                minute: "2-digit",
              })}
            </span>
            <span>{row.items?.[0]?.service_name || "Service"}</span>
            <span className="owner-status">{row.status}</span>
          </li>
        ))}
      </ul>
      {rows.length === 0 ? <p className="muted">No appointments in this range.</p> : null}
    </OwnerShell>
  );
}
