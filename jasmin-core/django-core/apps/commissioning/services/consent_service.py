"""Consent versioning service.

Owns the write side of ``ConsentRecord`` so the denormalised cache
columns on ``Member`` (``sepa_consent``, ``privacy_consent``,
``withdrawal_consent``) stay in lock-step with the canonical record
table. Views/serializers never write those Member columns directly —
they call ``ConsentService.record(...)`` and ``revoke(...)``.

The cache columns exist for the hot path: "is this member currently
consented to X?" which gets checked in many UI cards and queries
(``Member.sepa_consent is not None and member.billing_profile.is_active``
etc.). Recomputing them from ConsentRecord on every page would join
twice and pick the latest unrevoked row by ``consented_at`` — fine
once, but costly when fanned out across a member list.
"""

from __future__ import annotations

from django.core.mail import mail_admins
from django.db import models, transaction
from django.utils import timezone

from ..errors import ConsentAlreadyRevoked, ConsentDocumentNotFound
from ..models import ConsentDocument, ConsentKind, ConsentRecord, Member

# Map ``ConsentKind`` → the cache column on ``Member`` that the record
# updates as a side effect. Adding a new kind here makes
# ``record()`` / ``revoke()`` start maintaining it; absence means
# "ConsentRecord is the only place this lives" (which is fine for new
# kinds like ``terms`` that don't have a legacy cache column).
_CACHE_FIELD_BY_KIND: dict[str, str] = {
    ConsentKind.PRIVACY: "privacy_consent",
    ConsentKind.SEPA: "sepa_consent",
    ConsentKind.WITHDRAWAL: "withdrawal_consent",
}

# Withdrawing one of these is a processing-legal-basis withdrawal that needs an
# office review (unlike SEPA, which has its own automated consequence): the
# member is flagged (``consent_withdrawn_at``) and the office is emailed. NOT an
# automatic erasure — processing may still rest on contract / GenG retention.
_FLAG_ON_REVOKE: frozenset[str] = frozenset(
    {ConsentKind.PRIVACY, ConsentKind.WITHDRAWAL}
)


