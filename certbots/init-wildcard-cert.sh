#!/usr/bin/env bash
# =============================================================================
# Issue an initial wildcard Let's Encrypt certificate for the platform.
#
# Wildcard certs (e.g. *.mydomain.com) require DNS-01 validation. This script
# uses the Linode DNS plugin.
#
# Pre-reqs:
#   - DNS for ${DOMAIN} is managed by Linode (NS records point at
#     ns1.linode.com ... ns5.linode.com).
#   - You have a Linode Personal Access Token with read/write scope on Domains
#     (Linode Cloud Manager → Profile → API Tokens → Create A Personal Access
#     Token → Domains: Read/Write, everything else: None).
#   - Place the token at ./certbots/linode.ini with content:
#       dns_linode_key = <token>
#       dns_linode_version = 4
#     and chmod 600 it.
#
# Usage:
#   DOMAIN=mydomain.com EMAIL=you@example.com ./certbots/init-wildcard-cert.sh
#
# After this succeeds, `docker compose up -d gateway` will pick up the cert
# from the certbot_conf volume. Renewals are handled by the long-running
# certbot service in docker-compose.yml (see `entrypoint:` block).
# =============================================================================
set -euo pipefail

DOMAIN="${DOMAIN:?DOMAIN is required (e.g. mydomain.com)}"
EMAIL="${EMAIL:?EMAIL is required (for Lets Encrypt renewal notices)}"
CREDENTIALS="${CREDENTIALS:-./certbots/linode.ini}"

if [[ ! -f "${CREDENTIALS}" ]]; then
    echo "❌ Credentials file not found at ${CREDENTIALS}"
    echo "   Create it with:"
    echo "       dns_linode_key = <token>"
    echo "       dns_linode_version = 4"
    echo "   And run: chmod 600 ${CREDENTIALS}"
    exit 1
fi

# Ensure named volumes exist by bringing up the certbot service briefly.
docker compose up --no-start certbot >/dev/null

docker run --rm \
    -v jasmin-platform_certbot_conf:/etc/letsencrypt \
    -v jasmin-platform_certbot_www:/var/www/certbot \
    -v "$(realpath "${CREDENTIALS}"):/linode.ini:ro" \
    certbot/dns-linode:latest \
    certonly \
    --dns-linode \
    --dns-linode-credentials /linode.ini \
    --dns-linode-propagation-seconds 120 \
    --email "${EMAIL}" \
    --agree-tos \
    --no-eff-email \
    --non-interactive \
    -d "${DOMAIN}" \
    -d "*.${DOMAIN}"

echo ""
echo "✅ Wildcard certificate issued for ${DOMAIN} and *.${DOMAIN}"
echo "   docker compose up -d gateway   # to start serving with the new cert"
