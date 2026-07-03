# Auftragsverarbeitungsvertrag (AVV) Template

**Legal basis:** GDPR Art. 28
**Status:** Starting-point template — must be reviewed by a lawyer
before use in production. The text below maps Art. 28 requirements
to the Jasmin platform's actual data flows so the legal review has
something concrete to react to.
**Last reviewed:** 2026-06-02

---

## When you need this

You need an AVV whenever **another party processes personal data
on your behalf**. Two common shapes:

### Shape A — you (platform host) → tenant (Solawi)

You operate the Jasmin platform and host it for one or more Solawi
cooperatives. In this configuration:

- The Solawi is the **controller** (Verantwortlicher) of its
  members' data
- You are the **processor** (Auftragsverarbeiter)
- The Solawi is your customer; YOU sign this AVV with THEM

You do not need an AVV with a Solawi that self-hosts the platform
for its own members — in that case the Solawi is both controller
and processor of itself, and Art. 28 does not apply.

### Shape B — you (controller) → upstream services

You use third-party services that touch personal data on your
behalf:

- Hosting / IaaS provider
- Email delivery (SendGrid via Anymail)
- Payment processing
- Error monitoring (Sentry)
- Backup storage

Each of these needs its own AVV. Most major providers publish a
DPA you can sign electronically (e.g. SendGrid, Sentry). Keep
signed copies on file under `docs/gdpr/avv/` (gitignored).

---

## What the AVV must contain (Art. 28(3))

The contract MUST set out, in writing:

1. The subject-matter and duration of the processing
2. The nature and purpose of the processing
3. The type of personal data and categories of data subjects
4. The obligations and rights of the controller
5. That the processor will only process on documented instructions
   from the controller
6. That persons authorised to process the data are bound by
   confidentiality
7. That the processor takes all measures required by Art. 32
   (security)
8. Conditions for engaging sub-processors (Art. 28(2) and (4))
9. The processor's obligation to assist the controller in
   responding to data-subject requests
10. The processor's obligation to assist with Art. 32-36
    compliance (security, breach notification, DPIA)
11. What happens to the data at end of contract (return or delete)
12. That the processor will make available all information needed
    to demonstrate compliance with Art. 28, and allow audits

The template below has one section per item.

---

## Template body (fill in `[brackets]`)

### Preamble

This Data Processing Agreement ("DPA" / "AVV") is entered into
between:

- **Controller:** [Solawi legal name], [legal form], represented
  by [name], registered at [address] ("the Controller")
- **Processor:** [your legal name], [legal form], represented by
  [name], registered at [address] ("the Processor")

(For Shape B, swap the roles: you become the Controller and the
sub-processor becomes the Processor.)

This DPA supplements the underlying Service Agreement dated
[date] under which the Processor provides the Jasmin platform to
the Controller.

### §1 Subject-matter, nature, purpose, duration

The Processor processes personal data on the Controller's behalf
to provide a multi-tenant member-management platform for the
Controller's Solawi (CSA) operation. Specific functions:

- Member registration, KYC, consent management
- Cooperative-share equity tracking (GenG §30 / §31)
- SEPA Direct Debit billing and invoice generation
- Transactional communication (email)
- Member-rights workflows (GDPR Art. 15 / 16 / 17 / 20)

The DPA runs for the duration of the underlying Service Agreement.

### §2 Types of personal data and categories of data subjects

| Category of subject | Categories of data                                                              |
|---------------------|---------------------------------------------------------------------------------|
| Applicants          | Name, address, email, phone, birth date, consent records                        |
| Members             | All applicant fields + IBAN, account_owner, mandate data, equity history        |
| Customers           | Name, address, contact details, order + delivery history                        |
| Resellers           | Business name, contact, banking, order history                                  |
| Office staff        | User account, role, access logs                                                 |

Full inventory: see
[processing-activities.md](processing-activities.md).

### §3 Processing only on documented instructions

The Processor processes personal data only on the Controller's
documented instructions, unless required to do so by Union or
Member State law. The Processor informs the Controller of any
such legal requirement before processing, unless that law
prohibits such information on grounds of public interest.

The Service Agreement and this DPA together constitute the
documented instructions. Additional instructions require written
form (email suffices).

### §4 Confidentiality

