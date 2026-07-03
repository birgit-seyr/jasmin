# HTTPS deploy runbook

Status: TODO on first prod deploy. The code + compose are ready.

Without HTTPS the platform CANNOT be GDPR-compliant in production
(unencrypted PII in transit). This runbook is the operational half
of the GDPR P0 "HTTPS / Encryption in Transit" item.

## What's already in place

- `nginx.conf.template` listens on `:80` (HTTP, certbot ACME challenge
  only — everything else 301-redirects to HTTPS) and `:443` (TLS
  termination, routes `/api`, `/static`, `/media` to
  Django, everything else to the React SPA).
- `docker-compose.yml` exposes both `:80` and `:443` on the
  `gateway` container, mounts `certbot_conf` (cert store) and
  `certbot_www` (ACME challenge webroot) as named volumes.
- A long-running `certbot` service handles renewals: `certbot renew
--quiet` every 12h via the entrypoint loop.
- DNS validation uses the Linode plugin (`certbot/dns-linode`),
  which means we can issue **wildcard** certs (`*.mydomain.com`) —
  required for the multi-tenant subdomain routing.
- `certbots/init-wildcard-cert.sh` is the initial-issuance script.

## What you need on the prod host

1. **DNS for the platform domain points at Linode** — NS records on
   `ns1.linode.com` … `ns5.linode.com`. Required for the DNS-01
   challenge.
2. **Linode Personal Access Token** with `Domains: Read/Write`,
   everything else scoped to `None`. Get it from the Linode Cloud
   Manager → Profile → API Tokens.
3. **The platform domain registered + working** — `dig
mydomain.com NS` resolves to the Linode nameservers.
4. **`.env` populated** with at least the variables `docker-compose.yml`
   marks required (`${VAR:?}`) — compose refuses to start if any is unset:
   ```
   FRONTEND_DOMAIN=mydomain.com
   DJANGO_SECRET_KEY=<random>
   FIELD_ENCRYPTION_KEY=<random>
   DJANGO_ALLOWED_HOSTS=mydomain.com,.mydomain.com
   POSTGRES_DB=<db-name>
   POSTGRES_USER=<db-user>
   POSTGRES_PASSWORD=<strong>
   REDIS_PASSWORD=<strong>
   BACKUP_ENCRYPTION_KEY=<strong>   # required by the backup service
   ```
   See [`.env.example`](../../.env.example) for the full set (incl. the
   GlitchTip / observability vars if you enable that stack).

## Initial deploy — first time only

```bash
# 1. Drop the Linode API token where the init script expects it:
mkdir -p certbots
cat > certbots/linode.ini <<EOF
dns_linode_key = <paste-token-here>
dns_linode_version = 4
EOF
chmod 600 certbots/linode.ini

# 2. Issue the wildcard cert (interactive: agrees to ToS, hits the
#    Let's Encrypt DNS-01 endpoint, waits ~120s for DNS
#    propagation, writes the cert into the certbot_conf volume).
DOMAIN=mydomain.com EMAIL=admin@mydomain.com ./certbots/init-wildcard-cert.sh

# 3. Bring up the full stack — gateway picks up the cert from the
#    shared volume.
docker compose up -d

# 4. Sanity-check that HTTPS is serving:
curl -I https://mydomain.com
# expect: HTTP/2 200 (or 301 to your default tenant subdomain)

# 5. Sanity-check that HTTP redirects:
curl -I http://mydomain.com
# expect: HTTP/1.1 301 Moved Permanently → location: https://...
```

## Renewal — automatic

The `certbot` service in docker-compose.yml runs `certbot renew`
every 12 hours. Let's Encrypt's renewal window is 30 days before
expiry, so the 12h cadence is generous.

Verify the renewal loop is alive:

```bash
docker compose ps certbot
# State should be Up (entrypoint sleeps then renews in a loop)

docker compose logs --tail 50 certbot
# Recent runs show either "Certificate not yet due for renewal"
# (most days) or "Successfully received certificate" (every ~60d)
```

## Failure modes + recovery

**Cert expired in prod (renewal silently failed for 60+ days):**

```bash
# Force-renew immediately. --entrypoint certbot is required: the certbot
# service declares an entrypoint renew-loop and NO command, so plain
# `docker compose run certbot certbot renew ...` would append the args to
# the (absent) command and they'd be silently ignored — the entrypoint
# loop runs instead. Overriding the entrypoint runs certbot directly.
docker compose run --rm --entrypoint certbot certbot renew --force-renewal --dns-linode --dns-linode-credentials /linode.ini --dns-linode-propagation-seconds 120

# Reload nginx so it picks up the new cert without restarting
# active connections:
docker compose exec gateway nginx -s reload
```

**Linode API token rotated / leaked:**

```bash
# Update the credentials file with the new token, then:
docker compose restart certbot
# The next renewal run uses the new token.
```

**Need to add a new subdomain (e.g. for a new tenant):**

The cert is already a wildcard, so any `<tenant>.mydomain.com` is
covered automatically. Only the DNS A/CNAME record needs to land
(handle in Linode Cloud Manager). No cert work required.

**Switching from Linode DNS to another provider:**

`certbot/dns-linode` would need to change to the matching plugin
(`certbot/dns-route53` for AWS, `certbot/dns-cloudflare` for
Cloudflare, …). Update the `image:` in docker-compose.yml's
`certbot` service + the credentials file format. The init script
needs the matching plugin flag.

## Hardening checklist (post-deploy)

Once HTTPS is live, tighten the TLS config:

- [ ] Verify `ssl_protocols TLSv1.2 TLSv1.3;` is set in nginx
      (`TLSv1` and `TLSv1.1` deprecated by the GDPR-relevant
      regulators).
- [ ] HSTS header: `add_header Strict-Transport-Security
    "max-age=31536000; includeSubDomains" always;` on the `:443`
      server block. Only add AFTER you're sure HTTPS works — once
      a browser caches HSTS, an HTTPS misconfiguration locks
      everyone out for `max-age` seconds.
- [ ] Run [SSL Labs scan](https://www.ssllabs.com/ssltest/) →
      target A+ rating.
- [ ] Run [Mozilla Observatory](https://observatory.mozilla.org/)
      → review CSP / security-header recommendations.

## Marking this item done

Once HTTPS is live in prod AND the SSL Labs scan passes A+, record the
deploy date + the SSL Labs score against the "HTTPS / Encryption in
Transit" item in the relevant deploy tracker.

- [ ] **Activate Friendly Captcha when ready** — 1. Sign the Friendly Captcha DPA (vendor on
      [`../security/vendor-matrix.md`](../security/vendor-matrix.md)). 2. Create an FC Site → copy sitekey + secret. 3. Add `FRIENDLY_CAPTCHA_SITEKEY` + `FRIENDLY_CAPTCHA_SECRET`
      to the prod env file. 4. Set `FRIENDLY_CAPTCHA_ENABLED=True` in the same file. 5. `docker compose up -d backend` to reload settings. 6. `make generate-api` so the frontend type for
      `PublicRegisterRequest` picks up the new
      `frc_captcha_solution` field, and `CurrentTenant` picks up
      `friendly_captcha_sitekey` (currently the request payload
      uses a TS intersection in Step7Done.tsx as a stopgap). 7. Smoke-test: open `/login` from an incognito window, verify
      the FC badge mounts. Confirm logs show `captcha.rejected` on
      a forged submission (curl `/api/auth/login/` with no
      solution token).



BACKUP MEDIA TOO!!