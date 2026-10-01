# Production Readiness

Phase **6.1** — Hostinger VPS deployment & verification.

**Current verdict: NOT READY.** Launch blocker **OPEN**.

Agent environment has **no Hostinger SSH / `.env.production` / deploy credentials**.  
Nothing below marked VERIFIED without a live VPS test.

```
Hostinger VPS
  ├── Caddy (:80/:443)
  ├── Django (gunicorn)
  ├── Next.js
  ├── PostgreSQL (pg.digitalid.internal)
  ├── Redis (password)
  ├── Celery Worker
  └── Celery Beat (single)

Backups → EXTERNAL storage (scripts prepared; NOT CONFIGURED on VPS)
```

---

## Status matrix

| Area | State |
|---|---|
| Production compose / Caddy / frontend image | **PREPARED** |
| E010-safe DB alias `pg.digitalid.internal` | **PREPARED** (enforced) |
| Health endpoints `/health/live/` `/health/ready/` | **PREPARED** |
| Backup script `scripts/postgres_backup.sh` | **PREPARED** |
| Restore drill script `scripts/postgres_restore_drill.sh` | **PREPARED** |
| VPS deployed | **NOT DEPLOYED** |
| HTTPS / DNS | **NOT VERIFIED** |
| Firewall 5432/6379 blocked publicly | **NOT VERIFIED** |
| External backups configured + executed | **NOT CONFIGURED** |
| Restore drill | **NOT VERIFIED** |
| RPO / RTO | **NOT VERIFIED** |
| External monitoring / backup alerts | **NOT CONFIGURED** |
| Launch blocker | **OPEN** |

---

## Production readiness gate (must all pass)

| Gate | Status |
|---|---|
| VPS deployed | ☐ |
| PostgreSQL operational | ☐ |
| Redis operational | ☐ |
| Django operational | ☐ |
| Celery Worker operational | ☐ |
| Celery Beat operational (exactly one) | ☐ |
| Next.js operational | ☐ |
| Caddy operational | ☐ |
| HTTPS verified | ☐ |
| DNS verified | ☐ |
| 5432 blocked | ☐ |
| 6379 blocked | ☐ |
| `DJANGO_DEBUG=false` | ☐ |
| Production secrets configured securely | ☐ |
| Health endpoints verified | ☐ |
| Admin/API verified | ☐ |
| Webhook routes verified (HTTPS) | ☐ |
| External backups configured | ☐ |
| Backup successfully executed | ☐ |
| Restore drill successfully executed | ☐ |
| RPO measured | ☐ |
| RTO measured | ☐ |
| Failure alerting configured | ☐ |
| Rollback/recovery procedure documented | ☐ (procedure in docs; live drill ☐) |

**All unchecked → production NOT READY.**

See `docs/HOSTINGER_VPS_ASSESSMENT.md`, `docs/PRODUCTION_RUNBOOK.md`, `docs/ROADBLOCK_REPORT.md`.
