"""Tests for assign_final_number, display_number, and finalization numbering.

The numbering scheme works in two phases:

1. **Provisional** — ``generate_number()`` assigns a number from
   ``MAX(number) + 1`` of *all* objects on first save.  Non-finalized
   documents display this number with a ``"v"`` suffix.

2. **Final** — ``assign_final_number()`` is called at finalization time
   and reassigns the number from ``MAX(number) + 1`` of *finalized-only*
   objects.  This guarantees a gap-free legal sequence.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection

from apps.commissioning.models import InvoiceResellerContent
from apps.commissioning.services import InvoiceService
from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.services.order_service import OrderService
from apps.commissioning.tests.factories import (
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
)
from apps.shared.tenants.models import TenantSettings
from core.errors import JasminError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ensure_settings(tenant, **overrides):
    from django.utils import timezone

    defaults = dict(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(days=365),
        valid_until=None,
    )
    defaults.update(overrides)
    settings, _ = TenantSettings.objects.get_or_create(
        tenant=tenant, valid_until=None, defaults=defaults
    )
    for k, v in overrides.items():
        setattr(settings, k, v)
    settings.save()
    return settings


def _add_invoice_item(invoice, **kwargs):
    defaults = dict(
        invoice=invoice,
        share_article=ShareArticleFactory(),
        amount=Decimal("10.000"),
        price_per_unit=Decimal("1.00"),
        unit="KG",
        size="M",
        tax_rate=Decimal("7.00"),
    )
    defaults.update(kwargs)
    return InvoiceResellerContent.objects.create(**defaults)


# ===================================================================
# display_number property
# ===================================================================
@pytest.mark.django_db
class TestDisplayNumber:
    """display_number shows 'v' suffix for provisional, plain for finalized."""

    def test_non_finalized_order_shows_v_suffix(self, tenant):
        _ensure_settings(connection.tenant)
        order = OrderFactory()
        assert order.is_finalized is False
        assert order.display_number == f"{order.number}v"

    def test_finalized_order_shows_plain_number(self, tenant):
        _ensure_settings(connection.tenant)
        order = OrderFactory()
        OrderContentFactory(order=order)
        OrderService.finalize_order(order)
        order.refresh_from_db()
        assert order.display_number == str(order.number)

    def test_non_finalized_delivery_note_shows_v_suffix(self, tenant):
        _ensure_settings(connection.tenant)
        dn = DeliveryNoteResellerFactory()
        assert dn.display_number == f"{dn.number}v"

    def test_finalized_delivery_note_shows_plain_number(self, tenant):
        _ensure_settings(connection.tenant)
        order = OrderFactory()
        OrderContentFactory(order=order)
        dn = DeliveryNoteService.create_from_order(order)
        DeliveryNoteService.finalize_delivery_note(dn)
        dn.refresh_from_db()
        assert dn.display_number == str(dn.number)

    def test_non_finalized_invoice_shows_v_suffix(self, tenant):
        _ensure_settings(connection.tenant)
        inv = InvoiceResellerFactory()
        assert inv.display_number == f"{inv.number}v"

    def test_finalized_invoice_shows_plain_number(self, tenant):
        _ensure_settings(connection.tenant)
        inv = InvoiceResellerFactory()
        _add_invoice_item(inv)
        InvoiceService.finalize_invoice(inv)
        inv.refresh_from_db()
        assert inv.display_number == str(inv.number)

    def test_display_number_without_number_shows_dash(self, tenant):
        _ensure_settings(connection.tenant)
        order = OrderFactory.build(number=None)
        assert order.display_number == "–"

    def test_str_contains_display_number(self, tenant):
        _ensure_settings(connection.tenant)
        order = OrderFactory()
        assert f"{order.number}v" in str(order)

    def test_invoice_str_contains_display_number(self, tenant):
        _ensure_settings(connection.tenant)
        inv = InvoiceResellerFactory()
        assert f"{inv.number}v" in str(inv)


# ===================================================================
# assign_final_number — basic mechanics
# ===================================================================
@pytest.mark.django_db
class TestAssignFinalNumber:
    """assign_final_number picks MAX+1 from finalized-only objects."""

    def test_first_finalized_order_gets_number_1(self, tenant):
        _ensure_settings(connection.tenant)
        order = OrderFactory()
        OrderContentFactory(order=order)
        order.assign_final_number()
        assert order.number == 1

    def test_skips_non_finalized_when_computing_max(self, tenant):
        """Non-finalized orders should not affect the final numbering."""
        _ensure_settings(connection.tenant)
        # Create 5 non-finalized orders (they get provisional 1..5)
        for _ in range(5):
            OrderFactory()

        # Finalize the 6th order — should get final number 1, not 6
        order = OrderFactory()
        OrderContentFactory(order=order)
        OrderService.finalize_order(order)
        order.refresh_from_db()
        assert order.number == 1

    def test_sequential_finalization(self, tenant):
        """Finalizing objects in order gives sequential numbers."""
        _ensure_settings(connection.tenant)
        orders = []
        for _ in range(3):
            o = OrderFactory()
            OrderContentFactory(order=o)
            orders.append(o)

        for i, o in enumerate(orders, start=1):
            OrderService.finalize_order(o)
            o.refresh_from_db()
            assert o.number == i

    def test_out_of_order_finalization(self, tenant):
        """Finalizing in non-creation order still gives sequential numbers."""
        _ensure_settings(connection.tenant)
        o1 = OrderFactory()
        OrderContentFactory(order=o1)
        o2 = OrderFactory()
        OrderContentFactory(order=o2)
        o3 = OrderFactory()
        OrderContentFactory(order=o3)

        # Finalize in reverse: o3, o1, o2
        OrderService.finalize_order(o3)
        o3.refresh_from_db()
        assert o3.number == 1

        OrderService.finalize_order(o1)
        o1.refresh_from_db()
        assert o1.number == 2

        OrderService.finalize_order(o2)
        o2.refresh_from_db()
        assert o2.number == 3

    def test_deleted_non_finalized_causes_no_gap(self, tenant):
        """Deleting a non-finalized document doesn't create gaps."""
        _ensure_settings(connection.tenant)
        o1 = OrderFactory()
        OrderContentFactory(order=o1)
        o2 = OrderFactory()  # provisional number 2
        o3 = OrderFactory()
        OrderContentFactory(order=o3)

        # Delete o2 (non-finalized)
        o2.delete()

        # Finalize o1 and o3
        OrderService.finalize_order(o1)
        o1.refresh_from_db()
        assert o1.number == 1

        OrderService.finalize_order(o3)
        o3.refresh_from_db()
        assert o3.number == 2  # no gap!

    def test_provisional_number_changes_on_finalization(self, tenant):
        """The provisional number may differ from the final number."""
        _ensure_settings(connection.tenant)
        o1 = OrderFactory()  # provisional 1
        OrderContentFactory(order=o1)
        o2 = OrderFactory()  # provisional 2
        OrderContentFactory(order=o2)

        provisional_o2 = o2.number
        assert provisional_o2 == 2

        # Finalize only o2 (skip o1)
        OrderService.finalize_order(o2)
        o2.refresh_from_db()
        # Final number is 1 (first finalized object)
        assert o2.number == 1


