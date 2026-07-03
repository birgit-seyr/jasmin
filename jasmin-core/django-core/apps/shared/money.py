"""Float-safe ``Decimal`` money primitives.

All money and stock-quantity fields in the platform are ``DecimalField``s,
and money math must stay in ``Decimal`` end-to-end. The classic mistake
these helpers guard against is ``Decimal(float_value)``, which captures the
float's binary representation (``Decimal(1.1)`` ->
``Decimal('1.10000000000000008881784...')``) instead of the intended value —
floats are routed through ``str`` first (``Decimal(str(1.1))`` ->
``Decimal('1.1')``).

These are standalone, domain-free utilities — safe to import from any app
(including ``apps/commissioning``). Domain pricing math (line netto/brutto,
per-VAT-rate tax breakdowns, ...) stays in its owning app; only the
primitive lives here.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

#: One cent — the canonical money quantum.
CENT = Decimal("0.01")


def to_decimal(value) -> Decimal:
    """Coerce ``value`` to ``Decimal`` without binary-floating-point drift.

    ``None`` counts as zero; ``Decimal``s pass through unchanged; everything
    else (int, float, str) goes through ``Decimal(str(value))`` so floats
    keep their intended decimal value.
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_money(value) -> Decimal:
    """Coerce ``value`` (see :func:`to_decimal`) and round to whole cents
    with ``ROUND_HALF_UP``."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
