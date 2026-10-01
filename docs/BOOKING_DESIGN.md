# BOOKING DESIGN — Slot Engine and Appointment Lifecycle

Status: **implemented (booking core)** — internal APIs live in `booking/`. Public booking remains deferred.  
Authoritative sources: `docs/DATABASE.md` §4.7, `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/PRD.md` module 8.

---

## 0. Conflicts With This Task Prompt (Resolved Preferring Approved Docs)

| Topic | Task prompt | Approved docs | Design choice |
|---|---|---|---|
| Entity name | “Booking” model | `booking.Appointment` + `AppointmentItem` | Use **Appointment** / **AppointmentItem** |
| Status set | PENDING…NO_SHOW (no check-in) | Includes **CHECKED_IN** | Include **CHECKED_IN** |
| Source values | ADMIN, STAFF, PUBLIC_WEBSITE, QUICKCARD, API | `ONLINE`, `WHATSAPP`, `PHONE`, `WALK_IN`, `DASHBOARD` | Use DATABASE sources; map UX labels |
| Staff at create | Always exactly one staff | `staff_profile` **nullable** (any-staff) | Resolve any-staff → **one** staff before insert; persist non-null in v1 |
| Public paths | `/public/businesses/{slug}/locations/...` | `/public/locations/{slug}/…`, `/public/booking/…` | Follow **API.md** |
| Soft delete | Not specified | Soft-delete listed; never hard-deleted | Soft delete for erasure; **CANCELLED** for business cancel |

Any additive fields recommended below (e.g. occupancy range, `service_name` snapshot) require a **DATABASE.md update in the same change** as implementation. They are not invented silently at code time.

---

## 1. Booking Domain Model

### 1.1 Canonical names

- Django app: `booking/` (ARCHITECTURE target)
- Models: `Appointment`, `AppointmentItem` (DATABASE §5.5)
- HTTP resource (authenticated): `/api/v1/businesses/{business_id}/appointments/` (preferred) — alias “bookings” avoided to match the model. If product prefers `/bookings/`, document the alias in API.md; path must stay under the business nest.

### 1.2 `Appointment` (header)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `organization` | FK `PROTECT` | Denormalized tenant |
| `business` | FK `PROTECT` | Brand |
| `location` | FK `PROTECT` | Where the visit occurs |
| `customer` | FK `PROTECT` | Business-level customer |
| `staff_profile` | FK `PROTECT` | Assigned provider; **required at create in v1** after any-staff resolution |
| `starts_at` / `ends_at` | timestamptz | **Customer-visible** window in UTC |
| `status` | varchar(32) | See §2 |
| `source` | varchar(32) | See §16 |
| `total_price` / `currency` | decimal / varchar(3) | Snapshot sum of items |
| `deposit_amount` / `deposit_paid` | decimal / bool | Present per DATABASE; deposits deferred |
| `notes` | text | Staff/customer notes as allowed by channel |
| `cancelled_at` | timestamptz | Nullable |
| `cancellation_reason` | text/varchar | Nullable |
| `cancelled_by` | FK → User, nullable | Staff/owner cancel actor; null for public self-cancel |
| `public_reference` | varchar(32) unique | Opaque customer-facing id |
| timestamps | created_at / updated_at | |
| audit | created_by / updated_by | |
| soft delete | deleted_at / deleted_by | Erasure only; not used for normal cancel |

**Indexes** (DATABASE):  
`(organization, starts_at)`, `(location, starts_at, status)`, `(staff_profile, starts_at, status)`, `(customer, starts_at)`, unique `public_reference`, `(status, starts_at)`.

**Constraint:** `ends_at > starts_at`.

### 1.3 `AppointmentItem` (line — historical catalog snapshot)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `appointment` | FK `CASCADE` | Parent |
| `service` | FK `PROTECT` | Live catalog pointer (must not rewrite history fields) |
| `staff_profile` | FK `PROTECT` | Usually same as header in single-service v1 |
| `duration_minutes` | int | **Snapshot** |
| `price` / `currency` | decimal / varchar | **Snapshot** |

**v1 scope:** one Appointment → **exactly one** AppointmentItem (single service). Multi-service baskets are deferred (model already supports N items).

### 1.4 Recommended additive snapshots (doc update required at implement time)

DATABASE does not yet store name/buffer/occupancy snapshots. For historically correct and concurrency-safe booking, implementation should add (via DATABASE.md + migration):

