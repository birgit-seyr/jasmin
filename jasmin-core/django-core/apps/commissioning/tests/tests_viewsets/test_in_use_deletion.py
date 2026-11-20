"""DELETE honours ``can_be_deleted`` on share types and their variations,
plots, storages, share articles, crates, order and delivery days, delivery
stations and their pickup days, offer groups, resellers and members.

The list reports ``can_be_deleted`` from the rows that still point at an
object; the delete refuses the same objects with a 409 instead of cascading
over those rows (a plot's forecasts, an article's price history, a crate's
prices) or failing on a protected one. The delete also counts the hidden
relations (``related_name="+"``) the list leaves out to stay cheap, so it can
refuse what the list offers. An unused object still deletes.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.commissioning.models import (
    CapacityReservation,
    Crate,
    DeliveryStation,
    DeliveryStationDay,
    Member,
    OfferGroup,
    OrdersDeliveryDay,
    PaymentCycle,
    Plot,
    Reseller,
    ShareArticle,
    SharesDeliveryDay,
    ShareType,
    ShareTypeVariation,
    Storage,
)
from apps.commissioning.models.members import UserInvitation
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    CrateFactory,
    CrateNetPriceFactory,
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ForecastFactory,
    MemberFactory,
    OfferGroupFactory,
    OrdersDeliveryDayFactory,
    PaymentCycleFactory,
    PlotFactory,
    PurchaseFactory,
    ResellerFactory,
    ShareArticleFactory,
    ShareArticleNetPriceFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    StorageFactory,
    SubscriptionFactory,
    VirtualVariationComponentFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("tenant")]


def _in_use_plot():
    plot = PlotFactory()
    ForecastFactory(plot=plot)
    return plot


def _in_use_storage():
    storage = StorageFactory()
    ForecastFactory(storage=storage)
    return storage


def _in_use_share_article():
    return ShareArticleNetPriceFactory().share_article


def _in_use_crate():
    return CrateNetPriceFactory().crate


def _in_use_share_type():
    return ShareTypeVariationFactory().share_type


def _variation_in_a_virtual_one():
    # VirtualVariationComponent points at both sizes with related_name="+".
    return VirtualVariationComponentFactory().physical_variation


def _offer_group_with_a_reseller():
    group = OfferGroupFactory()
    ResellerFactory(offer_group=group)
    return group


def _station_with_a_pickup_day():
    return DeliveryStationDayFactory().delivery_station


def _station_day_a_subscription_collects_on():
    # Subscription.default_delivery_station_day has related_name="+".
    return SubscriptionFactory().default_delivery_station_day


def _delivery_day_a_subscription_collects_on():
    return SubscriptionFactory().default_delivery_station_day.delivery_day


def _pending_member_with_a_coop_share():
    # CoopShare.member has related_name="+".
    return CoopShareFactory(member=MemberFactory(admin_confirmed=False)).member


IN_USE = [
    ("plots-detail", Plot, _in_use_plot, "plot.in_use"),
    ("storages-detail", Storage, _in_use_storage, "storage.in_use"),
    (
        "share_article-detail",
        ShareArticle,
        _in_use_share_article,
        "share_article.in_use",
    ),
    ("crates-detail", Crate, _in_use_crate, "crate.in_use"),
    ("share_type-detail", ShareType, _in_use_share_type, "share_type.in_use"),
    (
        "share_type_variation-detail",
        ShareTypeVariation,
        _variation_in_a_virtual_one,
        "share_type_variation.in_use",
    ),
    (
        "offer_group-detail",
        OfferGroup,
        _offer_group_with_a_reseller,
        "offer_group.in_use",
    ),
    (
        "delivery_station-detail",
        DeliveryStation,
        _station_with_a_pickup_day,
        "delivery_station.referenced",
    ),
    (
        "delivery_station_day-detail",
        DeliveryStationDay,
        _station_day_a_subscription_collects_on,
        "delivery_station_day.referenced",
    ),
    (
        "share_delivery_day-detail",
        SharesDeliveryDay,
        _delivery_day_a_subscription_collects_on,
        "shares_delivery_day.referenced",
    ),
    ("member-detail", Member, _pending_member_with_a_coop_share, "member.in_use"),
]

UNUSED = [
    ("plots-detail", Plot, PlotFactory),
    ("storages-detail", Storage, StorageFactory),
    ("share_article-detail", ShareArticle, ShareArticleFactory),
    ("crates-detail", Crate, CrateFactory),
    ("share_type-detail", ShareType, ShareTypeFactory),
    ("orders_delivery_day-detail", OrdersDeliveryDay, OrdersDeliveryDayFactory),
    ("share_type_variation-detail", ShareTypeVariation, ShareTypeVariationFactory),
    ("offer_group-detail", OfferGroup, OfferGroupFactory),
    ("delivery_station-detail", DeliveryStation, DeliveryStationFactory),
    ("delivery_station_day-detail", DeliveryStationDay, DeliveryStationDayFactory),
    ("share_delivery_day-detail", SharesDeliveryDay, SharesDeliveryDayFactory),
]


@pytest.mark.parametrize(
    "route, model, make, code", IN_USE, ids=[row[0] for row in IN_USE]
)
def test_an_object_in_use_is_refused_and_kept(api_client, route, model, make, code):
    instance = make()

    resp = api_client.delete(reverse(route, args=[instance.pk]))

    assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
    assert resp.data["code"] == code
    assert model.objects.filter(pk=instance.pk).exists()


@pytest.mark.parametrize("route, model, make", UNUSED, ids=[row[0] for row in UNUSED])
def test_an_unused_object_is_deleted(api_client, route, model, make):
    instance = make()

    resp = api_client.delete(reverse(route, args=[instance.pk]))

    assert resp.status_code == status.HTTP_204_NO_CONTENT
    assert not model.objects.filter(pk=instance.pk).exists()


# The cases above where only a hidden relation points at the object.
HIDDEN_ONLY = {
    "share_type_variation-detail",
    "delivery_station_day-detail",
    "member-detail",
}


@pytest.mark.parametrize(
    "route, model, make, code", IN_USE, ids=[row[0] for row in IN_USE]
)
def test_the_flag_reads_false_for_what_the_delete_refuses_unless_only_hidden(
    api_client, route, model, make, code
):
    instance = make()

    resp = api_client.get(reverse(route, args=[instance.pk]))

    assert resp.status_code == status.HTTP_200_OK, resp.data
    assert resp.data["can_be_deleted"] is (route in HIDDEN_ONLY)


def test_a_delivery_day_with_shares_names_them(api_client):
    day = ShareFactory().delivery_day

    resp = api_client.delete(reverse("share_delivery_day-detail", args=[day.pk]))

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.data["code"] == "shares_delivery_day.in_use"
    assert resp.data["details"]["share_count"] == 1


def test_a_station_day_with_deliveries_names_them(api_client):
    day = SharesDeliveryDayFactory()
    station_day = DeliveryStationDayFactory(delivery_day=day)
    ShareDeliveryFactory(
        share=ShareFactory(delivery_day=day), delivery_station_day=station_day
    )

    resp = api_client.delete(
        reverse("delivery_station_day-detail", args=[station_day.pk])
    )

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.data["code"] == "delivery_station_day.in_use"
    assert resp.data["details"]["delivery_count"] == 1


def test_a_delivery_day_is_kept_while_its_station_days_are_used(api_client):
    # A reservation on one of its station days, for a subscription that
    # collects elsewhere: neither a share nor a subscription of this day.
    station_day = DeliveryStationDayFactory(
        delivery_day=SharesDeliveryDayFactory(day_number=4)
    )
    reservation = CapacityReservation.objects.create(
        delivery_station_day=station_day,
        subscription=SubscriptionFactory(),
        year=2026,
        week=48,
        expires_at=timezone.now(),
    )

    resp = api_client.delete(
        reverse("share_delivery_day-detail", args=[station_day.delivery_day_id])
    )

    assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
    assert resp.data["code"] == "shares_delivery_day.referenced"
    assert CapacityReservation.objects.filter(pk=reservation.pk).exists()


def test_the_default_offer_group_keeps_its_own_code(api_client):
    group = OfferGroup.get_default()

    resp = api_client.delete(reverse("offer_group-detail", args=[group.pk]))

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.data["code"] == "offer_group.cannot_delete_default"


def test_an_invited_applicant_is_deleted_with_the_invitation(api_client, user):
    member = MemberFactory(admin_confirmed=False)
    invitation = UserInvitation.objects.create(
        member=member, email="wrong@example.com", created_by=user
    )

    flag = api_client.get(reverse("member-detail", args=[member.pk]))
    resp = api_client.delete(reverse("member-detail", args=[member.pk]))

    assert flag.data["can_be_deleted"] is True
    assert resp.status_code == status.HTTP_204_NO_CONTENT
    assert not UserInvitation.objects.filter(pk=invitation.pk).exists()


def test_a_rejected_applicant_is_kept(api_client):
    member = MemberFactory(admin_confirmed=False, admin_rejected_at=timezone.now())

    resp = api_client.delete(reverse("member-detail", args=[member.pk]))

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.data["code"] == "member.rejected_kept"
    assert Member.objects.filter(pk=member.pk).exists()


class TestResellerDelete:
    """Dropping a row's last role deletes it only while nothing points at it;
    dropping one of two roles never deletes anything."""

    @staticmethod
    def _delete(api_client, reseller, delete_context="sellers"):
        return api_client.delete(
            reverse("reseller-detail", args=[reseller.pk])
            + f"?delete_context={delete_context}"
        )

    def test_a_supplier_with_purchases_is_refused_and_kept(self, api_client):
        supplier = ResellerFactory(is_reseller=False, is_seller=True)
        purchase = PurchaseFactory(seller=supplier)

        resp = self._delete(api_client, supplier)

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "reseller.in_use"
        assert Reseller.objects.filter(pk=supplier.pk).exists()
        purchase.refresh_from_db()
        assert purchase.seller_id == supplier.pk

    def test_an_unused_supplier_is_deleted(self, api_client):
        supplier = ResellerFactory(is_reseller=False, is_seller=True)

        resp = self._delete(api_client, supplier)

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not Reseller.objects.filter(pk=supplier.pk).exists()

    def test_dropping_one_of_two_roles_keeps_a_used_row(self, api_client):
        reseller = ResellerFactory(is_reseller=True, is_seller=True)
        PurchaseFactory(seller=reseller)

        resp = self._delete(api_client, reseller)

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        reseller.refresh_from_db()
        assert reseller.is_reseller
        assert not reseller.is_seller


def test_a_payment_cycle_cannot_be_deleted(api_client):
    cycle = PaymentCycleFactory()

    resp = api_client.delete(reverse("payment_cycle-detail", args=[cycle.pk]))

    assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert PaymentCycle.objects.filter(pk=cycle.pk).exists()
