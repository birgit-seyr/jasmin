"""How much of an article's theoretical stock is held for shares and how much
for resellers, as the documentation summary shows it."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.shared.money import to_decimal

StockKey = tuple[str, str, str | None, str | None]


def calculate_theoretical_stock(
    stock_key: StockKey,
    theoretical_stock_map: dict[StockKey, dict[str, Any]],
    theoretical_sum_share: Decimal | float = 0,
) -> tuple[Decimal, Decimal, Decimal]:
    """Calculate theoretical current stock for the entry at ``stock_key``
    (share article, unit, size, storage).

    Returns (total, share_stock, order_stock).
    Uses for_shares / for_resellers flags from the stock entries to split.
    Falls back from current_stock_amount to theoretical_current_stock.
    Negative values are clamped to 0.
    """
    matching_keys = [stock_key] if stock_key in theoretical_stock_map else []

    if not matching_keys:
        return Decimal("0"), Decimal("0"), Decimal("0")

    share_stock = Decimal("0")
    order_stock = Decimal("0")
    theoretical_sum_share = to_decimal(theoretical_sum_share)

    for key in matching_keys:
        entry = theoretical_stock_map[key]
        stock = entry.get("current_stock_amount")
        if stock is None:
            stock = entry.get("theoretical_current_stock") or 0
        stock = max(to_decimal(stock), Decimal("0"))

        is_share = entry.get("for_shares")
        is_order = entry.get("for_resellers")

        if is_share and is_order:
            # Both flags: assign up to theoretical_sum_share to share,
            # remainder to order
            to_share = min(
                stock, max(theoretical_sum_share - share_stock, Decimal("0"))
            )
            share_stock += to_share
            order_stock += stock - to_share
        elif is_share:
            share_stock += stock
        elif is_order:
            order_stock += stock
        else:
            share_stock += stock

    total = share_stock + order_stock

    return total, share_stock, order_stock
