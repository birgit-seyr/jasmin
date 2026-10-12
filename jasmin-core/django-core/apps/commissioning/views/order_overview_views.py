"""The office's combined overview of orders with their delivery notes and
invoices."""

from __future__ import annotations

from typing import Any

from django.db.models import prefetch_related_objects
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authz.permissions import APIViewRolePermissionsMixin, IsOffice

from ..models import InvoiceReseller, Order
from ..schemas import (
    get_day_number_parameter,
    get_delivery_week_parameter,
    get_reseller_parameter,
    get_year_parameter,
)
from ..serializers.order_overview_serializer import CombinedOrderOverviewSerializer
from ..services.delivery_note_invoices import current_invoices_by_delivery_note
from ..utils.iso_week_utils import week_day_to_date
from ..utils.query_params import validate_query_params


class CombinedOrderOverviewView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice
    """Get combined overview of orders with related delivery notes and invoices."""

    @extend_schema(
        summary="Get Combined Order Overview",
        description="""
        Get a comprehensive overview of orders including:
        - Order details (number, date, status)
        - Reseller information
        - Related delivery note (if exists)
        - Related invoice (if exists)
        - Payment status
        
        Results can be filtered by year, week, day_number, and reseller.
        """,
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=False),
            get_day_number_parameter(required=False),
            get_reseller_parameter(required=False),
        ],
        responses={
            200: CombinedOrderOverviewSerializer(many=True),
        },
    )
    def get(self, request: Request) -> Response:
        """Get combined overview of orders with delivery notes and invoices."""
        # year is required: without it this office endpoint would materialize
        # every order across all years with no pagination.
        params = validate_query_params(
            request,
            required=["year"],
            optional=["delivery_week", "day_number", "reseller"],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]
        reseller_id = params["reseller"]

        # Build query with optimized prefetching. The prefetches feed
        # ``sum_netto`` for whichever document wins in ``_get_total_price``
        # (invoice > delivery_note > order): delivery-note + order line items
        # here; invoice line items come from the batched lookup below.
        queryset = Order.objects.select_related(
            "reseller__contact", "delivery_note"
        ).prefetch_related(
            "delivery_note__items__share_article",
            "delivery_note__crate_items",
            "ordercontent_set",
            "crateordercontent_set",
            # Offer-bound deposits hang off OrderContent (order=NULL); Order's
            # money totals include them, so prefetch this edge too to keep
            # the order list query-free per order.
            "ordercontent_set__crateordercontent_set",
        )

        # Apply filters if provided
        filters: dict[str, Any] = {"year": year}
        if delivery_week:
            filters["delivery_week"] = delivery_week
        if day_number is not None:
            filters["day_number"] = day_number
        if reseller_id:
            filters["reseller__id"] = reseller_id

        # Order by most recent first
        orders = list(
            queryset.filter(**filters).order_by(
                "-year", "-delivery_week", "-day_number"
            )
        )

        # ``delivery_note`` is a REVERSE OneToOne (the FK lives on
        # DeliveryNoteReseller), so Order has no ``delivery_note_id`` — read the
        # related object (cached by ``select_related`` above) and take its id.
        delivery_notes = {
            order.pk: getattr(order, "delivery_note", None) for order in orders
        }

        # Batch the per-order invoice lookup (``get_invoice_for_delivery_note``)
        # over the whole page.
        invoice_by_delivery_note = self._invoices_by_delivery_note(
            [
                delivery_note.id
                for delivery_note in delivery_notes.values()
                if delivery_note is not None
            ]
        )

        # Build response data
        result = []
        for order in orders:
            delivery_note = delivery_notes[order.pk]
            invoice = (
                invoice_by_delivery_note.get(delivery_note.id)
                if delivery_note
                else None
            )
            result.append(self._build_order_overview(order, invoice))

        return Response(result)

    @staticmethod
    def _invoices_by_delivery_note(
        delivery_note_ids: list[str],
    ) -> dict[str, InvoiceReseller]:
        """Map ``delivery_note_id -> InvoiceReseller`` for the whole page in a
        constant number of queries (batched form of
        ``InvoiceService.get_invoice_for_delivery_note``). The invoice's line
        items ride along for ``sum_netto``, its cancelling storno for the
        storno fields."""
        invoice_by_delivery_note = current_invoices_by_delivery_note(delivery_note_ids)
        prefetch_related_objects(
            list(invoice_by_delivery_note.values()), "items", "crate_items"
        )
        return invoice_by_delivery_note

    def _build_order_overview(
        self, order: Order, invoice: InvoiceReseller | None
    ) -> dict[str, Any]:
        """Build overview data for a single order. ``invoice`` is resolved by
        the caller's batched lookup (``None`` when the order has no invoice)."""
        delivery_note = getattr(order, "delivery_note", None)
        order_date = self._calculate_order_date(
            order.year, order.delivery_week, order.day_number
        )

        return {
            # Order information
            "id": str(order.id),
            "order_number": order.full_number,
            "order_date": order_date.isoformat() if order_date else None,
            "order_is_finalized": order.is_finalized,
            "sum_netto": self._get_total_price(invoice, delivery_note, order),
            # Reseller information
            "reseller_id": str(order.reseller_id),
            "reseller_name": self._get_reseller_name(order),
            # Delivery note information
            "has_delivery_note": delivery_note is not None,
            "delivery_note_id": str(delivery_note.id) if delivery_note else None,
            "delivery_note_number": self._format_document_number(delivery_note),
            "delivery_note_prefix": delivery_note.prefix if delivery_note else None,
            "delivery_note_date": (
                delivery_note.date.isoformat()
                if delivery_note and delivery_note.date
                else None
            ),
            "delivery_note_is_finalized": (
                delivery_note.is_finalized if delivery_note else False
            ),
            "delivery_note_has_been_sent_to_reseller": (
                delivery_note.has_been_sent_to_reseller if delivery_note else False
            ),
            "delivery_note_has_been_sent_to_reseller_at": (
                delivery_note.has_been_sent_to_reseller_at.isoformat()
                if delivery_note and delivery_note.has_been_sent_to_reseller_at
                else None
            ),
            # Invoice information
            "has_invoice": invoice is not None,
            "invoice_id": str(invoice.id) if invoice else None,
            "invoice_number": self._format_document_number(invoice),
            "invoice_date": (
                invoice.date.isoformat() if invoice and invoice.date else None
            ),
            "has_finalized_invoice": invoice.is_finalized if invoice else False,
            "invoice_finalized_at": (
                invoice.finalized_at.isoformat()
                if invoice and invoice.finalized_at
                else None
            ),
            "invoice_has_been_sent_to_reseller": (
                invoice.has_been_sent_to_reseller if invoice else False
            ),
            "invoice_has_been_sent_to_reseller_at": (
                invoice.has_been_sent_to_reseller_at.isoformat()
                if invoice and invoice.has_been_sent_to_reseller_at
                else None
            ),
            "invoice_has_been_sent_to_accounting": (
                invoice.has_been_sent_to_accounting if invoice else False
            ),
            "invoice_has_been_sent_to_accounting_at": (
                invoice.has_been_sent_to_accounting_at.isoformat()
                if invoice and invoice.has_been_sent_to_accounting_at
                else None
            ),
            "has_been_paid": invoice.has_been_paid if invoice else None,
            "note": invoice.note if invoice else None,
            "invoice_cancelled_by": (
                str(invoice.cancelled_by_invoice_id)
                if invoice and invoice.cancelled_by_invoice_id
                else None
            ),
            "invoice_storno_id": (
                str(invoice.cancelled_by_invoice_id)
                if invoice and invoice.cancelled_by_invoice_id
                else None
            ),
            "invoice_storno_number": (
                invoice.cancelled_by_invoice.full_number
                if invoice and invoice.cancelled_by_invoice
                else None
            ),
        }

    def _calculate_order_date(
        self,
        year: int,
        delivery_week: int,
        day_number: int | None,
    ) -> Any:
        """Calculate order date from year, week, and day_number."""
        if day_number is None:
            return None

        try:
            return week_day_to_date(year, delivery_week, day_number)
        except (ValueError, TypeError):
            # Out-of-range week/day_number inputs — caller treats None as "no date".
            return None

    def _get_total_price(self, invoice, delivery_note, order) -> str:
        """Get net document total, preferring invoice > delivery note > order."""
        if invoice:
            return str(invoice.sum_netto)
        if delivery_note:
            return str(delivery_note.sum_netto)
        return str(order.sum_netto)

    def _get_reseller_name(self, order: Order) -> str | None:
        """Get reseller contact name."""
        return order.reseller.contact.name

    def _format_document_number(self, document) -> str | None:
        """Format document number as 'PREFIX-NUMBER'."""
        if not document:
            return None
        return document.full_number
