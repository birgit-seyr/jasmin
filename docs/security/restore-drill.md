# Backup restore drill — runbook

**Cadence:** quarterly (next due: see calendar reminder)
**Average run-time:** ~20 minutes once the runbook is internalised.

This runbook turns "we take daily backups" into "we **know** the
backups are restorable." Standard auditor question: _"When did you
last verify a restore?"_ — the answer needs a date, a row-count
diff, and a signed-off log entry in [`restore-drills/`](restore-drills/).

> **Why a drill matters.** Untested backups are theoretical. A
> Postgres dump can complete cleanly and still be unusable
> (truncated mid-stream, encryption-key drift, missing schemas,
> incompatible Postgres major version). The only way to find out
> is to restore one and look at it.

---

## State-of-play (current backup mechanics)

There are TWO things called "backup" in this repo. Know which one
you're restoring before you start.

| Mechanism                              | What it writes                          | Where                                                                                     | When it runs                                                    |
| -------------------------------------- | --------------------------------------- | ----------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `docker compose exec backup /usr/local/bin/backup.sh now` | `.sql.gz.gpg` (AES-256, gpg passphrase) | `./backups/<db>_YYYYMMDD_HHMMSS.sql.gz.gpg` on the prod host (bind-mounted into the container) | Ad-hoc, manual                                                  |
| `backups/backup.sh` (encrypted)        | `.sql.gz.gpg` (AES-256, gpg passphrase) | `/backups/<db>_YYYYMMDD_HHMMSS.sql.gz.gpg` inside the container, mounted from `./backups` | Automatically on `BACKUP_SCHEDULE` in the `backup` service      |

`backups/backup.sh` is the encrypted, GDPR-friendly script that the
super-admin backup-trigger view
(`apps/shared/super_admin/views/backup_views.py`) calls into via the
hard-coded path `/backup.sh`. It **is** wired into `docker-compose.yml`
now: a dedicated `backup:` service builds it and runs the encrypted dumps
automatically on `BACKUP_SCHEDULE` (the earlier bug — the script not being
wired to any container — is fixed). **This runbook handles BOTH formats**
so the drill works regardless of which mechanism produced the file.

---

## Prerequisites

1. **The prod host** (or a copy of `./backups/` with at least one
   recent backup file). The drill runs on the SAME machine as
   prod to avoid moving the encrypted blob over the wire.
2. **Docker + docker compose** installed (already required to run
   the stack).
3. **For encrypted backups only:** the `BACKUP_ENCRYPTION_KEY`
   passphrase. Stored in `.env` on prod and in your password
   manager. **Without this, encrypted backups are unrecoverable.**
   That alone is enough reason to run this drill — if the
   passphrase has drifted, you want to find out NOW.
4. **Enough free disk** for one extra copy of the database.
   The restored copy lives in a throwaway Docker container that
   the drill script tears down at the end.

---

## The drill

```bash
# From the repo root on the prod host (or wherever ./backups/ lives):
./scripts/restore_drill.sh                        # uses the newest file in ./backups/
# or pin a specific file:
./scripts/restore_drill.sh ./backups/jasmin-2026-05-25-0200.sql
./scripts/restore_drill.sh ./backups/jasmin_20260525_020000.sql.gz.gpg
```

What the script does (read
[`scripts/restore_drill.sh`](../../scripts/restore_drill.sh) for the full
sequence):

1. **Spins up a throwaway postgres** container
   (`jasmin-restore-sandbox`) on the same image (`postgres:15-alpine`)
   as prod, listening only on the docker-internal network — never
   exposed to the host.
2. **Decrypts + decompresses** if the file ends in `.sql.gz.gpg`
   (calls `gpg` + `gunzip`); otherwise restores the raw `.sql`
   directly. Restore uses `--single-transaction` so a corrupt dump
   fails atomically.
3. **Runs the row-count comparator:** per-schema, per-table row
   counts on the sandbox AND on the live prod DB, written
   side-by-side to a timestamped log under
   [`docs/security/restore-drills/`](restore-drills/).
4. **Tears down** the sandbox container + its volume. Nothing
   from prod is touched.

