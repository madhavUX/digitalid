#!/usr/bin/env sh
# Production PostgreSQL backup for Hostinger VPS (operator-owned).
#
# Status: PREPARED IN REPO — NOT CONFIGURED until run on the VPS with real
# secrets and EXTERNAL_BACKUP_CMD pointing at off-VPS storage.
#
# Required env (never commit real values):
#   COMPOSE_FILE          default: docker-compose.production.yml
#   COMPOSE_ENV_FILE      default: .env.production
#   POSTGRES_USER         required
#   POSTGRES_DB           required
#   BACKUP_DIR            default: /var/backups/bookanything
#   BACKUP_RETENTION_DAYS default: 30 (local encrypted copies only)
#   GPG_PASSPHRASE_FILE   path to passphrase file (mode 600) OR
#   GPG_RECIPIENT         public-key recipient for asymmetric encrypt
#   EXTERNAL_BACKUP_CMD   shell command; receives encrypted file path as $1
#                         example: rclone copy "$1" remote:bookanything-backups/
#   ALERT_CMD             optional; run on failure with message as $1
#
# VPS snapshots alone are NOT sufficient. External upload is mandatory.

set -eu

fail() {
  msg=$1
  echo "ERROR: $msg" >&2
  if [ -n "${ALERT_CMD:-}" ]; then
    # shellcheck disable=SC2086
    eval "$ALERT_CMD" "\"$msg\"" || true
  fi
  exit 1
}

COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.production.yml}
COMPOSE_ENV_FILE=${COMPOSE_ENV_FILE:-${ENV_FILE:-.env.production}}
COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-bookanything}
WORKDIR=${BACKUP_DIR:-/var/backups/bookanything}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-30}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DUMP="$WORKDIR/bookanything-$STAMP.dump"
ENC="$DUMP.gpg"

[ -n "${POSTGRES_USER:-}" ] || fail "POSTGRES_USER is required"
[ -n "${POSTGRES_DB:-}" ] || fail "POSTGRES_DB is required"
[ -n "${EXTERNAL_BACKUP_CMD:-}" ] || fail "EXTERNAL_BACKUP_CMD is required (off-VPS upload)"

if [ -z "${GPG_PASSPHRASE_FILE:-}" ] && [ -z "${GPG_RECIPIENT:-}" ]; then
  fail "Set GPG_PASSPHRASE_FILE or GPG_RECIPIENT for encryption"
fi

mkdir -p "$WORKDIR"
chmod 700 "$WORKDIR" 2>/dev/null || true

echo "dumping PostgreSQL (custom format) via compose exec..."
docker compose -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" --env-file "$COMPOSE_ENV_FILE" exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl >"$DUMP" \
  || fail "pg_dump failed"

echo "encrypting dump..."
if [ -n "${GPG_RECIPIENT:-}" ]; then
  gpg --batch --yes --encrypt --recipient "$GPG_RECIPIENT" -o "$ENC" "$DUMP" \
    || fail "gpg encrypt failed"
else
  [ -f "$GPG_PASSPHRASE_FILE" ] || fail "GPG_PASSPHRASE_FILE not found"
  gpg --batch --yes --symmetric --cipher-algo AES256 \
    --passphrase-file "$GPG_PASSPHRASE_FILE" -o "$ENC" "$DUMP" \
    || fail "gpg encrypt failed"
fi

rm -f "$DUMP"

echo "uploading encrypted dump to external storage..."
# EXTERNAL_BACKUP_CMD is operator-defined; pass the encrypted file path.
# shellcheck disable=SC2086
eval "$EXTERNAL_BACKUP_CMD" "\"$ENC\"" || fail "EXTERNAL_BACKUP_CMD failed"

echo "pruning local encrypted dumps older than ${RETENTION_DAYS} days..."
find "$WORKDIR" -type f -name 'bookanything-*.dump.gpg' -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true

echo "backup_ok stamp=$STAMP file=$(basename "$ENC")"
