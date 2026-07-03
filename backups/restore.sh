#!/bin/sh
set -eu

# ── Restore an encrypted backup — SQL restore only ─────────────
# Usage: ./restore.sh <backup_file.sql.gz.gpg>
#
# This script runs in the backup image (postgres-client + gnupg) and
# performs ONLY the database restore. It is reachable inside the
# ``backup`` service at ``/backups/restore.sh`` via the bind mount.
#
# GDPR note: the deletion-replay step is a SEPARATE, second step that
# MUST run in a Python/Django-bearing container (the ``huey`` or
# ``backend`` service) — it is NOT run here, because this image has no
# Python/Django. The instructions are printed at the end and in
# docs/security/restore-drill.md.
# ───────────────────────────────────────────────────────────────

BACKUP_FILE="${1:?Usage: restore.sh <backup_file.sql.gz.gpg>}"

DB_HOST="${POSTGRES_HOST:-postgres}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB}"
DB_USER="${POSTGRES_USER}"

export PGPASSWORD="${POSTGRES_PASSWORD}"
BACKUP_ENCRYPTION_KEY="${BACKUP_ENCRYPTION_KEY:?BACKUP_ENCRYPTION_KEY must be set}"

echo "[$(date)] Decrypting and restoring ${BACKUP_FILE}..."

# ash has no ``pipefail``: piping gpg | gunzip | psql would let a failed
# decrypt feed EMPTY input to psql, which then exits 0 and we'd print
# "Database restored." over a no-op. Stage each step as its own command so
# ``set -e`` catches a failure at the point it happens, and make psql abort on
# the first SQL error (``ON_ERROR_STOP=1``) instead of committing a partial
# restore. The temp files live in the backup volume and are removed on exit.
TMP_GZ="${BACKUP_FILE}.dec.gz"
TMP_SQL="${BACKUP_FILE}.dec.sql"
cleanup() { rm -f "$TMP_GZ" "$TMP_SQL"; }
trap cleanup EXIT

gpg --batch --yes --quiet --decrypt \
    --passphrase "$BACKUP_ENCRYPTION_KEY" \
    --output "$TMP_GZ" \
    "$BACKUP_FILE"

gunzip -c "$TMP_GZ" > "$TMP_SQL"

psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    --single-transaction \
    -v ON_ERROR_STOP=1 \
    -f "$TMP_SQL"

echo "[$(date)] Database restored."
echo ""
echo "============================================================"
echo " ACTION REQUIRED — re-apply pending GDPR deletions"
echo "============================================================"
echo " This was a SQL-only restore. Personal data that was lawfully"
echo " erased AFTER this backup was taken has just been"
echo " re-materialised. Replay those deletions from a Python/Django"
echo " container (this backup image has no Python). Run:"
echo ""
echo "     docker compose exec huey python manage.py replay_gdpr_deletions"
echo ""
echo " (the 'backend' service works too.) See"
echo " docs/security/restore-drill.md for the full runbook."
echo "============================================================"
