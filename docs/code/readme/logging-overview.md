# Logging & audit overview

**Owner:** Operations
**Last reviewed:** 2026-05-20
**Next review:** 2027-05-20 (annual)

Single source of truth for what the platform records, where it goes,
and how to add new log calls or audit-tracked models. Audiences:

- **Auditor / DPO** — sections 1, 2, 4. The "what is recorded and where"
  answer.
- **Engineer** — section 3 added: how to wire a new log call, register
  a new model for audit, change the LOGGING config.

Two independent layers run side-by-side, each answering a different
question:

1. **Event logs** — the `.log` files in
   [`jasmin-core/django-core/logs/`](../../jasmin-core/django-core/logs/).
   Append-only text. Records security / auth / business events with
   structured `key=value` lines. Best for *"what happened when, who
   tried what, was it allowed."*
2. **Model audit trail** — `django-auditlog` rows in the per-tenant
   database (`auditlog_logentry`). Records every
   create / update / delete on registered models with the acting user,
   timestamp, and a per-field diff. Best for *"when did this Member's
   IBAN change and who changed it."*

---

## Part 1 — Event logs (`.log` files)

### Where the files live

```
jasmin-core/django-core/logs/
  app.log        — general application events (info-level, low risk)
  auth.log       — authentication & account-management events
  security.log   — anything security-relevant (denied access, lockouts)
```

Each file rotates automatically via `RotatingFileHandler` — 50 MB per
file, 10 (`app.log`) or 20 (`auth.log`, `security.log`) generations.
Old rotations: `app.log.1`, `app.log.2`, … See
[`config/settings.py`](../../jasmin-core/django-core/config/settings.py)
`LOGGING` dict for the canonical config.

### Log line format

```
2026-05-13 15:17:22,479 1e6f712a1ea1 INFO     jasmin.errors         AuthError in user_login_view: ...
```

Shape: `<timestamp> <request_id> <level> <logger-name> <event-name> key=value …`

- `request_id` is an 8-char correlation token injected by
  [`core.middleware.RequestIdMiddleware`](../../jasmin-core/django-core/core/middleware.py)
  and rendered via the matching `RequestIdLogFilter`. It lets you trace
  a single request across every line it emits. Lines emitted outside
  a request (Huey tasks, management commands) get `-`.
- The `thing.what_happened` event-name convention makes events easy
  to grep.

### What goes into `auth.log`

**Login (tenant user)**

```
login.success   user=… tenant=… ip=…
login.failed    reason=invalid_credentials                                     user=… ip=…
login.blocked   reason=pending_approval | pending_invitation
                       | inactive_status | is_active_false                     user=… ip=…
login.error     user=… ip=… error=…
```

**Logout (tenant user)**

```
logout.success                                                                 user=… ip=…
logout.failed   reason=missing_refresh_token | token_error                     user=… ip=…
logout.error    user=… ip=… error=…
```

**JWT refresh**

```
refresh.failed  reason=missing_tenant_claim | tenant_mismatch | token_error    ip=…
refresh.error   ip=… error=…
```

**Profile update**

```
profile.updated         user=… ip=… fields=[…]
profile.update_error    user=… ip=… error=…
```

**Super-admin login / logout / refresh**

```
superadmin.login.success                                                       user=… ip=…
superadmin.login.failed   reason=user_not_found | invalid_password             user=… ip=…
superadmin.login.blocked  reason=inactive                                      user=… ip=…
superadmin.logout.success / .failed                                            user=… ip=…
superadmin.refresh.failed reason=invalid_or_expired | not_superadmin_token     ip=…
```

**Super-admin tenant management (highest-impact actions)**

```
tenant.created         actor=… tenant=… ip=…
tenant.create_failed   actor=… tenant=… ip=… error=…
tenant.updated         actor=… schema=… ip=… fields=[…]
tenant.admin_created   actor=… tenant=… target_user=… target_email=… ip=…
tenant.user_created    actor=… tenant=… target_user=… target_email=… roles=[…] ip=…
user.roles_changed     actor=… tenant=… target_user=… target_email=…
                       before=[…] after=[…] ip=…
```

### What goes into `security.log`

**Authorization** (every denied request hits this)

