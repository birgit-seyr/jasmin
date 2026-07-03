# Personal data inventory

**Owner:** Operations
**Last reviewed:** 2026-05-20
**Next review:** 2027-05-20 (annual)
**Companion docs:** [`retention-policy.md`](./retention-policy.md), [`AUDIT_CHECKLIST.txt`](./AUDIT_CHECKLIST.txt)

This inventory lists every database **field** that holds personal
data, the **legal basis** under DSGVO/GDPR Art. 6(1) for processing
it, and the **retention window** that applies. It is the field-level
counterpart to the activity-level **VVT** (Verzeichnis von
Verarbeitungstätigkeiten, Art. 30) — both documents exist for
different audit questions:

- *"What data do you hold, and on what legal basis?"* — this file.
- *"What processing activities do you perform?"* — VVT (to be written; see [`tasks.txt`](./tasks.txt)).

Models in apps marked "ignored for now" in `CLAUDE.md`
(cultivation / economics / staff / gdpr) are out of scope; they
hold no member PII at the field level.

## Legend

| Legal basis | DSGVO article | Used for |
|---|---|---|
| **Contract** | Art. 6(1)(b) | Membership contract performance — delivery, billing, scheduling |
| **Legal obligation** | Art. 6(1)(c) | Tax law (GoBD §147 / BAO §132 — 10y invoice retention) |
| **Legitimate interest** | Art. 6(1)(f) | Security, fraud prevention, technical audit logs |
| **Consent** | Art. 6(1)(a) | Optional comms, secondary contact channels |

| Retention window | Source |
|---|---|
| Membership + 10y | Mirrors invoice retention (tax law) — see [retention-policy.md §1](./retention-policy.md) |
| 10y from end of fiscal year | GoBD §147 / BAO §132 — finalized commercial documents |
| 90d rolling | Operational logs |
| 1y rolling | Security / auth logs |
| Forever | Audit trail (small rows, high evidentiary value) |
| Until revoked | Optional consents (e.g. marketing) |

---

## `accounts.JasminUser`

Authentication root. Lives in **tenant** schemas. One row per
person who has a login.

| Field | Category | Purpose | Legal basis | Retention | Notes |
|---|---|---|---|---|---|
| `username` | Identification | Login identifier | Contract | Membership + 10y | Often = email, but stored separately |
| `first_name`, `last_name` | Identification | Personalisation, display in UI / emails | Contract | Membership + 10y | Indexed for search |
| `email` | Contact | Login + transactional emails | Contract | Membership + 10y | Unique, indexed |
| `avatar` | Identification (image) | Optional profile picture | Consent | Until revoked or membership end | Uploaded by user |
| `last_login_ip` | Auth / security | Forensic value if account is compromised | Legitimate interest | 1y rolling (rotated on each login) | Stored as `GenericIPAddressField` |
| `roles` (JSON) | Identification | Authorisation — what the user may do | Contract | Membership + 10y | Functional, not PII per se |
| `account_status`, `activated_at`, `inactivated_at` | Membership | Account lifecycle | Contract | Forever (audit trail) | Drives the offboarding flow |
| `password` (Django auth) | Auth | Login credential | Contract | Membership + 10y | Hashed (Argon2 / PBKDF2 — never plaintext) |

---

## `commissioning.Member`

The CSA-membership record. One per natural-or-legal person who buys
shares. Most PII concentrates here.

| Field | Category | Purpose | Legal basis | Retention | Notes |
|---|---|---|---|---|---|
| `member_number` | Identification | Stable human-readable ID; appears on every invoice | Contract / Legal obligation | Forever (audit trail) | Unique sequence; the same number is referenced from `ChargeSchedule`, `Invoice`, etc. |
| `company_name`, `first_name`, `last_name` | Identification | Display, invoice header, salutation | Contract | Membership + 10y | Composite index on `(last_name, first_name)` for search |
| `pickup_name` | Identification (third party) | Person collecting the share on behalf of the member | Contract | Membership + 10y | Free-text |
| `address`, `zip_code`, `city`, `country` | Contact | Delivery routing, invoice address | Contract | Membership + 10y | |
| `email`, `email_2`, `email_3` | Contact | Notifications, invoice delivery | Contract (primary); Consent (secondary) | Membership + 10y | Primary `email` is unique + indexed |
| `iban` | Financial | SEPA Direct Debit | Contract | Membership + 10y | **Encrypted at rest** (Fernet via `django-encrypted-model-fields`) |
| `account_owner` | Financial | Named bank-account holder when ≠ member | Contract | Membership + 10y | **Encrypted at rest** |
| `is_active`, `is_trial`, `is_cancelled`, `is_student` | Membership | Membership status | Contract | Membership + 10y | |
| `entry_date` | Membership | When membership started | Contract / Legal obligation | Forever | |
| `number_of_rates` | Membership | Payment frequency preference | Contract | Membership + 10y | |
| `sepa_consent`, `privacy_consent`, `withdrawal_consent` | Consent record | Denormalised "latest consent" cache | Contract + Consent | Forever | Canonical record lives in `ConsentRecord`; these are the hot-path cache |
| `note` | Operational | Office-side free-text notes about the member | Legitimate interest | Membership + 10y | Could contain incidental PII — *do not* paste verbatim case notes here for special-category data |

