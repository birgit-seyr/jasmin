from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, IsStaff, RolePermissionsMixin
from core.serializers import ErrorResponseSerializer

from ..constants import get_default_tax_rate_crates
from ..errors import (
    CrateContentInvoiceMissingRequired,
    CrateDeliveryNoteContentMissingRequired,
    FinalizedError,
)
from ..models import (
    Crate,
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateNetPrice,
    DeliveryNoteReseller,
    InvoiceReseller,
)
from ..schemas import (
    get_crate_parameter,
    get_crate_type_parameter,
    get_current_parameter,
    get_delivery_note_id_parameter,
    get_invoice_id_parameter,
)
from ..serializers import (
    CrateContentInvoiceResellerSerializer,
    CrateDeliveryNoteContentSerializer,
    CrateItemSummarySerializer,
    CrateNetPriceSerializer,
)
from ..services import CrateContentService
from ..services.crate_summary import build_crate_summary_row, summarize_crate_items
from ..utils.iso_week_utils import date_from_order
from ..utils.lookup import get_or_404
from ..utils.query_params import validate_query_params
from ..utils.tax_rate_utils import resolve_crate_tax_rate


def _get_tax_rate(crate: Crate | None, date: datetime.date) -> float:
    """Resolve a crate tax rate, falling back to the configured default."""
    return float(
        resolve_crate_tax_rate(crate, date, default=get_default_tax_rate_crates())
        if crate is not None
        else get_default_tax_rate_crates()
    )


def _reject_finalized(obj: Any, kind: str, action: str) -> None:
    """Raise ``FinalizedError`` if ``obj`` is finalized; otherwise do nothing."""
    if getattr(obj, "is_finalized", False):
        raise FinalizedError(
            f"Cannot {action} {kind}",
            code=f"{kind.replace(' ', '_')}.finalized",
        )


# Explicit request bodies: create/update read raw ``request.data`` keys, so
# the model serializers declared on the viewsets do NOT describe the actual
# request payloads. Shared by create and update per viewset.
_CRATE_DELIVERY_NOTE_CONTENT_WRITE_REQUEST = inline_serializer(
    name="CrateDeliveryNoteContentWriteRequest",
    fields={
        "delivery_note_id": drf_serializers.CharField(),
        "crate_type": drf_serializers.CharField(),
        "amount": drf_serializers.IntegerField(),
        "price_per_unit": drf_serializers.DecimalField(
            max_digits=5, decimal_places=2, required=False, allow_null=True
        ),
        "rabatt": drf_serializers.IntegerField(required=False, allow_null=True),
        "note": drf_serializers.CharField(required=False, allow_blank=True),
    },
)

_CRATE_INVOICE_CONTENT_WRITE_REQUEST = inline_serializer(
    name="CrateInvoiceContentWriteRequest",
    fields={
        "invoice_id": drf_serializers.CharField(),
        "crate_type": drf_serializers.CharField(),
        "amount": drf_serializers.IntegerField(),
        "price_per_unit": drf_serializers.DecimalField(
            max_digits=5, decimal_places=2, required=False, allow_null=True
        ),
        "rabatt": drf_serializers.IntegerField(required=False, allow_null=True),
        "tax_rate": drf_serializers.DecimalField(
            max_digits=5, decimal_places=2, required=False, allow_null=True
        ),
        "note": drf_serializers.CharField(required=False, allow_blank=True),
    },
)


class CrateDeliveryNoteContentViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = CrateDeliveryNoteContentSerializer

    def get_queryset(self) -> QuerySet[CrateDeliveryNoteContent]:
        return CrateDeliveryNoteContent.objects.select_related(
            "crate_type", "delivery_note"
        )

    def _get_crate_summary(
        self,
        delivery_note: DeliveryNoteReseller,
        crate_type: Crate,
    ) -> dict[str, Any]:
        date = date_from_order(delivery_note.order)
        extras = {
            "delivery_note_id": str(delivery_note.id),
            "delivery_note_number": delivery_note.display_number,
            "delivery_note_prefix": delivery_note.prefix,
            "delivery_note_is_finalized": delivery_note.is_finalized,
        }
        rows = CrateDeliveryNoteContent.objects.filter(
            delivery_note=delivery_note, crate_type=crate_type
        ).select_related("crate_type")
        # Group by (crate_type, price, rabatt, tax) and sum per-row line_netto so
        # the per-line figure matches the document footer — not a lossy max().
        summary = summarize_crate_items(
            rows,
            resolve_tax_rate=lambda ct: _get_tax_rate(ct, date),
            extras=extras,
        )
        return (
            summary[0]
            if summary
            else build_crate_summary_row(
                crate_type_id=str(crate_type.id),
                crate_type_name=crate_type.name,
                amount=0,
                price=0,
                rabatt=0,
                tax_rate=_get_tax_rate(crate_type, date),
                extras=extras,
            )
        )

    @extend_schema(
        parameters=[get_delivery_note_id_parameter()],
        description="Get aggregated summary of crates by type for a delivery note.",
        responses={
            200: CrateItemSummarySerializer(many=True),
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        params = validate_query_params(request, required=["delivery_note_id"])
        delivery_note = get_or_404(
            DeliveryNoteReseller,
            params["delivery_note_id"],
            "Delivery note",
        )

        date = date_from_order(delivery_note.order)
        rows = CrateDeliveryNoteContent.objects.filter(
            delivery_note=delivery_note
        ).select_related("crate_type")
        summary = summarize_crate_items(
            rows,
            resolve_tax_rate=lambda crate_type: _get_tax_rate(crate_type, date),
            extras={
                "delivery_note_id": str(delivery_note.id),
                "delivery_note_number": delivery_note.display_number,
                "delivery_note_prefix": delivery_note.prefix,
                "delivery_note_is_finalized": delivery_note.is_finalized,
            },
        )
        return Response(summary)

    @transaction.atomic
    @extend_schema(
        description="Create a new crate entry for a delivery note.",
        request=_CRATE_DELIVERY_NOTE_CONTENT_WRITE_REQUEST,
        responses={
            201: CrateItemSummarySerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        delivery_note = get_or_404(
            DeliveryNoteReseller,
            request.data.get("delivery_note_id"),
            "Delivery note",
        )
        _reject_finalized(delivery_note, "delivery note", "add crates to finalized")

        crate_type = get_or_404(Crate, request.data.get("crate_type"), "Crate type")

        # tax_rate is NOT NULL on the model; resolve it the same way the invoice
        # crate paths do (caller-supplied → live CrateNetPrice → tenant setting →
        # crate default) so the INSERT never sends NULL.
        requested_tax_rate = request.data.get("tax_rate")
        if requested_tax_rate is None:
            requested_tax_rate = _get_tax_rate(
                crate_type, date_from_order(delivery_note.order)
            )
        CrateDeliveryNoteContent.objects.create(
            delivery_note=delivery_note,
            crate_type=crate_type,
            amount=request.data.get("amount"),
            price_per_unit=request.data.get("price_per_unit"),
            rabatt=request.data.get("rabatt", 0),
            tax_rate=requested_tax_rate,
            note=request.data.get("note", ""),
        )

        return Response(
            self._get_crate_summary(delivery_note, crate_type),
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    @extend_schema(
        description="Update crate amount for a delivery note via adjustment entries.",
        request=_CRATE_DELIVERY_NOTE_CONTENT_WRITE_REQUEST,
        responses={
            200: CrateItemSummarySerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    def update(
        self,
        request: Request,
        pk: str | None = None,
        **kwargs: Any,
    ) -> Response:
        delivery_note_id = request.data.get("delivery_note_id")
        crate_type_id = request.data.get("crate_type")
        new_total_amount = request.data.get("amount")
        price_per_unit = request.data.get("price_per_unit")
        rabatt = request.data.get("rabatt", 0)

        if not all([delivery_note_id, crate_type_id]) or new_total_amount is None:
            raise CrateDeliveryNoteContentMissingRequired(
                "delivery_note_id, crate_type and amount are required"
            )

        delivery_note = get_or_404(
            DeliveryNoteReseller, delivery_note_id, "Delivery note"
        )
        _reject_finalized(delivery_note, "delivery note", "modify crates in finalized")

        crate_type = get_or_404(Crate, crate_type_id, "Crate type")

        scope_qs = CrateDeliveryNoteContent.objects.filter(
            delivery_note=delivery_note,
            crate_type=crate_type,
        )
        # tax_rate is NOT NULL — an adjustment row created by the service would
        # otherwise INSERT NULL. Resolve it like create()/the invoice paths.
        requested_tax_rate = request.data.get("tax_rate")
        tax_rate = (
            requested_tax_rate
            if requested_tax_rate is not None
            else _get_tax_rate(crate_type, date_from_order(delivery_note.order))
        )
        CrateContentService.apply_total_amount_change(
            scope_qs=scope_qs,
            adjustment_qs=None,
            new_total_amount=int(new_total_amount),
            update_fields={
                "price_per_unit": price_per_unit,
                "rabatt": rabatt,
                "tax_rate": tax_rate,
            },
            create_kwargs={
                "delivery_note": delivery_note,
                "crate_type": crate_type,
            },
            model_class=CrateDeliveryNoteContent,
            lock_key=f"crate_totals:DeliveryNoteReseller:{delivery_note.id}:{crate_type.id}",
        )

        return Response(
            self._get_crate_summary(delivery_note, crate_type),
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        parameters=[
            get_delivery_note_id_parameter(),
            get_crate_type_parameter(),
        ],
        description="Delete all crate entries for a crate_type and delivery note.",
        responses={
            204: None,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    def destroy(
        self,
        request: Request,
        pk: str | None = None,
        **kwargs: Any,
    ) -> Response:
        params = validate_query_params(
            request, optional=["delivery_note_id", "crate_type"]
        )
        delivery_note_id = params["delivery_note_id"] or request.data.get(
            "delivery_note_id"
        )
        crate_type_id = params["crate_type"] or request.data.get("crate_type")

        if not delivery_note_id or not crate_type_id:
            raise CrateDeliveryNoteContentMissingRequired(
                "delivery_note_id and crate_type query parameters are required"
            )

        delivery_note = get_or_404(
            DeliveryNoteReseller, delivery_note_id, "Delivery note"
        )
        _reject_finalized(
            delivery_note, "delivery note", "delete crates from finalized"
        )

        crate_type = get_or_404(Crate, crate_type_id, "Crate type")

        CrateDeliveryNoteContent.objects.filter(
            delivery_note=delivery_note,
            crate_type=crate_type,
        ).delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# CrateContentInvoiceReseller
# ---------------------------------------------------------------------------


class CrateContentInvoiceResellerViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = CrateContentInvoiceResellerSerializer

    def get_queryset(self) -> QuerySet[CrateContentInvoiceReseller]:
        return CrateContentInvoiceReseller.objects.select_related(
            "crate_type", "invoice"
        )

    def _get_crate_summary(
        self,
        invoice: InvoiceReseller,
        crate_type: Crate,
    ) -> dict[str, Any]:
        extras = {
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.display_number,
            "invoice_prefix": invoice.prefix,
            "invoice_is_finalized": invoice.is_finalized,
        }
        rows = CrateContentInvoiceReseller.objects.filter(
            invoice=invoice, crate_type=crate_type
        ).select_related("crate_type")
        summary = summarize_crate_items(
            rows,
            resolve_tax_rate=lambda ct: get_default_tax_rate_crates(),
            extras=extras,
        )
        return (
            summary[0]
            if summary
            else build_crate_summary_row(
                crate_type_id=str(crate_type.id),
                crate_type_name=crate_type.name,
                amount=0,
                price=0,
                rabatt=0,
                tax_rate=get_default_tax_rate_crates(),
                extras=extras,
            )
        )

    @extend_schema(
        parameters=[get_invoice_id_parameter()],
        description="Get aggregated summary of crates by type for an invoice.",
        responses={
            200: CrateItemSummarySerializer(many=True),
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        params = validate_query_params(request, required=["invoice_id"])
        invoice = get_or_404(
            InvoiceReseller,
            params["invoice_id"],
            "Invoice",
        )

        rows = CrateContentInvoiceReseller.objects.filter(
            invoice=invoice
        ).select_related("crate_type")
        summary = summarize_crate_items(
            rows,
            resolve_tax_rate=lambda crate_type: get_default_tax_rate_crates(),
            extras={
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.display_number,
                "invoice_prefix": invoice.prefix,
                "invoice_is_finalized": invoice.is_finalized,
            },
        )
        return Response(summary)

    @transaction.atomic
    @extend_schema(
        description="Create a new crate entry for an invoice.",
        request=_CRATE_INVOICE_CONTENT_WRITE_REQUEST,
        responses={
            201: CrateItemSummarySerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        invoice = get_or_404(InvoiceReseller, request.data.get("invoice_id"), "Invoice")
        _reject_finalized(invoice, "invoice", "add crates to finalized")

        crate_type = get_or_404(Crate, request.data.get("crate_type"), "Crate type")

        # Fall through the canonical resolution chain when the caller
        # didn't pin a tax_rate: live CrateNetPrice → tenant setting →
        # hardcoded crate default. See utils/tax_rate_utils.py.
        requested_tax_rate = request.data.get("tax_rate")
        if requested_tax_rate is None:
            requested_tax_rate = _get_tax_rate(crate_type, invoice.date)
        CrateContentInvoiceReseller.objects.create(
            invoice=invoice,
            crate_type=crate_type,
            amount=request.data.get("amount"),
            price_per_unit=request.data.get("price_per_unit"),
            rabatt=request.data.get("rabatt", 0),
            tax_rate=requested_tax_rate,
            note=request.data.get("note", ""),
        )

        return Response(
            self._get_crate_summary(invoice, crate_type),
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    @extend_schema(
        description="Update crate amount for an invoice via adjustment entries.",
        request=_CRATE_INVOICE_CONTENT_WRITE_REQUEST,
        responses={
            200: CrateItemSummarySerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    def update(
        self,
        request: Request,
        pk: str | None = None,
        **kwargs: Any,
    ) -> Response:
        invoice_id = request.data.get("invoice_id")
        crate_type_id = request.data.get("crate_type")
        new_total_amount = request.data.get("amount")
        price_per_unit = request.data.get("price_per_unit")
        rabatt = request.data.get("rabatt", 0)

        if not all([invoice_id, crate_type_id]) or new_total_amount is None:
            raise CrateContentInvoiceMissingRequired(
                "invoice_id, crate_type and amount are required"
            )

        invoice = get_or_404(InvoiceReseller, invoice_id, "Invoice")
        _reject_finalized(invoice, "invoice", "modify crates in finalized")

        crate_type = get_or_404(Crate, crate_type_id, "Crate type")

        # Same canonical resolution as create() above.
        requested_tax_rate = request.data.get("tax_rate")
        tax_rate = (
            requested_tax_rate
            if requested_tax_rate is not None
            else _get_tax_rate(crate_type, invoice.date)
        )

        scope_qs = CrateContentInvoiceReseller.objects.filter(
            invoice=invoice,
            crate_type=crate_type,
        )
        CrateContentService.apply_total_amount_change(
            scope_qs=scope_qs,
            adjustment_qs=None,
            new_total_amount=int(new_total_amount),
            update_fields={
                "price_per_unit": price_per_unit,
                "rabatt": rabatt,
                "tax_rate": tax_rate,
            },
            create_kwargs={
                "invoice": invoice,
                "crate_type": crate_type,
            },
            model_class=CrateContentInvoiceReseller,
            lock_key=f"crate_totals:InvoiceReseller:{invoice.id}:{crate_type.id}",
        )

        return Response(
            self._get_crate_summary(invoice, crate_type),
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        parameters=[
            get_invoice_id_parameter(),
            get_crate_type_parameter(),
        ],
        description="Delete all crate entries for a crate_type and invoice.",
        responses={
            204: None,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    def destroy(
        self,
        request: Request,
        pk: str | None = None,
        **kwargs: Any,
    ) -> Response:
        params = validate_query_params(request, optional=["invoice_id", "crate_type"])
        invoice_id = params["invoice_id"] or request.data.get("invoice_id")
        crate_type_id = params["crate_type"] or request.data.get("crate_type")

        if not invoice_id or not crate_type_id:
            raise CrateContentInvoiceMissingRequired(
                "invoice_id and crate_type query parameters are required"
            )

        invoice = get_or_404(InvoiceReseller, invoice_id, "Invoice")
        _reject_finalized(invoice, "invoice", "delete crates from finalized")

        crate_type = get_or_404(Crate, crate_type_id, "Crate type")

        CrateContentInvoiceReseller.objects.filter(
            invoice=invoice,
            crate_type=crate_type,
        ).delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# CrateNetPrice
# ---------------------------------------------------------------------------


@extend_schema_view(
    create=extend_schema(responses=CrateNetPriceSerializer),
    retrieve=extend_schema(responses=CrateNetPriceSerializer),
    update=extend_schema(responses=CrateNetPriceSerializer),
    partial_update=extend_schema(responses=CrateNetPriceSerializer),
)
class CrateNetPriceViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """ViewSet for managing crate prices.

    Prices are time-bound with valid_from / valid_until dates. Pass
    ``?current=true`` to filter to the row that's currently valid.
    """

    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = CrateNetPriceSerializer

    @extend_schema(
        parameters=[get_crate_parameter(), get_current_parameter()],
        responses=CrateNetPriceSerializer(many=True),
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[CrateNetPrice]:
        queryset = CrateNetPrice.objects.select_related("crate")

        params = validate_query_params(self.request, optional=["crate", "current"])

        crate = params["crate"]
        if crate:
            queryset = queryset.filter(crate_id=crate)

        current = params["current"]
        if current is not None:
            queryset = queryset.filter(valid_until__isnull=True)

        # Latest first per crate — modals scroll through price history
        # newest-on-top; crate__name is the secondary group sort.
        return queryset.order_by("-valid_from", "-id")
