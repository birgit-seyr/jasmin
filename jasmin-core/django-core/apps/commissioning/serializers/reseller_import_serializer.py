"""CSV import serializer for resellers (data-list onboarding).

The template the resellers page hands out names a reseller's offer group by
``offer_group_name`` — the grid's display column — not by id, so the import
resolves that name to the group here. The office grid sends the id and keeps
using ``ResellerSerializer``.
"""

from __future__ import annotations

from rest_framework import serializers

from ..errors import OfferGroupNameAmbiguous, OfferGroupNameUnknown
from ..models import OfferGroup
from .resellers_serializer import ResellerSerializer


class ResellerImportSerializer(ResellerSerializer):
    """``ResellerSerializer`` that also reads ``offer_group_name``.

    The name matches ``OfferGroup.name`` ignoring case and surrounding spaces,
    among every offer group, active or not, as the grid's offer group select
    offers them all. An ``offer_group`` id in the row wins over the name; a row
    with neither gets the default offer group from
    ``ResellerAndDeliveryStationService.create_reseller``.
    """

    offer_group_name = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )

    @staticmethod
    def _resolve_offer_group(name: str) -> OfferGroup:
        matches = list(OfferGroup.objects.filter(name__iexact=name)[:2])
        if not matches:
            raise OfferGroupNameUnknown(
                f"No offer group named '{name}'.",
                field="offer_group_name",
                details={"offer_group_name": name},
            )
        if len(matches) > 1:
            raise OfferGroupNameAmbiguous(
                f"More than one offer group is named '{name}'.",
                field="offer_group_name",
                details={"offer_group_name": name},
            )
        return matches[0]

    def validate(self, data):
        name = data.pop("offer_group_name", "").strip()
        if name and data.get("offer_group") is None:
            data["offer_group"] = self._resolve_offer_group(name)
        return super().validate(data)
