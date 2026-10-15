from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.shared.display_formats import DisplayFormats
from apps.shared.tenants.models import RateLimitedAction
from apps.shared.tenants.rate_limits import enforce_action_quota
from core.errors import ConflictError

from ..constants import crates_should_be_on_documents
from ..errors import CommissioningError
from ..models import (
    CrateContentInvoiceReseller,
    DeliveryNoteReseller,
    InvoiceReseller,
    InvoiceResellerContent,
)
from ..utils.iso_week_utils import coerce_document_date
from .delivery_note_invoices import current_invoices_by_delivery_note
from .email_dispatch import load_pdf_attachments, send_document_email
from .finalize_utils import finalize_children
from .invoice_hash import compute_document_hash

logger = logging.getLogger(__name__)


def _payment_due_date(invoice_date, reseller):
    """Payment due date for a reseller invoice: issue date + the reseller's
    payment terms (default 14 days). Returns ``None`` when there is no issue
    date. Storno / correction credit notes deliberately get no due date."""
    if invoice_date is None:
        return None
    try:
        terms_days = reseller.get_payment_terms_days()
    except TypeError:
        # The tenant-settings lookup refuses a connection tenant without a
        # ``schema_name``; fall back to the default terms.
        terms_days = 14
    return invoice_date + timedelta(days=terms_days)


@dataclass(frozen=True)
class InvoiceLinePricing:
    """What a call site decides for one invoice line: the amount (negated on a
    storno), the tax rate, the discount, and the raw ``source_rabatt``
    snapshot, which can differ from the coerced ``rabatt``."""

    amount: Any
    tax_rate: Any
    rabatt: Any
    source_rabatt: Any


