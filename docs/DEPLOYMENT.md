# BookAnything Deployment

Safe, repeatable production deployment for Hostinger KVM VPS.

**Isolation rule:** This stack uses Docker Compose project **`bookanything`**.  
It must **not** modify, stop, or share ports/volumes with **WebGuardSphere** (`https://webguardsphere.com/`).

Do **not** deploy from Cursor without explicit SSH + operator approval.  
This document prepares repository automation only.

---

## Recommended VPS Resource Profile

| Resource | Recommendation |
|---|---|
| CPU | **1 vCPU** (MVP / shared-server profile) |
| RAM | **4 GB** total host RAM (shared with WebGuardSphere) |
| Disk | **≥ 20 GB free** for images + Postgres volume + logs (this VPS has ~45 GB free — OK) |
| Swap | **2 GB swap file recommended** on the host before production (manual; see below) |

Expected BookAnything services (Compose project `bookanything`):

- PostgreSQL (Docker, isolated volume)
- Redis (Docker, isolated — **not** host `127.0.0.1:6379`)
- Django / Gunicorn (1 worker)
- Celery Worker (concurrency 1, solo pool)
- Celery Beat (exactly one)
- Next.js (`next start`)

This is an **MVP / shared-server** profile. It makes no traffic or capacity guarantees. Higher traffic needs more CPU/RAM or a dedicated host.

### Low-resource runtime defaults

| Component | Setting | Rationale |
|---|---|---|
| Gunicorn workers | **1** | Match 1 vCPU; avoid process fan-out |
| Gunicorn threads | **2** | Light concurrency without extra processes |
| Gunicorn timeout / graceful / keep-alive | 60 / 30 / 5 | Stable request handling |
| Gunicorn max-requests (+ jitter) | 500 (+50) | Recycle workers to limit memory growth |
| Celery pool / concurrency | **solo / 1** | No prefork children on 1 vCPU |
| Celery Beat | 1 container | Never scale Beat |
| Postgres `shared_buffers` | 128MB | Small footprint beside WG MySQL |
| Postgres `max_connections` | 40 | Fits 1 web + worker + beat + ops |
| Redis `maxmemory` | 96mb + `allkeys-lru` | Cap BA Redis only |
| Next.js `NODE_OPTIONS` | `--max-old-space-size=384` | Soft Node heap cap |
| Docker logs | json-file `5m` × 3 | Prevent unbounded disk use |
| Hard `mem_limit` | **not set** | Avoid OOM-killing Postgres/Django under brief spikes |

### Manual swap (infrastructure — not created by this repo)

The VPS currently reports **0 GB swap**. A small swap file reduces OOM risk when WebGuardSphere and BookAnything spike together. **Do this on the VPS as root; do not run from Cursor.**

```bash
# Example: 2 GiB swap file (operator-owned; verify free disk first)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo sysctl vm.swappiness=10
```

Swap is **recommended**, not a hard deploy-script requirement. This repo does **not** claim swap has been created.

---

## Architecture (shared VPS)

```
Hostinger VPS (~1 vCPU / 4 GB)
├── Host Nginx (:80/:443)          ← WebGuardSphere + BookAnything server blocks
│     ├── webguardsphere.com       ← DO NOT MODIFY
│     └── book.example.com         ← MANUAL: deploy/nginx.host-snippet.conf
│           ├── /api /health /admin /static → 127.0.0.1:18080
│           └── /*                          → 127.0.0.1:13000
├── WebGuardSphere (untouched)
│     ├── MySQL 127.0.0.1:3306
│     ├── Redis 127.0.0.1:6379
│     └── Laravel API 127.0.0.1:8000
└── Compose project: bookanything
      ├── bookanything-postgres    (bookanything_postgres_data)
      ├── bookanything-redis       (internal only; NOT host :6379)
      ├── bookanything-web         gunicorn 1 worker → 127.0.0.1:18080
      ├── bookanything-worker      celery solo concurrency=1
      ├── bookanything-beat        exactly one
      └── bookanything-frontend    next start → 127.0.0.1:13000
```

- Do **not** bind BookAnything to `0.0.0.0:80` / `0.0.0.0:443`.
- Do **not** use host Redis or WebGuardSphere MySQL.
- Do **not** enable compose profile `standalone-edge` beside WebGuardSphere.

