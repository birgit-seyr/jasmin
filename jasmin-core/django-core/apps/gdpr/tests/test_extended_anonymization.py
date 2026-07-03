"""Tests for the extended anonymization pipeline.

Once ``GDPRService.check_retention_blocks`` passes, ``anonymize_user``
must scrub EVERY PII-bearing model, not just JasminUser + Member.

One test class per model the extended pipeline touches:

  - BillingProfile (encrypted IBAN / BIC / account_holder, mandate ref)
  - Reseller (invoice_* display fields) + ContactEntity (contact info)
  - UserInvitation (recipient email on historic invitations)
  - EmailLog (recipient on every email ever sent to them)
  - axes AccessLog (successful logins) + AccessAttempt +
    AccessFailureLog (failed logins) — purge entirely

Plus a guard test that the contact-shared safety branch leaves a
shared ContactEntity alone — important because a Reseller's contact
might also be referenced by a DeliveryStation, and we must not wipe
delivery-station data from under it.
"""

from __future__ import annotations

import datetime

import pytest
from axes.models import AccessAttempt, AccessFailureLog, AccessLog

from apps.commissioning.models import (
    UserInvitation,
)
from apps.commissioning.tests.factories import (
    ContactEntityFactory,
    JasminUserFactory,
    MemberFactory,
    ResellerFactory,
)
from apps.gdpr.services import GDPRService
from apps.notifications.models import EmailLog
from apps.payments.constants import PaymentMethodOptions
from apps.payments.models import BillingProfile


@pytest.mark.django_db
class TestBillingProfileAnonymization:
    def test_sepa_fields_scrubbed(self, tenant):
        """All encrypted bank-identifier fields end up empty, the
        unique mandate reference is nulled, the profile is deactivated
        (so the SEPA-required-fields ``clean()`` check stops applying)."""
        user = JasminUserFactory(email="member@example.com")
        member = MemberFactory(user=user)
        profile = BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            iban="DE89370400440532013000",
            account_holder="Anna Member",
            sepa_mandate_reference="MND-2026-0001",
            sepa_mandate_signed_at=datetime.date(2026, 1, 5),
            is_active=True,
        )

        GDPRService.anonymize_user(user)

        profile.refresh_from_db()
        assert profile.iban == ""
        assert profile.account_holder == ""
        assert profile.sepa_mandate_reference is None
        assert profile.sepa_mandate_signed_at is None
        assert profile.sepa_mandate_first_use_at is None
        assert profile.is_active is False
        assert profile.payment_method == PaymentMethodOptions.BANK_TRANSFER

    def test_no_billing_profile_is_fine(self, tenant):
        """User without a BillingProfile (e.g. staff) doesn't crash."""
        user = JasminUserFactory()
        MemberFactory(user=user)
        # No BillingProfile created. Should still succeed.
        GDPRService.anonymize_user(user)

    def test_multiple_anonymizations_dont_collide_on_mandate_uniq(self, tenant):
        """``sepa_mandate_reference`` is ``unique=True``. After we set
        it to None on multiple anonymized profiles, Postgres treats
        NULLs as non-equal — so no UNIQUE-violation.

        IBAN is reused across all three profiles because: (a) it isn't
        a unique field on BillingProfile, (b) this test exercises
        mandate-reference handling, not IBAN handling, and (c) the
        ``IBANValidator`` on the model rejects fictional IBANs with
        manufactured tails — only known-valid IBANs satisfy mod-97."""
        valid_iban = "DE89370400440532013000"
        for i in range(3):
            user = JasminUserFactory(email=f"m{i}@example.com")
            member = MemberFactory(user=user)
            BillingProfile.objects.create(
                member=member,
                payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
                iban=valid_iban,
                account_holder=f"M {i}",
                sepa_mandate_reference=f"MND-2026-{i:04d}",
                sepa_mandate_signed_at=datetime.date(2026, 1, 5),
                is_active=True,
            )
            GDPRService.anonymize_user(user)

        # All three profiles should have NULL mandate references with
        # no constraint violation.
        assert (
            BillingProfile.objects.filter(sepa_mandate_reference__isnull=True).count()
            == 3
        )


