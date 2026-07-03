"""Tests that ``GDPRService.anonymize_user`` scrubs every PII column
on the ``Member`` row.

The retention-block tests (``test_retention_blocks.py``) and the
extended-anonymization tests (``test_extended_anonymization.py``)
cover the surrounding pipeline. This file owns the
member-scrub-completeness check: one explicit assertion per
PII-bearing field, so any future column added to ``Member`` lands
either in this test (✓ classified) or in the
``test_field_classification_guard`` (✗ unclassified → CI fails).

Regression context: ``birth_date`` was added to ``Member`` in
2026-06 (GenG §30 audit). It was surfaced in the SAR bundle but
NOT registered in ``FIELD_CLASSIFICATION``, so anonymization
silently left the real date of birth on the row. The classification
guard didn't catch it because it only walked text-typed fields.
"""

from __future__ import annotations

import datetime

import pytest
from django.db.models import F

from apps.commissioning.models import CoopShare
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
)
from apps.gdpr.services import GDPRService


@pytest.mark.django_db
class TestMemberAnonymization:
    def test_birth_date_is_scrubbed(self, tenant):
        """DoB is directly-identifying PII — must be NULLed on
        anonymization. Regression test for the 2026-06 gap where the
        field shipped without a classification entry."""
        user = JasminUserFactory()
        member = MemberFactory(
            user=user,
            birth_date=datetime.date(1985, 3, 14),
        )

        GDPRService.anonymize_user(user)

        member.refresh_from_db()
        assert member.birth_date is None, (
            "birth_date survived anonymisation — check "
            "FIELD_CLASSIFICATION['commissioning.Member']"
        )

    def test_full_identity_block_is_scrubbed(self, tenant):
        """One pass across every identity column on the Member to
        catch any future addition that ships without a classification
        entry (defence in depth on top of the field-classification
        guard)."""
        user = JasminUserFactory()
        member = MemberFactory(
            user=user,
            first_name="Alice",
            last_name="Beispiel",
            company_name="Acme",
            email="alice@example.com",
            email_2="alice2@example.com",
            email_3="alice3@example.com",
            pickup_name="Alice B.",
            address="Marktplatz 1",
            zip_code="12345",
            city="Beispielstadt",
            country="DE",
            account_owner="Alice Beispiel",
            iban="DE89370400440532013000",
            note="internal note",
            birth_date=datetime.date(1985, 3, 14),
        )

        GDPRService.anonymize_user(user)

        member.refresh_from_db()
        # TOMBSTONE fields → "Gelöscht" (not NULL — so the row still
        # has a sortable name on the legal Mitgliederliste).
        assert member.first_name == "Gelöscht"
        assert member.last_name == "Gelöscht"
        # PII_IMMEDIATE fields → NULL / empty.
        assert member.company_name is None
        assert member.email is None
        assert member.email_2 is None
        assert member.email_3 is None
        assert member.pickup_name is None
        assert member.address is None
        assert member.zip_code is None
        assert member.city is None
        assert member.country is None
        assert member.account_owner is None
        assert member.note is None
        assert member.birth_date is None
        # iban: PII_IMMEDIATE with explicit empty-string replacement
        # (not None) because the IBANValidator on the column rejects
        # None; "" survives validation + leaks zero info.
        assert str(member.iban) == ""

    def test_anonymise_persists_scrub_when_member_already_cancelled(self, tenant):
        """Production flow: admin cancels the member via
        ``cancel_member_with_coop_shares`` (stamping member + cascading
        the shares' cancellation timestamps), THEN runs the GDPR
        anonymisation. Locks the Bug A regression end-to-end:

        - ``_anonymize_member`` scrubs PII columns + sets
          ``is_active=False`` and persists with ``member.save()`` —
          NOT lost by a follow-on ``save(update_fields=[3])``.
        - Pre-existing cancellation timestamps on the shares are
          preserved (the soft-retention rule: anonymisation doesn't
          rewrite historical equity dates).

        Retention means ``check_retention_blocks`` only passes once the
        equity is both cancelled AND paid back (GenG §73 Auseinandersetzung)
        — that's why the production flow cancels, returns the equity, then
        deletes.
        """
        from apps.commissioning.services.member_cancellation import (
            cancel_member_with_coop_shares,
        )

        user = JasminUserFactory(email="alice@example.com")
        member = MemberFactory(
            user=user,
            first_name="Alice",
            email="alice@example.com",
            birth_date=datetime.date(1985, 3, 14),
        )
        share_a = CoopShareFactory(member=member)
        share_b = CoopShareFactory(member=member)

        # Step 1 — office cancels the member (cascade stamps shares).
        cancel_member_with_coop_shares(member)
        # Equity is returned to the member — office stamps ``paid_back_date``.
        # Until this happens the GenG §73 retention obligation blocks
        # anonymisation even though the shares are already cancelled.
        CoopShare.objects.filter(member=member).update(
            paid_back_date=F("payback_due_date")
        )
        member.refresh_from_db()
        share_a.refresh_from_db()
        share_b.refresh_from_db()
        cancelled_at_snapshot = member.cancelled_at
        assert share_a.cancelled_at == cancelled_at_snapshot

        # Step 2 — GDPR anonymisation runs (retention check now passes
        # because the equity is cancelled AND paid back).
        GDPRService.anonymize_user(user)

        member.refresh_from_db()
        share_a.refresh_from_db()
        share_b.refresh_from_db()

        # (1) Scrub committed — the bug was here.
        assert member.first_name == "Gelöscht"
        assert member.email is None
        assert member.birth_date is None
        assert member.is_active is False
        # (2) Member's cancellation date is the one from Step 1,
        # NOT overwritten by anonymisation.
        assert member.cancelled_at == cancelled_at_snapshot
        # (3) Share dates also preserved — equity-history integrity.
        assert share_a.cancelled_at == cancelled_at_snapshot
        assert share_b.cancelled_at == cancelled_at_snapshot

    def test_anonymise_cancels_member_when_no_shares_held(self, tenant):
        """Edge case: trial member or fresh sign-up with zero
        CoopShares. Retention check passes immediately; the cascade
        runs inside ``_anonymize_member`` and stamps the Member's
        ``cancelled_at``. Sanity-check the safety-net branch."""
        user = JasminUserFactory(email="bob@example.com")
        member = MemberFactory(user=user, first_name="Bob")
        assert not CoopShare.objects.filter(member=member).exists()
        assert member.cancelled_at is None

        GDPRService.anonymize_user(user)

        member.refresh_from_db()
        assert member.first_name == "Gelöscht"
        assert member.cancelled_at is not None
        assert member.cancelled_effective_at is not None

    def test_cancellation_reasons_scrubbed_on_anonymize(self, tenant):
        """GDPR-DEL-2: free-text cancellation reasons on the Member AND its
        Subscription / MemberLoan rows are scrubbed on erasure (they routinely
        hold PII and previously survived anonymization)."""
        from apps.commissioning.models import MemberLoan, Subscription
        from apps.commissioning.tests.factories import SubscriptionFactory

        user = JasminUserFactory(email="reason@example.com")
        member = MemberFactory(
            user=user, cancellation_reason="moved to Berliner Str. 5"
        )
        # An ended (past) subscription — the realistic state for one carrying a
        # cancellation reason; also keeps it out of the active-subscription
        # retention block so anonymization can proceed.
        sub = SubscriptionFactory(
            member=member,
            cancellation_reason="too expensive",
            valid_from=datetime.date(2020, 1, 6),  # Monday
            valid_until=datetime.date(2020, 12, 27),  # Sunday
            default_delivery_station_day=None,  # skip the factory's DSD-coverage check
            # Already cancelled (past) — keeps it out of the active-subscription
            # retention block and out of the anonymize cancel-cascade.
            cancelled_at=datetime.datetime(2020, 6, 1, tzinfo=datetime.UTC),
            cancelled_effective_at=datetime.date(2020, 6, 7),
        )
        loan = MemberLoan.objects.create(
            member=member,
            amount=100,
            interest_rate=0,
            start_date=datetime.date(2020, 1, 6),
            cancelled_reason="changed my mind",
        )

        GDPRService.anonymize_user(user)

        member.refresh_from_db()
        sub.refresh_from_db()
        loan.refresh_from_db()
        assert member.cancellation_reason is None
        assert Subscription.objects.get(pk=sub.pk).cancellation_reason is None
        assert loan.cancelled_reason is None

    def test_reseller_name_scrubbed_in_background_job_results(self, tenant):
        """GDPR-DEL-3: the anonymized reseller's name, copied into offer
        bulk-send ``BackgroundJob.result`` payloads, is blanked while the
        ``reseller_id`` (a non-PII correlator) is preserved."""
        from apps.commissioning.tests.factories import ResellerFactory
        from apps.notifications.models import BackgroundJob

        user = JasminUserFactory(email="reseller@example.com")
        reseller = ResellerFactory(linked_user=user)
        job = BackgroundJob.objects.create(
            kind="offer_bulk_send",
            result={
                "results": [
                    {
                        "reseller_id": str(reseller.id),
                        "reseller_name": "Bio Müller GmbH",
                        "success": True,
                    }
                ]
            },
        )

        GDPRService.anonymize_user(user)

        job.refresh_from_db()
        item = job.result["results"][0]
        assert item["reseller_name"] == "[anonymised]"
        assert item["reseller_id"] == str(reseller.id)

    def test_auditlog_diffs_are_scrubbed(self, tenant):
        """Historical auditlog entries hold pre-anonymization values
        in ``changes`` (e.g. a first_name edit stores old AND new
        name) and the person's name in ``object_repr``. Both must be
        wiped by ``anonymize_user`` — ``mask_fields`` doesn't cover
        name columns and never rewrites history."""
        from auditlog.models import LogEntry

        user = JasminUserFactory(email="carla@example.com")
        member = MemberFactory(user=user, first_name="Carla", last_name="Beispiel")
        # Produce an UPDATE diff that contains the real name.
        member.first_name = "Carlotta"
        member.save()

        entries = LogEntry.objects.get_for_object(member)
        assert entries.exists(), (
            "Member saves should produce auditlog entries — is the "
            "auditlog registration in commissioning/apps.py gone?"
        )
        assert any(entry.changes and "first_name" in entry.changes for entry in entries)

        GDPRService.anonymize_user(user)

        for entry in LogEntry.objects.get_for_object(member):
            assert entry.changes is None
            assert entry.object_repr == "[anonymised]"

    def test_auditlog_scrub_covers_member_linked_models(self, tenant):
        """The scrub must reach every auditlog-registered model whose
        ``object_repr`` names the member, not just the Member row — a
        CoopShare's repr is ``"CoopShare N for <member>"``. Regression
        guard for the 2026-06-12 completeness gap."""
        from auditlog.models import LogEntry

        from apps.commissioning.services.member_cancellation import (
            cancel_member_with_coop_shares,
        )

        user = JasminUserFactory(email="dora@example.com")
        member = MemberFactory(user=user, first_name="Dora", last_name="Beispiel")
        share = CoopShareFactory(member=member)
        # The CoopShare repr embeds the member name in object_repr.
        share_entries = LogEntry.objects.get_for_object(share)
        assert share_entries.exists()
        assert any("Dora" in (e.object_repr or "") for e in share_entries)

        # Production flow: cancel the member and return the equity
        # (clears the CoopShare retention block) before anonymising. The
        # CoopShare ROW stays for the GenG paper trail — but its auditlog
        # repr must lose the member name.
        cancel_member_with_coop_shares(member)
        CoopShare.objects.filter(member=member).update(
            paid_back_date=F("payback_due_date")
        )
        GDPRService.anonymize_user(user)

        for entry in LogEntry.objects.get_for_object(share):
            assert entry.object_repr == "[anonymised]", (
                "CoopShare auditlog repr still names the deleted member — "
                "_scrub_auditlog_entries coverage drifted from "
                "auditlog.register(...) in commissioning/apps.py"
            )


