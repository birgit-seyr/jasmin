"""Persona classification + deletion preview (dry-run) — Art. 17 roadmap Step 5.

``preview_deletion`` reports EXACTLY what :meth:`anonymize_user` would scrub —
the subject's persona, the retention blockers that would currently refuse the
deletion, and the per-model field list — WITHOUT writing anything, so an admin
can review before firing the irreversible erasure.

It reads the SAME sources of truth the executor does
(:meth:`check_retention_blocks` + ``FIELD_CLASSIFICATION``) and mirrors which
rows :meth:`anonymize_user` touches, so the preview can't silently drift from
what actually happens on execute.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from apps.accounts.models import JasminUser
from apps.commissioning.models import (
    ConsentRecord,
    CoopShare,
    DeliveryStation,
    Member,
    MemberLoan,
    Reseller,
    Subscription,
    UserInvitation,
)
from apps.notifications.models import EmailLog
from apps.payments.models import BillingProfile

from ..field_classes import FieldClass, get_classification
from .anonymization import _ci_recipient_q

if TYPE_CHECKING:
    # ``GDPRService`` is assembled in the package ``__init__`` and bound into
    # this module's namespace there — see the binding loop in ``__init__``.
    from . import GDPRService


class Persona(StrEnum):
    """Which legal shape a user is, for deletion purposes.

    Structural signal — the same one :meth:`anonymize_user` branches on via
    presence checks: a ``Member`` row makes them a co-op **MEMBER** (GenG
    registry + HGB retention); a ``Reseller`` link with no Member makes them a
    B2B **CUSTOMER** (UStG §14b); a JasminUser with neither is **STAFF** (they
    act as ``created_by`` on documents, not as a data subject with retention).

    A user who is BOTH a member and a customer is classified MEMBER — the
    stricter registry obligation governs, and the anonymization touches both
    the member and the reseller side regardless of this label.
    """

    MEMBER = "member"
    CUSTOMER = "customer"
    STAFF = "staff"


def _describe_replacement(field_class: FieldClass, replacement: Any) -> str:
    """Human-readable "what this field becomes" for the preview payload."""
    if field_class is FieldClass.TOMBSTONE:
        return f'placeholder "{replacement}"'
    if callable(replacement):
        return "generated placeholder"
    if replacement is None:
        return "cleared (null)"
    if replacement == "":
        return "cleared (empty)"
    return f'set to "{replacement}"'


class PreviewMixin:
    """Persona detection + deletion dry-run, mixed into
    :class:`apps.gdpr.services.GDPRService`."""

    # ---------------------------------------------------------------
    # Persona
    # ---------------------------------------------------------------

    @staticmethod
    def detect_persona(user: JasminUser) -> Persona:
        """Classify ``user`` as MEMBER / CUSTOMER / STAFF (see :class:`Persona`)."""
        if Member.objects.filter(user=user).exists():
            return Persona.MEMBER
        if Reseller.objects.filter(linked_user=user).exists():
            return Persona.CUSTOMER
        return Persona.STAFF

    # ---------------------------------------------------------------
    # Preview (dry-run)
    # ---------------------------------------------------------------

    @staticmethod
    def preview_deletion(user: JasminUser) -> dict[str, Any]:
        """Dry-run of :meth:`anonymize_user`: report persona, retention
        blockers and every field that WOULD be scrubbed — writing nothing.

        Shape (see :class:`apps.gdpr.serializers.DeletionPreviewSerializer`):
        ``persona``, ``has_member`` / ``has_reseller``, ``can_anonymize_now``
        (False while retention blocks exist), ``retention_blocks`` (the
        human-readable reasons), ``models`` (per present model: label +
        affected ``row_count`` + the ``scrubbed_fields`` list), and
        ``side_channels`` (auditlog / axes / on-disk exports that are also
        cleared but aren't field-classified).
        """
        member = Member.objects.filter(user=user).first()
        reseller = Reseller.objects.filter(linked_user=user).first()
        persona = GDPRService.detect_persona(user)
        retention_blocks = GDPRService.check_retention_blocks(user)
        known_emails = GDPRService._collect_known_emails(user)

        presence = GDPRService._preview_presence(user, member, reseller, known_emails)

        models: list[dict[str, Any]] = []
        field_count = 0
        for model_label, (present, row_count) in presence.items():
            if not present:
                continue
            scrubbed_fields = [
                {
                    "field": field,
                    "action": str(field_class),
                    "becomes": _describe_replacement(field_class, replacement),
                }
                for field, (field_class, replacement) in get_classification(
                    model_label
                ).items()
                if field_class in (FieldClass.PII_IMMEDIATE, FieldClass.TOMBSTONE)
            ]
            if not scrubbed_fields:
                continue
            field_count += len(scrubbed_fields)
            models.append(
                {
                    "model": model_label,
                    "row_count": row_count,
                    "scrubbed_fields": scrubbed_fields,
                }
            )

        side_channels = GDPRService._preview_side_channels(member, reseller)

        return {
            "user_id": str(user.pk),
            "user_email": user.email,
            "persona": str(persona),
            "has_member": member is not None,
            "has_reseller": reseller is not None,
            "can_anonymize_now": not retention_blocks,
            "retention_blocks": retention_blocks,
            "model_count": len(models),
            "field_count": field_count,
            "models": models,
            "side_channels": side_channels,
        }

    @staticmethod
    def _preview_presence(
        user: JasminUser,
        member: Member | None,
        reseller: Reseller | None,
        known_emails: set[str],
    ) -> dict[str, tuple[bool, int]]:
        """``{model_label: (present, row_count)}`` for every classified model,
        scoped to this user — mirrors which rows :meth:`anonymize_user` touches.

        ``row_count`` is the number of rows that would actually change; for the
        Subscription / CoopShare / MemberLoan reasons the executor's bulk
        ``.update`` skips null reasons, so only rows carrying a reason count.
        """

        def count(model: type, **flt: Any) -> tuple[bool, int]:
            c = model.objects.filter(**flt).count()
            return (c > 0, c)

        presence: dict[str, tuple[bool, int]] = {"accounts.JasminUser": (True, 1)}

        if member is not None:
            presence["commissioning.Member"] = (True, 1)
            presence["commissioning.Subscription"] = count(
                Subscription, member=member, cancellation_reason__isnull=False
            )
            presence["commissioning.CoopShare"] = count(
                CoopShare, member=member, cancellation_reason__isnull=False
            )
            presence["commissioning.MemberLoan"] = count(
                MemberLoan, member=member, cancelled_reason__isnull=False
            )
            presence["payments.BillingProfile"] = count(BillingProfile, member=member)
            presence["commissioning.ConsentRecord"] = count(
                ConsentRecord, member=member
            )

        if reseller is not None:
            presence["commissioning.Reseller"] = (True, 1)
            presence["commissioning.ContactEntity"] = (
                GDPRService._contact_will_be_scrubbed(reseller),
                1,
            )

        presence["commissioning.UserInvitation"] = count(UserInvitation, user=user)

        # ``_ci_recipient_q`` on an EMPTY set is an empty ``Q()`` that matches
        # every row — guard it so an emailless user doesn't "match all".
        email_count = (
            EmailLog.objects.filter(_ci_recipient_q(known_emails)).count()
            if known_emails
            else 0
        )
        presence["notifications.EmailLog"] = (email_count > 0, email_count)
        return presence

    @staticmethod
    def _contact_will_be_scrubbed(reseller: Reseller) -> bool:
        """True iff the reseller's ContactEntity is solo — mirrors the safety
        branch in ``_anonymize_reseller_for_user`` (a contact shared with
        another Reseller or a DeliveryStation is kept, not scrubbed)."""
        contact = reseller.contact
        if contact is None:
            return False
        shared = (
            Reseller.objects.filter(contact=contact).exclude(pk=reseller.pk).exists()
            or DeliveryStation.objects.filter(contact=contact).exists()
        )
        return not shared

    @staticmethod
    def _preview_side_channels(
        member: Member | None, reseller: Reseller | None
    ) -> list[dict[str, str]]:
        """The non-field-classified scrubs the executor also performs, described
        for the preview (auditlog diffs, axes login records, on-disk exports)."""
        channels: list[dict[str, str]] = [
            {
                "target": "auditlog",
                "description": (
                    "Historical audit-log diffs for the scrubbed records are "
                    "cleared (the change rows stay; the old/new values go)."
                ),
            },
            {
                "target": "axes",
                "description": (
                    "django-axes login records (successful + failed) keyed by "
                    "the subject's email addresses are hard-deleted."
                ),
            },
        ]
        if member is not None:
            channels.append(
                {
                    "target": "sepa_export",
                    "description": (
                        "Plaintext pain.008 SEPA export files of the member's "
                        "past billing runs are deleted (BillingRun rows kept)."
                    ),
                }
            )
        if reseller is not None:
            channels.append(
                {
                    "target": "reseller_documents",
                    "description": (
                        "Rendered invoice / delivery-note PDFs + ZUGFeRD XML for "
                        "the reseller are purged from disk (document rows kept)."
                    ),
                }
            )
        return channels
