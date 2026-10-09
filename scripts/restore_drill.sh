#!/usr/bin/env bash
# Restore drill — restores a backup into a throwaway sandbox postgres and
# writes a per-table row-count comparison vs the live prod DB, dry-runs the
# GDPR erasure replay against the restored data, then unpacks the chosen
# media archive to prove that half restores too.
#
# Usage:
#     ./scripts/restore_drill.sh                       # newest file in ./backups/
#     ./scripts/restore_drill.sh ./backups/foo.sql
#     ./scripts/restore_drill.sh ./backups/foo.sql.gz.gpg
#
#     MEDIA_ARCHIVE=./backups/bar_media_20260525_020000.tar.gz.gpg \
#         ./scripts/restore_drill.sh                   # pin the media archive
#
#     DRILL_PICK=random ./scripts/restore_drill.sh     # a random older dump
#                                                      # and media archive
#
# Artifact choice:
#     By default the drill opens the newest dump and the newest media archive.
#     DRILL_PICK=random instead picks, independently for each, a random one of
#     the artifacts OLDER than the newest — the weeklies and monthlies the GFS
#     retention keeps are otherwise never opened until they are needed. With
#     only one artifact present it falls back to that one. An explicit backup
#     path or MEDIA_ARCHIVE always wins. Expect the row-count comparison to
#     show more drift against live for an older dump.
#
# Requires:
#     - docker
#     - the prod stack running (we read POSTGRES_USER/DB from its env and
#       query the live DB for the comparison column)
#     - for .sql.gz.gpg files: BACKUP_ENCRYPTION_KEY in the environment
#       (sourced from .env on prod, kept in your password manager)
#     - for the media archive: gpg + tar on the host, and room under $TMPDIR
#       for one unpacked copy of the media tree (point TMPDIR elsewhere if
#       /tmp is small — the media tree is PDFs and images, not rows)
#
# Output:
#     backups/restore-drills/YYYY-MM-DD_HHMMSS.md  (markdown; gitignored, next to
#     the backups it checks). Record each run on the "Restore-from-backup
#     drill" item of the super-admin ops checklist — its run log is the
#     record of every drill.
#
# Exit status:
#     Non-zero if the media archive was found but failed to restore, or if
#     the erasure replay could not run against the restored data. A missing
#     media archive is not a failure — a deployment with no uploads yet
#     legitimately has none.
#
# Safety:
#     The sandbox container is fully isolated (no host port, default
#     bridge network only) and torn down at the end. Prod is read-only
#     for the row-count query — no writes anywhere near it. The media
#     archive is unpacked into a throwaway mktemp dir, removed by the exit
#     trap, and NEVER into media_volume, which holds the live uploads.
#     The drill writes only its log, under backups/restore-drills/; no
#     backup artifact is moved or deleted.

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
SANDBOX_CONTAINER="jasmin-restore-sandbox"
SANDBOX_DB="jasmin_sandbox"
SANDBOX_USER="jasmin_sandbox"
# Passphrase is throwaway — the container lives for ~30s and never
# accepts a connection from outside docker exec.
SANDBOX_PASSWORD="sandbox_$(date +%s)_$RANDOM"
PROD_POSTGRES_CONTAINER="${PROD_POSTGRES_CONTAINER:-$(docker compose ps -q postgres 2>/dev/null || true)}"
OUTPUT_DIR="backups/restore-drills"
# One file per run: a rerun on the same day keeps the earlier log.
OUTPUT_FILE="${OUTPUT_DIR}/$(date +%Y-%m-%d_%H%M%S).md"
# Media-verification state. Declared up front because the exit trap reads
# MEDIA_EXTRACT_DIR under ``set -u``, and it must be empty until mktemp runs.
MEDIA_EXTRACT_DIR=""
MEDIA_STATUS="not run"
MEDIA_FAILED=0
# Erasure-replay state; APP_ENV_FILE holds the app's secrets while it exists,
# so the exit trap removes it too.
APP_ENV_FILE=""
REPLAY_STATUS="not run"
REPLAY_FAILED=0
# "newest" (default) or "random" — see "Artifact choice" in the header.
DRILL_PICK="${DRILL_PICK:-newest}"
case "$DRILL_PICK" in
    newest | random) ;;
    *)
        echo "ERROR: DRILL_PICK must be 'newest' or 'random', got '$DRILL_PICK'." >&2
        exit 1
        ;;
