import { apiRequest } from "./client";
import type {
  BookAgainPrefillResponse,
  BookingHistoryResponse,
  ManagedBooking,
  ManagedBookingCancelResponse,
  PublicAppointment,
  PublicAppointmentCreateInput,
  PublicAvailabilityResponse,
  PublicBookingPlanCreateInput,
  PublicBookingPlanCreateResponse,
  PublicPaymentOrder,
  PublicPaymentState,
  PublicRegularBooking,
} from "./types";

export function getPublicAvailability(
  params: {
    location_id: string;
    service_id: string;
    date: string;
    staff_id?: string | null;
  },
  signal?: AbortSignal,
) {
  return apiRequest<PublicAvailabilityResponse>(
    "/api/v1/public/booking/availability/",
    {
      query: {
        location_id: params.location_id,
        service_id: params.service_id,
        date: params.date,
        staff_id: params.staff_id || undefined,
      },
      signal,
      cache: "no-store",
    },
  );
}

export function createPublicAppointment(
  payload: PublicAppointmentCreateInput,
  idempotencyKey: string,
  signal?: AbortSignal,
) {
  return apiRequest<PublicAppointment>(
    "/api/v1/public/booking/appointments/",
    {
      method: "POST",
      body: payload,
      headers: { "Idempotency-Key": idempotencyKey },
      signal,
      cache: "no-store",
    },
  );
}

export function createPublicBookingPlan(
  payload: PublicBookingPlanCreateInput,
  idempotencyKey: string,
  signal?: AbortSignal,
) {
  return apiRequest<PublicBookingPlanCreateResponse>(
    "/api/v1/public/booking/plans/",
    {
      method: "POST",
      body: payload,
      headers: { "Idempotency-Key": idempotencyKey },
      signal,
      cache: "no-store",
    },
  );
}

export function pauseManagedRegularBooking(token: string, signal?: AbortSignal) {
  return apiRequest<PublicRegularBooking>(
    `/api/v1/public/booking/manage/${encodeURIComponent(token)}/plan/pause/`,
    { method: "POST", body: {}, signal, cache: "no-store" },
  );
}

export function resumeManagedRegularBooking(token: string, signal?: AbortSignal) {
  return apiRequest<PublicRegularBooking>(
    `/api/v1/public/booking/manage/${encodeURIComponent(token)}/plan/resume/`,
    { method: "POST", body: {}, signal, cache: "no-store" },
  );
}

export function cancelManagedRegularBooking(token: string, signal?: AbortSignal) {
  return apiRequest<PublicRegularBooking>(
    `/api/v1/public/booking/manage/${encodeURIComponent(token)}/plan/cancel/`,
    { method: "POST", body: {}, signal, cache: "no-store" },
  );
}

export function getPublicAppointment(publicReference: string, signal?: AbortSignal) {
  return apiRequest<PublicAppointment>(
    `/api/v1/public/booking/appointments/${encodeURIComponent(publicReference)}/`,
    { signal, cache: "no-store" },
  );
}

export function getManagedBooking(token: string, signal?: AbortSignal) {
  return apiRequest<ManagedBooking>(
    `/api/v1/public/booking/manage/${encodeURIComponent(token)}/`,
    { signal, cache: "no-store" },
  );
}

export function cancelManagedBooking(
  token: string,
  reason = "",
  signal?: AbortSignal,
) {
  return apiRequest<ManagedBookingCancelResponse>(
    `/api/v1/public/booking/manage/${encodeURIComponent(token)}/cancel/`,
    {
      method: "POST",
      body: reason ? { reason } : {},
      signal,
      cache: "no-store",
    },
  );
}

export function getBookingHistory(
  token: string,
  params: { category?: string; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
) {
  return apiRequest<BookingHistoryResponse>(
    `/api/v1/public/booking/history/${encodeURIComponent(token)}/`,
    {
      query: {
        category: params.category || "upcoming",
        limit: params.limit,
        offset: params.offset,
      },
      signal,
      cache: "no-store",
    },
  );
}

export function getBookAgainPrefill(
  token: string,
  publicReference: string,
  signal?: AbortSignal,
) {
  return apiRequest<BookAgainPrefillResponse>(
    `/api/v1/public/booking/history/${encodeURIComponent(token)}/book-again/${encodeURIComponent(publicReference)}/`,
    { signal, cache: "no-store" },
  );
}

export function createPublicPaymentOrder(
  publicReference: string,
  idempotencyKey: string,
  signal?: AbortSignal,
) {
  return apiRequest<PublicPaymentOrder>(
    `/api/v1/public/booking/appointments/${encodeURIComponent(publicReference)}/payment-order/`,
    {
      method: "POST",
      body: { idempotency_key: idempotencyKey },
      headers: { "Idempotency-Key": idempotencyKey },
      signal,
      cache: "no-store",
    },
  );
}

export function verifyPublicPayment(
  publicReference: string,
  payload: {
    razorpay_order_id: string;
    razorpay_payment_id: string;
    razorpay_signature: string;
  },
  signal?: AbortSignal,
) {
  return apiRequest<PublicPaymentState>(
    `/api/v1/public/booking/appointments/${encodeURIComponent(publicReference)}/payment/verify/`,
    {
      method: "POST",
      body: payload,
      signal,
      cache: "no-store",
    },
  );
}

export function getPublicPaymentStatus(
  publicReference: string,
  signal?: AbortSignal,
) {
  return apiRequest<PublicPaymentState>(
    `/api/v1/public/booking/appointments/${encodeURIComponent(publicReference)}/payment/`,
    { signal, cache: "no-store" },
  );
}
