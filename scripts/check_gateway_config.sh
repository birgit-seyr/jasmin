#!/bin/sh
# =============================================================================
# check_gateway_config.sh — CI's check of the production gateway config. It
# runs INSIDE the gateway's nginx image, with the repo's nginx/ directory at
# /work; from the repo root:
#
#   docker run --rm -v "$PWD/nginx:/work:ro" \
#     -v "$PWD/scripts/check_gateway_config.sh:/check.sh:ro" \
#     nginx:1.31-alpine sh /check.sh
#
# It renders the config through nginx/render_config.sh, as the gateway does,
# with the origin gate off and on, runs `nginx -t` on each, and serves both:
# which tenant requests get through, which client IP the backend sees, and
# that the origin secret never reaches it. A throwaway self-signed certificate
# satisfies the ssl_certificate paths, and the hosts entry lets nginx resolve
# the upstream names.
# =============================================================================
set -eu
apk add --no-cache openssl curl >/dev/null 2>&1
export FRONTEND_DOMAIN=ci.example.test SUPER_ADMIN_SUBDOMAIN=adminci
export BACKEND_HOST=backend BACKEND_PORT=8000 FRONTEND_HOST=frontend FRONTEND_PORT=80
echo "127.0.0.1 backend frontend" >> /etc/hosts
mkdir -p /etc/letsencrypt/live/$FRONTEND_DOMAIN /etc/nginx/templates /etc/nginx/bunny_edges
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -keyout /etc/letsencrypt/live/$FRONTEND_DOMAIN/privkey.pem \
  -out /etc/letsencrypt/live/$FRONTEND_DOMAIN/fullchain.pem \
  -subj "/CN=$FRONTEND_DOMAIN" >/dev/null 2>&1
# The files the gateway mounts next to the template.
cp /work/super_admin_allowed_ips.conf /etc/nginx/super_admin_allowed_ips.conf
cp /work/security_headers.conf /etc/nginx/security_headers.conf
cp /work/security_headers_admin.conf /etc/nginx/security_headers_admin.conf
cp /work/nginx.conf.template /etc/nginx/templates/nginx.conf.template
check_config() {
  out=$(nginx -t 2>&1) || { echo "$out"; exit 1; }
  echo "$out"
  # `nginx -t` exits 0 on a "conflicting server name" — but that
  # warning means the super-admin host is shadowed by the wildcard
  # block and its allowlist never applies. Treat it as a failure.
  if echo "$out" | grep -qiE 'conflicting server name'; then
    echo "FAIL: nginx reported a conflicting server name — super-admin host would route to the wrong (unrestricted) block"
    exit 1
  fi
}
code() {
  host=$1 path=$2; shift 2
  curl -sk -o /dev/null -w '%{http_code}' --resolve "$host:443:127.0.0.1" "https://$host$path" "$@" || true
}
expect() {
  if [ "$1" = closed ] && [ "$2" != 000 ]; then echo "FAIL: $3 answered $2, expected a closed connection"; exit 1; fi
  if [ "$1" = served ] && [ "$2" = 000 ]; then echo "FAIL: $3 was refused"; exit 1; fi
  echo "ok: $3 -> $2"
}
tenant=farm.$FRONTEND_DOMAIN
# What the backend receives: a one-shot listener on the backend port records
# the proxied request. nc gets a stdin that stays open: in the background its
# stdin would be /dev/null, and nc half-closes on that EOF as soon as nginx
# connects — sometimes before nginx has sent the request, which then fails.
upstream_headers() {
  rm -f /tmp/upstream_request
  sleep 5 | nc -l -p 8000 > /tmp/upstream_request &
  listener=$!
  for _ in $(seq 50); do
    netstat -ltn 2>/dev/null | grep -q ':8000 ' && break
    sleep 0.1
  done
  code $tenant /api/ -H 'X-Forwarded-For: 198.51.100.7' --max-time 2 "$@" >/dev/null
  kill $listener 2>/dev/null || true
  tr -d '\r' < /tmp/upstream_request
}
# The origin gate off, as on a server without BUNNY_ORIGIN_SECRET.
sh /work/render_config.sh
check_config
# Off, the edge's address stays the client: a forwarded one isn't trusted.
echo "set_real_ip_from 127.0.0.1;" > /etc/nginx/bunny_edges/edges.conf
nginx
upstream_headers -H 'X-Origin-Secret: anything' > /tmp/off
grep -qx 'X-Real-IP: 127.0.0.1' /tmp/off || { echo "FAIL: with the gate off the client IP came from X-Forwarded-For"; cat /tmp/off; exit 1; }
grep -qE '^X-Forwarded-For: .*, 127\.0\.0\.1$' /tmp/off || { echo "FAIL: with the gate off X-Forwarded-For doesn't end with the peer"; cat /tmp/off; exit 1; }
echo "ok: gate off keeps the peer's address"
nginx -s stop; sleep 0.5
# On, with both secrets and a stand-in edge list. A secret nginx could
# misread is refused before anything is written.
for bad in 'abc"; return 200; #0123456789abcdef0123456789' short; do
  if BUNNY_ORIGIN_SECRET=$bad sh /work/render_config.sh 2>/dev/null; then
    echo "FAIL: render_config.sh accepted the origin secret $bad"; exit 1
  fi
done
current=$(openssl rand -hex 32)
next=$(openssl rand -hex 32)
BUNNY_ORIGIN_SECRET=$current BUNNY_ORIGIN_SECRET_NEXT=$next sh /work/render_config.sh
check_config
# Serve it: a tenant request without an accepted secret gets its connection
# closed (curl reports 000); with either secret, or for /health/, it is
# proxied (the CI container has no backend, so 502 or the port-80 redirect).
nginx
expect closed "$(code $tenant /)" "tenant without a secret"
expect closed "$(code $tenant /api/ -H 'X-Origin-Secret: wrong')" "tenant with a wrong secret"
expect closed "$(code $tenant /api/ -H 'X-Origin-Secret: ')" "tenant with an empty secret"
expect served "$(code $tenant /api/ -H "X-Origin-Secret: $current")" "tenant with the secret"
expect served "$(code $tenant / -H "X-Origin-Secret: $next")" "tenant with the next secret"
expect served "$(code $tenant /health/)" "tenant /health/ without a secret"
expect served "$(code $FRONTEND_DOMAIN /health/)" "apex /health/ without a secret"
# Through the gate, the client is X-Forwarded-For's last address and the
# secret never reaches the backend.
upstream_headers -H "X-Origin-Secret: $current" > /tmp/on
grep -qx 'X-Real-IP: 198.51.100.7' /tmp/on || { echo "FAIL: the client IP didn't come from X-Forwarded-For"; cat /tmp/on; exit 1; }
# Django's client_ip reads the last X-Forwarded-For entry (TRUSTED_PROXY_COUNT=1).
grep -qE '^X-Forwarded-For: (.*, )?198\.51\.100\.7$' /tmp/on || { echo "FAIL: X-Forwarded-For doesn't end with the client"; cat /tmp/on; exit 1; }
if grep -qi '^X-Origin-Secret' /tmp/on; then echo "FAIL: the origin secret reached the backend"; exit 1; fi
echo "ok: gate on takes the forwarded client and drops the secret"
nginx -s stop