| Field | Why |
|---|---|
| `AppointmentItem.service_name` | Catalog rename must not rewrite past receipts |
| `AppointmentItem.buffer_before_minutes` / `buffer_after_minutes` | Occupancy must not drift if catalog buffers change |
| `Appointment.occupancy_starts_at` / `occupancy_ends_at` | Buffer-aware conflict range for exclusion constraints |

Until those land, occupancy is derived as:

```
occupancy_start = starts_at − buffer_before
occupancy_end   = ends_at   + buffer_after
```

using buffers snapshotted in memory at create (and, ideally, persisted).

### 1.5 What must be snapshotted at creation

| Value | Source resolution order | Stored on |
|---|---|---|
| Duration | StaffService.duration → ServiceLocation.duration → Service.duration | AppointmentItem |
| Price / currency | StaffService → ServiceLocation → Service | AppointmentItem + Appointment totals |
| Service identity | Service FK + recommended `service_name` | AppointmentItem |
| Buffers | Service (no location/staff override today) | Recommended on item |
| Visible window | Requested local start + duration | Appointment.starts_at/ends_at (UTC) |
| Occupancy window | Visible ± buffers | Derived / recommended columns |
| Staff | Explicit or any-staff pick | Appointment + Item |
| Location / customer / org / business | Resolved server-side | Appointment |

Mutable catalog or staff display changes **must not** alter stored duration, price, currency, buffers, or (recommended) service name on past appointments.

### 1.6 Soft delete vs cancel

- **Cancel** → `status=CANCELLED` + cancellation fields; row remains for history, analytics, reviews.
- **Soft delete** → GDPR / org erasure only; excluded from default managers.
- **Never hard delete** (DATABASE).

---

## 2. Status State Machine

### 2.1 States (DATABASE)

| Status | Meaning |
|---|---|
| `PENDING` | Held/awaiting confirmation (deposit, staff confirm, or async review) |
| `CONFIRMED` | Firmly booked; occupies staff calendar |
| `CHECKED_IN` | Customer arrived / service started |
| `COMPLETED` | Service finished |
| `CANCELLED` | Explicitly cancelled; no longer occupies |
| `NO_SHOW` | Customer missed confirmed appointment |

### 2.2 Occupying statuses

Statuses that **block** staff time for conflict and slot math:

`PENDING`, `CONFIRMED`, `CHECKED_IN`

Non-occupying: `COMPLETED`, `CANCELLED`, `NO_SHOW`, and soft-deleted rows.

> Open decision: whether `PENDING` occupies immediately (recommended **yes** for double-book safety) and how long a PENDING hold lasts (TTL / auto-expire — future config).

### 2.3 Allowed transitions

```
PENDING    → CONFIRMED | CANCELLED
CONFIRMED  → CHECKED_IN | COMPLETED | CANCELLED | NO_SHOW
CHECKED_IN → COMPLETED | CANCELLED | NO_SHOW
COMPLETED  → (terminal)
CANCELLED  → (terminal)
NO_SHOW    → (terminal)
```

Disallowed examples: `COMPLETED → CONFIRMED`, `CANCELLED → CONFIRMED` (create a new appointment instead), arbitrary PATCH of status outside this map.

### 2.4 Transition actors (target)

| Transition | Dashboard (OWNER/MANAGER) | STAFF (own) | Public (reference) |
|---|---|---|---|
| Create → PENDING/CONFIRMED | ✓ | ✓ (own / assigned) | ✓ (policy) |
| Confirm PENDING | ✓ | ✓ | — |
| Check in / complete / no-show | ✓ | ✓ | — |
| Cancel | ✓ | ✓ | ✓ within policy |

Exact STAFF “own only” enforcement follows ARCHITECTURE capability matrix once staff↔user linkage is reliable.

---

## 3. Slot Calculation Algorithm

### 3.1 Inputs

**Required:** business, location, service, local `date` (calendar date in `Location.timezone`).  
**Optional:** `staff_profile_id` (omit ⇒ any eligible staff).  
**Channel:** internal vs public (public additionally requires `is_bookable_online`, published resources).

### 3.2 Output

List of slots:

```json
{
  "starts_at": "2026-09-10T04:30:00Z",
  "ends_at": "2026-09-10T05:30:00Z",
  "local_starts_at": "2026-09-10T10:00:00+05:30",
  "staff_profile_id": "<uuid or null>",
  "staff_options": ["<uuid>", "..."]
}
```

