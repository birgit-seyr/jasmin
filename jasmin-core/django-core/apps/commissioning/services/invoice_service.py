from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from core.errors import ConflictError

from ..errors import CommissioningError
from ..models import (
    CrateContentInvoiceReseller,
    DeliveryNoteReseller,
    InvoiceReseller,
    InvoiceResellerContent,
)
from ..utils.iso_week_utils import coerce_document_date
from ..utils.tax_rate_utils import (
    effective_article_tax_rate,
    effective_crate_tax_rate,
)
from .email_dispatch import load_pdf_attachments, send_document_email
from .finalize_utils import finalize_children

logger = logging.getLogger(__name__)


def _payment_due_date(invoice_date, reseller):
    """Payment due date for a reseller invoice: issue date + the reseller's
    payment terms (default 14 days). Returns ``None`` when there is no issue
    date. Storno / correction credit notes deliberately get no due date."""
    if invoice_date is None:
        return None
    try:
        terms_days = reseller.get_payment_terms_days() if reseller else 14
    except (AttributeError, TypeError):
        terms_days = 14
    return invoice_date + timedelta(days=terms_days)


class InvoiceService:
    """Service for managing invoices."""

    @staticmethod
    def get_invoice_for_delivery_note(
        delivery_note,
    ) -> InvoiceReseller | None:
        """Return the invoice linked to *delivery_note*, or ``None``."""
        if not delivery_note:
            return None
        content = (
            InvoiceResellerContent.objects.filter(
                delivery_note_contents__delivery_note=delivery_note
            )
            .select_related("invoice", "invoice__cancelled_by_invoice")
            .first()
        )
        if content:
            return content.invoice
        # Crate-only delivery note: no article lines, so the article M2M above
        # misses. Fall back to the crate-line provenance link.
        crate_content = (
            CrateContentInvoiceReseller.objects.filter(
                crate_delivery_note_contents__delivery_note=delivery_note
            )
            .select_related("invoice", "invoice__cancelled_by_invoice")
            .first()
        )
        return crate_content.invoice if crate_content else None

    @staticmethod
    def get_invoices_for_delivery_notes(
        delivery_note_ids,
    ) -> dict[str, InvoiceReseller]:
        """Batch form of ``get_invoice_for_delivery_note``: map each delivery
        note id → its invoice in a constant number of queries instead of 1-2
        per note (the per-order N+1 in bulk reminder sends).

        A delivery note's article lines all belong to one invoice, so the first
        content per note is authoritative; crate-only notes fall back to the
        crate-line provenance. ``values_list`` over the SAME M2M path used in
        the filter reuses one join (no filter-vs-annotate join mismatch).
        """
        ids = list(delivery_note_ids)
        if not ids:
            return {}

        invoice_id_by_dn: dict[str, str] = {}
        for dn_id, invoice_id in InvoiceResellerContent.objects.filter(
            delivery_note_contents__delivery_note_id__in=ids
        ).values_list("delivery_note_contents__delivery_note_id", "invoice_id"):
            invoice_id_by_dn.setdefault(dn_id, invoice_id)

        missing = [dn_id for dn_id in ids if dn_id not in invoice_id_by_dn]
        if missing:
            for dn_id, invoice_id in CrateContentInvoiceReseller.objects.filter(
                crate_delivery_note_contents__delivery_note_id__in=missing
            ).values_list(
                "crate_delivery_note_contents__delivery_note_id", "invoice_id"
            ):
                invoice_id_by_dn.setdefault(dn_id, invoice_id)

        if not invoice_id_by_dn:
            return {}
        invoices = (
            InvoiceReseller.objects.filter(id__in=set(invoice_id_by_dn.values()))
            .select_related("cancelled_by_invoice")
            .in_bulk()
        )
        return {
            dn_id: invoices[invoice_id]
            for dn_id, invoice_id in invoice_id_by_dn.items()
            if invoice_id in invoices
        }

    @staticmethod
    def _create_invoice_article_content(
        invoice: InvoiceReseller,
        source_row,
        *,
        amount,
        tax_rate,
        rabatt,
        source_rabatt,
        order_content=None,
        delivery_note_contents=(),
    ) -> InvoiceResellerContent:
        """Create one ``InvoiceResellerContent`` article line from an upstream
        row, owning the identity kwargs, the FULL ``source_*`` snapshot block,
        and the provenance M2M so every write path (create-from-DN / storno /
        summary) produces a byte-identical audit surface.

        These are legally-immutable (GoBD/UStG) documents: a missed ``source_*``
        field silently breaks the serializer's ``*_differs`` audit, so the five
        snapshot fields are laid out in one place here. ``amount`` / sign /
        ``tax_rate`` / ``rabatt`` (and the raw ``source_rabatt`` snapshot, which
        legitimately diverges from the coerced ``rabatt or 0`` on the create
        path) stay at the CALL SITE:

          * create-from-DN passes the positive amount + stored-else-resolved tax
            + the single source DN content on the M2M;
          * storno passes the negated amount + the copied tax and wires NO M2M;
          * summary passes the merged total + the merged tax, omits
            ``order_content``, and wires all grouped DN contents on the M2M.

        ``source_row`` supplies the shared identity fields (offer /
        share_article / description / note / unit / size / sort /
        price_per_unit). ``source_amount`` mirrors the written ``amount``
        (equal at every call site) so the snapshot reads "unedited".
        """
        content = InvoiceResellerContent.objects.create(
            invoice=invoice,
            order_content=order_content,
            offer=source_row.offer,
            share_article=source_row.share_article,
            description=source_row.description,
            note=source_row.note,
            unit=source_row.unit,
            size=source_row.size,
            sort=source_row.sort,
            amount=amount,
            price_per_unit=source_row.price_per_unit,
            rabatt=rabatt,
            tax_rate=tax_rate,
            # Snapshot of the upstream row so the serializer's *_differs
            # fields are pure local comparisons on this immutable document.
            source_amount=amount,
            source_price_per_unit=source_row.price_per_unit,
            source_rabatt=source_rabatt,
            source_unit=source_row.unit,
            source_size=source_row.size,
        )
        if delivery_note_contents:
            content.delivery_note_contents.add(*delivery_note_contents)
        return content

    @staticmethod
    def _create_invoice_crate_content(
        invoice: InvoiceReseller,
        source_row,
        *,
        amount,
        tax_rate,
        rabatt,
        source_rabatt,
        crate_delivery_note_contents=(),
    ) -> CrateContentInvoiceReseller:
        """Create one ``CrateContentInvoiceReseller`` line from an upstream crate
        row — the crate counterpart to ``_create_invoice_article_content``.

        Owns the three ``source_*`` snapshot fields (crates carry no unit/size)
        + the crate provenance M2M. As with the article helper, ``amount`` /
        sign / ``tax_rate`` / ``rabatt`` / the raw ``source_rabatt`` stay at the
        call site; storno wires no M2M.
        """
        content = CrateContentInvoiceReseller.objects.create(
            invoice=invoice,
            crate_type=source_row.crate_type,
            amount=amount,
            price_per_unit=source_row.price_per_unit,
            rabatt=rabatt,
            tax_rate=tax_rate,
            note=source_row.note,
            # Snapshot of the upstream crate row — same rationale as above.
            source_amount=amount,
            source_price_per_unit=source_row.price_per_unit,
            source_rabatt=source_rabatt,
        )
        if crate_delivery_note_contents:
            content.crate_delivery_note_contents.add(*crate_delivery_note_contents)
        return content

    @staticmethod
    def build_hash_payload(invoice: InvoiceReseller) -> dict:
        """Canonical snapshot used to derive ``document_hash``.

        Covers every field that legally affects the invoice's monetary
        position: parent identity (number / prefix / date / reseller) and,
        per line, ``amount`` / ``price_per_unit`` / ``rabatt`` / ``tax_rate``
        — for both article items AND crate items.

        Lines are sorted by pk so the payload is deterministic regardless
        of fetch order; ``json.dumps(sort_keys=True)`` only sorts dict keys.
        """
        payload = {
            "number": invoice.number,
            "prefix": invoice.prefix,
            "date": invoice.date.isoformat() if invoice.date else None,
            "reseller_id": str(invoice.reseller.id),
            "items": [
                {
                    "amount": str(item.amount),
                    "price_per_unit": str(item.price_per_unit),
                    "rabatt": item.rabatt,
                    "tax_rate": str(item.tax_rate),
                }
                for item in invoice.items.order_by("pk")
            ],
            "crate_items": [
                {
                    "amount": str(crate.amount),
                    "price_per_unit": (
                        str(crate.price_per_unit)
                        if crate.price_per_unit is not None
                        else None
                    ),
                    "rabatt": crate.rabatt,
                    "tax_rate": str(crate.tax_rate),
                }
                for crate in invoice.crate_items.order_by("pk")
            ],
        }
        # v2 extends the sealed surface to the resolved §14/§14a recipient
        # block and the document-type / cancellation identity, so a
        # post-finalize edit to the reseller/contact row (or a forged
        # document_type / storno linkage) shows up as drift. v1 documents
        # keep the original payload so their stored hash still validates —
        # legacy invoices must not all suddenly report as tampered.
        if (getattr(invoice, "document_hash_version", 1) or 1) >= 2:
            recipient = invoice.resolved_recipient()
            payload["recipient"] = {
                key: (str(value) if value is not None else None)
                for key, value in recipient.items()
            }
            payload["document_type"] = invoice.document_type
            payload["cancels_invoice_id"] = (
                str(invoice.cancels_invoice_id) if invoice.cancels_invoice_id else None
            )
        return payload

    @staticmethod
    def compute_document_hash(invoice: InvoiceReseller) -> str:
        """SHA-256 of the canonical payload (see ``build_hash_payload``)."""
        payload = InvoiceService.build_hash_payload(invoice)
        data_string = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(data_string.encode()).hexdigest()

    @staticmethod
    def find_drifted_invoices() -> list[dict]:
        """Iterate every finalized invoice and return drift records for
        any whose stored hash no longer matches the recomputed hash.

        Returns ``[{"id", "number", "prefix", "stored", "recomputed"}, ...]``.
        Used by the ``check_invoice_hashes`` management command (run on a
        schedule) for tamper detection on commercial documents.
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
            recomputed = InvoiceService.compute_document_hash(invoice)
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

    @staticmethod
    @transaction.atomic
    def create_from_delivery_note(
        delivery_note: DeliveryNoteReseller,
        date: date | str | None = None,
        user=None,
    ) -> InvoiceReseller:
        """
        Create an InvoiceReseller from a DeliveryNoteReseller.

        Raises:
            ValidationError: If invoice already exists or delivery note is invalid
        """
        # Lock the delivery note row so two concurrent create-invoice
        # requests for the same DN serialize: the second blocks here until
        # the first commits, then sees the existing invoice-content link and
        # raises ConflictError instead of duplicate-billing the DN.
        DeliveryNoteReseller.objects.select_for_update().get(pk=delivery_note.pk)

        # Matches via BOTH the article-line and crate-line provenance links, so
        # a crate-only DN can't be double-billed (the article M2M is empty for
        # it — see get_invoice_for_delivery_note).
        existing_invoice = InvoiceService.get_invoice_for_delivery_note(delivery_note)

        if existing_invoice:
            raise ConflictError(
                f"Invoice already exists for this delivery note: {existing_invoice.number}",
                code="invoice.already_exists",
            )

        invoice_date = coerce_document_date(
            date,
            fallback_date=delivery_note.date,
            fallback_order=getattr(delivery_note, "order", None),
        )
        reseller = delivery_note.order.reseller
        invoice = InvoiceReseller.objects.create(
            date=invoice_date,
            # Persist the payment due date (issue date + the reseller's payment
            # terms) so reminders show the real due date + overdue days. due_date
            # is not in ALLOWED_FINALIZED_UPDATES, so it must be set at creation.
            due_date=_payment_due_date(invoice_date, reseller),
            reseller=reseller,
            created_by=user,
        )

        for delivery_note_content in delivery_note.items.select_related(
            "offer", "offer__share_article", "share_article"
        ):
            InvoiceService._create_invoice_article_content(
                invoice,
                delivery_note_content,
                amount=delivery_note_content.amount,
                tax_rate=effective_article_tax_rate(
                    delivery_note_content, invoice.date
                ),
                rabatt=delivery_note_content.rabatt or 0,
                source_rabatt=delivery_note_content.rabatt,
                order_content=delivery_note_content.order_content,
                delivery_note_contents=(delivery_note_content,),
            )

        for crate_delivery_note_content in delivery_note.crate_items.select_related(
            "crate_type"
        ):
            InvoiceService._create_invoice_crate_content(
                invoice,
                crate_delivery_note_content,
                amount=crate_delivery_note_content.amount,
                tax_rate=(
                    crate_delivery_note_content.tax_rate
                    if crate_delivery_note_content.tax_rate is not None
                    else effective_crate_tax_rate(
                        crate_delivery_note_content.crate_type, invoice.date
                    )
                ),
                rabatt=crate_delivery_note_content.rabatt or 0,
                source_rabatt=crate_delivery_note_content.rabatt,
                crate_delivery_note_contents=(crate_delivery_note_content,),
            )

        # Cascade-up finalize: creating an invoice locks in the upstream DN
        # (and transitively the order). Mirrors create_from_order → finalize_order.
        if not delivery_note.is_finalized:
            from .delivery_note_service import DeliveryNoteService

            DeliveryNoteService.finalize_delivery_note(delivery_note, user=user)

        return invoice

    @staticmethod
    @transaction.atomic
    def finalize_invoice(invoice: InvoiceReseller, user=None) -> bool:
        """
        Finalize an invoice (locks it from further changes).
        Cascades finalization to items, crate items, delivery notes, and orders.
        """
        invoice.assert_not_finalized(label="Invoice", code="invoice.already_finalized")

        # A crate-only invoice (e.g. a deposit/Pfand-only document) is a
        # legitimate finalizable invoice — guard on BOTH line collections so
        # only a genuinely empty invoice is refused.
        if not invoice.items.exists() and not invoice.crate_items.exists():
            raise CommissioningError(
                "Cannot finalize invoice - it has no items",
                code="invoice.empty",
            )

        invoice.assign_final_number()

        # Seal the wider v2 surface (recipient block + document-type /
        # cancellation identity). Set the version BEFORE computing the hash
        # so the payload and the stored version agree. This runs while the
        # invoice is still unfinalized, so the finalized-update guard is not
        # engaged yet.
        invoice.document_hash_version = 2
        # Freeze the §14/§14a recipient from the live Reseller/Contact NOW, so
        # the hash (and any later re-render) reads the snapshot instead of the
        # live row — a subsequent edit or GDPR anonymization of the reseller
        # then can't drift this immutable document. Set before computing the
        # hash so the sealed payload reads the frozen copy.
        #
        # DOC-1: a document created as a mirror of another (a storno of a
        # finalized invoice) may ALREADY carry the recipient block it must
        # legally reproduce. Only freeze from the live row when no snapshot was
        # pre-populated, so a storno keeps the cancelled invoice's §14b recipient
        # even if the reseller's billing address was edited in between.
        if invoice.recipient_snapshot is None:
            invoice.recipient_snapshot = invoice._live_recipient()
        invoice.document_hash = InvoiceService.compute_document_hash(invoice)
        invoice.save(
            update_fields=[
                "document_hash",
                "document_hash_version",
                "recipient_snapshot",
                "number",
                "prefix",
            ]
        )

        # Use the mixin's finalize() — it handles the two-step save
        # needed to bypass FinalizedProtectedMixin
        success = invoice.finalize(user=user)
        if not success:
            return False

        finalize_children(invoice.items, invoice.crate_items, user=user)

        from .delivery_note_service import DeliveryNoteService
        from .order_service import OrderService

        # Cascade-up: finalize each distinct un-finalized upstream delivery
        # note once, and — for manual lines that have no DN — the upstream
        # order once. Prefetch the M2M + FKs so this stays a constant number
        # of queries instead of O(lines) while the per-sequence advisory lock
        # and the outer transaction are held.
        items = invoice.items.prefetch_related(
            "delivery_note_contents__delivery_note"
        ).select_related("order_content")

        delivery_notes: dict[str, DeliveryNoteReseller] = {}
        manual_line_order_ids: set[str] = set()
        for item in items:
            delivery_note_contents = list(item.delivery_note_contents.all())
            if delivery_note_contents:
                for delivery_note_content in delivery_note_contents:
                    delivery_note = delivery_note_content.delivery_note
                    if delivery_note is not None and not delivery_note.is_finalized:
                        delivery_notes[delivery_note.pk] = delivery_note
            elif item.order_content_id:
                manual_line_order_ids.add(item.order_content.order_id)

        # Crate-only invoice: no article items, so the upstream DN lives only on
        # the crate-line provenance link. Walk it too so a crate-only invoice
        # cascade-finalizes its delivery note exactly like an article one.
        crate_items = invoice.crate_items.prefetch_related(
            "crate_delivery_note_contents__delivery_note"
        )
        for crate_item in crate_items:
            for crate_dn_content in crate_item.crate_delivery_note_contents.all():
                delivery_note = crate_dn_content.delivery_note
                if delivery_note is not None and not delivery_note.is_finalized:
                    delivery_notes[delivery_note.pk] = delivery_note

        for delivery_note in delivery_notes.values():
            DeliveryNoteService.finalize_delivery_note(delivery_note, user=user)

        # Re-read order state AFTER the DN finalisations — a DN finalize can
        # cascade up to its own order — so a manual line's order is never
        # double-finalized.
        if manual_line_order_ids:
            from ..models import Order

            for order in Order.objects.filter(
                pk__in=manual_line_order_ids, is_finalized=False
            ):
                OrderService.finalize_order(order, user=user)

        return True

    @staticmethod
    @transaction.atomic
    def create_storno(
        invoice: InvoiceReseller, reason: str, user=None
    ) -> InvoiceReseller:
        """
        Create a storno (cancellation) document for a finalized invoice.
        Copies all line items with negated amounts and auto-finalizes.
        """
        # Serialize concurrent storno attempts on the same invoice: lock the
        # original row, then re-read its cancellation state under the lock.
        # Without this, two concurrent requests both pass
        # ``can_be_cancelled()`` (each reads its own snapshot where
        # ``cancelled_by_invoice`` is still NULL) and both mint an immutable
        # storno — a double VAT reversal. The lock makes the second
        # transaction block until the first commits its
        # ``cancelled_by_invoice`` link, after which the re-check fails.
        invoice = InvoiceReseller.objects.select_for_update().get(pk=invoice.pk)

        if not invoice.can_be_cancelled():
            raise CommissioningError(
                "This invoice cannot be cancelled",
                code="invoice.not_cancellable",
            )

        # A storno is a NEW legal document — date it the day it is issued
        # (today), not the original invoice's date. Previously this relied
        # on the now-removed silent today-default in
        # ``InvoiceReseller.save``.
        storno = InvoiceReseller.objects.create(
            reseller=invoice.reseller,
            document_type="storno",
            cancels_invoice=invoice,
            correction_reason=reason,
            created_by=user,
            date=timezone.localdate(),
        )

        # DOC-1: a storno must reproduce the EXACT §14/§14a recipient of the
        # invoice it cancels (a legally-paired Rechnung/Storno set), NOT a
        # re-resolved live address. resolved_recipient() returns the original's
        # frozen v2 snapshot (or, for a legacy v1 original with no snapshot, a
        # live fallback). Freeze it onto the still-unfinalized storno and mark it
        # v2 so finalize_invoice seals THIS inherited block into the storno's
        # document_hash instead of overwriting it from the live reseller.
        storno.recipient_snapshot = invoice.resolved_recipient()
        storno.document_hash_version = 2
        storno.save(update_fields=["recipient_snapshot", "document_hash_version"])

        # A storno negates each line, copies the tax verbatim, and wires NO
        # provenance M2M; the snapshot mirrors the (negated) storno line so the
        # serializer's *_differs audit fields read "unedited" — a storno is
        # auto-generated and never hand-edited, so a diff would be noise.
        for item in invoice.items.select_related(
            "offer", "share_article", "order_content"
        ):
            InvoiceService._create_invoice_article_content(
                storno,
                item,
                amount=-item.amount,
                tax_rate=item.tax_rate,
                rabatt=item.rabatt,
                source_rabatt=item.rabatt,
                order_content=item.order_content,
            )

        for crate_item in invoice.crate_items.select_related("crate_type"):
            InvoiceService._create_invoice_crate_content(
                storno,
                crate_item,
                amount=-crate_item.amount,
                tax_rate=crate_item.tax_rate,
                rabatt=crate_item.rabatt,
                source_rabatt=crate_item.rabatt,
            )

        InvoiceService.finalize_invoice(storno, user=user)

        invoice.cancelled_by_invoice = storno
        invoice.save(update_fields=["cancelled_by_invoice"])

        return storno

    @staticmethod
    def _validate_summary_delivery_notes(
        delivery_notes: list[DeliveryNoteReseller],
    ):
        """Validate the delivery-note set for a summary invoice and return
        the shared reseller. Preserves the exact validation order and the
        raised ``JasminError`` codes: non-empty first, then same-reseller,
        then all-finalized."""
        if not delivery_notes:
            raise CommissioningError(
                "No delivery notes provided",
                code="invoice.no_delivery_notes",
            )

        reseller = delivery_notes[0].order.reseller
        for delivery_note in delivery_notes:
            if delivery_note.order.reseller_id != reseller.id:
                raise CommissioningError(
                    "All delivery notes must belong to the same reseller",
                    code="invoice.mixed_resellers",
                )

        for delivery_note in delivery_notes:
            if not delivery_note.is_finalized:
                raise CommissioningError(
                    f"Delivery note {delivery_note.prefix}-{delivery_note.number} is not finalized",
                    code="invoice.dn_not_finalized",
                )

        return reseller

    @staticmethod
    def _lock_and_assert_not_invoiced(
        delivery_notes: list[DeliveryNoteReseller],
    ) -> None:
        """Lock the source delivery notes (deterministic pk order to avoid
        deadlocks) so concurrent summary-invoice runs over the same DNs
        serialize, then refuse to bill a DN whose lines are already on an
        invoice — together this prevents double-billing."""
        delivery_note_pks = [delivery_note.pk for delivery_note in delivery_notes]
        list(
            DeliveryNoteReseller.objects.select_for_update()
            .filter(pk__in=delivery_note_pks)
            .order_by("pk")
        )
        already_invoiced = (
            InvoiceResellerContent.objects.filter(
                delivery_note_contents__delivery_note__in=delivery_note_pks
            )
            .select_related("invoice")
            .first()
        )
        # Crate-only DNs link only via the crate provenance M2M.
        already_invoiced_crate = (
            CrateContentInvoiceReseller.objects.filter(
                crate_delivery_note_contents__delivery_note__in=delivery_note_pks
            )
            .select_related("invoice")
            .first()
        )
        existing = already_invoiced or already_invoiced_crate
        if existing:
            raise ConflictError(
                "One or more delivery notes are already invoiced: "
                f"{existing.invoice.number}",
                code="invoice.already_exists",
            )

    @staticmethod
    def _build_summary_article_contents(
        delivery_notes: list[DeliveryNoteReseller],
        invoice: InvoiceReseller,
    ) -> None:
        """Group delivery-note article lines by article variation and create
        one merged ``InvoiceResellerContent`` per group.

        ``tax_rate`` and ``rabatt`` are part of the key — not just
        (article, unit, size, price) — because they directly change the
        net / VAT of the merged line. Two delivery-note lines for the same
        article at the same net price can legitimately carry different tax
        rates (e.g. a VAT-rate change where the net price is held constant
        across the change date) or different discounts; merging them under
        one rate/discount would misstate the VAT on the issued, finalized
        invoice. The effective rate is RESOLVED (stored value, else the
        date-based default) before keying so the key matches the value that
        is actually written to the line.
        """
        content_groups: dict[tuple, dict] = {}

        for delivery_note in delivery_notes:
            for delivery_note_content in delivery_note.items.select_related(
                "offer", "offer__share_article", "share_article"
            ):
                resolved_tax_rate = effective_article_tax_rate(
                    delivery_note_content, invoice.date
                )
                resolved_rabatt = delivery_note_content.rabatt or 0
                key = (
                    delivery_note_content.share_article_id,
                    delivery_note_content.unit,
                    delivery_note_content.size,
                    delivery_note_content.price_per_unit,
                    resolved_tax_rate,
                    resolved_rabatt,
                )

                if key not in content_groups:
                    content_groups[key] = {
                        "dn_contents": [],
                        "total_amount": 0,
                        "first_content": delivery_note_content,
                        "tax_rate": resolved_tax_rate,
                        "rabatt": resolved_rabatt,
                    }

                content_groups[key]["dn_contents"].append(delivery_note_content)
                content_groups[key]["total_amount"] += delivery_note_content.amount or 0

        # A summary line merges its group's totals, omits ``order_content``, and
        # wires every grouped DN content on the M2M. The grouping key guarantees
        # every merged line shares price/unit/size/rabatt; the amount snapshot is
        # the merged total, so the serializer's *_differs fields read "unedited"
        # like on single-DN invoices.
        for group in content_groups.values():
            InvoiceService._create_invoice_article_content(
                invoice,
                group["first_content"],
                amount=group["total_amount"],
                tax_rate=group["tax_rate"],
                rabatt=group["rabatt"],
                source_rabatt=group["rabatt"],
                delivery_note_contents=group["dn_contents"],
            )

    @staticmethod
    def _build_summary_crate_contents(
        delivery_notes: list[DeliveryNoteReseller],
        invoice: InvoiceReseller,
    ) -> None:
        """Group delivery-note crate lines and create one merged
        ``CrateContentInvoiceReseller`` per group. ``tax_rate`` and
        ``rabatt`` are in the key for the same reason as the article lines."""
        crate_groups: dict[tuple, dict] = {}

        for delivery_note in delivery_notes:
            for delivery_note_crate_content in delivery_note.crate_items.select_related(
                "crate_type"
            ):
                resolved_crate_tax_rate = (
                    delivery_note_crate_content.tax_rate
                    if delivery_note_crate_content.tax_rate is not None
                    else effective_crate_tax_rate(
                        delivery_note_crate_content.crate_type, invoice.date
                    )
                )
                resolved_crate_rabatt = delivery_note_crate_content.rabatt or 0
                key = (
                    delivery_note_crate_content.crate_type_id,
                    delivery_note_crate_content.price_per_unit,
                    resolved_crate_tax_rate,
                    resolved_crate_rabatt,
                )

                if key not in crate_groups:
                    crate_groups[key] = {
                        "total_amount": 0,
                        "first_content": delivery_note_crate_content,
                        "tax_rate": resolved_crate_tax_rate,
                        "rabatt": resolved_crate_rabatt,
                        "dn_crate_contents": [],
                    }

                crate_groups[key]["total_amount"] += (
                    delivery_note_crate_content.amount or 0
                )
                crate_groups[key]["dn_crate_contents"].append(
                    delivery_note_crate_content
                )

        # Merged crate line — same rationale as the summary article lines above.
        for group in crate_groups.values():
            InvoiceService._create_invoice_crate_content(
                invoice,
                group["first_content"],
                amount=group["total_amount"],
                tax_rate=group["tax_rate"],
                rabatt=group["rabatt"],
                source_rabatt=group["rabatt"],
                crate_delivery_note_contents=group["dn_crate_contents"],
            )

    @staticmethod
    @transaction.atomic
    def create_summary_invoice_from_delivery_notes(
        delivery_notes: list[DeliveryNoteReseller],
        date: date | str | None = None,
        user=None,
    ) -> InvoiceReseller:
        """
        Create a single summary invoice from multiple delivery notes.
        Groups items by (share_article, unit, size, price_per_unit)
        and sums the amounts. Links all source delivery note contents via M2M.
        """
        reseller = InvoiceService._validate_summary_delivery_notes(delivery_notes)

        InvoiceService._lock_and_assert_not_invoiced(delivery_notes)

        # Pick the latest delivery-note date as fallback so the summary
        # invoice's date covers the whole period being invoiced. All DNs
        # have already been gated on ``is_finalized`` above, and a
        # finalized DN has a non-null date (enforced by
        # ``DeliveryNoteReseller.save``), so ``latest_dn_date`` is
        # guaranteed to be set here. If the caller still manages to
        # produce a ``None`` (e.g. by passing junk that
        # ``coerce_document_date`` discards), ``InvoiceReseller.save``
        # raises ``DocumentDateRequired`` rather than silently dating
        # the invoice to "today".
        latest_delivery_note_date = max(
            (
                delivery_note.date
                for delivery_note in delivery_notes
                if delivery_note.date
            ),
            default=None,
        )
        invoice_date = coerce_document_date(
            date, fallback_date=latest_delivery_note_date
        )
        invoice = InvoiceReseller.objects.create(
            reseller=reseller,
            date=invoice_date,
            due_date=_payment_due_date(invoice_date, reseller),
            created_by=user,
        )

        InvoiceService._build_summary_article_contents(delivery_notes, invoice)
        InvoiceService._build_summary_crate_contents(delivery_notes, invoice)

        invoice.save()
        return invoice

    # -------------------------------------------------------------------
    # Email dispatch
    #
    # Auto-fired by ``InvoiceResellerViewSet.upload_pdf`` once the PDF
    # is on disk — that's the soonest point where every artifact the
    # reseller / accounting needs actually exists. Both helpers are
    # best-effort: a transient SMTP failure must not propagate into the
    # upload-PDF response, because the invoice was already legally
    # finalized in a prior transaction and rolling that back over an
    # email error is wrong. Resend uses the same helpers via an
    # explicit office-triggered action (TODO when product needs it).
    # -------------------------------------------------------------------

    @staticmethod
    def _build_invoice_email_context(invoice: InvoiceReseller) -> dict:
        """Render the ``{{ var }}`` context for the
        ``commissioning.invoice`` template. Identical shape for the
        reseller-facing and accounting-facing sends today; if the
        wording ever needs to diverge, split into two slugs and pass
        different contexts here."""
        from django.db import connection

        reseller = invoice.reseller
        reseller_name = reseller.contact.name if reseller and reseller.contact else ""
        tenant = getattr(connection, "tenant", None)
        tenant_name = getattr(tenant, "name", "") if tenant else ""
        iban = getattr(tenant, "iban", "") if tenant else ""
        bic = getattr(tenant, "bic", "") if tenant else ""
        bank_details = " / ".join(part for part in [iban, bic] if part)

        try:
            terms_days = reseller.get_payment_terms_days() if reseller else 14
        except (AttributeError, TypeError):
            terms_days = 14

        # A storno / correction is a credit note — it has no payment "due
        # date", so don't render a misleading pay-by date for it.
        is_storno = invoice.document_type in ("storno", "correction")
        if invoice.date and not is_storno:
            due_date_str = (invoice.date + timedelta(days=terms_days)).isoformat()
            period_str = invoice.date.strftime("%m/%Y")
        elif invoice.date:
            due_date_str = ""
            period_str = invoice.date.strftime("%m/%Y")
        else:
            due_date_str = ""
            period_str = ""

        try:
            total_str = f"{invoice.sum_brutto:.2f}"
        except (AttributeError, TypeError):
            total_str = ""

        invoice_number = invoice.full_number

        return {
            "tenant_name": tenant_name,
            "reseller": {"name": reseller_name},
            "invoice": {
                "number": invoice_number,
                "period": period_str,
                "total": total_str,
                "due_date": due_date_str,
            },
            "tenant": {"bank_details": bank_details},
        }

    @staticmethod
    def send_to_reseller(invoice: InvoiceReseller) -> bool:
        """Send the invoice PDF (ZUGFeRD embedded) to the reseller's
        ``invoice_email``. Stamps ``has_been_sent_to_reseller_at`` on
        success — the derived ``has_been_sent_to_reseller`` property
        on the model reads True from that timestamp.

        Idempotency is the caller's responsibility — this helper will
        happily re-send if invoked again. The auto-trigger in
        ``upload_pdf`` guards by checking the flag first.

        Best-effort: returns ``False`` on any failure (no reseller
        email configured, no PDF yet, SMTP error, template error).
        Never raises.
        """
        reseller = invoice.reseller
        # EML-2: honour the reseller's channel preference. invoice_via_email
        # (default True) is the explicit opt-out for paper-only resellers;
        # gating here protects every caller (auto-send on upload + any future
        # re-send/bulk path), not just upload_pdf.
        if not reseller or not reseller.invoice_email or not reseller.invoice_via_email:
            logger.info(
                "Skipping invoice-to-reseller send for invoice %s: reseller %s "
                "has no invoice_email or opted out of invoice email",
                invoice.pk,
                getattr(reseller, "pk", "<none>"),
            )
            return False

        attachments = load_pdf_attachments(
            invoice,
            default_pdf_name="rechnung.pdf",
            log_label="invoice",
            include_xml=True,
        )
        return send_document_email(
            invoice,
            slug="commissioning.invoice",
            to_email=reseller.invoice_email,
            context_builder=lambda: InvoiceService._build_invoice_email_context(
                invoice
            ),
            attachments=attachments,
            purpose="invoice:reseller",
            related_object_type="invoice",
            timestamp_field="has_been_sent_to_reseller_at",
            log_label="invoice",
        )

    @staticmethod
    def send_to_accounting(invoice: InvoiceReseller) -> bool:
        """Send the invoice PDF (+ standalone ZUGFeRD XML if present)
        to the tenant's ``accounting_email`` (typically a DATEV-import
        inbox). Same best-effort semantics as
        ``send_to_reseller``. Returns ``False`` and short-circuits when
        ``accounting_email`` isn't configured — many early-stage
        tenants don't have a DATEV pipeline, and that's a fine
        configuration."""
        from django.db import connection

        from apps.shared.tenants.models import TenantEmailConfig

        schema_name = getattr(getattr(connection, "tenant", None), "schema_name", None)
        if not schema_name:
            return False
        try:
            cfg = TenantEmailConfig.objects.get(
                tenant__schema_name=schema_name, is_active=True
            )
        except TenantEmailConfig.DoesNotExist:
            return False
        if not cfg.accounting_email:
            return False

        attachments = load_pdf_attachments(
            invoice,
            default_pdf_name="rechnung.pdf",
            log_label="invoice",
            include_xml=True,
        )
        return send_document_email(
            invoice,
            slug="commissioning.invoice",
            to_email=cfg.accounting_email,
            context_builder=lambda: InvoiceService._build_invoice_email_context(
                invoice
            ),
            attachments=attachments,
            purpose="invoice:accounting",
            related_object_type="invoice",
            timestamp_field="has_been_sent_to_accounting_at",
            log_label="invoice",
        )