@pytest.mark.django_db
class TestSepaExportPurge:
    """GDPR-2: a billing run's pain.008 file embeds the debtor name + IBAN in
    cleartext. When a member is anonymised (10y post-exit) every run that
    debited them is itself past retention, so anonymisation must erase the
    on-disk file while keeping the BillingRun row (the financial record)."""

    def test_past_retention_sepa_file_is_erased_row_kept(self, tenant):
        from datetime import timedelta
        from decimal import Decimal

        from django.core.files.base import ContentFile
        from django.utils import timezone

        from apps.commissioning.tests.factories import SubscriptionFactory
        from apps.gdpr.tasks import _retention_cutoff
        from apps.payments.models import (
            BillingRun,
            BillingRunStatus,
            ChargeSchedule,
            ChargeStatus,
            PaymentMethodOptions,
        )

        user = JasminUserFactory()
        member = MemberFactory(user=user)
        old = _retention_cutoff() - timedelta(days=30)  # comfortably past 10y

        run = BillingRun.objects.create(
            period_start=old,
            period_end=old + timedelta(days=27),
            collection_date=old + timedelta(days=5),
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            status=BillingRunStatus.DRAFT,
            total_amount=Decimal("25.00"),
            charge_count=1,
            msg_id="BR-OLD",
        )
        run.sepa_xml_export.save("old.xml", ContentFile(b"<Document/>"), save=True)
        # created_at is auto_now_add (== now); .update() bypasses it to back-date.
        BillingRun.objects.filter(pk=run.pk).update(
            created_at=timezone.make_aware(
                datetime.datetime.combine(old, datetime.time.min)
            )
        )
        ChargeSchedule.objects.create(
            member=member,
            subscription=SubscriptionFactory(),
            period_start=old,
            period_end=old + timedelta(days=27),
            due_date=old,
            expected_amount=Decimal("25.00"),
            currency="EUR",
            description="old charge",
            status=ChargeStatus.PAID,  # terminal — not an open retention block
            billing_run=run,
        )
        assert run.sepa_xml_export.name  # file present before anonymisation

        GDPRService.anonymize_user(user)

        run.refresh_from_db()
        assert not run.sepa_xml_export  # plaintext SEPA file erased
        assert BillingRun.objects.filter(pk=run.pk).exists()  # record kept

    def test_within_retention_sepa_file_is_kept(self, tenant):
        # Belt-and-braces gate: a run still inside its retention window must NOT
        # be erased even if (hypothetically) it bills an anonymised member.
        from datetime import timedelta
        from decimal import Decimal

        from django.core.files.base import ContentFile
        from django.utils import timezone

        from apps.commissioning.tests.factories import SubscriptionFactory
        from apps.payments.models import (
            BillingRun,
            BillingRunStatus,
            ChargeSchedule,
            ChargeStatus,
            PaymentMethodOptions,
        )

        user = JasminUserFactory()
        member = MemberFactory(user=user)
        recent = timezone.localdate() - timedelta(days=30)  # well within 10y

        run = BillingRun.objects.create(
            period_start=recent,
            period_end=recent + timedelta(days=27),
            collection_date=recent + timedelta(days=5),
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            status=BillingRunStatus.DRAFT,
            total_amount=Decimal("25.00"),
            charge_count=1,
            msg_id="BR-RECENT",
        )
        run.sepa_xml_export.save("recent.xml", ContentFile(b"<Document/>"), save=True)
        ChargeSchedule.objects.create(
            member=member,
            subscription=SubscriptionFactory(),
            period_start=recent,
            period_end=recent + timedelta(days=27),
            due_date=recent,
            expected_amount=Decimal("25.00"),
            currency="EUR",
            description="recent charge",
            status=ChargeStatus.PAID,  # terminal — not an open retention block
            billing_run=run,
        )

        GDPRService.anonymize_user(user)

        run.refresh_from_db()
        assert run.sepa_xml_export.name  # still within retention — kept
