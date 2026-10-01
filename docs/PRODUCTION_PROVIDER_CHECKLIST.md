# Production Provider Checklist

Distinguish **IMPLEMENTED IN CODE** from **VERIFIED LIVE**.
Passing automated tests with mocks does **not** count as live verification.

Last audit: Phase 6.0.3 preparation.

---

## PostgreSQL (managed production)

| Item | Code / docs | Live |
|---|---|---|
| `DATABASE_URL` authoritative | IMPLEMENTED | [ ] Provisioned |
| Production rejects localhost / Compose hosts | IMPLEMENTED (`digitalid.E010`) | N/A |
| TLS via `sslmode` on URL | DOCUMENTED | [ ] Enabled |
| Automated managed backups | DOCUMENTED requirement | [ ] Enabled |
| PITR (preferred) | DOCUMENTED | [ ] Enabled if available |
| Isolated restore drill | DOCUMENTED procedure | [ ] VERIFIED LIVE |
| Observed RPO / RTO | Template in backup doc | [ ] Recorded |

**PHASE 6.0.3: BLOCKED** until a managed provider is configured and restore is verified.  
Local `pg_dump` ≠ production backup proof.

---

## WhatsApp

### Platform transactional stack (`booking/`, `WHATSAPP_PROVIDER`)

| Item | Code | Live |
|---|---|---|
| Meta provider path | IMPLEMENTED (`meta`) | [ ] VERIFIED LIVE |
| Mock provider | IMPLEMENTED (default) | N/A |
| Template / body field env config | IMPLEMENTED | [ ] VERIFIED LIVE |
| Confirmation message path | IMPLEMENTED | [ ] Real confirmation message |
| Reminder path (legacy / platform) | IMPLEMENTED | [ ] Real reminder |
| Delivery webhook | IMPLEMENTED | [ ] Delivery webhook |
| Read webhook | IMPLEMENTED | [ ] Read webhook |
| Failed webhook | IMPLEMENTED | [ ] Failed webhook |
| Webhook signature verify | IMPLEMENTED | [ ] Webhook verification |
| Webhook HTTPS endpoint | IMPLEMENTED (assumes deploy TLS) | [ ] Webhook HTTPS |

### Business-owned stack (`messaging/`, `WHATSAPP_BUSINESS_PROVIDER`)

| Item | Code | Live |
|---|---|---|
| Connected account model | IMPLEMENTED | [ ] |
| Encrypted token (`WHATSAPP_TOKEN_ENCRYPTION_KEY`) | IMPLEMENTED | [ ] |
| Meta Business account | config required | [ ] Meta Business account |
| WhatsApp Business Account | config required | [ ] WhatsApp Business Account |
| Phone Number ID | stored when connected | [ ] Phone Number ID |
| Access token | encrypted at rest | [ ] Access token |
| App secret | env | [ ] App secret |
| Template status / approval tracking | IMPLEMENTED | [ ] Approved templates |
| Message queue + Celery send | IMPLEMENTED | [ ] |
| Inbound webhook / history | IMPLEMENTED | [ ] Inbound message |
| Review request scheduling | IMPLEMENTED | [ ] |
| Retention automation sends | IMPLEMENTED | [ ] |
| Token expiry / reauthentication | PARTIAL (reconnect flows in owner UI) | [ ] Token expiry/reauthentication |

**Default env:** business provider `deferred`; platform provider `mock`. Live Meta is opt-in.

**Verdict:** CODE COMPLETE for dual-stack architecture. **Not LIVE VERIFIED. Not PRODUCTION READY for WhatsApp.**

---

## Google Business Profile

| Item | Code | Live |
|---|---|---|
| OAuth state + callback | IMPLEMENTED | [ ] real OAuth |
| Encrypted tokens | IMPLEMENTED | [ ] |
| Account mapping | IMPLEMENTED | [ ] account selection |
| Location mapping | IMPLEMENTED | [ ] location selection |
| URL sync | IMPLEMENTED | [ ] URL sync |
| Disconnect | IMPLEMENTED | [ ] |
| Reconnect / reauthentication | IMPLEMENTED | [ ] reconnect |
| Provider abstraction (`mock` / `deferred` / `google`) | IMPLEMENTED | [ ] |
| Revoked-token behavior | PARTIAL (error paths exist; needs live prove-out) | [ ] revoked-token behavior |

**Default env:** `GOOGLE_BUSINESS_PROVIDER=deferred`, `GOOGLE_BUSINESS_ENABLED=false`.

**Verdict:** CODE COMPLETE for foundation. **Not LIVE VERIFIED. Not PRODUCTION READY for Google.**

---

## Razorpay payments

| Item | Code | Live |
|---|---|---|
| Mock provider + order/verify/webhook/refund | IMPLEMENTED + tested | N/A |
| Live Razorpay provider class | IMPLEMENTED | [ ] Live keys + sandbox/prod capture |
| Webhook secret verification | IMPLEMENTED | [ ] Live webhook |
| Owner refund API | IMPLEMENTED | [ ] Live refund |

**Verdict:** CODE COMPLETE with hardening tests. Live checkout not claimed verified in this audit.
