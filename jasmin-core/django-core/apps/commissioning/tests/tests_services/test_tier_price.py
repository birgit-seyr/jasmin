"""The server's tier picker prices a customer's order line the way the browser
prices the office's.

Both pickers are tested against one table of cases kept beside the frontend's
tests (``tierPriceCases.json``): the browser's ``pickTierPrice`` and
``pickTierPriceFromAmount`` in vitest, their Python ports here. A case changed
for one side fails the other until both agree again.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.utils import timezone

from apps.commissioning.constants import get_offer_price_tiers
from apps.commissioning.models import Offer, OrderContent
from apps.commissioning.services.tier_price import (
    TierPrices,
    offer_tier_price,
    pick_tier_price,
    pick_tier_price_from_amount,
    set_customer_line_price,
)
from apps.shared.tenants.models import TenantSettings

# This file lives at apps/commissioning/tests/tests_services/<file>, so
# django-core is four up.
DJANGO_CORE = Path(__file__).resolve().parents[4]
REACT_SRC = DJANGO_CORE.parent / "react-core" / "src"
CASES_FILE = REACT_SRC / "shared" / "utils" / "__tests__" / "tierPriceCases.json"


def _load_cases() -> dict[str, list[dict[str, Any]]]:
    """The shared table, or nothing where the frontend source isn't checked out
    (the dev backend container mounts only parts of react-core).
    ``test_the_case_table_is_there`` fails when it is checked out but the table
    has gone."""
    if not CASES_FILE.exists():
        return {}
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))


CASES = _load_cases()


def _decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _prices(row: dict[str, Any]) -> TierPrices:
    return TierPrices(**{key: _decimal(value) for key, value in row["prices"].items()})


def _case_id(row: dict[str, Any]) -> str:
    return row["case"]


def test_the_case_table_is_there():
    if not (REACT_SRC / "app").is_dir():
        pytest.skip("the frontend source isn't checked out here")
    assert CASES.get("pick_tier_price") and CASES.get("pick_tier_price_from_amount"), (
        f"{CASES_FILE} is gone or empty. Point CASES_FILE at the table the "
        "frontend's tierPrice tests read now, so both pickers stay pinned to it."
    )


@pytest.mark.parametrize("row", CASES.get("pick_tier_price", []), ids=_case_id)
def test_pick_tier_price_matches_the_browser(row):
    price = pick_tier_price(_decimal(row["pu_count"]), _prices(row), row["tiers"])

    assert price == Decimal(row["expected"])


@pytest.mark.parametrize(
    "row", CASES.get("pick_tier_price_from_amount", []), ids=_case_id
)
def test_pick_tier_price_from_amount_matches_the_browser(row):
    price = pick_tier_price_from_amount(
        _decimal(row["amount"]),
        _decimal(row["amount_per_pu"]),
        _prices(row),
        row["tiers"],
    )

    assert price == Decimal(row["expected"])


PRICES = TierPrices(Decimal("2.00"), Decimal("1.80"), Decimal("1.60"))


class TestPickTierPriceOnTheServer:
    def test_the_pu_count_of_an_amount_is_exact(self):
        """The customer order page sends ``n × amount_per_pu`` to three
        decimals for n PU; dividing it back in Decimal gives exactly n, also for
        a PU size without an exact binary form."""
        price = pick_tier_price_from_amount(
            Decimal("2.001"), Decimal("0.667"), PRICES, [1, 3, 5]
        )

        assert price == Decimal("1.80")

    @pytest.mark.parametrize("entry", ["5", True, {"from": 5}])
    def test_a_threshold_that_is_no_number_is_never_reached(self, entry):
        """The settings validator refuses such entries; a row stored before it
        must still price, at the price below that tier."""
        assert pick_tier_price(Decimal("100"), PRICES, [1, entry]) == Decimal("2.00")
        assert pick_tier_price(Decimal("100"), PRICES, [1, 5, entry]) == Decimal("1.80")


def _set_tiers(tenant, tiers) -> None:
    settings, _ = TenantSettings.objects.get_or_create(
        tenant=tenant,
        valid_until=None,
        defaults={"valid_from": timezone.now() - datetime.timedelta(days=365)},
    )
    settings.used_tiers_for_offers = tiers
    settings.save()


@pytest.mark.django_db
class TestOfferPriceTiers:
    def test_a_tenant_without_settings_has_the_single_tier(self, tenant):
        TenantSettings.objects.filter(tenant=tenant).delete()

        assert get_offer_price_tiers() == [1]

    @pytest.mark.parametrize("stored", [None, [], "1,5,10"])
    def test_no_tiers_set_is_the_single_tier(self, tenant, stored):
        _set_tiers(tenant, stored)

        assert get_offer_price_tiers() == [1]

    def test_the_tenants_tiers(self, tenant):
        _set_tiers(tenant, [1, 5, 10])

        assert get_offer_price_tiers() == [1, 5, 10]


def _offer(**prices: str) -> Offer:
    """An unsaved offer of 2 kg per PU: pricing reads only these fields."""
    return Offer(
        amount_per_pu=Decimal("2.000"),
        **{key: Decimal(value) for key, value in prices.items()},
    )


OFFER_PRICES = {"price_1": "2.00", "price_2": "1.80", "price_3": "1.60"}


@pytest.mark.django_db
class TestOfferTierPrice:
    def test_the_tenants_tiers_price_the_offers_pu(self, tenant):
        _set_tiers(tenant, [1, 5, 10])
        offer = _offer(**OFFER_PRICES)

        assert offer_tier_price(offer, Decimal("8.000")) == Decimal("2.00")
        assert offer_tier_price(offer, Decimal("10.000")) == Decimal("1.80")
        assert offer_tier_price(offer, Decimal("20.000")) == Decimal("1.60")

    def test_without_tiers_every_amount_takes_the_base_price(self, tenant):
        _set_tiers(tenant, [])

        assert offer_tier_price(_offer(**OFFER_PRICES), Decimal("200.000")) == Decimal(
            "2.00"
        )


@pytest.mark.django_db
class TestSetCustomerLinePrice:
    @pytest.fixture(autouse=True)
    def _tiers(self, tenant):
        _set_tiers(tenant, [1, 5, 10])

    def test_a_new_line_drops_the_sent_price_for_the_tier_price(self):
        line = {
            "offer": _offer(**OFFER_PRICES),
            "amount": Decimal("10.000"),
            "price_per_unit": Decimal("0.01"),
        }

        set_customer_line_price(line, None)

        assert line["price_per_unit"] == Decimal("1.80")

    def test_a_new_line_without_amount_takes_the_base_price(self):
        line: dict[str, Any] = {"offer": _offer(**OFFER_PRICES)}

        set_customer_line_price(line, None)

        assert line["price_per_unit"] == Decimal("2.00")

    def test_an_amount_write_reprices_the_stored_line(self):
        instance = OrderContent(offer=_offer(**OFFER_PRICES))
        line = {"amount": Decimal("20.000"), "price_per_unit": Decimal("0.01")}

        set_customer_line_price(line, instance)

        assert line["price_per_unit"] == Decimal("1.60")

    def test_a_write_without_amount_keeps_the_stored_price(self):
        instance = OrderContent(offer=_offer(**OFFER_PRICES))
        line = {"note": "ring twice", "price_per_unit": Decimal("0.01")}

        set_customer_line_price(line, instance)

        assert line == {"note": "ring twice"}

    def test_a_line_without_offer_keeps_the_stored_price(self):
        instance = OrderContent(offer=None)
        line = {"amount": Decimal("20.000"), "price_per_unit": Decimal("0.01")}

        set_customer_line_price(line, instance)

        assert line == {"amount": Decimal("20.000")}
