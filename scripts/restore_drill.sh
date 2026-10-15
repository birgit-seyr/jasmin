#!/usr/bin/env bash
# Restore drill — restores a backup into a throwaway sandbox postgres with
# backups/restore.sh itself and writes a per-table row-count comparison vs
# the live prod DB, dry-runs the GDPR erasure replay against the restored
# data, restores the backup once more over a migrated copy of it, then
# unpacks the chosen media archive to prove that half restores too.
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
# Restores:
#     Both restores run backups/restore.sh from this checkout in the backup
#     image, the way a real restore runs: into a new database, which a
#     throwaway app role fills (postgres/app_db_role.sh), then the swap
#     (confirmed up front), against the sandbox only. Its /backups is a
#     scratch directory holding just the dump, so its ledger refresh writes
#     nowhere near the real ledger. A plain .sql is first wrapped the way
#     backup.sh writes dumps, under a throwaway passphrase, since restore.sh
#     reads only those.
#
#     The first restore goes onto a server without the database, so
#     restore.sh only renames its copy. The second meets what a real one
#     meets: a live database that has grown since the dump, which the swap
#     replaces. The sandbox database plays that part: the restored backup,
#     migrated by the replay dry run when that ran, plus in every schema a
#     table with a foreign key into a table of the dump, and a schema the
#     dump doesn't know with a foreign key into public. These are what a
#     dump's DROP statements fail on when it is replayed over a database.
#     The restore has to bring back the dump's tables and nothing else, and
#     keep the replaced database, added objects included.
#
# Requires:
#     - docker
#     - the prod stack running (we read POSTGRES_USER/DB from its env and
#       query the live DB for the comparison column, and run restore.sh in
#       the backup container's image; BACKUP_IMAGE=<image> names another)
#     - for .sql.gz.gpg files: BACKUP_ENCRYPTION_KEY in the environment
#       (sourced from .env on prod, kept in your password manager)
#     - room under $TMPDIR for the decrypted dump, which restore.sh stages
#       next to the dump (point TMPDIR elsewhere if /tmp is small)
#     - for the media archive: gpg + tar on the host, and room under $TMPDIR
#       for one unpacked copy of the media tree (the media tree is PDFs and
#       images, not rows)
#
# Output:
#     backups/restore-drills/YYYY-MM-DD_HHMMSS.md  (markdown; gitignored, next to
#     the backups it checks). Record each run on the "Restore-from-backup
#     drill" item of the super-admin ops checklist — its run log is the
#     record of every drill.
#
# Exit status:
#     Non-zero if either restore failed, if the media archive was found but
#     failed to restore, or if the erasure replay could not run against the
#     restored data. A missing media archive is not a failure — a deployment
#     with no uploads yet legitimately has none.
#
# Safety:
#     The sandbox container is fully isolated (no host port, default
#     bridge network only) and torn down at the end, with every database
#     the restores made in it. Prod is read-only for the row-count query —
#     no writes anywhere near it. Every superuser session the drill opens
#     looks names up in pg_catalog only and reads plain tables only, under
#     quoted names: the app owns its database and may have put operators,
#     functions or views there, which must not run with a superuser's
#     rights. The dump is staged and the media
#     archive unpacked in throwaway mktemp dirs, removed by the exit
#     trap, and NEVER in ./backups or media_volume, which hold the real
#     backups and the live uploads. The drill writes only its log, under
#     backups/restore-drills/; no backup artifact is moved or deleted.

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
SANDBOX_CONTAINER="jasmin-restore-sandbox"
SANDBOX_DB="jasmin_sandbox"
SANDBOX_USER="jasmin_sandbox"
# Passphrase is throwaway — the container lives for ~30s and never
# accepts a connection from outside docker exec.
SANDBOX_PASSWORD="sandbox_$(date +%s)_$RANDOM"
# The app's role in the sandbox: restore.sh fills its copies as it, as a real
# restore does, and the erasure replay logs in as it, as huey does.
SANDBOX_APP_USER="jasmin_sandbox_app"
SANDBOX_APP_PASSWORD="sandbox_app_$(date +%s)_$RANDOM"
# Every superuser session looks names up in pg_catalog only (see "Safety").
CATALOG_ONLY="-c search_path=pg_catalog"
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
# Restore state. SCRATCH_DIR is restore.sh's /backups: the dump and, while a
# restore runs, its decrypted copy. Declared up front for the exit trap.
RESTORE_SH="$(pwd)/backups/restore.sh"
APP_DB_ROLE_SH="$(pwd)/postgres/app_db_role.sh"
SCRATCH_DIR=""
RESTORE_STATUS="not run"
MIGRATED_STATUS="not run"
MIGRATED_FAILED=0
TABLE_COUNT_SQL="SELECT count(*) FROM pg_tables
                 WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
