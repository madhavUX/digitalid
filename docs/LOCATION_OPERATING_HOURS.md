# Location Operating Hours — Proposed Design

## Current state

Scheduling uses **staff-centric** capacity only:

- `StaffAvailability` (weekly windows per staff + location)
- `StaffTimeOff`
- Appointment occupancy exclusion on `staff_profile`

There is **no** `LocationHours`, holiday calendar, or temporary closure entity in `docs/DATABASE.md` or the ORM.

### Gap

The system cannot distinguish:

| Concept | Today |
|---|---|
| Staff available | Enforced |
| Business / location open | **Not modeled** |

A staff member can be scheduled outside what an owner would call “shop hours,” because shop hours do not exist as a constraint.

**Phase 6.0.1 decision:** Document only. Booking is not unsafe solely because of this gap (staff availability still bounds slots). Full hours/holiday system is deferred.

---

## Proposed model (future)

Do not implement until approved against `DATABASE.md`.

### Weekly hours

`LocationOperatingHours`

- `organization`, `location` (tenant-scoped)
- `weekday` (0–6 or enum matching staff)
- `opens_at`, `closes_at` (local time)
- `is_closed` (closed all day)

Multiple rows per weekday allowed for split shifts (e.g. lunch break) — or a single window + optional break fields. Prefer multiple intervals for flexibility.

### Holidays

`LocationHoliday`

- date (local calendar date)
- `is_closed` or alternate `opens_at`/`closes_at`
- optional label

### Temporary closures

`LocationClosure`

- `starts_at` / `ends_at` (timestamptz) or local date range
- reason (optional)
- soft-delete / audit fields per platform conventions

### Special hours

Either reuse holiday/closure with alternate hours, or `LocationSpecialHours` keyed by date with open/close overrides.

### Timezone

- Location already has timezone (booking occupancy uses `_local_zone(location)`).
- All weekly/holiday rules are **local** to the location; convert to UTC only when intersecting occupancy windows.

---

## Booking interaction

When implemented:

1. Generate candidate slots from staff availability ∩ location open intervals.
2. Reject create/reschedule if occupancy falls outside location open time (unless an explicit owner override flag is added later).
3. Public availability API must apply the same intersection.

### Staff availability interaction

- Staff windows remain the capacity model.
- Location hours are an **upper bound** (AND), never a substitute for staff availability.
- Time off and closures both block occupancy.

---

## Severity

**P2 / P3** — product completeness, not a current data-integrity blocker.

Unsafe only if product marketing claims “we respect shop hours” while only staff hours apply — that is a messaging risk, not a corruption risk.