# ===================================================================
# assign_final_number — delivery notes
# ===================================================================
@pytest.mark.django_db
class TestAssignFinalNumberDeliveryNote:
    def test_delivery_note_final_number_ignores_non_finalized(self, tenant):
        _ensure_settings(connection.tenant)
        # Create several non-finalized DNs
        for _ in range(3):
            DeliveryNoteResellerFactory()

        order = OrderFactory()
        OrderContentFactory(order=order)
        dn = DeliveryNoteService.create_from_order(order)
        DeliveryNoteService.finalize_delivery_note(dn)
        dn.refresh_from_db()
        assert dn.number == 1

    def test_delivery_note_sequential_finalization(self, tenant):
        _ensure_settings(connection.tenant)
        dns = []
        for _ in range(3):
            o = OrderFactory()
            OrderContentFactory(order=o)
            dn = DeliveryNoteService.create_from_order(o)
            dns.append(dn)

        for i, dn in enumerate(dns, start=1):
            DeliveryNoteService.finalize_delivery_note(dn)
            dn.refresh_from_db()
            assert dn.number == i


# ===================================================================
# assign_final_number — invoices
# ===================================================================
@pytest.mark.django_db
class TestAssignFinalNumberInvoice:
    def test_invoice_final_number_ignores_non_finalized(self, tenant):
        _ensure_settings(connection.tenant)
        # Create several non-finalized invoices
        for _ in range(4):
            inv = InvoiceResellerFactory()
            _add_invoice_item(inv)

        # Finalize only the 5th
        inv5 = InvoiceResellerFactory()
        _add_invoice_item(inv5)
        InvoiceService.finalize_invoice(inv5)
        inv5.refresh_from_db()
        assert inv5.number == 1

    def test_invoice_sequential_finalization(self, tenant):
        _ensure_settings(connection.tenant)
        invoices = []
        for _ in range(3):
            inv = InvoiceResellerFactory()
            _add_invoice_item(inv)
            invoices.append(inv)

        for i, inv in enumerate(invoices, start=1):
            InvoiceService.finalize_invoice(inv)
            inv.refresh_from_db()
            assert inv.number == i

    def test_deleted_draft_invoice_no_gap(self, tenant):
        """Deleting a draft invoice doesn't cause gaps in final numbering."""
        _ensure_settings(connection.tenant)
        inv1 = InvoiceResellerFactory()
        _add_invoice_item(inv1)
        inv2 = InvoiceResellerFactory()
        _add_invoice_item(inv2)
        inv3 = InvoiceResellerFactory()
        _add_invoice_item(inv3)

        # Delete the middle draft
        inv2.delete()

        InvoiceService.finalize_invoice(inv1)
        inv1.refresh_from_db()
        assert inv1.number == 1

        InvoiceService.finalize_invoice(inv3)
        inv3.refresh_from_db()
        assert inv3.number == 2  # no gap

    def test_storno_gets_separate_sequence(self, tenant):
        """Storno numbers are separate from regular invoice numbers."""
        _ensure_settings(connection.tenant)
        inv = InvoiceResellerFactory()
        _add_invoice_item(inv)
        InvoiceService.finalize_invoice(inv)
        inv.refresh_from_db()
        assert inv.number == 1

        storno = InvoiceService.create_storno(inv, reason="test")
        storno.refresh_from_db()
        # Storno should be 1 in its own sequence, not 2
        assert storno.number == 1
        assert storno.document_type == "storno"

    def test_multiple_stornos_sequential(self, tenant):
        """Multiple stornos get their own sequential numbers."""
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()

        inv1 = InvoiceResellerFactory(reseller=reseller)
        _add_invoice_item(inv1)
        InvoiceService.finalize_invoice(inv1)
        inv1.refresh_from_db()

        inv2 = InvoiceResellerFactory(reseller=reseller)
        _add_invoice_item(inv2)
        InvoiceService.finalize_invoice(inv2)
        inv2.refresh_from_db()

        storno1 = InvoiceService.create_storno(inv1, reason="test1")
        storno1.refresh_from_db()
        assert storno1.number == 1

        storno2 = InvoiceService.create_storno(inv2, reason="test2")
        storno2.refresh_from_db()
        assert storno2.number == 2

        # Regular invoices untouched
        assert inv1.number == 1
        assert inv2.number == 2

    def test_invoice_without_items_cannot_be_finalized(self, tenant):
        _ensure_settings(connection.tenant)
        inv = InvoiceResellerFactory()
        with pytest.raises(JasminError, match="no items"):
            InvoiceService.finalize_invoice(inv)

    def test_already_finalized_raises(self, tenant):
        _ensure_settings(connection.tenant)
        inv = InvoiceResellerFactory()
        _add_invoice_item(inv)
        InvoiceService.finalize_invoice(inv)
        with pytest.raises(JasminError, match="already finalized"):
            InvoiceService.finalize_invoice(inv)


