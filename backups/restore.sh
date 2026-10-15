#!/bin/sh
set -eu

# ── Restore an encrypted backup — SQL restore only ─────────────
# Usage: sh /backups/restore.sh /backups/<backup_file>.sql.gz.gpg
#
# This script runs in the backup image (postgres-client + gnupg) and
# performs ONLY the database restore. It is reachable inside the
# ``backup`` service at ``/backups/restore.sh`` via the bind mount; run it
# through ``sh``, as the file has no executable bit.
#
# A dump is never replayed over the live database: its DROP statements carry
# no CASCADE, so they fail on what was added since the dump was taken — a
# table in a tenant schema, a foreign key into a dumped table, a new tenant's
# schema. The dump goes into a new database, <db>_restore, instead. Only
# once that restore has finished and the swap is confirmed do the two
# databases change names, in one transaction: the live one becomes
# <db>_pre_restore_<UTC time> and <db>_restore becomes <db>. The replaced
# database stays until it is dropped by hand; the script prints how, and how
# to swap back. A restore that fails drops <db>_restore and leaves <db> as it
# was. No other database on the server is touched, GlitchTip's included.
# The server needs room for a second full copy of the database, and
# /backups room for the decrypted dump while the script runs.
#
# The whole procedure, from the repo root on the host:
#
#   1. docker compose stop backend huey
#      Nothing may write to the database while it is replaced or stay
#      connected to it through the swap, and nothing may serve the personal
#      data the restore brings back before step 4 has erased it again. The
#      script cannot verify this: the app holds a connection only while a
#      request or a task runs, so an idle app shows no session, and once the
#      names swap its next connection opens the restored copy.
#   2. docker compose exec backup sh /backups/restore.sh /backups/<file>.sql.gz.gpg
#      Refreshes the GDPR deletion ledger from the live database first, then
#      restores into <db>_restore, prints its schemas and a few row counts
#      next to the live database's, and swaps once "swap" is typed at the
#      prompt, which asks for backend and huey to be stopped. Without a
#      terminal (exec -T, a script), -e CONFIRM_SWAP=1 confirms instead; with
#      neither, the script stops before the swap and <db> stays as it was.
#      The swap refuses while sessions are connected to <db>, or when one
#      connects in the few seconds it then watches. Once the app is stopped,
#      -e TERMINATE_SESSIONS=1 ends the sessions left, such as a psql shell
#      or the nightly pg_dump. Right before the swap the ledger is refreshed
#      once more; if that fails after the first refresh worked, the swap
#      refuses too.
#   3. Only when the media volume is lost or damaged: unpack the media archive
#      taken with that backup (<db>_media_<timestamp>.tar.gz.gpg), BEFORE
#      step 4 — the erasure replay deletes the files of everyone erased since:
#        docker compose exec -T backup sh -c \
#            'gpg --batch --quiet --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" "/backups/$1" | gunzip' \
#            sh <db>_media_<timestamp>.tar.gz.gpg \
#          | docker compose run --rm --no-deps -T --user root --entrypoint tar huey \
#              --numeric-owner -C /app/media -xf -
#      The backup service mounts the media volume read-only, so a one-off huey
#      container unpacks it, as root so every file keeps its owner. tar adds
#      and overwrites; it deletes nothing.
#   4. Re-apply the erasures made after the backup — printed at the end.
#   5. docker compose up -d backend huey && docker compose restart gateway
#      (nginx resolves the backend once, at startup, and it may come back on
#      a new address).
#   6. Once the restored data has proven good, drop the replaced database
#      with the command printed at the end.
#
# GDPR: the restore rolls every tenant's ``gdpr_deletionlog`` back with the
# data, so the replay reads the copy kept outside the database,
# /backups/gdpr-deletion-ledger.jsonl (``backup.sh ledger``). It runs in a
# Python/Django container, because this image has none. After losing the host,
# fetch the off-host copy first and decrypt it into place:
#   rclone copyto <remote>/gdpr-deletion-ledger.jsonl.gpg /backups/gdpr-deletion-ledger.jsonl.gpg
#   gpg --batch --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" \
#       --output /backups/gdpr-deletion-ledger.jsonl /backups/gdpr-deletion-ledger.jsonl.gpg
# ───────────────────────────────────────────────────────────────

