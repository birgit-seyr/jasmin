#!/usr/bin/env bash
# =============================================================================
# validate_gateway_config.sh — render the gateway config exactly like the
# gateway container does (nginx/render_config.sh, same environment, same
# mounts) and run `nginx -t` on it in a throwaway container, WITHOUT touching the
# running gateway. Run it before applying a template edit or a change to the
# gateway's .env values — a broken config otherwise takes the gateway down,
# every host with it, until rolled back. Apply with
# `docker compose up -d --force-recreate gateway`: a plain restart keeps the
# environment the container was created with, so it misses a .env change.
#
# Run from the repo root on the prod host:
#   ./scripts/validate_gateway_config.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
ENV_FILE="${REPO_ROOT}/.env"
[ -f "$ENV_FILE" ] || { echo "❌ .env not found"; exit 1; }

# A missing key reads as empty, so the defaults below apply: under pipefail,
# grep finding no line would otherwise end the script without a message.
envval() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true; }

PROJECT="$(envval COMPOSE_PROJECT_NAME)"; PROJECT="${PROJECT:-jasmin-platform}"
FRONTEND_DOMAIN="$(envval FRONTEND_DOMAIN)"
SUPER_ADMIN_SUBDOMAIN="$(envval SUPER_ADMIN_SUBDOMAIN)"; SUPER_ADMIN_SUBDOMAIN="${SUPER_ADMIN_SUBDOMAIN:-marillen}"
BUNNY_ORIGIN_SECRET="$(envval BUNNY_ORIGIN_SECRET)"
BUNNY_ORIGIN_SECRET_NEXT="$(envval BUNNY_ORIGIN_SECRET_NEXT)"
# Handed to docker by name (-e NAME), so the values never show in the process list.
export BUNNY_ORIGIN_SECRET BUNNY_ORIGIN_SECRET_NEXT

# Same image as the gateway service; join the compose network so the
# ``upstream`` hostnames (backend/frontend) resolve during nginx -t.
docker run --rm \
    --network "${PROJECT}_jasmin-net" \
    -e FRONTEND_DOMAIN="$FRONTEND_DOMAIN" \
    -e SUPER_ADMIN_SUBDOMAIN="$SUPER_ADMIN_SUBDOMAIN" \
    -e BACKEND_HOST=backend -e BACKEND_PORT=8000 \
    -e FRONTEND_HOST=frontend -e FRONTEND_PORT=80 \
    -e BUNNY_ORIGIN_SECRET -e BUNNY_ORIGIN_SECRET_NEXT \
    -v "$REPO_ROOT/nginx/nginx.conf.template:/etc/nginx/templates/nginx.conf.template:ro" \
    -v "$REPO_ROOT/nginx/render_config.sh:/etc/nginx/render_config.sh:ro" \
    -v "$REPO_ROOT/nginx/bunny_edges:/etc/nginx/bunny_edges:ro" \
    -v "$REPO_ROOT/nginx/super_admin_allowed_ips.conf:/etc/nginx/super_admin_allowed_ips.conf:ro" \
    -v "$REPO_ROOT/nginx/security_headers.conf:/etc/nginx/security_headers.conf:ro" \
    -v "$REPO_ROOT/nginx/security_headers_admin.conf:/etc/nginx/security_headers_admin.conf:ro" \
    -v "${PROJECT}_certbot_conf:/etc/letsencrypt:ro" \
    -v "${PROJECT}_certbot_www:/var/www/certbot:ro" \
    nginx:1.31-alpine \
    sh -c "sh /etc/nginx/render_config.sh && nginx -t"

echo "✅ rendered gateway config is valid — apply it with: docker compose up -d --force-recreate gateway"
