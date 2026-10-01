# Migration Drift — Booking Exclusion Constraint

## Current state (after Phase 6.0.1)

- Model: `Appointment.Meta.constraints` uses `status__in=sorted(OCCUPYING_STATUSES)`.
- Migration `booking.0015_pin_occupancy_status_order` updates **Django state only** via `SeparateDatabaseAndState` (`database_operations=[]`).
- `python manage.py makemigrations --check` → **No changes detected**.

## Cause

`OCCUPYING_STATUSES` is a `frozenset`. Historically migrations used `list(OCCUPYING_STATUSES)`, whose order is **not stable** across Python hash seeds / processes. Autodetector repeatedly proposed RemoveConstraint + AddConstraint with the same three statuses in different orders:

- `PENDING, CONFIRMED, CHECKED_IN`
- `CONFIRMED, PENDING, CHECKED_IN`
- `CHECKED_IN, CONFIRMED, PENDING`
- etc.

Pinned order is alphabetical: `CHECKED_IN`, `CONFIRMED`, `PENDING`.

## Impact on runtime schema

**None meaningful.** PostgreSQL `IN (...)` membership does not depend on list order. The live exclusion constraint already enforces the same status set. No double-booking semantics change.

## Why we did not DROP/CREATE on the database

Removing and recreating `excl_appointment_staff_occupancy` on a busy appointments table would:

- Take locks
- Briefly remove protection if not carefully transactional
- Provide zero behavioral benefit

State-only migration reconciles Django’s migration graph without touching Postgres.

## Safe remediation plan (if drift reappears)

1. Confirm only `status__in` order differs (`makemigrations --dry-run`).
2. Prefer `sorted(OCCUPYING_STATUSES)` (or a fixed tuple) in the model.
3. Add another **state-only** migration if needed — never blindly apply Remove+Add for cosmetic order churn.
4. Do not edit old applied migrations.

## Status

**Resolved for check stability** without altering runtime constraint DDL.
