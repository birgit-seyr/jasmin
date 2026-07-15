#!/usr/bin/env bash
# =============================================================================
# validate_gateway_config.sh — render nginx.conf.template exactly like the
# gateway container does (same envsubst var list, same mounts) and run
# `nginx -t` on the result in a throwaway container, WITHOUT touching the
# running gateway. Run this before `docker compose restart gateway` after any
# template edit — a broken config otherwise takes the gateway down until
# rolled back.
#
# Run from the repo root on the prod host:
#   ./scripts/validate_gateway_config.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
ENV_FILE="${REPO_ROOT}/.env"
[ -f "$ENV_FILE" ] || { echo "❌ .env not found"; exit 1; }

envval() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-; }

PROJECT="$(envval COMPOSE_PROJECT_NAME)"; PROJECT="${PROJECT:-jasmin-platform}"
FRONTEND_DOMAIN="$(envval FRONTEND_DOMAIN)"
SUPER_ADMIN_SUBDOMAIN="$(envval SUPER_ADMIN_SUBDOMAIN)"; SUPER_ADMIN_SUBDOMAIN="${SUPER_ADMIN_SUBDOMAIN:-marillen}"
BUNNY_ORIGIN_SECRET="$(envval BUNNY_ORIGIN_SECRET)"
# Mirror docker-compose's ${BUNNY_ORIGIN_SECRET:+on} derivation exactly.
BUNNY_ORIGIN_ENFORCE=""; [ -n "$BUNNY_ORIGIN_SECRET" ] && BUNNY_ORIGIN_ENFORCE="on"

# Same image as the gateway service; join the compose network so the
# ``upstream`` hostnames (backend/frontend) resolve during nginx -t.
docker run --rm \
    --network "${PROJECT}_jasmin-net" \
    -e FRONTEND_DOMAIN="$FRONTEND_DOMAIN" \
    -e SUPER_ADMIN_SUBDOMAIN="$SUPER_ADMIN_SUBDOMAIN" \
    -e BACKEND_HOST=backend -e BACKEND_PORT=8000 \
    -e FRONTEND_HOST=frontend -e FRONTEND_PORT=80 \
    -e BUNNY_ORIGIN_SECRET="$BUNNY_ORIGIN_SECRET" \
    -e BUNNY_ORIGIN_ENFORCE="$BUNNY_ORIGIN_ENFORCE" \
    -v "$REPO_ROOT/nginx/nginx.conf.template:/etc/nginx/templates/nginx.conf.template:ro" \
    -v "$REPO_ROOT/nginx/super_admin_allowed_ips.conf:/etc/nginx/super_admin_allowed_ips.conf:ro" \
    -v "$REPO_ROOT/nginx/security_headers.conf:/etc/nginx/security_headers.conf:ro" \
    -v "$REPO_ROOT/nginx/security_headers_admin.conf:/etc/nginx/security_headers_admin.conf:ro" \
    -v "${PROJECT}_certbot_conf:/etc/letsencrypt:ro" \
    -v "${PROJECT}_certbot_www:/var/www/certbot:ro" \
    nginx:1.27-alpine \
    sh -c "envsubst '\$FRONTEND_DOMAIN \$SUPER_ADMIN_SUBDOMAIN \$BACKEND_HOST \$BACKEND_PORT \$FRONTEND_HOST \$FRONTEND_PORT \$BUNNY_ORIGIN_SECRET \$BUNNY_ORIGIN_ENFORCE' \
           < /etc/nginx/templates/nginx.conf.template > /tmp/rendered.conf \
           && nginx -t -c /tmp/rendered.conf"

echo "✅ rendered gateway config is valid — safe to: docker compose restart gateway"