```
permission.denied  user=… tenant=… roles=[…] required=[…] path=… method=… ip=…
```

**Lockouts** (`django-axes` — after 5 failed attempts in 1 hour)

```
account.locked     user=… ip=…
```

**Invoice hash drift** (nightly check — see
[`../todos/huey-to-do.txt`](../todos/huey-to-do.txt))

```
invoice.hash_drift  tenant=… invoice_id=… prefix=… number=…
```

### What goes into `app.log`

**GDPR** (Art. 15 & 17 — must be logged for accountability)

```
gdpr.data_exported            user=… tenant=… ip=…
gdpr.deletion_executed        user=… user_id=… tenant=… ip=…    (WARNING level)
gdpr.deletion_log_accessed    actor=… tenant=… ip=…
```

**API error envelope** (`jasmin.errors`) — the project-wide DRF exception
handler at
[`core/exception_handler.py`](../../jasmin-core/django-core/core/exception_handler.py)
emits one structured line per error response so any failure that came
out of an API call is recoverable from the file with the same
`request_id` as the originating request:

```
AuthError in user_login_view: Email and password are required
InvalidCredentials in user_login_view: Invalid credentials
```

**Tenant provisioning** (`TenantService` — partial structured shape; the
older event lines are still in f-string format): tenant
create / migration / cleanup events.

**Email send / fail** (`TenantService.email_service`, async email
worker — older f-string format).

### What NEVER to log (GDPR data minimisation, Art. 5(1)(c))

- Plaintext passwords, password-reset tokens, JWT contents, API keys.
- Full request bodies on `/login`, `/register`, `/password-reset`.
- IBAN / SSN / card numbers in plaintext. Mask when needed:
  `DE89 **** **** 0042`.
- Personal data beyond what the event minimally requires.

### Identifying the actor: email vs. user_id

The convention across this codebase is **`user=<email>`** (not `user=<id>`)
on every auth-domain event line. This is deliberate:

  - Operators can grep `auth.log` by email when investigating a user's
    activity, without joining against the user table first.
  - Jasmin's logs are local files (no SaaS aggregation today) rotated at
    50 MB × ≤20 generations — the blast radius of the PII is bounded
    by the container's disk and the rotation window.

