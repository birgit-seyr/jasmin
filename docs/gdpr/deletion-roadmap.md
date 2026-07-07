# GDPR deletion / anonymization — implementation roadmap

**Owner:** Engineering
**Started:** 2026-05-25
**Status:** Steps 1 + 2 + 4 + 5 + 6 + 7 + 9 done; Step 3 effectively done (the command already delegates to `anonymize_user`; only the retention-skip-on-replay nuance is open). Remaining: Step 8 (retention cron), Step 10 (admin anonymize-other-user).

This is the step-by-step plan to bring GDPR-conformant deletion +
anonymization from the current half-wired state to a defensible,
state-of-the-art implementation.

Each step is checked off when shipped, with the commit / file path
recorded. Steps are ordered so that the highest-impact / lowest-effort
items ship first and the system is incrementally more compliant after
each merge.

---

## Current state (snapshot 2026-05-25)

| Piece | Status | Where |
|---|---|---|
| Data-export endpoint (Art. 15) | ✅ basic | `gdpr_my_data_view` → returns JasminUser + Member fields only |
| Self-deletion endpoint (Art. 17) | ✅ basic | `gdpr_request_deletion_view` → POST, no confirmation step |
| `GDPRService.anonymize_user()` | ⚠ partial | Anonymizes JasminUser + Member only |
| `DeletionLog` audit trail | ✅ | `apps/gdpr/models.py` |
| Backup-replay command | ⚠ outdated | Only re-sets first/last/email; misses Member fields, encrypted IBAN, etc. |
| Admin endpoint to anonymize OTHER users | ❌ missing | The view only handles self-deletion via JWT |

## Identified gaps

### 🟠 HIGH — Anonymization is incomplete; PII survives "deletion"

`anonymize_user()` only touches `JasminUser` + `Member`. The following still hold the deleted person's PII afterward:

1. **`BillingProfile`** (apps/payments) — encrypted IBAN/BIC/account_holder + `sepa_mandate_reference`. Untouched.
2. **`Reseller.contact` → `ContactEntity`** — for a member who's ALSO a customer/reseller, all the billing-side fields (`invoice_name`, `invoice_email`, `email`, `phone`, `iban`) survive.
3. **`UserInvitation`** — historic invitations still hold the email.
4. **`EmailLog`** (apps/notifications) — every email ever sent to them, with recipient address. Mass leak vector.
5. **`auditlog_logentry`** — old rows from BEFORE the §logging audit `mask_fields` was added still have plaintext PII in the `changes` JSON column.
6. **`axes_accessattempts` / `axes_accesslogs`** — failed-login records with username + IP.
7. **`Member.user_FK`** — currently SET_NULL on JasminUser delete, but `anonymize_user` doesn't `.delete()` the JasminUser, it overwrites it with placeholders. Fine, but means the original user row stays as `deleted_<pk>@deleted.invalid` forever.

### 🟠 HIGH — No pre-flight check for retention obligations

Current code happily anonymizes a Member who has:
- Active CoopShare (German GenG: member-registry must persist while shares are held)
- Open invoices < 10 years old (UStG §14, HGB §257)
- Active subscription with open ChargeSchedule

**Art. 17(3)(b) explicitly carves out** "compliance with a legal obligation that requires processing." The right move is **refuse anonymization** (or do **partial anonymization** — drop email/phone NOW, keep statutory name/address for the retention window) when these obligations are open.

### 🟠 HIGH — Different user shapes, one undifferentiated flow

The three personas have totally different legal pictures:

| Persona | Has CoopShare | Has invoices | Statutory retention | Action on "delete me" |
|---|---|---|---|---|
| **Member** (co-op member) | Yes | Yes | GenG (registry while held + 10y after exit) + HGB (10y invoices) | Refuse until exit + retention elapsed. Then tombstone. |
| **Customer** (reseller) | No | Yes | UStG §14 (10y) | Anonymize contact PII immediately. Keep invoice rows. Anonymize invoice address fields after 10y via cron. |
| **Staff** (JasminUser, no Member, no Reseller) | No | No (acts as `created_by`, not subject) | None (only HR docs outside this system) | Anonymize JasminUser immediately. `created_by` FKs are SET_NULL — invoices stay readable. |

