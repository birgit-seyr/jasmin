"""Tests for ``my_data_views`` — the member/customer self-edit surface.

Each endpoint must:
  * 401 when anonymous
  * 404 when the authenticated user has no matching profile row
  * round-trip the editable fields under PATCH
  * never echo encrypted columns (IBAN / account_owner) as plaintext
  * silently drop any field outside the allowlist
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.models import (
    ConsentDocument,
    ConsentKind,
    ConsentRecord,
    ContactEntity,
    CoopShare,
    Member,
    Subscription,
)
from apps.commissioning.tests.factories import (
    ContactEntityFactory,
    CoopShareFactory,
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    ResellerFactory,
    ShareTypeVariationFactory,
    ShareTypeVariationGrossPriceFactory,
    SubscriptionFactory,
)

URL_MY_MEMBER = reverse("my_member_data")
URL_MY_CUSTOMER = reverse("my_customer_data")
URL_COOP_SUBSCRIBE = reverse("my_coop_shares_subscribe")
URL_SUB_SUBSCRIBE = reverse("my_subscriptions_subscribe")
URL_MEMBERSHIP_CANCEL = reverse("my_membership_cancel")


def _client_for(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _step_up_client_for(user) -> APIClient:
    """Client whose token carries a fresh ``step_up_verified_at`` claim —
    needed to change the SEPA fields (``iban`` / ``account_owner``), which
    are step-up gated on the self-edit surface."""
    from apps.commissioning.tests.conftest import make_step_up_token

    c = APIClient()
    c.force_authenticate(user=user, token=make_step_up_token(user))
    return c


# ---------------------------------------------------------------------------
# my_member_data
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMyMemberDataGet:
    def test_anonymous_returns_401(self, anon_client, tenant):
        assert anon_client.get(URL_MY_MEMBER).status_code == (
            status.HTTP_401_UNAUTHORIZED
        )

    def test_user_without_member_returns_404(self, member_user, tenant):
        client = _client_for(member_user)
        resp = client.get(URL_MY_MEMBER)
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_returns_editable_and_readonly_fields(self, member_user, tenant):
        member = MemberFactory(
            user=member_user,
            first_name="Ada",
            last_name="Lovelace",
            address="Boulevard 1",
            zip_code="10115",
            city="Berlin",
            country="DE",
            iban="DE89370400440532013000",
            account_owner="Ada Lovelace",
            is_trial=False,
        )
        CoopShareFactory(member=member, amount_of_coop_shares=1)
        CoopShareFactory(member=member, amount_of_coop_shares=2)

        resp = _client_for(member_user).get(URL_MY_MEMBER)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.data
        assert data["first_name"] == "Ada"
        assert data["member_number"] == member.member_number
        assert data["is_trial"] is False
        # Encrypted columns surface only as boolean indicators.
        assert data["iban_stored"] is True
        assert data["account_owner_stored"] is True
        assert "iban" not in data
        assert "account_owner" not in data
        # Coop shares are projected.
        assert len(data["coop_shares"]) == 2
        amounts = sorted(
            Decimal(str(s["amount_of_coop_shares"])) for s in data["coop_shares"]
        )
        assert amounts == [Decimal("1.00"), Decimal("2.00")]


@pytest.mark.django_db
class TestMyMemberDataPatch:
    def test_patches_address_and_returns_fresh_state(self, member_user, tenant):
        MemberFactory(user=member_user, address="Old", city="Munich")
        client = _client_for(member_user)

        resp = client.patch(
            URL_MY_MEMBER,
            data={"address": "Neue Strasse 1", "city": "Hamburg"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["address"] == "Neue Strasse 1"
        assert resp.data["city"] == "Hamburg"

        member = Member.objects.get(user=member_user)
        assert member.address == "Neue Strasse 1"
        assert member.city == "Hamburg"

    def test_member_cannot_set_membership_paper_received(self, member_user, tenant):
        # ``membership_paper_received_at`` is an office-only receipt stamp and
        # is NOT in the member self-edit allowlist, so a self-PATCH silently
        # ignores it (a member must not be able to record their own paper).
        MemberFactory(user=member_user)
        resp = _client_for(member_user).patch(
            URL_MY_MEMBER,
            data={"membership_paper_received_at": "2026-06-30"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        member = Member.objects.get(user=member_user)
        assert member.membership_paper_received_at is None

    def test_confirmed_member_cannot_change_birth_date(self, member_user, tenant):
        # MEM-7: birth_date is GenG-locked once the member is admin-confirmed,
        # on the self-edit surface too (not just the office serializer).
        import datetime

        MemberFactory(
            user=member_user,
            admin_confirmed=True,
            birth_date=datetime.date(1990, 1, 1),
        )
        resp = _client_for(member_user).patch(
            URL_MY_MEMBER,
            data={"birth_date": "1991-02-02"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        member = Member.objects.get(user=member_user)
        assert member.birth_date == datetime.date(1990, 1, 1)  # unchanged

    def test_unconfirmed_member_can_change_birth_date(self, member_user, tenant):
        import datetime

        MemberFactory(
            user=member_user,
            admin_confirmed=False,
            birth_date=datetime.date(1990, 1, 1),
        )
        resp = _client_for(member_user).patch(
            URL_MY_MEMBER,
            data={"birth_date": "1991-02-02"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        member = Member.objects.get(user=member_user)
        assert member.birth_date == datetime.date(1991, 2, 2)

    def test_patches_iban_returns_stored_indicator(self, member_user, tenant):
        MemberFactory(user=member_user, iban=None)
        # Changing the IBAN is step-up gated — use a step-up-authenticated
        # client so the request gets past the gate to the write.
        client = _step_up_client_for(member_user)

        resp = client.patch(
            URL_MY_MEMBER,
            data={"iban": "DE89370400440532013000"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["iban_stored"] is True
        # Plaintext never crosses the wire.
        assert "iban" not in resp.data

        # …but the value did persist (decryption is transparent on read).
        member = Member.objects.get(user=member_user)
        assert member.iban == "DE89370400440532013000"

    def test_iban_change_without_step_up_is_blocked(self, member_user, tenant):
        """A SEPA-field change on a session WITHOUT a fresh step-up claim is
        rejected before any write — closes the hijacked-session
        mandate-redirect vector."""
        MemberFactory(user=member_user, iban=None)
        resp = _client_for(member_user).patch(
            URL_MY_MEMBER,
            data={"iban": "DE89370400440532013000"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "auth.step_up_required"
        # Nothing persisted.
        assert Member.objects.get(user=member_user).iban in (None, "")

    def test_unchanged_iban_does_not_require_step_up(self, member_user, tenant):
        """Re-submitting the SAME stored IBAN (e.g. a form that round-trips
        every field) must NOT demand step-up — the gate fires only on an
        actual change."""
        MemberFactory(user=member_user, iban="DE89370400440532013000")
        resp = _client_for(member_user).patch(
            URL_MY_MEMBER,
            data={"iban": "DE89370400440532013000", "first_name": "Ada"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert Member.objects.get(user=member_user).first_name == "Ada"

    def test_rejects_invalid_iban(self, member_user, tenant):
        MemberFactory(user=member_user)
        resp = _step_up_client_for(member_user).patch(
            URL_MY_MEMBER,
            data={"iban": "not-an-iban"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        # The tenant wraps validation errors in a standard envelope:
        # ``{"code": "validation_error", "details": {<field>: [...]},
        # "field": <first-field>, "message": ...}``.
        assert "iban" in resp.data["details"]

    def test_silently_drops_disallowed_fields(self, member_user, tenant):
        member = MemberFactory(user=member_user, is_trial=False, member_number=4242)
        resp = _client_for(member_user).patch(
            URL_MY_MEMBER,
            data={
                "first_name": "Ada",
                # All of these are NOT in the allowlist — must not change.
                "is_trial": True,
                "is_active": False,
                "member_number": 9999,
                "entry_date": "1900-01-01",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK

        member.refresh_from_db()
        assert member.first_name == "Ada"  # allowed field DID save
        assert member.is_trial is False  # disallowed — unchanged
        assert member.is_active is True
        assert member.member_number == 4242

    def test_other_user_cannot_patch_my_member(self, member_user, tenant):
        # A member-A user must not be able to mutate member-B by some
        # query trick. The endpoint resolves the target from the JWT
        # only, so there's no addressable other-row.
        target = MemberFactory(first_name="Untouched")
        MemberFactory(user=member_user, first_name="Self")

        _client_for(member_user).patch(
            URL_MY_MEMBER,
            data={"first_name": "Hijacked"},
            format="json",
        )
        target.refresh_from_db()
        assert target.first_name == "Untouched"


# ---------------------------------------------------------------------------
# my_customer_data
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMyCustomerDataGet:
    def test_anonymous_returns_401(self, anon_client, tenant):
        assert anon_client.get(URL_MY_CUSTOMER).status_code == (
            status.HTTP_401_UNAUTHORIZED
        )

    def test_user_without_reseller_returns_404(self, tenant):
        customer_user = JasminUserFactory(roles=["customer"])
        resp = _client_for(customer_user).get(URL_MY_CUSTOMER)
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_returns_contact_plus_customer_number(self, tenant):
        customer_user = JasminUserFactory(roles=["customer"])
        contact = ContactEntityFactory(
            company_name="Acme GmbH",
            first_name="Eve",
            last_name="Customer",
            address="Hauptstr. 5",
            zip_code="80331",
            city="Munich",
            email="eve@example.com",
            iban="DE89370400440532013000",
        )
        reseller = ResellerFactory(
            linked_user=customer_user, contact=contact, customer_number=4711
        )

        resp = _client_for(customer_user).get(URL_MY_CUSTOMER)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.data
        assert data["company_name"] == "Acme GmbH"
        assert data["email"] == "eve@example.com"
        assert data["customer_number"] == reseller.customer_number
        assert data["iban_stored"] is True
        assert "iban" not in data


@pytest.mark.django_db
class TestMyCustomerDataPatch:
    def test_patches_contact_fields(self, tenant):
        customer_user = JasminUserFactory(roles=["customer"])
        contact = ContactEntityFactory(address="Old", phone="123", city="Munich")
        ResellerFactory(linked_user=customer_user, contact=contact)

        resp = _client_for(customer_user).patch(
            URL_MY_CUSTOMER,
            data={"address": "Markt 9", "phone": "+49 30 99 99 99"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["address"] == "Markt 9"
        assert resp.data["phone"] == "+49 30 99 99 99"

        contact.refresh_from_db()
        assert contact.address == "Markt 9"
        assert contact.phone == "+49 30 99 99 99"

    def test_customer_iban_change_requires_step_up(self, tenant):
        """The customer's bank details (ContactEntity.iban) are step-up
        gated too — a session without a fresh claim cannot reroute the
        mandate."""
        customer_user = JasminUserFactory(roles=["customer"])
        contact = ContactEntityFactory(iban="DE89370400440532013000")
        ResellerFactory(linked_user=customer_user, contact=contact)

        resp = _client_for(customer_user).patch(
            URL_MY_CUSTOMER,
            data={"iban": "DE89370400440532099999"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "auth.step_up_required"
        contact.refresh_from_db()
        assert contact.iban == "DE89370400440532013000"  # unchanged

    def test_does_not_touch_reseller_invoice_fields(self, tenant):
        customer_user = JasminUserFactory(roles=["customer"])
        contact = ContactEntityFactory()
        reseller = ResellerFactory(
            linked_user=customer_user,
            contact=contact,
            customer_number=4711,
            invoice_name="LOCKED",
            invoice_city="LOCKED-CITY",
        )

        _client_for(customer_user).patch(
            URL_MY_CUSTOMER,
            data={
                "company_name": "Brand new",
                # These three must be ignored: they live on Reseller, not
                # in the allowlist, and the endpoint targets ContactEntity.
                "invoice_name": "PWNED",
                "invoice_city": "PWNED-CITY",
                "customer_number": 9999,
            },
            format="json",
        )

        reseller.refresh_from_db()
        assert reseller.invoice_name == "LOCKED"
        assert reseller.invoice_city == "LOCKED-CITY"
        assert reseller.customer_number == 4711
        # The allowed field made it through.
        assert ContactEntity.objects.get(pk=contact.pk).company_name == "Brand new"


# ---------------------------------------------------------------------------
# my_coop_shares/subscribe — member self-service coop-share subscription
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMyCoopShareSubscribe:
    @staticmethod
    def _settings(tenant, **kwargs):
        """Current TenantSettings (value_one_coop_share defaults to 100)."""
        import datetime

        from django.utils import timezone

        from apps.shared.tenants.models import TenantSettings

        return TenantSettings.objects.create(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(seconds=1),
            **kwargs,
        )

    def test_anonymous_returns_401(self, anon_client, tenant):
        resp = anon_client.post(
            URL_COOP_SUBSCRIBE, {"amount_of_coop_shares": 3}, format="json"
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_user_without_member_returns_404(self, member_user, tenant):
        resp = _client_for(member_user).post(
            URL_COOP_SUBSCRIBE, {"amount_of_coop_shares": 3}, format="json"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_self_subscribe_creates_unconfirmed_share(self, member_user, tenant):
        self._settings(tenant)
        member = MemberFactory(user=member_user, is_trial=False)
        resp = _client_for(member_user).post(
            URL_COOP_SUBSCRIBE, {"amount_of_coop_shares": 5}, format="json"
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        # Exactly one share, owned by the caller, pending office confirmation.
        share = CoopShare.objects.get(member=member)
        assert share.amount_of_coop_shares == 5
        assert share.admin_confirmed is False
        assert resp.data["admin_confirmed"] is False

    def test_self_subscribe_ignores_client_supplied_member(self, member_user, tenant):
        """A member cannot subscribe shares onto another member's account —
        the member is resolved from the token, never from the payload."""
        self._settings(tenant)
        me = MemberFactory(user=member_user, is_trial=False)
        someone_else = MemberFactory()
        resp = _client_for(member_user).post(
            URL_COOP_SUBSCRIBE,
            {"amount_of_coop_shares": 4, "member": str(someone_else.id)},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert CoopShare.objects.filter(member=someone_else).count() == 0
        assert CoopShare.objects.filter(member=me).count() == 1

    def test_value_not_configured_is_rejected(self, member_user, tenant):
        # MEM-2/6: no TenantSettings → no per-share value → refuse (never
        # persist a 0-valued share).
        MemberFactory(user=member_user, is_trial=False)
        resp = _client_for(member_user).post(
            URL_COOP_SUBSCRIBE, {"amount_of_coop_shares": 5}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "coop_share.value_not_configured"
        assert CoopShare.objects.count() == 0

    @staticmethod
    def _coop_contract_doc():
        """A currently-active coop-share ConsentDocument."""
        import datetime

        return ConsentDocument.objects.create(
            kind=ConsentKind.COOP_CONTRACT,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="Zeichnungsvertrag — Bedingungen …",
        )

    def test_contract_agreement_required_when_doc_published(self, member_user, tenant):
        # MEM-4: a published coop-share contract requires affirmative consent.
        self._settings(tenant)
        self._coop_contract_doc()
        MemberFactory(user=member_user, is_trial=False)

        resp = _client_for(member_user).post(
            URL_COOP_SUBSCRIBE, {"amount_of_coop_shares": 5}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "coop_share.contract_agreement_required"
        assert CoopShare.objects.count() == 0

    def test_contract_agreement_recorded_as_consent(self, member_user, tenant):
        self._settings(tenant)
        doc = self._coop_contract_doc()
        member = MemberFactory(user=member_user, is_trial=False)

        resp = _client_for(member_user).post(
            URL_COOP_SUBSCRIBE,
            {"amount_of_coop_shares": 5, "agreed_to_contract": True},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        # A versioned, revocable ConsentRecord proves the agreement (DSGVO Art. 7).
        assert ConsentRecord.objects.filter(
            member=member, document=doc, revoked_at__isnull=True
        ).exists()

    def test_below_min_is_rejected_for_confirmed_member(self, member_user, tenant):
        """A confirmed (non-trial) member is bound by the tenant min/max
        window — the model's clean() enforces it on create."""
        import datetime

        from django.utils import timezone

        from apps.shared.tenants.models import TenantSettings

        TenantSettings.objects.create(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(seconds=1),
            min_number_coop_shares=3,
            max_number_coop_shares=100,
        )
        MemberFactory(user=member_user, is_trial=False, admin_confirmed=True)
        resp = _client_for(member_user).post(
            URL_COOP_SUBSCRIBE, {"amount_of_coop_shares": 1}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_amount_is_rejected(self, member_user, tenant):
        MemberFactory(user=member_user, is_trial=False)
        resp = _client_for(member_user).post(
            URL_COOP_SUBSCRIBE, {"amount_of_coop_shares": 0}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cancelled_member_cannot_subscribe(self, member_user, tenant):
        # MEM-2: a member who has initiated their exit must not re-introduce
        # live equity by self-subscribing new shares.
        from django.utils import timezone

        MemberFactory(user=member_user, is_trial=False, cancelled_at=timezone.now())
        resp = _client_for(member_user).post(
            URL_COOP_SUBSCRIBE, {"amount_of_coop_shares": 1}, format="json"
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "member.already_cancelled"


# ---------------------------------------------------------------------------
# my_subscriptions/subscribe — member self-service subscription (abo)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMySubscriptionSubscribe:
    def _setup(self):
        """A variation with a current gross price, a payment cycle, a DSD."""
        variation = ShareTypeVariationFactory()
        ShareTypeVariationGrossPriceFactory(share_type_variation=variation)
        return variation, PaymentCycleFactory(), DeliveryStationDayFactory()

    def _payload(self, variation, payment_cycle, dsd, **over):
        data = {
            "share_type_variation": str(variation.id),
            "quantity": 1,
            "payment_cycle": str(payment_cycle.id),
            "valid_from": "2026-01-05",  # a Monday
            "valid_until": "2026-12-27",  # a Sunday (term end; no open-ended subs)
            "default_delivery_station_day": str(dsd.id),
        }
        data.update(over)
        return data

    def test_anonymous_returns_401(self, anon_client, tenant):
        resp = anon_client.post(URL_SUB_SUBSCRIBE, {}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_user_without_member_returns_404(self, member_user, tenant):
        resp = _client_for(member_user).post(URL_SUB_SUBSCRIBE, {}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_cancelled_member_cannot_subscribe(self, member_user, tenant):
        # MEM-2: a departing member must not self-subscribe a new abo (which
        # would reserve capacity + materialise on confirm). The gate fires
        # before serializer validation, so an empty body still 409s.
        from django.utils import timezone

        MemberFactory(user=member_user, is_trial=False, cancelled_at=timezone.now())
        resp = _client_for(member_user).post(URL_SUB_SUBSCRIBE, {}, format="json")
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "member.already_cancelled"

    def test_self_subscribe_creates_draft(self, member_user, tenant):
        member = MemberFactory(user=member_user)
        variation, payment_cycle, dsd = self._setup()
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            self._payload(variation, payment_cycle, dsd),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        # Created as a draft (pending office confirmation), not trial.
        assert resp.data["admin_confirmed"] is False
        sub = Subscription.objects.get(member=member)
        assert sub.admin_confirmed is False
        assert sub.is_trial is False

    # ---- Solidarity pricing ----
    def _enable_solidarity(self, tenant, allows=True):
        import datetime

        from django.utils import timezone

        from apps.shared.tenants.models import TenantSettings

        return TenantSettings.objects.create(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(seconds=1),
            allows_solidarity_pricing=allows,
        )

    def _solidarity_setup(self):
        variation = ShareTypeVariationFactory()
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=variation,
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("7.00"),
        )
        return variation, PaymentCycleFactory(), DeliveryStationDayFactory()

    def test_solidarity_off_forces_reference_price(self, member_user, tenant):
        # No solidarity setting → a member-submitted price is ignored; the
        # variation's reference price (10.00) is forced.
        member = MemberFactory(user=member_user)
        variation, payment_cycle, dsd = self._solidarity_setup()
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            self._payload(variation, payment_cycle, dsd, price_per_delivery="5.00"),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        sub = Subscription.objects.get(member=member)
        assert sub.price_per_delivery == Decimal("10.00")

    def test_solidarity_on_accepts_price_at_or_above_floor(self, member_user, tenant):
        member = MemberFactory(user=member_user)
        variation, payment_cycle, dsd = self._solidarity_setup()
        self._enable_solidarity(tenant)
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            # Enabling settings activates the start lead-time, so use a future
            # Monday >= today + lead weeks.
            self._payload(
                variation,
                payment_cycle,
                dsd,
                price_per_delivery="8.00",
                valid_from="2026-07-20",
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        sub = Subscription.objects.get(member=member)
        assert sub.price_per_delivery == Decimal("8.00")

    def test_solidarity_on_rejects_price_below_floor(self, member_user, tenant):
        MemberFactory(user=member_user)
        variation, payment_cycle, dsd = self._solidarity_setup()
        self._enable_solidarity(tenant)
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            self._payload(
                variation,
                payment_cycle,
                dsd,
                price_per_delivery="5.00",
                valid_from="2026-07-20",
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "subscription.solidarity_price_below_minimum"

    # ---- Solidarity pricing: date-resolution (floor is looked up at the
    # subscription's valid_from, not today). ShareTypeVariationGrossPrice is
    # time-bound — one window per variation, each with its own floor — so the
    # floor effective on a FUTURE valid_from can legitimately exceed today's.
    @staticmethod
    def _two_window_setup():
        """One variation with two non-overlapping gross-price windows:

          * current  ``[2026-06-29, 2026-07-19]`` floor 7.00
          * future   ``[2026-07-20, ∞)``          floor 9.00

        A subscription starting 2026-07-20 must be governed by the FUTURE
        window's higher floor (9.00), not today's (7.00). The current window
        carries an explicit ``valid_until`` so the future window's auto-
        succession (TimeBoundMixin closes an OPEN predecessor) leaves it alone.
        """
        import datetime

        variation = ShareTypeVariationFactory()
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=variation,
            valid_from=datetime.date(2026, 6, 29),  # Monday
            valid_until=datetime.date(2026, 7, 19),  # Sunday
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("7.00"),
        )
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=variation,
            valid_from=datetime.date(2026, 7, 20),  # Monday (== valid_from)
            price_per_delivery=Decimal("12.00"),
            solidarity_min_price_per_delivery=Decimal("9.00"),
        )
        return variation, PaymentCycleFactory(), DeliveryStationDayFactory()

    def test_solidarity_future_window_floor_rejects_below_future_floor(
        self, member_user, tenant
    ):
        # 8.00 clears TODAY's floor (7.00) but is below the FUTURE window's
        # floor (9.00) governing the chosen 2026-07-20 start. Proves the floor
        # is resolved at ``valid_from``, not at today — a today-anchored lookup
        # would wrongly accept 8.00.
        MemberFactory(user=member_user)
        variation, payment_cycle, dsd = self._two_window_setup()
        self._enable_solidarity(tenant)
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            self._payload(
                variation,
                payment_cycle,
                dsd,
                price_per_delivery="8.00",
                valid_from="2026-07-20",
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.solidarity_price_below_minimum"
        assert Subscription.objects.count() == 0

    def test_solidarity_future_window_floor_accepts_at_future_floor(
        self, member_user, tenant
    ):
        # 9.00 == the future window's floor → accepted, and the stored price is
        # the chosen 9.00 (not today-window's reference). Lower bound of the
        # future window enforced exactly.
        member = MemberFactory(user=member_user)
        variation, payment_cycle, dsd = self._two_window_setup()
        self._enable_solidarity(tenant)
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            self._payload(
                variation,
                payment_cycle,
                dsd,
                price_per_delivery="9.00",
                valid_from="2026-07-20",
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        sub = Subscription.objects.get(member=member)
        assert sub.price_per_delivery == Decimal("9.00")

    def test_solidarity_off_forces_future_window_reference_price(
        self, member_user, tenant
    ):
        # Solidarity OFF: the member-submitted price is ignored and the
        # reference price of the window effective AT valid_from (the future
        # 12.00), NOT today's window (10.00), is forced.
        member = MemberFactory(user=member_user)
        variation, payment_cycle, dsd = self._two_window_setup()
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            self._payload(
                variation,
                payment_cycle,
                dsd,
                price_per_delivery="5.00",
                valid_from="2026-07-20",
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        sub = Subscription.objects.get(member=member)
        assert sub.price_per_delivery == Decimal("12.00")

    def test_solidarity_future_only_window_is_subscribable(self, member_user, tenant):
        # A variation whose ONLY priced window starts in the future (nothing
        # active today). A today-anchored lookup would raise
        # ``subscription.no_active_price``; resolving at valid_from makes it
        # subscribable and snapshots the future window's price.
        import datetime

        member = MemberFactory(user=member_user)
        variation = ShareTypeVariationFactory()
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=variation,
            valid_from=datetime.date(2026, 7, 20),  # Monday, in the future
            price_per_delivery=Decimal("11.00"),
            solidarity_min_price_per_delivery=Decimal("8.00"),
        )
        payment_cycle, dsd = PaymentCycleFactory(), DeliveryStationDayFactory()
        self._enable_solidarity(tenant)
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            self._payload(
                variation,
                payment_cycle,
                dsd,
                price_per_delivery="8.50",
                valid_from="2026-07-20",
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        sub = Subscription.objects.get(member=member)
        assert sub.price_per_delivery == Decimal("8.50")

    def test_solidarity_on_null_floor_falls_back_to_reference(
        self, member_user, tenant
    ):
        # Floor is NULL → the guard floors at the reference price (10.00). A
        # below-reference price is rejected even though no explicit floor is
        # set. Exercises the ``solidarity_min or price_per_delivery`` fallback
        # branch (the existing tests all set an explicit floor).
        MemberFactory(user=member_user)
        variation = ShareTypeVariationFactory()
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=variation,
            price_per_delivery=Decimal("10.00"),
            # solidarity_min_price_per_delivery left NULL (factory default).
        )
        payment_cycle, dsd = PaymentCycleFactory(), DeliveryStationDayFactory()
        self._enable_solidarity(tenant)
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            self._payload(
                variation,
                payment_cycle,
                dsd,
                price_per_delivery="6.00",
                valid_from="2026-07-20",
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.solidarity_price_below_minimum"

    # ---- Office path: the shared SubscriptionSerializer floor guard applies to
    # the office abos-create too (it does NOT distinguish member vs office —
    # with solidarity ON, a below-floor office price is rejected just the same).
    def test_office_solidarity_on_rejects_below_floor(self, api_client, tenant):
        variation, payment_cycle, dsd = self._two_window_setup()
        self._enable_solidarity(tenant)
        member = MemberFactory()
        resp = api_client.post(
            reverse("abos-list"),
            {
                "member": str(member.id),
                "share_type_variation": str(variation.id),
                "quantity": 1,
                "payment_cycle": str(payment_cycle.id),
                "valid_from": "2026-07-20",
                "valid_until": "2026-12-27",
                "default_delivery_station_day": str(dsd.id),
                "is_trial": False,
                # 8.00 clears today's 7.00 floor but is below the future
                # window's 9.00 floor governing the 2026-07-20 start.
                "price_per_delivery": "8.00",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.solidarity_price_below_minimum"
        assert Subscription.objects.count() == 0

    def test_office_solidarity_on_accepts_at_floor(self, api_client, tenant):
        variation, payment_cycle, dsd = self._two_window_setup()
        self._enable_solidarity(tenant)
        member = MemberFactory()
        resp = api_client.post(
            reverse("abos-list"),
            {
                "member": str(member.id),
                "share_type_variation": str(variation.id),
                "quantity": 1,
                "payment_cycle": str(payment_cycle.id),
                "valid_from": "2026-07-20",
                "valid_until": "2026-12-27",
                "default_delivery_station_day": str(dsd.id),
                "is_trial": False,
                "price_per_delivery": "9.00",  # == future window floor
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        sub = Subscription.objects.get(member=member)
        assert sub.price_per_delivery == Decimal("9.00")

    # ---- Model guard: ShareTypeVariationGrossPrice.clean() rejects a floor
    # above the reference price. Load-bearing via TimeBoundMixin.save() →
    # full_clean(); a refactor dropping that call silently disables it.
    def test_gross_price_clean_rejects_floor_above_reference(self, tenant):
        from django.core.exceptions import ValidationError

        from apps.commissioning.models import ShareTypeVariationGrossPrice

        variation = ShareTypeVariationFactory()
        bad_price = ShareTypeVariationGrossPrice(
            share_type_variation=variation,
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("11.00"),  # > reference
            tax_rate=Decimal("7.00"),
        )
        with pytest.raises(ValidationError) as exc:
            bad_price.full_clean()
        assert "solidarity_min_price_per_delivery" in exc.value.message_dict

    def test_gross_price_clean_allows_floor_equal_to_reference(self, tenant):
        # Floor == reference is the boundary case — allowed (the guard rejects
        # strictly greater). save() runs full_clean(), so a successful save
        # proves clean() let it through.
        import datetime

        from apps.commissioning.models import ShareTypeVariationGrossPrice

        variation = ShareTypeVariationFactory()
        price = ShareTypeVariationGrossPrice(
            share_type_variation=variation,
            valid_from=datetime.date(2026, 1, 5),  # Monday
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("10.00"),  # == reference
            tax_rate=Decimal("7.00"),
        )
        price.save()  # full_clean() inside save() must not raise
        assert price.pk is not None

    def test_cannot_subscribe_for_another_member(self, member_user, tenant):
        """A member can only ever subscribe for THEMSELVES — the member is
        taken from the token, and any ``member`` in the body is ignored."""
        me = MemberFactory(user=member_user)
        someone_else = MemberFactory()
        variation, payment_cycle, dsd = self._setup()
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            self._payload(variation, payment_cycle, dsd, member=str(someone_else.id)),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert Subscription.objects.filter(member=someone_else).count() == 0
        assert Subscription.objects.filter(member=me).count() == 1

    def test_member_cannot_force_trial_or_price(self, member_user, tenant):
        # is_trial is forced False and price comes from the variation's gross
        # price, even if the member tries to inject them.
        from decimal import Decimal

        MemberFactory(user=member_user)
        variation, payment_cycle, dsd = self._setup()
        resp = _client_for(member_user).post(
            URL_SUB_SUBSCRIBE,
            self._payload(
                variation,
                payment_cycle,
                dsd,
                is_trial=True,
                price_per_delivery="0.01",
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        sub = Subscription.objects.get()
        assert sub.is_trial is False
        # ShareTypeVariationGrossPriceFactory default price_per_delivery.
        assert sub.price_per_delivery == Decimal("10.00")


# ---------------------------------------------------------------------------
# my_membership/cancel (self-service membership cancellation)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMyMembershipCancel:
    def test_anonymous_returns_401(self, anon_client, tenant):
        resp = anon_client.post(URL_MEMBERSHIP_CANCEL, {}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_user_without_member_returns_404(self, member_user, tenant):
        resp = _client_for(member_user).post(
            URL_MEMBERSHIP_CANCEL, {"effective_at": "2026-12-31"}, format="json"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_self_cancel_without_active_subscriptions(self, member_user, tenant):
        member = MemberFactory(user=member_user, admin_confirmed=True)
        share = CoopShareFactory(member=member)
        resp = _client_for(member_user).post(
            URL_MEMBERSHIP_CANCEL,
            {"effective_at": "2026-12-31", "reason": "leaving"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        share.refresh_from_db()
        assert member.cancelled_at is not None
        assert member.cancellation_reason == "leaving"
        assert share.cancelled_at is not None
        assert str(share.payback_due_date) == "2026-12-31"

    def test_self_cancel_blocked_with_active_subscription(self, member_user, tenant):
        member = MemberFactory(user=member_user, admin_confirmed=True)
        SubscriptionFactory(
            member=member,
            admin_confirmed=True,
        )
        resp = _client_for(member_user).post(
            URL_MEMBERSHIP_CANCEL, {"effective_at": "2026-12-31"}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "member.has_active_subscriptions"
        member.refresh_from_db()
        assert member.cancelled_at is None

    def test_self_cancel_requires_effective_at(self, member_user, tenant):
        MemberFactory(user=member_user, admin_confirmed=True)
        resp = _client_for(member_user).post(URL_MEMBERSHIP_CANCEL, {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_self_cancel_rejects_past_effective_at(self, member_user, tenant):
        # BIZ-2: a member may not backdate their own exit — that would rewrite
        # the GenG Austrittsdatum and shrink the coop-share payback window
        # without office review. Backdating stays office-only.
        member = MemberFactory(user=member_user, admin_confirmed=True)
        CoopShareFactory(member=member)
        resp = _client_for(member_user).post(
            URL_MEMBERSHIP_CANCEL,
            {"effective_at": "2020-01-01"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "member.cancel.effective_at_in_past"
        member.refresh_from_db()
        assert member.cancelled_at is None

    def test_self_cancel_already_cancelled_returns_409(self, member_user, tenant):
        from django.utils import timezone

        MemberFactory(
            user=member_user, admin_confirmed=True, cancelled_at=timezone.now()
        )
        resp = _client_for(member_user).post(
            URL_MEMBERSHIP_CANCEL, {"effective_at": "2026-12-31"}, format="json"
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
