# PRD — Local Business Digital Growth Platform

Status: approved architecture. Implementation is at foundation stage (see "Current Implementation Status").

---

## 1. Product Vision

Local service businesses lose customers because their digital presence is fragmented, manual, and invisible to modern search. They juggle a stale website, an Instagram bio link, a phone that rings during appointments, a WhatsApp inbox nobody owns, and Google reviews they never ask for. Agencies solve this for large brands at prices local businesses cannot pay.

**We give a local business its complete digital growth engine in one system: a fast website, a shareable digital identity, automated WhatsApp customer communication, online booking, review generation, and visibility in both traditional search and AI-generated answers.**

The platform is multi-tenant and vertical-aware. One codebase serves many business types; vertical-specific behavior is configuration and templates, not forks.

**Positioning:** not a website builder, not a booking tool, not a CRM. A growth system where those pieces are already connected.

### Product Principles

1. **Backend is the source of truth.** Business rules live in Django. The frontend renders and collects.
2. **Tenant isolation is absolute.** A tenant can never observe another tenant's data or its existence.
3. **Automation over dashboards.** The owner should not have to log in daily for the product to create value.
4. **Speed is a feature.** Public pages must be fast enough to win local search.
5. **One system, many verticals.** Vertical differences are data, not branches.

---

## 2. Target Customers

### Primary (launch)

Independent and small-chain salons, 1–5 locations, 2–25 staff, owner-operated, in urban and tier-2 markets. Typically:

- A neglected or nonexistent website
- Bookings taken by phone, WhatsApp, Instagram DM, and walk-in
- A paper or spreadsheet appointment book
- No structured customer database
- Reviews collected accidentally
- No SEO, no analytics, no retention marketing

### Secondary (expansion order)

Spa → Barber → Clinic → Dental → Gym → Restaurant → other local service businesses.

### Buyer and Users

| Persona | Role | Primary need |
|---|---|---|
| Owner | Buyer, admin | Growth, revenue visibility, control |
| Manager | Daily operator | Schedule, staff, customers |
| Staff | Service provider | Own schedule and clients |
| End customer | Consumer | Find, book, and return easily |

### Non-Customers

Enterprise chains needing bespoke ERP integration, franchises requiring corporate hierarchy accounting, pure e-commerce sellers, and non-local online-only businesses.

---

## 3. Initial Vertical: Salon

The salon vertical is the reference implementation. Every module is validated here before generalization.

**Salon-specific characteristics the platform must model:**

- Services with duration, price, and category (cut, color, spa, bridal)
- Staff with per-service capability and individual working hours
- Appointment durations that vary by service and by staff
- Buffer/cleanup time between appointments
- Multi-location chains sharing a brand but with separate staff and hours
- Peak demand on weekends and holidays
- Retention economics: a repeat customer is worth far more than a new one

**Salon success criteria:**

- Owner completes onboarding to a live public booking page in under 30 minutes
- Reduction in phone-call bookings within the first month
- Measurable increase in Google review volume
- Repeat booking rate visible in analytics

---

## 4. Customer Journey (End Consumer)

The consumer never creates a platform account to book.

1. **Discover** — finds the business via Google search, an AI assistant answer, a QR code in-store, a QuickCard link in an Instagram bio, or a WhatsApp share.
2. **Land** — arrives on the business's public site or QuickCard: services, prices, staff, hours, location, reviews. Loads fast on mobile.
3. **Choose** — selects a service, optionally a specific staff member, and sees genuinely available times. **Availability is computed by the backend.**
4. **Book** — submits name and phone. Optional deposit or prepayment where enabled.
5. **Confirm** — sees an on-site confirmation with booking reference and a secure manage/cancel link. Transactional WhatsApp confirmation is generated after commit (mock provider locally; Meta Cloud API templates in production when configured). Automated WhatsApp reminders follow later at configured offsets (default 24h and 1h before start) for still-CONFIRMED appointments. From the manage link, the guest can open booking history and Book Again without creating an account.
6. **Manage / cancel** — opens `/book/manage/{token}` without login to view details or cancel (releases the slot). Cancellation also triggers a transactional WhatsApp cancellation notification. Reschedule is not in this milestone.
7. **Remind** — receives automated WhatsApp reminders (default 24 hours and 1 hour before start) while the appointment remains CONFIRMED.
8. **Attend** — visits; staff marks the appointment complete.
9. **Review** — receives an automated review request with a direct link (target).
10. **Return** — receives win-back and offer messages based on visit history and service cadence (target).

Every step is instrumented for analytics.

---

## 5. Owner Journey

