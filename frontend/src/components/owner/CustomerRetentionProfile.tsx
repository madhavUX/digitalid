"use client";

import { formatMoney } from "@/lib/booking/format";
import type { RetentionSummary } from "@/lib/api/types";
import {
  retentionSegmentExplanation,
  retentionSegmentLabel,
} from "@/lib/customers/retentionLabels";

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function formatVisitDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(new Date(iso));
  } catch {
    return "—";
  }
}

type Props = {
  summary: RetentionSummary | null;
  loading?: boolean;
  error?: string | null;
  customerName?: string;
};

export function CustomerRetentionProfile({
  summary,
  loading = false,
  error = null,
  customerName,
}: Props) {
  if (loading) {
    return (
      <section className="owner-card" aria-busy="true" aria-label="Retention">
        <h2>Visit history</h2>
        <p className="muted">Loading visit history…</p>
      </section>
    );
  }

  if (error) {
    return (
      <section className="owner-card" aria-label="Retention">
        <h2>Visit history</h2>
        <p className="state error" role="alert">
          {error}
        </p>
      </section>
    );
  }

  if (!summary) {
    return null;
  }

  const hasVisits = summary.total_visits > 0;
  const segmentLabel = retentionSegmentLabel(summary.segment);
  const explanation = retentionSegmentExplanation(summary);

  return (
    <section className="owner-card" aria-label="Retention">
      <h2>Visit history{customerName ? ` · ${customerName}` : ""}</h2>
      <p className="muted">
        Historical completed visits only. This does not predict return dates.
      </p>

      <div className="owner-retention-segment">
        <p className="muted">Segment</p>
        <p className="owner-metric-value owner-metric-value-sm">{segmentLabel}</p>
        {explanation ? <p className="muted">{explanation}</p> : null}
        {summary.automation ? (
          <p className="muted">
            Automation:{" "}
            {summary.automation.status === "PENDING"
              ? "Scheduled"
              : summary.automation.status === "QUEUED"
                ? "Queued"
                : summary.automation.status === "SENT"
                  ? "Sent"
                  : summary.automation.status === "SKIPPED"
                    ? "Skipped"
                    : summary.automation.status === "CANCELLED"
                      ? "Cancelled"
                      : "Failed"}
          </p>
        ) : null}
      </div>

      <div className="owner-metrics owner-metrics-five">
        <div className="owner-metric">
          <p className="muted">Total visits</p>
          <p className="owner-metric-value">{summary.total_visits}</p>
        </div>
        <div className="owner-metric">
          <p className="muted">First visit</p>
          <p className="owner-metric-value owner-metric-value-sm">
            {formatVisitDate(summary.first_visit_at)}
          </p>
        </div>
        <div className="owner-metric">
          <p className="muted">Last visit</p>
          <p className="owner-metric-value owner-metric-value-sm">
            {formatVisitDate(summary.last_visit_at)}
          </p>
        </div>
        <div className="owner-metric">
          <p className="muted">Days since last visit</p>
          <p className="owner-metric-value">
            {dash(summary.days_since_last_visit)}
          </p>
        </div>
        <div className="owner-metric">
          <p className="muted">Avg days between visits</p>
          <p className="owner-metric-value">
            {dash(summary.average_days_between_visits)}
          </p>
        </div>
      </div>

      <h3>Recent visits</h3>
      {!hasVisits || summary.visits.length === 0 ? (
        <p className="muted">No completed visits yet.</p>
      ) : (
        <ul className="owner-simple-list">
          {summary.visits.map((visit) => (
            <li key={visit.appointment_reference}>
              <span>
                <strong>{visit.service || "Service"}</strong>
                {" · "}
                {visit.staff || "Staff"}
                {" · "}
                {visit.location || "Location"}
                <br />
                <span className="muted">
                  {formatVisitDate(visit.completed_at)} ·{" "}
                  {visit.appointment_reference} ·{" "}
                  {formatMoney(visit.price_snapshot, visit.currency)}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3>Service history</h3>
      {summary.service_history.length === 0 ? (
        <p className="muted">No visit history yet.</p>
      ) : (
        <ul className="owner-simple-list">
          {summary.service_history.map((row) => (
            <li key={row.service_name}>
              <span>
                <strong>{row.service_name}</strong>
                <br />
                <span className="muted">
                  Last {formatVisitDate(row.last_visit_at)}
                </span>
              </span>
              <span>{row.visit_count}</span>
            </li>
          ))}
        </ul>
      )}

      <h3>Staff history</h3>
      {summary.staff_history.length === 0 ? (
        <p className="muted">No visit history yet.</p>
      ) : (
        <ul className="owner-simple-list">
          {summary.staff_history.map((row) => (
            <li key={row.staff_name}>
              <span>
                <strong>{row.staff_name}</strong>
                <br />
                <span className="muted">
                  Last {formatVisitDate(row.last_visit_at)}
                </span>
              </span>
              <span>{row.visit_count}</span>
            </li>
          ))}
        </ul>
      )}

      <h3>Location history</h3>
      {summary.location_history.length === 0 ? (
        <p className="muted">No visit history yet.</p>
      ) : (
        <ul className="owner-simple-list">
          {summary.location_history.map((row) => (
            <li key={row.location_name}>
              <span>
                <strong>{row.location_name}</strong>
                <br />
                <span className="muted">
                  Last {formatVisitDate(row.last_visit_at)}
                </span>
              </span>
              <span>{row.visit_count}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
