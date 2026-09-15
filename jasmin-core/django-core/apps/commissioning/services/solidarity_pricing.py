"""The solidarity-pricing floor for a subscription's ``price_per_delivery``.

When the tenant enables ``allows_solidarity_pricing``, a member (or the office)
may price a subscription below the variation's reference price, but not below
its floor: ``solidarity_min_price_per_delivery``, or the reference price when no
explicit floor is set. There is no upper bound — paying more is the point. With
solidarity pricing off the rule is a no-op: the office keeps its price
discretion, and the member self-subscribe path forces the reference price
upstream.

One rule for every writer of a subscription price: ``SubscriptionSerializer``
(office create / PATCH and member self-subscribe) and
``WaitingListOfferService.offer_spot``.
"""

from __future__ import annotations

import datetime
from decimal import Decimal


def assert_price_meets_solidarity_floor(
    *,
    price: Decimal | None,
    share_type_variation_id: str | None,
    effective_date: datetime.date,
    is_trial: bool,
) -> None:
    """Raise ``SolidarityPriceBelowMinimum`` when ``price`` is below the floor
    of ``share_type_variation_id``'s gross-price window active at
    ``effective_date``.

    ``effective_date`` is the subscription's START (``valid_from``), not today:
    ``ShareTypeVariationGrossPrice`` is time-bound and a start date is virtually
    always in the future. Resolving at today would evade a future window's
    higher floor and miss a future-price-only variation entirely.

    A trial subscription is floored against the trial pair when the variation
    carries a trial reference price, otherwise against the regular pair. This
    mirrors the client (``NewSubscriptionModal``) so both agree on the boundary.

    No-op when solidarity pricing is off, when there is no price or variation to
    check, or when the variation has no priced window at ``effective_date``.
    """
    if price is None or share_type_variation_id is None:
        return

    from apps.shared.tenants.models import TenantSettings
    from core.tenant_db import connection

    current_settings = TenantSettings.get_current_settings(connection.tenant)
    if not (current_settings and current_settings.allows_solidarity_pricing):
        return

    from ..errors import SolidarityPriceBelowMinimum
    from ..models import ShareTypeVariationGrossPrice

    gross_price = (
        ShareTypeVariationGrossPrice.current.active_at_date(effective_date)
        .filter(share_type_variation_id=share_type_variation_id)
        .order_by("-valid_from")
        .first()
    )
    if gross_price is None:
        return

    if is_trial and gross_price.price_per_delivery_if_trial is not None:
        reference = gross_price.price_per_delivery_if_trial
        explicit_floor = gross_price.solidarity_min_price_per_delivery_if_trial
    else:
        reference = gross_price.price_per_delivery
        explicit_floor = gross_price.solidarity_min_price_per_delivery
    floor = explicit_floor if explicit_floor is not None else reference
    if floor is not None and price < floor:
        raise SolidarityPriceBelowMinimum(chosen=price, minimum=floor)