esac

# Print one artifact path from the paths on stdin, which arrive newest first
# (``ls -t``): the newest, or with DRILL_PICK=random a random older one.
pick_artifact() {
    local paths=()
    local path
    while IFS= read -r path; do
        [ -n "$path" ] && paths+=("$path")
    done
    [ "${#paths[@]}" -gt 0 ] || return 0
    if [ "$DRILL_PICK" = "random" ] && [ "${#paths[@]}" -gt 1 ]; then
        printf '%s\n' "${paths[1 + RANDOM % (${#paths[@]} - 1)]}"
    else
        printf '%s\n' "${paths[0]}"
    fi
}

# ── Argument: backup file ──────────────────────────────────────────────────
BACKUP="${1:-}"
if [ -z "$BACKUP" ]; then
    # Pick from the backups under ./backups/. ``ls -t`` sorts by mtime
    # descending; redirect stderr because either glob may not match.
    BACKUP="$(ls -t backups/*.sql.gz.gpg backups/*.sql 2>/dev/null | pick_artifact || true)"
fi

if [ -z "$BACKUP" ] || [ ! -f "$BACKUP" ]; then
    echo "ERROR: no backup file found." >&2
    echo "Pass one explicitly: $0 <path-to-backup>" >&2
    echo "Or put one under ./backups/ and re-run." >&2
    exit 1
fi

if [ -z "$PROD_POSTGRES_CONTAINER" ]; then
    echo "ERROR: prod postgres container not found. Is the stack up?" >&2
    echo "(Looked for: docker compose ps -q postgres)" >&2
    exit 1
fi

# ── Prep output dir + header ───────────────────────────────────────────────
mkdir -p "$OUTPUT_DIR"
BACKUP_MTIME=$(date -r "$BACKUP" '+%Y-%m-%d %H:%M:%S')

