# Database Backup & Restore

Provider-agnostic strategy for BookAnything / DigitalID PostgreSQL.  
Hostinger VPS context: `docs/HOSTINGER_VPS_ASSESSMENT.md`.

## Current status (Phase 6.1)

| Item | Status |
|---|---|
| PHASE 6.1 | **BLOCKED** (no VPS access from agent env; scripts prepared) |
| Production target | Hostinger VPS |
| Production PostgreSQL | Docker on VPS — **PREPARED / NOT DEPLOYED** |
| DB host for E010 | `pg.digitalid.internal` (compose network alias) |
| Backup script | `scripts/postgres_backup.sh` — **PREPARED** |
| Restore drill script | `scripts/postgres_restore_drill.sh` — **PREPARED** |
| Automated DB backups | **NOT CONFIGURED** |
| External backups (off-VPS) | **NOT CONFIGURED** |
| Restore verified | **NO** |
| RPO verified | **NO** |
| RTO verified | **NO** |
| Launch blocker | **OPEN** |

Local `pg_dump`, Compose volumes, and **Hostinger VPS snapshots alone** do **NOT** satisfy the application database backup requirement.

---

## Hostinger VPS + external backups (required design)

```
Hostinger VPS PostgreSQL (pg.digitalid.internal)
        ↓ pg_dump -Fc (scripts/postgres_backup.sh)
        ↓ gpg encrypt (AES256 or recipient key)
        ↓ EXTERNAL_BACKUP_CMD (rclone / S3 CLI / etc.)
EXTERNAL storage (independent of the VPS)
        ↓ scripts/postgres_restore_drill.sh
Isolated PostgreSQL (non-production)
```

Operator scripts (not live until configured on VPS):

- `scripts/postgres_backup.sh`
- `scripts/postgres_restore_drill.sh`

### Still required before VERIFIED

| Step | Status |
|---|---|
| Choose external storage provider | **NOT CONFIGURED** |
| `EXTERNAL_BACKUP_CMD` + GPG secrets on VPS | **NOT CONFIGURED** |
| Schedule (e.g. daily) + retention (≥30 days) | **NOT CONFIGURED** |
| Failure alerting (`ALERT_CMD`) | **NOT CONFIGURED** |
| Successful backup run recorded | **NOT VERIFIED** |
| Isolated restore + measured RPO/RTO | **NOT VERIFIED** |

**RPO:** equals configured backup interval only after a successful scheduled run is observed — do not invent.  
**RTO:** equals measured restore-drill duration (+ cutover) — do not invent.

Suggested provisional operator target (not measured): daily dumps → theoretical RPO ≈ 24h.

---

## Production PostgreSQL requirements

Keep the application **provider-agnostic**. Do not hard-code AWS RDS or any cloud vendor in application code.

| Requirement | Notes |
|---|---|
| Production Postgres | Managed cloud **or** Hostinger VPS Docker-internal (not a developer laptop) |
| Version | Compatible with Django 5.2 / `psycopg` v3 (PostgreSQL 14+ recommended; 16 in local Compose) |
| No public 5432 | Required on Hostinger |
| Automated backups | Required; **external** copy required on VPS |
| Encryption | At rest for backup artifacts; TLS when DB is not node-local-only |
| Credentials | Strong unique password; env/secrets only |
| `DATABASE_URL` | Sole production connection source — never commit |
| Isolated restore | Required for Phase 6.0.3 |
| Documented RPO/RTO | Record **observed** values from the drill — do not invent SLAs |

Operator metadata (deploy notes only; not read by the app):

- `PRODUCTION_DB_PROVIDER`
- `PRODUCTION_DB_REGION`
- `PRODUCTION_DB_BACKUP_POLICY`

Application connection:

```text
DATABASE_URL=postgres://USER:PASSWORD@MANAGED_HOST:5432/DBNAME?sslmode=require
DJANGO_ENV=production
```

`DJANGO_ENV=production` rejects localhost / Docker Compose hosts (`digitalid.E010`) and requires Redis, CSRF origins, etc. (`digitalid.E001`–`E010`).

---

## What counts as Phase 6.0.3 success

All of the following must be true against the **Hostinger VPS production PostgreSQL** (Docker-internal `pg.digitalid.internal`) with **external** backups:

