from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, IsStaff, RolePermissionsMixin
from apps.shared.request_utils import body
from core.serializers import ErrorResponseSerializer

from ..constants import crates_should_be_on_documents, get_default_tax_rate_crates
from ..errors import (
    CrateContentInvoiceMissingRequired,
    CrateDeliveryNoteContentMissingRequired,
    CrateNetPriceInUse,
    CratesDisabledOnDocuments,
    FinalizedError,
    InvalidAmount,
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
    CrateDeliveryNoteContentWriteRequestSerializer,
    CrateInvoiceContentWriteRequestSerializer,
    CrateItemSummarySerializer,
    CrateNetPriceSerializer,
)
from ..services import CrateContentService
from ..services.crate_summary import build_crate_summary_row, summarize_crate_items
from ..utils.iso_week_utils import date_from_order
from ..utils.lookup import get_or_404
from ..utils.query_params import validate_query_params
from ..utils.tax_rate_utils import resolve_crate_tax_rate
from .base_viewsets import CanBeDeletedDestroyMixin


def _get_tax_rate(crate: Crate | None, date: datetime.date) -> float:
    """Resolve a crate tax rate, falling back to the configured default."""
    return float(
        resolve_crate_tax_rate(crate, date, default=get_default_tax_rate_crates())
        if crate is not None
        else get_default_tax_rate_crates()
    )


