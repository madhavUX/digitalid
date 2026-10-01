# Platform Roadblock Report

Phase **6.4 Low-resource VPS production profile** (repository only)  
Date: 2026-10-01  

**Do not claim Hostinger/VPS verification. No remote deploy from this phase.**

---

## PHASE 6.4 SUMMARY

| Item | Status |
|---|---|
| Target profile | 1 vCPU / ~4 GB shared with WebGuardSphere |
| Gunicorn workers | **1** (default) |
| Celery | solo pool, concurrency **1**; Beat ×1 |
| Postgres/Redis | Isolated Docker; conservative memory settings |
| Host Redis/MySQL/API | **Not used** by BookAnything |
| Edge | Host **Nginx** snippet (`deploy/nginx.host-snippet.conf`) |
| Swap | Documented recommendation only — **not created** |
| Backup gate | Unchanged (still required for normal `./deploy.sh`) |
| Live VPS deploy | **NOT EXECUTED** |

Repo recommendation: **READY FOR MANUAL VPS DEPLOYMENT** (operator-executed).  
Live production verification (HTTPS/DNS/backups/restore) remains **OPEN**.