- Explicit staff query: each slot is for that staff; `staff_options` length 1.
- Any-staff query: return **distinct start times** where ≥1 staff is free; optionally include `staff_options` for assignment at create. Do **not** create multi-staff bookings.

### 3.3 Order of operations

1. **Resolve tenant context**  
   - Internal: membership → organization → business → location.  
   - Public: published location slug → business → organization (API.md rule 1).

2. **Validate location**  
   Alive, `is_active`, belongs to business, IANA `timezone` present.

3. **Validate service + ServiceLocation**  
   Service alive, `is_active`; public ⇒ `is_bookable_online`.  
   Require `ServiceLocation(service, location)`.  
   Resolve **effective duration/price** (see §9).

4. **Resolve eligible staff set**  
   - Same `organization` + `business`.  
   - Alive, `is_active`, `is_bookable`.  
   - Has `StaffService` for the service.  
   - Has `StaffAvailability` for this **location** on the weekday of `date` (staff may work multiple locations via availability rows; primary `StaffProfile.location` alone is insufficient).  
   - If `staff_profile_id` provided: intersect to that one staff (404/empty if ineligible).

5. **Resolve buffers**  
   From Service (`buffer_before_minutes`, `buffer_after_minutes`).  
   Slot step default: **effective duration** (open decision: fixed 5/15 min grid — see §15 open decisions).

6. **Per staff, build free intervals for the local day**  
   a. Convert local midnight→next midnight to UTC bounds.  
   b. Load `StaffAvailability` for `(staff, location, weekday)` → local time ranges → UTC intervals.  
   c. Subtract intersecting `StaffTimeOff` (org-wide for staff; aware UTC).  
   d. Subtract occupancy of existing appointments for that staff where status ∈ occupying set and `occupancy` overlaps the day (buffers included).  
   e. (**If LocationHours exists later**) intersect with location open intervals / subtract closures. **v1: skip** — staff availability is the schedule (see §4).

7. **Generate candidate starts**  
   For each free interval, emit starts where  
   `[start − buffer_before, start + duration + buffer_after] ⊆ free_interval`  
   and customer-visible `[start, start+duration]` fits.  
   Align to slot grid in **local** time, then convert to UTC.

8. **Any-staff merge**  
   Union start times across staff; attach eligible staff ids.

9. **Policy filters** (when configured)  
   Discard past (with grace), too-soon (min notice), too-far (max advance). Defaults TBD — see §17.

10. **Return** sorted by `starts_at`. Never cache at edge (ARCHITECTURE).

### 3.4 Pseudocode

```
eligible = staff satisfying steps 4
slots = {}
for staff in eligible:
    free = availability(staff, location, date) - time_off(staff) - occupying(staff)
    for start in candidates(free, duration, buffers, grid):
        slots.setdefault(start, []).append(staff.id)
return [{start, end, staff_options: ids} for start, ids in sorted(slots)]
```

---

## 4. Location Operating Hours Decision

**v1 decision: LocationHours is NOT a hard prerequisite for booking.**

| Approach | Pros | Cons |
|---|---|---|
| StaffAvailability only (chosen for v1) | Already implemented; multi-location per staff | Salon “closed” not expressible without emptying all staff schedules; public “hours” page incomplete |
| LocationHours required | Clear closed days; marketing hours | Not implemented; blocks booking if treated as hard dep |

**Recommendation:** Ship slot engine on **StaffAvailability + StaffTimeOff + appointments**. Treat `LocationHours` / `LocationClosure` (DATABASE target) as a **soft prerequisite** for:

- public hours display,
- global closed days without editing every staff row,
- intersecting open intervals in step 6e.

When LocationHours lands, slot algorithm intersects staff free time with location open time — no redesign of Appointment.

---

## 5. Timezone Strategy

| Concern | Rule |
|---|---|
| Storage | All appointment datetimes **timezone-aware UTC** (`USE_TZ=True`) |
| Location | `Location.timezone` is IANA source of truth |
| Availability walls | Local `TimeField` interpreted in location TZ |
| API | Accept/return ISO-8601 with offset or `Z`; reject naive |
| Slot generation | Operate in local civil time, convert boundaries with `ZoneInfo` |
| DST | Use zoneinfo fold/gap rules; never add fixed offsets manually |

### Conversion example

- Location: `Asia/Kolkata`  
- Customer wants local `2026-09-10 10:00` for 60m service  
- Persist: `starts_at=2026-09-10T04:30:00+00:00`, `ends_at=2026-09-10T05:30:00+00:00`  
- Display: convert with `astimezone(ZoneInfo(location.timezone))`

