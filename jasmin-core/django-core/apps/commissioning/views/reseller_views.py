from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import QuerySet
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import RequiresStepUp
from apps.authz.permissions import APIViewRolePermissionsMixin, IsOffice, IsStaff
from core.errors import ConflictError, NotFoundError
from core.serializers import ErrorResponseSerializer

from ..errors import (
    CommissioningError,
    DeliveryNoteFinalizeFailed,
    OfferGroupNotFound,
    OrderNotFound,
)
from ..models import (
    CrateContentInvoiceReseller,
    InvoiceResellerContent,
    OfferGroup,
    OfferSending,
    Order,
    OrderContent,
)
from ..schemas import (
    get_day_number_parameter,
    get_delivery_week_parameter,
    get_offer_group_parameter,
    get_reseller_parameter,
    get_year_parameter,
)
from ..serializers.resellers_serializer import (
    BackgroundJobEnqueueResponseSerializer,
    BulkCopyOffersResponseSerializer,
    BulkCopyOffersToOfferGroupRequestSerializer,
    BulkCreateSummaryInvoiceResponseSerializer,
    BulkDeleteResponseSerializer,
    BulkDocumentRequestSerializer,
    BulkDocumentWithDateRequestSerializer,
    BulkIdsRequestSerializer,
    BulkIdsWithDateRequestSerializer,
    BulkOperationResponseSerializer,
    BulkSendOffersRequestSerializer,
    BulkSetToPaidResponseSerializer,
    CombinedOrderOverviewSerializer,
    CreateOffersRequestSerializer,
    CreateOffersResponseSerializer,
    OfferSendingStatusSerializer,
)
from ..services import DeliveryNoteService, InvoiceService, OfferService
from ..services.bulk_operations import bulk_with_savepoints
from ..services.bulk_results import (
    format_order_error,
    get_delivery_note_or_error,
)
from ..utils.iso_week_utils import week_day_to_date
from ..utils.query_params import validate_query_params
from ..utils.validation_utils import (
    validate_and_parse_int_params,
    validate_bulk_document_request,
)


def _get_orders_with_related(order_ids: list[str]) -> QuerySet[Order]:
    """Fetch orders with delivery_note and reseller pre-loaded."""
    return Order.objects.filter(id__in=order_ids).select_related(
        "delivery_note", "reseller"
    )


_get_invoice_for_delivery_note = InvoiceService.get_invoice_for_delivery_note