1. Production PostgreSQL running on the Hostinger VPS (not a developer laptop)
2. Automated `pg_dump` (or equivalent) to **external** storage enabled (off-VPS)
3. Backup existence confirmed (timestamp / opaque reference — no secrets in docs)
4. Isolated restore performed (never onto production)
5. Restored schema verified
6. Restored migrations verified (`showmigrations` / expected apps)
7. Restored application data verified (representative counts — no PII in reports)
8. Booking data verified (including occupancy exclusion constraint present)
9. Payment data verified (`PaymentOrder` / `Payment` / `Refund` / webhook ledger)
10. Redis/Celery connectivity verified where applicable (safe/mock providers only)
11. Health checks verified (`/health/live/`, `/health/ready/`)
12. Booking/payment smoke tests verified (mock providers — no live WhatsApp/Razorpay/Google)
13. RPO recorded (from backup frequency / observed lag) — **do not invent**
14. RTO recorded (from restore + smoke duration) — **do not invent**

Until then: **RESTORE VERIFICATION BLOCKED**.

Hostinger VPS snapshots alone do **not** satisfy items 2–4.

---

## Backup strategy (required for production)

Do **not** invent a custom in-app backup daemon. Prefer **managed database backups** from the chosen host.

### Minimum (launch)

1. Automated daily full backup of the primary PostgreSQL database
2. Retention: at least 30 days (or host equivalent)
3. Encryption at rest + TLS in transit
4. Backup storage access limited to ops roles
5. Failure alerting for missed/failed backups
6. Off-host copy that survives primary instance loss

### Recommended

- Continuous PITR / WAL archiving
- Longer weekly/monthly retention
- Cross-region copy for DR

### Provider examples (choose one; document in deploy notes)

| Provider | What to enable |
|---|---|
| AWS RDS / Aurora | Automated backups + retention; optional PITR |
| Google Cloud SQL | Automated backups + PITR |
| Azure Database for PostgreSQL | Backup retention (+ geo-redundant if required) |
| Neon / Supabase / Railway / Render | Platform automated backups; note retention limits |
| Self-hosted Postgres | `pg_basebackup` / WAL archive to encrypted object storage — only if ops-owned |

This repo does **not** hard-code a provider.

---

## Local pg_dump (development only — not production proof)

```bash
pg_dump --format=custom --no-owner --no-acl "$DATABASE_URL" -f digitalid-dev.dump
```

Allowed for: local debugging, moving fixtures between developer machines.  
**Not allowed for:** claiming Phase 6.0.3 complete, resolving the launch blocker, or “production ready” statements.

---

## Restore procedure (isolated verification)

**Never restore over the production database** for a drill.

1. Confirm managed backup exists in the provider console.
2. Restore into an isolated instance/database (new instance preferred).
3. Point an isolated app env at the restore (`DATABASE_URL`, `REDIS_URL`); use mock providers.
4. Prefer **not** running `migrate` unless the dump is intentionally behind code — first confirm schema matches the release.
5. Validate: `manage.py check`, `showmigrations`, representative table counts, booking exclusion constraint, payment relationships.
6. Smoke: `/health/live/`, `/health/ready/`, auth/business/location/catalog/customer/appointment/payment lookups.
7. Record backup selected time, restore start/end, smoke complete → approximate RTO; backup frequency → provisional RPO.

Capture in the drill report (no secrets, no PII):

- `PRODUCTION_DB_PROVIDER` / region (non-secret)
- Backup timestamp / opaque backup id
- Restore duration
- Pass/fail per checklist item above

---

## Validation checklist

- [ ] Managed provider (not laptop Docker)
- [ ] Automated backup enabled + last success known
- [ ] Isolated restore target
- [ ] Schema + migrations OK
- [ ] Representative counts (org/business/location/customer/appointment/payment)
- [ ] Payment FKs and statuses preserved
- [ ] `excl_appointment_staff_occupancy` present
- [ ] Health ready green
- [ ] Redis/Celery safe smoke (optional but preferred)
- [ ] RPO / RTO recorded from this drill

---

## Incident recovery (high level)

1. Declare incident; freeze risky writes if needed.
2. Identify last good backup / PITR target.
3. Restore to **new** instance; validate.
4. Cut over `DATABASE_URL` / DNS.
5. Restart web, Celery worker, Celery Beat.
6. Verify health + sample reads.
7. Post-incident notes.

---

## Limitations

- Soft-deleted rows remain in backups (expected).
- Redis is not a recovery source of truth.
- In-flight Celery tasks may be lost on broker loss; DB state + idempotent tasks recover correctness.
- This document is **not** a verified restore certificate until Phase 6.0.3 passes.
