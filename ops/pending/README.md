# Pending ops changes: allowlist directory mount and read-only backup role

`allowlist-dir-and-backup-role.patch` holds two finished ops changes that are
not in the tree yet, because each needs a step on the production server. As
long as the patch is not applied, a `git pull` on the server changes nothing
about either of them.

## What the patch changes, and why

### 1. The super-admin allowlist is mounted as a directory

The gateway bind-mounts `nginx/super_admin_allowed_ips.conf` as a single file.
A file bind-mount pins the inode, so an edit that replaces the file (vim,
`sed -i`, `cp`) stays invisible to `docker compose exec gateway nginx -s reload`
— the gateway keeps serving the old allowlist until it is restarted.

The patch moves the file to
`nginx/super_admin_allowlist/super_admin_allowed_ips.conf` and mounts the
directory instead, so a reload always sees the current file. It also:

- adds a second `deny all;` after the `include` in `nginx/nginx.conf.template`,
  so the host stays closed if an edit ever drops the allowlist's own last line;
- updates the path in `docker-compose.yml`, `scripts/verify_super_admin_allowlist.sh`,
  `scripts/validate_gateway_config.sh`, `scripts/update.sh` (the clean-tree guard
  that tolerates the server-local allowlist edit), `scripts/deploy.sh` (the
  closing hint, which now says `nginx -s reload` instead of a restart), the
  `gateway` job in `.github/workflows/ci.yml`, and three comments in
  `jasmin-core/django-core/config/settings.py`.

### 2. The backup sidecar dumps as a read-only role

The `backup` service logs in as the database owner (a superuser) and holds its
password. Anything that gets into that container can write to or drop the whole
database.

The patch has the dumps and the GDPR ledger refresh log in as
`BACKUP_DB_USER` / `BACKUP_DB_PASSWORD`, a role granted `pg_read_all_data`, and
takes `POSTGRES_PASSWORD` out of the backup container:

- `docker-compose.yml`: `BACKUP_DB_USER: ${BACKUP_DB_USER:-${POSTGRES_USER}}`
  and `BACKUP_DB_PASSWORD: ${BACKUP_DB_PASSWORD:-${POSTGRES_PASSWORD}}`. While
  the two are unset in `.env`, backups keep running as the owner.
- `backups/backup.sh`: uses those two and warns when it dumps as the owner.
- `backups/restore.sh`: a restore writes, so it still runs as the owner, with
  the password handed in for that one command:

  ```sh
  export POSTGRES_PASSWORD="$(grep -E '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)"
  docker compose exec -e POSTGRES_PASSWORD backup \
      sh /backups/restore.sh /backups/<file>.sql.gz.gpg
  ```

- `scripts/deploy.sh`: refuses to deploy when only one of the two variables is
  set, and warns while they are unset or equal to the owner.
- `CLAUDE.md`: a sentence on the new variables under "Database backups".

## How to enable

1. `git apply ops/pending/allowlist-dir-and-backup-role.patch` from the repo root
   (`git apply --check` first; the patch also moves the allowlist file).
2. Run the gates: `bash scripts/verify_super_admin_allowlist.sh`,
   `sh -n backups/*.sh`, `bash -n scripts/*.sh`, and in
   `jasmin-core/django-core`: `poetry run black --check config` and
   `poetry run python scripts/module_length.py check`.
3. Fix the two comments in `.env.example` that name the allowlist path, and add
   `BACKUP_DB_USER=` / `BACKUP_DB_PASSWORD=` to it with a short comment.
4. Commit (delete this directory in the same commit), push, then do the server
   steps below.

## Server steps, in order

### Allowlist (must start BEFORE the pull)

The live allowlist is a local edit of a file the pull deletes, so a plain pull
fails, and `scripts/update.sh` cannot be used for this one update.

1. Save the live allowlist:
   `cp nginx/super_admin_allowed_ips.conf ~/super_admin_allowed_ips.conf.live`
2. Drop the local edit: `git checkout -- nginx/super_admin_allowed_ips.conf`
3. Pull: `git pull --ff-only`
4. Put the saved list in the new place:
   `cp ~/super_admin_allowed_ips.conf.live nginx/super_admin_allowlist/super_admin_allowed_ips.conf`
