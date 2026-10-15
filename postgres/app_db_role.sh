#!/bin/sh
set -eu

# ── The app's own database role ────────────────────────────────
# Usage: app_db_role.sh [--check] [<database>]
#
# The postgres image makes POSTGRES_USER the server's superuser. A superuser
# can run shell commands on the database server (COPY ... PROGRAM), read and
# write its files, change its configuration, create roles, and switch the
# finalized-document triggers off for its session (session_replication_role).
# The app needs none of that, only to own its database: the owner creates the
# tenant schemas and runs the migrations. So backend and huey log in as
# APP_DB_USER, a role without SUPERUSER, CREATEDB, CREATEROLE, REPLICATION or
# BYPASSRLS that owns the database and everything in it. The superuser stays
# for backups, restores and psql. Without APP_DB_USER this script does nothing,
# and the app logs in as the superuser.
#
# Run as the superuser, as often as needed. It
#   - creates APP_DB_USER with the password APP_DB_PASSWORD when the role
#     doesn't exist; an existing role only loses the attributes above and keeps
#     its password (change that with psql's \password),
#   - makes the role the owner of the database (<database>, else POSTGRES_DB),
#   - hands it the schemas, tables, views, sequences, functions and types the
#     superuser owns there, outside the system schemas and the extensions
#     (btree_gist keeps its owner). The migrations make no other kind.
# Every change commits on its own, so a run that stops halfway is finished by
# running it again. With --check it changes nothing, and fails unless the role
# exists without those attributes and owns the database and everything the
# superuser would otherwise hand over.
#
# It runs in the postgres container from /docker-entrypoint-initdb.d when the
# data volume is created, in backups/restore.sh on the new database a restore
# then fills as the role, and with --check in scripts/deploy.sh before a
# release starts.
#
# The role owns the public schema and may create schemas, so it can put an
# operator or a function where a superuser's session looks a name up, and have
# its own code run with the superuser's rights. Every session of this script
# looks names up in pg_catalog only, and so must a superuser's psql in this
# database: PGOPTIONS='-c search_path=pg_catalog' psql ..., with every table
# named with its schema.
#
# Moving a running database over, from the repo root on the server, at a
# quiet moment and not during the nightly backup:
#   1. Add to .env, and save the password in the password manager:
#        APP_DB_USER=jasmin_app
#        APP_DB_PASSWORD=<openssl rand -hex 32>
#   2. docker compose exec backup /usr/local/bin/backup.sh now
#   3. docker compose stop backend huey
#      Each change takes its object's lock for a moment; with the app stopped
#      nothing waits on them.
#   4. docker compose up -d postgres
#      The container takes the two variables (a restart of a few seconds).
#   5. docker compose exec postgres /docker-entrypoint-initdb.d/app_db_role.sh
#   6. docker compose up -d backend huey backup
#      docker compose restart gateway
#   7. docker compose exec postgres /docker-entrypoint-initdb.d/app_db_role.sh --check
#      and create a test tenant in the super-admin UI, then delete it.
# To go back, take the two lines out of .env and repeat step 6: the superuser
# reaches every object, whoever owns it.
# ───────────────────────────────────────────────────────────────

CHECK=0
if [ "${1:-}" = "--check" ]; then
    CHECK=1
    shift
fi
DATABASE="${1:-${POSTGRES_DB:?POSTGRES_DB must be set}}"
SUPERUSER="${POSTGRES_USER:?POSTGRES_USER must be set}"
APP_USER="${APP_DB_USER:-}"

if [ -z "$APP_USER" ]; then
    echo "[$(date)] APP_DB_USER is not set: the app logs in as ${SUPERUSER}; nothing to do."
    exit 0
fi
if [ "$APP_USER" = "$SUPERUSER" ]; then
    echo "[$(date)] ERROR: APP_DB_USER has to be a role of its own, not the superuser ${SUPERUSER}." >&2
    exit 1
fi

# psql on DATABASE as the superuser, without a psqlrc, stopping at the first
# error, with names looked up in pg_catalog only (see the header). SQL that uses
# -v variables comes on stdin: psql fills them in there, never in a -c command.
run_psql() {
    PGOPTIONS="-c search_path=pg_catalog" \
        psql -X -q -At -v ON_ERROR_STOP=1 -v app="$APP_USER" -v db="$DATABASE" \
        --username "$SUPERUSER" --dbname "$DATABASE" "$@"
}

# Prints how many objects the superuser still owns in DATABASE outside the
# system schemas and the extensions: the ones this script hands over.
superuser_objects() {
    run_psql <<'SQL'
WITH owned (kind, oid, owner, namespace) AS (
    SELECT 'pg_namespace'::regclass, oid, nspowner, oid FROM pg_namespace
    UNION ALL
    SELECT 'pg_class'::regclass, oid, relowner, relnamespace FROM pg_class
    WHERE relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    UNION ALL
    SELECT 'pg_proc'::regclass, oid, proowner, pronamespace FROM pg_proc
    UNION ALL
    SELECT 'pg_type'::regclass, t.oid, t.typowner, t.typnamespace
    FROM pg_type t LEFT JOIN pg_class c ON c.oid = t.typrelid
    WHERE t.typtype IN ('d', 'e', 'r') OR (t.typtype = 'c' AND c.relkind = 'c')
)
SELECT count(*)
FROM owned o
JOIN pg_namespace n ON n.oid = o.namespace
WHERE o.owner = to_regrole(current_user)
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg\_%'
  AND NOT EXISTS (
      SELECT 1 FROM pg_depend d
      WHERE d.classid = o.kind AND d.objid = o.oid AND d.deptype = 'e'
  );
SQL
}

