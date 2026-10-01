#!/usr/bin/env bash
# BookAnything production deploy — scoped ONLY to Compose project "bookanything".
# Never touches unrelated containers (e.g. WebGuardSphere).
#
# Usage (on the VPS):
#   cd /opt/bookanything && ./deploy.sh
#
# Optional env:
#   DEPLOY_PULL_GIT=1              git pull --ff-only before build
#   ALLOW_DEPLOY_WITHOUT_BACKUP=1  first bootstrap ONLY (never default)
#   DEPLOY_TIMEOUT_SECS=180        wait for healthy services
#
# Backup gate (security):
#   Normal ./deploy.sh REQUIRES EXTERNAL_BACKUP_CMD + GPG configuration and
#   runs scripts/postgres_backup.sh after postgres is healthy, before migrate.
#   Skipping backup without ALLOW_DEPLOY_WITHOUT_BACKUP=1 is a hard failure.
#   Using the override on a database with real data risks unrecoverable loss.
#
# Never prints secret values.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-bookanything}"
DEPLOY_TIMEOUT_SECS="${DEPLOY_TIMEOUT_SECS:-180}"

log() { printf '[deploy] %s\n' "$*"; }
err() { printf '[deploy] ERROR: %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed"
}

compose() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

env_get() {
  local key=$1
  local line
  line="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | head -n1 || true)"
  printf '%s' "${line#${key}=}" | tr -d '\r'
}

service_from_container() {
  case "$1" in
    bookanything-postgres) printf 'postgres' ;;
    bookanything-redis) printf 'redis' ;;
    bookanything-web) printf 'web' ;;
    bookanything-frontend) printf 'frontend' ;;
    bookanything-worker) printf 'worker' ;;
    bookanything-beat) printf 'beat' ;;
    *) printf '%s' "$1" ;;
  esac
}

load_deploy_knobs() {
  BOOKANYTHING_WEB_HOST_PORT="$(env_get BOOKANYTHING_WEB_HOST_PORT)"
  BOOKANYTHING_FRONTEND_HOST_PORT="$(env_get BOOKANYTHING_FRONTEND_HOST_PORT)"
  PUBLIC_APP_URL="$(env_get PUBLIC_APP_URL)"
  EXTERNAL_BACKUP_CMD="$(env_get EXTERNAL_BACKUP_CMD)"
  GPG_PASSPHRASE_FILE="$(env_get GPG_PASSPHRASE_FILE)"
  GPG_RECIPIENT="$(env_get GPG_RECIPIENT)"
  BOOKANYTHING_WEB_HOST_PORT="${BOOKANYTHING_WEB_HOST_PORT:-18080}"
  BOOKANYTHING_FRONTEND_HOST_PORT="${BOOKANYTHING_FRONTEND_HOST_PORT:-13000}"
}

show_preflight() {
  log "Compose project: $PROJECT_NAME"
  log "Compose file:    $COMPOSE_FILE"
  log "Env file:        $ENV_FILE (exists; contents not printed)"
  log "Web loopback:    127.0.0.1:${BOOKANYTHING_WEB_HOST_PORT}"
  log "Frontend loop:   127.0.0.1:${BOOKANYTHING_FRONTEND_HOST_PORT}"
  log "Current BookAnything containers:"
  compose ps || true
  log "Published BookAnything ports (project-scoped):"
  docker ps --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
    --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}' || true
}

backup_configured() {
  [ -n "${EXTERNAL_BACKUP_CMD}" ] && {
    [ -n "${GPG_PASSPHRASE_FILE}" ] || [ -n "${GPG_RECIPIENT}" ]
  }
}

backup_gate() {
  # Called only after bookanything-postgres is healthy.
  if backup_configured; then
    log "Backup mechanism appears configured (EXTERNAL_BACKUP_CMD + GPG)."
    if [ -x "$ROOT_DIR/scripts/postgres_backup.sh" ]; then
      log "Running pre-migrate backup via scripts/postgres_backup.sh ..."
      export EXTERNAL_BACKUP_CMD GPG_PASSPHRASE_FILE GPG_RECIPIENT
      POSTGRES_USER="$(env_get POSTGRES_USER)"
      POSTGRES_DB="$(env_get POSTGRES_DB)"
      export POSTGRES_USER POSTGRES_DB
      export COMPOSE_FILE ENV_FILE
      export COMPOSE_PROJECT_NAME="$PROJECT_NAME"
      "$ROOT_DIR/scripts/postgres_backup.sh" || die "Pre-migrate backup failed"
    else
      die "Backup configured but scripts/postgres_backup.sh is missing/not executable"
    fi
    return 0
  fi

  if [ "${ALLOW_DEPLOY_WITHOUT_BACKUP:-0}" = "1" ]; then
    log "WARNING: Backup is NOT CONFIGURED. Continuing because ALLOW_DEPLOY_WITHOUT_BACKUP=1"
    log "WARNING: This override is for empty first bootstrap only."
    log "WARNING: Deploying without an off-VPS encrypted backup risks permanent data loss."
    return 0
  fi

  die "Backup not configured. Normal ./deploy.sh requires EXTERNAL_BACKUP_CMD and GPG_PASSPHRASE_FILE (or GPG_RECIPIENT). First empty bootstrap only: ALLOW_DEPLOY_WITHOUT_BACKUP=1. See docs/DEPLOYMENT.md"
}

