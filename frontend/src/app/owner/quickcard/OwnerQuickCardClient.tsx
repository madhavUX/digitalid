"use client";

import { ApiError, friendlyApiMessage } from "@/lib/api/client";
import { apiRequest } from "@/lib/api/client";
import {
  createManagedQuickCard,
  getManagedQuickCard,
  getQuickCardAnalytics,
  managedQuickCardQrUrl,
  publishManagedQuickCard,
  unpublishManagedQuickCard,
  updateManagedQuickCard,
} from "@/lib/api/managedQuickCard";
import type { ManagedQuickCard, QuickCardAnalytics } from "@/lib/api/types";
import {
  customAnalyticsRange,
  customRangeMessage,
  formatAnalyticsDay,
  presetAnalyticsRange,
  type AnalyticsPreset,
} from "@/lib/quickcard/analyticsRange";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

const TOKEN_KEY = "ba_access_token";

export function formatBookingConversion(rate: number | null): string {
  if (rate === null) return "—";
  return `${rate.toFixed(1)}%`;
}

type BusinessRow = { id: string; name: string };
type LocationRow = { id: string; name: string; slug: string; is_active?: boolean };

export function OwnerQuickCardClient() {
  const search = useSearchParams();
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [businesses, setBusinesses] = useState<BusinessRow[]>([]);
  const [locations, setLocations] = useState<LocationRow[]>([]);
  const [businessId, setBusinessId] = useState(search.get("business") || "");
  const [locationId, setLocationId] = useState(search.get("location") || "");
  const [card, setCard] = useState<ManagedQuickCard | null>(null);
  const [analytics, setAnalytics] = useState<QuickCardAnalytics | null>(null);
  const [analyticsLocationId, setAnalyticsLocationId] = useState("");
  const [rangePreset, setRangePreset] = useState<AnalyticsPreset>("30");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    slug: "",
    headline: "",
    description: "",
    logo_url: "",
    cover_image_url: "",
    phone: "",
    whatsapp: "",
    website_url: "",
    google_maps_url: "",
    instagram_url: "",
    facebook_url: "",
  });

  useEffect(() => {
    const saved = window.localStorage.getItem(TOKEN_KEY) || "";
    if (saved) setToken(saved);
  }, []);

  const loadBusinesses = useCallback(async (access: string) => {
    const data = await apiRequest<{ results: BusinessRow[] }>(
      "/api/v1/businesses/",
      { headers: { Authorization: `Bearer ${access}` }, query: { limit: 50 } },
    );
    setBusinesses(data.results || []);
    if (!businessId && data.results?.[0]) {
      setBusinessId(data.results[0].id);
    }
  }, [businessId]);

  const loadLocations = useCallback(
    async (access: string, biz: string) => {
      if (!biz) return;
      const data = await apiRequest<{ results: LocationRow[] }>(
        `/api/v1/businesses/${biz}/locations/`,
        { headers: { Authorization: `Bearer ${access}` }, query: { limit: 50 } },
      );
      setLocations(data.results || []);
      if (!locationId && data.results?.[0]) {
        setLocationId(data.results[0].id);
      }
    },
    [locationId],
  );

  const loadCard = useCallback(
    async (access: string, biz: string, loc: string) => {
      if (!biz || !loc) return;
      setError(null);
      setMissing(false);
      try {
        const data = await getManagedQuickCard(biz, loc, access);
        setCard(data);
        setForm({
          slug: data.slug,
          headline: data.headline,
          description: data.description,
          logo_url: data.logo_url,
          cover_image_url: data.cover_image_url,
          phone: data.phone,
          whatsapp: data.whatsapp,
          website_url: data.website_url,
          google_maps_url: data.google_maps_url,
          instagram_url: data.instagram_url,
          facebook_url: data.facebook_url,
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          setCard(null);
          setMissing(true);
          return;
        }
        setError(friendlyApiMessage(err));
      }
    },
    [],
  );

  useEffect(() => {
    if (!token) return;
    void loadBusinesses(token).catch((err) =>
      setError(friendlyApiMessage(err)),
    );
  }, [token, loadBusinesses]);

  useEffect(() => {
    if (!token || !businessId) return;
    void loadLocations(token, businessId).catch((err) =>
      setError(friendlyApiMessage(err)),
    );
  }, [token, businessId, loadLocations]);

  useEffect(() => {
    if (!token || !businessId || !locationId) return;
    void loadCard(token, businessId, locationId);
  }, [token, businessId, locationId, loadCard]);

  useEffect(() => {
    if (!token || !businessId) return;
    const range =
      rangePreset === "custom"
        ? customAnalyticsRange(customStart, customEnd)
        : presetAnalyticsRange(rangePreset === "7" ? 7 : rangePreset === "90" ? 90 : 30);
    if (!range) {
      setAnalytics(null);
      setAnalyticsLoading(false);
      setAnalyticsError(null);
      return;
    }
    let ignore = false;
    setAnalytics(null);
    setAnalyticsLoading(true);
    setAnalyticsError(null);
    void getQuickCardAnalytics(businessId, token, {
      locationId: analyticsLocationId || undefined,
      dateFrom: range.dateFrom,
      dateTo: range.dateTo,
    })
      .then((data) => {
        if (!ignore) setAnalytics(data);
      })
      .catch((err) => {
        if (!ignore) {
          setAnalytics(null);
          setAnalyticsError(friendlyApiMessage(err));
        }
      })
      .finally(() => {
        if (!ignore) setAnalyticsLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [token, businessId, analyticsLocationId, rangePreset, customStart, customEnd]);

  async function login(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await apiRequest<{ access: string }>("/api/v1/auth/login/", {
        method: "POST",
        body: { email, password },
      });
      window.localStorage.setItem(TOKEN_KEY, data.access);
      setToken(data.access);
    } catch (err) {
      setError(friendlyApiMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!token || !businessId || !locationId) return;
    setBusy(true);
    setError(null);
    try {
      if (missing || !card) {
        const created = await createManagedQuickCard(
          businessId,
          locationId,
          token,
          form,
        );
        setCard(created);
        setMissing(false);
      } else {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars -- slug immutable
        const { slug, ...patch } = form;
        const updated = await updateManagedQuickCard(
          businessId,
          locationId,
          token,
          patch,
        );
        setCard(updated);
      }
    } catch (err) {
      setError(friendlyApiMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function togglePublish() {
    if (!token || !businessId || !locationId || !card) return;
    setBusy(true);
    try {
      const next = card.is_published
        ? await unpublishManagedQuickCard(businessId, locationId, token)
        : await publishManagedQuickCard(businessId, locationId, token);
      setCard(next);
    } catch (err) {
      setError(friendlyApiMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <main className="qc-owner">
        <form className="qc-owner-card" onSubmit={login}>
          <h1>QuickCard owner</h1>
          <p className="qc-muted">Sign in to manage your QuickCard.</p>
          {error ? <p className="state error">{error}</p> : null}
          <label>
            Email
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              required
            />
          </label>
          <label>
            Password
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              required
            />
          </label>
          <button className="qc-cta" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className="qc-owner">
      <div className="qc-owner-card">
        <h1>QuickCard</h1>
        <div className="actions">
          {locations.filter((row) => row.is_active !== false).length > 1 ? (
            <label>
              Analytics location
              <select
                value={analyticsLocationId}
                onChange={(e) => setAnalyticsLocationId(e.target.value)}
              >
                <option value="">All Locations</option>
                {locations
                  .filter((row) => row.is_active !== false)
                  .map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                    </option>
                  ))}
              </select>
            </label>
          ) : null}
          <label>
            Date range
            <select
              value={rangePreset}
              onChange={(e) => setRangePreset(e.target.value as AnalyticsPreset)}
            >
              <option value="7">Last 7 days</option>
              <option value="30">Last 30 days</option>
              <option value="90">Last 90 days</option>
              <option value="custom">Custom range</option>
            </select>
          </label>
          {rangePreset === "custom" ? (
            <>
              <label>
                Start date
                <input
                  type="date"
                  value={customStart}
                  onChange={(e) => setCustomStart(e.target.value)}
                />
              </label>
              <label>
                End date
                <input
                  type="date"
                  value={customEnd}
                  onChange={(e) => setCustomEnd(e.target.value)}
                />
              </label>
            </>
          ) : null}
        </div>
        {rangePreset === "custom" && customRangeMessage(customStart, customEnd) ? (
          <p className="state error">{customRangeMessage(customStart, customEnd)}</p>
        ) : null}
        {analyticsLoading ? <p className="qc-muted">Loading analytics…</p> : null}
        {analyticsError ? <p className="state error">{analyticsError}</p> : null}
        {analytics && !analyticsLoading ? (
          <section aria-label="QuickCard analytics" className="qc-kpis">
            <p className="qc-muted">
              {`Showing data for: ${formatAnalyticsDay(analytics.date_from)} – ${formatAnalyticsDay(analytics.date_to)}. These are event counts, not unique visitors.`}
            </p>
            <article>
              <span>QuickCard Views</span>
              <strong>{analytics.views.toLocaleString("en-IN")}</strong>
            </article>
            {(
              [
                ["book", "Book Now"],
                ["whatsapp", "WhatsApp"],
                ["call", "Call"],
                ["directions", "Directions"],
                ["review", "Review"],
                ["share", "Share"],
              ] as const
            ).map(([key, label]) => (
              <article key={key}>
                <span>{label}</span>
                <strong>{analytics.cta_clicks[key].toLocaleString("en-IN")}</strong>
              </article>
            ))}
            <article>
              <span>Bookings</span>
              <strong>{analytics.bookings.toLocaleString("en-IN")}</strong>
            </article>
            <article>
              <span>Booking Conversion</span>
              <strong>{formatBookingConversion(analytics.booking_conversion_rate)}</strong>
              <p className="qc-muted">Book Now → Booking</p>
              <p className="qc-muted">
                Percentage of Book Now clicks that resulted in an attributed booking.
              </p>
            </article>
          </section>
        ) : null}
        {error ? <p className="state error">{error}</p> : null}
        <label>
          Business
          <select
            value={businessId}
            onChange={(e) => {
              setBusinessId(e.target.value);
              setLocationId("");
              setAnalyticsLocationId("");
            }}
          >
            {businesses.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Location
          <select
            value={locationId}
            onChange={(e) => setLocationId(e.target.value)}
          >
            {locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>

        {(
          [
            ["slug", "Slug", missing],
            ["headline", "Headline", true],
            ["description", "Description", true],
            ["logo_url", "Logo URL", true],
            ["cover_image_url", "Cover image URL", true],
            ["phone", "Phone", true],
            ["whatsapp", "WhatsApp", true],
            ["website_url", "Website", true],
            ["google_maps_url", "Google Maps URL", true],
            ["instagram_url", "Instagram URL", true],
            ["facebook_url", "Facebook URL", true],
          ] as const
        ).map(([key, label, editable]) => (
          <label key={key}>
            {label}
            <input
              value={form[key]}
              disabled={!editable || (!missing && key === "slug" && !!card)}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, [key]: e.target.value }))
              }
            />
          </label>
        ))}

        <div className="actions">
          <button
            type="button"
            className="qc-cta"
            disabled={busy || !locationId}
            onClick={() => void save()}
          >
            {missing ? "Create QuickCard" : "Save"}
          </button>
          {card ? (
            <button
              type="button"
              className="ghost"
              disabled={busy}
              onClick={() => void togglePublish()}
            >
              {card.is_published ? "Unpublish" : "Publish"}
            </button>
          ) : null}
        </div>

        {card ? (
          <section className="qc-owner-meta">
            <p>
              Status:{" "}
              <strong>{card.is_published ? "Published" : "Draft"}</strong>
            </p>
            <p>
              Public URL:{" "}
              <a href={card.public_path} target="_blank" rel="noreferrer">
                {card.public_url}
              </a>
            </p>
            <Link className="ghost" href={card.public_path} target="_blank">
              View QuickCard
            </Link>
            <div className="qc-qr-box">
              <p>QR code</p>
              {/* Auth via Authorization header is not possible for <img>; fetch blob */}
              <QrPreview
                businessId={businessId}
                locationId={locationId}
                token={token}
              />
            </div>
          </section>
        ) : null}

        <button
          type="button"
          className="ghost"
          onClick={() => {
            window.localStorage.removeItem(TOKEN_KEY);
            setToken("");
          }}
        >
          Sign out
        </button>
      </div>
    </main>
  );
}

function QrPreview({
  businessId,
  locationId,
  token,
}: {
  businessId: string;
  locationId: string;
  token: string;
}) {
  const [src, setSrc] = useState<string>("");

  useEffect(() => {
    let revoked = "";
    const controller = new AbortController();
    (async () => {
      const response = await fetch(
        managedQuickCardQrUrl(businessId, locationId),
        {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        },
      );
      if (!response.ok) return;
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      revoked = url;
      setSrc(url);
    })().catch(() => undefined);
    return () => {
      controller.abort();
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [businessId, locationId, token]);

  if (!src) return <p className="qc-muted">Loading QR…</p>;
  return (
    <>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt="QuickCard QR code" width={180} height={180} />
      <a className="ghost" href={src} download={`quickcard-${locationId}.png`}>
        Download QR
      </a>
    </>
  );
}
