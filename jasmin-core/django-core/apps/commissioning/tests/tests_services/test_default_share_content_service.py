"""Tests for DefaultShareContentService."""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.commissioning.models import (
    DefaultShareContent,
    MovementShareArticle,
    Share,
    ShareContent,
)
from apps.commissioning.services.default_share_content_service import (
    DefaultShareContentService,
)
from apps.commissioning.tests.factories import (
    DefaultShareContentFactory,
    DeliveryStationDayFactory,
    MemberFactory,
    MovementShareArticleFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from core.errors import JasminError


# ---------------------------------------------------------------------------
# _filter_weeks  (pure — no DB)
# ---------------------------------------------------------------------------
class TestFilterWeeks:
    def test_no_filters_returns_all(self):
        result = DefaultShareContentService._filter_weeks(range(1, 6))
        assert result == [1, 2, 3, 4, 5]

    def test_only_odd(self):
        result = DefaultShareContentService._filter_weeks(range(1, 7), only_odd=True)
        assert result == [1, 3, 5]

    def test_only_even(self):
        result = DefaultShareContentService._filter_weeks(range(1, 7), only_even=True)
        assert result == [2, 4, 6]

    def test_only_every_three(self):
        result = DefaultShareContentService._filter_weeks(
            range(1, 10), only_every_three=True
        )
        # indices 0, 3, 6 → weeks 1, 4, 7
        assert result == [1, 4, 7]

    def test_empty_range(self):
        result = DefaultShareContentService._filter_weeks(range(0, 0))
        assert result == []


# ---------------------------------------------------------------------------
# _detect_week_pattern  (pure — no DB)
# ---------------------------------------------------------------------------
class TestDetectWeekPattern:
    def test_all_weeks(self):
        (
            only_odd,
            only_even,
            every_three,
        ) = DefaultShareContentService._detect_week_pattern([1, 2, 3, 4], 1, 4)
        assert not only_odd
        assert not only_even
        assert not every_three

    def test_odd_weeks(self):
        (
            only_odd,
            only_even,
            every_three,
        ) = DefaultShareContentService._detect_week_pattern([1, 3, 5], 1, 6)
        assert only_odd
        assert not only_even

    def test_even_weeks(self):
        (
            only_odd,
            only_even,
            every_three,
        ) = DefaultShareContentService._detect_week_pattern([2, 4, 6], 1, 6)
        assert not only_odd
        assert only_even

    def test_every_three_weeks(self):
        # range_1=1, range_2=7 → expected indices 0,3,6 → weeks 1,4,7
        (
            only_odd,
            only_even,
            every_three,
        ) = DefaultShareContentService._detect_week_pattern([1, 4, 7], 1, 7)
        assert every_three


# ---------------------------------------------------------------------------
# _get_future_weeks  (pure — no DB)
# ---------------------------------------------------------------------------
class TestGetFutureWeeks:
    def test_returns_only_future(self):
        # Use a date in the middle of a year
        current = datetime.date(2026, 6, 1)  # a Monday in week 23
        weeks = [20, 22, 24, 26]
        result = DefaultShareContentService._get_future_weeks(2026, weeks, current)
        # Week 20 Mon=May 11, Week 22 Mon=May 25, Week 24 Mon=Jun 8, Week 26 Mon=Jun 22
        # Only weeks whose Monday >= Jun 1 should pass
        assert all(date >= current for _, date in result)

    def test_empty_when_all_past(self):
        current = datetime.date(2026, 12, 31)
        result = DefaultShareContentService._get_future_weeks(2026, [1, 2, 3], current)
        assert result == []


# ---------------------------------------------------------------------------
# create_default_share_content
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateDefaultShareContent:
    def test_creates_records_for_week_range(self, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()

        data = {
            "year": 2026,
            "share_article": str(article.pk),
            "share_option": "HARVEST_SHARE",
            "range_1": 15,
            "range_2": 17,
            "unit": "KG",
            "size": "M",
            f"amount_{variation.pk}": "3.5",
        }

        result = DefaultShareContentService.create_default_share_content(data)
        assert len(result) == 3  # weeks 15, 16, 17

        db_count = DefaultShareContent.objects.filter(
            year=2026, share_article=article, unit="KG", size="M"
        ).count()
        assert db_count == 3

    def test_zero_amount_is_dropped_as_scaffold(self, tenant):
        # "0" is scaffold, not a real plan (same as HarvestSharePlanning): no
        # zero-quantity default row is persisted, but a sibling non-zero
        # variation still is.
        article = ShareArticleFactory()
        var_zero = ShareTypeVariationFactory(size="S")
        var_real = ShareTypeVariationFactory(size="M", share_type=var_zero.share_type)
        data = {
            "year": 2026,
            "share_article": str(article.pk),
            "share_option": "HARVEST_SHARE",
            "range_1": 15,
            "range_2": 17,
            "unit": "KG",
            "size": "M",
            f"amount_{var_zero.pk}": "0",
            f"amount_{var_real.pk}": "4",
        }
        DefaultShareContentService.create_default_share_content(data)

        assert not DefaultShareContent.objects.filter(
            share_type_variation=var_zero
        ).exists()
        assert (
            DefaultShareContent.objects.filter(share_type_variation=var_real).count()
            == 3
        )

    def test_raises_on_missing_amounts(self, tenant):
        article = ShareArticleFactory()
        data = {
            "year": 2026,
            "share_article": str(article.pk),
            "share_option": "HARVEST_SHARE",
            "range_1": 15,
            "range_2": 17,
            "unit": "KG",
            "size": "M",
        }
        with pytest.raises(JasminError, match="No share type variation amounts"):
            DefaultShareContentService.create_default_share_content(data)

    def test_raises_on_missing_field(self, tenant):
        data = {"year": 2026, "amount_1": "5"}
        with pytest.raises(JasminError, match="Missing required field"):
            DefaultShareContentService.create_default_share_content(data)

    def test_creates_shares_for_future_weeks(self, tenant):
        """When delivery days and stations exist, Share + ShareContent rows are created."""
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        DeliveryStationDayFactory(delivery_day=delivery_day)

        # Use a far-future year so all weeks are "future"
        data = {
            "year": 2030,
            "share_article": str(article.pk),
            "share_option": "HARVEST_SHARE",
            "range_1": 10,
            "range_2": 10,
            "unit": "KG",
            "size": "M",
            f"amount_{variation.pk}": "2",
        }
        DefaultShareContentService.create_default_share_content(data)

        share = Share.objects.filter(year=2030, delivery_week=10).first()
        assert share is not None
        assert ShareContent.objects.filter(
            share__year=2030, share_article=article
        ).exists()

        # The bulk-create path bypasses ``Share.save()``, so it must default
        # ALL day fields from the delivery day in memory — a NULL one would
        # silently drop the share from that day-filtered list. SHR-2 caught
        # ``get_current_stock_day`` being the one left out.
        assert share.harvesting_day == delivery_day.default_harvesting_day
        assert share.packing_day == delivery_day.default_packing_day
        assert share.washing_day == delivery_day.default_washing_day
        assert share.cleaning_day == delivery_day.default_cleaning_day
        assert share.get_current_stock_day == delivery_day.default_get_current_stock_day


# ---------------------------------------------------------------------------
# get_default_share_content_list  (needed-amount query-count lock)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetDefaultShareContentListQueryCount:
    """The bulk list computes a per-group "needed amount" from active
    subscriptions. Subscriber counts are precomputed ONCE for the page, so the
    query count must not grow with the number of (article/unit/size) groups —
    no per-group, per-variation subscription aggregation."""

    @staticmethod
    def _seed_group(article, variation):
        DefaultShareContentFactory(
            year=2026,
            share_article=article,
            share_type_variation=variation,
            delivery_week=10,
            unit="KG",
            size="M",
            amount=Decimal("2"),
        )

    def test_needed_amount_is_scale_invariant_in_group_count(self, tenant):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # One active subscription on the shared variation so the needed-amount
        # math actually exercises the subscriber count (non-vacuity).
        variation = ShareTypeVariationFactory()
        SubscriptionFactory(
            member=MemberFactory(),
            share_type_variation=variation,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2027, 1, 3),  # Sunday, ~1 year later
            quantity=1,
        )

        for _ in range(2):
            self._seed_group(ShareArticleFactory(), variation)
        with CaptureQueriesContext(connection) as small_ctx:
            small = DefaultShareContentService.get_default_share_content_list(2026)

        for _ in range(6):
            self._seed_group(ShareArticleFactory(), variation)
        with CaptureQueriesContext(connection) as large_ctx:
            large = DefaultShareContentService.get_default_share_content_list(2026)

        # Non-vacuity: groups present and the subscriber-driven needed amount
        # was actually computed (> 0 means the subscription was counted).
        assert len(small) == 2
        assert len(large) == 8
        assert any(Decimal(row["needed_amount"]) > 0 for row in large)

        # The N+1 lock: 4× more groups must NOT add proportional queries.
        delta = len(large_ctx.captured_queries) - len(small_ctx.captured_queries)
        assert delta <= 3, (
            f"needed-amount N+1 suspected: 2 groups -> "
            f"{len(small_ctx.captured_queries)} queries, 8 groups -> "
            f"{len(large_ctx.captured_queries)} queries (delta {delta})."
        )


# ---------------------------------------------------------------------------
# update_default_share_content  (snapshot cascade + recompute on trim)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateDefaultShareContentCascades:
    """Trimming a default-content range deletes future-week ShareContent
    whose MovementShareArticle rows cascade away (FK on_delete=CASCADE). The
    service must cascade stock snapshots for those movements and recompute the
    affected shares — otherwise StockSnapshots / INVENTORY balances go stale
    and an emptied share (no replacement after the trim) is never rebuilt."""

    @patch(
        "apps.commissioning.services.snapshot_service.SnapshotService.cascade_for_movements",
        return_value=0,
    )
    @patch(
        "apps.commissioning.services.recompute.recompute_shares",
        return_value=None,
    )
    def test_deleting_future_share_content_cascades_snapshots_and_recomputes(
        self, mock_recompute, mock_cascade, tenant
    ):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        DeliveryStationDayFactory(delivery_day=delivery_day)

        # A far-future share so the slot week counts as "future" (and is
        # therefore deleted by update_default_share_content).
        share = ShareFactory(
            year=2030,
            delivery_week=10,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share_content = ShareContentFactory(
            share=share,
            share_article=article,
            unit="KG",
            size="M",
            amount=Decimal("5"),
        )
        # A real movement on the slot — this is what the ShareContent .delete()
        # cascades away and what must drive the snapshot cascade afterwards.
        movement = MovementShareArticleFactory(
            share_content=share_content,
            share_article=article,
            unit="KG",
            size="M",
            movement_type="SHARECONTENT",
        )

        DefaultShareContentService.update_default_share_content(
            year=2030,
            share_article_id=str(article.pk),
            validated_data={
                "year": 2030,
                "share_article": str(article.pk),
                "share_option": "HARVEST_SHARE",
                "range_1": 10,
                "range_2": 10,
                "unit": "KG",
                "size": "M",
                f"amount_{variation.pk}": "2",
            },
        )

        # The old slot ShareContent and its movement were removed.
        assert not ShareContent.objects.filter(pk=share_content.pk).exists()
        assert not MovementShareArticle.objects.filter(pk=movement.pk).exists()

        # Snapshots were cascaded for the removed movement — before the fix
        # this was never called and downstream balances went stale.
        mock_cascade.assert_called_once()
        cascaded_movements = mock_cascade.call_args.args[0]
        assert any(moved.pk == movement.pk for moved in cascaded_movements)

        # The emptied share was fed into recompute_shares so a share that loses
        # content with no replacement is rebuilt.
        recomputed_id_sets = [
            set(call.args[0]) for call in mock_recompute.call_args_list
        ]
        assert any(share.pk in ids for ids in recomputed_id_sets)


# ---------------------------------------------------------------------------
# get_default_share_content
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetDefaultShareContent:
    def test_returns_grouped_data(self, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        DefaultShareContentFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            share_type_variation=variation,
            amount=Decimal("3"),
            unit="KG",
            size="M",
        )
        DefaultShareContentFactory(
            year=2026,
            delivery_week=16,
            share_article=article,
            share_type_variation=variation,
            amount=Decimal("3"),
            unit="KG",
            size="M",
        )

        result = DefaultShareContentService.get_default_share_content(
            2026, article.pk, "KG", "M"
        )
        assert result is not None
        assert result["range_1"] == 15
        assert result["range_2"] == 16
        assert f"amount_{variation.pk}" in result

    def test_returns_none_when_empty(self, tenant):
        article = ShareArticleFactory()
        result = DefaultShareContentService.get_default_share_content(
            2026, article.pk, "KG", "M"
        )
        assert result is None

    def test_raises_for_nonexistent_article(self, tenant):
        with pytest.raises(JasminError, match="does not exist"):
            DefaultShareContentService.get_default_share_content(
                2026, 999999, "KG", "M"
            )


# ---------------------------------------------------------------------------
# get_default_share_content_list
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetDefaultShareContentList:
    def test_returns_list_of_groups(self, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        DefaultShareContentFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            share_type_variation=variation,
            unit="KG",
            size="M",
        )

        results = DefaultShareContentService.get_default_share_content_list(year=2026)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# _calculate_needed_amount
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCalculateNeededAmount:
    """needed_amount = Σ (current_subscribers × amount × num_filtered_weeks).

    The snapshot is a single date (``datetime.date.today()``) — subscriber
    counts are assumed constant for the whole timespan.
    """

    def test_returns_zero_for_empty_amounts(self, tenant):
        result = DefaultShareContentService._calculate_needed_amount(
            year=2026,
            range_1=10,
            range_2=12,
            only_odd=False,
            only_even=False,
            only_every_three=False,
            amounts_dict={},
        )
        assert result == "0"

    def test_returns_zero_when_no_weeks_pass_filter(self, tenant):
        from apps.commissioning.tests.factories import SubscriptionFactory

        variation = ShareTypeVariationFactory()
        SubscriptionFactory(share_type_variation=variation)
        # range 10–10 with only_every_three=False, but only_odd on an even
        # single-week range → 0 filtered weeks.
        result = DefaultShareContentService._calculate_needed_amount(
            year=2026,
            range_1=10,
            range_2=10,
            only_odd=True,
            only_even=False,
            only_every_three=False,
            amounts_dict={f"amount_{variation.pk}": "3"},
        )
        assert result == "0"

    def test_multiplies_subscribers_amount_and_filtered_weeks(self, tenant):
        import time_machine

        from apps.commissioning.tests.factories import SubscriptionFactory

        variation = ShareTypeVariationFactory()
        # Share one DeliveryStationDay across the subscriptions —
        # ``SharesDeliveryDayFactory`` uses a fixed ``day_number=2`` and
        # ``SharesDeliveryDay`` is time-bound unique on day_number, so
        # creating multiple via SubFactory triggers an overlap error.
        station_day = DeliveryStationDayFactory()

        for _ in range(3):
            SubscriptionFactory(
                share_type_variation=variation,
                default_delivery_station_day=station_day,
            )

        # Pin "today" to a date after the factory's valid_from (2026-01-05)
        # so the subscriptions are active in the snapshot.
        with time_machine.travel(datetime.date(2026, 6, 1), tick=False):
            result = DefaultShareContentService._calculate_needed_amount(
                year=2026,
                range_1=10,
                range_2=12,  # weeks 10, 11, 12 → 3 weeks unfiltered
                only_odd=False,
                only_even=False,
                only_every_three=False,
                amounts_dict={f"amount_{variation.pk}": "2"},
            )

        # 3 subscribers × 2 KG × 3 weeks = 18
        assert Decimal(result) == Decimal("18.00")

    def test_counts_next_future_cohort_when_none_active_today(self, tenant):
        import time_machine

        from apps.commissioning.tests.factories import SubscriptionFactory

        variation = ShareTypeVariationFactory()
        station_day = DeliveryStationDayFactory()
        # Subscriptions that START in the future (after the pinned "today"), so
        # they are NOT active at the snapshot.
        for _ in range(2):
            SubscriptionFactory(
                share_type_variation=variation,
                default_delivery_station_day=station_day,
                valid_from=datetime.date(2026, 8, 3),
                valid_until=datetime.date(2026, 12, 27),
            )

        # "today" is before the cohort starts → 0 active now → forward-scan picks
        # up the next future cohort (pre-fix this returned 0).
        with time_machine.travel(datetime.date(2026, 6, 1), tick=False):
            result = DefaultShareContentService._calculate_needed_amount(
                year=2026,
                range_1=10,
                range_2=12,  # 3 weeks
                only_odd=False,
                only_even=False,
                only_every_three=False,
                amounts_dict={f"amount_{variation.pk}": "2"},
            )

        # 2 future subscribers × 2 × 3 weeks = 12
        assert Decimal(result) == Decimal("12.00")

    def test_week_filter_reduces_total(self, tenant):
        import time_machine

        from apps.commissioning.tests.factories import SubscriptionFactory

        variation = ShareTypeVariationFactory()
        SubscriptionFactory(share_type_variation=variation)

        with time_machine.travel(datetime.date(2026, 6, 1), tick=False):
            result = DefaultShareContentService._calculate_needed_amount(
                year=2026,
                range_1=10,
                range_2=15,  # 10..15 → 6 weeks; only_even → 10, 12, 14 = 3
                only_odd=False,
                only_even=True,
                only_every_three=False,
                amounts_dict={f"amount_{variation.pk}": "4"},
            )

        # 1 subscriber × 4 × 3 filtered weeks = 12
        assert Decimal(result) == Decimal("12.00")

    def test_sums_across_variations(self, tenant):
        import time_machine

        from apps.commissioning.tests.factories import SubscriptionFactory

        var_s = ShareTypeVariationFactory(size="S")
        var_m = ShareTypeVariationFactory(size="M", share_type=var_s.share_type)
        station_day = DeliveryStationDayFactory()
        SubscriptionFactory(
            share_type_variation=var_s,
            default_delivery_station_day=station_day,
        )
        SubscriptionFactory(
            share_type_variation=var_s,
            default_delivery_station_day=station_day,
        )
        SubscriptionFactory(
            share_type_variation=var_m,
            default_delivery_station_day=station_day,
        )

        with time_machine.travel(datetime.date(2026, 6, 1), tick=False):
            result = DefaultShareContentService._calculate_needed_amount(
                year=2026,
                range_1=10,
                range_2=12,  # 3 weeks
                only_odd=False,
                only_even=False,
                only_every_three=False,
                amounts_dict={
                    f"amount_{var_s.pk}": "1",
                    f"amount_{var_m.pk}": "2",
                },
            )

        # S: 2 subs × 1 × 3 = 6
        # M: 1 sub × 2 × 3 = 6
        # Total: 12
        assert Decimal(result) == Decimal("12.00")


# ---------------------------------------------------------------------------
# delete_default_share_content_bulk
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteDefaultShareContentBulk:
    def test_deletes_by_criteria(self, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        DefaultShareContentFactory(
            year=2026,
            share_article=article,
            share_type_variation=variation,
            unit="KG",
            size="M",
        )
        DefaultShareContentFactory(
            year=2026,
            share_article=article,
            share_type_variation=variation,
            unit="KG",
            size="M",
            delivery_week=16,
        )

        count = DefaultShareContentService.delete_default_share_content_bulk(
            year=2026, share_article=article, unit="KG", size="M"
        )
        assert count == 2
        assert not DefaultShareContent.objects.filter(year=2026).exists()

    def test_returns_zero_for_no_match(self, tenant):
        count = DefaultShareContentService.delete_default_share_content_bulk(year=9999)
        assert count == 0


# ---------------------------------------------------------------------------
# materialize_for_new_station_day
#
# When a new DeliveryStationDay is added (a station starts delivering), the
# existing year-long DefaultShareContent plan must fan out to that station so
# its shares are "theoretically delivered" there too — future weeks only.
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMaterializeForNewStationDay:
    # "now" is frozen here; week 40/2026 is future, week 10/2026 is past.
    NOW = datetime.date(2026, 6, 1)
    FUTURE_WEEK = 40
    PAST_WEEK = 10

    def _plan(self, week: int):
        """A DefaultShareContent row plus the delivery day + new station-day
        to fan it onto. Returns (station_day, variation, article)."""
        delivery_day = SharesDeliveryDayFactory(default_packing_day=2)
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        DefaultShareContentFactory(
            year=2026,
            delivery_week=week,
            share_type_variation=variation,
            share_article=article,
            amount=Decimal("3.000"),
            unit="KG",
            size="M",
        )
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        return station_day, variation, article

    def test_materializes_plan_to_new_station_for_future_week(self, tenant):
        import time_machine

        station_day, variation, article = self._plan(self.FUTURE_WEEK)

        with time_machine.travel(self.NOW, tick=False):
            created = DefaultShareContentService.materialize_for_new_station_day(
                station_day
            )

        assert created == 1
        content = ShareContent.objects.get(
            share__delivery_week=self.FUTURE_WEEK,
            delivery_station=station_day.delivery_station,
        )
        assert content.amount == Decimal("3.000")
        assert content.unit == "KG"
        assert content.share.delivery_day_id == station_day.delivery_day_id
        assert content.share.share_type_variation_id == variation.id
        # The reused/created Share carries its day fields (not NULL), so it
        # surfaces in day-filtered packing lists.
        assert content.share.packing_day == 2

    def test_skips_past_weeks(self, tenant):
        import time_machine

        station_day, _variation, _article = self._plan(self.PAST_WEEK)

        with time_machine.travel(self.NOW, tick=False):
            created = DefaultShareContentService.materialize_for_new_station_day(
                station_day
            )

        assert created == 0
        assert not ShareContent.objects.filter(
            delivery_station=station_day.delivery_station
        ).exists()

    def test_skips_weeks_outside_station_day_validity(self, tenant):
        import time_machine

        delivery_day = SharesDeliveryDayFactory()
        DefaultShareContentFactory(year=2026, delivery_week=self.FUTURE_WEEK)
        # Station-day ends (Monday boundary) well before the future week.
        station_day = DeliveryStationDayFactory(
            delivery_day=delivery_day,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),
        )

        with time_machine.travel(self.NOW, tick=False):
            created = DefaultShareContentService.materialize_for_new_station_day(
                station_day
            )

        assert created == 0

    def test_is_idempotent(self, tenant):
        import time_machine

        station_day, _variation, _article = self._plan(self.FUTURE_WEEK)

        with time_machine.travel(self.NOW, tick=False):
            first = DefaultShareContentService.materialize_for_new_station_day(
                station_day
            )
            DefaultShareContentService.materialize_for_new_station_day(station_day)

        assert first == 1
        # Second run hits the ShareContent unique constraint and inserts
        # nothing new (ignore_conflicts) — no duplicate rows.
        assert (
            ShareContent.objects.filter(
                delivery_station=station_day.delivery_station
            ).count()
            == 1
        )
