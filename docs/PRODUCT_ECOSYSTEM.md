# Product Ecosystem

Boundary between CreativeNuron, DigitalID, and BookAnything.
Phase 6.0.1 documents intent only — **no repo renames or restructures**.

```
CreativeNuron
    ↓
DigitalID
    ↓
BookAnything technology
```

---

## CreativeNuron

**Role:** Services company — implementation, branding, websites, SEO, AI assist, marketing, growth engagements.

- Customer of / partner on top of DigitalID
- Must not be hard-wired into the booking engine’s domain model, auth, or payment ledger
- Branding and agency workflows stay outside `booking/` / `payments/` core

---

## DigitalID

**Role:** Customer-facing business digital identity and SaaS product.

- Owner onboarding, websites/sites, Google presence, WhatsApp business messaging UX, QuickCard, retention product surfaces
- Multi-tenant organization/business/location model exposed to end customers
- Product name customers recognize

---

## BookAnything

**Role:** Underlying booking and customer-growth technology layer.

- Appointments, scheduling, catalog, staff availability, public booking APIs
- Payments foundation, messaging automation primitives, attribution fields
- This repository’s technical core (`booking`, `payments`, `customers`, `staff`, …)

Avoid coupling core booking/payment services to CreativeNuron-specific branding, copy, or agency entitlements.

---

## Practical rules for agents

1. New booking/payment rules belong in BookAnything services, not CreativeNuron marketing sites.
2. DigitalID UI may brand the experience; APIs remain tenant-generic.
3. Do not add `creativenuron_*` tables or hard-coded agency tenant privileges into the core engine.
4. Attribution and revenue definitions stay product-neutral (`ANALYTICS_DEFINITIONS.md`).
