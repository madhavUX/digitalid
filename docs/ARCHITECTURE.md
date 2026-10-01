# ARCHITECTURE — Local Business Digital Growth Platform

Status: approved. Sections marked **Current** describe what exists today; sections marked **Target** describe the approved end state.

---

## 1. Technology Stack

| Concern | Technology | Notes |
|---|---|---|
| Frontend | Next.js (App Router) | Public sites, QuickCard, owner dashboard |
| Backend | Django + Django REST Framework | Source of truth for all business logic |
| Database | PostgreSQL | Single logical database, shared schema |
| Background jobs | Celery | Async and scheduled work (Celery Beat) |
| Queue / cache | Redis | Celery broker, result backend, cache, rate limits |
| Frontend hosting | Vercel | Edge/CDN rendering for public pages |
| DNS / CDN / WAF | Cloudflare | DNS, custom domains, TLS, edge protection |
| Auth | JWT (SimpleJWT) | Bearer access + refresh tokens |
| Object storage | S3-compatible | Media, generated QR assets |

**Current:** Django 5.2, DRF, SimpleJWT, `django-environ`, `psycopg` v3, PostgreSQL, Celery, Redis (via `REDIS_URL`), `django-redis`, Ruff, Gunicorn, WhiteNoise (admin/static behind Gunicorn). Next.js public booking UI lives in `frontend/`. Local production-like stack: `docker-compose.yml` (Postgres + Redis + web + worker + beat). Hostinger production compose project: `bookanything`. Object storage is **not yet configured**.

---

## 2. Frontend / Backend Separation

```
┌──────────────────────────────┐        ┌──────────────────────────────┐
│  Next.js (Vercel)            │        │  Django + DRF                │
│                              │        │                              │
│  • Public business sites     │        │  • Business rules            │
│  • QuickCard pages           │  HTTPS │  • Tenant resolution         │
│  • Owner/staff dashboard     │ ─────► │  • Availability computation  │
│  • Rendering, routing, UX    │  JSON  │  • Persistence               │
│  • UX-level validation       │ ◄───── │  • Integrations              │
│                              │        │  • Authorization             │
└──────────────────────────────┘        └──────────────────────────────┘
                                              │
                                    ┌─────────┴─────────┐
                                    ▼                   ▼
                              PostgreSQL            Redis ── Celery
```

### The Backend Is Authoritative

The frontend **must not** implement:

- Booking availability or slot computation
- Pricing, discounts, or deposit calculation
- Permission or role decisions (it may hide UI, but access is enforced server-side)
- Tenant selection or tenant scoping
- Subscription limits or feature gating enforcement
- Any validation that protects data integrity

The frontend **may** implement: presentation, routing, optimistic UI, client-side form validation for responsiveness (always re-validated server-side), and caching of backend responses.

**Rule:** if removing the frontend would allow invalid data into the system, the rule is in the wrong place.

### Rendering Strategy

| Surface | Strategy | Reason |
|---|---|---|
| Public business site | SSG/ISR with revalidation | SEO and speed |
| QuickCard | SSG/ISR | Speed, shareability |
| Booking flow | SSR/client with live API calls | Availability must never be cached |
| Dashboard | Client-rendered, authenticated | Private, dynamic |

Availability responses are never cached at the edge.

---

## 3. Backend Module Boundaries

Each Django app owns one bounded domain. Apps expose behavior through their **service layer**; other apps call services, not each other's internals.

```
config/                 Project settings, root URLs, WSGI/ASGI
core/                   Cross-cutting: mixins, permissions, exceptions, base models
api/v1/                 URL composition for version 1
accounts/               User identity and authentication
organizations/          Organization, membership, roles, tenant resolution
businesses/              Business entity, vertical configuration
locations/               Location, address, timezone + public location/catalog discovery URLs
catalog/                 Services, categories, service-location assignments (+ public catalog services)
staff/                   Staff profiles, service capabilities, availability, time-off
customers/               Customer records, tags, tag assignments
booking/                 Slot engine, appointments, public booking API + idempotency records
                 Design: docs/BOOKING_DESIGN.md
sites/          Presence: QuickCard (+ future website/template/QR inventory)
messaging/      Business WhatsApp connection, templates, queued outbound messages
payments/       Provider-agnostic appointment payments (Razorpay first)
reviews/        (target) Review requests and aggregation
discovery/      (target) SEO, AEO, GEO readiness
analytics/      (target) Metrics and reporting
billing/        (target) Platform subscriptions (separate from customer payments)
automation/     (target) Rule engine, triggers, scheduled actions
```

**Current apps:** `config`, `core`, `api`, `accounts`, `organizations`, `businesses`, `locations`, `catalog`, `staff`, `customers`, `booking`, `sites`, `messaging`, `payments`.

**Scheduling foundation (current in `staff/`):** `StaffAvailability` is recurring weekly hours bound to a specific `Location` (local `TimeField`s in `Location.timezone`). `StaffTimeOff` is org-wide for the staff member (aware datetimes). Overlaps for the same staff+location+weekday are rejected in services.

