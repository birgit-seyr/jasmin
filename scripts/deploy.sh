#!/usr/bin/env bash
# =============================================================================
# deploy.sh — first-deploy (and redeploy) orchestrator. Run from the repo root
# on the server, as the non-root user (must be in the 'docker' group).
#
# It:
#   1. validates .env (exists, no CHANGE_ME left, required vars set)
#   2. issues the wildcard TLS cert if it isn't in the volume yet
#   3. builds the images
#   4. brings up the CORE stack (skips glitchtip/uptime — Phase 5)
#   5. waits for the backend to migrate + report healthy
#   6. smoke-tests HTTPS
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
[ -f "$ENV_FILE" ] || die ".env not found — run scripts/init-env.sh first."

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
GLITCHTIP_DOMAIN GLITCHTIP_DB_PASSWORD GLITCHTIP_SECRET_KEY \
DJANGO_SUPERUSER_EMAIL DJANGO_SUPERUSER_PASSWORD"
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
docker compose build

# ── 4. bring up the core stack (glitchtip/uptime deferred to Phase 5) ───────
log "starting core services"
docker compose up -d postgres redis backend huey frontend gateway certbot backup

# nginx resolves the backend/frontend upstream hostnames ONCE, at startup.
# `up -d` may RECREATE those containers with NEW network IPs while the
# (config-unchanged) gateway keeps running against the stale ones — result:
# static pages still load but every /api/ call 502s ("nobody can log in").
# Restarting the gateway after every up forces a fresh resolve. Sub-second.
log "restarting gateway (refresh upstream DNS after possible recreates)"
docker compose restart gateway

# ── 5. wait for the backend to migrate + go healthy ──────────────────────────
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

# ── 6. smoke test (best-effort) ──────────────────────────────────────────────
code="$(curl -ksS -o /dev/null -w '%{http_code}' "https://${DOMAIN}/health/" 2>/dev/null || echo 000)"
log "https://${DOMAIN}/health/ -> HTTP ${code} (expect 200)"

echo ""
echo "✅ Deploy run complete."
echo "   Next (see the runbook, Phase 2.5+):"
echo "   1. Add your IP to nginx/super_admin_allowed_ips.conf, then:"
echo "        docker compose restart gateway"
echo "   2. Log in at https://${ADMIN_HOST}.${DOMAIN} and create your tenants."
echo "   3. Configure EACH tenant's own SMTP before inviting its users."
echo "   4. Wire off-host backups (Phase 3), then run scripts/restore_drill.sh."
