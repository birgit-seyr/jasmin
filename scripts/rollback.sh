#!/usr/bin/env bash
# =============================================================================
# rollback.sh — run one of the last releases again, without a rebuild.
#
#   ./scripts/rollback.sh             # list the releases kept on this host
#   ./scripts/rollback.sh <release>   # switch back to one of them
#
# deploy.sh tags every release's images with the UTC time and git short hash
# of its build (20261002-180133-a1b2c3d) and keeps the last few
# (KEEP_RELEASES there). A rollback points the tag compose runs (IMAGE_TAG) at
# an earlier release's images and recreates backend, huey, frontend and
# backup. The checkout stays where it is: revert or fix forward, push, and the
# next ./scripts/update.sh deploys HEAD again — until then don't re-run it, or
# it rebuilds the release you just left.
#
# Migrations are forward-only, so the earlier code runs on the database as it
# is now. A release with a migration the database hasn't applied is refused:
# its migrations have to be a prefix of the applied ones. The migrations the
# database has that the release doesn't know are listed for you to confirm —
# additive ones are fine, a dropped or renamed column the earlier code still
# uses is not.
#
# After the switch it probes https://<domain>/health/ready/, which answers 200
# only while the backend reaches the database and Redis takes writes. A failed
# probe stops nothing: it is reported with what to check next, and the script
# exits 1 at the very end, after every step has run. A release older than that
# probe only has /health/ (liveness), which is checked instead, with a note.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

die() { echo "❌ $*" >&2; exit 1; }
log() { echo "[rollback] $*"; }

[ -f .env ] || die ".env not found — run this from the repo root on the server."

# The images this repo builds, as compose runs them (repository:IMAGE_TAG).
IMAGES="$(docker compose config --images | grep '^jasmin/' | sort -u || true)"
BACKEND_IMAGE="$(grep '^jasmin/backend:' <<< "$IMAGES" || true)"
[ -n "$BACKEND_IMAGE" ] || die "docker-compose.yml runs no jasmin/backend image."
BACKEND_REPOSITORY="${BACKEND_IMAGE%:*}"
FRONTEND_IMAGE="$(grep '^jasmin/frontend:' <<< "$IMAGES" || true)"
FRONTEND_REPOSITORY="${FRONTEND_IMAGE%:*}"

# The release tags of repository $1, newest first.
release_tags() {
    docker image ls "$1" --format '{{.Tag}}' | grep -E '^[0-9]{8}-[0-9]{6}-' | sort -r || true
}

# The image the container of service $1 runs, if it is up.
running_image() {
    local cid
    cid="$(docker compose ps -q "$1" 2>/dev/null || true)"
    [ -z "$cid" ] || docker inspect -f '{{.Image}}' "$cid"
}

# The images of release $1 that a release can be told apart by.
release_images() {
    echo "$(docker image inspect -f '{{.Id}}' "${BACKEND_REPOSITORY}:$1" 2>/dev/null || true)" \
        "$(docker image inspect -f '{{.Id}}' "${FRONTEND_REPOSITORY}:$1" 2>/dev/null || true)"
}

list_releases() {
    local running tags tag subject marker
    running="$(running_image backend) $(running_image frontend)"
    tags="$(release_tags "$BACKEND_REPOSITORY")"
    if [ -z "$tags" ]; then
        echo "No releases kept yet — deploy.sh tags one on every deploy."
        return
    fi
    echo "Releases kept on this host, newest first (built at, UTC):"
    for tag in $tags; do
        subject="$(git log -1 --format=%s "${tag##*-}" 2>/dev/null | cut -c1-60 || true)"
        marker=""
        [ "$(release_images "$tag")" != "$running" ] || marker="  ← running"
        printf '  %s  %s%s\n' "$tag" "$subject" "$marker"
    done
    echo ""
    echo "Switch with: ./scripts/rollback.sh <release>"
}

RELEASE="${1:-}"
if [ -z "$RELEASE" ]; then
    list_releases
    exit 0
fi

for image in $IMAGES; do
    docker image inspect "${image%:*}:${RELEASE}" >/dev/null 2>&1 || \
        die "${image%:*}:${RELEASE} isn't on this host. ./scripts/rollback.sh lists the releases kept."
done

# ── migrations ───────────────────────────────────────────────────────────────
# The release's own code compares its migrations with what every schema has
# applied. It reads only, and runs with the backend container's network and
# its compose environment (not the image's, so the release keeps its own
# PATH and the like).
APP_CID="$(docker compose ps -a -q backend 2>/dev/null | head -n 1)"
[ -n "$APP_CID" ] || die "no backend container to take the environment and network from."
NETWORK="$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
    "$APP_CID" | head -n 1)"
