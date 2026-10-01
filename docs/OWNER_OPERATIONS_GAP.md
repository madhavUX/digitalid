# Owner Operations Gap

What an organization owner can manage today vs gaps.
Classification: **READY** | **PARTIAL** | **MISSING**.

Do not build a new dashboard in Phase 6.0.1.

---

## Current surfaces

| Capability | Status | Evidence |
|---|---|---|
| Businesses | PARTIAL | Created/managed primarily via `/owner/onboarding`; no dedicated multi-business hub |
| Locations | PARTIAL | Onboarding + location switcher; no full locations CRUD page |
| Services (catalog) | READY | `/owner/services` |
| Staff + availability | READY | `/owner/staff` |
| Customers / CRM | READY | `/owner/customers` |
| Bookings + calendar | READY | `/owner/bookings`, calendar views |
| Website / site provisioning | READY | `/owner/website` |
| Google Business | PARTIAL | Card on onboarding launch setup; not a first-class nav item |
| WhatsApp connect / templates | PARTIAL | Card on onboarding; limited ongoing health UI |
| QuickCard | READY | `/owner/quickcard` (+ analytics in product) |
| Retention settings / profiles | PARTIAL | Customer profile + settings; no dedicated retention ops console |
| Payments (orders, refunds, status) | MISSING | Public `PaymentStep` only; owner refund is API-only (no UI) |
| Booking plans | READY | `/owner/booking-plans` |

---

## Potential future dashboard modules

| Module | Need |
|---|---|
| Today’s bookings | Operational triage |
| Pending bookings | Confirm / chase payment |
| Completed / Cancelled / No-show | Lifecycle ops |
| Revenue / Payments | Depends on Phase 6.1 definitions + owner payments UI |
| Customers / Returning | Partially covered by CRM + retention |
| Retention due | Missing dedicated queue view |
| WhatsApp health | Template/account status monitoring |
| Location performance | Not started |

---

## Severity

- Missing owner **payments** UI: **P2** (API exists; ops can use API/admin carefully)
- Partial Google/WhatsApp surfaces: **P2** (usable via onboarding cards)
- Full ops dashboard: **P3** (Phase 6.1+ / later)

---

## Verdict

Owners can run day-to-day catalog, staff, bookings, customers, website, and QuickCard.

**Not launch-complete for payment operations or provider health monitoring without API/admin fallback.**
