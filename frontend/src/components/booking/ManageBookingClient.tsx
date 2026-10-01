"use client";

import { ApiError, friendlyApiMessage } from "@/lib/api/client";
import {
  cancelManagedBooking,
  cancelManagedRegularBooking,
  getManagedBooking,
  pauseManagedRegularBooking,
  resumeManagedRegularBooking,
} from "@/lib/api/publicBooking";
import type { ManagedBooking } from "@/lib/api/types";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

type ViewState =
  | { kind: "loading" }
  | { kind: "invalid" }
  | { kind: "error"; message: string }
  | { kind: "ready"; booking: ManagedBooking }
  | { kind: "confirm"; booking: ManagedBooking }
  | { kind: "cancelling"; booking: ManagedBooking }
  | {
      kind: "cancelled";
      public_reference: string;
      locationName: string;
      locationSlug: string;
      message: string;
    };

function formatWhen(startsAt: string, endsAt: string) {
  const start = new Date(startsAt);
  const end = new Date(endsAt);
  const day = new Intl.DateTimeFormat("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(start);
  const timeFmt = new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
  });
  return `${day} · ${timeFmt.format(start)} – ${timeFmt.format(end)}`;
}

function statusLabel(status: string) {
  switch (status) {
    case "CONFIRMED":
      return "Confirmed";
    case "PENDING":
      return "Pending";
    case "CHECKED_IN":
      return "Checked in";
    case "COMPLETED":
      return "Completed";
    case "CANCELLED":
      return "Cancelled";
    case "NO_SHOW":
      return "No-show";
    default:
      return status;
  }
}