DST (e.g. `America/New_York`): generate slots on the local calendar day; skip non-existent local times; treat ambiguous fold times as the earlier offset unless product policy says otherwise (document in open decisions).

---

## 6. Buffer Strategy

Service fields (existing, unchanged):

- `duration_minutes` — customer-visible length  
- `buffer_before_minutes` — prep  
- `buffer_after_minutes` — cleanup  

### Example

- Duration 60, buffer before 10, buffer after 10  
- Customer-visible: **10:00 → 11:00** local  
- Staff occupancy: **09:50 → 11:10** local  

### Effects

| Concern | Uses |
|---|---|
| Slot generation | Occupancy must fit inside free intervals |
| Overlap / exclusion | Compare **occupancy** ranges, not only visible windows |
| Customer UI | Show visible start/end only |
| Staff calendar | Prefer showing occupancy or visible+buffer indicators |

Two appointments can abut on visible times (11:00 end / 11:00 start) only if buffers still do not overlap.

---

## 7. Staff Selection

### Option A — Explicit staff

Client sends `staff_profile_id`. Validate eligibility (§3.4). Lock/conflicts for that staff only.

### Option B — Any available staff

1. Slot API returns starts with `staff_options[]`.  
2. On create without staff: server picks one eligible staff whose occupancy is free (deterministic rule: least booked that day, then `display_name`, then UUID — **open decision**).  
3. Persist **exactly one** `staff_profile` on Appointment + Item.  
4. Never assign multiple staff to one appointment in v1.

DATABASE nullable `staff_profile` is interpreted as “selection not yet resolved”; **v1 API always resolves before insert**.

---

## 8. ServiceLocation Rules

Booking allowed only if `ServiceLocation(service, location)` exists.

### Effective duration / price (snapshot source)

```
duration = StaffService.duration_minutes
        or ServiceLocation.duration_minutes
        or Service.duration_minutes

price    = StaffService.price
        or ServiceLocation.price
        or Service.price

currency = StaffService.currency
        or ServiceLocation.currency
        or Service.currency
```

Buffers: Service only (no overrides today).

---

## 9. Concurrency Strategy (Critical)

Frontend checks and pre-read “is available” are **not** sufficient.

### Recommended stack (matches DATABASE intent)

1. **`transaction.atomic()`** around create/reschedule.  
2. **`select_for_update()`** on occupying appointments for the target `staff_profile` whose occupancy overlaps the candidate range (and optionally lock the `StaffProfile` row as a serialization point).  
3. **Recompute** occupancy conflicts inside the transaction after locks.  
4. **Insert** Appointment + Item.  
5. **PostgreSQL exclusion constraint** (target hardening, implement with v1 if Postgres in all envs):

```sql
-- Conceptual; Django ExclusionConstraint + tstzrange
EXCLUDE USING gist (
  staff_profile_id WITH =,
  tstzrange(occupancy_starts_at, occupancy_ends_at, '[)') WITH &&
) WHERE (status IN ('PENDING','CONFIRMED','CHECKED_IN') AND deleted_at IS NULL)
```

Requires `btree_gist` and stored occupancy columns (recommended additive fields).

### Simultaneous requests

| T1 | T2 |
|---|---|
| BEGIN | BEGIN |
| Lock overlapping rows / staff | Waits on lock |
| Sees free; INSERT | — |
| COMMIT | Acquires lock; sees T1 row; conflict → `409` |

SQLite test DB cannot fully prove exclusion constraints; concurrency tests should run against **PostgreSQL** (CI job or documented manual). Service-layer locking still tested with threads/transactions on Postgres.

DATABASE already states: service locking now; exclusion constraint as hardening — this design adopts both for production.

---

## 10. Booking Creation Transaction

Exact service flow (`booking.services.create_appointment`):

1. Authenticate / authorize (internal roles or public rate limit).  
2. Resolve organization (membership or public slug).  
3. Resolve business (tenant-scoped).  
4. Resolve location (same business, active).  
5. Resolve service (active; public ⇒ online bookable).  
6. Resolve or create customer (internal: existing id; public: find-by-phone or create — §11).  
7. Resolve staff (explicit or any-staff picker).  
8. Validate ServiceLocation.  
9. Validate StaffService.  
10. Validate staff has availability context for location (and optional primary-location policy — open).  
11. Compute visible window + occupancy from local start + snapshots.  
12. `atomic` + `select_for_update` conflict set.  
13. Revalidate occupancy free; revalidate time-off / weekly availability still hold.  
14. Create Appointment + AppointmentItem; set `public_reference`; audit actors.  
15. Commit.  
16. Post-commit (deferred): visit counters, WhatsApp, Celery — **out of scope for engine v1** beyond hooks.