`anonymize_user()` doesn't branch on persona. It does the same thing for all three.

### 🟡 MEDIUM — Self-deletion endpoint has no confirmation step

`POST /api/gdpr/request-deletion/` with a valid JWT immediately anonymizes. No email verification, no 2nd-factor, no admin acknowledgement. If a session token leaks, the attacker can permanently nuke the legitimate user's data.

Industry standard: request creates a `DeletionRequest` row in `PENDING` state, sends an email with a confirmation link valid for 24h, only then anonymize.

### 🟡 MEDIUM — Subject Access Request (Art. 15) is incomplete

`get_personal_data_summary()` returns Member + JasminUser fields. But a complete export should include:
- All Subscriptions, CoopShares (with dates + amounts)
- All Orders + OrderContents (their purchase history)
- All Invoices (links + amounts + dates)
- All EmailLog entries (every email sent to them)
- All ConsentRecord entries (privacy/SEPA consent timestamps)
- Login history (last_login, last_login_ip, recent axes-attempt records)

### 🟡 MEDIUM — `replay_gdpr_deletions` command is out of date

Only re-sets `first_name`, `last_name`, `email` on the JasminUser. Misses everything else `anonymize_user` does (the Member fields, encrypted IBANs, etc.). A restore would resurrect those fields.

### 🟢 LOW — No retention-cron for cleanup

No Huey task that walks anonymized rows past their retention window and hard-deletes (or scrubs further). Statutory invoices from 2014 should not still have member names on them in 2026.

---

## Target architecture

### 1. Field-level retention classification

Tag each PII-bearing model field with one of four retention statuses. Single source of truth in `apps/gdpr/field_classes.py`:

```python
class FieldClass(str, Enum):
    PII_IMMEDIATE = "pii_immediate"     # anonymize on request, no obligation
    PII_RETAINED  = "pii_retained"      # legally retained for N years post-event
    TOMBSTONE     = "tombstone"         # name/id kept as "Gelöscht #<id>" placeholder
    OPERATIONAL   = "operational"       # not PII; leave alone

FIELD_CLASSIFICATION = {
    "accounts.JasminUser": {
        "email":           (FieldClass.PII_IMMEDIATE, None),
        "first_name":      (FieldClass.TOMBSTONE,    "Gelöscht"),
        ...
    },
    ...
}
```

A guard test (same shape as `apps/authz/tests/test_state_field_update_bypass_guard.py`) enforces every PII-typed field has an entry.

### 2. Persona-aware deletion service

```python
class GDPRService:
    @staticmethod
    def preview_deletion(user) -> DeletionPreview: ...     # dry-run
    @staticmethod
    def request_deletion(user, *, requested_by) -> DeletionRequest: ...  # creates PENDING
    @staticmethod
    def execute_deletion(request: DeletionRequest) -> DeletionResult: ...  # post-confirmation
```

Branches inside `execute_deletion` per persona (Member / Customer / Staff).

### 3. Two-step confirmation flow

```
POST /api/gdpr/request-deletion/    → DeletionRequest(state="PENDING", token=<random>)
                                    → email with confirmation link
POST /api/gdpr/confirm-deletion/<token>/    → state="CONFIRMED" → execute → log
```

### 4. Proper Subject Access Request (Art. 15) bundle

JSON or ZIP export containing all related rows the data subject has,
not just account+member fields.

### 5. Retention cron

Huey periodic task processing `DeferredAnonymization` rows whose
`execute_after <= today`.

---

## Step-by-step implementation plan

Each step is a small PR; merge when it passes locally + CI.

### ☑ Step 1 — Pre-flight retention check (DONE 2026-05-25)

**What:** Refuse anonymization when active CoopShare / open invoice /
active subscription / open ChargeSchedule exists for the user.

**Shipped:**
- New: `apps/gdpr/errors.py` — `GDPRError`, `RetentionPeriodActive`
  (subclass of `ConflictError` → HTTP 409, carries `reasons` list
  in `details`).
- New: `apps/gdpr/services.py::GDPRService.check_retention_blocks(user) -> list[str]`
  — checks the four obligation classes (GenG §5, HGB §257, UStG §14b,
  active service contract).
