# DATABASE — Schema and Data Conventions

PostgreSQL, single logical database, shared schema, row-level multi-tenancy.

Sections marked **Current** exist in code today. Sections marked **Target** are approved but not yet implemented. Do not implement target entities without an explicit task.

---

## 1. Global Conventions

### 1.1 Primary Keys

All application tables use `UUID` primary keys, `default=uuid.uuid4`, `editable=False`.

Rationale: identifiers appear in public URLs (booking links, QuickCards, QR codes); sequential integers leak volume and enable enumeration.

Django's own tables (`auth_*`, `django_*`) keep their default integer keys. `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"` applies only to models that do not declare an explicit primary key.

### 1.2 Timestamps

Every application table carries:

| Field | Type | Behavior |
|---|---|---|
| `created_at` | `timestamptz` | `auto_now_add=True`, immutable |
| `updated_at` | `timestamptz` | `auto_now=True`, updated on every save |

All timestamps are stored in UTC (`USE_TZ = True`, `TIME_ZONE = "UTC"`). Local business time is derived from `Location.timezone`, never from the server timezone.

**Current:** `Organization` and `OrganizationMember` have both. `User` has `date_joined` and `last_login` only — this is a documented exception inherited from `AbstractBaseUser`.

### 1.3 Soft Deletion (Target)

The platform uses **soft deletion for business-meaningful records** and hard deletion for junction/ephemeral rows.

| Field | Type | Meaning |
|---|---|---|
| `deleted_at` | `timestamptz`, nullable, indexed | `NULL` = live; timestamp = deleted |
| `deleted_by` | FK → `User`, nullable, `SET_NULL` | Actor who deleted |

Rules:

1. Soft-deleted rows are excluded by the default manager. An `all_objects` manager exposes them for admin and recovery.
2. Uniqueness that must survive deletion uses a **partial unique index** with `condition=Q(deleted_at__isnull=True)`.
3. Soft-deleted parents cascade logically, not physically: children are filtered out through the parent's state.
4. Records referenced by financial or legal history (appointments, payments, invoices) are **never** hard deleted.
5. Hard deletion is permitted only for: session rows, cache rows, expired tokens, and explicit GDPR-style erasure requests.
6. Status is not deletion. `is_active` means "currently usable"; `deleted_at` means "removed". Both may exist on one model and mean different things.

**Soft delete applies to:** Organization (target), Business, Location, Service, ServiceCategory, StaffProfile, Customer, Appointment, BookingPlan, Template, QuickCard, QRCode, Review, AutomationRule.

**Soft delete does not apply to:** OrganizationMember (deactivated via `is_active`), ServiceLocation / StaffService / StaffAvailability / StaffTimeOff / CustomerTag / CustomerTagAssignment (junctions or hard-delete labels), audit logs, webhook/event logs, analytics facts.

**Current:** soft deletion is implemented for `Business`, `Location`, `ServiceCategory`, `Service`, `StaffProfile`, `Customer`, and `Appointment` via `core.models.SoftDeleteModel`. Organization soft delete remains target.

### 1.4 Audit Requirements

**Row-level audit (Current for Business/Location).** Business-owned tables carry:

| Field | Type | Notes |
|---|---|---|
| `created_by` | FK → `User`, nullable, `SET_NULL` | Null for system/automated creation |
| `updated_by` | FK → `User`, nullable, `SET_NULL` | Last actor |

`deleted_by` is set on soft delete. Append-only `AuditLog` remains **target**.

**Event-level audit (Target).** An append-only `AuditLog` table records security- and money-relevant events. It is never updated or deleted. Events required:

- Authentication: login success, login failure, logout, password change, token refresh anomaly
- Membership: member invited, added, removed, role changed, deactivated
- Tenancy: organization created, updated, deactivated
- Structure: business or location created, updated, deleted
- Money: subscription created/changed/cancelled, payment succeeded/failed, refund
- Data: customer export, bulk delete, integration credential change
- Access: cross-tenant access attempt (denied)

Audit entries must never contain passwords, tokens, or full payment instrument data.

**Current:** no event-level audit implementation. Row-level `created_by` / `updated_by` / `deleted_by` exist on Business and Location.

### 1.5 Tenant Ownership

Every tenant-owned table must resolve to exactly one `Organization`.

| Ownership style | When | Mechanism |
|---|---|---|
| Direct | Table is organization-level | `organization_id` FK |
| Denormalized | Table is deep in the hierarchy and queried directly | `organization_id` FK **plus** the natural parent FK |
| Derived | Table is always queried through its parent | Parent FK only |

**Rule:** any table that is queried directly by an API endpoint carries a direct `organization_id`. Denormalized `organization_id` is maintained by the service layer and must never diverge from the parent chain. Reads never use a client-supplied organization identifier — see `docs/ARCHITECTURE.md` §6.

Every tenant-owned table indexes `organization_id`, and composite indexes lead with it.

### 1.6 Naming

- Tables: Django default, `<app>_<model>` lowercase.
- Foreign keys: `<entity>` in Python, `<entity>_id` in SQL.
- Booleans: `is_*` / `has_*`.
- Timestamps: `*_at`.
- Enumerations: `models.TextChoices`, stored as uppercase snake-case strings. No integer enums.
- Money: `DecimalField(max_digits=10, decimal_places=2)` plus a separate ISO-4217 `currency` field. Never `FloatField`.
- Durations: integer minutes.
- Phone numbers: E.164 strings.

### 1.7 Referential Integrity

| Relationship | `on_delete` | Reason |
|---|---|---|
| Child of tenant hierarchy (Business → Organization, Location → Business) | `PROTECT` | Prevent accidental tenant data loss |
| Membership → Organization / User | `CASCADE` | Membership is meaningless without either side |
| Historical record → referenced entity (Appointment → Service) | `PROTECT` | Preserve history |
| Optional pointer (User → active_organization, `*_by` audit fields) | `SET_NULL` | Pointer loss is acceptable |
| True junction rows | `CASCADE` | No independent meaning |

**Current:** `Business.organization` and `Location.business` / `Location.organization` use `PROTECT`. `OrganizationMember` uses `CASCADE` on both sides; `User.active_organization` uses `SET_NULL`.

---

## 2. Entity Relationship Overview

```
                    ┌──────────────┐
                    │     User     │  platform identity
                    └──────┬───────┘
                           │ 1..*
                    ┌──────▼──────────────┐
                    │ OrganizationMember  │  role: OWNER|MANAGER|STAFF
                    └──────┬──────────────┘
                           │ *..1
                    ┌──────▼───────┐
                    │ Organization │  ◄── TENANT ROOT
                    └──────┬───────┘
                           │ 1..*
                    ┌──────▼───────┐
                    │   Business   │  vertical: SALON|SPA|…
                    └──────┬───────┘
                           │ 1..*
                    ┌──────▼───────┐
                    │   Location   │  address, timezone, hours
                    └──────┬───────┘
                           │
       ┌───────────┬───────┴────┬────────────┬─────────────┐
       ▼           ▼            ▼            ▼             ▼
   Service    StaffProfile   Customer   Appointment    QuickCard
       │           │            │            │             │
  ServiceCategory  │       CustomerTag       │           QRCode
                   │                         │
            StaffAvailability          AppointmentItem
            StaffTimeOff
```

---

## 3. Current Entities

### 3.1 `accounts.User`

