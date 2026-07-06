"""Anonymization engine — Art. 17 erasure via PII scrubbing."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Q

from apps.accounts.models import JasminUser
from apps.commissioning.models import (
    ConsentRecord,
    ContactEntity,
    CoopShare,
    DeliveryNoteContent,
    DeliveryNoteReseller,
    DeliveryStation,
    InvoiceReseller,
    InvoiceResellerContent,
    Member,
    MemberLoan,
    Order,
    OrderContent,
    Reseller,
    ShareDelivery,
    Subscription,
    UserInvitation,
)
from apps.notifications.models import EmailLog
from apps.payments.constants import PaymentMethodOptions
from apps.payments.models import BillingProfile

from ..errors import RetentionPeriodActive
from ..field_classes import FieldClass, get_classification, resolve_replacement
from ..models import DeletionLog

if TYPE_CHECKING:
    # ``GDPRService`` is assembled in the package ``__init__`` and bound into
    # this module's namespace there. Method bodies must resolve it at call
    # time through the ASSEMBLED class so monkeypatched attributes on
    # ``GDPRService`` are honoured.
    from . import GDPRService

logger = logging.getLogger("gdpr")


def _ci_username_q(emails: Iterable[str]) -> Q:
    """OR of case-insensitive ``username`` matches for every address.

    ``django-axes`` stores the raw submitted login credential, so a
    member who signed in as ``Foo@Bar.com`` lands an axes row whose
    ``username`` is mixed-case. Matching the canonical lowercase email
    with ``username__in`` would miss it — leaving login records behind
    on an Art. 17 deletion, or overlooking them in an Art. 15 export.
    ``username__iexact`` per address closes the gap; email addresses are
    case-insensitive identifiers, so this is the correct comparison."""
    query = Q()
    for email in emails:
        query |= Q(username__iexact=email)
    return query


def _ci_recipient_q(emails: Iterable[str]) -> Q:
    """OR of case-insensitive ``recipient`` matches for every address.

    ``EmailLog.recipient`` stores whatever casing the send used, and the
    secondary address columns (``Member.email_2``/``email_3``, reseller
    contact fields) are unvalidated CharFields — so mixed-case rows exist
    on both sides of the match. A case-sensitive ``recipient__in`` would
    let those rows survive an Art. 17 scrub, or hide them from an
    Art. 15 export; ``recipient__iexact`` per address mirrors
    ``_ci_username_q``."""
    query = Q()
    for email in emails:
        query |= Q(recipient__iexact=email)
    return query


def _apply_classification(instance: Any, model_label: str) -> None:
    """Apply the PII_IMMEDIATE + TOMBSTONE entries from
    ``FIELD_CLASSIFICATION[model_label]`` to ``instance`` (in-memory;
    caller still has to ``.save()``).

    Skips ``PII_RETAINED`` (Step 8's retention cron handles those)
    and ``OPERATIONAL`` (not PII, listed only for guard-test
    completeness). Lives at module level rather than as a static
    method because the helper has no dependency on ``GDPRService``
    state and gets reused unchanged across every per-model helper.
    """
    classification = get_classification(model_label)
    for field, (field_class, replacement) in classification.items():
        if field_class in (FieldClass.PII_IMMEDIATE, FieldClass.TOMBSTONE):
            setattr(instance, field, resolve_replacement(replacement, instance))


class AnonymizationMixin:
    """Anonymization engine, mixed into
    :class:`apps.gdpr.services.GDPRService`."""

    # ---------------------------------------------------------------
    # Anonymization
    # ---------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def anonymize_user(user: JasminUser) -> DeletionLog:
        """Anonymize all personal data for a user (Art. 17).

        Replaces PII with placeholder values on every model that
        directly or indirectly holds the subject's data. Keeps the
        rows for referential integrity (statutory documents on the
        other side of FKs stay readable).

        Refuses with :class:`RetentionPeriodActive` (HTTP 409) when
        the subject still has statutory retention obligations. See
        :meth:`check_retention_blocks` for the rules.

        Order of operations matters:

        1. **Collect known emails** BEFORE any wipe — they're the
           search key for the side-channel records (EmailLog, axes).
        2. **Anonymize primary records** (JasminUser, Member).
        3. **Anonymize related records via FK** (BillingProfile,
           Reseller + its ContactEntity, UserInvitation).
        4. **Scrub side-channel records** keyed by email (EmailLog,
           axes AccessLog / AccessAttempt / AccessFailureLog).
        5. **Log to DeletionLog** for backup-replay.

        Wrapped in ``@transaction.atomic`` so a failure halfway
        through rolls back everything — you're never left with a
        half-anonymized user that the next call sees as already-done.
        """
        reasons = GDPRService.check_retention_blocks(user)
        if reasons:
            raise RetentionPeriodActive(reasons)

        # Phase 1: collect every email address tied to this user.
        # These become the search keys for EmailLog + axes scrubs.
        known_emails = GDPRService._collect_known_emails(user)
        original_email = user.email

        # Auditlog scrub targets — capture BEFORE the wipes. Phase 3
        # releases ``reseller.linked_user`` (the lookup key), so the
        # reseller must be resolved up front.
        member = Member.objects.filter(user=user).first()
        reseller = Reseller.objects.filter(linked_user=user).first()

        # Phase 2: primary records.
        GDPRService._anonymize_jasmin_user(user)
        if member is not None:
            GDPRService._anonymize_member(member)
            GDPRService._anonymize_billing_profile(member)
            GDPRService._anonymize_consent_records(member)

        # Phase 3: FK-related records.
        GDPRService._anonymize_reseller_for_user(user)
        GDPRService._anonymize_user_invitations(user)

        # Phase 4: side-channel scrubs.
        GDPRService._anonymize_email_logs(known_emails)
        GDPRService._purge_axes_records(known_emails)

        # Phase 4.6: purge the plaintext SEPA export. pain.008 files embed the
        # debtor name + IBAN in cleartext (the encrypted DB columns are scrubbed
        # above, but the on-disk file is not). By the time a member is anonymised
        # (10y after exit) every billing run that debited them predates the exit
        # and is therefore itself past the 10y GoBD/UStG retention, so the file
        # may be erased (Art. 17). The BillingRun row — the financial record —
        # is kept; only the plaintext file is removed.
        if member is not None:
            GDPRService._purge_member_sepa_exports(member)

        # Phase 4.5: auditlog diffs. Historical ``LogEntry.changes``
        # rows for the scrubbed records hold pre-anonymization values
        # (name changes, address edits, consent IP/UA, ...) —
        # ``mask_fields`` only covers a subset of columns and only
        # from the moment it was configured.
        GDPRService._scrub_auditlog_entries(user, member, reseller)

        # Phase 5: audit trail (for backup-replay + auditor proof).
        return DeletionLog.objects.create(
            user_email=original_email,
            description="GDPR deletion request — all personal data anonymized.",
        )

    # ---- Per-model anonymization helpers ----

    @staticmethod
    def _purge_member_sepa_exports(member: Member) -> None:
        """Delete the plaintext pain.008 SEPA export files of the billing runs
        that debited ``member`` (keeping the BillingRun rows).

        Gated on the run being past the same ``EX_MEMBER_RETENTION_YEARS`` window
        the member sweep uses — belt-and-braces, since a member anonymised that
        long after exit can only have runs older than the window. A run's file
        is shared across that period's members, but a run past its retention is
        past it for everyone in it, so erasing it here is correct.
        """
        from apps.payments.models import BillingRun

        from ..tasks import _retention_cutoff

        cutoff = _retention_cutoff()
        runs = BillingRun.objects.filter(charges__member=member).distinct()
        for run in runs:
            if not run.sepa_xml_export:
                continue
            if run.created_at.date() > cutoff:
                # Still within statutory retention — leave it (unreachable for a
                # correctly-aged anonymisation, but never erase a live record).
                continue
            run.sepa_xml_export.delete(save=True)

    @staticmethod
    def _collect_known_emails(
        user: JasminUser, *, include_shared_secondaries: bool = True
    ) -> set[str]:
        """Return email addresses attached to the subject.

        Two callers, two needs:

        * **Art. 17 anonymization** (phase 4 scrubs) — pass the default.
          We're erasing this subject, so scrub EVERY address they ever
          used, secondary addresses included.
        * **Art. 15 SAR side-channel** (EmailLog + login history) — pass
          ``include_shared_secondaries=False``. ``Member.email_2`` /
          ``email_3`` (and the reseller contact's secondaries) are plain
          CharFields with NO unique constraint, so a shared household /
          family address can legitimately sit on several Members. Keying
          the SAR search on a shared address would surface ANOTHER
          subject's emails + login records — over-disclosing a third
          party, which Art. 15 forbids. The primary ``email`` columns are
          unique (``JasminUser.email`` and ``Member.email``), so restrict
          the SAR to those plus the reseller's own business addresses.

        Must run BEFORE any of the wipes — otherwise the addresses we're
        trying to find historical records for are already gone.
        """
        emails: set[str] = set()
        if user.email:
            emails.add(user.email)

        member = Member.objects.filter(user=user).first()
        if member is not None:
            # No ``, None`` default — the field tuple is hard-coded; a
            # missing attribute here would mean the Member schema changed
            # out from under us and the GDPR email-erasure target list is
            # silently incomplete. Better to raise.
            member_fields = ["email"]
            if include_shared_secondaries:
                member_fields += ["email_2", "email_3"]
            for field in member_fields:
                value = getattr(member, field)
                if value:
                    emails.add(value)

        # B2B side: any ContactEntity the user's Reseller points to.
        reseller = Reseller.objects.filter(linked_user=user).first()
        if reseller is not None and reseller.contact is not None:
            contact_fields = ["email", "order_email"]
            if include_shared_secondaries:
                contact_fields += ["email_2", "email_3"]
            for field in contact_fields:
                value = getattr(reseller.contact, field)
                if value:
                    emails.add(value)
            if reseller.invoice_email:
                emails.add(reseller.invoice_email)

        # Historical invitation emails (the address invited to the
        # platform, even if it was never accepted).
        for invitation_email in UserInvitation.objects.filter(user=user).values_list(
            "email", flat=True
        ):
            if invitation_email:
                emails.add(invitation_email)

        return emails

    @staticmethod
    def _anonymize_jasmin_user(user: JasminUser) -> None:
        """Scrub the JasminUser row in place.

        Field-set replacements come from ``FIELD_CLASSIFICATION``;
        the operational ``is_active`` / ``account_status`` flips
        stay inline because they're status transitions, not PII
        scrubs.
        """
        # GDPR-3: remove the uploaded avatar FILE from storage BEFORE the
        # classification nulls the column — assigning None to an ImageField
        # only clears the path, leaving the image (a photo of the data subject)
        # on disk, which would survive Art. 17 erasure. Mirrors the FileField
        # delete used for ``run.sepa_xml_export`` elsewhere in this module.
        if user.avatar:
            user.avatar.delete(save=False)
        _apply_classification(user, "accounts.JasminUser")
        user.is_active = False
        user.account_status = "inactive"
        user.save()

    @staticmethod
    def _anonymize_member(member: Member) -> None:
        """Scrub the Member row in place. Field-set from
        ``FIELD_CLASSIFICATION``; status transitions inline."""
        from apps.commissioning.services.member_cancellation import (
            cancel_member_with_coop_shares,
        )

        _apply_classification(member, "commissioning.Member")
        member.is_active = False

        member.save()
        # Anonymisation implies the member is gone — set the
        # cancellation timestamps and cascade to open CoopShares so the
        # equity history reflects the exit date.
        if member.cancelled_at is None:
            cancel_member_with_coop_shares(member)

        # Scrub the free-text cancellation reasons on the member's related rows
        # (Subscription / MemberLoan) — same PII exposure as the Member's own,
        # but those models have no per-instance anonymization pass. Done LAST so
        # any reason the cancel cascade wrote is cleared too. ``.update`` avoids
        # re-running save()/clean() on rows tied to a now-scrubbed member and
        # emits no fresh auditlog diff (historical diffs are handled by
        # ``_scrub_auditlog_entries``).
        Subscription.objects.filter(member=member).exclude(
            cancellation_reason__isnull=True
        ).update(cancellation_reason=None)
        CoopShare.objects.filter(member=member).exclude(
            cancellation_reason__isnull=True
        ).update(cancellation_reason=None)
        MemberLoan.objects.filter(member=member).exclude(
            cancelled_reason__isnull=True
        ).update(cancelled_reason=None)

    @staticmethod
    def _anonymize_billing_profile(member: Member) -> None:
        """Scrub the SEPA mandate fields on the member's BillingProfile.

        Tricky bit: ``BillingProfile.clean()`` refuses to save when
        ``payment_method=SEPA_DIRECT_DEBIT and is_active=True`` and
        the mandate fields are empty. So we deactivate the profile
        first (one transaction, but two save calls — that's fine
        inside the surrounding ``@transaction.atomic``).
        """
        profile = BillingProfile.objects.filter(member=member).first()
        if profile is None:
            return

        # Step 1: deactivate so clean() doesn't block on missing mandate fields.
        profile.is_active = False
        profile.payment_method = PaymentMethodOptions.BANK_TRANSFER
        profile.save()

        # Step 2: scrub the PII columns via the central classification.
        # ``sepa_mandate_reference`` has unique=True; nulls don't
        # collide in Postgres, so None is safe even with multiple
        # anonymized profiles.
        _apply_classification(profile, "payments.BillingProfile")
        profile.save()

    @staticmethod
    def _anonymize_reseller_for_user(user: JasminUser) -> None:
        """Scrub the user's Reseller + its ContactEntity.

        ContactEntity is shared infrastructure — a single row can be
        referenced by multiple Resellers AND by DeliveryStations. We
        only wipe the contact if it's used solely by this user's
        Reseller; otherwise we log a warning and leave the contact
        intact (the other entity's legitimate business need wins).
        """
        reseller = Reseller.objects.filter(linked_user=user).first()
        if reseller is None:
            return

        # Scrub the Reseller's billing-side display fields via the
        # central classification; status transitions + the OneToOne
        # release stay inline (operational, not PII scrubs).
        _apply_classification(reseller, "commissioning.Reseller")
        reseller.is_active_reseller = False
        reseller.is_active_seller = False
        reseller.is_active_donation_recipient = False
        reseller.is_active_supplier = False
        reseller.linked_user = None  # release the OneToOne
        reseller.save()

        # The reseller's contact name is copied into every offer bulk-send
        # ``BackgroundJob.result`` payload and outlives Huey's TTL there, beyond
        # the classification walker's reach — scrub those copies (GDPR-DEL-3).
        GDPRService._scrub_reseller_name_in_background_jobs(reseller.id)

        contact = reseller.contact
        if contact is None:
            return

        # Safety: only wipe the contact if nobody else uses it.
        other_resellers = (
            Reseller.objects.filter(contact=contact).exclude(pk=reseller.pk).exists()
        )
        delivery_stations = DeliveryStation.objects.filter(contact=contact).exists()
        if other_resellers or delivery_stations:
            logger.warning(
                "gdpr.contact_entity_shared_kept "
                "contact_id=%s reseller_id=%s other_resellers=%s delivery_stations=%s "
                "— skipping contact wipe to preserve other entities' data",
                contact.pk,
                reseller.pk,
                other_resellers,
                delivery_stations,
            )
            return

        GDPRService._anonymize_contact_entity(contact)

    @staticmethod
    def _scrub_reseller_name_in_background_jobs(reseller_id) -> None:
        """Blank the anonymized reseller's ``reseller_name`` in every offer
        bulk-send ``BackgroundJob.result`` payload (a persisted copy of
        ``contact.name`` that survives the reseller/contact scrub). Uses a JSONB
        containment filter so only the affected rows are loaded."""
        from apps.notifications.models import BackgroundJob

        rid = str(reseller_id)
        jobs = BackgroundJob.objects.filter(
            result__results__contains=[{"reseller_id": rid}]
        )
        for job in jobs:
            changed = False
            for item in job.result.get("results", []):
                if (
                    isinstance(item, dict)
                    and item.get("reseller_id") == rid
                    and item.get("reseller_name") not in (None, "", "[anonymised]")
                ):
                    item["reseller_name"] = "[anonymised]"
                    changed = True
            if changed:
                job.save(update_fields=["result"])

    @staticmethod
    def _anonymize_contact_entity(contact: ContactEntity) -> None:
        """Scrub a ContactEntity row in place. The NOT-NULL fields
        (``address``, ``zip_code``, ``city``) are TOMBSTONE in the
        classification dict so they get placeholder values rather
        than NULL — delivery routing depends on those columns being
        non-empty for any DeliveryStation that references the contact."""
        _apply_classification(contact, "commissioning.ContactEntity")
        contact.save()

    @staticmethod
    def _scrub_logentries_for(model: type, pks: Any) -> None:
        """Bulk-blank the auditlog ``changes`` + ``object_repr`` for the
        ``model`` rows in ``pks``. One UPDATE per model regardless of
        row count (a heavy member/reseller can have thousands of
        ShareDelivery / OrderContent audit rows).

        ``object_pk`` is auditlog's string-PK column; JasminModel PKs are
        already strings, so the ``str()`` coercion is a no-op for safety.
        """
        from auditlog.models import LogEntry
        from django.contrib.contenttypes.models import ContentType

        pk_strs = [str(pk) for pk in pks]
        if not pk_strs:
            return
        content_type = ContentType.objects.get_for_model(model)
        LogEntry.objects.filter(
            content_type=content_type, object_pk__in=pk_strs
        ).update(changes=None, object_repr="[anonymised]")

    @staticmethod
    def _scrub_auditlog_entries(
        user: JasminUser,
        member: Member | None,
        reseller: Reseller | None,
    ) -> None:
        """Blank the django-auditlog diffs for every record the
        anonymization touched (Art. 17).

        The ``LogEntry`` rows themselves stay — "column X changed at
        time T by actor Y" remains provable — but ``changes`` (the
        old/new values: names, addresses, consent IP/UA, pre-mask IBAN
        edits) and ``object_repr`` (``str()`` of the instance, which for
        most of these models embeds the member's or reseller's name —
        e.g. ``"CoopShare 5 for Anna Müller"``, ``"Order #7 - Hof
        Müller - …"``) are wiped. ``mask_fields`` on the registrations
        only covers a subset of columns and only from the moment it was
        configured; this closes the historical tail.

        Coverage MUST track ``auditlog.register(...)`` across the apps
        (commissioning/apps.py, payments/apps.py): every registered
        model whose ``object_repr`` or diff can name the subject is
        scrubbed via its FK chain back to ``member`` / ``reseller``.
        ``ConsentDocument`` / ``PaymentCycle`` carry no subject PII and
        are intentionally omitted.
        """
        scrub = GDPRService._scrub_logentries_for

        scrub(type(user), [user.pk])
        scrub(
            UserInvitation,
            UserInvitation.objects.filter(user=user).values_list("pk", flat=True),
        )

        if member is not None:
            scrub(Member, [member.pk])
            scrub(
                BillingProfile,
                BillingProfile.objects.filter(member=member).values_list(
                    "pk", flat=True
                ),
            )
            scrub(
                ConsentRecord,
                ConsentRecord.objects.filter(member=member).values_list(
                    "pk", flat=True
                ),
            )
            scrub(
                CoopShare,
                CoopShare.objects.filter(member=member).values_list("pk", flat=True),
            )
            scrub(
                Subscription,
                Subscription.objects.filter(member=member).values_list("pk", flat=True),
            )
            scrub(
                ShareDelivery,
                ShareDelivery.objects.filter(subscription__member=member).values_list(
                    "pk", flat=True
                ),
            )

        if reseller is not None:
            scrub(Reseller, [reseller.pk])
            scrub(
                Order,
                Order.objects.filter(reseller=reseller).values_list("pk", flat=True),
            )
            scrub(
                OrderContent,
                OrderContent.objects.filter(order__reseller=reseller).values_list(
                    "pk", flat=True
                ),
            )
            scrub(
                InvoiceReseller,
                InvoiceReseller.objects.filter(reseller=reseller).values_list(
                    "pk", flat=True
                ),
            )
            scrub(
                InvoiceResellerContent,
                InvoiceResellerContent.objects.filter(
                    invoice__reseller=reseller
                ).values_list("pk", flat=True),
            )
            scrub(
                DeliveryNoteReseller,
                DeliveryNoteReseller.objects.filter(
                    order__reseller=reseller
                ).values_list("pk", flat=True),
            )
            scrub(
                DeliveryNoteContent,
                DeliveryNoteContent.objects.filter(
                    delivery_note__order__reseller=reseller
                ).values_list("pk", flat=True),
            )

            contact = reseller.contact
            if contact is not None:
                # Mirror ``_anonymize_reseller_for_user``: a contact
                # shared with other resellers / delivery stations keeps
                # its PII, so its audit history stays too.
                shared = (
                    Reseller.objects.filter(contact=contact)
                    .exclude(pk=reseller.pk)
                    .exists()
                    or DeliveryStation.objects.filter(contact=contact).exists()
                )
                if not shared:
                    scrub(ContactEntity, [contact.pk])

    @staticmethod
    def _anonymize_consent_records(member: Member) -> None:
        """Scrub the IP + user-agent capture on every ConsentRecord
        the member ever made. The row itself stays (legal audit trail
        of "consent given on <date> for <document>" + revocation tail);
        only the forensic-capture columns lose their PII link.

        Bulk ``.update`` keyed by the centralised classification —
        same pattern as ``_anonymize_email_logs``."""
        update_kwargs: dict[str, Any] = {}
        for field, (field_class, replacement) in get_classification(
            "commissioning.ConsentRecord"
        ).items():
            if field_class not in (FieldClass.PII_IMMEDIATE, FieldClass.TOMBSTONE):
                continue
            if callable(replacement):
                raise RuntimeError(
                    f"ConsentRecord.{field} replacement is a callable; "
                    "bulk-update path needs a static value."
                )
            update_kwargs[field] = replacement
        ConsentRecord.objects.filter(member=member).update(**update_kwargs)

    @staticmethod
    def _anonymize_user_invitations(user: JasminUser) -> None:
        """Scrub the recipient email on every historical invitation
        sent to the user. The token + status stay so the audit trail
        of who-was-invited-when remains intact.

        Per-instance loop (not a bulk ``.update``) so the
        FIELD_CLASSIFICATION lambda — which builds the placeholder
        from the row's ``user_id`` — fires for each row through the
        central ``_apply_classification``."""
        for invitation in UserInvitation.objects.filter(user=user):
            _apply_classification(invitation, "commissioning.UserInvitation")
            invitation.save()

    @staticmethod
    def _anonymize_email_logs(known_emails: set[str]) -> None:
        """Scrub recipient, subject, and error on every EmailLog row
        that was sent to any of the subject's known addresses.

        We KEEP the row (audit trail of "an email was sent on
        <date> for <purpose>"), but everything that can name the
        natural person goes: the recipient address, the rendered
        ``subject`` (tenant-editable templates can put the person's
        name in it — we can't police that), and the ``error`` text
        (bounce messages echo the address). The ``template`` +
        ``purpose`` columns keep the operational signal.

        Bulk ``.update`` here (not per-instance) because a heavy
        user can have thousands of EmailLog rows. Values come from
        ``FIELD_CLASSIFICATION`` — all EmailLog entries are static
        strings so the bulk update is safe.
        """
        if not known_emails:
            return
        update_kwargs: dict[str, Any] = {}
        for field, (field_class, replacement) in get_classification(
            "notifications.EmailLog"
        ).items():
            if field_class not in (FieldClass.PII_IMMEDIATE, FieldClass.TOMBSTONE):
                continue
            if callable(replacement):
                # Sanity guard: bulk update can't run a per-row
                # callable. If you're adding a per-row replacement
                # for EmailLog, switch this helper to a per-instance
                # loop like ``_anonymize_user_invitations``.
                raise RuntimeError(
                    f"EmailLog.{field} replacement is a callable; "
                    "bulk-update path needs a static value."
                )
            update_kwargs[field] = replacement
        EmailLog.objects.filter(_ci_recipient_q(known_emails)).update(**update_kwargs)

    @staticmethod
    def _purge_axes_records(known_emails: set[str]) -> None:
        """Delete axes login records keyed by the subject's emails:
        ``AccessLog`` (SUCCESSFUL logins — stores the username/email,
        ip_address and user_agent, see ``_sar_login_history``),
        ``AccessAttempt`` and ``AccessFailureLog`` (failed attempts).
        These are transient security records (no statutory retention) —
        hard-delete is the right action."""
        if not known_emails:
            return
        # Local import: ``django-axes`` is in TENANT_APPS so the
        # tables exist in tenant schemas; using a top-level import
        # would still work, but keeping the import local makes the
        # tenant-only dependency explicit.
        from axes.models import AccessAttempt, AccessFailureLog, AccessLog

        # Case-insensitive match: axes stores the credential as typed, so a
        # mixed-case login would survive an exact ``username__in`` purge.
        username_q = _ci_username_q(known_emails)
        AccessAttempt.objects.filter(username_q).delete()
        AccessFailureLog.objects.filter(username_q).delete()
        # Successful-login rows carry the subject's email/IP/UA in plaintext —
        # purge them too, or Art. 17 anonymization leaves them behind forever.
        AccessLog.objects.filter(username_q).delete()
