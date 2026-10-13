"""The price per unit an order line of an offer is charged at: the offer's price
for the quantity tier the line reaches.

The tenant's ``used_tiers_for_offers`` lists the tier thresholds in PU, the
first one the base tier. A line takes ``price_3`` from the third threshold on
and ``price_2`` from the second, each only while that price is above zero, so a
tier left without a price falls back to the next lower one; otherwise
``price_1``. A tenant with fewer thresholds never escalates past its last one.

The browser applies the same rule (``pickTierPrice`` and
``pickTierPriceFromAmount`` in the frontend's ``shared/utils/tierPrice.ts``) to
the lines the office prices. Both sides are tested against one table of cases,
``shared/utils/__tests__/tierPriceCases.json``, so they cannot drift apart.
A customer never prices their own line; the server does it here
(``set_customer_line_price``).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, NamedTuple

from apps.shared.money import to_decimal

from ..constants import get_offer_price_tiers

if TYPE_CHECKING:
    from ..models import Offer, OrderContent


class TierPrices(NamedTuple):
    """An offer's price per unit for each tier, ``None`` where it has none."""

    price_1: Decimal | None = None
    price_2: Decimal | None = None
    price_3: Decimal | None = None


def _reaches(pu_count: Decimal, tiers: Sequence[object], index: int) -> bool:
    """Whether ``pu_count`` reaches the threshold at ``tiers[index]``.

    A threshold ``tiers`` doesn't list is never reached. One stored as ``None``
    (a tier the office added but left empty) compares as 0, as the browser's
    ``null`` does, so every count reaches it. Any other entry that is no number
    is never reached.
    """
    if index >= len(tiers):
        return False
    threshold = tiers[index]
    if threshold is None:
        return pu_count >= 0
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float, Decimal)):
        return False
    return pu_count >= to_decimal(threshold)


def pick_tier_price(
    pu_count: Decimal, prices: TierPrices, tiers: Sequence[object] = ()
) -> Decimal:
    """The price per unit of a line of ``pu_count`` PU under ``tiers``. A
    missing price counts as 0."""
    base, second, third = (to_decimal(price) for price in prices)
    if _reaches(pu_count, tiers, 2) and third > 0:
        return third
    if _reaches(pu_count, tiers, 1) and second > 0:
        return second
    return base


def pick_tier_price_from_amount(
    amount: Decimal | None,
    amount_per_pu: Decimal | None,
    prices: TierPrices,
    tiers: Sequence[object] = (),
) -> Decimal:
    """``pick_tier_price`` for an amount in the offer's unit (kg, pieces,
    bunches), ``amount_per_pu`` of which make one PU. A missing amount counts
    as 0, a missing or zero ``amount_per_pu`` as 1."""
    count = to_decimal(amount)
    per_pu = to_decimal(amount_per_pu) or Decimal("1")
    return pick_tier_price(count / per_pu if per_pu > 0 else count, prices, tiers)


def offer_tier_price(offer: Offer, amount: Decimal | None) -> Decimal:
    """The price per unit of a line of ``amount`` (in the offer's unit) of
    ``offer`` under the tenant's tiers."""
    return pick_tier_price_from_amount(
        amount,
        offer.amount_per_pu,
        TierPrices(offer.price_1, offer.price_2, offer.price_3),
        get_offer_price_tiers(),
    )


def set_customer_line_price(
    line: dict[str, Any], instance: OrderContent | None
) -> None:
    """Price a customer's write of an order line on the server's terms.

    ``line`` is the validated request body. Its ``price_per_unit`` is dropped,
    not refused, so a client that still sends the price it worked out keeps
    working. A new line (``instance`` ``None``) and a write that sets an
    existing line's amount take the tier price of the line's offer for that
    amount; any other write keeps the stored price, as does a line without an
    offer.
    """
    line.pop("price_per_unit", None)
    offer = line.get("offer") if instance is None else instance.offer
    if offer is not None and (instance is None or "amount" in line):
        line["price_per_unit"] = offer_tier_price(offer, line.get("amount"))
