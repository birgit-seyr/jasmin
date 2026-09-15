"""Single source of truth for commissioning's dynamically-named request keys.

A plain DRF serializer can't declare a field whose NAME embeds a runtime id
(``amount_<variation_id>``, ``day_<day>_variation_<var>``). These constants +
the ``parse_amount_cell`` helper are the ONE definition of each key family,
imported by both the validating serializer mixin (``serializers.dynamic_keys``)
and the services that iterate the raw payload — so the patterns and the
value-coercion can't drift.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from ..errors import InvalidAmount

# ``amount_<share_type_variation_id>`` — DefaultShareContent planning cells.
AMOUNT_KEY_PREFIX = "amount_"

# ``day_<day_id>_variation_<variation_id>[_tour_<n>|_station_<id>]`` — harvest
# share-planning + backup cells. Hyphen-tolerant; the optional tour/station
# groups make it match the plain
# day/variation key too (the backup path just ignores groups 3/4).
DAY_VARIATION_RE = re.compile(
    r"day_([a-zA-Z0-9-]+)_variation_([a-zA-Z0-9-]+)(?:_(tour|station)_([a-zA-Z0-9-]+))?"
)

# Cell values meaning "no plan / clear this cell" — intentionally skipped,
# never persisted, never an error. A tuple (not a set) so an unhashable cell
# value can't blow up the membership test.
SCAFFOLD_VALUES = (None, "", "undefined")


def parse_amount_cell(value: object, *, field: str) -> Decimal:
    """Coerce a dynamic amount cell to a FINITE ``Decimal`` or raise
    ``InvalidAmount`` (400) naming the offending key.

    Rejects non-numeric input AND the well-formed-but-not-a-real-number Decimals
    ``NaN`` / ``Infinity`` — ``Decimal(str("NaN"))`` parses fine, so without the
    finiteness guard a ``"NaN"`` cell either 500s on a later comparison or is
    silently stored. Does NOT reject negatives; callers that forbid them (e.g.
    the request serializer) check ``< 0`` separately on the finite result.
    """
    try:
        amount = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise InvalidAmount(
            f"Invalid amount {value!r} for {field} — expected a number.",
            field=field,
        ) from exc
    if not amount.is_finite():
        raise InvalidAmount(
            f"Invalid amount {value!r} for {field} — expected a finite number.",
            field=field,
        )
    return amount


def extract_amounts_from_keys(
    data: dict[str, Any], prefix: str = AMOUNT_KEY_PREFIX
) -> dict[str, Any]:
    """
    Extract IDs and amounts from data keys with a specific prefix pattern.

    Args:
        data: Dictionary containing keys like 'amount_<id>'
        prefix: The prefix to look for (default: ``AMOUNT_KEY_PREFIX``)

    Returns:
        Dictionary mapping IDs to their amounts

    Example:
        >>> data = {'amount_V9uWuNNgV0h6': '10.5', 'amount_UJVEq_SRG4RY': '20.0'}
        >>> extract_amounts_from_keys(data)
        {'V9uWuNNgV0h6': '10.5', 'UJVEq_SRG4RY': '20.0'}
    """
    amounts = {}
    prefix_len = len(prefix)

    for key, value in data.items():
        if key.startswith(prefix) and len(key) > prefix_len:
            # Extract ID by removing prefix
            extracted_id = key[prefix_len:]
            amounts[extracted_id] = value

    return amounts
