#!/usr/bin/env bash
# =============================================================================
# refresh_bunny_edge_ips.sh — write nginx/bunny_edges/edges.conf from Bunny's
# published edge-server lists.
#
# While the origin gate is on (nginx/render_config.sh), the tenant hosts take
# the client's IP from X-Forwarded-For only when the request comes from an
# address in this file. deploy.sh runs it before starting the stack; run it by
# hand when enabling the gate, and from the repo root:
#
#   ./scripts/refresh_bunny_edge_ips.sh              # refresh, reload a running gateway
#   ./scripts/refresh_bunny_edge_ips.sh --no-reload  # refresh the file only
#
# What keeps the list trustworthy:
#   * Every entry must parse as a single IPv4 or IPv6 address, so an error page
#     or a tampered answer can't add a directive or a network range.
#   * An answer with too few addresses leaves the file as it is.
#   * A stale list is safe: a Bunny edge missing from it is not trusted, and
#     its requests keep the edge's IP. The gateway's 12-hourly reload picks a
#     refreshed file up even when this script doesn't reload.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
TARGET_DIR="nginx/bunny_edges"
TARGET="${TARGET_DIR}/edges.conf"
# Bunny lists several hundred of each; far fewer means a broken answer.
MIN_V4=100
MIN_V6=20

RELOAD=1
[ "${1:-}" = "--no-reload" ] && RELOAD=0

command -v python3 >/dev/null || { echo "❌ python3 required" >&2; exit 1; }

fetch_and_validate() {
    # $1 = URL; prints one canonical address per line. A JSON number would
    # pass ipaddress.ip_address, so only strings are accepted, and addresses
    # that must never count as a proxy are refused.
    curl -fsS --max-time 30 "$1" | python3 -I -c '
import ipaddress, json, sys
addrs = json.load(sys.stdin)
if not isinstance(addrs, list):
    sys.exit("not a JSON list")
for a in addrs:
    if not isinstance(a, str):
        sys.exit("non-string element in edge list: %r" % (a,))
    ip = ipaddress.ip_address(a)
    if ip.is_unspecified or ip.is_loopback or ip.is_multicast or ip.is_private:
        sys.exit("refusing edge entry: %s" % a)
    print(str(ip))
'
}

echo "Fetching Bunny edge lists ..."
V4="$(fetch_and_validate https://api.bunny.net/system/edgeserverlist)"
V6="$(fetch_and_validate https://api.bunny.net/system/edgeserverlist/ipv6)"

N4="$(printf '%s\n' "$V4" | sed '/^$/d' | wc -l | tr -d ' ')"
N6="$(printf '%s\n' "$V6" | sed '/^$/d' | wc -l | tr -d ' ')"
if [ "$N4" -lt "$MIN_V4" ] || [ "$N6" -lt "$MIN_V6" ]; then
    echo "❌ only ${N4} IPv4 and ${N6} IPv6 edges returned (at least ${MIN_V4} and ${MIN_V6} expected) — ${TARGET} left as it is" >&2
    exit 1
fi

NEW_CONTENT="$( {
    echo "# Written by scripts/refresh_bunny_edge_ips.sh — do not edit by hand."
    echo "# ${N4} IPv4 + ${N6} IPv6 Bunny edge servers, fetched $(date -u +%Y-%m-%dT%H:%M:%SZ)."
    printf '%s\n' "$V4" | sed '/^$/d; s/.*/set_real_ip_from &;/'
    printf '%s\n' "$V6" | sed '/^$/d; s/.*/set_real_ip_from &;/'
} )"

# Compare the addresses, not the timestamp line.
OLD_PAYLOAD="$(grep '^set_real_ip_from' "$TARGET" 2>/dev/null || true)"
NEW_PAYLOAD="$(printf '%s\n' "$NEW_CONTENT" | grep '^set_real_ip_from')"
if [ "$OLD_PAYLOAD" = "$NEW_PAYLOAD" ]; then
    echo "✅ ${TARGET} already current (${N4} IPv4 + ${N6} IPv6 edges)"
    exit 0
fi

# Written beside the target and moved over it, so the gateway never reads a
# half-written file. The name doesn't match the gateway's *.conf include.
mkdir -p "$TARGET_DIR"
printf '%s\n' "$NEW_CONTENT" > "${TARGET_DIR}/.edges.conf.new"
mv "${TARGET_DIR}/.edges.conf.new" "$TARGET"
echo "✅ wrote ${TARGET}: ${N4} IPv4 + ${N6} IPv6 edges"

if [ "$RELOAD" -eq 1 ] && command -v docker >/dev/null 2>&1 \
   && [ -n "$(docker compose ps -q gateway 2>/dev/null)" ]; then
    echo "Checking and reloading the gateway ..."
    docker compose exec -T gateway nginx -t
    docker compose exec -T gateway nginx -s reload
    echo "✅ gateway reloaded"
fi
