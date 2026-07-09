"""Tests for PackingListBoxesMatrixService.

The pure box-combination logic (``_boxes_for_group``) is unit-tested with light
fakes; the full ``get_boxes_matrix`` wiring is exercised against the DB.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.commissioning.errors import PackingAmountsDivergeAcrossStations
from apps.commissioning.services.packing_list_boxes_matrix_service import (
    PackingListBoxesMatrixService,
    _BoxLine,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    MemberFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)


def _line(
    variation_id: str,
    *,
    additional: bool = False,
    quantity: int = 1,
    weight: str | None = None,
    sort_order: int = 0,
) -> _BoxLine:
    share_type = SimpleNamespace(is_additional_share_type=additional)
    variation = SimpleNamespace(
        id=variation_id,
        average_weight=Decimal(weight) if weight is not None else None,
        sort_order=sort_order,
        share_type=share_type,
    )
    return _BoxLine(variation, share_type, quantity)


# ═══════════════════════════════════════════════════════
# Pure combination logic
# ═══════════════════════════════════════════════════════


class TestBoxesForGroup:
    def test_single_base_no_addons(self):
        result = dict(PackingListBoxesMatrixService._boxes_for_group([_line("M")]))
        assert result == {("M", ()): 1}

    def test_base_plus_one_addon(self):
        result = dict(
            PackingListBoxesMatrixService._boxes_for_group(
                [_line("M"), _line("H", additional=True)]
            )
        )
        assert result == {("M", ("H",)): 1}

    def test_base_plus_two_addons_is_one_combination(self):
        # Two add-ons on one base = a single combined box (add-on ids sorted).
        result = dict(
            PackingListBoxesMatrixService._boxes_for_group(
                [
                    _line("M"),
                    _line("H", additional=True),
                    _line("B", additional=True),
                ]
            )
        )
        assert result == {("M", ("B", "H")): 1}

    def test_quantity_gt_one_nests_addons_fullest_first(self):
        # base ×2 + add-on ×1 = one combined box + one base-only box.
        result = dict(
            PackingListBoxesMatrixService._boxes_for_group(
                [_line("M", quantity=2), _line("H", additional=True, quantity=1)]
            )
        )
        assert result == {("M", ("H",)): 1, ("M", ()): 1}

    def test_quantity_matches_addon_quantity(self):
        # base ×2 + add-on ×2 = two identical combined boxes.
        result = dict(
            PackingListBoxesMatrixService._boxes_for_group(
                [_line("M", quantity=2), _line("H", additional=True, quantity=2)]
            )
        )
        assert result == {("M", ("H",)): 2}

    def test_multiple_bases_addon_rides_heaviest(self):
        # Two base boxes; the add-on rides the heavier (average_weight) one.
        result = dict(
            PackingListBoxesMatrixService._boxes_for_group(
                [
                    _line("M", weight="5.0"),
                    _line("S", weight="2.0"),
                    _line("H", additional=True),
                ]
            )
        )
        assert result == {("M", ("H",)): 1, ("S", ()): 1}

    def test_multiple_bases_weight_tie_breaks_on_sort_order(self):
        # Equal (null) weight → the lower sort_order base is primary.
        result = dict(
            PackingListBoxesMatrixService._boxes_for_group(
                [
                    _line("A", sort_order=1),
                    _line("B", sort_order=0),
                    _line("H", additional=True),
                ]
            )
        )
        assert result == {("B", ("H",)): 1, ("A", ()): 1}

    def test_orphan_addons_without_base(self):
        result = dict(
            PackingListBoxesMatrixService._boxes_for_group(
                [_line("H", additional=True, quantity=3)]
            )
        )
        assert result == {(None, ("H",)): 3}

    def test_empty_group(self):
        assert PackingListBoxesMatrixService._boxes_for_group([]) == []

    def test_addon_overflow_spills_to_no_base_box(self):
        # base ×1 + add-on ×2: one combined box + one orphan add-on box (no
        # paid add-on unit is dropped).
        result = dict(
            PackingListBoxesMatrixService._boxes_for_group(
                [_line("M"), _line("H", additional=True, quantity=2)]
            )
        )
        assert result == {("M", ("H",)): 1, (None, ("H",)): 1}

    def test_orphan_addons_nest_fullest_first(self):
        # No base; add-on A ×2, B ×1 → one {A,B} box + one {A} box (B is not
        # over-reported into a second box).
        result = dict(
            PackingListBoxesMatrixService._boxes_for_group(
                [
                    _line("A", additional=True, quantity=2),
                    _line("B", additional=True, quantity=1),
                ]
            )
        )
        assert result == {(None, ("A", "B")): 1, (None, ("A",)): 1}

    def test_same_addon_across_two_lines_aggregates(self):
        # Two separate subscriptions to the SAME add-on = 2 units of one add-on
        # spread one-per-box (not stacked into "(H, H)").
        result = dict(
            PackingListBoxesMatrixService._boxes_for_group(
                [
                    _line("M", quantity=2),
                    _line("H", additional=True, quantity=1),
                    _line("H", additional=True, quantity=1),
                ]
            )
        )
        assert result == {("M", ("H",)): 2}


# ═══════════════════════════════════════════════════════
# Full matrix (DB wiring)
# ═══════════════════════════════════════════════════════

_YEAR = 2026
_WEEK = 15
_DAY = 2


def _base_variation(size="M"):
    return ShareTypeVariationFactory(
        share_type=ShareTypeFactory(
            share_option="HARVEST_SHARE", is_additional_share_type=False
        ),
        size=size,
    )


def _addon_variation(share_option, short_name, size="M"):
    return ShareTypeVariationFactory(
        share_type=ShareTypeFactory(
            share_option=share_option,
            is_additional_share_type=True,
            short_name=short_name,
        ),
        size=size,
    )


def _share(variation, delivery_day):
    return ShareFactory(
        year=_YEAR,
        delivery_week=_WEEK,
        delivery_day=delivery_day,
        share_type_variation=variation,
    )


@pytest.mark.django_db
class TestGetBoxesMatrix:
    def test_base_plus_addon_single_combination(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        member = MemberFactory()

        base_var = _base_variation("M")
        honey_var = _addon_variation("HONEY_SHARE", "HONIG")

        base_share = _share(base_var, delivery_day)
        honey_share = _share(honey_var, delivery_day)

        base_sub = SubscriptionFactory(
            member=member,
            share_type_variation=base_var,
            quantity=1,
            default_delivery_station_day=station_day,
        )
        honey_sub = SubscriptionFactory(
            member=member,
            share_type_variation=honey_var,
            quantity=1,
            default_delivery_station_day=station_day,
        )
        ShareDeliveryFactory(
            share=base_share, delivery_station_day=station_day, subscription=base_sub
        )
        ShareDeliveryFactory(
            share=honey_share, delivery_station_day=station_day, subscription=honey_sub
        )

        carrots = ShareArticleFactory(name="Möhren")
        honey = ShareArticleFactory(name="Honig")
        ShareContentFactory(
            share=base_share,
            share_article=carrots,
            delivery_station=station_day.delivery_station,
            amount=Decimal("3"),
            unit="KG",
            size="M",
        )
        ShareContentFactory(
            share=honey_share,
            share_article=honey,
            delivery_station=station_day.delivery_station,
            amount=Decimal("1"),
            unit="KG",
            size="M",
        )

        result = PackingListBoxesMatrixService.get_boxes_matrix(
            year=_YEAR, delivery_week=_WEEK, day_number=_DAY
        )

        assert len(result["columns"]) == 1
        column = result["columns"][0]
        assert column["base_variation_id"] == base_var.id
        assert column["base_size"] == "M"
        assert column["count"] == 1
        assert [addon["share_type_short_name"] for addon in column["add_ons"]] == [
            "HONIG"
        ]

        key = column["key"]
        rows_by_name = {row["share_article_name"]: row for row in result["rows"]}
        # Base article + add-on article both land in the SAME combined column.
        assert rows_by_name["Möhren"][key] == 3
        assert rows_by_name["Honig"][key] == 1

    def test_two_addons_form_their_own_column(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        member = MemberFactory()

        base_var = _base_variation("M")
        honey_var = _addon_variation("HONEY_SHARE", "HONIG")
        bread_var = _addon_variation("BREAD_SHARE", "BROT", size="L")

        for variation in (base_var, honey_var, bread_var):
            share = _share(variation, delivery_day)
            sub = SubscriptionFactory(
                member=member,
                share_type_variation=variation,
                quantity=1,
                default_delivery_station_day=station_day,
            )
            ShareDeliveryFactory(
                share=share, delivery_station_day=station_day, subscription=sub
            )

        result = PackingListBoxesMatrixService.get_boxes_matrix(
            year=_YEAR, delivery_week=_WEEK, day_number=_DAY
        )

        assert len(result["columns"]) == 1
        column = result["columns"][0]
        assert column["count"] == 1
        assert {addon["share_type_short_name"] for addon in column["add_ons"]} == {
            "HONIG",
            "BROT",
        }

    def test_quantity_two_base_one_addon_splits_into_two_columns(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        member = MemberFactory()

        base_var = _base_variation("M")
        honey_var = _addon_variation("HONEY_SHARE", "HONIG")

        base_share = _share(base_var, delivery_day)
        honey_share = _share(honey_var, delivery_day)
        base_sub = SubscriptionFactory(
            member=member,
            share_type_variation=base_var,
            quantity=2,
            default_delivery_station_day=station_day,
        )
        honey_sub = SubscriptionFactory(
            member=member,
            share_type_variation=honey_var,
            quantity=1,
            default_delivery_station_day=station_day,
        )
        ShareDeliveryFactory(
            share=base_share, delivery_station_day=station_day, subscription=base_sub
        )
        ShareDeliveryFactory(
            share=honey_share, delivery_station_day=station_day, subscription=honey_sub
        )

        result = PackingListBoxesMatrixService.get_boxes_matrix(
            year=_YEAR, delivery_week=_WEEK, day_number=_DAY
        )

        counts = {
            len(column["add_ons"]): column["count"] for column in result["columns"]
        }
        # One combined box (M+Honig) + one base-only box (M).
        assert counts == {1: 1, 0: 1}

    def test_diverging_amounts_across_stations_raise(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day_a = DeliveryStationDayFactory(delivery_day=delivery_day)
        station_day_b = DeliveryStationDayFactory(delivery_day=delivery_day)

        base_var = _base_variation("M")
        base_share = _share(base_var, delivery_day)
        article = ShareArticleFactory(name="Möhren")

        for station_day, amount in (
            (station_day_a, Decimal("3")),
            (station_day_b, Decimal("5")),
        ):
            member = MemberFactory()
            sub = SubscriptionFactory(
                member=member,
                share_type_variation=base_var,
                quantity=1,
                default_delivery_station_day=station_day,
            )
            ShareDeliveryFactory(
                share=base_share, delivery_station_day=station_day, subscription=sub
            )
            ShareContentFactory(
                share=base_share,
                share_article=article,
                delivery_station=station_day.delivery_station,
                amount=amount,
                unit="KG",
                size="M",
            )

        # No station scope → the same (article, variation) has two amounts.
        with pytest.raises(PackingAmountsDivergeAcrossStations):
            PackingListBoxesMatrixService.get_boxes_matrix(
                year=_YEAR, delivery_week=_WEEK, day_number=_DAY
            )

    def test_two_members_same_combination_accumulate_count(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        base_var = _base_variation("M")
        honey_var = _addon_variation("HONEY_SHARE", "HONIG")
        base_share = _share(base_var, delivery_day)
        honey_share = _share(honey_var, delivery_day)

        for _ in range(2):
            member = MemberFactory()
            base_sub = SubscriptionFactory(
                member=member,
                share_type_variation=base_var,
                quantity=1,
                default_delivery_station_day=station_day,
            )
            honey_sub = SubscriptionFactory(
                member=member,
                share_type_variation=honey_var,
                quantity=1,
                default_delivery_station_day=station_day,
            )
            ShareDeliveryFactory(
                share=base_share,
                delivery_station_day=station_day,
                subscription=base_sub,
            )
            ShareDeliveryFactory(
                share=honey_share,
                delivery_station_day=station_day,
                subscription=honey_sub,
            )

        result = PackingListBoxesMatrixService.get_boxes_matrix(
            year=_YEAR, delivery_week=_WEEK, day_number=_DAY
        )

        assert len(result["columns"]) == 1
        assert result["columns"][0]["count"] == 2

    def test_orphan_addon_forms_no_base_column(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        member = MemberFactory()

        honey_var = _addon_variation("HONEY_SHARE", "HONIG")
        honey_share = _share(honey_var, delivery_day)
        honey_sub = SubscriptionFactory(
            member=member,
            share_type_variation=honey_var,
            quantity=1,
            default_delivery_station_day=station_day,
        )
        ShareDeliveryFactory(
            share=honey_share, delivery_station_day=station_day, subscription=honey_sub
        )
        honey = ShareArticleFactory(name="Honig")
        ShareContentFactory(
            share=honey_share,
            share_article=honey,
            delivery_station=station_day.delivery_station,
            amount=Decimal("1"),
            unit="KG",
            size="M",
        )

        result = PackingListBoxesMatrixService.get_boxes_matrix(
            year=_YEAR, delivery_week=_WEEK, day_number=_DAY
        )

        assert len(result["columns"]) == 1
        column = result["columns"][0]
        assert column["base_variation_id"] is None
        assert column["base_share_type_id"] is None
        assert [addon["share_type_short_name"] for addon in column["add_ons"]] == [
            "HONIG"
        ]
        assert column["count"] == 1

    def test_is_packed_bulk_filters_columns(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        base_share_type = ShareTypeFactory(
            share_option="HARVEST_SHARE", is_additional_share_type=False
        )
        boxed_var = ShareTypeVariationFactory(
            share_type=base_share_type, size="M", is_packed_bulk=False
        )
        bulk_var = ShareTypeVariationFactory(
            share_type=base_share_type, size="L", is_packed_bulk=True
        )

        for variation in (boxed_var, bulk_var):
            share = _share(variation, delivery_day)
            member = MemberFactory()
            sub = SubscriptionFactory(
                member=member,
                share_type_variation=variation,
                quantity=1,
                default_delivery_station_day=station_day,
            )
            ShareDeliveryFactory(
                share=share, delivery_station_day=station_day, subscription=sub
            )

        result = PackingListBoxesMatrixService.get_boxes_matrix(
            year=_YEAR, delivery_week=_WEEK, day_number=_DAY, is_packed_bulk=False
        )

        assert len(result["columns"]) == 1
        assert result["columns"][0]["base_variation_id"] == boxed_var.id

    def test_base_and_addon_on_different_dsd_rows_same_station_combine(self, tenant):
        # A member's base and add-on can land on different DeliveryStationDay
        # rows of the SAME station (e.g. across a DSD succession). Grouping by
        # station (not the DSD row) still pairs them into one combination.
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station = DeliveryStationFactory()
        dsd_old = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=delivery_day,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),
        )
        dsd_new = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=delivery_day,
            valid_from=datetime.date(2026, 7, 6),
        )
        member = MemberFactory()

        base_var = _base_variation("M")
        honey_var = _addon_variation("HONEY_SHARE", "HONIG")
        base_share = _share(base_var, delivery_day)
        honey_share = _share(honey_var, delivery_day)
        # Subscriptions cover the queried week and use the covering DSD row.
        base_sub = SubscriptionFactory(
            member=member,
            share_type_variation=base_var,
            quantity=1,
            default_delivery_station_day=dsd_old,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),
        )
        honey_sub = SubscriptionFactory(
            member=member,
            share_type_variation=honey_var,
            quantity=1,
            default_delivery_station_day=dsd_old,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),
        )
        # Base ships on the OLD DSD row, honey on the NEW one — same station,
        # different DeliveryStationDay rows.
        ShareDeliveryFactory(
            share=base_share, delivery_station_day=dsd_old, subscription=base_sub
        )
        ShareDeliveryFactory(
            share=honey_share, delivery_station_day=dsd_new, subscription=honey_sub
        )

        result = PackingListBoxesMatrixService.get_boxes_matrix(
            year=_YEAR, delivery_week=_WEEK, day_number=_DAY
        )

        assert len(result["columns"]) == 1
        column = result["columns"][0]
        assert column["base_variation_id"] == base_var.id
        assert [addon["share_type_short_name"] for addon in column["add_ons"]] == [
            "HONIG"
        ]

    def test_tour_scope_limits_to_tour_stations(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day_t1 = DeliveryStationDayFactory(
            delivery_day=delivery_day, tour_number=1
        )
        station_day_t2 = DeliveryStationDayFactory(
            delivery_day=delivery_day, tour_number=2
        )

        base_var = _base_variation("M")
        base_share = _share(base_var, delivery_day)
        for station_day in (station_day_t1, station_day_t2):
            member = MemberFactory()
            sub = SubscriptionFactory(
                member=member,
                share_type_variation=base_var,
                quantity=1,
                default_delivery_station_day=station_day,
            )
            ShareDeliveryFactory(
                share=base_share, delivery_station_day=station_day, subscription=sub
            )

        # tour=1 → only the tour-1 station's member is counted.
        result = PackingListBoxesMatrixService.get_boxes_matrix(
            year=_YEAR, delivery_week=_WEEK, day_number=_DAY, tour=1
        )

        assert len(result["columns"]) == 1
        assert result["columns"][0]["count"] == 1


@pytest.mark.django_db
class TestGetStationMemberMatrix:
    def test_member_row_carries_their_combination_quantity(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        member = MemberFactory(first_name="Anna", last_name="Müller")

        base_var = _base_variation("M")
        honey_var = _addon_variation("HONEY_SHARE", "HONIG")
        base_share = _share(base_var, delivery_day)
        honey_share = _share(honey_var, delivery_day)
        base_sub = SubscriptionFactory(
            member=member,
            share_type_variation=base_var,
            quantity=1,
            default_delivery_station_day=station_day,
        )
        honey_sub = SubscriptionFactory(
            member=member,
            share_type_variation=honey_var,
            quantity=1,
            default_delivery_station_day=station_day,
        )
        ShareDeliveryFactory(
            share=base_share, delivery_station_day=station_day, subscription=base_sub
        )
        ShareDeliveryFactory(
            share=honey_share, delivery_station_day=station_day, subscription=honey_sub
        )

        result = PackingListBoxesMatrixService.get_station_member_matrix(
            year=_YEAR,
            delivery_week=_WEEK,
            day_number=_DAY,
            delivery_station=station_day.delivery_station_id,
        )

        # One combination column (M + HONIG), one member row.
        assert len(result["columns"]) == 1
        assert len(result["rows"]) == 1
        row = result["rows"][0]
        assert row["name"]  # member name resolved
        key = result["columns"][0]["key"]
        assert row[key] == 1

    def test_two_members_two_rows_shared_columns(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        base_var = _base_variation("M")
        base_share = _share(base_var, delivery_day)

        for _ in range(2):
            member = MemberFactory()
            sub = SubscriptionFactory(
                member=member,
                share_type_variation=base_var,
                quantity=1,
                default_delivery_station_day=station_day,
            )
            ShareDeliveryFactory(
                share=base_share, delivery_station_day=station_day, subscription=sub
            )

        result = PackingListBoxesMatrixService.get_station_member_matrix(
            year=_YEAR,
            delivery_week=_WEEK,
            day_number=_DAY,
            delivery_station=station_day.delivery_station_id,
        )
        assert len(result["columns"]) == 1  # both members share the M column
        assert len(result["rows"]) == 2
        key = result["columns"][0]["key"]
        assert all(row[key] == 1 for row in result["rows"])


@pytest.mark.django_db
class TestGetStationCombinationCounts:
    """Per-STATION box-combination counts for a whole delivery day — the
    DeliveryStations tour overview renders one row per station with these."""

    def test_counts_group_per_station_with_shared_columns(self, tenant):
        delivery_day = SharesDeliveryDayFactory(day_number=_DAY)
        station_day_a = DeliveryStationDayFactory(delivery_day=delivery_day)
        station_day_b = DeliveryStationDayFactory(delivery_day=delivery_day)

        base_var = _base_variation("M")
        honey_var = _addon_variation("HONEY_SHARE", "HONIG")
        base_share = _share(base_var, delivery_day)
        honey_share = _share(honey_var, delivery_day)

        # Station A: member 1 has base + honey (one combined box), member 2 has
        # a base-only box.
        member_1 = MemberFactory()
        m1_base = SubscriptionFactory(
            member=member_1,
            share_type_variation=base_var,
            quantity=1,
            default_delivery_station_day=station_day_a,
        )
        m1_honey = SubscriptionFactory(
            member=member_1,
            share_type_variation=honey_var,
            quantity=1,
            default_delivery_station_day=station_day_a,
        )
        ShareDeliveryFactory(
            share=base_share, delivery_station_day=station_day_a, subscription=m1_base
        )
        ShareDeliveryFactory(
            share=honey_share, delivery_station_day=station_day_a, subscription=m1_honey
        )

        member_2 = MemberFactory()
        m2_base = SubscriptionFactory(
            member=member_2,
            share_type_variation=base_var,
            quantity=1,
            default_delivery_station_day=station_day_a,
        )
        ShareDeliveryFactory(
            share=base_share, delivery_station_day=station_day_a, subscription=m2_base
        )

        # Station B: member 3 has a base-only box.
        member_3 = MemberFactory()
        m3_base = SubscriptionFactory(
            member=member_3,
            share_type_variation=base_var,
            quantity=1,
            default_delivery_station_day=station_day_b,
        )
        ShareDeliveryFactory(
            share=base_share, delivery_station_day=station_day_b, subscription=m3_base
        )

        columns, counts_by_station = (
            PackingListBoxesMatrixService.get_station_combination_counts(
                year=_YEAR, delivery_week=_WEEK, day_number=_DAY
            )
        )

        # Two combinations occur across the day: base+honey and base-only —
        # both stations share these column definitions.
        assert len(columns) == 2
        combo_key = next(c["key"] for c in columns if c["add_ons"])
        base_only_key = next(c["key"] for c in columns if not c["add_ons"])

        station_a = station_day_a.delivery_station_id
        station_b = station_day_b.delivery_station_id
        assert counts_by_station[station_a][combo_key] == 1
        assert counts_by_station[station_a][base_only_key] == 1
        assert counts_by_station[station_b][base_only_key] == 1
        # Station B has no combined box.
        assert combo_key not in counts_by_station[station_b]


@pytest.mark.django_db
class TestGetWeeklyCombinationMatrix:
    """The whole-week AmountShares matrix: one ROW per delivery day (or day ×
    tour / day × station), COLUMNS = the box combinations, cell = box count."""

    def test_days_as_rows_with_combination_counts(self, tenant):
        day1 = SharesDeliveryDayFactory(day_number=0)
        day2 = SharesDeliveryDayFactory(day_number=3)
        station1 = DeliveryStationDayFactory(delivery_day=day1)
        station2 = DeliveryStationDayFactory(delivery_day=day2)

        base_var = _base_variation("M")
        share1 = _share(base_var, day1)
        share2 = _share(base_var, day2)

        # Day 0: two members each take one base box → count 2.
        for _ in range(2):
            member = MemberFactory()
            sub = SubscriptionFactory(
                member=member,
                share_type_variation=base_var,
                quantity=1,
                default_delivery_station_day=station1,
            )
            ShareDeliveryFactory(
                share=share1, delivery_station_day=station1, subscription=sub
            )
        # Day 3: one member takes one base box → count 1.
        member = MemberFactory()
        sub = SubscriptionFactory(
            member=member,
            share_type_variation=base_var,
            quantity=1,
            default_delivery_station_day=station2,
        )
        ShareDeliveryFactory(
            share=share2, delivery_station_day=station2, subscription=sub
        )

        result = PackingListBoxesMatrixService.get_weekly_combination_matrix(
            year=_YEAR, delivery_week=_WEEK, mode="day"
        )

        # One combination column (the plain base box), shared across the week.
        assert len(result["columns"]) == 1
        column_key = result["columns"][0]["key"]

        # Rows are the two delivery days, ordered by day_number, each carrying
        # that day's box count in the shared column.
        rows_by_day = {row["day_number"]: row for row in result["rows"]}
        assert sorted(rows_by_day) == [0, 3]
        assert rows_by_day[0][column_key] == 2
        assert rows_by_day[3][column_key] == 1
        # Day rows are not tour/station scoped.
        assert rows_by_day[0]["tour"] is None
        assert rows_by_day[0]["delivery_station_id"] is None

    def test_stations_mode_splits_rows_per_station(self, tenant):
        day = SharesDeliveryDayFactory(day_number=0)
        station_a = DeliveryStationDayFactory(delivery_day=day)
        station_b = DeliveryStationDayFactory(delivery_day=day)

        base_var = _base_variation("M")
        share = _share(base_var, day)

        for station_day, member_count in ((station_a, 2), (station_b, 1)):
            for _ in range(member_count):
                member = MemberFactory()
                sub = SubscriptionFactory(
                    member=member,
                    share_type_variation=base_var,
                    quantity=1,
                    default_delivery_station_day=station_day,
                )
                ShareDeliveryFactory(
                    share=share,
                    delivery_station_day=station_day,
                    subscription=sub,
                )

        result = PackingListBoxesMatrixService.get_weekly_combination_matrix(
            year=_YEAR, delivery_week=_WEEK, mode="stations"
        )

        column_key = result["columns"][0]["key"]
        rows_by_station = {row["delivery_station_id"]: row for row in result["rows"]}
        assert rows_by_station[station_a.delivery_station_id][column_key] == 2
        assert rows_by_station[station_b.delivery_station_id][column_key] == 1
