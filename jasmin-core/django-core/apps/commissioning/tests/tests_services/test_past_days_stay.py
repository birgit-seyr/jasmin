"""A day before today keeps its harvest, washing and cleaning amounts as they
were planned: a later change of the shares or orders, or a deleted line, leaves
them alone, nothing new is planned onto it, and its additional amounts stay.
Today and the days after it follow the plan.

The shares are delivered on Friday 13 November 2026 (week 46), harvested and
cleaned on Wednesday and washed on Thursday. The plan is made on Tuesday and
changed on Thursday, when Wednesday lies in the past and Thursday is today.
"""

from __future__ import annotations

import datetime
import importlib
from decimal import Decimal
from unittest.mock import patch

import pytest
import time_machine
from django.apps import apps as django_apps
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import (
    AdditionalTheoreticalHarvest,
    Harvest,
    MovementShareArticle,
    OrderContent,
    Share,
    ShareContent,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalWashAmount,
)
from apps.commissioning.services.documentation_service import (
    GenericDocumentationService,
)
from apps.commissioning.services.documentation_summary_service import (
    DocumentationSummaryService,
)
from apps.commissioning.services.order_content_service import OrderContentService
from apps.commissioning.services.planning_slots import PlanningSlot
from apps.commissioning.services.share_content_service import ShareContentService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ForecastFactory,
    OfferFactory,
    ResellerFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
)

TUESDAY = datetime.datetime(2026, 11, 10, 12, 0)
THURSDAY = datetime.datetime(2026, 11, 12, 12, 0)
WEEK = 46
WEDNESDAY_NUMBER = 2
THURSDAY_NUMBER = 3


@pytest.fixture(autouse=True)
def _freeze_clock():
    # Planned on Tuesday; each test moves on to Thursday where it says so.
    with time_machine.travel(TUESDAY, tick=False):
        yield


def _on_thursday():
    return time_machine.travel(THURSDAY, tick=False)


def _three_shares_of(share_content):
    """Three subscribers of the line's share at its station, whatever the
    subscriptions say."""
    share = share_content.share
    totals = {
        "basic": {(share.delivery_day_id, share.share_type_variation_id): Decimal(3)},
        "tour": {},
        "station": {
            (
                share.delivery_day_id,
                share.share_type_variation_id,
                share_content.delivery_station_id,
            ): Decimal(3)
        },
    }
    return patch(
        "apps.commissioning.services.share_content_stock"
        ".batch_get_physical_variation_totals_for_weeks",
        side_effect=lambda physical_variations, year, weeks: {
            week: totals for week in weeks
        },
    )


def _share_content(day=None, year=2026, week=WEEK, **fields):
    """A line of a share, for 5 kg a share: by default delivered on Friday of
    week 46, harvested and cleaned on Wednesday and washed on Thursday."""
    StorageFactory(is_short_term_harvest_storage=True)
    article = ShareArticleFactory()
    day = day or SharesDeliveryDayFactory(
        day_number=4,
        default_harvesting_day=WEDNESDAY_NUMBER,
        default_washing_day=THURSDAY_NUMBER,
        default_cleaning_day=WEDNESDAY_NUMBER,
    )
    share = ShareFactory(
        year=year,
        delivery_week=week,
        delivery_day=day,
        share_type_variation=ShareTypeVariationFactory(),
    )
    station = DeliveryStationFactory()
    DeliveryStationDayFactory(delivery_station=station, delivery_day=day)
    forecast = ForecastFactory(
        share_article=article, year=year, delivery_week=week, size="M"
    )
    return ShareContentFactory(
        share=share,
        share_article=article,
        delivery_station=station,
        forecast=forecast,
        amount=Decimal("5"),
        unit="KG",
        size="M",
        **fields,
    )


def _plan(share_content):
    with _three_shares_of(share_content):
        ShareContentService().recompute_for_shares([share_content.share_id])


def _change_amount(share_content, amount):
    ShareContent.objects.filter(pk=share_content.pk).update(amount=amount)
    _plan(share_content)