- Modified: `GDPRService.anonymize_user()` — calls the check first;
  raises if any block exists. JasminUser row is left unchanged on
  refusal (verified by `test_anonymize_raises_when_blocks_exist`).
- View: no change needed — `core.exception_handler` converts
  `RetentionPeriodActive` to a 409 with
  `{code: "gdpr.retention_active", message, details: {reasons: [...]}}`
  automatically.

**Tests:** `apps/gdpr/tests/test_retention_blocks.py` — 12 tests across 2
classes covering: clean staff user, each obligation class in isolation,
parametrised PLANNED/ISSUED/PARTIAL + PAID/WAIVED for charges,
unpaid vs paid invoices, aggregation, settled-then-anonymizable path.

**Acceptance:** ✅ No more anonymizations that destroy statutory data links.

### ☑ Step 2 — Extend `anonymize_user()` to cover the missing models (DONE 2026-05-25)

**What:** Scrub PII on `BillingProfile`, `ContactEntity` (via Reseller),
`Reseller`, `UserInvitation`, `EmailLog`,
`axes AccessAttempt + AccessFailureLog`.

**Shipped:**
- Refactored: `apps/gdpr/services.py::anonymize_user` is now an
  orchestrator wrapped in `@transaction.atomic`. Each model gets its
  own `_anonymize_<model>(...)` helper so the pipeline reads
  top-down and each helper is independently testable.
- New phase: `_collect_known_emails(user)` runs FIRST so the
  side-channel scrubs (EmailLog, axes) have search keys before the
  primary records' emails are wiped.
- New helpers:
  - `_anonymize_billing_profile` — deactivates the profile, switches
    payment method to `BANK_TRANSFER`, scrubs the 3 encrypted bank
    columns + `sepa_mandate_reference` (NULL — safe under the
    `unique=True` constraint because Postgres treats NULLs as
    non-equal).
  - `_anonymize_reseller_for_user` — scrubs the Reseller's
    `invoice_*` display fields, deactivates all 4 `is_active_*`
    flags, releases the `linked_user` OneToOne. Then delegates to
    `_anonymize_contact_entity` IF the contact isn't shared.
  - **Safety branch in the contact wipe:** if the same `ContactEntity`
    is referenced by another `Reseller` OR by a `DeliveryStation`,
    we skip the wipe (delivery routing / other tenants' B2B data
    depends on it) and log a warning. Only solo contacts get
    scrubbed.
  - `_anonymize_user_invitations` — overwrites the recipient `email`
    on every historic `UserInvitation`; keeps token + status so the
    audit trail of who-was-invited-when stays intact.
  - `_anonymize_email_logs` — rewrites `recipient` to
    `deleted@deleted.invalid` on every `EmailLog` row sent to any
    of the subject's known addresses. Also tombstones `subject` to
    `Gelöscht` (tenant-editable templates can render the person's
    name into the subject; `template` + `purpose` keep the
    operational signal) and wipes `error` (bounce messages echo the
    address). Subject scrub added 2026-06-12 (audit finding A12).
  - `_purge_axes_records` — hard-deletes `AccessAttempt` +
    `AccessFailureLog` rows keyed by `username in known_emails`.
    These are transient security records, no retention obligation.

**Tests:** `apps/gdpr/tests/test_extended_anonymization.py` — 14 tests
across 7 classes:
- `TestBillingProfileAnonymization` (3) — happy scrub, no-profile no-op,
  multi-row uniqueness on NULL mandate refs.
- `TestResellerAnonymization` (2) — invoice fields scrubbed + linked_user
  released, no-reseller no-op.
- `TestContactEntityAnonymization` (3) — solo contact wiped, shared
  with another Reseller kept, shared with DeliveryStation kept.
- `TestUserInvitationAnonymization` (1) — recipient emails scrubbed,
  status preserved.
- `TestEmailLogAnonymization` (1) — multiple known addresses + error
  field wipe + unrelated rows untouched.
- `TestAxesPurge` (2) — AccessAttempt + AccessFailureLog deletion,
  other users' rows untouched.
