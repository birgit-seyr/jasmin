from __future__ import annotations

from typing import Any

from django.contrib.postgres.aggregates import StringAgg
from django.db.models import Count, F, Prefetch, QuerySet
from django.db.models.expressions import Exists, OuterRef
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import (
    IsOffice,
    IsOfficeOrCustomer,
    IsStaff,
    IsStaffOrCustomer,
    RolePermissionsMixin,
)
from apps.shared.pii_logging import PIIReadLoggingMixin
from core.errors import ForbiddenError, NotFoundError
from core.pagination import OptionalLimitOffsetPagination
from core.serializers import ErrorResponseSerializer

from ..errors import (
    DocumentNotFinalized,
    DocumentPdfMissing,
    InvalidUploadedDocument,
    OfferGroupCannotDeleteDefault,
    RequiredFieldMissing,
    ResellerEmailMissing,
    ResellerNotFound,
)
from ..models import (
    DeliveryNoteContent,
    DeliveryNoteReseller,
    Forecast,
    InvoiceReseller,
    InvoiceResellerContent,
    Offer,
    OfferGroup,
    Order,
    OrderContent,
    OrganicCertificate,
    Reseller,
)
from ..models.choices_text import InvitationStatus
from ..models.members import UserInvitation
from ..schemas import (
    get_day_number_parameter,
    get_delivery_day_parameter,
    get_delivery_note_id_parameter,
    get_delivery_week_parameter,
    get_invoice_id_parameter,
    get_offer_group_parameter,
    get_order_id_parameter,
    get_reseller_parameter,
    get_year_parameter,
)
from ..scoping import (
    enforce_own_reseller,
    enforce_privileged,
    is_privileged,
    own_reseller_id,
    scope_to_offer_group,
    scope_to_reseller,
)
from ..serializers import (
    CommissioningListResellersEntry,
    CrateOrderContentCreateRequestSerializer,
    CrateOrderContentSerializer,
    CrateOrderContentUpdateRequestSerializer,
    CrateOrderSummarySerializer,
    CreateStornoRequestSerializer,
    DeliveryNoteResellerContentSerializer,
    DeliveryNoteResellerSerializer,
    InvoiceResellerContentSerializer,
    InvoiceResellerSerializer,
    OfferGroupSerializer,
    OfferSerializer,
    OrderContentItemSerializer,
    OrderContentListResponseSerializer,
    OrderContentSerializer,
    OrganicCertificateSerializer,
    ResellerSerializer,
)
from ..services import (
    CrateOrderContentService,
    InvoiceService,
    OfferService,
    OrderContentService,
    ResellerAndDeliveryStationService,
)
from ..utils import get_contact_annotations
from ..utils.lookup import get_or_404
from ..utils.query_params import validate_query_params
from ..utils.queryset_helpers import apply_optional_filters

_BOOL_RESELLER_PARAMS = [
    OpenApiParameter(
        name=name, type=OpenApiTypes.BOOL, required=False, description=desc
    )
    for name, desc in [
        ("is_active_reseller", "Filter by active reseller status"),
        ("is_active_seller", "Filter by active seller status"),
        ("is_active_donation_recipient", "Filter by active donation recipient status"),
        ("is_active_supplier", "Filter by active supplier status"),
        ("is_reseller", "Filter by reseller flag"),
        ("is_seller", "Filter by seller flag"),
        ("is_supplier", "Filter by supplier flag"),
        ("is_donation_recipient", "Filter by donation recipient flag"),
    ]
]

# Legit ``upload_pdf`` traffic is the frontend's own @react-pdf output
# (a real invoice is well under 2 MB), but the endpoint accepts arbitrary
# bytes from any authenticated client — so check the content, not just
# the filename, and cap the size. The stored file is emailed to resellers
# and accounting, which makes "malware named invoice.pdf" a real concern.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _validate_uploaded_document(uploaded_file, *, kind: str) -> str | None:
    """Magic-byte + size check for upload_pdf payloads.

    ``kind`` is ``"pdf"`` or ``"xml"``. Returns an error message for the
    400 response, or ``None`` when the file passes.
    """
    if uploaded_file.size > _MAX_UPLOAD_BYTES:
        return (
            f"{uploaded_file.name} exceeds the "
            f"{_MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit"
        )
    head = uploaded_file.read(64)
    uploaded_file.seek(0)
    if kind == "pdf" and not head.startswith(b"%PDF-"):
        return "file content is not a PDF"
    if kind == "xml":
        # Tolerate a UTF-8 BOM and leading whitespace; any XML document
        # (e-invoice XRechnung/ZUGFeRD included) then starts with ``<``.
        stripped = head.removeprefix(b"\xef\xbb\xbf").lstrip()
        if not stripped.startswith(b"<"):
            return "xml_file content is not XML"
    return None