export function ManageBookingClient() {
  const params = useParams<{ token: string }>();
  const token = typeof params.token === "string" ? params.token : "";
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setState({ kind: "invalid" });
      return;
    }
    const controller = new AbortController();
    setState({ kind: "loading" });
    getManagedBooking(token, controller.signal)
      .then((booking) => {
        if (booking.status === "CANCELLED") {
          setState({
            kind: "cancelled",
            public_reference: booking.public_reference,
            locationName: booking.location.name,
            locationSlug: booking.location.slug,
            message: "Your booking has been cancelled.",
          });
          return;
        }
        setState({ kind: "ready", booking });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
          setState({ kind: "invalid" });
          return;
        }
        setState({ kind: "error", message: friendlyApiMessage(error) });
      });
    return () => controller.abort();
  }, [token]);

  async function confirmCancel() {
    if (state.kind !== "confirm") return;
    const booking = state.booking;
    setState({ kind: "cancelling", booking });
    try {
      const result = await cancelManagedBooking(token);
      setState({
        kind: "cancelled",
        public_reference: result.public_reference,
        locationName: booking.location.name,
        locationSlug: booking.location.slug,
        message: result.message,
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setState({ kind: "invalid" });
        return;
      }
      setState({
        kind: "error",
        message: friendlyApiMessage(error),
      });
    }
  }

  if (state.kind === "loading") {
    return (
      <div className="booking-shell success-shell">
        <div className="success-card" aria-busy="true" aria-live="polite">
          <p className="eyebrow">Manage booking</p>
          <h1>Loading your booking…</h1>
          <p className="lede">Just a moment.</p>
        </div>
      </div>
    );
  }

  if (state.kind === "invalid") {
    return (
      <div className="booking-shell success-shell">
        <div className="success-card" role="alert" aria-live="polite">
          <p className="eyebrow">Manage booking</p>
          <h1>Link unavailable</h1>
          <p className="lede">
            This booking link is invalid or has expired.
          </p>
        </div>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="booking-shell success-shell">
        <div className="success-card" role="alert" aria-live="assertive">
          <p className="eyebrow">Manage booking</p>
          <h1>Something went wrong</h1>
          <p className="lede">{state.message}</p>
          <div className="actions">
            <button
              type="button"
              className="primary"
              onClick={() => window.location.reload()}
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (state.kind === "cancelled") {
    return (
      <div className="booking-shell success-shell">
        <div className="success-card" aria-live="polite">
          <p className="eyebrow">Manage booking</p>
          <h1>Booking cancelled</h1>
          <p className="lede">{state.message}</p>
          <dl className="success-dl">
            <div>
              <dt>Business</dt>
              <dd>{state.locationName}</dd>
            </div>
            <div>
              <dt>Booking reference</dt>
              <dd>{state.public_reference}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>Cancelled</dd>
            </div>
          </dl>
          <div className="actions">
            <Link
              className="primary"
              href={`/book/${encodeURIComponent(state.locationSlug)}`}
            >
              Book again
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const booking =
    state.kind === "ready" ||
    state.kind === "confirm" ||
    state.kind === "cancelling"
      ? state.booking
      : null;
  if (!booking) return null;

  const confirming = state.kind === "confirm" || state.kind === "cancelling";
  const busy = state.kind === "cancelling";
  const regular = booking.regular_booking || null;

  async function runPlanAction(action: "pause" | "resume" | "cancel") {
    setPlanBusy(true);
    setPlanError(null);
    try {
      const next =
        action === "pause"
          ? await pauseManagedRegularBooking(token)
          : action === "resume"
            ? await resumeManagedRegularBooking(token)
            : await cancelManagedRegularBooking(token);
      setState((prev) => {
        if (prev.kind !== "ready" && prev.kind !== "confirm") return prev;
        return {
          ...prev,
          booking: {
            ...prev.booking,
            regular_booking: next,
            is_regular_booking: true,
          },
        };
      });
    } catch (error) {
      setPlanError(friendlyApiMessage(error));
    } finally {
      setPlanBusy(false);
    }
  }

  return (
    <div className="booking-shell success-shell">
      <div className="success-card">
        <p className="eyebrow">Your booking</p>
        <h1>{booking.location.name}</h1>
        <p className="lede">
          {booking.service.name}
          <br />
          {booking.staff.name}
        </p>
        <dl className="success-dl">
          <div>
            <dt>When</dt>
            <dd>{formatWhen(booking.starts_at, booking.ends_at)}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{statusLabel(booking.status)}</dd>
          </div>
          <div>
            <dt>Customer</dt>
            <dd>{booking.customer.name}</dd>
          </div>
          <div>
            <dt>Booking reference</dt>
            <dd>{booking.public_reference}</dd>
          </div>
        </dl>

        {regular ? (
          <section className="regular-booking-panel" aria-labelledby="regular-heading">
            <h2 id="regular-heading">Regular booking</h2>
            <p>
              {regular.service_name}
              <br />
              {regular.frequency_label}
              <br />
              Preferred staff:{" "}
              {regular.staff_preference === "SAME_STAFF"
                ? regular.staff_name || "Same staff"
                : "Any staff"}
            </p>
            {regular.next_appointment ? (
              <p>
                Next appointment: {regular.next_appointment.date} ·{" "}
                {regular.next_appointment.time}
              </p>
            ) : null}
            {regular.needs_action ? (
              <p className="state error" role="status">
                Action needed to book the next visit
                {regular.needs_action_code
                  ? ` (${regular.needs_action_code})`
                  : ""}
                .
              </p>
            ) : null}
            <p>
              Status: <strong>{regular.status}</strong>
            </p>
            {planError ? (
              <p className="state error" role="alert">
                {planError}
              </p>
            ) : null}
            <div className="actions">
              {regular.status === "ACTIVE" ? (
                <button
                  type="button"
                  className="ghost"
                  disabled={planBusy}
                  onClick={() => void runPlanAction("pause")}
                >
                  Pause
                </button>
              ) : null}
              {regular.status === "PAUSED" ? (
                <button
                  type="button"
                  className="ghost"
                  disabled={planBusy}
                  onClick={() => void runPlanAction("resume")}
                >
                  Resume
                </button>
              ) : null}
              {regular.status !== "CANCELLED" ? (
                <button
                  type="button"
                  className="danger"
                  disabled={planBusy}
                  onClick={() => void runPlanAction("cancel")}
                >
                  Cancel regular booking
                </button>
              ) : null}
            </div>
            <p className="muted">
              Cancelling the regular plan does not cancel this appointment.
            </p>
          </section>
        ) : null}

        {confirming ? (
          <div className="manage-confirm" aria-live="polite">
            <p className="lede">
              Are you sure you want to cancel this booking?
            </p>
            <div className="actions">
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={() => setState({ kind: "ready", booking })}
              >
                Keep booking
              </button>
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={() => void confirmCancel()}
              >
                {busy ? "Cancelling…" : "Cancel booking"}
              </button>
            </div>
          </div>
        ) : booking.can_cancel ? (
          <div className="actions">
            <button
              type="button"
              className="danger"
              onClick={() => setState({ kind: "confirm", booking })}
            >
              Cancel booking
            </button>
            <Link
              className="ghost"
              href={`/book/manage/${encodeURIComponent(token)}/history`}
            >
              View booking history
            </Link>
          </div>
        ) : (
          <div className="actions">
            <p className="lede" aria-live="polite">
              This booking can no longer be cancelled online.
            </p>
            <Link
              className="ghost"
              href={`/book/manage/${encodeURIComponent(token)}/history`}
            >
              View booking history
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