### `commissioning.UserInvitation`

| Field | Category | Purpose | Legal basis | Retention | Notes |
|---|---|---|---|---|---|
| `email` | Contact | Where the invite was sent | Contract | Until accepted or expired (≤30d after `expires_at`) | |
| `token` (UUID) | Auth | One-time invite secret | Contract | Same as row | |

---

## `commissioning.ContactEntity`

Reseller / delivery-station contact information. **Not member PII**,
but Art. 4(1) DSGVO covers natural persons identifiable through a
business contact, so we treat the data accordingly.

| Field | Category | Purpose | Legal basis | Retention | Notes |
|---|---|---|---|---|---|
| `company_name`, `first_name`, `last_name`, `acronym` | Identification | Display, invoice header | Contract | While business relationship + 10y | |
| `address`, `zip_code`, `city`, `country` | Contact | Delivery routing, invoice address | Contract | Same | |
| `coords_lon`, `coords_lat` | Location | Tour planning | Contract | Same | Derived from address; not user-submitted |
| `email`, `email_2`, `email_3`, `order_email` | Contact | Notifications, order forms | Contract | Same | |
| `phone`, `phone_2`, `phone_3`, `fax` | Contact | Telephony, fax | Contract | Same | |
| `uid` | Identification | VAT number — required on B2B invoices | Legal obligation | 10y from end of fiscal year | Public-ish (printed on every invoice) |
| `iban` | Financial | Outgoing payments to suppliers, reseller credits | Contract | While business relationship + 10y | **Encrypted at rest** |

---

## `commissioning.ConsentDocument` / `ConsentRecord`

The audit trail for what each member agreed to and when. Both
tables are append-only by design.

| Field | Category | Purpose | Legal basis | Retention | Notes |
|---|---|---|---|---|---|
| `ConsentRecord.member` (FK) | Identification | Link the consent to a person | Contract + Legal obligation | Forever | Even after Member anonymisation; the record itself stays as proof |
| `ConsentRecord.document` (FK) | Audit | Which version of the policy was shown | Legal obligation | Forever | Backs Art. 7(1) "demonstrate consent" |
| `ConsentRecord.consented_at`, `revoked_at` | Audit | When | Legal obligation | Forever | |
| `ConsentRecord.ip_address`, `user_agent` | Auth / security | Anti-repudiation: prove it was the member, not staff | Legitimate interest | Forever (paired with the consent) | Optional — staff-recorded paper consents have NULL here |
| `ConsentDocument.body`, `body_sha256` | Audit | The text the member saw | Legal obligation | Forever | Append-only by convention; SHA-256 detects post-hoc edits |

---

## `payments.BillingProfile`

Per-member SEPA mandate record. One per `Member`.

| Field | Category | Purpose | Legal basis | Retention | Notes |
|---|---|---|---|---|---|
| `iban` | Financial | Direct-debit collection | Contract | Membership + 10y | **Encrypted at rest** |

| `account_holder` | Financial | Named bank-account holder | Contract | Same | **Encrypted at rest** |
| `sepa_mandate_reference` | Financial / audit | SEPA scheme requirement on every debit | Legal obligation (SEPA Rulebook) | 14 months past last debit (SEPA chargeback window) + invoice retention | Plaintext intentionally — `unique=True` would be silently broken by Fernet's random IV |
| `sepa_mandate_signed_at` | Audit | Mandate validity | Legal obligation | Same | |
| `sepa_mandate_first_use_at` | Operational | Drives FRST→RCUR sequence type | Legal obligation | Same | |
| `notes` | Operational | Office-side free-text | Legitimate interest | Membership + 10y | |

---

## `notifications.EmailLog`

Operational record of every email sent.