**CRM foundation (current in `customers/`):** `Customer` is business-scoped (not location-scoped), soft-deleted, identified by E.164 phone within a business. `CustomerTag` is business-owned; assignments are a hard-delete junction. Visit totals (`total_visits`, `first_visit_at`, `last_visit_at`) are derived from live COMPLETED appointments when `transition_appointment_status` sets `Appointment.completed_at`. Soft-deleted appointments are excluded. Public customer lookup/create is deferred. Writes require OWNER/MANAGER; STAFF may read all business customers for now, including `GET .../customers/{id}/retention-summary/`. The retention-summary response is a factual owner profile: visit counters, derived `days_since_last_visit` / `average_days_between_visits`, up to 10 recent completed visits, aggregated service/staff/location history, and a **deterministic** primary `segment` from business `CustomerRetentionSettings` thresholds (`return_after_days`, `inactive_after_days`). Segment priority: `NO_VISITS` → `NEW` (exactly one visit) → `INACTIVE` → `DUE_FOR_RETURN` → `RETURNING`. Segments are calculated dynamically (not stored on Customer) and are not predictions or churn scores. When `CustomerRetentionSettings.enabled`, completing an appointment with ≥2 visits schedules a `CustomerRetentionMessage` for `last_visit_at + return_after_days + due_message_delay_hours` (default delay 24h). Celery beat `process_due_retention_messages` revalidates eligibility (still `DUE_FOR_RETURN`, opt-in, connected WhatsApp, approved English `RETENTION`/`RETENTION_DUE_RETURN` template, unchanged visit cycle) then queues via existing `queue_whatsapp_message`. The retention WhatsApp `booking_url` is `/book/{location-slug}?source=retention&ref={public_reference}` (opaque ref, not a tenant/customer id). On public appointment create, after customer matching by phone, valid refs set `acquisition_source=RETENTION` and `acquisition_reference=CustomerRetentionMessage.id`; invalid/cross-tenant/cross-customer/cancelled refs still book with both fields null. This phase establishes attribution only — retention conversion analytics comes later. Disabled automation does not change segment classification. Owner UI: `/owner/customers` lists/filter customers, shows retention profile + automation status, and lets OWNER edit thresholds/automation (MANAGER may read settings; STAFF cannot). Reconcile with `manage.py reconcile_customer_visits`.

**Booking core (current in `booking/`):** `Appointment` + single `AppointmentItem` with catalog snapshots and occupancy windows. Slot engine uses a **15-minute** local grid. Any-staff resolves to one staff (lowest UUID among free candidates) before insert. Concurrency: `select_for_update` + PostgreSQL GiST exclusion on occupying occupancy ranges (`btree_gist`). Internal APIs under `/businesses/{id}/…` plus unauthenticated public booking under `/api/v1/public/booking/` (reuses the same services; `IdempotencyRecord` for create replay). Secure customer manage/cancel via `AppointmentManageToken` (hash-at-rest). **Book Regularly:** `BookingPlan` stores frequency/preferred time; each occurrence is created only through `create_appointment` (never direct inserts). Scheduler `process_due_booking_plans` books the next preferred slot when available, otherwise sets `needs_action` (no silent reschedule). Not a subscription; no payments inside the booking engine itself. See `docs/BOOKING_DESIGN.md`.

**Payments (current in `payments/`):** Provider-agnostic domain with Razorpay as the first provider (`PaymentProvider` → mock / razorpay / deferred). `Business.payment_mode` defaults to `NONE` (opt-in). When `FULL`/`DEPOSIT`, appointments get `payment_status=PENDING` and the public funnel shows a Payment step after create. Amounts come only from appointment snapshots. Checkout creates `PaymentOrder` (org+idempotency unique); verify + webhook update `Payment` then sync lightweight `Appointment.payment_status`. **Payment provider state is authoritative only after verified provider response/webhook.** Secrets never leave the backend. Attribution (`QUICKCARD` / `RETENTION`) is unchanged and independent of payment.

**Booking events → notifications (current):** After a successful booking or cancellation commits, the service layer emits a lightweight in-process domain event (`AppointmentBooked` / `AppointmentCancelled`) via `transaction.on_commit`. Handlers call `NotificationService`, which creates a `NotificationDelivery`, freezes a `payload_snapshot` (including the already-generated manage URL for confirmations), then invokes a `WhatsAppProvider` (`mock` or `meta`). `MetaWhatsAppProvider` sends approved Cloud API template messages; webhooks under `/api/v1/webhooks/whatsapp/` update provider delivery status. Notification failures never roll back the appointment. Retries reuse the frozen snapshot and never regenerate manage tokens.