This trades the strict DSGVO minimisation guidance ("log the id, not
the row") for operator UX. If logs ever get shipped to a SaaS
aggregator (Loki / Better Stack — see "Not yet implemented" below),
revisit the trade — emails leaving the local container into a
third-party service is a different risk profile.

### How to read the logs

Tail live (inside the container):

```bash
docker compose exec django-core tail -f /app/logs/security.log
```

Find every failed login from one IP:

```bash
grep 'login.failed' logs/auth.log | grep 'ip=1.2.3.4'
```

Find every lockout in the past day:

```bash
grep 'account.locked' logs/security.log | tail -50
```

Find role changes by a super admin (audit who got promoted to admin):

```bash
grep 'user.roles_changed' logs/auth.log
```

Find every GDPR deletion ever:

```bash
grep 'gdpr.deletion_executed' logs/app.log
```

Find invoice tamper attempts (will be empty if all hashes match):

```bash
grep 'invoice.hash_drift' logs/security.log
```

Trace every line of one request:

```bash
grep ' 1e6f712a1ea1 ' logs/*.log
```

---

## Part 2 — Model audit trail (`django-auditlog`)

### What it is

A Django package that hooks into model save / delete signals and writes
every change to `auditlog_logentry`. For each change you get:

- which model + which row (`object_pk`)
- which user did it (`actor` — wired via `AuditlogMiddleware`)
- what changed: a per-field `{old, new}` diff stored as JSON
- the action: `CREATE` / `UPDATE` / `DELETE`
- timestamp + `remote_addr`

This is the *"who changed what, when"* log — separate from the event
logs above. Event logs say *"user X tried to log in"*; auditlog says
*"Member #42's IBAN was changed from `DE12…` to `DE34…` by user X on
2026-05-07 at 09:12"*.

### Why it matters

- **Compliance**: DSGVO Art. 5(2) accountability — you must be able
  to prove what happened to personal data and who did it. GoBD §147 /
  BAO §132 (tax law) require a retrievable change history on
  commercial documents (invoices, delivery notes, orders).
- **Operational**: *"who deleted this subscription?"* *"why is this
  member showing inactive?"* — auditlog answers in seconds.
- **Security**: tamper detection. Every change is recorded, so
  unauthorised modifications stand out.

### Currently registered models — 17 total

All registered in each app's `apps.py` `ready()` method. **All
tenant-scoped** — public-schema models (`Tenant`, `TenantSettings`,
`Domain`, `TenantEmailConfig`, `SuperAdmin`) cannot be audited via
django-auditlog because `LogEntry.actor` has a hard FK to
`settings.AUTH_USER_MODEL` (`accounts.JasminUser`), which lives in
tenant schemas only. See *Still NOT tracked* below for the
workaround currently in use.

#### `apps.commissioning` (14) — see
[`apps/commissioning/apps.py`](../../jasmin-core/django-core/apps/commissioning/apps.py)

##### Member + membership core (6)

| Model | Notes |
|---|---|
| `Member` | Full tracking. The following fields are **masked** in the audit log (the change is recorded, but the raw value is replaced by `******`): `iban`, `email`, `email_2`, `email_3`, `address`, `zip_code`, `city`, `account_owner`, `note`. Minimises PII duplication into the log table while still proving "this field changed". |
| `CoopShare` | Full tracking (financial relevance). |
| `SubscriptionGroup` | Full tracking (the persistent subscription record). |
| `Subscription` | Full tracking (every term, price / quantity / payment-cycle / station change). |
| `ShareDelivery` | Full tracking. **This is where the "joker" audit lives** — `joker_taken` flips are recorded with timestamp and acting user. |
| `PaymentCycle` | Config table; rarely changed, but if someone alters a billing-cycle definition we need to know. |

##### Commercial documents (6) — highest-priority audit targets for tax-law compliance

| Model | Notes |
|---|---|
| `InvoiceReseller` | `document_hash` excluded — it's deterministic from the other fields; logging both would duplicate noise on every mutation. |
| `InvoiceResellerContent` | Line items. |
| `DeliveryNoteReseller` | Same shape as invoice. |
| `DeliveryNoteContent` | Line items. |
| `Order` | Pre-document; part of the audit trail. |
| `OrderContent` | Line items. |

##### Consent versioning (2) — DSGVO Art. 7(1) "demonstrate consent"

| Model | Notes |
|---|---|
| `ConsentDocument` | Append-only by convention. Registered so any post-hoc body edit (which violates the convention) is captured. `body_sha256` excluded — derived from `body`, would duplicate the diff line. |
| `ConsentRecord` | Member ↔ document with IP / user-agent and revocation tail. The audit-relevant table for *"what did this member agree to and when."* |

#### `apps.payments` (3) — see
[`apps/payments/apps.py`](../../jasmin-core/django-core/apps/payments/apps.py)

| Model | Notes |
|---|---|
| `BillingProfile` | SEPA mandate-relevant fields. Per-member billing setup; changes are tax / consent material. |
| `ChargeSchedule` | The "when do we draw" plan. Mutations affect what gets charged and when. |
| `BillingRun` | Per-run execution record. Tracks who ran a billing batch and the state transitions. |

#### Still NOT tracked

- `Tenant`, `TenantSettings`, `Domain`, `TenantEmailConfig`,
  `SuperAdmin` — all five live in the public schema. Adding
  `auditlog` to `SHARED_APPS` was attempted on 2026-05-20 and
  rolled back the same day: `auditlog.LogEntry.actor` is a hard FK
  to `settings.AUTH_USER_MODEL` (`accounts.JasminUser`), which is
  tenant-scoped, so the public-schema table can't be created
  (`relation "accounts_jasminuser" does not exist`).
  `AUTH_USER_MODEL` is global; we can't aim it at `JasminUser` for
  tenants and `SuperAdmin` for public.
  Coverage in the meantime comes from the structured event log
  in `auth.log` — `tenant.created`, `tenant.updated`,
  `tenant.admin_created`, `tenant.user_created`,
  `user.roles_changed` etc. — fine for forensics, NOT a queryable
  per-field diff. To close the gap properly, options are:
  (a) fork django-auditlog and drop the AUTH_USER_MODEL FK, or
  (b) build a small parallel audit table for the public schema
  with signal handlers in `apps/shared/tenants` and
  `apps/shared/super_admin`.

- `JasminUser` — auth-side identity. Role changes are logged via
  the event log (`user.roles_changed`); add a model-level
  registration if you ever need a queryable per-field diff
  (e.g. email address changes by a super-admin).

- `SuperAdminBlacklistedToken` — would have been skipped even if
  the FK problem above didn't exist. It IS itself a revocation
  audit trail (every row is a logout / revocation event);
  wrapping it in another audit layer would just double-log every
  logout.

### How to read the audit trail

**Programmatic** — full history of one Member:

```python
from auditlog.models import LogEntry
from apps.commissioning.models import Member

member = Member.objects.get(member_number=42)
for entry in member.history.all().order_by("-timestamp"):
    print(entry.timestamp, entry.actor, entry.action, entry.changes)
```

**By actor** — every change a given user made:

```python
LogEntry.objects.filter(actor=user)
```

**By action / time**:

```python
LogEntry.objects.filter(
    action=LogEntry.Action.UPDATE,
    timestamp__gte=since,
)
```

**Django admin** — every registered model gets a "History" tab on its
admin change page when admin is enabled.

### Required migration

`django-auditlog` ships its own table (`auditlog_logentry`). It lives
in each **tenant** schema (because `auditlog` is in `TENANT_APPS`):

```bash
python manage.py migrate_schemas --tenant
```

Run this once after deploying. Existing data is NOT back-filled — only
changes made AFTER the migration are recorded.

### Retention

The `auditlog_logentry` table grows monotonically. Current policy
(see [`retention-policy.md`](retention-policy.md)):

- **Keep forever** for now. `LogEntry` rows are small (~1 KiB), high
  audit value, and the generic-FK design means the row's history
  survives even when the row itself is deleted (exactly what tax-audit
  retention needs).
- **Do NOT clear actor reference** when a user is anonymised — the
  actor record is itself audit material. Anonymisation replaces the
  user's PII fields (per `Member.iban` etc. anonymisation rules in the
  retention policy) but leaves the `LogEntry.actor_id` intact, so
  *"user pk=123 made this change"* remains demonstrable.
