# Analytics Definitions

Locked before Phase 6.1 Payment & Revenue Analytics.
Do **not** create a separate revenue ledger. Use `payments.Payment` / `payments.Refund` and `booking.Appointment`.

---

## Money metrics

| Metric | Definition |
|---|---|
| **Gross Revenue** | Sum of successful paid amounts = `Payment.amount_paid` where `Payment.status` is in `{PAID, PARTIALLY_REFUNDED, REFUNDED}` (money that cleared). Prefer summing `amount_paid` on captured payments. |
| **Refunded Amount** | Sum of `Refund.amount` where `Refund.status = PROCESSED` |
| **Net Revenue** | Gross Revenue − Refunded Amount |
| **Paid Transaction** | One `Payment` row that reached `PAID` (or later refunded states derived from a prior PAID) |
| **Average Transaction Value** | Gross Revenue ÷ count of Paid Transactions in the period |
| **Payment Success** | Paid Transactions ÷ (Paid Transactions + failed terminal attempts in period) — exact failure denominator must use distinct failed `Payment` / `PaymentOrder` attempts; document filter in Phase 6.1 implementation |

### Dating rules

| Event | Timestamp |
|---|---|
| Revenue date | `Payment.paid_at` |
| Refund date | `Refund.processed_at` |

Filter reports by these timestamps in the location/org timezone for display; store UTC.

Currency: report in payment currency; do not FX-convert in v1 unless explicitly scoped later.

---

## Acquisition metrics

Source of truth: `Appointment.acquisition_source` (nullable).

| Label | Rule |
|---|---|
| **Direct Acquisition** | `acquisition_source IS NULL` |
| **QuickCard Acquisition** | `acquisition_source = QUICKCARD` |
| **Retention Acquisition** | `acquisition_source = RETENTION` |

Companion field: `Appointment.source` for channel (`ONLINE`, etc.). Public funnel bookings use:

| Path | `source` | `acquisition_source` |
|---|---|---|
| Direct public book | `ONLINE` | `NULL` |
| QuickCard | `ONLINE` | `QUICKCARD` |
| Retention deep link | `ONLINE` | `RETENTION` |

**Invariant:** Payment create/verify/webhook/refund **must not** modify acquisition attribution. Verified in payment tests.

---

## Scope notes for Phase 6.1

- Tenant-scope every query by resolved organization (and business/location filters as product requires).
- Soft-deleted appointments: follow existing reporting conventions (exclude unless erasure audit).
- `NOT_REQUIRED` / unpaid appointments contribute **0** to Gross Revenue.
- Partial refunds reduce Net via Refunded Amount; Gross still counts original `amount_paid`.

---

## Non-goals

- Loyalty points, campaign ROI, multi-provider FX, subscription MRR (platform billing) — separate systems.
