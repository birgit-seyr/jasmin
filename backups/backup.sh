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
# Succeeds when the dump $1 decrypts with the current key, decompresses, and
# ends with pg_dump's completion trailer (absent on a truncated dump).
dump_is_complete() {
    gpg --batch --quiet --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" "$1" 2>/dev/null \
        | gunzip \
        | tail -n 5 \
        | grep -q 'PostgreSQL database dump complete'
}

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

    if ! dump_is_complete "$FILEPATH"; then
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

# Prints the ledger's lines and those of the file $1, sorted and without
# repeats.
merged_ledger() {
    {
        if [ -f "$LEDGER_FILE" ]; then
            cat "$LEDGER_FILE"
        fi
        cat "$1"
    } | sort -u
}

export_gdpr_ledger() {
    rows="${LEDGER_FILE}.rows"
    part="${LEDGER_FILE}.part"
    merged="${LEDGER_FILE}.new"
    # Nothing here relies on set -e, which the callers that carry on after a
    # failed export (export_gdpr_ledger || true) turn off. A write a full disk
    # cut short must never replace the ledger: its copy goes off-host too, and
    # the entries only the ledger still holds would be lost. ``true``, not
    # ``:``: a failed redirect on that special built-in ends the whole script.
    if ! true > "$rows"; then
        echo "[$(date)] ERROR: GDPR ledger: cannot write ${rows}; the ledger stays as it is" >&2
        return 1
    fi
    schemas=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -At \
        -c "SELECT schema_name FROM public.tenants_tenant WHERE schema_name <> 'public' ORDER BY schema_name") \
        || { echo "[$(date)] ERROR: GDPR ledger: cannot list tenant schemas" >&2; rm -f "$rows"; return 1; }
    for schema in $schemas; do
        # UTC, so a timestamp prints the same way on every run. A psql that
        # fails may have printed part of a line, so a schema joins the rows
        # only once it has been read in full.
        if ! PGTZ=UTC psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -At \
                -v ON_ERROR_STOP=1 -c "$(ledger_sql "$schema")" > "$part"; then
            echo "[$(date)] WARN: GDPR ledger: could not read ${schema}.gdpr_deletionlog; its new entries wait for the next run" >&2
        elif ! cat "$part" >> "$rows"; then
            echo "[$(date)] ERROR: GDPR ledger: cannot write ${rows}; the ledger stays as it is" >&2
            rm -f "$rows" "$part"
            return 1
        fi
    done
    rm -f "$part"
    # A merge the disk cut short fails, or differs from a second one that
    # writes nothing.
    if ! merged_ledger "$rows" > "$merged" || ! merged_ledger "$rows" | cmp -s - "$merged"; then
        echo "[$(date)] ERROR: GDPR ledger: cannot write the merged ledger; the ledger stays as it is" >&2
        rm -f "$rows" "$merged"
        return 1
    fi
    rm -f "$rows"
    if [ -f "$LEDGER_FILE" ] && cmp -s "$merged" "$LEDGER_FILE"; then
        rm -f "$merged"
        return 0
    fi
    # 644 like the dumps: the host user reads it for the restore drill, and it
    # holds ids and hashes, no names or addresses.
    chmod 644 "$merged"
    if ! mv "$merged" "$LEDGER_FILE"; then
        echo "[$(date)] ERROR: GDPR ledger: cannot replace ${LEDGER_FILE}; it stays as it is" >&2
        rm -f "$merged"
        return 1
    fi
    echo "[$(date)] GDPR deletion ledger updated: $(wc -l < "$LEDGER_FILE") entries"
    if encrypt_gpg "${LEDGER_FILE}.gpg" < "$LEDGER_FILE"; then
        chmod 644 "${LEDGER_FILE}.gpg"
        push_offsite "${LEDGER_FILE}.gpg"
    else
        echo "[$(date)] ERROR: GDPR ledger: encryption failed; no off-host copy this run" >&2
    fi
}

# ── Media backup ───────────────────────────────────────────────
# Succeeds when the archive $1 decrypts with the current key, decompresses,
# and lists cleanly.
archive_is_complete() {
    gpg --batch --quiet --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" "$1" 2>/dev/null \
        | gunzip \
        | tar -tf - >/dev/null 2>&1
}

# Succeeds when the backup filesystem has room for a new media archive: 1.5
# times the size of the newest one free, or of the media tree while there is
# none. That filesystem usually holds the database volume too, and an archive
# that outgrows it fails only once the disk is full.
media_space_ok() {
    newest=""
    for archive in "${BACKUP_DIR}/${DB_NAME}"_media_*.tar.gz.gpg; do
        if [ -f "$archive" ]; then
            newest="$archive"
        fi
    done
    reference_kb=$(du -sk "${newest:-$MEDIA_DIR}" 2>/dev/null | cut -f1)
    free_kb=$(df -Pk "$BACKUP_DIR" 2>/dev/null | awk 'NR == 2 { print $4 }')
    # A malformed operand in the arithmetic below would end the whole script,
    # even when the caller handles a failure.
    for kb in "$reference_kb" "$free_kb"; do
        case "$kb" in
            '' | *[!0-9]*)
                echo "[$(date)] WARN: cannot measure the room for a media archive on ${BACKUP_DIR}; writing it unchecked" >&2
                return 0
                ;;
        esac
    done
    needed_kb=$((reference_kb * 3 / 2))
    if [ "$free_kb" -lt "$needed_kb" ]; then
        echo "[$(date)] ERROR: ${free_kb} KiB free on ${BACKUP_DIR}, a media archive needs about ${needed_kb} KiB; not writing one" >&2
        return 1
    fi
}

