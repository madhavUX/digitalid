# API — Conventions and Surface

Base path: `/api/v1/`

Sections marked **Current** describe implemented behavior. Sections marked **Target** are approved but not yet implemented.

---

## 1. Versioning

All endpoints are namespaced by URL path version: `/api/v1/<resource>/`.

- The version changes only for breaking changes. Additive fields and new endpoints are not breaking.
- A new version means a new URL namespace (`/api/v2/`), not conditional behavior inside v1.
- Versions are composed in `api/v1/urls.py`, which only includes app URL modules and contains no logic.
- Django Admin is served at `/admin/` and is outside the API contract.

**Current:**

```
config/urls.py     /admin/            → Django Admin
                   /api/v1/           → api.v1.urls
api/v1/urls.py     ""                 → accounts.urls
                   ""                 → organizations.urls
```

---

## 2. Naming Conventions

| Rule | Example |
|---|---|
| Lowercase, hyphen-separated path segments | `/api/v1/service-categories/` |
| Plural nouns for collections | `/api/v1/appointments/` |
| Resource id in path for detail | `/api/v1/appointments/{id}/` |
| Nested only one level deep | `/api/v1/locations/{id}/staff/` |
| Trailing slash required | `/api/v1/customers/` |
| Verbs only as explicit sub-actions | `/api/v1/appointments/{id}/cancel/` |
| No verbs in resource names | not `/api/v1/get-appointments/` |
| Singular path allowed for the implicit current tenant resource | `/api/v1/organization/` |
| `snake_case` for JSON fields and query parameters | `starts_at`, `is_active` |
| Public endpoints under a `public/` prefix | `/api/v1/public/booking/availability/` |

Deeper relationships are expressed with query filters rather than deep nesting: `/api/v1/appointments/?location_id=...` rather than `/api/v1/businesses/{id}/locations/{id}/appointments/`.

**HTTP methods**

| Method | Use | Idempotent |
|---|---|---|
| `GET` | Read | Yes |
| `POST` | Create, or a non-idempotent action | No |
| `PATCH` | Partial update (preferred) | Yes |
| `PUT` | Full replacement (rare) | Yes |
| `DELETE` | Delete (soft delete where applicable) | Yes |

---

## 3. Authentication

JWT bearer tokens via `djangorestframework-simplejwt`.

```
Authorization: Bearer <access_token>
```

| Token | Lifetime | Purpose |
|---|---|---|
| Access | 30 minutes | Sent with every authenticated request |
| Refresh | 7 days | Exchanged for a new access token |

**Conventions**

- Email is the username; it is normalized to lowercase on input and storage.
- Access tokens carry the user identity (`user_id` claim, the user UUID). **Tokens do not carry tenant authority.** A tenant identifier in a token is never used to select data.
- `register` and `login` set `authentication_classes = []`; they must not require a token.
- Missing or invalid credentials return `401`. An authenticated user lacking permission or tenant context returns `403`.
- Refresh tokens are exchanged at `/api/v1/auth/refresh/`.

**Target:** refresh-token rotation with blacklisting, logout endpoint, password reset flow, email verification, and per-IP throttling on authentication endpoints.

**Role permissions (current):** `IsOrganizationOwner` gates create/update/delete of businesses and locations. Read access is available to any member with tenant context.

### Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/auth/register/` | Public | Create user + organization, return tokens |
| `POST` | `/api/v1/auth/login/` | Public | Authenticate, return tokens |
| `POST` | `/api/v1/auth/refresh/` | Public (valid refresh token) | New access token |
| `GET` | `/api/v1/auth/me/` | Bearer | Current user, organization, membership |

**`POST /api/v1/auth/register/`**

```json
{
  "email": "owner@example.com",
  "password": "StrongPass123",
  "first_name": "Ada",
  "last_name": "Lovelace",
  "organization_name": "Ada Salon"
}
```

`first_name` and `last_name` are optional. Creates the `User`, creates the `Organization`, and creates an `OrganizationMember` with role `OWNER`. Returns `201`.

```json
{
  "user": {
    "id": "…", "email": "owner@example.com",
    "first_name": "Ada", "last_name": "Lovelace",
    "date_joined": "2026-09-07T08:00:00Z"
  },
  "organization": {
    "id": "…", "name": "Ada Salon", "slug": "ada-salon",
    "is_active": true, "created_at": "2026-09-07T08:00:00Z"
  },
  "membership": { "id": "…", "role": "OWNER", "is_active": true },
  "access": "…",
  "refresh": "…"
}
```

**`POST /api/v1/auth/login/`** — `{ "email": …, "password": … }`. Returns `200` with the same shape. Invalid credentials return `401`. `organization` and `membership` are `null` if the user has no active membership.

**`POST /api/v1/auth/refresh/`** — `{ "refresh": … }` → `{ "access": … }`.

**`GET /api/v1/auth/me/`** — returns `{ "user": …, "organization": … | null, "membership": … | null }`. Does **not** require tenant context, so a user without a membership can still read their own profile.

---

## 4. Tenant Resolution

**The client never selects the tenant.**

Resolution order, performed server-side on every authenticated request:

1. Authenticate the bearer token → `request.user`.
2. Resolve the active membership from persisted user state:
   - `User.active_organization`, if the user has an **active** membership in it and the organization is active;
   - otherwise the user's oldest active membership in an active organization.
3. Attach `request.organization` and `request.membership`.
4. If no membership resolves, `request.organization` is `None`.

**Current implementation:** `core/mixins.TenantContextMixin` (overrides `perform_authentication`) calling `organizations.services.resolve_current_membership`.

**Rules**

- `tenant_id`, `organization_id`, `business_id`, and `location_id` in a request body, query string, or header are **never** trusted as authority. They are either ignored or validated against the resolved tenant.
- Every tenant-owned query is filtered by the resolved organization.
- A record belonging to another tenant returns `404`, never `403`, so existence is not disclosed.
- Endpoints that need tenant data require the `HasOrganizationContext` permission, which returns `403` when no organization resolves.

**Target:** an explicit organization-switch endpoint (`POST /api/v1/auth/switch-organization/`) that validates membership server-side before updating `User.active_organization`, plus resolution of the active business and location. Until then, switching is not supported through the API.

---

## 5. Permissions

| Layer | Mechanism |
|---|---|
| Default | `IsAuthenticated` (DRF `DEFAULT_PERMISSION_CLASSES`) |
| Public endpoints | Explicit `AllowAny` |
| Tenant context required | `core.permissions.HasOrganizationContext` |
| Role required | Role permission classes (**target**) |
| Object access | Tenant-scoped querysets, not post-hoc object checks |

Authorization is **deny by default**. An endpoint is public only when it explicitly declares `AllowAny` and appears in §9.

**Role permissions (current / target)** — `IsOrganizationOwner` gates Business/Location/Catalog writes. `IsOrganizationManagerOrAbove` gates Staff writes (OWNER + MANAGER per capability matrix). Additional classes remain target. Role checks read `request.membership.role`, never a client-supplied role.

**Platform administration** is not exposed through the product API. It is available through Django Admin and internal tooling only.

**Status code semantics**