1. **Sign up** — creates an account; an Organization is created and the user becomes `OWNER`.
2. **Set up business** — enters business details and vertical, creating a Business and its first Location.
3. **Configure catalog** — adds services with duration and price; adds staff with working hours and service capability.
4. **Publish presence** — selects a template; the public website, QuickCard, and QR codes go live.
5. **Enable booking** — sets booking rules: lead time, cancellation window, buffers, deposits.
6. **Connect WhatsApp** — links the business number and enables confirmation, reminder, and review flows.
7. **Operate** — manages the appointment calendar, staff schedules, and customer records.
8. **Grow** — reviews analytics, SEO/AEO/GEO readiness, review volume, and retention; runs campaigns.
9. **Scale** — adds locations under the same Business; staff and services are managed per location.
10. **Bill** — manages subscription tier and payment method; usage limits are enforced by tier.

---

## 6. Core Modules

Ordered roughly by dependency.

| # | Module | Purpose |
|---|---|---|
| 1 | **Multi-tenant organizations** | Tenant root. Owns all data. Isolation boundary. |
| 2 | **Businesses** | A brand/operating entity within an Organization. Carries vertical. |
| 3 | **Locations** | A physical outlet of a Business. Address, hours, timezone. Multi-location support. |
| 4 | **Users and roles** | Authentication, organization membership, `OWNER`/`MANAGER`/`STAFF`. Platform admin is separate. |
| 5 | **Services** | Catalog: name, category, duration, price, per-location availability. |
| 6 | **Staff** | Service providers, working hours, time off, service capability. |
| 7 | **Customers / CRM** | Customer records, contact details, visit history, tags, notes. |
| 8 | **Booking** | Availability computation, appointment lifecycle, rules, cancellation. Backend-only logic. |
| 9 | **Website / template engine** | Public site per business/location from selectable templates and content blocks. |
| 10 | **QuickCard** | Shareable single-page digital identity: contact, services, booking, social. |
| 11 | **QR codes** | Generated, trackable codes for card, booking, review, and menu links. |
| 12 | **WhatsApp automation** | Confirmations, reminders, review requests, win-back, inbound handling. |
| 13 | **Reviews** | Review requests, aggregation, display, response workflow. |
| 14 | **SEO** | Metadata, structured data, sitemaps, local search optimization, performance. |
| 15 | **AEO** | Answer Engine Optimization: FAQ and entity structuring for direct-answer surfaces. |
| 16 | **GEO / AI Search Readiness** | Machine-readable business facts for AI assistants and generative search. |
| 17 | **Analytics** | Traffic, bookings, revenue, retention, channel attribution, review velocity. |
| 18 | **Subscriptions** | Plans, tiers, feature gating, usage limits, trials. |
| 19 | **Payments** | Subscription billing and optional customer-side deposits/prepayment. |
| 20 | **Automation engine** | Rule-based triggers and scheduled actions across modules. |

### Module Dependencies

```
Organization
  └── Business (vertical)
        └── Location
              ├── Services
              ├── Staff
              ├── Customers
              └── Booking ──────┐
                                ├── WhatsApp automation
                                ├── Reviews
                                └── Analytics
        └── Website / QuickCard / QR ── SEO / AEO / GEO
Organization ── Subscriptions ── Payments
Automation engine spans Booking, WhatsApp, Reviews, CRM
```

---

## 7. Current Implementation Status

Implemented today:

