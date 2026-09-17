"""GiST exclusion constraints on the TimeBoundMixin subclasses.

``TimeBoundMixin._validate_no_overlap`` runs from ``clean()`` only, so it is
TOCTOU-racy (two concurrent saves can both pass ``full_clean()``) and absent
altogether from ``bulk_create`` / ``bulk_update`` / ``QuerySet.update()`` / raw
SQL. Each model below carries a ``<model>_no_overlap`` exclusion constraint as
the DB backstop.

Every group is asserted three ways, because no single one of them pins the
boundary:

  * a genuinely overlapping window is rejected;
  * an ADJACENT window (one starts the day after the other ends) is ACCEPTED —
    succession creates back-to-back rows constantly (``handle_succession``
    closes a predecessor on ``new_valid_from - 1 day``), so a range that
    rejected these would reject legal data; and
  * two windows that TOUCH on a single shared day are rejected. This is the
    pair that pins the bounds as inclusive: an adjacent pair is non-overlapping
    under ``'[]'`` and ``'[)'`` alike, so only a touching pair tells
    ``daterange(…, '[]')`` apart from a ``'[)'`` / ``'(]'`` mistake.

The writes go through ``bulk_create``, which bypasses ``full_clean()`` — so an
``IntegrityError`` here proves the DB layer holds, not the Python one. The
expected constraint name is asserted as well: several of these models also
carry a one-open-row partial unique, and without the name a test could pass on
the wrong constraint.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.db import IntegrityError, transaction

from apps.commissioning.models import (
    ConsentDocument,
    ConsentKind,
    CrateNetPrice,
    DeliveryExceptionPeriod,
    DeliveryStationDay,
    OrganicCertificate,
    Season,
    ShareArticleNetPrice,
    SharesDeliveryDay,
    ShareType,
    ShareTypeVariation,
)
from apps.commissioning.tests.factories import (
    CrateFactory,
    DeliveryStationFactory,
    ResellerFactory,
    ShareArticleFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
)

_FIRST_FROM = datetime.date(2026, 1, 5)  # Monday
_FIRST_UNTIL = datetime.date(2026, 3, 29)  # Sunday
_OVERLAP_FROM = datetime.date(2026, 3, 2)  # Monday inside the first window
_ADJACENT_FROM = datetime.date(2026, 3, 30)  # Monday, the day after it ends
_EARLIER_FROM = datetime.date(2025, 10, 6)  # Monday well before the first window


@pytest.fixture(autouse=True)
def _freeze_clock():
    # The windows are fixed calendar dates; pin the clock to the Monday they
    # start on so nothing in the create paths can read a moving "now".
    with time_machine.travel(datetime.datetime(2026, 1, 5, 12, 0), tick=False):
        yield


# Each builder creates the group's parent rows and returns the constraint that
# guards the group plus a callable making an UNSAVED row in it.


def _delivery_exception_period():
    variation = ShareTypeVariationFactory(size="M")
    return "deliveryexceptionperiod_no_overlap", (
        lambda valid_from, valid_until: DeliveryExceptionPeriod(
            share_type_variation=variation,
            valid_from=valid_from,
            valid_until=valid_until,
        )
    )


def _organic_certificate():
    reseller = ResellerFactory()
    return "organiccertificate_no_overlap", (
        lambda valid_from, valid_until: OrganicCertificate(
            reseller=reseller,
            certificate_number=f"CERT-{valid_from}",
            valid_from=valid_from,
            valid_until=valid_until,
        )
    )


def _share_article_net_price():
    share_article = ShareArticleFactory()
    return "sharearticlenetprice_no_overlap", (
        lambda valid_from, valid_until: ShareArticleNetPrice(
            share_article=share_article,
            tax_rate=Decimal("7.00"),
            net_price_for_boxes_kg=Decimal("1.50"),
            valid_from=valid_from,
            valid_until=valid_until,
        )
    )


def _crate_net_price():
    crate = CrateFactory()
    return "cratenetprice_no_overlap", (
        lambda valid_from, valid_until: CrateNetPrice(
            crate=crate,
            price=Decimal("2.50"),
            tax_rate=Decimal("19.00"),
            valid_from=valid_from,
            valid_until=valid_until,
        )
    )


def _consent_document():
    # (kind, version, locale) is unique, so each row gets its own version.
    return "consentdocument_no_overlap", (
        lambda valid_from, valid_until: ConsentDocument(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version=f"v-{valid_from}",
            body="Policy text",
            valid_from=valid_from,
            valid_until=valid_until,
        )
    )


def _shares_delivery_day():
    return "sharesdeliveryday_no_overlap", (
        lambda valid_from, valid_until: SharesDeliveryDay(
            day_number=3,
            name="Thursday",
            number_of_tours=1,
            valid_from=valid_from,
            valid_until=valid_until,
        )
    )


def _delivery_station_day():
    delivery_station = DeliveryStationFactory()
    delivery_day = SharesDeliveryDayFactory()
    return "deliverystationday_no_overlap", (
        lambda valid_from, valid_until: DeliveryStationDay(
            delivery_station=delivery_station,
            delivery_day=delivery_day,
            tour_number=1,
            valid_from=valid_from,
            valid_until=valid_until,
        )
    )


def _share_type():
    return "sharetype_no_overlap", (
        lambda valid_from, valid_until: ShareType(
            share_option="HARVEST_SHARE",
            name=f"Harvest share from {valid_from}",
            delivery_cycle="WEEKLY",
            valid_from=valid_from,
            valid_until=valid_until,
        )
    )


def _share_type_variation():
    share_type = ShareTypeFactory()
    return "sharetypevariation_no_overlap", (
        lambda valid_from, valid_until: ShareTypeVariation(
            share_type=share_type,
            size="M",
            variation_type=ShareTypeVariation.VariationType.PHYSICAL,
            valid_from=valid_from,
            valid_until=valid_until,
        )
    )


def _season():
    # Global group (``overlap_unique_fields = ()``): every season is in the
    # same group, so two rows need no parent or shared key to collide. The
    # one-open-season partial unique from migration 0015 covers only OPEN
    # rows; this constraint is what catches two overlapping CLOSED ones.
    return "season_no_overlap", (
        lambda valid_from, valid_until: Season(
            valid_from=valid_from,
            valid_until=valid_until,
        )
    )


_OVERLAP_GROUPS = [
    pytest.param(_delivery_exception_period, id="deliveryexceptionperiod"),
    pytest.param(_organic_certificate, id="organiccertificate"),
    pytest.param(_share_article_net_price, id="sharearticlenetprice"),
    pytest.param(_crate_net_price, id="cratenetprice"),
    pytest.param(_consent_document, id="consentdocument"),
    pytest.param(_shares_delivery_day, id="sharesdeliveryday"),
    pytest.param(_delivery_station_day, id="deliverystationday"),
    pytest.param(_share_type, id="sharetype"),
    pytest.param(_share_type_variation, id="sharetypevariation"),
    pytest.param(_season, id="season"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("build_group", _OVERLAP_GROUPS)
class TestTimeBoundOverlapExclusions:
    def test_overlapping_window_rejected_by_db(self, build_group, tenant):
        constraint_name, build_row = build_group()
        build_row(_FIRST_FROM, _FIRST_UNTIL).save()

        # Starts inside the closed window above and runs open-ended. Only the
        # second row is open, so the one-open partial uniques are satisfied and
        # the exclusion constraint is what rejects this.
        overlapping = build_row(_OVERLAP_FROM, None)

        with pytest.raises(IntegrityError, match=constraint_name), transaction.atomic():
            type(overlapping).objects.bulk_create([overlapping])

    def test_window_overlapping_an_open_ended_row_rejected_by_db(
        self, build_group, tenant
    ):
        constraint_name, build_row = build_group()
        build_row(_FIRST_FROM, None).save()

        # A NULL valid_until is an unbounded upper bound, so a later closed
        # window still falls inside it.
        overlapping = build_row(_OVERLAP_FROM, _FIRST_UNTIL)

        with pytest.raises(IntegrityError, match=constraint_name), transaction.atomic():
            type(overlapping).objects.bulk_create([overlapping])

    def test_window_starting_on_the_predecessors_last_day_rejected(
        self, build_group, tenant
    ):
        constraint_name, build_row = build_group()
        build_row(_FIRST_FROM, _FIRST_UNTIL).save()

        # Shares exactly one day — the predecessor's ``valid_until`` — with the
        # row above. Rejected only because the UPPER bound is inclusive: under
        # ``'[)'`` this same pair would be accepted.
        touching = build_row(_FIRST_UNTIL, None)

        with pytest.raises(IntegrityError, match=constraint_name), transaction.atomic():
            type(touching).objects.bulk_create([touching])

    def test_window_ending_on_the_successors_first_day_rejected(
        self, build_group, tenant
    ):
        constraint_name, build_row = build_group()
        build_row(_FIRST_FROM, None).save()

        # Shares exactly ``_FIRST_FROM`` with the open row above. Rejected only
        # because the LOWER bound is inclusive.
        touching = build_row(_EARLIER_FROM, _FIRST_FROM)

        with pytest.raises(IntegrityError, match=constraint_name), transaction.atomic():
            type(touching).objects.bulk_create([touching])

    def test_adjacent_window_allowed(self, build_group, tenant):
        _, build_row = build_group()
        build_row(_FIRST_FROM, _FIRST_UNTIL).save()

        # Succession shape: the successor starts the day after the predecessor
        # ends. Inclusive bounds on both sides, so these do NOT overlap.
        adjacent = build_row(_ADJACENT_FROM, None)
        type(adjacent).objects.bulk_create([adjacent])

        assert type(adjacent).objects.filter(pk=adjacent.pk).exists()