@pytest.mark.django_db
class TestResellerAnonymization:
    def test_invoice_display_fields_scrubbed(self, tenant):
        user = JasminUserFactory()
        reseller = ResellerFactory(
            linked_user=user,
            name_for_member_pages="Big Customer GmbH",
            invoice_name="Big Customer GmbH",
            invoice_name2="z.H. Anna Müller",
            invoice_address="Hauptstr. 1",
            invoice_plz="10115",
            invoice_city="Berlin",
            invoice_email="billing@bigcustomer.example",
            note="VIP customer, calls every Friday",
            is_active_reseller=True,
        )

        GDPRService.anonymize_user(user)

        reseller.refresh_from_db()
        assert reseller.name_for_member_pages == "Gelöscht"
        assert reseller.invoice_name is None
        assert reseller.invoice_name2 is None
        assert reseller.invoice_address is None
        assert reseller.invoice_plz is None
        assert reseller.invoice_city is None
        assert reseller.invoice_email is None
        assert reseller.note is None
        assert reseller.is_active_reseller is False
        # ``linked_user`` OneToOne is released so the same user pk is
        # never re-associated to this stale Reseller.
        assert reseller.linked_user_id is None

    def test_no_reseller_link_is_fine(self, tenant):
        """Pure staff user with no Reseller doesn't crash."""
        user = JasminUserFactory()
        GDPRService.anonymize_user(user)


@pytest.mark.django_db
class TestContactEntityAnonymization:
    def test_solo_contact_is_wiped(self, tenant):
        """Contact referenced ONLY by the user's Reseller → safe to wipe."""
        contact = ContactEntityFactory(
            company_name="Solo GmbH",
            email="solo@example.com",
            phone="+49 30 1234",
            iban="DE89370400440532013000",
        )
        user = JasminUserFactory()
        ResellerFactory(linked_user=user, contact=contact)

        GDPRService.anonymize_user(user)

        contact.refresh_from_db()
        assert contact.company_name == "Gelöscht"
        assert contact.email is None
        assert contact.phone is None
        assert contact.iban == ""
        assert contact.address == "Gelöscht"
        assert contact.zip_code == "00000"

    # NB: a contact can be shared between a reseller and a delivery station,
    # but NOT between two resellers — that's enforced by the
    # ``reseller_unique_contact`` partial unique constraint (regression test in
    # ``test_reseller_delivery_station_service.py``). The "shared contact kept"
    # GDPR behaviour is therefore exercised via the reseller + delivery-station
    # case below.
    def test_shared_contact_kept_when_delivery_station_uses_it(self, tenant):
        """A Reseller's contact is also pointed at by a DeliveryStation.
        Anonymizing the Reseller must NOT wipe the contact —
        delivery routing depends on it."""
        from apps.commissioning.models import DeliveryStation

        contact = ContactEntityFactory(
            company_name="Pickup Point Marzahn", email="pickup@example.com"
        )
        user = JasminUserFactory()
        ResellerFactory(linked_user=user, contact=contact)
        DeliveryStation.objects.create(contact=contact, short_name="Marzahn")

        GDPRService.anonymize_user(user)

        contact.refresh_from_db()
        assert contact.company_name == "Pickup Point Marzahn"
        assert contact.email == "pickup@example.com"


@pytest.mark.django_db
class TestUserInvitationAnonymization:
    def test_recipient_email_replaced(self, tenant):
        user = JasminUserFactory(email="invitee@example.com")
        member = MemberFactory(user=user)
        UserInvitation.objects.create(
            user=user,
            member=member,
            email="invitee@example.com",
            status="accepted",
        )
        UserInvitation.objects.create(
            user=user,
            member=member,
            email="invitee+alt@example.com",
            status="expired",
        )

        GDPRService.anonymize_user(user)

        emails = list(
            UserInvitation.objects.filter(user=user).values_list("email", flat=True)
        )
        # Both rows scrubbed; statuses preserved (verified separately).
        assert all(e == f"deleted_{user.pk}@deleted.invalid" for e in emails)
        statuses = set(
            UserInvitation.objects.filter(user=user).values_list("status", flat=True)
        )
        assert statuses == {"accepted", "expired"}


