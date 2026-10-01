# Production Runbook

Operational procedures for BookAnything / DigitalID.
Mock providers only in local smoke tests — never call live Meta/Razorpay/Google from smoke scripts.

Full Hostinger assessment: `docs/HOSTINGER_VPS_ASSESSMENT.md`.  
Deployment automation: `docs/DEPLOYMENT.md` (`./deploy.sh`, project `bookanything`).  
**WebGuardSphere isolation:** do not bind host 80/443; use host Caddy snippet.

---

## Architecture

### Hostinger VPS (BookAnything project — isolated from WebGuardSphere)

```
Host Caddy (:80/:443)  ← WebGuardSphere + BookAnything site blocks (manual)
Compose project: bookanything
  ├── bookanything-frontend → 127.0.0.1:13000
  ├── bookanything-web      → 127.0.0.1:18080
  ├── bookanything-worker
  ├── bookanything-beat (single)
  ├── bookanything-postgres (pg.digitalid.internal)
  └── bookanything-redis

PostgreSQL backups ──► EXTERNAL storage (required)
```

Normal deploy: `cd /opt/bookanything && ./deploy.sh`  
See `docs/DEPLOYMENT.md`. Do **not** enable compose profile `standalone-edge` beside WebGuardSphere.

### Local Docker Compose (dev)

`docker-compose.yml` — publishes 5432/6379, `runserver`, no Next.js, `DJANGO_ENV=development`.  
**Do not deploy it to Hostinger.**

---

## Phase 6.1 verification checklist (operator on VPS)

Execute only after SSH + `.env.production` exist on the Hostinger host.

1. **Preflight:** confirm hostname/IP; never `docker compose down -v`.  
2. **Deploy:**  
   `docker compose -f docker-compose.production.yml --env-file .env.production up -d --build`  
3. **Containers:** `ps` shows postgres, redis, web, worker, beat, frontend, caddy running.  
4. **Health:** `curl -fsS http://127.0.0.1/health/live/` and `/health/ready/`.  
5. **Django:** `docker compose … exec web python manage.py check` and `showmigrations`.  
6. **Redis:** readiness check includes redis; 6379 not published.  
7. **Celery worker (safe):** enqueue `payments.tasks.noop_reconcile_payments` — no WhatsApp/payments live.  
8. **Celery beat:** exactly one replica; schedule includes reminder + retention tasks.  
9. **Frontend:** HTTPS (or HTTP smoke) `/`, `/owner`, `/book`, `/q`, `/site`.  
10. **HTTPS:** public `https://HOST/health/live/` — valid cert; document Cloudflare mode if used.  
11. **Admin/API:** `/admin/`, CSRF origins, `DJANGO_DEBUG=false`.  
12. **Webhooks (routing only):**  
    - `https://HOST/api/v1/webhooks/whatsapp/`  
    - `https://HOST/api/v1/webhooks/payments/razorpay/`  
13. **Firewall:** 80/443 open; 22 restricted; 5432/6379 closed externally.  
14. **Backup:** configure `EXTERNAL_BACKUP_CMD` + GPG; run `scripts/postgres_backup.sh`.  
15. **Restore drill:** isolated DB via `scripts/postgres_restore_drill.sh`; record duration.  
16. **RPO/RTO:** from actual backup interval + drill duration — do not invent.

Until evidenced: all of the above remain **NOT VERIFIED**.

---

## Domain / reverse-proxy routing (Caddy)

| Public path | Upstream | Notes |
|---|---|---|
| `/api/*` | `web:8000` | API + Razorpay/WhatsApp webhooks |
| `/health/*` | `web:8000` | live / ready |
| `/admin/*` | `web:8000` | Django admin |
| `/*` | `frontend:3000` | `/owner`, `/book`, `/q`, `/site`, `/backend` rewrite |

Next.js keeps `NEXT_PUBLIC_API_BASE_URL=/backend` and server `DJANGO_API_URL=http://web:8000`.