BACKUP_FILE="${1:?Usage: sh /backups/restore.sh <backup_file.sql.gz.gpg>}"

DB_HOST="${POSTGRES_HOST:-postgres}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB}"
DB_USER="${POSTGRES_USER}"

export PGPASSWORD="${POSTGRES_PASSWORD}"
BACKUP_ENCRYPTION_KEY="${BACKUP_ENCRYPTION_KEY:?BACKUP_ENCRYPTION_KEY must be set}"

LEDGER_FILE="/backups/gdpr-deletion-ledger.jsonl"

# The database the dump goes into, and the name the swap gives the live one.
RESTORE_DB="${DB_NAME}_restore"
REPLACED_DB="${DB_NAME}_pre_restore_$(date -u +%Y%m%d_%H%M%S)"
# Postgres cuts a longer name to 63 bytes with no more than a notice, and the
# commands printed at the end would then name a database that doesn't exist.
if [ "${#REPLACED_DB}" -gt 63 ]; then
    echo "[$(date)] ERROR: the database name ${DB_NAME} is too long for ${REPLACED_DB}" >&2
    exit 1
fi
# Statements on whole databases run from the maintenance database: no session
# can rename or drop the database it is connected to.
ADMIN_DB="postgres"
if [ "$DB_NAME" = "postgres" ]; then
    ADMIN_DB="template1"
fi

# ── Helpers ────────────────────────────────────────────────────
# psql on the database $1, without a psqlrc or a pager, stopping at the first
# error. SQL that uses -v variables comes on stdin: psql fills them in there,
# never in a -c command.
run_psql() {
    psql_database="$1"
    shift
    psql -X -q -P pager=off -v ON_ERROR_STOP=1 \
        -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$psql_database" "$@"
}

admin_psql() {
    run_psql "$ADMIN_DB" "$@"
}

# Succeeds when a database named $1 exists.
database_exists() {
    found=$(admin_psql -At -v name="$1" <<'SQL'
SELECT count(*) FROM pg_database WHERE datname = :'name';
SQL
)
    [ "$found" = "1" ]
}

# Prints the client sessions connected to the database $1, one line each.
# Autovacuum workers are left out: they come and go on any database, and the
# rename ends them by itself.
sessions_on() {
    admin_psql -At -F ' | ' -v name="$1" <<'SQL'
SELECT pid, usename, coalesce(nullif(application_name, ''), '-'),
       coalesce(host(client_addr), 'local socket'), coalesce(state, '-')
FROM pg_stat_activity
WHERE datname = :'name' AND pid <> pg_backend_pid()
  AND backend_type = 'client backend'
ORDER BY backend_start;
SQL
}

# Ends the client sessions on the database $1, waiting up to 5 s for each.
terminate_sessions_on() {
    admin_psql -At -v name="$1" > /dev/null <<'SQL'
SELECT pg_terminate_backend(pid, 5000)
FROM pg_stat_activity
WHERE datname = :'name' AND pid <> pg_backend_pid()
  AND backend_type = 'client backend';
SQL
}

# A new, empty database with the live one's encoding, collation and owner
# (the server's defaults when there is no live database). template0, because
# the dump expects nothing beyond what a bare database holds.
create_restore_database() {
    admin_psql -v live="$DB_NAME" -v restore="$RESTORE_DB" <<'SQL'
SELECT count(*) > 0 AS found,
       max(pg_encoding_to_char(encoding)) AS encoding,
       max(datcollate::text) AS collate,
       max(datctype::text) AS ctype,
       max(pg_get_userbyid(datdba)::text) AS owner
FROM pg_database
WHERE datname = :'live' \gset live_
\if :live_found
CREATE DATABASE :"restore" WITH TEMPLATE template0 OWNER :"live_owner"
    ENCODING :'live_encoding' LC_COLLATE :'live_collate' LC_CTYPE :'live_ctype';
\else
CREATE DATABASE :"restore" WITH TEMPLATE template0;
\endif
SQL
}

