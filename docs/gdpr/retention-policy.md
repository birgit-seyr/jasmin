# Data retention policy

**Owner:** Operations
**Last reviewed:** 2026-06-03
**Next review:** 2027-06-03 (annual)

This policy defines how long each data category is retained on the
Jasmin Platform and what mechanisms enforce it. It is the authoritative
answer to audit questions like:

- *"How long do you keep invoices?"* (GoBD §147 / BAO §132)
- *"How long after a member leaves do you keep their personal data?"* (DSGVO Art. 5(1)(e))
- *"How long do you keep change-history / log data?"*

## Summary table

| Data category | Retention | Enforcement | Rationale |
|---|---|---|---|
| Finalized invoices (`InvoiceReseller`, `InvoiceResellerContent`, ZUGFeRD XML, PDF) | **10 years** from end of fiscal year | `FinalizedProtectedMixin` blocks delete; pg_dump backups retained ≥10y | GoBD §147 AO (DE), BAO §132 (AT) |
| Finalized delivery notes (`DeliveryNoteReseller`, `DeliveryNoteContent`) | **10 years** from end of fiscal year | Same as above | Same — accompanying commercial document |
| Finalized orders (`Order`, `OrderContent`) | **10 years** from end of fiscal year | Same as above | Same — pre-document, but part of the audit trail |
| Member master data — active members | **For the duration of membership** + 10 years from last payment | DB row + backups; no automatic deletion | Tax law (joint liability for membership fees, SEPA mandate records) |
| Ex-member personal data | **10 years** from last payment, then **anonymise** (replace PII with NULL while keeping aggregate/sequence integrity) | Anonymisation cron (see ACTION below) | DSGVO Art. 5(1)(e) "storage limitation"; balanced against tax-law obligation |
| Change history (`auditlog_logentry`) | **Forever** | Default django-auditlog behaviour (no pruning) | Small row size, high audit value; documents survive even after their source row is deleted (generic FK) |
| Auth events (`logs/auth.log`) | **1 year** rolling window | `RotatingFileHandler`, size-rotated | Industry baseline for security forensics |
| Security events (`logs/security.log`) | **1 year** rolling window | Same | Same |
| App logs (`logs/app.log`) | **90 days** rolling window | Same | Operational, not legal — short window OK |
| GDPR deletion stubs (`DeletionLog`) | **Forever** | Default behaviour | Required as the audit trail of erasure requests; contains no personal data itself |
| pg_dump backups | **Daily snapshots for 30 days, weekly for 12 months, monthly forever (or ≥10y)** | Manual / cron pruning, with the "≥10y monthly" floor as the hard rule | Disaster recovery (recent) + tax retention (long tail) |

## What blocks accidental deletion

The platform already enforces invoice / delivery note / order
immutability at multiple layers:

- **Per-instance**: `FinalizedProtectedMixin.delete()` raises
  `FinalizedError` if `is_finalized=True`
  (`apps/commissioning/models/mixin.py`).
- **Bulk ORM**: `FinalizedProtectedQuerySet.delete()` raises
  `ValidationError` if the queryset includes any finalized row
  (`apps/commissioning/models/mixin.py`).
- **Tamper detection** for finalized invoices: the nightly Huey periodic
  task `nightly_invoice_hash_check` (`apps/commissioning/tasks.py`, crontab
  03:00, per-tenant) recomputes each invoice's `document_hash` and writes
  `invoice.hash_drift` warnings to `logs/security.log`. For an ad-hoc check,
  run `python manage.py check_invoice_hashes --schema=<tenant>` (exit 1 on
  drift).

Immutability of finalized documents is enforced at three layers:
`FinalizedProtectedMixin.save()` in Python, the `is_finalized` guard in
the serializers, and a Postgres `BEFORE UPDATE OR DELETE` trigger
installed per table (see `PROTECTED_TABLES` in
`apps/commissioning/migrations/0002_finalized_protection_and_reference_data.py`),
which raises `check_violation` on any attempt to alter or delete a
finalized row — including via raw SQL.

## Action items

- [x] **Ex-member anonymisation cron** — DONE 2026-06-03.
  `anonymise_long_cancelled_members` in `apps/gdpr/tasks.py`
  (Huey periodic task, daily 03:00) walks every tenant and
  anonymises Members whose `cancelled_effective_at` is more than
  10 years ago, honouring `check_retention_blocks` for ex-members
  with open CoopShares / open invoices.
- [x] **Backup pruning script** — DONE 2026-06-03.
  `prune_old_backups` in `apps/shared/tenants/tasks.py` (Huey
  periodic task, daily 05:00) enforces the retention window above
  (daily 30d / weekly 12mo / monthly ≥10y) against the
  `BACKUP_DIR` filesystem location.

## Enforcement mechanism for log retention

The three log windows above (auth: 1y, security: 1y, app: 90d)
are enforced by Python's `RotatingFileHandler` configuration in
`config/settings.py::LOGGING`. Concretely:

- File-size cap + backup-count rolling: when a log file hits its
  size cap, it rotates and the oldest backup beyond the count is
  deleted. The configured `maxBytes` / `backupCount` sizing covers
  the documented windows under normal traffic.

The policy windows above are the source of truth; the
RotatingFileHandler config below them is the current enforcement
mechanism, replaceable when scale demands it. If log volume ever
outgrows the rotation budget, raise `backupCount` or ship off-box
and treat the central store as authoritative.

## Review cadence

This document is reviewed annually (next: 2027-06-03). It must be
re-reviewed sooner if:

- Tax law changes (GoBD / BAO amendments, EU rules)
- A new data category is added to the platform
- A tenant requests a stricter / more permissive policy