- Custom `User` with email login
- `Organization` and `OrganizationMember` (`OWNER` / `MANAGER` / `STAFF`)
- `Business` and `Location` with soft delete and row-level audit fields
- `ServiceCategory`, `Service`, and `ServiceLocation` catalog
- `StaffProfile` and `StaffService` (capability assignment)
- `StaffAvailability` (recurring weekly hours per location) and `StaffTimeOff` (dated absences)
- `Customer`, `CustomerTag`, and `CustomerTagAssignment` (business-level CRM foundation; visit totals from COMPLETED appointments; retention profile + deterministic segments; Due-for-Return WhatsApp automation with opt-in and visit-cycle idempotency; retention booking attribution via `acquisition_source=RETENTION`; `reconcile_customer_visits` / `process_due_retention_messages`; owner `/owner/customers` UI)
- `payments/` — provider-agnostic payment domain with Razorpay (mock|razorpay|deferred); `PaymentOrder` / `Payment` / `Refund` / `PaymentWebhookEvent`; `Business.payment_mode` opt-in (`NONE` default / `FULL` / `DEPOSIT`); `Appointment.payment_status`; public payment-order + verify APIs; Razorpay webhook; owner refund API
- `Appointment` / `AppointmentItem` with slot engine, internal availability + appointment APIs, concurrency exclusion
- Public booking API (`/api/v1/public/booking/…`) including secure manage/cancel by hashed manage token, guest booking history + Book Again prefill, plus public catalog/discovery API (`/api/v1/public/locations/{slug}/…` including services, categories, and staff)
- Lightweight booking events (`AppointmentBooked`, `AppointmentCreated`, `AppointmentConfirmed`, `AppointmentCancelled`, `AppointmentRescheduled`, `AppointmentCompleted`), WhatsApp notifications/reminders, guest booking history + Book Again, QuickCard (`sites`), Book Regularly (`BookingPlan`), OWNER/MANAGER onboarding + dashboard (`/owner/*`), Business Launch Profile, **salon website templates** (`SALON_MODERN` / `CLASSIC` / `LUXURY` via `/site/{slug}`), **website provisioning** (BookAnything subdomain publish/unpublish → `https://{subdomain}.{BOOKANYTHING_SITE_DOMAIN}`), **Google Business OAuth + GBP location mapping + booking URL sync** (encrypted credentials; mock/real provider; owner-selected account/location; `websiteUri` sync), and **business WhatsApp** (encrypted connection; approved-template transactional sends; durable 24-hour and 1-hour reminders for a connected account; delayed review request using the location `google_review_url`, not `google_business_url`; read-only inbound history; platform sender remains for unconnected accounts)
- Next.js public booking funnel (`frontend/`, routes `/book/[locationSlug]`, success page, `/book/manage/[token]`)
- JWT authentication: register, login, refresh, me
- Server-side tenant resolution from user membership
- Business, Location, Catalog, Staff, scheduling, customer, and booking CRUD under `/api/v1/`
- Django Admin for users, organizations, members, businesses, locations, catalog, staff, availability, time-off, customers, tags, appointments, notification deliveries
- Tests for authentication and cross-tenant isolation (including catalog, staff, scheduling, customers, public catalog/staff, booking concurrency on PostgreSQL, manage-token security, WhatsApp notification idempotency, Meta provider unit tests, webhook security, reminder eligibility/idempotency, and business WhatsApp connection/template/message/provider/lifecycle tests)

Not yet implemented: free-form website builder, SMS/email providers, custom-domain DNS/SSL automation, **Google Posts / Messaging / review analytics**, automatic Google review URL discovery, QuickCard revenue attribution, **retention conversion analytics** (attribution exists; dashboards later), payment conversion dashboards / revenue analytics UI, deposits UI beyond `payment_mode=DEPOSIT` + `deposit_amount`, marketing/win-back WhatsApp campaigns, WhatsApp replies, and modules 9–20 except the QuickCard public profile at `/q/{slug}` with anonymous view and CTA counts, durable booking attribution, and a Book Now → booking conversion rate, with an optional location filter and date range on the same endpoint, Book Regularly, owner onboarding/dashboard, Launch Profile, salon templates, BookAnything subdomain provisioning, Google OAuth + location mapping + booking URL sync, and business WhatsApp connection plus transactional booking automation, delayed review requests, and read-only inbound history. See `docs/ARCHITECTURE.md` §10.

---

## 8. Future Modules

Post-core, not in scope until the core modules ship:

- Marketing campaigns (email/SMS broadcast) beyond the automation engine
- Loyalty and membership packages
- Inventory and retail product sales
- Point of sale and billing/invoicing
- Staff payroll and commission
- Multi-language public sites
- Mobile applications for owners and staff
- Marketplace/directory discovery across tenants
- Partner and reseller/white-label portal
- Public API for third-party integrations
- Advanced AI: demand forecasting, dynamic pricing, automated content generation

---

## 9. Non-Goals

Explicitly out of scope. Do not build these without a documented decision.

- **Not a general website builder.** Templates are vertical-specific and opinionated. No free-form drag-and-drop page composition.
- **Not a social media scheduler.**
- **Not a general-purpose CRM.** Customer records exist to serve booking, retention, and communication.
- **Not an accounting or tax system.**
- **Not an HR/payroll system.**
- **Not an e-commerce platform.** Physical product catalogs and carts are out of scope.
- **Not a consumer marketplace.** We do not aggregate businesses into a consumer-facing directory or compete with our own customers for demand.
- **No business logic in the frontend.** Next.js never computes booking availability, pricing, or permissions.
- **No client-controlled tenancy.** The client never selects which tenant's data it reads.
- **No per-tenant code forks.** Vertical differences are configuration and data.