# The tables the restore over a migrated copy adds, and has to see gone.
DRILL_OBJECTS_SQL="SELECT count(*) FROM pg_class c
                   JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE c.relkind = 'r'
                     AND (c.relname = 'restore_drill_extra' OR n.nspname = 'restore_drill_tenant')"
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

if [ ! -f "$RESTORE_SH" ] || [ ! -f "$APP_DB_ROLE_SH" ]; then
    echo "ERROR: $RESTORE_SH or $APP_DB_ROLE_SH not found. Run the drill from the repo root." >&2
    exit 1
fi

# restore.sh needs psql, gpg and backup.sh, which the backup image has.
BACKUP_IMAGE="${BACKUP_IMAGE:-}"
if [ -z "$BACKUP_IMAGE" ]; then
    BACKUP_CONTAINER="$(docker compose ps -q backup 2>/dev/null || true)"
    if [ -n "$BACKUP_CONTAINER" ]; then
        BACKUP_IMAGE="$(docker inspect -f '{{.Config.Image}}' "$BACKUP_CONTAINER")"
    fi
fi
if [ -z "$BACKUP_IMAGE" ]; then
    echo "ERROR: backup container not found, so there is no image to run restore.sh in." >&2
    echo "Start it (docker compose up -d backup) or name an image: BACKUP_IMAGE=<image> $0" >&2
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
    if [ -n "$SCRATCH_DIR" ] && [ -d "$SCRATCH_DIR" ]; then
        rm -rf "$SCRATCH_DIR"
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
# Over TCP: on its first start the image runs a temporary server on the
# socket only, which answers on it too, and stops it again.
for _ in $(seq 1 30); do
    if docker exec "$SANDBOX_CONTAINER" pg_isready -h 127.0.0.1 -U "$SANDBOX_USER" -d "$SANDBOX_DB" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! docker exec "$SANDBOX_CONTAINER" pg_isready -h 127.0.0.1 -U "$SANDBOX_USER" -d "$SANDBOX_DB" > /dev/null 2>&1; then
    echo "ERROR: sandbox postgres didn't become ready in 30s" >&2
    exit 1
fi

# ── Restore ────────────────────────────────────────────────────────────────
# Through backups/restore.sh (see "Restores" in the header).
SCRATCH_DIR="$(mktemp -d)"
case "$BACKUP" in
    *.sql.gz.gpg)
        if [ -z "${BACKUP_ENCRYPTION_KEY:-}" ]; then
            echo "ERROR: BACKUP_ENCRYPTION_KEY not set — cannot decrypt $BACKUP" >&2
            echo "Source .env on the prod host or paste the passphrase from your password manager." >&2
            exit 1
        fi
        DUMP_NAME="$(basename "$BACKUP")"
        DUMP_SOURCE="$(cd "$(dirname "$BACKUP")" && pwd)/${DUMP_NAME}"
        RESTORE_KEY="$BACKUP_ENCRYPTION_KEY"
        ;;
    *.sql)
        DUMP_NAME="drill_dump.sql.gz.gpg"
        DUMP_SOURCE="${SCRATCH_DIR}/${DUMP_NAME}"
        RESTORE_KEY="drill_$(date +%s)_$RANDOM"
        RESTORE_KEY="$RESTORE_KEY" docker run --rm -i \
            -v "${SCRATCH_DIR}:/backups" \
            -e RESTORE_KEY \
            --entrypoint sh "$BACKUP_IMAGE" \
            -c 'gzip | gpg --batch --yes --quiet --symmetric --cipher-algo AES256 --passphrase "$RESTORE_KEY" --output "/backups/$1"' \
            sh "$DUMP_NAME" < "$BACKUP"
        ;;
    *)
        echo "ERROR: unsupported backup format: $BACKUP" >&2
        echo "Supported: .sql, .sql.gz.gpg" >&2
        exit 1
        ;;
esac