- **If the table ever crosses ~1 billion rows**, add an index on
  `(timestamp DESC, content_type_id)` first; only after that, write a
  Huey periodic task ([`../todos/huey-to-do.txt`](../todos/huey-to-do.txt))
  that deletes entries older than the relevant legal window (10 years
  for invoice-linked rows, shorter for everything else). **Do not
  Celery — this project uses Huey** (already running in
  docker-compose).

---

## Part 3 — Engineering howto

For when you're adding a new event or registering a new model.

### Named loggers (configured in `LOGGING`)

Use `logging.getLogger("<name>")` with one of these. They map to
handlers — see
[`config/settings.py`](../../jasmin-core/django-core/config/settings.py)
`LOGGING` for authoritative routing.

| Logger | Use for | Routes to |
|---|---|---|
| `authentication` | Login attempts, JWT issuance / refresh / logout, profile updates | `auth.log` + console |
| `authz` | Permission denials, role-check failures | `security.log` + console |
| `super_admin` | Anything done by a super-admin (tenant CRUD, role grants) | `auth.log` + console |
| `axes` | `django-axes` lockout events (the package itself logs here) | `security.log` + console |
| `gdpr` | Data exports, deletion requests, anonymisation | `app.log` + console |
| `payments` | Invoicing, charge schedules, billing runs | `app.log` + console |
| `tenants` | Tenant lifecycle (create / suspend / delete / migrate) | `app.log` + console |
| `tasks` | Huey background jobs (start / finish / error) | `app.log` + console |
| `jasmin.errors` | Project-wide DRF exception handler — do not call directly; use `raise JasminError(...)` and the handler logs it. | `app.log` + console |
| `apps.shared.tenants` | Tenants app's own internal messages | `app.log` + console |
| `django.security` | Django's built-in security events | `security.log` + console |
| `django.request` | Django request-cycle warnings | `app.log` + console |

### Adding a new log line

