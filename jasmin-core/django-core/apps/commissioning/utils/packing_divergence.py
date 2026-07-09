"""All-stations packing-amount divergence guard.

The packing list and the member-amount / boxes-matrix views can be rendered
WITHOUT a ``delivery_station`` scope. In that case the same
``(article, unit, size, variation)`` cell can receive rows from several
stations within one delivery day; collapsing them to a single value is only
correct when those amounts AGREE. :func:`record_amount` records each cell's
amount as it is seen and refuses loudly — raising
:class:`PackingAmountsDivergeAcrossStations` — the moment two stations disagree,
rather than silently dropping one station's amount.

The cell key is caller-supplied so each view keeps its own granularity (every
site keys by delivery day, so two delivery days that share a packing day may
legitimately differ and must NOT trip the guard).
"""

from __future__ import annotations

from typing import Any

from ..errors import PackingAmountsDivergeAcrossStations


def record_amount(
    seen: dict[Any, Any],
    cell_key: Any,
    amount: Any,
    *,
    article_id: str,
    unit: str,
    size: str,
    variation_id: str,
) -> None:
    """Record ``amount`` for ``cell_key``, raising if it diverges from a prior one.

    ``seen`` maps each caller-supplied ``cell_key`` to the first amount recorded
    for it. If ``cell_key`` was already seen with a DIFFERENT amount, raise
    :class:`PackingAmountsDivergeAcrossStations` carrying the article/variation
    identity; otherwise store ``amount`` under ``cell_key``.
    """
    if cell_key in seen and seen[cell_key] != amount:
        raise PackingAmountsDivergeAcrossStations(
            share_article_id=article_id,
            unit=unit,
            size=size,
            variation_id=variation_id,
            amounts=[seen[cell_key], amount],
        )
    seen[cell_key] = amount
