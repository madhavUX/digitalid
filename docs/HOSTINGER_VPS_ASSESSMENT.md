# Hostinger VPS Production Assessment

**Status:** Phase 6.1 **BLOCKED** — infrastructure **PREPARED IN CODE**, VPS **NOT DEPLOYED** from this environment.  
**Date:** 2026-10-01  

Do **not** treat this as production readiness.

---

## Verdict

| Question | Answer |
|---|---|
| Hostinger VPS technically suitable? | **Yes, in principle** |
| Production compose prepared? | **YES** |
| Agent has VPS SSH access? | **NO** |
| Deployed on VPS? | **NO** |
| Production PostgreSQL | **PREPARED / NOT DEPLOYED** |
| External backups | **PREPARED scripts / NOT CONFIGURED** |
| Restore / RPO / RTO verified? | **NO** |
| Launch blocker | **OPEN** |

**Hostinger VPS specifications and access must be provided by the operator.**

---

## READY IN CODE vs MANUAL vs NOT VERIFIED

| Item | State |
|---|---|
| Dev `docker-compose.yml` | PREPARED (local only — do not deploy) |
| Production compose (7 services) | **PREPARED** |
| Private DB alias `pg.digitalid.internal` | **PREPARED** (E010) |
| Caddy / Gunicorn / Next.js prod image | **PREPARED** |
| `.env.production.example` | **PREPARED** |
| `scripts/postgres_backup.sh` | **PREPARED** |
| `scripts/postgres_restore_drill.sh` | **PREPARED** |
| VPS SSH / DNS / TLS live | **REQUIRES MANUAL VPS CONFIGURATION** |
| External backup pipeline live | **NOT CONFIGURED** |
| Isolated restore drill | **NOT VERIFIED** |
| Monitoring / alerting | **NOT CONFIGURED** |

---

## Target architecture

```
Hostinger VPS
  ├── Caddy (:80/:443)     ← only public app ports
  ├── frontend (Next.js)
  ├── web (Django/gunicorn)
  ├── worker (Celery)
  ├── beat (Celery, single)
  ├── postgres             ← internal; alias pg.digitalid.internal
  └── redis                ← internal; password required

PostgreSQL backups → EXTERNAL storage (required; not VPS-only)
```

---

## Deploy commands (manual on VPS — not executed here)

```bash
cp .env.production.example .env.production
# edit secrets on the VPS only

docker compose -f docker-compose.production.yml --env-file .env.production up -d --build

curl -fsS http://127.0.0.1/health/live/
curl -fsS http://127.0.0.1/health/ready/
docker compose -f docker-compose.production.yml --env-file .env.production ps
```

Never: `docker compose down -v` on production. Never delete `postgres_data`.

---

## Firewall

**Public:** 80, 443, 22 (SSH restricted).  
**Never public:** 5432, 6379.  
**Verification of live firewall:** **NOT VERIFIED** (requires VPS).

---

## External backups

`scripts/postgres_backup.sh` + `scripts/postgres_restore_drill.sh`.  
See `docs/DATABASE_BACKUP_RESTORE.md`.  
**NOT CONFIGURED / NOT VERIFIED** until operator sets `EXTERNAL_BACKUP_CMD` and runs drills.
