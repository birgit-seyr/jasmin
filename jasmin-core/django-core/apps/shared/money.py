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


def fits_decimal_column(
    amount: Decimal, *, max_digits: int, decimal_places: int
) -> bool:
    """Whether ``amount`` is storable as written in a
    ``numeric(max_digits, decimal_places)`` column.

    ``False`` for a non-finite amount, for one whose integer part overflows the
    column, and for one carrying more decimals than the column keeps — that last
    one is the quiet failure, since the write would round it away and store an
    amount nobody asked for. A trailing zero is not extra precision:
    ``10.9900`` fits two decimal places.

    Screening for non-finite first also makes this safe to call before any
    comparison of ``amount``, which would raise on a NaN.

    ``copy_abs`` rather than ``abs``: the latter is context-sensitive and
    raises ``decimal.Overflow`` on an extreme exponent (``1e6000000``), which
    would turn a value this predicate exists to refuse into an unhandled
    error. ``copy_abs`` only flips the sign, so such an amount reaches the
    comparison and is answered with ``False``.
    """
    if not amount.is_finite():
        return False
    if amount.copy_abs() >= Decimal(10) ** (max_digits - decimal_places):
        return False
    quantum = Decimal(1).scaleb(-decimal_places)
    return amount.quantize(quantum, rounding=ROUND_HALF_UP) == amount
