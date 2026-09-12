from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.authz.permissions import (
    IsOffice,
    IsStaff,
    IsStaffOrMember,
    RolePermissionsMixin,
)
from apps.authz.scoping import enforce_owner
from apps.shared.money import round_money
from apps.shared.openapi_params import catalogue_parameter
from apps.shared.pii_logging import PIIReadLoggingMixin
from apps.shared.query_params import (
    ParamSpec,
    validate_choice_param,
    validate_query_params,
)
from core.errors import InvalidQueryParam
from core.pagination import OptionalLimitOffsetPagination
from core.serializers import ErrorResponseSerializer

from .constants import OPEN_CHARGE_STATUSES, BillingRunStatus, ChargeStatus
from .errors import BillingRunInvalidCollectionDate, BillingRunNotDraft
from .models import BillingProfile, BillingRun, ChargeSchedule
from .scoping import scope_to_member
from .serializers import (
    BillingProfileMemberSerializer,
    BillingProfileSerializer,
    BillingRunSerializer,
    ChargeScheduleMonthlyIncomeSerializer,
    ChargeScheduleSerializer,
    CreateBillingRunSerializer,
    SepaMandateStatusSerializer,
)
from .services import BillingRunService, ChargeScheduleService

# The typed query params the payments read endpoints accept (validated via
# the shared catalogue machinery; a bad or out-of-range value 400s).
PARAM_CATALOGUE: dict[str, ParamSpec] = {
    "year": ParamSpec("int", min_value=1900, max_value=2100),
    "month": ParamSpec("int", min_value=1, max_value=12),
    "date_from": ParamSpec("date"),
    "date_to": ParamSpec("date"),
    # Filter-only params: declared so the OpenAPI schema derives from this
    # catalogue too, rather than being re-typed inline at each endpoint.
    "member": ParamSpec("str"),
    "status": ParamSpec("str"),
}

# "Billed" income = every charge that represents owed revenue not written off:
# the open ones (PLANNED / ISSUED / PARTIAL) plus the collected ones (PAID).
# WAIVED (forgiven) and FAILED (returned by the bank) are excluded.
BILLED_INCOME_STATUSES = (*OPEN_CHARGE_STATUSES, ChargeStatus.PAID)