**Appointment reminders (current):** Unconnected businesses still use `booking.reminders.process_due_reminders`. It finds CONFIRMED appointments whose UTC `starts_at - offset` falls in the late window and the appointment existed before the due instant. Connected WhatsApp businesses do not use that path for the 24-hour or 1-hour reminder. Both are `AppointmentReminder` rows, 24 hours and 1 hour before UTC start. A completed appointment schedules one `REVIEW_REQUEST` row `WHATSAPP_REVIEW_REQUEST_DELAY_HOURS` later (default 3). It is not sent at completion. The review link is the location launch profile `google_review_url` when it is an https URL. `google_business_url` remains owner-entered tracking and is not copied into the review link. Automatic Google review URL discovery is later work if an official API supplies it. A missing or invalid review URL, missing approved template, disconnected account, or `whatsapp_opt_in=false` marks the row `SKIPPED`. Confirmations, cancellations, reschedules, and reminders do not read that flag. Production needs Redis or RabbitMQ, a Celery worker, and Celery Beat. `memory://` is for local development and tests.

```
Appointment create/cancel (authoritative)
        ↓ commit
Booking event (AppointmentBooked / AppointmentCancelled)
        ↓
NotificationService
        ↓
NotificationDelivery + payload_snapshot
        ↓
WhatsAppProvider (mock | MetaWhatsAppProvider)
        ↓
Meta Cloud API (production)
        ↑
WhatsApp Webhook (signature-verified status updates)

Appointment (CONFIRMED, future starts_at)
        ↓
Reminder scheduler (process_due_reminders / send_due_reminders)
        ↓
NotificationService.send_appointment_reminder
        ↓
NotificationDelivery (REMINDER_24H | REMINDER_1H)
        ↓
WhatsAppProvider → Meta
```

Transactional WhatsApp uses the customer's existing E.164 `phone`. `Customer.whatsapp_opt_in` / `marketing_opt_in` remain reserved for future promotional messaging and do not gate booking confirmations, cancellations, or appointment reminders. Raw manage tokens remain hash-only on `AppointmentManageToken`. The customer-facing manage URL may appear inside `payload_snapshot` for retry fidelity only — it is not an authorization credential. Reminders reuse the confirmation snapshot's `manage_url` when present and never mint a new manage token.
**Public catalog (current):** Unauthenticated discovery under `/api/v1/public/locations/{slug}/…` resolves tenant from `Location.slug` (exactly one active match). Lists bookable services/categories/staff with `ServiceLocation` effective pricing via `booking.services.resolve_effective_pricing` (staff listing also applies `StaffService` overrides). Public staff requires availability at the location plus ≥1 bookable service there. Catalog/staff may be short-TTL cached (`Cache-Control`); availability/booking must not. UUID `id`s are returned only as a bridge to the existing public booking API.

**Public booking UI (current in `frontend/`):** Next.js App Router funnel at `/book/[locationSlug]` consumes public catalog + booking APIs (optional `service` / `staff` query prefill for Book Again, optional `source` / `ref` for QuickCard or retention attribution held only in the funnel for that attempt). Success page links to `/book/manage/[token]` using the one-time `manage_token` from create. Guest booking history lives at `/book/manage/[token]/history` (token-scoped; no customer login). Browser traffic is rewritten through `/backend/api/…` to Django (no CORS dependency). Availability is client-fetched and not long-cached; create sends `Idempotency-Key` and handles `409` stale slots.

**QuickCard (current in `sites/`):** One QuickCard per Location. The public slug is unique among live cards, so `/q/{slug}` does not collide the way `Location.slug` can across businesses. `Location.slug` remains the booking path (`/book/{locationSlug}`). API `GET /api/v1/public/quickcards/{slug}/` and the same handler at `GET /api/v1/public/q/{slug}/` compose Location, public catalog/staff pricing, launch-profile directions and review links, and provisional hours. `Cache-Control: public, max-age=60`. The page does not include availability. Unpublished, inactive, or deleted business/location → `404`. Book Now uses the existing funnel with `?source=quickcard&ref={slug}`. The booking page keeps that pair in React state for the current attempt and sends it as optional `attribution_source` / `attribution_ref` on `POST /public/booking/appointments/`. Django accepts `QUICKCARD` only when the slug is a published, live card for that same location, business, and organization; anything else creates a normal unattributed appointment. The stored value is the card UUID in `Appointment.acquisition_reference`. There is no foreign key, so later unpublish or soft delete leaves historical appointments attributed. Public appointment JSON does not include those fields. WhatsApp, call, directions, and review links are omitted unless a safe public value exists. Directions prefer `google_business_url`; the review CTA uses only `google_review_url`. No Google rating is invented. CTA elements carry `data-cta` (`book`, `whatsapp`, `call`, `directions`, `review`, `share`). A displayed card sends one anonymous `PAGE_VIEW`, and a click sends `CTA_CLICK`, to `POST /api/v1/public/quickcards/{slug}/events/`. That write is not cached, does not store IP, cookies, or customer identity, and is throttled per IP. Failure does not block the CTA. Clicks and attribution are separate: a Book Now click is an event even when no appointment is created. OWNER and MANAGER read last-30-day counts at `GET /api/v1/businesses/{id}/quickcard/analytics/`, including `bookings` from `Appointment.created_at`. Counts are events or attributed appointments, not unique visitors or revenue. `booking_conversion_rate` is attributed bookings divided by Book Now clicks times 100, one decimal, or null when Book Now clicks are 0. Bookings in that ratio are limited to QuickCard ids for the business, including cards later soft-deleted. Event dates use `occurred_at`; booking dates use `created_at`. The owner analytics page can request last 7, 30, or 90 UTC calendar days, or a custom `date_from`/`date_to`. Those parameters combine with optional `location_id`. The displayed range is the `date_from` and `date_to` returned by the API. OWNER/MANAGER manage via `/api/v1/businesses/{business_id}/locations/{location_id}/quickcard/`. QR PNG encodes only the public `/q/{slug}` URL. Book Regularly plans are not attributed in this phase.

