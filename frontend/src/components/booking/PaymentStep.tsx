"use client";

import {
  createPublicPaymentOrder,
  verifyPublicPayment,
} from "@/lib/api/publicBooking";
import type { PublicAppointment, PublicPaymentOrder } from "@/lib/api/types";
import { ApiError, friendlyApiMessage } from "@/lib/api/client";
import { createIdempotencyKey } from "@/lib/booking/idempotency";
import { formatMoney } from "@/lib/booking/format";
import { useCallback, useEffect, useState } from "react";

type Props = {
  appointment: PublicAppointment;
  onPaid: () => void;
  onSkipToSuccess?: () => void;
};

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => {
      open: () => void;
      on: (event: string, handler: (response: unknown) => void) => void;
    };
  }
}

function loadRazorpayScript(): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  if (window.Razorpay) return Promise.resolve(true);
  return new Promise((resolve) => {
    const existing = document.querySelector("script[data-razorpay]");
    if (existing) {
      existing.addEventListener("load", () => resolve(true));
      existing.addEventListener("error", () => resolve(false));
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.dataset.razorpay = "1";
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}

export function PaymentStep({ appointment, onPaid }: Props) {
  const [order, setOrder] = useState<PublicPaymentOrder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"idle" | "checkout" | "verifying" | "failed">(
    "idle",
  );
  const [idempotencyKey] = useState(() => createIdempotencyKey());

  const createOrder = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await createPublicPaymentOrder(
        appointment.public_reference,
        idempotencyKey,
      );
      setOrder(created);
      setPhase("idle");
    } catch (err) {
      if (err instanceof ApiError && err.code === "PAYMENT_ALREADY_PAID") {
        onPaid();
        return;
      }
      setError(friendlyApiMessage(err));
      setPhase("failed");
    } finally {
      setBusy(false);
    }
  }, [appointment.public_reference, idempotencyKey, onPaid]);

  useEffect(() => {
    void createOrder();
  }, [createOrder]);

  async function openCheckout() {
    if (!order || busy) return;
    setBusy(true);
    setError(null);
    setPhase("checkout");
    try {
      if (order.provider === "mock") {
        // Deterministic mock checkout: signature uses mock provider convention.
        const paymentId = `pay_mock_${Date.now()}`;
        const encoder = new TextEncoder();
        const data = encoder.encode(`${order.provider_order_id}|${paymentId}|mock`);
        const digest = await crypto.subtle.digest("SHA-256", data);
        const signature = Array.from(new Uint8Array(digest))
          .map((b) => b.toString(16).padStart(2, "0"))
          .join("");
        setPhase("verifying");
        const verified = await verifyPublicPayment(appointment.public_reference, {
          razorpay_order_id: order.provider_order_id,
          razorpay_payment_id: paymentId,
          razorpay_signature: signature,
        });
        if (verified.status === "PAID") {
          onPaid();
          return;
        }
        setError("Payment verification did not confirm payment.");
        setPhase("failed");
        return;
      }

      const loaded = await loadRazorpayScript();
      if (!loaded || !window.Razorpay) {
        setError("Could not load Razorpay Checkout. Please retry.");
        setPhase("failed");
        return;
      }
      const rzp = new window.Razorpay({
        key: order.key_id,
        amount: order.amount,
        currency: order.currency,
        order_id: order.provider_order_id,
        name: appointment.location,
        description: appointment.service,
        handler: async (response: {
          razorpay_order_id: string;
          razorpay_payment_id: string;
          razorpay_signature: string;
        }) => {
          try {
            setPhase("verifying");
            const verified = await verifyPublicPayment(appointment.public_reference, {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            if (verified.status === "PAID") {
              onPaid();
              return;
            }
            setError("Payment verification did not confirm payment.");
            setPhase("failed");
          } catch (err) {
            setError(friendlyApiMessage(err));
            setPhase("failed");
          } finally {
            setBusy(false);
          }
        },
        modal: {
          ondismiss: () => {
            setBusy(false);
            setPhase("idle");
            setError("Checkout was closed before payment completed.");
          },
        },
      });
      rzp.open();
    } catch (err) {
      setError(friendlyApiMessage(err));
      setPhase("failed");
      setBusy(false);
    }
  }

  const amountLabel = formatMoney(
    appointment.payable_amount || appointment.total,
    appointment.currency,
  );

  return (
    <section className="booking-card" aria-label="Payment">
      <h2>Payment</h2>
      <p className="muted">Pay securely to confirm your booking. Card details are never stored by us.</p>
      <p>
        Amount due: <strong>{amountLabel}</strong>
      </p>
      {phase === "verifying" ? <PaymentStatus message="Verifying payment…" /> : null}
      {phase === "failed" || error ? <PaymentFailure message={error || "Payment failed."} /> : null}
      {order && phase !== "verifying" ? (
        <div className="booking-actions">
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() => void openCheckout()}
          >
            {busy ? "Please wait…" : "Pay now"}
          </button>
          <button type="button" className="ghost" disabled={busy} onClick={() => void createOrder()}>
            Retry payment setup
          </button>
        </div>
      ) : null}
      {!order && !error ? <p className="muted">Preparing checkout…</p> : null}
    </section>
  );
}

export function PaymentStatus({ message }: { message: string }) {
  return <p className="muted" role="status">{message}</p>;
}

export function PaymentFailure({ message }: { message: string }) {
  return (
    <p className="error" role="alert">
      {message}
    </p>
  );
}

export function PaymentSuccess({ message }: { message: string }) {
  return (
    <p className="success" role="status">
      {message}
    </p>
  );
}
