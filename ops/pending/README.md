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
