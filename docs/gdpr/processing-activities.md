# Record of Processing Activities (Verzeichnis von Verarbeitungstätigkeiten)

**Legal basis:** GDPR Art. 30
**Status:** Template — each tenant fills in its own copy
**Last reviewed:** 2026-06-02

Art. 30 requires every data controller to maintain a written record
of all processing activities. This document is the per-tenant
template that maps the Jasmin platform's data flows to the Art. 30
schema. The codebase columns / endpoints / retention rules are
factual (extracted from this repo on 2026-06-02). The fields marked
`[fill in]` are tenant-specific operational data.

---

## 1. Controller (Verantwortlicher)

| Field                       | Value          |
|-----------------------------|----------------|
| Organisation name           | [fill in]      |
| Legal form                  | [fill in]      |
| Registered address          | [fill in]      |
| Contact email               | [fill in]      |
| Contact phone               | [fill in]      |
| Data-protection contact     | [fill in]      |
| DPO (if appointed)          | [fill in / na] |
| Supervisory authority       | [fill in]      |

These fields are already stored on `Tenant` (`name`, `address`,
`zip_code`, `city`, `country`, `email`, `phone_number`) and surface
in the public privacy-policy template. Keep them in sync.

---

## 2. Joint Controllers / Processors (Art. 26 / Art. 28)

| Role                       | Party              | Contract on file |
|----------------------------|--------------------|------------------|
| Hosting / Infrastructure   | [fill in]          | [AVV yes/no]     |
| Email delivery (Anymail)   | SendGrid (default) | [AVV yes/no]     |
| Payment / SEPA             | [fill in]          | [AVV yes/no]     |
| Error monitoring           | Sentry (optional)  | [AVV yes/no]     |
| Backup storage             | [fill in]          | [AVV yes/no]     |

See [avv-template.md](avv-template.md) for the AVV template you sign
WITH your sub-processors AND, if you host this platform for OTHER
Solawis, the AVV THEY sign with you.

---

## 3. Processing Activities

Each activity is one row in the public-facing Verzeichnis. The codebase
implements all of them — paths refer to `apps/` packages.

### 3.1 Member registration & onboarding

| Field                       | Value                                                                                                                              |
|-----------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| Purpose                     | Onboarding new cooperative members; KYC; consent capture                                                                           |
| Legal basis                 | Art. 6(1)(b) contract performance; Art. 6(1)(c) GenG §15                                                                           |
| Categories of data subjects | Applicants, members                                                                                                                |
| Categories of personal data | Name, address, email, phone, birth date, IBAN, account_owner, optional company name, optional VAT id                               |
| Source                      | Self-submitted via the public registration wizard                                                                                  |
| Recipients                  | Office staff (role `office`); admin users (role `admin`)                                                                           |
| Third-country transfers     | None                                                                                                                               |
| Retention                   | Active membership + 10 years post-cancellation (GenG §31); then anonymisation                                                      |
| Security measures           | Field-level encryption for IBAN; TLS in transit; per-tenant schema isolation; role-based access; auditlog on writes; rate-limiting |
| Code locations              | `apps/accounts/`, `apps/commissioning/`, `apps/authz/`                                                                             |

### 3.2 SEPA Direct Debit billing

| Field                       | Value                                                                                                                |
|-----------------------------|----------------------------------------------------------------------------------------------------------------------|
| Purpose                     | Collecting contributions and equity payments                                                                         |
| Legal basis                 | Art. 6(1)(b) contract; Art. 6(1)(c) HGB §257 / AO §147 (invoice retention)                                           |
| Categories of data subjects | Members, resellers                                                                                                   |
| Categories of personal data | IBAN, BIC (derived), account_owner, mandate reference, mandate signature date, charge schedule, invoice history      |
| Source                      | Member self-edit via Profile › Meine Daten; office edit via member detail page                                       |
| Recipients                  | Office staff; SEPA service provider (if any)                                                                         |
| Retention                   | 10 years per HGB §257 (1) Nr. 4; mandates plus 14 months after last debit per SEPA rulebook                          |
| Security measures           | `django-encrypted-fields` for IBAN at rest; mandate stored separately; auditlog                                      |
| Code locations              | `apps/payments/`                                                                                                     |

### 3.3 Communication (transactional + bulk email)