def _validated_crate_write(
    serializer_class: type[drf_serializers.Serializer], request: Request
) -> dict[str, Any]:
    """Validate a crate-line create/update body and return its validated data.

    A missing, blank or non-integer ``amount`` reports the catalogued
    ``amount.invalid`` (400) the create endpoints already returned for it,
    rather than the serializer's generic ``validation_error``: unlike an order
    line, where a missing amount means zero, a crate line with no crate count
    is a malformed request. Every other field error is the serializer's own 400
    with a per-field ``details`` map.
    """
    serializer = serializer_class(data=request.data)
    if not serializer.is_valid() and "amount" in serializer.errors:
        raw = body(request).get("amount")
        if raw is None or raw == "":
            raise InvalidAmount("An amount is required.", field="amount")
        raise InvalidAmount(
            f"Invalid amount {raw!r} — expected a whole number of crates.",
            field="amount",
        )
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _crate_update_fields(
    data: dict[str, Any], resolve_tax_rate: Callable[[], float]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a validated crate update into ``(update_fields, new_row_defaults)``.

    ``update_fields`` is written to every existing row of the crate type, so it
    carries only the keys the client sent: a body without ``price_per_unit``,
    ``rabatt`` or ``tax_rate`` keeps the stored values instead of clearing the
    price and discount of a document line. ``tax_rate`` is NOT NULL, so an
    explicit null resolves the crate's rate and writes that.

    ``new_row_defaults`` covers a row the service creates for the amount
    difference when the crate type has no rows yet: an omitted ``rabatt``
    stores 0 (as ``create`` does) and an omitted ``tax_rate`` the resolved rate.
    """
    update_fields: dict[str, Any] = {
        field: data[field] for field in ("price_per_unit", "rabatt") if field in data
    }
    new_row_defaults: dict[str, Any] = {}
    if "rabatt" not in data:
        new_row_defaults["rabatt"] = 0
    if data.get("tax_rate") is not None:
        update_fields["tax_rate"] = data["tax_rate"]
    elif "tax_rate" in data:
        update_fields["tax_rate"] = resolve_tax_rate()
    else:
        new_row_defaults["tax_rate"] = resolve_tax_rate()
    return update_fields, new_row_defaults


def _reject_finalized(obj: Any, kind: str, action: str) -> None:
    """Raise ``FinalizedError`` if ``obj`` is finalized; otherwise do nothing."""
    if getattr(obj, "is_finalized", False):
        raise FinalizedError(
            f"Cannot {action} {kind}",
            code=f"{kind.replace(' ', '_')}.finalized",
        )


def _reject_if_crates_disabled() -> None:
    """Reject a manual crate write when the tenant keeps crates OFF documents.
    The office UI hides these controls, but the endpoints are still reachable
    (direct API / a stale tab) — this closes that bypass so the setting is
    honoured end-to-end."""
    if not crates_should_be_on_documents():
        raise CratesDisabledOnDocuments(
            "Crates are disabled on documents for this tenant."
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
        request=CrateDeliveryNoteContentWriteRequestSerializer,
        responses={
            201: CrateItemSummarySerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _reject_if_crates_disabled()
        delivery_note_id = body(request).get("delivery_note_id")
        crate_type_id = body(request).get("crate_type")

        # The same three-key pre-check ``update`` runs, so an omitted field
        # reports one code for the whole write regardless of the verb, and
        # ``get_or_404`` is left to answer only for an id that is present but
        # unknown.
        if (
            not all([delivery_note_id, crate_type_id])
            or body(request).get("amount") is None
        ):
            raise CrateDeliveryNoteContentMissingRequired(
                "delivery_note_id, crate_type and amount are required"
            )

        delivery_note = get_or_404(
            DeliveryNoteReseller,
            delivery_note_id,
            "Delivery note",
        )
        _reject_finalized(delivery_note, "delivery note", "add crates to finalized")

        crate_type = get_or_404(Crate, crate_type_id, "Crate type")
        data = _validated_crate_write(
            CrateDeliveryNoteContentWriteRequestSerializer, request
        )

        # tax_rate is NOT NULL on the model; resolve it the same way the invoice
        # crate paths do (caller-supplied → live CrateNetPrice → tenant setting →
        # crate default) so the INSERT never sends NULL.
        requested_tax_rate = data.get("tax_rate")
        if requested_tax_rate is None:
            requested_tax_rate = _get_tax_rate(
                crate_type, date_from_order(delivery_note.order)
            )
        CrateDeliveryNoteContent.objects.create(
            delivery_note=delivery_note,
            crate_type=crate_type,
            amount=data["amount"],
            price_per_unit=data.get("price_per_unit"),
            rabatt=data.get("rabatt", 0),
            tax_rate=requested_tax_rate,
            note=data.get("note", ""),
        )

        return Response(
            self._get_crate_summary(delivery_note, crate_type),
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    @extend_schema(
        description="Update crate amount for a delivery note via adjustment entries.",
        request=CrateDeliveryNoteContentWriteRequestSerializer,
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
        _reject_if_crates_disabled()
        delivery_note_id = body(request).get("delivery_note_id")
        crate_type_id = body(request).get("crate_type")

        if (
            not all([delivery_note_id, crate_type_id])
            or body(request).get("amount") is None
        ):
            raise CrateDeliveryNoteContentMissingRequired(
                "delivery_note_id, crate_type and amount are required"
            )

        delivery_note = get_or_404(
            DeliveryNoteReseller, delivery_note_id, "Delivery note"
        )
        _reject_finalized(delivery_note, "delivery note", "modify crates in finalized")

        crate_type = get_or_404(Crate, crate_type_id, "Crate type")
        data = _validated_crate_write(
            CrateDeliveryNoteContentWriteRequestSerializer, request
        )

        scope_qs = CrateDeliveryNoteContent.objects.filter(
            delivery_note=delivery_note,
            crate_type=crate_type,
        )
        # tax_rate is NOT NULL — an adjustment row created by the service would
        # otherwise INSERT NULL. Resolve it like create()/the invoice paths.
        update_fields, new_row_defaults = _crate_update_fields(
            data,
            lambda: _get_tax_rate(crate_type, date_from_order(delivery_note.order)),
        )
        CrateContentService.apply_total_amount_change(
            scope_qs=scope_qs,
            adjustment_qs=None,
            new_total_amount=data["amount"],
            update_fields=update_fields,
            create_kwargs={
                "delivery_note": delivery_note,
                "crate_type": crate_type,
                **new_row_defaults,
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
        delivery_note_id = params["delivery_note_id"] or body(request).get(
            "delivery_note_id"
        )
        crate_type_id = params["crate_type"] or body(request).get("crate_type")

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
        request=CrateInvoiceContentWriteRequestSerializer,
        responses={
            201: CrateItemSummarySerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _reject_if_crates_disabled()
        invoice_id = body(request).get("invoice_id")
        crate_type_id = body(request).get("crate_type")

        # The same three-key pre-check ``update`` runs — see the delivery-note
        # sibling for the rationale.
        if not all([invoice_id, crate_type_id]) or body(request).get("amount") is None:
            raise CrateContentInvoiceMissingRequired(
                "invoice_id, crate_type and amount are required"
            )

        invoice = get_or_404(InvoiceReseller, invoice_id, "Invoice")
        _reject_finalized(invoice, "invoice", "add crates to finalized")

        crate_type = get_or_404(Crate, crate_type_id, "Crate type")
        data = _validated_crate_write(
            CrateInvoiceContentWriteRequestSerializer, request
        )

        # Fall through the canonical resolution chain when the caller
        # didn't pin a tax_rate: live CrateNetPrice → tenant setting →
        # hardcoded crate default. See utils/tax_rate_utils.py.
        requested_tax_rate = data.get("tax_rate")
        if requested_tax_rate is None:
            requested_tax_rate = _get_tax_rate(crate_type, invoice.date)
        CrateContentInvoiceReseller.objects.create(
            invoice=invoice,
            crate_type=crate_type,
            amount=data["amount"],
            price_per_unit=data.get("price_per_unit"),
            rabatt=data.get("rabatt", 0),
            tax_rate=requested_tax_rate,
            note=data.get("note", ""),
        )

        return Response(
            self._get_crate_summary(invoice, crate_type),
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    @extend_schema(
        description="Update crate amount for an invoice via adjustment entries.",
        request=CrateInvoiceContentWriteRequestSerializer,
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
        _reject_if_crates_disabled()
        invoice_id = body(request).get("invoice_id")
        crate_type_id = body(request).get("crate_type")

        if not all([invoice_id, crate_type_id]) or body(request).get("amount") is None:
            raise CrateContentInvoiceMissingRequired(
                "invoice_id, crate_type and amount are required"
            )

        invoice = get_or_404(InvoiceReseller, invoice_id, "Invoice")
        _reject_finalized(invoice, "invoice", "modify crates in finalized")

        crate_type = get_or_404(Crate, crate_type_id, "Crate type")
        data = _validated_crate_write(
            CrateInvoiceContentWriteRequestSerializer, request
        )

        # Same canonical resolution as create() above.
        update_fields, new_row_defaults = _crate_update_fields(
            data, lambda: _get_tax_rate(crate_type, invoice.date)
        )

        scope_qs = CrateContentInvoiceReseller.objects.filter(
            invoice=invoice,
            crate_type=crate_type,
        )
        CrateContentService.apply_total_amount_change(
            scope_qs=scope_qs,
            adjustment_qs=None,
            new_total_amount=data["amount"],
            update_fields=update_fields,
            create_kwargs={
                "invoice": invoice,
                "crate_type": crate_type,
                **new_row_defaults,
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
        invoice_id = params["invoice_id"] or body(request).get("invoice_id")
        crate_type_id = params["crate_type"] or body(request).get("crate_type")

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
class CrateNetPriceViewSet(
    CanBeDeletedDestroyMixin, RolePermissionsMixin, viewsets.ModelViewSet
):
    """ViewSet for managing crate prices.

    Prices are time-bound with valid_from / valid_until dates. Pass
    ``?current=true`` to filter to the row that's currently valid.
    """

    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = CrateNetPriceSerializer
    # DELETE enforces the serializer's ``can_be_deleted`` rule: an active price
    # of a crate that is in use is refused.
    not_deletable_error = CrateNetPriceInUse

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
        # Truthiness, not ``is not None``: ``current`` is a strict bool, so
        # ``?current=false`` must NOT restrict to the open record.
        if current:
            queryset = queryset.filter(valid_until__isnull=True)

        # Latest first per crate — modals scroll through price history
        # newest-on-top; crate__name is the secondary group sort.
        return queryset.order_by("-valid_from", "-id")
