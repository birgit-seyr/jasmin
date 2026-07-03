# Deploy / operational TODOs

Things that are done **at deploy or operational time** (configure
nginx, set up CDN, run a CLI command on prod, sign a contract,
fill in a template, configure firewall, vendor selection). For
code changes, see [`code.md`](code.md).

Items extracted from the former `audit_checklist.txt` and
`security_checklist.txt` on 2026-06-06.

The order roughly follows "do this first" — start at the top.

---

## Edge layer (in front of nginx)

- [ ] **Put a CDN / WAF in front of origin.** Sign up with [Bunny.net](https://bunny.net) or Gcore (see [`../security/vendor-matrix.md`](../security/vendor-matrix.md)). Point domain at their edge; they forward to your Linode/Hetzner IP. Enable WAF/Shield. Hides real server IP, absorbs DDoS, blocks common attack patterns. Cost: Bunny ~€15/mo (€10 Shield + small egress).
- [ ] **Edge rate-limiting on auth endpoints.** At the CDN: max 10 req/min per IP to `/api/auth/login/`, `/api/auth/refresh/`, `/api/auth/register/`, `/api/auth/password-reset/request/`, `/api/auth/password-reset/confirm/`, `/api/auth/invitations/accept/`. Stops credential-stuffing + reset spam before it costs DB queries. Included with Bunny Shield / Gcore WAF.

## Network / server layer

- [ ] **Cloud firewall.** In the Linode/Hetzner control panel: allow ONLY 22 (SSH), 80, 443 inbound. Block everything else. Postgres/Redis never reachable from the internet.
- [ ] **SSH hardening.** In `/etc/ssh/sshd_config`: `PasswordAuthentication no`, `PermitRootLogin no`, `PubkeyAuthentication yes`. Restart sshd. Use SSH keys only.
- [ ] **Restrict SSH to your IP or a bastion.** In the cloud firewall: allow port 22 only from your home IP or a Tailscale/WireGuard subnet. Attackers can't try if they can't reach the port. Tailscale free tier covers up to 100 devices.
- [ ] **fail2ban.** `apt install fail2ban`. Default config bans IPs with too many failed SSH logins for 10 min. Belt-and-braces in case the SSH IP restriction lapses.
- [ ] **Automatic security updates.** `apt install unattended-upgrades && dpkg-reconfigure unattended-upgrades` — pick "Yes" for security updates. OS / kernel / openssl / libc patches arrive constantly; one missed patch is the breach.
- [ ] **Private network for DB + Redis (when split off-host).** If/when DB/Redis move to separate hosts, put them on a private VPC (Hetzner Cloud Networks / Linode VLAN), bind them to private IPs only.

## Backups + DR

- [ ] **Off-host + restore-drill coverage for media backups.** _(code half shipped.)_ `backups/backup.sh` now archives the `media_volume` (uploaded invoice / delivery-note PDFs, XML e-invoices, tenant logos) as an encrypted `*_media_*.tar.gz.gpg` alongside each DB dump (the backup service mounts `media_volume:ro`), and the Huey `prune_old_backups` task retains it under the same GFS policy. Remaining operational work: ship those media archives to the same off-host bucket as the DB dumps (set `RCLONE_REMOTE` — see "Encrypted, off-host backups"), and add a media-archive restore to the quarterly drill.
- [ ] **Encrypted, off-host backups.** Daily DB dump (you have `backups/backup.sh`); encrypt with age or gpg; push to Hetzner Storage Box / Scaleway Object / OVH Object / Bunny Storage. Keep 30 daily + 12 monthly. Hetzner Storage Box 1TB is €4/mo.
- [ ] **Quarterly restore test.** Spin up throwaway Postgres, restore latest backup, verify it loads. Document each run in [`../security/restore-drills/`](../security/restore-drills/). See [`../security/restore-drill.md`](../security/restore-drill.md). **Untested backups are not backups.**
- [x] **Backup pruning (local).** Local pruning per a GFS retention policy already ships as the Huey `prune_old_backups` task (`apps/shared/tenants/tasks.py`) — `backups/backup.sh` deliberately does NOT prune. The remaining work is off-site retention (create the off-site bucket + prune it), covered by "Encrypted, off-host backups" above.
- [ ] **Managed Postgres (when you can afford it).** Move from self-hosted to Hetzner Cloud DB / Scaleway DB / OVH Public Cloud DB. They handle encryption at rest, automated backups, PITR, version upgrades. Hetzner CCX13 + DB ~€30/mo, Scaleway DB-DEV-S ~€25/mo.
- [ ] **Full-disk encryption on host.** If staying self-hosted: enable LUKS on the Linode volume, or pick a provider that does it by default. Protects against decommissioned-disk leaks.

## Logging + observability

- [ ] **Centralized logs: self-hosted Loki + Grafana on a Hetzner box.** Ship container STDOUT + nginx access logs to a separate central store so they (a) survive the app host being lost and (b) support cross-log queries + alert rules. Note: under `RUNNING_IN_DOCKER` the app.log/auth.log/security.log file handlers are popped — Django logs go to stdout only, so there ARE no log files inside the containers to tail. Ship the container stdout streams instead. Concrete steps:
  1. Spin up a small Hetzner CX21 (~€5/mo) for the Loki + Grafana sidecar.
  2. Install Promtail (the shipper) on the app host; point it at the Docker `json-file` / `journald` logs (container stdout) + `/var/log/nginx/access.log`.
  3. Install Loki + Grafana on the sidecar; ingest from Promtail.
  4. Build dashboards: logins-per-hour (by tenant), `account.locked` rate, `invoice.hash_drift` count, `csp.violation` count.
  5. Wire alert rules — Grafana Alerting → Telegram / email — for: any `invoice.hash_drift`, `>10 account.locked` in 5min, no fresh `./backups/*.sql.gz.gpg` file in the last >36h (backup success is a plain echo, not a structured event — watch the newest encrypted dump's mtime), any `gdpr.ex_member_blocked` (so the office sees blockers).
  6. Sign a Hetzner DPA (covered in §Art. 28 below).
- [ ] **Status page + uptime monitoring.** Uptime Kuma (self-hosted, free) or Better Stack. Expected by B2B customers. Status page is optional but builds trust.
- [ ] **Route background-job / liveness alerts to a live sink.** The in-app monitoring already exists: a `*/15min` Huey periodic task `reconcile_stale_background_jobs` (`apps/notifications/tasks.py`) reconciles worker-lost `BackgroundJob` rows and calls `mail_admins`, and a `huey_heartbeat` periodic task drives the huey container healthcheck. What's missing is a live destination for those signals — configure prod SMTP so `mail_admins` actually delivers (optionally add Sentry/GlitchTip for exception aggregation and Uptime Kuma to watch the heartbeat / healthcheck). Until SMTP is wired, the reconciler runs but the admin alert silently goes nowhere.

## GDPR / contracts (Art. 28, 30, 13)

- [ ] **Sign DPAs with every subprocessor.** Linode/Hetzner (host), Bunny (CDN), email provider, error monitoring (Sentry/GlitchTip), backup storage. Use [`../gdpr/avv-template.md`](../gdpr/avv-template.md) as the starting point. Required by Art. 28; B2B customers will ask for the list.
- [ ] **Sub-processor list.** Per-tenant operational task — document every third-party service that touches PII (host, email, payment gateway, SMS gateway, monitoring, backups). Include in privacy policy OR make available on request. Each sub-processor needs its own DPA on file (covered above).
- [ ] **Privacy policy.** Required by Art. 13. Disclose: personal data collected (name, email, IBAN, address), legal basis, retention (link to [`../gdpr/retention-policy.md`](../gdpr/retention-policy.md)), subprocessors (match Art. 30 list), data-subject rights + how to exercise them, DPO contact. Tooling: iubenda.com (€27/yr) or hand-write markdown.
- [ ] **Records of processing (Art. 30).** Companion to [`../gdpr/processing-activities.md`](../gdpr/processing-activities.md): document what personal data is processed, why, retention, who has access. A spreadsheet is fine. An API would be nicer (tracked in [`code.md`](code.md)).

## Super-admin hardening

- [x] **IP allowlist for super-admin login** — _shipped at the nginx edge_ (not in Django). Super-admin (the public-schema realm) is **not** covered by tenant-side TOTP; instead its host is locked to a known IP set by a dedicated nginx server block + fail-closed `deny all;` allowlist ([`nginx/super_admin_allowed_ips.conf`](../../nginx/super_admin_allowed_ips.conf)), CI-verified by the `gateway` job ([`scripts/verify_super_admin_allowlist.sh`](../../scripts/verify_super_admin_allowlist.sh)). Operators add their `allow` line (Tailscale gives a stable IP) and `docker compose exec gateway nginx -s reload`; recovery if your IP changes: SSH in, edit the file, reload. **Caveat:** the file is bind-mounted into the gateway as a single file, so an inode-replacing edit (vim/`sed -i`/`cp`) leaves the container serving the stale content even after `nginx -s reload` — run `docker compose restart gateway` after such an edit (or edit in place with `>>`; the durable fix would be a directory bind-mount). Design + steps: [`../security/access-hardening.md`](../security/access-hardening.md) Part 1.
  - [ ] _Optional defense-in-depth (not done):_ also enforce in Django — a `SUPER_ADMIN_ALLOWED_IPS` setting checked in the super-admin login view via `client_ip(request)`. Deferred deliberately: the edge allowlist keys on the unspoofable TCP `$remote_addr`, whereas a Django check would trust the forwarded header and add lockout risk, so it's only worth it as a second layer.

## Operational hygiene

- [ ] **Rotate secrets yearly.** `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, DB password, CDN API tokens, email API keys. Document the rotation procedure in the runbook below. The CLI commands already exist (5 rotations are end-to-end wired) — this is the cadence task.
- [ ] **Quarterly user-account review.** List all super-admin + admin users, confirm each is still needed, disable orphaned accounts. Stale privileged accounts are the top breach vector.
- [ ] **Quarterly CSP re-audit.** Once enforced (see [`code.md`](code.md)), grep `security.log` for `csp.violation` lines every quarter; allowlist new legitimate sources, or rollback to report-only if anything is broken.
- [ ] **Dependabot SLA.** Document "we triage Dependabot alerts within X days." Most enterprise procurement asks. Add to the runbook below.
- [ ] **Disaster-recovery procedure.** Document RTO/RPO targets and the steps to meet them. No formal DR procedure exists yet.
- [ ] **Change-management procedure.** Define: who approves prod deploys, who can run migrations, the approval chain. One-pager.
- [ ] **Tagged images + rollback.** The four `jasmin/*` images are pinned via `${IMAGE_TAG:-latest}` (see `.env.example`). Build + push an immutable per-release tag (git SHA / version) each deploy and keep the last N; roll back with `IMAGE_TAG=<prev> docker compose up -d backend huey frontend backup`. **Forward-only-migrations caveat:** an image rollback is safe only to a release whose migrations are a *prefix* of what already ran — never reverse a shipped migration (`migrate <app> <older>`); write a forward fix instead.
- [ ] **Runbook.** Short markdown covering: maintenance mode, secret rotation, restore from backup, revoke tenant admin, who-to-contact for what. The "3am incident" playbook.
