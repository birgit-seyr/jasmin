"""Weighted forecast split for harvest-share content.

Distributes a forecast total across physical ``ShareTypeVariation``s
proportional to each size's ``average_weight``, weighted by the physical
variation counts (the same demand totals used everywhere), floored to 0.10 so
the split never over-allocates.

Wired into exactly one place — ``ForecastService._build_share_content_changes``
— where it REPLACES the resolved default amount when the tenant opted into
``distribute_forecast_by_weight``. Everything else about creating the
``ShareContent`` (and the recompute of theoreticals + movements) stays the same;
only the ``amount`` differs.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Any

# Amounts are rounded DOWN to a tenth (0.10) — the office asked for "3.30", and
# flooring guarantees the sum handed out never exceeds the forecast.
_FLOOR_STEP = Decimal("0.1")

# ``ShareContent.amount`` is a NUMERIC(5,3) column — max 99.999. A split larger
# than that means the forecast is huge relative to the number of shares; rather
# than overflow the save, cap it at 99.99. (Floored amounts are multiples of
# 0.10, so "over 99.90" is exactly "≥ 100.00".)
_AMOUNT_CAP = Decimal("99.99")
_AMOUNT_CAP_THRESHOLD = Decimal("99.90")


def split_forecast_amount_by_weight(
    forecast_amount: Decimal | int | float | None,
    variation_weights: dict[Any, Decimal | int | float | None],
    variation_counts: dict[Any, int],
) -> dict[Any, Decimal]:
    """Split ``forecast_amount`` across variations proportional to each
    variation's ``average_weight``, weighted by its physical count.

    Per-share amount for variation ``v``::

        k         = forecast_amount / Σ (count_v · weight_v)
        amount_v  = floor_to_0.10(weight_v · k)

    so each share's amount scales with its size's weight (a size that weighs half
    of another gets half the amount), and the total handed out across every share
    — ``Σ count_v · amount_v`` — is ≤ ``forecast_amount`` (floored, never
    over-allocates; a small remainder may stay unassigned).

    Any amount over 99.90 is capped to 99.99 so it always fits the
    ``ShareContent.amount`` NUMERIC(5,3) column (a per-share amount that large
    means the forecast is huge relative to the shares).

    Returns ``{variation_id: Decimal}`` for the eligible variations only, or an
    empty dict when there is nothing to distribute:

    * ``forecast_amount`` is falsy / ≤ 0, or
    * every variation has a missing/≤ 0 ``average_weight`` (such variations are
      skipped: no amount, and they don't consume any forecast), or
    * the weighted denominator ``Σ count_v · weight_v`` is 0 (e.g. all counts 0).

    Pure and side-effect-free — the caller supplies weights + counts, this only
    does the Decimal math.
    """
    if not forecast_amount or Decimal(str(forecast_amount)) <= 0:
        return {}

    denominator = Decimal(0)
    eligible: list[tuple[Any, Decimal]] = []
    for variation_id, weight in variation_weights.items():
        if weight is None:
            continue
        weight_dec = Decimal(str(weight))
        if weight_dec <= 0:
            continue
        count = int(variation_counts.get(variation_id, 0) or 0)
        denominator += count * weight_dec
        eligible.append((variation_id, weight_dec))

    if denominator <= 0:
        return {}

    per_weight_unit = Decimal(str(forecast_amount)) / denominator
    result: dict[Any, Decimal] = {}
    for variation_id, weight_dec in eligible:
        amount = (weight_dec * per_weight_unit).quantize(
            _FLOOR_STEP, rounding=ROUND_FLOOR
        )
        if amount > _AMOUNT_CAP_THRESHOLD:
            amount = _AMOUNT_CAP
        result[variation_id] = amount
    return result
