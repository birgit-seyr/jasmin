"""Tests for the storno audit-chain integrity rules and the
"no insert into a finalized parent" gap.

Storno-chain rules (enforced by
:meth:`apps.commissioning.models.resellers.InvoiceReseller.can_be_cancelled`
+ ``InvoiceReseller.clean()``):

* No double storno — each invoice can be cancelled at most once.
* No storno of a storno — the audit chain is one level deep.
* No storno of a draft (unfinalized) invoice — drafts are simply deleted.
* No storno of an already-cancelled invoice — even if you somehow
  retain a stale reference.
* No storno of a correction document.
* No self-cancellation (already in ``clean()``).

Insert-into-finalized-parent rule (enforced by
``FinalizedProtectedMixin.PARENT_FK_FIELDS``):

* You cannot ``Model.objects.create(parent=finalized_parent, ...)``
  for any of the 6 content models. The Postgres ``finalized_protect``
  trigger only catches UPDATE/DELETE — INSERT is closed at the Python
  layer.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateOrderContent,
    DeliveryNoteContent,
    InvoiceReseller,
    InvoiceResellerContent,
    OrderContent,
)
from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.tests.factories import (
    CrateFactory,
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
def _ensure_settings(tenant):
    TenantSettings.objects.get_or_create(
        tenant=tenant,
        valid_until=None,
        defaults=dict(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(days=365),
            valid_until=None,
        ),
    )


def _make_simple_order(reseller=None, week=15):
    """One article line + one crate line so every cascade level has both."""
    order = OrderFactory(
        reseller=reseller or ResellerFactory(),
        year=2026,
        delivery_week=week,
        day_number=2,
    )
    OrderContentFactory(
        order=order,
        share_article=ShareArticleFactory(),
        amount=Decimal("2"),
        price_per_unit=Decimal("3.00"),
        tax_rate=Decimal("7"),
        unit="KG",
        size="M",
    )
    CrateOrderContent.objects.create(
        order=order,
        crate_type=CrateFactory(),
        amount=2,
        price_per_unit=Decimal("1.50"),
        tax_rate=Decimal("19"),
    )
    return order


def _make_finalized_invoice(reseller=None, week=15) -> InvoiceReseller:
    order = _make_simple_order(reseller=reseller, week=week)
    dn = DeliveryNoteService.create_from_order(order=order)
    DeliveryNoteService.finalize_delivery_note(dn)
    invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
    InvoiceService.finalize_invoice(invoice)
    invoice.refresh_from_db()
    return invoice


# ===================================================================
# Storno chain integrity
# ===================================================================
@pytest.mark.django_db
class TestStornoChainIntegrity:
    """An invoice can be cancelled at most once. The cancellation
    document (storno) is itself immutable. There is no chain — every
    storno points back at exactly one regular invoice."""

    def test_double_storno_is_refused(self, tenant):
        """The same invoice cannot be stornoed twice."""
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()

        first = InvoiceService.create_storno(invoice, reason="first storno")
        invoice.refresh_from_db()
        assert invoice.cancelled_by_invoice_id == first.id
        assert invoice.can_be_cancelled() is False

        with pytest.raises(JasminError, match="cannot be cancelled"):
            InvoiceService.create_storno(invoice, reason="second storno")

        # And no second cancelled_by_invoice was set under the hood.
        invoice.refresh_from_db()
        assert invoice.cancelled_by_invoice_id == first.id

    def test_db_backstop_blocks_a_second_storno(self, tenant):
        """Belt-and-suspenders for the ``select_for_update`` re-check in
        ``create_storno``: the partial UNIQUE constraint on
        ``cancels_invoice`` (document_type='storno') makes a second storno
        for the same invoice impossible even via a write path that skips
        the service-level ``can_be_cancelled()`` guard — so a concurrent
        double reversal cannot slip through.
        """
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()

        first = InvoiceService.create_storno(invoice, reason="first storno")
        assert first.document_type == "storno"

        # Forge a second storno directly via the ORM, bypassing
        # can_be_cancelled(). The uniqueness guard must refuse it.
        with pytest.raises((IntegrityError, ValidationError)):
            with transaction.atomic():
                InvoiceReseller.objects.create(
                    reseller=invoice.reseller,
                    document_type="storno",
                    cancels_invoice=invoice,
                    correction_reason="forged duplicate",
                    date=timezone.localdate(),
                )

    def test_storno_of_storno_is_refused(self, tenant):
        """A storno is not itself a regular invoice and cannot be cancelled."""
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()
        storno = InvoiceService.create_storno(invoice, reason="r")

        # Service-layer guard.
        assert storno.can_be_cancelled() is False
        with pytest.raises(JasminError, match="cannot be cancelled"):
            InvoiceService.create_storno(storno, reason="storno-of-storno")

        # Defence in depth: even constructing one manually trips clean().
        with pytest.raises(JasminError, match="Cannot storno a storno"):
            invalid = InvoiceReseller(
                reseller=invoice.reseller,
                document_type="storno",
                cancels_invoice=storno,
            )
            invalid.full_clean()

    def test_storno_of_draft_is_refused(self, tenant):
        """Drafts have no audit weight — delete them, don't storno them."""
        _ensure_settings(connection.tenant)
        order = _make_simple_order()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        draft = InvoiceService.create_from_delivery_note(delivery_note=dn)
        # Deliberately NOT finalized.
        assert draft.is_finalized is False

        assert draft.can_be_cancelled() is False
        with pytest.raises(JasminError, match="cannot be cancelled"):
            InvoiceService.create_storno(draft, reason="cancel a draft")

    def test_storno_of_correction_is_refused(self, tenant):
        """Correction documents are auto-finalized and immutable like stornos."""
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()
        # Build a correction by hand (mirroring how the service would).
        correction = InvoiceReseller(
            reseller=invoice.reseller,
            document_type="correction",
            created_by=None,
            date=datetime.date.today(),
        )
        correction.save()
        correction.finalize()
        correction.refresh_from_db()

        assert correction.can_be_cancelled() is False
        with pytest.raises(JasminError, match="cannot be cancelled"):
            InvoiceService.create_storno(correction, reason="cancel a correction")

    def test_self_cancellation_is_refused(self, tenant):
        """clean() rejects ``cancels_invoice == self``."""
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()
        invoice.cancels_invoice = invoice
        with pytest.raises(JasminError, match="cannot cancel itself"):
            invoice.full_clean()

    def test_storno_must_reference_an_invoice(self, tenant):
        """``document_type='storno'`` without ``cancels_invoice`` is invalid."""
        _ensure_settings(connection.tenant)
        bad = InvoiceReseller(
            reseller=ResellerFactory(),
            document_type="storno",
            cancels_invoice=None,
        )
        with pytest.raises(JasminError, match="must reference"):
            bad.full_clean()

    def test_regular_invoice_cannot_carry_cancels_invoice(self, tenant):
        """A document of type='invoice' must not point at a cancelled doc."""
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()
        another = _make_finalized_invoice()
        another.cancels_invoice = invoice
        with pytest.raises(
            ValidationError, match="cannot have cancellation/replacement"
        ):
            another.full_clean()

    def test_circular_cancellation_is_refused(self, tenant):
        """``A.cancels_invoice = B`` and ``B.cancels_invoice = A`` is caught."""
        _ensure_settings(connection.tenant)
        a = _make_finalized_invoice()
        b = _make_finalized_invoice()
        # Hack: simulate two stornos pointing at each other (only one save
        # would actually pass, the second one trips clean()).
        a.document_type = "storno"
        a.cancels_invoice = b
        b.document_type = "storno"
        b.cancels_invoice = a
        with pytest.raises(JasminError, match="Circular cancellation"):
            a.full_clean()

    def test_storno_is_legally_immutable(self, tenant):
        """A storno can never be unfinalized, deleted, or edited."""
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()
        storno = InvoiceService.create_storno(invoice, reason="r")

        with pytest.raises(JasminError, match="immutable"):
            storno.unfinalize()
        with pytest.raises(JasminError, match="immutable"):
            storno.delete()
        # And of course mutating any non-whitelisted field is blocked too.
        storno.correction_reason = "edited"
        with pytest.raises(JasminError, match="finalized"):
            storno.save()

    def test_can_be_cancelled_state_table(self, tenant):
        """Compact truth table for can_be_cancelled()."""
        _ensure_settings(connection.tenant)

        # Draft regular invoice → False.
        order = _make_simple_order()
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        draft = InvoiceService.create_from_delivery_note(delivery_note=dn)
        assert draft.can_be_cancelled() is False

        # Finalized regular invoice (not yet cancelled) → True.
        InvoiceService.finalize_invoice(draft)
        draft.refresh_from_db()
        assert draft.can_be_cancelled() is True

        # Finalized regular invoice that has been cancelled → False.
        storno = InvoiceService.create_storno(draft, reason="r")
        draft.refresh_from_db()
        assert draft.can_be_cancelled() is False

        # The storno itself → False.
        assert storno.can_be_cancelled() is False