| Field | Category | Purpose | Legal basis | Retention | Notes |
|---|---|---|---|---|---|
| `recipient` | Contact | Delivery target | Contract | 90 days rolling (see [`huey-to-do.txt`](./huey-to-do.txt) §"Stale email_log cleanup") | Indexed |
| `subject`, `template`, `purpose` | Comms | What was sent + why | Contract | 90 days | |
| `provider_message_id` | Audit | External reference (e.g. SendGrid) | Legitimate interest | 90 days | |
| `error` | Audit | Failure reason | Legitimate interest | 90 days | |
| `related_object_type`, `related_object_id` | Audit | Link back to the invoice / membership event | Legitimate interest | 90 days | Indexed |
| `created_at`, `sent_at`, `delivered_at` | Audit | Delivery confirmation | Legitimate interest | 90 days | |

The full **body** of each email is NOT persisted on `EmailLog` —
only the metadata above. The template lives in `EmailTemplate`
(append-only versioned via the audit log) so the historical body
can be reconstructed.

---

## Per-tenant cross-cutting tables

### `auditlog.LogEntry` (django-auditlog)

Lives in each **tenant** schema. Captures every change to the 14
registered models (see [`AUDIT_CHECKLIST.txt`](./AUDIT_CHECKLIST.txt) §"Audit trail").

| Field | Category | Purpose | Legal basis | Retention | Notes |
|---|---|---|---|---|---|
| `actor_id` (FK to JasminUser) | Audit | Who made the change | Legitimate interest | Forever | Survives Member deletion via NULLing (the user's display value goes; the change record stays) |
| `remote_addr` | Auth / security | Forensic value | Legitimate interest | Forever | `GenericIPAddressField` |
| `changes` (JSON) | Audit | Field-level before/after | Legitimate interest | Forever | Sensitive fields are listed in `mask_fields` on the registration call (e.g. `Member.iban`, `email`, `address` — see `apps/commissioning/apps.py`) so the raw values never reach `LogEntry.changes` |
| `timestamp` | Audit | When | Legitimate interest | Forever | |

### `axes.AccessAttempt` (django-axes)

Failed-login + lockout tracking, used for brute-force protection.

| Field | Category | Purpose | Legal basis | Retention | Notes |
|---|---|---|---|---|---|
| `ip_address` | Auth / security | Brute-force lockout key | Legitimate interest | 1y rolling | |
| `username` | Auth / security | Attempted login (often = email) | Legitimate interest | 1y rolling | |
| `user_agent` | Auth / security | Forensic | Legitimate interest | 1y rolling | |
| `attempt_time` | Auth / security | Rate-limit window | Legitimate interest | 1y rolling | |

---

## Special-category data (Art. 9)

**None stored.** The platform does not record:

- Health / dietary-restriction data (allergies/preferences are not persisted)
- Religious or political affiliation
- Race / ethnic origin
- Sexual orientation
- Trade-union membership
- Biometric / genetic data

If a future feature crosses into Art. 9 territory (e.g. "allergies"
on Member to support special baskets), a DPIA per Art. 35 is
required *before* the model migration ships.

---

## Encryption at rest

These columns are stored as Fernet ciphertext via
`django-encrypted-model-fields`:

- `Member.iban`, `Member.account_owner`
- `ContactEntity.iban`
- `BillingProfile.iban`, `.account_holder`
- `TenantEmailConfig.api_key`, `.smtp_password` (credentials, not member PII — but same mechanism)

Consequence the inventory has to acknowledge: encrypted columns
**cannot be filtered by plaintext value** (`Model.objects.filter(iban=...)` matches zero rows). Any code that needs lookup by IBAN must go via the parent FK (`Member` / `BillingProfile`).

## Rights of the data subject

| Right | Endpoint / mechanism |
|---|---|
| **Art. 15 — Access** | `GET /api/gdpr/my-data/` (see [`AUDIT_CHECKLIST.txt`](./AUDIT_CHECKLIST.txt) §"Art. 15"). Member portal also exposes `MemberConsentsCard` for the consent subset. |
| **Art. 16 — Rectification** | Member can edit their own profile (`PATCH /api/commissioning/members/{self}/`); office staff can edit any. |
| **Art. 17 — Erasure** | `GDPRService` deletion logic + `DeletionLog` audit trail. See [`AUDIT_CHECKLIST.txt`](./AUDIT_CHECKLIST.txt) §"Art. 17". Tax-law retention overrides erasure for invoice-linked PII (anonymise instead — task pending, see [`huey-to-do.txt`](./huey-to-do.txt)). |
| **Art. 7(3) — Withdraw consent** | `POST /api/commissioning/consents/{id}/revoke/` (and `MemberConsentsCard` in the UI). |
| **Art. 20 — Portability** | Same as Art. 15 access — `my-data/` returns the full JSON. |

## When to update this file

- A new field that holds personal data is added to any model.
- A retention window changes (cross-check with `retention-policy.md`).
- A new processing purpose is introduced (cross-check with VVT, when that document exists).
- An auditor / DPA request — at minimum re-confirm the "Last reviewed" date.