5. Check that its last directive is `deny all;`:
   `grep -vE '^[[:space:]]*(#|$)' nginx/super_admin_allowlist/super_admin_allowed_ips.conf | tail -n 1`
6. `scripts/validate_gateway_config.sh` — must pass.
7. Deploy: `./scripts/deploy.sh` (it recreates the gateway with the new mount).
8. Verify: the super-admin host answers from an allowed IP and returns 403 from
   any other IP.
9. From now on, edit the file in `nginx/super_admin_allowlist/` and run
   `docker compose exec gateway nginx -s reload` — no restart needed. Later
   updates go through `scripts/update.sh` again, which tolerates the edit at the
   new path.

### Backup role (after the deploy above)

Backups keep running as the owner until these steps are done.

1. Check the fallback is active: `docker compose config | grep BACKUP_DB_USER`
   shows the owner's name.
2. Generate a password: `openssl rand -hex 32`
3. Create the role (replace `<hex>` and `<db>`, the value of `POSTGRES_DB`):

   ```sh
   docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   CREATE ROLE jasmin_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '<hex>';
   GRANT pg_read_all_data TO jasmin_backup;
   GRANT CONNECT ON DATABASE <db> TO jasmin_backup;
   ALTER ROLE jasmin_backup SET default_transaction_read_only = on;
   SQL
   ```

4. Add `BACKUP_DB_USER=jasmin_backup` and `BACKUP_DB_PASSWORD=<hex>` to `.env`.
5. Dry dump with the new role: `docker compose run --rm --no-deps -T backup predeploy`
   — must finish without error and without the "dumping as the database owner"
   warning.
6. `docker compose up -d backup`
7. `docker compose logs --tail=50 backup` — no errors, no owner warning.
8. `docker compose exec backup printenv POSTGRES_PASSWORD` — prints nothing.

## Risks

- **Rollback past this release.** An older backup image's `backup.sh` reads
  `POSTGRES_PASSWORD`, which the new `docker-compose.yml` no longer passes to the
  backup container, so its dumps fail. After such a rollback, check out that
  release's `docker-compose.yml` as well (or add `POSTGRES_PASSWORD` back to the
  backup service) and watch the next backup run.
- **Missing allowlist file stops the gateway.** The template includes one named
  file, not a glob, so nginx refuses to start when
  `nginx/super_admin_allowlist/super_admin_allowed_ips.conf` is missing — and
  with it every tenant's site. Run `scripts/validate_gateway_config.sh` before
  every deploy that follows a change to the file.
- **Restores need the owner password passed in.** Once the patch is live,
  `restore.sh` fails fast without `-e POSTGRES_PASSWORD`; use the command shown
  above.

---

# Pending ops changes: uptime monitoring and error tracking

`monitoring-and-error-tracking.patch` turns on Uptime Kuma and GlitchTip in
production. Like the patch above it is not in the tree yet: a `git pull` on the
server changes nothing about monitoring until it is applied. The two patches
apply in either order.

## What the patch changes, and why

Nothing watches production from outside. The stale-backup alert runs inside
huey, so it cannot notice huey itself being down, and a wedged huey stays down:
`restart: unless-stopped` restarts a container whose process exits, never one
that is merely unhealthy. Uptime Kuma is defined in `docker-compose.yml` but
never started and publishes no port, so the documented SSH tunnel reaches
nothing. The Sentry SDK is wired to GlitchTip but stays a no-op, since
GlitchTip is never started and `SENTRY_DSN` is unset.

- `docker-compose.yml`
  - `uptime-kuma` publishes `127.0.0.1:3001:3001`, `glitchtip-web`
    `127.0.0.1:8004:8000`. The `127.0.0.1` matters: Docker opens published
    ports in its own iptables chain, which ufw never sees.
  - `huey` gets `KUMA_PUSH_HUEY_URL`, `backup` gets `KUMA_PUSH_BACKUP_URL`
    (both empty by default).
  - The huey healthcheck comment now says what happens: the container is marked
    unhealthy, nothing restarts it, Kuma alerts.
  - The GlitchTip setup recipe runs `psql -U "$POSTGRES_USER"` inside the
    container (`sh -c '…'`) instead of expanding `${POSTGRES_USER}` in the
    host shell, where it is empty.
  - Comments on `GLITCHTIP_EMAIL_URL` and on the shared Redis (below).