Platform identity. Email is the username. A user is not tenant-owned; tenancy is expressed through membership.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | `uuid4` |
| `password` | varchar(128) | not null | Django hashed |
| `last_login` | timestamptz | nullable | Django |
| `is_superuser` | boolean | default `false` | **Platform administration** |
| `email` | varchar(254) | **unique**, not null | Lowercased on save; `USERNAME_FIELD` |
| `first_name` | varchar(150) | blank allowed | |
| `last_name` | varchar(150) | blank allowed | |
| `is_active` | boolean | default `true` | Login permitted |
| `is_staff` | boolean | default `false` | Django Admin access |
| `date_joined` | timestamptz | default `now` | |
| `active_organization` | FK → `Organization` | nullable, `SET_NULL` | Last selected tenant; **a hint, not authority** |

**Indexes:** PK; unique index on `email`; index on `active_organization_id` (implicit FK index).
**Unique constraints:** `email`.
**Ordering:** `email`.
**Manager:** `accounts.managers.UserManager` (`create_user`, `create_superuser`; email required and normalized).
**M2M:** `groups` → `auth.Group`, `user_permissions` → `auth.Permission` (Django `PermissionsMixin`).

Notes:

- `is_superuser` / `is_staff` are **platform administration**, deliberately separate from organization roles.
- `active_organization` is a convenience pointer. Authorization always re-verifies an active membership.

### 3.2 `organizations.Organization`

The tenant root and the isolation boundary. All business data resolves to exactly one Organization.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | Tenant identifier |
| `name` | varchar(255) | not null | Display name |
| `slug` | varchar(255) | **unique**, not null | Generated from name; collision-suffixed |
| `is_active` | boolean | default `true` | Inactive tenants fail tenant resolution |
| `created_at` | timestamptz | auto | |
| `updated_at` | timestamptz | auto | |

**Indexes:** PK; unique index on `slug`.
**Unique constraints:** `slug`.
**Ordering:** `name`.
**Tenant ownership:** this **is** the tenant root.
**Target additions:** `deleted_at`, `deleted_by`, `created_by`, `updated_by`; `slug` uniqueness becomes a partial unique index over live rows.

### 3.3 `organizations.OrganizationMember`

Joins a User to an Organization with a role. This table is the authority for tenant access.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `organization` | FK → `Organization` | not null, `CASCADE`, related `members` | Tenant |
| `user` | FK → `User` | not null, `CASCADE`, related `memberships` | |
| `role` | varchar(32) | choices | See below |
| `is_active` | boolean | default `true` | Inactive membership grants no access |
| `created_at` | timestamptz | auto | Determines fallback tenant order |
| `updated_at` | timestamptz | auto | |

**Unique constraints:** `unique_organization_member` on (`organization`, `user`) — one membership per user per organization.

**Indexes:**

| Index | Columns | Serves |
|---|---|---|
| `organizatio_organiz_bd2d0f_idx` | (`organization`, `is_active`) | Member listing per tenant |
| `organizatio_user_id_8783ae_idx` | (`user`, `is_active`) | Tenant resolution for a user |

**Ordering:** `created_at`.
**Tenant ownership:** direct, via `organization_id`.

**Role choices — current / approved:**

```
OWNER, MANAGER, STAFF
```

Platform administration is `User.is_superuser` / `User.is_staff`, not an organization role. Migration `organizations.0002_remove_super_admin_role` reassigns any legacy `SUPER_ADMIN` membership rows to `OWNER` (no rows deleted) and removes the choice.

**Target additions:** `invited_by` (FK → `User`, `SET_NULL`), `joined_at`.

---

## 4. Current Entities (Business / Location)

### 4.1 `businesses.Business`

A brand or operating entity inside an Organization. **Separate from Organization** so one tenant can run multiple brands.

| Field | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK → `Organization` | not null, `PROTECT`, related `businesses` |
| `name` | varchar(255) | not null |
| `slug` | varchar(255) | unique per organization (partial, live rows) |
| `vertical` | varchar(32) | `SALON`, `SPA`, `BARBER`, `CLINIC`, `DENTAL`, `GYM`, `RESTAURANT`, `OTHER` |
| `description` | text | blank |
| `logo_url` | varchar(500) | blank |
| `primary_domain` | varchar(255) | unique among live rows when set, nullable |
| `is_active` | boolean | default `true` |
| `created_at` / `updated_at` | timestamptz | auto |
| `deleted_at` / `deleted_by` | — | soft delete |
| `created_by` / `updated_by` | FK → `User` | audit |

**Unique:** (`organization`, `slug`) partial on live rows; `primary_domain` unique among live non-null values.
**Indexes:** (`organization`, `is_active`); (`vertical`); (`primary_domain`).
**Tenant ownership:** direct.
**Managers:** `objects` (alive only), `all_objects` (includes soft-deleted).

### 4.1b `businesses.BusinessLaunchProfile`

Per-location **launch configuration** for commercial go-live. Does **not** duplicate business name, address, services, staff, availability, or QuickCard content — those remain on existing entities.

| Field | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK → `Organization` | tenant, `PROTECT` |
| `business` | FK → `Business` | `PROTECT` |
| `location` | FK → `Location` | `PROTECT`; unique with business among live rows |
| `template_key` | varchar(64) | blank or `SALON_MODERN` / `SALON_CLASSIC` / `SALON_LUXURY` (app registry; no template tables) |
| `subdomain` | slug(63) | blank; unique among live non-empty |
| `custom_domain` | varchar(255) | blank; unique among live non-empty; storage only (no DNS/SSL automation) |
| `domain_status` | varchar(32) | `NOT_CONFIGURED`, `PROVISIONING`, `SUBDOMAIN_ACTIVE`, `FAILED`, `CUSTOM_DOMAIN_PENDING`, `CUSTOM_DOMAIN_ACTIVE` |
| `google_business_url` | varchar(500) | blank; tracking only; not a review link |
| `google_review_url` | varchar(500) | blank; https-only customer review link; not copied from `google_business_url` |
| `google_business_status` | varchar(32) | `NOT_STARTED`, `IN_PROGRESS`, `READY`, `VERIFIED` (owner-claimed; platform does not verify with Google) |
| `whatsapp_setup_status` | varchar(32) | `NOT_CONFIGURED`, `CONFIGURED`, `ACTIVE` (launch checklist only; no tokens). Business Cloud API credentials live on `messaging.WhatsAppAccount` |
| `website_status` | varchar(32) | `NOT_STARTED`, `DRAFT`, `READY`, `PUBLISHED`, `UNPUBLISHED` |
| `launch_status` | varchar(32) | `DRAFT`, `READY`, `LIVE` |
| timestamps / soft delete / audit | — | standard |

**Unique:** (`business`, `location`) live; `subdomain` live non-empty; `custom_domain` live non-empty.
**Indexes:** (`organization`, `business`); (`business`, `location`); (`launch_status`).

**Website provisioning:** Publish (`sites.provisioning_services.publish_website`) allocates a unique BookAnything subdomain (`normalize` → collision `base`, `base-2`, …), sets `domain_status=SUBDOMAIN_ACTIVE`, `website_status=PUBLISHED`, `launch_status=LIVE`, and returns canonical `public_url` = `https://{subdomain}.{BOOKANYTHING_SITE_DOMAIN}` (path fallback on localhost). Idempotent per location. Unpublish → `UNPUBLISHED` while keeping subdomain reserved. Custom-domain DNS/SSL deferred.

**Google Business (launch tracking vs connection):** `google_business_url` / `google_business_status` on this profile are **owner-claimed tracking only** (no API). Live connection metadata lives on `GoogleBusinessConnection` (§4.1c).

