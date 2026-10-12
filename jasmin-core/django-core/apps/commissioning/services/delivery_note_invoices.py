"""The invoice of each delivery note.

A delivery note reaches its invoice through the provenance links of the invoice
lines: ``InvoiceResellerContent.delivery_note_contents`` for article lines,
``CrateContentInvoiceReseller.crate_delivery_note_contents`` for crate lines
(the only link a crate-only note has). A storno carries no provenance links,
and a cancelled invoice keeps its own, so a cancelled invoice still holds its
notes: billing refuses a note any invoice holds, cancelled or not.

Billing allows one invoice per note, yet older data can link a note to several.
The current one is then the newest that isn't cancelled, else the newest
overall — newest by document date, then creation time, then id, so the pick
never depends on row order.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable

from django.db.models import F

from ..models import (
    CrateContentInvoiceReseller,
    InvoiceReseller,
    InvoiceResellerContent,
)


def _current_first_rank(invoice: InvoiceReseller) -> tuple:
    return (
        invoice.cancelled_by_invoice_id is None,
        invoice.date or datetime.date.min,
        invoice.created_at,
        invoice.pk,
    )


def current_invoices_by_delivery_note(
    delivery_note_ids: Iterable[str],
) -> dict[str, InvoiceReseller]:
    """Map each invoiced delivery note id to its current invoice, in two
    queries, leaving out notes no invoice holds. Each invoice comes with its
    cancelling storno (``cancelled_by_invoice``) loaded.

    Filtering and annotating through the same M2M path reuses one join, so
    each row is one (line, linked delivery note) pair within ``delivery_note_ids``.
    """
    ids = set(delivery_note_ids)
    if not ids:
        return {}
    article_lines = (
        InvoiceResellerContent.objects.filter(
            delivery_note_contents__delivery_note_id__in=ids
        )
        .annotate(linked_delivery_note_id=F("delivery_note_contents__delivery_note_id"))
        .select_related("invoice", "invoice__cancelled_by_invoice")
    )
    crate_lines = (
        CrateContentInvoiceReseller.objects.filter(
            crate_delivery_note_contents__delivery_note_id__in=ids,
            invoice__isnull=False,
        )
        .annotate(
            linked_delivery_note_id=F("crate_delivery_note_contents__delivery_note_id")
        )
        .select_related("invoice", "invoice__cancelled_by_invoice")
    )
    current: dict[str, InvoiceReseller] = {}
    for lines in (article_lines, crate_lines):
        for line in lines:
            delivery_note_id = line.linked_delivery_note_id
            invoice = line.invoice
            if invoice is None:
                continue
            shown = current.get(delivery_note_id)
            if shown is None or _current_first_rank(invoice) > _current_first_rank(
                shown
            ):
                current[delivery_note_id] = invoice
    return current