- `TestTransactionalAtomicity` (1) — mid-pipeline failure rolls back
  all earlier writes (the whole point of `@transaction.atomic`).

**Acceptance:** ✅ The seven models that previously leaked PII after
"anonymization" now get scrubbed in the same atomic call. Auditor
question "can you show me what's left after we delete a member?" now
has an answerable, tested response.

### ☐ Step 3 — Bring `replay_gdpr_deletions` back in sync (MEDIUM, ~30m)

**What:** Stop duplicating anonymization logic. The command should
re-call `GDPRService.anonymize_user()` (or a special variant that
skips the retention check, since we already passed it before backup).

**Where:**
- Modify: `apps/gdpr/management/commands/replay_gdpr_deletions.py`.

**Tests:**
- `test_replay_calls_anonymize_user_for_each_logged_email`
  (mock the service, assert called per log entry).

**Acceptance:** Restoring a backup + running the replay yields the
same DB state as if the deletions had happened post-restore.

### ☑ Step 4 — `FIELD_CLASSIFICATION` map + iterate-over-it refactor (DONE 2026-05-25)

**What:** Replace the per-model hardcoded field lists in `anonymize_user`
with a single dict + a generic iterator, plus a discovery guard so a
new PII column can't ship without an explicit classification choice.

**Shipped:**
- New: `apps/gdpr/field_classes.py` — `FieldClass` enum
  (`PII_IMMEDIATE` / `PII_RETAINED` / `TOMBSTONE` / `OPERATIONAL`)
  + `FIELD_CLASSIFICATION` dict keyed by `Model._meta.label`. Eight
  models classified: `accounts.JasminUser`, `commissioning.Member`,
  `payments.BillingProfile`, `commissioning.Reseller`,
  `commissioning.ContactEntity`, `commissioning.UserInvitation`,
  `notifications.EmailLog`, `commissioning.ConsentRecord`.
- New helpers in the same module: `get_classification(model_label)`
  + `resolve_replacement(replacement, instance)` (handles both
  static values and per-row callables like
  `lambda i: f"deleted_{i.pk}@deleted.invalid"`).
