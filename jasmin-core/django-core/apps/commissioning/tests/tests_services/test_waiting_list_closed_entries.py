"""A waiting-list entry that is out of the running — its subscription cancelled
or rejected, or its member gone or rejected — is never offered a spot, and its
open offer can't be accepted. Rejecting the subscription or the member, and the
member's exit, take the entry off the list and cancel its open offer, freeing
the station-day slot and the variation slot the offer held. Rejecting the member
rejects the member's open subscriptions with it, an accepted offer among them,
and no offer, open or accepted, of a member rejected or gone holds a variation
slot.

The station-day reservation is real here, so "the slot is free" means one more
subscription fits both capacity gates; only the offer email is stubbed.
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.commissioning.errors import (
    DeliveryStationOverCapacity,
    SubscriptionDeliveryStationDayOutOfRange,
    WaitingListOfferEntryClosed,
    WaitingListOfferInvalid,
)
from apps.commissioning.models import (
    CapacityReservation,
    DeliveryStationDay,
    Member,
    Subscription,
)
from apps.commissioning.services.capacity_reservation_service import (
    CapacityReservationService,
)
from apps.commissioning.services.member_cancellation import (
    cancel_member_with_coop_shares,
)
from apps.commissioning.services.variation_capacity_service import (
    VariationCapacityService,
)
from apps.commissioning.services.waiting_list_offer_service import (
    WaitingListOfferService,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)

VALID_FROM = datetime.date(2026, 9, 7)  # Monday
VALID_UNTIL = datetime.date(2026, 9, 27)  # Sunday: three delivery weeks


@pytest.fixture(autouse=True)
def _frozen_clock_without_offer_email():
    """Pin "now" to a Monday well before the term, so its weeks stay
    reservable, and keep the offer email (covered by its own suite) out."""
    with (
        time_machine.travel(datetime.datetime(2026, 7, 20, 12, 0), tick=False),
        mock.patch.object(
            WaitingListOfferService, "_send_offer_email", return_value=None
        ),
    ):
        yield


@pytest.fixture
def station_day(tenant):
    """A station-day with room for one box a week."""
    return DeliveryStationDayFactory(
        delivery_day=SharesDeliveryDayFactory(day_number=2), capacity=1
    )


@pytest.fixture
def variation(tenant):
    """A harvest-share variation with room for one subscription."""
    return ShareTypeVariationFactory(
        share_type=ShareTypeFactory(share_option="HARVEST_SHARE"), capacity=1
    )


def _draft(variation, station_day, *, member) -> Subscription:
    """A subscription off the waiting list, awaiting the office."""
    return SubscriptionFactory(
        member=member,
        share_type_variation=variation,
        default_delivery_station_day=station_day,
        valid_from=VALID_FROM,
        valid_until=VALID_UNTIL,
    )


def _entry(variation, station_day, *, member=None) -> Subscription:
    """A pending waiting-list entry."""
    return SubscriptionFactory(
        member=member or MemberFactory(),
        share_type_variation=variation,
        default_delivery_station_day=station_day,
        valid_from=VALID_FROM,
        valid_until=VALID_UNTIL,
        admin_confirmed=False,
        on_waiting_list=True,
        waiting_list_status=Subscription.WaitingListStatus.PENDING,
        waiting_list_position=1,
    )


def _offered(variation, station_day, *, member=None) -> Subscription:
    """A waiting-list entry the office has offered the one free slot."""
    entry = _entry(variation, station_day, member=member)
    WaitingListOfferService.offer_spot(entry)
    entry.refresh_from_db()
    assert entry.waiting_list_status == Subscription.WaitingListStatus.SPOT_AVAILABLE
    return entry


def _slot_is_free(variation, station_day) -> bool:
    """Whether one more subscription for the term fits the variation's cap and
    the station-day's. Probes only: neither check reserves anything."""
    newcomer = SubscriptionFactory(
        share_type_variation=variation,
        default_delivery_station_day=station_day,
        valid_from=VALID_FROM,
        valid_until=VALID_UNTIL,
    )
    if VariationCapacityService.is_over_capacity(newcomer):
        return False
    try:
        CapacityReservationService.assert_capacity_available_for_confirm(newcomer)
    except DeliveryStationOverCapacity:
        return False
    return True


def _assert_withdrawn(entry: Subscription) -> None:
    entry.refresh_from_db()
    assert entry.on_waiting_list is False
    assert entry.waiting_list_status == Subscription.WaitingListStatus.NOT_ON_LIST
    assert entry.waiting_list_position is None
    assert entry.notification_token is None
    assert not CapacityReservation.objects.filter(subscription=entry).exists()


