"""Tests for the ``DefaultShareArticleInShare`` model.

Covers:
- ``__str__`` representation.
- Unique constraint on ``(share_article, share_type_variation, unit)``.
- ``unit`` may be NULL.
- Cascading deletes from both FKs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.commissioning.models import DefaultShareArticleInShare
from apps.commissioning.tests.factories import (
    ShareArticleFactory,
    ShareTypeVariationFactory,
)


@pytest.mark.django_db
class TestDefaultShareArticleInShareModel:
    def test_str_includes_article_quantity_unit_and_variation(self, tenant):
        article = ShareArticleFactory(name="Carrots")
        variation = ShareTypeVariationFactory()
        row = DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=variation,
            quantity=Decimal("1.500"),
            unit="KG",
        )
        s = str(row)
        assert "Carrots" in s
        assert "1.500" in s
        assert "KG" in s

    def test_unit_can_be_null(self, tenant):
        row = DefaultShareArticleInShare.objects.create(
            share_article=ShareArticleFactory(),
            share_type_variation=ShareTypeVariationFactory(),
            quantity=Decimal("1.000"),
            unit=None,
        )
        assert row.pk is not None
        assert row.unit is None

    def test_quantity_keeps_three_decimals(self, tenant):
        row = DefaultShareArticleInShare.objects.create(
            share_article=ShareArticleFactory(),
            share_type_variation=ShareTypeVariationFactory(),
            quantity=Decimal("2.345"),
            unit="KG",
        )
        row.refresh_from_db()
        assert row.quantity == Decimal("2.345")

    def test_unique_constraint_on_article_variation_unit(self, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=variation,
            quantity=Decimal("1.000"),
            unit="KG",
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DefaultShareArticleInShare.objects.create(
                    share_article=article,
                    share_type_variation=variation,
                    quantity=Decimal("2.000"),
                    unit="KG",
                )

    def test_same_article_and_variation_with_different_unit_is_allowed(self, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=variation,
            quantity=Decimal("1.000"),
            unit="KG",
        )
        # different unit → distinct row
        row = DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=variation,
            quantity=Decimal("2.000"),
            unit="PIECE",
        )
        assert row.pk is not None
        assert (
            DefaultShareArticleInShare.objects.filter(
                share_article=article, share_type_variation=variation
            ).count()
            == 2
        )

    def test_cascade_delete_when_share_article_deleted(self, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        row = DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=variation,
            quantity=Decimal("1.000"),
            unit="KG",
        )
        article.delete()
        assert not DefaultShareArticleInShare.objects.filter(pk=row.pk).exists()

    def test_cascade_delete_when_share_type_variation_deleted(self, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        row = DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=variation,
            quantity=Decimal("1.000"),
            unit="KG",
        )
        variation.delete()
        assert not DefaultShareArticleInShare.objects.filter(pk=row.pk).exists()