- `scripts/deploy.sh` pulls and starts `uptime-kuma` with the core stack, and
  starts `glitchtip-web` / `glitchtip-worker` once the `glitchtip` database
  exists (before that they would only crash-loop). Its closing hints mention
  the Kuma tunnel.
- `backups/backup.sh` pushes to `KUMA_PUSH_BACKUP_URL` after each nightly run
  (`now` / `scheduled`, not `predeploy` or the 10-minute ledger run):
  `status=up` once the dump is verified and every off-host push went through,
  `status=down` when an off-host push failed. A failed dump sends nothing, so
  Kuma alerts when the interval passes. Busybox `wget` with a 10 s timeout; a
  failed push is a warning, never a failed backup. Any query string on the URL
  is dropped and rebuilt.
- `apps/notifications/tasks.py`: `huey_heartbeat` also pushes `status=up` to
  `KUMA_PUSH_HUEY_URL` every minute — no-op while unset, http(s) only, 5 s
  timeout, a failure logs a warning without the URL (it carries the token) and
  never raises. Tested in `apps/notifications/tests/test_huey_heartbeat.py`.
- `scripts/init-env.sh` writes `GLITCHTIP_DOMAIN=http://localhost:8004` (with a
  scheme — the URL the UI is opened at through the tunnel) and empty
  `KUMA_PUSH_BACKUP_URL`, `KUMA_PUSH_HUEY_URL`, `GLITCHTIP_EMAIL_URL` and
  `SENTRY_DSN` entries with a comment each.
- `CLAUDE.md`: the "Scheduled work" line on huey's liveness names the Kuma push.

Not in the patch:

- **Autoheal.** `willfarrell/autoheal` would restart an unhealthy huey, but it
  needs `/var/run/docker.sock` mounted, which is root on the host for anything
  that gets into that container. The Kuma push alert plus a manual
  `docker compose restart huey` is the safer trade for now. To add it later:
  a service with `image: willfarrell/autoheal:<pinned tag>`, the socket mounted
  read-only, `AUTOHEAL_CONTAINER_LABEL=autoheal`, and the label
  `autoheal: "true"` on `huey` only.
- **A separate Redis for GlitchTip.** GlitchTip's Celery uses Redis DB 2 on the
  same instance as huey and the cache. The DB index separates keys, not memory:
  all share the 384 MB `noeviction` cap, so a Celery backlog that fills it makes
  Redis refuse huey's enqueues and the cache writes. Watch
  `docker compose exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning info memory'`
  for the first weeks. If GlitchTip's share grows, give it its own small
  `redis:7-alpine` service (its own `mem_limit` and `--maxmemory`, no volume
  needed) and point both GlitchTip `REDIS_URL`s at it.

The Sentry scrubber (`core/sentry_scrub.py`) covers formatted messages, log
params and exception values, and request bodies are not sent — both are in
the tree already, so enabling GlitchTip is safe from that side.

## How to enable

1. `git apply --check ops/pending/monitoring-and-error-tracking.patch`, then
   `git apply` it from the repo root.
2. Run the gates: `sh -n backups/backup.sh`, `bash -n scripts/*.sh`, and in
   `jasmin-core/django-core`:
   `POSTGRES_PORT=5433 poetry run pytest apps/notifications/tests/test_huey_heartbeat.py`,
   `poetry run black --check apps`, `poetry run python scripts/ruff_baseline.py check`,
   `poetry run python scripts/mypy_baseline.py check`.
3. Add `KUMA_PUSH_BACKUP_URL=`, `KUMA_PUSH_HUEY_URL=` and
   `GLITCHTIP_EMAIL_URL=` with a short comment to `.env.example`, and check its
   `GLITCHTIP_DOMAIN` example carries a scheme.