| Code | Meaning |
|---|---|
| `401` | No credentials, or invalid/expired token |
| `403` | Authenticated but not permitted, or no tenant context |
| `404` | Not found, **or belongs to another tenant** |

---

## 6. Response Format

### Success

Detail and action responses return the resource object directly, with no wrapper:

```json
{ "id": "…", "name": "Ada Salon", "slug": "ada-salon", "is_active": true, "created_at": "…" }
```

Collection responses return the pagination envelope in §7.

Conventions:

- `Content-Type: application/json`. JSON is the only renderer (`JSONRenderer`).
- Field names are `snake_case`.
- Timestamps are ISO 8601 UTC with a `Z` suffix.
- Identifiers are UUID strings.
- Money is a decimal string with an accompanying `currency` field.
- Absent values are `null`, not omitted.

| Method | Success code |
|---|---|
| `GET` | `200` |
| `POST` (create) | `201` |
| `POST` (action) | `200`, or `202` if queued |
| `PATCH` / `PUT` | `200` |
| `DELETE` | `204` |

### Errors

All errors pass through `core.exceptions.api_exception_handler` and share one envelope:

```json
{
  "error": "Invalid email or password.",
  "status_code": 401
}
```

Field-level validation errors place the DRF error map in `error`:

```json
{
  "error": {
    "email": ["A user with this email already exists."],
    "password": ["This password is too short."]
  },
  "status_code": 400
}
```

When the underlying exception has a single `detail` key, it is unwrapped into a plain string; otherwise the full structure is preserved.

**Target:** add a stable machine-readable `code` (for example `validation_error`, `not_found`, `tenant_forbidden`, `rate_limited`) and a `request_id` for correlation, without changing the existing keys.

| Code | Meaning |
|---|---|
| `400` | Validation failure |
| `401` | Authentication required or failed |
| `403` | Permission denied, or no tenant context |
| `404` | Not found, or another tenant's record |
| `405` | Method not allowed |
| `409` | Conflict (for example, a double-booked slot) |
| `422` | Semantically invalid but well-formed (**target**) |
| `429` | Rate limited (**target**) |
| `500` | Server error; never leaks internals |

---

## 7. Pagination

Limit/offset pagination with a fixed envelope (`core.pagination.StandardLimitOffsetPagination`):

```
GET /api/v1/businesses/?limit=50&offset=100
```

```json
{
  "count": 1284,
  "limit": 50,
  "offset": 100,
  "next": "/api/v1/businesses/?limit=50&offset=150",
  "previous": "/api/v1/businesses/?limit=50&offset=50",
  "results": [ … ]
}
```

- Default page size 25, maximum 100.
- `count` is scoped to the tenant and to active filters.
- High-volume time-series collections (analytics events, messages) use cursor pagination on `created_at` instead.

**Current:** Business, Location, ServiceCategory, Service, ServiceLocation, StaffProfile, StaffService, StaffAvailability, StaffTimeOff, Customer, CustomerTag, CustomerTagAssignment, Appointment, and AppointmentItem list endpoints are paginated. `/api/v1/organization/members/` still returns a bare JSON array (known gap).

---

## 8. Filtering, Sorting, Search

| Concern | Parameter | Example |
|---|---|---|
| Field filter | `<field>=<value>` | `?vertical=SALON` |
| Multi-value | repeat or comma-separate | `?status=PENDING,CONFIRMED` (**target**) |
| Range | `<field>_after` / `<field>_before` | `?starts_at_after=…` (**target**) |
| Search | `search` | `?search=ada` |
| Sort | `ordering`, `-` for descending | `?ordering=-created_at` |
| Field selection | `fields` | `?fields=id,name` (**target**) |

**Current Business filters:** `vertical`, `is_active`, `search` (name/slug), `ordering` (`name`, `created_at`, `updated_at`).
**Current Location filters:** `is_active`, `is_primary`, `search` (name/city/slug), `ordering` (`name`, `created_at`, `city`).
**Current ServiceCategory filters:** `search`, `ordering` (`display_order`, `name`, `created_at`).
**Current Service filters:** `category_id`, `is_active`, `is_bookable_online`, `search`, `ordering` (`name`, `created_at`, `price`).
**Current Staff filters:** `location_id`, `is_active`, `is_bookable`, `search` (display_name/title), `ordering` (`display_name`, `created_at`, `title`).

Rules:

- Filters apply **after** tenant scoping. A filter can narrow a tenant's data; it can never widen it.
- Only whitelisted fields are filterable, searchable, and sortable. Arbitrary field lookups are rejected with `400`.
- `organization_id`, `tenant_id`, and equivalents are **not** valid filter parameters. Supplying them has no effect on scoping.
- Every filterable and sortable field must be index-backed.
- Unknown query parameters are ignored.

---

## 9. Public vs Authenticated APIs

### Authenticated (default)

Everything under `/api/v1/` requires a bearer token unless explicitly listed below. Most endpoints additionally require tenant context.

### Infrastructure health (unauthenticated, outside `/api/v1/`)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health/live/` | Liveness — process up (`200`) |
| `GET` | `/health/ready/` | Readiness — database required; Redis when `REDIS_URL` set or `DJANGO_ENV=production`. `503` if dependencies down. No secrets in body. |

### Public

Public endpoints are unauthenticated, read-only apart from booking submission, and expose **only published, customer-facing data**. They are explicitly enumerated here.

**Current public endpoints:** `/api/v1/auth/register/`, `/api/v1/auth/login/`, `/api/v1/auth/refresh/`, public catalog under `/api/v1/public/locations/`, and public booking under `/api/v1/public/booking/`.

**Current public catalog endpoints** (under `/api/v1/public/locations/`):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/public/locations/{slug}/` | Public location + business summary |
| `GET` | `/public/locations/{slug}/services/` | Bookable services at that location (paginated) |
| `GET` | `/public/locations/{slug}/services/{service_identifier}/` | Service detail (`service_identifier` = service `slug` or UUID) |
| `GET` | `/public/locations/{slug}/categories/` | Categories that have ≥1 public bookable service at the location |
| `GET` | `/public/locations/{slug}/staff/` | Bookable staff at that location (paginated) |
| `GET` | `/public/quickcards/{slug}/` | Published QuickCard. Unpublished, inactive, or unknown → `404`. `Cache-Control: public, max-age=60` |
| `GET` | `/public/q/{slug}/` | Same public QuickCard payload |
| `POST` | `/public/quickcards/{slug}/events/` | Anonymous `PAGE_VIEW` or `CTA_CLICK`. `204`, `Cache-Control: no-store`. Hidden card → `404`. Unknown values → `400` |

**Current public booking endpoints** (under `/api/v1/public/booking/`):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/public/booking/availability/` | **Backend-computed** slots (`location_id`, `service_id`, `date`, optional `staff_id`) |
| `POST` | `/public/booking/appointments/` | Create an appointment (optional `Idempotency-Key`); response includes one-time `manage_token` |
| `GET` | `/public/booking/manage/{token}/` | Secure manage lookup by opaque manage token (hash-at-rest) |
| `POST` | `/public/booking/manage/{token}/cancel/` | Cancel via manage token (reuses lifecycle; idempotent if already cancelled) |
| `GET` | `/public/booking/history/{token}/` | Guest booking history for the customer scoped by the manage token (`category`, `limit`, `offset`) |
| `GET` | `/public/booking/history/{token}/book-again/{public_reference}/` | Book Again prefill (bridge IDs); does **not** create an appointment |
| `POST` | `/public/booking/plans/` | Create BookingPlan + first Appointment (Book Regularly; optional `Idempotency-Key`); returns `manage_token` + `plan_token` |
| `GET` | `/public/booking/plans/{token}/` | Plan summary via plan manage token |
| `POST` | `/public/booking/plans/{token}/pause/` · `/resume/` · `/cancel/` | Plan lifecycle (cancel does not cancel appointments) |
| `POST` | `/public/booking/manage/{token}/plan/pause/` · `/resume/` · `/cancel/` | Same actions authorized via appointment manage token when linked |
| `GET` | `/public/booking/appointments/{public_reference}/` | Look up a booking by opaque reference (read-only summary) |
| `POST` | `/public/booking/appointments/{public_reference}/cancel/` | Legacy cancel by reference (prefer manage-token cancel for customer links) |