On conflict: raise validation / conflict → API **`409`**.

---

## 11. Customer Handling

- Appointment always FK → `Customer` (`PROTECT`).  
- Customers are **not** Users.

| Channel | Behavior |
|---|---|
| Internal | Require existing `customer_id` in tenant business (or allow create via CRM services in same request — open) |
| Public (future) | Lookup by E.164 phone within business; if miss, create Customer with provided name/phone/email; never expose other customers |

No public customer list. Visit counters updated when appointment reaches `COMPLETED` (service in customers app called from booking).

---

## 12. Rescheduling

**Practical choice: in-place update** of the same Appointment (not a new row), because DATABASE has no reschedule-event entity.

### Rules

1. Only from `PENDING` | `CONFIRMED` (not terminal / not CHECKED_IN unless product allows — default: allow CONFIRMED only; CHECKED_IN blocked).  
2. Same transaction pattern as create: recompute occupancy, lock, conflict check.  
3. Update `starts_at` / `ends_at` / occupancy; keep snapshots unless service/staff change (staff change allowed with revalidation).  
4. Record `updated_by`; when `AuditLog` exists, log before/after.  
5. Do **not** clear cancellation fields unless resurrecting (not allowed).

Alternative (rejected for v1): cancel + new appointment — better audit trail but breaks `public_reference` continuity and review FK uniqueness.

---

## 13. Cancellation

| Field | Use |
|---|---|
| `status=CANCELLED` | Terminal non-occupying |
| `cancelled_at` | UTC now |
| `cancellation_reason` | Free text / coded reason |
| `cancelled_by` | Authenticated staff/owner user; **null** for public self-service |

Public cancel: `POST /public/booking/{public_reference}/cancel/` within policy (window TBD).  
Notifications: **out of scope** (hook only).

---

## 14. API Design

### 14.1 Authenticated (tenant from membership)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/businesses/{business_id}/locations/{location_id}/availability/` | Query: `service_id`, `date`, optional `staff_id` |
| `GET` | `/api/v1/businesses/{business_id}/appointments/` | Paginated list + filters §15 |
| `POST` | `/api/v1/businesses/{business_id}/appointments/` | Create |
| `GET` | `/api/v1/businesses/{business_id}/appointments/{id}/` | Detail |
| `PATCH` | `/api/v1/businesses/{business_id}/appointments/{id}/` | Status transitions, reschedule fields, notes |
| `POST` | `/api/v1/businesses/{business_id}/appointments/{id}/cancel/` | Optional explicit cancel action |

Permissions (target): OWNER/MANAGER full calendar; STAFF manage own schedule / create for self; reads per matrix.

### 14.2 Public (API.md — do not invent alternate trees)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/public/locations/{slug}/services/` | Bookable catalog |
| `GET` | `/api/v1/public/locations/{slug}/staff/` | Bookable staff |
| `GET` | `/api/v1/public/booking/availability/` | Query: location, service, date, optional staff |
| `POST` | `/api/v1/public/booking/` | Create |
| `GET` | `/api/v1/public/booking/{public_reference}/` | Lookup |
| `POST` | `/api/v1/public/booking/{public_reference}/cancel/` | Cancel |

Public never returns full customer PII lists, tenant ids as authority, or other customers’ data. Availability never edge-cached.

---

## 15. Pagination / Filtering (Internal Lists)

Paginated via existing `StandardLimitOffsetPagination`.

Allowed filters (narrow only; never widen tenant):

| Param | Effect |
|---|---|
| `starts_at_after` / `starts_at_before` | Date range |
| `location_id` | |
| `staff_id` | |
| `service_id` | Via items |
| `customer_id` | |
| `status` | Single or multi (API target comma-separate) |

Ignored: `organization_id`, `tenant_id`. Unknown params ignored per API.md.

---

## 16. Booking Source

Use DATABASE values:

| Value | Typical mapping |
|---|---|
| `DASHBOARD` | Owner/manager UI (task “ADMIN”) |
| `WALK_IN` | Front-desk walk-in |
| `PHONE` | Booked by staff from phone call |
| `ONLINE` | Public website / QuickCard (task “PUBLIC_WEBSITE” / “QUICKCARD”) |
| `WHATSAPP` | Future messaging-originated |

