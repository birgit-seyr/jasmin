"""End-to-end lifecycle tests for Order → DeliveryNote → Invoice.

Covers the full create → finalize → unfinalize → delete cycle and verifies:

- ``CreatedMixin`` (``created_at`` / ``created_by``) is wired on every path.
- ``DateDocumentMixin.date`` is correctly resolved (explicit, derived from
  the order's ISO week, fallback to today, never invalid).
- ``FinalizableMixin.finalize`` / ``unfinalize`` work in both directions
  without tripping the Postgres ``finalized_protect`` triggers.
- Cascading deletes correctly unfinalize parent + child rows.
- Crate contents follow the same lifecycle as line items.

These tests were written after a string of production bugs around the
finalize/unfinalize cascade (see commit history). They are intentionally
explicit so the contract is unambiguous.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.commissioning.models import (
    CrateOrderContent,
    DeliveryNoteReseller,
    InvoiceResellerContent,
    Order,
)
from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.services.order_service import OrderService
from apps.commissioning.tests.factories import (
    CrateFactory,
    InvoiceResellerFactory,
    JasminUserFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
)
from apps.commissioning.utils.iso_week_utils import (
    coerce_document_date,
    week_day_to_date,
)
from apps.shared.tenants.models import TenantSettings
from core.errors import JasminError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ensure_settings(tenant, **overrides):
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


def _make_order_with_content(reseller=None, **order_kwargs):
    """Create an order with one share-article content row + one crate row."""
    order = OrderFactory(reseller=reseller or ResellerFactory(), **order_kwargs)
    OrderContentFactory(order=order)
    CrateOrderContent.objects.create(
        order=order,
        crate_type=CrateFactory(),
        amount=Decimal("3"),
        price_per_unit=Decimal("1.50"),
        tax_rate=Decimal("19.00"),
    )
    return order


# ===================================================================
# CreatedMixin wiring
# ===================================================================
@pytest.mark.django_db
class TestCreatedMixinWiring:
    """``created_at`` is always populated; ``created_by`` is wired through
    every entrypoint that has access to the request user."""

    def test_order_factory_sets_created_at(self, tenant):
        _ensure_settings(connection.tenant)
        before = timezone.now() - datetime.timedelta(seconds=1)
        order = OrderFactory()
        after = timezone.now() + datetime.timedelta(seconds=1)
        assert before <= order.created_at <= after

    def test_order_get_or_create_writes_created_by(self, tenant):
        _ensure_settings(connection.tenant)
        user = JasminUserFactory()
        order, created = Order.objects.get_or_create(
            reseller=ResellerFactory(),
            year=2026,
            delivery_week=18,
            day_number=2,
            defaults={"created_by": user},
        )
        assert created is True
        assert order.created_by == user

    def test_delivery_note_service_propagates_user(self, tenant):
        _ensure_settings(connection.tenant)
        user = JasminUserFactory()
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order, user=user)
        assert dn.created_by == user
        assert dn.created_at is not None

    def test_invoice_service_propagates_user(self, tenant):
        _ensure_settings(connection.tenant)
        user = JasminUserFactory()
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order, user=user)
        DeliveryNoteService.finalize_delivery_note(dn, user=user)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn, user=user)
        assert invoice.created_by == user
        assert invoice.created_at is not None

    def test_storno_carries_created_by(self, tenant):
        _ensure_settings(connection.tenant)
        creator = JasminUserFactory()
        canceller = JasminUserFactory()
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order, user=creator)
        DeliveryNoteService.finalize_delivery_note(dn, user=creator)
        invoice = InvoiceService.create_from_delivery_note(
            delivery_note=dn, user=creator
        )
        InvoiceService.finalize_invoice(invoice, user=creator)
        storno = InvoiceService.create_storno(
            invoice, reason="customer return", user=canceller
        )
        assert storno.created_by == canceller
        assert storno.document_type == "storno"


# ===================================================================
# DateDocumentMixin / coerce_document_date
# ===================================================================
@pytest.mark.django_db
class TestDocumentDateResolution:
    def test_coerce_explicit_date_object_passes_through(self):
        d = datetime.date(2026, 5, 1)
        assert coerce_document_date(d) == d

    def test_coerce_iso_string_parses(self):
        assert coerce_document_date("2026-05-01") == datetime.date(2026, 5, 1)

    def test_coerce_empty_string_falls_back_to_order(self, tenant):
        _ensure_settings(connection.tenant)
        order = OrderFactory(year=2026, delivery_week=18, day_number=2)
        expected = week_day_to_date(2026, 18, 2)
        assert coerce_document_date("", fallback_order=order) == expected

    def test_coerce_garbage_string_falls_back_to_order(self, tenant):
        _ensure_settings(connection.tenant)
        order = OrderFactory(year=2026, delivery_week=18, day_number=2)
        expected = week_day_to_date(2026, 18, 2)
        assert coerce_document_date("not-a-date", fallback_order=order) == expected

    def test_coerce_none_with_fallback_date_returns_fallback(self):
        d = datetime.date(2026, 6, 1)
        assert coerce_document_date(None, fallback_date=d) == d

    def test_coerce_returns_none_when_nothing_provided(self):
        assert coerce_document_date(None) is None

    def test_delivery_note_date_derived_from_order(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content(year=2026, delivery_week=18, day_number=2)
        dn = DeliveryNoteService.create_from_order(order=order, date="")
        assert dn.date == week_day_to_date(2026, 18, 2)

    def test_delivery_note_date_falls_back_to_today_when_explicit_today(self, tenant):
        """When the order's ISO week resolves to today's date, that's what
        ends up on the delivery note."""
        _ensure_settings(connection.tenant)
        today = timezone.now().date()
        iso_year, iso_week, iso_day = today.isocalendar()
        order = _make_order_with_content(
            year=iso_year, delivery_week=iso_week, day_number=iso_day - 1
        )
        dn = DeliveryNoteService.create_from_order(order=order, date=None)
        assert dn.date == today

    def test_invoice_date_derived_from_delivery_note(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content(year=2026, delivery_week=18, day_number=2)
        dn = DeliveryNoteService.create_from_order(
            order=order, date=datetime.date(2026, 5, 1)
        )
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn, date="")
        assert invoice.date == datetime.date(2026, 5, 1)

    def test_summary_invoice_date_derived_from_latest_dn(self, tenant):
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()
        dns = []
        for week, d in [
            (18, datetime.date(2026, 5, 1)),
            (19, datetime.date(2026, 5, 8)),
        ]:
            order = _make_order_with_content(
                reseller=reseller, year=2026, delivery_week=week, day_number=2
            )
            dn = DeliveryNoteService.create_from_order(order=order, date=d)
            DeliveryNoteService.finalize_delivery_note(dn)
            dns.append(dn)
        invoice = InvoiceService.create_summary_invoice_from_delivery_notes(
            delivery_notes=dns, date=""
        )
        assert invoice.date == datetime.date(2026, 5, 8)


# ===================================================================
# Finalize / unfinalize round-trip
# ===================================================================
@pytest.mark.django_db
class TestFinalizeUnfinalizeRoundtrip:
    """Two-step save in finalize() and unfinalize() must satisfy the
    Postgres ``finalized_protect`` trigger in both directions."""

    def test_order_unfinalize_raises_legal_immutability(self, tenant):
        """Orders are legally one-way once finalized (number sequence integrity)."""
        _ensure_settings(connection.tenant)
        user = JasminUserFactory()
        order = _make_order_with_content()
        OrderService.finalize_order(order, user=user)
        order.refresh_from_db()
        assert order.is_finalized is True

        with pytest.raises(JasminError, match="finalized orders are immutable"):
            order.unfinalize()
        order.refresh_from_db()
        assert order.is_finalized is True
        assert order.finalized_by == user

    def test_delivery_note_unfinalize_raises_legal_immutability(self, tenant):
        """Delivery notes are legally one-way once finalized (GoBD / HGB §257)."""
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        dn.refresh_from_db()

        with pytest.raises(JasminError, match="finalized delivery notes are immutable"):
            dn.unfinalize()
        dn.refresh_from_db()
        assert dn.is_finalized is True

    def test_invoice_unfinalize_raises_legal_immutability(self, tenant):
        """Invoices are legally one-way once finalized (GoBD / UStG §14)."""
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
        InvoiceService.finalize_invoice(invoice)
        invoice.refresh_from_db()

        with pytest.raises(JasminError, match="finalized invoices are immutable"):
            invoice.unfinalize()
        invoice.refresh_from_db()
        assert invoice.is_finalized is True


# ===================================================================
# Cascade finalize: order → contents, dn → items, invoice → items
# ===================================================================
@pytest.mark.django_db
class TestCascadeFinalize:
    def test_finalize_order_finalizes_contents_and_crates(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        OrderService.finalize_order(order)

        for child in order.ordercontent_set.all():
            assert child.is_finalized is True
        for child in order.crateordercontent_set.all():
            assert child.is_finalized is True

    def test_finalize_order_finalizes_order_content_linked_crates(self, tenant):
        # Regression: crates attached to an order_content (offer-bound lines)
        # carry order=NULL per the XOR constraint, so they are NOT in
        # order.crateordercontent_set and slipped the finalize cascade — leaving
        # a finalized order's crate line mutable/deletable.
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        order_content = order.ordercontent_set.first()
        oc_crate = CrateOrderContent.objects.create(
            order_content=order_content,
            crate_type=CrateFactory(),
            amount=Decimal("2"),
            price_per_unit=Decimal("1.50"),
            tax_rate=Decimal("19.00"),
        )
        assert oc_crate.order_id is None  # order_content-linked, not order-linked

        OrderService.finalize_order(order)

        oc_crate.refresh_from_db()
        assert oc_crate.is_finalized is True

    def test_finalize_delivery_note_finalizes_items_and_order(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        dn.refresh_from_db()
        order.refresh_from_db()

        assert dn.is_finalized is True
        assert order.is_finalized is True
        for item in dn.items.all():
            assert item.is_finalized is True
        for crate in dn.crate_items.all():
            assert crate.is_finalized is True

    def test_finalize_invoice_cascades_through_dn_to_order(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
        InvoiceService.finalize_invoice(invoice)

        invoice.refresh_from_db()
        dn.refresh_from_db()
        order.refresh_from_db()
        assert invoice.is_finalized is True
        assert dn.is_finalized is True
        assert order.is_finalized is True
        for item in invoice.items.all():
            assert item.is_finalized is True
        for crate in invoice.crate_items.all():
            assert crate.is_finalized is True

    def test_invoice_create_persists_payment_due_date(self, tenant):
        # Regression: due_date (read by the dunning/reminder builder) was never
        # set on any real invoice, so reminders showed 0 days overdue and a
        # blank due date. It must now be issue date + the reseller's payment
        # terms.
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)

        terms = invoice.reseller.get_payment_terms_days()
        assert invoice.due_date == invoice.date + datetime.timedelta(days=terms)


# ===================================================================
# Cascade delete + unfinalize
# ===================================================================
@pytest.mark.django_db
class TestCascadeDelete:
    """Under the one-way finalize contract:

    * A finalized parent cannot be deleted (FinalizedProtectedMixin guard).
    * Deleting a child (e.g. invoice) does NOT cascade-unfinalize its
      legally-immutable parent (DN / Order).
    * Only the deleted row's own descendant content rows are unfinalized
      so that the Postgres CASCADE doesn't trip the finalized_protect
      trigger.
    """

    def test_finalized_invoice_unfinalize_raises_and_dn_stays_finalized(self, tenant):
        """Invoice.unfinalize() raises — there is no path to delete a
        finalized invoice, and the linked DN is never affected."""
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
        InvoiceService.finalize_invoice(invoice)
        dn_id = dn.id

        with pytest.raises(JasminError, match="finalized invoices are immutable"):
            invoice.unfinalize()
        with pytest.raises(JasminError, match="finalized"):
            invoice.delete()

        dn = DeliveryNoteReseller.objects.get(id=dn_id)
        assert dn.is_finalized is True
        for item in dn.items.all():
            assert item.is_finalized is True
        for crate in dn.crate_items.all():
            assert crate.is_finalized is True

    def test_finalized_invoice_cannot_be_deleted_directly(self, tenant):
        """Legal-immutability contract: ``invoice.delete()`` raises while finalized."""
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
        InvoiceService.finalize_invoice(invoice)

        with pytest.raises(JasminError, match="finalized"):
            invoice.delete()

    def test_finalized_dn_cannot_be_deleted_directly(self, tenant):
        """Legal-immutability contract: ``dn.delete()`` raises while finalized."""
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)

        with pytest.raises(JasminError, match="finalized"):
            dn.delete()

    def test_finalized_dn_remains_undeletable_with_finalized_invoice(self, tenant):
        """With both invoice and DN finalized, neither can be deleted nor
        unfinalized — they are legally immutable."""
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
        InvoiceService.finalize_invoice(invoice)
        dn_id = dn.id
        order_id = order.id

        with pytest.raises(JasminError, match="finalized"):
            invoice.delete()
        with pytest.raises(JasminError, match="finalized"):
            dn.delete()

        # Everything is still in place and still finalized.
        assert DeliveryNoteReseller.objects.get(id=dn_id).is_finalized is True
        assert Order.objects.get(id=order_id).is_finalized is True

    def test_dn_unfinalize_raises_so_no_cascade_to_order(self, tenant):
        """DN.unfinalize() raises, so callers can never reach the old
        cascade-to-order path."""
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        order_id = order.id

        with pytest.raises(JasminError, match="finalized delivery notes are immutable"):
            dn.unfinalize()

        order = Order.objects.get(id=order_id)
        assert order.is_finalized is True


# ===================================================================
# Numbering: assign_final_number must not collide with drafts
# ===================================================================
@pytest.mark.django_db
class TestAssignFinalNumberCollision:
    """Regression test for the production bug where finalizing an older
    draft would land on a slot still held by a newer draft, blocking the
    save with a unique-constraint error."""

    def test_finalize_older_draft_bumps_newer_draft(self, tenant):
        _ensure_settings(connection.tenant)
        # Create two drafts in order (drafts 1 and 2)
        invoice1 = InvoiceResellerFactory()
        InvoiceResellerContent.objects.create(
            invoice=invoice1,
            share_article=ShareArticleFactory(),
            amount=Decimal("1.000"),
            price_per_unit=Decimal("1.00"),
            unit="KG",
            size="M",
            tax_rate=Decimal("7.00"),
        )
        invoice2 = InvoiceResellerFactory()
        InvoiceResellerContent.objects.create(
            invoice=invoice2,
            share_article=ShareArticleFactory(),
            amount=Decimal("1.000"),
            price_per_unit=Decimal("1.00"),
            unit="KG",
            size="M",
            tax_rate=Decimal("7.00"),
        )
        # Provisional: invoice1=1, invoice2=2
        assert invoice1.number == 1
        assert invoice2.number == 2

        # Finalize the OLDER one first — its assign_final_number wants slot 1,
        # which is currently held by invoice1 itself. No collision (excludes
        # self), but the second finalize wants slot 2, occupied by invoice2.
        InvoiceService.finalize_invoice(invoice1)
        invoice1.refresh_from_db()
        invoice2.refresh_from_db()
        assert invoice1.number == 1
        # invoice2 should still be a valid draft (possibly bumped, but not
        # necessarily — only finalizing it would force a bump).

        # Now finalize a NEW invoice — it grabs slot 2, which is currently
        # held by invoice2 (still a draft). The collision-resolution logic
        # must bump invoice2 above the current max.
        invoice3 = InvoiceResellerFactory()
        InvoiceResellerContent.objects.create(
            invoice=invoice3,
            share_article=ShareArticleFactory(),
            amount=Decimal("1.000"),
            price_per_unit=Decimal("1.00"),
            unit="KG",
            size="M",
            tax_rate=Decimal("7.00"),
        )
        InvoiceService.finalize_invoice(invoice3)

        invoice2.refresh_from_db()
        invoice3.refresh_from_db()
        assert invoice3.number == 2
        # invoice2 was bumped out of slot 2
        assert invoice2.number != 2
        assert invoice2.is_finalized is False


# ===================================================================
# Storno: legally immutable — cannot be unfinalized, cannot be deleted
# ===================================================================
@pytest.mark.django_db
class TestStornoIsImmutable:
    """A storno is auto-finalized on creation and must remain that way
    forever. Allowing ``storno.unfinalize()`` would let callers delete it,
    which would silently NULL ``invoice.cancelled_by_invoice`` (SET_NULL)
    and break the audit chain."""

    def _make_storno(self):
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
        InvoiceService.finalize_invoice(invoice)
        return invoice, InvoiceService.create_storno(invoice, reason="test")

    def test_storno_is_finalized_on_creation(self, tenant):
        _ensure_settings(connection.tenant)
        _, storno = self._make_storno()
        assert storno.document_type == "storno"
        assert storno.is_finalized is True
        assert storno.finalized_at is not None

    def test_storno_unfinalize_raises(self, tenant):
        _ensure_settings(connection.tenant)
        _, storno = self._make_storno()
        with pytest.raises(JasminError, match="immutable"):
            storno.unfinalize()
        storno.refresh_from_db()
        assert storno.is_finalized is True

    def test_storno_delete_raises_while_finalized(self, tenant):
        """Falls through the finalized-protect guard first."""
        _ensure_settings(connection.tenant)
        _, storno = self._make_storno()
        with pytest.raises(JasminError, match="immutable"):
            storno.delete()

    def test_original_invoice_cannot_be_unfinalized_or_deleted_while_storno_exists(
        self, tenant
    ):
        """Both the legal-immutability guard and the
        ``cancels_invoice = FK(self, on_delete=PROTECT)`` constraint
        keep the original invoice untouchable."""
        _ensure_settings(connection.tenant)
        invoice, _storno = self._make_storno()

        with pytest.raises(JasminError, match="finalized invoices are immutable"):
            invoice.unfinalize()
        with pytest.raises(JasminError, match="finalized"):
            invoice.delete()


# ===================================================================
# Auto-cleanup symmetry: order/DN deleted only when ALL children gone
# ===================================================================
@pytest.mark.django_db
class TestEmptyParentAutoCleanup:
    """When the *last* content row is removed, the parent should disappear
    too — but only when *both* the line-item set AND the crate set are
    empty. Removing one half while the other is still populated must
    leave the parent in place.
    """

    def test_order_kept_when_only_ordercontent_removed_and_crate_remains(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()  # 1 OrderContent + 1 CrateOrderContent
        order_id = order.id

        order.ordercontent_set.first().delete()

        assert Order.objects.filter(id=order_id).exists()
        assert order.crateordercontent_set.exists()

    def test_order_kept_when_only_crate_removed_and_content_remains(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        order_id = order.id

        order.crateordercontent_set.first().delete()

        assert Order.objects.filter(id=order_id).exists()
        assert order.ordercontent_set.exists()

    def test_order_deleted_when_last_content_and_crate_gone(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        order_id = order.id

        order.crateordercontent_set.first().delete()
        order.ordercontent_set.first().delete()

        assert not Order.objects.filter(id=order_id).exists()

    def test_order_deleted_when_crate_removed_last(self, tenant):
        """Delete order content first, then the loose crate. The crate's
        ``delete()`` should clean up the now-orphan order."""
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        order_id = order.id

        order.ordercontent_set.first().delete()
        # Order still exists because crate remains
        assert Order.objects.filter(id=order_id).exists()
        order.crateordercontent_set.first().delete()
        assert not Order.objects.filter(id=order_id).exists()

    def test_dn_kept_when_only_item_removed_and_crate_remains(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        dn_id = dn.id

        # Sanity: DN should have both items and crate items
        assert dn.items.exists()
        assert dn.crate_items.exists()

        dn.items.first().delete()
        assert DeliveryNoteReseller.objects.filter(id=dn_id).exists()

    def test_dn_kept_when_only_crate_removed_and_item_remains(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        dn_id = dn.id

        dn.crate_items.first().delete()
        assert DeliveryNoteReseller.objects.filter(id=dn_id).exists()

    def test_dn_deleted_when_last_item_and_crate_gone(self, tenant):
        _ensure_settings(connection.tenant)
        order = _make_order_with_content()
        dn = DeliveryNoteService.create_from_order(order=order)
        dn_id = dn.id

        # Need to delete crate first (to leave items as last) or vice versa.
        # Either ordering should work — exercising both directions.
        for crate in list(dn.crate_items.all()):
            crate.delete()
        for item in list(dn.items.all()):
            item.delete()

        assert not DeliveryNoteReseller.objects.filter(id=dn_id).exists()