**Owner onboarding + dashboard (current):** Authenticated OWNER/MANAGER UI under `/owner/*` (JWT stored as `ba_access_token`). Setup readiness is authoritative via `GET /api/v1/businesses/{id}/setup/`; dashboard summary via `GET /api/v1/businesses/{id}/dashboard/`. **Business Launch Profile** (`BusinessLaunchProfile`, per location) stores template key, domain config, Google Business tracking, WhatsApp setup status, website/launch status — not duplicated catalog/ops data. Launch readiness via `GET|POST|PATCH /api/v1/businesses/{id}/launch-profile/` (`get_business_launch_status`).

**Salon website templates (current):** Application registry `SALON_MODERN` / `SALON_CLASSIC` / `SALON_LUXURY` (no template tables). Public site payload `GET /api/v1/public/sites/{slug}/` (location slug or launch subdomain) composes Business/Location/services/staff/hours/QuickCard. Public only when launch-ready **and** `website_status=PUBLISHED`. Owner preview `GET /api/v1/businesses/{id}/website/preview/`. Owner management `GET|POST .../website/` (+ publish/unpublish). Frontend routes `/site/[slug]`, `/owner/website`, `/owner/website/preview`; middleware rewrites `{sub}.{BOOKANYTHING_SITE_DOMAIN}/` → `/site/{sub}` (skips `/api`, `/owner`, `/book`, `/q`, `/site`). Templates are presentation-only; BOOK A SLOT → existing `/book/{locationSlug}`. Canonical `public_url` uses the provisioned subdomain host (not `/site/...`). Custom-domain DNS/SSL automation remains out of scope.

**Business WhatsApp Platform foundation (current in `messaging/`):** A business-owned Cloud API connection (`WhatsAppAccount`), local `MessageTemplate` catalog, and append-only outbound `WhatsAppMessage` records. Credentials are AES-GCM encrypted (`messaging/whatsapp_crypto.py`, key `WHATSAPP_TOKEN_ENCRYPTION_KEY`) and never returned by API, admin, serializers, logs, `__str__`, or exception text. Provider boundary: `messaging.services` → `WhatsAppBusinessProvider` → `MockWhatsAppBusinessProvider` | `RealWhatsAppBusinessProvider` (Meta Graph `/{phone_number_id}/messages` only) | `DeferredWhatsAppBusinessProvider`. Selector `WHATSAPP_BUSINESS_PROVIDER=mock|meta|deferred`. This is **separate** from the platform transactional sender in `booking/whatsapp.py` (`WHATSAPP_PROVIDER` + platform `META_WHATSAPP_*` env), which remains the sender for booking confirmation, cancellation, and the 24-hour reminder when the business has not connected its own number. A connected account owns the 24-hour reminder even if the reminder template is not approved yet; that reminder is skipped instead of falling back to the platform sender. When a CONNECTED account and an `APPROVED` `en` template exist for `BOOKING_CONFIRMATION` or `BOOKING_CANCELLED`, the platform confirmation/cancellation send is skipped so the customer receives one message through the business account.

