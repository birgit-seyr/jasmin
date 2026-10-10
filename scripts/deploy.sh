#!/usr/bin/env bash
# =============================================================================
# deploy.sh — first-deploy (and redeploy) orchestrator. Run from the repo root
# on the server, as the non-root user (must be in the 'docker' group).
#
# It:
#   1. validates .env (exists, no CHANGE_ME left, required vars set)
#   2. issues the wildcard TLS cert if it isn't in the volume yet
#   3. pulls the newest build of every image tag, builds the images and tags
#      them as a release (scripts/rollback.sh)
#   4. takes an encrypted snapshot of the database before it is migrated
#   5. brings up the CORE stack (skips glitchtip/uptime — Phase 5)
#   6. waits for the backend to migrate + report healthy
#   7. smoke-tests HTTPS
#
# Idempotent: re-run any time to rebuild + roll the stack. The cert is only
# issued once (skipped when already present).
#
#   ./scripts/deploy.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
ENV_FILE="${REPO_ROOT}/.env"

die() { echo "❌ $*" >&2; exit 1; }
log() { echo "[deploy] $*"; }

# ── preflight ────────────────────────────────────────────────────────────────
[ -f docker-compose.yml ] || die "no docker-compose.yml here — run from the repo root."
command -v docker >/dev/null 2>&1 || die "docker not found — run scripts/bootstrap-server.sh first."
docker info >/dev/null 2>&1 || die "can't talk to docker (add your user to the 'docker' group and re-login)."
[ -f "$ENV_FILE" ] || die ".env not found — restore the production .env from the password manager."

# Read a value from .env (keeps everything after the first '=').
envval() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-; }

# 1a. no unfilled placeholders (the platform SMTP is a hard boot requirement).
# Match "=CHANGE_ME" (value assignments) only — the file's comments mention the
# token too, and matching those would refuse to launch forever.
if grep -qE '=CHANGE_ME' "$ENV_FILE"; then
    echo "❌ .env still has CHANGE_ME placeholders — fill these first:" >&2
    grep -nE '=CHANGE_ME' "$ENV_FILE" | sed 's/^/   /' >&2
    exit 1
fi

# 1a-bis. A lone unescaped "$" in a value is silently mangled by compose
# interpolation (an SMTP password "ab$cd" becomes "ab"); doubled "$$" is fine.
# Generated secrets never contain "$", so this only catches hand-entered creds.
if grep -qE '=([^$]*\$([^$]|$))' "$ENV_FILE"; then
    echo "⚠️  .env has value(s) with a lone '\$' — compose will truncate them." >&2
    echo "    If it's meant literally (common in SMTP tokens), double it to '\$\$':" >&2
    grep -nE '=([^$]*\$([^$]|$))' "$ENV_FILE" | sed 's/^/    /' >&2
fi

# 1b. required vars present (compose fails to parse otherwise; the backend
#     refuses to boot without the email/secret ones)
REQUIRED="COMPOSE_PROJECT_NAME FRONTEND_DOMAIN DJANGO_ALLOWED_HOSTS \
DJANGO_SECRET_KEY FIELD_ENCRYPTION_KEY POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD \
REDIS_PASSWORD BACKUP_ENCRYPTION_KEY EMAIL_HOST EMAIL_ADMIN \
GLITCHTIP_DOMAIN GLITCHTIP_DB_PASSWORD GLITCHTIP_SECRET_KEY"
missing=""
for v in $REQUIRED; do
    [ -n "$(envval "$v")" ] || missing="$missing $v"
done
[ -z "$missing" ] || die "missing/empty required .env vars:$missing"

PROJECT="$(envval COMPOSE_PROJECT_NAME)"
DOMAIN="$(envval FRONTEND_DOMAIN)"
EMAIL="$(envval EMAIL_ADMIN)"
ADMIN_HOST="$(envval SUPER_ADMIN_SUBDOMAIN)"; ADMIN_HOST="${ADMIN_HOST:-admin}"
[ "$PROJECT" = "jasmin-platform" ] || \
    die "COMPOSE_PROJECT_NAME must be 'jasmin-platform' (the cert script hardcodes those volume names). Got '$PROJECT'."

