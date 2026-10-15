# GDPR erasure — how it works, and what is open

**Owner:** Engineering
**Status (2026-10-02):** erasure on request, requests the office files on
someone's behalf, the Art. 15 bundle and the replay after a restore are in
place. Open: statutory data kept for a period and then scrubbed (see the end).

This page describes the code as it is. When the erasure flow changes, change
this page in the same commit.

---

## How a deletion request runs

1. **Self-service request.** `POST /api/gdpr/request-deletion/` creates a
   `DeletionRequest` in `pending_email` and sends a confirmation link that is
   valid for 24 hours (email `gdpr.deletion_confirm`). Retention obligations
   are not checked here: the right to erasure stands, only its execution waits
   (Art. 17(3)). A new request cancels the person's earlier open one.
2. **Confirmation.** `POST /api/gdpr/confirm-deletion/<token>/` needs no login
   — the token is the proof. It moves the request to `pending_admin` and emails
   the tenant office (`gdpr.deletion_pending_admin_office`, without personal
   data).
3. **Requests the office files.** A person may ask by email, letter, phone or
   in person, also without a login.
   `POST /api/gdpr/admin/members/<id>/erase/` and
   `POST /api/gdpr/admin/resellers/<id>/erase/` (admin + step-up) record who
   filed the request and how the person asked, skip the email step and run it
   straight away.
4. **Approval.** Every request needs the office's approval — there is no
   per-tenant or per-role opt-out.
   `POST /api/gdpr/admin/approve-deletion/<id>/` (admin + step-up) runs the
   erasure; `POST /api/gdpr/admin/reject-deletion/<id>/` (admin) needs a
   reason. The office works the queue on the members area's data-protection
   page (`/members/data-protection`).
5. **Execution checks retention first.** While the subject has open coop
   shares (a payback still due included), active subscriptions, open charges or
   unpaid finalized invoices, it refuses with `gdpr.retention_active` (HTTP
   409, the reasons in `details`). The request then stays in `pending_admin`
   until the office has resolved them and approves again.

`GET /api/gdpr/admin/preview-deletion/<user_id>/` (admin, writes nothing)
shows what an erasure would change and what blocks it, read from the same
sources the execution uses.

## What an erasure does

`GDPRService.anonymize_subject` (in `jasmin-core/django-core/apps/gdpr/services/`)
runs in one transaction for an `ErasureSubject` — a login user, a member, a
reseller, or any combination of them:

- Each field is scrubbed or replaced by a placeholder as
  `apps/gdpr/field_classes.py` classifies it. Twelve models are classified:
  `accounts.JasminUser`, `commissioning.Member`, `Subscription`, `CoopShare`,
  `CoopShareTransfer`, `MemberLoan`, `Reseller`, `ContactEntity`,
  `UserInvitation`, `ConsentRecord`, `notifications.EmailLog` and
  `payments.BillingProfile`. A guard test fails when a new field that looks
  like personal data has no classification.
- A contact shared with another reseller or a delivery station is left as it
  is; the other records depend on it.
- Side channels: email-log recipients, subjects and errors; invitation
  addresses; consent IP addresses and user agents; the login records of
  django-axes (deleted); the audit-log entries of the records it touched (their
  `changes` and label wiped).
- Files on disk: the SEPA export files and the reseller invoice and
  delivery-note PDFs/XML older than the ten-year window are deleted; files
  still inside the window stay.
- A `DeletionLog` row records the erasure.

`anonymise_long_cancelled_members` (daily, 03:00) erases ex-members with a
login ten years after their exit, tenant by tenant through
`apps.shared.tenants.sweep.for_each_tenant`. A login that also holds a staff or
customer role outlives its member: the sweep erases the member alone and
releases the login, which keeps its account and loses only the member role
(`ErasureSubject.of_ex_member`).

## Access requests (Art. 15)

`GET /api/gdpr/my-data/` (the person themselves) and
`GET /api/gdpr/admin/members/<id>/subject-access/` /
`GET /api/gdpr/admin/resellers/<id>/subject-access/` (admin + step-up) return
`GDPRService.get_subject_access_bundle`: `format_version` 3 with 19 top-level
keys, each present even when empty.

## After a restore

A restore rolls every tenant's deletion log back together with the data the
logged erasures removed. The backup container therefore keeps a copy outside
the database: `backups/backup.sh ledger` merges every tenant's log into one
ledger every 10 minutes (an email address only as its SHA-256), never drops an
entry, and pushes an encrypted copy off-host. After the database restore,
`replay_gdpr_deletions --ledger -` re-runs the erasure for every subject the
restored data holds again and writes the log rows back. A log row without a
login names a member erased without one, so a login the restored member is
linked to is released again, not erased. The whole procedure is
in the header of `backups/restore.sh`; `scripts/restore_drill.sh` dry-runs the
replay on every drill. A subject whose retention obligation came back with the
restore is listed instead of erased, for the office to re-enter what the
restore undid (a share paid back, an invoice settled) and then erase.

---

## Open work

- **Statutory data kept for a period, then scrubbed.** `FieldClass.PII_RETAINED`
  and a `DeferredAnonymization` cron that scrubs such fields once their
  retention window ends are not built.

---

## Pattern reference

- **GDPR services** — `apps/gdpr/services/`: one mixin per concern
  (anonymization, retention, deletion workflow, subject access, preview),
  assembled into `GDPRService` in its `__init__.py`.
- **Encrypted-field handling** —
  `apps/shared/super_admin/management/commands/rotate_field_encryption.py`
  (iterating and rewriting ciphertext rows in chunks).
- **Per-tenant periodic jobs** — `apps.shared.tenants.sweep.for_each_tenant`.
- **Domain errors → HTTP** — `apps/gdpr/errors.py` (`raise SomeError` → DRF
  returns its code through `core.exception_handler`).