# ===================================================================
# No INSERT into a finalized parent (the gap the trigger doesn't cover)
# ===================================================================
@pytest.mark.django_db
class TestNoInsertIntoFinalizedParent:
    """The Postgres ``finalized_protect`` trigger fires on UPDATE / DELETE
    only. INSERT into a finalized parent's content set is closed at the
    Python layer via ``FinalizedProtectedMixin.PARENT_FK_FIELDS``."""

    def test_cannot_add_order_content_to_finalized_order(self, tenant):
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()
        # ``invoice.items.first().order_content.order`` is the finalized order.
        order = invoice.items.first().order_content.order
        assert order.is_finalized is True

        with pytest.raises(JasminError, match="finalized Order"):
            OrderContent.objects.create(
                order=order,
                share_article=ShareArticleFactory(),
                amount=Decimal("1"),
                unit="KG",
                size="M",
                tax_rate=Decimal("7.00"),
            )

    def test_cannot_add_crate_order_content_to_finalized_order(self, tenant):
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()
        order = invoice.items.first().order_content.order

        with pytest.raises(JasminError, match="finalized Order"):
            CrateOrderContent.objects.create(
                order=order,
                crate_type=CrateFactory(),
                amount=1,
                price_per_unit=Decimal("1.50"),
                tax_rate=Decimal("19.00"),
            )

    def test_cannot_add_dn_content_to_finalized_dn(self, tenant):
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()
        dn = invoice.items.first().delivery_note_contents.first().delivery_note
        assert dn.is_finalized is True

        with pytest.raises(JasminError, match="finalized DeliveryNoteReseller"):
            DeliveryNoteContent.objects.create(
                delivery_note=dn,
                share_article=ShareArticleFactory(),
                amount=Decimal("1"),
                unit="KG",
                size="M",
                tax_rate=Decimal("7.00"),
            )

    def test_cannot_add_crate_dn_content_to_finalized_dn(self, tenant):
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()
        dn = invoice.items.first().delivery_note_contents.first().delivery_note

        with pytest.raises(JasminError, match="finalized DeliveryNoteReseller"):
            CrateDeliveryNoteContent.objects.create(
                delivery_note=dn,
                crate_type=CrateFactory(),
                amount=1,
                price_per_unit=Decimal("1.50"),
                tax_rate=Decimal("19.00"),
            )

    def test_cannot_add_invoice_content_to_finalized_invoice(self, tenant):
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()
        assert invoice.is_finalized is True

        with pytest.raises(JasminError, match="finalized InvoiceReseller"):
            InvoiceResellerContent.objects.create(
                invoice=invoice,
                share_article=ShareArticleFactory(),
                amount=Decimal("1"),
                price_per_unit=Decimal("1.00"),
                unit="KG",
                size="M",
                tax_rate=Decimal("7"),
            )

    def test_cannot_add_crate_invoice_content_to_finalized_invoice(self, tenant):
        _ensure_settings(connection.tenant)
        invoice = _make_finalized_invoice()

        with pytest.raises(JasminError, match="finalized InvoiceReseller"):
            CrateContentInvoiceReseller.objects.create(
                invoice=invoice,
                crate_type=CrateFactory(),
                amount=1,
                price_per_unit=Decimal("1.50"),
                tax_rate=Decimal("19"),
            )

    def test_can_still_add_to_unfinalized_parent(self, tenant):
        """Sanity check: the guard only fires when the parent is finalized."""
        _ensure_settings(connection.tenant)
        order = _make_simple_order()
        # Order is a draft.
        before = order.ordercontent_set.count()
        OrderContent.objects.create(
            order=order,
            share_article=ShareArticleFactory(),
            amount=Decimal("1"),
            unit="KG",
            size="M",
            tax_rate=Decimal("7.00"),
        )
        assert order.ordercontent_set.count() == before + 1


