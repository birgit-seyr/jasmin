from __future__ import annotations

import logging
from datetime import date

from django.db import models, transaction

from apps.shared.tenants.models import RateLimitedAction
from apps.shared.tenants.rate_limits import enforce_action_quota
from core.errors import ConflictError

from ..errors import CommissioningError
from ..models import (
    CrateDeliveryNoteContent,
    CrateOrderContent,
    DeliveryNoteContent,
    DeliveryNoteReseller,
    Order,
)
from ..utils.iso_week_utils import coerce_document_date
from .email_dispatch import load_pdf_attachments, send_document_email
from .finalize_utils import finalize_children

logger = logging.getLogger(__name__)


class DeliveryNoteService:
    """Service for managing delivery notes."""

    @staticmethod
    @transaction.atomic
    def create_from_order(
        order: Order,
        date: date | str | None = None,
        user=None,
    ) -> DeliveryNoteReseller:
        """
        Create a DeliveryNoteReseller from an Order.

        Raises:
            ValidationError: If delivery note already exists
        """
        if getattr(order, "delivery_note", None):
            raise ConflictError(
                "Delivery note already exists for this order",
                code="delivery_note.already_exists",
            )

        # Under the one-way finalize contract, a finalized order without a
        # delivery note is a legally inconsistent state (the DN cannot have
        # been deleted without also deleting the order). Refuse loudly
        # rather than silently re-issuing a number for an immutable order.

        delivery_note = DeliveryNoteReseller.objects.create(
            date=coerce_document_date(date, fallback_order=order),
            order=order,
            created_by=user,
        )

        for order_content in order.ordercontent_set.select_related(
            "offer", "offer__share_article", "share_article"
        ):
            offer = order_content.offer
            share_article = (
                offer.share_article if offer else order_content.share_article
            )
            unit = offer.unit if offer else order_content.unit
            size = offer.size if offer else order_content.size

            DeliveryNoteContent.objects.create(
                delivery_note=delivery_note,
                order_content=order_content,
                share_article=share_article,
                description=(offer.description if offer else order_content.description),
                unit=unit,
                size=size,
                price_per_unit=order_content.price_per_unit,
                sort=offer.sort if offer else order_content.sort,
                rabatt=order_content.rabatt,
                tax_rate=order_content.tax_rate,
                amount=order_content.amount,
                # Snapshot of upstream OrderContent (with offer fallback) so
                # the *_differs serializer fields are pure local comparisons.
                source_amount=order_content.amount,
                source_price_per_unit=order_content.price_per_unit,
                source_rabatt=order_content.rabatt,
                source_unit=unit,
                source_size=size,
            )

        # Create crate delivery note contents from ALL crate order contents
        all_crate_contents = (
            CrateOrderContent.objects.filter(
                models.Q(order=order) | models.Q(order_content__order=order)
            )
            .select_related("crate_type")
            .distinct()
        )

        for crate_content in all_crate_contents:
            CrateDeliveryNoteContent.objects.create(
                delivery_note=delivery_note,
                crate_type=crate_content.crate_type,
                amount=crate_content.amount,
                price_per_unit=crate_content.price_per_unit,
                rabatt=crate_content.rabatt,
                tax_rate=crate_content.tax_rate,
                note=crate_content.note,
                # Snapshot of upstream CrateOrderContent.
                source_amount=crate_content.amount,
                source_price_per_unit=crate_content.price_per_unit,
                source_rabatt=crate_content.rabatt,
            )

        if not order.is_finalized:
            from .order_service import OrderService

            OrderService.finalize_order(order, user=user)

        return delivery_note

    @staticmethod
    @transaction.atomic
    def finalize_delivery_note(
        delivery_note: DeliveryNoteReseller, user=None, *, skip_quota: bool = False
    ) -> bool:
        """
        Finalize a delivery note and cascade to items, crate items, and the order.

        ``skip_quota=True`` is passed by bulk endpoints that have already
        reserved the whole batch against the weekly cap up front, so a legitimate
        bulk finalize doesn't trip the per-minute burst cap mid-batch.
        """
        delivery_note.assert_not_finalized(
            label="Delivery note", code="delivery_note.already_finalized"
        )

        has_items = delivery_note.items.exists() or delivery_note.crate_items.exists()
        if not has_items:
            raise CommissioningError(
                "Cannot finalize delivery note - it has no items",
                code="delivery_note.empty",
            )

        # Volume cap on the legally-relevant finalization step (mints a
        # sequential number, becomes a sendable document). Before
        # assign_final_number so a refused call burns no number.
        if not skip_quota:
            enforce_action_quota(
                RateLimitedAction.DELIVERY_NOTE_FINALIZATION, actor=user
            )

        delivery_note.assign_final_number()
        delivery_note.save(update_fields=["number", "prefix"])

        success = delivery_note.finalize(user=user)
        if not success:
            return False

        finalize_children(delivery_note.items, delivery_note.crate_items, user=user)

        if delivery_note.order and not delivery_note.order.is_finalized:
            from .order_service import OrderService

            OrderService.finalize_order(delivery_note.order, user=user)

        return True

    # -------------------------------------------------------------------
    # Email dispatch
    #
    # Manual, NOT auto-fired. Unlike the invoice (where upload_pdf
    # auto-triggers send_to_reseller via transaction.on_commit), the
    # delivery note's canonical artifact is the paper copy that rides
    # in the box. The email is an opt-in advance-notice / reconciliation
    # aid that an office user triggers per-DN via the
    # ``DeliveryNoteResellerViewSet.send_to_reseller`` action.
    #
    # Mirrors the InvoiceService send shape (best-effort, never raises,
    # bounded exception list, post-finalize tracker flip via
    # ALLOWED_FINALIZED_UPDATES).
    # -------------------------------------------------------------------

    @staticmethod
    def _build_delivery_note_email_context(delivery_note: DeliveryNoteReseller) -> dict:
        """Render the ``{{ var }}`` context for the
        ``commissioning.delivery_note`` template."""
        from django.db import connection

        reseller = delivery_note.order.reseller if delivery_note.order else None
        reseller_name = reseller.contact.name if reseller and reseller.contact else ""

        tenant = getattr(connection, "tenant", None)
        tenant_name = getattr(tenant, "name", "") if tenant else ""

        delivery_note_number = delivery_note.full_number

        if delivery_note.date:
            date_str = delivery_note.date.strftime("%d.%m.%Y")
        else:
            date_str = ""

        order = delivery_note.order
        order_number = order.full_number if order is not None else ""

        return {
            "tenant_name": tenant_name,
            "reseller": {"name": reseller_name},
            "delivery_note": {
                "number": delivery_note_number,
                "date": date_str,
                "order_number": order_number,
            },
        }

    @staticmethod
    def send_to_reseller(delivery_note: DeliveryNoteReseller) -> bool:
        """Send the delivery-note PDF to the reseller's
        ``invoice_email`` (resellers use the same inbox for both
        invoice and DN correspondence). Flips
        ``has_been_sent_to_reseller_at`` (the derived
        ``has_been_sent_to_reseller`` @property reads True from it)
        on success.

        Idempotency is the caller's responsibility — this helper will
        happily re-send if invoked again. The viewset action checks
        the flag at the boundary; calling this directly from a
        management command would resend.

        Best-effort: returns ``False`` on any failure (no reseller
        email configured, no PDF on disk, SMTP error, template
        error). Never raises.
        """
        reseller = delivery_note.order.reseller if delivery_note.order else None
        if not reseller or not reseller.invoice_email:
            logger.info(
                "Skipping DN-to-reseller send for DN %s: no "
                "invoice_email on reseller %s",
                delivery_note.pk,
                getattr(reseller, "pk", "<none>"),
            )
            return False

        # No XML attachment for DNs — ZUGFeRD is invoice-only.
        attachments = load_pdf_attachments(
            delivery_note,
            default_pdf_name="lieferschein.pdf",
            log_label="delivery note",
        )
        return send_document_email(
            delivery_note,
            slug="commissioning.delivery_note",
            to_email=reseller.invoice_email,
            context_builder=lambda: (
                DeliveryNoteService._build_delivery_note_email_context(delivery_note)
            ),
            attachments=attachments,
            purpose="delivery_note:reseller",
            related_object_type="delivery_note",
            timestamp_field="has_been_sent_to_reseller_at",
            log_label="delivery note",
        )