- Refactor in `apps/gdpr/services.py`: a single module-level
  `_apply_classification(instance, model_label)` does the in-memory
  field setting for `PII_IMMEDIATE` + `TOMBSTONE`. Every
  `_anonymize_<model>` helper calls it instead of hand-listing
  fields. Bulk paths (`_anonymize_email_logs`,
  `_anonymize_consent_records`) build their `update(**kwargs)` from
  the dict and raise if they hit a per-row callable (which the bulk
  path can't run — switches the helper to a per-instance loop).
- Step 4 surfaced two new gaps:
  - `commissioning.ConsentRecord.ip_address` + `user_agent` weren't
    in `anonymize_user` at all. New helper
    `_anonymize_consent_records(member)` wired into Phase 2; row
    stays (consent audit trail), columns get scrubbed.
  - `commissioning.Member.company_name` wasn't classified — added
    as `PII_IMMEDIATE`.

**Tests:** `apps/gdpr/tests/test_field_classification_guard.py` —
walks every model in `accounts`, `commissioning`, `payments`,
`notifications`; for each field whose NAME matches a PII token
(`email`, `iban`, `phone`, `address`, `first_name`,
`account_holder`, `ip_address`, …), asserts it's either in
`FIELD_CLASSIFICATION` or in the test-module `IGNORE_FIELDS`
allow-list (with a one-line reason). Two extra guards catch dict
drift (entry references a model/field that no longer exists).

The allow-list documents the deliberate non-classifications:
- `gdpr.DeletionLog.user_email` — audit trail of the deletion event
  itself; required by `replay_gdpr_deletions`.
- `commissioning.DeliveryStation.contact_name` / `contact_phone` /
  `access_code` — belong to a shared pickup point, not to any one
  data subject.
- `commissioning.SharesDeliveryDay.acronym` /
  `commissioning.OrdersDeliveryDay.acronym` — route codes ("MO"),
  not a person's initials.

**Acceptance:** ✅ Adding a new PII field forces an explicit
classification choice at PR time — the guard test fails with the
exact `model.field` name and a pointer to the two valid responses
(classify, or add to `IGNORE_FIELDS` with a reason).

### ☑ Step 5 — Persona-aware branching + `preview_deletion()` (DONE 2026-07-07)

**What:** Classify the data subject by persona (Member / Customer /
Staff) and add a dry-run that returns the would-be diff so the admin
sees exactly what will happen before clicking go.

**Shipped:**
- New: `apps/gdpr/services/preview.py` — a `PreviewMixin` added to the
  mixin-composed `GDPRService` (the `services.py` in the original plan
  is now a package; the facade in `services/__init__.py` gained the
  mixin + the runtime-binding-loop entry).
- New: `GDPRService.detect_persona(user) -> Persona` + a `Persona`
  StrEnum (`MEMBER` / `CUSTOMER` / `STAFF`), re-exported from the
  package. Classification is the **structural** signal `anonymize_user`
  already branches on — a `Member` row ⇒ MEMBER, a `Reseller` link with
  no Member ⇒ CUSTOMER, neither ⇒ STAFF. A member-who-is-also-a-customer
  is MEMBER (stricter registry obligation governs).
- New: `GDPRService.preview_deletion(user) -> dict` — a pure **dry-run**
  (writes nothing) that reports persona, `has_member` / `has_reseller`,
  `can_anonymize_now`, the `retention_blocks` list, and per present
  model the affected `row_count` + `scrubbed_fields` (field + action +
  human "becomes"), plus the non-field-classified `side_channels`
  (auditlog / axes / on-disk SEPA + reseller-document purges). It reads
  the SAME sources of truth the executor does — `check_retention_blocks`
  + `FIELD_CLASSIFICATION`, and mirrors the executor's per-model row
  scoping (incl. the shared-ContactEntity skip) — so the preview can't
  drift from what `anonymize_user` actually does.
- New endpoint: `GET /api/gdpr/admin/preview-deletion/<user_id>/`
  (`IsAdmin`, read-only so no step-up). Placed under `admin/` for
  consistency with the other admin deletion endpoints (the plan wrote
  `/preview-deletion/`). Serializer: `DeletionPreviewSerializer` (+ the
  nested `PreviewModel` / `PreviewField` / `PreviewSideChannel`
  serializers) in `apps/gdpr/serializers.py`.

**Design note — no `execute_deletion` path rewrite.** The plan's
`_member_path` / `_customer_path` / `_staff_path` refactor was written
before Step 6, which already introduced `_execute_deletion(request)` as
the confirmed-execution tail. The atomic `anonymize_user` pipeline is
already persona-adaptive via presence checks (`if member is not None`,
`Reseller.objects.filter(linked_user=user)`, the shared-contact skip),
and the retention pre-flight (Step 1) enforces the persona-specific
"refuse while obligations are open" rule. Rewriting that well-tested
pipeline into three explicit path methods is pure churn with no
behavior change, so persona-awareness was delivered as an explicit
`Persona` classification + the faithful preview instead of a risky
re-org of the executor.

**Tests:** `apps/gdpr/tests/test_deletion_preview.py` — 13 tests across
5 classes: persona detection (member / reseller-only / staff /
member+reseller), preview shape per persona (staff JasminUser fields +
`can_anonymize_now`, member Member fields with the tombstone/immediate
actions, customer Reseller model, side-channels), retention surfacing
(open CoopShare ⇒ `can_anonymize_now=False` + a surfaced block), the
writes-nothing guarantee (user/member unchanged after a preview), and
the endpoint (admin 200, non-admin 403, unknown id 404).

**Acceptance:** ✅ Admin can GET the endpoint and see "this will
anonymize X fields on Y models" (`field_count` / `model_count` + the
per-model list) and "…and is currently blocked by Z" (`retention_blocks`
+ `can_anonymize_now`). The "under retention until `<date>`" wording is
softened to the block reasons, because the system refuses on *open*
obligations rather than computing per-field expiry dates (those land
with Step 8's `PII_RETAINED` cron).

### ☑ Step 6 — Two-step (optionally three-step) confirmation flow (DONE 2026-05-25)

**What:** `POST /request-deletion/` no longer anonymizes immediately.
It creates a `DeletionRequest` and sends a 24h confirmation email.
The user clicks the link to actually delete. An OPTIONAL admin-approval
gate sits between the email confirm and the execute step, switched on
EITHER per tenant (a new TenantSettings flag) OR automatically when
the data subject is a high-risk persona (staff/admin).

**Shipped:**
- New model: `apps/gdpr/models.py::DeletionRequest` with a 7-state
  enum (PENDING_EMAIL → PENDING_ADMIN → APPROVED → EXECUTED, plus
  EXPIRED / CANCELLED / REJECTED terminals). Token is a UUID with a
  24h TTL stamped on `save()`. The row pairs 1:1 with the
  `DeletionLog` audit row on execute (via the `deletion_log` FK).
  Inherits `AdminConfirmableMixin` from
  `apps.commissioning.models.mixin` for the admin-decision fields
  (`admin_confirmed`, `admin_confirmed_by`, `admin_confirmed_at`,
  `admin_rejection_reason`) + the `confirm()` / `reject()` methods.
  Cross-app import is fine here: the rule per CLAUDE.md is one-way
  — other apps may import FROM commissioning; commissioning may
  not import from elsewhere.
- Migration: generated by `python manage.py makemigrations gdpr`
  after the model lands (left to the developer running it locally;
  the hand-written first cut was discarded in favour of letting
  Django produce the exact shape).
- New tenant setting:
  `TenantSettings.require_admin_approval_for_gdpr_deletion`
  (Boolean, default **True** — admin gate is the safer baseline;
  tenants who want the Art-17-clean fast path flip it off).
  Migration: `apps/shared/tenants/migrations/0006_…`. The service
  honours the model-level default when no `TenantSettings` row
  exists yet, so a brand-new tenant isn't silently in
  "gate-off" mode until someone clicks Save.
- New errors in `apps/gdpr/errors.py`:
  - `DeletionTokenInvalid` (404 — also covers malformed-UUID and
    already-consumed tokens, identical response to "unknown" so an
    attacker can't probe).
  - `DeletionTokenExpired` (409 — also flips the row to EXPIRED so
    the audit trail captures the lapse).
  - `DeletionRequestNotPending` (409 — admin tried to act on a
    request not in PENDING_ADMIN).
- New service methods on `GDPRService`:
  - `request_deletion(user) → DeletionRequest` — runs the retention
    pre-flight FIRST (no point sending a doomed email), cancels any
    prior open request (one live request per user), stamps the
    admin-gate flag from tenant settings + persona role.
  - `confirm_deletion_token(token, *, ip) → DeletionRequest` — either
    executes immediately or transitions to PENDING_ADMIN. Wrapped in
    `@transaction.atomic` with `select_for_update` so two
    simultaneous clicks can't race.
  - `admin_approve_deletion(request, *, admin_user, note)` — third
    gate; runs anonymization on success.
  - `admin_reject_deletion(request, *, admin_user, reason)` —
    terminal REJECTED state with the reason captured for audit.
  - `_execute_deletion(request)` — common tail used by both
    no-gate and admin-approved paths; re-checks retention to
    avoid the stale-pre-flight Art. 17(3)(b) edge case (member
    could have signed a new CoopShare while the request sat in
    PENDING_ADMIN).
- Elevated personas that ALWAYS need admin sign-off, regardless of
  the tenant toggle: `ADMIN, MANAGEMENT, OFFICE, STAFF, GARDENER`.
  Defined as `_ELEVATED_ROLES_REQUIRING_ADMIN_GATE` in
  `apps/gdpr/services.py`.
- View layer (`apps/gdpr/views.py`):
  - `POST /api/gdpr/request-deletion/` — 202, returns
    `request_id` + `requires_admin_approval`.
  - `POST /api/gdpr/confirm-deletion/<token>/` — `AllowAny`
    (the token IS the proof; the JWT may have expired by the time
    the user opens their email).
  - `POST /api/gdpr/admin/approve-deletion/<request_id>/` (IsAdmin).
  - `POST /api/gdpr/admin/reject-deletion/<request_id>/` (IsAdmin)
    — `reason` field is required, 400 if missing.
- Email template `gdpr.deletion_confirm` (DE + EN, HTML + TXT)
  registered in `apps/notifications/registry.py`. Renders a red
  confirm button (visually distinct from the green
  invitation/password-reset CTA) and a conditional "office will
  review" line when `requires_admin_approval=True`.
- `anonymize_user()` now returns the `DeletionLog` it created (was
  void) so the `DeletionRequest` can store a pointer for audit.

**Tests:** `apps/gdpr/tests/test_two_step_deletion.py` — 17 tests
across 6 classes:
- `TestRequestDeletion` (5) — happy path, retention blocks early,
  tenant-setting gate, parametrised elevated-role gate (admin /
  office / staff / management / gardener), supersession of prior
  open request.
- `TestConfirmDeletionToken` (6) — no-gate executes immediately,
  with-gate moves to PENDING_ADMIN, unknown / malformed / consumed
  / expired token paths, late retention re-check.
- `TestAdminApproveDeletion` (2) — happy path executes, refuses
  outside PENDING_ADMIN.
- `TestAdminRejectDeletion` (2) — happy path captures reason,
  refuses outside PENDING_ADMIN.
- View-level (3) — request → 202, confirm with bad token → 404,
  admin endpoints execute / require reason / 403 for non-admins.

**Acceptance:** ✅ A leaked JWT can no longer anonymize on its own.
A second factor (email control) is always required; high-risk
deletions (staff/admin, or any deletion in tenants who opt in) need
a third factor (office human-in-the-loop).

### ☑ Step 7 — Expand Art. 15 SAR to include all related data (DONE 2026-05-25)

**What:** Return a complete bundle of every row tied to the user,
not just account + member. Subscriptions, CoopShares, Orders,
Invoices, EmailLog, ConsentRecord, login history.

**Shipped:**
- Renamed: `GDPRService.get_personal_data_summary()` →
  `get_subject_access_bundle()`. View
  (`gdpr_my_data_view` at `GET /api/gdpr/my-data/`) updated to call
  the new name. The pre-existing keys (`account`, `member`) keep
  their exact field names so the in-modal viewer
  (`UserProfileModal`) continues to render without changes — the
  expansion is purely additive.
- Bundle shape (15 top-level keys, always present — empty lists /
  `None` when not applicable so the frontend doesn't need
  defensive guards):
  - `format_version` (int) + `exported_at` (ISO) + `subject` —
    metadata block.
  - `account`, `member`, `reseller` — the three identity rows
    (latter two `None` when the persona doesn't apply).
  - `consents` — every `ConsentRecord` ever stamped (privacy /
    SEPA / …) with the document version + forensic IP/UA capture
    + revocation tail. Newest-first.
  - `coop_shares` — GenG cooperative-share holdings (amount +
    confirmation + payment status).
  - `subscriptions` — active + historical service contracts on the
    member's SubscriptionGroups.
  - `member_loans` — member-to-co-op loans (amount, interest,
    start/end/paid_back dates).
  - `charge_schedules` — the member's billing ledger (period,
    amount, due date, status).
  - `reseller_orders` + `reseller_invoices` — B2B order +
    invoice history (only populated when the user is linked to a
    Reseller).
  - `email_log` — every `EmailLog` row sent to any of the
    subject's known addresses (capped at `SAR_EMAIL_LOG_LIMIT=500`,
    with `truncated` + `total_count` flags).
  - `login_history` — successful `AccessLog` + failed
    `AccessFailureLog` records keyed by username (capped at
    `SAR_LOGIN_HISTORY_LIMIT=200`).
  - `deletion_requests` — the user's own Art-17 history (lets
    them audit their own erasure choices).
