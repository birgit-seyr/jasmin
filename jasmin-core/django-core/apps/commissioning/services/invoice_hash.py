"""The tamper hash sealed into a finalized reseller invoice.

``document_hash`` is a SHA-256 of a canonical payload of the invoice: what it
prints from its own rows, and the recipient block frozen at finalization.
"""

from __future__ import annotations

import hashlib
import json

from ..models import (
    CrateContentInvoiceReseller,
    InvoiceReseller,
    InvoiceResellerContent,
)


def build_hash_payload(invoice: InvoiceReseller) -> dict:
    """Canonical snapshot used to derive ``document_hash``.

    Covers the parent identity (number / prefix / date / reseller), the
    resolved §14/§14a recipient block, the document type and the invoice a
    storno cancels with its reason, and every article and crate line
    (``_item_payload``, ``_crate_payload``). A post-finalize edit to any of
    them shows up as drift.

    Lines are sorted by pk so the payload is deterministic regardless
    of fetch order; ``json.dumps(sort_keys=True)`` only sorts dict keys.
    """
    recipient = invoice.resolved_recipient()
    return {
        "number": invoice.number,
        "prefix": invoice.prefix,
        "date": invoice.date.isoformat() if invoice.date else None,
        "reseller_id": str(invoice.reseller.id),
        "recipient": {
            key: (str(value) if value is not None else None)
            for key, value in recipient.items()
        },
        "document_type": invoice.document_type,
        "cancels_invoice_id": (
            str(invoice.cancels_invoice_id) if invoice.cancels_invoice_id else None
        ),
        "correction_reason": invoice.correction_reason,
        "items": [_item_payload(item) for item in invoice.items.order_by("pk")],
        "crate_items": [
            _crate_payload(crate) for crate in invoice.crate_items.order_by("pk")
        ],
    }


def _item_payload(item: InvoiceResellerContent) -> dict:
    """An article line as the invoice prints it from the line's own row.

    The article's name and organic mark are read from the article itself when
    the invoice is rendered, so they aren't sealed: the PDF stored at
    finalization keeps what was printed then, and sealing them would show
    every invoice naming an article as tampered with once it is renamed.
    """
    return {
        "share_article_id": (
            str(item.share_article_id) if item.share_article_id else None
        ),
        "sort": item.sort,
        "size": item.size,
        "unit": item.unit,
        "amount": str(item.amount),
        "price_per_unit": str(item.price_per_unit),
        "rabatt": item.rabatt,
        "tax_rate": str(item.tax_rate),
    }


def _crate_payload(crate: CrateContentInvoiceReseller) -> dict:
    return {
        "crate_type_id": str(crate.crate_type_id),
        "amount": str(crate.amount),
        "price_per_unit": (
            str(crate.price_per_unit) if crate.price_per_unit is not None else None
        ),
        "rabatt": crate.rabatt,
        "tax_rate": str(crate.tax_rate),
    }


def compute_document_hash(invoice: InvoiceReseller) -> str:
    """SHA-256 of the canonical payload (see ``build_hash_payload``)."""
    payload = build_hash_payload(invoice)
    data_string = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(data_string.encode()).hexdigest()


def find_drifted_invoices() -> list[dict]:
    """Iterate every finalized invoice and return drift records for
    any whose stored hash no longer matches the recomputed hash.

    Returns ``[{"id", "number", "prefix", "stored", "recomputed"}, ...]``.
    Used for tamper detection on commercial documents by the nightly
    ``nightly_invoice_hash_check`` Huey task and the
    ``check_invoice_hashes`` management command.
    """
    drift: list[dict] = []
    finalized = (
        InvoiceReseller.objects.filter(is_finalized=True)
        .exclude(document_hash__isnull=True)
        .exclude(document_hash="")
        # build_hash_payload reads invoice.reseller per row. (items /
        # crate_items are intentionally NOT prefetched: build_hash_payload
        # iterates them via .order_by("pk"), and that SQL ordering is part
        # of the deterministic GoBD hash — switching to a prefetched/
        # Python-sorted list could change the order under a different
        # collation and invalidate every stored hash.)
        .select_related("reseller")
    )
    for invoice in finalized.iterator():
        recomputed = compute_document_hash(invoice)
        if invoice.document_hash != recomputed:
            drift.append(
                {
                    "id": str(invoice.id),
                    "number": invoice.number,
                    "prefix": invoice.prefix,
                    "stored": invoice.document_hash,
                    "recomputed": recomputed,
                }
            )
    return drift