Lifecycle hooks (in-process, after commit): `AppointmentCreated`, `AppointmentConfirmed`, `AppointmentCancelled`, `AppointmentRescheduled`, `AppointmentCompleted`. `observe_appointment_lifecycle` calls `messaging.automation` and `messaging.reminders`. It does not call Meta. Missing account, missing/inactive template, or missing phone skips with a non-sensitive log and does not create a message. A provider failure marks `WhatsAppMessage` `FAILED` and never rolls back the appointment. Mapping: Created → `BOOKING_CONFIRMATION`, Confirmed → `BOOKING_CONFIRMED`, Rescheduled → `BOOKING_RESCHEDULED` (idempotency includes `updated_at`), Cancelled → `BOOKING_CANCELLED` (idempotency includes `cancelled_at`). Completion does not send a review immediately; it stores a delayed `REVIEW_REQUEST` reminder. The same webhook accepts inbound `text` messages, stores `WhatsAppInboundMessage`, and does not reply. OWNER and MANAGER can read `GET /api/v1/businesses/{id}/whatsapp/inbound/`. STAFF receives 403. The list is newest first and does not include tokens or the raw provider payload. Template catalog sync writes `provider_status` and does not replace local status or an existing body. Submit stores Meta `PENDING` and does not mark the local template approved. Production template submission requires `WHATSAPP_BUSINESS_PROVIDER=meta` and a configured WABA; that live call has not been executed. Variable names are an allowlist (`customer_name`, `business_name`, `location_name`, `service_name`, `staff_name`, `appointment_date`, `appointment_time`, `appointment_reference`, `booking_reference`, `booking_url`, `business_phone`, `review_url`). `booking_reference` is the same public reference as `appointment_reference`. Display date and time use `Location.timezone` (DST via `zoneinfo`). Reminder scheduling uses UTC. `POST /api/v1/webhooks/whatsapp/meta/` is the same signature-verified handler as `/api/v1/webhooks/whatsapp/`. Status moves `SENT` → `DELIVERED` → `READ`. `FAILED` and `CANCELLED` are terminal. Event time comes from the provider timestamp. Unknown `phone_number_id` is ignored. Transient provider errors stay `QUEUED` for up to three attempts; `PROVIDER_ERROR` is permanent. The same message row is retried. `booking/whatsapp.py` stays for businesses that have not connected their own account and can be removed after those businesses are migrated.

```
Owner API → messaging.services → WhatsAppBusinessProvider
  ├── MockWhatsAppBusinessProvider
  ├── DeferredWhatsAppBusinessProvider (no network)
  └── RealWhatsAppBusinessProvider → Meta Graph Cloud API only

Appointment service (after commit)
        ↓
AppointmentCreated / Confirmed / Cancelled / Rescheduled / Completed
        ↓
observe_appointment_lifecycle
        ↓
messaging.automation (skip if no account or approved template)
        ↓
queue_whatsapp_message
        ↓
Celery deliver_whatsapp_message
        ↓
WhatsAppBusinessProvider.send_template_message

queue_whatsapp_message (on commit)
        ↓
Celery deliver_whatsapp_message
        ↓
WhatsAppBusinessProvider.send_message | send_template_message
```

**Google Business Profile OAuth + location sync (current in `businesses/`):** Owner OAuth 2.0 connects a Google account; credentials encrypted (AES-GCM) on `GoogleBusinessConnection`. Single-use `GoogleOAuthState` (hashed). After OAuth: list GBP accounts (auto-select if one) → list locations → owner maps `google_location_id` → `CONNECTED`. Sync pushes canonical `{PUBLIC_APP_URL}/book/{location.slug}` to Google `websiteUri` when website is `PUBLISHED`. Provider boundary: `google_services` → `GoogleBusinessProvider` → `MockGoogleBusinessProvider` | `RealGoogleBusinessProvider` | deferred. Reviews/posts/messaging/photos/analytics remain deferred. Publish does **not** auto-call Google.

```
Owner API → google_services → GoogleBusinessProvider
  ├── MockGoogleBusinessProvider
  └── RealGoogleBusinessProvider → Account Management + Business Information APIs
```

```
Secure Manage Token
        ↓
Appointment → Customer scope
        ↓
GET /public/booking/history/{token}/
        ↓
Book Again prefill (bridge UUIDs)
        ↓
Existing booking funnel + POST /public/booking/appointments/
        ↓
New Appointment + new manage token + notifications
```

History is derived from `Appointment` rows (no history table). Authorization is token → appointment → customer only — never phone/email query params.

### Dependency Rules

- `core` depends on nothing internal except Django/DRF. Every app may depend on `core`.
- `accounts` and `organizations` are foundational; downstream apps may depend on them.
- Downstream apps must not import from each other's `models.py` for behavior — call the owning app's services.
- No circular dependencies. If two apps need each other, the shared concept belongs in `core` or a new app.
- `api/v1` only composes URLs. It contains no logic.

---

## 4. Layered Design

```
HTTP request
   │
   ▼
URL router            api/v1/urls.py → <app>/urls.py
   │
   ▼
View                  HTTP concerns, permissions, tenant context
   │
   ▼
Serializer            Input shape validation / output representation
   │
   ▼
Service               Business rules, transactions, orchestration   ◄── the important layer
   │
   ▼
Queryset / Manager    Tenant-scoped data access
   │
   ▼
Model                 Schema, constraints, invariants
```

### Layer Responsibilities

**View** — resolve tenant context, enforce permissions, deserialize input, call exactly one service, serialize output, choose the status code. No business rules.

**Serializer** — field types, format validation, required/optional, representation shape. **No** cross-entity rules, no writes that span entities, no external calls, no side effects. Model serializers are used for read representation; plain `Serializer` for input contracts.

**Service** — the only place business rules live. Functions are keyword-only, explicit, and testable without HTTP. Multi-step writes are wrapped in `transaction.atomic`. Services raise domain/DRF exceptions; they do not build HTTP responses.

**Current examples:**

