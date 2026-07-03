"""Serializer mixin that validates dynamically-named numeric request cells.

See ``utils.dynamic_keys`` for the canonical key patterns and the
``parse_amount_cell`` coercion. The mixin validates each matching cell in
``to_internal_value`` — raising one canonical ``InvalidAmount`` (400) on a
non-numeric / non-finite / negative value instead of letting the service 500 or
silently coerce it — and merges the coerced cells into ``validated_data``.

Because the cells land in ``validated_data`` under their original keys, the
share-planning / default-share-content handlers pass ``serializer.validated_data``
(NOT ``request.data``) to their services; the services' extractors then walk the
already-validated dynamic keys. Validation therefore happens once, here.
"""

from __future__ import annotations

from ..errors import InvalidAmount
from ..utils.dynamic_keys import SCAFFOLD_VALUES, parse_amount_cell


class DynamicAmountKeysMixin:
    """Validate dynamically-named numeric cells in ``to_internal_value``.

    Subclasses implement ``_is_dynamic_amount_key(key)``. Matching cells whose
    value is a scaffold sentinel are dropped; the rest are coerced to a finite
    ``Decimal`` (rejecting negatives) and merged into ``validated_data`` under
    their original key. Place the mixin BEFORE ``serializers.Serializer`` in the
    bases so ``super()`` reaches DRF.
    """

    def _is_dynamic_amount_key(self, key: str) -> bool:
        raise NotImplementedError

    def to_internal_value(self, data):
        # Non-mapping bodies: let DRF raise its canonical "expected a dict" 400.
        if not hasattr(data, "items"):
            return super().to_internal_value(data)

        standard: dict = {}
        dynamic: dict = {}
        for key, value in data.items():
            if self._is_dynamic_amount_key(key):
                if value in SCAFFOLD_VALUES:
                    continue
                amount = parse_amount_cell(value, field=key)
                if amount < 0:
                    raise InvalidAmount(
                        f"Amount for {key} must not be negative.", field=key
                    )
                dynamic[key] = amount
            else:
                standard[key] = value

        validated = super().to_internal_value(standard)
        validated.update(dynamic)
        return validated