**Target public endpoints** (under `/api/v1/public/`, not yet implemented):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/public/businesses/{slug}/` | Published business profile |
| `GET` | `/public/reviews/{location_slug}/` | Published reviews |

**Public identifier strategy**

1. **Location selector:** path `{slug}` is `Location.slug`. Schema uniqueness is per-business; public resolution requires **exactly one** live, active location with that slug under an active business. Zero or multiple matches → `404`. Prefer unique location slugs across tenants until a global unique constraint is added.
2. **Service path identifier:** `{service_identifier}` accepts service `slug` (preferred in URLs) or service UUID. Both are scoped to the resolved location’s business and `ServiceLocation` assignment.
3. **Booking bridge IDs:** catalog/staff responses include location/service/staff UUID `id` fields so clients can call existing `/public/booking/*` endpoints without a second lookup. Organization IDs are never returned. Staff has no public slug; UUID is the approved public staff identifier for booking.
4. There is **no** public list/enumerate endpoint for locations or businesses.

**Public endpoint rules**

1. For public catalog, tenant context is resolved **only** from the location slug → location → business → organization. For public booking, tenant context is resolved from the selected `location_id`. Never trust client-supplied `organization_id` / `tenant_id` / price / duration / buffers.
2. Never expose customer PII, occupancy windows, payment internals, audit actors (`created_by` / `updated_by` / `deleted_by`), or organization identifiers on public responses.
3. Booking **reads** may use opaque `public_reference`. Customer **management/cancellation** must use a cryptographically random `manage_token` (only the SHA-256 hash is stored). Never expose appointment UUIDs on public manage responses.
4. Guest **booking history** is authorized only via a valid manage token → appointment → `customer_id`. There is no public phone/email history lookup. History rows omit internal IDs, phone, and email. `Book Again` returns existing public booking bridge UUIDs (`location_id` / `service_id` / optional `staff_id`) for funnel prefill only and never creates an appointment by itself.
4. Rate-limited per IP (`public_catalog`, `public_booking_availability`, `public_booking_write`).
5. Availability is always computed server-side via the existing slot engine and is **never** cached. Catalog responses may send `Cache-Control: public, max-age=60` (short TTL for mutable price/duration). Current backend cache is LocMem — not shared across workers; production should use Redis for throttle/cache backends.
6. Public create reuses `booking.services.create_appointment` (source `ONLINE`). Concurrent same-slot creates return one `201` and one `409` (`SLOT_UNAVAILABLE`).
7. Optional `Idempotency-Key` on create: same key + same payload replays the original `201` body (including the original `manage_token`); same key + different payload → `409` `IDEMPOTENCY_CONFLICT`.
8. Machine-readable `code` may appear on public booking errors (e.g. `INVALID_LOCATION`, `INVALID_SERVICE`, `INVALID_STAFF`, `SLOT_UNAVAILABLE`, `BOOKING_NOT_FOUND`, `CANCELLATION_NOT_ALLOWED`, `IDEMPOTENCY_CONFLICT`).
9. Manage GET returns customer-safe fields only (`public_reference`, status, location name/slug, service name/duration, staff display name, starts/ends, customer display name, `can_cancel`). No phone/email, no internal IDs.
10. Manage cancel uses `booking.services.cancel_appointment`. Already-cancelled → `200` with a safe message (no second side effect). Completed / no-show → `CANCELLATION_NOT_ALLOWED`. Invalid/expired/revoked token → `404` `BOOKING_NOT_FOUND` (same wording as missing).
11. **QuickCard** public GET (`/public/quickcards/{slug}/` and `/public/q/{slug}/`) returns only a published card whose business and location are active. Response reuses public catalog pricing and staff. `actions.booking_url` and `booking.booking_path` are `/book/{location.slug}?source=quickcard&ref={quickcard.slug}`. `ref` is the public card slug, not an organization, business, customer, or appointment id. `actions.whatsapp_url`, `call_url`, `directions_url`, and `review_url` are null unless a safe public value exists. Directions prefer the launch profile `google_business_url`; the review link is only `google_review_url`. `reviews` is null until a real rating is stored. No organization id, credentials, customers, or audit fields. SEO title, description, canonical path, and optional image are in `seo`. Structured data is LocalBusiness without an invented aggregate rating. CTA `data-cta` values post to the event endpoint. There is no visitor id. IP is used only by the `public_quickcard_events` throttle (`60/min`) and is not stored. Owner GET `/api/v1/businesses/{business_id}/quickcard/analytics/` returns view and click totals plus `bookings` and `booking_conversion_rate` for the business over `date_from`/`date_to` (default last 30 days). `bookings` counts appointments created in that window with `acquisition_source=QUICKCARD` whose reference is a QuickCard of this business, including soft-deleted cards. `booking_conversion_rate` is those bookings divided by Book Now clicks (`cta_clicks.book`) times 100, rounded to one decimal, or `null` when Book Now clicks are 0. It is not a views-to-booking rate and is not capped at 100. Optional `location_id` returns the same shape for one location. That id is resolved server-side for the current organization and business. A card soft-deleted later still counts when its location matches. Omitting `location_id` keeps the business total. The owner UI sends inclusive UTC calendar dates as `date_from` and `date_to`: last 7, 30, or 90 days, or a custom range. Last 30 days is the default. A custom range is sent only when both dates are present and the start is on or before the end. Date-only values are UTC day bounds in Django (`TIME_ZONE` is UTC). Event rows use `occurred_at`; attributed bookings use `created_at`. OWNER and MANAGER may read it. STAFF is 403. Another organization is 404. The response is not a list of events and does not include revenue. Public appointment responses omit `acquisition_source` and `acquisition_reference`.

### Webhooks

Provider callbacks live under `/api/v1/webhooks/<provider>/`, are unauthenticated in the bearer sense, verify the provider signature before any processing, are idempotent by provider event id, and return `200` quickly.

**WhatsApp (Meta Cloud API)** — `GET|POST /api/v1/webhooks/whatsapp/`

- `GET`: Meta subscription verification (`hub.mode`, `hub.verify_token`, `hub.challenge`). Challenge returned only when verify token matches `META_WHATSAPP_VERIFY_TOKEN`.
- `POST`: Requires `X-Hub-Signature-256` HMAC-SHA256 of the **raw body** using `META_WHATSAPP_APP_SECRET`. Invalid/missing signature → `403`.
- Status callbacks (`sent` / `delivered` / `read` / `failed`) update `NotificationDelivery` by `provider_message_id` (`wamid…`) when that row exists. Otherwise the same callback may update `messaging.WhatsAppMessage` only when `metadata.phone_number_id` matches that message's business `WhatsAppAccount`. Payload business ids are ignored. Unknown IDs are ignored. Duplicate status events are idempotent (`WhatsAppWebhookEvent`). Appointment rows are never modified by webhooks.
- Public booking APIs remain unchanged and do not expose notification/provider internals.

**WhatsApp appointment reminders (ops, not a public API):** `python manage.py send_due_reminders` invokes `booking.reminders.process_due_reminders`. Sends transactional `REMINDER_24H` / `REMINDER_1H` WhatsApp templates for eligible CONFIRMED appointments inside the configured UTC due window (+ lateness). Does not expose reminder state on public booking responses. Covered by `booking/tests/test_reminders.py`.

---

## 10. Current Endpoint Reference

| Method | Path | Auth | Tenant context | Notes |
|---|---|---|---|---|
| `POST` | `/api/v1/auth/register/` | Public | Creates one | `201`; returns user, organization, membership, tokens |
| `POST` | `/api/v1/auth/login/` | Public | Resolved | `200`; `401` on bad credentials |
| `POST` | `/api/v1/auth/refresh/` | Public | — | `200`; returns `access` |
| `GET` | `/api/v1/auth/me/` | Bearer | Optional | Organization/membership may be `null` |
| `GET` | `/api/v1/protected/example/` | Bearer | **Required** | Demonstrates server-side tenant resolution |
| `GET` | `/api/v1/organization/` | Bearer | **Required** | Current organization only |
| `GET` | `/api/v1/organization/members/` | Bearer | **Required** | Members of the current organization; unpaginated |
| `GET` | `/api/v1/businesses/` | Bearer | **Required** | Paginated; soft-deleted excluded |
| `POST` | `/api/v1/businesses/` | Bearer + OWNER | **Required** | Organization derived server-side |
| `GET` | `/api/v1/businesses/{id}/` | Bearer | **Required** | Cross-tenant → `404` |
| `GET` | `/api/v1/businesses/{id}/setup/` | Bearer + OWNER/MANAGER | **Required** | Setup readiness (`ready`, `progress`, `steps`, `blocking_reasons`); optional `?location_id=` |
| `GET` | `/api/v1/businesses/{id}/dashboard/` | Bearer + OWNER/MANAGER | **Required** | Today/upcoming/regular counts + today’s appointments + `launch` summary; optional `?location_id=`; no manage tokens |
| `GET` | `/api/v1/businesses/{id}/launch-profile/` | Bearer + OWNER/MANAGER | **Required** | Launch readiness + profile; optional `?location_id=`; auto-creates profile with subdomain from location slug |
| `POST` | `/api/v1/businesses/{id}/launch-profile/` | Bearer + OWNER/MANAGER | **Required** | Create/ensure profile; body may include `location_id`, `template_key`, domain/Google/website/launch fields |
| `PATCH` | `/api/v1/businesses/{id}/launch-profile/` | Bearer + OWNER/MANAGER | **Required** | Update launch config; `website_status=PUBLISHED` / `launch_status=LIVE` rejected until ready; no secrets |
| `GET` | `/api/v1/public/sites/{slug}/` | Public | — | Salon website payload by location slug or launch subdomain; unpublished → `404`; no PII/secrets |
| `GET` | `/api/v1/businesses/{id}/website/preview/` | Bearer + OWNER/MANAGER | **Required** | Same payload as public site with `preview: true` (skips publish gate); optional `?location_id=` |
| `GET` | `/api/v1/businesses/{id}/website/` | Bearer + OWNER/MANAGER | **Required** | Website management status (`website_status`, `domain_status`, `subdomain`, `public_url`); optional `?location_id=` |
| `POST` | `/api/v1/businesses/{id}/website/publish/` | Bearer + OWNER/MANAGER | **Required** | Launch-ready check + provision subdomain + publish; returns `public_url`; optional `?location_id=` |
| `POST` | `/api/v1/businesses/{id}/website/unpublish/` | Bearer + OWNER/MANAGER | **Required** | Hides public site (`UNPUBLISHED`); keeps subdomain reserved; optional `?location_id=` |
| `GET` | `/api/v1/businesses/{business_id}/locations/{location_id}/google/` | Bearer + OWNER/MANAGER | **Required** | Connection/mapping/sync status + canonical URLs; **never** tokens |
| `POST` | `/api/v1/businesses/{business_id}/locations/{location_id}/google/` | Bearer + OWNER | **Required** | Start connect: `mock` + `GOOGLE_MOCK_DIRECT_CONNECT` → direct mock connect; otherwise `{ authorization_url }` |
| `GET` | `/api/v1/businesses/{business_id}/locations/{location_id}/google/accounts/` | Bearer + OWNER/MANAGER | **Required** | List GBP accounts for the connected Google user; auto-selects when exactly one account |
| `POST` | `/api/v1/businesses/{business_id}/locations/{location_id}/google/accounts/` | Bearer + OWNER | **Required** | Explicitly select GBP account (`google_account_name`); clears prior location mapping |
| `GET` | `/api/v1/businesses/{business_id}/locations/{location_id}/google/locations/` | Bearer + OWNER/MANAGER | **Required** | List GBP locations for selected/account_name query; safe fields only (id, title, address, phone) |
| `POST` | `/api/v1/businesses/{business_id}/locations/{location_id}/google/select-location/` | Bearer + OWNER | **Required** | Persist BookAnything Location ↔ Google location mapping (`google_location_id`) |
| `GET` | `/api/v1/businesses/google/callback/` | Public (state-bound) | — | OAuth redirect; encrypts tokens; redirects owner UI |
| `POST` | `/api/v1/businesses/{business_id}/locations/{location_id}/google/disconnect/` | Bearer + OWNER | **Required** | Clears tokens + mapping; best-effort revoke |
| `POST` | `/api/v1/businesses/{business_id}/locations/{location_id}/google/sync-url/` | Bearer + OWNER | **Required** | Writes canonical booking URL to mapped Google location `websiteUri` when website `PUBLISHED` |

**Google Business OAuth + mapping rules:** Tenant resolved server-side. Cross-business/cross-tenant → `404`. STAFF → `403` on connect/select/disconnect/sync; MANAGER read-only on GET status/accounts/locations. Scope: `https://www.googleapis.com/auth/business.manage`. One GBP account → auto-selected; multiple → explicit selection. One or many locations → owner must confirm mapping (UI may preselect a single location). OAuth connected ≠ GBP location mapped. Sync does **not** run on website publish. Reviews/posts/messaging/analytics deferred. Booking destination: `{PUBLIC_APP_URL}/book/{location.slug}`.

**Launch readiness rules:** Blocking = booking setup ready (same as `/setup/` ready) + template selected. Domain (BookAnything subdomain) does not block when configured/auto-assigned. Google Business and WhatsApp statuses are informational and do not block. **Publish Website** provisions a unique subdomain (idempotent), sets `website_status=PUBLISHED`, `domain_status=SUBDOMAIN_ACTIVE`, `launch_status=LIVE`, and returns canonical `https://{subdomain}.{BOOKANYTHING_SITE_DOMAIN}`. Unpublish does not delete business data or free the subdomain. STAFF → 403. Cross-business → 404.

**Business WhatsApp (Phase 4.1–4.3):** Tenant resolved server-side from membership. Cross-business/cross-tenant → `404`. STAFF → `403`. MANAGER may GET status, templates, and messages. OWNER may connect, disconnect, and create/update/delete templates. Responses never include `access_token`, ciphertext, or `payload`. Status includes `message_counts` and `reminder_24h` (`ENABLED` or `NOT_CONFIGURED`, plus `upcoming_count`). Message list filters: `appointment`, `purpose`, `message_type`, `status`, `created_after`, `created_before`. Each message adds `customer_name` and `appointment_reference` when present. `POST /api/v1/webhooks/whatsapp/meta/` uses the same signed handler as `/api/v1/webhooks/whatsapp/`. Allowed delivery progression is `SENT` → `DELIVERED` → `READ`. `FAILED` is not overwritten. A connected business schedules `APPOINTMENT_REMINDER_24H` and `APPOINTMENT_REMINDER_1H` when the appointment is confirmed, and one delayed `REVIEW_REQUEST` when it is completed (`WHATSAPP_REVIEW_REQUEST_DELAY_HOURS`, default 3). `POST /api/v1/businesses/{business_id}/whatsapp/templates/sync/` is OWNER-only and stores provider status without replacing local status. `POST .../templates/{id}/submit/` submits through the provider and records `PENDING` from the mock. Inbound text on the existing Meta webhook is stored and not answered. OWNER and MANAGER may `GET /api/v1/businesses/{business_id}/whatsapp/inbound/` (filters: `customer`, `phone`, `message_type`, `processing_status`, `date_from`, `date_to`). STAFF is 403. Phones in that list are masked. Launch profile `google_review_url` is https-only: OWNER may set it, MANAGER may read it, STAFF is 403. Review requests use that field. `google_business_url` is not used as the review link and is not copied. The current Google integration does not supply a review URL.

| Method | Path | Auth | Tenant context | Notes |
|---|---|---|---|---|
| `GET` | `/api/v1/businesses/{business_id}/whatsapp/` | Bearer + OWNER/MANAGER | **Required** | Connection status; no credentials |
| `POST` | `/api/v1/businesses/{business_id}/whatsapp/connect/` | Bearer + OWNER | **Required** | Body: `access_token`, `phone_number_id`, `business_account_id`; token encrypted at rest |
| `POST` | `/api/v1/businesses/{business_id}/whatsapp/disconnect/` | Bearer + OWNER | **Required** | Clears ciphertext; status `DISCONNECTED` |
| `GET` | `/api/v1/businesses/{business_id}/whatsapp/templates/` | Bearer + OWNER/MANAGER | **Required** | Business-scoped templates |
| `POST` | `/api/v1/businesses/{business_id}/whatsapp/templates/` | Bearer + OWNER | **Required** | Duplicate live name+language → `400` |
| `PATCH` | `/api/v1/businesses/{business_id}/whatsapp/templates/{id}/` | Bearer + OWNER | **Required** | Cross-business template → `404` |
| `DELETE` | `/api/v1/businesses/{business_id}/whatsapp/templates/{id}/` | Bearer + OWNER | **Required** | Soft delete |
| `GET` | `/api/v1/businesses/{business_id}/whatsapp/messages/` | Bearer + OWNER/MANAGER | **Required** | Paginated history. Filters: `appointment`, `purpose`, `message_type`, `status`, `created_after`, `created_before`. No payload, no tokens |
| `GET` | `/api/v1/businesses/{business_id}/whatsapp/inbound/` | Bearer + OWNER/MANAGER | **Required** | Paginated inbound texts. Masked phone. No payload, no tokens. STAFF → 403 |
| `POST` | `/api/v1/webhooks/whatsapp/meta/` | Meta signature | — | Alias of the platform webhook. Resolves the business from `phone_number_id` and the provider message id |
| `PATCH` | `/api/v1/businesses/{id}/` | Bearer + OWNER | **Required** | Cross-tenant → `404` |
| `DELETE` | `/api/v1/businesses/{id}/` | Bearer + OWNER | **Required** | Soft delete; cross-tenant → `404` |
| `GET` | `/api/v1/businesses/{business_id}/locations/` | Bearer | **Required** | Paginated; business must belong to tenant |
| `POST` | `/api/v1/businesses/{business_id}/locations/` | Bearer + OWNER | **Required** | Denormalized `organization_id` set server-side |
| `GET` | `/api/v1/businesses/{business_id}/locations/{id}/` | Bearer | **Required** | Cross-tenant → `404` |
| `PATCH` | `/api/v1/businesses/{business_id}/locations/{id}/` | Bearer + OWNER | **Required** | Cross-tenant → `404` |
| `DELETE` | `/api/v1/businesses/{business_id}/locations/{id}/` | Bearer + OWNER | **Required** | Soft delete; cross-tenant → `404` |
| `GET` | `/api/v1/businesses/{business_id}/locations/{location_id}/quickcard/` | Bearer | **Required** | Managed QuickCard for the location; missing → `404` |
| `POST` | `/api/v1/businesses/{business_id}/locations/{location_id}/quickcard/` | Bearer + OWNER/MANAGER | **Required** | Create; slug unique globally among live cards; immutable after create |
| `PATCH` | `/api/v1/businesses/{business_id}/locations/{location_id}/quickcard/` | Bearer + OWNER/MANAGER | **Required** | Update display fields (not slug) |
| `POST` | `/api/v1/businesses/{business_id}/locations/{location_id}/quickcard/publish/` | Bearer + OWNER/MANAGER | **Required** | Sets `is_published` |
| `POST` | `/api/v1/businesses/{business_id}/locations/{location_id}/quickcard/unpublish/` | Bearer + OWNER/MANAGER | **Required** | Clears published flag |
| `GET` | `/api/v1/businesses/{business_id}/locations/{location_id}/quickcard/qr/` | Bearer + OWNER/MANAGER | **Required** | PNG QR encoding only the public `/q/{slug}` URL |
| `GET` | `/api/v1/businesses/{business_id}/quickcard/analytics/` | Bearer + OWNER/MANAGER | **Required** | Views, CTA clicks, attributed `bookings`, and `booking_conversion_rate`. Default last 30 days for the whole business. Optional `location_id` limits events and bookings to QuickCards for that location. The location must belong to this business and organization; a missing, foreign, or deleted location is `404`. Clicks use `QuickCardEvent.occurred_at`. Bookings use appointment `created_at` and QuickCard ids from `QuickCard.all_objects`, including soft-deleted cards. Rate is bookings / Book Now clicks × 100, one decimal, or `null` when Book Now clicks are 0. No raw events, unique visitors, or revenue |
| `GET` | `/api/v1/businesses/{business_id}/service-categories/` | Bearer | **Required** | Paginated |
| `POST` | `/api/v1/businesses/{business_id}/service-categories/` | Bearer + OWNER | **Required** | |
| `GET` | `/api/v1/businesses/{business_id}/service-categories/{id}/` | Bearer | **Required** | Cross-tenant → `404` |
| `PATCH` | `/api/v1/businesses/{business_id}/service-categories/{id}/` | Bearer + OWNER | **Required** | |
| `DELETE` | `/api/v1/businesses/{business_id}/service-categories/{id}/` | Bearer + OWNER | **Required** | Soft delete |
| `GET` | `/api/v1/businesses/{business_id}/services/` | Bearer | **Required** | Paginated; filters: `category_id`, `is_active`, `is_bookable_online`, `search` |
| `POST` | `/api/v1/businesses/{business_id}/services/` | Bearer + OWNER | **Required** | Category must belong to same business |
| `GET` | `/api/v1/businesses/{business_id}/services/{id}/` | Bearer | **Required** | |
| `PATCH` | `/api/v1/businesses/{business_id}/services/{id}/` | Bearer + OWNER | **Required** | |
| `DELETE` | `/api/v1/businesses/{business_id}/services/{id}/` | Bearer + OWNER | **Required** | Soft delete; clears ServiceLocations |
| `GET` | `/api/v1/businesses/{business_id}/services/{service_id}/service-locations/` | Bearer | **Required** | Paginated |
| `POST` | `/api/v1/businesses/{business_id}/services/{service_id}/service-locations/` | Bearer + OWNER | **Required** | Body: `location_id`, optional overrides |
| `GET` | `/api/v1/businesses/{business_id}/services/{service_id}/service-locations/{id}/` | Bearer | **Required** | |
| `PATCH` | `/api/v1/businesses/{business_id}/services/{service_id}/service-locations/{id}/` | Bearer + OWNER | **Required** | Override fields only |
| `DELETE` | `/api/v1/businesses/{business_id}/services/{service_id}/service-locations/{id}/` | Bearer + OWNER | **Required** | Hard delete junction |
| `GET` | `/api/v1/businesses/{business_id}/staff/` | Bearer | **Required** | Paginated |
| `POST` | `/api/v1/businesses/{business_id}/staff/` | Bearer + OWNER/MANAGER | **Required** | Requires `location_id` |
| `GET` | `/api/v1/businesses/{business_id}/staff/{id}/` | Bearer | **Required** | Cross-tenant → `404` |
| `PATCH` | `/api/v1/businesses/{business_id}/staff/{id}/` | Bearer + OWNER/MANAGER | **Required** | |
| `DELETE` | `/api/v1/businesses/{business_id}/staff/{id}/` | Bearer + OWNER/MANAGER | **Required** | Soft delete; clears StaffServices |
| `GET` | `/api/v1/businesses/{business_id}/staff/{staff_id}/services/` | Bearer | **Required** | Capability assignments |
| `POST` | `/api/v1/businesses/{business_id}/staff/{staff_id}/services/` | Bearer + OWNER/MANAGER | **Required** | Body: `service_id`, optional overrides |
| `GET` | `/api/v1/businesses/{business_id}/staff/{staff_id}/services/{id}/` | Bearer | **Required** | |
| `PATCH` | `/api/v1/businesses/{business_id}/staff/{staff_id}/services/{id}/` | Bearer + OWNER/MANAGER | **Required** | |
| `DELETE` | `/api/v1/businesses/{business_id}/staff/{staff_id}/services/{id}/` | Bearer + OWNER/MANAGER | **Required** | Hard delete junction |
| `GET` | `/api/v1/businesses/{business_id}/staff/{staff_id}/availability/` | Bearer | **Required** | Paginated; order weekday, starts_at |
| `POST` | `/api/v1/businesses/{business_id}/staff/{staff_id}/availability/` | Bearer + OWNER/MANAGER | **Required** | Body: `location_id`, `weekday`, `starts_at`, `ends_at` |
| `GET` | `/api/v1/businesses/{business_id}/staff/{staff_id}/availability/{id}/` | Bearer | **Required** | Cross-tenant → `404` |
| `PATCH` | `/api/v1/businesses/{business_id}/staff/{staff_id}/availability/{id}/` | Bearer + OWNER/MANAGER | **Required** | |
| `DELETE` | `/api/v1/businesses/{business_id}/staff/{staff_id}/availability/{id}/` | Bearer + OWNER/MANAGER | **Required** | Hard delete |
| `GET` | `/api/v1/businesses/{business_id}/staff/{staff_id}/time-off/` | Bearer | **Required** | Paginated; order `-starts_at` |
| `POST` | `/api/v1/businesses/{business_id}/staff/{staff_id}/time-off/` | Bearer + OWNER/MANAGER | **Required** | Body: `starts_at`, `ends_at`, optional `reason` |
| `GET` | `/api/v1/businesses/{business_id}/staff/{staff_id}/time-off/{id}/` | Bearer | **Required** | Cross-tenant → `404` |
| `PATCH` | `/api/v1/businesses/{business_id}/staff/{staff_id}/time-off/{id}/` | Bearer + OWNER/MANAGER | **Required** | |
| `DELETE` | `/api/v1/businesses/{business_id}/staff/{staff_id}/time-off/{id}/` | Bearer + OWNER/MANAGER | **Required** | Hard delete |

**Scheduling notes:** Availability times are local wall-clock in `Location.timezone`. Time-off datetimes are timezone-aware. Overlapping availability for the same staff+location+weekday is rejected (`400`). Covered by tests in `staff/tests/`.

| `GET` | `/api/v1/businesses/{business_id}/customers/` | Bearer | **Required** | Paginated; `search` on name/phone/email; filter `tag_id`; optional `segment` (`NO_VISITS`/`NEW`/`RETURNING`/`DUE_FOR_RETURN`/`INACTIVE`); ordering |
| `POST` | `/api/v1/businesses/{business_id}/customers/` | Bearer + OWNER/MANAGER | **Required** | Phone E.164; unique live phone per business |
| `GET` | `/api/v1/businesses/{business_id}/customers/{id}/` | Bearer | **Required** | Cross-tenant → `404` |
| `GET` | `/api/v1/businesses/{business_id}/customers/{customer_id}/retention-summary/` | Bearer | **Required** | Factual retention profile including `segment`, `return_after_days`, `inactive_after_days`, visit counters, recent visits, histories. No phone/email. Cross-tenant → `404` |
| `GET` | `/api/v1/businesses/{business_id}/retention-settings/` | Bearer + OWNER/MANAGER | **Required** | Thresholds + `due_message_delay_hours` + `enabled`. STAFF → `403`. Cross-tenant → `404` |
| `PATCH` | `/api/v1/businesses/{business_id}/retention-settings/` | Bearer + OWNER | **Required** | `return_after_days` ≥ 1; `inactive_after_days` > `return_after_days`; `due_message_delay_hours` ≥ 1; `enabled`. MANAGER/STAFF → `403` |
| `PATCH` | `/api/v1/businesses/{business_id}/customers/{id}/` | Bearer + OWNER/MANAGER | **Required** | Visit counters not writable |
| `DELETE` | `/api/v1/businesses/{business_id}/customers/{id}/` | Bearer + OWNER/MANAGER | **Required** | Soft delete; clears tag assignments |
| `GET` | `/api/v1/businesses/{business_id}/customer-tags/` | Bearer | **Required** | Paginated; `search` on name |
| `POST` | `/api/v1/businesses/{business_id}/customer-tags/` | Bearer + OWNER/MANAGER | **Required** | Unique name per business |
| `GET` | `/api/v1/businesses/{business_id}/customer-tags/{id}/` | Bearer | **Required** | |
| `PATCH` | `/api/v1/businesses/{business_id}/customer-tags/{id}/` | Bearer + OWNER/MANAGER | **Required** | |
| `DELETE` | `/api/v1/businesses/{business_id}/customer-tags/{id}/` | Bearer + OWNER/MANAGER | **Required** | Hard delete; cascades assignments |
| `GET` | `/api/v1/businesses/{business_id}/customers/{customer_id}/tags/` | Bearer | **Required** | Paginated assignments |
| `POST` | `/api/v1/businesses/{business_id}/customers/{customer_id}/tags/` | Bearer + OWNER/MANAGER | **Required** | Body: `tag_id`; same-business only |
| `GET` | `/api/v1/businesses/{business_id}/customers/{customer_id}/tags/{id}/` | Bearer | **Required** | |
| `DELETE` | `/api/v1/businesses/{business_id}/customers/{customer_id}/tags/{id}/` | Bearer + OWNER/MANAGER | **Required** | Hard delete assignment |

**CRM notes:** Customers are business-scoped, not location-scoped, and are not exposed on public APIs. STAFF may read customers; writes require OWNER/MANAGER. A visit is a live `Appointment` with `status=COMPLETED`. Retention summary includes deterministic segments and optional `automation` status for the current visit cycle (`PENDING`/`QUEUED`/`SENT`/`SKIPPED`/`CANCELLED`/`FAILED`) without internal IDs. **Due-for-Return automation** (when `CustomerRetentionSettings.enabled`) schedules a WhatsApp template message for `last_visit_at + return_after_days + due_message_delay_hours`, idempotent per `retention:due:{customer_id}:{last_visit_at}`. Send requires opt-in, connected WhatsApp, and an approved English `RETENTION_DUE_RETURN` template. The template `booking_url` includes `?source=retention&ref={public_reference}`. Public booking validates org/business/location/customer match after phone matching; success stores `acquisition_source=RETENTION` and the message UUID. Invalid attribution never blocks booking. Eligibility is revalidated before send. Retention automation is deterministic and rule-based — not churn prediction. **This phase establishes attribution only; retention conversion analytics comes later.** No inactive/win-back journeys in this phase. Management commands: `reconcile_customer_visits`, `process_due_retention_messages`. Covered by tests in `customers/tests/` and `booking/tests/test_retention_attribution.py`.

| `GET` | `/api/v1/businesses/{business_id}/locations/{location_id}/availability/` | Bearer | **Required** | Query: `service_id`, `date`, optional `staff_id`; 15-min grid; returns timezone + slots |
| `GET` | `/api/v1/businesses/{business_id}/appointments/` | Bearer | **Required** | Paginated; filters: `starts_at_after/before`, `location_id`, `staff_id`, `customer_id`, `service_id`, `status` |
| `POST` | `/api/v1/businesses/{business_id}/appointments/` | Bearer + OWNER/MANAGER | **Required** | Body: `location_id`, `customer_id`, `service_id`, `starts_at`, optional `staff_id`/`status`/`source`/`notes` |
| `GET` | `/api/v1/businesses/{business_id}/appointments/{id}/` | Bearer | **Required** | Cross-tenant → `404` |
| `PATCH` | `/api/v1/businesses/{business_id}/appointments/{id}/` | Bearer + OWNER/MANAGER | **Required** | Status transitions / reschedule `starts_at` / notes |
| `POST` | `/api/v1/businesses/{business_id}/appointments/{id}/cancel/` | Bearer + OWNER/MANAGER | **Required** | Sets `CANCELLED` + metadata |
| `GET` | `/api/v1/businesses/{business_id}/booking-plans/` | Bearer | **Required** | Minimal list of active/paused Book Regularly plans (no internal IDs) |

**Booking notes:** Slot engine is server-side only. Occupancy includes buffers; conflicts return `409`. Any-staff resolves to one staff (lowest UUID among free). PostgreSQL exclusion constraint required for production concurrency. Covered by tests in `booking/tests/` (including Postgres concurrency).

| `GET` | `/api/v1/public/booking/availability/` | Public | — | Query: `location_id`, `service_id`, `date`, optional `staff_id`. Requires active location, active online-bookable service offered at that location. Response: location/service summaries + local/UTC slots. |
| `POST` | `/api/v1/public/booking/appointments/` | Public | — | Body: `location_id`, `service_id`, `start`, `customer` `{name, phone, email?}`, optional `staff_id` (`null` = any staff). Optional `attribution_source` / `attribution_ref`: `quickcard`+slug or `retention`+opaque retention `public_reference`. Server validates and may set `acquisition_source`/`acquisition_reference`; invalid refs still book with both null. Phone: E.164 or 10-digit Indian mobile. Optional header `Idempotency-Key`. `201` includes one-time `manage_token`, `payment_status`, `payment_required`, `payable_amount`. Does not include attribution internals. |
| `POST` | `/api/v1/public/booking/appointments/{public_reference}/payment-order/` | Public | — | Body: `idempotency_key`. Creates/reuses `PaymentOrder`; amount from appointment snapshots (never client). Returns `payment_order_id`, `provider`, `provider_order_id`, `amount` (minor units), `currency`, `key_id` (public only). Throttled. |
| `POST` | `/api/v1/public/booking/appointments/{public_reference}/payment/verify/` | Public | — | Body: `razorpay_order_id`, `razorpay_payment_id`, `razorpay_signature`. Server verifies signature + fetches provider payment; updates Payment + `payment_status`. Idempotent. Frontend callback alone is never trusted. |
| `GET` | `/api/v1/public/booking/appointments/{public_reference}/payment/` | Public | — | Sanitized payment state (`status`, `amount`, `currency`, `paid_at`, `payment_reference`). |
| `POST` | `/api/v1/webhooks/payments/razorpay/` | Public | — | Raw body + `X-Razorpay-Signature`. Verified; idempotent by provider event id. |
| `POST` | `/api/v1/businesses/{business_id}/payments/{payment_id}/refunds/` | Bearer + OWNER | **Required** | Body: `amount`, `reason`, `idempotency_key`. Partial/full refunds. MANAGER/STAFF → 403. Cross-tenant → 404. |
| `GET` | `/api/v1/public/booking/manage/{token}/` | Public | — | Secure manage payload; invalid/expired token → `404` `BOOKING_NOT_FOUND`. No internal IDs / phone / email. |
| `POST` | `/api/v1/public/booking/manage/{token}/cancel/` | Public | — | Body: optional `reason`. Uses lifecycle cancel. Already cancelled → `200` safe message. Terminal states → `CANCELLATION_NOT_ALLOWED`. |
| `GET` | `/api/v1/public/booking/history/{token}/` | Public | — | Guest history for the token’s customer. Query: `category=upcoming\|past\|cancelled` (default `upcoming`), `limit` (max `MAX_PUBLIC_BOOKING_HISTORY_PAGE_SIZE`, default 50), `offset`. No phone lookup. |
| `GET` | `/api/v1/public/booking/history/{token}/book-again/{public_reference}/` | Public | — | Prefill for Book Again within the same customer scope. Returns bridge UUIDs when the current service is bookable; does not create an appointment. Cross-customer reference → `404`. |
| `GET` | `/api/v1/public/booking/appointments/{public_reference}/` | Public | — | Customer-safe booking summary. Soft-deleted → `404`. |
| `POST` | `/api/v1/public/booking/appointments/{public_reference}/cancel/` | Public | — | Body: optional `reason`. Reuses lifecycle cancel; completed/cancelled/no-show → `CANCELLATION_NOT_ALLOWED`. Prefer manage-token cancel for customer links. |

**Public booking examples**

Availability:

`GET /api/v1/public/booking/availability/?location_id=<uuid>&service_id=<uuid>&date=2026-09-10`

```json
{
  "location": {"id": "...", "name": "Downtown", "timezone": "Asia/Kolkata"},
  "service": {"id": "...", "name": "Haircut", "duration_minutes": 60, "price": "499.00", "currency": "INR"},
  "date": "2026-09-10",
  "slot_grid_minutes": 15,
  "slots": [
    {
      "start": "2026-09-10T10:00:00+05:30",
      "end": "2026-09-10T11:00:00+05:30",
      "starts_at": "2026-09-10T04:30:00Z",
      "ends_at": "2026-09-10T05:30:00Z",
      "staff_id": null,
      "staff_options": ["..."]
    }
  ]
}
```

Create (optional `Idempotency-Key: 8f9a2d7c-example`):

```json
{
  "location_id": "...",
  "service_id": "...",
  "staff_id": null,
  "start": "2026-09-10T18:00:00+05:30",
  "customer": {"name": "Rahul", "phone": "9876543210", "email": "rahul@example.com"}
}
```

```json
{
  "public_reference": "BK-7F82K9",
  "status": "CONFIRMED",
  "service": "Haircut",
  "location": "Downtown",
  "staff": "Priya",
  "start": "2026-09-10T18:00:00+05:30",
  "end": "2026-09-10T19:00:00+05:30",
  "total": "499.00",
  "currency": "INR",
  "manage_token": "<opaque-url-safe-token-shown-once>"
}
```

Manage booking:

`GET /api/v1/public/booking/manage/{token}/`

```json
{
  "public_reference": "BK-7F82K9",
  "status": "CONFIRMED",
  "location": {"name": "Downtown", "slug": "downtown"},
  "service": {"name": "Haircut", "duration_minutes": 60},
  "staff": {"name": "Priya"},
  "starts_at": "2026-09-10T18:00:00+05:30",
  "ends_at": "2026-09-10T19:00:00+05:30",
  "customer": {"name": "Rahul"},
  "can_cancel": true
}
```

`POST /api/v1/public/booking/manage/{token}/cancel/` body optional `{ "reason": "…" }` →

```json
{
  "public_reference": "BK-7F82K9",
  "status": "CANCELLED",
  "message": "Your booking has been cancelled."
}
```

**Public booking notes:** Unauthenticated (`AllowAny`) with IP throttles. Reuses existing slot engine + `create_appointment` / `cancel_appointment`. Customer matched/created by phone within the location's business. Manage tokens are SHA-256 hashed at rest; raw tokens are never logged as dedicated fields. Booking/cancellation emit domain events after commit → `NotificationService` → `NotificationDelivery` (frozen `payload_snapshot`) → `WhatsAppProvider` (`mock` or Meta Cloud API templates). Automated 24h/1h reminders use the same stack via `send_due_reminders` / `process_due_reminders` and are not reflected in public API payloads. Public responses do **not** expose notification status, provider IDs, or errors. Transactional WhatsApp confirmations/cancellations/reminders are separate from future marketing opt-in (`whatsapp_opt_in`). Covered by `booking/tests/test_public_booking_api.py`, `booking/tests/test_manage_booking_api.py`, `booking/tests/test_whatsapp_notifications.py`, `booking/tests/test_meta_whatsapp_provider.py`, `booking/tests/test_whatsapp_webhooks.py`, and `booking/tests/test_reminders.py`.

**Public booking UI:** Next.js funnel at `/book/{locationSlug}` (optional `?service=&staff=` prefill for Book Again, optional `?source=quickcard&ref=` held in funnel state) with success page manage link, `/book/manage/{token}`, and `/book/manage/{token}/history` (see `frontend/`). Consumes the public location/catalog/staff/booking endpoints above. Create always sends `Idempotency-Key`; `409` returns the customer to slot selection. Book Again never auto-creates; it prefills the existing funnel then uses `POST /public/booking/appointments/`. A QuickCard `ref` is sent again with the create body and is trusted only after the server matches the slug to that location.

| `GET` | `/api/v1/public/locations/{slug}/` | Public | — | Location + business-safe fields; `id` UUID for booking bridge; inactive/deleted/ambiguous slug → `404` |
| `GET` | `/api/v1/public/locations/{slug}/services/` | Public | — | Paginated; active + `is_bookable_online` + offered via `ServiceLocation`; effective duration/price/currency |
| `GET` | `/api/v1/public/locations/{slug}/services/{service_identifier}/` | Public | — | Detail by service slug or UUID within the location |
| `GET` | `/api/v1/public/locations/{slug}/categories/` | Public | — | Paginated; categories with ≥1 qualifying public service at the location |
| `GET` | `/api/v1/public/locations/{slug}/staff/` | Public | — | Paginated; active + bookable staff with availability at the location and ≥1 online-bookable service offered there. Nested `services` use effective pricing (incl. staff overrides). Ordered by `display_name`. |

**Public catalog notes:** Short `Cache-Control: public, max-age=60`. Does not cache availability/booking. No location enumeration. Covered by `locations/tests/test_public_catalog_api.py` and `locations/tests/test_public_staff_api.py`.

**Public staff eligibility:** `StaffProfile` live + `is_active` + `is_bookable`; has `StaffAvailability` for the location; has ≥1 `StaffService` whose service is active, `is_bookable_online`, and assigned via `ServiceLocation` to that location. Does not expose user/login, org/business IDs, availability rows, or time-off.

Any `tenant_id` or `organization_id` passed to these endpoints is ignored for ownership. Covered by tests in `organizations/tests/`, `businesses/tests/`, and `locations/tests/`.

---

## 11. Rules for New Endpoints

1. Place it under `/api/v1/` in the owning app's `urls.py`; register that module in `api/v1/urls.py`.
2. Follow the naming conventions in §2.
3. Default to authenticated. Making an endpoint public requires adding it to §9.
4. Resolve tenant context server-side; never read a tenant identifier from the client.
5. Scope every tenant-owned query to the resolved organization.
6. Keep business logic in the service layer — the view calls one service.
7. Validate input with a serializer; validate business rules in the service.
8. Paginate every collection.
9. Return `404` for another tenant's record.
10. Add tests, including a cross-tenant isolation test.
11. Update this document in the same change.
