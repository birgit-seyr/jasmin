# Restore-drill logs

This directory holds the output of each quarterly restore drill.
The drill itself is documented in [`../restore-drill.md`](../restore-drill.md).

## Filename convention

```
YYYY-MM-DD.md          # drill date
YYYY-MM-DD-rerun.md    # if the same-day drill needed a retry
```

The `./scripts/restore_drill.sh` script writes the log automatically
on a successful run, picking today's date.

## What each log contains

1. **Header** — backup file used, backup timestamp, drill timestamp.
2. **Row-count comparison table** — per-schema, per-table counts
   on the sandbox-restored DB vs live prod, with a `diff` column.
3. **Sign-off block** — appended manually by the operator after
   reviewing the diff:

   ```markdown
   ## Sign-off
   - **Operator:** <name>
   - **Date:** <YYYY-MM-DD>
   - **Outcome:** PASS | FAIL
   - **Notes:** <anything weird, expected drift, follow-ups>
   ```

A signed-off log = the audit artifact. Auditor question "when did
you last verify a restore?" is answered with `git log` of this dir.

## What's NOT in this directory

- The backup files themselves. Those stay in `./backups/` (or
  off-site once that's wired up). Logs reference the filename but
  don't embed the contents — a backup is large and may contain
  PII even encrypted (the filename / size leaks signal).
- Failure dumps. If the drill fails, leave the log in place AND
  open an incident ticket; don't delete or rerun without
  signing off on the failure mode first.