# Runs restore.sh against the sandbox, the swap confirmed, and prints its
# output. The encryption key reaches docker through its environment, not
# its arguments.
run_restore() {
    BACKUP_ENCRYPTION_KEY="$RESTORE_KEY" docker run --rm \
        --network "container:${SANDBOX_CONTAINER}" \
        -v "${SCRATCH_DIR}:/backups" \
        -v "${DUMP_SOURCE}:/backups/${DUMP_NAME}:ro" \
        -v "${RESTORE_SH}:/drill/restore.sh:ro" \
        -v "${APP_DB_ROLE_SH}:/usr/local/bin/app_db_role.sh:ro" \
        -e POSTGRES_HOST=127.0.0.1 \
        -e POSTGRES_PORT=5432 \
        -e POSTGRES_DB="$SANDBOX_DB" \
        -e POSTGRES_USER="$SANDBOX_USER" \
        -e POSTGRES_PASSWORD="$SANDBOX_PASSWORD" \
        -e APP_DB_USER="$SANDBOX_APP_USER" \
        -e APP_DB_PASSWORD="$SANDBOX_APP_PASSWORD" \
        -e BACKUP_ENCRYPTION_KEY \
        -e ALLOW_MISSING_GDPR_LEDGER=1 \
        -e CONFIRM_SWAP=1 \
        --entrypoint sh "$BACKUP_IMAGE" \
        /drill/restore.sh "/backups/${DUMP_NAME}" 2>&1
}

# Prints the result of the query $2 on the sandbox database $1.
sandbox_query() {
    docker exec -e PGOPTIONS="$CATALOG_ONLY" "$SANDBOX_CONTAINER" \
        psql -X -At -v ON_ERROR_STOP=1 -U "$SANDBOX_USER" -d "$1" -c "$2"
}

# Prints "<schema> <TAB> <table> <TAB> <rows>" for every plain table of the
# database $3 in the container $1, read as $2; <rows> is empty for a table
# that went or changed. The app names the tables: format() quotes them, the
# printed names have their control characters (a tab, a newline) turned into
# "?" so they keep to their field, and every count is a statement of its own
# (\gexec) that locks its table first and counts it only while it is a plain
# table, as a view put under its name would run the app's code.
table_rows() {
    docker exec -i -e PGOPTIONS="$CATALOG_ONLY" "$1" \
        psql -X -q -At -F "$(printf '\t')" -v ON_ERROR_STOP=1 -U "$2" -d "$3" <<'SQL'
CREATE FUNCTION pg_temp.table_rows(schema_name name, table_name name) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    total bigint;
BEGIN
    EXECUTE format('LOCK TABLE %I.%I IN ACCESS SHARE MODE', schema_name, table_name);
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = schema_name AND c.relname = table_name
          AND c.relkind IN ('r', 'p')
    ) THEN
        RETURN NULL;
    END IF;
    EXECUTE format('SELECT count(*) FROM %I.%I', schema_name, table_name) INTO total;
    RETURN total;
EXCEPTION WHEN undefined_table OR invalid_schema_name THEN
    RETURN NULL;
END
$$;
SELECT format('SELECT %L, %L, pg_temp.table_rows(%L, %L)',
              regexp_replace(n.nspname, '[[:cntrl:]]', '?', 'g'),
              regexp_replace(c.relname, '[[:cntrl:]]', '?', 'g'),
              n.nspname, c.relname)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname !~ '^pg_'
ORDER BY n.nspname, c.relname
\gexec
SQL
}

# restore.sh's comparison of the restored copy with the database it replaced,
# and the swap; its closing banner is for a real restore only.
restore_report() {
    sed -n '/^Restored copy,/,/Database restored:/p'
}

# The first restore goes onto a server without the database and only
# renames; the second one, over a migrated copy, swaps.
docker exec "$SANDBOX_CONTAINER" dropdb -U "$SANDBOX_USER" "$SANDBOX_DB"

echo "Restoring backup into sandbox through backups/restore.sh (this may take a minute)..."
{
    echo "## Restore"
    echo ""
    echo "Through \`backups/restore.sh\`, into a new database that then takes the"
    echo "sandbox database's name."
    echo ""
} >> "$OUTPUT_FILE"
if RESTORE_OUTPUT="$(run_restore)"; then
    RESTORE_STATUS="PASS"
    {
        echo "- **Result:** PASS"
        echo ""
        echo '```'
        echo "$RESTORE_OUTPUT" | restore_report
        echo '```'
        echo ""
    } >> "$OUTPUT_FILE"
else
    RESTORE_STATUS="FAIL"
    echo "ERROR: the backup did not restore:" >&2
    echo "$RESTORE_OUTPUT" | tail -n 40 >&2
    {
        echo "- **Result:** FAIL — the backup did not restore. Treat this as an incident."
        echo ""
        echo '```'
        echo "$RESTORE_OUTPUT" | tail -n 40
        echo '```'
    } >> "$OUTPUT_FILE"
    echo ""
    echo "RESTORE FAILED — the drill did NOT pass. See $OUTPUT_FILE" >&2
    exit 1
fi
RESTORED_TABLES="$(sandbox_query "$SANDBOX_DB" "$TABLE_COUNT_SQL")"