**Launch readiness (blocking):** booking setup ready (business, location, services, staff+assignment, availability, QuickCard created+published) **and** `template_key` selected. A BookAnything subdomain does not block when available/auto-assigned. Google and WhatsApp do not block launch. **Public website** (`GET /api/v1/public/sites/{slug}/`) is visible only when launch-ready **and** `website_status=PUBLISHED` (draft/unpublished/inactive → `404`).

### 4.1c `businesses.GoogleBusinessConnection`

Per-location **Google Business Profile connection** with AES-GCM encrypted OAuth credentials (`businesses/google_crypto.py`; key `GOOGLE_TOKEN_ENCRYPTION_KEY`). Tokens never appear in admin, API responses, logs, or model `__str__`.

| Field | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK → `Organization` | tenant, `PROTECT` |
| `business` | FK → `Business` | `PROTECT` |
| `location` | FK → `Location` | `PROTECT`; unique with business among live rows |
| `provider` | varchar(32) | `mock` \| `google` \| `deferred` |
| `status` | varchar(32) | `NOT_CONNECTED`, `CONNECTED`, `LOCATION_SELECTION_REQUIRED`, `SYNCING`, `REAUTH_REQUIRED`, `ERROR`, `DISCONNECTED` |
| `google_location_id` | varchar(255) | blank; explicit owner-selected GBP location resource name; never auto-matched across multiple options |
| `google_business_account_name` | varchar(255) | blank; selected GBP account resource (e.g. `accounts/{id}`); auto-set when exactly one account exists |
| `google_location_display_name` | varchar(255) | blank; safe display title from Google at selection time |
| `google_account_id` | varchar(255) | blank; stable Google OAuth subject id (not email as primary key) |
| `google_email` | email | blank; metadata only |
| `access_token_encrypted` | text | blank; AES-GCM ciphertext |
| `refresh_token_encrypted` | text | blank; AES-GCM ciphertext; preserved on reconnect if Google omits a new refresh token |
| `token_expires_at` | timestamptz | nullable |
| `scopes` | varchar(500) | blank; granted scope string |
| `connected_at` | timestamptz | nullable |
| `last_synced_booking_url` | varchar(500) | blank; last booking URL pushed to provider |
| `last_sync_status` | varchar(32) | `NEVER`, `SUCCESS`, `FAILED`, `SKIPPED` |
| `last_synced_at` | timestamptz | nullable |
| `last_error_code` | varchar(64) | blank; safe category code |
| `last_error_message` | varchar(500) | blank; safe operator message (no tokens) |
| timestamps / soft delete / audit | — | standard |

**Unique:** (`business`, `location`) live.
**Indexes:** (`organization`, `business`); (`business`, `location`); (`status`).

**OAuth ≠ GBP location:** `LOCATION_SELECTION_REQUIRED` means Google account linked without an explicit GBP location mapping. `CONNECTED` with `google_location_id` means mapped and ready to sync. Sync success is recorded on `last_sync_status=SUCCESS` (not a separate connection status).

**Canonical URLs for sync:** Website must be `PUBLISHED` with a provisioned subdomain. Sync pushes `{PUBLIC_APP_URL}/book/{location.slug}` onto the mapped Google location `websiteUri`. Unpublished / inactive locations are not syncable. Unpublish after a prior sync does not automatically clear Google; BookAnything records sync as blocked/`WEBSITE_NOT_PUBLISHED` on the next sync attempt (removal of Google websiteUri is not implemented).

**Migrations:** `0005_google_oauth_credentials.py`, `0006_google_location_selection_fields.py`.

### 4.1d `businesses.GoogleOAuthState`

Single-use OAuth CSRF/state rows. Stores **SHA-256 hash** of the raw state (never the raw state). Bound to user + organization + business + location.

| Field | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `state_hash` | char(64) | unique |
| `user` | FK → `User` | `CASCADE` |
| `organization` | FK → `Organization` | `CASCADE` |
| `business` | FK → `Business` | `CASCADE` |
| `location` | FK → `Location` | `CASCADE` |
| `expires_at` | timestamptz | required |
| `used_at` | timestamptz | nullable; set on consume |
| timestamps | — | standard |

**Indexes:** (`expires_at`); (`user`, `business`). Reject missing/invalid/expired/reused/cross-user/cross-business/cross-location states.

### 4.2 `locations.Location`

A physical outlet. **Separate from Business** to support multi-location operations.

| Field | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK → `Organization` | not null, `PROTECT` (denormalized tenant) |
| `business` | FK → `Business` | not null, `PROTECT`, related `locations` |
| `name` | varchar(255) | not null |
| `slug` | varchar(255) | unique per business (partial, live rows); public URL selector — public APIs require an unambiguous match (0 or >1 → 404). Global unique constraint is recommended hardening. |
| `address_line1` / `address_line2` | varchar(255) | blank |
| `city` / `state` / `postal_code` / `country` | varchar | blank; `country` ISO-2 |
| `latitude` / `longitude` | decimal(9,6) / (10,6) | nullable |
| `timezone` | varchar(64) | IANA name; validated |
| `phone` | varchar(20) | blank; E.164 preferred |
| `email` | varchar(254) | blank |
| `is_primary` | boolean | default `false`; first location auto-primary |
| `is_active` | boolean | default `true` |
| timestamps / soft delete / audit | — | standard |

**Unique:** (`business`, `slug`) partial on live rows; one `is_primary=true` per business (partial unique).
**Indexes:** (`organization`, `is_active`); (`business`, `is_active`); (`city`, `country`).
**Tenant ownership:** denormalized `organization_id` + `business_id` (service keeps them aligned).

`LocationHours` / `LocationClosure` remain **target** (not yet implemented).

### 4.3 `catalog.ServiceCategory` / `catalog.Service` / `catalog.ServiceLocation`

**ServiceCategory**

| Field | Type | Constraints |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK → `Organization` | not null, `PROTECT` |
| `business` | FK → `Business` | not null, `PROTECT` |
| `name` | varchar(255) | not null |
| `slug` | varchar(255) | unique per business (partial, live rows) |
| `display_order` | positive int | default 0 |
| timestamps / soft delete / audit | — | standard |

**Indexes:** (`organization`, `business`); (`business`, `display_order`).

**Service**

| Field | Type | Notes |
|---|---|---|
| `organization` / `business` | FK `PROTECT` | Tenant + brand |
| `category` | FK → `ServiceCategory` | `PROTECT`, nullable |
| `name` / `slug` | varchar | slug unique per business, live rows |
| `description` | text | blank |
| `duration_minutes` | positive int | ≥ 1 |
| `buffer_before_minutes` / `buffer_after_minutes` | positive int | default 0 |
| `price` | decimal(10,2) | ≥ 0 |
| `currency` | varchar(3) | ISO 4217; default `INR` |
| `is_bookable_online` | boolean | default `true` |
| `is_active` | boolean | default `true` |
| timestamps / soft delete / audit | — | standard |

**Indexes:** (`organization`, `is_active`); (`business`, `category`); (`business`, `is_bookable_online`).

**ServiceLocation** (junction; **not** soft-deleted)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK `PROTECT` | denormalized tenant |
| `service` | FK → `Service` | `CASCADE` |
| `location` | FK → `Location` | `CASCADE` |
| `duration_minutes` | positive int | nullable override |
| `price` / `currency` | decimal / varchar | nullable price override |
| timestamps / `created_by` / `updated_by` | — | row audit |

**Unique:** (`service`, `location`). Soft-deleting a Service hard-deletes its ServiceLocation rows.