@pytest.mark.django_db
class TestStornoRecipientMirror:
    """DOC-1: a storno reproduces the cancelled invoice's FROZEN §14b recipient,
    not a re-resolved live (possibly edited) reseller billing address."""

    def test_storno_mirrors_cancelled_invoice_recipient_after_address_edit(
        self, tenant
    ):
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory(
            invoice_name="Alt GmbH",
            invoice_address="Altstrasse 1",
            invoice_plz="11111",
            invoice_city="Altstadt",
        )
        invoice = _make_finalized_invoice(reseller=reseller)
        invoice.refresh_from_db()
        assert invoice.recipient_snapshot["name"] == "Alt GmbH"

        # Office edits the live billing address AFTER the invoice is finalized.
        reseller.invoice_name = "Neu GmbH"
        reseller.invoice_address = "Neustrasse 2"
        reseller.invoice_plz = "22222"
        reseller.invoice_city = "Neustadt"
        reseller.save(
            update_fields=[
                "invoice_name",
                "invoice_address",
                "invoice_plz",
                "invoice_city",
            ]
        )

        storno = InvoiceService.create_storno(invoice, reason="r")
        storno.refresh_from_db()
        invoice.refresh_from_db()

        # The storno reproduces the ORIGINAL recipient, not the edited live one.
        assert storno.recipient_snapshot == invoice.recipient_snapshot
        assert storno.recipient_snapshot["name"] == "Alt GmbH"
        assert storno.document_hash_version == 2
        # And the storno's hash validates against its inherited recipient block.
        assert storno.document_hash == InvoiceService.compute_document_hash(storno)