# FORCE ends the sessions on it first: a leftover or half-restored copy has
# none worth keeping.
drop_restore_database() {
    admin_psql -v name="$RESTORE_DB" <<'SQL'
DROP DATABASE IF EXISTS :"name" WITH (FORCE);
SQL
}

# Prints, per schema of the database $1, its table count, a few row counts
# (empty where the schema has no such table) and its newest migration. It
# writes nothing but the session's own temporary functions.
summarize() {
    run_psql "$1" -P footer=off <<'SQL'
CREATE FUNCTION pg_temp.row_count(schema_name name, table_name text) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    total bigint;
BEGIN
    IF to_regclass(format('%I.%I', schema_name, table_name)) IS NULL THEN
        RETURN NULL;
    END IF;
    EXECUTE format('SELECT count(*) FROM %I.%I', schema_name, table_name) INTO total;
    RETURN total;
END
$$;
CREATE FUNCTION pg_temp.newest_migration(schema_name name) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    applied text;
BEGIN
    IF to_regclass(format('%I.django_migrations', schema_name)) IS NULL THEN
        RETURN NULL;
    END IF;
    EXECUTE format(
        'SELECT to_char(max(applied), ''YYYY-MM-DD HH24:MI'') FROM %I.django_migrations',
        schema_name
    ) INTO applied;
    RETURN applied;
END
$$;
SELECT n.nspname AS schema,
       (SELECT count(*) FROM pg_class c
        WHERE c.relnamespace = n.oid AND c.relkind IN ('r', 'p')) AS tables,
       pg_temp.row_count(n.nspname, 'tenants_tenant') AS tenants,
       pg_temp.row_count(n.nspname, 'accounts_jasminuser') AS logins,
       pg_temp.row_count(n.nspname, 'commissioning_member') AS members,
       pg_temp.row_count(n.nspname, 'commissioning_subscription') AS subscriptions,
       pg_temp.row_count(n.nspname, 'gdpr_deletionlog') AS erasures,
       pg_temp.newest_migration(n.nspname) AS newest_migration
FROM pg_namespace n
WHERE n.nspname NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
  AND n.nspname !~ '^pg_(temp|toast_temp)_'
ORDER BY n.nspname <> 'public', n.nspname;
SQL
}

# Prints the live database's own grants and settings. pg_dump leaves these
# out (they come only with --create), so the restored database has the
# server's defaults instead.
database_level_settings() {
    admin_psql -At -v name="$DB_NAME" <<'SQL'
SELECT 'grants: ' || datacl::text
FROM pg_database
WHERE datname = :'name' AND datacl IS NOT NULL
UNION ALL
SELECT 'settings' || coalesce(' for ' || r.rolname, '') || ': '
       || array_to_string(s.setconfig, ', ')
FROM pg_db_role_setting s
JOIN pg_database d ON d.oid = s.setdatabase
LEFT JOIN pg_roles r ON r.oid = s.setrole
WHERE d.datname = :'name';
SQL
}

# Both renames in one transaction: either the restored copy is <db> and the
# old database is REPLACED_DB, or nothing changed.
swap_databases() {
    admin_psql -v live="$DB_NAME" -v restore="$RESTORE_DB" -v replaced="$REPLACED_DB" <<'SQL'
SELECT count(*) > 0 AS live_found FROM pg_database WHERE datname = :'live' \gset
BEGIN;
\if :live_found
ALTER DATABASE :"live" RENAME TO :"replaced";
\endif
ALTER DATABASE :"restore" RENAME TO :"live";
COMMIT;
SQL
}

# ── GDPR deletion ledger ───────────────────────────────────────
# Capture the erasures made since the last ledger run while the live database
# still has them. A database too broken to read leaves the ledger as it was.
# The swap refreshes it once more.
echo "[$(date)] Refreshing the GDPR deletion ledger from the live database..."
ledger_refreshed=0
if /usr/local/bin/backup.sh ledger; then
    ledger_refreshed=1
else
    echo "[$(date)] WARN: could not refresh the ledger; using the last copy" >&2
fi

