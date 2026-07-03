"""OFFER-2: partial unique constraint on the general-offer slot.

``offer_unique_general_per_slot`` enforces at most one GENERAL offer (reseller
IS NULL) per (year, delivery_week, share_article, unit, size, offer_group),
turning the ``create_offers`` double-click / concurrent race into a catchable
IntegrityError — while still allowing a reseller-specific offer for the same
slot (the partial ``WHERE reseller IS NULL`` condition).
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.commissioning.models import Offer
from apps.commissioning.tests.factories import (
    OfferFactory,
    OfferGroupFactory,
    ResellerFactory,
    ShareArticleFactory,
)


@pytest.mark.django_db
class TestOfferUniqueGeneralPerSlot:
    @staticmethod
    def _slot():
        return {
            "share_article": ShareArticleFactory(),
            "offer_group": OfferGroupFactory(),
            "year": 2026,
            "delivery_week": 15,
            "unit": "KG",
            "size": "M",
        }

    def test_duplicate_general_offer_rejected(self, tenant):
        slot = self._slot()
        OfferFactory(**slot)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OfferFactory(**slot)

    def test_reseller_specific_offer_can_coexist(self, tenant):
        slot = self._slot()
        OfferFactory(**slot)  # general (reseller IS NULL)
        OfferFactory(**slot, reseller=ResellerFactory())  # reseller-specific
        assert (
            Offer.objects.filter(
                share_article=slot["share_article"],
                offer_group=slot["offer_group"],
            ).count()
            == 2
        )
