"""Pins the address-resolution order on ``InvoiceResellerSerializer``.

The PDF + ZUGFeRD renderers both consume the flat ``invoice.reseller_*``
keys this serializer emits. UStG §14 requires the recipient block on a
reseller invoice to be the BILLING address, not the storefront/delivery
contact — so the serializer must read from ``reseller.invoice_*`` first
(set explicitly via ``ResellerInvoiceSettingsModal`` when billing
diverges from the contact) and only fall back to ``reseller.contact.*``
when the invoice block is blank (legacy rows, fresh imports, etc.).

Was a straight ``source="reseller.contact.*"`` traversal — every issued
invoice rendered the contact address even when the office had
customised the invoice block.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.commissioning.models import InvoiceReseller
from apps.commissioning.serializers.resellers_serializer import (
    InvoiceResellerSerializer,
)
from apps.commissioning.tests.factories import (
    ContactEntityFactory,
    InvoiceResellerFactory,
    ResellerFactory,
)


@pytest.mark.django_db
class TestInvoiceResellerAddressResolution:
    def test_invoice_fields_win_over_contact(self, tenant):
        contact = ContactEntityFactory(
            company_name="Storefront GmbH",
            address="Marktstrasse 1",
            zip_code="80331",
            city="Munich",
        )
        reseller = ResellerFactory(
            contact=contact,
            invoice_name="Accounting Office AG",
            invoice_name2="c/o Buchhaltung",
            invoice_address="Buchhalterweg 99",
            invoice_plz="10115",
            invoice_city="Berlin",
        )
        invoice = InvoiceResellerFactory(reseller=reseller)

        data = InvoiceResellerSerializer(invoice).data

        assert data["reseller_name"] == "Accounting Office AG"
        assert data["reseller_name2"] == "c/o Buchhaltung"
        assert data["reseller_address"] == "Buchhalterweg 99"
        assert data["reseller_zip"] == "10115"
        assert data["reseller_city"] == "Berlin"

    def test_falls_back_to_contact_when_invoice_blank(self, tenant):
        contact = ContactEntityFactory(
            company_name="Storefront GmbH",
            address="Marktstrasse 1",
            zip_code="80331",
            city="Munich",
        )
        reseller = ResellerFactory(
            contact=contact,
            invoice_name="",
            invoice_address=None,
            invoice_plz="",
            invoice_city=None,
        )
        invoice = InvoiceResellerFactory(reseller=reseller)

        data = InvoiceResellerSerializer(invoice).data

        # ``contact.name`` is a property that prefers ``company_name`` —
        # the factory sets company_name explicitly, so that's what falls
        # through.
        assert data["reseller_name"] == "Storefront GmbH"
        # ``reseller_name2`` has no contact counterpart — stays blank.
        assert data["reseller_name2"] is None or data["reseller_name2"] == ""
        assert data["reseller_address"] == "Marktstrasse 1"
        assert data["reseller_zip"] == "80331"
        assert data["reseller_city"] == "Munich"

    def test_finalized_snapshot_overrides_live_reseller(self, tenant):
        """DOC-8: when recipient_snapshot is frozen (at finalization) the
        serializer renders IT, not the live reseller — so a later reseller edit
        or GDPR anonymization can't drift the immutable invoice away from its
        sealed document_hash."""
        reseller = ResellerFactory(
            invoice_name="Live Billing",
            invoice_address="Live St 1",
            invoice_plz="11111",
            invoice_city="Liveheim",
        )
        invoice = InvoiceResellerFactory(reseller=reseller)
        # Freeze a recipient_snapshot (what finalize_invoice does), with values
        # deliberately different from the live reseller.
        invoice.recipient_snapshot = {
            "name": "Frozen Billing",
            "name2": "c/o Snapshot",
            "address": "Frozen St 9",
            "zip": "99999",
            "city": "Frozenburg",
            "country": "DE",
            "uid": "DE123456789",
        }
        invoice.save(update_fields=["recipient_snapshot"])

        data = InvoiceResellerSerializer(invoice).data

        assert data["reseller_name"] == "Frozen Billing"
        assert data["reseller_name2"] == "c/o Snapshot"
        assert data["reseller_address"] == "Frozen St 9"
        assert data["reseller_zip"] == "99999"
        assert data["reseller_city"] == "Frozenburg"
        assert data["reseller_country"] == "DE"
        assert data["reseller_uid"] == "DE123456789"
        # Proves the snapshot — not the live reseller — drove the render.
        assert data["reseller_name"] != reseller.invoice_name

    def test_resolved_recipient_computed_once_per_row(self, tenant):
        """DOC-3/5: the seven reseller_* fields share ONE resolved_recipient()
        call per row (cached in to_representation), not one each."""
        invoice = InvoiceResellerFactory(reseller=ResellerFactory())

        original = InvoiceReseller.resolved_recipient
        calls = {"count": 0}

        def counting(self):
            calls["count"] += 1
            return original(self)

        with patch.object(InvoiceReseller, "resolved_recipient", counting):
            data = InvoiceResellerSerializer(invoice).data

        assert calls["count"] == 1, (
            f"resolved_recipient() ran {calls['count']}× — expected 1 "
            "(the recipient block must be cached across the 7 reseller_* fields)"
        )
        # The recipient block still rendered.
        assert "reseller_name" in data

    def test_sum_fields_serialize_as_strings(self, tenant):
        """DOC-1 regression guard: money goes on the wire as canonical 2dp
        STRINGS. DecimalField under DRF's COERCE_DECIMAL_TO_STRING=True default
        already does this — pin it so a future settings change can't silently
        flip sum_netto/sum_brutto to JSON floats."""
        invoice = InvoiceResellerFactory(reseller=ResellerFactory())

        data = InvoiceResellerSerializer(invoice).data

        assert isinstance(data["sum_netto"], str)
        assert isinstance(data["sum_brutto"], str)