### DNS / Cloudflare (manual)

1. Point A/AAAA (or CNAME) for the app hostname to the Hostinger VPS.  
2. Set `SITE_ADDRESS=your.hostname` in `.env.production` for Caddy auto-HTTPS, **or** terminate TLS at Cloudflare and set `SITE_ADDRESS=:80` with Cloudflare “Flexible/Full” as you choose (prefer Full/Strict with origin certs).  
3. Ensure webhook URLs (Razorpay/Meta) use the public HTTPS origin.  
4. Do not open 5432/6379 on the Hostinger firewall.

---

## Environment separation

| Variable | Development | Production (Hostinger) |
|---|---|---|
| `DJANGO_ENV` | `development` | `production` |
| `DJANGO_DEBUG` | may be true | `false` |
| DB host | `postgres` / localhost OK | **`pg.digitalid.internal`** (E010) |
| `REDIS_URL` | optional | required + password |
| `CELERY_TASK_ALWAYS_EAGER` | tests may true | `false` |
| `CSRF_TRUSTED_ORIGINS` | optional | required HTTPS origins |
| `SITE_ADDRESS` | n/a | Caddy host or `:80` |

Production checks: `digitalid.E001`–`E010`.

### Required variables

See `.env.production.example`. Categories: Django secrets/hosts, Postgres/Redis compose secrets, Celery, `PUBLIC_APP_URL`, Razorpay / WhatsApp / Google keys. **Never commit `.env.production`.**

Compose injects `DATABASE_URL` / `REDIS_URL` / `CELERY_*` using `pg.digitalid.internal` and Redis password.

---

## Startup — Hostinger production compose (manual)

```bash
cp .env.production.example .env.production
# fill secrets on the VPS

docker compose -f docker-compose.production.yml --env-file .env.production up -d --build

curl -fsS http://127.0.0.1/health/live/
curl -fsS http://127.0.0.1/health/ready/
docker compose -f docker-compose.production.yml --env-file .env.production ps
```

Migrate runs on web container start. Scale **worker** if needed; **never scale beat**.

### Local Docker Compose

```bash
docker compose up --build
```

---

## Persistent storage

| Volume / path | Purpose | Backup |
|---|---|---|
| `postgres_data` | PostgreSQL | **External** encrypted dumps required |
| `redis_data` | Redis AOF | Not source of truth; optional |
| `caddy_data` | TLS certs | Recreatable via Caddy/DNS |
| Container FS | ephemeral | Do not store uploads here |

No Django `MEDIA_ROOT` volume is configured yet; add a volume when media uploads ship.

---

## Hostinger firewall

**Public:** 80, 443, 22 (SSH restricted).  
**Never public:** 5432, 6379.

**Hostinger VPS specifications must be confirmed manually.**

---

## Shutdown

1. Stop accepting traffic (load balancer / freeze deploy).
2. Stop Beat (prevent new scheduled enqueue).
3. Stop workers after queue drains (or SIGTERM and wait).
4. Stop web.
5. Do not shut down Postgres/Redis until workers are gone.

---

## Migrations

```bash
python manage.py makemigrations --check
python manage.py migrate
python manage.py check
```

Run migrate once per release from a single deployer. Workers/web should run the same code revision.

---

## Health verification

| Endpoint | Expect |
|---|---|
| `GET /health/live/` | `200` `{"status":"ok"}` |
| `GET /health/ready/` | `200` when DB (+ Redis if required) up; `503` otherwise |

No authentication. Responses must not include secrets or stack traces.

---

## Smoke test (mock providers)

1. Start PostgreSQL + Redis (+ web/worker/beat via compose or locally).
2. `curl -sS http://127.0.0.1:8000/health/live/` → ok
3. `curl -sS http://127.0.0.1:8000/health/ready/` → database ok, redis ok
4. Confirm Beat schedule includes:
   - `messaging.tasks.process_due_appointment_reminders`
   - `messaging.tasks.process_due_retention_messages`