def _verify_einvoice_xml_matches(obj, uploaded_xml) -> str | None:
    """Cross-check that an uploaded e-invoice XML actually describes THIS
    finalized document, so a wrong or hand-edited e-invoice can't be stored
    and emailed in its place (the magic-byte check alone only proves it is
    *some* XML).

    Deliberately conservative: it only HARD-FAILS on an unambiguous mismatch
    of the document number or the grand total. A missing element, an
    unparseable body, or a credit-note sign flip is tolerated (returns
    ``None``) so a legitimate upload is never blocked by a format quirk.
    """
    from decimal import Decimal, InvalidOperation

    import defusedxml.ElementTree as ET
    from defusedxml.common import DefusedXmlException

    number = getattr(obj, "number", None)
    try:
        sum_brutto = obj.sum_brutto
    except (AttributeError, TypeError):
        sum_brutto = None
    if number is None and sum_brutto is None:
        return None

    try:
        raw = uploaded_xml.read()
        uploaded_xml.seek(0)
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError, TypeError, DefusedXmlException):
        # Not structurally XML (magic-byte check stands), OR a hostile
        # DTD/entity payload defusedxml refuses to parse — reject either way
        # rather than letting an XXE / entity-expansion attempt through.
        return None

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    doc_id = None
    grand_total = None
    for element in root.iter():
        name = local(element.tag)
        if name == "ExchangedDocument" and doc_id is None:
            for child in element.iter():
                if local(child.tag) == "ID" and (child.text or "").strip():
                    doc_id = child.text.strip()
                    break
        elif name == "GrandTotalAmount" and (element.text or "").strip():
            grand_total = element.text.strip()

    # Number: compare the trailing segment after the last "-" (the XML id is
    # ``<prefix>-<number>``; the prefix itself may carry dashes / a year).
    if number is not None and doc_id:
        xml_number = doc_id.rsplit("-", 1)[-1].strip()
        if xml_number and xml_number != str(number):
            return "uploaded e-invoice number does not match this document"

    # Total: compare magnitudes (a storno credit note is positive in the XML
    # but negative on the record), 1-cent tolerance.
    if sum_brutto is not None and grand_total:
        try:
            if abs(abs(Decimal(grand_total)) - abs(Decimal(sum_brutto))) > Decimal(
                "0.01"
            ):
                return "uploaded e-invoice total does not match this document"
        except (InvalidOperation, ValueError, TypeError):
            pass

    return None


def validate_finalized_pdf_upload(
    obj, request, *, doc_label: str, allow_xml: bool = False
):
    """Shared pre-checks for the reseller ``upload_pdf`` actions.

    The document must be finalized, a ``file`` (``.pdf``, passing the
    magic-byte check) must be present, and — when ``allow_xml`` — an optional
    ``xml_file`` (``.xml``) is validated too. Raises the matching typed error on
    failure; on success returns ``(uploaded_file, uploaded_xml)`` where
    ``uploaded_xml`` is ``None`` unless ``allow_xml`` and one was sent.
    """
    if not obj.is_finalized:
        raise DocumentNotFinalized(
            f"{doc_label} must be finalized before uploading PDF."
        )
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        raise RequiredFieldMissing("No file provided.", field="file")
    if not uploaded_file.name.lower().endswith(".pdf"):
        raise InvalidUploadedDocument("file must be a .pdf", field="file")
    uploaded_xml = request.FILES.get("xml_file") if allow_xml else None
    if uploaded_xml and not uploaded_xml.name.lower().endswith(".xml"):
        raise InvalidUploadedDocument("xml_file must be a .xml", field="xml_file")
    content_error = _validate_uploaded_document(uploaded_file, kind="pdf")
    if content_error is None and uploaded_xml:
        content_error = _validate_uploaded_document(uploaded_xml, kind="xml")
    if content_error:
        raise InvalidUploadedDocument(content_error)
    if uploaded_xml:
        mismatch = _verify_einvoice_xml_matches(obj, uploaded_xml)
        if mismatch:
            raise InvalidUploadedDocument(mismatch, field="xml_file")
    return uploaded_file, uploaded_xml


# Reseller fields a non-privileged (customer-portal) caller may self-edit on
# their OWN reseller row via PATCH. Deliberately an ALLOWLIST, not a blocklist:
# every other field — pricing (offer_group), billing identity (invoice_*,
# customer_number, filial_number), role / activation flags, payment terms,
# notification channels — is office-only, and any field added to the model in
# future is office-only by default until explicitly listed here.
_CUSTOMER_EDITABLE_RESELLER_FIELDS = frozenset({"name_for_member_pages"})

# Pricing + finalization fields on an OrderContent that a customer must NEVER
# set on their own order — price is resolved server-side from the offer/article
# canonical chain. Without this guard a reseller-customer could PATCH their own
# order to price_per_unit=0.01 / rabatt=100 and self-underbill straight into the
# delivery note + invoice (their row is ownership-scoped, but the serializer is
# ``fields = "__all__"`` with no field-level privilege guard).
_ORDER_CONTENT_OFFICE_ONLY_FIELDS = frozenset(
    {"price_per_unit", "rabatt", "tax_rate", "is_finalized"}
)


