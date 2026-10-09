from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
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
from core.db_locks import acquire_advisory_xact_lock
from core.serializers import ErrorResponseSerializer

from ..constants import crates_should_be_on_documents, get_default_tax_rate_crates
from ..errors import (
    CompositeIdInvalid,
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
from ..services.crate_lines import CrateLineId, crate_line_rows, parse_crate_line_id
from ..services.crate_summary import (
    build_crate_summary_row,
    summarize_crate_items,
    summarize_crate_line,
)
from ..utils.iso_week_utils import date_from_order
from ..utils.lookup import get_or_404
from ..utils.query_params import validate_query_params
from ..utils.tax_rate_utils import resolve_crate_tax_rate
from .base_viewsets import CanBeDeletedDestroyMixin


def _get_tax_rate(crate: Crate, date: datetime.date) -> float:
    """Resolve a crate tax rate, falling back to the configured default."""
    return float(
        resolve_crate_tax_rate(crate, date, default=get_default_tax_rate_crates())
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

    ``update_fields`` is written to every row of the crate line, so it carries
    only the keys the client sent: a body without ``price_per_unit``,
    ``rabatt``, ``tax_rate`` or ``note`` keeps the stored values instead of
    clearing the price, discount or note of a document line. ``tax_rate`` is
    NOT NULL, so an explicit null resolves the crate's rate and writes that.

    ``new_row_defaults`` covers a row the service creates for the amount
    difference when the line has no rows: an omitted ``rabatt`` stores 0 (as
    ``create`` does) and an omitted ``tax_rate`` the resolved rate.
    """
    update_fields: dict[str, Any] = {
        field: data[field]
        for field in ("price_per_unit", "rabatt", "note")
        if field in data
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


def _reject_finalized(
    obj: DeliveryNoteReseller | InvoiceReseller, kind: str, action: str
) -> None:
    """Raise ``FinalizedError`` if ``obj`` is finalized; otherwise do nothing."""
    if obj.is_finalized:
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


def _delivery_note_extras(delivery_note: DeliveryNoteReseller) -> dict[str, Any]:
    return {
        "delivery_note_id": str(delivery_note.id),
        "delivery_note_number": delivery_note.display_number,
        "delivery_note_prefix": delivery_note.prefix,
        "delivery_note_is_finalized": delivery_note.is_finalized,
    }


def _invoice_extras(invoice: InvoiceReseller) -> dict[str, Any]:
    return {
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.display_number,
        "invoice_prefix": invoice.prefix,
        "invoice_is_finalized": invoice.is_finalized,
    }


def _crate_line_of_type(pk: str | None, crate_type: Crate) -> CrateLineId:
    """Parse the crate line id ``pk`` of a write whose body or query names
    ``crate_type``. A line of another crate type is a malformed request."""
    line_id = parse_crate_line_id(pk or "")
    if line_id.row_pk is not None and line_id.crate_type_id != str(crate_type.id):
        raise CompositeIdInvalid(
            f"Crate line {pk!r} is not a line of crate type {crate_type.id!r}.",
            code="crate_line.invalid_id",
        )
    return line_id


@dataclass(frozen=True)
class _DocumentCrateRows:
    """The crate rows of one crate type on one delivery note or invoice.

    A write to one of their lines reads them, picks the line it names and
    writes it, all under the per-(document, crate type) advisory lock, so no
    other write changes the line in between.
    """

    model: type[CrateDeliveryNoteContent] | type[CrateContentInvoiceReseller]
    document_field: str
    document: DeliveryNoteReseller | InvoiceReseller
    crate_type: Crate

    @property
    def lock_key(self) -> str:
        return (
            f"crate_totals:{type(self.document).__name__}:"
            f"{self.document.id}:{self.crate_type.id}"
        )

    def queryset(self) -> QuerySet:
        return self.model.objects.filter(
            **{self.document_field: self.document}, crate_type=self.crate_type
        )


def _write_crate_line(
    rows: _DocumentCrateRows,
    line_id: CrateLineId,
    amount: int,
    fields: tuple[dict[str, Any], dict[str, Any]],
) -> str | None:
    """Set the line ``line_id`` names to ``amount`` crates and stamp the
    update ``fields`` (see ``_crate_update_fields``) on its rows.

    The scope is the line's row pks, never its values: the service re-sums the
    scope after stamping a new price or rabatt, which a value filter would no
    longer match. The line's other rows take the amount change, so the row
    naming the line stays, and with it the line's id; a line of one row takes
    the change itself and goes when it reaches 0. A line whose named row is
    gone is written anew while the document has no crates of the type.

    Returns the pk of the row whose line answers the request: the named row,
    or the row written in its place. None for a bare crate type id, which the
    type's first line answers.
    """
    update_fields, new_row_defaults = fields
    acquire_advisory_xact_lock(rows.lock_key)
    before = list(rows.queryset())
    line_pks = [row.pk for row in crate_line_rows(before, line_id)]
    others = [pk for pk in line_pks if pk != line_id.row_pk]
    CrateContentService.apply_total_amount_change(
        scope_qs=rows.model.objects.filter(pk__in=line_pks),
        adjustment_qs=rows.model.objects.filter(pk__in=others) if others else None,
        new_total_amount=amount,
        update_fields=update_fields,
        create_kwargs={
            rows.document_field: rows.document,
            "crate_type": rows.crate_type,
            **new_row_defaults,
        },
        model_class=rows.model,
        lock_key=rows.lock_key,
    )
    if line_id.row_pk is None:
        return None
    after = set(rows.queryset().values_list("pk", flat=True))
    created = sorted(after - {row.pk for row in before})
    if line_id.row_pk not in after and created:
        return created[0]
    return line_id.row_pk


def _delete_crate_line(rows: _DocumentCrateRows, line_id: CrateLineId) -> None:
    """Delete the rows of the line ``line_id`` names, every row of the crate
    type for a bare crate type id, under the lock the line's writes take."""
    acquire_advisory_xact_lock(rows.lock_key)
    line_pks = [row.pk for row in crate_line_rows(rows.queryset(), line_id)]
    rows.model.objects.filter(pk__in=line_pks).delete()


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
        row_pk: str | None,
        requested_id: str,
    ) -> dict[str, Any]:
        """The crate line holding the row ``row_pk``, or the type's first line
        for None; a zero line under ``requested_id`` when there is none."""
        extras = _delivery_note_extras(delivery_note)
        rows = CrateDeliveryNoteContent.objects.filter(
            delivery_note=delivery_note, crate_type=crate_type
        ).select_related("crate_type")
        line = summarize_crate_line(rows, row_pk, extras=extras)
        if line is not None:
            return line
        placeholder = build_crate_summary_row(
            crate_type_id=str(crate_type.id),
            crate_type_name=crate_type.name,
            amount=0,
            price=0,
            rabatt=0,
            tax_rate=_get_tax_rate(crate_type, date_from_order(delivery_note.order)),
            extras=extras,
        )
        placeholder["id"] = requested_id
        return placeholder

    @extend_schema(
        parameters=[get_delivery_note_id_parameter()],
        description=(
            "List a delivery note's crate lines: one per crate type, price, rabatt "
            "and tax rate, named `{crate type id}_{row id}`."
        ),
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

        rows = CrateDeliveryNoteContent.objects.filter(
            delivery_note=delivery_note
        ).select_related("crate_type")
        summary = summarize_crate_items(
            rows, extras=_delivery_note_extras(delivery_note)
        )
        return Response(summary)

    @transaction.atomic
    @extend_schema(
        description=(
            "Add a crate row to a delivery note and answer with the crate line "
            "that holds it."
        ),
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
        row = CrateDeliveryNoteContent.objects.create(
            delivery_note=delivery_note,
            crate_type=crate_type,
            amount=data["amount"],
            price_per_unit=data.get("price_per_unit"),
            rabatt=data.get("rabatt", 0),
            tax_rate=requested_tax_rate,
            note=data.get("note", ""),
        )

        return Response(
            self._get_crate_summary(
                delivery_note, crate_type, row.pk, str(crate_type.id)
            ),
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    @extend_schema(
        description=(
            "Set the amount, price, rabatt, tax rate and note of one crate line "
            "of a delivery note, through adjustment entries. The id names the line; a "
            "bare crate type id names every line of that type."
        ),
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
        line_id = _crate_line_of_type(pk, crate_type)
        data = _validated_crate_write(
            CrateDeliveryNoteContentWriteRequestSerializer, request
        )

        # tax_rate is NOT NULL — an adjustment row created by the service would
        # otherwise INSERT NULL. Resolve it like create()/the invoice paths.
        fields = _crate_update_fields(
            data,
            lambda: _get_tax_rate(crate_type, date_from_order(delivery_note.order)),
        )
        row_pk = _write_crate_line(
            _DocumentCrateRows(
                CrateDeliveryNoteContent, "delivery_note", delivery_note, crate_type
            ),
            line_id,
            data["amount"],
            fields,
        )

        return Response(
            self._get_crate_summary(delivery_note, crate_type, row_pk, str(pk)),
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
    @extend_schema(
        parameters=[
            get_delivery_note_id_parameter(),
            get_crate_type_parameter(),
        ],
        description=(
            "Delete one crate line of a delivery note. The id names the line; a "
            "bare crate type id deletes every line of that type."
        ),
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

        _delete_crate_line(
            _DocumentCrateRows(
                CrateDeliveryNoteContent, "delivery_note", delivery_note, crate_type
            ),
            _crate_line_of_type(pk, crate_type),
        )

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
        row_pk: str | None,
        requested_id: str,
    ) -> dict[str, Any]:
        """The crate line holding the row ``row_pk``, or the type's first line
        for None; a zero line under ``requested_id`` when there is none."""
        extras = _invoice_extras(invoice)
        rows = CrateContentInvoiceReseller.objects.filter(
            invoice=invoice, crate_type=crate_type
        ).select_related("crate_type")
        line = summarize_crate_line(rows, row_pk, extras=extras)
        if line is not None:
            return line
        placeholder = build_crate_summary_row(
            crate_type_id=str(crate_type.id),
            crate_type_name=crate_type.name,
            amount=0,
            price=0,
            rabatt=0,
            tax_rate=get_default_tax_rate_crates(),
            extras=extras,
        )
        placeholder["id"] = requested_id
        return placeholder

    @extend_schema(
        parameters=[get_invoice_id_parameter()],
        description=(
            "List an invoice's crate lines: one per crate type, price, rabatt and "
            "tax rate, named `{crate type id}_{row id}`."
        ),
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
        summary = summarize_crate_items(rows, extras=_invoice_extras(invoice))
        return Response(summary)

    @transaction.atomic
    @extend_schema(
        description=(
            "Add a crate row to an invoice and answer with the crate line that "
            "holds it."
        ),
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
        row = CrateContentInvoiceReseller.objects.create(
            invoice=invoice,
            crate_type=crate_type,
            amount=data["amount"],
            price_per_unit=data.get("price_per_unit"),
            rabatt=data.get("rabatt", 0),
            tax_rate=requested_tax_rate,
            note=data.get("note", ""),
        )

        return Response(
            self._get_crate_summary(invoice, crate_type, row.pk, str(crate_type.id)),
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    @extend_schema(
        description=(
            "Set the amount, price, rabatt, tax rate and note of one crate line "
            "of an invoice, through adjustment entries. The id names the line; a bare "
            "crate type id names every line of that type."
        ),
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
        line_id = _crate_line_of_type(pk, crate_type)
        data = _validated_crate_write(
            CrateInvoiceContentWriteRequestSerializer, request
        )

        # Same canonical resolution as create() above.
        fields = _crate_update_fields(
            data, lambda: _get_tax_rate(crate_type, invoice.date)
        )
        row_pk = _write_crate_line(
            _DocumentCrateRows(
                CrateContentInvoiceReseller, "invoice", invoice, crate_type
            ),
            line_id,
            data["amount"],
            fields,
        )

        return Response(
            self._get_crate_summary(invoice, crate_type, row_pk, str(pk)),
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
    @extend_schema(
        parameters=[
            get_invoice_id_parameter(),
            get_crate_type_parameter(),
        ],
        description=(
            "Delete one crate line of an invoice. The id names the line; a bare "
            "crate type id deletes every line of that type."
        ),
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

        _delete_crate_line(
            _DocumentCrateRows(
                CrateContentInvoiceReseller, "invoice", invoice, crate_type
            ),
            _crate_line_of_type(pk, crate_type),
        )

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
