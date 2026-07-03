"""DB-1: Purchase no-seller upsert key must be unique at the DB level.

``bulk_set_purchase_as_expected`` and ``_ensure_purchase_placeholder`` upsert
Purchase rows on
``(year, delivery_week, day_number, share_article, unit, size, storage)`` while
leaving ``seller`` NULL. The original seller-scoped partial constraint only
fires when ``seller IS NOT NULL``, so concurrent no-seller upserts could
double-insert (MultipleObjectsReturned + double-counted stock). The new
partial UniqueConstraint (condition ``seller IS NULL``, ``nulls_distinct=
False``) closes that gap while still de-duping the NULL ``day_number`` rows
that ``bulk_set_purchase_as_expected`` produces.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.commissioning.models import Purchase
from apps.commissioning.tests.factories import (
    PurchaseFactory,
    ResellerFactory,
    ShareArticleFactory,
    StorageFactory,
)


@pytest.mark.django_db
class TestPurchaseNoSellerUniqueConstraint:
    def test_duplicate_no_seller_key_raises_integrity_error(self, tenant):
        """Second insert on the same no-seller key is rejected by the DB."""
        article = ShareArticleFactory(is_purchased=True)
        storage = StorageFactory(is_short_term_harvest_storage=True)

        PurchaseFactory(
            year=2026,
            delivery_week=15,
            day_number=1,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            seller=None,
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PurchaseFactory(
                    year=2026,
                    delivery_week=15,
                    day_number=1,
                    share_article=article,
                    unit="KG",
                    size="M",
                    storage=storage,
                    seller=None,
                )

    def test_null_day_number_still_dedupes(self, tenant):
        """bulk_set_purchase_as_expected leaves day_number NULL; nulls_distinct
        keeps those rows de-duped too."""
        article = ShareArticleFactory(is_purchased=True)
        storage = StorageFactory(is_short_term_harvest_storage=True)

        PurchaseFactory(
            year=2026,
            delivery_week=21,
            day_number=None,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            seller=None,
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PurchaseFactory(
                    year=2026,
                    delivery_week=21,
                    day_number=None,
                    share_article=article,
                    unit="KG",
                    size="M",
                    storage=storage,
                    seller=None,
                )

    def test_seller_scoped_path_unaffected(self, tenant):
        """The no-seller constraint must not block seller-bearing rows: two
        Purchases on the same key but with a non-NULL seller fall under the
        seller-scoped constraint only, and differing sellers stay distinct."""
        article = ShareArticleFactory(is_purchased=True)
        storage = StorageFactory(is_short_term_harvest_storage=True)
        seller_a = ResellerFactory()
        seller_b = ResellerFactory()

        PurchaseFactory(
            year=2026,
            delivery_week=22,
            day_number=1,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            seller=seller_a,
        )
        # Same composite key, different seller — allowed (no constraint fires).
        PurchaseFactory(
            year=2026,
            delivery_week=22,
            day_number=1,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            seller=seller_b,
        )

        assert (
            Purchase.objects.filter(
                year=2026, delivery_week=22, day_number=1, share_article=article
            ).count()
            == 2
        )

    def test_seller_row_coexists_with_no_seller_row(self, tenant):
        """A seller row and a no-seller row on the same composite key live under
        two different partial constraints — neither blocks the other."""
        article = ShareArticleFactory(is_purchased=True)
        storage = StorageFactory(is_short_term_harvest_storage=True)
        seller = ResellerFactory()

        PurchaseFactory(
            year=2026,
            delivery_week=23,
            day_number=1,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            seller=None,
        )
        PurchaseFactory(
            year=2026,
            delivery_week=23,
            day_number=1,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            seller=seller,
        )

        assert (
            Purchase.objects.filter(
                year=2026, delivery_week=23, day_number=1, share_article=article
            ).count()
            == 2
        )