@extend_schema_view(
    list=extend_schema(
        tags=["Payments — Billing profiles"],
        summary="List billing profiles",
        description=(
            "Members see only their own billing profile. "
            "Staff (Office) sees every member's profile."
        ),
        parameters=[
            catalogue_parameter(
                "member",
                PARAM_CATALOGUE,
                required=False,
                description="Filter by member id (staff only).",
            ),
        ],
    ),
    retrieve=extend_schema(
        tags=["Payments — Billing profiles"],
        summary="Retrieve a single billing profile",
    ),
    create=extend_schema(
        tags=["Payments — Billing profiles"],
        summary="Create a billing profile (Office only)",
    ),
    update=extend_schema(
        tags=["Payments — Billing profiles"],
        summary="Replace a billing profile (Office only)",
    ),
    partial_update=extend_schema(
        tags=["Payments — Billing profiles"],
        summary="Patch a billing profile (Office only)",
    ),
    destroy=extend_schema(
        tags=["Payments — Billing profiles"],
        summary="Delete a billing profile (Office only)",
    ),
)
class BillingProfileViewSet(
    PIIReadLoggingMixin, RolePermissionsMixin, viewsets.ModelViewSet
):
    """Members can read their own profile. Staff (Office) can manage all.

    Edits that touch any of the SEPA-mandate fields require step-up
    auth, because rewriting IBAN / mandate-reference could redirect a
    member's direct-debit money to an attacker-controlled account.
    ``is_active`` is included too (TXN-4): toggling it has direct payment
    consequences — it gates ``create_run`` eligibility and re-enables /
    disables collection on the mandate — so flipping it must not be a
    silent, un-stepped-up PATCH. Only ``notes`` PATCHes without prompting.
    """

    read_permission = IsStaffOrMember
    write_permission = IsOffice
    serializer_class = BillingProfileSerializer

    _SEPA_SENSITIVE_FIELDS = (
        "iban",
        "account_holder",
        "sepa_mandate_reference",
        "sepa_mandate_signed_at",
        # TXN-4: activating / deactivating a mandate is payment-relevant
        # (eligibility + collection), so it requires step-up like the mandate
        # fields — not a benign toggle.
        "is_active",
        # Switching ``payment_method`` INTO SEPA_DIRECT_DEBIT re-arms direct-debit
        # collection — and, on a profile that was moved OFF SEPA while keeping its
        # mandate columns (e.g. an Art. 7(3) consent revoke that only flips the
        # method), silently resurrects a usable mandate (``is_sepa_ready`` -> True,
        # next run debits the member). That is exactly the payment-relevant toggle
        # ``is_active`` is gated for, so gate it too. ``requires_step_up_for_fields``
        # only fires on an actual value change, so unrelated PATCHes are untouched.
        "payment_method",
    )

    # Fields that are sensitive only when TOGGLED on an EXISTING mandate — on
    # create there is no mandate to hijack and both are always present in the
    # payload (model defaults), so gating every create on step-up would be
    # friction without benefit. (A SEPA create still steps up via ``iban`` etc.)
    _CREATE_EXEMPT_STEP_UP_FIELDS = ("is_active", "payment_method")

    def get_permissions(self):
        from apps.accounts.permissions import requires_step_up_for_fields

        perms = super().get_permissions()
        if self.action in {"create", "update", "partial_update"}:
            fields = self._SEPA_SENSITIVE_FIELDS
            if self.action == "create":
                fields = tuple(
                    f for f in fields if f not in self._CREATE_EXEMPT_STEP_UP_FIELDS
                )
            perms.append(requires_step_up_for_fields(*fields)())
        return perms

    def get_serializer_class(self):
        # ``read_permission = IsStaffOrMember`` lets a member GET their OWN
        # profile (queryset scoped to it). The office serializer exposes the
        # internal ``notes`` field — ``read_only_fields`` guards writes, not
        # reads — so serve member-role callers the narrowed serializer on the
        # read actions. Staff keep the full serializer; writes are office-only;
        # anonymous / schema-generation fall through to the office shape.
        request = getattr(self, "request", None)
        if (
            self.action in {"list", "retrieve"}
            and request is not None
            and getattr(request, "user", None)
            and request.user.is_authenticated
            and not IsStaff().has_permission(request, self)
        ):
            return BillingProfileMemberSerializer
        return BillingProfileSerializer

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        # SEC-1: unlike the name/member_number/status lists that PIIReadLoggingMixin
        # deliberately skips, the billing-profile list decrypts the IBAN +
        # account holder into the payload. A bulk read of every member's bank
        # identifier must leave an Art. 5(2) accountability trail, so log it
        # explicitly here (the mixin only auto-logs the detail retrieve()).
        if status.is_success(response.status_code):
            member = request.query_params.get("member")
            self._log_pii_list_read(
                request, f"list(member={member})" if member else "list(all)"
            )
        return response

    def get_queryset(self):
        qs = BillingProfile.objects.select_related("member").all()
        qs = scope_to_member(qs, self.request, path="member")
        # Staff can narrow to one member (members are already self-scoped, so
        # the param is a redundant no-op for them). Lets callers that only need
        # one member's mandate fetch + decrypt a single row instead of the whole
        # tenant, and keeps the PII-read audit line scoped (``list(member=...)``).
        member_id = self.request.query_params.get("member")
        if member_id:
            qs = qs.filter(member_id=member_id)
        return qs

    @extend_schema(
        summary="Per-member SEPA mandate status (no bank identifiers)",
        description=(
            "Lightweight mandate-status list for overview tables (e.g. the Abos "
            "SEPA column): whether each member has an active, usable SEPA "
            "mandate (``has_active_sepa_mandate`` mirrors ``is_sepa_ready``) "
            "plus the mandate reference and the signed / paper-received dates. "
            "Excludes IBAN / account holder, so a bulk read neither decrypts "
            "nor exposes bank PII and does NOT emit the SEC-1 bank-identifier "
            "audit line. Office-only (mapped to ``write_permission`` — it is "
            "not one of the member-readable ``_READ_ACTIONS``)."
        ),
        responses={200: SepaMandateStatusSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="mandate_status")
    def mandate_status(self, request, *args, **kwargs):
        """Return each member's SEPA mandate status, without bank identifiers."""
        # No ``?member`` scoping: office-only + no PII, so the whole-tenant list
        # is the intended payload. ``member_id`` is a local column (no join), so
        # only the name ordering touches the member table — no N+1.
        profiles = BillingProfile.objects.order_by(
            "member__last_name", "member__first_name"
        )
        data = SepaMandateStatusSerializer(profiles, many=True).data
        return Response(data)


@extend_schema_view(
    list=extend_schema(
        tags=["Payments — Charge schedule"],
        summary="List charge schedule rows",
        description=(
            "Read-only ledger of planned/issued/paid charges. "
            "Members only see their own rows; staff sees all."
        ),
        parameters=[
            catalogue_parameter(
                "member",
                PARAM_CATALOGUE,
                required=False,
                description="Filter by member id (staff only).",
            ),
            catalogue_parameter(
                "status",
                PARAM_CATALOGUE,
                required=False,
                description="Filter by ChargeStatus value (PLANNED, ISSUED, ...).",
            ),
            catalogue_parameter(
                "year",
                PARAM_CATALOGUE,
                required=False,
                description="Filter by due_date year.",
            ),
            catalogue_parameter(
                "month",
                PARAM_CATALOGUE,
                required=False,
                description="Filter by due_date month (1–12). Requires `year`.",
            ),
        ],
        responses={
            200: ChargeScheduleSerializer(many=True),
            400: ErrorResponseSerializer,
        },
    ),
    retrieve=extend_schema(
        tags=["Payments — Charge schedule"],
        summary="Retrieve a single charge",
    ),
)
class ChargeScheduleViewSet(RolePermissionsMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only ledger view.

    Members see only their own rows. Staff sees all.
    Mutations only happen via the regenerator service or BillingRunService.
    """

    pagination_class = OptionalLimitOffsetPagination

    read_permission = IsStaffOrMember
    write_permission = IsOffice  # unused; ReadOnly viewset
    serializer_class = ChargeScheduleSerializer

    def get_queryset(self):
        # N+1 lock: ChargeScheduleSerializer.get_subscription_label()
        # walks subscription -> share_type_variation -> share_type. Without
        # joining all three, list payloads issue ~3 extra queries per row.
        # Locked by apps/payments/tests/test_query_count_locks.py.
        qs = ChargeSchedule.objects.select_related(
            "member",
            "subscription",
            "subscription__share_type_variation",
            "subscription__share_type_variation__share_type",
            "billing_run",
        ).all()
        params = self.request.query_params
        member_id = params.get("member")
        status_param = params.get("status")
        if member_id:
            # TEN-2: a non-privileged caller may query only their OWN charges; a
            # foreign ``?member=`` is a 403, not a silent empty set. Privileged
            # roles (office/admin/management) bypass. ``scope_to_member`` below
            # is the defense-in-depth backstop.
            enforce_owner(self.request, member_id, user_attr="member_profile")
            qs = qs.filter(member_id=member_id)
        if status_param:
            validate_choice_param(status_param, ChargeStatus.values, "status")
            qs = qs.filter(status=status_param)
        # ``month`` alone is meaningless (it would match that month across ALL
        # years); the documented contract is "month requires year" — enforce it.
        if params.get("month") and not params.get("year"):
            raise InvalidQueryParam(
                "`month` requires `year`.",
                field="month",
                details={"month": params.get("month"), "year": params.get("year")},
            )
        # Catalogue-validated ints: a bad or out-of-range ``year``/``month``
        # 400s instead of silently returning every charge ever.
        validated = validate_query_params(
            self.request, PARAM_CATALOGUE, optional=["year", "month"]
        )
        if validated["year"] is not None:
            qs = qs.filter(due_date__year=validated["year"])
        if validated["month"] is not None:
            qs = qs.filter(due_date__month=validated["month"])
        return scope_to_member(qs, self.request, path="member")

    @extend_schema(
        tags=["Payments — Charge schedule"],
        summary="Regenerate planned charges (Office only)",
        description=(
            "Re-runs the schedule generator for every active subscription in "
            "the current tenant. Idempotent. Only PLANNED rows are touched."
        ),
        request=None,
        responses={
            200: inline_serializer(
                name="RegenerateChargesResponse",
                fields={
                    "regenerated_subscriptions": drf_serializers.IntegerField(),
                    "details": drf_serializers.DictField(
                        child=drf_serializers.IntegerField(),
                        help_text="subscription_id -> created PLANNED rows",
                    ),
                },
            ),
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["post"], permission_classes=[IsOffice])
    def regenerate(self, request):
        """Regenerate PLANNED charges for all subscriptions (staff only)."""
        result = ChargeScheduleService.regenerate_all()
        return Response({"regenerated_subscriptions": len(result), "details": result})

    @extend_schema(
        tags=["Payments — Charge schedule"],
        summary="Monthly billed income (Office only)",
        description=(
            "Sums the expected amount of every billed charge "
            "(PLANNED / ISSUED / PARTIAL / PAID — excludes WAIVED and FAILED) "
            "per due-date month within the inclusive [date_from, date_to] "
            "window. Powers the DashboardAbos income chart."
        ),
        parameters=[
            catalogue_parameter(
                "date_from",
                PARAM_CATALOGUE,
                required=True,
                description="Inclusive start (YYYY-MM-DD), matched on due_date.",
            ),
            catalogue_parameter(
                "date_to",
                PARAM_CATALOGUE,
                required=True,
                description="Inclusive end (YYYY-MM-DD), matched on due_date.",
            ),
        ],
        responses={
            200: ChargeScheduleMonthlyIncomeSerializer(many=True),
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="income_by_month",
        permission_classes=[IsOffice],
    )
    def income_by_month(self, request):
        """Billed income per due-date month within [date_from, date_to]."""
        params = validate_query_params(
            request, PARAM_CATALOGUE, required=["date_from", "date_to"]
        )
        date_from = params["date_from"]
        date_to = params["date_to"]
        if date_from > date_to:
            raise InvalidQueryParam(
                "`date_from` must be on or before `date_to`.",
                field="date_from",
                details={"date_from": str(date_from), "date_to": str(date_to)},
            )
        # One GROUP BY over the ledger — no N+1. Money stays Decimal end to end
        # (Sum of a DecimalField is Decimal); quantized to 2dp and sent as a
        # STRING so full precision survives the wire.
        rows = (
            ChargeSchedule.objects.filter(
                status__in=BILLED_INCOME_STATUSES,
                due_date__gte=date_from,
                due_date__lte=date_to,
            )
            .annotate(month=TruncMonth("due_date"))
            .values("month")
            .annotate(total=Sum("expected_amount"))
            .order_by("month")
        )
        data = [
            {
                "month": row["month"].strftime("%Y-%m"),
                "amount": str(round_money(row["total"] or Decimal("0"))),
            }
            for row in rows
        ]
        return Response(ChargeScheduleMonthlyIncomeSerializer(data, many=True).data)


@extend_schema_view(
    list=extend_schema(
        tags=["Payments — Billing runs"],
        summary="List billing runs (staff only)",
        parameters=[
            catalogue_parameter(
                "year",
                PARAM_CATALOGUE,
                required=False,
                description="Filter to runs whose period falls in this year "
                "(matched on period_start's year).",
            ),
        ],
        responses={
            200: BillingRunSerializer(many=True),
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    ),
    retrieve=extend_schema(
        tags=["Payments — Billing runs"],
        summary="Retrieve a single billing run",
        responses={
            200: BillingRunSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    ),
    destroy=extend_schema(
        tags=["Payments — Billing runs"],
        summary="Delete a DRAFT billing run (Office only)",
        responses={
            204: None,
            # BillingRunNotDraft — only DRAFT runs may be deleted.
            409: ErrorResponseSerializer,
        },
    ),
)
class BillingRunViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """Staff-only. Manages export batches."""

    read_permission = IsStaff
    write_permission = IsOffice
    queryset = BillingRun.objects.all()
    serializer_class = BillingRunSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        qs = BillingRun.objects.all()
        year = validate_query_params(self.request, PARAM_CATALOGUE, optional=["year"])[
            "year"
        ]
        if year is not None:
            qs = qs.filter(period_start__year=year)
        return qs

    @extend_schema(
        tags=["Payments — Billing runs"],
        summary="Create a billing run (Office only)",
        description=(
            "Bundles eligible PLANNED charges (matching due_date and "
            "payment_method) into a new DRAFT BillingRun. Use the `export` "
            "action afterwards to generate the SEPA XML file."
        ),
        request=CreateBillingRunSerializer,
        responses={
            201: BillingRunSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def create(self, request, *args, **kwargs):
        serializer = CreateBillingRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Reject a past RequestedCollectionDate before building a run: SEPA
        # can't settle a debit before today, so the bank would reject the whole
        # pain.008 batch at export. (The DatePicker disables past dates too;
        # this is the server-side backstop.)
        collection_date = serializer.validated_data["collection_date"]
        if collection_date < timezone.localdate():
            raise BillingRunInvalidCollectionDate(
                "collection_date must not be in the past "
                f"(got {collection_date.isoformat()}).",
                details={"collection_date": collection_date.isoformat()},
            )
        # ``BillingRunService.create_run`` raises payments JasminErrors
        # (BillingRunInvalidPeriod / NoEligibleCharges / NoValidSepaMandates)
        # — they carry stable dotted codes and reach the canonical handler
        # on their own, no ``ValidationError`` re-wrap needed.
        run = BillingRunService.create_run(
            period_start=serializer.validated_data["period_start"],
            period_end=serializer.validated_data["period_end"],
            collection_date=serializer.validated_data["collection_date"],
            created_by=getattr(request, "user", None),
            payment_method=serializer.validated_data["payment_method"],
        )
        return Response(
            BillingRunSerializer(run, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request, *args, **kwargs):
        # ``get_object()`` is an unlocked snapshot — a concurrent ``export`` can
        # flip the run DRAFT→EXPORTED between the status check and the delete,
        # letting an exported SEPA run (with its pain.008 + ISSUED charges) be
        # deleted. Re-fetch under a row lock and re-check inside the transaction,
        # same pattern as ``BillingRunService.export``.
        from django.db import transaction

        run = self.get_object()
        with transaction.atomic():
            locked = BillingRun.objects.select_for_update().get(pk=run.pk)
            if locked.status != BillingRunStatus.DRAFT:
                raise BillingRunNotDraft("Only DRAFT billing runs can be deleted.")
            locked.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["Payments — Billing runs"],
        summary="Export a billing run (Office only)",
        description=(
            "Exports a DRAFT run: flips its charges to ISSUED and marks the "
            "run EXPORTED. SEPA Direct Debit runs also get a pain.008.001.02 "
            "XML attached; Bank Transfer runs produce no direct-debit file "
            "(those charges are settled manually)."
        ),
        request=None,
        responses={
            200: BillingRunSerializer,
            # SepaExportInvalid / BillingRunHasNoCharges.
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            # BillingRunNotDraft — re-export of a non-DRAFT run.
            409: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"], permission_classes=[IsOffice])
    def export(self, request, pk=None):
        """Generate the SEPA pain.008 XML and flip charges to ISSUED."""
        run = self.get_object()
        # ``BillingRunService.export`` raises payments JasminErrors
        # (BillingRunNotDraft → 409, BillingRunHasNoCharges /
        # SepaExportInvalid → 400) which reach the canonical handler.
        run = BillingRunService.export(run)
        return Response(BillingRunSerializer(run, context={"request": request}).data)