@pytest.mark.django_db
class TestEmailLogAnonymization:
    def test_recipient_replaced_on_matching_rows_only(self, tenant):
        """Rows where ``recipient`` was the subject's address get the
        recipient overwritten. Unrelated rows are untouched."""
        user = JasminUserFactory(email="alice@example.com")
        # Member needed so _collect_known_emails picks up the
        # secondary address — the row, not the variable, is what matters.
        MemberFactory(user=user, email="alice.member@example.com")

        # Three log rows for the subject.
        EmailLog.objects.create(
            recipient="alice@example.com",
            subject="Welcome",
            status="sent",
        )
        EmailLog.objects.create(
            recipient="alice.member@example.com",
            subject="Invoice March",
            status="delivered",
        )
        EmailLog.objects.create(
            recipient="alice@example.com",
            subject="Reset link",
            status="sent",
            error="alice@example.com bounced",  # error field can echo address
        )
        # An unrelated row for someone else.
        EmailLog.objects.create(
            recipient="bob@example.com", subject="Hi Bob", status="sent"
        )

        GDPRService.anonymize_user(user)

        # All three subject-rows have the recipient anonymized.
        scrubbed = EmailLog.objects.filter(recipient="deleted@deleted.invalid")
        assert scrubbed.count() == 3
        # Subject lines tombstoned — tenant-editable templates can
        # render the person's name into the subject, so it must not
        # survive deletion. ``template`` + ``purpose`` keep the signal.
        assert all(row.subject == "Gelöscht" for row in scrubbed)
        # Error field was wiped too (it can echo the address).
        assert all(row.error == "" for row in scrubbed)
        # Unrelated Bob row is intact, subject included.
        bob_row = EmailLog.objects.get(recipient="bob@example.com")
        assert bob_row.subject == "Hi Bob"