- One private `_sar_<section>` helper per top-level key on
  `GDPRService` so the orchestrator stays readable and each
  section can be unit-tested in isolation. Module-level `_iso()`
  + `_sar_contact_entity()` helpers handle the boilerplate
  (datetime-or-None serialisation; the Reseller→ContactEntity
  nested fields).

**Tests:** `apps/gdpr/tests/test_subject_access_bundle.py` — 14
tests across 11 classes:
- One class per section (`TestAccountSection`, `TestMemberSection`,
  `TestResellerSection`, `TestConsentsSection`,
  `TestCoopSharesSection`, `TestSubscriptionsSection`,
  `TestMemberLoansSection`, `TestChargeSchedulesSection`,
  `TestResellerOrdersSection`, `TestResellerInvoicesSection`)
  verifying the section is populated with the expected fields.
- `TestEmailLogSection` — filters to subject's known addresses
  only, plus a `monkeypatch`-driven truncation test (knocks the
  cap to 2, creates 3 rows, asserts `truncated=True` +
  `total_count=3`).
- `TestLoginHistorySection` — successful + failed records
  surface; other users' rows are filtered out.
- `TestDeletionRequestsSection` — the user's own Art-17 row
  appears in their SAR bundle.
- `TestBundleShapeContract` — exact set of 15 top-level keys,
  every section empty/None for a pure staff user (stable shape
  contract), `format_version` pinned, `subject` block carries
  id + email.

