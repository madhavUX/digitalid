"use client";

import { OwnerApiError, OwnerShell, useOwnerToken } from "@/components/owner/OwnerShell";
import {
  getBusinessDashboard,
  listBusinesses,
} from "@/lib/api/ownerApi";
import { managedQuickCardQrUrl } from "@/lib/api/managedQuickCard";
import type { BusinessDashboard } from "@/lib/api/types";
import { authHeaders } from "@/lib/owner/auth";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export function OwnerDashboardClient() {
  const token = useOwnerToken();
  const [businessId, setBusinessId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [data, setData] = useState<BusinessDashboard | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [qrUrl, setQrUrl] = useState("");

  const load = useCallback(async () => {
    if (!token) return;
    setError(null);
    try {
      let biz = businessId;
      if (!biz) {
        const list = await listBusinesses(token);
        if (!list.results?.length) {
          setData(null);
          return;
        }
        biz = list.results[0].id;
        setBusinessId(biz);
      }
      const dash = await getBusinessDashboard(biz, token, locationId || null);
      setData(dash);
      if (!locationId && dash.location?.id) {
        setLocationId(dash.location.id);
      }
    } catch (err) {
      setError(err);
    }
  }, [token, businessId, locationId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!token || !businessId || !locationId || !data?.quickcard?.is_published) {
      setQrUrl("");
      return;
    }
    let revoked = "";
    const controller = new AbortController();
    (async () => {
      const response = await fetch(managedQuickCardQrUrl(businessId, locationId), {
        headers: authHeaders(token),
        signal: controller.signal,
      });
      if (!response.ok) return;
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      revoked = url;
      setQrUrl(url);
    })().catch(() => undefined);
    return () => {
      controller.abort();
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [token, businessId, locationId, data?.quickcard?.is_published]);

  async function copyText(label: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      window.setTimeout(() => setCopied(null), 2000);
    } catch {
      setCopied(null);
    }
  }

  if (!token) {
    return (
      <OwnerShell>
        <p />
      </OwnerShell>
    );
  }

  if (!businessId && !error && !data) {
    return (
      <OwnerShell title="Dashboard">
        <div className="owner-card">
          <h2>Welcome</h2>
          <p>Create your business to get started.</p>
          <Link className="primary" href="/owner/onboarding">
            Start setup
          </Link>
        </div>
      </OwnerShell>
    );
  }

  return (
    <OwnerShell
      title="Dashboard"
      businessName={data?.business.name}
      locationName={data?.location?.name}
      locations={data?.locations || []}
      locationId={locationId}
      onLocationChange={(id) => setLocationId(id)}
    >
      {error ? <OwnerApiError error={error} /> : null}
      {!data ? (
        <p className="muted">Loading dashboard…</p>
      ) : (
        <>
          <p className="lede">
            Good {greeting()}, {data.business.name}
          </p>

          {!data.setup.ready ? (
            <section className="owner-card owner-alert" aria-live="polite">
              <h2>Finish setting up your business</h2>
              <p>
                {data.setup.completed_steps} of {data.setup.total_steps} steps
                completed ({data.setup.progress}%)
              </p>
              <div className="owner-progress" aria-hidden>
                <span style={{ width: `${data.setup.progress}%` }} />
              </div>
              {data.setup.blocking_reasons[0] ? (
                <p className="muted">{data.setup.blocking_reasons[0]}</p>
              ) : null}
              <Link className="primary" href="/owner/onboarding">
                Continue setup
              </Link>
            </section>
          ) : data.launch && !data.launch.ready ? (
            <section className="owner-card owner-alert" aria-live="polite">
              <h2>Finish your launch setup</h2>
              <p>
                {data.launch.remaining_blocking} item
                {data.launch.remaining_blocking === 1 ? "" : "s"} remaining (
                {data.launch.progress}%)
              </p>
              <div className="owner-progress" aria-hidden>
                <span style={{ width: `${data.launch.progress}%` }} />
              </div>
              {data.launch.blocking_reasons[0] ? (
                <p className="muted">{data.launch.blocking_reasons[0]}</p>
              ) : null}
              <Link className="primary" href="/owner/onboarding">
                Continue Setup
              </Link>
            </section>
          ) : data.launch?.ready ? (
            <section className="owner-card">
              <h2>Your business is ready</h2>
              <div className="owner-progress" aria-hidden>
                <span style={{ width: "100%" }} />
              </div>
              <ul className="owner-checklist">
                <li>✓ Business</li>
                <li>✓ Booking</li>
                <li>✓ QuickCard</li>
                <li>✓ Template</li>
                <li>
                  {data.launch.checklist.domain ? "✓" : "○"} Domain
                </li>
                <li>
                  {data.launch.checklist.whatsapp ? "✓" : "○"} WhatsApp
                </li>
              </ul>
              {data.launch.launch_status === "LIVE" &&
              data.launch.profile?.public_url ? (
                <>
                  <p>
                    Website <strong>LIVE</strong>
                  </p>
                  <p>
                    <code>{data.launch.profile.public_url.replace(/^https?:\/\//, "")}</code>
                  </p>
                  <div className="actions">
                    <a
                      className="primary"
                      href={data.launch.profile.public_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      View Website
                    </a>
                    <Link className="ghost" href="/owner/website">
                      Manage Website
                    </Link>
                  </div>
                </>
              ) : (
                <>
                  <p>Website setup incomplete</p>
                  <Link className="primary" href="/owner/website">
                    Complete Website Setup
                  </Link>
                </>
              )}
            </section>
          ) : (
            <section className="owner-card">
              <h2>Setup</h2>
              <p>✓ Ready to accept bookings</p>
              <div className="owner-progress">
                <span style={{ width: "100%" }} />
              </div>
            </section>
          )}

          <section className="owner-metrics" aria-label="Today overview">
            <div className="owner-metric">
              <p className="muted">Bookings today</p>
              <p className="owner-metric-value">{data.today.bookings}</p>
            </div>
            <div className="owner-metric">
              <p className="muted">Upcoming</p>
              <p className="owner-metric-value">{data.today.upcoming}</p>
            </div>
            <div className="owner-metric">
              <p className="muted">Regular</p>
              <p className="owner-metric-value">{data.today.regular_bookings}</p>
            </div>
          </section>

          <section className="owner-card">
            <div className="owner-card-head">
              <h2>Today&apos;s appointments</h2>
              <Link className="ghost" href="/owner/bookings">
                View all bookings
              </Link>
            </div>
            {data.appointments.length === 0 ? (
              <div className="owner-empty">
                <p>No bookings yet.</p>
                <p className="muted">
                  Share your QuickCard to start receiving bookings.
                </p>
                <div className="actions">
                  {data.quickcard?.public_path ? (
                    <Link className="primary" href={data.quickcard.public_path}>
                      View QuickCard
                    </Link>
                  ) : (
                    <Link className="primary" href="/owner/quickcard">
                      Complete QuickCard
                    </Link>
                  )}
                  {data.booking_path ? (
                    <button
                      type="button"
                      className="ghost"
                      onClick={() =>
                        void copyText(
                          "booking",
                          `${window.location.origin}${data.booking_path}`,
                        )
                      }
                    >
                      Copy booking link
                    </button>
                  ) : null}
                </div>
              </div>
            ) : (
              <ul className="owner-appt-list">
                {data.appointments.map((row) => (
                  <li key={row.public_reference}>
                    <span className="owner-appt-time">{row.time_label}</span>
                    <span>
                      <strong>{row.service_name}</strong>
                      <br />
                      {row.customer_name} · {row.staff_name}
                    </span>
                    <span className="owner-status">{row.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="owner-card" aria-label="Website">
            <h2>Website</h2>
            {data.launch?.launch_status === "LIVE" &&
            data.launch.profile?.public_url ? (
              <>
                <p className="owner-metric-value">LIVE</p>
                <p>
                  <code>
                    {data.launch.profile.public_url.replace(/^https?:\/\//, "")}
                  </code>
                </p>
                <div className="actions">
                  <a
                    className="primary"
                    href={data.launch.profile.public_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View Website
                  </a>
                  <Link className="ghost" href="/owner/website">
                    Manage
                  </Link>
                </div>
              </>
            ) : (
              <>
                <p>Setup incomplete</p>
                <Link className="primary" href="/owner/website">
                  Complete Website Setup
                </Link>
              </>
            )}
          </section>

          <section className="owner-card">
            <h2>QuickCard</h2>
            {data.quickcard?.is_published ? (
              <>
                <p>
                  <code>{data.quickcard.public_path}</code>
                </p>
                <div className="actions">
                  <Link
                    className="primary"
                    href={data.quickcard.public_path || "/"}
                    target="_blank"
                  >
                    View QuickCard
                  </Link>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() =>
                      void copyText(
                        "quickcard",
                        data.quickcard?.public_url ||
                          `${window.location.origin}${data.quickcard?.public_path}`,
                      )
                    }
                  >
                    Copy link
                  </button>
                  {data.booking_path ? (
                    <button
                      type="button"
                      className="ghost"
                      onClick={() =>
                        void copyText(
                          "booking",
                          `${window.location.origin}${data.booking_path}`,
                        )
                      }
                    >
                      Copy booking link
                    </button>
                  ) : null}
                  <Link className="ghost" href="/owner/quickcard">
                    Edit
                  </Link>
                </div>
                {qrUrl ? (
                  <div className="qc-qr-box">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={qrUrl} alt="QuickCard QR code" width={140} height={140} />
                    <a className="ghost" href={qrUrl} download="quickcard-qr.png">
                      Download QR
                    </a>
                  </div>
                ) : null}
                {copied ? (
                  <p className="muted" aria-live="polite">
                    Copied {copied} link
                  </p>
                ) : null}
              </>
            ) : (
              <>
                <p>Your QuickCard isn&apos;t live yet.</p>
                <Link className="primary" href="/owner/quickcard">
                  Complete QuickCard
                </Link>
              </>
            )}
          </section>
        </>
      )}
    </OwnerShell>
  );
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "morning";
  if (hour < 17) return "afternoon";
  return "evening";
}
