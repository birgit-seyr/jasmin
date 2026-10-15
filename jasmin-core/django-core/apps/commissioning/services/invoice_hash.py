"""The tamper hash sealed into a finalized reseller invoice.

``document_hash`` is an HMAC-SHA256 of a canonical payload of the invoice
(what it prints from its own rows, and the recipient block frozen at
finalization), keyed with ``settings.INVOICE_HASH_KEY``. The key lives outside
the database: a change that gets past an invoice's protection can't be given a
matching hash without the server's secrets, so the nightly check reports it.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from django.conf import settings

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
    """The hash ``invoice`` is sealed with: the canonical payload (see
    ``build_hash_payload``) under the current ``INVOICE_HASH_KEY``."""
    return _seal(_canonical_bytes(invoice), settings.INVOICE_HASH_KEY)


def _canonical_bytes(invoice: InvoiceReseller) -> bytes:
    payload = build_hash_payload(invoice)
    return json.dumps(payload, sort_keys=True, default=str).encode()


def _seal(canonical: bytes, key: str) -> str:
    return hmac.new(key.encode(), canonical, hashlib.sha256).hexdigest()


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
        stored = invoice.document_hash
        if not stored:  # the query leaves unsealed invoices out
            continue
        canonical = _canonical_bytes(invoice)
        recomputed = _seal(canonical, settings.INVOICE_HASH_KEY)
        # An invoice sealed before a key rotation verifies under the key it
        # was sealed with, which the rotation keeps among the fallbacks.
        if not hmac.compare_digest(stored, recomputed) and not any(
            hmac.compare_digest(stored, _seal(canonical, key))
            for key in settings.INVOICE_HASH_KEY_FALLBACKS
        ):
            drift.append(
                {
                    "id": str(invoice.id),
                    "number": invoice.number,
                    "prefix": invoice.prefix,
                    "stored": stored,
                    "recomputed": recomputed,
                }
            )
    return drift