**Acceptance:** ✅ A real SAR is satisfiable from this endpoint
alone — auditor question "show me everything you stored about
member X" answered by `GET /api/gdpr/my-data/` plus a screen
recording.

**Deferred (mentioned in roadmap, NOT shipped this PR):** the
optional ZIP-with-JSON/CSV machine-readable export. The current
JSON response is already a machine-readable bundle; a ZIP wrapper
is purely an ergonomic improvement for users who want one file
per category. Add when an actual SAR forces the question.

### ☐ Step 8 — `DeferredAnonymization` + retention-cron Huey task (LOW, ~3h)

**What:** When `execute_deletion` decides to keep fields under
retention, it writes a `DeferredAnonymization(field, execute_after)`
row. A monthly Huey task walks those rows where `execute_after <= today`
and runs the scrub.

**Where:**
- New model: `DeferredAnonymization`.
- New Huey task: `execute_pending_deferred_anonymizations`.
- Migration.

**Acceptance:** Statutory data from 10+ years ago automatically
becomes anonymized on schedule.

### ☑ Step 9 — Auditlog historical-PII scrub (done 2026-06-12, audit A11)

**Shipped differently than planned:** instead of a one-shot command +
weekly Huey sweep, the scrub runs INSIDE `anonymize_user` (phase 4.5,
`_scrub_auditlog_entries`): every `LogEntry` for the records the
anonymization touched (JasminUser, Member, BillingProfile,
ConsentRecords, Reseller, non-shared ContactEntity, UserInvitations)
gets `changes=None` + `object_repr="[anonymised]"`. The rows stay
("column X changed at time T by actor Y" remains provable); the
old/new values go. Because it's part of `anonymize_user`, the
backup-restore `DeletionLog` replay re-scrubs automatically — no
separate command to remember.