@pytest.mark.django_db
class TestPlanChangedAfterTheDay:
    def test_a_past_harvest_keeps_its_amount(self, tenant):
        line = _share_content()
        _plan(line)
        planned = TheoreticalHarvest.objects.get(share_content=line)
        assert planned.amount == Decimal("15")

        with _on_thursday():
            _change_amount(line, Decimal("2"))

        kept = TheoreticalHarvest.objects.get(share_content=line)
        assert (kept.pk, kept.amount) == (planned.pk, Decimal("15"))
        assert MovementShareArticle.objects.get(
            theoretical_harvest=kept
        ).amount == Decimal("15")

    def test_todays_washing_follows_the_plan(self, tenant):
        line = _share_content(washing=True)
        _plan(line)

        with _on_thursday():
            _change_amount(line, Decimal("2"))

        assert TheoreticalWashAmount.objects.get(share_content=line).amount == Decimal(
            "6"
        )

    def test_a_past_cleaning_keeps_its_amount(self, tenant):
        line = _share_content(cleaning=True)
        _plan(line)

        with _on_thursday():
            _change_amount(line, Decimal("2"))

        assert TheoreticalCleanAmount.objects.get(share_content=line).amount == Decimal(
            "15"
        )

    def test_nothing_is_planned_onto_a_past_day(self, tenant):
        with _on_thursday():
            line = _share_content(washing=True)
            _plan(line)

        assert not TheoreticalHarvest.objects.filter(share_content=line).exists()
        assert not Harvest.objects.filter(
            share_article=line.share_article, day_number=WEDNESDAY_NUMBER
        ).exists()
        assert TheoreticalWashAmount.objects.filter(share_content=line).exists()

    def test_the_entered_harvest_stays_the_stock_after_the_plan_is_lowered(
        self, tenant
    ):
        line = _share_content()
        _plan(line)
        harvest = Harvest.objects.get(
            share_article=line.share_article, day_number=WEDNESDAY_NUMBER
        )
        with time_machine.travel(datetime.datetime(2026, 11, 11, 16, 0), tick=False):
            harvest.amount = Decimal("12")
            harvest.save()
            GenericDocumentationService._upsert_movement(harvest)

        with _on_thursday():
            _change_amount(line, Decimal("2"))

        wednesday = MovementShareArticle.objects.filter(
            movement_type="HARVEST", share_article=line.share_article
        )
        assert sum(movement.amount for movement in wednesday) == Decimal("12")

    def test_a_harvest_moved_into_the_past_is_planned_nowhere(self, tenant):
        line = _share_content()
        line.share.harvesting_day = 4
        line.share.save(update_fields=["harvesting_day"])
        _plan(line)
        assert TheoreticalHarvest.objects.get(share_content=line).day_number == 4

        with _on_thursday():
            line.share.harvesting_day = WEDNESDAY_NUMBER
            line.share.save(update_fields=["harvesting_day"])
            _plan(line)

        assert not TheoreticalHarvest.objects.filter(share_content=line).exists()

    def test_the_last_days_of_the_year_are_past_in_the_new_one(self, tenant):
        # Delivered on Monday of week 1 of 2027; harvested on Thursday and
        # washed on Saturday of the week before, week 53 of 2026.
        day = SharesDeliveryDayFactory(
            day_number=0,
            default_harvesting_day=THURSDAY_NUMBER,
            default_washing_day=5,
            default_cleaning_day=THURSDAY_NUMBER,
        )
        with time_machine.travel(datetime.datetime(2026, 12, 30, 12, 0), tick=False):
            line = _share_content(day=day, year=2027, week=1, washing=True)
            _plan(line)
        harvest = TheoreticalHarvest.objects.get(share_content=line)
        assert (harvest.year, harvest.delivery_week) == (2026, 53)

        with time_machine.travel(datetime.datetime(2027, 1, 1, 12, 0), tick=False):
            _change_amount(line, Decimal("2"))

        assert TheoreticalHarvest.objects.get(share_content=line).amount == Decimal(
            "15"
        )
        assert TheoreticalWashAmount.objects.get(share_content=line).amount == Decimal(
            "6"
        )

    def test_a_harvest_moved_after_its_day_is_not_planned_twice(self, tenant):
        line = _share_content()
        _plan(line)

        with _on_thursday():
            line.share.harvesting_day = 4
            line.share.save(update_fields=["harvesting_day"])
            _plan(line)

        harvests = TheoreticalHarvest.objects.filter(share_content=line)
        assert [harvest.day_number for harvest in harvests] == [WEDNESDAY_NUMBER]


