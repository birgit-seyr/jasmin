from __future__ import annotations

import datetime
from collections.abc import Callable, Iterable
from typing import Any

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import QuerySet
from drf_spectacular.utils import (
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
from apps.shared.request_utils import auth_user, body
from core.errors import JasminError, NotFoundError
from core.serializers import ErrorResponseSerializer

from ..errors import (
    CommissioningError,
    DeliveryNoteFinalizeFailed,
    OfferGroupNotFound,
    OrderNotFound,
)
from ..models import (
    DeliveryNoteReseller,
    InvoiceReseller,
    OfferGroup,
    OfferSending,
    Order,
    OrderContent,
)
from ..schemas import (
    catalogue_param,
    get_delivery_week_parameter,
    get_offer_group_parameter,
    get_year_parameter,
)
from ..serializers.bulk_serializer import (
    BulkIdsRequestSerializer,
    BulkIdsWithDateRequestSerializer,
)
from ..serializers.resellers_serializer import (
    BackgroundJobEnqueueResponseSerializer,
    BulkCopyOffersResponseSerializer,
    BulkCopyOffersToOfferGroupRequestSerializer,
    BulkCreateSummaryInvoiceResponseSerializer,
    BulkDeleteResponseSerializer,
    BulkDocumentRequestSerializer,
    BulkDocumentWithDateRequestSerializer,
    BulkOperationResponseSerializer,
    BulkSendOffersRequestSerializer,
    BulkSetToPaidResponseSerializer,
    CreateOffersRequestSerializer,
    CreateOffersResponseSerializer,
    OfferSendingStatusSerializer,
    SetInvoiceNoteRequestSerializer,
    SetOrderNoteRequestSerializer,
)
from ..services import DeliveryNoteService, InvoiceService, OfferService
from ..services.bulk_operations import bulk_with_savepoints
from ..services.bulk_results import (
    format_order_error,
    get_delivery_note_or_error,
)
from ..services.delivery_note_invoices import current_invoices_by_delivery_note
from ..services.finalization_quota import (
    FinalizationReservation,
    reserve_finalizations,
)
from ..utils.lookup import get_or_404
from ..utils.query_params import validate_query_params
from ..utils.validation_utils import (
    parse_body_date,
    parse_body_int_fields,
    parse_bulk_ids,
    validate_bulk_document_request,
)


def _get_orders_with_related(order_ids: list[str]) -> QuerySet[Order]:
    """Fetch orders with delivery_note and reseller pre-loaded."""
    return Order.objects.filter(id__in=order_ids).select_related(
        "delivery_note", "reseller"
    )


def _unique_order_ids(order_ids: list[str]) -> list[str]:
    """The requested ids with repeats dropped, first occurrence winning.

    Results and errors are keyed by order, so one id can only ever yield one
    row. Counting a repeated id twice in ``total_processed`` would put it
    permanently out of step with ``successful + failed``.
    """
    return list(dict.fromkeys(order_ids))


def _append_missing_order_errors(
    order_ids: list[str],
    orders: Iterable[Order],
    errors: list[dict[str, Any]],
) -> None:
    """Record one error row per requested id that matches no order.

    An id nobody can resolve otherwise disappears from the batch: it yields
    neither a result nor an error, so ``successful + failed`` falls short of
    ``total_processed`` and the caller never learns which ids were unknown.
    """
    found_ids = {str(order.id) for order in orders}
    for order_id in order_ids:
        if str(order_id) in found_ids:
            continue
        errors.append(
            {
                "order_id": str(order_id),
                "order_number": None,
                "error": "Order not found",
                "success": False,
            }
        )


_get_invoice_for_delivery_note = InvoiceService.get_invoice_for_delivery_note


def _has_finalized_delivery_note(order: Order) -> bool:
    delivery_note = getattr(order, "delivery_note", None)
    return delivery_note is not None and delivery_note.is_finalized


def _release_unused(reservations: Iterable[FinalizationReservation]) -> None:
    for reservation in reservations:
        reservation.release_unused()


def _finalize_for_summary(delivery_note: DeliveryNoteReseller, user: Any) -> str:
    """Finalize ``delivery_note`` (quota reserved by the caller) in a
    savepoint; return why it couldn't be, or "" — one note that can't be
    finalized (an empty one) is left out of a summary invoice instead of
    aborting it."""
    try:
        with transaction.atomic():
            finalized = DeliveryNoteService.finalize_delivery_note(
                delivery_note=delivery_note, user=user, skip_quota=True
            )
    except (ValidationError, JasminError) as exc:
        return str(exc)
    return "" if finalized else "Failed to finalize delivery note"


def _run_per_order_bulk(
    orders: QuerySet[Order],
    handler: Callable[[Order, list[dict[str, Any]], list[dict[str, Any]]], None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run ``handler`` for each order under the shared per-order bulk except
    trailer, returning ``(results, errors)``.

    ``handler(order, results, errors)`` does one order's work: it appends a
    success row to ``results`` and may append business-rule rejections to
    ``errors`` directly (then ``return`` to skip the order). Any
    ``ValidationError``, domain error (``JasminError`` — an already-finalized
    conflict, an empty document), DB error or ``ValueError`` it raises is
    caught here and recorded as a per-order error, so a single bad order never
    aborts the whole batch.
    """
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def record_error(order: Order, exc: Exception) -> None:
        if isinstance(exc, (ValidationError, JasminError)):
            # Expected per-order outcomes in a bulk run — they belong in the
            # 207 errors list, not as a request-aborting 400 / 409.
            errors.append(format_order_error(order, str(exc)))
        else:
            # DatabaseError covers IntegrityError / DataError / etc.
            errors.append(format_order_error(order, f"Unexpected error: {exc}"))

    bulk_with_savepoints(
        orders,
        lambda order: handler(order, results, errors),
        catch=(
            ValidationError,
            JasminError,
            DatabaseError,
            ValueError,
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

        order_ids = _unique_order_ids(params["order_ids"])
        model = params["model"]
        date = params["date"]

        orders = _get_orders_with_related(order_ids)
        if not orders.exists():
            raise NotFoundError("No valid orders found")

        # The invoice branch finalizes each order's delivery note — creating it
        # first where there is none — before creating the (draft) invoice, so it
        # reserves those finalizations (see ``finalization_quota``). The
        # delivery_note branch only creates.
        reservation: FinalizationReservation | None = None
        if model == "invoice":
            from apps.shared.tenants.models import RateLimitedAction

            to_finalize = [
                order.id for order in orders if not _has_finalized_delivery_note(order)
            ]
            reservation = reserve_finalizations(
                RateLimitedAction.DELIVERY_NOTE_FINALIZATION,
                DeliveryNoteReseller.objects.filter(order_id__in=to_finalize),
                count=len(to_finalize),
                actor=request.user,
            )

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
        _append_missing_order_errors(order_ids, orders, errors)
        if reservation is not None:
            reservation.release_unused()

        return _build_bulk_response(
            model, order_ids, results, errors, success_status=status.HTTP_201_CREATED
        )

    def _create_delivery_note(
        self, order: Order, date: datetime.date | str | None, user: Any = None
    ) -> dict[str, Any]:
        """Create delivery note from order."""
        delivery_note = DeliveryNoteService.create_from_order(
            order=order, date=date, user=user
        )

        return _delivery_note_result(order, delivery_note)

    def _create_invoice(
        self, order: Order, date: datetime.date | str | None, user: Any
    ) -> dict[str, Any]:
        """Create invoice from order (via delivery note)."""
        # Get or create delivery note
        delivery_note = getattr(order, "delivery_note", None)
        if not delivery_note:
            delivery_note = DeliveryNoteService.create_from_order(
                order=order, date=date, user=user
            )

        # Finalize delivery note if needed (quota reserved for the batch in post()).
        if not delivery_note.is_finalized:
            finalize_success = DeliveryNoteService.finalize_delivery_note(
                delivery_note=delivery_note, user=user, skip_quota=True
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
        order_ids = _unique_order_ids(params["order_ids"])
        model = params["model"]  # "delivery_note" or "invoice"

        orders = _get_orders_with_related(order_ids)
        if not orders.exists():
            raise NotFoundError("No valid orders found")

        reservations = self._reserve(orders, model, request.user)

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
                    delivery_note=delivery_note, user=request.user, skip_quota=True
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
                    invoice=invoice, user=request.user, skip_quota=True
                )
                if success:
                    results.append(_invoice_result(order, delivery_note, invoice))
                else:
                    errors.append(
                        format_order_error(order, "Failed to finalize invoice")
                    )

        results, errors = _run_per_order_bulk(orders, handler)
        _append_missing_order_errors(order_ids, orders, errors)
        _release_unused(reservations)
        return _build_bulk_response(model, order_ids, results, errors)

    @staticmethod
    def _reserve(
        orders: QuerySet[Order], model: str, actor: Any
    ) -> list[FinalizationReservation]:
        """Reserve the finalizations this batch may perform, up front, so an
        over-cap batch is refused (429) before anything is finalized; the run
        then finalizes with ``skip_quota``. Only documents not yet final count,
        and finalizing an invoice also finalizes the delivery notes behind it."""
        from apps.shared.tenants.models import RateLimitedAction

        delivery_notes = [
            order.delivery_note
            for order in orders
            if getattr(order, "delivery_note", None) is not None
        ]
        if model == "delivery_note":
            return [
                reserve_finalizations(
                    RateLimitedAction.DELIVERY_NOTE_FINALIZATION,
                    DeliveryNoteReseller.objects.filter(
                        pk__in=[
                            note.pk for note in delivery_notes if not note.is_finalized
                        ]
                    ),
                    actor=actor,
                )
            ]
        invoice_ids = {
            invoice.pk
            for invoice in InvoiceService.get_invoices_for_delivery_notes(
                [note.pk for note in delivery_notes]
            ).values()
            if not invoice.is_finalized
        }
        return [
            reserve_finalizations(
                RateLimitedAction.INVOICE_FINALIZATION,
                InvoiceReseller.objects.filter(pk__in=invoice_ids),
                actor=actor,
            ),
            reserve_finalizations(
                RateLimitedAction.DELIVERY_NOTE_FINALIZATION,
                DeliveryNoteReseller.objects.filter(
                    pk__in=InvoiceService.unfinalized_upstream_delivery_note_ids(
                        invoice_ids
                    )
                ),
                actor=actor,
            ),
        ]


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
        order_ids = _unique_order_ids(params["order_ids"])
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
        _append_missing_order_errors(order_ids, orders, errors)
        return _build_bulk_response(model, order_ids, results, errors)


class BulkSetToPaidDocumentsView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Bulk Set Documents as Paid/Unpaid",
        description="Mark invoices as paid or unpaid for multiple orders. Use ?undo=true to mark as unpaid.",
        parameters=[
            catalogue_param(
                "undo",
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
        order_ids = _unique_order_ids(parse_bulk_ids(request))
        model = body(request).get("model")  # Should be "invoice"
        undo = validate_query_params(request, optional=["undo"])["undo"]

        if model != "invoice":
            raise CommissioningError(
                "model must be 'invoice'",
                field="model",
                code="bulk_set_paid.model_invalid",
            )

        orders = _get_orders_with_related(order_ids)
        if not orders.exists():
            raise NotFoundError("No valid orders found")

        # A summary invoice spans several orders, so many orders in one
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

            invoice_id = str(invoice.id)
            if invoice_id in processed_invoices:
                # Another order in this batch already acted on this same
                # (summary) invoice — report one outcome per invoice, not a
                # spurious already-paid / not-paid failure for the siblings.
                results.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "delivery_note_id": str(delivery_note.id),
                        "delivery_note_number": delivery_note.full_number,
                        "invoice_id": invoice_id,
                        "invoice_number": invoice.full_number,
                        "action": processed_invoices[invoice_id],
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
                processed_invoices[invoice_id] = "unpaid"
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
                processed_invoices[invoice_id] = "paid"
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
        _append_missing_order_errors(order_ids, orders, errors)

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
        offer_ids = parse_bulk_ids(request)

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


#: Message + stable code per field of the copy-to-group body. Running the
#: declared request serializer would otherwise replace the codes this endpoint
#: already emits with DRF's generic ``validation_error``.
_BULK_COPY_TO_GROUP_ERRORS = {
    "ids": (
        "A non-empty list of offer ids is required",
        "bulk_copy_offers.ids_required",
    ),
    "offer_group": (
        "offer_group is required",
        "bulk_copy_offers.offer_group_required",
    ),
    # ``year`` / ``delivery_week`` are load-bearing, not optional: they are
    # part of ``copy_offers_to_offer_group``'s ``exists_filter``, the query
    # that decides whether an offer is ALREADY in the target group. Passing
    # None turns those clauses into ``IS NULL``, which matches no row, so the
    # already-present check silently never fires and every repeat call copies
    # the same offers again — ``skipped_count`` stuck at 0 while duplicates
    # accumulate. Required rather than defaulted, because there is no sane
    # default week to invent.
    "year": ("year and delivery_week are required", "bulk_copy_offers.week_required"),
    "delivery_week": (
        "year and delivery_week are required",
        "bulk_copy_offers.week_required",
    ),
}


def _validated_copy_to_group_body(request: Request) -> dict:
    """Run the declared request serializer and return its validated data.

    These values go straight into ``OfferService``'s ORM lookups, so they are
    typed before the service sees them: read raw, ``{"year": "abc"}`` reached
    the query as a string and ``{"ids": 5}`` was iterated as one.
    """
    serializer = BulkCopyOffersToOfferGroupRequestSerializer(data=body(request))
    if serializer.is_valid():
        return dict(serializer.validated_data)

    field, details = next(iter(serializer.errors.items()))
    # ``ids`` and ``offer_group`` mean the same thing however they fail —
    # absent, empty, or the wrong JSON type. A year or week that is PRESENT
    # but unusable is a different failure from one that is missing, so only
    # the absent case keeps the "required" code.
    absent = any(
        getattr(detail, "code", "") in ("required", "null") for detail in details
    )
    if field in ("ids", "offer_group") or absent:
        message, code = _BULK_COPY_TO_GROUP_ERRORS[field]
        raise CommissioningError(message, field=field, code=code)
    raise CommissioningError(
        f"Invalid value for '{field}'",
        field=field,
        code="bulk_copy_offers.invalid",
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
        data = _validated_copy_to_group_body(request)
        offer_ids = data["ids"]

        result = OfferService.copy_offers_to_offer_group(
            offer_ids, data["year"], data["delivery_week"], data["offer_group"]
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
        order_ids = _unique_order_ids(parse_bulk_ids(request))
        # A malformed non-empty ``date`` must not reach the invoice service:
        # ``coerce_document_date`` falls back to the latest delivery-note date,
        # so a typo would silently issue a summary invoice carrying a date
        # nobody asked for — on a document that is legally immutable once
        # finalized. Absent / empty still means "derive it".
        date = parse_body_date(
            request, "date", required=False, code_prefix="summary_invoice"
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
        # Which of these delivery notes an invoice already holds, a cancelled
        # one included, in a constant number of queries for the whole batch.
        all_delivery_note_ids = [
            delivery_note.id
            for delivery_note in delivery_note_by_order.values()
            if delivery_note is not None
        ]
        already_invoiced_delivery_note_ids = set(
            current_invoices_by_delivery_note(all_delivery_note_ids)
        )

        # The view finalizes each usable delivery note that isn't final yet
        # before rolling them into one summary invoice, so it reserves those
        # finalizations (see ``finalization_quota``).
        from apps.shared.tenants.models import RateLimitedAction

        reservation = reserve_finalizations(
            RateLimitedAction.DELIVERY_NOTE_FINALIZATION,
            DeliveryNoteReseller.objects.filter(
                pk__in=[
                    delivery_note.pk
                    for delivery_note in delivery_note_by_order.values()
                    if delivery_note is not None
                    and not delivery_note.is_finalized
                    and delivery_note.id not in already_invoiced_delivery_note_ids
                ]
            ),
            actor=request.user,
        )

        delivery_notes = []
        errors: list[dict[str, Any]] = []
        _append_missing_order_errors(order_ids, orders, errors)

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

            # A note an invoice holds, even a cancelled one, can't be billed again.
            if delivery_note.id in already_invoiced_delivery_note_ids:
                errors.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "error": "Delivery note already has an invoice",
                    }
                )
                continue

            if not delivery_note.is_finalized and (
                finalize_error := _finalize_for_summary(delivery_note, request.user)
            ):
                errors.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.full_number,
                        "error": finalize_error,
                    }
                )
                continue

            delivery_notes.append(delivery_note)

        reservation.release_unused()

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
        year, delivery_week = parse_body_int_fields(
            request,
            ["year", "delivery_week"],
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
        request=SetInvoiceNoteRequestSerializer,
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
        order = get_or_404(
            Order,
            pk,
            "Order",
            error_cls=OrderNotFound,
            queryset=Order.objects.select_related("delivery_note"),
        )

        delivery_note = getattr(order, "delivery_note", None)
        invoice = _get_invoice_for_delivery_note(delivery_note)

        if not invoice:
            from ..errors import InvoiceNotFound

            raise InvoiceNotFound("No invoice found for this order")

        serializer = SetInvoiceNoteRequestSerializer(data=body(request))
        serializer.is_valid(raise_exception=True)
        invoice.note = serializer.validated_data.get("note", "")
        invoice.save(update_fields=["note"])
        return Response({"note": invoice.note})


class SetOrderNoteView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Set Order Note",
        description="Update the note on an order.",
        request=SetOrderNoteRequestSerializer,
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
        order = get_or_404(Order, pk, "Order", error_cls=OrderNotFound)

        serializer = SetOrderNoteRequestSerializer(data=body(request))
        serializer.is_valid(raise_exception=True)
        order.note = serializer.validated_data.get("note", "")
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

        order_ids = parse_bulk_ids(request)
        model = body(request).get("model")

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
            created_by=auth_user(request),
        )

        return Response(
            BackgroundJobEnqueueResponseSerializer(
                {"job_id": job.id, "kind": job.kind, "status": job.status}
            ).data,
            status=status.HTTP_202_ACCEPTED,
        )


class BulkSendDocumentsViaEmailView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsOffice
    write_permission = IsOffice
    # Step-up required: one email per selected document goes out from the
    # tenant's mail server, which a stolen session must not fan out unconfirmed.
    permission_classes = (RequiresStepUp,)

    @extend_schema(
        summary="Enqueue a bulk send of invoices or delivery notes",
        description=(
            "Enqueues a Huey background job that emails each selected order's "
            "finalized invoice or delivery note (``model``) as a PDF to the "
            "reseller's invoice address. A document already sent is skipped; "
            "one that can't be sent (not finalized, no PDF, no address, "
            "invoices on paper only) is reported in the job result. Returns "
            "202 with a ``job_id``; the frontend polls ``GET /api/"
            "notifications/jobs/{job_id}/`` until status is ``done`` or "
            "``failed``."
        ),
        request=BulkDocumentRequestSerializer,
        responses={
            202: BackgroundJobEnqueueResponseSerializer,
            400: ErrorResponseSerializer,
            # ``EmailSendingNotSetUp`` — the tenant has no SMTP host of its own.
            409: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        from apps.commissioning.tasks import run_bulk_document_send
        from apps.notifications.jobs import enqueue_job
        from apps.shared.tenants.email_service import assert_tenant_can_send_email

        params = validate_bulk_document_request(request)
        assert_tenant_can_send_email()
        job = enqueue_job(
            kind=f"{params['model']}.bulk_send",
            task=run_bulk_document_send,
            task_kwargs={
                "order_ids": [str(order_id) for order_id in params["order_ids"]],
                "model": params["model"],
            },
            created_by=auth_user(request),
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

    offer_group = get_or_404(
        OfferGroup, offer_group_id, "Offer group", error_cls=OfferGroupNotFound
    )

    resellers = offer_group.reseller_set.select_related("contact").all()

    # Direct composite-key lookup — no JOIN through Offer needed
    # since OfferSending stores the (offer_group, year,
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
                "name": contact.name,
                "address": contact.address,
                "zip_code": contact.zip_code,
                "city": contact.city,
                "country": contact.country,
                "uid": contact.uid,
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
            "holds ``total_processed``, ``successful``, ``failed`` and "
            "``results``: one entry per reseller with ``reseller_id``, "
            "``reseller_name``, ``success`` and, where it applies, ``error`` "
            "or ``already_sent``."
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

        offer_group = get_or_404(
            OfferGroup, data["offer_group"], "Offer group", error_cls=OfferGroupNotFound
        )

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
            created_by=auth_user(request),
        )

        return Response(
            BackgroundJobEnqueueResponseSerializer(
                {"job_id": job.id, "kind": job.kind, "status": job.status}
            ).data,
            status=status.HTTP_202_ACCEPTED,
        )