APP_ENV_FILE="$(mktemp)"
trap 'rm -f "$APP_ENV_FILE"' EXIT
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$APP_CID" \
    | grep -vxF -f <(docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' \
        "$(docker inspect -f '{{.Image}}' "$APP_CID")") \
    > "$APP_ENV_FILE" || true

read -r -d '' MIGRATION_CHECK <<'PY' || true
import django

django.setup()

from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django_tenants.utils import get_public_schema_name, get_tenant_model

public = get_public_schema_name()
connection.set_schema_to_public()
schemas = [public] + sorted(
    get_tenant_model()
    .objects.exclude(schema_name=public)
    .values_list("schema_name", flat=True)
)
missing, unknown = set(), set()
for schema in schemas:
    connection.set_schema(schema)
    if not MigrationRecorder(connection).has_table():
        print(f"note: schema {schema} has no migration table; skipped")
        continue
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    known = set(loader.graph.nodes)
    replaced = {
        key
        for migration in loader.disk_migrations.values()
        for key in (migration.replaces or [])
    }
    applied = set(loader.applied_migrations)
    missing |= {(schema, app, name) for app, name in known - applied}
    unknown |= (applied - known) - replaced
for schema, app, name in sorted(missing):
    print(f"missing: {app}.{name} (schema {schema})")
for app, name in sorted(unknown):
    print(f"unknown: {app}.{name}")
PY

# Runs the check with image $1 and prints its report.
check_migrations() {
    docker run --rm --network "$NETWORK" --env-file "$APP_ENV_FILE" -e SENTRY_DSN= \
        --entrypoint python "$1" -c "$MIGRATION_CHECK" 2>&1
}

log "comparing ${RELEASE}'s migrations with the database"
if ! report="$(check_migrations "${BACKEND_REPOSITORY}:${RELEASE}")"; then
    echo "$report" | tail -n 20 >&2
    die "could not compare ${RELEASE}'s migrations with the database."
fi
grep '^note: ' <<< "$report" | sed 's/^note: /    /' || true
missing="$(grep '^missing: ' <<< "$report" | sed 's/^missing: //' || true)"
# Records the running release doesn't know either — left behind by squashed or
# deleted migration files — don't concern the rollback. If the running release
# can't even run the check, the list stays complete.
if ! baseline="$(check_migrations "$BACKEND_IMAGE")"; then
    log "the running release couldn't run the check; the list below may include old records"
fi
unknown="$(comm -23 <(grep '^unknown: ' <<< "$report" | sort || true) \
                    <(grep '^unknown: ' <<< "$baseline" | sort || true) \
           | sed 's/^unknown: //')"

if [ -n "$missing" ]; then
    echo "$missing" | sed 's/^/    /' >&2
    die "${RELEASE} has migrations the database hasn't applied (above), so it isn't an earlier state of it — built from another branch, or never deployed here."
fi

echo ""
if [ -n "$unknown" ]; then
    echo "The database has $(wc -l <<< "$unknown" | tr -d ' ') migration(s) ${RELEASE} doesn't know; its code will run against them:"
    echo "$unknown" | sed 's/^/    /'
    echo "Additive ones (a new table, a nullable or defaulted column) are fine; a dropped or"
    echo "renamed column that ${RELEASE} still uses is not."
else
    echo "${RELEASE} knows every migration the database has applied."
fi
read -r -p "Switch backend, huey, frontend and backup to ${RELEASE}? [y/N] " answer
case "$answer" in
    [Yy]*) ;;
    *) echo "Nothing changed."; exit 0 ;;
esac

# ── switch ───────────────────────────────────────────────────────────────────
for image in $IMAGES; do
    docker tag "${image%:*}:${RELEASE}" "$image"
