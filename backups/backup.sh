#!/bin/sh
set -eu

# ── Configuration ──────────────────────────────────────────────
BACKUP_DIR="/backups"
# Uploaded media tree (invoice / delivery-note PDFs, e-invoice XML, tenant
# logos). Mounted read-only into the backup service; empty/absent -> skipped.
MEDIA_DIR="${MEDIA_DIR:-/app/media}"
SCHEDULE="${BACKUP_SCHEDULE:-0 2 * * *}"
# Reject a dump smaller than this many bytes as a failed/empty backup.
BACKUP_MIN_BYTES="${BACKUP_MIN_BYTES:-1000}"
# The absolute path this script is installed at (see backups/Dockerfile). The
# crontab line MUST use it — a bare "/backup.sh" would exec a nonexistent path
# and scheduled backups would silently never run.
SELF="/usr/local/bin/backup.sh"

# NOTE on retention: this container only WRITES backups. Pruning is
# handled by the ``prune_old_backups`` Huey task in
# apps/shared/tenants/tasks.py, which implements the GFS retention
# rule (daily 30d / weekly 52w / monthly forever) for BOTH the
# ``*.sql.gz.gpg`` DB dumps and the ``*.tar.gz.gpg`` media archives
# written here. Keeping pruning out of this script avoids the
# two-systems-fighting-over-the-same-files failure mode.

DB_HOST="${POSTGRES_HOST:-postgres}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB}"
DB_USER="${POSTGRES_USER}"

export PGPASSWORD="${POSTGRES_PASSWORD}"

# GDPR: encryption passphrase (required)
BACKUP_ENCRYPTION_KEY="${BACKUP_ENCRYPTION_KEY:?BACKUP_ENCRYPTION_KEY must be set}"

# Optional off-host push (scaffold). Set RCLONE_REMOTE (e.g.
# "storagebox:jasmin-backups") and provide an rclone config via RCLONE_CONFIG (a
# file mounted read-only into this container) to copy every freshly written,
# already-encrypted artifact off-host. Unset -> local-only backups (a no-op).
RCLONE_REMOTE="${RCLONE_REMOTE:-}"

# ── Helpers ────────────────────────────────────────────────────
# Encrypt stdin -> $1 with the shared AES256 passphrase.
encrypt_gpg() {
    gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase "$BACKUP_ENCRYPTION_KEY" \
        --output "$1"
}

# Copy $1 off-host if RCLONE_REMOTE is configured. No-op (with a warning) when
# rclone isn't installed, so the scaffold never fails a backup.
push_offsite() {
    [ -n "$RCLONE_REMOTE" ] || return 0
    if ! command -v rclone >/dev/null 2>&1; then
        echo "[$(date)] WARN: RCLONE_REMOTE set but rclone not installed; skipping off-host push of $(basename "$1")" >&2
        return 0
    fi
    echo "[$(date)] Pushing $(basename "$1") → ${RCLONE_REMOTE}"
    # Best-effort: a failed off-host push must NOT discard the verified local
    # backup or (in the scheduled case) abort before cron is installed. Warn
    # loudly instead — provisioning + verifying the first real push is the
    # operator go-live step.
    if [ -n "${RCLONE_CONFIG:-}" ]; then
        rclone --config "$RCLONE_CONFIG" copyto "$1" "${RCLONE_REMOTE}/$(basename "$1")" \
            || echo "[$(date)] WARN: off-host push of $(basename "$1") failed" >&2
    else
        rclone copyto "$1" "${RCLONE_REMOTE}/$(basename "$1")" \
            || echo "[$(date)] WARN: off-host push of $(basename "$1") failed" >&2
    fi
}

