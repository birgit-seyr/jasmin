from decimal import ROUND_HALF_UP, Decimal

WEIGHT_QUANTIZE = Decimal("0.001")


def quantize_weight(value: Decimal | float) -> Decimal:
    """3dp Decimal for share / packing weights — the single home for
    3-decimal weight rounding (shares-weights CSV export + bulk packing
    totals). Coerces float via ``str`` to dodge binary-fp drift (the
    money/quantity rule), replacing the older ``Decimal(f"{x:.3f}")``
    round-trip."""
    if isinstance(value, float):
        value = str(value)
    return Decimal(value).quantize(WEIGHT_QUANTIZE, rounding=ROUND_HALF_UP)