# ===================================================================
# Year-based numbering with assign_final_number
# ===================================================================
@pytest.mark.django_db
class TestYearBasedFinalNumber:
    def test_year_based_order_final_number_resets(self, tenant):
        """Year-based numbering resets the final count per year."""
        _ensure_settings(
            connection.tenant,
            order_numbers_start_new_at_year_change=True,
            order_number_prefix="BE",
        )
        o2025 = OrderFactory(year=2025)
        OrderContentFactory(order=o2025)
        OrderService.finalize_order(o2025)
        o2025.refresh_from_db()
        assert o2025.number == 1
        assert o2025.prefix == "BE-2025"

        o2026 = OrderFactory(year=2026)
        OrderContentFactory(order=o2026)
        OrderService.finalize_order(o2026)
        o2026.refresh_from_db()
        assert o2026.number == 1  # reset for new year
        assert o2026.prefix == "BE-2026"

    def test_year_based_empty_prefix_does_not_collide_cross_year(self, tenant):
        """DOC-1: year-reset with an EMPTY base prefix must still yield a
        year-distinct prefix (the year itself), so 2026's number=1 doesn't
        collide with 2025's on UNIQUE(prefix, number) at create."""
        _ensure_settings(
            connection.tenant,
            order_numbers_start_new_at_year_change=True,
            order_number_prefix="",  # empty base prefix — the armed case
        )
        o2025 = OrderFactory(year=2025)
        OrderContentFactory(order=o2025)
        OrderService.finalize_order(o2025)
        o2025.refresh_from_db()
        assert o2025.prefix == "2025"  # the year IS the prefix
        assert o2025.number == 1

        # Without the fix, this create raised IntegrityError ((prefix='', 1)
        # already exists from 2025).
        o2026 = OrderFactory(year=2026)
        OrderContentFactory(order=o2026)
        OrderService.finalize_order(o2026)
        o2026.refresh_from_db()
        assert o2026.prefix == "2026"
        assert o2026.number == 1
        assert (o2025.prefix, o2025.number) != (o2026.prefix, o2026.number)

    def test_year_based_invoice_final_number_resets(self, tenant):
        _ensure_settings(
            connection.tenant,
            invoice_numbers_start_new_at_year_change=True,
            invoice_number_prefix="RE",
        )
        inv1 = InvoiceResellerFactory(date=datetime.date(2025, 12, 1))
        _add_invoice_item(inv1)
        InvoiceService.finalize_invoice(inv1)
        inv1.refresh_from_db()
        assert inv1.number == 1
        assert inv1.prefix == "RE-2025"

        inv2 = InvoiceResellerFactory(date=datetime.date(2026, 1, 15))
        _add_invoice_item(inv2)
        InvoiceService.finalize_invoice(inv2)
        inv2.refresh_from_db()
        assert inv2.number == 1  # reset
        assert inv2.prefix == "RE-2026"

    def test_year_based_final_number_only_counts_finalized(self, tenant):
        """Non-finalized docs in the same year don't affect final sequence."""
        _ensure_settings(
            connection.tenant,
            order_numbers_start_new_at_year_change=True,
            order_number_prefix="BE",
        )
        # 3 non-finalized orders in 2026
        for _ in range(3):
            OrderFactory(year=2026)

        o = OrderFactory(year=2026)
        OrderContentFactory(order=o)
        OrderService.finalize_order(o)
        o.refresh_from_db()
        assert o.number == 1  # ignores non-finalized

    def test_year_based_delivery_note_final_number_resets(self, tenant):
        _ensure_settings(
            connection.tenant,
            delivery_note_numbers_start_new_at_year_change=True,
            delivery_note_number_prefix="LS",
        )
        o1 = OrderFactory()
        OrderContentFactory(order=o1)
        dn1 = DeliveryNoteService.create_from_order(o1)
        dn1.date = datetime.date(2025, 11, 1)
        dn1.save(update_fields=["date"])
        DeliveryNoteService.finalize_delivery_note(dn1)
        dn1.refresh_from_db()
        assert dn1.number == 1
        assert dn1.prefix == "LS-2025"

        o2 = OrderFactory()
        OrderContentFactory(order=o2)
        dn2 = DeliveryNoteService.create_from_order(o2)
        dn2.date = datetime.date(2026, 1, 5)
        dn2.save(update_fields=["date"])
        DeliveryNoteService.finalize_delivery_note(dn2)
        dn2.refresh_from_db()
        assert dn2.number == 1  # reset
        assert dn2.prefix == "LS-2026"