| Field                       | Value                                                                                                                |
|-----------------------------|----------------------------------------------------------------------------------------------------------------------|
| Purpose                     | Transactional notifications (invoices, deliveries, consent confirmations); operational announcements                 |
| Legal basis                 | Art. 6(1)(b) contract for transactional; Art. 6(1)(a) consent for non-transactional bulk                             |
| Categories of data subjects | Members, customers, resellers                                                                                        |
| Categories of personal data | Name, email, message content, send-time metadata                                                                     |
| Source                      | Triggered by platform events                                                                                         |
| Recipients                  | Anymail provider (SendGrid by default)                                                                               |
| Retention                   | EmailLog: 2 years; then purge                                                                                        |
| Security measures           | TLS to provider; provider has own AVV (DPA); EmailLog scrubs subject + recipient on member anonymisation             |
| Code locations              | `apps/notifications/`                                                                                                |

### 3.4 Login + access logging

| Field                       | Value                                                                                                                |
|-----------------------------|----------------------------------------------------------------------------------------------------------------------|
| Purpose                     | Authentication; brute-force protection (Art. 32 security); audit-trail (Art. 5(2) accountability)                    |
| Legal basis                 | Art. 6(1)(f) legitimate interest in platform security                                                                |
| Categories of data subjects | All authenticated users                                                                                              |
| Categories of personal data | Username, IP, user-agent, success/failure, timestamp                                                                 |
| Source                      | Auto-captured by `django-axes` + auditlog                                                                            |
| Recipients                  | Office staff (read-only)                                                                                             |
| Retention                   | django-axes: per platform config; auditlog: same as member retention                                                 |
| Security measures           | JWT auth; rate limiting on /login (20/min) + /register (10/h); axes lockout                                          |
| Code locations              | `apps/accounts/`, `apps/authz/`                                                                                      |

### 3.5 Member-rights workflows (GDPR Art. 15 / 16 / 17 / 20)

| Field                       | Value                                                                                                                |
|-----------------------------|----------------------------------------------------------------------------------------------------------------------|
| Purpose                     | Fulfilling data-subject rights                                                                                       |
| Legal basis                 | Art. 6(1)(c) legal obligation                                                                                        |
| Categories of data subjects | Members, customers, resellers                                                                                        |
| Categories of personal data | Full subject access bundle (everything the user touched); deletion-request metadata; DeletionLog audit row           |
| Source                      | User initiates via Profile › Meine Daten                                                                             |
| Recipients                  | The requesting user; office staff approving / rejecting                                                              |
| Retention                   | SAR exports: not retained — generated on-demand. DeletionLog rows: indefinitely (regulator-facing accountability)    |
| Security measures           | Two-step deletion with admin gate; rate-limiting (2/h SAR, 5/h request-deletion, 10/min confirm)                     |
| Code locations              | `apps/gdpr/`                                                                                                         |

---

## 4. Technical & Organisational Measures (Art. 32)

Concrete platform measures that satisfy Art. 32 — all already in code:

- **In transit:** TLS via gateway nginx + Let's Encrypt wildcard
  (see [https-deploy-runbook.md](https-deploy-runbook.md))
- **At rest:** PostgreSQL with `django-encrypted-fields` for IBAN,
  signed JWTs, hashed passwords (Django default + zxcvbn validator)
- **Access control:** role-based (`member` / `office` / `admin`);
  per-tenant schema isolation prevents cross-tenant reads
- **Audit:** `django-auditlog` on writes; throttle-scope enforcement
  via class attribute (2026-06 fix in `apps/accounts/views.py` and
  `apps/gdpr/views.py`)
- **Backups:** AES-256 GPG-encrypted `pg_dump`; restore replays the
  `DeletionLog` so anonymised PII doesn't resurrect
- **Brute-force protection:** `django-axes` lockout + per-endpoint
  throttle scopes
- **Honeypot field on registration:** silent drop on bot fills

---

## 5. Review schedule

This document is reviewed at least once per year and after every
material change to the data flows (new sub-processor, new column
holding personal data, new role with PII access). Each review
appends a row below.

| Date       | Reviewer       | Notes                          |
|------------|----------------|--------------------------------|
| 2026-06-02 | Initial draft  | Extracted from codebase state  |