@pytest.mark.django_db
class TestLineDeletedAfterTheDay:
    def test_a_past_harvest_stays_without_its_line(self, tenant):
        line = _share_content(washing=True)
        _plan(line)
        planned = TheoreticalHarvest.objects.get(share_content=line)

        with _on_thursday():
            line.delete()

        kept = TheoreticalHarvest.objects.get(pk=planned.pk)
        assert (kept.share_content_id, kept.amount) == (None, Decimal("15"))
        assert MovementShareArticle.objects.filter(theoretical_harvest=kept).exists()
        assert not TheoreticalWashAmount.objects.filter(
            share_article=line.share_article
        ).exists()
        # Still the shares' amount on the day's harvesting list.
        sums = DocumentationSummaryService._calculate_sums([kept], [], "harvest")
        assert sums[2:4] == (Decimal("15"), 0)

    def test_a_line_replaced_after_its_day_is_not_harvested_twice(self, tenant):
        line = _share_content()
        _plan(line)
        planned = TheoreticalHarvest.objects.get(share_content=line)

        with _on_thursday():
            share, article, station = (
                line.share,
                line.share_article,
                line.delivery_station,
            )
            forecast = line.forecast
            line.delete()
            again = ShareContentFactory(
                share=share,
                share_article=article,
                delivery_station=station,
                forecast=forecast,
                amount=Decimal("2"),
                unit="KG",
                size="M",
            )
            _plan(again)

        harvests = TheoreticalHarvest.objects.filter(share_article=article)
        assert [(h.pk, h.amount) for h in harvests] == [(planned.pk, Decimal("15"))]

    def test_a_planning_save_after_the_day_keeps_the_harvest(self, tenant):
        line = _share_content()
        _plan(line)
        planned = TheoreticalHarvest.objects.get(share_content=line)
        cell = (
            f"day_{line.share.delivery_day_id}"
            f"_variation_{line.share.share_type_variation_id}"
        )

        with _on_thursday(), _three_shares_of(line):
            ShareContentService().replace_share_planning(
                slot=PlanningSlot(
                    year=2026,
                    delivery_week=WEEK,
                    share_article_id=str(line.share_article_id),
                    unit="KG",
                    size="M",
                ),
                data={"year": 2026, "delivery_week": WEEK, cell: "2"},
            )

        harvests = TheoreticalHarvest.objects.filter(share_article=line.share_article)
        assert [(h.pk, h.amount) for h in harvests] == [(planned.pk, Decimal("15"))]

    def test_a_share_deleted_in_bulk_after_its_day_keeps_the_harvest(self, tenant):
        line = _share_content()
        _plan(line)

        with _on_thursday():
            Share.objects.filter(pk=line.share_id).delete()

        kept = TheoreticalHarvest.objects.get(share_article=line.share_article)
        assert kept.amount == Decimal("15")

    def test_a_forecast_deleted_after_its_day_keeps_the_harvest(
        self, api_client, tenant
    ):
        line = _share_content()
        _plan(line)

        with _on_thursday():
            resp = api_client.delete(
                reverse("forecast-detail", kwargs={"pk": line.forecast_id})
            )

        assert resp.status_code == status.HTTP_204_NO_CONTENT, resp.content
        kept = TheoreticalHarvest.objects.get(share_article=line.share_article)
        assert (kept.forecast_id, kept.share_content_id) == (None, None)
        assert kept.amount == Decimal("15")
        assert MovementShareArticle.objects.get(
            theoretical_harvest=kept
        ).amount == Decimal("15")

    def test_a_line_deleted_before_its_day_takes_its_amounts_along(self, tenant):
        line = _share_content(washing=True)
        _plan(line)

        line.delete()

        article = line.share_article
        assert not TheoreticalHarvest.objects.filter(share_article=article).exists()
        assert not TheoreticalWashAmount.objects.filter(share_article=article).exists()


def _order_line():
    """10 kg ordered for Wednesday, planned on Monday."""
    storage = StorageFactory(is_short_term_harvest_storage=True)
    article = ShareArticleFactory()
    ForecastFactory(
        share_article=article,
        year=2026,
        delivery_week=WEEK,
        size="M",
        storage=storage,
    )
    offer = OfferFactory(share_article=article, amount=Decimal("100"))
    with time_machine.travel(datetime.datetime(2026, 11, 9, 8, 0), tick=False):
        result = OrderContentService.create_order_with_content_and_crates(
            reseller=ResellerFactory(),
            year=2026,
            delivery_week=WEEK,
            day_number=WEDNESDAY_NUMBER,
            offer=offer,
            amount=Decimal("10"),
        )
    return OrderContent.objects.get(pk=result["id"])


