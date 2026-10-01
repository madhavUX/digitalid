"use client";

import { ApiError, friendlyApiMessage } from "@/lib/api/client";
import {
  getBookAgainPrefill,
  getBookingHistory,
} from "@/lib/api/publicBooking";
import type { HistoryBooking } from "@/lib/api/types";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

function formatWhen(startsAt: string) {
  const start = new Date(startsAt);
  const day = new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
  }).format(start);
  const time = new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
  }).format(start);
  return `${day} · ${time}`;
}

function BookingRow({
  booking,
  token,
  scopePublicReference,
  onBookAgainError,
}: {
  booking: HistoryBooking;
  token: string;
  scopePublicReference: string;
  onBookAgainError: (message: string) => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const canManage =
    booking.category === "upcoming" &&
    booking.public_reference === scopePublicReference;

  async function bookAgain() {
    setBusy(true);
    try {
      const prefill = await getBookAgainPrefill(token, booking.public_reference);
      if (!prefill.available || !prefill.prefill) {
        onBookAgainError(
          prefill.message ||
            "This service is no longer available to book online.",
        );
        return;
      }
      const params = new URLSearchParams();
      params.set("service", prefill.prefill.service_id);
      if (prefill.prefill.staff_id) {
        params.set("staff", prefill.prefill.staff_id);
      } else {
        params.set("staff", "any");
      }
      router.push(
        `/book/${encodeURIComponent(prefill.location.slug)}?${params.toString()}`,
      );
    } catch (error) {
      onBookAgainError(friendlyApiMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="history-row">
      <div>
        <h3>{booking.location.name}</h3>
        <p>
          {booking.service.name}
          {booking.staff.name ? ` with ${booking.staff.name}` : ""}
        </p>
        <p className="history-when">{formatWhen(booking.starts_at)}</p>
        {booking.is_regular_booking ? (
          <p className="muted">Regular booking</p>
        ) : null}
      </div>
      <div className="actions">
        {canManage ? (
          <Link
            className="ghost"
            href={`/book/manage/${encodeURIComponent(token)}`}
          >
            Manage
          </Link>
        ) : null}
        {booking.can_book_again && booking.category !== "upcoming" ? (
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() => void bookAgain()}
          >
            {busy ? "Loading…" : "Book again"}
          </button>
        ) : null}
      </div>
    </article>
  );
}

export function BookingHistoryClient() {
  const params = useParams<{ token: string }>();
  const token = typeof params.token === "string" ? params.token : "";
  const [upcoming, setUpcoming] = useState<HistoryBooking[]>([]);
  const [past, setPast] = useState<HistoryBooking[]>([]);
  const [cancelled, setCancelled] = useState<HistoryBooking[]>([]);
  const [scopePublicReference, setScopePublicReference] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);
  const [bookAgainError, setBookAgainError] = useState<string | null>(null);
  const [defaultSlug, setDefaultSlug] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!token) {
      setInvalid(true);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [u, p, c] = await Promise.all([
        getBookingHistory(token, { category: "upcoming", limit: 20 }, signal),
        getBookingHistory(token, { category: "past", limit: 20 }, signal),
        getBookingHistory(token, { category: "cancelled", limit: 20 }, signal),
      ]);
      setUpcoming(u.results);
      setPast(p.results);
      setCancelled(c.results);
      setScopePublicReference(u.scope_public_reference);
      const slug =
        u.results[0]?.location.slug ||
        p.results[0]?.location.slug ||
        c.results[0]?.location.slug ||
        null;
      setDefaultSlug(slug);
    } catch (err) {
      if (signal?.aborted) return;
      if (err instanceof ApiError && err.status === 404) {
        setInvalid(true);
        return;
      }
      setError(friendlyApiMessage(err));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (loading) {
    return (
      <div className="booking-shell success-shell">
        <div className="success-card" aria-busy="true">
          <p className="eyebrow">Your bookings</p>
          <h1>Loading…</h1>
        </div>
      </div>
    );
  }

  if (invalid) {
    return (
      <div className="booking-shell success-shell">
        <div className="success-card" role="alert">
          <p className="eyebrow">Your bookings</p>
          <h1>Link unavailable</h1>
          <p className="lede">This booking link is invalid or has expired.</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="booking-shell success-shell">
        <div className="success-card" role="alert">
          <p className="eyebrow">Your bookings</p>
          <h1>Something went wrong</h1>
          <p className="lede">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="booking-shell success-shell">
      <div className="success-card history-card">
        <p className="eyebrow">Your bookings</p>
        <h1>Booking history</h1>
        {bookAgainError ? (
          <p className="lede" role="alert">
            {bookAgainError}
          </p>
        ) : null}

        <section className="history-section" aria-labelledby="upcoming-heading">
          <h2 id="upcoming-heading">Upcoming</h2>
          {upcoming.length === 0 ? (
            <p className="lede">You don&apos;t have any upcoming bookings.</p>
          ) : (
            upcoming.map((booking) => (
              <BookingRow
                key={booking.public_reference}
                booking={{ ...booking, category: "upcoming" }}
                token={token}
                scopePublicReference={scopePublicReference}
                onBookAgainError={setBookAgainError}
              />
            ))
          )}
          {upcoming.length === 0 && defaultSlug ? (
            <div className="actions">
              <Link
                className="primary"
                href={`/book/${encodeURIComponent(defaultSlug)}`}
              >
                Book a service
              </Link>
            </div>
          ) : null}
        </section>

        <section className="history-section" aria-labelledby="past-heading">
          <h2 id="past-heading">Past</h2>
          {past.length === 0 ? (
            <p className="lede">Your completed bookings will appear here.</p>
          ) : (
            past.map((booking) => (
              <BookingRow
                key={booking.public_reference}
                booking={{ ...booking, category: "past" }}
                token={token}
                scopePublicReference={scopePublicReference}
                onBookAgainError={setBookAgainError}
              />
            ))
          )}
        </section>

        {cancelled.length > 0 ? (
          <section
            className="history-section"
            aria-labelledby="cancelled-heading"
          >
            <h2 id="cancelled-heading">Cancelled</h2>
            {cancelled.map((booking) => (
              <BookingRow
                key={booking.public_reference}
                booking={{ ...booking, category: "cancelled" }}
                token={token}
                scopePublicReference={scopePublicReference}
                onBookAgainError={setBookAgainError}
              />
            ))}
          </section>
        ) : null}

        <div className="actions">
          <Link
            className="ghost"
            href={`/book/manage/${encodeURIComponent(token)}`}
          >
            Back to booking
          </Link>
        </div>
      </div>
    </div>
  );
}