### 4.4 `staff.StaffProfile` / `staff.StaffService`

**StaffProfile**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` / `business` | FK `PROTECT` | Tenant + brand |
| `location` | FK → `Location` | `PROTECT`; primary location |
| `user` | FK → `User` | nullable, `SET_NULL`; optional login |
| `display_name` | varchar(255) | required |
| `title` / `bio` / `photo_url` | varchar/text/url | blank allowed |
| `is_bookable` / `is_active` | boolean | default `true` |
| timestamps / soft delete / audit | — | standard |

**Unique:** (`organization`, `user`) partial on live rows where `user` is not null.
**Indexes:** (`organization`, `is_active`); (`location`, `is_bookable`); (`business`, `is_active`).

**StaffService** (junction; **not** soft-deleted)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK `PROTECT` | denormalized tenant |
| `staff_profile` | FK → `StaffProfile` | `CASCADE` |
| `service` | FK → `Service` | `CASCADE` |
| `duration_minutes` / `price` / `currency` | optional overrides | |
| timestamps / audit | — | `created_by` / `updated_by` |

**Unique:** (`staff_profile`, `service`). Soft-deleting a StaffProfile hard-deletes its StaffService rows.

### 4.5 `staff.StaffAvailability` / `staff.StaffTimeOff`

**Timezone convention**

- Recurring availability uses local wall-clock `TimeField`s interpreted in `Location.timezone`. No conversion logic in this module; booking will apply the location timezone later.
- Time-off uses timezone-aware `DateTimeField`s (stored UTC by Django/`USE_TZ`).

**StaffAvailability** (recurring weekly; **not** soft-deleted)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK `PROTECT` | denormalized tenant |
| `staff_profile` | FK → `StaffProfile` | `CASCADE` |
| `location` | FK → `Location` | `PROTECT`; must share business with staff |
| `weekday` | small int | `0=Monday` … `6=Sunday` |
| `starts_at` / `ends_at` | time | local wall-clock in `Location.timezone` |
| timestamps / audit | — | `created_by` / `updated_by` |

**Constraint:** `ends_at > starts_at`.
**Indexes:** (`staff_profile`, `weekday`); (`organization`, `staff_profile`); (`staff_profile`, `location`, `weekday`).
**Overlap rule:** same `staff_profile` + `location` + `weekday` intervals must not overlap — enforced in the service layer (no Postgres exclusion constraint yet). Soft-deleting a StaffProfile hard-deletes its availability rows.

**StaffTimeOff** (dated absence; **not** soft-deleted; **not** location-scoped)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK `PROTECT` | denormalized tenant |
| `staff_profile` | FK → `StaffProfile` | `CASCADE` |
| `starts_at` / `ends_at` | timestamptz | aware; supports multi-day and same-day ranges |
| `reason` | varchar(255) | blank allowed |
| timestamps / audit | — | `created_by` / `updated_by` |

**Constraint:** `ends_at > starts_at`.
**Indexes:** (`staff_profile`, `starts_at`, `ends_at`); (`organization`, `staff_profile`).
Soft-deleting a StaffProfile hard-deletes its time-off rows.

**Deferred to Booking:** slot calculation, appointment conflicts, buffers, and calendar sync.

### 4.6 `customers.Customer` / `customers.CustomerTag` / `customers.CustomerTagAssignment`

Customers are **business-level** (not location-scoped). A customer may visit any location of the same business. Customers are not platform users.

**Customer** (soft-deleted)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` / `business` | FK `PROTECT` | Tenant + brand |
| `first_name` / `last_name` | varchar(150) | `last_name` blank allowed |
| `phone` | varchar(20) | required; E.164 normalized; primary identity |
| `email` | varchar(254) | optional; lowercased |
| `date_of_birth` | date | optional |
| `notes` | text | staff-visible; blank allowed |
| `marketing_opt_in` / `whatsapp_opt_in` | boolean | default `false` |
| `first_visit_at` / `last_visit_at` | timestamptz | nullable; from COMPLETED appointments via `completed_at` (historical rows may use `ends_at` until backfilled) |
| `total_visits` | positive int | default 0; count of live COMPLETED appointments for this customer/business |
| `total_spend` | decimal(10,2) | default 0; booking maintains later |
| timestamps / soft delete / audit | — | standard |

**Unique:** (`business`, `phone`) partial on live rows.
**Indexes:** (`organization`, `business`); (`business`, `phone`); (`business`, `last_visit_at`); (`business`, `email`).
Soft-deleting a Customer hard-deletes its tag assignments. Phone may be reused after soft delete. Visit totals are recalculated on appointment completion and by `manage.py reconcile_customer_visits`. Historical COMPLETED appointments without `completed_at` receive `completed_at = ends_at` during reconciliation only.

**Retention profile (derived, not stored):** Owner retention-summary reads denormalized visit counters plus live COMPLETED appointments for the same customer/organization/business. Recent visits (max 10) use `public_reference`, `completed_at` (fallback `ends_at`), location/staff display names from FKs, `AppointmentItem.service_name` snapshot, and appointment `total_price`/`currency`. Service history groups by `AppointmentItem.service_name`. Staff/location history group by `staff_profile.display_name` / `location.name` (soft-deleted staff/location rows remain visible through appointment joins; names are not snapshotted on Appointment). `average_days_between_visits` = elapsed days between first and last completed visit ÷ (visits − 1), one decimal, null when visits < 2. Soft-deleted appointments are excluded. These metrics are historical only — not predictions, scores, or campaign triggers.

**CustomerRetentionSettings** (one row per business; **not** soft-deleted)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` / `business` | FK `PROTECT` | Tenant + brand; unique on `business` |
| `return_after_days` | positive int | default 30; must be ≥ 1 |
| `inactive_after_days` | positive int | default 90; must be > `return_after_days` |
| `due_message_delay_hours` | positive int | default 24; hours after the due threshold before WhatsApp send |
| `enabled` | boolean | default `true`; when false, automation is not scheduled/sent (segments still calculate) |
| timestamps / audit | — | standard |

**Constraints:** unique `business`; check `return_after_days ≥ 1`; check `inactive_after_days > return_after_days`; check `due_message_delay_hours ≥ 1`.

**Retention segments (derived, not stored on Customer):** Primary segment priority — `NO_VISITS` (zero completed visits / null last visit) → `NEW` (exactly one completed visit) → `INACTIVE` (`days_since_last_visit ≥ inactive_after_days`) → `DUE_FOR_RETURN` (`≥ return_after_days` and `< inactive_after_days`) → `RETURNING` (otherwise, with ≥ 2 visits). These are deterministic classifications based on completed-visit history and owner-configured thresholds. They are not predictions.

**CustomerRetentionMessage** (durable Due-for-Return WhatsApp schedule; **not** soft-deleted)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK (stored as `Appointment.acquisition_reference` when attributed) |
| `organization` / `business` / `customer` | FK `PROTECT` | Tenant + customer |
| `location` | FK nullable | Location used in the retention booking URL (set when queued) |
| `public_reference` | varchar(32) unique | Opaque URL ref (`?source=retention&ref=…`); not a tenant/customer id |
| `segment` | varchar | Stored as `DUE_FOR_RETURN` for this journey |
| `trigger_visit_at` | timestamptz | `Customer.last_visit_at` for this cycle |
| `scheduled_for` | timestamptz | `last_visit_at + return_after_days + due_message_delay_hours` |
| `status` | varchar | `PENDING` / `QUEUED` / `SENT` / `SKIPPED` / `CANCELLED` / `FAILED` |
| `whatsapp_message` | FK nullable | Existing outbound `WhatsAppMessage` |
| `idempotency_key` | varchar unique | `retention:due:{customer_id}:{last_visit_at}` |
| `skip_reason` / `sent_at` / `cancelled_at` | — | Outcome metadata |

Retention automation is deterministic and rule-based. It does not predict churn or customer intent. Requires `whatsapp_opt_in`, connected WhatsApp, and an approved English `RETENTION` / `RETENTION_DUE_RETURN` template. Booking attribution (`acquisition_source=RETENTION`) links an appointment to a specific message after server validation; this phase establishes attribution only — retention conversion analytics comes later.

**CustomerTag** (business-owned label; **not** soft-deleted)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` / `business` | FK `PROTECT` | Tenant + brand |
| `name` | varchar(100) | unique per business |
| timestamps / audit | — | |

