"""Which additional theoretical amounts a documentation write sets, and the rule
that keeps those of a day before today as they are."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Model
from django.utils import timezone

from ..errors import PastDayAdditionalAmount
from ..utils.iso_week_utils import week_day_to_date

# HARVEST additional entries split per content source (share vs order):
# (payload amount key, for_*_content flags).
CONTENT_TYPE_FLAGS: list[tuple[str, dict[str, bool]]] = [
    (
        "amount_share_content",
        {"for_share_content": True, "for_order_content": False},
    ),
    (
        "amount_order_content",
        {"for_share_content": False, "for_order_content": True},
    ),
]

AdditionalWrite = tuple[Any, dict[str, bool] | None]


def additional_writes(
    data: dict[str, Any], model_key: str, *, partial: bool
) -> list[AdditionalWrite]:
    """The (amount, flags) entries a write of ``data`` sets.

    A harvest sets its share-content and order-content entries; every other
    model a single ``amount`` entry. ``partial`` (an update) sets only the keys
    present in ``data``, a harvest edit perhaps just one content amount; an add
    always sets both harvest entries. A harvest payload carrying a plain
    ``amount`` instead of the content keys sets the single entry.
    """
    if model_key == "harvest":
        writes: list[AdditionalWrite] = [
            (data.get(amount_key) or 0, flags)
            for amount_key, flags in CONTENT_TYPE_FLAGS
            if not partial or amount_key in data
        ]
        if writes:
            return writes
    if partial and "amount" not in data:
        return []
    return [(data.get("amount"), None)]


def refuse_past_day_change(
    additional_model: type[Model],
    common_fields: dict[str, Any],
    writes: list[AdditionalWrite],
    model_key: str,
) -> None:
    """Refuse a write that changes an additional harvest, washing or cleaning
    amount of a day before today. Sending the stored amount again passes, so a
    row's other fields still change. A purchase sits on a fixed day of the
    delivery week rather than a planned one and is never refused."""
    day_number = common_fields["day_number"]
    if model_key == "purchase" or day_number is None:
        return
    day = week_day_to_date(
        common_fields["year"], common_fields["delivery_week"], day_number
    )
    if day >= timezone.localdate():
        return
    for amount, flags in writes:
        stored = (
            additional_model._default_manager.filter(**common_fields, **(flags or {}))
            .values_list("amount", flat=True)
            .first()
        )
        if Decimal(str(amount or 0)) != (stored or Decimal(0)):
            raise PastDayAdditionalAmount(
                f"{day} lies in the past, so its additional amount can no "
                "longer be changed.",
                details={"date": day.isoformat()},
            )