Files:

| File | Role |
|---|---|
| `docker-compose.production.yml` | Project `bookanything` + low-resource defaults |
| `./deploy.sh` | Root wrapper |
| `scripts/deploy.sh` | Deploy logic (backup gate unchanged) |
| `deploy/nginx.host-snippet.conf` | **Manual** host Nginx server block (preferred) |
| `deploy/caddy.host-snippet.caddyfile` | Alternate if edge were Caddy |
| `deploy/Caddyfile` | Standalone-edge only |
| `.env.production` | Secrets on VPS only (never commit) |

---

## Normal deployment

```bash
cd /opt/bookanything
./deploy.sh
```

Optional git update:

```bash
DEPLOY_PULL_GIT=1 ./deploy.sh
```

What `./deploy.sh` does:

1. Verifies Docker + `.env.production` + compose file  
2. Shows current BookAnything containers/ports/project (not WebGuardSphere)  
3. Optional `git pull --ff-only` when `DEPLOY_PULL_GIT=1`  
4. Builds images; starts postgres/redis; **backup gate**; web → migrate → collectstatic → worker/beat/frontend  
5. Waits for healthchecks; probes `/health/live/`, `/health/ready/`, frontend loopback  
6. Exits non-zero on failure  

It never runs `docker system prune`, `docker volume prune`, or unscoped `docker compose down`.  
`ALLOW_DEPLOY_WITHOUT_BACKUP` remains **off** unless explicitly set.

---

## First-time VPS setup

```bash
# 0) Recommended: create host swap (see above) — manual on VPS
# 1) Install Docker Engine + Compose plugin if missing
# 2) Clone or copy the repo
sudo mkdir -p /opt/bookanything
sudo chown "$USER":"$USER" /opt/bookanything
cd /opt/bookanything
# git clone <repo-url> .

# 3) Production env (never commit)
cp .env.production.example .env.production
chmod 600 .env.production
# edit secrets; keep GUNICORN_WORKERS=1 and CELERY_CONCURRENCY=1

# 4) Make scripts executable
chmod +x deploy.sh scripts/deploy.sh scripts/postgres_backup.sh scripts/postgres_restore_drill.sh

# 5) First bootstrap (backup not yet configured)
ALLOW_DEPLOY_WITHOUT_BACKUP=1 ./deploy.sh

# 6) MANUAL host Nginx — add deploy/nginx.host-snippet.conf as a NEW server block
#    Do NOT edit webguardsphere.com blocks. Then:
#    sudo nginx -t && sudo systemctl reload nginx

# 7) DNS A/AAAA for BookAnything hostname → VPS IP + TLS (Certbot/Hostinger)

# 8) Configure external backups, then stop using ALLOW_DEPLOY_WITHOUT_BACKUP
```

---

## Backup requirement

### Security policy

| Mode | Behavior |
|---|---|
| Normal `./deploy.sh` | **FAILS** unless `EXTERNAL_BACKUP_CMD` and `GPG_PASSPHRASE_FILE` (or `GPG_RECIPIENT`) are set; then runs encrypted off-VPS backup **after** postgres is healthy and **before** migrate |
| `ALLOW_DEPLOY_WITHOUT_BACKUP=1` | Explicit emergency/bootstrap override — **never enabled by default** |

**Implications of the override:** migrations and deploys can proceed with no recoverable off-VPS copy. A disk failure, botched migration, or accidental volume delete can cause **permanent data loss**. Use only for an empty first bootstrap, then configure backup immediately and never rely on the override for routine deploys.

VPS snapshots alone are **not** sufficient.

Before migrations on a database that already has (or will have) real data:

- Set `EXTERNAL_BACKUP_CMD` and `GPG_PASSPHRASE_FILE` (or `GPG_RECIPIENT`).
- Prefer operator secret files (mode 600), not long-lived secrets in `.env.production`.


---

## Migrations

Deploy runs:

```bash
docker compose -p bookanything -f docker-compose.production.yml --env-file .env.production \
  exec -T web python manage.py migrate --noinput
```

Manual (same project only):

```bash
docker compose -p bookanything -f docker-compose.production.yml --env-file .env.production \
  exec web python manage.py migrate
```

---

## Health checks