**Unique:** (`business`, `name`).

**CustomerTagAssignment** (junction; **not** soft-deleted)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK `PROTECT` | denormalized tenant |
| `customer` | FK → `Customer` | `CASCADE` |
| `tag` | FK → `CustomerTag` | `CASCADE` |
| timestamps / audit | — | |

**Unique:** (`customer`, `tag`). Customer and tag must share the same business (enforced in services).

**Privacy:** no public customer APIs. Visit counters are read-only via API until booking writes them. No customer merge tooling yet.

### 4.7 `booking.Appointment` / `booking.AppointmentItem`

Financial and operational record. **Never hard deleted.** Soft delete is for erasure only; normal cancel uses `status=CANCELLED`.

**Appointment**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` / `business` / `location` | FK `PROTECT` | Tenant chain |
| `customer` | FK → `Customer` | `PROTECT` |
| `staff_profile` | FK → `StaffProfile` | `PROTECT`; **required** (any-staff resolved before insert) |
| `starts_at` / `ends_at` | timestamptz | Customer-visible window (UTC) |
| `occupancy_starts_at` / `occupancy_ends_at` | timestamptz | Visible ± snapshotted buffers; used for conflicts |
| `status` | varchar(32) | `PENDING`, `CONFIRMED`, `CHECKED_IN`, `COMPLETED`, `CANCELLED`, `NO_SHOW` |
| `source` | varchar(32) | Channel: `ONLINE`, `WHATSAPP`, `PHONE`, `WALK_IN`, `DASHBOARD`. Not attribution |
| `completed_at` | timestamptz | nullable; set once when transitioning to `COMPLETED`. Source for customer visit history |
| `acquisition_source` | varchar(32) | nullable. `QUICKCARD` or `RETENTION` when validated. Blank otherwise |
| `acquisition_reference` | UUID | nullable. QuickCard id (`QUICKCARD`) or `CustomerRetentionMessage` id (`RETENTION`). No cascading FK |
| `total_price` / `currency` | decimal / varchar(3) | Snapshot |
| `deposit_amount` / `deposit_paid` | decimal / bool | Present; used when `Business.payment_mode=DEPOSIT` |
| `payment_status` | varchar(32) | `NOT_REQUIRED` / `PENDING` / `PAID` / `PARTIALLY_PAID` / `REFUNDED`. Maintained by `payments` services only |
| `notes` | text | |
| `cancelled_at` / `cancellation_reason` / `cancelled_by` | — | Cancel metadata |
| `public_reference` | varchar(32) unique | Opaque public id |
| timestamps / soft delete / audit | — | standard |

**Indexes:** (`organization`, `starts_at`); (`location`, `starts_at`, `status`); (`staff_profile`, `starts_at`, `status`); (`customer`, `starts_at`); (`status`, `starts_at`); (`staff_profile`, `occupancy_starts_at`, `occupancy_ends_at`); partial `appt_qc_acq_created_idx` on (`acquisition_source`, `created_at`) where `acquisition_source = 'QUICKCARD'`; partial `appt_ret_acq_created_idx` where `acquisition_source = 'RETENTION'`. Migrations: `booking/0011_appointment_quickcard_attribution.py`, `booking/0013_retention_booking_attribution.py`.

**Constraints:** `ends_at > starts_at`; `occupancy_ends_at > occupancy_starts_at`; PostgreSQL GiST exclusion `excl_appointment_staff_occupancy` on `(staff_profile =, tstzrange(occupancy) &&)` for live occupying statuses (`PENDING`/`CONFIRMED`/`CHECKED_IN`). Requires `btree_gist`.

**AppointmentItem** (exactly one per appointment in v1)

| Field | Type | Notes |
|---|---|---|
| `appointment` | FK `CASCADE` | |
| `service` | FK `PROTECT` | Live pointer |
| `staff_profile` | FK `PROTECT` | Same as header in v1 |
| `service_name` | varchar | **Snapshot** |
| `duration_minutes` | int | **Snapshot** |
| `buffer_before_minutes` / `buffer_after_minutes` | int | **Snapshot** |
| `price` / `currency` | decimal / varchar | **Snapshot** |
| timestamps / audit | — | |

**Slot engine:** 15-minute local grid; availability from StaffAvailability − time off − occupying appointments; buffers apply to occupancy. See `docs/BOOKING_DESIGN.md`.

**IdempotencyRecord** (reusable request-idempotency store; not soft-deleted)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `scope` | varchar(64) | e.g. `public_booking.create` |
| `key` | varchar(255) | Client `Idempotency-Key` |
| `request_hash` | varchar(64) | SHA-256 of canonical payload |
| `response_status` | smallint | `0` = in progress; otherwise HTTP status |
| `response_body` | jsonb | Cached successful response body |
| timestamps | — | `created_at` / `updated_at` |

**Unique:** (`scope`, `key`). First consumer: public appointment create. Designed so payment idempotency can reuse the same table with a different `scope`.

**AppointmentManageToken** (secure public manage capability; one per appointment)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `appointment` | FK → Appointment | OneToOne, CASCADE |
| `token_hash` | varchar(64) unique | SHA-256 of raw token (raw never stored) |
| `expires_at` | timestamptz nullable | Rejected when past |
| `revoked_at` | timestamptz nullable | Soft revoke |
| timestamps | — | `created_at` / `updated_at` |

Raw token is returned once on public create (`manage_token`) and used in `/book/manage/{token}`, `/book/manage/{token}/history`, and `/api/v1/public/booking/manage|history/{token}/`. Lookup uses `token_hash` only. The raw token is passed in-process to post-commit notification handlers so the confirmation message can include the manage URL. It is never stored as a dedicated field on `AppointmentManageToken` and cannot be recovered from the hash.

**Appointment** may optionally reference a `BookingPlan` (`booking_plan` nullable FK, `plan_occurrence_date` local date). Unique live constraint: (`booking_plan`, `plan_occurrence_date`) when both set.

### 4.7b `booking.BookingPlan` / `BookingPlanManageToken`

Book Regularly — **not a subscription**. No payments. Each visit is a normal `Appointment` created via `create_appointment`.

| Field | Type | Notes |
|---|---|---|
| `customer` / `location` / `service` | FK `PROTECT` | Existing entities |
| `staff_profile` | FK nullable | Set only for `SAME_STAFF` |
| `staff_preference` | `SAME_STAFF` / `ANY_STAFF` | |
| `frequency` | `WEEK` / `MONTH` | |
| `interval` | positive int | MVP: 1 or 2 |
| `preferred_time` | time | Local wall clock |
| `timezone` | varchar | From `Location.timezone` |
| `start_date` | date | First occurrence local date |
| `next_due_at` | timestamptz | Next intended start (UTC) |
| `status` | `ACTIVE` / `PAUSED` / `CANCELLED` | |
| `needs_action` / `needs_action_code` | bool / varchar | e.g. `SLOT_UNAVAILABLE`, `SERVICE_INACTIVE` |

**Manage token:** hash-at-rest `BookingPlanManageToken` (same pattern as appointment manage tokens). Cancelling a plan does **not** cancel existing appointments. Scheduler: `process_due_booking_plans` / `manage.py process_due_booking_plans`.

---

**NotificationDelivery** (outbound transactional notification ledger)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `appointment` | FK → Appointment | CASCADE |
| `channel` | varchar(16) | `WHATSAPP` / `SMS` / `EMAIL` |
| `notification_type` | varchar(32) | `BOOKING_CONFIRMATION` / `BOOKING_CANCELLATION` / `REMINDER_24H` / `REMINDER_1H` |
| `recipient` | varchar(64) | E.164 phone (or future email) |
| `status` | varchar(16) | `PENDING` / `SENT` / `FAILED` (BookAnything outcome) |
| `provider_status` | varchar(16) | Meta transport: `sent` / `delivered` / `read` / `failed` |
| `provider_message_id` | varchar(128) | Meta `wamid…` (webhook correlation) |
| `attempt_count` | smallint | Incremented per send attempt |
| `last_error` | text | Sanitized last provider error |
| `error_class` | varchar(16) | `TRANSIENT` / `PERMANENT` when failed |
| `sent_at` / `delivered_at` / `read_at` / `failed_at` | timestamptz nullable | Lifecycle timestamps |
| `payload_version` | smallint | Snapshot schema version (currently `1`) |
| `payload_snapshot` | jsonb | Frozen message for retries (may include `manage_url` + `text`) |
| timestamps | — | `created_at` / `updated_at` |

**Unique:** (`appointment`, `channel`, `notification_type`) — one delivery row per reminder/confirmation/cancellation type; failed rows may be retried via `retry_notification`, which reuses `payload_snapshot` and must not mint a new manage token. Reminder rows are created at dispatch time by `process_due_reminders` (not at booking create).

**WhatsAppWebhookEvent** — idempotency ledger for Meta status callbacks (`provider_message_id` + `provider_status` unique).

**Snapshot security:** `payload_snapshot` may embed the customer-facing manage URL so retries send the same link. It is not an auth store — manage/cancel authorization still requires presenting the raw token against `token_hash`. Do not log full snapshots; redact manage URLs in structured logs. Admin excludes `payload_snapshot` from the detail form.

### 4.8 `sites.QuickCard`

Shareable public digital identity for a `Location`. Presentation layer only — does **not** own services, staff, hours, or booking logic.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK → `Organization` | not null, `PROTECT` (denormalized tenant) |
| `business` | FK → `Business` | not null, `PROTECT` |
| `location` | OneToOne → `Location` | not null, `PROTECT`, related `quickcard` |
| `slug` | slug(255) | Unique among live rows; public URL `/q/{slug}`; **stable after create** |
| `headline` / `description` | varchar / text | blank |
| `logo_url` / `cover_image_url` | URL | blank (URL fields, matching `Business.logo_url`) |
| `phone` / `whatsapp` | varchar(32) | blank; contact CTAs |
| `website_url` / `google_maps_url` / `instagram_url` / `facebook_url` | URL | blank |
| `is_published` | boolean | default `false`; public GET requires `true` |
| `published_at` | timestamptz | nullable |
| `view_count` | positive int | default `0` (reserved; no persistent analytics pipeline yet) |
| timestamps / soft delete / audit | — | standard |

**Unique:** `slug` partial on live rows (`unique_quickcard_slug_alive`).
**Indexes:** (`organization`, `is_published`); (`business`, `is_published`); (`slug`).
**Public composition:** services and prices via `catalog.public_services` (`resolve_effective_pricing`); staff via `staff.public_services`; booking CTA → existing `/book/{location.slug}?source=quickcard&ref={quickcard.slug}`. The slug is the public reference. The appointment stores the card UUID only after the server matches that slug to the same location, business, and organization. A bad ref still books with both attribution fields null. Revenue attribution is later work. Canonical public URL is `/q/{slug}` because the QuickCard slug is globally unique among live rows; location slugs are unique only inside a business. Directions use a safe https `BusinessLaunchProfile.google_business_url`, then the card `google_maps_url`. The review CTA uses only https `google_review_url`. Call uses the location phone, then the card phone. WhatsApp uses the card WhatsApp number, then the card or location phone. Opening hours are a provisional aggregate of `StaffAvailability` until `LocationHours` exists. Public GET sends `Cache-Control: public, max-age=60` and does not include availability, credentials, customers, or organization ids. `data-cta` on the page posts anonymous `QuickCardEvent` rows. `view_count` on the card remains unused; counts come from those events.
**QR:** PNG generated on demand (no `QRCode` table yet); encodes `PUBLIC_APP_URL/q/{slug}` only.

**QuickCardEvent** — append-only anonymous engagement. No customer, cookie, IP, or fingerprint. `event_type` is `PAGE_VIEW` or `CTA_CLICK`. `cta_type` is blank for a view and otherwise `BOOK`, `WHATSAPP`, `CALL`, `DIRECTIONS`, `REVIEW`, or `SHARE`. `occurred_at` is UTC set by the server. `referrer` stores scheme, host, and path only when the `Referer` header is a normal http(s) URL without a token. Indexes: (`business`, `occurred_at`), (`quickcard`, `event_type`, `occurred_at`), (`business`, `cta_type`, `occurred_at`). Migration: `sites/0002_quickcard_event.py`. Owner counts are aggregated on read. Those events are clicks, not attributed appointments. Attributed bookings are counted from live `Appointment` rows whose `created_at` falls in the same window and whose `acquisition_reference` is a QuickCard id for that business, including soft-deleted cards (`QuickCard.all_objects`). `booking_conversion_rate` is attributed bookings divided by Book Now clicks (`CTA_CLICK` / `BOOK`, `occurred_at`) times 100, rounded to one decimal. It is `null` when Book Now clicks are zero. Optional analytics `location_id` limits both sides of that ratio to QuickCards whose location matches, still including soft-deleted cards. Page views and the other CTA types are not part of that ratio. The percentage is not capped at 100 because a click and an appointment are independent rows. Revenue is not included.

### 4.9 `messaging.WhatsAppAccount` / `MessageTemplate` / `WhatsAppMessage`

Business-owned WhatsApp Business Platform foundation. Separate from platform transactional `booking.NotificationDelivery` (which uses `WHATSAPP_PROVIDER` and platform `META_WHATSAPP_*` settings). Access tokens are AES-GCM ciphertext (`messaging/whatsapp_crypto.py`, env `WHATSAPP_TOKEN_ENCRYPTION_KEY`, prefix `v1:`). Plaintext tokens are never stored, logged, serialized, or shown in admin. Migration: `messaging/0001_whatsapp_business_foundation.py`.

**WhatsAppAccount** — one live connection per business. Soft-deleted.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` / `business` | FK | `PROTECT` |
| `phone_number_id` | varchar(64) | Meta phone number id |
| `business_account_id` | varchar(64) | WhatsApp Business Account id |
| `display_phone_number` | varchar(20) | E.164 display number when known |
| `verified_name` | varchar(255) | blank |
| `access_token_encrypted` | text | AES-GCM; cleared on disconnect |
| `token_expires_at` | timestamptz | nullable |
| `status` | varchar(32) | `CONNECTED`, `DISCONNECTED`, `REAUTH_REQUIRED`, `ERROR` |
| `last_error_code` / `last_error_message` | varchar | safe codes/messages only; no token text |
| `connected_at` / `disconnected_at` | timestamptz | nullable |
| timestamps / soft delete / audit | — | standard |