{
    echo "# Restore drill — $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "- **Backup file:** \`$BACKUP\`"
    echo "- **Artifact choice:** ${DRILL_PICK}"
    echo "- **Backup mtime:** $BACKUP_MTIME"
    echo "- **Operator:** $(whoami)"
    echo "- **Host:** $(hostname)"
    echo ""
} > "$OUTPUT_FILE"

echo "Restore drill starting — log: $OUTPUT_FILE"

# ── Cleanup hook (always runs, even on failure) ────────────────────────────
cleanup() {
    # Extend this function rather than adding a second ``trap ... EXIT``: a
    # second trap on the same signal REPLACES this one, silently leaving the
    # sandbox container running.
    if [ -n "$MEDIA_EXTRACT_DIR" ] && [ -d "$MEDIA_EXTRACT_DIR" ]; then
        echo "Removing media scratch dir ($MEDIA_EXTRACT_DIR)..."
        rm -rf "$MEDIA_EXTRACT_DIR"
    fi
    if [ -n "$APP_ENV_FILE" ]; then
        rm -f "$APP_ENV_FILE"
    fi
    if docker ps -q --filter "name=^${SANDBOX_CONTAINER}$" | grep -q .; then
        echo "Tearing down sandbox container..."
        docker stop "$SANDBOX_CONTAINER" > /dev/null 2>&1 || true
        docker rm "$SANDBOX_CONTAINER" > /dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# ── Spin up sandbox postgres ───────────────────────────────────────────────
echo "Starting sandbox postgres ($SANDBOX_CONTAINER)..."
docker run -d --rm \
    --name "$SANDBOX_CONTAINER" \
    -e POSTGRES_DB="$SANDBOX_DB" \
    -e POSTGRES_USER="$SANDBOX_USER" \
    -e POSTGRES_PASSWORD="$SANDBOX_PASSWORD" \
    postgres:15-alpine > /dev/null

# Wait for accept-connections. ``pg_isready`` returns 0 once it's ready.
for _ in $(seq 1 30); do
    if docker exec "$SANDBOX_CONTAINER" pg_isready -U "$SANDBOX_USER" -d "$SANDBOX_DB" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! docker exec "$SANDBOX_CONTAINER" pg_isready -U "$SANDBOX_USER" -d "$SANDBOX_DB" > /dev/null 2>&1; then
    echo "ERROR: sandbox postgres didn't become ready in 30s" >&2
    exit 1
fi

# ── Restore ────────────────────────────────────────────────────────────────
echo "Restoring backup into sandbox (this may take a minute)..."
case "$BACKUP" in
    *.sql.gz.gpg)
        if [ -z "${BACKUP_ENCRYPTION_KEY:-}" ]; then
            echo "ERROR: BACKUP_ENCRYPTION_KEY not set — cannot decrypt $BACKUP" >&2
            echo "Source .env on the prod host or paste the passphrase from your password manager." >&2
            exit 1
        fi
        gpg --batch --yes --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" "$BACKUP" \
            | gunzip \
            | docker exec -i "$SANDBOX_CONTAINER" \
                psql -v ON_ERROR_STOP=1 --single-transaction \
                -U "$SANDBOX_USER" -d "$SANDBOX_DB" \
                > /dev/null
        ;;
    *.sql)
        docker exec -i "$SANDBOX_CONTAINER" \
            psql -v ON_ERROR_STOP=1 --single-transaction \
            -U "$SANDBOX_USER" -d "$SANDBOX_DB" \
            < "$BACKUP" > /dev/null
        ;;
    *)
        echo "ERROR: unsupported backup format: $BACKUP" >&2
        echo "Supported: .sql, .sql.gz.gpg" >&2
        exit 1
        ;;
esac

echo "Restore complete. Running row-count comparison..."

# ── Read prod creds (already-exported env on prod, fallback to compose env)
PROD_USER="${POSTGRES_USER:-$(docker exec "$PROD_POSTGRES_CONTAINER" printenv POSTGRES_USER)}"
PROD_DB="${POSTGRES_DB:-$(docker exec "$PROD_POSTGRES_CONTAINER" printenv POSTGRES_DB)}"

# ── Enumerate tables + emit markdown row-count comparison ─────────────────
ENUMERATE_SQL="SELECT schemaname || '.' || tablename
               FROM pg_tables
               WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
               ORDER BY schemaname, tablename"

{
    echo "## Row-count comparison"
    echo ""
    echo "| Schema | Table | Sandbox rows | Prod rows | Diff (prod − sandbox) |"
    echo "|---|---|---:|---:|---:|"
} >> "$OUTPUT_FILE"

TOTAL_TABLES=0
LARGE_DIFFS=0

while IFS= read -r qualified; do
    [ -z "$qualified" ] && continue
    schema="${qualified%%.*}"
    table="${qualified#*.}"
    TOTAL_TABLES=$((TOTAL_TABLES + 1))

    sandbox_count=$(docker exec "$SANDBOX_CONTAINER" \
        psql -U "$SANDBOX_USER" -d "$SANDBOX_DB" -t -A \
        -c "SELECT count(*) FROM \"$schema\".\"$table\";" 2>/dev/null || echo "ERR")

    prod_count=$(docker exec "$PROD_POSTGRES_CONTAINER" \
        psql -U "$PROD_USER" -d "$PROD_DB" -t -A \
        -c "SELECT count(*) FROM \"$schema\".\"$table\";" 2>/dev/null || echo "n/a")

    if [ "$prod_count" = "n/a" ] || [ "$prod_count" = "ERR" ] || [ "$sandbox_count" = "ERR" ]; then
        diff="n/a"
    else
        diff=$((prod_count - sandbox_count))
        # Flag tables whose diff is suspiciously large — operator should
        # eyeball these in the sign-off.
        abs_diff=${diff#-}
        if [ "$abs_diff" -gt 1000 ]; then
            LARGE_DIFFS=$((LARGE_DIFFS + 1))
        fi
        # Prefix positive diffs with + for readability.
        if [ "$diff" -gt 0 ]; then
            diff="+$diff"
        fi
    fi

    printf "| %s | %s | %s | %s | %s |\n" \
        "$schema" "$table" "$sandbox_count" "$prod_count" "$diff" >> "$OUTPUT_FILE"
done < <(docker exec "$SANDBOX_CONTAINER" \
    psql -U "$SANDBOX_USER" -d "$SANDBOX_DB" -t -A -c "$ENUMERATE_SQL")

# ── GDPR erasure replay (dry run) ──────────────────────────────────────────
# A real restore is followed by ``replay_gdpr_deletions``, which re-applies
# the erasures made after the backup from the ledger kept outside the
# database (backups/restore.sh prints the command). The dry run against the
# sandbox shows what it would re-apply to THIS backup, and proves the app can
# read the restored data and the ledger at all.
#
# The app container runs the live image with the live environment, but shares
# only the sandbox's network: it reaches the sandbox database on localhost and
# nothing of the running stack.
LEDGER_FILE="backups/gdpr-deletion-ledger.jsonl"
HUEY_CONTAINER="$(docker compose ps -q huey 2>/dev/null || true)"

{
    echo ""
    echo "## GDPR erasure replay (dry run)"
    echo ""
} >> "$OUTPUT_FILE"

if [ ! -f "$LEDGER_FILE" ]; then
    REPLAY_STATUS="SKIPPED (no ledger)"
    echo "WARNING: $LEDGER_FILE not found — skipping the erasure replay." >&2
    {
        echo "- **Result:** SKIPPED — \`$LEDGER_FILE\` not found. The backup"
        echo "  container writes it every 10 minutes; check \`/var/log/backup.log\`"
        echo "  in that container."
    } >> "$OUTPUT_FILE"
elif [ -z "$HUEY_CONTAINER" ]; then
    REPLAY_STATUS="SKIPPED (huey not running)"
    echo "WARNING: huey container not found — skipping the erasure replay." >&2
    {
        echo "- **Result:** SKIPPED — the huey container isn't running, so there"
        echo "  is no app image and environment to run the replay with."
    } >> "$OUTPUT_FILE"
else
    echo "Dry-running the GDPR erasure replay against the sandbox..."
    APP_IMAGE="$(docker inspect -f '{{.Config.Image}}' "$HUEY_CONTAINER")"
    APP_ENV_FILE="$(mktemp)"
    docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$HUEY_CONTAINER" \
        > "$APP_ENV_FILE"
    # Migrates first: an older backup may predate the code's tables.
    if REPLAY_OUTPUT="$(docker run --rm -i \
            --network "container:${SANDBOX_CONTAINER}" \
            --env-file "$APP_ENV_FILE" \
            -e POSTGRES_HOST=127.0.0.1 \
            -e POSTGRES_PORT=5432 \
            -e POSTGRES_DB="$SANDBOX_DB" \
            -e POSTGRES_USER="$SANDBOX_USER" \
            -e POSTGRES_PASSWORD="$SANDBOX_PASSWORD" \
            -e SENTRY_DSN= \
            --entrypoint sh "$APP_IMAGE" \
            -c 'python manage.py migrate_schemas --noinput > /dev/null && python manage.py replay_gdpr_deletions --dry-run --ledger -' \
            < "$LEDGER_FILE" 2>&1)"; then
        REPLAY_STATUS="PASS"
        echo "  replay dry run OK"
        {
            echo "- **Result:** PASS — the replay read the ledger and the restored data."
            echo "- **Ledger entries:** $(wc -l < "$LEDGER_FILE" | tr -d ' ')"
            echo ""
            echo '```'
            echo "$REPLAY_OUTPUT"
            echo '```'
        } >> "$OUTPUT_FILE"
    else
        REPLAY_STATUS="FAIL"
        REPLAY_FAILED=1
        echo "ERROR: the GDPR erasure replay failed against the sandbox" >&2
        {
            echo "- **Result:** FAIL — after a real restore, erasures made after this"
            echo "  backup could not be re-applied. Treat this as an incident."
            echo ""
            echo '```'
            echo "$REPLAY_OUTPUT" | tail -n 40
            echo '```'
        } >> "$OUTPUT_FILE"
    fi
    rm -f "$APP_ENV_FILE"
    APP_ENV_FILE=""
