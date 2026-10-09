"""``clear_legacy_crate_notes``: clears the "+N" / "-N" notes the crate
amount adjustment used to write on order, delivery-note and invoice crate
rows, now that the crate summaries show each line's note.

Only a note that is exactly such an adjustment is cleared; any other text is
the office's own. A finalized row, or a row of a finalized document, keeps its
note: ``note`` may not change on a finalized crate row.
"""

from __future__ import annotations

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateOrderContent,
    Order,
)
from apps.commissioning.tests.factories import (
    CrateFactory,
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OrderFactory,
    ResellerFactory,
)
from apps.shared.tenants.models import Tenant

TAX = Decimal("19.00")
LEGACY_NOTES = ["+1", "+12", "-3"]
OFFICE_NOTES = ["Pallet", "+3 crates", "3", "+", "-", "+0", " +3", "+3 ", "+-3", "1+2"]


def _run(**options) -> str:
    out = StringIO()
    call_command("clear_legacy_crate_notes", stdout=out, **options)
    return out.getvalue()


@pytest.fixture
def documents(tenant):
    """A draft order, delivery note and invoice, each with a crate type."""
    crate = CrateFactory()
    order = OrderFactory(reseller=ResellerFactory())
    return {
        CrateOrderContent: {"order": order, "crate_type": crate},
        CrateDeliveryNoteContent: {
            "delivery_note": DeliveryNoteResellerFactory(
                order=OrderFactory(reseller=ResellerFactory())
            ),
            "crate_type": crate,
        },
        CrateContentInvoiceReseller: {
            "invoice": InvoiceResellerFactory(),
            "crate_type": crate,
        },
    }


def _crate_row(documents, model, note, **fields):
    return model.objects.create(
        **documents[model],
        amount=2,
        price_per_unit=Decimal("2.50"),
        tax_rate=TAX,
        note=note,
        **fields,
    )


def _notes(rows) -> list[str | None]:
    for row in rows:
        row.refresh_from_db()
    return [row.note for row in rows]


MODELS = [CrateOrderContent, CrateDeliveryNoteContent, CrateContentInvoiceReseller]


@pytest.mark.django_db
class TestClearLegacyCrateNotes:
    @pytest.mark.parametrize("model", MODELS)
    def test_clears_the_adjustment_notes_and_keeps_the_office_notes(
        self, tenant, documents, model
    ):
        legacy = [_crate_row(documents, model, note) for note in LEGACY_NOTES]
        office = [_crate_row(documents, model, note) for note in OFFICE_NOTES]
        empty = [_crate_row(documents, model, None)]

        output = _run(tenant=tenant.schema_name)

        assert _notes(legacy) == [None] * len(LEGACY_NOTES)
        assert _notes(office) == OFFICE_NOTES
        assert _notes(empty) == [None]
        assert f"Tenant {tenant.schema_name}:" in output
        assert f"{model.__name__}: cleared {len(LEGACY_NOTES)}" in output

    def test_a_dry_run_changes_nothing_and_counts_what_it_would_clear(
        self, tenant, documents
    ):
        rows = [_crate_row(documents, model, "+2") for model in MODELS]

        output = _run(tenant=tenant.schema_name, dry_run=True)

        assert _notes(rows) == ["+2"] * len(MODELS)
        assert "dry run" in output
        for model in MODELS:
            assert f"{model.__name__}: would clear 1" in output

    def test_a_second_run_finds_nothing_to_clear(self, tenant, documents):
        _crate_row(documents, CrateOrderContent, "+2")
        _run(tenant=tenant.schema_name)

        output = _run(tenant=tenant.schema_name)

        for model in MODELS:
            assert f"{model.__name__}: cleared 0" in output

    @pytest.mark.parametrize("model", MODELS)
    def test_a_finalized_row_keeps_its_note_and_is_counted(
        self, tenant, documents, model
    ):
        finalized = _crate_row(documents, model, "+2", is_finalized=True)
        draft = _crate_row(documents, model, "+2")

        output = _run(tenant=tenant.schema_name)

        assert _notes([finalized, draft]) == ["+2", None]
        assert f"{model.__name__}: cleared 1, skipped 1 finalized" in output

    def test_a_row_of_a_finalized_document_keeps_its_note(self, tenant, documents):
        row = _crate_row(documents, CrateOrderContent, "+2")
        Order.objects.filter(pk=documents[CrateOrderContent]["order"].pk).update(
            is_finalized=True
        )

        output = _run(tenant=tenant.schema_name)

        assert _notes([row]) == ["+2"]
        assert "CrateOrderContent: cleared 0, skipped 1 finalized" in output

    def test_every_active_tenant_by_default(self, tenant, documents):
        row = _crate_row(documents, CrateOrderContent, "+2")

        output = _run()

        assert _notes([row]) == [None]
        assert f"Tenant {tenant.schema_name}:" in output

    def test_an_inactive_tenant_is_skipped(self, tenant, documents):
        row = _crate_row(documents, CrateOrderContent, "+2")
        Tenant.objects.filter(pk=tenant.pk).update(is_active=False)

        output = _run()

        assert _notes([row]) == ["+2"]
        assert f"Tenant {tenant.schema_name}:" not in output

    def test_an_unknown_tenant_is_refused(self, tenant):
        with pytest.raises(CommandError, match="No tenant with schema 'no_such'"):
            _run(tenant="no_such")
