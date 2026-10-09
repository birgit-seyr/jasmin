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

# Optional off-host push. The rclone config lives at /backups/rclone.conf (the
# ./backups mount), created with
#   docker compose run --rm --entrypoint rclone backup --config /backups/rclone.conf config
# With RCLONE_REMOTE (e.g. "storagebox:jasmin-backups") and
# RCLONE_CONFIG=/backups/rclone.conf set in .env, every freshly written,
# already-encrypted artifact is copied off-host. Unset -> local-only backups.
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
# $1, optional, labels the file: "predeploy" writes
# <db>_predeploy_<timestamp>.sql.gz.gpg. The GFS prune reads only the
# timestamp, so a labelled dump is retained like any other.
do_backup() {
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    FILENAME="${DB_NAME}${1:+_$1}_${TIMESTAMP}.sql.gz.gpg"
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

# ── GDPR deletion ledger ───────────────────────────────────────
# Every tenant's ``gdpr_deletionlog`` lives in the database, so restoring a
# backup rolls it back together with the personal data the logged erasures
# removed. This keeps a copy outside the database for the replay
# (``manage.py replay_gdpr_deletions``): one JSON line per erasure, merged
# into the existing file so that no entry is ever dropped, not even when a
# restore took it out of the database. The email column leaves only as its
# SHA-256; an encrypted copy goes off-host whenever the ledger changed.
LEDGER_FILE="${BACKUP_DIR}/gdpr-deletion-ledger.jsonl"

ledger_sql() {
    # One row per erasure, keys sorted by jsonb: the same row always prints
    # the same line, so ``sort -u`` merges repeated exports.
    printf '%s' "SELECT ((to_jsonb(t) - 'user_email' - 'description') || jsonb_build_object(
        'schema', '$1',
        'email_sha256', CASE WHEN coalesce(t.user_email, '') <> ''
            THEN encode(sha256(convert_to(lower(trim(t.user_email)), 'UTF8')), 'hex') END
    ))::text FROM \"$1\".gdpr_deletionlog t"
}

export_gdpr_ledger() {
    rows="${LEDGER_FILE}.rows"
    merged="${LEDGER_FILE}.new"
    : > "$rows"
    schemas=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -At \
        -c "SELECT schema_name FROM public.tenants_tenant WHERE schema_name <> 'public' ORDER BY schema_name") \
        || { echo "[$(date)] ERROR: GDPR ledger: cannot list tenant schemas" >&2; rm -f "$rows"; return 1; }
    for schema in $schemas; do
        # UTC, so a timestamp prints the same way on every run.
        if ! PGTZ=UTC psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -At \
                -v ON_ERROR_STOP=1 -c "$(ledger_sql "$schema")" >> "$rows"; then
            echo "[$(date)] WARN: GDPR ledger: could not read ${schema}.gdpr_deletionlog; its new entries wait for the next run" >&2
        fi
    done
    { [ -f "$LEDGER_FILE" ] && cat "$LEDGER_FILE"; cat "$rows"; } | sort -u > "$merged"
    rm -f "$rows"
    if [ -f "$LEDGER_FILE" ] && cmp -s "$merged" "$LEDGER_FILE"; then
        rm -f "$merged"
        return 0
    fi
    # 644 like the dumps: the host user reads it for the restore drill, and it
    # holds ids and hashes, no names or addresses.
    chmod 644 "$merged"
    mv "$merged" "$LEDGER_FILE"
    echo "[$(date)] GDPR deletion ledger updated: $(wc -l < "$LEDGER_FILE") entries"
    if encrypt_gpg "${LEDGER_FILE}.gpg" < "$LEDGER_FILE"; then
        chmod 644 "${LEDGER_FILE}.gpg"
        push_offsite "${LEDGER_FILE}.gpg"
    else
        echo "[$(date)] ERROR: GDPR ledger: encryption failed; no off-host copy this run" >&2
    fi
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
        export_gdpr_ledger || true
        ;;
    ledger)
        # Refresh the GDPR deletion ledger (cron, and restore.sh before it
        # restores).
        export_gdpr_ledger
        ;;
    predeploy)
        # The database right before a deploy migrates it
        # (scripts/deploy.sh); the nightly run covers media and the ledger.
        do_backup predeploy
        ;;
    scheduled)
        # Run one backup on startup, then schedule via cron
        do_backup
        do_media_backup
        export_gdpr_ledger || true
        echo "${SCHEDULE} ${SELF} now >> /var/log/backup.log 2>&1" > /etc/crontabs/root
        # The ledger every 10 minutes, so an erasure reaches it (and its
        # off-host copy) long before the next nightly backup.
        echo "*/10 * * * * ${SELF} ledger >> /var/log/backup.log 2>&1" >> /etc/crontabs/root
        echo "[$(date)] Cron scheduled: ${SCHEDULE} (GDPR ledger every 10 minutes)"
        exec crond -f -l 2
        ;;
    *)
        # Not a fallback to "scheduled": that one never returns.
        echo "Usage: backup.sh [now | ledger | predeploy | scheduled]" >&2
        exit 2
        ;;
esac