# ===================================================================
# Prefix handling
# ===================================================================
@pytest.mark.django_db
class TestPrefixOnFinalization:
    def test_prefix_applied_at_finalization(self, tenant):
        _ensure_settings(connection.tenant, order_number_prefix="BE")
        order = OrderFactory()
        OrderContentFactory(order=order)
        OrderService.finalize_order(order)
        order.refresh_from_db()
        assert order.prefix == "BE"

    def test_invoice_prefix_applied_at_finalization(self, tenant):
        _ensure_settings(connection.tenant, invoice_number_prefix="RE")
        inv = InvoiceResellerFactory()
        _add_invoice_item(inv)
        InvoiceService.finalize_invoice(inv)
        inv.refresh_from_db()
        assert inv.prefix == "RE"


# ===================================================================
# Edge cases — interplay between provisional and final numbers
# ===================================================================
@pytest.mark.django_db
class TestProvisionalVsFinalInterplay:
    def test_provisional_numbers_do_not_pollute_final_sequence(self, tenant):
        """Even with many provisionals, final sequence starts at 1."""
        _ensure_settings(connection.tenant)
        # Create 10 provisionals with numbers 1..10
        for _ in range(10):
            OrderFactory()

        o = OrderFactory()
        OrderContentFactory(order=o)
        assert o.number == 11  # provisional

        OrderService.finalize_order(o)
        o.refresh_from_db()
        assert o.number == 1  # final — ignores all 10 non-finalized

    def test_finalize_then_create_provisional(self, tenant):
        """Provisionals created after a finalized doc continue from all objects."""
        _ensure_settings(connection.tenant)
        o1 = OrderFactory()  # provisional 1
        OrderContentFactory(order=o1)
        OrderService.finalize_order(o1)
        o1.refresh_from_db()
        assert o1.number == 1

        o2 = OrderFactory()  # provisional — MAX of all=1, so gets 2
        assert o2.number == 2

    def test_mixed_finalized_and_provisional(self, tenant):
        """Final numbers form a clean sequence regardless of provisionals."""
        _ensure_settings(connection.tenant)

        o1 = OrderFactory()  # prov 1
        OrderContentFactory(order=o1)
        o2 = OrderFactory()  # prov 2
        OrderContentFactory(order=o2)
        o3 = OrderFactory()  # prov 3
        OrderContentFactory(order=o3)

        # Finalize o2 first
        OrderService.finalize_order(o2)
        o2.refresh_from_db()
        assert o2.number == 1  # first finalized → 1

        # Create another provisional
        _o4 = OrderFactory()  # prov 4

        # Finalize o3
        OrderService.finalize_order(o3)
        o3.refresh_from_db()
        assert o3.number == 2  # second finalized → 2

        # o1 and o4 remain non-finalized, their numbers don't matter for the sequence
        OrderService.finalize_order(o1)
        o1.refresh_from_db()
        assert o1.number == 3  # third finalized → 3


