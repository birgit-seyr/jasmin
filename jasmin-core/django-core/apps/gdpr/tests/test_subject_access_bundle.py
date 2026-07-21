"""Tests for the Art-15 Subject Access Bundle.

``GDPRService.get_subject_access_bundle(user)`` is the Art-15 SAR
endpoint payload: every row tied to the user's identity, across
account, member, reseller, subscriptions, coop shares, invoices,
email log, login history, and the user's own Art-17 deletion
requests.

The service returns NATIVE Python types (``datetime``, ``date``,
``Decimal``, ``str``, ``None``) — formatting to ISO 8601 / decimal
strings happens in
:class:`apps.gdpr.serializers.SubjectAccessBundleSerializer`,
which the view applies before returning JSON. Tests in this file
exercise the service layer (native types). One end-to-end class
at the bottom hits the API endpoint and verifies the serialised
shape.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from axes.models import AccessFailureLog, AccessLog

from apps.commissioning.models import (
    ConsentDocument,
    ConsentRecord,
    MemberLoan,
    UserInvitation,
)
from apps.commissioning.models.choices import ConsentKind
from apps.commissioning.tests.factories import (
    ContactEntityFactory,
    CoopShareFactory,
    InvoiceResellerFactory,
    JasminUserFactory,
    MemberFactory,
    OrderFactory,
    ResellerFactory,
    SubscriptionFactory,
)
from apps.gdpr.services import GDPRService
from apps.notifications.models import EmailLog
from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule

# ---------------------------------------------------------------------------
# Account + Member + Reseller (the three identity rows)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAccountSection:
    def test_account_fields_populated(self, tenant):
        user = JasminUserFactory(
            roles=["member"],
            email="alice@example.com",
            first_name="Alice",
            last_name="Adams",
            user_language="de",
        )
        bundle = GDPRService.get_subject_access_bundle(user)
        account = bundle["account"]
        assert account["user_id"] == str(user.pk)
        assert account["email"] == "alice@example.com"
        assert account["first_name"] == "Alice"
        assert account["last_name"] == "Adams"
        assert account["user_language"] == "de"
        assert account["roles"] == ["member"]
        # Booleans + nullable timestamps come through (None when unset).
        assert "is_active" in account
        assert "last_login" in account


@pytest.mark.django_db
class TestMemberSection:
    def test_member_block_populated_when_member_exists(self, tenant):
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(
            user=user,
            first_name="Bob",
            last_name="Builder",
            address="Hauptstr. 1",
            city="Wien",
            zip_code="1010",
        )
        bundle = GDPRService.get_subject_access_bundle(user)
        assert bundle["member"] is not None
        m = bundle["member"]
        assert m["member_id"] == str(member.pk)
        assert m["first_name"] == "Bob"
        assert m["address"] == "Hauptstr. 1"
        assert m["city"] == "Wien"
        assert m["zip_code"] == "1010"

    def test_member_block_is_none_for_pure_staff_user(self, tenant):
        """A staff/office user without a Member row → ``member: None``,
        not omitted. Stable shape lets the frontend render `?.field`
        without defensive guards."""
        user = JasminUserFactory(roles=["office"])
        bundle = GDPRService.get_subject_access_bundle(user)
        assert bundle["member"] is None


@pytest.mark.django_db
class TestBillingProfileSection:
    def test_billing_profile_mandate_in_bundle(self, tenant):
        """GDPR-SAR-1: the SEPA mandate (reference + signing date) lives only on
        BillingProfile — Art. 15 must surface it, decrypted."""
        from apps.payments.constants import PaymentMethodOptions
        from apps.payments.models import BillingProfile

        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user)
        BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            iban="DE89370400440532013000",
            account_holder="Anna Member",
            sepa_mandate_reference="MND-2026-0001",
            sepa_mandate_signed_at=datetime.date(2026, 1, 5),
            is_active=True,
        )

        bundle = GDPRService.get_subject_access_bundle(user)

        bp = bundle["billing_profile"]
        assert bp is not None
        assert bp["sepa_mandate_reference"] == "MND-2026-0001"
        assert bp["sepa_mandate_signed_at"] == datetime.date(2026, 1, 5)
        assert bp["iban"] == "DE89370400440532013000"
        assert bp["account_holder"] == "Anna Member"

    def test_billing_profile_none_when_absent(self, tenant):
        user = JasminUserFactory(roles=["member"])
        MemberFactory(user=user)
        bundle = GDPRService.get_subject_access_bundle(user)
        assert bundle["billing_profile"] is None


@pytest.mark.django_db
class TestUserInvitationSection:
    def test_user_invitation_in_bundle_without_raw_token(self, tenant):
        """GDPR-SAR-2: an invitation to the subject's email is classified PII
        that anonymization scrubs, so Art. 15 discloses it — but the raw token
        (a live account-provisioning capability) is surfaced only as a boolean."""
        user = JasminUserFactory(roles=["member"])
        invitation = UserInvitation.objects.create(
            user=user, email="invitee@example.com", status="sent"
        )

        bundle = GDPRService.get_subject_access_bundle(user)

        invitations = bundle["user_invitations"]
        assert len(invitations) == 1
        row = invitations[0]
        assert row["email"] == "invitee@example.com"
        assert row["status"] == "sent"
        assert row["has_token"] is True
        # The raw token value must never appear anywhere in the payload.
        assert str(invitation.token) not in str(bundle)
        assert "token" not in row

    def test_no_invitations_yields_empty_list(self, tenant):
        user = JasminUserFactory(roles=["member"])
        bundle = GDPRService.get_subject_access_bundle(user)
        assert bundle["user_invitations"] == []


@pytest.mark.django_db
class TestResellerSection:
    def test_reseller_block_with_contact_populated(self, tenant):
        user = JasminUserFactory(roles=["customer"])
        contact = ContactEntityFactory(
            company_name="Bio Müller GmbH",
            email="orders@biomueller.example",
            phone="+49 30 12345",
            address="Marktplatz 7",
            zip_code="10115",
            city="Berlin",
        )
        reseller = ResellerFactory(linked_user=user, contact=contact)
        bundle = GDPRService.get_subject_access_bundle(user)
        r = bundle["reseller"]
        assert r is not None
        assert r["reseller_id"] == str(reseller.pk)
        assert r["customer_number"] == reseller.customer_number
        assert r["contact"] is not None
        c = r["contact"]
        assert c["company_name"] == "Bio Müller GmbH"
        assert c["email"] == "orders@biomueller.example"
        assert c["phone"] == "+49 30 12345"
        assert c["city"] == "Berlin"

    def test_reseller_block_is_none_when_no_reseller_link(self, tenant):
        user = JasminUserFactory(roles=["member"])
        bundle = GDPRService.get_subject_access_bundle(user)
        assert bundle["reseller"] is None


# ---------------------------------------------------------------------------
# Member-scoped collections
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConsentsSection:
    def test_consent_records_with_revocation_in_bundle(self, tenant):
        """Privacy + SEPA consents materialise as ConsentRecord rows
        with the document version + forensic IP/UA capture + any
        revocation tail. Order is newest-first."""
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user)
        document = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            version="2026-05-20",
            locale="de",
            title="Datenschutzerklärung",
            body="Wir verarbeiten Ihre Daten …",
            valid_from=datetime.date(2026, 5, 18),
        )
        record = ConsentRecord.objects.create(
            member=member,
            document=document,
            ip_address="10.0.0.5",
            user_agent="Mozilla/5.0 Test",
        )

        bundle = GDPRService.get_subject_access_bundle(user)
        consents = bundle["consents"]
        assert len(consents) == 1
        entry = consents[0]
        assert entry["id"] == str(record.pk)
        assert entry["kind"] == ConsentKind.PRIVACY
        assert entry["document_version"] == "2026-05-20"
        assert entry["ip_address"] == "10.0.0.5"
        assert entry["user_agent"] == "Mozilla/5.0 Test"
        # No revocation yet.
        assert entry["revoked_at"] is None


@pytest.mark.django_db
class TestCoopSharesSection:
    def test_coop_shares_listed(self, tenant):
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user)
        # Single row with amount=3 satisfies the model's min-shares
        # invariant; see test_two_step_deletion.py for the same trick.
        share = CoopShareFactory(member=member, amount_of_coop_shares=3)

        bundle = GDPRService.get_subject_access_bundle(user)
        shares = bundle["coop_shares"]
        assert len(shares) == 1
        assert shares[0]["id"] == str(share.pk)
        # Service returns native Decimal; serializer formats to string.
        assert shares[0]["amount_of_coop_shares"] == Decimal("3")


@pytest.mark.django_db
class TestSubscriptionsSection:
    def test_subscriptions_listed_newest_first(self, tenant):
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user)
        sub = SubscriptionFactory(member=member, valid_from=datetime.date(2026, 1, 5))

        bundle = GDPRService.get_subject_access_bundle(user)
        subs = bundle["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["id"] == str(sub.pk)
        # Service returns native date; serializer formats to ISO string.
        assert subs[0]["valid_from"] == datetime.date(2026, 1, 5)
        assert "share_type_variation" in subs[0]

    def test_cancellation_reasons_are_surfaced(self, tenant):
        # cancellation_reason is PII_IMMEDIATE (may hold health reasons /
        # complaints), so the Art. 15 bundle must disclose it on member,
        # subscription AND coop-share — like MemberLoan.cancelled_reason already
        # is. Regression for the omission that hid it on right-of-access.
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user, cancellation_reason="health reason")
        SubscriptionFactory(member=member, cancellation_reason="moved away")
        CoopShareFactory(
            member=member, amount_of_coop_shares=3, cancellation_reason="downsized"
        )

        bundle = GDPRService.get_subject_access_bundle(user)
        assert bundle["member"]["cancellation_reason"] == "health reason"
        assert bundle["subscriptions"][0]["cancellation_reason"] == "moved away"
        assert bundle["coop_shares"][0]["cancellation_reason"] == "downsized"

        # And it must survive the API serializer (explicit-field serializers drop
        # anything not declared) — the actual right-of-access response, not just
        # the internal dict.
        from apps.gdpr.serializers import SubjectAccessBundleSerializer

        data = SubjectAccessBundleSerializer(bundle).data
        assert data["member"]["cancellation_reason"] == "health reason"
        assert data["subscriptions"][0]["cancellation_reason"] == "moved away"
        assert data["coop_shares"][0]["cancellation_reason"] == "downsized"


@pytest.mark.django_db
class TestMemberLoansSection:
    def test_loans_listed(self, tenant):
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user)
        loan = MemberLoan.objects.create(
            member=member,
            amount=500,
            interest_rate=Decimal("1.50"),
            start_date=datetime.date(2026, 1, 1),
        )

        bundle = GDPRService.get_subject_access_bundle(user)
        loans = bundle["member_loans"]
        assert len(loans) == 1
        assert loans[0]["id"] == str(loan.pk)
        assert loans[0]["amount"] == 500
        # Service returns native Decimal; serializer formats to string.
        assert loans[0]["interest_rate"] == Decimal("1.50")


@pytest.mark.django_db
class TestChargeSchedulesSection:
    def test_charge_schedules_listed(self, tenant):
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user)
        sub = SubscriptionFactory(member=member)
        charge = ChargeSchedule.objects.create(
            member=member,
            subscription=sub,
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            due_date=datetime.date(2026, 2, 28),
            expected_amount=Decimal("42.50"),
            status=ChargeStatus.PLANNED,
            description="Februar-Abo",
        )

        bundle = GDPRService.get_subject_access_bundle(user)
        charges = bundle["charge_schedules"]
        assert len(charges) == 1
        assert charges[0]["id"] == str(charge.pk)
        # Service returns native Decimal; serializer formats to string.
        assert charges[0]["expected_amount"] == Decimal("42.50")
        assert charges[0]["status"] == ChargeStatus.PLANNED
        assert charges[0]["description"] == "Februar-Abo"


# ---------------------------------------------------------------------------
# Reseller-scoped collections
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestResellerOrdersSection:
    def test_orders_listed_when_user_is_reseller(self, tenant):
        user = JasminUserFactory(roles=["customer"])
        reseller = ResellerFactory(linked_user=user)
        order = OrderFactory(reseller=reseller)

        bundle = GDPRService.get_subject_access_bundle(user)
        orders = bundle["reseller_orders"]
        assert len(orders) == 1
        assert orders[0]["id"] == str(order.pk)
        assert orders[0]["year"] == order.year
        assert orders[0]["delivery_week"] == order.delivery_week


@pytest.mark.django_db
class TestResellerInvoicesSection:
    def test_invoices_listed_when_user_is_reseller(self, tenant):
        user = JasminUserFactory(roles=["customer"])
        reseller = ResellerFactory(linked_user=user)
        invoice = InvoiceResellerFactory(reseller=reseller)

        bundle = GDPRService.get_subject_access_bundle(user)
        invoices = bundle["reseller_invoices"]
        assert len(invoices) == 1
        assert invoices[0]["id"] == str(invoice.pk)
        assert "document_type" in invoices[0]
        assert "has_been_paid" in invoices[0]


# ---------------------------------------------------------------------------
# Email-keyed side-channel collections
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEmailLogSection:
    def test_only_emails_to_the_subject_appear(self, tenant):
        """Bundle contains EmailLog rows sent to ANY of the user's
        known addresses; other tenants' / other users' rows are
        filtered out."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        MemberFactory(user=user, email="alice.member@example.com")

        EmailLog.objects.create(
            recipient="alice@example.com", subject="Welcome", status="sent"
        )
        EmailLog.objects.create(
            recipient="alice.member@example.com",
            subject="Invoice March",
            status="delivered",
        )
        # Unrelated row.
        EmailLog.objects.create(
            recipient="bob@example.com", subject="Hi Bob", status="sent"
        )

        bundle = GDPRService.get_subject_access_bundle(user)
        section = bundle["email_log"]
        recipients = {entry["recipient"] for entry in section["entries"]}
        assert recipients == {"alice@example.com", "alice.member@example.com"}
        assert section["total_count"] == 2
        assert section["truncated"] is False

    def test_truncation_flag_set_when_over_limit(self, tenant, monkeypatch):
        """Past ``SAR_EMAIL_LOG_LIMIT``, ``truncated`` flips to True
        + ``total_count`` reflects the full row count even though
        ``entries`` is capped."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        # Knock the cap down to 2 so this test only has to create 3 rows.
        monkeypatch.setattr(GDPRService, "SAR_EMAIL_LOG_LIMIT", 2)
        for i in range(3):
            EmailLog.objects.create(
                recipient="alice@example.com",
                subject=f"Msg {i}",
                status="sent",
            )

        bundle = GDPRService.get_subject_access_bundle(user)
        section = bundle["email_log"]
        assert section["total_count"] == 3
        assert len(section["entries"]) == 2
        assert section["truncated"] is True


@pytest.mark.django_db
class TestLoginHistorySection:
    def test_successful_and_failed_login_records_listed(self, tenant):
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        AccessLog.objects.create(
            username="alice@example.com",
            ip_address="10.0.0.7",
            user_agent="UA/test",
            http_accept="*/*",
            path_info="/api/auth/login/",
        )
        AccessFailureLog.objects.create(
            username="alice@example.com",
            ip_address="10.0.0.8",
            user_agent="UA/attacker",
            http_accept="*/*",
            path_info="/api/auth/login/",
            locked_out=False,
        )
        # Unrelated user — must not appear in the subject's bundle.
        AccessLog.objects.create(
            username="bob@example.com",
            ip_address="10.0.0.9",
            user_agent="UA/test",
            http_accept="*/*",
            path_info="/api/auth/login/",
        )

        bundle = GDPRService.get_subject_access_bundle(user)
        history = bundle["login_history"]
        assert len(history["successful_logins"]) == 1
        assert history["successful_logins"][0]["ip_address"] == "10.0.0.7"
        assert len(history["failed_attempts"]) == 1
        assert history["failed_attempts"][0]["ip_address"] == "10.0.0.8"


@pytest.mark.django_db
class TestSharedSecondaryEmailIsolation:
    """``Member.email_2`` / ``email_3`` are non-unique CharFields, so a
    shared household / family address can sit on several Members. The SAR
    side-channel (email_log + login_history) must key ONLY on the subject's
    UNIQUE addresses — keying on a shared secondary would surface ANOTHER
    subject's emails + login records, which Art. 15 forbids."""

    def test_records_on_a_shared_secondary_email_are_not_disclosed(self, tenant):
        shared = "household@example.com"
        user_a = JasminUserFactory(roles=["member"], email="alice@example.com")
        MemberFactory(user=user_a, email="alice@example.com", email_2=shared)
        user_b = JasminUserFactory(roles=["member"], email="bob@example.com")
        MemberFactory(user=user_b, email="bob@example.com", email_2=shared)

        # Records on the SHARED address — could belong to either subject, so
        # they must NOT land in A's bundle.
        EmailLog.objects.create(
            recipient=shared, subject="Shared household mail", status="sent"
        )
        AccessLog.objects.create(
            username=shared,
            ip_address="1.2.3.4",
            user_agent="UA/test",
            http_accept="*/*",
            path_info="/api/auth/login/",
        )
        # Records on A's UNIQUE primary — these MUST still appear (the SAR is
        # narrowed, not broken).
        EmailLog.objects.create(
            recipient="alice@example.com", subject="Just for Alice", status="sent"
        )
        AccessLog.objects.create(
            username="alice@example.com",
            ip_address="9.9.9.9",
            user_agent="UA/test",
            http_accept="*/*",
            path_info="/api/auth/login/",
        )

        bundle = GDPRService.get_subject_access_bundle(user_a)

        email_recipients = {e["recipient"] for e in bundle["email_log"]["entries"]}
        assert "alice@example.com" in email_recipients  # own unique address
        assert shared not in email_recipients  # shared secondary excluded

        login_usernames = {
            row["username"] for row in bundle["login_history"]["successful_logins"]
        }
        assert "alice@example.com" in login_usernames
        assert shared not in login_usernames


