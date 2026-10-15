"""Persona classification + deletion preview (dry-run) for Art. 17 erasure.

``preview_subject_deletion`` reports EXACTLY what :meth:`anonymize_subject`
would scrub — the subject's persona, the retention blockers that would
currently refuse the deletion, and the per-model field list — WITHOUT writing
anything, so an admin can review before firing the irreversible erasure.

It reads the SAME sources of truth the executor does
(:meth:`check_retention_blocks_for_subject` + ``FIELD_CLASSIFICATION``) and
mirrors which rows :meth:`anonymize_subject` touches, so the preview can't
silently drift from what actually happens on execute.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from django.conf import settings

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
from .subject_emails import SubjectEmailKeys, subject_email_keys
from .subjects import ErasureSubject

if TYPE_CHECKING:
    # Type-only: the runtime path uses ``get_user_model()``, so this module
    # also works under a host project with a different ``AUTH_USER_MODEL``.
    from apps.accounts.models import JasminUser

    # ``GDPRService`` is assembled in the package ``__init__`` and bound into
    # this module's namespace there — see the binding loop in ``__init__``.
    from . import GDPRService


class Persona(StrEnum):
    """Which legal shape a subject is, for deletion purposes.

    Structural signal — the same one :meth:`anonymize_subject` branches on via
    presence checks: a ``Member`` row makes them a co-op **MEMBER** (GenG
    registry + HGB retention); a ``Reseller`` with no Member makes them a
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
        return GDPRService.detect_subject_persona(ErasureSubject.of_user(user))

    @staticmethod
    def detect_subject_persona(subject: ErasureSubject) -> Persona:
        """Classify ``subject`` as MEMBER / CUSTOMER / STAFF (see :class:`Persona`)."""
        if subject.member is not None:
            return Persona.MEMBER
        if subject.reseller is not None:
            return Persona.CUSTOMER
        return Persona.STAFF

    # ---------------------------------------------------------------
    # Preview (dry-run)
    # ---------------------------------------------------------------

    @staticmethod
    def preview_deletion(user: JasminUser) -> dict[str, Any]:
        """:meth:`preview_subject_deletion` for a login user and the member
        and reseller records tied to it."""
        return GDPRService.preview_subject_deletion(ErasureSubject.of_user(user))

    @staticmethod
    def preview_subject_deletion(subject: ErasureSubject) -> dict[str, Any]:
        """Dry-run of :meth:`anonymize_subject`: report persona, retention
        blockers and every field that WOULD be scrubbed — writing nothing.

        Shape (see :class:`apps.gdpr.serializers.DeletionPreviewSerializer`):
        ``user_id`` (empty for a subject without a login), ``user_email``
        (the address the subject is best known by), ``persona``,
        ``has_member`` / ``has_reseller``, ``can_anonymize_now`` (False while
        retention blocks exist), ``retention_blocks`` (the human-readable
        reasons), ``models`` (per present model: label + affected
        ``row_count`` + the ``scrubbed_fields`` list), and ``side_channels``
        (auditlog / axes / on-disk exports that are also cleared but aren't
        field-classified).
        """
        user, member, reseller = subject.user, subject.member, subject.reseller
        persona = GDPRService.detect_subject_persona(subject)
        retention_blocks = GDPRService.check_retention_blocks_for_subject(subject)
        email_keys = subject_email_keys(subject)

        presence = GDPRService._preview_presence(subject, email_keys)

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
            "user_id": str(user.pk) if user is not None else "",
            "user_email": subject.email,
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
        subject: ErasureSubject, email_keys: SubjectEmailKeys
    ) -> dict[str, tuple[bool, int]]:
        """``{model_label: (present, row_count)}`` for every classified model,
        scoped to this subject — mirrors which rows :meth:`anonymize_subject`
        touches.

        ``row_count`` is the number of rows that would actually change; for the
        Subscription / CoopShare / MemberLoan reasons the executor's bulk
        ``.update`` skips null reasons, so only rows carrying a reason count. For
        CoopShareTransfer it counts the transfers with a note plus the coop share
        rows those transfers created with a note, the other member's rows included.
        """

        def presence_and_row_count(model: type, **filters: Any) -> tuple[bool, int]:
            row_count = model.objects.filter(**filters).count()
            return (row_count > 0, row_count)

        user, member, reseller = subject.user, subject.member, subject.reseller
        presence: dict[str, tuple[bool, int]] = {}
        if user is not None:
            presence[settings.AUTH_USER_MODEL] = (True, 1)

        if member is not None:
            presence["commissioning.Member"] = (True, 1)
            presence["commissioning.Subscription"] = presence_and_row_count(
                Subscription, member=member, cancellation_reason__isnull=False
            )
            presence["commissioning.CoopShare"] = presence_and_row_count(
                CoopShare, member=member, cancellation_reason__isnull=False
            )
            presence["commissioning.MemberLoan"] = presence_and_row_count(
                MemberLoan, member=member, cancelled_reason__isnull=False
            )
            transfers = GDPRService._coop_share_transfers_of(member)
            transfer_notes = (
                transfers.exclude(note__isnull=True).count()
                + CoopShare.objects.filter(transfer__in=transfers)
                .exclude(note__isnull=True)
                .count()
            )
            presence["commissioning.CoopShareTransfer"] = (
                transfer_notes > 0,
                transfer_notes,
            )
            presence["payments.BillingProfile"] = presence_and_row_count(
                BillingProfile, member=member
            )
            presence["commissioning.ConsentRecord"] = presence_and_row_count(
                ConsentRecord, member=member
            )

        if reseller is not None:
            presence["commissioning.Reseller"] = (True, 1)
            presence["commissioning.ContactEntity"] = (
                GDPRService._contact_will_be_scrubbed(reseller),
                1,
            )

        if user is not None:
            presence["commissioning.UserInvitation"] = presence_and_row_count(
                UserInvitation, user=user
            )

        email_log_q = email_keys.email_log_q()
        email_count = (
            EmailLog.objects.filter(email_log_q).count()
            if email_log_q is not None
            else 0
        )
        presence["notifications.EmailLog"] = (email_count > 0, email_count)
        return presence

    @staticmethod
    def _contact_will_be_scrubbed(reseller: Reseller) -> bool:
        """True iff the reseller's ContactEntity is solo — mirrors the safety
        branch in ``_anonymize_reseller`` (a contact shared with
        another Reseller or a DeliveryStation is kept, not scrubbed)."""
        contact = reseller.contact
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