if [ "$CHECK" = "1" ]; then
    state=$(run_psql <<'SQL'
SELECT CASE
    WHEN r.oid IS NULL THEN 'missing'
    WHEN r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication
         OR r.rolbypassrls OR NOT r.rolcanlogin THEN 'attributes'
    WHEN d.datdba <> r.oid THEN 'database'
    ELSE 'ok'
END
FROM pg_database d
LEFT JOIN pg_roles r ON r.rolname = :'app'
WHERE d.datname = :'db';
SQL
)
    left=$(superuser_objects)
    case "$state" in
        missing) problem="the role ${APP_USER} doesn't exist" ;;
        attributes) problem="the role ${APP_USER} can't log in, or has rights the app must not have" ;;
        database) problem="${APP_USER} doesn't own the database ${DATABASE}" ;;
        ok) problem="" ;;
        *) problem="the check got no answer about ${APP_USER} in ${DATABASE}" ;;
    esac
    if [ -z "$problem" ] && [ "$left" != "0" ]; then
        problem="${SUPERUSER} still owns ${left} object(s) in ${DATABASE}"
    fi
    if [ -n "$problem" ]; then
        echo "[$(date)] ERROR: ${problem}." >&2
        echo "  Hand the database to ${APP_USER} as the header of postgres/app_db_role.sh" >&2
        echo "  describes, or take APP_DB_USER and APP_DB_PASSWORD out of .env to let the" >&2
        echo "  app log in as ${SUPERUSER} again." >&2
        exit 1
    fi
    echo "[$(date)] ${APP_USER} owns ${DATABASE} and everything in it."
    exit 0
fi

role_exists=$(run_psql <<'SQL'
SELECT count(*) FROM pg_roles WHERE rolname = :'app';
SQL
)
if [ "$role_exists" = "0" ] && [ -z "${APP_DB_PASSWORD:-}" ]; then
    echo "[$(date)] ERROR: the role ${APP_USER} doesn't exist yet, and APP_DB_PASSWORD is empty." >&2
    exit 1
fi

# The password comes from the environment through \getenv, so it is on no
# command line.
run_psql <<'SQL'
SELECT count(*) > 0 AS role_exists FROM pg_roles WHERE rolname = :'app' \gset
\if :role_exists
ALTER ROLE :"app" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\else
\getenv password APP_DB_PASSWORD
CREATE ROLE :"app" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'password';
\endif
ALTER DATABASE :"db" OWNER TO :"app";
SQL

before=$(superuser_objects)

# Schemas first, then tables and views, which take their indexes and the
# sequences of their columns along; then the sequences left, the routines (the
# finalized-protection trigger functions among them) and the types.
run_psql <<'SQL'
SELECT format('ALTER SCHEMA %I OWNER TO %I', n.nspname, :'app')
FROM pg_namespace n
WHERE n.nspowner = to_regrole(current_user)
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg\_%'
  AND NOT EXISTS (
      SELECT 1 FROM pg_depend d
      WHERE d.classid = 'pg_namespace'::regclass AND d.objid = n.oid AND d.deptype = 'e'
  )
ORDER BY n.nspname
\gexec

SELECT format(
    'ALTER %s %s OWNER TO %I',
    CASE c.relkind
        WHEN 'v' THEN 'VIEW'
        WHEN 'm' THEN 'MATERIALIZED VIEW'
        WHEN 'f' THEN 'FOREIGN TABLE'
        ELSE 'TABLE'
    END,
    c.oid::regclass,
    :'app'
)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relowner = to_regrole(current_user)
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg\_%'
  AND NOT EXISTS (
      SELECT 1 FROM pg_depend d
      WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'
  )
ORDER BY n.nspname, c.relname
\gexec

SELECT format('ALTER SEQUENCE %s OWNER TO %I', c.oid::regclass, :'app')
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relowner = to_regrole(current_user)
  AND c.relkind = 'S'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg\_%'
  AND NOT EXISTS (
      SELECT 1 FROM pg_depend d
      WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'
  )
ORDER BY n.nspname, c.relname
\gexec

SELECT format('ALTER ROUTINE %s OWNER TO %I', p.oid::regprocedure, :'app')
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.proowner = to_regrole(current_user)
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg\_%'
  AND NOT EXISTS (
      SELECT 1 FROM pg_depend d
      WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'
  )
ORDER BY n.nspname, p.proname
\gexec

SELECT format(
    'ALTER %s %s OWNER TO %I',
    CASE t.typtype WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END,
    t.oid::regtype,
    :'app'
)
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
LEFT JOIN pg_class c ON c.oid = t.typrelid
WHERE t.typowner = to_regrole(current_user)
  AND (t.typtype IN ('d', 'e', 'r') OR (t.typtype = 'c' AND c.relkind = 'c'))
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg\_%'
  AND NOT EXISTS (
      SELECT 1 FROM pg_depend d
      WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e'
  )
ORDER BY n.nspname, t.typname
\gexec
SQL

left=$(superuser_objects)
if [ "$left" != "0" ]; then
    echo "[$(date)] ERROR: ${SUPERUSER} still owns ${left} object(s) in ${DATABASE}." >&2
    exit 1
fi
echo "[$(date)] ${APP_USER} owns ${DATABASE}; handed over ${before} object(s)."