@pytest.mark.django_db
class TestAxesPurge:
    def test_access_attempt_records_deleted(self, tenant):
        user = JasminUserFactory(email="brute@example.com")

        AccessAttempt.objects.create(
            username="brute@example.com",
            ip_address="1.2.3.4",
            user_agent="curl/8",
            get_data="",
            post_data="",
            http_accept="*/*",
            path_info="/api/auth/login/",
            failures_since_start=3,
        )
        # An attempt by someone ELSE must stay.
        AccessAttempt.objects.create(
            username="other@example.com",
            ip_address="5.6.7.8",
            user_agent="curl/8",
            get_data="",
            post_data="",
            http_accept="*/*",
            path_info="/api/auth/login/",
            failures_since_start=1,
        )

        GDPRService.anonymize_user(user)

        assert not AccessAttempt.objects.filter(username="brute@example.com").exists()
        assert AccessAttempt.objects.filter(username="other@example.com").exists()

    def test_access_failure_log_records_deleted(self, tenant):
        user = JasminUserFactory(email="brute2@example.com")
        AccessFailureLog.objects.create(
            username="brute2@example.com",
            ip_address="1.2.3.4",
            user_agent="curl/8",
            http_accept="*/*",
            path_info="/api/auth/login/",
            locked_out=True,
        )

        GDPRService.anonymize_user(user)

        assert not AccessFailureLog.objects.filter(
            username="brute2@example.com"
        ).exists()

    def test_access_log_records_deleted(self, tenant):
        """SUCCESSFUL logins (``AccessLog``) carry the subject's email
        as ``username`` plus their IP and user-agent in plaintext. They
        were left behind by the old purge (which only touched the two
        failed-login tables), so Art. 17 anonymization never removed the
        login history. Now they go too — but only the subject's rows."""
        user = JasminUserFactory(email="loginhistory@example.com")
        AccessLog.objects.create(
            username="loginhistory@example.com",
            ip_address="1.2.3.4",
            user_agent="curl/8",
            http_accept="*/*",
            path_info="/api/auth/login/",
        )
        # A successful login by someone ELSE must stay.
        AccessLog.objects.create(
            username="other@example.com",
            ip_address="5.6.7.8",
            user_agent="curl/8",
            http_accept="*/*",
            path_info="/api/auth/login/",
        )

        GDPRService.anonymize_user(user)

        assert not AccessLog.objects.filter(
            username="loginhistory@example.com"
        ).exists()
        assert AccessLog.objects.filter(username="other@example.com").exists()

    def test_axes_records_purged_case_insensitively(self, tenant):
        """axes stores the credential exactly as typed, so a member who
        logged in as ``Casey@Example.COM`` lands rows whose ``username``
        is mixed-case. The subject's canonical email is lowercase, so an
        exact ``username__in`` purge would leave those rows behind. The
        purge matches case-insensitively now — a login-history record
        can't survive deletion just because of letter-casing."""
        user = JasminUserFactory(email="casey@example.com")

        AccessLog.objects.create(
            username="Casey@Example.COM",
            ip_address="1.2.3.4",
            user_agent="curl/8",
            http_accept="*/*",
            path_info="/api/auth/login/",
        )
        AccessAttempt.objects.create(
            username="CASEY@example.com",
            ip_address="1.2.3.4",
            user_agent="curl/8",
            get_data="",
            post_data="",
            http_accept="*/*",
            path_info="/api/auth/login/",
            failures_since_start=2,
        )

        GDPRService.anonymize_user(user)

        assert not AccessLog.objects.filter(
            username__iexact="casey@example.com"
        ).exists()
        assert not AccessAttempt.objects.filter(
            username__iexact="casey@example.com"
        ).exists()


@pytest.mark.django_db
class TestTransactionalAtomicity:
    def test_partial_failure_rolls_everything_back(self, tenant, monkeypatch):
        """If a helper raises mid-pipeline, the whole anonymization
        rolls back — no half-anonymized state. Otherwise a retry would
        skip the already-scrubbed parts and the rest would never run.
        """
        user = JasminUserFactory(first_name="Alice", email="alice@x.com")
        MemberFactory(user=user, first_name="Alice")

        original_user_email = user.email

        # Force the EmailLog helper to blow up. Anything written before
        # it (JasminUser, Member) must be rolled back too.
        def boom(_emails):
            raise RuntimeError("simulated failure mid-pipeline")

        monkeypatch.setattr(GDPRService, "_anonymize_email_logs", staticmethod(boom))

        with pytest.raises(RuntimeError, match="simulated failure"):
            GDPRService.anonymize_user(user)

        user.refresh_from_db()
        assert user.email == original_user_email  # NOT rewritten
        assert user.first_name == "Alice"


@pytest.mark.django_db
class TestAvatarAnonymization:
    """GDPR-3: anonymisation must remove the uploaded avatar FILE from storage,
    not just NULL the column (the image is a photo of the data subject)."""

    def test_avatar_file_deleted_on_anonymize(self, tenant):
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        user = JasminUserFactory(email="avatar@example.com")
        MemberFactory(user=user)
        user.avatar.save("face.png", ContentFile(b"\x89PNG fake-bytes"), save=True)
        stored_name = user.avatar.name
        assert default_storage.exists(stored_name)

        GDPRService.anonymize_user(user)

        user.refresh_from_db()
        assert not user.avatar  # column cleared
        assert not default_storage.exists(stored_name)  # file gone from disk

    def test_no_avatar_is_fine(self, tenant):
        # The ``if user.avatar:`` guard makes anonymising a user with no avatar
        # a no-op rather than a crash.
        user = JasminUserFactory(email="noavatar@example.com")
        MemberFactory(user=user)
        GDPRService.anonymize_user(user)
        user.refresh_from_db()
        assert not user.avatar