# 1c. certbots/linode.ini must exist BEFORE any `docker compose up` that starts
# the certbot service — compose bind-mounts it as a single file, and Docker
# materialises a missing bind source as a DIRECTORY, silently breaking cert
# renewals and blocking the later file creation. Checked unconditionally (not
# just on first issuance) for exactly that reason.
[ -f certbots/linode.ini ] || die "certbots/linode.ini missing. Create it with your Linode API token:
   printf 'dns_linode_key = <token>\\ndns_linode_version = 4\\n' > certbots/linode.ini && chmod 600 certbots/linode.ini
(needs your domain's nameservers pointed at Linode — see the runbook, Phase 0.2)."

log "domain=$DOMAIN project=$PROJECT"

# Container logs go to the systemd journal (docker-compose.yml); without the
# retention drop-in from bootstrap-server.sh journald keeps its own defaults.
[ -f /etc/systemd/journald.conf.d/90-jasmin.conf ] || \
    log "WARN: no journald retention drop-in — run the '4a. journald' step of scripts/bootstrap-server.sh"

# ── 2. wildcard TLS cert (issue once) ────────────────────────────────────────
# Inspect-first: a bare `docker run -v name:/...` would AUTO-CREATE the named
# volume without compose's ownership labels, and newer compose versions then
# refuse to reuse it at `up`. No volume yet ⇒ definitely no cert.
CERT_VOL="${PROJECT}_certbot_conf"
have_cert=0
if docker volume inspect "$CERT_VOL" >/dev/null 2>&1; then
    if docker run --rm -v "${CERT_VOL}:/etc/letsencrypt:ro" busybox \
           test -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" 2>/dev/null; then
        have_cert=1
    fi
fi
if [ "$have_cert" -eq 1 ]; then
    log "TLS cert already present for ${DOMAIN} — skipping issuance"
else
    log "no cert yet — issuing wildcard cert for ${DOMAIN}"
    DOMAIN="$DOMAIN" EMAIL="$EMAIL" ./certbots/init-wildcard-cert.sh
fi

# ── 3. build ─────────────────────────────────────────────────────────────────
log "building images (first build takes a few minutes)"
# Stamped into the frontend bundle and /build.json: an app still running the
# previous build sees the new id and offers a reload. A timestamp stands in when
# there's no git checkout.
VITE_BUILD_ID="$(git rev-parse --short HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S)"
export VITE_BUILD_ID
# --pull and the pull below fetch the newest build of each tag (python:3.14-slim,
# postgres:15-alpine, …), so OS and library fixes ship with every deploy instead
# of waiting for someone to pull by hand. A registry hiccup — a Docker Hub rate
# limit, an outage — must not block a hotfix, so both fall back to the images
# already on the host and say so.
if ! docker compose build --pull; then
    log "WARN: build with --pull failed — retrying with the base images already on this host"
    docker compose build
fi
# The core stack's images that come from a registry as published (the others
# are built above). Glitchtip and Uptime Kuma aren't started here.
docker compose pull --quiet postgres redis gateway certbot || \
    log "WARN: couldn't pull newer postgres/redis/nginx/certbot images — keeping the ones on this host"

# Compose always runs the IMAGE_TAG tag, which every build moves. Each release
# also keeps its images under a release tag, <UTC time>-<build id>, so
# scripts/rollback.sh can switch back to one of the last KEEP_RELEASES without
# a rebuild. The time is in the tag because an unchanged image (the backup one,
# mostly) keeps its old creation time across builds.
KEEP_RELEASES=5
RELEASE="$(date -u +%Y%m%d-%H%M%S)-${VITE_BUILD_ID}"
# The release tags of repository $1, newest first.
release_tags() {
    docker image ls "$1" --format '{{.Tag}}' | grep -E '^[0-9]{8}-[0-9]{6}-' | sort -r || true
}
for image in $(docker compose config --images | grep '^jasmin/' | sort -u); do
    repository="${image%:*}"
    docker tag "$image" "${repository}:${RELEASE}"
    # Removing a tag deletes the image only when no other tag or container
    # still uses it.
    release_tags "$repository" | tail -n +$((KEEP_RELEASES + 1)) \
        | while read -r tag; do
            docker rmi "${repository}:${tag}" >/dev/null 2>&1 || true
        done
done
log "release ${RELEASE} tagged (the last ${KEEP_RELEASES} are kept)"

# ── 4. snapshot the database before the backend migrates it ─────────────────
# The backend applies migrations when it starts in step 5, so this is the last
# moment the database matches the running release. The freshly built backup
# image takes it like its nightly dumps — encrypted, verified, copied off-host
# — as backups/<db>_predeploy_<timestamp>.sql.gz.gpg, which the GFS prune
# keeps like any other backup. FAIL-CLOSED: no snapshot, no deploy. Skipped
# when postgres isn't running yet (a first deploy has no data to lose).
PG_CID="$(docker compose ps -q postgres 2>/dev/null || true)"
if [ -n "$PG_CID" ] && \
   [ "$(docker inspect -f '{{.State.Running}}' "$PG_CID" 2>/dev/null)" = "true" ]; then
    log "snapshotting the database before migrations run"
    docker compose run --rm --no-deps -T backup predeploy \
        || die "pre-deploy snapshot FAILED — not deploying. The backup output above says why."
else
    log "postgres not running — no pre-deploy snapshot (first deploy?)"
fi

# Database dumps belong in backups/ only encrypted.
plain_dumps="$(find backups -maxdepth 1 -type f \( -name '*.sql' -o -name '*.sql.gz' \) 2>/dev/null || true)"
if [ -n "$plain_dumps" ]; then
    log "WARN: unencrypted database dumps in backups/ — delete them once you've confirmed the encrypted backups:"
    echo "$plain_dumps" | sed 's/^/    /'
fi

# ── 5. bring up the core stack (glitchtip/uptime deferred to Phase 5) ───────
log "starting core services"
docker compose up -d postgres redis backend huey frontend gateway certbot backup

# nginx resolves the backend/frontend upstream hostnames ONCE, at startup.
# `up -d` may RECREATE those containers with NEW network IPs while the
# (config-unchanged) gateway keeps running against the stale ones — result:
# static pages still load but every /api/ call 502s ("nobody can log in").
# Restarting the gateway after every up forces a fresh resolve. Sub-second.
log "restarting gateway (refresh upstream DNS after possible recreates)"
docker compose restart gateway

# ── 6. wait for the backend to migrate + go healthy ──────────────────────────
log "waiting for the backend (runs migrations on first boot — can take minutes)"
BACKEND_CID="$(docker compose ps -q backend)"
healthy=0
for _ in $(seq 1 60); do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$BACKEND_CID" 2>/dev/null || echo starting)"
    if [ "$status" = "healthy" ]; then healthy=1; break; fi
    sleep 10
done
if [ "$healthy" -ne 1 ]; then
    log "WARN: backend not healthy yet. Tail logs with: docker compose logs -f backend"
fi

# ── 7. smoke test (best-effort) ──────────────────────────────────────────────
# curl prints 000 itself when it gets no answer.
code="$(curl -ksS -o /dev/null -w '%{http_code}' "https://${DOMAIN}/health/" 2>/dev/null || true)"
log "https://${DOMAIN}/health/ -> HTTP ${code} (expect 200)"

echo ""
echo "✅ Deploy run complete."
echo "   Next (see the runbook, Phase 2.5+):"
echo "   1. Add your IP to nginx/super_admin_allowed_ips.conf, then:"
echo "        docker compose restart gateway"
echo "   2. Log in at https://${ADMIN_HOST}.${DOMAIN} and create your tenants."
echo "   3. Configure EACH tenant's own SMTP before inviting its users."
echo "   4. Wire off-host backups (Phase 3), then run scripts/restore_drill.sh."