**Unique:** (`business`) where `deleted_at IS NULL`.
**Indexes:** (`organization`, `business`); (`status`).

**MessageTemplate** — business-scoped catalog. Soft-deleted. Not sent by booking views.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` / `business` | FK | `PROTECT` |
| `name` | varchar(128) | template name |
| `purpose` | varchar(32) | blank, or `BOOKING_CONFIRMATION`, `BOOKING_CONFIRMED`, `BOOKING_RESCHEDULED`, `BOOKING_CANCELLED`, `REVIEW_REQUEST` |
| `language` | varchar(16) | default `en` |
| `category` | varchar(32) | `CONFIRMATION`, `REMINDER`, `REVIEW_REQUEST`, `WIN_BACK`, `CUSTOM` |
| `provider_template_id` | varchar(128) | blank until Meta approval is wired |
| `status` | varchar(32) | `DRAFT`, `PENDING`, `APPROVED`, `REJECTED`, `DISABLED` |
| `body` | text | local content metadata |
| `variables` | jsonb | variable definitions (list) |
| timestamps / soft delete / audit | — | standard |

**Unique:** (`business`, `name`, `language`) where `deleted_at IS NULL`; (`business`, `purpose`, `language`) where `deleted_at IS NULL` and `purpose` is not empty.
**Indexes:** (`organization`, `business`); (`business`, `status`).

**WhatsAppMessage** — append-only outbound log. **Not soft-deleted.** Inbound is deferred. Payload is operator metadata (body text or template variables), not a full customer profile. API list omits `payload` and credentials.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` / `business` | FK | `PROTECT` |
| `customer` | FK | nullable, `SET_NULL` |
| `appointment` | FK | nullable, `SET_NULL` |
| `phone_number` | varchar(20) | normalized public E.164 via `customers.services.normalize_public_phone` |
| `purpose` | varchar(32) | blank, or a lifecycle purpose such as `BOOKING_CONFIRMATION` / `REVIEW_REQUEST` |
| `message_type` | varchar(16) | `TEXT` or `TEMPLATE` |
| `template_name` / `template_language` | varchar | blank for text |
| `payload` | jsonb | send metadata plus frozen `rendered_text` when a template snapshot was stored |
| `provider_message_id` | varchar(128) | blank until sent; unique when non-empty |
| `status` | varchar(16) | `QUEUED`, `SENT`, `DELIVERED`, `READ`, `FAILED`, `CANCELLED` |
| `failure_code` / `failure_message` | varchar | safe; no secrets |
| `idempotency_key` | varchar(255) | blank allowed; unique with `business` when non-empty |
| `delivery_attempts` | small int | incremented on provider failure; transient retry reuses the row |
| `sent_at` / `delivered_at` / `read_at` / `failed_at` | timestamptz | nullable; webhook times use the provider event time |
| timestamps / audit | — | no soft delete |

