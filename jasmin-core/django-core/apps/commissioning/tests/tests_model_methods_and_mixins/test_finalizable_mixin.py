"""Tests for FinalizableMixin and FinalizedProtectedMixin."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commissioning.models import Offer
from apps.commissioning.tests.factories import (
    JasminUserFactory,
    OfferFactory,
    OrderFactory,
    ShareArticleFactory,
)
from core.errors import JasminError


@pytest.mark.django_db
class TestFinalize:
    def test_first_finalize_returns_true(self, tenant):
        user = JasminUserFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100.000"))

        result = offer.finalize(user=user)

        assert result is True
        offer.refresh_from_db()
        assert offer.is_finalized is True
        assert offer.finalized_by == user
        assert offer.finalized_at is not None

    def test_second_finalize_returns_false(self, tenant):
        user = JasminUserFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100.000"))

        offer.finalize(user=user)
        result = offer.finalize(user=user)

        assert result is False

    def test_finalize_locks_the_row(self, tenant):
        """REF-2/REF-5: finalize() must take a SELECT … FOR UPDATE row lock so
        concurrent finalizes serialise."""
        user = JasminUserFactory()
        offer = OfferFactory(
            share_article=ShareArticleFactory(), amount=Decimal("100.000")
        )

        with CaptureQueriesContext(connection) as ctx:
            offer.finalize(user=user)

        assert any(
            "for update" in q["sql"].lower() for q in ctx.captured_queries
        ), "finalize() did not lock the row with SELECT ... FOR UPDATE"

    def test_stale_refinalize_is_noop_and_preserves_audit(self, tenant):
        """The TOCTOU guard: a stale in-memory instance (is_finalized still
        False) whose row was finalized by another path must, on finalize(),
        lock + re-check, return False, NOT re-stamp finalized_at/by, and
        reconcile its own is_finalized to True."""
        user = JasminUserFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100.000"))

        # Two in-memory handles on the same row; ``stale`` predates finalization.
        stale = Offer.objects.get(pk=offer.pk)
        fresh = Offer.objects.get(pk=offer.pk)
        assert fresh.finalize(user=user) is True
        original_finalized_at = Offer.objects.get(pk=offer.pk).finalized_at

        # ``stale`` still believes it is un-finalized — the race window.
        assert stale.is_finalized is False
        assert stale.finalize(user=user) is False
        # In-memory instance reconciled to the persisted truth …
        assert stale.is_finalized is True
        # … and the audit columns were NOT re-stamped by the losing call.
        reloaded = Offer.objects.get(pk=offer.pk)
        assert reloaded.finalized_at == original_finalized_at
        assert reloaded.finalized_by == user


@pytest.mark.django_db
class TestUnfinalize:
    def test_resets_finalization_fields(self, tenant):
        user = JasminUserFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100.000"))

        offer.finalize(user=user)
        offer.unfinalize()

        offer.refresh_from_db()
        assert offer.is_finalized is False
        assert offer.finalized_at is None
        assert offer.finalized_by is None


@pytest.mark.django_db
class TestOfferFinalizedProtected:
    """DOC-6: Offer's bases now place FinalizedProtectedMixin before JasminModel,
    so its per-instance save()/delete() guards fire (previously dead — only the
    Postgres trigger enforced immutability)."""

    def test_save_on_finalized_disallowed_field_raises(self, tenant):
        user = JasminUserFactory()
        offer = OfferFactory()
        offer.finalize(user=user)

        offer.description = "changed"  # not in ALLOWED_FINALIZED_UPDATES (['amount'])
        with pytest.raises(JasminError, match="finalized"):
            offer.save()

    def test_delete_on_finalized_raises(self, tenant):
        user = JasminUserFactory()
        offer = OfferFactory()
        offer.finalize(user=user)

        with pytest.raises(JasminError, match="finalized"):
            offer.delete()

    def test_save_on_non_finalized_works(self, tenant):
        offer = OfferFactory()
        offer.description = "updated"
        offer.save()  # not finalized → no guard
        offer.refresh_from_db()
        assert offer.description == "updated"


@pytest.mark.django_db
class TestFinalizedProtected:
    """Order's MRO places FinalizedProtectedMixin before JasminModel so its
    save()/delete() overrides are invoked (the canonical pattern)."""

    def test_save_on_finalized_raises(self, tenant):
        user = JasminUserFactory()
        order = OrderFactory()
        order.finalize(user=user)

        order.note = "Changed"
        with pytest.raises(JasminError, match="finalized"):
            order.save()

    def test_save_is_finalized_field_allowed(self, tenant):
        user = JasminUserFactory()
        order = OrderFactory()
        order.finalize(user=user)

        # The finalization step itself — should work
        order.is_finalized = True
        order.save(update_fields=["is_finalized"])  # should not raise

    def test_delete_on_finalized_raises(self, tenant):
        user = JasminUserFactory()
        order = OrderFactory()
        order.finalize(user=user)

        with pytest.raises(JasminError, match="finalized"):
            order.delete()

    def test_save_on_non_finalized_works(self, tenant):
        order = OrderFactory()

        order.note = "Updated"
        order.save()  # should not raise
        order.refresh_from_db()
        assert order.note == "Updated"