# ===================================================================
# Cascading finalization — number assignment
# ===================================================================
@pytest.mark.django_db
class TestCascadingFinalization:
    def test_invoice_finalization_cascades_to_dn_and_order(self, tenant):
        """Finalizing an invoice cascades and assigns final numbers to DN and order."""
        _ensure_settings(connection.tenant)
        order = OrderFactory()
        OrderContentFactory(order=order)
        dn = DeliveryNoteService.create_from_order(order)
        inv = InvoiceService.create_from_delivery_note(dn)

        # create_from_order auto-finalizes the order; create_from_delivery_note
        # cascade-finalizes the DN (see InvoiceService.create_from_delivery_note).
        order.refresh_from_db()
        dn.refresh_from_db()
        assert order.is_finalized
        assert dn.is_finalized
        assert not inv.is_finalized

        InvoiceService.finalize_invoice(inv)

        inv.refresh_from_db()
        dn.refresh_from_db()
        order.refresh_from_db()

        assert inv.is_finalized
        assert dn.is_finalized
        assert order.is_finalized

        # All should have final number 1 (first finalized in each sequence)
        assert inv.number == 1
        assert dn.number == 1
        assert order.number == 1

    def test_dn_finalization_cascades_to_order(self, tenant):
        """Finalizing a DN cascades to its order."""
        _ensure_settings(connection.tenant)
        order = OrderFactory()
        OrderContentFactory(order=order)
        dn = DeliveryNoteService.create_from_order(order)

        DeliveryNoteService.finalize_delivery_note(dn)

        dn.refresh_from_db()
        order.refresh_from_db()

        assert dn.is_finalized
        assert order.is_finalized
        assert dn.number == 1
        assert order.number == 1