do_media_backup() {
    # Media contains PII (invoice PDFs etc.) → encrypt with the same AES256 key.
    # Skipped when the media dir is absent or empty (nothing to protect yet).
    if [ ! -d "$MEDIA_DIR" ] || [ -z "$(ls -A "$MEDIA_DIR" 2>/dev/null)" ]; then
        echo "[$(date)] No media at ${MEDIA_DIR}; skipping media backup"
        return 0
    fi
    media_space_ok || return 1

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

    if ! archive_is_complete "$FILEPATH"; then
        rm -f "$FILEPATH"
        echo "[$(date)] ERROR: ${FILENAME} failed integrity check; discarding" >&2
        return 1
    fi

    SIZE=$(du -h "$FILEPATH" | cut -f1)
    echo "[$(date)] Media backup complete + verified: ${FILENAME} (${SIZE})"
    push_offsite "$FILEPATH"
}

# ── Scheduled startup ──────────────────────────────────────────
# After a host reboot the Docker daemon starts the containers on its own,
# without compose's depends_on, so the database may still be starting. Fails
# once it has not accepted connections for about a minute.
wait_for_db() {
    attempts=0
    until pg_isready -q -t 2 -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME"; do
        attempts=$((attempts + 1))
        if [ "$attempts" -ge 30 ]; then
            return 1
        fi
        sleep 2
    done
}

# Prints a backup in BACKUP_DIR that matches the name pattern $1, was written
# in the last 20 hours and passes the check $2; fails when there is none. The
# check decrypts it with the current key, so a file a killed run left behind
# does not count, and neither does one encrypted with a key that has since
# been rotated: a container started with a new key backs up with it at once.
recent_backup() {
    while IFS= read -r candidate; do
        [ -n "$candidate" ] || continue
        if "$2" "$candidate" </dev/null; then
            echo "$candidate"
            return 0
        fi
        echo "[$(date)] WARN: $(basename "$candidate") fails verification (truncated, or encrypted with another key); not counting it as a recent backup" >&2
    done <<EOF
$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "$1" -mmin -1200)
EOF
    return 1
}

# ── Entrypoint ─────────────────────────────────────────────────
# The directory is shared with the huey container, whose non-root user prunes
# the old backups and checks the newest ones for the stale-backup alert. It
# reaches them through BACKUP_GID, which docker-compose.yml adds to that user as
# a supplementary group: 2770 gives the group the listing and the deletes (both
# need only the directory's write and search bits), keeps the bind-mounted
# directory's host owner in for scripts/restore_drill.sh, and closes it to
# everyone else, so the 644 files inside are readable only by those two. The
# setgid bit hands the group on to every file and directory created inside.
BACKUP_GID="${BACKUP_GID:-61000}"
case "$BACKUP_GID" in
    '' | *[!0-9]*)
        echo "[$(date)] ERROR: BACKUP_GID must be a numeric group id, got '${BACKUP_GID}'" >&2
        exit 2
        ;;
esac
mkdir -p "$BACKUP_DIR"
chgrp "$BACKUP_GID" "$BACKUP_DIR"
chmod 2770 "$BACKUP_DIR"

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
        # One backup on startup, then cron. No startup step may end the
        # script: the restart policy would rerun it in a loop, a full dump on
        # every pass, and crond, with the nightly backup and the ledger export,
        # would never start. The scheduled run retries a failed step instead.
        wait_for_db \
            || echo "[$(date)] WARN: ${DB_HOST}:${DB_PORT} still refuses connections; trying the startup backup anyway" >&2
        ok=1
        # A restart or a deploy adds no copy of what a backup from the last 20
        # hours already holds; a deploy's predeploy dump counts as one.
        if recent=$(recent_backup "${DB_NAME}_*.sql.gz.gpg" dump_is_complete); then
            echo "[$(date)] $(basename "$recent") is recent and verifies; no startup DB dump"
        else
            do_backup || ok=0
        fi
        if recent=$(recent_backup "${DB_NAME}_media_*.tar.gz.gpg" archive_is_complete); then
            echo "[$(date)] $(basename "$recent") is recent and verifies; no startup media archive"
        else
            do_media_backup || ok=0
        fi
        export_gdpr_ledger || true
        if [ "$ok" -eq 0 ]; then
            echo "[$(date)] ERROR: startup backup FAILED (see above); starting cron anyway, the run at '${SCHEDULE}' tries again" >&2
        fi
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
