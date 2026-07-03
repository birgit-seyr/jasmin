"""BL-13: a ShareTypeVariation's validity must stay nested within its parent
ShareType's window. Covers the open-variation-vs-closed-parent gap in the
model clean(), and a direct shortening of the parent that would strand an
open / late-ending child (the exploitable office-edit path)."""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import ValidationError

from apps.commissioning.errors import ShareTypeShorteningStrandsVariation
from apps.commissioning.tests.factories import (
    ShareTypeFactory,
    ShareTypeVariationFactory,
)

# valid_from is the Monday 2026-01-05; these are subsequent Sundays (valid ends).
_SUNDAY = datetime.date(2026, 1, 11)
_LATER_SUNDAY = datetime.date(2026, 1, 18)
_LATE_VARIATION_END = datetime.date(2026, 2, 22)


@pytest.mark.django_db
class TestShareTypeValidityNesting:
    def test_shortening_parent_strands_open_variation(self, tenant):
        # The exploit: an office edit shortening the parent's end date must not
        # strand an open child that would then outlive its parent.
        share_type = ShareTypeFactory()
        ShareTypeVariationFactory(share_type=share_type, valid_until=None)

        share_type.valid_until = _SUNDAY
        with pytest.raises(ShareTypeShorteningStrandsVariation):
            share_type.save()

    def test_shortening_parent_strands_late_ending_variation(self, tenant):
        share_type = ShareTypeFactory()
        ShareTypeVariationFactory(
            share_type=share_type, valid_until=_LATE_VARIATION_END
        )

        share_type.valid_until = _SUNDAY  # earlier than the child's end
        with pytest.raises(ShareTypeShorteningStrandsVariation):
            share_type.save()

    def test_open_variation_under_closed_parent_rejected_by_model(self, tenant):
        # The model clean() (not just the serializer) rejects an open variation
        # once its parent is closed.
        share_type = ShareTypeFactory()
        share_type.valid_until = _SUNDAY
        share_type.save()  # close it — no children yet, so allowed

        with pytest.raises(ValidationError):
            ShareTypeVariationFactory(share_type=share_type, valid_until=None)

    def test_shortening_parent_still_covering_variation_allowed(self, tenant):
        # Sanity: shortening to a date that still covers a closed child is fine.
        share_type = ShareTypeFactory()
        ShareTypeVariationFactory(share_type=share_type, valid_until=_SUNDAY)

        share_type.valid_until = _LATER_SUNDAY  # after the child's end
        share_type.save()  # no raise

        share_type.refresh_from_db()
        assert share_type.valid_until == _LATER_SUNDAY
