# Booking Policies

Status of booking lifecycle rules as of Phase 6.0.1.
Do not treat this document as a commitment to implement missing policies.

| Status | Meaning |
|---|---|
| IMPLEMENTED | Enforced in service layer with tests or clear code path |
| PARTIAL | Exists in limited form; gaps remain |
| NOT IMPLEMENTED | No product rule in code |
| DEFERRED | Intentionally out of scope until a later phase |

---

## Cancellation

**Status:** IMPLEMENTED

- Owner/staff: `booking.services.cancel_appointment`
- Public/manage-token: `booking.public_services.cancel_managed_appointment` / `cancel_public_appointment`
- Terminal statuses (`COMPLETED`, `CANCELLED`, `NO_SHOW`) cannot cancel again
- Emits `AppointmentCancelled`; WhatsApp cancellation template queued when connected

**Gaps:** No cancellation cutoff window. Cancel does not auto-refund or change `payment_status`.

---

## Rescheduling

**Status:** IMPLEMENTED

- `booking.services.reschedule_appointment` for `PENDING` / `CONFIRMED`
- Re-validates staff occupancy, buffers, grid alignment, location timezone
- Increments `schedule_version` (reminder idempotency keys use it)
- Does not rewrite `acquisition_source` / `acquisition_reference`
- Does not change `payment_status` or create a new payment order

---

## No-show

**Status:** PARTIAL

- Status `NO_SHOW` exists; transitions from `CONFIRMED` / `CHECKED_IN` via `transition_appointment_status`
- No automatic no-show job, grace period, or payment side effect

---

## Minimum lead time

**Status:** PARTIAL

- Public/owner availability listing skips slots whose visible start is already in the past (`starts_at < now`)
- No configurable business “book at least N hours ahead” policy

---

## Cancellation cutoff

**Status:** NOT IMPLEMENTED

- Cancel allowed whenever status permits; no “must cancel N hours before start” rule

---

## Past booking override

**Status:** PARTIAL

- Availability APIs exclude past starts for new bookings
- No explicit owner “force book in the past” override flag; owner create still goes through occupancy rules

---

## Payment behavior during cancellation

**Status:** NOT IMPLEMENTED (by design for Phase 6 foundation)

- Cancel leaves `Appointment.payment_status` unchanged
- Refunds are owner-initiated via payments API only
- No automatic refund-on-cancel

---

## Payment behavior during rescheduling

**Status:** IMPLEMENTED (preserve)

- Reschedule does not alter payment rows or `payment_status`
- Paid appointments remain paid after time change

---

## Retention attribution after rescheduling

**Status:** IMPLEMENTED (preserve)

- `acquisition_source` / `acquisition_reference` are set only at create
- Reschedule updates schedule fields only

---

## QuickCard attribution after rescheduling

**Status:** IMPLEMENTED (preserve)

- Same as retention: create-time attribution is unchanged by reschedule

---

## Upcoming booking interaction with retention automation

**Status:** NOT IMPLEMENTED

- Retention due processing skips inactive customer/business, opt-out, segment change, missing WhatsApp/template/URL
- Does **not** skip because the customer already has an upcoming `PENDING`/`CONFIRMED` appointment

---

## Related implemented rules (reference)

| Rule | Status |
|---|---|
| Staff double-booking exclusion | IMPLEMENTED (Postgres exclusion constraint) |
| Staff weekly availability + time off | IMPLEMENTED |
| Location operating hours | NOT IMPLEMENTED (see `LOCATION_OPERATING_HOURS.md`) |
| Soft-delete of appointments | Soft-delete for erasure only; cancel uses status |

---

## Recommended policy backlog (not Phase 6.0.1)

1. Cancellation cutoff + optional auto-refund policy
2. Configurable minimum lead time
3. Skip retention send when an upcoming booking exists
4. Automated no-show after grace period