**Indexes:** (`organization`, `created_at`); (`business`, `created_at`); (`customer`, `created_at`); (`status`, `created_at`); (`business`, `purpose`).

**Automation:** After commit, appointment lifecycle events queue an approved English template for the matching purpose through `queue_whatsapp_message`. Idempotency keys: `booking-confirmation:{appointment}`, `booking-confirmed:{appointment}`, `booking-rescheduled:{appointment}:{updated_at}`, `booking-cancelled:{appointment}:{cancelled_at}`, `review-request:{appointment}`. Reminder key: `appointment:{appointment_id}:reminder:{schedule_version}:24h`. Missing account or template skips with no message row for lifecycle sends. A connected business still stores an `AppointmentReminder` for the 24-hour reminder; a missing template marks that reminder `SKIPPED` at processing time. Provider failure sets `FAILED` and does not affect the appointment. Rollback before commit queues nothing. Migrations: `0002_whatsapp_transactional_automation`, `0003_appointment_reminder`.

**AppointmentReminder** also stores `APPOINTMENT_REMINDER_1H` (`appointment:{id}:reminder:{version}:1h`) and one `REVIEW_REQUEST` per appointment (`appointment:{id}:review-request`, `schedule_version` 0). Review `scheduled_for` is completion time plus `WHATSAPP_REVIEW_REQUEST_DELAY_HOURS` (default 3), in UTC.

**MessageTemplate.provider_status** is the Meta status from sync or submission. Local `status` is the send gate and is not Meta approval.

