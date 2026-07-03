"""Art. 30 Record-of-Processing-Activities (VVT) — codebase facts.

The platform-level facts (which activities exist, what categories of
data each one touches, what the retention rule is, where the code
lives) are static — they describe **what the codebase does**, not
what an individual tenant configured. So they live here as a Python
data structure rather than per-tenant DB rows.

The tenant-specific overlay (controller name, address, supervisory
authority, …) gets layered on at serialisation time in
:func:`apps.gdpr.views.gdpr_processing_activities_view` from the
live ``Tenant`` row. That keeps the codebase facts in one place
and the tenant operational config in another — same separation
that ``processing-activities.md`` documents in prose.

Schema:

  * **CONTROLLER_FIELDS** — keys the serializer pulls off the tenant
    AND keys the auditor expects to see filled in.
  * **PROCESSORS** — the sub-processors / joint-controllers the
    codebase relies on. Tenant overlay sets the "AVV on file" yes/no
    column (which is operational, not code-level).
  * **ACTIVITIES** — the 5 Art. 30 records. One ``Activity`` per row
    of section 3 of ``processing-activities.md``. Fields:
    ``key``, ``label``, ``purpose``, ``legal_basis``,
    ``data_subjects``, ``personal_data``, ``source``, ``recipients``,
    ``third_country_transfers``, ``retention``, ``security_measures``,
    ``code_locations``.
  * **TOMS** — the Art. 32 Technical & Organisational Measures
    (separate block in the prose doc + the auditor checklist).

When the codebase grows a new processing activity (new domain area,
new column holding personal data), add a row here AND extend
``processing-activities.md`` AND ``data-inventory.md``. The three
must agree.

"""

from __future__ import annotations

from dataclasses import asdict, dataclass

CONTROLLER_FIELDS: tuple[str, ...] = (
    # The platform pulls these off the live ``Tenant`` row. Static
    # here just to document the contract: an auditor expects every
    # one of these populated before they accept the VVT as
    # Art-30-compliant.
    "organisation_name",
    "legal_form",
    "registered_address",
    "contact_email",
    "contact_phone",
    "data_protection_contact",
    "dpo",
    "supervisory_authority",
)


# Joint controllers / processors the codebase relies on. The "AVV
# yes/no" column is intentionally NOT here — that's an operational
# question the tenant answers, not a code fact. The endpoint surfaces
# this list and the office UI lets the admin tick each one off.
PROCESSORS: list[dict[str, str]] = [
    {
        "role": "Hosting / Infrastructure",
        "party": "[tenant-specific]",
    },
    {
        "role": "Email delivery (Anymail)",
        "party": "SendGrid (default; override in TenantEmailConfig)",
    },
    {
        "role": "Payment / SEPA",
        "party": "[tenant-specific]",
    },
    {
        "role": "Error monitoring",
        "party": "Sentry (optional)",
    },
    {
        "role": "Backup storage",
        "party": "[tenant-specific]",
    },
]


@dataclass(frozen=True)
class Activity:
    """One Art. 30(1) processing-activity record."""

    key: str
    label: str
    purpose: str
    legal_basis: str
    data_subjects: str
    personal_data: str
    source: str
    recipients: str
    third_country_transfers: str
    retention: str
    security_measures: str
    code_locations: list[str]


