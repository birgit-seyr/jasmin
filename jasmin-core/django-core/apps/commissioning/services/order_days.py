"""The days an order carries besides its delivery day: when its goods are
harvested, washed, cleaned and packed, and the reseller's ordering deadline."""

from __future__ import annotations

from typing import Any

from ..errors import OrderDayMissing
from ..models import Order, OrdersDeliveryDay

ORDER_DAY_FIELDS = (
    "harvesting_day",
    "packing_day",
    "washing_day",
    "cleaning_day",
    "last_possible_ordering_day",
)


def apply_order_days(
    order: Order, *, created: bool, day_number: int, sent: dict[str, Any]
) -> None:
    """Set the order's days from ``sent``, popping each one off it.

    A new order takes the delivery day's order default for a day not sent or
    sent empty. A work day left out may stay empty, as a customer's order does
    (the work then falls back to the delivery day); one sent empty must be
    filled by a default, or the order is refused. The ordering deadline may
    stay empty either way. An existing order keeps any day sent empty.
    """
    if not created:
        changed = False
        for field in ORDER_DAY_FIELDS:
            value = sent.pop(field, None)
            if value is not None and getattr(order, field) != value:
                setattr(order, field, value)
                changed = True
        if changed:
            order.save()
        return

    defaults = OrdersDeliveryDay.objects.filter(day_number=day_number).first()
    for field in ORDER_DAY_FIELDS:
        sent_empty = field in sent and sent[field] is None
        value = sent.pop(field, None)
        if value is None and defaults:
            # OrdersDeliveryDay carries a ``default_<field>`` column for every
            # entry in ``ORDER_DAY_FIELDS``; no safety default — a typo there
            # should crash here rather than silently fall through with ``None``.
            value = getattr(defaults, f"default_{field}")
        if value is None and sent_empty and field != "last_possible_ordering_day":
            raise OrderDayMissing(field=field, day_number=day_number)
        setattr(order, field, value)
    order.save()
