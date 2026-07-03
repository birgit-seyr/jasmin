# Data Protection Impact Assessment — Decision Record

**Legal basis:** GDPR Art. 35
**Status:** Assessed; DPIA **not required** for current processing
**Last reviewed:** 2026-06-09

Art. 35(1) obliges the controller to carry out a Data Protection
Impact Assessment **only when a type of processing is likely to
result in a high risk to the rights and freedoms of natural
persons**. Art. 35(3) gives three non-exhaustive triggers, and the
EDPB / national supervisory authorities publish lists of further
triggers ("blacklists").

This file records that we assessed those triggers against the
Jasmin platform's processing and concluded a DPIA is **not** required
today. Per Art. 5(2) accountability, the reasoning needs to be
written down — auditors want evidence we thought about it, not
just the absence of a DPIA.

## How to read this document

An auditor asking "why didn't you run a DPIA?" gets a three-level
answer:

1. **The Art. 35(3) matrix** below — the three statutory triggers
   in the GDPR text, each lined up against what we actually do +
   the code location that proves it.
2. **The EDPB WP248rev01 nine-criteria checklist** (next section)
   — the EDPB's own framework for "when is risk high enough?".
   Two or more criteria met → DPIA expected; we hit zero.
3. **The supervisory-authority blacklists** (BfDI Germany /
   DSB Austria) — explicit "DPIA always required" entries that
   override our own assessment if we hit one. We hit none.

Each row cites the code path or fact that makes the trigger
non-applicable, so a future auditor (or future-you doing the
annual review) can re-verify the claim without taking it on
trust.

## Art. 35(3) statutory triggers — none apply

The three statutory triggers, with the verifiable code-side facts
that make each one non-applicable here.

### 35(3)(a) — Systematic + extensive evaluation including profiling, with legal or similarly significant effects

| Element of the trigger              | What we do                                                                                                                                       | Why it doesn't fire                                                                                                                                                          |
|-------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Systematic evaluation               | Members place share-orders; the platform records what they ordered, paid for, and consented to.                                                  | Recording transactions ≠ evaluating people. There is no derived attribute about a member ("reliability score", "credit class", "engagement segment") computed and persisted. |
| Profiling (Art. 4(4))               | We have no automated processing producing a personal-profile attribute from the data subject's behaviour.                                        | No profile fields exist on `Member` / `JasminUser`. Verified by grep against `apps/commissioning/models/members.py` (2026-06-09).                                              |
| Automated decision-making (Art. 22) | Member-status transitions (admit / cancel / anonymise) require an office user to click; see `apps.commissioning.models.mixin.AdminConfirmableMixin`. | Every life-cycle transition has an `admin_confirmed_by` audit column — by construction these are office decisions, not algorithmic outputs.                                  |
| Legal or similarly significant effects | None.                                                                                                                                            | The platform does not deny membership, deny billing, or block deliveries based on a computed score. Membership decisions sit with the Vorstand (GenG §43a), recorded here as audit. |

**Re-trigger condition.** A new column on `Member` or `JasminUser`
that holds a computed personal attribute (e.g. `engagement_score`,
`payment_risk_band`, `predicted_churn`) flips this trigger. Any
PR adding such a column must reopen this assessment.

### 35(3)(b) — Large-scale processing of Art. 9 special categories or Art. 10 conviction data

| Element of the trigger | What we do                                                                                                            | Why it doesn't fire                                                                                                                                                                                 |
|------------------------|-----------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Art. 9 categories      | We collect no race, political opinion, religious belief, union membership, genetic, biometric, health, or sex-life data. | The field-level [data-inventory.md](data-inventory.md) lists every PII column on every model. Cross-checked: zero Art. 9 columns. The "dietary preference" surfaces some Solawis ask for is intentionally NOT modelled. |
| Art. 10 conviction data | None collected.                                                                                                       | No `criminal_record`, `prior_conviction`, or equivalent column anywhere in the schema. Verified by `grep -rin "conviction\\|criminal_record" apps/` (no matches in production code).                  |
| Scale                  | If we were to add such a column, each tenant's user count (low thousands) would still cross the EDPB "large-scale" threshold for sensitive data. | Moot — we collect none. The check is preemptive: even **starting** to collect Art. 9 data here would require a DPIA before the first row lands.                                                       |