**WhatsAppInboundMessage** — inbound text. Unique `provider_message_id`. Customer is set only when the normalized phone matches a customer of the same business. No reply is sent. OWNER/MANAGER read the paginated history. Migration: `0004_inbound_and_review_schedule`. `google_review_url` is added by `businesses/0007_google_review_url.py` and is not backfilled.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` / `business` / `appointment` | FK | `PROTECT` |
| `whatsapp_message` | FK | nullable, `SET_NULL` |
| `notification_type` | varchar(64) | `APPOINTMENT_REMINDER_24H`, `APPOINTMENT_REMINDER_1H`, or `REVIEW_REQUEST` |
| `schedule_version` | positive int | must match the appointment at send time |
| `scheduled_for` | timestamptz | UTC; start minus 24 hours |
| `status` | varchar(16) | `PENDING`, `QUEUED`, `SENT`, `CANCELLED`, `FAILED`, `SKIPPED` |
| `idempotency_key` | varchar(255) | unique |
| `attempt_count` | small int | copied from the message when known |
| `last_error_code` / `last_error_message` | varchar | safe reason |
| `sent_at` / `cancelled_at` | timestamptz | nullable |
| timestamps | — | standard |

**Unique:** (`appointment`, `notification_type`, `schedule_version`); `idempotency_key`.
**Indexes:** (`status`, `scheduled_for`); (`organization`, `business`, `status`); (`appointment`, `status`).

---

## 5. Target Entities

Approved shapes for unimplemented modules. Field lists are the minimum contract; add only with a documentation update.

### 5.1 Reserved — through Booking core

Implemented; see §4 (including §4.3–§4.7).

### 5.3 Reserved — Staff

Implemented; see §4.4–§4.5.

### 5.4 Reserved — Customers

Implemented; see §4.6.

### 5.5 Reserved — Booking

Implemented; see §4.7.

### 5.6 Presence: `sites.*`

- **QuickCard** — implemented; see §4.8.
- **QRCode** — target multi-target QR inventory (`target_type`, `short_code`, `scan_count`). MVP QR for QuickCard is on-demand PNG only (see §4.8).
- **Template** / **Site** / **SitePage** — still target (full website builder).

### 5.7 Communication

Business WhatsApp connection, templates, outbound messages, 24-hour reminders, and delivery status webhooks are implemented; see §4.9. Remaining target work: inbound messages, Meta template submission, and delayed review requests.

### 5.8 Reputation: `reviews.*`

- **ReviewRequest** — `organization`, `business`, `location`, `customer`, `appointment` (`PROTECT`), `channel`, `status`, `sent_at`, `responded_at`. Unique (`appointment`) on live rows — one request per appointment.
- **Review** — `organization`, `business`, `location`, `customer` (nullable), `source` (`GOOGLE`, `PLATFORM`, `FACEBOOK`, `OTHER`), `external_id`, `rating` (1–5), `body`, `author_name`, `reviewed_at`, `response_body`, `responded_at`. Unique (`source`, `external_id`) where both present. Indexes: (`organization`, `reviewed_at`); (`location`, `rating`).

### 5.9 Discovery: `discovery.*`

- **SeoProfile** — per site/page metadata, canonical URL, robots directives, Open Graph fields, structured-data JSON.
- **FaqEntry** — `organization`, `business`, `location` (nullable), `question`, `answer`, `display_order`, `is_published`. Powers AEO and structured data.
- **BusinessFact** — machine-readable key/value facts for GEO/AI search readiness: `organization`, `business`, `location` (nullable), `key`, `value`, `source`, `verified_at`. Unique (`business`, `location`, `key`).

### 5.10 Analytics: `analytics.*`

- **Event** — append-only fact table: `organization`, `business`, `location` (nullable), `event_type`, `entity_type`, `entity_id`, `properties` JSONB, `occurred_at`, hashed `session_id`. Indexes: (`organization`, `occurred_at`); (`organization`, `event_type`, `occurred_at`); BRIN on `occurred_at` at volume. Partition by month when the table grows. **Never updated or deleted** outside retention policy.
- **DailyMetric** — precomputed rollups: `organization`, `business`, `location` (nullable), `date`, `metric_key`, `value`. Unique (`organization`, `business`, `location`, `date`, `metric_key`).

### 5.11 Commerce: `payments.*` (current) + `billing.*` (target)

**Current (`payments/`):** Provider-agnostic appointment payments. Razorpay is the first provider (`RAZORPAY_PROVIDER=mock|razorpay|deferred`).

- **Business.payment_mode** — `NONE` (default, no online collection), `FULL` (pay `Appointment.total_price`), `DEPOSIT` (pay `Appointment.deposit_amount` when > 0). Opt-in only.
- **Appointment.payment_status** — lightweight: `NOT_REQUIRED` / `PENDING` / `PAID` / `PARTIALLY_PAID` / `REFUNDED`. Updated only by payment services. Payment rows remain source of truth. Does not store provider IDs.
- **PaymentOrder** — checkout attempt: org/business/location/appointment/customer, amount, currency, provider, `provider_order_id`, unique `(organization, idempotency_key)`, statuses `CREATED|ATTEMPTED|PAID|FAILED|EXPIRED|CANCELLED`, opaque `public_reference`.
- **Payment** — verified outcome: amounts (`amount`, `amount_paid`, `amount_refunded` as Decimal), provider ids, statuses `CREATED|PENDING|AUTHORIZED|PAID|FAILED|CANCELLED|PARTIALLY_REFUNDED|REFUNDED`, opaque `public_reference`. Unique provider payment id when present.
- **Refund** — `payment`, amount, currency, status `PENDING|PROCESSED|FAILED|CANCELLED`, `provider_refund_id`, org-scoped idempotency key. Owner-only API in v1.
- **PaymentWebhookEvent** — unique `(provider, provider_event_id)`; `payload_hash`; process-once ledger.

**Target (`billing/`):** platform subscription Plan / Subscription / UsageCounter (unchanged target). Platform subscription Payment is separate from appointment `payments.Payment`.

### 5.12 Automation: `automation.*`

- **AutomationRule** — `organization`, `business`, `name`, `trigger_type`, `trigger_config` JSONB, `conditions` JSONB, `action_type`, `action_config` JSONB, `is_active`. Index (`organization`, `trigger_type`, `is_active`).
- **AutomationRun** — append-only execution log: `rule`, `organization`, `status`, `triggered_at`, `completed_at`, `error`, `context` JSONB. Index (`rule`, `triggered_at`).

### 5.13 `core.AuditLog`

Append-only. Not soft deletable, not updatable.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization` | FK → `Organization` | nullable (platform-level events) |
| `actor` | FK → `User` | nullable, `SET_NULL` |
| `action` | varchar(64) | e.g. `member.role_changed` |
| `entity_type` / `entity_id` | varchar / UUID | Target |
| `changes` | JSONB | Before/after, secrets redacted |
| `ip_address` | inet | nullable |
| `user_agent` | varchar(500) | nullable |
| `created_at` | timestamptz | auto |

**Indexes:** (`organization`, `created_at`); (`actor`, `created_at`); (`entity_type`, `entity_id`); (`action`, `created_at`).

---

## 6. Index Strategy

1. Every foreign key is indexed (Django does this by default).
2. Every tenant-owned table indexes `organization_id`.
3. Composite indexes lead with the tenant column, then the most selective filter, then the sort column.
4. Time-series tables index (`organization`, `<timestamp>`) for range scans.
5. Uniqueness that must coexist with soft deletion uses partial unique indexes over `deleted_at IS NULL`.
6. `deleted_at` is indexed on every soft-deletable table.
7. JSONB fields get GIN indexes only when actually queried by content.
8. Indexes are justified by a real query. Unused indexes are removed.

### 6.1 Owner setup + launch readiness

- **Setup** (`get_business_setup_status`): derived from Business/Location/Service/Staff/Availability/QuickCard.
- **Launch** (`get_business_launch_status`): extends setup with `BusinessLaunchProfile` (template, domain, Google tracking, WhatsApp status, website/launch state). Progress is over launch-blocking checklist items only.

---

## 7. Migration Rules

1. Every schema change ships as a Django migration. No manual production DDL.
2. Never edit an applied migration; add a new one.
3. Never delete a migration.
4. Migrations must be backward compatible with the previous release (expand → migrate data → contract in a later release).
5. Adding a non-nullable column requires a default or a three-step expand/contract.
6. Data migrations are separate from schema migrations and must be idempotent.
7. Index creation on large tables uses `CREATE INDEX CONCURRENTLY` via `AddIndexConcurrently`.
8. Destructive operations require explicit approval.
9. Any migration touching entities, fields, relationships, indexes, or constraints requires an update to this document in the same change.

**Current migrations:**

```
accounts/migrations/0001_initial.py                    User
accounts/migrations/0002_initial.py                    User.active_organization, groups, user_permissions
organizations/migrations/0001_initial.py               Organization, OrganizationMember
organizations/migrations/0002_remove_super_admin_role.py
businesses/migrations/0001_initial.py                  Business
businesses/migrations/0002_business_launch_profile.py  BusinessLaunchProfile
businesses/migrations/0003_website_provisioning_statuses.py  Domain/Website status choices
businesses/migrations/0004_google_business_connection.py  GoogleBusinessConnection
businesses/migrations/0005_google_oauth_credentials.py Google OAuth ciphertext + GoogleOAuthState
businesses/migrations/0006_google_location_selection_fields.py GBP account/location mapping fields
locations/migrations/0001_initial.py                   Location
catalog/migrations/0001_initial.py                     ServiceCategory, Service, ServiceLocation
staff/migrations/0001_initial.py                       StaffProfile, StaffService
```

---

## 8. Data Retention

| Data | Retention |
|---|---|
| Appointments, payments | Indefinite (financial record) |
| Customer records | Life of the organization; erasable on request |
| Messages | 24 months, then archive |
| Analytics events | 13 months raw; rollups indefinite |
| Audit logs | 24 months minimum |
| Soft-deleted records | 90 days recoverable, then archived |
| Expired refresh tokens | Purged on schedule |

Organization deletion triggers a documented erasure workflow: financial records are retained as required by law, customer PII is erased, and the action is audited.
