#!/bin/sh
# =============================================================================
# render_config.sh — render the gateway's nginx config inside an nginx
# container: the template through envsubst into /etc/nginx/nginx.conf, and the
# two files of the origin gate into /etc/nginx/origin_gate/. The gateway
# service runs it at every start; CI and scripts/validate_gateway_config.sh run
# it before `nginx -t`, so all three render the same config.
#
# The origin gate: Bunny adds a secret header (X-Origin-Secret, set by an edge
# rule on every tenant pull zone) to each request it passes to the origin.
# While BUNNY_ORIGIN_SECRET is set, the tenant hosts
#   * close the connection (444) on a request without it, /health/ excepted —
#     one sent to the origin IP directly, past Bunny Shield, or through another
#     Bunny customer's pull zone;
#   * take the client's IP from X-Forwarded-For when the request comes from a
#     Bunny edge (/etc/nginx/bunny_edges/*.conf, which
#     scripts/refresh_bunny_edge_ips.sh writes).
# The two are switched on together: trusting Bunny's edges without the secret
# would let anyone's pull zone choose the client IP the rate limits, the login
# lockout and the audit records key on. nginx resolves the client IP before the
# gate refuses a request, so the access log keeps the connecting address as
# well (peer=). A tenant hostname that bypasses Bunny gets no answer while the
# gate is on: a new tenant's host goes into the pull zone first. Empty, the
# tenant hosts serve every request and see the edge's IP.
#
# BUNNY_ORIGIN_SECRET_NEXT is accepted alongside it while the secret changes,
# so Bunny never sends one the gateway refuses.
# =============================================================================
set -eu

GATE_DIR=/etc/nginx/origin_gate
current="${BUNNY_ORIGIN_SECRET:-}"
next="${BUNNY_ORIGIN_SECRET_NEXT:-}"

fail() { echo "render_config.sh: $*" >&2; exit 1; }

# A secret becomes a key of an nginx map: anything but letters and digits could
# break the config or add directives to it.
for secret in "$current" "$next"; do
    case "$secret" in
        *[!A-Za-z0-9]*) fail "an origin secret may hold only letters and digits" ;;
    esac
    if [ -n "$secret" ] && { [ "${#secret}" -lt 32 ] || [ "${#secret}" -gt 64 ]; }; then
        fail "an origin secret needs 32 to 64 characters (openssl rand -hex 32)"
    fi
done
[ -n "$current" ] || [ -z "$next" ] || \
    fail "BUNNY_ORIGIN_SECRET_NEXT is set but BUNNY_ORIGIN_SECRET is empty"

mkdir -p "$GATE_DIR"

# The entries of the map that accepts a secret. Only set ones: an empty key
# would match every request that carries no secret at all.
{
    echo "# Rendered by render_config.sh."
    for secret in "$current" "$next"; do
        if [ -n "$secret" ]; then
            printf '"%s" 1;\n' "$secret"
        fi
    done
} > "$GATE_DIR/secrets.conf"

if [ -n "$current" ]; then
    cat > "$GATE_DIR/tenant.conf" <<'EOF'
# Rendered by render_config.sh: BUNNY_ORIGIN_SECRET is set.
if ($origin_gate_deny) {
    return 444;
}
real_ip_header    X-Forwarded-For;
real_ip_recursive on;
include /etc/nginx/bunny_edges/*.conf;
EOF
    if ! ls /etc/nginx/bunny_edges/*.conf >/dev/null 2>&1; then
        echo "render_config.sh: WARNING: the origin gate is on but /etc/nginx/bunny_edges has no edge list, so the tenant hosts keep seeing Bunny's addresses — run scripts/refresh_bunny_edge_ips.sh" >&2
    fi
else
    echo "# Rendered by render_config.sh: BUNNY_ORIGIN_SECRET is empty, so the gate is off." \
        > "$GATE_DIR/tenant.conf"
fi

envsubst '$FRONTEND_DOMAIN $SUPER_ADMIN_SUBDOMAIN $BACKEND_HOST $BACKEND_PORT $FRONTEND_HOST $FRONTEND_PORT' \
    < /etc/nginx/templates/nginx.conf.template > /etc/nginx/nginx.conf
