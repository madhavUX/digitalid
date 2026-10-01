#!/usr/bin/env bash
# Root wrapper — BookAnything only. Does not touch WebGuardSphere.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT_DIR/scripts/deploy.sh" "$@"