ACTIVITIES: list[Activity] = [
    Activity(
        key="member_registration",
        label="Member registration & onboarding",
        purpose="Onboarding new cooperative members; KYC; consent capture",
        legal_basis=("Art. 6(1)(b) contract performance; Art. 6(1)(c) GenG §15"),
        data_subjects="Applicants, members",
        personal_data=(
            "Name, address, email, phone, birth date, IBAN, "
            "account_owner, optional company name, optional VAT id"
        ),
        source="Self-submitted via the public registration wizard",
        recipients=("Office staff (role 'office'); admin users (role 'admin')"),
        third_country_transfers="None",
        retention=(
            "Active membership + 10 years post-cancellation (GenG §31); "
            "then anonymisation"
        ),
        security_measures=(
            "Field-level encryption for IBAN; TLS in transit; per-tenant "
            "schema isolation; role-based access; auditlog on writes; "
            "rate-limiting"
        ),
        code_locations=[
            "apps/accounts/",
            "apps/commissioning/",
            "apps/authz/",
        ],
    ),
    Activity(
        key="sepa_billing",
        label="SEPA Direct Debit billing",
        purpose="Collecting contributions and equity payments",
        legal_basis=(
            "Art. 6(1)(b) contract; Art. 6(1)(c) HGB §257 / AO §147 "
            "(invoice retention)"
        ),
        data_subjects="Members, resellers",
        personal_data=(
            "IBAN, BIC (derived), account_owner, mandate reference, "
            "mandate signature date, charge schedule, invoice history"
        ),
        source=(
            "Member self-edit via Profile › Meine Daten; "
            "office edit via member detail page"
        ),
        recipients="Office staff; SEPA service provider (if any)",
        third_country_transfers="None",
        retention=(
            "10 years per HGB §257 (1) Nr. 4; mandates plus 14 months "
            "after last debit per SEPA rulebook"
        ),
        security_measures=(
            "django-encrypted-fields for IBAN at rest; mandate stored "
            "separately; auditlog"
        ),
        code_locations=["apps/payments/"],
    ),
    Activity(
        key="communication",
        label="Communication (transactional + bulk email)",
        purpose=(
            "Transactional notifications (invoices, deliveries, consent "
            "confirmations); operational announcements"
        ),
        legal_basis=(
            "Art. 6(1)(b) contract for transactional; Art. 6(1)(a) "
            "consent for non-transactional bulk"
        ),
        data_subjects="Members, customers, resellers",
        personal_data="Name, email, message content, send-time metadata",
        source="Triggered by platform events",
        recipients="Anymail provider (SendGrid by default)",
        third_country_transfers=(
            "Depends on the configured provider — SendGrid is US-based "
            "(Standard Contractual Clauses); SMTP fallback can be "
            "configured to an EU provider"
        ),
        retention="EmailLog: 2 years; then purge",
        security_measures=(
            "TLS to provider; provider has own AVV (DPA); EmailLog "
            "scrubs subject + recipient on member anonymisation"
        ),
        code_locations=["apps/notifications/"],
    ),
    Activity(
        key="auth_logging",
        label="Login + access logging",
        purpose=(
            "Authentication; brute-force protection (Art. 32 security); "
            "audit-trail (Art. 5(2) accountability)"
        ),
        legal_basis=("Art. 6(1)(f) legitimate interest in platform security"),
        data_subjects="All authenticated users",
        personal_data=("Username, IP, user-agent, success/failure, timestamp"),
        source="Auto-captured by django-axes + auditlog",
        recipients="Office staff (read-only)",
        third_country_transfers="None",
        retention=(
            "django-axes: per platform config; auditlog: same as " "member retention"
        ),
        security_measures=(
            "JWT auth; rate limiting on /login (20/min) + /register "
            "(10/h); axes lockout"
        ),
        code_locations=["apps/accounts/", "apps/authz/"],
    ),
    Activity(
        key="member_rights",
        label="Member-rights workflows (GDPR Art. 15 / 16 / 17 / 20)",
        purpose="Fulfilling data-subject rights",
        legal_basis="Art. 6(1)(c) legal obligation",
        data_subjects="Members, customers, resellers",
        personal_data=(
            "Full subject access bundle (everything the user touched); "
            "deletion-request metadata; DeletionLog audit row"
        ),
        source="User initiates via Profile › Meine Daten",
        recipients=("The requesting user; office staff approving / rejecting"),
        third_country_transfers="None",
        retention=(
            "SAR exports: not retained — generated on-demand. "
            "DeletionLog rows: indefinitely (regulator-facing accountability)"
        ),
        security_measures=(
            "Two-step deletion with admin gate; rate-limiting "
            "(2/h SAR, 5/h request-deletion, 10/min confirm)"
        ),
        code_locations=["apps/gdpr/"],
    ),
]


# Art. 32 Technical & Organisational Measures — the platform-side
# guarantees the controller can cite to a supervisory authority
# without having to re-introspect the code.
TOMS: list[dict[str, str]] = [
    {
        "label": "Encryption in transit",
        "value": (
            "TLS via gateway nginx + Let's Encrypt wildcard. See "
            "docs/security/https-deploy-runbook.md."
        ),
    },
    {
        "label": "Encryption at rest",
        "value": (
            "PostgreSQL with django-encrypted-fields for IBAN; signed "
            "JWTs; hashed passwords (Django default + zxcvbn)"
        ),
    },
    {
        "label": "Access control",
        "value": (
            "Role-based (member / office / admin); per-tenant schema "
            "isolation prevents cross-tenant reads"
        ),
    },
    {
        "label": "Audit logging",
        "value": (
            "django-auditlog on writes; throttle-scope enforcement via "
            "class attribute"
        ),
    },
    {
        "label": "Backups",
        "value": (
            "AES-256 GPG-encrypted pg_dump; restore replays the "
            "DeletionLog so anonymised PII doesn't resurrect"
        ),
    },
    {
        "label": "Brute-force protection",
        "value": ("django-axes lockout + per-endpoint throttle scopes"),
    },
    {
        "label": "Bot protection",
        "value": "Honeypot field on the registration form",
    },
]


def activity_dicts() -> list[dict]:
    """Return the activity records as plain dicts (serializer-friendly)."""
    return [asdict(a) for a in ACTIVITIES]