fi

# ── Media archive verification ─────────────────────────────────────────────
# backups/backup.sh verifies the media tar only as far as ``tar -t`` (a
# listing). This step actually unpacks it, so a drill produces evidence that
# BOTH halves of a backup restore — the DB and the uploaded documents.
#
# The extract target is a throwaway mktemp dir removed by the exit trap. It is
# never media_volume: that holds the live uploads, and the drill must not be
# able to write anywhere near them. ./backups/ is read-only here too.
MEDIA_ARCHIVE="${MEDIA_ARCHIVE:-$(ls -t backups/*_media_*.tar.gz.gpg 2>/dev/null | pick_artifact || true)}"

{
    echo ""
    echo "## Media archive verification"
    echo ""
} >> "$OUTPUT_FILE"

if [ -z "$MEDIA_ARCHIVE" ]; then
    MEDIA_STATUS="SKIPPED (none present)"
    echo "No *_media_*.tar.gz.gpg under ./backups/ — skipping media verification."
    {
        echo "- **Result:** SKIPPED — no \`*_media_*.tar.gz.gpg\` under \`./backups/\`."
        echo "- A deployment with no uploads yet legitimately has none, so this does"
        echo "  not fail the drill."
    } >> "$OUTPUT_FILE"
elif [ ! -f "$MEDIA_ARCHIVE" ]; then
    MEDIA_STATUS="FAIL (no such file)"
    MEDIA_FAILED=1
    echo "ERROR: media archive not found: $MEDIA_ARCHIVE" >&2
    {
        echo "- **Result:** FAIL — \`$MEDIA_ARCHIVE\` does not exist."
    } >> "$OUTPUT_FILE"
