"""Anonymization engine — Art. 17 erasure via PII scrubbing."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction
from django.db.models import Model, Q, QuerySet

from apps.commissioning.models import (
    ConsentRecord,
    ContactEntity,
    CoopShare,
    CoopShareTransfer,
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
from .subject_emails import SubjectEmailKeys, subject_email_keys
from .subjects import ErasureSubject

if TYPE_CHECKING:
    # Type-only: the runtime path uses ``get_user_model()``, so this module
    # also works under a host project with a different ``AUTH_USER_MODEL``.
    from apps.accounts.models import JasminUser

    # ``GDPRService`` is assembled in the package ``__init__`` and bound into
    # this module's namespace there. Method bodies must resolve it at call
    # time through the ASSEMBLED class so monkeypatched attributes on
    # ``GDPRService`` are honoured.
    from . import GDPRService

logger = logging.getLogger("gdpr")


def _apply_classification(instance: Any, model_label: str) -> None:
    """Apply the PII_IMMEDIATE + TOMBSTONE entries from
    ``FIELD_CLASSIFICATION[model_label]`` to ``instance`` (in-memory;
    caller still has to ``.save()``).

    Skips ``PII_RETAINED`` (a future retention cron will handle those)
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
    def anonymize_user(user: JasminUser) -> DeletionLog:
        """Anonymize all personal data of a login user and of the member and
        reseller records tied to it (Art. 17). See :meth:`anonymize_subject`."""
        return GDPRService.anonymize_subject(ErasureSubject.of_user(user))

    @staticmethod
    @transaction.atomic
    def anonymize_subject(
        subject: ErasureSubject, *, replayed_log: DeletionLog | None = None
    ) -> DeletionLog:
        """Anonymize all personal data of ``subject`` (Art. 17): a login user,
        a member or reseller without one, or any combination.

        Replaces PII with placeholder values on every model that
        directly or indirectly holds the subject's data. Keeps the
        rows for referential integrity (statutory documents on the
        other side of FKs stay readable).

        Refuses with :class:`RetentionPeriodActive` (HTTP 409) when
        the subject still has statutory retention obligations. See
        :meth:`check_retention_blocks_for_subject` for the rules.

        Order of operations matters:

        1. **Work out the email keys** BEFORE any wipe — the subject's
           addresses and record links find the side-channel records
           (EmailLog, axes); see :mod:`.subject_emails`.
        2. **Anonymize primary records** (JasminUser, Member).
        3. **Anonymize related records via FK** (BillingProfile,
           Reseller + its ContactEntity, UserInvitation).
        4. **Scrub side-channel records** found by those keys (EmailLog,
           axes AccessLog / AccessAttempt / AccessFailureLog).
        5. **Log to DeletionLog** for backup-replay.

        ``replayed_log`` is set by the replay after a backup restore: an
        erasure the restore undid. Its row is written back with its original
        id and time instead of a new one.

        Wrapped in ``@transaction.atomic`` so a failure halfway
        through rolls back everything — you're never left with a
        half-anonymized user that the next call sees as already-done.
        """
        # Lock the member row and work on it as it is now. The instance the
        # subject was built with can be stale, and ``_anonymize_member`` saves
        # the row in full: an office cancellation committed in the meantime
        # would be overwritten and replaced by one dated today. Locked before
        # anything is written, as the cancellation path locks it too.
        if subject.member is not None:
            subject = replace(
                subject,
                member=Member.objects.select_for_update().get(pk=subject.member.pk),
            )

        reasons = GDPRService.check_retention_blocks_for_subject(subject)
        if reasons:
            raise RetentionPeriodActive(reasons)

        # The subject was resolved before any wipe: phase 3 releases
        # ``reseller.linked_user``, the key it was found by.
        user, member, reseller = subject.user, subject.member, subject.reseller

        # Phase 1: the keys the EmailLog + axes scrubs find the subject's
        # records by. Only the subject's own: an address someone else's record
        # holds too, or a row linked to someone else's record, stays untouched.
        email_keys = subject_email_keys(subject)
        original_email = subject.email

        # Phase 2: primary records.
        if user is not None:
            GDPRService._anonymize_jasmin_user(user)
        if member is not None:
            if user is None or member.user_id != user.pk:
                # A login of the member's outside the subject outlives the
                # erasure (``ErasureSubject.of_ex_member``). It is released, as
                # phase 3 releases a reseller's: the link would name the
                # anonymised member again. Saving the member without it
                # retracts the login's member role.
                member.user = None
            GDPRService._anonymize_member(member)
            GDPRService._anonymize_billing_profile(member)
            GDPRService._anonymize_consent_records(member)

        # Phase 3: FK-related records.
        if reseller is not None:
            GDPRService._anonymize_reseller(reseller)
        if user is not None:
            GDPRService._anonymize_user_invitations(user)

        # Phase 4: side-channel scrubs.
        GDPRService._anonymize_email_logs(email_keys)
        GDPRService._purge_axes_records(email_keys)

        # Phase 4.6: purge the plaintext SEPA export. pain.008 files embed the
        # debtor name + IBAN in cleartext (the encrypted DB columns are scrubbed
        # above, but the on-disk file is not). By the time a member is anonymised
        # (10y after exit) every billing run that debited them predates the exit
        # and is therefore itself past the 10y GoBD/UStG retention, so the file
        # may be erased (Art. 17). The BillingRun row — the financial record —
        # is kept; only the plaintext file is removed.
        if member is not None:
            GDPRService._purge_member_sepa_exports(member)

        # Phase 4.5: auditlog diffs. ``LogEntry.changes`` rows for the
        # scrubbed records hold pre-anonymization values (name changes,
        # invoice address snapshots, consent IP/UA, ...) —
        # ``mask_fields`` only covers a subset of columns.
        GDPRService._scrub_auditlog_entries(user, member, reseller)

        # Phase 5: audit trail (for backup-replay + auditor proof).
        if replayed_log is not None:
            # ``deleted_at`` is ``auto_now_add``, which overwrites it on
            # insert: put the original time back afterwards.
            deleted_at = replayed_log.deleted_at
            replayed_log.save(force_insert=True)
            DeletionLog.objects.filter(pk=replayed_log.pk).update(deleted_at=deleted_at)
            replayed_log.deleted_at = deleted_at
            return replayed_log
        return DeletionLog.objects.create(
            user_email=original_email,
            user_pk=user.pk if user is not None else "",
            member_pk=member.pk if member is not None else "",
            reseller_pk=reseller.pk if reseller is not None else "",
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
    def _anonymize_jasmin_user(user: JasminUser) -> None:
        """Scrub the JasminUser row in place.

        Field-set replacements come from ``FIELD_CLASSIFICATION``;
        the operational ``is_active`` / ``account_status`` flips
        stay inline because they're status transitions, not PII
        scrubs.
        """
        # Remove the uploaded avatar FILE from storage BEFORE the
        # classification nulls the column — assigning None to an ImageField
        # only clears the path, leaving the image (a photo of the data subject)
        # on disk, which would survive Art. 17 erasure. Mirrors the FileField
        # delete used for ``run.sepa_xml_export`` elsewhere in this module.
        if user.avatar:
            user.avatar.delete(save=False)
        _apply_classification(user, settings.AUTH_USER_MODEL)
        user.is_active = False
        user.account_status = "inactive"
        user.save()

    @staticmethod
    def _anonymize_member(member: Member) -> None:
        """Scrub the Member row in place. Field-set from
        ``FIELD_CLASSIFICATION``; status transitions inline.

        ``member`` is the row as it is now, locked by
        :meth:`anonymize_subject` — the full save below would otherwise write
        a stale copy back."""
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

        # Coop share transfers keep amounts and dates (GenG equity history), but
        # their notes name both members: the transfer's own note and the notes of
        # the rows it created, on this member's side AND the other member's.
        _, note_replacement = get_classification("commissioning.CoopShareTransfer")[
            "note"
        ]
        transfers = GDPRService._coop_share_transfers_of(member)
        transfers.exclude(note__isnull=True).update(note=note_replacement)
        CoopShare.objects.filter(transfer__in=transfers).exclude(
            note__isnull=True
        ).update(note=note_replacement)

    @staticmethod
    def _coop_share_transfers_of(member: Member) -> QuerySet[CoopShareTransfer]:
        """Transfers the member gave or received coop shares in."""
        return CoopShareTransfer.objects.filter(
            Q(from_member=member) | Q(to_member=member)
        )

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
    def _purge_reseller_documents(reseller: Reseller) -> None:
        """Delete the plaintext rendered invoice / delivery-note PDFs (and the
        ZUGFeRD XML) of ``reseller``. Their recipient block embeds the reseller's
        name + postal address in cleartext, so they'd otherwise survive Art. 17
        erasure on disk (recoverable from any media backup). Keeps the rows (GoBD
        audit trail); only the on-disk artifacts are purged.

        Same belt-and-braces retention gate as ``_purge_member_sepa_exports``: a
        reseller anonymised 10y after their last activity can only have documents
        older than the window, but never erase one still inside it. ``file`` /
        ``xml_file`` are in InvoiceReseller's (and ``file`` in
        DeliveryNoteReseller's) finalized-update allowlist, so clearing them is
        permitted even on a finalized row. The immutable ``recipient_snapshot``
        JSON is deliberately left — it is sealed into ``document_hash`` and can't
        be scrubbed without breaking the GoBD document integrity the trigger
        protects; the file purge is what removes the readable copy.
        """
        from apps.commissioning.models import DeliveryNoteReseller, InvoiceReseller

        from ..tasks import _retention_cutoff

        cutoff = _retention_cutoff()

        for invoice in InvoiceReseller.objects.filter(reseller=reseller):
            if invoice.date and invoice.date > cutoff:
                continue
            cleared = []
            for field_name in ("file", "xml_file"):
                field_file = getattr(invoice, field_name)
                if field_file:
                    field_file.delete(save=False)
                    cleared.append(field_name)
            if cleared:
                invoice.save(update_fields=cleared)

        for note in DeliveryNoteReseller.objects.filter(order__reseller=reseller):
            if note.date and note.date > cutoff:
                continue
            if note.file:
                note.file.delete(save=False)
                note.save(update_fields=["file"])

    @staticmethod
    def _anonymize_reseller(reseller: Reseller) -> None:
        """Scrub the Reseller + its ContactEntity.

        ContactEntity is shared infrastructure — a single row can be
        referenced by multiple Resellers AND by DeliveryStations. We
        only wipe the contact if it's used solely by this Reseller;
        otherwise we log a warning and leave the contact intact (the
        other entity's legitimate business need wins).
        """
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
        # the classification walker's reach — scrub those copies.
        GDPRService._scrub_reseller_name_in_background_jobs(reseller.id)

        # Purge the plaintext rendered documents (invoice / delivery-note PDFs +
        # ZUGFeRD XML) whose recipient block embeds the (sole-trader) reseller's
        # name + postal address — else they survive Art. 17 erasure on disk.
        GDPRService._purge_reseller_documents(reseller)

        contact = reseller.contact

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
        """Bulk-blank the auditlog diffs (``changes``, the older
        ``changes_text`` and ``serialized_data``) and ``object_repr`` for
        the ``model`` rows in ``pks``. One UPDATE per model regardless of
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
        ).update(
            changes=None,
            changes_text="",
            serialized_data=None,
            object_repr="[anonymised]",
        )

    @staticmethod
    def _deleted_rows_named_in_logentries(
        model: type[Model], field: str, parent_pks: Iterable[Any]
    ) -> set[str]:
        """Pks of deleted ``model`` rows whose audit entries record one of
        ``parent_pks`` in the foreign key ``field``.

        A queryset no longer finds a deleted row, but the CREATE and DELETE
        entries it left behind still store its foreign keys, each as an
        ``[old, new]`` pair of strings.
        """
        from auditlog.models import LogEntry
        from django.contrib.contenttypes.models import ContentType
        from django.db.models.fields.json import KT

        parents = [str(pk) for pk in parent_pks]
        if not parents:
            return set()
        logged = set(
            LogEntry.objects.filter(
                content_type=ContentType.objects.get_for_model(model),
                action__in=(LogEntry.Action.CREATE, LogEntry.Action.DELETE),
            )
            .annotate(
                old_parent=KT(f"changes__{field}__0"),
                new_parent=KT(f"changes__{field}__1"),
            )
            .filter(Q(old_parent__in=parents) | Q(new_parent__in=parents))
            .values_list("object_pk", flat=True)
        )
        if not logged:
            return set()
        live = model._base_manager.filter(pk__in=logged).values_list("pk", flat=True)
        return logged - {str(pk) for pk in live}

    @staticmethod
    def _remove_note_from_logentries(model: type, pks: Any) -> None:
        """Drop the ``note`` key from the auditlog diffs of the ``model`` rows in
        ``pks``; the rest of each diff and ``object_repr`` stay."""
        from auditlog.models import LogEntry
        from django.contrib.contenttypes.models import ContentType
        from django.db.models.expressions import RawSQL

        pk_strs = [str(pk) for pk in pks]
        if not pk_strs:
            return
        LogEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(model),
            object_pk__in=pk_strs,
            changes__has_key="note",
        ).update(changes=RawSQL("changes - 'note'", []))

    @staticmethod
    def _scrub_auditlog_entries(
        user: JasminUser | None,
        member: Member | None,
        reseller: Reseller | None,
    ) -> None:
        """Blank the django-auditlog diffs for every record the
        anonymization touched (Art. 17).

        The ``LogEntry`` rows themselves stay — "column X changed at
        time T by actor Y" remains provable — but ``changes`` (the
        old/new values: names, invoice address snapshots, consent IP/UA,
        notes) and ``object_repr`` (``str()`` of the instance, which for
        most of these models embeds the member's or reseller's name —
        e.g. ``"CoopShare 5 for Anna Müller"``, ``"Order #7 - Hof
        Müller - …"``) are wiped. ``mask_fields`` on the registrations
        only covers a subset of columns; this wipes the rest. Records are
        found through their live rows and, once deleted (a draft
        subscription, the future deliveries a cancellation removes, an
        unconfirmed coop share, a draft order), through the foreign keys
        their CREATE and DELETE entries store.

        The entries the subject made as the acting user lose the email
        address and the IP address recorded next to them; the actor link
        to the anonymized user stays.

        Coverage MUST track ``auditlog.register(...)`` across the apps
        (commissioning/apps.py, payments/apps.py): every registered
        model whose ``object_repr`` or diff can name the subject is
        scrubbed via its FK chain back to ``member`` / ``reseller``.
        ``ConsentDocument`` / ``PaymentCycle`` carry no subject PII and
        are intentionally omitted.
        """
        from auditlog.models import LogEntry

        scrub = GDPRService._scrub_logentries_for
        deleted = GDPRService._deleted_rows_named_in_logentries

        def pks(queryset: QuerySet[Any]) -> set[str]:
            return {str(pk) for pk in queryset.values_list("pk", flat=True)}

        if user is not None:
            scrub(type(user), [user.pk])
            scrub(UserInvitation, pks(UserInvitation.objects.filter(user=user)))
            LogEntry.objects.filter(actor=user).update(
                actor_email=None, remote_addr=None
            )

        if member is not None:
            member_pks = [member.pk]
            scrub(Member, member_pks)
            for model in (BillingProfile, ConsentRecord, CoopShare):
                scrub(
                    model,
                    pks(model.objects.filter(member=member))
                    | deleted(model, "member", member_pks),
                )
            # A transfer's note and the notes of the other member's rows it created
            # name this member; the rest of those records is the other member's
            # history, so only the note leaves their diffs.
            transfers = (
                pks(GDPRService._coop_share_transfers_of(member))
                | deleted(CoopShareTransfer, "from_member", member_pks)
                | deleted(CoopShareTransfer, "to_member", member_pks)
            )
            remove_note = GDPRService._remove_note_from_logentries
            remove_note(CoopShareTransfer, transfers)
            remove_note(
                CoopShare,
                pks(
                    CoopShare.objects.filter(transfer__in=transfers).exclude(
                        member=member
                    )
                )
                | deleted(CoopShare, "transfer", transfers),
            )
            subscriptions = pks(Subscription.objects.filter(member=member)) | deleted(
                Subscription, "member", member_pks
            )
            scrub(Subscription, subscriptions)
            scrub(
                ShareDelivery,
                pks(ShareDelivery.objects.filter(subscription__member=member))
                | deleted(ShareDelivery, "subscription", subscriptions),
            )

        if reseller is not None:
            reseller_pks = [reseller.pk]
            scrub(Reseller, reseller_pks)
            orders = pks(Order.objects.filter(reseller=reseller)) | deleted(
                Order, "reseller", reseller_pks
            )
            scrub(Order, orders)
            scrub(
                OrderContent,
                pks(OrderContent.objects.filter(order__reseller=reseller))
                | deleted(OrderContent, "order", orders),
            )
            invoices = pks(InvoiceReseller.objects.filter(reseller=reseller)) | deleted(
                InvoiceReseller, "reseller", reseller_pks
            )
            scrub(InvoiceReseller, invoices)
            scrub(
                InvoiceResellerContent,
                pks(InvoiceResellerContent.objects.filter(invoice__reseller=reseller))
                | deleted(InvoiceResellerContent, "invoice", invoices),
            )
            delivery_notes = pks(
                DeliveryNoteReseller.objects.filter(order__reseller=reseller)
            ) | deleted(DeliveryNoteReseller, "order", orders)
            scrub(DeliveryNoteReseller, delivery_notes)
            scrub(
                DeliveryNoteContent,
                pks(
                    DeliveryNoteContent.objects.filter(
                        delivery_note__order__reseller=reseller
                    )
                )
                | deleted(DeliveryNoteContent, "delivery_note", delivery_notes),
            )

            # Mirror ``_anonymize_reseller``: a contact shared with
            # other resellers / delivery stations keeps its PII, so its audit
            # history stays too.
            contact = reseller.contact
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
    def _anonymize_email_logs(email_keys: SubjectEmailKeys) -> None:
        """Scrub recipient, subject, and error on every EmailLog row of the
        subject: linked to one of their records, or sent to one of their own
        addresses (:meth:`SubjectEmailKeys.email_log_q`).

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
        email_log_q = email_keys.email_log_q()
        if email_log_q is None:
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
        EmailLog.objects.filter(email_log_q).update(**update_kwargs)

    @staticmethod
    def _purge_axes_records(email_keys: SubjectEmailKeys) -> None:
        """Delete axes login records keyed by the subject's own addresses:
        ``AccessLog`` (SUCCESSFUL logins — stores the username/email,
        ip_address and user_agent, see ``_sar_login_history``),
        ``AccessAttempt`` and ``AccessFailureLog`` (failed attempts).
        These are transient security records (no statutory retention) —
        hard-delete is the right action."""
        username_q = email_keys.login_q()
        if username_q is None:
            return
        # Local import: ``django-axes`` is in TENANT_APPS so the
        # tables exist in tenant schemas; using a top-level import
        # would still work, but keeping the import local makes the
        # tenant-only dependency explicit.
        from axes.models import AccessAttempt, AccessFailureLog, AccessLog

        # Case-insensitive match: axes keys its rows by the lower-cased
        # address, so an address stored with capitals would miss them in an
        # exact ``username__in`` purge.
        AccessAttempt.objects.filter(username_q).delete()
        AccessFailureLog.objects.filter(username_q).delete()
        # Successful-login rows carry the subject's email/IP/UA in plaintext —
        # purge them too, or Art. 17 anonymization leaves them behind forever.
        AccessLog.objects.filter(username_q).delete()
