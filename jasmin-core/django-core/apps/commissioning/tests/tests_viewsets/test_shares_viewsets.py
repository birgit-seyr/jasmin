"""Tests for shares_viewsets.py — ShareType, ShareTypeVariation, ShareView."""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest import mock

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.errors import DeliveryStationOverCapacity
from apps.commissioning.models import (
    DefaultShareContent,
    DeliveryExceptionPeriod,
    ExternalShareDemand,
    Share,
    ShareContent,
    ShareDelivery,
    ShareImportBatch,
    ShareTypeVariationGrossPrice,
    VirtualVariationComponent,
)
from apps.commissioning.services.share_demand_service import ExternalDemandBackend
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    MemberFactory,
    ShareArticleFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    ShareTypeVariationGrossPriceFactory,
    SubscriptionFactory,
)
from apps.commissioning.viewsets.shares_viewsets import (
    ShareDeliveryOverviewViewSet,
    ShareDeliveryViewSet,
)


# ---------------------------------------------------------------------------
# ShareTypeViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareTypeViewSet:
    URL = reverse("share_type-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_list_returns_share_types(self, api_client, tenant):
        ShareTypeFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_include_future_returns_current_and_upcoming_not_past(
        self, api_client, tenant
    ):
        """``include_future=true`` returns share types active today OR starting
        later, but excludes already-ended ones — so the abos picker can offer
        future share types (and, via the variations endpoint, their future
        variations)."""
        # Distinct share_options → distinct ShareTypes (the factory's
        # ``django_get_or_create=("share_option",)`` would otherwise return the
        # same row and ignore the valid_from/until overrides).
        with time_machine.travel(datetime.date(2026, 6, 30)):
            active = ShareTypeFactory(share_option="HARVEST_SHARE")  # open-ended
            past = ShareTypeFactory(
                share_option="CHICKEN_SHARE", valid_until=datetime.date(2026, 3, 1)
            )
            future = ShareTypeFactory(
                share_option="HONEY_SHARE", valid_from=datetime.date(2027, 1, 4)
            )

            resp = api_client.get(self.URL, {"include_future": "true"})

        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert str(active.id) in ids
        assert str(future.id) in ids
        assert str(past.id) not in ids

    def test_list_includes_variation_sizes(self, api_client, tenant):
        st = ShareTypeFactory()
        ShareTypeVariationFactory(share_type=st, size="S")
        resp = api_client.get(self.URL)
        item = next(d for d in resp.data if d["id"] == str(st.id))
        assert "share_type_variation_sizes_in_use" in item

    def test_list_exposes_variation_valid_until_bounds(self, api_client, tenant):
        # The datepicker floor: a share type can't end before its latest
        # variation, and can't be closed at all while a variation is open-ended.
        st = ShareTypeFactory()
        ShareTypeVariationFactory(
            share_type=st, size="S", valid_until=datetime.date(2026, 9, 13)
        )
        ShareTypeVariationFactory(share_type=st, size="M", valid_until=None)
        item = next(d for d in api_client.get(self.URL).data if d["id"] == str(st.id))
        assert item["variations_valid_until_max"] == "2026-09-13"
        assert item["has_open_ended_variation"] is True

    def test_not_deletable_with_variations(self, api_client, tenant):
        # The frontend hides the delete icon on can_be_deleted; a ShareType with
        # variations is blocked by the PROTECT FK, so it must report False.
        st = ShareTypeFactory()
        item = next(d for d in api_client.get(self.URL).data if d["id"] == str(st.id))
        assert item["can_be_deleted"] is True

        ShareTypeVariationFactory(share_type=st)
        item = next(d for d in api_client.get(self.URL).data if d["id"] == str(st.id))
        assert item["can_be_deleted"] is False

    def test_filter_by_share_option(self, api_client, tenant):
        ShareTypeFactory(share_option="HARVEST_SHARE")
        ShareTypeFactory(share_option="HONEY_SHARE")
        resp = api_client.get(self.URL, {"share_option": "HARVEST_SHARE"})
        assert all(d["share_option"] == "HARVEST_SHARE" for d in resp.data)

    def test_filter_by_share_option_accepts_any_casing(self, api_client, tenant):
        # The create/update body takes either casing for this enum, so the
        # filter over the same enum takes it too.
        ShareTypeFactory(share_option="HARVEST_SHARE")
        ShareTypeFactory(share_option="HONEY_SHARE")
        resp = api_client.get(self.URL, {"share_option": "harvest_share"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data
        assert all(d["share_option"] == "HARVEST_SHARE" for d in resp.data)

    def test_create_uppercases_share_option(self, api_client, tenant):
        resp = api_client.post(
            self.URL,
            {
                "name": "Test Type",
                "share_option": "harvest_share",
                "valid_from": "2028-01-03",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["share_option"] == "HARVEST_SHARE"

    def test_create_invalid_share_option_returns_400(self, api_client, tenant):
        resp = api_client.post(
            self.URL,
            {"name": "Bad", "share_option": "INVALID_OPTION"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_uppercases_share_option(self, api_client, tenant):
        st = ShareTypeFactory(share_option="HARVEST_SHARE")
        url = reverse("share_type-detail", kwargs={"pk": st.pk})
        resp = api_client.patch(url, {"share_option": "honey_share"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["share_option"] == "HONEY_SHARE"

    def test_create_non_string_share_option_returns_400(self, api_client, tenant):
        """A non-string option is the same field-level 400 as an unknown one —
        the case pre-check used to call ``.upper()`` on it and 500."""
        resp = api_client.post(
            self.URL,
            {"name": "Bad", "share_option": 5, "valid_from": "2028-01-03"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "share_type.invalid_share_option"
        assert resp.data["field"] == "share_option"

    def test_update_non_string_share_option_returns_400(self, api_client, tenant):
        st = ShareTypeFactory(share_option="HARVEST_SHARE")
        url = reverse("share_type-detail", kwargs={"pk": st.pk})

        resp = api_client.patch(url, {"share_option": ["HONEY_SHARE"]}, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "share_type.invalid_share_option"
        st.refresh_from_db()
        assert st.share_option == "HARVEST_SHARE"

    def test_create_succeeds_open_predecessor(self, api_client, tenant):
        # Creating a new ShareType for a share_option whose open predecessor has
        # no active variations must SUCCEED and close the predecessor. The DRF
        # UniqueValidator (auto-built from the partial sharetype_one_open_per_
        # option constraint, ignoring its condition) must not pre-empt the
        # model's succession-in-save().
        predecessor = ShareTypeFactory(
            share_option="HARVEST_SHARE",
            valid_from=datetime.date(2026, 11, 30),
            valid_until=None,
        )
        resp = api_client.post(
            self.URL,
            {
                "name": "Successor",
                "share_option": "HARVEST_SHARE",
                "valid_from": "2027-01-18",
                "delivery_cycle": "WEEKLY",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        predecessor.refresh_from_db()
        assert predecessor.valid_until == datetime.date(2027, 1, 17)

    def test_create_same_start_still_conflicts(self, api_client, tenant):
        # A genuine violation — a second OPEN ShareType on the SAME start date,
        # which succession can't resolve — must still be rejected (by the model
        # full_clean / DB constraint, not a serializer UniqueValidator).
        ShareTypeFactory(
            share_option="HARVEST_SHARE",
            valid_from=datetime.date(2027, 1, 18),
            valid_until=None,
        )
        resp = api_client.post(
            self.URL,
            {
                "name": "Dup",
                "share_option": "HARVEST_SHARE",
                "valid_from": "2027-01-18",
                "delivery_cycle": "WEEKLY",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_blocked_by_active_variations(self, api_client, tenant):
        # Succession is refused (409) when the predecessor still has a variation
        # that would outlive it.
        predecessor = ShareTypeFactory(
            share_option="HONEY_SHARE",
            valid_from=datetime.date(2026, 11, 30),
            valid_until=None,
        )
        ShareTypeVariationFactory(
            share_type=predecessor,
            valid_from=datetime.date(2026, 11, 30),
            valid_until=None,
        )
        resp = api_client.post(
            self.URL,
            {
                "name": "Successor",
                "share_option": "HONEY_SHARE",
                "valid_from": "2027-01-18",
                "delivery_cycle": "WEEKLY",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "share_type.succession_has_active_variations"


# ---------------------------------------------------------------------------
# ShareTypeVariationViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareTypeVariationViewSet:
    URL = reverse("share_type_variation-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_variations(self, api_client, tenant):
        ShareTypeVariationFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_list_exposes_active_trial_price(self, api_client, tenant):
        # ``active_price_per_delivery_if_trial`` mirrors
        # ``active_price_per_delivery`` for the variation's TRIAL reference
        # price — it drives the abos price auto-fill when ``is_trial`` is on.
        # ``active_solidarity_min_price_per_delivery_if_trial`` is the trial
        # counterpart of the solidarity floor — the modal floors a trial price
        # against it (and the backend re-validates the same value).
        price = ShareTypeVariationGrossPriceFactory(
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("8.00"),
            price_per_delivery_if_trial=Decimal("6.00"),
            solidarity_min_price_per_delivery_if_trial=Decimal("5.00"),
        )
        resp = api_client.get(
            self.URL,
            {
                "share_type_variation": str(price.share_type_variation.id),
                "active_at_date": "2026-06-01",
            },
        )
        item = next(
            d for d in resp.data if d["id"] == str(price.share_type_variation.id)
        )
        assert item["active_price_per_delivery"] == "10.00"
        assert item["active_solidarity_min_price_per_delivery"] == "8.00"
        assert item["active_price_per_delivery_if_trial"] == "6.00"
        assert item["active_solidarity_min_price_per_delivery_if_trial"] == "5.00"

    def test_list_exposes_subscription_valid_until_bounds(self, api_client, tenant):
        # The datepicker floor: a variation can't end before its LATEST
        # subscription. (Subscriptions are never open-ended — the model forbids
        # it — so ``has_open_ended_subscription`` is a defensive False here.)
        variation = ShareTypeVariationFactory()
        # One shared (open-ended) station-day so the two subscriptions don't
        # each spin up a clashing SharesDeliveryDay.
        dsd = DeliveryStationDayFactory()
        SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=dsd,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 9, 6),
        )
        SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=dsd,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 9, 13),
        )
        resp = api_client.get(self.URL)
        item = next(d for d in resp.data if d["id"] == str(variation.id))
        assert item["subscriptions_valid_until_max"] == "2026-09-13"
        assert item["has_open_ended_subscription"] is False

    def test_include_future_returns_current_and_upcoming_not_past(
        self, api_client, tenant
    ):
        """``include_future=true`` returns variations active today OR starting
        later, but excludes already-ended ones. Each variation is on its own
        share type, so their validity windows don't overlap-clash."""
        with time_machine.travel(datetime.date(2026, 6, 30)):
            active = ShareTypeVariationFactory()  # 2026-01-05, open-ended
            past = ShareTypeVariationFactory(valid_until=datetime.date(2026, 3, 1))
            future = ShareTypeVariationFactory(valid_from=datetime.date(2027, 1, 4))

            resp = api_client.get(self.URL, {"include_future": "true"})

        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert str(active.id) in ids
        assert str(future.id) in ids
        assert str(past.id) not in ids

    def test_create_within_share_type_range_ok(self, api_client, tenant):
        st = ShareTypeFactory(
            share_option="HARVEST_SHARE",
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),
        )
        resp = api_client.post(
            self.URL,
            {
                "share_type": st.pk,
                "size": "M",
                "variation_type": "physical",
                "valid_from": "2026-01-05",
                "valid_until": "2026-12-27",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

    def test_create_outside_share_type_range_rejected(self, api_client, tenant):
        # A variation that starts before its share type (or would outlive it)
        # is rejected with a coded, translatable error.
        st = ShareTypeFactory(
            share_option="HARVEST_SHARE",
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),
        )
        resp = api_client.post(
            self.URL,
            {
                "share_type": st.pk,
                "size": "S",
                "variation_type": "physical",
                "valid_from": "2025-12-29",  # before the share type
                "valid_until": "2026-12-27",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "share_type_variation.outside_share_type_range"

    def test_create_blocked_by_active_subscriptions(self, api_client, tenant):
        # Succession is refused (409) when the predecessor variation still has a
        # subscription running on/after the successor's start date.
        st = ShareTypeFactory(
            share_option="HONEY_SHARE",
            valid_from=datetime.date(2026, 1, 5),
            valid_until=None,
        )
        predecessor = ShareTypeVariationFactory(
            share_type=st,
            size="M",
            valid_from=datetime.date(2026, 1, 5),
            valid_until=None,
        )
        SubscriptionFactory(
            share_type_variation=predecessor,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(
                2027, 1, 3
            ),  # Sunday, runs past any successor start
            default_delivery_station_day=None,
        )
        resp = api_client.post(
            self.URL,
            {
                "share_type": st.pk,
                "size": "M",
                "variation_type": "physical",
                "valid_from": "2026-06-29",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert (
            resp.data["code"]
            == "share_type_variation.succession_has_active_subscriptions"
        )

    def test_succession_allowed_after_last_subscription_ended(self, api_client, tenant):
        # The successor MAY start once the last subscription on the predecessor
        # has ended (its valid_until is before the new start date).
        st = ShareTypeFactory(
            share_option="HONEY_SHARE",
            valid_from=datetime.date(2026, 1, 5),
            valid_until=None,
        )
        predecessor = ShareTypeVariationFactory(
            share_type=st,
            size="M",
            valid_from=datetime.date(2026, 1, 5),
            valid_until=None,
        )
        SubscriptionFactory(
            share_type_variation=predecessor,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),  # Sunday, ended before the start
            default_delivery_station_day=None,
        )
        resp = api_client.post(
            self.URL,
            {
                "share_type": st.pk,
                "size": "M",
                "variation_type": "physical",
                "valid_from": "2026-06-29",  # Monday after the subscription ended
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        # The succession closed the predecessor the day before the new start.
        predecessor.refresh_from_db()
        assert predecessor.valid_until == datetime.date(2026, 6, 28)

    def test_shorten_blocked_by_active_subscriptions(self, api_client, tenant):
        # Directly shortening a variation's window (PATCH valid_until earlier) is
        # refused (409) when it would strand a subscription.
        st = ShareTypeFactory(
            share_option="HONEY_SHARE",
            valid_from=datetime.date(2026, 1, 5),
            valid_until=None,
        )
        variation = ShareTypeVariationFactory(
            share_type=st,
            size="M",
            valid_from=datetime.date(2026, 1, 5),
            valid_until=None,
        )
        SubscriptionFactory(
            share_type_variation=variation,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(
                2027, 1, 3
            ),  # Sunday, outlives the earlier end date
            default_delivery_station_day=None,
        )
        resp = api_client.patch(
            reverse("share_type_variation-detail", args=[variation.pk]),
            {"valid_until": "2026-06-28"},
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert (
            resp.data["code"] == "share_type_variation.shortening_strands_subscriptions"
        )

    def test_filter_by_share_type(self, api_client, tenant):
        var = ShareTypeVariationFactory()
        resp = api_client.get(self.URL, {"share_type": str(var.share_type.id)})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) >= 1

    def test_filter_physical(self, api_client, tenant):
        ShareTypeVariationFactory(variation_type="physical")
        resp = api_client.get(self.URL, {"physical": "true"})
        assert resp.status_code == status.HTTP_200_OK

    def test_filter_physical_false_returns_both(self, api_client, tenant):
        # ``physical`` is a strict bool: ``physical=false`` is present-but-false
        # and must NOT restrict to physical — the filter is opt-in on an explicit
        # true only. (Keying on ``is not None`` would hide virtuals here.)
        physical = ShareTypeVariationFactory(variation_type="physical")
        virtual = ShareTypeVariationFactory(variation_type="virtual")
        resp = api_client.get(self.URL, {"physical": "false"})
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert physical.id in ids
        assert virtual.id in ids

    def test_filter_by_share_option(self, api_client, tenant):
        var = ShareTypeVariationFactory()
        name = var.share_type.share_option
        resp = api_client.get(self.URL, {"share_option": name})
        assert resp.status_code == status.HTTP_200_OK

    def test_filter_is_packed_bulk_true(self, api_client, tenant):
        st = ShareTypeFactory()
        bulk = ShareTypeVariationFactory(share_type=st, size="S", is_packed_bulk=True)
        ShareTypeVariationFactory(share_type=st, size="M", is_packed_bulk=False)

        resp = api_client.get(self.URL, {"is_packed_bulk": "true"})
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert str(bulk.id) in ids
        assert all(row["is_packed_bulk"] is True for row in resp.data)

    def test_filter_is_packed_bulk_false(self, api_client, tenant):
        st = ShareTypeFactory()
        ShareTypeVariationFactory(share_type=st, size="S", is_packed_bulk=True)
        boxed = ShareTypeVariationFactory(share_type=st, size="M", is_packed_bulk=False)

        resp = api_client.get(self.URL, {"is_packed_bulk": "false"})
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert str(boxed.id) in ids
        assert all(row["is_packed_bulk"] is False for row in resp.data)

    def test_filter_is_packed_bulk_omitted_returns_all(self, api_client, tenant):
        """Default behavior: no filter applied; both bulk and boxed
        variations must be present in the response. This is critical
        because most callers in the codebase need ALL variations."""
        st = ShareTypeFactory()
        bulk = ShareTypeVariationFactory(share_type=st, size="S", is_packed_bulk=True)
        boxed = ShareTypeVariationFactory(share_type=st, size="M", is_packed_bulk=False)

        resp = api_client.get(self.URL, {"share_type": str(st.id)})
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert {str(bulk.id), str(boxed.id)}.issubset(ids)


# ---------------------------------------------------------------------------
# ShareTypeVariationGrossPriceViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareTypeVariationGrossPriceViewSet:
    URL = reverse("share_type_variation_price-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_prices(self, api_client, tenant):
        ShareTypeVariationGrossPriceFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_by_variation(self, api_client, tenant):
        price = ShareTypeVariationGrossPriceFactory()
        resp = api_client.get(
            self.URL,
            {"share_type_variation": str(price.share_type_variation.id)},
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_not_deletable_when_variation_has_subscription(self, api_client, tenant):
        # No FK points at the price row, but a price whose variation a member
        # has subscribed to must report can_be_deleted=False (billable history).
        price = ShareTypeVariationGrossPriceFactory()
        params = {"share_type_variation": str(price.share_type_variation.id)}

        resp = api_client.get(self.URL, params)
        assert resp.data[0]["can_be_deleted"] is True

        SubscriptionFactory(share_type_variation=price.share_type_variation)
        resp = api_client.get(self.URL, params)
        assert resp.data[0]["can_be_deleted"] is False


# ---------------------------------------------------------------------------
# ShareViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareViewSet:
    URL = reverse("share-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_shares(self, api_client, tenant):
        ShareFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_by_year_and_week(self, api_client, tenant):
        _share = ShareFactory(year=2026, delivery_week=15)
        resp = api_client.get(self.URL, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) >= 1

    def test_get_days_action(self, api_client, tenant):
        _share = ShareFactory(year=2026, delivery_week=15)
        url = reverse("share-get-days")
        resp = api_client.get(url, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# ShareViewSet — the weekday columns belong to SharesDayChangeService
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareDayFieldsLockedOnUpdate:
    """Moving a day rebuilds the week's theoretical objects and movements and
    is refused for a past week — both live in ``SharesDayChangeService``, behind
    ``/shares/bulk_update/``. A plain PATCH drops the day keys instead of
    writing them straight to the column; create still sets them.
    """

    def test_patch_drops_the_day_keys(self, api_client, tenant):
        share = ShareFactory()
        share.refresh_from_db()
        original_harvesting_day = share.harvesting_day
        original_packing_day = share.packing_day

        url = reverse("share-detail", kwargs={"pk": share.pk})
        resp = api_client.patch(
            url,
            {
                "harvesting_day": 5,
                "packing_day": 6,
                "changed_day_number": 4,
                "get_current_stock_day": 2,
                # The legitimate half of the same payload.
                "weight1": "2.500",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        share.refresh_from_db()
        assert share.harvesting_day == original_harvesting_day
        assert share.packing_day == original_packing_day
        assert share.changed_day_number is None
        assert share.weight1 == Decimal("2.500")

    def test_create_still_sets_the_day_fields(self, api_client, tenant):
        """``ShareDays.tsx`` creates rows through this endpoint, so the lock is
        update-only."""
        delivery_day = SharesDeliveryDayFactory()
        variation = ShareTypeVariationFactory()
        resp = api_client.post(
            reverse("share-list"),
            {
                "year": 2026,
                "delivery_week": 15,
                "delivery_day": delivery_day.pk,
                "share_type_variation": variation.pk,
                "harvesting_day": 3,
                "changed_day_number": 4,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED
        share = Share.objects.get(pk=resp.data["id"])
        assert share.harvesting_day == 3
        assert share.changed_day_number == 4


# ---------------------------------------------------------------------------
# ShareViewSet — bulk_update / export_csv @actions
# ---------------------------------------------------------------------------
URL_SHARE_BULK_UPDATE = reverse("share-bulk-update")
URL_SHARE_EXPORT_CSV = reverse("share-export-csv")


@pytest.mark.django_db
class TestShareBulkUpdateAction:
    def test_missing_year_returns_400(self, api_client, tenant):
        resp = api_client.put(URL_SHARE_BULK_UPDATE, {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert "year" in resp.data["message"]

    def test_empty_week_succeeds_with_empty_response(self, api_client, tenant):
        """No shares in the week → service no-op → get_days returns [].
        Asserts the early-empty path doesn't 500."""
        resp = api_client.put(
            URL_SHARE_BULK_UPDATE,
            {},
            format="json",
            QUERY_STRING="year=2099&delivery_week=1",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []


@pytest.mark.django_db
class TestShareBulkUpdateDayValidation:
    """The body is written straight onto ``Share`` weekday columns by
    ``SharesDayChangeService``, so the request serializer coerces and bounds it
    before the service runs."""

    @pytest.fixture(autouse=True)
    def _frozen_today(self):
        """Pin "today" to 2026-04-22 (ISO week 17).

        ``bulk_update`` refuses a past/current week, so these tests target week
        30 of 2026 — frozen here, that stays in the future forever.
        """
        with time_machine.travel(datetime.datetime(2026, 4, 22, 12, 0), tick=False):
            yield

    @staticmethod
    def _put(api_client, body):
        return api_client.put(
            URL_SHARE_BULK_UPDATE,
            body,
            format="json",
            QUERY_STRING="year=2026&delivery_week=30",
        )

    def test_non_numeric_day_returns_400(self, api_client, tenant):
        share = ShareFactory(year=2026, delivery_week=30)
        stored_day = share.harvesting_day

        resp = self._put(api_client, {"harvesting_day": "abc"})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["field"] == "harvesting_day"
        share.refresh_from_db()
        assert share.harvesting_day == stored_day

    def test_day_outside_the_week_returns_400(self, api_client, tenant):
        share = ShareFactory(year=2026, delivery_week=30)
        stored_day = share.packing_day

        resp = self._put(api_client, {"packing_day": 9})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["field"] == "packing_day"
        share.refresh_from_db()
        assert share.packing_day == stored_day

    def test_valid_day_is_applied_and_omitted_fields_survive(self, api_client, tenant):
        share = ShareFactory(year=2026, delivery_week=30)
        stored_packing_day = share.packing_day

        resp = self._put(api_client, {"harvesting_day": 3})

        assert resp.status_code == status.HTTP_200_OK
        share.refresh_from_db()
        assert share.harvesting_day == 3
        assert share.packing_day == stored_packing_day

    def test_undefined_sentinel_is_accepted_as_a_cleared_day(self, api_client, tenant):
        # The office grid has always sent this string for a blanked cell, so the
        # serializer has to keep taking it as "no day" instead of rejecting it.
        # A cleared day then falls back to the delivery day's default in
        # ``Share.save`` — a NULL would drop the share out of every day-filtered
        # list.
        share = ShareFactory(year=2026, delivery_week=30)
        assert (
            self._put(api_client, {"washing_day": 4}).status_code == status.HTTP_200_OK
        )

        resp = self._put(api_client, {"washing_day": "undefined"})

        assert resp.status_code == status.HTTP_200_OK
        share.refresh_from_db()
        assert share.washing_day == share.delivery_day.default_washing_day
        assert share.washing_day != 4


@pytest.mark.django_db
class TestShareExportCsvAction:
    def test_missing_dates_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_SHARE_EXPORT_CSV)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_date_format_returns_400(self, api_client, tenant):
        resp = api_client.get(
            URL_SHARE_EXPORT_CSV,
            {"date_from": "not-a-date", "date_to": "2026-06-01"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "date_from"

    def test_inverted_range_returns_400(self, api_client, tenant):
        """An end before the start would stream an empty CSV that reads as "no
        shares in that window"; the sibling exports refuse it, so this one does
        too, naming the parameter to fix."""
        resp = api_client.get(
            URL_SHARE_EXPORT_CSV,
            {"date_from": "2099-01-31", "date_to": "2099-01-01"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "date_from"

    def test_empty_range_returns_csv_with_header_only(self, api_client, tenant):
        """Valid dates with no shares in the range → CSV with just the
        header row + a Soll target row (no data rows)."""
        resp = api_client.get(
            URL_SHARE_EXPORT_CSV,
            {"date_from": "2099-01-01", "date_to": "2099-01-31"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "text/csv" in resp["Content-Type"]
        assert "attachment" in resp["Content-Disposition"]
        # BOM + at least the "KW" header line. The export streams, so read the
        # body from streaming_content rather than .content.
        body = b"".join(resp.streaming_content).decode("utf-8-sig")
        assert body.startswith("KW")

    def test_range_filters_to_iso_week_window(self, api_client, tenant):
        """A populated June range exports the variation whose ISO week falls
        inside it and omits one whose week is months earlier — exercising the
        SQL (year, week) window + the exact day-level narrow together."""
        from datetime import date

        from isoweek import Week

        in_variation = ShareTypeVariationFactory()
        out_variation = ShareTypeVariationFactory()
        # Share one delivery day: two ShareFactory calls would otherwise each
        # open a day_number=2 SharesDeliveryDay and trip the global
        # one-open-per-day-number constraint. The export ignores delivery_day.
        delivery_day = SharesDeliveryDayFactory()
        in_week = Week.withdate(date(2026, 6, 15))  # Monday inside the range
        out_week = Week.withdate(date(2026, 3, 15))  # months before the range
        ShareFactory(
            year=in_week.year,
            delivery_week=in_week.week,
            delivery_day=delivery_day,
            share_type_variation=in_variation,
        )
        ShareFactory(
            year=out_week.year,
            delivery_week=out_week.week,
            delivery_day=delivery_day,
            share_type_variation=out_variation,
        )

        resp = api_client.get(
            URL_SHARE_EXPORT_CSV,
            {"date_from": "2026-06-01", "date_to": "2026-06-30"},
        )
        assert resp.status_code == status.HTTP_200_OK
        body = b"".join(resp.streaming_content).decode("utf-8-sig")
        # The in-range week appears as a column; the out-of-range week does not.
        assert f"{in_week.week}/{in_week.year}" in body
        assert f"{out_week.week}/{out_week.year}" not in body


# ---------------------------------------------------------------------------
# DefaultShareContentViewSet — bulk_list / bulk_create / bulk_update / bulk_delete
# ---------------------------------------------------------------------------
URL_DSC_BULK_LIST = reverse("default_share_contents-bulk-list")
URL_DSC_BULK_CREATE = reverse("default_share_contents-bulk-create")


@pytest.mark.django_db
class TestDefaultShareContentBulkList:
    def test_invalid_year_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_DSC_BULK_LIST, {"year": "not-a-number"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_year_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_DSC_BULK_LIST, {"share_option": "HARVEST_SHARE"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "year"

    def test_missing_share_option_returns_400(self, api_client, tenant):
        """The rows are the planning slots of ONE share option, so without it
        the endpoint could only answer with an empty list."""
        resp = api_client.get(URL_DSC_BULK_LIST, {"year": 2099})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "share_option"

    def test_filters_to_requested_share_option(self, api_client, tenant):
        """The view filters service results to entries where
        ``share_option == share_option``. With no matches, returns []."""
        resp = api_client.get(
            URL_DSC_BULK_LIST,
            {"year": 2099, "share_option": "HARVEST_SHARE"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []


URL_DSC_SUBSCRIBER_COUNTS = reverse("default_share_contents-subscriber-counts")


@pytest.mark.django_db
class TestDefaultShareContentSubscriberCounts:
    """Read-only per-variation active-subscriber snapshot powering the reverse
    'total → per-share' planning suggestion."""

    def test_returns_count_per_variation(self, api_client, tenant):
        import datetime

        import time_machine

        from apps.commissioning.tests.factories import (
            DeliveryStationDayFactory,
            ShareTypeVariationFactory,
            SubscriptionFactory,
        )

        variation = ShareTypeVariationFactory()  # physical, HARVEST_SHARE
        station_day = DeliveryStationDayFactory()
        for _ in range(4):
            SubscriptionFactory(
                share_type_variation=variation,
                default_delivery_station_day=station_day,
            )

        with time_machine.travel(datetime.date(2026, 6, 1), tick=False):
            resp = api_client.get(
                URL_DSC_SUBSCRIBER_COUNTS,
                {"year": 2026, "share_option": "HARVEST_SHARE"},
            )

        assert resp.status_code == status.HTTP_200_OK
        # 4 active subscriptions on this variation, keyed by variation id.
        assert resp.data[str(variation.pk)] == "4"

    def test_excludes_other_share_options(self, api_client, tenant):
        from apps.commissioning.tests.factories import ShareTypeVariationFactory

        other = ShareTypeVariationFactory(
            share_type__share_option="HARVEST_SHARE_FRUIT"
        )

        resp = api_client.get(
            URL_DSC_SUBSCRIBER_COUNTS,
            {"year": 2026, "share_option": "HARVEST_SHARE"},
        )
        assert resp.status_code == status.HTTP_200_OK
        # A variation of a different share option must not appear in the map.
        assert str(other.pk) not in resp.data

    def test_invalid_year_returns_400(self, api_client, tenant):
        resp = api_client.get(
            URL_DSC_SUBSCRIBER_COUNTS,
            {"year": "not-a-number", "share_option": "HARVEST_SHARE"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestDefaultShareContentBulkUpdate:
    def test_invalid_composite_id_returns_400(self, api_client, tenant):
        """Composite ID must split into exactly 4 parts on ``_``; the error is a
        canonical ``CompositeIdInvalid`` body."""
        url = reverse("default_share_contents-bulk-update", args=["only-two_parts"])
        resp = api_client.put(url, {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "default_share_content.invalid_composite_id"


@pytest.mark.django_db
class TestDefaultShareContentBulkDelete:
    def test_invalid_composite_id_raises_validation(self, api_client, tenant):
        """Composite ID malformed → CommissioningError → 400."""
        url = reverse("default_share_contents-bulk-delete", args=["bogus_id"])
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_share_article_returns_404(self, api_client, tenant):
        """Well-formed composite ID but article doesn't exist →
        ShareArticleNotFound → 404."""
        url = reverse(
            "default_share_contents-bulk-delete",
            args=["2026_nonexistent_KG_M"],
        )
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestShareDeliveryMemberPermissions:
    """Members may ONLY reach the opt-in actions; all standard CRUD on
    ShareDelivery is office-only. Permissions are checked before
    ``get_object``, so a member is rejected on any pk (no row needed)."""

    @staticmethod
    def _member(member_user):
        client = APIClient()
        client.force_authenticate(user=member_user)
        return client

    def test_member_cannot_delete(self, member_user, tenant):
        resp = self._member(member_user).delete(
            reverse("share_delivery-detail", args=["any-id"])
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_member_cannot_create(self, member_user, tenant):
        resp = self._member(member_user).post(
            reverse("share_delivery-list"), {}, format="json"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_member_can_still_reach_pending_optin(self, member_user, tenant):
        # The member-facing opt-in path stays open — NOT a 403. (A downstream
        # business error like 400 "no member context" is fine: it proves the
        # caller passed the permission layer.)
        resp = self._member(member_user).get(reverse("share_delivery-pending-optin"))
        assert resp.status_code != status.HTTP_403_FORBIDDEN

    def test_office_passes_permission_layer_on_delete(self, api_client, tenant):
        # Office is allowed through the permission layer — the 404 is only
        # because the pk doesn't exist, NOT a 403.
        resp = api_client.delete(reverse("share_delivery-detail", args=["missing"]))
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# DefaultShareContentViewSet — bulk_create / bulk_update validation wiring
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDefaultShareContentBulkCreateValidation:
    """``bulk_create`` validates ``DefaultShareContentRequestSerializer`` and
    passes ``validated_data`` (the dynamic ``amount_<variation_id>`` cells are
    merged back in by ``DynamicAmountKeysMixin`` and survive).

    Year 2099 has no delivery days configured, so the service persists only
    the plain ``DefaultShareContent`` rows — a self-contained path needing no
    station setup or recompute.
    """

    def test_valid_payload_persists_default_share_content(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        payload = {
            "year": 2099,
            "share_article": str(article.id),
            "share_option": "HARVEST_SHARE",
            "unit": "KG",
            "size": "M",
            "range_1": 10,
            "range_2": 10,
            f"amount_{variation.id}": "3.5",
        }
        resp = api_client.post(URL_DSC_BULK_CREATE, payload, format="json")
        assert resp.status_code == status.HTTP_200_OK
        row = DefaultShareContent.objects.get(
            year=2099,
            share_article=article,
            delivery_week=10,
            share_type_variation=variation,
            unit="KG",
            size="M",
        )
        assert row.amount == Decimal("3.5")

    def test_missing_required_field_returns_400(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        # ``share_article`` omitted → is_valid rejects before the service runs.
        bad = {
            "year": 2099,
            "share_option": "HARVEST_SHARE",
            "unit": "KG",
            "size": "M",
            "range_1": 10,
            "range_2": 10,
            f"amount_{variation.id}": "3.5",
        }
        resp = api_client.post(URL_DSC_BULK_CREATE, bad, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_finite_amount_returns_400(self, api_client, tenant):
        # "NaN"/"Infinity" parse as Decimal but aren't real numbers — the cell
        # validator must reject them with a clean 400, not 500 or a silent store.
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        bad = {
            "year": 2099,
            "share_article": str(article.id),
            "share_option": "HARVEST_SHARE",
            "unit": "KG",
            "size": "M",
            "range_1": 10,
            "range_2": 10,
            f"amount_{variation.id}": "NaN",
        }
        resp = api_client.post(URL_DSC_BULK_CREATE, bad, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_amount_wider_than_the_column_returns_400(self, api_client, tenant):
        """``DefaultShareContent.amount`` is numeric(5,3) — 100 overflows it.
        The cell is named here instead of the INSERT failing."""
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        bad = {
            "year": 2099,
            "share_article": str(article.id),
            "share_option": "HARVEST_SHARE",
            "unit": "KG",
            "size": "M",
            "range_1": 10,
            "range_2": 10,
            f"amount_{variation.id}": "100",
        }

        resp = api_client.post(URL_DSC_BULK_CREATE, bad, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "amount.invalid"
        assert resp.data["field"] == f"amount_{variation.id}"
        assert not DefaultShareContent.objects.filter(share_article=article).exists()


@pytest.mark.django_db
class TestDefaultShareContentBulkUpdateValidation:
    def test_valid_payload_replaces_slot_amount(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        composite_id = f"2099_{article.id}_KG_M"
        url = reverse("default_share_contents-bulk-update", args=[composite_id])
        body = {
            "share_option": "HARVEST_SHARE",
            "range_1": 12,
            "range_2": 12,
            f"amount_{variation.id}": "7.0",
        }
        resp = api_client.put(url, body, format="json")
        assert resp.status_code == status.HTTP_200_OK
        row = DefaultShareContent.objects.get(
            year=2099,
            share_article=article,
            delivery_week=12,
            share_type_variation=variation,
            unit="KG",
            size="M",
        )
        assert row.amount == Decimal("7.0")

    def test_bad_typed_field_returns_400(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        composite_id = f"2099_{article.id}_KG_M"
        url = reverse("default_share_contents-bulk-update", args=[composite_id])
        # ``partial=True`` on update → missing fields are allowed, but a
        # wrong-typed declared field (non-numeric range_1) is still rejected.
        body = {"range_1": "abc", f"amount_{variation.id}": "1"}
        resp = api_client.put(url, body, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_without_range_1_returns_400(self, api_client, tenant):
        """The service indexes ``range_1``/``range_2`` unconditionally, so on
        this partially-validated path an omitted range reached it as a
        KeyError. It is a named field error now."""
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        composite_id = f"2099_{article.id}_KG_M"
        url = reverse("default_share_contents-bulk-update", args=[composite_id])

        resp = api_client.patch(
            url,
            {"share_option": "HARVEST_SHARE", f"amount_{variation.id}": "2.0"},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "required_field.missing"
        assert resp.data["field"] == "range_1"
        assert not DefaultShareContent.objects.filter(share_article=article).exists()

    def test_patch_with_ranges_rewrites_the_slot(self, api_client, tenant):
        """A partial body that carries the ranges still works — the rest of the
        slot identity comes from the composite id."""
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        composite_id = f"2099_{article.id}_KG_M"
        url = reverse("default_share_contents-bulk-update", args=[composite_id])

        resp = api_client.patch(
            url,
            {
                "share_option": "HARVEST_SHARE",
                "range_1": 14,
                "range_2": 14,
                f"amount_{variation.id}": "2.5",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        row = DefaultShareContent.objects.get(
            year=2099,
            share_article=article,
            delivery_week=14,
            share_type_variation=variation,
            unit="KG",
            size="M",
        )
        assert row.amount == Decimal("2.5")


# ---------------------------------------------------------------------------
# HarvestSharePlanningViewSet — create validation wiring (pass-raw)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestHarvestSharePlanningViewSet:
    """``create`` validates ``HarvestSharePlanningCreateRequestSerializer`` and
    passes ``validated_data`` (the dynamic ``day_<id>_variation_<id>`` cells are
    merged back in by ``DynamicAmountKeysMixin`` and survive).

    A current, active ``DeliveryStationDay`` must link the delivery day to an
    active station for the week, else the service resolves zero stations and
    ``create`` returns 400 "Please enter at least one amount.".
    """

    @staticmethod
    def _setup():
        article = ShareArticleFactory()
        day = SharesDeliveryDayFactory()
        variation = ShareTypeVariationFactory(variation_type="physical")
        station = DeliveryStationFactory(is_active=True)
        DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=day,
            tour_number=1,
        )
        return article, day, variation, station

    def test_create_persists_share_content(self, api_client, tenant):
        article, day, variation, station = self._setup()
        payload = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": str(article.id),
            "unit": "KG",
            "size": "M",
            f"day_{day.id}_variation_{variation.id}": "3.5",
        }
        resp = api_client.post(
            reverse("harvest_share_planning-list"), payload, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK
        share_content = ShareContent.objects.filter(
            share_article=article, unit="KG", size="M"
        ).first()
        assert share_content is not None
        assert share_content.amount == Decimal("3.5")
        assert share_content.delivery_station_id == station.id

    def test_create_accepts_null_note(self, api_client, tenant):
        # The EditableTable sends note=null for un-annotated rows; the request
        # serializer must allow it (allow_null=True).
        article, day, variation, _station = self._setup()
        payload = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": str(article.id),
            "unit": "KG",
            "size": "M",
            "note": None,
            f"day_{day.id}_variation_{variation.id}": "3.5",
        }
        resp = api_client.post(
            reverse("harvest_share_planning-list"), payload, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_create_missing_required_field_returns_400(self, api_client, tenant):
        article, day, variation, _station = self._setup()
        # year + share_article omitted → is_valid 400 before the service runs.
        bad = {
            "delivery_week": 15,
            f"day_{day.id}_variation_{variation.id}": "3.5",
        }
        resp = api_client.post(
            reverse("harvest_share_planning-list"), bad, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_with_no_amounts_returns_400(self, api_client, tenant):
        # Valid serializer payload but zero plannable cells → the
        # create-specific "at least one amount" guard.
        article, _day, _variation, _station = self._setup()
        payload = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": str(article.id),
            "unit": "KG",
            "size": "M",
        }
        resp = api_client.post(
            reverse("harvest_share_planning-list"), payload, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_kg_per_piece_wider_than_the_column_returns_400(self, api_client, tenant):
        """``ShareContent.kg_per_piece`` is numeric(5,3). A wider value used to
        pass the serializer and fail at the INSERT as a generic data error; the
        serializer width now names the field."""
        article, day, variation, _station = self._setup()
        payload = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": str(article.id),
            "unit": "KG",
            "size": "M",
            "kg_per_piece": "1234.567",
            f"day_{day.id}_variation_{variation.id}": "3.5",
        }

        resp = api_client.post(
            reverse("harvest_share_planning-list"), payload, format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "kg_per_piece" in resp.data["details"]
        assert not ShareContent.objects.filter(share_article=article).exists()

    def test_price_per_unit_wider_than_the_column_returns_400(self, api_client, tenant):
        """``ShareContent.price_per_unit`` is numeric(6,2)."""
        article, day, variation, _station = self._setup()
        payload = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": str(article.id),
            "unit": "KG",
            "size": "M",
            "price_per_unit": "12345.67",
            f"day_{day.id}_variation_{variation.id}": "3.5",
        }

        resp = api_client.post(
            reverse("harvest_share_planning-list"), payload, format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "price_per_unit" in resp.data["details"]
        assert not ShareContent.objects.filter(share_article=article).exists()

    def test_amount_cell_wider_than_the_column_returns_400(self, api_client, tenant):
        """The dynamic cells land in numeric(5,3), so 100 is one integral digit
        too many. The offending cell key is named rather than the whole row
        failing at the database."""
        article, day, variation, _station = self._setup()
        cell = f"day_{day.id}_variation_{variation.id}"
        payload = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": str(article.id),
            "unit": "KG",
            "size": "M",
            cell: "100.5",
        }

        resp = api_client.post(
            reverse("harvest_share_planning-list"), payload, format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "amount.invalid"
        assert resp.data["field"] == cell
        assert not ShareContent.objects.filter(share_article=article).exists()

    def test_amount_cell_at_the_column_limit_is_accepted(self, api_client, tenant):
        article, day, variation, _station = self._setup()
        payload = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": str(article.id),
            "unit": "KG",
            "size": "M",
            f"day_{day.id}_variation_{variation.id}": "99.999",
        }

        resp = api_client.post(
            reverse("harvest_share_planning-list"), payload, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK
        share_content = ShareContent.objects.filter(share_article=article).first()
        assert share_content.amount == Decimal("99.999")

    @staticmethod
    def _create_slot(api_client, article, day, variation, **extra):
        payload = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": str(article.id),
            "unit": "KG",
            "size": "M",
            f"day_{day.id}_variation_{variation.id}": "3.5",
            **extra,
        }
        return api_client.post(
            reverse("harvest_share_planning-list"), payload, format="json"
        )

    @staticmethod
    def _slot_url(article):
        return reverse(
            "harvest_share_planning-detail", args=[f"2026_15_{article.id}_KG_M"]
        )

    def test_patch_keeps_the_stored_row_level_fields(self, api_client, tenant):
        """Editing one cell must not reset the slot's washing / cleaning /
        packing-station flags: the rebuild stamps them onto every recreated
        row, so an omitted flag used to come back as the column default."""
        article, day, variation, _station = self._setup()
        created = self._create_slot(
            api_client,
            article,
            day,
            variation,
            washing=True,
            packing_station=2,
            note="keep me",
        )
        assert created.status_code == status.HTTP_200_OK

        resp = api_client.patch(
            self._slot_url(article),
            {f"day_{day.id}_variation_{variation.id}": "4"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        row = ShareContent.objects.get(share_article=article, unit="KG", size="M")
        assert row.amount == Decimal("4")
        assert row.washing is True
        assert row.packing_station == 2
        assert row.note == "keep me"

    def test_patch_switching_to_cleaning_clears_the_stored_washing_flag(
        self, api_client, tenant
    ):
        """``ShareContent`` holds at most one of the two flags, so carrying the
        stored ``washing`` over onto a body that sets ``cleaning`` would rebuild
        the slot into the pair the database refuses."""
        article, day, variation, _station = self._setup()
        created = self._create_slot(api_client, article, day, variation, washing=True)
        assert created.status_code == status.HTTP_200_OK

        resp = api_client.patch(
            self._slot_url(article),
            {"cleaning": True, f"day_{day.id}_variation_{variation.id}": "5"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        row = ShareContent.objects.get(share_article=article, unit="KG", size="M")
        assert row.cleaning is True
        assert row.washing is False
        assert row.amount == Decimal("5")

    def test_a_payload_carrying_both_flags_is_refused(self, api_client, tenant):
        article, day, variation, _station = self._setup()

        resp = self._create_slot(
            api_client, article, day, variation, washing=True, cleaning=True
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "share_content.washing_cleaning_mutually_exclusive"
        assert not ShareContent.objects.filter(share_article=article).exists()

    def test_put_still_replaces_the_row_level_fields(self, api_client, tenant):
        """PUT stays a full replace: a flag the body omits falls back to the
        serializer default."""
        article, day, variation, _station = self._setup()
        created = self._create_slot(
            api_client, article, day, variation, washing=True, packing_station=2
        )
        assert created.status_code == status.HTTP_200_OK

        resp = api_client.put(
            self._slot_url(article),
            {f"day_{day.id}_variation_{variation.id}": "4"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        row = ShareContent.objects.get(share_article=article, unit="KG", size="M")
        assert row.washing is False
        assert row.packing_station == 1

    def test_delete_removes_the_slot(self, api_client, tenant):
        """The composite pk carries the week: its parsed parts reach the
        service as they are, so the rows of that week are the ones deleted."""
        article, day, variation, _station = self._setup()
        created = self._create_slot(api_client, article, day, variation)
        assert created.status_code == status.HTTP_200_OK

        resp = api_client.delete(self._slot_url(article))

        assert resp.status_code == status.HTTP_200_OK
        assert not ShareContent.objects.filter(
            share_article=article, share__year=2026, share__delivery_week=15
        ).exists()

    def test_delete_of_an_unplanned_slot_returns_404(self, api_client, tenant):
        article, _day, _variation, _station = self._setup()

        resp = api_client.delete(self._slot_url(article))

        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# VirtualComponentsViewSet — create validation wiring
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestVirtualComponentsViewSet:
    URL = reverse("virtual_variation_components-list")

    def test_valid_payload_creates_component(self, api_client, tenant):
        virtual = ShareTypeVariationFactory(variation_type="virtual")
        physical = ShareTypeVariationFactory(variation_type="physical")
        payload = {
            "virtual_variation": str(virtual.id),
            "components": [
                {"physical_variation": str(physical.id), "quantity": 3},
            ],
        }
        resp = api_client.post(self.URL, payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        component = VirtualVariationComponent.objects.get(
            virtual_variation_id=virtual.id
        )
        assert component.physical_variation_id == physical.id
        assert component.quantity == Decimal("3")
        virtual.refresh_from_db()
        assert virtual.variation_type == "virtual"

    def test_missing_virtual_variation_returns_400(self, api_client, tenant):
        physical = ShareTypeVariationFactory(variation_type="physical")
        # ``virtual_variation`` omitted → is_valid rejects (required CharField).
        bad = {"components": [{"physical_variation": str(physical.id), "quantity": 1}]}
        resp = api_client.post(self.URL, bad, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_physical_component_returns_400(self, api_client, tenant):
        virtual = ShareTypeVariationFactory(variation_type="virtual")
        other_virtual = ShareTypeVariationFactory(variation_type="virtual")
        # Passes is_valid, but the view rejects a non-physical component.
        bad = {
            "virtual_variation": str(virtual.id),
            "components": [
                {"physical_variation": str(other_virtual.id), "quantity": 1},
            ],
        }
        resp = api_client.post(self.URL, bad, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("quantity", [0, -1, "0.00"])
    def test_a_non_positive_quantity_is_rejected(self, api_client, tenant, quantity):
        """The factor multiplies subscription counts when virtual demand fans
        out into the physical variations, so it has to stay above zero."""
        virtual = ShareTypeVariationFactory(variation_type="virtual")
        physical = ShareTypeVariationFactory(variation_type="physical")
        resp = api_client.post(
            self.URL,
            {
                "virtual_variation": str(virtual.id),
                "components": [
                    {"physical_variation": str(physical.id), "quantity": quantity},
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert not VirtualVariationComponent.objects.filter(
            virtual_variation_id=virtual.id
        ).exists()

    def test_a_fractional_quantity_lands_exactly_on_the_column(
        self, api_client, tenant
    ):
        virtual = ShareTypeVariationFactory(variation_type="virtual")
        physical = ShareTypeVariationFactory(variation_type="physical")
        resp = api_client.post(
            self.URL,
            {
                "virtual_variation": str(virtual.id),
                "components": [
                    {"physical_variation": str(physical.id), "quantity": 2.5},
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        component = VirtualVariationComponent.objects.get(
            virtual_variation_id=virtual.id
        )
        assert component.quantity == Decimal("2.50")
        # The response echoes the quantity as a number, unchanged.
        assert resp.data["components"][0]["quantity"] == 2.5

    def test_an_omitted_quantity_defaults_to_one(self, api_client, tenant):
        virtual = ShareTypeVariationFactory(variation_type="virtual")
        physical = ShareTypeVariationFactory(variation_type="physical")
        resp = api_client.post(
            self.URL,
            {
                "virtual_variation": str(virtual.id),
                "components": [{"physical_variation": str(physical.id)}],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        component = VirtualVariationComponent.objects.get(
            virtual_variation_id=virtual.id
        )
        assert component.quantity == Decimal("1.00")

    def test_the_column_default_is_a_decimal(self):
        """The round-trip above cannot tell the defaults apart — Postgres
        normalises a float and a Decimal to the same stored value. An unsaved
        instance can, and it is the one that reaches Decimal arithmetic."""
        default = VirtualVariationComponent().quantity

        assert isinstance(default, Decimal)
        assert default == Decimal("1.00")


# ---------------------------------------------------------------------------
# ShareDeliveryViewSet / ShareDeliveryOverviewViewSet — joker_taken re-plans
# billing. Editing joker_taken must notify payments so a jokered
# (skipped) week isn't still charged; the recompute alone doesn't touch billing.
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareDeliveryJokerBillingNotify:
    def _share_delivery_with_subscription(self):
        # Share + delivery_station_day must reference ONE SharesDeliveryDay,
        # otherwise the two factory chains each open a day_number=2 row and
        # violate the global ``sharesdeliveryday_one_open_per_day_number``
        # constraint. (Mirrors test_optin_service._make_share_delivery.)
        day = SharesDeliveryDayFactory()
        station_day = DeliveryStationDayFactory(delivery_day=day)
        # The share and the subscription must share one ShareTypeVariation
        # (ShareDelivery.save validates they match).
        variation = ShareTypeVariationFactory()
        share = ShareFactory(delivery_day=day, share_type_variation=variation)
        subscription = SubscriptionFactory(
            share_type_variation=variation, default_delivery_station_day=station_day
        )
        return ShareDeliveryFactory(
            share=share,
            subscription=subscription,
            delivery_station_day=station_day,
            joker_taken=False,
        )

    def test_share_delivery_update_notifies_subscription(self, api_client, tenant):
        share_delivery = self._share_delivery_with_subscription()
        url = reverse("share_delivery-detail", kwargs={"pk": share_delivery.pk})

        # Patch at the source module: perform_update imports
        # notify_subscription_changed (and recompute_shares) function-locally,
        # so the name resolves from the source at call time. recompute_shares is
        # isolated here — the assertion is purely about the billing notify.
        with (
            mock.patch(
                "apps.shared.subscription_hooks.notify_subscription_changed"
            ) as notify,
            mock.patch("apps.commissioning.services.recompute.recompute_shares"),
        ):
            resp = api_client.patch(url, {"joker_taken": True}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        notify.assert_called_once_with(share_delivery.subscription)

    def test_share_delivery_destroy_notifies_subscription(self, api_client, tenant):
        # Removing a delivery changes the billable set → must notify.
        share_delivery = self._share_delivery_with_subscription()
        subscription = share_delivery.subscription
        with (
            mock.patch(
                "apps.shared.subscription_hooks.notify_subscription_changed"
            ) as notify,
            mock.patch("apps.commissioning.services.recompute.recompute_shares"),
        ):
            resp = api_client.delete(
                reverse("share_delivery-detail", kwargs={"pk": share_delivery.pk})
            )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        notify.assert_called_once_with(subscription)

    def test_share_delivery_overview_destroy_notifies_subscription(
        self, api_client, tenant
    ):
        share_delivery = self._share_delivery_with_subscription()
        subscription = share_delivery.subscription
        with (
            mock.patch(
                "apps.shared.subscription_hooks.notify_subscription_changed"
            ) as notify,
            mock.patch("apps.commissioning.services.recompute.recompute_shares"),
        ):
            resp = api_client.delete(
                reverse(
                    "share_delivery_overview-detail", kwargs={"pk": share_delivery.pk}
                )
            )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        notify.assert_called_once_with(subscription)

    def test_share_delivery_overview_update_notifies_subscription(
        self, api_client, tenant
    ):
        share_delivery = self._share_delivery_with_subscription()
        url = reverse(
            "share_delivery_overview-detail", kwargs={"pk": share_delivery.pk}
        )

        with (
            mock.patch(
                "apps.shared.subscription_hooks.notify_subscription_changed"
            ) as notify,
            mock.patch("apps.commissioning.services.recompute.recompute_shares"),
        ):
            resp = api_client.patch(url, {"joker_taken": True}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        notify.assert_called_once_with(share_delivery.subscription)


@pytest.mark.django_db
class TestShareDeliveryOverviewFilter:
    """The overview list can scope to a single delivery station (the Abos >
    ShareDeliveries station filter)."""

    def test_list_filters_by_delivery_station(self, api_client, tenant):
        # ONE SharesDeliveryDay (global day_number scope), TWO stations on it.
        day = SharesDeliveryDayFactory()
        station_day_1 = DeliveryStationDayFactory(delivery_day=day)
        station_day_2 = DeliveryStationDayFactory(delivery_day=day)

        def _delivery(station_day):
            variation = ShareTypeVariationFactory()
            share = ShareFactory(
                year=2026, delivery_day=day, share_type_variation=variation
            )
            subscription = SubscriptionFactory(
                share_type_variation=variation,
                default_delivery_station_day=station_day,
            )
            return ShareDeliveryFactory(
                share=share,
                subscription=subscription,
                delivery_station_day=station_day,
            )

        d1 = _delivery(station_day_1)
        _delivery(station_day_2)  # a second station's delivery — must be excluded

        resp = api_client.get(
            reverse("share_delivery_overview-list"),
            {"year": 2026, "delivery_station": station_day_1.delivery_station_id},
        )
        assert resp.status_code == status.HTTP_200_OK
        rows = resp.json()
        if isinstance(rows, dict):
            rows = rows.get("results", [])
        assert {row["id"] for row in rows} == {d1.id}


@pytest.mark.django_db
class TestShareDeliveryCreateCapacity:
    """``perform_create`` must run the same station-day capacity guard as
    ``perform_update`` — otherwise the office could over-fill a station-day by
    creating deliveries directly. Exercised at the ``perform_create``
    boundary with the REAL capacity service (the write serializer's nested-source
    fields make a plain POST payload impractical, but the guard is the unit here).
    """

    YEAR = 2026
    WEEK = 40

    def _harvest_share(self, day):
        variation = ShareTypeVariationFactory(
            share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
        )
        return ShareFactory(
            year=self.YEAR,
            delivery_week=self.WEEK,
            delivery_day=day,
            share_type_variation=variation,
        )

    def _serializer_with(self, *, share, dsd):
        serializer = mock.MagicMock()
        serializer.validated_data = {"share": share, "delivery_station_day": dsd}
        return serializer

    @pytest.mark.parametrize(
        "viewset_cls",
        [ShareDeliveryViewSet, ShareDeliveryOverviewViewSet],
    )
    def test_create_onto_full_station_day_is_rejected(self, tenant, viewset_cls):
        day = SharesDeliveryDayFactory()
        dsd = DeliveryStationDayFactory(delivery_day=day, capacity=1)
        # Fill the single slot with a harvest delivery for the week.
        ShareDeliveryFactory(share=self._harvest_share(day), delivery_station_day=dsd)
        new_share = self._harvest_share(day)
        serializer = self._serializer_with(share=new_share, dsd=dsd)

        with pytest.raises(DeliveryStationOverCapacity):
            viewset_cls().perform_create(serializer)
        # The guard runs BEFORE save() — nothing was persisted.
        serializer.save.assert_not_called()

    def test_create_with_free_capacity_proceeds(self, tenant):
        day = SharesDeliveryDayFactory()
        dsd = DeliveryStationDayFactory(delivery_day=day, capacity=5)  # room to spare
        new_share = self._harvest_share(day)
        serializer = self._serializer_with(share=new_share, dsd=dsd)
        # subscription_id / share_id None → the notify + recompute hooks no-op.
        serializer.save.return_value = mock.MagicMock(
            subscription_id=None, share_id=None
        )

        ShareDeliveryViewSet().perform_create(serializer)
        serializer.save.assert_called_once()


@pytest.mark.django_db
class TestShareDeliveryCrossDayMove:
    """Moving a delivery to a station-day on ANOTHER weekday re-points its Share
    to that day's planning unit (creating it), instead of failing the
    Share/DeliveryStationDay day-match validation."""

    def test_moving_to_another_day_repoints_the_share(self, api_client, tenant):
        day_a = SharesDeliveryDayFactory(day_number=4)  # Friday
        day_b = SharesDeliveryDayFactory(day_number=0)  # Monday
        variation = ShareTypeVariationFactory()
        dsd_a = DeliveryStationDayFactory(delivery_day=day_a)
        dsd_b = DeliveryStationDayFactory(delivery_day=day_b)
        share_a = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=day_a,
            share_type_variation=variation,
        )
        sub = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=dsd_a,
        )
        delivery = ShareDeliveryFactory(
            share=share_a, delivery_station_day=dsd_a, subscription=sub
        )

        url = reverse("share_delivery-detail", args=[delivery.pk])
        resp = api_client.patch(url, {"delivery_station_day": dsd_b.id}, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        delivery.refresh_from_db()
        assert delivery.delivery_station_day_id == dsd_b.id
        # The delivery's Share moved to the Monday planning unit (get-or-created).
        assert delivery.share.delivery_day_id == day_b.id
        assert Share.objects.filter(
            year=2026,
            delivery_week=15,
            delivery_day=day_b,
            share_type_variation=variation,
        ).exists()

    def test_same_day_station_move_keeps_the_share(self, api_client, tenant):
        day = SharesDeliveryDayFactory(day_number=4)
        variation = ShareTypeVariationFactory()
        dsd_1 = DeliveryStationDayFactory(delivery_day=day)
        dsd_2 = DeliveryStationDayFactory(delivery_day=day)
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=day,
            share_type_variation=variation,
        )
        sub = SubscriptionFactory(
            share_type_variation=variation, default_delivery_station_day=dsd_1
        )
        delivery = ShareDeliveryFactory(
            share=share, delivery_station_day=dsd_1, subscription=sub
        )

        url = reverse("share_delivery-detail", args=[delivery.pk])
        resp = api_client.patch(url, {"delivery_station_day": dsd_2.id}, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        delivery.refresh_from_db()
        assert delivery.delivery_station_day_id == dsd_2.id
        # Same weekday → the Share is untouched.
        assert delivery.share_id == share.id

    def test_overview_grid_cross_day_move_repoints_the_share(self, api_client, tenant):
        """The Abos > ShareDeliveries office grid (ShareDeliveryOverviewViewSet)
        round-trips the current ``share`` id back with a station-day edit; moving
        to another weekday must re-point the Share, not fail the day-match
        validation."""
        day_a = SharesDeliveryDayFactory(day_number=4)  # Friday
        day_b = SharesDeliveryDayFactory(day_number=0)  # Monday
        variation = ShareTypeVariationFactory()
        dsd_a = DeliveryStationDayFactory(delivery_day=day_a)
        dsd_b = DeliveryStationDayFactory(delivery_day=day_b)
        share_a = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=day_a,
            share_type_variation=variation,
        )
        sub = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=dsd_a,
        )
        delivery = ShareDeliveryFactory(
            share=share_a, delivery_station_day=dsd_a, subscription=sub
        )

        url = reverse("share_delivery_overview-detail", args=[delivery.pk])
        # Mirror the grid's round-trip: it echoes the current ``share`` id back
        # alongside the new station-day. Without the re-point this trips
        # "Delivery day of Share and DeliveryStationDay must match".
        resp = api_client.patch(
            url,
            {"share": share_a.id, "delivery_station_day": dsd_b.id},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        delivery.refresh_from_db()
        assert delivery.delivery_station_day_id == dsd_b.id
        assert delivery.share.delivery_day_id == day_b.id
        assert Share.objects.filter(
            year=2026,
            delivery_week=15,
            delivery_day=day_b,
            share_type_variation=variation,
        ).exists()


@pytest.mark.django_db
class TestShareDeliveryApplyToFuture:
    """``apply_to_future`` is read from the serializer, which parses it, so an
    explicit false leaves the subscription's later deliveries where they are."""

    def _subscription_with_two_deliveries(self):
        day = SharesDeliveryDayFactory(day_number=4)  # Friday
        variation = ShareTypeVariationFactory()
        station_day_from = DeliveryStationDayFactory(delivery_day=day)
        station_day_to = DeliveryStationDayFactory(delivery_day=day)
        subscription = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=station_day_from,
        )
        deliveries = [
            ShareDeliveryFactory(
                share=ShareFactory(
                    year=2026,
                    delivery_week=week,
                    delivery_day=day,
                    share_type_variation=variation,
                ),
                delivery_station_day=station_day_from,
                subscription=subscription,
            )
            for week in (15, 16)
        ]
        return deliveries[0], deliveries[1], station_day_from, station_day_to

    @pytest.mark.parametrize("raw", ["false", "0"])
    def test_false_does_not_propagate_to_future_deliveries(
        self, api_client, tenant, raw
    ):
        edited, later, station_day_from, station_day_to = (
            self._subscription_with_two_deliveries()
        )
        resp = api_client.patch(
            reverse("share_delivery-detail", args=[edited.pk]),
            {"delivery_station_day": station_day_to.id, "apply_to_future": raw},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        edited.refresh_from_db()
        later.refresh_from_db()
        assert edited.delivery_station_day_id == station_day_to.id
        assert later.delivery_station_day_id == station_day_from.id

    def test_absent_does_not_propagate_to_future_deliveries(self, api_client, tenant):
        edited, later, station_day_from, station_day_to = (
            self._subscription_with_two_deliveries()
        )
        resp = api_client.patch(
            reverse("share_delivery-detail", args=[edited.pk]),
            {"delivery_station_day": station_day_to.id},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        later.refresh_from_db()
        assert later.delivery_station_day_id == station_day_from.id

    def test_true_still_propagates_to_future_deliveries(self, api_client, tenant):
        edited, later, _station_day_from, station_day_to = (
            self._subscription_with_two_deliveries()
        )
        resp = api_client.patch(
            reverse("share_delivery-detail", args=[edited.pk]),
            {"delivery_station_day": station_day_to.id, "apply_to_future": True},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        later.refresh_from_db()
        assert later.delivery_station_day_id == station_day_to.id


@pytest.mark.django_db
class TestShareDeliveryExceptionGaps:
    """The ``exception_gaps`` action reconstructs the weeks a member's
    subscriptions WOULD deliver but don't, because a delivery exception
    (Lieferpause) removed the ShareDelivery — there's no ShareDelivery row for
    the deliveries card to show, so it needs these."""

    URL = reverse("share_delivery-exception-gaps")

    def _confirmed_subscription(self, member, variation):
        from isoweek import Week

        return SubscriptionFactory(
            member=member,
            share_type_variation=variation,
            default_delivery_station_day=DeliveryStationDayFactory(),  # Wed (2)
            valid_from=datetime.date(2026, 1, 5),  # Monday
            valid_until=Week(2026, 52).sunday(),
            admin_confirmed=True,
        )

    def test_returns_paused_weeks_as_gaps(self, api_client, tenant):
        from isoweek import Week

        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        self._confirmed_subscription(member, variation)
        pause = Week(2026, 40)
        DeliveryExceptionPeriod.objects.create(
            share_type_variation=variation,
            valid_from=pause.monday(),
            valid_until=pause.sunday(),
            note="Herbstpause",
        )

        resp = api_client.get(self.URL, {"member": str(member.id), "year": 2026})
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert len(resp.data) == 1
        gap = resp.data[0]
        assert gap["year"] == 2026
        assert gap["delivery_week"] == 40
        assert gap["note"] == "Herbstpause"
        assert gap["share_type_name"] == variation.share_type.name
        assert gap["delivery_day_number"] == 2

    def test_no_exceptions_returns_empty(self, api_client, tenant):
        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        self._confirmed_subscription(member, variation)

        resp = api_client.get(self.URL, {"member": str(member.id), "year": 2026})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_member_may_fetch_own_gaps(self, member_user, tenant):
        """A plain member reaches the action for their OWN gaps — the whole
        point of the self-scoping. exception_gaps must be in the
        viewset's member-reachable allowlist, else the member is 403'd by
        write_permission=IsOffice before the self-check runs."""
        member = MemberFactory(user=member_user)
        variation = ShareTypeVariationFactory()
        self._confirmed_subscription(member, variation)

        client = APIClient()
        client.force_authenticate(user=member_user)
        resp = client.get(self.URL, {"member": str(member.id), "year": 2026})
        assert resp.status_code == status.HTTP_200_OK, resp.data

    def test_member_may_not_fetch_another_members_gaps(self, member_user, tenant):
        """Self-scoping still bites: a member asking for someone else's gaps
        is forbidden."""
        MemberFactory(user=member_user)
        other = MemberFactory()

        client = APIClient()
        client.force_authenticate(user=member_user)
        resp = client.get(self.URL, {"member": str(other.id), "year": 2026})
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# ShareTypeVariationGrossPriceViewSet — DELETE enforces can_be_deleted
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareTypeVariationGrossPriceDestroyGuard:
    @staticmethod
    def _url(price) -> str:
        return reverse("share_type_variation_price-detail", args=[price.id])

    def test_price_of_subscribed_variation_is_409_and_kept(self, api_client, tenant):
        price = ShareTypeVariationGrossPriceFactory()
        SubscriptionFactory(share_type_variation=price.share_type_variation)

        resp = api_client.delete(self._url(price))

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "share_type_variation.gross_price_in_use"
        assert ShareTypeVariationGrossPrice.objects.filter(pk=price.pk).exists()

    def test_price_of_unsubscribed_variation_is_deleted(self, api_client, tenant):
        price = ShareTypeVariationGrossPriceFactory()

        resp = api_client.delete(self._url(price))

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not ShareTypeVariationGrossPrice.objects.filter(pk=price.pk).exists()


# ---------------------------------------------------------------------------
# ShareDeliveryOverviewViewSet — re-pointing a delivery to another week
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareDeliveryShareOnlyRepointCapacity:
    """``share`` stays writable on the office grid, so a delivery can be moved
    to another week without touching its station-day. That re-point lands on a
    different (station-day, week) slot and must clear the same capacity gate as
    a station-day move."""

    @staticmethod
    def _url(delivery) -> str:
        return reverse("share_delivery_overview-detail", args=[delivery.id])

    @staticmethod
    def _week_shares(day):
        """Two Shares one week apart, same weekday and variation — the before
        and after of a week re-point."""
        variation = ShareTypeVariationFactory(
            share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
        )
        return [
            ShareFactory(
                year=2026,
                delivery_week=week,
                delivery_day=day,
                share_type_variation=variation,
            )
            for week in (15, 16)
        ]

    def test_repointing_into_a_full_week_is_rejected(self, api_client, tenant):
        day = SharesDeliveryDayFactory()
        station_day = DeliveryStationDayFactory(delivery_day=day, capacity=1)
        share_week_15, share_week_16 = self._week_shares(day)
        moving = ShareDeliveryFactory(
            share=share_week_15, delivery_station_day=station_day
        )
        # Week 16's single slot at this station-day is already taken.
        ShareDeliveryFactory(share=share_week_16, delivery_station_day=station_day)

        resp = api_client.patch(
            self._url(moving), {"share": share_week_16.id}, format="json"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "delivery_station.over_capacity"
        moving.refresh_from_db()
        assert moving.share_id == share_week_15.id

    def test_repointing_into_a_week_with_room_succeeds(self, api_client, tenant):
        day = SharesDeliveryDayFactory()
        station_day = DeliveryStationDayFactory(delivery_day=day, capacity=5)
        share_week_15, share_week_16 = self._week_shares(day)
        moving = ShareDeliveryFactory(
            share=share_week_15, delivery_station_day=station_day
        )
        ShareDeliveryFactory(share=share_week_16, delivery_station_day=station_day)

        resp = api_client.patch(
            self._url(moving), {"share": share_week_16.id}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        moving.refresh_from_db()
        assert moving.share_id == share_week_16.id


# ---------------------------------------------------------------------------
# ShareDeliveryViewSet — one PATCH that reassigns the week AND crosses weekdays
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareDeliveryCombinedShareAndCrossDayMove:
    """Both ``share`` and ``delivery_station_day`` are writable, so a single
    PATCH can move a delivery to another week AND to a station-day on another
    weekday. The weekday re-point must carry the REQUESTED week — and the
    capacity gate must judge the slot the save actually writes."""

    @staticmethod
    def _url(delivery) -> str:
        return reverse("share_delivery-detail", args=[delivery.pk])

    @staticmethod
    def _week_shares(variation, day):
        """The week-15 and week-16 Shares for one weekday + variation."""
        return {
            week: ShareFactory(
                year=2026,
                delivery_week=week,
                delivery_day=day,
                share_type_variation=variation,
            )
            for week in (15, 16)
        }

    def test_the_requested_week_is_written_not_the_original_one(
        self, api_client, tenant
    ):
        friday = SharesDeliveryDayFactory(day_number=4)
        monday = SharesDeliveryDayFactory(day_number=0)
        variation = ShareTypeVariationFactory(
            share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
        )
        origin_station_day = DeliveryStationDayFactory(delivery_day=friday, capacity=5)
        target_station_day = DeliveryStationDayFactory(delivery_day=monday, capacity=1)
        friday_shares = self._week_shares(variation, friday)
        monday_shares = self._week_shares(variation, monday)
        moving = ShareDeliveryFactory(
            share=friday_shares[15], delivery_station_day=origin_station_day
        )
        # The target station-day's only week-15 slot is taken; week 16 is free.
        ShareDeliveryFactory(
            share=monday_shares[15], delivery_station_day=target_station_day
        )

        resp = api_client.patch(
            self._url(moving),
            {
                "share": friday_shares[16].id,
                "delivery_station_day": target_station_day.id,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        moving.refresh_from_db()
        assert moving.delivery_station_day_id == target_station_day.id
        # The requested week survives the weekday re-point…
        assert moving.share.delivery_week == 16
        assert moving.share.delivery_day_id == monday.id
        # …so the full week-15 slot at the target station-day is untouched.
        assert (
            ShareDelivery.objects.filter(
                delivery_station_day=target_station_day, share__delivery_week=15
            ).count()
            == 1
        )

    def test_a_full_requested_week_is_rejected(self, api_client, tenant):
        friday = SharesDeliveryDayFactory(day_number=4)
        monday = SharesDeliveryDayFactory(day_number=0)
        variation = ShareTypeVariationFactory(
            share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
        )
        origin_station_day = DeliveryStationDayFactory(delivery_day=friday, capacity=5)
        target_station_day = DeliveryStationDayFactory(delivery_day=monday, capacity=1)
        friday_shares = self._week_shares(variation, friday)
        monday_shares = self._week_shares(variation, monday)
        moving = ShareDeliveryFactory(
            share=friday_shares[15], delivery_station_day=origin_station_day
        )
        # Week 16 is the one being asked for, and it is full at the target.
        ShareDeliveryFactory(
            share=monday_shares[16], delivery_station_day=target_station_day
        )

        resp = api_client.patch(
            self._url(moving),
            {
                "share": friday_shares[16].id,
                "delivery_station_day": target_station_day.id,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "delivery_station.over_capacity"
        moving.refresh_from_db()
        assert moving.share_id == friday_shares[15].id
        assert moving.delivery_station_day_id == origin_station_day.id


@pytest.mark.django_db
class TestShareDeliveryDetailsList:
    """The station pickup sheet: one merged row per member, scoped to the week
    and weekday it is printed for, and paginatable."""

    URL = reverse("share_delivery_details-list")
    YEAR = 2026
    WEEK = 12
    DAY_NUMBER = 2

    def _delivery(self, *, day, station_day, last_name, week=None):
        variation = ShareTypeVariationFactory()
        share = ShareFactory(
            year=self.YEAR,
            delivery_week=week or self.WEEK,
            delivery_day=day,
            share_type_variation=variation,
        )
        subscription = SubscriptionFactory(
            member=MemberFactory(last_name=last_name),
            share_type_variation=variation,
            default_delivery_station_day=station_day,
        )
        return ShareDeliveryFactory(
            share=share, subscription=subscription, delivery_station_day=station_day
        )

    def _scope(self, **extra):
        return {
            "year": self.YEAR,
            "delivery_week": self.WEEK,
            "day_number": self.DAY_NUMBER,
            **extra,
        }

    def test_list_without_the_week_scope_is_400(self, api_client, tenant):
        """Without a week scope the sheet is every shippable delivery in the
        tenant; the schema declares the three as required and the endpoint
        enforces it."""
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["field"] == "year"

    def test_returns_a_plain_array_of_member_rows(self, api_client, tenant):
        day = SharesDeliveryDayFactory(day_number=self.DAY_NUMBER)
        station_day = DeliveryStationDayFactory(delivery_day=day)
        self._delivery(day=day, station_day=station_day, last_name="Aaa")
        self._delivery(day=day, station_day=station_day, last_name="Bbb")

        resp = api_client.get(self.URL, self._scope())

        assert resp.status_code == status.HTTP_200_OK
        rows = resp.json()
        assert isinstance(rows, list)
        assert [row["name"] for row in rows] == sorted(row["name"] for row in rows)
        assert len(rows) == 2

    def test_another_week_is_excluded_without_a_station_filter(
        self, api_client, tenant
    ):
        """Each filter narrows on its own: with no station filter the week
        scope still holds, rather than widening to every delivery."""
        day = SharesDeliveryDayFactory(day_number=self.DAY_NUMBER)
        station_day = DeliveryStationDayFactory(delivery_day=day)
        self._delivery(day=day, station_day=station_day, last_name="Thisweek")
        self._delivery(
            day=day, station_day=station_day, last_name="Nextweek", week=self.WEEK + 1
        )

        rows = api_client.get(self.URL, self._scope()).json()

        assert len(rows) == 1
        assert rows[0]["name"].startswith("Thisweek")

    def test_station_filter_narrows_to_that_station(self, api_client, tenant):
        day = SharesDeliveryDayFactory(day_number=self.DAY_NUMBER)
        station_day = DeliveryStationDayFactory(delivery_day=day)
        other_station_day = DeliveryStationDayFactory(delivery_day=day)
        self._delivery(day=day, station_day=station_day, last_name="Mine")
        self._delivery(day=day, station_day=other_station_day, last_name="Theirs")

        rows = api_client.get(
            self.URL,
            self._scope(delivery_station=station_day.delivery_station_id),
        ).json()

        assert len(rows) == 1
        assert "Mine" in rows[0]["name"]

    def test_limit_returns_the_envelope_counting_member_rows(self, api_client, tenant):
        day = SharesDeliveryDayFactory(day_number=self.DAY_NUMBER)
        station_day = DeliveryStationDayFactory(delivery_day=day)
        for last_name in ("Aaa", "Bbb", "Ccc"):
            self._delivery(day=day, station_day=station_day, last_name=last_name)

        body = api_client.get(self.URL, self._scope(limit=2)).json()

        assert body["count"] == 3
        assert len(body["results"]) == 2

    @pytest.mark.parametrize("raw", ["abc", "0", "-3"])
    def test_unusable_limit_is_400(self, api_client, tenant, raw):
        resp = api_client.get(self.URL, self._scope(limit=raw))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["field"] == "limit"


# ---------------------------------------------------------------------------
# ShareDeliveryViewSet.box_combination_matrix — flag handling
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBoxCombinationMatrixFlags:
    """The whole-week matrix answers one row axis and one box scope at a time:
    ``for_tours`` / ``for_stations`` choose the axis, ``joker`` /
    ``donation_joker`` choose which boxes are counted. Both halves of a pair
    have no single answer, so they are refused rather than reconciled by a
    precedence the caller cannot see. ``is_packed_bulk`` narrows the variations
    on the import branch too, not only on the box-combination one.
    """

    URL = reverse("share_delivery-box-combination-matrix")

    @staticmethod
    def _scope(**extra: object) -> dict[str, object]:
        return {"year": 2026, "delivery_week": 15, **extra}

    def test_for_stations_and_for_tours_both_true_is_400(self, api_client, tenant):
        resp = api_client.get(
            self.URL, self._scope(for_stations="true", for_tours="true")
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "for_tours"

    def test_joker_and_donation_joker_both_true_is_400(self, api_client, tenant):
        resp = api_client.get(
            self.URL, self._scope(joker="true", donation_joker="true")
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "donation_joker"

    def test_axis_conflict_details_echo_the_sent_spellings(self, api_client, tenant):
        """``details`` carries the offending values so the client can show them.
        Both halves parsed to true, so the wire text is the only thing left that
        distinguishes the accepted spellings the caller actually used."""
        resp = api_client.get(self.URL, self._scope(for_stations="on", for_tours="1"))

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["details"] == {"for_stations": "on", "for_tours": "1"}

    def test_scope_conflict_details_echo_the_sent_spellings(self, api_client, tenant):
        resp = api_client.get(self.URL, self._scope(joker="yes", donation_joker="true"))

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["details"] == {"joker": "yes", "donation_joker": "true"}

    def test_one_flag_from_each_pair_still_answers(self, api_client, tenant):
        resp = api_client.get(self.URL, self._scope(for_stations="true", joker="true"))
        assert resp.status_code == status.HTTP_200_OK

    def test_an_explicit_false_half_is_not_a_conflict(self, api_client, tenant):
        """The refusal keys on a flag being requested, not on it being present:
        a caller that sends the whole flag set with one half false is asking for
        exactly one axis and one scope, so it is served."""
        resp = api_client.get(
            self.URL,
            self._scope(
                for_stations="false",
                for_tours="true",
                joker="false",
                donation_joker="true",
            ),
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_import_branch_applies_is_packed_bulk(self, api_client, tenant):
        """On an import (external-demand) tenant the flag narrows the matrix to
        the bulk-packed variations — the COLUMNS included, since a variation
        outside the filter has no column to carry."""
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(
            delivery_day=delivery_day, tour_number=1
        )
        bulk = ShareTypeVariationFactory(size="S", is_packed_bulk=True)
        individual = ShareTypeVariationFactory(size="L", is_packed_bulk=False)
        batch = ShareImportBatch.objects.create(
            year=2026,
            delivery_week=15,
            file_checksum="1" * 64,
            original_filename="seed.csv",
            status=ShareImportBatch.STATUS_APPLIED,
        )
        for variation, quantity in ((bulk, 3), (individual, 5)):
            ExternalShareDemand.objects.create(
                batch=batch,
                year=2026,
                delivery_week=15,
                delivery_station_day=station_day,
                share_type_variation=variation,
                quantity=quantity,
            )

        with mock.patch(
            "apps.commissioning.services.share_demand_service._resolve_backend",
            return_value=ExternalDemandBackend(),
        ):
            body = api_client.get(self.URL, self._scope(is_packed_bulk="true")).json()

        assert [column["key"] for column in body["columns"]] == [f"variation_{bulk.pk}"]
        row = body["rows"][0]
        assert row[f"variation_{bulk.pk}"] == 3
        assert f"variation_{individual.pk}" not in row

    def test_import_branch_forwards_both_joker_flags(self, api_client, tenant):
        """Import (CSV) demand carries no joker information, so asking the
        import branch for jokered or donation-jokered counts yields no rows —
        each flag reaches the demand port on its own, while a request for the
        shipping counts still sees the imported demand."""
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(
            delivery_day=delivery_day, tour_number=1
        )
        variation = ShareTypeVariationFactory(size="S")
        batch = ShareImportBatch.objects.create(
            year=2026,
            delivery_week=15,
            file_checksum="2" * 64,
            original_filename="seed.csv",
            status=ShareImportBatch.STATUS_APPLIED,
        )
        ExternalShareDemand.objects.create(
            batch=batch,
            year=2026,
            delivery_week=15,
            delivery_station_day=station_day,
            share_type_variation=variation,
            quantity=4,
        )

        with mock.patch(
            "apps.commissioning.services.share_demand_service._resolve_backend",
            return_value=ExternalDemandBackend(),
        ):
            shipping = api_client.get(self.URL, self._scope()).json()
            jokered = api_client.get(self.URL, self._scope(joker="true")).json()
            donated = api_client.get(
                self.URL, self._scope(donation_joker="true")
            ).json()

        assert shipping["rows"][0][f"variation_{variation.pk}"] == 4
        assert jokered["rows"] == []
        assert donated["rows"] == []