Extensibility: varchar + documented choices; new channels require API/DATABASE note. Do not use task’s alternate enum without a doc change.

---

## 17. Business Rules

| Rule | v1 stance |
|---|---|
| Past times | Reject for public; internal may allow with OWNER/MANAGER override (**open**) |
| Max advance | **Future config** (e.g. 30/60/90 days) — not invented |
| Min notice | **Future config** |
| Cancellation window | **Future config**; public cancel endpoint reserved |
| Inactive service / staff / location | Reject |
| Staff not bookable | Exclude from slots / reject create |
| No ServiceLocation | Reject |
| No StaffService | Reject |
| Time-off / no availability | No slots / reject create |
| Buffers | Always applied (§6) |
| Deposits | Fields exist; logic deferred |
| PENDING TTL | **Future config** |

PRD mentions lead time / cancellation / deposits at onboarding — store later on Business/Location settings; until then, only structural validation + occupancy.

---

## 18. Test Strategy

### Functional

- Happy-path create (explicit staff)  
- Any-staff create assigns exactly one staff  
- No eligible staff → empty slots / create 400  
- Staff time off removes slots  
- Weekly availability respected per location  
- Service not at location → reject  
- Inactive service / staff / location → reject  
- Buffer-aware non-overlap (visible abut, occupancy clash)  
- Cancel frees capacity  
- Reschedule conflict / success  
- Status machine rejects illegal transitions  
- Timezone round-trip Asia/Kolkata  
- DST day generation (America/New_York spring/fall)  
- Cross-tenant appointment access → 404  
- Public reference lookup without leaking other orgs  

### Concurrency (CRITICAL)

- Two parallel transactions booking the **same staff** overlapping occupancy → exactly one success, one `409` / integrity error  
- Run on **PostgreSQL** (not only SQLite)  
- Assert exclusion constraint if shipped  

### Regression

- Existing suite (org, business, location, catalog, staff, scheduling, customers) remains green  

---

## 19. Prerequisites

| Prerequisite | Hard / Soft | Notes |
|---|---|---|
| Existing org → business → location → catalog → staff → availability → time-off → customers | **Hard** | Already implemented |
| `booking` Django app + migrations aligned to DATABASE §5.5 | **Hard** | Implementation task |
| PostgreSQL for production concurrency / exclusion | **Hard** for exclusion; locking works on PG |
| `LocationHours` / `LocationClosure` | **Soft** | Not required for v1 slots |
| Celery / WhatsApp / deposits / public site publish flags | **Soft** | Hooks later |
| DATABASE updates for occupancy + `service_name` snapshots | **Recommended hard** before exclusion constraint |

---

## 20. Explicit Assumptions / Resolved Decisions (v1)

1. **Slot grid** — **15 minutes** (local wall-clock).  
2. **PENDING occupies calendar** — yes; no TTL yet.  
3. **Any-staff pick** — among staff free for the requested start, choose lowest `staff_profile.id` (UUID string).  
4. **Eligibility** — requires `StaffAvailability` at the booking location (primary location alone insufficient).  
5. **Past appointments** — availability listing hides past starts; internal create does not invent lead-time policies.  
6. **Path** — authenticated resource is `/appointments/` (not `/bookings/`).  
7. **Snapshots** — `service_name`, buffers, occupancy columns implemented.  
8. **Staff required** — non-null `staff_profile` after any-staff resolution.  
9. **Lead time / cancel window / deposits** — deferred (no magic numbers).  
10. **Public booking** — deferred.  
11. **Multi-service** — deferred (one AppointmentItem).  
12. **LocationHours** — soft prerequisite; not required for v1 slots.

---

## 21. Implementation Sequence (When Authorized)

1. Update DATABASE.md / API.md for additive fields + authenticated appointment routes.  
2. Create `booking` app: models, exclusion constraint, services (`compute_slots`, `create_appointment`, `reschedule`, `transition_status`, `cancel`).  
3. Internal APIs + tests (including Postgres concurrency).  
4. Public availability + create/cancel (still no WhatsApp).  
5. Soft LocationHours later to tighten open intervals.

---

## Document Control

- Created as design-only output for the Booking + Slot Engine task.  
- **No application code, migrations, or model changes** accompany this document in that task.  
- Implementation must not begin until this design (and any open decisions the team closes) is accepted.