```
accounts/services.py         register_user, login_user, issue_tokens
organizations/services.py    create_organization_with_owner, resolve_current_membership,
                             get_active_membership, user_can_access_organization,
                             list_organization_members, generate_unique_slug
```

**Model** — fields, relationships, database-level constraints, indexes, trivial derived properties. No orchestration, no external I/O.

---

## 5. Query and Repository Conventions

We do **not** use a separate repository pattern. Django's ORM managers and querysets are the data access layer. Conventions:

1. **Tenant-scoped querysets.** Every tenant-owned model gets a manager exposing a scoping entry point. All reads and writes go through it.

```python
Appointment.objects.for_organization(request.organization)
```

2. **Scoping happens first.** Filter by tenant before filtering by identifier, never after.

3. **Services own queries that encode business rules.** Views may perform trivial retrieval through a tenant-scoped manager; anything conditional belongs in a service.

4. **Explicit `select_related` / `prefetch_related`** on list endpoints. N+1 queries are defects.

5. **Missing or cross-tenant records return `404`**, so tenant boundaries do not leak existence.

6. **No raw SQL** unless justified in review, and always parameterized.

---

## 6. Tenant Model and Isolation

### Hierarchy

```
User
 └── OrganizationMember (role: OWNER | MANAGER | STAFF)
      └── Organization          ← tenant root, isolation boundary
           └── Business         ← brand / operating entity, carries vertical
                └── Location    ← physical outlet
                     └── Resources (services, staff, customers, appointments, …)
```

**Business is separate from Organization** so one tenant can operate multiple brands. **Location is separate from Business** so one brand can operate multiple outlets. Do not collapse these.

### Isolation Rules

1. Tenancy is **shared-schema, row-level**, enforced in application code.
2. The current organization is derived **only** from the authenticated user's membership.
3. `tenant_id` / `organization_id` / `business_id` / `location_id` supplied by the client is **never** trusted as authority. Such values are validated against the resolved tenant or ignored.
4. Every tenant-owned query is scoped to the resolved organization.
5. Cross-tenant access returns `404`.
6. Every tenant-owned endpoint requires an automated test proving Organization A cannot reach Organization B data.

### Current Implementation

`core/mixins.TenantContextMixin` overrides `perform_authentication` and attaches `request.organization` and `request.membership` from `organizations.services.resolve_current_membership(user)`, which reads `User.active_organization` and falls back to the user's oldest active membership. `core/permissions.HasOrganizationContext` rejects requests with no resolved organization.

**Target:** the same resolution promoted to middleware or a shared base view so it cannot be forgotten, plus tenant-scoped managers on every tenant-owned model, plus resolution of the active Business and Location.

### Platform Administration vs Organization Roles

These are **separate systems** and must not be merged.

| | Organization roles | Platform administration |
|---|---|---|
| Scope | One organization | Cross-tenant |
| Values | `OWNER`, `MANAGER`, `STAFF` | Platform staff/superuser |
| Stored on | `OrganizationMember.role` | `User.is_staff` / `User.is_superuser` |
| Granted via | Organization invitation | Internal provisioning only |
| Surface | Product API | Django Admin / internal tooling |

`SUPER_ADMIN` is **not** an organization role. Organization role choices are `OWNER`, `MANAGER`, `STAFF`.

**Current:** `organizations.models.Role` matches the approved set. Platform administration remains `User.is_superuser` / `User.is_staff`.

### Role Capabilities (target)

| Capability | OWNER | MANAGER | STAFF |
|---|:--:|:--:|:--:|
| Manage organization settings | ✓ | | |
| Manage subscription and billing | ✓ | | |
| Invite/remove members | ✓ | | |
| Create/manage businesses and locations | ✓ | | |
| Manage services and pricing | ✓ | ✓ | |
| Manage staff and schedules | ✓ | ✓ | |
| View all appointments | ✓ | ✓ | |
| Manage own appointments and schedule | ✓ | ✓ | ✓ |
| View customer records | ✓ | ✓ | own only |
| View analytics | ✓ | ✓ | |
| Manage website/templates | ✓ | ✓ | |
| Connect / select Google account+location / disconnect / sync Google booking URL | ✓ | | |
| View Google Business connection / accounts / locations status | ✓ | ✓ | |
| Connect / disconnect WhatsApp Business / manage templates | ✓ | | |
| View WhatsApp connection, templates, and outbound messages | ✓ | ✓ | |

---

## 7. Background Jobs

Celery (`config/celery.py`) runs async outbound WhatsApp delivery and periodic reminder/retention scans.

- **Broker / cache:** `REDIS_URL` in production (`DJANGO_ENV=production`). Development may omit Redis (LocMem cache + `memory://` broker).
- **Worker:** `celery -A config worker`
- **Beat:** `celery -A config beat` — run **exactly one** Beat per environment. Schedule is `CELERY_BEAT_SCHEDULE` in settings (60s reminder + retention processors).
- **Eager mode:** `CELERY_TASK_ALWAYS_EAGER` for tests only; forbidden in production (system check).
- **Tasks:** `messaging.tasks.deliver_whatsapp_message`, `process_due_appointment_reminders`, `process_due_retention_messages`; payment placeholder `payments.tasks.noop_reconcile_payments`.
- **Reliability:** queue after `transaction.on_commit`; task failures must not corrupt appointments/payments. See `docs/PRODUCTION_RUNBOOK.md`.