# ── DB backup ──────────────────────────────────────────────────
do_backup() {
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    FILENAME="${DB_NAME}_${TIMESTAMP}.sql.gz.gpg"
    FILEPATH="${BACKUP_DIR}/${FILENAME}"

    echo "[$(date)] Starting encrypted DB backup → ${FILENAME}"

    # ash has no ``pipefail``: a pg_dump that dies mid-stream would otherwise be
    # masked by gpg's success and stored as a truncated but "successful" dump.
    # The ``if`` below only sees gpg's exit status, so the REAL guard is the
    # post-write verification: the dump is accepted only if it (a) clears a
    # sanity-floor size and (b) decrypts, decompresses, and ends with pg_dump's
    # completion trailer (absent on a truncated dump).
    if ! pg_dump \
            -h "$DB_HOST" \
            -p "$DB_PORT" \
            -U "$DB_USER" \
            -d "$DB_NAME" \
            --no-owner \
            --no-acl \
            --clean \
            --if-exists \
          | gzip \
          | encrypt_gpg "$FILEPATH"; then
        rm -f "$FILEPATH"
        echo "[$(date)] ERROR: DB backup pipeline failed for ${FILENAME}" >&2
        return 1
    fi
    # 644, not 600: this container runs as root, so 600 would lock the HOST
    # user out of the bind-mounted file and the unprivileged restore drill
    # (scripts/restore_drill.sh) fails with EACCES. The artifact is AES256
    # ciphertext — the security boundary is BACKUP_ENCRYPTION_KEY, not the
    # file mode.
    chmod 644 "$FILEPATH"

    SIZE_BYTES=$(stat -c %s "$FILEPATH" 2>/dev/null || echo 0)
    if [ "$SIZE_BYTES" -lt "$BACKUP_MIN_BYTES" ]; then
        rm -f "$FILEPATH"
        echo "[$(date)] ERROR: ${FILENAME} is only ${SIZE_BYTES}B (< ${BACKUP_MIN_BYTES}); discarding" >&2
        return 1
    fi

    if ! gpg --batch --quiet --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" "$FILEPATH" 2>/dev/null \
          | gunzip \
          | tail -n 5 \
          | grep -q 'PostgreSQL database dump complete'; then
        rm -f "$FILEPATH"
        echo "[$(date)] ERROR: ${FILENAME} failed integrity/completion check; discarding" >&2
        return 1
    fi

    SIZE=$(du -h "$FILEPATH" | cut -f1)
    echo "[$(date)] DB backup complete + verified: ${FILENAME} (${SIZE})"
    push_offsite "$FILEPATH"
}

# ── Media backup ───────────────────────────────────────────────
do_media_backup() {
    # Media contains PII (invoice PDFs etc.) → encrypt with the same AES256 key.
    # Skipped when the media dir is absent or empty (nothing to protect yet).
    if [ ! -d "$MEDIA_DIR" ] || [ -z "$(ls -A "$MEDIA_DIR" 2>/dev/null)" ]; then
        echo "[$(date)] No media at ${MEDIA_DIR}; skipping media backup"
        return 0
    fi

    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    FILENAME="${DB_NAME}_media_${TIMESTAMP}.tar.gz.gpg"
    FILEPATH="${BACKUP_DIR}/${FILENAME}"

    echo "[$(date)] Starting encrypted media backup → ${FILENAME}"

    if ! tar -C "$MEDIA_DIR" -cf - . \
          | gzip \
          | encrypt_gpg "$FILEPATH"; then
        rm -f "$FILEPATH"
        echo "[$(date)] ERROR: media backup pipeline failed for ${FILENAME}" >&2
        return 1
    fi
    # 644 for the same reason as the DB dump above: ciphertext + host-side
    # readability for the unprivileged restore drill.
    chmod 644 "$FILEPATH"

    # Verify the archive decrypts, decompresses, and lists cleanly.
    if ! gpg --batch --quiet --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" "$FILEPATH" 2>/dev/null \
          | gunzip \
          | tar -tf - >/dev/null 2>&1; then
        rm -f "$FILEPATH"
        echo "[$(date)] ERROR: ${FILENAME} failed integrity check; discarding" >&2
        return 1
    fi

    SIZE=$(du -h "$FILEPATH" | cut -f1)
    echo "[$(date)] Media backup complete + verified: ${FILENAME} (${SIZE})"
    push_offsite "$FILEPATH"
}

# ── Entrypoint ─────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

case "${1:-scheduled}" in
    now)
        # Run a single backup immediately
        do_backup
        do_media_backup
        ;;
    scheduled|*)
        # Run one backup on startup, then schedule via cron
        do_backup
        do_media_backup
        echo "${SCHEDULE} ${SELF} now >> /var/log/backup.log 2>&1" > /etc/crontabs/root
        echo "[$(date)] Cron scheduled: ${SCHEDULE}"
        exec crond -f -l 2
        ;;
esac
