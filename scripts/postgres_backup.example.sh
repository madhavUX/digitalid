#!/usr/bin/env sh
# EXAMPLE ONLY — prefer scripts/postgres_backup.sh on the VPS.
# Kept for documentation references from Phase 6.0.3.
#
# Production path:
#   export POSTGRES_USER=... POSTGRES_DB=... EXTERNAL_BACKUP_CMD='rclone copy "$1" remote:digitalid-backups/'
#   export GPG_PASSPHRASE_FILE=/root/.secrets/backup-gpg-pass
#   ./scripts/postgres_backup.sh
#
# Status remains NOT CONFIGURED until EXTERNAL_BACKUP_CMD and encryption
# secrets exist on the Hostinger VPS and a successful run is recorded.

echo "Use scripts/postgres_backup.sh — this file is a pointer only."
exit 1