5. Enqueue a no-op or WhatsApp deliver against a missing id (safe):
   ```bash
   python -c "import django; django.setup(); from messaging.tasks import deliver_whatsapp_message; deliver_whatsapp_message.delay('00000000-0000-0000-0000-000000000000')"
   ```
   Worker log should show the task received; DB unchanged for appointments/payments.
6. Create a booking via existing public API tests or UI with `RAZORPAY_PROVIDER=mock`, `WHATSAPP_PROVIDER=mock`.
7. Confirm appointment row exists; background failures must not roll back the appointment.

---

## Backup verification

See `docs/DATABASE_BACKUP_RESTORE.md`.

On VPS after deploy:

```bash
# once EXTERNAL_BACKUP_CMD + GPG_PASSPHRASE_FILE are set (operator secrets)
./scripts/postgres_backup.sh
# isolated restore (never production URL):
ENCRYPTED_BACKUP=/path/to/digitalid-….dump.gpg \
RESTORE_DATABASE_URL=postgres://…@isolated-host/digitalid_restore \
./scripts/postgres_restore_drill.sh
```

Weekly: confirm last external backup succeeded.  
Quarterly: restore to isolated DB and run validation checklist.

**Current status:** PHASE 6.1 **BLOCKED** — VPS not deployed from this environment; external backups **NOT CONFIGURED**; restore **NOT VERIFIED**.

---

## Failure behavior

| Dependency | Request path | Background path |
|---|---|---|
| PostgreSQL down | Booking/payment APIs fail loudly (5xx); no silent success | Worker cannot persist; tasks retry/fail |
| Redis down | Cache/throttle degrade (IGNORE_EXCEPTIONS on cache); readiness 503 if Redis required | Celery cannot broker; tasks not queued — use logs/alerts |
| Celery worker down | HTTP booking still commits; WhatsApp stays QUEUED until worker returns | Delivery delayed |
| Celery Beat down | No new due reminder/retention scans | Existing queued messages still process |
| WhatsApp provider down | Booking succeeds; message FAILED/retry per task rules | No appointment corruption |
| Razorpay down | Order create/verify fails with API error; appointment payment stays pending/failed correctly | Webhooks retry at provider; our handler is idempotent |
| Google down | Connect/sync errors surfaced to owner | Booking unaffected |

---

## Incident response basics

1. Check `/health/ready/` and platform status (DB, Redis).
2. Check worker/Beat process presence and error logs (`messaging.tasks`, `payments`, `celery`).
3. For payment webhook issues: inspect `PaymentWebhookEvent` rows; fix signature/secret; allow provider retry.
4. For data loss: follow restore procedure — never restore onto prod without decision record.
5. Page on-call; capture timeline.

---

## Monitoring (minimum)

| Signal | Status |
|---|---|
| Application error logs (stdout) | **PREPARED** (compose json-file) |
| Celery task exception logs | **PREPARED** |
| Webhook failure logs | **PREPARED** |
| Health probes | **PREPARED** (`/health/live/`, `/health/ready/`) |
| Backup failure alerts (`ALERT_CMD`) | **NOT CONFIGURED** |
| Central APM/Sentry | **NOT CONFIGURED** |
| Worker/Beat uptime monitors | **NOT CONFIGURED** |
| Disk / container health monitors | **NOT CONFIGURED** |

Docker logs alone are not production monitoring.

---

## Rate limiting

Production uses Redis cache backend when `REDIS_URL` is set; DRF throttles share that cache.

Current public rates (`REST_FRAMEWORK.DEFAULT_THROTTLE_RATES`):

- `public_booking_availability`: 120/min
- `public_booking_write`: 30/min
- `public_catalog`: 120/min
- `public_quickcard_events`: 60/min
- `public_payment_write`: 30/min

LocMem throttling is **not** acceptable when `DJANGO_ENV=production`.
