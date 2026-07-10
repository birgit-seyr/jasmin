"""ShareTypeSerializer coerces a blanked joker count to 0.

Clearing a joker cell in the office ShareType table sends "" / null; the intent
is "no jokers" (0), not a validation error. A PATCH that omits the field must
leave the stored value untouched.
"""

from __future__ import annotations

import pytest

from apps.commissioning.serializers.shares_serializer import ShareTypeSerializer
from apps.commissioning.tests.factories import ShareTypeFactory


@pytest.mark.django_db
@pytest.mark.parametrize("blank", ["", None])
def test_blanked_joker_counts_coerce_to_zero(tenant, blank):
    share_type = ShareTypeFactory(amount_of_jokers=4, amount_of_donation_jokers=2)
    serializer = ShareTypeSerializer(
        instance=share_type,
        data={"amount_of_jokers": blank, "amount_of_donation_jokers": blank},
        partial=True,
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["amount_of_jokers"] == 0
    assert serializer.validated_data["amount_of_donation_jokers"] == 0


@pytest.mark.django_db
def test_absent_joker_count_is_left_unchanged(tenant):
    share_type = ShareTypeFactory(amount_of_jokers=4)
    serializer = ShareTypeSerializer(instance=share_type, data={}, partial=True)
    assert serializer.is_valid(), serializer.errors
    # An omitted field must not be reset — it simply isn't in validated_data.
    assert "amount_of_jokers" not in serializer.validated_data