done
log "recreating the containers on ${RELEASE} (up -d waits until the backend is healthy)"
docker compose up -d --no-build backend huey frontend backup
# nginx resolves the upstreams once, at startup — see deploy.sh.
docker compose restart gateway

# ── readiness smoke test ─────────────────────────────────────────────────────
# /health/ready/ answers 200 only while the backend reaches the database and
# Redis takes writes; /health/, the containers' healthcheck, stays 200 through
# an outage of either. A failure stops nothing: it is reported here, and the
# script exits 1 at the very end.

# Prints the HTTP code of URL $1. No answer yet (000, the gateway restarted a
# moment ago) and 5xx are retried a few times; --max-time keeps a hung backend
# from stalling the rollback. curl prints 000 itself when it gets no answer.
probe() {
    local attempt code
    for attempt in 1 2 3 4 5 6; do
        code="$(curl -ksS -o /dev/null --max-time 10 -w '%{http_code}' "$1" 2>/dev/null || true)"
        code="${code:-000}"
        case "$code" in
            000 | 5??) ;;
            *) break ;;
        esac
        [ "$attempt" -eq 6 ] || sleep 5
    done
    echo "$code"
}

# What a failed readiness probe means and where to look next. $1: the URL,
# $2: the HTTP code it answered.
warn_not_ready() {
    local meaning
    case "$2" in
        503) meaning="The backend answers but can't reach the database or can't write to Redis." ;;
        502 | 504) meaning="The gateway can't reach the backend." ;;
        000) meaning="No answer: the gateway is down, TLS or DNS fails, or the backend hangs." ;;
        *) meaning="The readiness probe never answers that: is this the right host and release?" ;;
    esac
    cat >&2 <<EOF

⚠️  ==========================================================================
⚠️  NOT READY: $1 -> HTTP $2
⚠️  ${meaning}
⚠️  The containers may still report healthy: their healthcheck, /health/, touches
⚠️  neither the database nor Redis. Real requests are failing.
⚠️  Next:
⚠️    docker compose ps                     # postgres, redis, backend up and healthy?
⚠️    docker compose logs --tail=200 backend
⚠️        # "health.ready.unavailable component=..." names what failed, the
⚠️        # traceback below it says why
⚠️    docker compose logs --tail=100 postgres redis gateway
⚠️    docker compose exec redis sh -c 'redis-cli -a "\$REDIS_PASSWORD" --no-auth-warning info memory'
⚠️        # used_memory over maxmemory: Redis refuses writes
⚠️  Check again with: curl -k $1
⚠️  If ${RELEASE} itself is the cause, ./scripts/rollback.sh lists the other releases.
⚠️  ==========================================================================
EOF
}

DOMAIN="$(grep -E '^FRONTEND_DOMAIN=' .env | head -1 | cut -d= -f2-)"
READY_URL="https://${DOMAIN}/health/ready/"
ready_code="$(probe "$READY_URL")"
log "${READY_URL} -> HTTP ${ready_code} (expect 200)"
ready=1
if [ "$ready_code" != "200" ]; then
    # A release older than the readiness probe answers its path like any other
    # unknown one on the gateway's host: 400 or 404. Its liveness probe is all
    # there is to check then.
    live_code=""
    case "$ready_code" in
        400 | 404)
            live_code="$(probe "https://${DOMAIN}/health/")"
            log "https://${DOMAIN}/health/ -> HTTP ${live_code} (expect 200)"
            ;;
    esac
    if [ "$live_code" = "200" ]; then
        log "${RELEASE} predates /health/ready/, and /health/ leaves out the database and Redis: open a tenant's site to see it serve"
    else
        ready=0
        warn_not_ready "$READY_URL" "$ready_code"
    fi
fi

echo ""
echo "✅ Running ${RELEASE}. The checkout is still at $(git rev-parse --short HEAD): revert"
echo "   or fix the change, push, then ./scripts/update.sh. Until then don't re-run"
echo "   update.sh — it would rebuild and deploy HEAD again."

# The readiness verdict, after every step has run.
if [ "$ready" -ne 1 ]; then
    echo "" >&2
    echo "❌ ${RELEASE} is running but NOT READY: ${READY_URL} answered HTTP ${ready_code} (see the warning above)." >&2
    exit 1
fi