```bash
curl -fsS http://127.0.0.1:18080/health/live/
curl -fsS http://127.0.0.1:18080/health/ready/
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:13000/
# After DNS + host Nginx:
curl -fsS https://book.example.com/health/live/
curl -fsS https://book.example.com/health/ready/
```

---

## Logs

Compose uses `json-file` logging with **`max-size: 5m`** and **`max-file: 3`** per BookAnything service (~15 MB/service ceiling) so Docker logs cannot silently fill the ~45 GB free disk.

```bash
cd /opt/bookanything
docker compose -p bookanything -f docker-compose.production.yml --env-file .env.production logs -f web
docker compose -p bookanything -f docker-compose.production.yml --env-file .env.production logs -f worker beat frontend
```

Never paste secrets from logs into tickets.

---

## Restart individual BookAnything services

```bash
docker compose -p bookanything -f docker-compose.production.yml --env-file .env.production restart web
docker compose -p bookanything -f docker-compose.production.yml --env-file .env.production restart worker
docker compose -p bookanything -f docker-compose.production.yml --env-file .env.production restart beat
docker compose -p bookanything -f docker-compose.production.yml --env-file .env.production restart frontend
```

Never scale beat: keep exactly one `bookanything-beat`.

---

## Rollback

Simple, manual rollback (no automatic risky rollback).

**Does not delete PostgreSQL volumes.** Redeploy only rebuilds/recreates BookAnything app containers for project `bookanything`.

```bash
cd /opt/bookanything
git log --oneline -5
git checkout <previous_good_commit>
./deploy.sh
# Prefer backup configured. Use ALLOW_DEPLOY_WITHOUT_BACKUP=1 only if policy allows.
# If host Nginx unchanged, no WebGuardSphere action needed.
```

Never run `docker compose down -v`, `docker volume prune`, or `docker volume rm bookanything_postgres_data` for rollback.

Image tags `bookanything-web:latest` / `bookanything-frontend:latest` are overwritten on build — prefer **git commit** rollback then rebuild.  
Database content rollback requires an isolated restore (`scripts/postgres_restore_drill.sh`) — never restore onto production casually.

---

## Nginx / domain (WebGuardSphere isolation)

Preferred on this VPS (Nginx owns the edge):

1. Leave all `webguardsphere.com` server blocks untouched.  
2. Add a **new** `server` from `deploy/nginx.host-snippet.conf`.  
3. Point BookAnything DNS at the same VPS; configure TLS with your existing Certbot/Hostinger process.  
4. `sudo nginx -t && sudo systemctl reload nginx` — do not restart WebGuardSphere containers/services.  
5. Do **not** run BookAnything with `--profile standalone-edge`.  
6. Do **not** proxy BookAnything to `127.0.0.1:8000`, `:6379`, or `:3306`.

Alternate: `deploy/caddy.host-snippet.caddyfile` only if the edge were Caddy (not this VPS).

---

## Static / frontend / Django admin

- Next.js: multi-stage production image; `npm run build` at image build; `npm run start` at runtime; production `node_modules` only.  
- Django API/admin: Gunicorn + **WhiteNoise** + `collectstatic` (image build + deploy).  
- Public UI paths `/owner`, `/book`, `/q`, `/site` remain on Next.js.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Port conflict on 80/443 | `standalone-edge` off; Nginx owns edge |
| Clash with WG API | BookAnything must use `127.0.0.1:18080`, never `:8000` |
| Accidental host Redis | BA Redis is Docker-internal only; not `127.0.0.1:6379` |
| Deploy fails backup gate | Configure backup or first-boot `ALLOW_DEPLOY_WITHOUT_BACKUP=1` |
| health/ready 503 | postgres/redis not healthy; `compose ps` / logs |
| Frontend 502 via HTTPS | Nginx snippet + loopback `18080`/`13000` |
| OOM / thrashing | Confirm swap; keep workers=1 / celery solo; check WG + BA RSS |
| Wrong containers restarted | Always `-p bookanything` |
| Multiple beats | `docker ps \| grep bookanything-beat` — stop extras |

---

## Related docs

- `docs/PRODUCTION_RUNBOOK.md`  
- `docs/DATABASE_BACKUP_RESTORE.md`  
- `docs/HOSTINGER_VPS_ASSESSMENT.md`  
- `docs/ROADBLOCK_REPORT.md`