Health probes: `/health/live/`, `/health/ready/` (DB + Redis when required).

### Queues

| Queue | Purpose | Latency |
|---|---|---|
| `default` | General async work | Seconds |
| `messaging` | WhatsApp send/receive | Near real-time |
| `scheduled` | Reminders, review requests, win-back | Minute-accurate |
| `analytics` | Aggregation and rollups | Minutes |
| `maintenance` | Sitemaps, cleanup, exports | Best effort |

### Rules

1. Tasks are thin: a task resolves inputs and calls a service. **No business logic in tasks.**
2. Tasks take primitive arguments (UUIDs, strings) — never model instances.
3. Tasks are idempotent; redelivery must not double-send or double-charge.
4. Every task carries the organization identifier explicitly and re-scopes its queries.
5. Retries use bounded exponential backoff. Terminal failures are recorded, not swallowed.
6. Anything touching a third-party network call is async.
7. Long-running jobs report progress; they do not block a request.

### Representative Jobs

Appointment reminders, review requests, WhatsApp delivery and inbound processing, review aggregation, website revalidation triggers, sitemap generation, analytics rollups, subscription renewal and dunning, automation rule evaluation, QR asset generation.

---

## 8. Integrations

| Integration | Purpose | Direction | Boundary rules |
|---|---|---|---|
| WhatsApp Business Platform (business-owned) | Owner-connected Cloud API number for later automation | Out via `RealWhatsAppBusinessProvider` | AES-GCM token; `WHATSAPP_BUSINESS_PROVIDER`; async Celery delivery; no WhatsApp Web; official Graph API only |
| WhatsApp Cloud API (platform transactional) | Booking confirmation, cancellation, reminder | Out + status webhook | Existing `booking/whatsapp.py` + `WHATSAPP_PROVIDER`; signature-verified webhook; separate from business connection |
| Payment gateway | Appointment prepaid / deposits | Out + webhook | **Payment provider state is authoritative only after verified provider response/webhook.** Signature required. Idempotent by event id. Secrets never to frontend. |
| Google Business Profile | OAuth + location mapping + booking URL sync | Out (OAuth + API) | Encrypted tokens; single-use OAuth state; owner-only connect/select/sync; never auto-match multiple GBP locations; rate-limit/normalize 401/403/429; never blocks booking |
| Email provider | Transactional email | Out | Async |
| S3-compatible storage | Media, QR assets | Out | Signed URLs; no public buckets for private media |
| Cloudflare | DNS, custom domains, TLS | Out | Domain automation is async and auditable |
| Vercel | Public site revalidation | Out | Triggered by content change events |
| Analytics/monitoring | Errors, performance | Out | No PII or secrets in payloads |

**Integration rules:**

- Every integration sits behind a service in its owning app. No view or component calls a third party directly.
- All credentials come from environment variables.
- All outbound calls have timeouts and retry policies.
- All inbound webhooks verify signatures **before** processing and are idempotent.
- Provider failures degrade gracefully; a WhatsApp outage must not break booking.

**Google Cloud setup (manual, outside the repo):**

1. Create a Google Cloud project.
2. Enable Business Profile APIs (Account Management / Business Information as required for later sync).
3. Configure OAuth consent screen; request scope `https://www.googleapis.com/auth/business.manage` only.
4. Create an OAuth 2.0 Web client; set authorized redirect URI to `GOOGLE_OAUTH_REDIRECT_URI` (e.g. `https://bookanything.in/api/v1/businesses/google/callback/`).
5. Set `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_TOKEN_ENCRYPTION_KEY`, `GOOGLE_BUSINESS_PROVIDER=google`, `GOOGLE_BUSINESS_ENABLED=true`.
6. Obtain Business Profile API access/approval as required by Google (no general sandbox).
7. Production requires HTTPS and a verified production domain/website where Google demands it.

There is no general Google Business Profile API sandbox; CI uses `GOOGLE_BUSINESS_PROVIDER=mock`.

---

## 9. Security Boundaries

### Trust Zones

```
Untrusted:  End consumers, public pages, inbound webhooks, all client input
Semi:       Authenticated organization users (trusted only within their tenant)
Trusted:    Django backend, Celery workers, PostgreSQL, Redis
```

### Controls

**Authentication** — JWT bearer tokens (SimpleJWT). Access token 30 minutes, refresh token 7 days. Passwords hashed by Django with the full validator set. Email is the username and is normalized to lowercase.

**Authorization** — DRF defaults to `IsAuthenticated`. Tenant context is required by `HasOrganizationContext`. Role checks are explicit per endpoint. Object-level access is enforced by tenant-scoped querysets, not by object permission checks after the fact.

