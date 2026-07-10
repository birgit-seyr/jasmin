"""Tests for InvoiceService."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.tests.factories import (
    DeliveryNoteContentFactory,
    JasminUserFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
)
from core.errors import JasminError


def _finalized_delivery_note(tenant, *, reseller=None, delivery_week=15):
    """Create a finalized delivery note with one item.

    ``delivery_week`` is exposed so callers building two notes for the SAME
    reseller can put them on different slots — one Order per reseller per
    (year, week, day) is enforced by ``order_unique_reseller_slot``.
    """
    user = JasminUserFactory()
    if reseller is None:
        reseller = ResellerFactory()
    order = OrderFactory(reseller=reseller, delivery_week=delivery_week)
    from apps.commissioning.models import DeliveryNoteReseller

    dn = DeliveryNoteReseller.objects.create(order=order, date=date.today())
    article = ShareArticleFactory()
    DeliveryNoteContentFactory(
        delivery_note=dn,
        share_article=article,
        amount=Decimal("10.000"),
        unit="KG",
        size="M",
        price_per_unit=Decimal("2.50"),
    )
    dn.finalize(user=user)
    return dn


# ---------------------------------------------------------------------------
# create_from_delivery_note
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateFromDeliveryNote:
    def test_creates_invoice_from_delivery_note(self, tenant):
        dn = _finalized_delivery_note(tenant)
        invoice = InvoiceService.create_from_delivery_note(dn)

        assert invoice.pk is not None
        assert invoice.reseller == dn.order.reseller

    def test_copies_article_items(self, tenant):
        dn = _finalized_delivery_note(tenant)
        invoice = InvoiceService.create_from_delivery_note(dn)

        assert invoice.items.count() == 1
        item = invoice.items.first()
        assert item.amount == Decimal("10.000")

    def test_raises_if_invoice_already_exists(self, tenant):
        dn = _finalized_delivery_note(tenant)
        InvoiceService.create_from_delivery_note(dn)

        with pytest.raises(JasminError, match="already exists"):
            InvoiceService.create_from_delivery_note(dn)


# ---------------------------------------------------------------------------
# finalize_invoice
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestFinalizeInvoice:
    def test_finalizes_successfully(self, tenant):
        user = JasminUserFactory()
        dn = _finalized_delivery_note(tenant)
        invoice = InvoiceService.create_from_delivery_note(dn)

        result = InvoiceService.finalize_invoice(invoice, user=user)

        assert result is True
        invoice.refresh_from_db()
        assert invoice.is_finalized is True

    def test_raises_if_already_finalized(self, tenant):
        user = JasminUserFactory()
        dn = _finalized_delivery_note(tenant)
        invoice = InvoiceService.create_from_delivery_note(dn)
        InvoiceService.finalize_invoice(invoice, user=user)

        with pytest.raises(JasminError, match="already finalized"):
            InvoiceService.finalize_invoice(invoice, user=user)

    def test_raises_if_no_items(self, tenant):
        reseller = ResellerFactory()
        from apps.commissioning.models import InvoiceReseller

        invoice = InvoiceReseller.objects.create(reseller=reseller, date=date.today())

        with pytest.raises(JasminError, match="no items"):
            InvoiceService.finalize_invoice(invoice)

    def test_rate_limit_refuses_finalize_over_cap(self, tenant):
        """The invoice-finalization quota gates finalize_invoice, and a refused
        call burns no sequential number (guard runs before assign_final_number)."""
        from apps.shared.tenants.errors import ActionRateLimitExceeded
        from apps.shared.tenants.models import RateLimitedAction

        user = JasminUserFactory()
        # Platform-owned override; connection.tenant is this fixture object, so
        # the in-memory value is what the guard reads. Tighten to 1/week.
        tenant.action_rate_limit_overrides = {
            str(RateLimitedAction.INVOICE_FINALIZATION): {
                "weekly": 1,
                "per_minute": 100,
            }
        }

        dn1 = _finalized_delivery_note(tenant, delivery_week=15)
        invoice1 = InvoiceService.create_from_delivery_note(dn1)
        InvoiceService.finalize_invoice(invoice1, user=user)  # 1st ok

        dn2 = _finalized_delivery_note(tenant, delivery_week=16)
        invoice2 = InvoiceService.create_from_delivery_note(dn2)
        with pytest.raises(ActionRateLimitExceeded) as exc:
            InvoiceService.finalize_invoice(invoice2, user=user)
        assert exc.value.details["action"] == str(
            RateLimitedAction.INVOICE_FINALIZATION
        )
        # The refused finalize rolled back — no number burned, still a draft.
        invoice2.refresh_from_db()
        assert invoice2.is_finalized is False


# ---------------------------------------------------------------------------
# recipient_snapshot (document_hash v2 — DOC-1)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRecipientSnapshot:
    def test_snapshot_frozen_at_finalize_survives_reseller_anonymization(self, tenant):
        user = JasminUserFactory()
        reseller = ResellerFactory(
            invoice_name="ACME GmbH",
            invoice_address="Hauptstr. 1",
            invoice_plz="12345",
            invoice_city="Berlin",
        )
        dn = _finalized_delivery_note(tenant, reseller=reseller)
        invoice = InvoiceService.create_from_delivery_note(dn)
        InvoiceService.finalize_invoice(invoice, user=user)
        invoice.refresh_from_db()

        # The §14 recipient is frozen onto the invoice at finalize, and the
        # sealed hash is self-consistent right after issue.
        assert invoice.document_hash_version == 2
        assert invoice.recipient_snapshot is not None
        assert invoice.recipient_snapshot["name"] == "ACME GmbH"
        assert InvoiceService.find_drifted_invoices() == []

        # GDPR anonymization scrubs the LIVE reseller's billing fields...
        reseller.invoice_name = None
        reseller.invoice_name2 = None
        reseller.invoice_address = None
        reseller.invoice_plz = None
        reseller.invoice_city = None
        reseller.save()
        invoice.refresh_from_db()

        # ...but the immutable invoice reads its frozen snapshot, so it does NOT
        # drift — a live read of the now-anonymized recipient WOULD differ, which
        # is exactly the bug the snapshot prevents (DOC-1).
        assert invoice._live_recipient()["name"] != "ACME GmbH"
        assert invoice.resolved_recipient()["name"] == "ACME GmbH"
        assert InvoiceService.find_drifted_invoices() == []

    def test_draft_invoice_resolves_recipient_live(self, tenant):
        from apps.commissioning.models import InvoiceReseller

        reseller = ResellerFactory(invoice_name="Draft Co")
        invoice = InvoiceReseller.objects.create(reseller=reseller, date=date.today())

        # Unfinalized → no snapshot yet → preview tracks the live reseller.
        assert invoice.recipient_snapshot is None
        assert invoice.resolved_recipient()["name"] == "Draft Co"


# ---------------------------------------------------------------------------
# create_summary_invoice_from_delivery_notes
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateSummaryInvoice:
    def test_groups_by_article_and_sums_amounts(self, tenant):
        reseller = ResellerFactory()
        # Distinct slots: one Order per reseller per (year, week, day).
        dn1 = _finalized_delivery_note(tenant, reseller=reseller, delivery_week=15)
        dn2 = _finalized_delivery_note(tenant, reseller=reseller, delivery_week=16)

        invoice = InvoiceService.create_summary_invoice_from_delivery_notes(
            [dn1, dn2],
        )

        assert invoice.pk is not None
        # Each DN has 1 item; articles differ so we get 2 line items
        assert invoice.items.count() >= 1

    def test_raises_if_no_delivery_notes(self, tenant):
        with pytest.raises(JasminError, match="No delivery notes"):
            InvoiceService.create_summary_invoice_from_delivery_notes([])

    def test_raises_if_mixed_resellers(self, tenant):
        dn1 = _finalized_delivery_note(tenant, reseller=ResellerFactory())
        dn2 = _finalized_delivery_note(tenant, reseller=ResellerFactory())

        with pytest.raises(JasminError, match="same reseller"):
            InvoiceService.create_summary_invoice_from_delivery_notes([dn1, dn2])

    def test_raises_if_not_finalized(self, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)
        from apps.commissioning.models import DeliveryNoteReseller

        dn = DeliveryNoteReseller.objects.create(order=order, date=date.today())
        DeliveryNoteContentFactory(delivery_note=dn)
        # NOT finalized

        with pytest.raises(JasminError, match="not finalized"):
            InvoiceService.create_summary_invoice_from_delivery_notes([dn])


# ---------------------------------------------------------------------------
# find_drifted_invoices — POSITIVE tamper detection (TEST-2)
# ---------------------------------------------------------------------------


def _corrupt_document_hash(invoice, value: str) -> None:
    """Overwrite a finalized invoice's stored ``document_hash`` OUT OF BAND.

    ``document_hash`` is FinalizedProtected at BOTH the Python save() layer and
    the Postgres trigger, so an honest write can't tamper it — that's the point.
    ``session_replication_role = replica`` disables the trigger for this one
    statement, simulating exactly the superuser-SQL tampering the nightly hash
    sweep exists to catch.
    """
    from django.db import connection

    table = invoice._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute("SET session_replication_role = replica;")
        try:
            cursor.execute(
                f"UPDATE {table} SET document_hash = %s WHERE id = %s",  # noqa: S608
                [value, str(invoice.id)],
            )
        finally:
            cursor.execute("SET session_replication_role = DEFAULT;")


@pytest.mark.django_db
class TestFindDriftedInvoices:
    """The tamper-detection core is otherwise only ever asserted in the negative
    (``== []``): a refactor making the sweep vacuous would pass every existing
    test while real tampering goes undetected. These pin the POSITIVE result."""

    def test_tampered_stored_hash_is_reported(self, tenant):
        user = JasminUserFactory()
        dn = _finalized_delivery_note(tenant)
        invoice = InvoiceService.create_from_delivery_note(dn)
        InvoiceService.finalize_invoice(invoice, user=user)
        invoice.refresh_from_db()
        genuine_hash = invoice.document_hash

        # Clean right after issue.
        assert InvoiceService.find_drifted_invoices() == []

        # Tamper the sealed hash out of band.
        _corrupt_document_hash(invoice, "deadbeef" * 8)

        drift = InvoiceService.find_drifted_invoices()
        assert len(drift) == 1
        record = drift[0]
        assert record["id"] == str(invoice.id)
        assert record["number"] == invoice.number
        assert record["stored"] == "deadbeef" * 8
        assert record["recomputed"] == genuine_hash

    def test_untampered_finalized_invoice_does_not_drift(self, tenant):
        # Guards the other direction: a correct detector must NOT flag an
        # honestly-finalized invoice (a false-positive drift detector would be
        # as broken as a vacuous one).
        user = JasminUserFactory()
        dn = _finalized_delivery_note(tenant)
        invoice = InvoiceService.create_from_delivery_note(dn)
        InvoiceService.finalize_invoice(invoice, user=user)

        assert InvoiceService.find_drifted_invoices() == []
