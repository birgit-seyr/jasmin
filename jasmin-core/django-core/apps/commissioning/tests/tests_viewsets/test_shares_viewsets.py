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
    Share,
    ShareContent,
    VirtualVariationComponent,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
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
        # full_clean / DB constraint, not the removed serializer validator).
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
# ShareDeliveryViewSet — variation_delivery_counts
# ---------------------------------------------------------------------------
URL_SD_VARIATION_COUNTS = reverse("share_delivery-variation-delivery-counts")


@pytest.mark.django_db
class TestShareDeliveryVariationCountsAction:
    def test_missing_share_type_returns_400(self, api_client, tenant):
        resp = api_client.get(
            URL_SD_VARIATION_COUNTS,
            {"year": 2026, "delivery_week": 15},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["field"] == "share_type"

    def test_returns_empty_for_unknown_share_type(self, api_client, tenant):
        """No deliveries for the week → service returns empty container."""
        st = ShareTypeFactory()
        resp = api_client.get(
            URL_SD_VARIATION_COUNTS,
            {"share_type": str(st.id), "year": 2099, "delivery_week": 1},
        )
        assert resp.status_code == status.HTTP_200_OK


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

    def test_filters_to_requested_share_option(self, api_client, tenant):
        """The view filters service results to entries where
        ``share_option == share_option``. With no matches, returns []."""
        resp = api_client.get(
            URL_DSC_BULK_LIST,
            {"year": 2099, "share_option": "HARVEST_SHARE"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []


@pytest.mark.django_db
class TestDefaultShareContentBulkUpdate:
    def test_invalid_composite_id_returns_400(self, api_client, tenant):
        """Composite ID must split into exactly 4 parts on ``_``. Now a
        canonical ``CompositeIdInvalid`` body, not a hand-built ``{"error"}``."""
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
        # Regression guard: the EditableTable sends note=null for un-annotated
        # rows; the request serializer must allow it (allow_null=True).
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
        # create-specific "at least one amount" guard (kept after wiring).
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


# ---------------------------------------------------------------------------
# ShareDeliveryViewSet / ShareDeliveryOverviewViewSet — joker_taken re-plans
# billing (BIZ-1). Editing joker_taken must notify payments so a jokered
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
        # MEM-2: removing a delivery changes the billable set → must notify.
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
    """MEM-2: ``perform_create`` must run the same station-day capacity guard as
    ``perform_update`` — the create path skipped it, so the office could over-fill
    a station-day by creating deliveries directly. Exercised at the ``perform_create``
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