class ConsentService:
    """Stateless helper — instantiate per request or call class-style."""

    # ------------------------------------------------------------------ #
    # Document lookup                                                    #
    # ------------------------------------------------------------------ #
    @staticmethod
    def get_current_document(
        kind: str,
        locale: str = "de",
        as_of=None,
    ) -> ConsentDocument:
        """Return the active document for ``(kind, locale)`` at ``as_of``.

        Active = ``valid_from <= as_of`` AND
        (``valid_until IS NULL`` OR ``valid_until >= as_of``).
        Auto-succession on create closes the predecessor's
        ``valid_until``, so there's at most one active row per
        (kind, locale) at any given moment — but we still order by
        ``-valid_from`` defensively.

        Raises ``ConsentDocumentNotFound`` if no row matches, so the
        caller can render a clear "no policy uploaded yet" message
        instead of silently consenting the user to nothing.
        """
        as_of = as_of or timezone.now().date()
        doc = (
            ConsentDocument.objects.filter(
                kind=kind,
                locale=locale,
                valid_from__lte=as_of,
            )
            .filter(
                models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=as_of)
            )
            .order_by("-valid_from")
            .first()
        )
        if doc is None:
            raise ConsentDocumentNotFound(
                f"No ConsentDocument for kind={kind!r} locale={locale!r} "
                f"effective on or before {as_of.isoformat()}.",
            )
        return doc

    # ------------------------------------------------------------------ #
    # Record consent                                                     #
    # ------------------------------------------------------------------ #
    @staticmethod
    @transaction.atomic
    def record(
        *,
        member: Member,
        document: ConsentDocument,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> ConsentRecord:
        """Create a ConsentRecord and refresh the Member cache column.

        ``document`` is the *exact* row the user saw — the caller fetched
        it via ``get_current_document`` and showed its ``body`` to the
        member. Don't pass a kind string; pass the document, so we
        capture which version was actually displayed.
        """
        now = timezone.now()
        record = ConsentRecord.objects.create(
            member=member,
            document=document,
            consented_at=now,
            ip_address=ip_address,
            user_agent=user_agent[:500],
        )
        ConsentService._sync_member_cache(member, document.kind)
        # Re-consenting to a flagged kind clears the office review flag: the
        # member has an active legal basis again (if they later withdraw again,
        # ``revoke`` re-flags them).
        if document.kind in _FLAG_ON_REVOKE:
            Member.objects.filter(pk=member.pk).update(consent_withdrawn_at=None)
        return record

    # ------------------------------------------------------------------ #
    # Revoke (Art. 7(3) — withdraw consent)                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    @transaction.atomic
    def revoke(
        consent: ConsentRecord,
        *,
        reason: str = "",
        revoked_by=None,
    ) -> ConsentRecord:
        """Mark a consent revoked. Refreshes the Member cache to the
        next-latest unrevoked record (or NULL if no consent remains).
        """
        if consent.revoked_at is not None:
            raise ConsentAlreadyRevoked(
                f"ConsentRecord {consent.pk} was already revoked at "
                f"{consent.revoked_at.isoformat()}."
            )
        consent.revoked_at = timezone.now()
        consent.revoked_reason = reason[:200]
        consent.revoked_by = revoked_by
        consent.save(update_fields=["revoked_at", "revoked_reason", "revoked_by"])
        ConsentService._sync_member_cache(consent.member, consent.document.kind)

        # Withdrawing the SEPA mandate consent (Art. 7(3)) must actually stop
        # the direct debit — payments switches the member's BillingProfile off
        # SEPA via this shared seam (commissioning must not import payments).
        # Inside the same atomic block: a handler failure rolls the revoke back.
        if consent.document.kind == ConsentKind.SEPA:
            from apps.shared.sepa_mandate_hooks import notify_sepa_mandate_revoked

            notify_sepa_mandate_revoked(consent.member)

        # Privacy / withdrawal-terms consent is a processing legal basis:
        # withdrawing it needs a HUMAN review (not an automatic erasure). Flag
        # the member for the office and email them. Emailed on_commit so a mail
        # hiccup can't roll back the (committed) revoke.
        if consent.document.kind in _FLAG_ON_REVOKE:
            ConsentService._flag_member_for_consent_review(consent)

        return consent

    @staticmethod
    def _flag_member_for_consent_review(consent: ConsentRecord) -> None:
        member = consent.member
        Member.objects.filter(pk=member.pk).update(consent_withdrawn_at=timezone.now())
        kind_label = ConsentKind(consent.document.kind).label
        subject = f"[Consent withdrawn] {member} withdrew {kind_label}"
        message = (
            f"Member {member} (id={member.pk}) withdrew their '{kind_label}' "
            f"consent.\n\n"
            f"Withdrawing a processing-legal-basis consent needs an office "
            f"review: confirm whether processing may continue on another legal "
            f"basis (contract / GenG retention) or must be restricted. This is "
            f"NOT an automatic erasure. The member stays flagged "
            f"(consent_withdrawn_at) until they re-consent."
        )
        transaction.on_commit(lambda: mail_admins(subject, message, fail_silently=True))

    # ------------------------------------------------------------------ #
    # Cache maintenance                                                  #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _sync_member_cache(member: Member, kind: str) -> None:
        """Set ``Member.<kind>_consent`` to the latest active record's
        ``consented_at``, or NULL if none. Always reads from the DB so
        a concurrent revoke can't leave the cache pointing at a
        revoked row.
        """
        field_name = _CACHE_FIELD_BY_KIND.get(kind)
        if field_name is None:
            return  # Kind doesn't have a legacy cache column — fine.
        latest = (
            ConsentRecord.objects.filter(
                member=member,
                document__kind=kind,
                revoked_at__isnull=True,
            )
            .order_by("-consented_at")
            .values_list("consented_at", flat=True)
            .first()
        )
        Member.objects.filter(pk=member.pk).update(**{field_name: latest})