if [ ! -f "$LEDGER_FILE" ] && [ "${ALLOW_MISSING_GDPR_LEDGER:-0}" != "1" ]; then
    echo "[$(date)] ERROR: ${LEDGER_FILE} is missing. Without it, erasures made after" >&2
    echo "  this backup can't be re-applied. Restore it from the off-host copy (see the" >&2
    echo "  header of this script), or set ALLOW_MISSING_GDPR_LEDGER=1 if this" >&2
    echo "  deployment has never erased anyone." >&2
    exit 1
fi
if [ -f "$LEDGER_FILE" ]; then
    echo "[$(date)] GDPR deletion ledger: $(wc -l < "$LEDGER_FILE") entries"
fi

# Warned about now, not only at the swap: the restore before it can take a
# while.
early_sessions=$(sessions_on "$DB_NAME" 2>/dev/null || true)
if [ -n "$early_sessions" ]; then
    echo "[$(date)] WARN: sessions are connected to ${DB_NAME}. Stop backend and huey before" >&2
    echo "  the swap (docker compose stop backend huey); the swap refuses while sessions are" >&2
    echo "  connected:" >&2
    echo "$early_sessions" | sed 's/^/    /' >&2
fi

# ── Restore into a new database ────────────────────────────────
echo "[$(date)] Decrypting ${BACKUP_FILE}..."