# ===================================================================
# No tenant settings fallback
# ===================================================================
@pytest.mark.django_db
class TestNoTenantSettings:
    def test_assign_final_number_without_settings(self, tenant):
        """Works without TenantSettings — falls back to simple MAX+1."""
        TenantSettings.objects.filter(tenant=connection.tenant).delete()
        order = OrderFactory()
        OrderContentFactory(order=order)
        order.assign_final_number()
        assert order.number == 1

    def test_sequential_without_settings(self, tenant):
        TenantSettings.objects.filter(tenant=connection.tenant).delete()
        o1 = OrderFactory()
        OrderContentFactory(order=o1)
        OrderService.finalize_order(o1)
        o1.refresh_from_db()

        o2 = OrderFactory()
        OrderContentFactory(order=o2)
        OrderService.finalize_order(o2)
        o2.refresh_from_db()

        assert o1.number == 1
        assert o2.number == 2


# ===================================================================
# Idempotency
# ===================================================================
@pytest.mark.django_db
class TestIdempotency:
    def test_generate_number_idempotent(self, tenant):
        """Calling generate_number twice doesn't change the number."""
        _ensure_settings(connection.tenant)
        order = OrderFactory()
        first = order.number
        order.generate_number()
        assert order.number == first

    def test_assign_final_number_overwrites_provisional(self, tenant):
        """assign_final_number always reassigns even if number already set."""
        _ensure_settings(connection.tenant)
        # Create 5 orders, then assign_final_number on the 5th
        for _ in range(4):
            OrderFactory()
        o = OrderFactory()  # provisional = 5
        assert o.number == 5
        o.assign_final_number()
        assert o.number == 1  # first finalized

    def test_finalized_invoice_cannot_be_finalized_again(self, tenant):
        _ensure_settings(connection.tenant)
        inv = InvoiceResellerFactory()
        _add_invoice_item(inv)
        InvoiceService.finalize_invoice(inv)
        with pytest.raises(JasminError, match="already finalized"):
            InvoiceService.finalize_invoice(inv)