**Test:** `test_member_anonymization.py::test_auditlog_diffs_are_scrubbed`.

**Acceptance (met):** Old auditlog rows no longer leak the name/email
of a deleted member via the `changes` column.

### ☐ Step 10 — Admin endpoint to anonymize OTHER users (LOW, ~1h)

**What:** Office / admin can act on a written deletion request from a
member (e.g. paper form, phone call) — submits via API as the actor,
the subject is identified by user_id.

**Where:**
- New endpoint: `POST /api/gdpr/admin/anonymize-user/<user_id>/`
  (requires IsAdmin).
- Reuses `execute_deletion()`.

**Acceptance:** Member who can't access their own account (e.g.
already locked out) can still have their request honored via admin.

---

## Pattern reference

When in doubt, copy from:
- **Existing GDPR scaffolding** — `apps/gdpr/services.py` (current
  partial impl), `apps/gdpr/models.py::DeletionLog`.
- **Encrypted-field handling** — `apps/shared/super_admin/management/commands/rotate_field_encryption.py`
  (how to iterate and rewrite ciphertext rows in chunks).
- **Per-tenant Huey loops** — `apps/notifications/tasks.py` (the
  proper `for tenant in iterator(): try/except: continue` pattern).
- **Domain errors → HTTP** — `apps/commissioning/errors.py` (`raise SomeError`
  → DRF returns the right code via `core.exception_handler`).

When a step uncovers a sub-task, add it inline to this doc rather
than spawning a new file — keeps the GDPR backlog in one place.