class ResellerViewSet(PIIReadLoggingMixin, RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaffOrCustomer
    write_permission = IsOfficeOrCustomer
    serializer_class = ResellerSerializer
    pagination_class = OptionalLimitOffsetPagination

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.service = ResellerAndDeliveryStationService()

    @extend_schema(
        parameters=[
            *_BOOL_RESELLER_PARAMS,
            get_year_parameter(required=False),
            get_delivery_week_parameter(required=False),
            get_delivery_day_parameter(required=False),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Reseller]:
        from django.utils import timezone

        from ..models.managers import active_on_date_q

        # ``linked_delivery_station`` (reverse OneToOne) is read twice
        # per row by the serializer — in ``to_representation`` and
        # ``get_linked_delivery_station_can_be_deleted`` — and a reverse
        # OneToOne that resolves to "no row" is NOT cached, so each
        # access re-queries. ``linked_user`` is read by
        # ``get_linked_user_info``. select_related both so the list
        # endpoint stays scale-invariant (locked by
        # apps/payments/tests/test_query_count_locks.py).
        # ``serialize_user_row`` (via ``get_linked_user_info``) reads the
        # linked user's reverse ``linked_reseller`` OneToOne and its sent
        # invitation per row — both N+1 without the joins below. Mirror
        # ``_build_member_queryset`` so the list stays scale-invariant
        # (locked by apps/payments/tests/test_query_count_locks.py).
        sent_invitations_qs = UserInvitation.objects.filter(
            status=InvitationStatus.SENT
        ).order_by("-created_at")
        queryset = (
            Reseller.objects.select_related(
                "contact",
                "linked_user",
                "linked_user__linked_reseller",
                "linked_delivery_station",
            )
            .prefetch_related(
                Prefetch(
                    "linked_user__invitations",
                    queryset=sent_invitations_qs,
                    to_attr="_prefetched_sent_invitations",
                )
            )
            .annotate(
                # Drives the ListSellers certificate-button colour: does the
                # reseller hold an organic certificate whose validity window
                # covers today? One correlated subquery — stays scale-invariant.
                has_active_organic_certificate=Exists(
                    OrganicCertificate.objects.filter(reseller=OuterRef("pk")).filter(
                        active_on_date_q(timezone.now().date())
                    )
                )
            )
            .all()
        )

        params = validate_query_params(
            self.request,
            optional=[
                "is_active_reseller",
                "is_active_seller",
                "is_active_donation_recipient",
                "is_active_supplier",
                "is_reseller",
                "is_seller",
                "is_supplier",
                "is_donation_recipient",
                "year",
                "delivery_week",
                "delivery_day",
            ],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        delivery_day = params["delivery_day"]

        queryset = apply_optional_filters(
            queryset,
            params,
            [
                "is_active_reseller",
                "is_active_seller",
                "is_active_donation_recipient",
                "is_active_supplier",
                "is_reseller",
                "is_seller",
                "is_supplier",
                "is_donation_recipient",
            ],
        )

        if year and delivery_week and delivery_day:
            queryset = queryset.annotate(
                has_orders=Exists(
                    OrderContent.objects.filter(
                        order__year=year,
                        order__delivery_week=delivery_week,
                        order__day_number=delivery_day,
                        order__reseller=OuterRef("pk"),
                    )
                ),
            )

        contact_annotations = get_contact_annotations()
        queryset = queryset.annotate(**contact_annotations)

        # Non-privileged callers (customers) may only see/edit their own
        # linked reseller row.
        return scope_to_reseller(queryset, self.request, path="pk")

    @extend_schema(description="Create a reseller with a linked contact entity.")
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Customers may not create new resellers; only office/admin/management.
        enforce_privileged(request, "Only office staff may create resellers.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reseller = self.service.create_reseller(serializer.validated_data)

        updated_instance = self.get_queryset().get(pk=reseller.pk)
        response_serializer = self.get_serializer(updated_instance)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(description="Update a reseller and its linked contact entity.")
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        # Field-level privilege guard (``partial_update`` routes here too).
        # ``get_object`` already scopes a customer to their OWN reseller, but
        # the serializer is ``fields = "__all__"`` — so without this a customer
        # could rewrite pricing (offer_group), billing identity (invoice_*,
        # customer_number) or activation flags on that row: self-assign a
        # cheaper offer group, redirect their own invoices, reactivate
        # themselves. Non-privileged callers may only touch the display
        # allowlist; their contact details are self-edited via
        # ``MyCustomerDataView``. create/destroy are office-only (above/below).
        if not is_privileged(request):
            office_only_fields = (
                set(serializer.validated_data) - _CUSTOMER_EDITABLE_RESELLER_FIELDS
            )
            if office_only_fields:
                raise ForbiddenError(
                    "Only office staff may edit these reseller fields."
                )

        updated_instance = self.service.update_reseller(
            instance, serializer.validated_data
        )

        annotated_instance = self.get_queryset().get(pk=updated_instance.pk)
        response_serializer = self.get_serializer(annotated_instance)
        return Response(response_serializer.data)

    @extend_schema(
        description="Delete a reseller, optionally handling delivery station reassignment.",
        parameters=[
            OpenApiParameter(
                name="delete_context",
                type=OpenApiTypes.STR,
                required=False,
                description="Context for deletion logic (e.g. delivery station handling)",
            ),
        ],
    )
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Resellers may never be deleted by a customer — office-only operation.
        enforce_privileged(request, "Only office staff may delete resellers.")
        instance = self.get_object()
        params = validate_query_params(request, optional=["delete_context"])
        delete_context = params["delete_context"]

        self.service.delete_reseller(instance, delete_context)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ``partial_update`` is inherited from ``UpdateModelMixin`` (it routes into
# ``update`` below), so its schema has to be declared at class level.
@extend_schema_view(
    partial_update=extend_schema(
        description="Update order content amount and related fields.",
        responses={
            200: OrderContentItemSerializer,
            409: ErrorResponseSerializer,
        },
    )
)
class OrderContentViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaffOrCustomer
    write_permission = IsOfficeOrCustomer
    serializer_class = OrderContentSerializer

    @extend_schema(
        parameters=[
            get_reseller_parameter(required=True),
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=True),
        ],
        description="List offers and order contents for a reseller/week/day_number.",
        responses={200: OpenApiResponse(response=OrderContentListResponseSerializer)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Optional filters (the service handles ``None`` → empty scope); the
        # catalogue still type-validates them when present.
        params = validate_query_params(
            request,
            optional=["reseller", "year", "delivery_week", "day_number"],
        )
        reseller = params["reseller"]
        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]

        # Object scoping: non-privileged callers may only list order content
        # for their own linked reseller. Privileged staff roles bypass.
        if not is_privileged(request):
            own_id = own_reseller_id(request)
            if own_id is None:
                return Response({"items": [], "orders_delivery_day_defaults": {}})
            if reseller and str(reseller) != own_id:
                raise ForbiddenError("Cannot view order content for another reseller.")
            reseller = own_id

        result = OrderContentService.get_offers_and_order_content(
            reseller, year, delivery_week, day_number
        )

        return Response(result)

    def get_queryset(self) -> QuerySet[OrderContent]:
        queryset = OrderContent.objects.all()

        params = validate_query_params(
            self.request,
            optional=["year", "delivery_week", "day_number", "reseller"],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]
        reseller = params["reseller"]

        if year:
            queryset = queryset.filter(order__year=year)
        if delivery_week:
            queryset = queryset.filter(order__delivery_week=delivery_week)
        if day_number:
            queryset = queryset.filter(order__day_number=day_number)
        if reseller:
            try:
                queryset = queryset.filter(order__reseller=reseller)
            except Reseller.DoesNotExist:
                queryset = OrderContent.objects.none()

        queryset = queryset.annotate(
            order_number=F("order__number"),
            order_number_prefix=F("order__prefix"),
            offer_name=F("offer__share_article__name"),
        )

        return scope_to_reseller(queryset, self.request, path="order__reseller")

    @extend_schema(
        description="Create order content with an order and crates.",
        responses={
            200: OrderContentItemSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Non-privileged callers may only create order content for their own
        # linked reseller.
        reseller_obj = serializer.validated_data.get("reseller")
        reseller_id = getattr(reseller_obj, "pk", reseller_obj)
        enforce_own_reseller(request, reseller_id)
        self._reject_office_only_pricing(request, serializer.validated_data)

        result = OrderContentService.create_order_with_content_and_crates(
            created_by=getattr(request, "user", None),
            **serializer.validated_data,
        )
        return Response(result)

    @extend_schema(
        description="Update order content amount and related fields.",
        responses={
            200: OrderContentItemSerializer,
            409: ErrorResponseSerializer,
        },
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Enforce ownership: get_object() honours the scoped get_queryset() and
        # raises 404 for rows the caller may not access.
        self.get_object()
        order_content_id = kwargs.get("pk")
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self._reject_office_only_pricing(request, serializer.validated_data)

        result = OrderContentService.update_order_content(
            order_content_id=order_content_id,
            amount=serializer.validated_data.get("amount"),
            **{k: v for k, v in serializer.validated_data.items() if k != "amount"},
        )
        return Response(result)

    @staticmethod
    def _reject_office_only_pricing(request: Request, validated_data: dict) -> None:
        """Non-privileged (customer) callers may not set price/rabatt/tax_rate/
        is_finalized on an order content — those are resolved server-side.
        Office/staff bypass. Mirrors ResellerViewSet's office_only_fields guard.
        """
        if is_privileged(request):
            return
        offending = _ORDER_CONTENT_OFFICE_ONLY_FIELDS & set(validated_data)
        if offending:
            raise ForbiddenError(
                "Only office staff may set order pricing fields.",
            )

    @extend_schema(
        description="Delete order content (and its parent order if empty).",
        responses={
            200: inline_serializer(
                name="OrderContentDeleteResponse",
                fields={
                    "message": drf_serializers.CharField(),
                    "order_deleted": drf_serializers.BooleanField(),
                },
            )
        },
    )
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Enforce ownership via scoped get_queryset().
        self.get_object()
        order_content_id = kwargs.get("pk")

        result = OrderContentService.delete_order_content(order_content_id)
        return Response(
            {
                "message": "Order content deleted successfully",
                "order_deleted": result["order_deleted"],
            },
            status=status.HTTP_200_OK,
        )


class OfferViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaffOrCustomer
    write_permission = IsOffice
    serializer_class = OfferSerializer

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_offer_group_parameter(),
            get_reseller_parameter(),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Offer]:
        queryset = Offer.objects.all()

        params = validate_query_params(
            self.request,
            optional=["year", "delivery_week", "offer_group", "reseller"],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        offer_group = params["offer_group"]
        reseller_id = params["reseller"]

        # Object scoping (IDOR): the ``amount_ordered`` annotation exposes a
        # reseller's per-article order volume. A non-privileged caller (customer)
        # may only see their OWN reseller's totals — reject a ?reseller= pointing
        # at a peer in the same offer_group, and force their own reseller when the
        # param is omitted (else the annotation sums the whole group's orders).
        # Mirrors OrderContentViewSet.list; privileged staff bypass.
        if not is_privileged(self.request):
            own_id = own_reseller_id(self.request)
            if own_id is None:
                return Offer.objects.none()
            if reseller_id and str(reseller_id) != own_id:
                raise ForbiddenError("Cannot view offers for another reseller.")
            reseller_id = own_id

        if year is not None:
            queryset = queryset.filter(year=year)
        if delivery_week is not None:
            queryset = queryset.filter(delivery_week=delivery_week)

        if reseller_id is not None:

            reseller_obj = get_or_404(
                Reseller, reseller_id, "Reseller", error_cls=ResellerNotFound
            )
            offer_group = reseller_obj.offer_group
            if offer_group is not None:
                queryset = queryset.filter(offer_group=offer_group)
            else:
                queryset = Offer.objects.none()

        if offer_group is not None:
            queryset = queryset.filter(offer_group=offer_group)

        queryset = OfferService.annotate_offers_with_ordered_amounts(
            queryset=queryset,
            year=year,
            delivery_week=delivery_week,
            reseller=reseller_id,
        )

        queryset = queryset.annotate(
            share_article_name=F("share_article__name"),
            forecast_exists=Exists(
                Forecast.objects.filter(
                    year=OuterRef("year"),
                    delivery_week=OuterRef("delivery_week"),
                    share_article=OuterRef("share_article"),
                    unit=OuterRef("unit"),
                    size=OuterRef("size"),
                )
            ),
        )
        queryset = scope_to_offer_group(queryset, self.request, path="offer_group_id")
        # ``OfferSerializer.organic_status`` reads ``share_article.organic_status``
        # per row — select_related the FK so the list isn't N+1 (the
        # ``share_article_name`` annotation only pulls the name column via JOIN,
        # it does not populate the related instance). Locked by
        # ``test_query_count_locks.test_offers_list_is_scale_invariant``.
        return queryset.select_related("share_article").order_by("share_article_name")


class OfferGroupViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = OfferGroupSerializer

    def get_queryset(self) -> QuerySet[OfferGroup]:
        return OfferGroup.objects.annotate(
            reseller_names=StringAgg(
                "reseller__contact__company_name",
                delimiter=", ",
                distinct=True,
                order_by="reseller__contact__company_name",
            ),
            reseller_count=Count("reseller", distinct=True),
        ).order_by("number")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # The seeded default offer group is protected (see OfferGroup.is_default)
        # — it must always persist as the new-reseller default.
        if self.get_object().is_default:
            raise OfferGroupCannotDeleteDefault(
                "The default offer group cannot be deleted."
            )
        return super().destroy(request, *args, **kwargs)


class CrateOrderContentViewSet(RolePermissionsMixin, viewsets.ViewSet):
    read_permission = IsStaffOrCustomer
    write_permission = IsOfficeOrCustomer
    serializer_class = CrateOrderContentSerializer

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=True),
            get_reseller_parameter(required=True),
        ],
        description="Get aggregated crate summary for a period and reseller.",
        responses={200: CrateOrderSummarySerializer(many=True)},
    )
    def list(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "day_number", "reseller"],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]
        reseller = params["reseller"]

        enforce_own_reseller(request, reseller)

        crates_summary = CrateOrderContentService.get_crates_summary_for_period(
            year=year,
            delivery_week=delivery_week,
            day_number=day_number,
            reseller=reseller,
        )

        return Response(CrateOrderSummarySerializer(crates_summary, many=True).data)

    @extend_schema(
        request=CrateOrderContentCreateRequestSerializer,
        description="Create a crate order content record.",
        responses={
            201: CrateOrderSummarySerializer,
            404: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request) -> Response:
        # Validate the body so a non-numeric / missing ``amount`` or period int
        # yields a clean 400 instead of a bare ValueError / IntegrityError →
        # HTTP 500 once it reaches the Order / CrateOrderContent integer columns.
        serializer = CrateOrderContentCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        enforce_own_reseller(request, data["reseller"])
        result = CrateOrderContentService.create_crate_order_content(
            crate_type_id=data["crate_type"],
            amount=data["amount"],
            year=data["year"],
            delivery_week=data["delivery_week"],
            day_number=data["day_number"],
            reseller=data["reseller"],
            price_per_unit=data.get("price_per_unit"),
            rabatt=data.get("rabatt"),
            note=data.get("note"),
            created_by=getattr(request, "user", None),
        )
        return Response(
            CrateOrderSummarySerializer(result).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=CrateOrderContentUpdateRequestSerializer,
        description="Partially update crate order content records by crate type.",
        responses={
            200: PolymorphicProxySerializer(
                component_name="CrateOrderContentPartialUpdateResponse",
                # Non-empty path → the serialized summary row; all-deleted path
                # (the updated amount zeroed every crate in the period) → the
                # ``{"success": true}`` acknowledgement envelope.
                serializers=[
                    CrateOrderSummarySerializer,
                    inline_serializer(
                        name="CrateOrderContentDeletedAck",
                        fields={"success": drf_serializers.BooleanField()},
                    ),
                ],
                resource_type_field_name=None,
            )
        },
    )
    def partial_update(self, request: Request, pk: str = None) -> Response:
        # Period (year/week/day_number/reseller) is required to scope the rows;
        # the mutable fields are optional (PATCH). Validation keeps malformed
        # period ints off the 500 path, same as create above.
        serializer = CrateOrderContentUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        enforce_own_reseller(request, data["reseller"])
        result = CrateOrderContentService.update_crate_order_content_by_crate_type(
            crate_type_id=pk,
            year=data["year"],
            delivery_week=data["delivery_week"],
            day_number=data["day_number"],
            reseller=data["reseller"],
            update_data=data,
        )
        # The service returns {} when the update left no crate rows in the
        # period (e.g. the new amount zeroed every crate of this type). Return a
        # small acknowledgement envelope instead of an empty body so the schema
        # stays honest and the frontend table still receives a truthy payload.
        if not result:
            return Response({"success": True})
        return Response(CrateOrderSummarySerializer(result).data)

    @extend_schema(
        description="Delete crate order content records by crate type.",
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=True),
            get_reseller_parameter(required=True),
            get_order_id_parameter(required=True),
        ],
    )
    def destroy(self, request: Request, pk: str = None) -> Response:
        # Validate through the central catalogue (mirrors ``list`` above) so a
        # non-numeric ``?year=abc`` yields a clean InvalidQueryParam (400,
        # field="year") instead of a bare ValueError → HTTP 500 from the
        # service's integer ORM lookups, and so runtime matches the required-int
        # @extend_schema contract.
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "day_number", "reseller", "order_id"],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]
        reseller = params["reseller"]
        order_id = params["order_id"]

        enforce_own_reseller(request, reseller)

        deleted = CrateOrderContentService.delete_crate_order_content_by_crate_type(
            crate_type_id=pk,
            year=year,
            delivery_week=delivery_week,
            day_number=day_number,
            reseller=reseller,
            order_id=order_id,
            # Bind the delete to the caller's own reseller (privileged roles
            # bypass) so an omitted or forged ``reseller`` can't reach another
            # reseller's content via the reseller-blind order_id branch
            # (cross-reseller IDOR). Same helper OrderContentViewSet scopes with.
            scope=lambda qs: scope_to_reseller(qs, request, path="order__reseller"),
        )
        if deleted:
            return Response(status=status.HTTP_204_NO_CONTENT)
        raise NotFoundError(
            "Crate order content not found.",
            code="crate_order_content.not_found",
        )


class InvoiceResellerViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsOfficeOrCustomer
    write_permission = IsOffice
    pagination_class = OptionalLimitOffsetPagination
    # N+1 lock: every join below is consumed by the serializer.
    #   * ``reseller__contact``        — six get_reseller_* methods
    #   * ``created_by``               — get_created_by_name
    #   * ``cancels_invoice``          — get_cancels_invoice_number
    #   * Prefetch("items", select_related("share_article",
    #             "offer__share_article"),
    #             prefetch_related("delivery_note_contents__delivery_note"))
    #                                  — InvoiceResellerContentSerializer's
    #                                    get_share_article_name reads
    #                                    obj.share_article / obj.offer.
    #                                    share_article; outer serializer's
    #                                    get_corresponding_delivery_notes
    #                                    walks items → delivery_note_contents
    #                                    → delivery_note.
    #   * crate_items__crate_type      — get_crate_items aggregates the
    #                                    prefetched ``obj.crate_items.all()``
    #                                    in Python (do NOT issue a fresh
    #                                    ``.objects.filter(invoice=obj)``
    #                                    here — that would defeat the
    #                                    prefetch).
    # Locked by apps/payments/tests/test_query_count_locks.py.
    queryset = (
        InvoiceReseller.objects.all()
        .select_related(
            "reseller__contact",
            "created_by",
            "cancels_invoice",
        )
        .prefetch_related(
            Prefetch(
                "items",
                queryset=(
                    InvoiceResellerContent.objects.select_related(
                        "share_article", "offer__share_article"
                    )
                    .prefetch_related("delivery_note_contents__delivery_note")
                    .order_by("share_article__name")
                ),
            ),
            "crate_items__crate_type",
            # get_corresponding_delivery_notes walks the crate-line provenance
            # M2M for crate-only invoices — prefetch it so that stays query-free.
            "crate_items__crate_delivery_note_contents__delivery_note",
        )
    )
    serializer_class = InvoiceResellerSerializer

    def get_queryset(self):
        return scope_to_reseller(super().get_queryset(), self.request, path="reseller")

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "xml_file": {"type": "string", "format": "binary"},
                },
            }
        },
        responses={
            200: inline_serializer(
                name="InvoiceUploadPdfResponse",
                fields={
                    # ``invoice.file.url`` / ``invoice.xml_file.url`` — media
                    # URLs. ``xml_file`` is only present when an XML companion
                    # was uploaded alongside the PDF.
                    "file": drf_serializers.URLField(),
                    "xml_file": drf_serializers.URLField(required=False),
                },
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="upload_pdf")
    def upload_pdf(self, request: Request, pk: str | None = None) -> Response:
        invoice = self.get_object()
        uploaded_file, uploaded_xml = validate_finalized_pdf_upload(
            invoice, request, doc_label="Invoice", allow_xml=True
        )

        from django.db import transaction
        from django.utils import timezone

        from apps.commissioning.models import InvoiceReseller
        from apps.commissioning.services.invoice_service import (
            InvoiceService as _InvoiceServiceForSend,
        )

        # EML-6/7: lock the invoice row and decide + STAMP the send markers inside
        # ONE transaction, so two concurrent upload_pdf calls (double-click / retry
        # storm) can't both observe "not yet sent" and both fire — the second
        # blocks on the lock, then reads the marker as already set and skips. The
        # auto-send still fires exactly once, on the first successful upload;
        # re-send is a separate explicit action. Trade-off: if the SMTP send later
        # fails the marker is already set (no auto-retry on re-upload) — acceptable,
        # it converts a user-visible double-send into a recoverable missed send.
        with transaction.atomic():
            locked = InvoiceReseller.objects.select_for_update().get(pk=invoice.pk)

            # EML-2 interplay: only stamp + schedule the reseller send when the
            # reseller actually wants invoice email — else we'd mark a paper-only
            # invoice "sent" without sending. send_to_reseller re-checks the flag.
            channel_on = bool(getattr(locked.reseller, "invoice_via_email", True))
            should_send_to_reseller = (
                not locked.has_been_sent_to_reseller and channel_on
            )
            should_send_to_accounting = not locked.has_been_sent_to_accounting

            locked.file = uploaded_file
            update_fields = ["file"]
            if uploaded_xml:
                locked.xml_file = uploaded_xml
                update_fields.append("xml_file")

            now = timezone.now()
            if should_send_to_reseller:
                locked.has_been_sent_to_reseller_at = now
                update_fields.append("has_been_sent_to_reseller_at")
            if should_send_to_accounting:
                locked.has_been_sent_to_accounting_at = now
                update_fields.append("has_been_sent_to_accounting_at")
            locked.save(update_fields=update_fields)

            # ``on_commit`` so the SMTP send fires only after the save lands.
            if should_send_to_reseller:
                transaction.on_commit(
                    lambda inv=locked: _InvoiceServiceForSend.send_to_reseller(inv)
                )
            if should_send_to_accounting:
                transaction.on_commit(
                    lambda inv=locked: _InvoiceServiceForSend.send_to_accounting(inv)
                )

        result = {"file": locked.file.url}
        if locked.xml_file:
            result["xml_file"] = locked.xml_file.url
        return Response(result, status=status.HTTP_200_OK)

    @extend_schema(
        request=CreateStornoRequestSerializer,
        responses={
            201: InvoiceResellerSerializer,
            400: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"], url_path="create_storno")
    def create_storno(self, request: Request, pk: str | None = None) -> Response:
        invoice = self.get_object()
        serializer = CreateStornoRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["reason"]
        # A model ``full_clean()`` failure inside ``create_storno`` raises a
        # Django ``ValidationError``, which ``core.exception_handler`` already
        # renders as a canonical 400 ``{code, message}``. (The previous manual
        # ``except`` read ``e.message`` — absent on dict-form ValidationErrors —
        # and turned that 400 into a 500.) Domain errors (JasminError) keep
        # propagating with their own status as before.
        storno = InvoiceService.create_storno(invoice, reason=reason, user=request.user)
        return Response(
            self.get_serializer(storno).data, status=status.HTTP_201_CREATED
        )


class InvoiceResellerContentViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsOfficeOrCustomer
    write_permission = IsOffice
    serializer_class = InvoiceResellerContentSerializer

    @extend_schema(parameters=[get_invoice_id_parameter(required=True)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[InvoiceResellerContent]:
        # On ``list`` the ``invoice_id`` filter is REQUIRED — a bare GET would
        # otherwise return every content row in the tenant. Detail routes
        # (retrieve / update / destroy) address a single row by pk and don't
        # carry the query param, so the filter is optional there.
        required = ["invoice_id"] if self.action == "list" else []
        optional = [] if self.action == "list" else ["invoice_id"]
        params = validate_query_params(
            self.request, required=required, optional=optional
        )
        queryset = (
            InvoiceResellerContent.objects
            # N+1 lock: the serializer's ShareArticleResolutionMixin reads
            # ``obj.share_article`` / ``obj.offer.share_article`` and
            # DifferenceTrackingMixin._diff_disabled reads ``obj.invoice`` per
            # row; ``fields="__all__"`` also serializes the
            # ``delivery_note_contents`` M2M (one query/row without a prefetch).
            .select_related("share_article", "offer__share_article", "invoice")
            .prefetch_related("delivery_note_contents")
            .order_by("share_article__name")
        )
        invoice_id = params["invoice_id"]
        if invoice_id:
            queryset = queryset.filter(invoice_id=invoice_id)
        return scope_to_reseller(queryset, self.request, path="invoice__reseller")


class DeliveryNoteResellerViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsOfficeOrCustomer
    write_permission = IsOffice
    # N+1 lock: every join below is consumed by the serializer.
    #   * ``order__reseller__contact`` — six get_reseller_* methods +
    #                                    get_order_number / _date / _prefix
    #   * ``created_by``               — get_created_by_name
    #   * Prefetch("items", select_related("share_article",
    #             "offer__share_article"))
    #                                  — DeliveryNoteResellerContentSerializer's
    #                                    get_share_article_name reads
    #                                    obj.share_article / obj.offer.
    #                                    share_article.
    #   * crate_items__crate_type      — get_crate_items aggregates the
    #                                    prefetched ``obj.crate_items.all()``
    #                                    in Python.
    # Locked by apps/payments/tests/test_query_count_locks.py.
    queryset = (
        DeliveryNoteReseller.objects.all()
        .select_related(
            "order__reseller__contact",
            "created_by",
        )
        .prefetch_related(
            Prefetch(
                "items",
                queryset=DeliveryNoteContent.objects.select_related(
                    "share_article", "offer__share_article"
                ).order_by("share_article__name"),
            ),
            "crate_items__crate_type",
        )
    )
    serializer_class = DeliveryNoteResellerSerializer

    def get_queryset(self):
        return scope_to_reseller(
            super().get_queryset(), self.request, path="order__reseller"
        )

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                },
            }
        },
        responses={
            200: inline_serializer(
                name="DeliveryNoteUploadPdfResponse",
                # ``delivery_note.file.url`` — the uploaded PDF's media URL.
                fields={"file": drf_serializers.URLField()},
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="upload_pdf")
    def upload_pdf(self, request: Request, pk: str | None = None) -> Response:
        delivery_note = self.get_object()
        uploaded_file, _ = validate_finalized_pdf_upload(
            delivery_note, request, doc_label="Delivery note"
        )
        delivery_note.file = uploaded_file
        delivery_note.save(update_fields=["file"])
        return Response({"file": delivery_note.file.url}, status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="DeliveryNoteSendToResellerResponse",
                fields={
                    "sent": drf_serializers.BooleanField(),
                    # ISO datetime of the send; null on the ``sent: false`` path
                    # (SMTP rejected the message, timestamp never set).
                    "has_been_sent_to_reseller_at": drf_serializers.DateTimeField(
                        allow_null=True
                    ),
                },
            ),
            400: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"], url_path="send_to_reseller")
    def send_to_reseller(self, request: Request, pk: str | None = None) -> Response:
        """Manually send the DN PDF to the reseller's invoice_email.

        Mirrors the InvoiceService.send_to_reseller flow but is
        explicit-trigger-only (the office decides per-DN). Returns
        200 with ``sent: True`` when the send succeeded, 400 with an
        error message on a precondition failure (not finalized, no
        PDF, no reseller email), or 200 with ``sent: False`` when the
        SMTP layer rejected the message — see the EmailLog row for
        the actual error string in the latter case.
        """
        from apps.commissioning.services.delivery_note_service import (
            DeliveryNoteService,
        )

        delivery_note = self.get_object()

        if not delivery_note.is_finalized:
            raise DocumentNotFinalized(
                "Delivery note must be finalized before sending."
            )
        if not delivery_note.file:
            raise DocumentPdfMissing(
                "PDF not yet uploaded — finalize and upload first."
            )

        reseller = delivery_note.order.reseller if delivery_note.order else None
        if not reseller or not reseller.invoice_email:
            raise ResellerEmailMissing("Reseller has no invoice_email configured.")

        sent = DeliveryNoteService.send_to_reseller(delivery_note)
        # Refresh from DB to pick up the timestamp if the service
        # flipped it. ``sent`` already reflects success-of-send; the
        # timestamp is just for the response payload.
        delivery_note.refresh_from_db(fields=["has_been_sent_to_reseller_at"])
        return Response(
            {
                "sent": bool(sent),
                "has_been_sent_to_reseller_at": (
                    delivery_note.has_been_sent_to_reseller_at.isoformat()
                    if delivery_note.has_been_sent_to_reseller_at
                    else None
                ),
            },
            status=status.HTTP_200_OK,
        )


class DeliveryNoteResellerContentViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsOfficeOrCustomer
    write_permission = IsOffice
    serializer_class = DeliveryNoteResellerContentSerializer

    @extend_schema(parameters=[get_delivery_note_id_parameter(required=True)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[DeliveryNoteContent]:
        # On ``list`` the ``delivery_note_id`` filter is REQUIRED — a bare GET
        # would otherwise return every content row in the tenant. Detail routes
        # (retrieve / update / destroy) address a single row by pk and don't
        # carry the query param, so the filter is optional there.
        required = ["delivery_note_id"] if self.action == "list" else []
        optional = [] if self.action == "list" else ["delivery_note_id"]
        params = validate_query_params(
            self.request, required=required, optional=optional
        )
        queryset = (
            DeliveryNoteContent.objects
            # N+1 lock: the serializer's ShareArticleResolutionMixin reads
            # ``obj.share_article`` and ``obj.offer.share_article`` per row.
            .select_related("share_article", "offer__share_article").order_by(
                "share_article__name"
            )
        )
        delivery_note_id = params["delivery_note_id"]
        if delivery_note_id:
            queryset = queryset.filter(delivery_note_id=delivery_note_id)
        return scope_to_reseller(
            queryset, self.request, path="delivery_note__order__reseller"
        )


class CommissioningListResellersViewSet(RolePermissionsMixin, viewsets.ViewSet):
    """ViewSet for the RESELLER commissioning list (pick list grouped by
    reseller) — distinct from the commissioning-list PACKING view."""

    read_permission = IsStaff
    write_permission = IsOffice

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=True),
        ],
        description="Get commissioning list grouped by reseller for a given week and day_number.",
        responses={200: CommissioningListResellersEntry(many=True)},
    )
    def list(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "day_number"],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]

        orders = (
            Order.objects.filter(
                year=year,
                delivery_week=delivery_week,
                day_number=day_number,
            )
            .select_related("reseller__contact")
            .prefetch_related(
                Prefetch(
                    "ordercontent_set",
                    queryset=OrderContent.objects.select_related(
                        "share_article", "offer__share_article"
                    ).order_by("share_article__name"),
                )
            )
        )

        result = [_build_commissioning_resellers_entry(order) for order in orders]
        return Response(result)


def _build_commissioning_resellers_entry(order: Order) -> dict[str, Any]:
    """Build a single commissioning list entry from an order."""
    contact = order.reseller.contact
    return {
        "id": str(order.reseller.id),
        "name": contact.company_name if contact else "",
        "address": contact.address if contact else "",
        "order": {
            "id": str(order.id),
            "number": order.display_number,
            "note": order.note or "",
            "contents": [
                _build_content_entry(content)
                for content in order.ordercontent_set.all()
            ],
        },
    }


def _build_content_entry(content: OrderContent) -> dict[str, Any]:
    """Build a single order content entry for the commissioning list.

    ``share_article`` and ``amount_per_pu`` are delegated to
    ``OrderContent.resolve_*`` so this endpoint and every other reader
    (line pricing, serializers, snapshot/movement creation) agree on the
    fallback chain. ``unit`` and ``size`` are read directly off the row
    — they are required OrderContent columns, not derived.
    """
    share_article = content.resolve_share_article()
    return {
        "id": str(content.id),
        "share_article_id": str(share_article.id) if share_article else None,
        "share_article_name": share_article.name if share_article else "",
        "amount": float(content.amount) if content.amount else 0,
        "amount_per_pu": float(content.resolve_amount_per_pu()),
        "size": content.size,
        "unit": content.unit,
        "sort": content.sort,
        "note": content.note or "",
    }


class OrganicCertificateViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """CRUD for a reseller's time-bound organic certificates (office-managed).

    Drives the ListSellers certificate modal; filter the list by ``?reseller=``.
    """

    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = OrganicCertificateSerializer

    @extend_schema(parameters=[get_reseller_parameter()])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[OrganicCertificate]:
        queryset = OrganicCertificate.objects.select_related("reseller").order_by(
            "-valid_from"
        )
        params = validate_query_params(self.request, optional=["reseller"])
        reseller = params["reseller"]
        if reseller is not None:
            queryset = queryset.filter(reseller_id=reseller)
        return queryset