```python
import logging
logger = logging.getLogger("authentication")  # or one of the names above

logger.info(
    "login.failed user=%s ip=%s reason=%s",
    user_id_or_email,
    ip,
    "invalid_credentials",
)
```

Conventions:

- Event name first, key=value pairs after. Stick to the
  `thing.what_happened` shape so grep recipes keep working.
- Include `user=` and `ip=` (or `actor=` for super-admin actions)
  whenever the event involves identity.
- Use `WARNING` for failures that point at the user's input
  (`login.failed`); `ERROR` for unexpected backend failures
  (`login.error`).
- Never log payload bodies or secrets — see *"What NEVER to log"* in
  Part 1.

### Registering a new model for the audit trail

Edit the relevant app's `apps.py` `ready()` method:

```python
def ready(self) -> None:
    from auditlog.registry import auditlog
    from .models import MyModel

    auditlog.register(
        MyModel,
        # Optional knobs — use sparingly:
        mask_fields=["iban", "email"],          # value replaced by ******
        exclude_fields=["document_hash"],       # field skipped entirely
    )
```

Then create a migration only if `MyModel` lives in a tenant app for
the first time (the `auditlog_logentry` table is per-schema):

```bash
poetry run python manage.py migrate_schemas --tenant
```

Bias toward `mask_fields` over `exclude_fields` for PII — the
record-that-something-changed value is preserved, only the raw value
is hidden. `exclude_fields` is right for derived columns (hashes,
denormalised totals) where the diff line would just be noise.

### Changing the `LOGGING` dict

The dict lives in
[`config/settings.py`](../../jasmin-core/django-core/config/settings.py).
When adding a new logger, mirror the existing pattern:

```python
"my_new_logger": {
    "handlers": ["app_file", "console"],
    "level": "INFO",
    "propagate": False,
},
```

Always set `propagate: False` so messages don't double-log via Django's
root logger. Keep new files routed through `app_file` unless the events
are security-relevant (`security_file`) or strictly auth-domain
(`auth_file`).

---

## Part 4 — Quick reference: where do I look?

| I want to know … | Look at |
|---|---|
| Who tried to log in (success / fail) | `logs/auth.log` |
| Who got locked out | `logs/security.log` |
| Who was denied access to a view | `logs/security.log` |
| Whether any invoice was tampered with | `logs/security.log` (grep `invoice.hash_drift`) |
| Who created / updated / deleted a tenant | `logs/auth.log` |
| Who changed a TenantSettings field | `logs/auth.log` (`tenant.updated` line for now — no queryable diff; see *Still NOT tracked*) |
| Who created / disabled a SuperAdmin account | `logs/auth.log` (`tenant.admin_created`, `user.roles_changed`) |
| Who changed someone's roles | `logs/auth.log` (`user.roles_changed`) |
| Who exported / deleted personal data | `logs/app.log` |
| Why an API call returned an error to the client | `logs/app.log` (`jasmin.errors`, by `request_id`) |
| Who changed a Member's address / IBAN | auditlog (DB) + `Member.history` |
| Joker history for a delivery | auditlog (DB) + `ShareDelivery.history` |
| When a subscription was cancelled | auditlog (DB) + `Subscription.history` |
| Who edited a finalized invoice (should be nobody) | auditlog (DB) + `InvoiceReseller.history` |
| What consent text a member agreed to | `ConsentRecord` (via `document` FK) — see [`data-inventory.md`](data-inventory.md) §Consent versioning |
| SEPA mandate / billing-profile changes | auditlog (DB) + `BillingProfile.history` |
| Who ran a billing batch | auditlog (DB) + `BillingRun.history` |
| Business decisions (offers, choices, etc.) | `logs/app.log` + service logs |

---

## Not yet implemented

These are referenced occasionally in other docs but are NOT live in
this codebase:

- **Sentry / GlitchTip** — no DSN is wired. Unhandled exceptions are
  captured by `jasmin.errors` into `app.log` only.
- **Centralized logs** (Loki / Better Stack) — the JSON formatter is
  stubbed in `LOGGING["formatters"]` but commented out.
- **OS-level `logrotate`** — file rotation today is handled in-process
  by `RotatingFileHandler`. A `logrotate.d/jasmin` config can be added
  later as belt-and-braces.

When any of these land, update this doc and the engineering section in
particular.