def _run_per_order_bulk(
    orders: QuerySet[Order],
    handler: Callable[[Order, list[dict[str, Any]], list[dict[str, Any]]], None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run ``handler`` for each order under the shared per-order bulk except
    trailer, returning ``(results, errors)``.

    ``handler(order, results, errors)`` does one order's work: it appends a
    success row to ``results`` and may append business-rule rejections to
    ``errors`` directly (then ``return`` to skip the order). Any
    ``ValidationError`` / ``ConflictError`` / DB / type error it raises is
    caught here and recorded as a per-order error, so a single bad order never
    aborts the whole batch.
    """
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def record_error(order: Order, exc: Exception) -> None:
        if isinstance(exc, (ValidationError, ConflictError)):
            # Already-finalized / already-exists conflicts (and validation
            # failures) are expected per-order outcomes in a bulk run — they
            # belong in the 207 errors list, not as a request-aborting 409.
            errors.append(format_order_error(order, str(exc)))
        else:
            # DatabaseError covers IntegrityError / DataError / etc.
            errors.append(format_order_error(order, f"Unexpected error: {exc}"))

    bulk_with_savepoints(
        orders,
        lambda order: handler(order, results, errors),
        catch=(
            ValidationError,
            ConflictError,
            DatabaseError,
            ValueError,
            TypeError,
            AttributeError,
        ),
        on_error=record_error,
    )
    return results, errors


def _delivery_note_result(order: Order, delivery_note: Any) -> dict[str, Any]:
    """Standard success row for a delivery-note bulk operation."""
    return {
        "order_id": str(order.id),
        "order_number": order.full_number,
        "delivery_note_id": str(delivery_note.id),
        "delivery_note_number": delivery_note.full_number,
        "success": True,
    }


def _invoice_result(order: Order, delivery_note: Any, invoice: Any) -> dict[str, Any]:
    """Standard success row for an invoice bulk operation (delivery-note row
    plus the invoice id/number)."""
    return {
        "order_id": str(order.id),
        "order_number": order.full_number,
        "delivery_note_id": str(delivery_note.id),
        "delivery_note_number": delivery_note.full_number,
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.full_number,
        "success": True,
    }


def _build_bulk_response(
    model: str,
    order_ids: list[str],
    results: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    success_status: int = status.HTTP_200_OK,
) -> Response:
    """Build a standard bulk operation response."""
    response_data = {
        "model": model,
        "total_processed": len(order_ids),
        "successful": len(results),
        "failed": len(errors),
        "results": results,
    }
    if errors:
        response_data["errors"] = errors
    status_code = status.HTTP_207_MULTI_STATUS if errors else success_status
    return Response(response_data, status=status_code)


class DaysWithOrdersView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsStaff
    write_permission = IsStaff
    """Get distinct delivery days that have orders for a given year and week."""

    @extend_schema(
        summary="Get Days With Orders",
        description="Returns list of delivery days (day_numbers) (0-6) that have orders for the specified year and week.",
        parameters=[
            get_year_parameter(),
            get_delivery_week_parameter(),
        ],
        responses={
            200: inline_serializer(
                name="DaysWithOrdersResponse",
                fields={
                    "days": drf_serializers.ListField(
                        child=drf_serializers.IntegerField()
                    )
                },
            ),
            400: ErrorResponseSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        """Get days with orders for a given year and week."""
        # Validate parameters
        params = validate_query_params(request, required=["year", "delivery_week"])
        year = params["year"]
        delivery_week = params["delivery_week"]

        # Get distinct delivery_days that have orders
        days_with_orders = (
            OrderContent.objects.filter(
                order__year=year, order__delivery_week=delivery_week
            )
            .values_list("order__day_number", flat=True)
            .distinct()
        )

        return Response({"days": list(days_with_orders)})


class BulkCreateDocumentsFromOrdersView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Bulk Create Documents",
        description="""
        Create delivery notes or invoices from multiple orders.
        
        - For delivery_note: Creates delivery note from order
        - For invoice: Creates/finalizes delivery note, then creates invoice
        """,
        request=BulkDocumentWithDateRequestSerializer,
        responses={
            201: BulkOperationResponseSerializer,
            207: BulkOperationResponseSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        params = validate_bulk_document_request(request)

        order_ids = params["order_ids"]
        model = params["model"]
        date = params["date"]

        orders = _get_orders_with_related(order_ids)
        if not orders.exists():
            raise NotFoundError("No valid orders found")

        def handler(
            order: Order,
            results: list[dict[str, Any]],
            errors: list[dict[str, Any]],
        ) -> None:
            if model == "delivery_note":
                results.append(self._create_delivery_note(order, date, request.user))
            else:  # invoice
                results.append(self._create_invoice(order, date, request.user))

        results, errors = _run_per_order_bulk(orders, handler)

        response_data: dict[str, Any] = {
            "model": model,
            "total_processed": len(order_ids),
            "successful": len(results),
            "failed": len(errors),
            "results": results,
        }
        if errors:
            response_data["errors"] = errors
        status_code = (
            status.HTTP_207_MULTI_STATUS if errors else status.HTTP_201_CREATED
        )
        return Response(response_data, status=status_code)

    def _create_delivery_note(
        self, order: Order, date: str | None, user: Any = None
    ) -> dict[str, Any]:
        """Create delivery note from order."""
        delivery_note = DeliveryNoteService.create_from_order(
            order=order, date=date, user=user
        )

        return _delivery_note_result(order, delivery_note)

    def _create_invoice(
        self, order: Order, date: str | None, user: Any
    ) -> dict[str, Any]:
        """Create invoice from order (via delivery note)."""
        # Get or create delivery note
        delivery_note = getattr(order, "delivery_note", None)
        if not delivery_note:
            delivery_note = DeliveryNoteService.create_from_order(
                order=order, date=date, user=user
            )

        # Finalize delivery note if needed
        if not delivery_note.is_finalized:
            finalize_success = DeliveryNoteService.finalize_delivery_note(
                delivery_note=delivery_note, user=user
            )
            if not finalize_success:
                raise DeliveryNoteFinalizeFailed(
                    "Failed to finalize delivery note before creating invoice"
                )

        # Create invoice
        invoice = InvoiceService.create_from_delivery_note(
            delivery_note=delivery_note, date=date, user=user
        )

        return _invoice_result(order, delivery_note, invoice)


class BulkFinalizeDocumentsView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Bulk Finalize Documents",
        description="Finalize delivery notes or invoices for multiple orders.",
        request=BulkDocumentRequestSerializer,
        responses={
            200: BulkOperationResponseSerializer,
            207: BulkOperationResponseSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        params = validate_bulk_document_request(request)
        order_ids = params["order_ids"]
        model = params["model"]  # "delivery_note" or "invoice"

        orders = _get_orders_with_related(order_ids)
        if not orders.exists():
            raise NotFoundError("No valid orders found")

        def handler(
            order: Order,
            results: list[dict[str, Any]],
            errors: list[dict[str, Any]],
        ) -> None:
            if model == "delivery_note":
                delivery_note, error = get_delivery_note_or_error(order)
                if error:
                    errors.append(error)
                    return

                success = DeliveryNoteService.finalize_delivery_note(
                    delivery_note=delivery_note, user=request.user
                )
                if success:
                    results.append(_delivery_note_result(order, delivery_note))
                else:
                    errors.append(
                        format_order_error(order, "Failed to finalize delivery note")
                    )

            elif model == "invoice":
                delivery_note, error = get_delivery_note_or_error(order)
                if error:
                    errors.append(error)
                    return

                invoice = _get_invoice_for_delivery_note(delivery_note)
                if not invoice:
                    errors.append(
                        format_order_error(
                            order, "No invoice found for this delivery note"
                        )
                    )
                    return

                success = InvoiceService.finalize_invoice(
                    invoice=invoice, user=request.user
                )
                if success:
                    results.append(_invoice_result(order, delivery_note, invoice))
                else:
                    errors.append(
                        format_order_error(order, "Failed to finalize invoice")
                    )

        results, errors = _run_per_order_bulk(orders, handler)
        return _build_bulk_response(model, order_ids, results, errors)


class BulkDeleteDocumentsView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Bulk Delete Documents",
        description="Delete delivery notes or invoices for multiple orders. Cannot delete finalized documents.",
        request=BulkDocumentRequestSerializer,
        responses={
            200: BulkDeleteResponseSerializer,
            207: BulkDeleteResponseSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        params = validate_bulk_document_request(request)
        order_ids = params["order_ids"]
        model = params["model"]  # "delivery_note" or "invoice"

        orders = _get_orders_with_related(order_ids)
        if not orders.exists():
            raise NotFoundError("No valid orders found")

        def handler(
            order: Order,
            results: list[dict[str, Any]],
            errors: list[dict[str, Any]],
        ) -> None:
            if model == "delivery_note":
                delivery_note, error = get_delivery_note_or_error(order)
                if error:
                    errors.append(error)
                    return

                if delivery_note.is_finalized:
                    errors.append(
                        format_order_error(
                            order, "Cannot delete finalized delivery note"
                        )
                    )
                    return

                invoice = _get_invoice_for_delivery_note(delivery_note)
                if invoice:
                    errors.append(
                        format_order_error(
                            order,
                            "Cannot delete delivery note that has an invoice",
                        )
                    )
                    return

                # Capture the number before delete() voids the row.
                delivery_note_number = delivery_note.full_number
                delivery_note.delete()
                results.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "delivery_note_number": delivery_note_number,
                        "success": True,
                    }
                )

            elif model == "invoice":
                delivery_note, error = get_delivery_note_or_error(order)
                if error:
                    errors.append(error)
                    return

                invoice = _get_invoice_for_delivery_note(delivery_note)
                if not invoice:
                    errors.append(
                        format_order_error(
                            order, "No invoice found for this delivery note"
                        )
                    )
                    return

                if invoice.is_finalized:
                    errors.append(
                        format_order_error(order, "Cannot delete finalized invoice")
                    )
                    return

                invoice_number = invoice.full_number
                invoice.delete()
                results.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "delivery_note_id": str(delivery_note.id),
                        "delivery_note_number": delivery_note.full_number,
                        "invoice_number": invoice_number,
                        "success": True,
                    }
                )

        results, errors = _run_per_order_bulk(orders, handler)
        return _build_bulk_response(model, order_ids, results, errors)


class BulkSetToPaidDocumentsView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Bulk Set Documents as Paid/Unpaid",
        description="Mark invoices as paid or unpaid for multiple orders. Use ?undo=true to mark as unpaid.",
        parameters=[
            OpenApiParameter(
                name="undo",
                type=OpenApiTypes.STR,
                required=False,
                description="Set to 'true' to undo payment (mark as unpaid)",
            ),
        ],
        request=BulkDocumentRequestSerializer,
        responses={
            200: BulkSetToPaidResponseSerializer,
            207: BulkSetToPaidResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        order_ids = request.data.get("ids", [])
        model = request.data.get("model")  # Should be "invoice"
        undo = validate_query_params(request, optional=["undo"])["undo"]

        if not order_ids or not isinstance(order_ids, list):
            raise CommissioningError(
                "order_ids must be a non-empty list",
                field="ids",
                code="bulk_set_paid.ids_required",
            )

        if model != "invoice":
            raise CommissioningError(
                "model must be 'invoice'",
                field="model",
                code="bulk_set_paid.model_invalid",
            )

        orders = _get_orders_with_related(order_ids)
        if not orders.exists():
            raise NotFoundError("No valid orders found")

        # DOC-9: a summary invoice spans several orders, so many orders in one
        # batch resolve to the SAME invoice. Track invoices already acted on so
        # the 2nd..Nth order reports one success no-op instead of a spurious
        # "already paid" / "not paid, cannot undo" failure.
        processed_invoices: dict[str, str] = {}

        def handler(
            order: Order,
            results: list[dict[str, Any]],
            errors: list[dict[str, Any]],
        ) -> None:
            delivery_note, error = get_delivery_note_or_error(order)
            if error:
                errors.append(error)
                return

            invoice = _get_invoice_for_delivery_note(delivery_note)
            if not invoice:
                errors.append(
                    format_order_error(order, "No invoice found for this delivery note")
                )
                return

            inv_id = str(invoice.id)
            if inv_id in processed_invoices:
                # Another order in this batch already acted on this same
                # (summary) invoice — report one outcome per invoice, not a
                # spurious already-paid / not-paid failure for the siblings.
                results.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "delivery_note_id": str(delivery_note.id),
                        "delivery_note_number": delivery_note.full_number,
                        "invoice_id": inv_id,
                        "invoice_number": invoice.full_number,
                        "action": processed_invoices[inv_id],
                        "success": True,
                    }
                )
                return

            # A cancelled (storno'd) invoice is no longer a live payable —
            # refuse to mark it paid. (Undoing an earlier payment is still
            # allowed so a mistaken paid-flag can be cleared.)
            if not undo and invoice.cancelled_by_invoice_id:
                errors.append(
                    format_order_error(
                        order,
                        "Invoice has been cancelled by a storno and cannot be"
                        " marked as paid",
                    )
                )
                return

            if undo:
                if not invoice.has_been_paid:
                    errors.append(
                        {
                            "order_id": str(order.id),
                            "order_number": order.full_number,
                            "invoice_number": invoice.full_number,
                            "error": "Invoice is not paid, cannot undo",
                            "success": False,
                        }
                    )
                    return

                invoice.mark_as_unpaid()
                processed_invoices[inv_id] = "unpaid"
                results.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "delivery_note_id": str(delivery_note.id),
                        "delivery_note_number": delivery_note.full_number,
                        "invoice_id": str(invoice.id),
                        "invoice_number": invoice.full_number,
                        "action": "unpaid",
                        "success": True,
                    }
                )
            else:
                if invoice.has_been_paid:
                    errors.append(
                        {
                            "order_id": str(order.id),
                            "order_number": order.full_number,
                            "invoice_number": invoice.full_number,
                            "error": "Invoice has already been paid",
                            "success": False,
                        }
                    )
                    return

                invoice.mark_as_paid(user=request.user)
                processed_invoices[inv_id] = "paid"
                results.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "delivery_note_id": str(delivery_note.id),
                        "delivery_note_number": delivery_note.full_number,
                        "invoice_id": str(invoice.id),
                        "invoice_number": invoice.full_number,
                        "paid_at": (
                            invoice.paid_at.isoformat() if invoice.paid_at else None
                        ),
                        "action": "paid",
                        "success": True,
                    }
                )

        results, errors = _run_per_order_bulk(orders, handler)

        response_data = {
            "model": model,
            "action": "unpaid" if undo else "paid",
            "total_processed": len(order_ids),
            "successful": len(results),
            "failed": len(errors),
            "results": results,
        }
        if errors:
            response_data["errors"] = errors

        status_code = status.HTTP_207_MULTI_STATUS if errors else status.HTTP_200_OK
        return Response(response_data, status=status_code)


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
            get_year_parameter(required=False),
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
        # year is required at runtime: without it this office endpoint would
        # materialize every order across all years with no pagination. All real
        # callers (DeliveryNotes / Invoices / PaymentsResellers) always send it.
        # (The @extend_schema marks year optional only for doc back-compat, the
        # same split ShareView uses — runtime validation is the real gate.)
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
        orders = Order.objects.select_related(
            "reseller__contact", "delivery_note"
        ).prefetch_related(
            "delivery_note__items__share_article",
            "delivery_note__crate_items",
            "ordercontent_set",
            "crateordercontent_set",
            # Offer-bound deposits hang off OrderContent (order=NULL); Order's
            # money totals now include them, so prefetch this edge too to keep
            # the order list query-free per order (DOC-4).
            "ordercontent_set__crateordercontent_set",
        )

        # Apply filters if provided
        filters: dict[str, Any] = {}
        if year:
            filters["year"] = year
        if delivery_week:
            filters["delivery_week"] = delivery_week
        if day_number is not None:
            filters["day_number"] = day_number
        if reseller_id:
            filters["reseller__id"] = reseller_id

        if filters:
            orders = orders.filter(**filters)

        # Order by most recent first
        orders = list(orders.order_by("-year", "-delivery_week", "-day_number"))

        # ``delivery_note`` is a REVERSE OneToOne (the FK lives on
        # DeliveryNoteReseller), so Order has no ``delivery_note_id`` — read the
        # related object (cached by ``select_related`` above) and take its id.
        delivery_notes = {
            order.pk: getattr(order, "delivery_note", None) for order in orders
        }

        # Batch the per-order invoice lookup — previously each order ran its
        # own ``get_invoice_for_delivery_note`` query (plus a
        # ``cancelled_by_invoice`` fetch). Resolve them all in one query.
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
    def _invoices_by_delivery_note(delivery_note_ids: list[Any]) -> dict[Any, Any]:
        """Map ``delivery_note_id -> InvoiceReseller`` for the whole page in a
        single query (batched form of
        ``InvoiceService.get_invoice_for_delivery_note``).
        ``delivery_note_contents`` is prefetched so the inner mapping stays
        query-free; the invoice's line items + cancelled-by invoice ride along
        for ``sum_netto`` and the storno fields."""
        if not delivery_note_ids:
            return {}
        id_set = set(delivery_note_ids)
        out: dict[Any, Any] = {}
        contents = (
            InvoiceResellerContent.objects.filter(
                delivery_note_contents__delivery_note_id__in=delivery_note_ids
            )
            .select_related("invoice", "invoice__cancelled_by_invoice")
            .prefetch_related(
                "delivery_note_contents",
                "invoice__items",
                "invoice__crate_items",
            )
            .distinct()
        )
        for content in contents:
            for delivery_note_content in content.delivery_note_contents.all():
                delivery_note_id = delivery_note_content.delivery_note_id
                if delivery_note_id in id_set and delivery_note_id not in out:
                    out[delivery_note_id] = content.invoice
        # Crate-only delivery notes have no article lines, so they link to their
        # invoice only via the crate provenance M2M — query that too.
        crate_contents = (
            CrateContentInvoiceReseller.objects.filter(
                crate_delivery_note_contents__delivery_note_id__in=delivery_note_ids
            )
            .select_related("invoice", "invoice__cancelled_by_invoice")
            .prefetch_related(
                "crate_delivery_note_contents",
                "invoice__items",
                "invoice__crate_items",
            )
            .distinct()
        )
        for crate_content in crate_contents:
            for crate_dn_content in crate_content.crate_delivery_note_contents.all():
                delivery_note_id = crate_dn_content.delivery_note_id
                if delivery_note_id in id_set and delivery_note_id not in out:
                    out[delivery_note_id] = crate_content.invoice
        return out

    def _build_order_overview(self, order: Order, invoice: Any) -> dict[str, Any]:
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
            "reseller_id": str(order.reseller.id) if order.reseller else None,
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
                if invoice and invoice.cancelled_by_invoice_id
                else None
            ),
        }

    def _calculate_order_date(
        self,
        year: int | None,
        delivery_week: int | None,
        day_number: int | None,
    ) -> Any:
        """Calculate order date from year, week, and day_number."""
        if year is None or delivery_week is None or day_number is None:
            return None

        try:
            return week_day_to_date(year, delivery_week, day_number)
        except (ValueError, TypeError):
            # Out-of-range week/day_number inputs — caller treats None as "no date".
            return None

    def _get_total_price(self, invoice, delivery_note, order) -> str | None:
        """Get net document total, preferring invoice > delivery note > order."""
        if invoice:
            return str(invoice.sum_netto)
        if delivery_note:
            return str(delivery_note.sum_netto)
        if order:
            return str(order.sum_netto)
        return None

    def _get_reseller_name(self, order: Order) -> str | None:
        """Get reseller contact name."""
        if not order.reseller:
            return None
        if not order.reseller.contact:
            return None
        return order.reseller.contact.name

    def _format_document_number(self, document) -> str | None:
        """Format document number as 'PREFIX-NUMBER'."""
        if not document:
            return None
        return document.full_number


class BulkCopyOffersToNextWeekView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Bulk Copy Offers to Next Week",
        description="Copy selected offers to the next delivery week.",
        request=BulkIdsRequestSerializer,
        responses={
            201: BulkCopyOffersResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        offer_ids = request.data.get("ids", [])

        if not offer_ids or not isinstance(offer_ids, list):
            raise CommissioningError(
                "offer_ids must be a non-empty list",
                field="ids",
                code="bulk_copy_offers.ids_required",
            )

        result = OfferService.copy_offers_to_next_week(offer_ids)

        return Response(
            {
                "total_requested": len(offer_ids),
                "total_copied": result["created_count"],
                "skipped_count": result["skipped_count"],
                "copied_offers": result["created_ids"],
            },
            status=status.HTTP_201_CREATED,
        )


class BulkCopyOffersToOfferGroupView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Bulk Copy Offers to Offer Group",
        description="Copy selected offers to a different offer group for a specific year and week.",
        request=BulkCopyOffersToOfferGroupRequestSerializer,
        responses={
            201: BulkCopyOffersResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        year, delivery_week = request.data.get("year"), request.data.get(
            "delivery_week"
        )
        offer_ids = request.data.get("ids", [])
        offer_group = request.data.get("offer_group", None)

        if not offer_group:
            raise CommissioningError(
                "offer_group is required",
                field="offer_group",
                code="bulk_copy_offers.offer_group_required",
            )

        result = OfferService.copy_offers_to_offer_group(
            offer_ids, year, delivery_week, offer_group
        )

        return Response(
            {
                "total_requested": len(offer_ids),
                "total_copied": result["created_count"],
                "skipped_count": result["skipped_count"],
                "copied_offers": result["created_ids"],
            },
            status=status.HTTP_201_CREATED,
        )


class BulkCreateSummaryInvoiceFromOrdersView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice
    """
    Create a single summary invoice from multiple orders.
    Groups items by (share_article, unit, size, price_per_unit)
    and sums the amounts.
    """

    @extend_schema(
        summary="Bulk Create Summary Invoice from Orders",
        description="Create a single summary invoice from multiple orders. Groups items and sums amounts.",
        request=BulkIdsWithDateRequestSerializer,
        responses={
            201: BulkCreateSummaryInvoiceResponseSerializer,
            207: BulkCreateSummaryInvoiceResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        order_ids = request.data.get("ids", [])
        date = request.data.get("date", None)

        if not order_ids or not isinstance(order_ids, list):
            raise CommissioningError(
                "order_ids must be a non-empty list",
                field="ids",
                code="summary_invoice.ids_required",
            )

        # Fetch all orders at once
        orders = list(
            Order.objects.filter(id__in=order_ids)
            .select_related("delivery_note", "reseller")
            .prefetch_related(
                "delivery_note__items",
                "delivery_note__items__share_article",
                "delivery_note__crate_items",
                "delivery_note__crate_items__crate_type",
            )
        )

        if not orders:
            raise NotFoundError("No valid orders found")

        # ``delivery_note`` is a reverse OneToOne (FK on DeliveryNoteReseller),
        # so Order has no ``_id`` for it — read via getattr; select_related
        # above keeps the access query-free.
        delivery_note_by_order = {
            order.id: getattr(order, "delivery_note", None) for order in orders
        }
        # One query for the whole batch: which of these delivery notes already
        # have content on an invoice (was an ``.exists()`` per order).
        all_delivery_note_ids = [
            delivery_note.id
            for delivery_note in delivery_note_by_order.values()
            if delivery_note is not None
        ]
        already_invoiced_delivery_note_ids = set(
            InvoiceResellerContent.objects.filter(
                delivery_note_contents__delivery_note_id__in=all_delivery_note_ids
            ).values_list("delivery_note_contents__delivery_note_id", flat=True)
        )
        # Crate-only delivery notes are already-invoiced via the crate link only.
        already_invoiced_delivery_note_ids.update(
            CrateContentInvoiceReseller.objects.filter(
                crate_delivery_note_contents__delivery_note_id__in=all_delivery_note_ids
            ).values_list("crate_delivery_note_contents__delivery_note_id", flat=True)
        )

        delivery_notes = []
        errors = []

        for order in orders:
            delivery_note = delivery_note_by_order[order.id]
            if not delivery_note:
                errors.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "error": "No delivery note found for this order",
                    }
                )
                continue

            # M2M: any delivery-note content already on an invoice blocks reuse.
            if delivery_note.id in already_invoiced_delivery_note_ids:
                errors.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "error": "Delivery note already has an invoice",
                    }
                )
                continue

            if not delivery_note.is_finalized:
                finalize_success = DeliveryNoteService.finalize_delivery_note(
                    delivery_note=delivery_note, user=request.user
                )
                if not finalize_success:
                    errors.append(
                        {
                            "order_id": str(order.id),
                            "order_number": order.full_number,
                            "error": "Failed to finalize delivery note",
                        }
                    )
                    continue

            delivery_notes.append(delivery_note)

        if not delivery_notes:
            raise CommissioningError(
                "No valid delivery notes found to create summary invoice",
                code="summary_invoice.no_valid_dns",
                details={"errors": errors},
            )

        summary_invoice = InvoiceService.create_summary_invoice_from_delivery_notes(
            delivery_notes=delivery_notes, date=date, user=request.user
        )

        included_orders = []
        for order in orders:
            delivery_note = getattr(order, "delivery_note", None)
            if delivery_note and delivery_note in delivery_notes:
                included_orders.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "delivery_note_id": str(delivery_note.id),
                        "delivery_note_number": delivery_note.full_number,
                    }
                )

        response_data: dict[str, Any] = {
            "invoice_id": str(summary_invoice.id),
            "invoice_number": summary_invoice.full_number,
            "sum_netto": str(summary_invoice.sum_netto),
            "sum_brutto": str(summary_invoice.sum_brutto),
            "total_orders_included": len(included_orders),
            "total_line_items": summary_invoice.items.count(),
            "included_orders": included_orders,
            "success": True,
        }
        if errors:
            response_data["errors"] = errors
            response_data["partial_success"] = True

        status_code = (
            status.HTTP_207_MULTI_STATUS if errors else status.HTTP_201_CREATED
        )
        return Response(response_data, status=status_code)


class CreateOffersView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice
    """Create offers based on forecasts, share contents, and current stock."""

    @extend_schema(
        summary="Create Offers for Week",
        description="""
        Create offers for a specific year and delivery week based on:
        - Forecasts (what we expect to harvest)
        - ShareContents (what's needed for shares)
        - CurrentStock (what's available in storage)
        """,
        request=CreateOffersRequestSerializer,
        responses={
            200: CreateOffersResponseSerializer,
            201: CreateOffersResponseSerializer,
            400: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        """Create offers for a week."""
        year, delivery_week = validate_and_parse_int_params(
            request,
            ["year", "delivery_week"],
            source="data",
        )

        result = OfferService.create_offers(year=year, delivery_week=delivery_week)

        if result["created_count"] == 0 and result["skipped_count"] == 0:
            return Response(
                {
                    "success": False,
                    "message": result.get("message", "No offers created"),
                    **result,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "success": True,
                "message": f"Created {result['created_count']} offers, skipped {result['skipped_count']}",
                **result,
            },
            status=status.HTTP_201_CREATED,
        )


class SetInvoiceNoteView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Set Invoice Note",
        description="Update the note on an invoice by order ID.",
        request=inline_serializer(
            name="SetInvoiceNoteRequest",
            fields={
                "note": drf_serializers.CharField(
                    allow_blank=True, required=False, allow_null=True
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="SetInvoiceNoteResponse",
                fields={
                    "note": drf_serializers.CharField(allow_null=True),
                },
            ),
            # patch() raises OrderNotFound / InvoiceNotFound (both 404).
            404: ErrorResponseSerializer,
        },
    )
    def patch(self, request: Request, pk: str) -> Response:
        try:
            order = Order.objects.select_related("delivery_note").get(id=pk)
        except Order.DoesNotExist as exc:
            raise OrderNotFound("Order not found") from exc

        delivery_note = getattr(order, "delivery_note", None)
        invoice = _get_invoice_for_delivery_note(delivery_note)

        if not invoice:
            from ..errors import InvoiceNotFound

            raise InvoiceNotFound("No invoice found for this order")

        invoice.note = request.data.get("note", "")
        invoice.save(update_fields=["note"])
        return Response({"note": invoice.note})


class SetOrderNoteView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Set Order Note",
        description="Update the note on an order.",
        request=inline_serializer(
            name="SetOrderNoteRequest",
            fields={
                "note": drf_serializers.CharField(
                    allow_blank=True, required=False, allow_null=True
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="SetOrderNoteResponse",
                fields={
                    "note": drf_serializers.CharField(allow_null=True),
                },
            ),
            # patch() raises OrderNotFound (404).
            404: ErrorResponseSerializer,
        },
    )
    def patch(self, request: Request, pk: str) -> Response:
        try:
            order = Order.objects.get(id=pk)
        except Order.DoesNotExist as exc:
            raise OrderNotFound("Order not found") from exc

        order.note = request.data.get("note", "")
        order.save(update_fields=["note"])
        return Response({"note": order.note})


class BulkSendInvoiceRemindersViaEmailView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice
    # Step-up required: enqueues mass outbound email (one per reseller
    # across every overdue invoice). A stolen session shouldn't be able
    # to fan out hundreds of emails on the tenant's SMTP without a
    # fresh password re-confirmation.
    permission_classes = (RequiresStepUp,)

    @extend_schema(
        summary="Enqueue bulk invoice-reminder job",
        description=(
            "Enqueues a Huey background job that sends consolidated "
            "payment-reminder emails (one per reseller, covering all "
            "of their ticked overdue invoices). Returns 202 with a "
            "``job_id``; the frontend polls ``GET /api/notifications/"
            "jobs/{job_id}/`` until status is ``done`` or ``failed``."
        ),
        request=BulkDocumentRequestSerializer,
        responses={
            202: BackgroundJobEnqueueResponseSerializer,
            400: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        from apps.commissioning.tasks import run_bulk_invoice_reminder_send
        from apps.notifications.jobs import enqueue_job
        from apps.shared.tenants.email_service import capture_tenant_email_context

        order_ids = request.data.get("ids", [])
        model = request.data.get("model")

        if not order_ids or not isinstance(order_ids, list):
            raise CommissioningError(
                "ids must be a non-empty list",
                field="ids",
                code="bulk_invoice_reminder.ids_required",
            )

        if model != "invoice":
            raise CommissioningError(
                "model must be 'invoice'",
                field="model",
                code="bulk_invoice_reminder.model_invalid",
            )

        # Capture tenant name / language / bank details HERE, where
        # connection.tenant is the real Tenant — the Huey worker runs under
        # a FakeTenant that exposes only schema_name.
        job = enqueue_job(
            kind="invoice_reminder.bulk_send",
            task=run_bulk_invoice_reminder_send,
            task_kwargs={
                "order_ids": [str(order_id) for order_id in order_ids],
                "email_ctx": capture_tenant_email_context(),
            },
            created_by=request.user if request.user.is_authenticated else None,
        )

        return Response(
            BackgroundJobEnqueueResponseSerializer(
                {"job_id": job.id, "kind": job.kind, "status": job.status}
            ).data,
            status=status.HTTP_202_ACCEPTED,
        )


@extend_schema(
    summary="Get Offer Sending Status",
    description="Get the sending status of offers for a specific year, week, and offer group.",
    parameters=[
        get_year_parameter(required=True),
        get_delivery_week_parameter(required=True),
        get_offer_group_parameter(required=True),
    ],
    responses={
        200: OfferSendingStatusSerializer(many=True),
        400: ErrorResponseSerializer,
        404: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsOffice])
def offer_sending_status(request: Request) -> Response:
    params = validate_query_params(
        request, required=["year", "delivery_week", "offer_group"]
    )
    year = params["year"]
    delivery_week = params["delivery_week"]
    offer_group_id = params["offer_group"]

    try:
        offer_group = OfferGroup.objects.get(id=offer_group_id)
    except OfferGroup.DoesNotExist as exc:
        raise OfferGroupNotFound("Offer group not found") from exc

    resellers = offer_group.reseller_set.select_related("contact").all()

    # Direct composite-key lookup — no JOIN through Offer needed
    # since OfferSending now stores the (offer_group, year,
    # delivery_week) tuple explicitly.
    sendings = OfferSending.objects.filter(
        offer_group=offer_group,
        year=year,
        delivery_week=delivery_week,
        reseller__in=resellers,
    ).select_related("reseller")

    sending_by_reseller = {s.reseller_id: s for s in sendings}

    result = []
    for reseller in resellers:
        offer_sending = sending_by_reseller.get(reseller.id)
        contact = reseller.contact
        result.append(
            {
                "id": reseller.id,
                "name": contact.name if contact else None,
                "address": contact.address if contact else None,
                "zip_code": contact.zip_code if contact else None,
                "city": contact.city if contact else None,
                "country": contact.country if contact else None,
                "uid": contact.uid if contact else None,
                "sent": offer_sending is not None,
                "sent_at": offer_sending.created_at if offer_sending else None,
            }
        )

    return Response(result)


class BulkSendOffersViaEmailView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice
    # Step-up required: fans out offer emails to every selected
    # reseller. Same blast-radius reasoning as the invoice-reminder
    # variant above.
    permission_classes = (RequiresStepUp,)

    @extend_schema(
        summary="Enqueue bulk offer-send job",
        description=(
            "Enqueues a Huey background job that sends offer emails to "
            "the selected resellers. Returns 202 with a ``job_id``; the "
            "frontend polls ``GET /api/notifications/jobs/{job_id}/`` "
            "until status is ``done`` or ``failed``. The job's ``result`` "
            "field holds the per-reseller results in the same shape this "
            "endpoint used to return synchronously."
        ),
        request=BulkSendOffersRequestSerializer,
        responses={202: BackgroundJobEnqueueResponseSerializer},
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        from apps.commissioning.tasks import run_bulk_offer_send
        from apps.notifications.jobs import enqueue_job
        from apps.shared.tenants.email_service import capture_tenant_email_context

        serializer = BulkSendOffersRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            offer_group = OfferGroup.objects.get(id=data["offer_group"])
        except OfferGroup.DoesNotExist as exc:
            raise OfferGroupNotFound("Offer group not found") from exc

        # Capture tenant name / language / frontend URL HERE, where
        # connection.tenant is the real Tenant — the Huey worker runs under
        # a FakeTenant that exposes only schema_name.
        job = enqueue_job(
            kind="offer.bulk_send",
            task=run_bulk_offer_send,
            task_kwargs={
                "reseller_ids": data["reseller_ids"],
                "year": data["year"],
                "delivery_week": data["delivery_week"],
                "offer_group_id": str(offer_group.id),
                "email_ctx": capture_tenant_email_context(),
            },
            created_by=request.user if request.user.is_authenticated else None,
        )

        return Response(
            BackgroundJobEnqueueResponseSerializer(
                {"job_id": job.id, "kind": job.kind, "status": job.status}
            ).data,
            status=status.HTTP_202_ACCEPTED,
        )