class InvoiceService:
    """Service for managing invoices."""

    @staticmethod
    def get_invoice_for_delivery_note(
        delivery_note,
    ) -> InvoiceReseller | None:
        """Return the current invoice of *delivery_note*, or ``None``.

        The current one is the newest that isn't cancelled, else the newest
        overall, reached through article and crate lines alike (see
        ``current_invoices_by_delivery_note``).
        """
        if not delivery_note:
            return None
        return current_invoices_by_delivery_note([delivery_note.pk]).get(
            delivery_note.pk
        )

    @staticmethod
    def get_invoices_for_delivery_notes(
        delivery_note_ids,
    ) -> dict[str, InvoiceReseller]:
        """Batch form of ``get_invoice_for_delivery_note``: map each delivery
        note id to its current invoice in a constant number of queries, however
        many notes are asked for. Notes without an invoice are left out."""
        return current_invoices_by_delivery_note(delivery_note_ids)

    @staticmethod
    def unfinalized_upstream_delivery_note_ids(invoice_ids) -> set[str]:
        """The unfinalized delivery notes that finalizing these invoices
        cascades to (see ``finalize_invoice``): those behind their article
        lines and those behind their crate lines, in two queries. A bulk
        finalize reserves their quota up front."""
        ids = list(invoice_ids)
        if not ids:
            return set()
        article_notes = InvoiceResellerContent.objects.filter(
            invoice_id__in=ids,
            delivery_note_contents__delivery_note__is_finalized=False,
        ).values_list("delivery_note_contents__delivery_note_id", flat=True)
        crate_notes = CrateContentInvoiceReseller.objects.filter(
            invoice_id__in=ids,
            crate_delivery_note_contents__delivery_note__is_finalized=False,
        ).values_list("crate_delivery_note_contents__delivery_note_id", flat=True)
        return {str(pk) for pk in article_notes} | {str(pk) for pk in crate_notes}

    @staticmethod
    def _create_invoice_article_content(
        invoice: InvoiceReseller,
        source_row,
        pricing: InvoiceLinePricing,
        *,
        order_content=None,
        delivery_note_contents=(),
    ) -> InvoiceResellerContent:
        """Create one ``InvoiceResellerContent`` article line from an upstream
        row, owning the identity kwargs, the FULL ``source_*`` snapshot block,
        and the provenance M2M so every write path (create-from-DN / storno /
        summary) produces a byte-identical audit surface.

        These are legally-immutable (GoBD/UStG) documents: a missed ``source_*``
        field silently breaks the serializer's ``*_differs`` audit, so the five
        snapshot fields are laid out in one place here. ``pricing`` — amount /
        sign / ``tax_rate`` / ``rabatt`` and the raw ``source_rabatt`` snapshot,
        which legitimately diverges from the coerced ``rabatt or 0`` on the
        create path — is decided at the CALL SITE:

          * create-from-DN passes the positive amount + the DN content's tax
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
            amount=pricing.amount,
            price_per_unit=source_row.price_per_unit,
            rabatt=pricing.rabatt,
            tax_rate=pricing.tax_rate,
            # Snapshot of the upstream row so the serializer's *_differs
            # fields are pure local comparisons on this immutable document.
            source_amount=pricing.amount,
            source_price_per_unit=source_row.price_per_unit,
            source_rabatt=pricing.source_rabatt,
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
        pricing: InvoiceLinePricing,
        *,
        crate_delivery_note_contents=(),
    ) -> CrateContentInvoiceReseller:
        """Create one ``CrateContentInvoiceReseller`` line from an upstream crate
        row — the crate counterpart to ``_create_invoice_article_content``.

        Owns the three ``source_*`` snapshot fields (crates carry no unit/size)
        + the crate provenance M2M. As with the article helper, ``pricing`` is
        decided at the call site; storno wires no M2M.
        """
        content = CrateContentInvoiceReseller.objects.create(
            invoice=invoice,
            crate_type=source_row.crate_type,
            amount=pricing.amount,
            price_per_unit=source_row.price_per_unit,
            rabatt=pricing.rabatt,
            tax_rate=pricing.tax_rate,
            note=source_row.note,
            # Snapshot of the upstream crate row — same rationale as above.
            source_amount=pricing.amount,
            source_price_per_unit=source_row.price_per_unit,
            source_rabatt=pricing.source_rabatt,
        )
        if crate_delivery_note_contents:
            content.crate_delivery_note_contents.add(*crate_delivery_note_contents)
        return content

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
        # a crate-only DN can't be double-billed. A cancelled invoice counts
        # too: a storno is final and doesn't free the DN for a new invoice.
        existing_invoice = InvoiceService.get_invoice_for_delivery_note(delivery_note)

        if existing_invoice:
            raise ConflictError(
                f"Invoice already exists for this delivery note: {existing_invoice.number}",
                code="invoice.already_exists",
            )

        invoice_date = coerce_document_date(
            date,
            fallback_date=delivery_note.date,
            fallback_order=delivery_note.order,
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
            "offer", "share_article"
        ):
            InvoiceService._create_invoice_article_content(
                invoice,
                delivery_note_content,
                # ``InvoiceResellerContent.amount`` is NOT NULL while the upstream
                # ``DeliveryNoteContent.amount`` is nullable, so an uncoerced None
                # would abort the whole atomic invoice creation with an IntegrityError.
                # The SUMMARY invoice path coerces the same value (``amount or 0``
                # when accumulating ``total_amount``), so both paths accept the same
                # data. ``rabatt`` below is coerced too.
                InvoiceLinePricing(
                    amount=delivery_note_content.amount or 0,
                    tax_rate=delivery_note_content.tax_rate,
                    rabatt=delivery_note_content.rabatt or 0,
                    source_rabatt=delivery_note_content.rabatt,
                ),
                order_content=delivery_note_content.order_content,
                delivery_note_contents=(delivery_note_content,),
            )

        # Defence-in-depth: don't copy crates onto the invoice when the tenant
        # keeps crates OFF documents — covers pre-existing delivery-note crates
        # (from before the setting was turned off) so totals never count them.
        crate_items = (
            delivery_note.crate_items.select_related("crate_type")
            if crates_should_be_on_documents()
            else delivery_note.crate_items.none()
        )
        for crate_delivery_note_content in crate_items:
            InvoiceService._create_invoice_crate_content(
                invoice,
                crate_delivery_note_content,
                InvoiceLinePricing(
                    amount=crate_delivery_note_content.amount,
                    tax_rate=crate_delivery_note_content.tax_rate,
                    rabatt=crate_delivery_note_content.rabatt or 0,
                    source_rabatt=crate_delivery_note_content.rabatt,
                ),
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
    def finalize_invoice(
        invoice: InvoiceReseller, user=None, *, skip_quota: bool = False
    ) -> bool:
        """
        Finalize an invoice (locks it from further changes).
        Cascades finalization to items, crate items, delivery notes, and orders.

        ``skip_quota=True`` is passed by bulk endpoints that have already
        reserved the whole batch against the weekly cap up front (see
        ``apps.commissioning.services.finalization_quota``); it suppresses the
        per-item guard — for the invoice and for the delivery notes it
        cascades to, whose quota the caller reserves too
        (``unfinalized_upstream_delivery_note_ids``) — so a legitimate bulk
        finalize doesn't trip the per-minute burst cap mid-batch.
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

        # Volume cap: refuse if this tenant is over its finalization quota. This
        # is the legally-relevant moment (a sequential number is minted and the
        # document auto-sends), so it is where a compromised office account could
        # do the most damage. Storno creation routes through here too, so both
        # invoices and cancellations draw on the one INVOICE_FINALIZATION cap.
        # Runs before assign_final_number so a refused call burns no number.
        if not skip_quota:
            enforce_action_quota(RateLimitedAction.INVOICE_FINALIZATION, actor=user)

        invoice.assign_final_number()

        # Freeze the §14/§14a recipient from the live Reseller/Contact NOW, so
        # the hash (and any later re-render) reads the snapshot instead of the
        # live row — a subsequent edit or GDPR anonymization of the reseller
        # then can't drift this immutable document. Set before computing the
        # hash so the sealed payload reads the frozen copy.
        #
        # A document created as a mirror of another (a storno of a
        # finalized invoice) may ALREADY carry the recipient block it must
        # legally reproduce. Only freeze from the live row when no snapshot was
        # pre-populated, so a storno keeps the cancelled invoice's §14b recipient
        # even if the reseller's billing address was edited in between.
        if invoice.recipient_snapshot is None:
            invoice.recipient_snapshot = invoice._live_recipient()
        invoice.document_hash = compute_document_hash(invoice)
        invoice.save(
            update_fields=[
                "document_hash",
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
                    if not delivery_note.is_finalized:
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
            DeliveryNoteService.finalize_delivery_note(
                delivery_note, user=user, skip_quota=skip_quota
            )

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
        # (today), not the original invoice's date.
        storno = InvoiceReseller.objects.create(
            reseller=invoice.reseller,
            document_type="storno",
            cancels_invoice=invoice,
            correction_reason=reason,
            created_by=user,
            date=timezone.localdate(),
        )

        # A storno must reproduce the EXACT §14/§14a recipient of the
        # invoice it cancels (a legally-paired Rechnung/Storno set), NOT a
        # re-resolved live address. resolved_recipient() returns the original's
        # frozen snapshot. Freeze it onto the still-unfinalized storno, so
        # finalize_invoice seals THIS inherited block into the storno's
        # document_hash instead of overwriting it from the live reseller.
        storno.recipient_snapshot = invoice.resolved_recipient()
        storno.save(update_fields=["recipient_snapshot"])

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
                InvoiceLinePricing(
                    amount=-item.amount,
                    tax_rate=item.tax_rate,
                    rabatt=item.rabatt,
                    source_rabatt=item.rabatt,
                ),
                order_content=item.order_content,
            )

        for crate_item in invoice.crate_items.select_related("crate_type"):
            InvoiceService._create_invoice_crate_content(
                storno,
                crate_item,
                InvoiceLinePricing(
                    amount=-crate_item.amount,
                    tax_rate=crate_item.tax_rate,
                    rabatt=crate_item.rabatt,
                    source_rabatt=crate_item.rabatt,
                ),
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
        serialize, then refuse to bill a DN any invoice already holds, a
        cancelled one included — together this prevents double-billing."""
        delivery_note_pks = [delivery_note.pk for delivery_note in delivery_notes]
        list(
            DeliveryNoteReseller.objects.select_for_update()
            .filter(pk__in=delivery_note_pks)
            .order_by("pk")
        )
        billed = current_invoices_by_delivery_note(delivery_note_pks)
        if billed:
            existing = billed[min(billed)]
            raise ConflictError(
                "One or more delivery notes are already invoiced: "
                f"{existing.number}",
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
        invoice.
        """
        content_groups: dict[tuple, dict] = {}

        for delivery_note in delivery_notes:
            for delivery_note_content in delivery_note.items.select_related(
                "offer", "share_article"
            ):
                resolved_tax_rate = delivery_note_content.tax_rate
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
                InvoiceLinePricing(
                    amount=group["total_amount"],
                    tax_rate=group["tax_rate"],
                    rabatt=group["rabatt"],
                    source_rabatt=group["rabatt"],
                ),
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

        # Skip crates entirely when the tenant keeps them OFF documents (read the
        # setting once — no per-note query). Covers pre-existing delivery-note
        # crates so a multi-note invoice's totals never count them.
        include_crates = crates_should_be_on_documents()
        for delivery_note in delivery_notes:
            crate_items = (
                delivery_note.crate_items.select_related("crate_type")
                if include_crates
                else delivery_note.crate_items.none()
            )
            for delivery_note_crate_content in crate_items:
                resolved_crate_tax_rate = delivery_note_crate_content.tax_rate
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

                crate_groups[key]["total_amount"] += delivery_note_crate_content.amount
                crate_groups[key]["dn_crate_contents"].append(
                    delivery_note_crate_content
                )

        # Merged crate line — same rationale as the summary article lines above.
        for group in crate_groups.values():
            InvoiceService._create_invoice_crate_content(
                invoice,
                group["first_content"],
                InvoiceLinePricing(
                    amount=group["total_amount"],
                    tax_rate=group["tax_rate"],
                    rabatt=group["rabatt"],
                    source_rabatt=group["rabatt"],
                ),
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
    # email error is wrong. The office sends again through the viewset's
    # ``send_to_reseller`` / ``send_to_accounting`` actions, which call
    # the same helpers.
    # -------------------------------------------------------------------

    @staticmethod
    def reseller_recipient(invoice: InvoiceReseller) -> str | None:
        """The address an invoice email to the reseller goes to, or ``None``
        when there is none or the reseller takes invoices on paper only
        (``invoice_via_email`` off)."""
        reseller = invoice.reseller
        if not reseller.invoice_email or not reseller.invoice_via_email:
            return None
        return reseller.invoice_email

    @staticmethod
    def accounting_recipient() -> str | None:
        """The tenant's accounting inbox (typically a DATEV import address),
        or ``None`` when none is configured — a fine setup for a tenant
        without such a pipeline."""
        from apps.shared.tenants.models import TenantEmailConfig
        from core.tenant_db import connection

        config = TenantEmailConfig.get_active_for_schema(connection.tenant.schema_name)
        return (config.accounting_email or None) if config else None

    @staticmethod
    def send_claimed(
        invoice: InvoiceReseller,
        send: Callable[[InvoiceReseller], bool],
        *,
        timestamp_field: str,
        claimed_at: datetime,
    ) -> bool:
        """Run ``send`` for a send ``upload_pdf`` has claimed by stamping
        ``timestamp_field`` with ``claimed_at``, and release the claim if the
        send fails or raises, so the invoice reads as unsent and can be sent
        again. Only a process that dies mid-send leaves a claim behind; the
        office's send-again recovers it.
        """
        try:
            sent = send(invoice)
        except Exception:
            # The send helpers catch the failures they expect. Anything else
            # must not leave the claim standing either.
            logger.exception(
                "Sending invoice %s (%s) raised", invoice.pk, timestamp_field
            )
            sent = False
        if not sent:
            InvoiceService._release_claim(
                invoice, timestamp_field=timestamp_field, claimed_at=claimed_at
            )
        return sent

    @staticmethod
    @transaction.atomic
    def _release_claim(
        invoice: InvoiceReseller, *, timestamp_field: str, claimed_at: datetime
    ) -> None:
        # Only while the field still holds this claim: a send that succeeded
        # meanwhile stamped its own time, and that stays. A save rather than
        # ``.update()``, so auditlog records the release as it did the claim.
        row = InvoiceReseller.objects.select_for_update().get(pk=invoice.pk)
        if getattr(row, timestamp_field) == claimed_at:
            setattr(row, timestamp_field, None)
            row.save(update_fields=[timestamp_field])

    @staticmethod
    def _build_invoice_email_context(invoice: InvoiceReseller) -> dict:
        """Render the ``{{ var }}`` context for the
        ``commissioning.invoice`` template. Identical shape for the
        reseller-facing and accounting-facing sends today; if the
        wording ever needs to diverge, split into two slugs and pass
        different contexts here."""
        from apps.shared.tenants.email_service import capture_tenant_email_context

        reseller = invoice.reseller
        # ``name`` is None for a contact with no company, first or last name.
        reseller_name = reseller.contact.name or ""
        # Invoices are sent from office requests, so the tenant is the real one.
        tenant_context = capture_tenant_email_context()

        try:
            terms_days = reseller.get_payment_terms_days()
        except TypeError:
            # The tenant-settings lookup refuses a connection tenant without a
            # ``schema_name``; fall back to the default terms.
            terms_days = 14

        formats = DisplayFormats.current()
        # A storno / correction is a credit note — it has no payment "due
        # date", so don't render a misleading pay-by date for it.
        is_storno = invoice.document_type in ("storno", "correction")
        if invoice.date and not is_storno:
            due_date_str = formats.format_date(
                invoice.date + timedelta(days=terms_days)
            )
            period_str = invoice.date.strftime("%m/%Y")
        elif invoice.date:
            due_date_str = ""
            period_str = invoice.date.strftime("%m/%Y")
        else:
            due_date_str = ""
            period_str = ""

        total_str = formats.format_money(invoice.sum_brutto)

        invoice_number = invoice.full_number

        return {
            "tenant_name": tenant_context["tenant_name"],
            "reseller": {"name": reseller_name},
            "invoice": {
                "number": invoice_number,
                "period": period_str,
                "total": total_str,
                "due_date": due_date_str,
            },
            "tenant": {"bank_details": tenant_context["bank_details"]},
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
        # Gating here, on the reseller's address and channel preference
        # (``invoice_via_email`` off means paper only), protects every caller:
        # the auto-send on upload and the office's re-send alike.
        to_email = InvoiceService.reseller_recipient(invoice)
        if to_email is None:
            logger.info(
                "Skipping invoice-to-reseller send for invoice %s: reseller %s "
                "has no invoice_email or opted out of invoice email",
                invoice.pk,
                invoice.reseller_id,
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
            to_email=to_email,
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
        to_email = InvoiceService.accounting_recipient()
        if to_email is None:
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
            to_email=to_email,
            context_builder=lambda: InvoiceService._build_invoice_email_context(
                invoice
            ),
            attachments=attachments,
            purpose="invoice:accounting",
            related_object_type="invoice",
            timestamp_field="has_been_sent_to_accounting_at",
            log_label="invoice",
        )