4. Commit (remove this patch and its README section in the same commit), push,
   then do the server steps below.

## Server steps, in order

### Uptime Kuma

1. Pull and deploy: `scripts/update.sh` (or `git pull --ff-only` and
   `./scripts/deploy.sh`). Deploy now starts `uptime-kuma`; check with
   `docker compose ps uptime-kuma` and `ss -ltn | grep 3001` — it must show
   `127.0.0.1:3001`, not `0.0.0.0`.
2. From your machine: `ssh -L 3001:localhost:3001 <host>`, open
   http://localhost:3001 and create the admin account.
3. Add a notification (email via the platform SMTP, or another channel) and
   make it the default for new monitors.
4. Create the monitors:
   - one HTTP(s) monitor per tenant host, `https://<tenant>.<domain>/`;
   - an HTTP(s) monitor on `https://<domain>/health/` (expects 200);
   - certificate expiry: enable "Certificate Expiry Notification" on the HTTPS
     monitors (one per certificate is enough — the wildcard covers the rest);
   - a Push monitor "backup", heartbeat interval 90000 s (25 h);
   - a Push monitor "huey", heartbeat interval 180 s.
5. Copy each push monitor's URL, keep only `/api/push/<token>`, and put it in
   `.env` with the internal host name:

   ```sh
   KUMA_PUSH_BACKUP_URL=http://uptime-kuma:3001/api/push/<backup token>
   KUMA_PUSH_HUEY_URL=http://uptime-kuma:3001/api/push/<huey token>
   ```

6. `docker compose up -d huey backup` (they read `.env` only on recreate). The
   huey monitor turns green within a minute; the backup monitor turns green
   after the backup container's startup run. Confirm with
   `docker compose logs --tail=50 backup` — no "heartbeat to the backup monitor
   failed" warning.
7. Add at least one check from another machine (a free external uptime service
   or a second VM) on `https://<domain>/health/`: Kuma runs on this VM and
   cannot report the whole host going down.

### GlitchTip

1. Create its role and database inside the postgres container (replace
   `<password>` with `GLITCHTIP_DB_PASSWORD` from `.env`):

   ```sh
   docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres' <<'SQL'
   CREATE ROLE glitchtip LOGIN PASSWORD '<password>';
   CREATE DATABASE glitchtip OWNER glitchtip;
   SQL
   ```

2. In `.env`: `GLITCHTIP_DOMAIN=http://localhost:8004` (with the scheme) and
   `GLITCHTIP_EMAIL_URL=smtp+tls://<user>:<url-encoded password>@<host>:587`
   (without it GlitchTip sends no alert mail).
3. Start it: `docker compose up -d glitchtip-web glitchtip-worker` (later
   deploys start it on their own now that the database exists). Wait for
   `docker compose logs glitchtip-web` to finish its migrations; check
   `ss -ltn | grep 8004` shows `127.0.0.1:8004`.
4. Create the superuser:
   `docker compose exec glitchtip-web ./manage.py createsuperuser`
   (registration is off).
5. `ssh -L 8004:localhost:8004 <host>`, open http://localhost:8004, log in,
   create the organization and a project (platform Django), and set up its
   alert to email you.
6. Copy the project's DSN and replace its host with the internal one:
   `SENTRY_DSN=http://<key>@glitchtip-web:8000/<project id>` in `.env`.
7. `docker compose up -d backend huey` (both read `SENTRY_DSN`).
8. Check: `docker compose exec backend python manage.py shell -c "import sentry_sdk; sentry_sdk.capture_message('glitchtip test'); sentry_sdk.flush()"`
   — the event shows up in the project.
9. Add an HTTP monitor in Kuma on `http://glitchtip-web:8000/_health/` so a stopped
   GlitchTip doesn't go unnoticed.

## Risks

- **Redis memory.** See "A separate Redis for GlitchTip" above: an event spike
  can fill the shared 384 MB and block huey's queue.
- **GlitchTip on the production database server.** It runs migrations against
  its own database on the shared postgres; keep its image pinned and bump it
  deliberately.
- **Push URLs are credentials.** Anyone holding one can mark the monitor green;
  keep them in `.env` only.
