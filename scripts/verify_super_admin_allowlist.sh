#!/usr/bin/env sh
# =============================================================================
# Verify the super-admin IP-allowlist guardrail in the nginx gateway config.
#
# WHY THIS EXISTS
#   The super-admin platform host (tenant CRUD, backups) is protected ONLY by
#   an nginx IP allowlist. Super-admins are deliberately exempt from 2FA on the
#   strength of that allowlist (see config/settings.py). Django enforces NO IP
#   restriction for them, so if the gateway rule ever regresses, the most
#   privileged account silently falls back to password-only with no second
#   factor and no network restriction.
#
#   This script makes that infra-layer control verifiable in CI (and locally).
#   It checks the ways the allowlist can silently stop applying — not just that
#   the right strings exist SOMEWHERE, but that they are wired correctly:
#
#     1a. The allowlist file terminates in `deny all;` (fail-closed default).
#     1b. The allowlist file has NO blanket `allow` (all / 0.0.0.0/0 / ::/0).
#         nginx access rules are FIRST-match-wins, so an `allow all;` above the
#         `deny all;` opens the host wide while still ending in `deny all;`.
#     2.  The super-admin host appears in EXACTLY ONE server block (a duplicate
#         on the wildcard block makes nginx warn "conflicting server name" and
#         route to the unrestricted wildcard block — exit 0, but bypassed).
#     3.  That one block includes the allowlist (an include in the WRONG block
#         leaves the super-admin host open AND wrongly denies tenants).
#
#   Pure POSIX sh + envsubst/grep/awk — no nginx, no root, no certs needed, so
#   it runs identically on a dev machine and in CI. (Full `nginx -t` syntax
#   validation runs in the CI gateway job and at deploy time.)
# =============================================================================
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
template="$repo_root/nginx/nginx.conf.template"
allowlist="$repo_root/nginx/super_admin_allowed_ips.conf"

fail() {
    echo "FAIL: $1" >&2
    exit 1
}

[ -f "$template" ] || fail "gateway template not found: $template"
[ -f "$allowlist" ] || fail "allowlist file not found: $allowlist"

command -v envsubst >/dev/null 2>&1 \
    || fail "envsubst not on PATH (install gettext / gettext-base)"

# real (comment- and blank-stripped) directives of the allowlist
allow_directives=$(grep -vE '^[[:space:]]*(#|$)' "$allowlist" || true)

# --- 1a) fail-closed: last real directive is `deny all;` -------------------
last_directive=$(printf '%s\n' "$allow_directives" | tail -n 1)
printf '%s\n' "$last_directive" \
    | grep -qE '^[[:space:]]*deny[[:space:]]+all;[[:space:]]*$' \
    || fail "nginx/super_admin_allowed_ips.conf must end in 'deny all;' (last directive: '${last_directive}')"

# --- 1b) no blanket allow (first-match-wins would open the host) -----------
if printf '%s\n' "$allow_directives" \
    | grep -qE '^[[:space:]]*allow[[:space:]]+(all|0\.0\.0\.0/0|::/0);'; then
    fail "nginx/super_admin_allowed_ips.conf has a blanket 'allow' (all / 0.0.0.0/0 / ::/0) — that opens the super-admin host to everyone"
fi

# --- render the template the way docker-compose's gateway command does ------
export FRONTEND_DOMAIN="ci.example.test"
export SUPER_ADMIN_SUBDOMAIN="adminci"
export BACKEND_HOST="backend"
export BACKEND_PORT="8000"
export FRONTEND_HOST="frontend"
export FRONTEND_PORT="80"
super_admin_host="${SUPER_ADMIN_SUBDOMAIN}.${FRONTEND_DOMAIN}"

rendered=$(envsubst '$FRONTEND_DOMAIN $SUPER_ADMIN_SUBDOMAIN $BACKEND_HOST $BACKEND_PORT $FRONTEND_HOST $FRONTEND_PORT' <"$template")