elif [ -z "${BACKUP_ENCRYPTION_KEY:-}" ]; then
    MEDIA_STATUS="SKIPPED (BACKUP_ENCRYPTION_KEY not set)"
    echo "WARNING: BACKUP_ENCRYPTION_KEY not set — cannot verify $MEDIA_ARCHIVE" >&2
    {
        echo "- **Result:** SKIPPED — \`BACKUP_ENCRYPTION_KEY\` not set, so"
        echo "  \`$MEDIA_ARCHIVE\` could not be decrypted."
        echo "- The media half of this backup is therefore **unverified**. Re-run with"
        echo "  the passphrase exported to get a complete drill."
    } >> "$OUTPUT_FILE"
elif ! command -v gpg > /dev/null 2>&1; then
    MEDIA_STATUS="SKIPPED (gpg not installed)"
    echo "WARNING: gpg not installed on this host — cannot verify $MEDIA_ARCHIVE" >&2
    {
        echo "- **Result:** SKIPPED — \`gpg\` is not installed on this host."
        echo "- The media half of this backup is therefore **unverified**."
    } >> "$OUTPUT_FILE"
else
    MEDIA_MTIME=$(date -r "$MEDIA_ARCHIVE" '+%Y-%m-%d %H:%M:%S')
    MEDIA_EXTRACT_DIR="$(mktemp -d)"
    echo "Verifying media archive: $MEDIA_ARCHIVE"
    echo "  unpacking into $MEDIA_EXTRACT_DIR (removed on exit)"

    if gpg --batch --quiet --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" "$MEDIA_ARCHIVE" \
         | gunzip \
         | tar -C "$MEDIA_EXTRACT_DIR" -xf -; then
        media_files=$(find "$MEDIA_EXTRACT_DIR" -type f | wc -l | tr -d ' ' || true)
        # BSD du right-pads its size column; strip so the report reads cleanly.
        media_size=$(du -sh "$MEDIA_EXTRACT_DIR" | cut -f1 | tr -d ' ' || true)
        # backup.sh runs ``tar -C /app/media -cf - .``, so the immediate
        # subdirectories of the extract root are the per-tenant media roots.
        media_top_dirs=$(find "$MEDIA_EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d \
            -exec basename {} \; | sort | tr '\n' ' ' | sed 's/ *$//' || true)
        [ -n "$media_top_dirs" ] || media_top_dirs="(none — archive has no top-level directories)"

        MEDIA_STATUS="PASS"
        echo "  decrypted + unpacked OK — $media_files files"
        {
            echo "- **Result:** PASS — decrypts, gunzips and untars cleanly."
            echo "- **Archive:** \`$MEDIA_ARCHIVE\`"
            echo "- **Archive mtime:** $MEDIA_MTIME"
            echo "- **Files extracted:** $media_files"
            echo "- **Unpacked size:** $media_size"
            echo "- **Top-level directories (per-tenant media roots):** $media_top_dirs"
        } >> "$OUTPUT_FILE"
    else
        MEDIA_STATUS="FAIL"
        MEDIA_FAILED=1
        echo "ERROR: media archive failed to decrypt/unpack: $MEDIA_ARCHIVE" >&2
        {
            echo "- **Result:** FAIL — \`$MEDIA_ARCHIVE\` did not decrypt, gunzip and untar."
            echo "- **Archive mtime:** $MEDIA_MTIME"
            echo "- Treat this as an incident. The DB half may be fine, but the uploaded"
            echo "  documents (invoice / delivery-note PDFs, e-invoice XML, consent"
            echo "  documents, share imports) are NOT recoverable from this archive."
        } >> "$OUTPUT_FILE"
    fi
fi

{
    echo ""
    echo "## Summary"
    echo ""
    echo "- Tables compared: **$TOTAL_TABLES**"
    echo "- Tables with diff > ±1000 rows: **$LARGE_DIFFS** (eyeball these in sign-off)"
    echo "- GDPR erasure replay (dry run): **$REPLAY_STATUS**"
    echo "- Media archive: **$MEDIA_STATUS**"
    echo ""
    echo "## Sign-off"
    echo ""
    echo "<!-- Edit the block below after reviewing the diff above. -->"
    echo "- **Outcome:** PASS | FAIL"
    echo "- **Notes:**"
    echo ""
} >> "$OUTPUT_FILE"

echo ""
echo "Drill complete."
echo "Log: $OUTPUT_FILE"
echo ""
echo "Next steps:"
echo "  1. Review the row-count table, the erasure replay and the media verification result"
echo "  2. Fill in the sign-off block (Outcome: PASS / FAIL + notes)"
echo "  3. Mark the \"Restore-from-backup drill\" item of the super-admin ops checklist"
echo "     done, with the outcome and the log's file name in the notes"

if [ "$REPLAY_FAILED" -ne 0 ]; then
    echo ""
    echo "GDPR ERASURE REPLAY FAILED — the drill did NOT pass. See $OUTPUT_FILE" >&2
fi
if [ "$MEDIA_FAILED" -ne 0 ]; then
    echo ""
    echo "MEDIA VERIFICATION FAILED — the drill did NOT pass. See $OUTPUT_FILE" >&2
fi
if [ "$REPLAY_FAILED" -ne 0 ] || [ "$MEDIA_FAILED" -ne 0 ]; then
    exit 1
fi