@pytest.mark.django_db
class TestOrderChangedAfterTheDay:
    def test_a_past_harvest_of_an_order_keeps_its_amount(self, tenant):
        line = _order_line()
        planned = TheoreticalHarvest.objects.get(order_content=line)

        with _on_thursday():
            OrderContentService.update_order_content(line.pk, Decimal("4"))

        kept = TheoreticalHarvest.objects.get(order_content=line)
        assert (kept.pk, kept.amount) == (planned.pk, Decimal("10"))

    def test_a_past_harvest_stays_the_orders_without_its_line(self, tenant):
        line = _order_line()
        planned = TheoreticalHarvest.objects.get(order_content=line)

        with _on_thursday():
            line.delete()

        kept = TheoreticalHarvest.objects.get(pk=planned.pk)
        assert (kept.order_content_id, kept.for_order_content) == (None, True)
        sums = DocumentationSummaryService._calculate_sums([kept], [], "harvest")
        assert sums[2:4] == (0, Decimal("10"))


@pytest.mark.django_db
class TestMarkingOrderHarvests:
    def test_the_migration_marks_the_harvests_of_order_lines(self, tenant):
        migration = importlib.import_module(
            "apps.commissioning.migrations.0040_past_theoretical_amounts_stay"
        )
        line = _order_line()
        TheoreticalHarvest.objects.update(for_order_content=False)

        migration.mark_order_harvests(django_apps, None)

        assert TheoreticalHarvest.objects.get(order_content=line).for_order_content


def _additional_harvest(api_client, day_number, shares_amount, **fields):
    """An additional harvest for the shares, or with ``model`` and ``amount``
    an additional amount of another kind."""
    article = fields.pop("article", None) or ShareArticleFactory()
    return api_client.post(
        reverse("documentation_summary-add-additional-theoretical-amount"),
        {
            "model": "harvest",
            "year": 2026,
            "delivery_week": WEEK,
            "day_number": day_number,
            "share_article": article.pk,
            "unit": "KG",
            "size": "M",
            "amount_share_content": shares_amount,
            "amount_order_content": 0,
            **fields,
        },
        format="json",
    )


@pytest.mark.django_db
class TestAdditionalAmountsOfAPastDay:
    @pytest.fixture(autouse=True)
    def _thursday(self, tenant):
        StorageFactory(is_short_term_harvest_storage=True)
        with _on_thursday():
            yield

    def test_refuses_an_additional_harvest_on_a_past_day(self, api_client, tenant):
        article = ShareArticleFactory()
        resp = _additional_harvest(api_client, WEDNESDAY_NUMBER, 3, article=article)

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.content
        assert resp.json()["code"] == "documentation.past_day_additional_amount"
        assert not AdditionalTheoreticalHarvest.objects.filter(
            share_article=article
        ).exists()

    def test_refuses_an_additional_washing_on_a_past_day(self, api_client, tenant):
        resp = _additional_harvest(
            api_client, WEDNESDAY_NUMBER, 0, model="washamount", amount=3
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.content
        assert resp.json()["code"] == "documentation.past_day_additional_amount"

    def test_takes_an_additional_purchase_whatever_the_day(self, api_client, tenant):
        # A purchase sits on Tuesday of the delivery week, before today.
        resp = _additional_harvest(
            api_client, WEDNESDAY_NUMBER, 0, model="purchase", amount=3
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.content

    def test_takes_an_additional_harvest_today(self, api_client, tenant):
        resp = _additional_harvest(api_client, THURSDAY_NUMBER, 3)

        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        assert AdditionalTheoreticalHarvest.objects.filter(
            day_number=THURSDAY_NUMBER, amount=Decimal("3")
        ).exists()

    def test_a_past_days_row_still_takes_its_other_fields(self, api_client, tenant):
        article = ShareArticleFactory()
        with time_machine.travel(TUESDAY, tick=False):
            created = _additional_harvest(
                api_client, WEDNESDAY_NUMBER, 3, article=article
            )
        assert created.status_code == status.HTTP_201_CREATED, created.content
        row = Harvest.objects.get(share_article=article)
        url = reverse(
            "documentation_summary-update-additional-theoretical-amount",
            kwargs={"pk": row.pk},
        )

        unchanged = api_client.patch(
            url,
            {
                "model": "harvest",
                "amount_share_content": 3,
                "amount_order_content": 0,
                "amount_per_pu": "2.5",
            },
            format="json",
        )
        changed = api_client.patch(
            url,
            {"model": "harvest", "amount_share_content": 5},
            format="json",
        )

        assert unchanged.status_code == status.HTTP_200_OK, unchanged.content
        row.refresh_from_db()
        assert row.amount_per_pu == Decimal("2.5")
        assert changed.status_code == status.HTTP_409_CONFLICT, changed.content
        assert AdditionalTheoreticalHarvest.objects.get(
            share_article=article, for_share_content=True
        ).amount == Decimal("3")