# --- 2) + 3) block-aware structural check ----------------------------------
# Walk server{} blocks by brace depth. Assert the super-admin host lives in
# EXACTLY ONE server block and that that block pulls in the allowlist. A
# whole-file grep can't express "in the right block, and only there".
printf '%s\n' "$rendered" | awk -v host="$super_admin_host" '
    {
        line = $0
        # A server BLOCK opener ("server {"), not the "server host:port;"
        # directive used inside upstream{} blocks.
        if (in_server == 0 && line ~ /^[[:space:]]*server[[:space:]]*\{/) {
            in_server = 1; server_base = depth; cur_name = ""; cur_include = 0
        }
        if (in_server) {
            if (line ~ /server_name/) cur_name = cur_name " " line
            if (line ~ /include[[:space:]]+\/etc\/nginx\/super_admin_allowed_ips\.conf;/) cur_include = 1
        }
        o = gsub(/\{/, "{"); c = gsub(/\}/, "}"); depth += o - c
        if (in_server && depth <= server_base) {
            if (index(cur_name, host) > 0) { host_blocks++; if (cur_include) inc_blocks++ }
            in_server = 0
        }
    }
    END {
        if (host_blocks == 0) { print "ERR: no server block with server_name " host; exit 3 }
        if (host_blocks > 1)  { print "ERR: super-admin host " host " is in " host_blocks " server blocks (conflicting server_name -> routes to the wrong, unrestricted block)"; exit 4 }
        if (inc_blocks == 0)  { print "ERR: the super-admin server block does not include super_admin_allowed_ips.conf"; exit 5 }
    }
' || fail "gateway structural check failed (see ERR above) — super-admin allowlist is not correctly wired in nginx.conf.template"

# --- 4) the wildcard (tenant + apex) HTTPS block must NOT serve super-admin -
# The apex ${FRONTEND_DOMAIN} is matched by the wildcard server block (which
# has no IP allowlist) and resolves to the public schema where the super-admin
# API is mounted. Without an explicit guard there, the platform-root API is
# reachable on the apex from any IP, bypassing the allowlist entirely (CFG-1).
# Assert the wildcard HTTPS block (the one carrying a ``*.`` server_name and
# listening on 443 — NOT the :80 redirect block) returns/denies on
# /api/super-admin/ instead of proxying it to the backend.
printf '%s\n' "$rendered" | awk '
    {
        line = $0
        if (in_server == 0 && line ~ /^[[:space:]]*server[[:space:]]*\{/) {
            in_server = 1; server_base = depth
            is_wildcard = 0; is_https = 0; in_sa_loc = 0; has_guard = 0
        }
        if (in_server) {
            if (line ~ /server_name/ && line ~ /\*\./) is_wildcard = 1
            if (line ~ /listen/ && line ~ /443/) is_https = 1
            if (line ~ /location[[:space:]]+\/api\/super-admin\//) in_sa_loc = 1
            # within the super-admin location, a return/deny is the guard;
            # a proxy_pass there would mean it is being served (bad).
            if (in_sa_loc && line ~ /(return|deny)/) { has_guard = 1; in_sa_loc = 0 }
        }
        o = gsub(/\{/, "{"); c = gsub(/\}/, "}"); depth += o - c
        if (in_server && depth <= server_base) {
            if (is_wildcard && is_https && !has_guard) {
                print "ERR: the wildcard/apex HTTPS server block does not guard /api/super-admin/ (return/deny) — the apex host can reach the platform-root API with no IP allowlist"
                exit 6
            }
            in_server = 0
        }
    }
' || fail "the wildcard (tenant + apex) HTTPS block must block /api/super-admin/ — otherwise the apex reaches the platform-root API off-allowlist (CFG-1)"

echo "OK: super-admin IP allowlist guardrail intact (fail-closed deny-all, no blanket allow, single dedicated server block, allowlist included in that block, wildcard/apex block denies /api/super-admin/)."