def _close_entry(entry: Subscription, closure: str) -> None:
    """Stamp the closure on the entry or its member and leave the entry on the
    list: an entry that closed without being withdrawn."""
    now = timezone.now()
    if closure == "subscription_cancelled":
        Subscription.objects.filter(pk=entry.pk).update(cancelled_at=now)
    elif closure == "subscription_rejected":
        Subscription.objects.filter(pk=entry.pk).update(admin_rejected_at=now)
    elif closure == "member_cancelled":
        Member.objects.filter(pk=entry.member_id).update(cancelled_at=now)
    else:
        Member.objects.filter(pk=entry.member_id).update(admin_rejected_at=now)


CLOSURES = [
    "subscription_cancelled",
    "subscription_rejected",
    "member_cancelled",
    "member_rejected",
]


@pytest.mark.django_db
class TestOfferToAClosedEntry:
    @pytest.mark.parametrize("closure", CLOSURES)
    def test_refused_with_the_code_before_anything_changes(
        self, variation, station_day, closure
    ):
        entry = _entry(variation, station_day)
        _close_entry(entry, closure)

        with pytest.raises(WaitingListOfferEntryClosed) as refused:
            WaitingListOfferService.offer_spot(entry)

        assert refused.value.code == "waiting_list_offer.entry_closed"
        entry.refresh_from_db()
        assert entry.waiting_list_status == Subscription.WaitingListStatus.PENDING
        assert entry.notification_token is None
        assert not CapacityReservation.objects.filter(subscription=entry).exists()
        assert _slot_is_free(variation, station_day)

    def test_the_office_offering_to_a_rejected_member_gets_409_with_the_code(
        self, api_client, email_config, variation, station_day
    ):
        """The office rejects the member, then clicks Notify on the waiting-list
        page it loaded before."""
        entry = _entry(variation, station_day)
        rejected = api_client.post(
            reverse("member-reject", kwargs={"pk": entry.member_id}),
            {"reason": "Duplicate"},
            format="json",
        )
        assert rejected.status_code == status.HTTP_200_OK, rejected.data

        resp = api_client.post(
            reverse("abos-offer-spot", kwargs={"pk": entry.pk}), {}, format="json"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "waiting_list_offer.entry_closed"
        entry.refresh_from_db()
        assert entry.notification_token is None
        assert not CapacityReservation.objects.filter(subscription=entry).exists()

    def test_an_open_entry_is_still_offered(self, variation, station_day):
        entry = _offered(variation, station_day)

        assert entry.notification_token is not None
        assert CapacityReservation.objects.filter(subscription=entry).exists()
        assert not _slot_is_free(variation, station_day)


@pytest.mark.django_db
class TestOpenOfferOfAClosedEntry:
    """An offer that was already open when its entry closed without being
    withdrawn: the link answers like an unknown one, and the refused accept
    withdraws the entry, freeing the slot."""

    @pytest.mark.parametrize("closure", CLOSURES)
    def test_the_link_reads_as_invalid(
        self, anon_client, variation, station_day, closure
    ):
        entry = _offered(variation, station_day)
        _close_entry(entry, closure)

        resp = anon_client.get(
            reverse(
                "waiting_list_offer_detail",
                kwargs={"token": entry.notification_token},
            )
        )

        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.data
        assert resp.data["code"] == "waiting_list_offer.invalid"

    @pytest.mark.parametrize("closure", CLOSURES)
    def test_accepting_is_refused_as_invalid_and_frees_the_slot(
        self, anon_client, variation, station_day, closure
    ):
        entry = _offered(variation, station_day)
        _close_entry(entry, closure)
        assert not _slot_is_free(variation, station_day)

        resp = anon_client.post(
            reverse(
                "waiting_list_offer_accept",
                kwargs={"token": entry.notification_token},
            )
        )

        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.data
        assert resp.data["code"] == "waiting_list_offer.invalid"
        _assert_withdrawn(entry)
        assert entry.response_received_at is None
        assert _slot_is_free(variation, station_day)

    def test_an_open_entry_still_accepts(self, variation, station_day):
        entry = _offered(variation, station_day)

        WaitingListOfferService.accept_offer(entry.notification_token)

        entry.refresh_from_db()
        assert entry.waiting_list_status == Subscription.WaitingListStatus.CONFIRMED


@pytest.mark.django_db
class TestMemberRejection:
    def test_withdraws_the_entries_and_cancels_the_open_offer(
        self, api_client, variation, station_day
    ):
        member = MemberFactory()
        offered = _offered(variation, station_day, member=member)
        pending = _entry(variation, station_day, member=member)
        other_members_entry = _entry(variation, station_day)
        token = offered.notification_token
        assert not _slot_is_free(variation, station_day)

        resp = api_client.post(
            reverse("member-reject", kwargs={"pk": member.pk}),
            {"reason": "Duplicate"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        _assert_withdrawn(offered)
        _assert_withdrawn(pending)
        other_members_entry.refresh_from_db()
        assert other_members_entry.on_waiting_list is True
        assert (
            other_members_entry.waiting_list_status
            == Subscription.WaitingListStatus.PENDING
        )
        assert other_members_entry.admin_rejected_at is None
        assert _slot_is_free(variation, station_day)
        with pytest.raises(WaitingListOfferInvalid):
            WaitingListOfferService.accept_offer(token)

    def test_an_accepted_offer_frees_both_slots(
        self, api_client, user, variation, station_day
    ):
        """The member accepted, so the entry already left the list and awaits
        the office; the office rejects the applicant on the members page."""
        entry = _offered(variation, station_day)
        WaitingListOfferService.accept_offer(entry.notification_token)
        assert not _slot_is_free(variation, station_day)

        resp = api_client.post(
            reverse("member-reject", kwargs={"pk": entry.member_id}),
            {"reason": "Duplicate"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _slot_is_free(variation, station_day)
        assert not CapacityReservation.objects.filter(subscription=entry).exists()
        entry.refresh_from_db()
        assert entry.admin_rejected_at is not None
        assert entry.admin_rejection_reason == "Duplicate"
        assert entry.admin_confirmed_by_id == user.pk
        # The accepted status stays as the record of the member's answer.
        assert entry.waiting_list_status == Subscription.WaitingListStatus.CONFIRMED

    def test_rejects_the_open_subscriptions_and_frees_their_slots(
        self, api_client, variation, station_day
    ):
        """A draft off the waiting list is part of the application too: it is
        rejected with the member and its station-day hold released, instead of
        waiting for the office as a pending subscription. A subscription
        already cancelled or rejected keeps its own stamps."""
        member = MemberFactory()
        draft = _draft(variation, station_day, member=member)
        CapacityReservationService.reserve_for_subscription(draft)
        assert not _slot_is_free(variation, station_day)
        earlier = timezone.now() - datetime.timedelta(days=3)
        cancelled = _draft(variation, station_day, member=member)
        Subscription.objects.filter(pk=cancelled.pk).update(cancelled_at=earlier)
        rejected = _draft(variation, station_day, member=member)
        Subscription.objects.filter(pk=rejected.pk).update(
            admin_rejected_at=earlier, admin_rejection_reason="Earlier"
        )

        resp = api_client.post(
            reverse("member-reject", kwargs={"pk": member.pk}),
            {"reason": "Duplicate"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _slot_is_free(variation, station_day)
        assert not CapacityReservation.objects.filter(subscription=draft).exists()
        draft.refresh_from_db()
        assert draft.admin_rejected_at is not None
        assert draft.admin_rejection_reason == "Duplicate"
        cancelled.refresh_from_db()
        assert cancelled.admin_rejected_at is None
        rejected.refresh_from_db()
        assert rejected.admin_rejected_at == earlier
        assert rejected.admin_rejection_reason == "Earlier"

    def test_an_entry_its_own_validation_refuses_is_rejected_too(
        self, api_client, variation
    ):
        """The entry's station-day ends inside the entry's term, so saving the
        entry refuses its term; the rejection still goes through."""
        station_day = DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=2)
        )
        entry = _entry(variation, station_day)
        DeliveryStationDay.objects.filter(pk=station_day.pk).update(
            valid_until=VALID_FROM + datetime.timedelta(days=6)
        )
        with pytest.raises(SubscriptionDeliveryStationDayOutOfRange):
            Subscription.objects.get(pk=entry.pk).save()

        resp = api_client.post(
            reverse("member-reject", kwargs={"pk": entry.member_id}),
            {},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        _assert_withdrawn(entry)
        assert entry.admin_rejected_at is not None


@pytest.mark.django_db
class TestSubscriptionRejection:
    def test_withdraws_the_entry_and_cancels_the_open_offer(
        self, api_client, variation, station_day
    ):
        entry = _offered(variation, station_day)
        token = entry.notification_token

        resp = api_client.post(
            reverse("abos-reject", kwargs={"pk": entry.pk}),
            {"reason": "Duplicate"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        _assert_withdrawn(entry)
        assert entry.admin_rejected_at is not None
        assert _slot_is_free(variation, station_day)
        with pytest.raises(WaitingListOfferInvalid):
            WaitingListOfferService.accept_offer(token)

    def test_a_pending_entry_leaves_the_list(self, api_client, variation, station_day):
        entry = _entry(variation, station_day)

        resp = api_client.post(
            reverse("abos-reject", kwargs={"pk": entry.pk}), {}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        _assert_withdrawn(entry)

    def test_an_accepted_offer_frees_both_slots(
        self, api_client, variation, station_day
    ):
        """The member accepted, so the entry already left the list and awaits
        the office; the office rejects it on the subscriptions page."""
        entry = _offered(variation, station_day)
        WaitingListOfferService.accept_offer(entry.notification_token)
        assert not _slot_is_free(variation, station_day)

        resp = api_client.post(
            reverse("abos-reject", kwargs={"pk": entry.pk}), {}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        entry.refresh_from_db()
        # The accepted status stays as the record of the member's answer.
        assert entry.waiting_list_status == Subscription.WaitingListStatus.CONFIRMED
        assert not CapacityReservation.objects.filter(subscription=entry).exists()
        assert _slot_is_free(variation, station_day)


@pytest.mark.django_db
class TestMemberExit:
    def test_the_open_offer_link_stops_working_and_the_slot_frees(
        self, anon_client, variation, station_day
    ):
        member = MemberFactory(admin_confirmed=True)
        offered = _offered(variation, station_day, member=member)
        pending = _entry(variation, station_day, member=member)
        token = offered.notification_token
        assert not _slot_is_free(variation, station_day)

        cancel_member_with_coop_shares(
            member, cancelled_by=JasminUserFactory(roles=["office"])
        )

        _assert_withdrawn(offered)
        _assert_withdrawn(pending)
        assert offered.cancelled_at is not None
        assert _slot_is_free(variation, station_day)
        detail = anon_client.get(
            reverse("waiting_list_offer_detail", kwargs={"token": token})
        )
        assert detail.status_code == status.HTTP_404_NOT_FOUND, detail.data
        accept = anon_client.post(
            reverse("waiting_list_offer_accept", kwargs={"token": token})
        )
        assert accept.status_code == status.HTTP_404_NOT_FOUND, accept.data
        assert accept.data["code"] == "waiting_list_offer.invalid"
        offered.refresh_from_db()
        assert offered.waiting_list_status == Subscription.WaitingListStatus.NOT_ON_LIST


@pytest.mark.django_db
class TestRejectedOccupancy:
    """A rejected subscription holds no variation slot, whether its offer is
    still open or was accepted before the rejection."""

    def test_a_rejected_open_offer_holds_no_variation_slot(
        self, variation, station_day
    ):
        entry = _offered(variation, station_day)
        newcomer = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=station_day,
            valid_from=VALID_FROM,
            valid_until=VALID_UNTIL,
        )
        assert VariationCapacityService.is_over_capacity(newcomer) is True

        Subscription.objects.filter(pk=entry.pk).update(
            admin_rejected_at=timezone.now()
        )

        assert VariationCapacityService.is_over_capacity(newcomer) is False

    def test_a_rejected_accepted_offer_holds_no_variation_slot(
        self, variation, station_day
    ):
        entry = _offered(variation, station_day)
        WaitingListOfferService.accept_offer(entry.notification_token)
        newcomer = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=station_day,
            valid_from=VALID_FROM,
            valid_until=VALID_UNTIL,
        )
        assert VariationCapacityService.is_over_capacity(newcomer) is True

        Subscription.objects.filter(pk=entry.pk).update(
            admin_rejected_at=timezone.now()
        )

        assert VariationCapacityService.is_over_capacity(newcomer) is False

    @pytest.mark.parametrize("closure", ["member_rejected", "member_cancelled"])
    @pytest.mark.parametrize("accepted", [False, True])
    def test_an_offer_to_a_member_rejected_or_gone_holds_no_variation_slot(
        self, variation, station_day, closure, accepted
    ):
        """The member is rejected or gone while the subscription carries no
        stamp of its own: neither the open offer nor the accepted one holds
        the slot."""
        entry = _offered(variation, station_day)
        if accepted:
            WaitingListOfferService.accept_offer(entry.notification_token)
        newcomer = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=station_day,
            valid_from=VALID_FROM,
            valid_until=VALID_UNTIL,
        )
        assert VariationCapacityService.is_over_capacity(newcomer) is True

        _close_entry(entry, closure)

        assert VariationCapacityService.is_over_capacity(newcomer) is False
