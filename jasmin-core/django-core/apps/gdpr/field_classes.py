"""Field-level retention classification for GDPR anonymization.

Single source of truth for "what happens to this field when its data
subject requests deletion." The pipeline in :mod:`apps.gdpr.services`
iterates over this dict — adding a new PII field anywhere in the
codebase requires adding an entry here, enforced by the guard test
``apps/gdpr/tests/test_field_classification_guard.py``.

Why a dict per model instead of hardcoded ``setattr`` calls:

- Auditor / DPO can read this file and see in one place exactly
  which fields hold PII and what happens to them on anonymization.
- The guard test catches "PII field added but nobody classified it"
  at PR time, before the bug reaches prod.
- The forthcoming retention cron (Step 8 of
  ``docs/gdpr/deletion-roadmap.md``) reads the ``PII_RETAINED`` rows
  to know what to scrub when the statutory window expires.

Replacement value semantics
---------------------------
Each entry is ``(FieldClass, replacement)`` where ``replacement`` is
either a static value or a callable ``(instance) -> Any``. Callables
are useful for per-instance placeholders that need the row's pk
(``f"deleted_{instance.pk}@deleted.invalid"`` style).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any


class FieldClass(StrEnum):
    """How a field gets handled during anonymization."""

    #: Pure PII with no statutory retention. Scrubbed immediately on
    #: anonymization. Replacement is typically ``None`` (nullable
    #: columns) or ``""`` (CharField with ``null=False``).
    PII_IMMEDIATE = "pii_immediate"

    #: PII covered by a statutory retention obligation (HGB §257,
    #: UStG §14b, etc.). **Left alone at anonymization time**; the
    #: Step 8 retention cron scrubs the field once the obligation
    #: window has expired. Documented here so the cron knows what
    #: to scrub when the day comes.
    PII_RETAINED = "pii_retained"

    #: Name / id-like field that gets a deterministic placeholder
    #: ("Gelöscht") so existing FK references still render readably
    #: in admin / reports without revealing the original PII.
    TOMBSTONE = "tombstone"

    #: Not PII. Listed in the dict only to make the entry exhaustive
    #: (so the guard test can confirm "this field WAS considered and
    #: classified"). Most non-PII fields just don't appear in the dict
    #: at all — this status is for fields whose NAME suggests PII but
    #: which are actually operational (e.g. a ``status`` flag that
    #: happens to be on the same model).
    OPERATIONAL = "operational"


# Type alias: replacement can be a literal value OR a unary callable
# that receives the instance and returns the value.
Replacement = Any | Callable[[Any], Any]


FIELD_CLASSIFICATION: dict[str, dict[str, tuple[FieldClass, Replacement]]] = {
    # ----------------------------------------------------------------
    # accounts.JasminUser — the auth identity, may be linked to a
    # Member, a Reseller, both, or neither (staff-only).
    # ----------------------------------------------------------------
    "accounts.JasminUser": {
        "first_name": (FieldClass.TOMBSTONE, "Gelöscht"),
        "last_name": (FieldClass.TOMBSTONE, "Gelöscht"),
        "email": (
            FieldClass.PII_IMMEDIATE,
            lambda i: f"deleted_{i.pk}@deleted.invalid",
        ),
        "username": (FieldClass.PII_IMMEDIATE, lambda i: f"deleted_{i.pk}"),
        "last_login_ip": (FieldClass.PII_IMMEDIATE, None),
        "avatar": (FieldClass.PII_IMMEDIATE, None),
    },
    # ----------------------------------------------------------------
    # commissioning.Member — co-op member record. ``address`` /
    # ``zip_code`` / ``city`` / ``country`` are arguably PII_RETAINED
    # (10y HGB if the member is on invoices), but the pre-flight
    # retention check (Step 1) already refuses anonymization while
    # invoices are open. By the time we reach the scrub, the member
    # has fully exited; address can go.
    # ----------------------------------------------------------------
    "commissioning.Member": {
        "first_name": (FieldClass.TOMBSTONE, "Gelöscht"),
        "last_name": (FieldClass.TOMBSTONE, "Gelöscht"),
        "company_name": (FieldClass.PII_IMMEDIATE, None),
        "email": (FieldClass.PII_IMMEDIATE, None),
        "email_2": (FieldClass.PII_IMMEDIATE, None),
        "email_3": (FieldClass.PII_IMMEDIATE, None),
        "pickup_name": (FieldClass.PII_IMMEDIATE, None),
        "address": (FieldClass.PII_IMMEDIATE, None),
        "zip_code": (FieldClass.PII_IMMEDIATE, None),
        "city": (FieldClass.PII_IMMEDIATE, None),
        "country": (FieldClass.PII_IMMEDIATE, None),
        "account_owner": (FieldClass.PII_IMMEDIATE, None),
        "iban": (FieldClass.PII_IMMEDIATE, ""),
        "note": (FieldClass.PII_IMMEDIATE, None),
        # Free-text "why" of a cancellation — routinely holds personal data
        # (health reasons, complaints, "moved to <address>"). Scrubbed on
        # erasure like ``note``.
        "cancellation_reason": (FieldClass.PII_IMMEDIATE, None),
        "birth_date": (FieldClass.PII_IMMEDIATE, None),
    },
    "commissioning.Subscription": {
        # Free-text cancellation reason — same PII exposure as
        # ``Member.cancellation_reason``; applied via ``_anonymize_member``.
        "cancellation_reason": (FieldClass.PII_IMMEDIATE, None),
    },
    "commissioning.MemberLoan": {
        # Free-text cancellation reason (also echoed into the SAR bundle).
        "cancelled_reason": (FieldClass.PII_IMMEDIATE, None),
    },
    # ----------------------------------------------------------------
    # payments.BillingProfile — SEPA mandate. The encrypted fields
    # are at-rest-encrypted but the auditlog leak (closed in the
    # §logging audit) showed: encryption at rest doesn't help if
    # the Python value is read into a plain string in a diff column.
    # Scrub on Python-side too.
    # ----------------------------------------------------------------
    "payments.BillingProfile": {
        "iban": (FieldClass.PII_IMMEDIATE, ""),
        "account_holder": (FieldClass.PII_IMMEDIATE, ""),
        "sepa_mandate_reference": (FieldClass.PII_IMMEDIATE, None),
        "sepa_mandate_signed_at": (FieldClass.PII_IMMEDIATE, None),
        "sepa_mandate_first_use_at": (FieldClass.PII_IMMEDIATE, None),
        "notes": (FieldClass.PII_IMMEDIATE, ""),
    },
    # ----------------------------------------------------------------
    # commissioning.Reseller — B2B customer record. The
    # ``invoice_*`` fields are display strings on rendered invoice
    # PDFs; replacing them with NULL on the live row is fine because
    # the rendered PDFs are immutable snapshots (we never re-render
    # an issued invoice).
    # ----------------------------------------------------------------
    "commissioning.Reseller": {
        "name_for_member_pages": (FieldClass.TOMBSTONE, "Gelöscht"),
        "invoice_name": (FieldClass.PII_IMMEDIATE, None),
        "invoice_name2": (FieldClass.PII_IMMEDIATE, None),
        "invoice_address": (FieldClass.PII_IMMEDIATE, None),
        "invoice_plz": (FieldClass.PII_IMMEDIATE, None),
        "invoice_city": (FieldClass.PII_IMMEDIATE, None),
        "invoice_email": (FieldClass.PII_IMMEDIATE, None),
        "note": (FieldClass.PII_IMMEDIATE, None),
    },
    # ----------------------------------------------------------------
    # commissioning.ContactEntity — shared infrastructure (Resellers
    # AND DeliveryStations point at it). Only scrubbed when no
    # OTHER entity still references the row; the safety check lives
    # in ``GDPRService._anonymize_reseller_for_user``.
    #
    # ``address`` / ``zip_code`` / ``city`` are NOT NULL on the
    # model — delivery routing breaks without them — so they get
    # TOMBSTONE placeholders instead of NULL.
    # ----------------------------------------------------------------
    "commissioning.ContactEntity": {
        "company_name": (FieldClass.TOMBSTONE, "Gelöscht"),
        "first_name": (FieldClass.PII_IMMEDIATE, None),
        "last_name": (FieldClass.PII_IMMEDIATE, None),
        "acronym": (FieldClass.PII_IMMEDIATE, None),
        "email": (FieldClass.PII_IMMEDIATE, None),
        "email_2": (FieldClass.PII_IMMEDIATE, None),
        "email_3": (FieldClass.PII_IMMEDIATE, None),
        "order_email": (FieldClass.PII_IMMEDIATE, None),
        "phone": (FieldClass.PII_IMMEDIATE, None),
        "phone_2": (FieldClass.PII_IMMEDIATE, None),
        "phone_3": (FieldClass.PII_IMMEDIATE, None),
        "uid": (FieldClass.PII_IMMEDIATE, None),
        "iban": (FieldClass.PII_IMMEDIATE, ""),
        "coords_lon": (FieldClass.PII_IMMEDIATE, None),
        "coords_lat": (FieldClass.PII_IMMEDIATE, None),
        "address": (FieldClass.TOMBSTONE, "Gelöscht"),
        "zip_code": (FieldClass.TOMBSTONE, "00000"),
        "city": (FieldClass.TOMBSTONE, "Gelöscht"),
        "country": (FieldClass.PII_IMMEDIATE, None),
    },
    # ----------------------------------------------------------------
    # commissioning.UserInvitation — historic invitations. The
    # token + status + timestamps stay so the audit trail
    # "an invite was sent on <date>" remains, but the recipient
    # email is anonymized.
    # ----------------------------------------------------------------
    "commissioning.UserInvitation": {
        "email": (
            FieldClass.PII_IMMEDIATE,
            lambda i: f"deleted_{i.user_id}@deleted.invalid",
        ),
    },
    # ----------------------------------------------------------------
    # notifications.EmailLog — every email ever sent to the subject.
    # Recipient is the search key + the PII. ``subject`` is rendered
    # free text from tenant-editable templates — it can carry the
    # person's name ("Rechnung Mai für Anna Müller") and we can't
    # police what tenants put there, so it gets tombstoned; the
    # ``template`` + ``purpose`` columns keep the operational signal
    # ("which kind of email was this"). ``error`` text can echo the
    # recipient address back, so it goes too.
    # ----------------------------------------------------------------
    "notifications.EmailLog": {
        "recipient": (FieldClass.PII_IMMEDIATE, "deleted@deleted.invalid"),
        "subject": (FieldClass.TOMBSTONE, "Gelöscht"),
        "error": (FieldClass.PII_IMMEDIATE, ""),
    },
    # ----------------------------------------------------------------
    # commissioning.ConsentRecord — one row per consent act with a
    # forensic IP + user-agent capture. Surfaced as a gap by the
    # Step 4 guard test: the row STAYS (legal audit trail of
    # "consent given on <date> for <document>" survives), but the
    # IP + UA are PII linked to the member and get scrubbed.
    # ----------------------------------------------------------------
    "commissioning.ConsentRecord": {
        "ip_address": (FieldClass.PII_IMMEDIATE, None),
        "user_agent": (FieldClass.PII_IMMEDIATE, ""),
    },
}


def get_classification(model_label: str) -> dict[str, tuple[FieldClass, Replacement]]:
    """Return the field-classification dict for a model (by
    ``Model._meta.label``), or an empty dict if not classified."""
    return FIELD_CLASSIFICATION.get(model_label, {})


def resolve_replacement(replacement: Replacement, instance: Any) -> Any:
    """Evaluate the replacement value for a given instance.

    Static values pass through unchanged; callables are invoked with
    the instance so they can build per-row placeholders
    (``f"deleted_{instance.pk}@deleted.invalid"`` etc.).
    """
    if callable(replacement):
        return replacement(instance)
    return replacement