If steps 1-3 all succeed, the drill **passed**. Sign off in the
generated log file with your initials + any notes (e.g. "rowcounts
match within ±3 on auditlog_logentry, expected drift between
backup time and now").

If anything fails, do NOT clear the log — leave the failure in
place, file an incident, and skip the next scheduled drill until
the root cause is fixed.

---

## Real restore (production recovery — NOT the drill)

The drill above is a **read-only sandbox** — it never touches prod and
never replays GDPR deletions. A real recovery is a different, **two-step**
operation, and step 2 is mandatory: a SQL restore re-materialises
personal data that was lawfully erased *after* the backup was taken, so
the GDPR-deletion replay must follow immediately.

> **Two containers, by design.** The SQL restore needs `psql` + `gpg`
> (the `backup` image); the GDPR replay needs Python + Django (the
> `huey` / `backend` image). No single image has both, so the restore is
> split into two explicit steps rather than one script that can't run
> end-to-end.

**Step 1 — restore the SQL dump.** Run in the `backup` container, which
has `psql` + `gpg` and already carries the `POSTGRES_*` /
`BACKUP_ENCRYPTION_KEY` env. `restore.sh` is reachable at
`/backups/restore.sh` via the bind mount; override the entrypoint to run
it.

First stop the app services that hold DB connections — the dumps use
`pg_dump --clean --if-exists`, so the restore drops and recreates objects,
and any active connection mid-`--clean` can corrupt the restored DB:

```bash
docker compose stop backend huey

docker compose run --rm --entrypoint sh backup \
  /backups/restore.sh /backups/<db>_YYYYMMDD_HHMMSS.sql.gz.gpg
```

**Step 2 — replay GDPR deletions.** Run in a Python/Django container.
The `huey` service runs `jasmin/backend:latest` (has `manage.py`):

```bash
docker compose exec huey python manage.py replay_gdpr_deletions
```

(`backend` works too.) Skipping step 2 re-exposes erased personal data —
a GDPR breach. `restore.sh` prints this exact command on completion so
the second step can't be silently forgotten.

Once both steps are done, bring the app services back up:

```bash
docker compose start backend huey
```

**Media archive (if present).** Alongside each DB dump, `backup.sh` also writes
an encrypted `*_media_*.tar.gz.gpg` of the `media_volume` (invoice / delivery-
note PDFs, e-invoice XML, tenant logos). A DB-only restore leaves `file` columns
pointing at files that no longer exist, so restore the matching media archive
into the volume too:

```bash
docker compose run --rm --entrypoint sh backup -c '
  gpg --batch --quiet --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" \
      /backups/<db>_media_YYYYMMDD_HHMMSS.tar.gz.gpg \
    | gunzip | tar -C /app/media -xf -'
```

(The `backup` service mounts `media_volume` read-only, so for a real restore
run this from a container with the volume mounted read-write, e.g. a one-off
`docker compose run` with an `-v media_volume:/app/media` override.)

---

## Reading the row-count comparison

The log under `docs/security/restore-drills/YYYY-MM-DD.md` contains a table
per tenant schema (plus `public`). Each row is:

```
schema   | table                       | sandbox_rows | prod_rows | diff
---------+-----------------------------+--------------+-----------+------
public   | tenants_tenant              |            3 |         3 |    0
public   | tenants_domain              |            5 |         5 |    0
test_pyt | commissioning_member        |          412 |       415 |   +3
test_pyt | accounts_jasminuser          |          418 |       421 |   +3
test_pyt | auditlog_logentry           |        12943 |     13104 |  +161
...
```

**Expected drift:** rows created in the window between when the
backup ran and when the drill runs (typically hours). These will
show as `prod_rows > sandbox_rows`. Healthy.

**Red flags:**

| Pattern                                                                   | What it means                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sandbox_rows > prod_rows` for any row                                    | Either the backup is OLDER than the sandbox state (impossible if you took it from `./backups/`), or rows were deleted on prod since. Investigate.                                                                                                 |
| `diff` much larger than the time-window's typical write rate              | Either the backup is much older than expected, or something on prod is silently writing a lot more than usual.                                                                                                                                    |
| Missing schema in the sandbox (tenant present on prod, absent in sandbox) | Backup was taken before that tenant was provisioned — usually fine if you can match the date. Otherwise serious.                                                                                                                                  |
| Table present on prod, absent in sandbox                                  | New migration shipped between backup and now. Check `migrations/` git log against backup date.                                                                                                                                                    |
| `gpg: decryption failed: Bad session key`                                 | The passphrase in `BACKUP_ENCRYPTION_KEY` doesn't match what was used to encrypt. **STOP.** Find the right passphrase before doing anything else — if you can't, your encrypted backups are unrecoverable and you need a new backup strategy NOW. |

---

## Filing the drill output

After a successful drill:

```bash
# Generated log lives at docs/security/restore-drills/2026-05-25.md (today's date).
# Append a sign-off block to it:
cat >> docs/security/restore-drills/2026-05-25.md <<'EOF'

## Sign-off
- **Operator:** bia
- **Date:** 2026-05-25
- **Outcome:** PASS — row count diff within expected window
- **Notes:** (anything weird, e.g. one tenant schema 1.5x larger than expected)
EOF

git add docs/security/restore-drills/2026-05-25.md
git commit -m "ops: Q2 2026 restore drill — pass"
```

The committed log is the **audit artifact**. Auditors / DPOs
asking "when did you last verify a restore?" get a `git log`
answer with a real diff attached.

---

## Failure modes (what to do if the drill fails)

1. **`gpg` fails to decrypt.** See the table above. Stop, find
   the passphrase, do not retry.
2. **`psql` reports a syntax error mid-restore.** Backup is
   truncated or corrupt. Try the next newer or next older backup.
   If multiple consecutive backups fail, the backup pipeline
   itself is broken — open a P1.
3. **`pg_restore: error: schema "<tenant>" already exists`** (only
   relevant if you're using `pg_dump`/`pg_restore` directly). The
   sandbox container is fresh per drill, so this shouldn't happen
   — if it does, `docker volume rm` the sandbox volume and re-run.
4. **Row counts wildly off.** See "Red flags" above. The drill is
   a CHECK, not a fix — if the check fails, file an incident
   ticket and investigate before signing off.

---

## Related items in [`docs/todos/tasks.txt`](todos/tasks.txt)

This drill addresses one item on a larger backup backlog:

- **[ ] Off-site backups** — local backups in `./backups/` don't
  survive a disk failure on the prod box. Drill doesn't help
  with that; it's a separate task.
- **[x] Quarterly restore drill** — this runbook.
- **[ ] Backup retention policy** — "daily for 30, weekly for 12
  months, monthly forever." Currently implicit (the
  `backup.sh` script has a `BACKUP_RETENTION_DAYS=30` default
  but no longer-term tiering).

When you finish the off-site backup task, add a second step to
this drill: also pull the latest off-site copy and restore from
THAT, to verify the off-site upload didn't corrupt anything.