wait_container_healthy() {
  local name=$1
  local svc
  svc="$(service_from_container "$name")"
  local deadline=$((SECONDS + DEPLOY_TIMEOUT_SECS))
  log "Waiting for ${name} healthy (timeout ${DEPLOY_TIMEOUT_SECS}s)..."
  while true; do
    local status
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || echo missing)"
    if [ "$status" = "healthy" ]; then
      log "${name} is healthy"
      return 0
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      compose logs --tail=80 "$svc" 2>/dev/null || true
      die "Timed out waiting for ${name} (status=${status})"
    fi
    sleep 3
  done
}

verify_http() {
  local web_url="http://127.0.0.1:${BOOKANYTHING_WEB_HOST_PORT}"
  local fe_url="http://127.0.0.1:${BOOKANYTHING_FRONTEND_HOST_PORT}"
  local code

  log "Checking ${web_url}/health/live/"
  curl -fsS "${web_url}/health/live/" >/dev/null || die "health/live failed"
  log "Checking ${web_url}/health/ready/"
  curl -fsS "${web_url}/health/ready/" >/dev/null || die "health/ready failed"
  log "Running Django system check inside web container"
  compose exec -T web python manage.py check || die "manage.py check failed"
  log "Checking frontend at ${fe_url}/"
  code="$(curl -fsS -o /dev/null -w '%{http_code}' "${fe_url}/" || true)"
  case "$code" in
    200|301|302|307|308) ;;
    *) die "frontend HTTP check failed (status=${code:-none})" ;;
  esac
  if [ -n "${PUBLIC_APP_URL}" ]; then
    log "PUBLIC_APP_URL is set — verify DNS + host Caddy routing manually (not auto-probed)"
  fi
}

main() {
  require_cmd docker
  require_cmd curl
  docker info >/dev/null 2>&1 || die "Docker daemon is not available"
  [ -f "$COMPOSE_FILE" ] || die "Missing $COMPOSE_FILE"
  [ -f "$ENV_FILE" ] || die "Missing $ENV_FILE — copy from .env.production.example on the VPS"

  load_deploy_knobs
  show_preflight

  if [ "${DEPLOY_PULL_GIT:-0}" = "1" ]; then
    require_cmd git
    log "DEPLOY_PULL_GIT=1 — pulling fast-forward only"
    git pull --ff-only || die "git pull --ff-only failed"
  else
    log "Skipping git pull (set DEPLOY_PULL_GIT=1 to enable)"
  fi

  log "Building BookAnything images (project=$PROJECT_NAME)"
  compose build web frontend

  log "Starting postgres + redis (BookAnything only)"
  compose up -d postgres redis
  wait_container_healthy bookanything-postgres
  wait_container_healthy bookanything-redis

  # Backup AFTER postgres is up, BEFORE migrate — never default-skip.
  backup_gate

  log "Starting web"
  compose up -d --no-deps web
  wait_container_healthy bookanything-web

  log "Running migrations inside bookanything-web"
  compose exec -T web python manage.py migrate --noinput || die "migrate failed"

  log "Refreshing collected static files (WhiteNoise / admin)"
  compose exec -T web python manage.py collectstatic --noinput || die "collectstatic failed"

  log "Starting worker, beat (single), frontend"
  compose up -d --no-deps worker
  compose up -d --no-deps beat
  compose up -d --no-deps frontend
  wait_container_healthy bookanything-frontend

  local beat_count
  beat_count="$(docker ps -q --filter "name=^bookanything-beat$" | wc -l | tr -d ' ')"
  if [ "${beat_count}" != "1" ]; then
    die "Expected exactly one bookanything-beat container, found ${beat_count}"
  fi

  verify_http

  log "Final BookAnything container status:"
  compose ps
  log "Deploy succeeded. Unrelated VPS apps (e.g. WebGuardSphere) were not targeted."
}

main "$@"
