"""Tests for DeliveryNoteService."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.tests.factories import (
    CrateFactory,
    DeliveryNoteContentFactory,
    DeliveryNoteResellerFactory,
    JasminUserFactory,
    OrderContentFactory,
    OrderFactory,
    ShareArticleFactory,
)
from core.errors import JasminError


# ---------------------------------------------------------------------------
# create_from_order
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateFromOrder:
    def test_creates_delivery_note_from_order(self, tenant):
        order = OrderFactory()
        OrderContentFactory(order=order)

        dn = DeliveryNoteService.create_from_order(order)

        assert dn.pk is not None
        assert dn.order == order

    def test_copies_order_contents_to_delivery_note(self, tenant):
        article = ShareArticleFactory()
        order = OrderFactory()
        OrderContentFactory(order=order, share_article=article, amount=Decimal("5.000"))
        OrderContentFactory(order=order, share_article=article, amount=Decimal("3.000"))

        dn = DeliveryNoteService.create_from_order(order)

        assert dn.items.count() == 2

    def test_copies_crate_contents(self, tenant):
        from apps.commissioning.models import CrateOrderContent

        order = OrderFactory()
        OrderContentFactory(order=order)
        crate = CrateFactory()
        CrateOrderContent.objects.create(
            order=order,
            crate_type=crate,
            amount=10,
            price_per_unit=Decimal("1.00"),
            tax_rate=Decimal("19.00"),
        )

        dn = DeliveryNoteService.create_from_order(order)

        assert dn.crate_items.count() == 1

    def test_finalizes_order_on_creation(self, tenant):
        order = OrderFactory()
        OrderContentFactory(order=order)

        DeliveryNoteService.create_from_order(order)

        order.refresh_from_db()
        assert order.is_finalized is True

    def test_raises_if_delivery_note_already_exists(self, tenant):
        order = OrderFactory()
        OrderContentFactory(order=order)
        DeliveryNoteService.create_from_order(order)

        with pytest.raises(JasminError, match="already exists"):
            DeliveryNoteService.create_from_order(order)


# ---------------------------------------------------------------------------
# finalize_delivery_note
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestFinalizeDeliveryNote:
    def test_finalizes_successfully(self, tenant):
        user = JasminUserFactory()
        dn = DeliveryNoteResellerFactory()
        DeliveryNoteContentFactory(delivery_note=dn)

        result = DeliveryNoteService.finalize_delivery_note(dn, user=user)

        assert result is True
        dn.refresh_from_db()
        assert dn.is_finalized is True

    def test_raises_if_already_finalized(self, tenant):
        user = JasminUserFactory()
        dn = DeliveryNoteResellerFactory()
        DeliveryNoteContentFactory(delivery_note=dn)
        dn.finalize(user=user)

        with pytest.raises(JasminError, match="already finalized"):
            DeliveryNoteService.finalize_delivery_note(dn, user=user)

    def test_raises_if_no_items(self, tenant):
        dn = DeliveryNoteResellerFactory()

        with pytest.raises(JasminError, match="no items"):
            DeliveryNoteService.finalize_delivery_note(dn)