**Re-trigger condition.** Any new column that even arguably falls
in Art. 9 (e.g. a "health-related dietary restriction" field on a
member's profile, rather than just a free-form `note`) flips this
trigger.

### 35(3)(c) — Systematic large-scale monitoring of a publicly accessible area

| Element of the trigger      | What we do                                                                                            | Why it doesn't fire                                                                                                                                       |
|-----------------------------|-------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| Public-area monitoring      | The platform has no camera / sensor / location-feed integration.                                      | No CCTV ingest, no IoT field-sensor ingest, no behavioural-event stream is implemented. The codebase is a back-office data-management UI plus a member portal. |
| Location tracking           | The platform does not track member device locations.                                                  | No geolocation API is requested by the React frontend (verified `grep -rin "navigator.geolocation" jasmin-core/react-core/src/` — no matches).              |
| Server-side IP retention    | `django-axes` stores the IP for authentication-failure tracking; auditlog stores it for write events. | Bounded retention (per platform config) and a security purpose under Art. 6(1)(f) — not "monitoring" in the Art. 35(3)(c) sense.                          |

**Re-trigger condition.** Any new feature that ingests sensor /
camera / location data on a routine basis (a delivery-tracking
map for resellers, a "check-in" feature at the pickup point, …)
flips this trigger.

## EDPB WP248rev01 nine-criteria checklist — zero hit

EDPB Guidelines on DPIA (WP248rev01, endorsed at the first
plenary, 2018) list nine criteria that signal high-risk processing.
The EDPB's rule of thumb is that **two or more criteria** typically
mean a DPIA is expected.

| # | Criterion (EDPB WP248rev01)                              | Jasmin status | Reason                                                                                                                |
|---|----------------------------------------------------------|--------------|-----------------------------------------------------------------------------------------------------------------------|
| 1 | Evaluation or scoring                                    | **No**       | No persisted personal-attribute scores; see Art. 35(3)(a) matrix above.                                               |
| 2 | Automated decision-making with legal or similar effect   | **No**       | Member life-cycle is office-confirmed (`AdminConfirmableMixin`); see Art. 35(3)(a) matrix.                            |
| 3 | Systematic monitoring                                    | **No**       | No behavioural-event stream; auth logging is bounded and security-purpose, see Art. 35(3)(c).                          |
| 4 | Sensitive data or data of a highly personal nature       | **No**       | No Art. 9 or Art. 10 data; see Art. 35(3)(b) matrix.                                                                  |
| 5 | Data processed on a large scale                          | **No**       | Each tenant is a small-to-medium cooperative; low thousands per tenant. EDPB "large scale" threshold is not met.       |
| 6 | Matching or combining datasets                           | **No**       | No cross-tenant aggregation; per-tenant PostgreSQL schema isolation prevents it by construction.                       |
| 7 | Data concerning vulnerable data subjects                 | **No**       | Members are adults (cooperative-law minimum age is 18 in DE / AT). No children, patients, employees in a power asymmetry. |
| 8 | Innovative use or applying new technological solutions   | **No**       | Standard Django REST + React + SEPA. No AI scoring, no novel biometrics, no drones, no blockchain identity, no LLM-based decisions.  |
| 9 | When the processing in itself prevents data subjects from exercising a right or using a service / contract | **No**       | The platform does not gate access to a public service on this processing. Membership in a cooperative is voluntary; non-members are not denied anything. |

**Score: 0 / 9.** EDPB threshold for "DPIA expected" (2 or more)
is not met by a wide margin.

## Supervisory-authority blacklists — none apply

Cross-checked against the DSB Austria and BfDI Germany blacklists
of processing operations requiring a DPIA (BfDI Liste, version
2018-10-04, plus the DSK joint list).

| Blacklist entry                                                   | Jasmin status | Reason                                                                                                                                                                       |
|-------------------------------------------------------------------|--------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Health / biometric / genetic data at scale                        | **N/A**      | We collect none; see Art. 35(3)(b).                                                                                                                                          |
| Employee monitoring                                               | **N/A**      | "Office staff" users are Solawi-internal staff using a back-office UI. Auth events (axes / security.log) are bounded-retention Art. 6(1)(f) security logs, not productivity monitoring. |
| Credit-scoring / financial-fraud detection                        | **N/A**      | SEPA Direct Debit is operational billing, not evaluative. No score is computed about a member's creditworthiness.                                                              |
| Children's data at scale                                          | **N/A**      | Members are adults (GenG: minimum age 18). The platform is not marketed to or designed for children.                                                                          |
| Innovative technology with unclear risk (AI scoring, drones, etc.) | **N/A**      | None used.                                                                                                                                                                   |
| Profiling that produces effects on legal positions                | **N/A**      | No profiling; see Art. 35(3)(a) matrix.                                                                                                                                      |
| Mobile-app permissions beyond the necessary (camera, location)    | **N/A**      | The Jasmin frontend is a web SPA; it does not request `camera` or `geolocation` permissions. The PWA wrapper, when used, asks for no additional permissions.                    |

## Scale check

Each tenant is a small-to-medium Solawi cooperative; member count
per tenant is in the low thousands. Total platform-wide subjects
are in the low tens of thousands. Even if a single Solawi grew an
order of magnitude, the processing categories above would not
change.

## What would re-trigger this assessment

The decision should be revisited if any of the following lands:

- New field that holds Art. 9 special-category data (e.g. dietary
  reasons recorded as medical info, not preferences)
- Automated decision-making with legal effect (e.g. algorithmic
  share-allocation that affects who eats)
- Profiling for marketing (a feature we have explicitly decided
  not to add — see `docs/gdpr/processing-activities.md`)
- Cross-tenant aggregation that produces person-level analytics
- A processing operation a new supervisory-authority blacklist
  adds after this date

If any of those land, run a full DPIA per Art. 35(7) and replace
this file with the result.

## Review schedule

| Date       | Reviewer       | Outcome                                                                 |
|------------|----------------|-------------------------------------------------------------------------|
| 2026-06-03 | Initial draft  | DPIA not required (this doc)                                            |
| 2026-06-09 | Audit-pass     | Added Art. 35(3) matrix + EDPB WP248 9-criteria checklist + blacklist table; outcome unchanged (DPIA not required). |