@pytest.mark.django_db
class TestDeletionRequestsSection:
    def test_user_own_deletion_requests_listed(self, tenant):
        """The user's Art-17 history surfaces in the SAR bundle so
        they can audit their own erasure choices."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        request = GDPRService.request_deletion(user)

        bundle = GDPRService.get_subject_access_bundle(user)
        requests = bundle["deletion_requests"]
        assert len(requests) == 1
        assert requests[0]["id"] == str(request.pk)
        assert requests[0]["state"] == "pending_email"
        assert requests[0]["requested_email"] == "alice@example.com"


# ---------------------------------------------------------------------------
# Top-level contract — keys are stable; sections present even when empty.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBundleShapeContract:
    EXPECTED_TOP_KEYS = {
        "format_version",
        "exported_at",
        "subject",
        "account",
        "member",
        "billing_profile",
        "reseller",
        "consents",
        "coop_shares",
        "subscriptions",
        "member_loans",
        "charge_schedules",
        "reseller_orders",
        "reseller_invoices",
        "email_log",
        "login_history",
        "deletion_requests",
        "user_invitations",
    }

    def test_keys_present_for_pure_staff_user(self, tenant):
        """Even a user with NO member/reseller/orders gets the full
        shape — empty lists, None for the persona blocks. Frontend
        renders without defensive guards."""
        user = JasminUserFactory(roles=["office"])
        bundle = GDPRService.get_subject_access_bundle(user)

        assert set(bundle.keys()) == self.EXPECTED_TOP_KEYS
        assert bundle["member"] is None
        assert bundle["reseller"] is None
        assert bundle["consents"] == []
        assert bundle["coop_shares"] == []
        assert bundle["subscriptions"] == []
        assert bundle["member_loans"] == []
        assert bundle["charge_schedules"] == []
        assert bundle["reseller_orders"] == []
        assert bundle["reseller_invoices"] == []
        assert bundle["deletion_requests"] == []
        assert bundle["user_invitations"] == []
        # Email log + login history have their own truncation shape.
        assert bundle["email_log"]["entries"] == []
        assert bundle["login_history"]["successful_logins"] == []
        assert bundle["login_history"]["failed_attempts"] == []

    def test_format_version_pinned(self, tenant):
        """The frontend branches on ``format_version`` to handle
        future-shape changes. Bump on every breaking change."""
        user = JasminUserFactory(roles=["office"])
        bundle = GDPRService.get_subject_access_bundle(user)
        assert bundle["format_version"] == GDPRService.SAR_FORMAT_VERSION

    def test_subject_block_carries_id_and_email(self, tenant):
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        bundle = GDPRService.get_subject_access_bundle(user)
        assert bundle["subject"]["user_id"] == str(user.pk)
        assert bundle["subject"]["email"] == "alice@example.com"


# ---------------------------------------------------------------------------
# End-to-end: hit the API endpoint and verify the serializer formats
# the native types to the expected JSON shape (ISO 8601 dates, decimal
# strings). Locks the service↔serializer contract in one place.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSubjectAccessBundleView:
    def test_get_my_data_returns_serialized_bundle(self, tenant):
        """The view runs the bundle through
        ``SubjectAccessBundleSerializer`` — datetimes become ISO
        8601 strings, Decimals become strings, the top-level shape
        matches the contract."""
        from rest_framework.test import APIClient

        user = JasminUserFactory(
            roles=["member"],
            email="alice@example.com",
            first_name="Alice",
        )
        member = MemberFactory(user=user)
        CoopShareFactory(member=member, amount_of_coop_shares=3)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/gdpr/my-data/")

        assert response.status_code == 200
        body = response.json()

        # Top-level contract
        assert body["format_version"] == GDPRService.SAR_FORMAT_VERSION
        assert isinstance(body["exported_at"], str)  # ISO 8601 string
        assert body["subject"]["user_id"] == str(user.pk)

        # Account block — serializer formats datetimes
        assert body["account"]["email"] == "alice@example.com"
        assert body["account"]["first_name"] == "Alice"

        # CoopShare amount comes through as a string (DecimalField).
        shares = body["coop_shares"]
        assert len(shares) == 1
        assert shares[0]["amount_of_coop_shares"] == "3.00"

    def test_get_my_data_requires_auth(self, tenant):
        from rest_framework.test import APIClient

        response = APIClient().get("/api/gdpr/my-data/")
        assert response.status_code in (401, 403)