**Tenant boundary** — the primary security boundary. See §6.

**Input validation** — serializers validate shape at the boundary; services validate business rules. Never interpolate user input into SQL.

**Public surface** — public endpoints are explicitly enumerated in `docs/API.md`, are read-only apart from booking submission, expose only published content, and are rate-limited by IP.

**Secrets** — environment variables only. `.env` is git-ignored; `.env.example` documents required keys without values.

**Transport** — HTTPS everywhere; HSTS, secure cookies, and `SECURE_*` settings enabled in production.

**Rate limiting** — Redis-backed throttling on authentication, public booking, and public content endpoints.

**Audit** — security-relevant events (login, membership change, role change, permission change, billing change) are recorded with actor, organization, timestamp, and IP.

**Data protection** — customer PII is tenant-owned; never logged in full; export and deletion supported per organization.

---

## 10. Known Gaps Between Current Code and This Architecture

Tracked, not yet fixed. Do not treat current code as the specification where it disagrees with this document.

| # | Gap | Approved state |
|---|---|---|
| 1 | ~~`Role.SUPER_ADMIN` as organization role~~ | **Resolved:** `OWNER`, `MANAGER`, `STAFF` only |
| 2 | ~~No `Business` model~~ | **Resolved:** `businesses.Business` |
| 3 | ~~No `Location` model~~ | **Resolved:** `locations.Location` (hours/closures still target) |
| 4 | ~~Celery not installed or configured~~ | **Resolved (Phase 6.0.2):** Celery app, worker/beat runbook, Beat schedule |
| 5 | ~~Redis not configured~~ | **Resolved (Phase 6.0.2):** `REDIS_URL` → cache/broker/throttles; required in production |
| 6 | Soft deletion / row audit on Business, Location, ServiceCategory, Service, StaffProfile, Customer, Appointment | Extend to Organization; add `AuditLog`; junctions/labels/availability/time-off hard-delete |
| 7 | Pagination used by Business/Location lists; members still bare | Paginate remaining collection endpoints |
| 8 | Success responses are unwrapped; only errors have an envelope | Documented response format |
| 9 | Soft-delete managers exist; no shared TenantOwnedModel base yet | Promote shared tenant-owned base as more models land |
| 10 | Tenant context is opt-in per view via a mixin | Promote to middleware/base view so it cannot be omitted |
| 11 | `resolve_current_membership` writes `User.active_organization` during read requests | Read requests must not mutate state |
| 12 | `LoginView` catches `AuthenticationFailed` to force `401` | Acceptable workaround; centralize in the exception handler |
| 13 | ~~No throttling or production security settings~~ | **Partial (6.0.2):** Redis throttles + `SECURE_*` when `DEBUG=False`; CORS still optional (Next proxy) |
| 14 | Single-file `settings.py` | Env split via `DJANGO_ENV`; full file split still optional |
| 15 | Public booking + location catalog/staff APIs + Next.js booking funnel exist; QuickCard done | Redis-backed prod throttles ready when `REDIS_URL` set |

---

## 11. Deployment Architecture

```
                            ┌──────────────┐
        End users  ───────► │  Cloudflare  │  DNS, TLS, CDN, WAF
                            └──────┬───────┘
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
              ┌─────────────┐            ┌───────────────┐
              │   Vercel    │  API calls │  Django + DRF │
              │  (Next.js)  │ ─────────► │  (app servers)│
              └─────────────┘            └───────┬───────┘
                                                 │
                            ┌────────────────────┼────────────────────┐
                            ▼                    ▼                    ▼
                     ┌────────────┐       ┌────────────┐      ┌──────────────┐
                     │ PostgreSQL │       │   Redis    │◄────►│Celery workers│
                     │  (primary  │       │ broker +   │      │  + Beat      │
                     │  + replica)│       │   cache    │      └──────────────┘
                     └────────────┘       └────────────┘
                            │
                            ▼
                     ┌────────────┐
                     │ S3 storage │
                     └────────────┘
```

### Environments

| Environment | Purpose | Data |
|---|---|---|
| Local | Development | Seeded/synthetic |
| Staging | Pre-release verification | Anonymized |
| Production | Live | Real |

### Configuration

All configuration is environment-driven (`django-environ`). Required keys are documented in `.env.example`. No environment-specific values in source. `DEBUG` is never true in staging or production.

### Custom Domains

Businesses may attach custom domains. Domains are validated and provisioned through Cloudflare, with TLS issued automatically. Domain-to-tenant mapping is stored server-side; a request's `Host` header resolves published public content only and never grants authenticated access.

### Deployment Rules

1. Migrations run before application rollout.
2. Migrations must be backward compatible with the previous release (expand/contract).
3. Celery workers deploy from the same image as the web application.
4. Static and media assets are served from CDN/object storage, never from application servers.
5. Health checks cover the database, Redis, and Celery.
6. Zero-downtime rolling deploys; roll back by redeploying the previous image.
7. Automated database backups with tested restores.
