"""Integration tests for the payments viewsets.

Covers:
    - URL routing under /api/payments/
    - BillingProfileViewSet: scoping (members see only own profile)
    - ChargeScheduleViewSet: scoping + filters + regenerate action
    - BillingRunViewSet: staff-only, create + export action
    - Auth/permission edge cases (anonymous, member-only, etc.)
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from rest_framework import status

from apps.commissioning.tests.factories import MemberFactory
from apps.payments.constants import (
    BillingRunStatus,
    ChargeStatus,
    PaymentMethodOptions,
)
from apps.payments.models import BillingProfile, BillingRun, ChargeSchedule


def _make_charge(member, subscription, *, status=ChargeStatus.PLANNED, due=None):
    due = due or datetime.date(2026, 2, 1)
    return ChargeSchedule.objects.create(
        member=member,
        subscription=subscription,
        period_start=due,
        period_end=due + datetime.timedelta(days=27),
        due_date=due,
        expected_amount=Decimal("25.00"),
        currency="EUR",
        status=status,
    )


# ---------------------------------------------------------------------------
# BillingProfileViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBillingProfileViewSet:
    URL = "/api/payments/billing_profiles/"

    def test_anonymous_is_rejected(self, anon_client, tenant):
        resp = anon_client.get(self.URL)
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_office_user_sees_all_profiles(self, api_client, tenant, billing_profile):
        # Add a second profile for noise.
        other_member = MemberFactory()
        BillingProfile.objects.create(
            member=other_member,
            payment_method=PaymentMethodOptions.BANK_TRANSFER,
            is_active=True,
        )
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 2

    def test_member_only_sees_own_profile(
        self, member_api_client, tenant, billing_profile
    ):
        # Create an unrelated profile owned by a different member.
        other = MemberFactory()
        BillingProfile.objects.create(
            member=other,
            payment_method=PaymentMethodOptions.BANK_TRANSFER,
            is_active=True,
        )
        resp = member_api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert ids == {str(billing_profile.pk)}

    def test_member_self_read_omits_office_notes(
        self, member_api_client, tenant, billing_profile
    ):
        """SEC-15: a member reading their OWN billing profile must NOT receive
        the office-internal free-text ``notes``. ``read_only_fields`` guards
        writes, not reads, so the office serializer would otherwise leak it."""
        billing_profile.notes = "internal: flagged for manual review"
        billing_profile.save(update_fields=["notes"])

        resp = member_api_client.get(f"{self.URL}{billing_profile.pk}/")

        assert resp.status_code == status.HTTP_200_OK
        assert "notes" not in resp.data
        # The member still sees their own billing data.
        assert resp.data["id"] == str(billing_profile.pk)
        # Decrypted IBAN is never echoed — only the masked companion.
        assert "iban" not in resp.data
        assert "iban_masked" in resp.data

    def test_office_read_still_includes_notes(
        self, api_client, tenant, billing_profile
    ):
        """The narrowing is member-only — office keeps the full serializer."""
        billing_profile.notes = "internal note"
        billing_profile.save(update_fields=["notes"])

        resp = api_client.get(f"{self.URL}{billing_profile.pk}/")

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data.get("notes") == "internal note"

    def test_office_read_masks_bank_details(self, api_client, tenant, billing_profile):
        """Even the office full serializer never echoes the decrypted IBAN /
        account_holder — only the masked companions (country code + last 4)."""
        resp = api_client.get(f"{self.URL}{billing_profile.pk}/")

        assert resp.status_code == status.HTTP_200_OK
        assert "iban" not in resp.data
        assert "account_holder" not in resp.data
        assert resp.data["iban_masked"] == "DE •••• 3000"
        assert "•" in resp.data["account_holder_masked"]

    def test_member_cannot_create(self, member_api_client, tenant, member):
        resp = member_api_client.post(
            self.URL,
            {
                "member": str(member.pk),
                "payment_method": PaymentMethodOptions.BANK_TRANSFER,
                "is_active": True,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_office_can_create(self, api_client, tenant):
        m = MemberFactory()
        resp = api_client.post(
            self.URL,
            {
                "member": str(m.pk),
                "payment_method": PaymentMethodOptions.BANK_TRANSFER,
                "is_active": True,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert BillingProfile.objects.filter(member=m).exists()

    def test_toggle_is_active_requires_step_up(
        self, api_client, tenant, billing_profile
    ):
        # TXN-4: deactivating a mandate is payment-relevant (it gates collection
        # + run eligibility), so a plain office PATCH of ``is_active`` is now
        # rejected without step-up.
        resp = api_client.patch(
            f"{self.URL}{billing_profile.pk}/",
            {"is_active": False},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        billing_profile.refresh_from_db()
        assert billing_profile.is_active is True  # unchanged

    def test_patch_notes_does_not_require_step_up(
        self, api_client, tenant, billing_profile
    ):
        # ``notes`` is office-internal and not payment-sensitive — still PATCHes
        # without a step-up prompt.
        resp = api_client.patch(
            f"{self.URL}{billing_profile.pk}/",
            {"notes": "called member re: mandate"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_change_payment_method_requires_step_up(self, api_client, tenant, member):
        # A profile moved OFF SEPA while KEEPING its mandate columns (e.g. an
        # Art. 7(3) consent revoke that only flips payment_method). Flipping it
        # BACK to SEPA_DD would re-arm a usable mandate (is_sepa_ready -> True),
        # so it must require step-up — not a silent office PATCH.
        profile = BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.BANK_TRANSFER,
            iban="DE89370400440532013000",
            account_holder="Test Holder",
            sepa_mandate_reference="MND-RETAINED-001",
            sepa_mandate_signed_at=datetime.date(2026, 1, 1),
            is_active=True,
        )
        assert profile.is_sepa_ready is False  # BANK_TRANSFER -> not sepa-ready

        resp = api_client.patch(
            f"{self.URL}{profile.pk}/",
            {"payment_method": PaymentMethodOptions.SEPA_DIRECT_DEBIT},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        profile.refresh_from_db()
        # Not resurrected: method unchanged, mandate still not usable.
        assert profile.payment_method == PaymentMethodOptions.BANK_TRANSFER
        assert profile.is_sepa_ready is False

    def test_office_can_set_paper_mandate_received(
        self, api_client, tenant, billing_profile
    ):
        # The office records the signed paper SEPA mandate via this field. It is
        # NOT payment-sensitive (not in _SEPA_SENSITIVE_FIELDS), so it PATCHes
        # without step-up, and the date round-trips.
        resp = api_client.patch(
            f"{self.URL}{billing_profile.pk}/",
            {"sepa_mandate_paper_received_at": "2026-06-30"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        billing_profile.refresh_from_db()
        assert str(billing_profile.sepa_mandate_paper_received_at) == "2026-06-30"

    def test_list_logs_pii_read(self, api_client, tenant, billing_profile):
        # SEC-1: the billing-profile list decrypts IBAN / account holder, so a
        # bulk read must emit an Art. 5(2) accountability line (unlike the
        # name/number/status lists the mixin deliberately skips).
        from unittest.mock import patch

        from apps.payments.viewsets import BillingProfileViewSet

        with patch.object(BillingProfileViewSet, "_log_pii_list_read") as mock_log:
            resp = api_client.get(self.URL)

        assert resp.status_code == status.HTTP_200_OK
        mock_log.assert_called_once()

    def test_member_fk_is_immutable_on_update(
        self, api_client, tenant, billing_profile
    ):
        # TEN-3: the owning ``member`` FK is read-only on update — a PATCH that
        # tries to reassign it is silently ignored, so an existing profile can't
        # be pointed at another member. (``member`` stays writable on create.)
        other = MemberFactory()
        original_member_id = billing_profile.member_id
        assert str(other.pk) != original_member_id

        resp = api_client.patch(
            f"{self.URL}{billing_profile.pk}/",
            {"member": str(other.pk), "notes": "reassign attempt"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        billing_profile.refresh_from_db()
        assert billing_profile.member_id == original_member_id


# ---------------------------------------------------------------------------
# ChargeScheduleViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestChargeScheduleViewSet:
    URL = "/api/payments/charge_schedules/"

    def test_member_only_sees_own_charges(
        self, member_api_client, tenant, member, subscription
    ):
        _make_charge(member, subscription)
        # Noise: charge for another member.
        other = MemberFactory()
        from apps.commissioning.tests.factories import (
            PaymentCycleFactory,
            SubscriptionFactory,
        )

        # Reuse the existing default_delivery_station_day so we don't trigger
        # the SharesDeliveryDay overlap-on-day_number constraint.
        other_sub = SubscriptionFactory(
            member=other,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),
            payment_cycle=PaymentCycleFactory(),
            default_delivery_station_day=subscription.default_delivery_station_day,
        )
        _make_charge(other, other_sub)

        resp = member_api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        member_ids = {row["member"] for row in resp.data}
        assert member_ids == {str(member.pk)}

    def test_member_foreign_member_param_is_403(
        self, member_api_client, tenant, member
    ):
        # TEN-2: a non-privileged caller passing another member's ?member= gets
        # a 403, not a silent empty 200.
        other = MemberFactory()
        resp = member_api_client.get(self.URL, {"member": str(other.pk)})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_member_own_member_param_is_allowed(
        self, member_api_client, tenant, member, subscription
    ):
        # Passing their OWN id is fine (privileged callers bypass entirely).
        _make_charge(member, subscription)
        resp = member_api_client.get(self.URL, {"member": str(member.pk)})
        assert resp.status_code == status.HTTP_200_OK
        assert {row["member"] for row in resp.data} == {str(member.pk)}

    def test_office_filter_by_status(self, api_client, tenant, member, subscription):
        _make_charge(member, subscription, status=ChargeStatus.PLANNED)
        c2 = _make_charge(
            member,
            subscription,
            status=ChargeStatus.PLANNED,
            due=datetime.date(2026, 3, 1),
        )
        c2.status = ChargeStatus.PAID
        c2.save(allow_immutable_change=True)

        resp = api_client.get(self.URL, {"status": "PAID"})
        assert resp.status_code == status.HTTP_200_OK
        statuses = {row["status"] for row in resp.data}
        assert statuses == {"PAID"}

    def test_member_cannot_regenerate(self, member_api_client, tenant, tenant_settings):
        resp = member_api_client.post(self.URL + "regenerate/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_office_can_regenerate(
        self, api_client, tenant, tenant_settings, subscription
    ):
        # ``regenerate_all`` only bills admin-confirmed subscriptions (COR-13);
        # the shared fixture is unconfirmed, so confirm it for this path.
        subscription.admin_confirmed = True
        subscription.save(update_fields=["admin_confirmed"])

        resp = api_client.post(self.URL + "regenerate/")
        assert resp.status_code == status.HTTP_200_OK
        assert "regenerated_subscriptions" in resp.data
        assert resp.data["regenerated_subscriptions"] >= 1
        # Charges actually created.
        assert ChargeSchedule.objects.filter(subscription=subscription).exists()


# ---------------------------------------------------------------------------
# BillingRunViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBillingRunViewSet:
    URL = "/api/payments/billing_runs/"

    def test_member_cannot_list(self, member_api_client, tenant):
        resp = member_api_client.get(self.URL)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_office_can_list(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_filters_by_period_year(self, api_client, tenant):
        for yr, msg in ((2025, "BR-2025"), (2026, "BR-2026")):
            BillingRun.objects.create(
                period_start=datetime.date(yr, 6, 1),
                period_end=datetime.date(yr, 6, 30),
                collection_date=datetime.date(yr, 7, 5),
                payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
                status=BillingRunStatus.DRAFT,
                total_amount=Decimal("0"),
                charge_count=0,
                msg_id=msg,
            )
        resp = api_client.get(self.URL, {"year": 2026})
        assert resp.status_code == status.HTTP_200_OK
        assert {row["period_start"][:4] for row in resp.data} == {"2026"}

    def test_list_invalid_year_returns_400(self, api_client, tenant):
        resp = api_client.get(self.URL, {"year": "not-a-year"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # Freeze "today" before collection_date so the past-date guard
    # (BillingRunViewSet.create) doesn't reject this otherwise-valid run.
    @time_machine.travel("2026-02-15")
    def test_create_run_bundles_charges(
        self,
        api_client,
        tenant,
        tenant_settings,
        billing_profile,
        subscription,
        member,
    ):
        _make_charge(member, subscription, due=datetime.date(2026, 2, 5))
        resp = api_client.post(
            self.URL,
            {
                "period_start": "2026-02-01",
                "period_end": "2026-02-28",
                "collection_date": "2026-03-05",
                "payment_method": PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["charge_count"] == 1
        assert resp.data["status"] == BillingRunStatus.DRAFT

    @time_machine.travel("2026-03-10")
    def test_create_run_rejects_past_collection_date(
        self, api_client, tenant, tenant_settings, billing_profile
    ):
        """A collection_date before today is rejected (400): SEPA can't settle a
        past debit and the bank would bounce the whole pain.008 batch."""
        resp = api_client.post(
            self.URL,
            {
                "period_start": "2026-02-01",
                "period_end": "2026-02-28",
                "collection_date": "2026-03-05",  # before frozen today (2026-03-10)
                "payment_method": PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "billing_run.invalid_collection_date"

    def test_create_run_with_no_charges_returns_400(
        self, api_client, tenant, tenant_settings, billing_profile
    ):
        resp = api_client.post(
            self.URL,
            {
                "period_start": "2026-02-01",
                "period_end": "2026-02-28",
                "collection_date": "2026-03-05",
                "payment_method": PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @time_machine.travel("2026-02-15")
    def test_export_action(
        self,
        api_client,
        tenant,
        tenant_settings,
        billing_profile,
        subscription,
        member,
    ):
        _make_charge(member, subscription, due=datetime.date(2026, 2, 5))
        create_resp = api_client.post(
            self.URL,
            {
                "period_start": "2026-02-01",
                "period_end": "2026-02-28",
                "collection_date": "2026-03-05",
                "payment_method": PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            },
            format="json",
        )
        run_id = create_resp.data["id"]

        export_resp = api_client.post(f"{self.URL}{run_id}/export/")
        assert export_resp.status_code == status.HTTP_200_OK
        assert export_resp.data["status"] == BillingRunStatus.EXPORTED
        assert export_resp.data["sepa_xml_export_url"] is not None

        # Charge was flipped to ISSUED.
        run = BillingRun.objects.get(pk=run_id)
        assert all(c.status == ChargeStatus.ISSUED for c in run.charges.all())

    @time_machine.travel("2026-02-15")
    def test_member_cannot_export(
        self,
        member_api_client,
        api_client,
        tenant,
        tenant_settings,
        billing_profile,
        subscription,
        member,
    ):
        _make_charge(member, subscription, due=datetime.date(2026, 2, 5))
        run_resp = api_client.post(
            self.URL,
            {
                "period_start": "2026-02-01",
                "period_end": "2026-02-28",
                "collection_date": "2026-03-05",
                "payment_method": PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            },
            format="json",
        )
        run_id = run_resp.data["id"]
        resp = member_api_client.post(f"{self.URL}{run_id}/export/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# BillingProfileViewSet.mandate_status (SEPA overview column)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSepaMandateStatusAction:
    URL = "/api/payments/billing_profiles/mandate_status/"

    def test_office_lists_per_member_status(
        self, api_client, tenant, member, billing_profile
    ):
        # A second member whose mandate is deactivated → not sepa-ready.
        other = MemberFactory(last_name="Zzz")
        BillingProfile.objects.create(
            member=other,
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            is_active=False,
        )

        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        by_member = {row["member"]: row for row in resp.data}
        assert by_member[str(member.pk)]["has_active_sepa_mandate"] is True
        assert by_member[str(other.pk)]["has_active_sepa_mandate"] is False
        # The ready mandate exposes its reference + signed date for the details view.
        assert by_member[str(member.pk)]["sepa_mandate_reference"]
        assert by_member[str(member.pk)]["sepa_mandate_signed_at"] == "2026-01-01"

    def test_no_bank_identifiers_in_payload(self, api_client, tenant, billing_profile):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        for row in resp.data:
            # The whole point of this endpoint: never ship IBAN / account holder,
            # not even masked — that's the SEC-1 bulk-read the profile list logs.
            assert "iban" not in row
            assert "iban_masked" not in row
            assert "account_holder" not in row
            assert "account_holder_masked" not in row

    def test_member_is_forbidden(self, member_api_client, tenant, billing_profile):
        # A member must NOT see every member's mandate status.
        resp = member_api_client.get(self.URL)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_anonymous_is_rejected(self, anon_client, tenant):
        resp = anon_client.get(self.URL)
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