echo "Restore complete. Running row-count comparison..."

# ── Read prod creds (already-exported env on prod, fallback to compose env)
PROD_USER="${POSTGRES_USER:-$(docker exec "$PROD_POSTGRES_CONTAINER" printenv POSTGRES_USER)}"
PROD_DB="${POSTGRES_DB:-$(docker exec "$PROD_POSTGRES_CONTAINER" printenv POSTGRES_DB)}"

# ── Row-count comparison ──────────────────────────────────────────────────
{
    echo "## Row-count comparison"
    echo ""
    echo "| Schema | Table | Sandbox rows | Prod rows | Diff (prod − sandbox) |"
    echo "|---|---|---:|---:|---:|"
} >> "$OUTPUT_FILE"

TOTAL_TABLES=0
LARGE_DIFFS=0

SANDBOX_ROWS="$(table_rows "$SANDBOX_CONTAINER" "$SANDBOX_USER" "$SANDBOX_DB")" || {
    echo "WARNING: could not count the sandbox's rows." >&2
    SANDBOX_ROWS=""
}
PROD_ROWS="$(table_rows "$PROD_POSTGRES_CONTAINER" "$PROD_USER" "$PROD_DB" 2>/dev/null)" || PROD_ROWS=""

# The sandbox's tables, each with its prod count, or n/a where prod has none.
while IFS="$(printf '\t')" read -r schema table sandbox_count prod_count; do
    [ -z "$schema" ] && continue
    TOTAL_TABLES=$((TOTAL_TABLES + 1))

    # Digits only before the arithmetic: bash evaluates what it is given, and
    # these come from the app's database.
    if ! [[ "$sandbox_count" =~ ^[0-9]+$ && "$prod_count" =~ ^[0-9]+$ ]]; then
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
done < <(awk -F '\t' -v OFS='\t' '
    NR == FNR { if ($3 != "") prod[$1 OFS $2] = $3; next }
    $1 != "" { print $1, $2, ($3 == "" ? "n/a" : $3), (($1 OFS $2) in prod) ? prod[$1 OFS $2] : "n/a" }
' <(printf '%s\n' "$PROD_ROWS") <(printf '%s\n' "$SANDBOX_ROWS"))

# ── GDPR erasure replay (dry run) ──────────────────────────────────────────
# A real restore is followed by ``replay_gdpr_deletions``, which re-applies
# the erasures made after the backup from the ledger kept outside the
# database (backups/restore.sh prints the command). The dry run against the
# sandbox shows what it would re-apply to THIS backup, and proves the app can
# read the restored data and the ledger at all.
#
# The app container runs the live image with the live environment, but shares
# only the sandbox's network: it reaches the sandbox database on localhost and
# nothing of the running stack. It logs in as the sandbox's app role, as huey
# logs in as the live one.
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
            -e POSTGRES_USER="$SANDBOX_APP_USER" \
            -e POSTGRES_PASSWORD="$SANDBOX_APP_PASSWORD" \
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

# ── Restore over a migrated copy ───────────────────────────────────────────
# See "Restores" in the header. The added objects are what a migration or a
# new tenant adds: a table holding a foreign key into a table of the dump,
# in every schema, and a schema of its own whose table points into public.
{
    echo ""
    echo "## Restore over a migrated copy"
    echo ""
} >> "$OUTPUT_FILE"
echo "Restoring the backup again, over a migrated copy of it..."
MIGRATED_OUTPUT=""
MIGRATED_DETAIL=""
docker exec -i -e PGOPTIONS="$CATALOG_ONLY" "$SANDBOX_CONTAINER" \
    psql -X -q -v ON_ERROR_STOP=1 -U "$SANDBOX_USER" -d "$SANDBOX_DB" <<'SQL' || true
DO $$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT DISTINCT ON (n.nspname)
               n.nspname AS schema_name, c.relname AS table_name,
               a.attname AS column_name,
               format_type(a.atttypid, a.atttypmod) AS column_type
        FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.conkey[1]
        WHERE k.contype = 'p' AND cardinality(k.conkey) = 1
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname !~ '^pg_'
        ORDER BY n.nspname, c.relname
    LOOP
        EXECUTE format(
            'CREATE TABLE %I.restore_drill_extra (id integer PRIMARY KEY, ref %s REFERENCES %I.%I (%I))',
            target.schema_name, target.column_type,
            target.schema_name, target.table_name, target.column_name);
        IF target.schema_name = 'public' THEN
            CREATE SCHEMA restore_drill_tenant;
            EXECUTE format(
                'CREATE TABLE restore_drill_tenant.extra (id integer PRIMARY KEY, ref %s REFERENCES public.%I (%I))',
                target.column_type, target.table_name, target.column_name);
        END IF;
    END LOOP;
END
$$;
SQL
ADDED="$(sandbox_query "$SANDBOX_DB" "$DRILL_OBJECTS_SQL" || echo 0)"
REPLACED_DB=""
if [ "$ADDED" = "0" ]; then
    MIGRATED_DETAIL="no table could be added to restore over"
elif ! MIGRATED_OUTPUT="$(run_restore)"; then
    MIGRATED_DETAIL="restore.sh failed over the migrated copy"
else
    REPLACED_DB="$(sandbox_query postgres \
        "SELECT datname FROM pg_database
         WHERE starts_with(datname, '${SANDBOX_DB}_pre_restore_')
         ORDER BY datname DESC LIMIT 1" || true)"
    LEFT="$(sandbox_query "$SANDBOX_DB" "$DRILL_OBJECTS_SQL" || echo ERR)"
    TABLES="$(sandbox_query "$SANDBOX_DB" "$TABLE_COUNT_SQL" || echo ERR)"
    KEPT="ERR"
    if [ -n "$REPLACED_DB" ]; then
        KEPT="$(sandbox_query "$REPLACED_DB" "$DRILL_OBJECTS_SQL" || echo ERR)"
    fi
    if [ "$LEFT" != "0" ]; then
        MIGRATED_DETAIL="${LEFT} of the added tables are still in ${SANDBOX_DB} after the restore"
    elif [ "$TABLES" != "$RESTORED_TABLES" ]; then
        MIGRATED_DETAIL="${SANDBOX_DB} has ${TABLES} tables after the restore, the backup ${RESTORED_TABLES}"
    elif [ "$KEPT" != "$ADDED" ]; then
        MIGRATED_DETAIL="the replaced database ${REPLACED_DB:-(none)} holds ${KEPT} of the ${ADDED} added tables"
    fi
fi
if [ -z "$MIGRATED_DETAIL" ]; then
    MIGRATED_STATUS="PASS"
    echo "  restore over the migrated copy OK"
    {
        echo "- **Result:** PASS — restored over a database holding ${ADDED} tables the"
        echo "  backup doesn't have, each with a foreign key into it. They are gone from"
        echo "  \`${SANDBOX_DB}\` and kept in the replaced \`${REPLACED_DB}\`."
    } >> "$OUTPUT_FILE"
else
    MIGRATED_STATUS="FAIL"
    MIGRATED_FAILED=1
    echo "ERROR: restore over a migrated copy: ${MIGRATED_DETAIL}" >&2
    {
        echo "- **Result:** FAIL — ${MIGRATED_DETAIL}. A real restore meets a live"
        echo "  database like this one. Treat this as an incident."
        if [ -n "$MIGRATED_OUTPUT" ]; then
            echo ""
            echo '```'
            echo "$MIGRATED_OUTPUT" | tail -n 40
            echo '```'
        fi
    } >> "$OUTPUT_FILE"
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
    echo "- Restore (backups/restore.sh): **$RESTORE_STATUS**"
    echo "- Tables compared: **$TOTAL_TABLES**"
    echo "- Tables with diff > ±1000 rows: **$LARGE_DIFFS** (eyeball these in sign-off)"
    echo "- GDPR erasure replay (dry run): **$REPLAY_STATUS**"
    echo "- Restore over a migrated copy: **$MIGRATED_STATUS**"
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
echo "  1. Review the row-count table, the erasure replay, the restore over a migrated"
echo "     copy and the media verification result"
echo "  2. Fill in the sign-off block (Outcome: PASS / FAIL + notes)"
echo "  3. Mark the \"Restore-from-backup drill\" item of the super-admin ops checklist"
echo "     done, with the outcome and the log's file name in the notes"

if [ "$REPLAY_FAILED" -ne 0 ]; then
    echo ""
    echo "GDPR ERASURE REPLAY FAILED — the drill did NOT pass. See $OUTPUT_FILE" >&2
fi
if [ "$MIGRATED_FAILED" -ne 0 ]; then
    echo ""
    echo "RESTORE OVER A MIGRATED COPY FAILED — the drill did NOT pass. See $OUTPUT_FILE" >&2
fi
if [ "$MEDIA_FAILED" -ne 0 ]; then
    echo ""
    echo "MEDIA VERIFICATION FAILED — the drill did NOT pass. See $OUTPUT_FILE" >&2
fi
if [ "$REPLAY_FAILED" -ne 0 ] || [ "$MIGRATED_FAILED" -ne 0 ] || [ "$MEDIA_FAILED" -ne 0 ]; then
    exit 1
fi
