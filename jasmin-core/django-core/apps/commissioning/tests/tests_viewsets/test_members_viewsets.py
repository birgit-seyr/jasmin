"""Tests for members_viewsets.py — Member, Subscription, CoopShare."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import CoopShare, Member, MemberLoan, Subscription
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SubscriptionFactory,
)


# ---------------------------------------------------------------------------
# MemberViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMemberViewSet:
    URL = reverse("member-list")

    def test_list_returns_members(self, api_client, tenant):
        MemberFactory()
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) >= 1

    def test_payback_due_date_is_latest_across_coop_shares(self, api_client, tenant):
        """``member.payback_due_date`` (annotation) = the latest
        ``payback_due_date`` across the member's coop shares; live shares
        (NULL payback) are ignored by ``Max``."""
        member = MemberFactory()
        CoopShareFactory(member=member, payback_due_date=datetime.date(2027, 1, 1))
        CoopShareFactory(member=member, payback_due_date=datetime.date(2027, 6, 1))
        CoopShareFactory(member=member, payback_due_date=None)
        resp = api_client.get(self.URL)
        row = next(r for r in resp.data if r["id"] == str(member.id))
        assert row["payback_due_date"] == "2027-06-01"

    def test_coop_shares_total_excludes_cancelled(self, api_client, tenant):
        # coop_shares_total must count only LIVE shares (cancelled /
        # divested = 0 equity), matching the enforced min-equity invariant.
        from django.utils import timezone

        member = MemberFactory()
        CoopShareFactory(member=member, amount_of_coop_shares=3)
        CoopShareFactory(
            member=member, amount_of_coop_shares=5, cancelled_at=timezone.now()
        )
        resp = api_client.get(self.URL)
        row = next(m for m in resp.data if m["id"] == str(member.id))
        # Live total is 3 (the cancelled 5-share row is excluded), not 8.
        assert Decimal(str(row["coop_shares_total"])) == Decimal("3")

    def test_filter_is_active(self, api_client, tenant):
        MemberFactory(is_active=True)
        MemberFactory(is_active=False)
        resp = api_client.get(self.URL, {"is_active": "true"})
        for m in resp.data:
            assert m["is_active"] is True

    def test_filter_is_trial(self, api_client, tenant):
        MemberFactory(is_trial=True)
        MemberFactory(is_trial=False)
        resp = api_client.get(self.URL, {"is_trial": "true"})
        for m in resp.data:
            assert m["is_trial"] is True

    def test_exclude_trial_members(self, api_client, tenant):
        MemberFactory(is_trial=True)
        MemberFactory(is_trial=False)
        resp = api_client.get(self.URL, {"exclude_trial_members": "true"})
        for m in resp.data:
            assert m["is_trial"] is False

    def test_exclude_trial_members_false_keeps_everyone(self, api_client, tenant):
        """The flag is one-armed: an explicit false means "don't exclude", not
        "only trial members" (which is what applying it as a value filter
        would do)."""
        trial = MemberFactory(is_trial=True)
        regular = MemberFactory(is_trial=False)

        for raw in ("false", "0"):
            resp = api_client.get(self.URL, {"exclude_trial_members": raw})
            ids = {m["id"] for m in resp.data}
            assert {str(trial.id), str(regular.id)} <= ids, raw

    def test_exclude_trial_members_absent_keeps_everyone(self, api_client, tenant):
        trial = MemberFactory(is_trial=True)
        regular = MemberFactory(is_trial=False)
        resp = api_client.get(self.URL)
        ids = {m["id"] for m in resp.data}
        assert {str(trial.id), str(regular.id)} <= ids

    def test_export_csv_member_register(self, api_client, tenant):
        # GenG §30 register for a window: an admitted member (entry_date set)
        # with shares is listed; a never-admitted applicant is excluded.
        import datetime

        member = MemberFactory(
            admin_confirmed=True,
            entry_date=datetime.date(2026, 1, 15),
            first_name="Anna",
            last_name="Acker",
            member_number=4321,
            address="Feldweg 1",
            zip_code="12345",
            city="Ackerstadt",
        )
        CoopShareFactory(
            member=member,
            admin_confirmed=True,
            amount_of_coop_shares=Decimal("5"),
            value_one_coop_share=100,
        )
        # Not yet admitted (no entry_date) → not on the register.
        MemberFactory(admin_confirmed=False, entry_date=None, last_name="Pending")

        resp = api_client.get(
            reverse("member-export-csv"),
            {"date_from": "2026-01-01", "date_to": "2026-06-30"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp["Content-Type"].startswith("text/csv")
        content = b"".join(resp.streaming_content).decode("utf-8")
        assert "Mitgliedsnummer" in content  # German header
        assert "Acker" in content and "4321" in content  # the admitted member
        assert "Pending" not in content  # never admitted → excluded

    def test_export_csv_requires_date_range(self, api_client, tenant):
        resp = api_client.get(reverse("member-export-csv"))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_confirm_member(self, api_client, tenant):
        member = MemberFactory(admin_confirmed=False)
        url = reverse("member-confirm", kwargs={"pk": member.pk})
        resp = api_client.post(url)
        assert resp.status_code == status.HTTP_200_OK
        member.refresh_from_db()
        assert member.admin_confirmed is True

    def test_office_can_set_membership_paper_received(self, api_client, tenant):
        # The office records the signed paper membership declaration via this
        # field on the office serializer (fields="__all__"); the date round-trips.
        member = MemberFactory()
        resp = api_client.patch(
            reverse("member-detail", kwargs={"pk": member.pk}),
            {"membership_paper_received_at": "2026-06-30"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        member.refresh_from_db()
        assert str(member.membership_paper_received_at) == "2026-06-30"

    def test_confirm_member_cascades_to_pending_coop_shares(self, api_client, tenant):
        # Admitting a member confirms their pending (self-subscribed) shares.
        member = MemberFactory(admin_confirmed=False, is_trial=False)
        share = CoopShareFactory(member=member, admin_confirmed=False)
        resp = api_client.post(reverse("member-confirm", kwargs={"pk": member.pk}))
        assert resp.status_code == status.HTTP_200_OK
        share.refresh_from_db()
        assert share.admin_confirmed is True
        assert share.admin_confirmed_by is not None

    def test_office_cancel_member_cascades_and_snapshots_payback(
        self, api_client, tenant
    ):
        import datetime

        # Entry must precede the cancellation effective date — MemberFactory
        # defaults entry_date to today, so pin it before the exit date.
        member = MemberFactory(
            admin_confirmed=True, entry_date=datetime.date(2026, 1, 5)
        )
        share = CoopShareFactory(member=member)
        resp = api_client.post(
            reverse("member-cancel", kwargs={"pk": member.pk}),
            {"effective_at": "2026-06-29", "reason": "moved away"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        share.refresh_from_db()
        assert member.cancelled_at is not None
        assert member.cancellation_reason == "moved away"
        assert share.cancelled_at is not None
        # No TenantSettings → retention 0 → payback due on the exit date itself.
        assert share.payback_due_date == datetime.date(2026, 6, 29)

    def test_office_cancel_requires_effective_at(self, api_client, tenant):
        member = MemberFactory(admin_confirmed=True)
        resp = api_client.post(reverse("member-cancel", kwargs={"pk": member.pk}))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_office_cancel_already_cancelled_returns_409(self, api_client, tenant):
        from django.utils import timezone

        member = MemberFactory(admin_confirmed=True, cancelled_at=timezone.now())
        resp = api_client.post(
            reverse("member-cancel", kwargs={"pk": member.pk}),
            {"effective_at": "2026-06-29"},
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    @time_machine.travel(datetime.date(2026, 3, 30), tick=False)  # Monday
    def test_office_cancel_refused_with_active_subscription(self, api_client, tenant):
        # By default the office cancel is REFUSED while the member holds
        # an active subscription — end it first, or force-cancel.
        from apps.commissioning.tests.factories import SubscriptionFactory

        member = MemberFactory(admin_confirmed=True)
        SubscriptionFactory(
            member=member,
            admin_confirmed=True,
            valid_until=datetime.date(2026, 4, 5),  # Sunday, still active (>= today)
        )
        resp = api_client.post(
            reverse("member-cancel", kwargs={"pk": member.pk}),
            {"effective_at": "2026-04-12"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "member.has_active_subscriptions"
        member.refresh_from_db()
        assert member.cancelled_at is None  # nothing was written

    @time_machine.travel(datetime.date(2026, 3, 30), tick=False)  # Monday
    def test_office_force_cancel_bypasses_active_subscription(self, api_client, tenant):
        # force=True ends the membership anyway; the response reports any
        # subscription it could not end.
        from apps.commissioning.tests.factories import SubscriptionFactory

        member = MemberFactory(admin_confirmed=True)
        SubscriptionFactory(
            member=member,
            admin_confirmed=True,
            valid_until=datetime.date(2026, 4, 5),  # ends on/before the exit
        )
        resp = api_client.post(
            reverse("member-cancel", kwargs={"pk": member.pk}),
            {"effective_at": "2026-04-12", "force": True},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["subscriptions_not_ended"] == []
        assert resp.data["member"]["id"] == member.id
        member.refresh_from_db()
        assert member.cancelled_at is not None

    @time_machine.travel(datetime.date(2026, 3, 30), tick=False)  # Monday
    def test_office_cancel_force_false_string_does_not_force(self, api_client, tenant):
        """``force`` is parsed, not truth-tested: the strings "false" and "0"
        mean "do not force", so the active-subscription restraint still refuses
        the cancel and nothing is written."""
        from apps.commissioning.tests.factories import (
            ShareTypeVariationFactory,
            SubscriptionFactory,
        )

        # Built once: a second OPEN SharesDeliveryDay for the same day_number
        # (which a second SubscriptionFactory would create) is refused by the
        # one-open-per-day constraint.
        station_day = DeliveryStationDayFactory()
        variation = ShareTypeVariationFactory()

        for raw_force in ("false", "0"):
            member = MemberFactory(admin_confirmed=True)
            SubscriptionFactory(
                member=member,
                admin_confirmed=True,
                valid_until=datetime.date(2026, 4, 5),  # Sunday, still active
                default_delivery_station_day=station_day,
                share_type_variation=variation,
            )
            resp = api_client.post(
                reverse("member-cancel", kwargs={"pk": member.pk}),
                {"effective_at": "2026-04-12", "force": raw_force},
                format="json",
            )
            assert resp.status_code == status.HTTP_400_BAD_REQUEST, raw_force
            assert resp.data["code"] == "member.has_active_subscriptions"
            member.refresh_from_db()
            assert member.cancelled_at is None  # nothing was written

    @time_machine.travel(datetime.date(2026, 3, 30), tick=False)  # Monday
    def test_office_cancel_force_true_string_still_forces(self, api_client, tenant):
        """The string spellings stay accepted alongside a JSON boolean, so a
        client that sends ``"true"`` keeps working."""
        from apps.commissioning.tests.factories import SubscriptionFactory

        member = MemberFactory(admin_confirmed=True)
        SubscriptionFactory(
            member=member,
            admin_confirmed=True,
            valid_until=datetime.date(2026, 4, 5),
        )
        resp = api_client.post(
            reverse("member-cancel", kwargs={"pk": member.pk}),
            {"effective_at": "2026-04-12", "force": "true"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.cancelled_at is not None

    @time_machine.travel(datetime.date(2026, 3, 30), tick=False)  # Monday
    def test_office_cancel_unparseable_force_is_400(self, api_client, tenant):
        member = MemberFactory(admin_confirmed=True)
        resp = api_client.post(
            reverse("member-cancel", kwargs={"pk": member.pk}),
            {"effective_at": "2026-04-12", "force": "maybe"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "force"
        member.refresh_from_db()
        assert member.cancelled_at is None

    def test_confirm_already_confirmed_returns_409(self, api_client, tenant):
        # MemberAlreadyConfirmed is a ConflictError -> 409 (not 400).
        member = MemberFactory(admin_confirmed=True)
        url = reverse("member-confirm", kwargs={"pk": member.pk})
        resp = api_client.post(url)
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_reject_member(self, api_client, tenant):
        member = MemberFactory(admin_confirmed=False)
        url = reverse("member-reject", kwargs={"pk": member.pk})
        resp = api_client.post(url, {"reason": "Duplicate"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        member.refresh_from_db()
        assert member.admin_rejection_reason == "Duplicate"

    def test_retrieve_member(self, api_client, tenant):
        member = MemberFactory()
        url = reverse("member-detail", kwargs={"pk": member.pk})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == str(member.pk)


# ---------------------------------------------------------------------------
# SubscriptionViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSubscriptionViewSet:
    URL = reverse("abos-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_subscriptions(self, api_client, tenant):
        SubscriptionFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_by_is_trial(self, api_client, tenant):
        dsd = DeliveryStationDayFactory()
        m1 = MemberFactory()
        m2 = MemberFactory()
        SubscriptionFactory(
            is_trial=True,
            member=m1,
            default_delivery_station_day=dsd,
        )
        SubscriptionFactory(
            is_trial=False,
            member=m2,
            default_delivery_station_day=dsd,
        )
        resp = api_client.get(self.URL, {"is_trial": "true"})
        for s in resp.data:
            assert s["is_trial"] is True

    def test_filter_by_member(self, api_client, tenant):
        sub = SubscriptionFactory()
        member_id = sub.member.id
        resp = api_client.get(self.URL, {"member": str(member_id)})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) >= 1

    def test_joker_fields_taken_and_allowance(self, api_client, tenant):
        """``jokers_taken`` counts the subscription's joker_taken ShareDeliveries
        and ``amount_of_jokers`` is the share type's allowance (per-share-type
        joker system). Critically: the two Count annotations over the same
        ``sharedelivery`` reverse join must NOT multiply each other — assert
        the exact counts."""
        sub = SubscriptionFactory(
            share_type_variation__share_type__amount_of_jokers=5,
            share_type_variation__share_type__amount_of_donation_jokers=3,
        )
        # Reuse the SharesDeliveryDay the subscription already created (via its
        # default_delivery_station_day) for the shares + deliveries — creating
        # fresh ones trips the global ``sharesdeliveryday_one_open_per_day_number``
        # guard. Distinct shares keep the share/sub/dsd unique constraint happy.
        dsd = sub.default_delivery_station_day
        sdd = dsd.delivery_day
        stv = sub.share_type_variation
        # The share's share_type_variation must match the subscription's.
        share = ShareFactory(delivery_day=sdd, share_type_variation=stv)
        ShareDeliveryFactory(
            subscription=sub, share=share, delivery_station_day=dsd, joker_taken=True
        )

        resp = api_client.get(self.URL, {"member": str(sub.member.id)})
        assert resp.status_code == status.HTTP_200_OK
        row = next(r for r in resp.data if r["id"] == str(sub.id))
        # 1 joker_taken=True row → jokers_taken==1 (the parallel deliveries_count
        # Count over the same join does not inflate it); allowance from the type.
        assert row["jokers_taken"] == 1
        assert row["amount_of_jokers"] == 5
        # Donation-joker counterparts: allowance from the share type, 0 taken
        # (the one delivery above is a regular joker, not a donation).
        assert row["amount_of_donation_jokers"] == 3
        assert row["donation_jokers_taken"] == 0

    def test_joker_and_donation_joker_are_mutually_exclusive(self, tenant):
        """A delivery can't be both a skip (joker) and a donation — the model
        ``clean`` rejects both flags set at once."""
        from django.core.exceptions import ValidationError

        sub = SubscriptionFactory()
        dsd = sub.default_delivery_station_day
        sdd = dsd.delivery_day
        stv = sub.share_type_variation
        share = ShareFactory(delivery_day=sdd, share_type_variation=stv)
        delivery = ShareDeliveryFactory(
            subscription=sub, share=share, delivery_station_day=dsd, joker_taken=True
        )
        delivery.donation_joker_taken = True
        with pytest.raises(ValidationError):
            delivery.save()  # full_clean() in save() enforces the invariant

    def test_confirm_blocked_for_cancelled_member(self, api_client, tenant):
        # Confirming a pending subscription for a member who has
        # initiated their exit must be refused — it would materialise deliveries
        # + PLANNED charges and back-cascade member.confirm() onto a departed
        # member.
        from django.utils import timezone

        sub = SubscriptionFactory()
        assert not sub.admin_confirmed
        member = sub.member
        member.cancelled_at = timezone.now()
        member.save(update_fields=["cancelled_at"])

        resp = api_client.post(reverse("abos-confirm", kwargs={"pk": sub.pk}))
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "member.already_cancelled"
        sub.refresh_from_db()
        assert not sub.admin_confirmed

    def test_reject_releases_capacity_reservation(self, api_client, tenant):
        # Rejecting a draft must free its held station-day slot. Reject
        # only stamps flags (no row delete), so the CASCADE never fires — the
        # action must release the reservation explicitly, else the slot stays
        # blocked for the 14-day TTL.
        import datetime

        from django.utils import timezone

        from apps.commissioning.models import CapacityReservation

        sub = SubscriptionFactory()
        CapacityReservation.objects.create(
            subscription=sub,
            delivery_station_day=sub.default_delivery_station_day,
            year=2026,
            week=10,
            expires_at=timezone.now() + datetime.timedelta(days=1),
        )

        resp = api_client.post(reverse("abos-reject", kwargs={"pk": sub.pk}))

        assert resp.status_code == status.HTTP_200_OK, resp.data
        sub.refresh_from_db()
        assert sub.admin_confirmed is False
        assert not CapacityReservation.objects.filter(subscription=sub).exists()


# ---------------------------------------------------------------------------
# CoopShareViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCoopShareViewSet:
    URL = reverse("coop_shares-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_shares(self, api_client, tenant):
        CoopShareFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_by_member(self, api_client, tenant):
        cs = CoopShareFactory()
        resp = api_client.get(self.URL, {"member": str(cs.member.id)})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) >= 1

    def test_office_create_auto_confirms(self, api_client, tenant):
        """Office-created shares are confirmed by definition (the office is
        the authority) — unlike member self-service shares."""
        member = MemberFactory(is_trial=True)
        resp = api_client.post(
            self.URL,
            {
                "member": str(member.id),
                "amount_of_coop_shares": 2,
                "value_one_coop_share": 100,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["admin_confirmed"] is True
        share = CoopShare.objects.get(pk=resp.data["id"])
        assert share.admin_confirmed is True
        assert share.admin_confirmed_by is not None

    def test_confirm_action_confirms_pending_share(self, api_client, tenant):
        """The confirm action flips a pending (e.g. self-subscribed) share."""
        member = MemberFactory(admin_confirmed=True)
        share = CoopShareFactory(member=member, admin_confirmed=False)
        url = reverse("coop_shares-confirm", kwargs={"pk": share.pk})
        resp = api_client.post(url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["admin_confirmed"] is True
        share.refresh_from_db()
        assert share.admin_confirmed is True
        assert share.admin_confirmed_by is not None

    def test_confirm_share_admits_unconfirmed_member(self, api_client, tenant):
        # Vice-versa: confirming a share of a not-yet-admitted member admits
        # the member too (initial admission from the equity side).
        member = MemberFactory(admin_confirmed=False, is_trial=False)
        share = CoopShareFactory(member=member, admin_confirmed=False)
        resp = api_client.post(reverse("coop_shares-confirm", kwargs={"pk": share.pk}))
        assert resp.status_code == status.HTTP_200_OK
        member.refresh_from_db()
        assert member.admin_confirmed is True

    def test_confirm_share_blocked_for_cancelled_member(self, api_client, tenant):
        # A departed member (cancelled_at set) must NOT be re-admitted by
        # confirming a leftover pending share: the confirm is rejected and the
        # share stays pending.
        from django.utils import timezone

        member = MemberFactory(admin_confirmed=True, cancelled_at=timezone.now())
        share = CoopShareFactory(member=member, admin_confirmed=False)
        resp = api_client.post(reverse("coop_shares-confirm", kwargs={"pk": share.pk}))
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "member.already_cancelled"
        share.refresh_from_db()
        assert share.admin_confirmed is False


# ---------------------------------------------------------------------------
# Confirmed → cancel, not delete (immutable-once-confirmed guards)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestConfirmedImmutableDeletion:
    def test_confirmed_member_cannot_be_deleted(self, api_client, tenant):
        member = MemberFactory(admin_confirmed=True)
        resp = api_client.delete(reverse("member-detail", kwargs={"pk": member.pk}))
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "member.confirmed_immutable"

    def test_unconfirmed_member_can_be_deleted(self, api_client, tenant):
        member = MemberFactory(admin_confirmed=False)
        resp = api_client.delete(reverse("member-detail", kwargs={"pk": member.pk}))
        assert resp.status_code == status.HTTP_204_NO_CONTENT

    def test_confirmed_coop_share_cannot_be_deleted(self, api_client, tenant):
        share = CoopShareFactory(admin_confirmed=True)
        resp = api_client.delete(reverse("coop_shares-detail", kwargs={"pk": share.pk}))
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "coop_share.confirmed_immutable"

    def test_unconfirmed_coop_share_can_be_deleted(self, api_client, tenant):
        share = CoopShareFactory(admin_confirmed=False)
        resp = api_client.delete(reverse("coop_shares-detail", kwargs={"pk": share.pk}))
        assert resp.status_code == status.HTTP_204_NO_CONTENT


# ---------------------------------------------------------------------------
# List filters stop at the list route
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestListFiltersDoNotScopeDetailRoutes:
    """Every one of these viewsets narrows its LIST by query params. A detail
    route addresses one row by id, so the same parameter left on the URL must
    not 404 a row that exists — nor drop the row a successful write returns."""

    def test_member_detail_ignores_a_list_filter(self, api_client, tenant):
        member = MemberFactory(is_trial=False)
        resp = api_client.get(
            reverse("member-detail", kwargs={"pk": member.pk}), {"is_trial": "true"}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == member.id

    def test_member_patch_is_not_refused_by_a_list_filter(self, api_client, tenant):
        member = MemberFactory(is_trial=False)
        resp = api_client.patch(
            reverse("member-detail", kwargs={"pk": member.pk}) + "?is_trial=true",
            {"note": "reachable"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["note"] == "reachable"

    def test_subscription_detail_ignores_a_list_filter(self, api_client, tenant):
        subscription = SubscriptionFactory(is_trial=False)
        resp = api_client.get(
            reverse("abos-detail", kwargs={"pk": subscription.pk}), {"is_trial": "true"}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == subscription.id

    def test_coop_share_detail_ignores_the_year_filter(self, api_client, tenant):
        share = CoopShareFactory()
        resp = api_client.get(
            reverse("coop_shares-detail", kwargs={"pk": share.pk}), {"year": 1999}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == share.id

    def test_member_loan_detail_ignores_the_year_filter(self, api_client, tenant):
        loan = MemberLoan.objects.create(
            member=MemberFactory(),
            amount=500,
            interest_rate=Decimal("1.50"),
            start_date=datetime.date(2026, 1, 5),
        )
        resp = api_client.get(
            reverse("member_loans-detail", kwargs={"pk": loan.pk}), {"year": 1999}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == loan.id


@pytest.mark.django_db
class TestMemberRegisterExportDateRange:
    def test_inverted_range_is_refused(self, api_client, tenant):
        resp = api_client.get(
            reverse("member-export-csv"),
            {"date_from": "2026-02-01", "date_to": "2026-01-01"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "date_from"


@pytest.mark.django_db
class TestBulkRenewIdList:
    """``bulk_renew`` reads its id array through the shared bulk parser, so a
    malformed list is refused with the same code as every other bulk-by-ids
    endpoint — and refused before any subscription is renewed."""

    URL = reverse("abos-bulk-renew")

    def test_a_non_string_id_is_refused_before_anything_is_renewed(
        self, api_client, tenant
    ):
        resp = api_client.post(
            self.URL, {"subscription_ids": ["some-id", 17]}, format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "bulk.ids_invalid"
        assert resp.data["field"] == "subscription_ids"
        assert not Subscription.objects.filter(
            previous_subscription__isnull=False
        ).exists()


@pytest.mark.django_db
class TestMemberCreateNonStringEmail:
    """``create`` reads ``email`` off the body to look for an existing
    JasminUser before the serializer runs. A non-string value is refused by the
    serializer's ``EmailField`` instead of reaching ``.strip()``, and never
    reaches the lookup — so it cannot report whether an account exists."""

    URL = reverse("member-list")

    @pytest.mark.parametrize(
        "bad_email", [["ada@example.com"], 17, {"address": "ada@example.com"}, True]
    )
    def test_a_non_string_email_is_a_clean_400(self, api_client, tenant, bad_email):
        resp = api_client.post(
            self.URL,
            {"first_name": "Ada", "last_name": "Lovelace", "email": bad_email},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "validation_error"
        assert resp.data["field"] == "email"
        assert not Member.objects.filter(first_name="Ada").exists()

    def test_a_non_string_email_cannot_probe_for_an_existing_account(
        self, api_client, tenant
    ):
        # The address belongs to a user in a link-blocking status, so the
        # well-formed request answers with the conflict.
        JasminUserFactory(email="taken@example.com", account_status="pending_approval")
        taken = api_client.post(
            self.URL, {"first_name": "A", "email": "taken@example.com"}, format="json"
        )
        assert taken.status_code == status.HTTP_409_CONFLICT, taken.data

        # The malformed variants of a taken and an unused address must be
        # indistinguishable, or the refusal leaks the account's existence.
        malformed_taken = api_client.post(
            self.URL, {"first_name": "A", "email": ["taken@example.com"]}, format="json"
        )
        malformed_unused = api_client.post(
            self.URL,
            {"first_name": "A", "email": ["nobody@example.com"]},
            format="json",
        )

        assert malformed_taken.status_code == status.HTTP_400_BAD_REQUEST
        assert malformed_taken.status_code == malformed_unused.status_code
        assert malformed_taken.data["code"] == malformed_unused.data["code"]
        assert malformed_taken.data["message"] == malformed_unused.data["message"]

    def test_a_string_email_still_trims_and_links_the_existing_user(
        self, api_client, tenant
    ):
        JasminUserFactory(email="Ada.Linked@Example.com", account_status="active")

        resp = api_client.post(
            self.URL,
            {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "  Ada.Linked@Example.com  ",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        # The lookup only matches once the surrounding whitespace is stripped.
        assert resp.data["linked_user_info"] is not None


@pytest.mark.django_db
class TestMemberCreateIdentityFloor:
    """``create`` refuses a body that names nobody.

    Every Member column is nullable or defaulted and ``MemberSerializer``
    declares no required field, so serializer validation alone accepts an empty
    body — and the legally-relevant register gains a row with no holder.
    """

    URL = reverse("member-list")

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({}, id="empty-object"),
            pytest.param({"note": "walk-in, papers to follow"}, id="note-only"),
            pytest.param({"is_active": True, "is_student": True}, id="flags-only"),
            pytest.param(
                {"address": "Feldweg 1", "zip_code": "12345", "city": "Ackerstadt"},
                id="address-only",
            ),
            pytest.param({"first_name": "   ", "last_name": ""}, id="blank-names"),
        ],
    )
    def test_a_body_without_an_identifying_field_is_refused(
        self, api_client, tenant, payload
    ):
        before = Member.objects.count()

        resp = api_client.post(self.URL, payload, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "member.identity_required"
        assert "company_name" in resp.data["details"]["any_of"]
        assert Member.objects.count() == before

    def test_a_json_array_body_is_refused(self, api_client, tenant):
        # ``body()`` yields {} for a body that is not a JSON object, so the
        # array's contents never reach the serializer and the create would
        # otherwise persist an empty row.
        before = Member.objects.count()

        resp = api_client.post(self.URL, [{"first_name": "Ada"}], format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "member.identity_required"
        assert Member.objects.count() == before

    @pytest.mark.parametrize(
        "field_name, value",
        [
            ("first_name", "Ada"),
            ("last_name", "Lovelace"),
            # A company member carries no natural-person name.
            ("company_name", "Hofladen GmbH"),
            ("pickup_name", "Ada L."),
            ("email", "identity.floor@example.com"),
            ("email_2", "second.floor@example.com"),
            ("email_3", "third.floor@example.com"),
        ],
    )
    def test_one_identifying_field_is_enough(
        self, api_client, tenant, field_name, value
    ):
        resp = api_client.post(self.URL, {field_name: value}, format="json")

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert Member.objects.filter(**{field_name: value}).exists()

    def test_an_ordinary_create_still_works(self, api_client, tenant):
        resp = api_client.post(
            self.URL,
            {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada.identity-floor@example.com",
                "address": "Feldweg 1",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert Member.objects.filter(email="ada.identity-floor@example.com").exists()

    def test_a_patch_carrying_no_identifying_field_is_unaffected(
        self, api_client, tenant
    ):
        # The floor is on create only: an ordinary edit sends just the field it
        # changes, and the stored row already names its holder.
        member = MemberFactory()

        resp = api_client.patch(
            reverse("member-detail", kwargs={"pk": member.pk}),
            {"note": "edited"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.note == "edited"