The Processor ensures that all persons authorised to process the
personal data have committed themselves to confidentiality or are
under an appropriate statutory obligation of confidentiality.

The Processor maintains an internal access-control matrix (role
`office`, `admin`, `member`) and enforces it at the application
and database level (per-tenant schema isolation; role-based DRF
permissions).

### §5 Security measures (Art. 32)

The Processor implements appropriate technical and organisational
measures, including:

- **Encryption in transit:** TLS 1.2+ via gateway nginx
- **Encryption at rest:** `django-encrypted-fields` for IBAN
- **Pseudonymisation:** N/A in the application layer; data is
  identifiable by design (members must be reachable)
- **Confidentiality:** role-based access; per-tenant schema
  isolation
- **Integrity:** auditlog on all writes; signed JWTs
- **Availability:** AES-256 GPG-encrypted backups (daily) with
  DeletionLog replay on restore
- **Resilience:** containerised deployment with health checks
- **Regular testing:** pytest + ESLint + automated CI on every
  push (`.github/workflows/ci.yml`)
- **Brute-force protection:** `django-axes` lockout + per-endpoint
  rate limits

Detailed measures: see §4 of
[processing-activities.md](processing-activities.md).

### §6 Sub-processors

The Controller grants the Processor general written authorisation
to engage sub-processors, subject to the conditions below.

Current sub-processors:

| Sub-processor       | Purpose             | Country   |
|---------------------|---------------------|-----------|
| [Hosting provider]  | IaaS                | [country] |
| SendGrid (Anymail)  | Email delivery      | USA       |
| [Payment processor] | SEPA execution      | [country] |
| Sentry (optional)   | Error monitoring    | USA       |
| [Backup storage]    | Offsite backups     | [country] |

The Processor informs the Controller of any intended changes
to the sub-processor list with at least 30 days' notice. The
Controller may object in writing; if no agreement is reached the
Controller may terminate the underlying Service Agreement.

Where a sub-processor is in a third country (USA, etc.) the
Processor ensures appropriate transfer safeguards (SCCs or
equivalent) are in place.

### §7 Assistance with data-subject rights

The Processor assists the Controller in responding to data-subject
requests under Articles 15-22 by providing the technical means
to do so:

- The platform's built-in Subject Access bundle endpoint
  (`GET /api/gdpr/my-data/`) covers Art. 15 and 20
- The self-service edit screens (`Profile › Meine Daten`) cover
  Art. 16
- The two-step deletion flow with admin gate covers Art. 17

Where a request cannot be served by these built-in tools, the
Processor responds to written requests from the Controller within
five working days.

### §8 Assistance with security and breach notification

The Processor notifies the Controller without undue delay (and in
any case within **24 hours**) of becoming aware of a personal
data breach affecting the Controller's data. The notification
contains the information listed in Art. 33(3).

The Processor follows
[breach-runbook.md](breach-runbook.md) for breach handling.

### §9 End of contract

Upon termination of the underlying Service Agreement, at the
Controller's choice the Processor:

(a) returns all personal data to the Controller in an open
    machine-readable format and deletes all copies, or
(b) deletes all personal data unless Union or Member State law
    requires further storage.

Backup tapes containing the data are retained for the standard
backup-retention period (currently 90 days) then destroyed; the
Controller is informed of the final destruction date.

The DeletionLog audit-trail rows that **do not contain personal
data** (admin id, timestamp, request id) are retained indefinitely
as required for Art. 5(2) accountability.

### §10 Audits

The Processor makes available all information necessary to
demonstrate compliance with Art. 28 and allows for and contributes
to audits, including inspections, conducted by the Controller or
an auditor mandated by the Controller.

Audits are scheduled with at least 14 days' notice and conducted
during business hours. Where the Processor's compliance can be
demonstrated by certifications (ISO 27001, SOC 2) or attestations,
those are provided in lieu of on-site audit.

### Signatures

| Controller            | Processor             |
|-----------------------|-----------------------|
| Name: [fill in]       | Name: [fill in]       |
| Position: [fill in]   | Position: [fill in]   |
| Date:                 | Date:                 |
| Signature:            | Signature:            |

---

## Review schedule

| Date       | Reviewer       | Notes                          |
|------------|----------------|--------------------------------|
| 2026-06-02 | Initial draft  | Mapped Art. 28 to repo state   |