# ash has no ``pipefail``: piping gpg | gunzip | psql would let a failed
# decrypt feed EMPTY input to psql, which then exits 0 and we'd swap in an
# empty database. Stage each step as its own command so ``set -e`` catches a
# failure at the point it happens, and make psql abort on the first SQL
# error (``ON_ERROR_STOP=1``). The temp files live in the backup volume and
# are removed on exit.
TMP_GZ="${BACKUP_FILE}.dec.gz"
TMP_SQL="${BACKUP_FILE}.dec.sql"
# "restoring" from the creation of RESTORE_DB until the dump is in: the
# script ending in that state, by an error or a signal, drops the copy.
RESTORE_STATE=""
cleanup() {
    rm -f "$TMP_GZ" "$TMP_SQL"
    if [ "$RESTORE_STATE" = "restoring" ]; then
        echo "[$(date)] ERROR: the restore into ${RESTORE_DB} did not finish; dropping it." >&2
        echo "  ${DB_NAME} is unchanged." >&2
        drop_restore_database \
            || echo "[$(date)] WARN: could not drop ${RESTORE_DB}; the next run drops it" >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

gpg --batch --yes --quiet --decrypt \
    --passphrase "$BACKUP_ENCRYPTION_KEY" \
    --output "$TMP_GZ" \
    "$BACKUP_FILE"

gunzip -c "$TMP_GZ" > "$TMP_SQL"
rm -f "$TMP_GZ"

# The completion trailer pg_dump writes last, which backup.sh checks every
# dump for: a file without it, cut short or no dump at all, would restore
# into a database missing whatever it lacks, and the swap would put that in
# place of the live one.
if ! tail -n 5 "$TMP_SQL" | grep -q 'PostgreSQL database dump complete'; then
    echo "[$(date)] ERROR: $(basename "$BACKUP_FILE") does not end like a complete pg_dump;" >&2
    echo "  nothing restored. ${DB_NAME} is unchanged." >&2
    exit 1
fi

if database_exists "$RESTORE_DB"; then
    echo "[$(date)] Dropping ${RESTORE_DB}, left over from an earlier restore..."
    drop_restore_database
fi

echo "[$(date)] Restoring into the new database ${RESTORE_DB}..."
create_restore_database
RESTORE_STATE="restoring"
# Not --single-transaction: a new database needs no rollback, since a failed
# restore drops it, and one transaction would hold a lock on every restored
# relation until the end, thousands per tenant schema, past what Postgres'
# default lock table holds. The query results the dump prints (setval and
# the like) go to /dev/null; errors still reach stderr.
run_psql "$RESTORE_DB" -f "$TMP_SQL" > /dev/null
RESTORE_STATE="restored"
rm -f "$TMP_SQL"
echo "[$(date)] The dump is restored into ${RESTORE_DB}."

# ── Check, confirm, swap ───────────────────────────────────────
echo ""
echo "Restored copy, ${RESTORE_DB}, from $(basename "$BACKUP_FILE"):"
if ! summarize "$RESTORE_DB"; then
    echo "[$(date)] ERROR: cannot read the restored copy; not swapping. ${DB_NAME} is" >&2
    echo "  unchanged, and ${RESTORE_DB} stays for a look until the next run drops it." >&2
    exit 1
fi
live_found=0
if database_exists "$DB_NAME"; then
    live_found=1
    echo "Live database, ${DB_NAME}, which the swap replaces:"
    summarize "$DB_NAME" || echo "  (cannot read ${DB_NAME})"
    own_settings=$(database_level_settings || true)
    if [ -n "$own_settings" ]; then
        echo "NOTE: ${DB_NAME} has grants or settings of its own, which a dump doesn't"
        echo "  carry; the restored database starts with the server's defaults. Re-apply"
        echo "  any that still matter after the swap:"
        echo "$own_settings" | sed 's/^/    /'
        echo ""
    fi
else
    echo "There is no database ${DB_NAME}: the swap only renames ${RESTORE_DB}."
    echo ""
fi

# The app holds a connection only while a request or a task runs, so the
# session check below cannot tell an idle app from a stopped one.
echo "Backend and huey have to be stopped before the swap:"
echo "      docker compose stop backend huey"
echo "  An app still running when the names swap opens the restored copy on its next"
echo "  request and serves the personal data erased since the backup."
answer=""
if [ "${CONFIRM_SWAP:-0}" = "1" ]; then
    answer="swap"
elif [ -t 0 ]; then
    printf 'Type "swap" once backend and huey are stopped, to make %s the database %s: ' \
        "$RESTORE_DB" "$DB_NAME"
    read -r answer || answer=""
fi
if [ "$answer" != "swap" ]; then
    echo "[$(date)] Not swapped: ${DB_NAME} is unchanged."
    echo "  ${RESTORE_DB} holds the restored copy, with the personal data erased since"
    echo "  the backup. Drop it once done with it:"
    echo "      docker compose exec postgres dropdb -U ${DB_USER} ${RESTORE_DB}"
    echo "  To put a restore in place, stop backend and huey, run this script again and"
    echo "  type \"swap\", or pass -e CONFIRM_SWAP=1."
    exit 0
fi

if [ "$live_found" = "1" ]; then
    # The ledger cron and this script's own checks connect for a moment, so
    # give the sessions a few seconds to end before refusing.
    sessions=$(sessions_on "$DB_NAME")
    waited=0
    while [ -n "$sessions" ] && [ "$waited" -lt 10 ]; do
        sleep 1
        waited=$((waited + 1))
        sessions=$(sessions_on "$DB_NAME")
    done
    if [ -n "$sessions" ]; then
        if [ "${TERMINATE_SESSIONS:-0}" != "1" ]; then
            echo "[$(date)] ERROR: these sessions are connected to ${DB_NAME}; not swapping:" >&2
            echo "$sessions" | sed 's/^/    /' >&2
            echo "  Stop backend and huey if they still run (docker compose stop backend huey)" >&2
            echo "  and run the restore again. Once the app is stopped, -e TERMINATE_SESSIONS=1" >&2
            echo "  ends the sessions left, such as a psql shell or the nightly pg_dump." >&2
            echo "  ${DB_NAME} is unchanged, and ${RESTORE_DB} keeps the restored copy until the" >&2
            echo "  next run drops it." >&2
            exit 1
        fi
        echo "[$(date)] Ending the sessions connected to ${DB_NAME}:"
        echo "$sessions" | sed 's/^/    /'
        terminate_sessions_on "$DB_NAME"
    fi
    # An app still running holds a session only while a request or a task
    # runs, so a single look sees it by chance at best, and the sessions
    # ended above come back with its next one. Watch for five seconds more,
    # looking five times a second, and refuse once a session turns up.
    looks=0
    while [ "$looks" -lt 25 ]; do
        sleep 0.2
        looks=$((looks + 1))
        sessions=$(sessions_on "$DB_NAME")
        if [ -n "$sessions" ]; then
            echo "[$(date)] ERROR: sessions keep connecting to ${DB_NAME}; not swapping:" >&2
            echo "$sessions" | sed 's/^/    /' >&2
            echo "  Something still runs against it. Stop it (docker compose stop backend huey," >&2
            echo "  if the app still runs) and run the restore again. ${DB_NAME} is unchanged," >&2
            echo "  and ${RESTORE_DB} keeps the restored copy until the next run drops it." >&2
            exit 1
        fi
    done

    # Erasures made since the refresh at the start are in the live database
    # only, and once the names swap the ledger is read from the restored
    # copy. With nothing connected any more, this refresh catches them all.
    # Only a live database the ledger could not be read from at the start
    # either goes ahead without it.
    echo "[$(date)] Refreshing the GDPR deletion ledger once more before the swap..."
    if ! /usr/local/bin/backup.sh ledger; then
        if [ "$ledger_refreshed" = "1" ]; then
            echo "[$(date)] ERROR: could not refresh the GDPR deletion ledger; not swapping. The" >&2
            echo "  erasures made since its refresh at the start would be lost with the swap." >&2
            echo "  ${DB_NAME} is unchanged, and ${RESTORE_DB} keeps the restored copy until the" >&2
            echo "  next run drops it." >&2
            exit 1
        fi
        echo "[$(date)] WARN: could not refresh the GDPR deletion ledger before the swap either;" >&2
        echo "  it holds the erasures up to its last successful run" >&2
    fi
fi

if [ "$live_found" = "1" ]; then
    echo "[$(date)] Swapping: ${DB_NAME} -> ${REPLACED_DB}, ${RESTORE_DB} -> ${DB_NAME}"
else
    echo "[$(date)] Renaming ${RESTORE_DB} to ${DB_NAME}"
fi
if ! swap_databases; then
    echo "[$(date)] ERROR: the swap failed and changed nothing: ${DB_NAME} is as it was," >&2
    echo "  and ${RESTORE_DB} keeps the restored copy until the next run drops it." >&2
    exit 1
fi

echo "[$(date)] Database restored: ${DB_NAME} now holds $(basename "$BACKUP_FILE")."
if [ "$live_found" = "1" ]; then
    replaced_size=$(admin_psql -At -v name="$REPLACED_DB" <<'SQL'
SELECT pg_size_pretty(pg_database_size(:'name'));
SQL
) || replaced_size="size unknown"
    echo "[$(date)] The database it replaced is kept as ${REPLACED_DB} (${replaced_size})."
fi
echo ""
echo "============================================================"
echo " ACTION REQUIRED — re-apply the GDPR erasures, THEN start"
echo "============================================================"
echo " This was a SQL-only restore. Personal data that was lawfully"
echo " erased AFTER this backup was taken has just been"
echo " re-materialised. If the media volume needs restoring too, do"
echo " that first (step 3 in the header of backups/restore.sh). Then,"
echo " with backend and huey still stopped, run from the repo root"
echo " (migrates first, then replays the ledger):"
echo ""
echo "     docker compose exec -T backup cat ${LEDGER_FILE} \\"
echo "       | docker compose run --rm --no-deps -T -e SKIP_MIGRATIONS=0 \\"
echo "           huey manage replay_gdpr_deletions --ledger -"
echo ""
echo " Only then start the app again:"
echo ""
echo "     docker compose up -d backend huey"
echo "     docker compose restart gateway"
echo ""
echo " Starting it first serves the re-materialised personal data."
if [ "$live_found" = "1" ]; then
    echo ""
    echo " The database as it was before the restore is kept, a full"
    echo " copy on the same disk that no erasure from now on reaches."
    echo " Drop it once the restored data has proven good:"
    echo ""
    echo "     docker compose exec postgres dropdb -U ${DB_USER} ${REPLACED_DB}"
    echo ""
    echo " To go back to it instead, stop backend and huey, then swap"
    echo " the names back (both renames in one transaction):"
    echo ""
    echo "     docker compose exec postgres psql -U ${DB_USER} -d ${ADMIN_DB} -c \\"
    echo "       'ALTER DATABASE \"${DB_NAME}\" RENAME TO \"${RESTORE_DB}\"; ALTER DATABASE \"${REPLACED_DB}\" RENAME TO \"${DB_NAME}\"'"
fi
echo "============================================================"
