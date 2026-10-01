#!/usr/bin/env sh
# Isolated PostgreSQL restore drill (NEVER restore onto production).
#
# Status: PREPARED IN REPO — NOT VERIFIED until executed against a real
# encrypted backup and an isolated postgres instance.
#
# Required env:
#   ENCRYPTED_BACKUP     path to digitalid-*.dump.gpg
#   GPG_PASSPHRASE_FILE  or GPG_RECIPIENT (must be able to decrypt)
#   RESTORE_DATABASE_URL postgres URL for an ISOLATED database only
#                        e.g. postgres://postgres:postgres@127.0.0.1:55433/digitalid_restore
#   WORKDIR              default: /var/tmp/digitalid-restore-drill
#
# Optional:
#   SKIP_APP_CHECK=1     skip manage.py check against RESTORE_DATABASE_URL
#
# Records timing to stdout for RTO measurement. Do not invent RPO/RTO.

set -eu

fail() {
  echo "ERROR: $1" >&2
  exit 1
}

[ -n "${ENCRYPTED_BACKUP:-}" ] || fail "ENCRYPTED_BACKUP is required"
[ -f "$ENCRYPTED_BACKUP" ] || fail "ENCRYPTED_BACKUP file not found"
[ -n "${RESTORE_DATABASE_URL:-}" ] || fail "RESTORE_DATABASE_URL is required"

case "$RESTORE_DATABASE_URL" in
  *pg.digitalid.internal*|*digitalid-prod*)
    fail "REFUSING: RESTORE_DATABASE_URL looks like production — use an isolated DB"
    ;;
esac

WORKDIR=${WORKDIR:-/var/tmp/digitalid-restore-drill}
mkdir -p "$WORKDIR"
DUMP="$WORKDIR/restore.dump"
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
START_EPOCH=$(date +%s)

echo "restore_drill_start=$START_TS"
echo "encrypted_backup=$(basename "$ENCRYPTED_BACKUP")"

echo "decrypting..."
if [ -n "${GPG_RECIPIENT:-}" ]; then
  gpg --batch --yes --decrypt -o "$DUMP" "$ENCRYPTED_BACKUP" || fail "gpg decrypt failed"
else
  [ -n "${GPG_PASSPHRASE_FILE:-}" ] || fail "GPG_PASSPHRASE_FILE or GPG_RECIPIENT required"
  [ -f "$GPG_PASSPHRASE_FILE" ] || fail "GPG_PASSPHRASE_FILE not found"
  gpg --batch --yes --decrypt --passphrase-file "$GPG_PASSPHRASE_FILE" \
    -o "$DUMP" "$ENCRYPTED_BACKUP" || fail "gpg decrypt failed"
fi

echo "restoring into isolated database (pg_restore --clean --if-exists)..."
pg_restore --clean --if-exists --no-owner --no-acl -d "$RESTORE_DATABASE_URL" "$DUMP" \
  || fail "pg_restore failed"

rm -f "$DUMP"

if [ "${SKIP_APP_CHECK:-0}" != "1" ]; then
  echo "running Django check against restored DB..."
  DATABASE_URL="$RESTORE_DATABASE_URL" DJANGO_ENV=development \
    python manage.py check || fail "manage.py check failed against restore"
  DATABASE_URL="$RESTORE_DATABASE_URL" \
    python manage.py showmigrations || fail "showmigrations failed"
fi

END_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
END_EPOCH=$(date +%s)
DURATION=$((END_EPOCH - START_EPOCH))

echo "restore_drill_finish=$END_TS"
echo "restore_duration_seconds=$DURATION"
echo "restore_drill_result=PASS"
echo "NOTE: Full RTO includes DNS/app cutover time measured during a real recovery drill."
