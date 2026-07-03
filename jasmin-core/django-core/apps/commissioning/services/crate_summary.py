"""Helpers to build crate summary rows shared by viewsets and serializers.

The shape returned by ``build_crate_summary_row`` matches the
``CrateItemSummarySerializer`` schema: decimal-shaped fields are rendered
as strings, ``rabatt`` and ``tax_rate`` as floats. Per-scope extras
(``order_*`` / ``delivery_note_*`` / ``invoice_*``) are merged via the
``extras`` argument so the dict keeps a stable layout across callers.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Any

from ..models.mixin import PRICE_QUANTIZE as _CENT
from ..models.mixin import line_netto


def build_crate_summary_row(
    *,
    crate_type_id: Any,
    crate_type_name: str | None,
    amount: int | None,
    price: Any,
    rabatt: Any,
    tax_rate: Any,
    line_netto_value: Any = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the canonical crate summary dict for a single crate type.

    ``line_netto_value`` — when given (e.g. the SUM of the grouped rows'
    per-row ``line_netto``) it is used verbatim so the displayed per-line
    figure equals what the document footer sums. When ``None`` the net is
    recomputed from ``amount`` / ``price`` / ``rabatt`` (legacy callers).
    """
    amount_v = amount or 0
    price_d = Decimal(str(price or 0))
    rabatt_d = Decimal(str(rabatt or 0))
    if line_netto_value is not None:
        line = Decimal(str(line_netto_value))
    else:
        line = line_netto(amount=amount_v, price_per_unit=price_d, rabatt=rabatt_d)

    row: dict[str, Any] = {
        "id": crate_type_id,
        "crate_type": crate_type_id,
        "crate_type_name": crate_type_name,
        "amount": amount_v,
        "price_per_unit": str(price_d),
        "rabatt": float(rabatt_d),
        "line_netto": str(line.quantize(_CENT)),
        "tax_rate": float(tax_rate or 0),
    }
    if extras:
        row.update(extras)
    return row


def summarize_crate_items(
    crate_items: Iterable[Any],
    *,
    resolve_tax_rate: Callable[[Any], Any] | None = None,
    extras: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Group crate line items into display summary rows.

    One row per distinct ``(crate_type, price_per_unit, rabatt, tax_rate)`` so
    the displayed price / rabatt / tax_rate are exact rather than lossy
    ``max()`` aggregates, and ``line_netto`` is the SUM of the grouped rows'
    per-row ``line_netto`` — the same value the document footer
    (``sum_netto`` / ``tax_breakdown``) uses, so the per-line display and the
    totals never diverge. Homogeneous groups also avoid the
    ``max(None, Decimal)`` TypeError that a NULL ``price_per_unit`` mixed with
    a non-null one used to raise (a hard 500 on the detail endpoint).

    ``resolve_tax_rate(crate_type) -> rate`` supplies the rate for a group
    whose stored ``tax_rate`` is NULL (e.g. the date-based fallback the
    delivery-note serializer needs).
    """
    groups: dict[tuple, list] = defaultdict(list)
    for crate_item in crate_items:
        key = (
            crate_item.crate_type_id,
            crate_item.price_per_unit,
            crate_item.rabatt or 0,
            crate_item.tax_rate,
        )
        groups[key].append(crate_item)

    def _sort_key(entry: tuple) -> tuple:
        items = entry[1]
        crate_type = items[0].crate_type
        name = crate_type.name if crate_type else ""
        price = items[0].price_per_unit
        return (name, price if price is not None else Decimal("0"))

    rows: list[dict[str, Any]] = []
    for _key, items in sorted(groups.items(), key=_sort_key):
        first = items[0]
        tax_rate = first.tax_rate
        if tax_rate is None and resolve_tax_rate is not None:
            tax_rate = resolve_tax_rate(first.crate_type)
        rows.append(
            build_crate_summary_row(
                crate_type_id=first.crate_type_id,
                crate_type_name=first.crate_type.name if first.crate_type else None,
                amount=sum((item.amount for item in items), Decimal("0")),
                price=first.price_per_unit,
                rabatt=first.rabatt or 0,
                tax_rate=tax_rate,
                line_netto_value=sum((item.line_netto for item in items), Decimal("0")),
                extras=extras,
            )
        )
    return rows
