from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.db.models import (
    Case,
    Count,
    DateField,
    DecimalField,
    F,
    IntegerField,
    Max,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
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
    IsOfficeOrMember,
    IsStaff,
    IsStaffOrMember,
    RolePermissionsMixin,
)
from apps.shared.pii_logging import PIIReadLoggingMixin
from core.pagination import OptionalLimitOffsetPagination
from core.serializers import ErrorResponseSerializer

from ..errors import (
    CoopShareConfirmedImmutable,
    MemberConfirmedImmutable,
    SubscriptionAlreadyConfirmed,
    SubscriptionConfirmedImmutable,
)
from ..models import CoopShare, Member, ShareDelivery, Subscription
from ..models.choices_text import InvitationStatus
from ..models.managers import active_on_date_q
from ..models.members import MemberLoan, UserInvitation
from ..schemas import (
    EXPORT_DATE_RANGE_PARAMETERS,
    get_active_at_date_parameter,
    get_is_active_parameter,
    get_is_trial_parameter,
    get_member_parameter,
    get_share_option_parameter,
    get_share_type_variation_parameter,
    get_year_parameter,
)
from ..scoping import enforce_privileged, scope_to_member
from ..serializers import (
    CoopShareSerializer,
    MemberCreateRequestSerializer,
    MemberEmailLogSerializer,
    MemberLoanSerializer,
    MemberSelfReadSerializer,
    MemberSerializer,
    SubscriptionSerializer,
)
from ..services import MemberService, SubscriptionService
from ..utils.query_params import validate_query_params
from ..utils.queryset_helpers import apply_optional_filters
from ..utils.validation_utils import parse_body_date
from .badge_viewsets import pending_admin_confirmation_q

logger = logging.getLogger(__name__)


class RefetchForResponseMixin:
    """Reload a mutated instance through ``get_queryset()`` so the serialized
    response carries the annotations / ``select_related`` the list-and-detail
    queryset adds (the raw instance returned by ``serializer.save()`` lacks
    them). Returns ``None`` if the row vanished (e.g. deleted concurrently)."""

    def refetch_for_response(self, instance: Any) -> Any:
        return self.get_queryset().filter(id=instance.id).first()


def _build_member_queryset(request: Request) -> QuerySet[Member]:
    """Return the annotated/filtered Member queryset for list/retrieve.

    Extracted from `MemberViewSet.get_queryset` to keep the viewset thin.
    The N+1 lock note (see joins/prefetch below) is enforced by
    ``apps/payments/tests/test_query_count_locks.py``.
    """
    sent_invitations_qs = UserInvitation.objects.filter(
        status=InvitationStatus.SENT
    ).order_by("-created_at")
    queryset: QuerySet[Member] = Member.objects.select_related(
        "user", "user__linked_reseller", "admin_confirmed_by", "created_by"
    ).prefetch_related(
        Prefetch(
            "user__invitations",
            queryset=sent_invitations_qs,
            to_attr="_prefetched_sent_invitations",
        )
    )

    params = validate_query_params(
        request,
        optional=[
            "is_active",
            "is_trial",
            "only_with_subscriptions",
            "exclude_trial_members",
        ],
    )
    queryset = apply_optional_filters(
        queryset,
        params,
        [
            "is_active",
            "is_trial",
            ("exclude_trial_members", "is_trial", lambda v: not v),
        ],
    )
    if params["only_with_subscriptions"]:
        queryset = queryset.filter(subscriptions__isnull=False).distinct()

    today = timezone.now().date()
    active_count_sq = (
        Subscription.objects.filter(
            active_on_date_q(today),
            member=OuterRef("pk"),
            admin_confirmed=True,
            # Exclude cancelled subs (canonical "active" = cancelled_at IS NULL),
            # matching Member.active_subscriptions_count.
            cancelled_at__isnull=True,
        )
        .order_by()
        .values("member")
        .annotate(c=Count("*"))
        .values("c")
    )
    # Per-member sum of coop-share quantities, used by the office
    # Members table to display "X shares" on the coop-shares button +
    # paint that button red when a non-trial member has zero shares
    # (violates the GenG min-equity invariant the bounds rule
    # enforces). Subquery so we don't fan out the row count via JOIN.
    coop_shares_sq = (
        # Live equity excludes cancelled (divested) shares, matching the enforced
        # GenG invariant (CoopShareService.member_total_shares / CoopShare.clean
        # both filter cancelled_at__isnull=True). Without this the min-equity
        # warning never fires for a member who divested all their shares.
        CoopShare.objects.filter(member=OuterRef("pk"), cancelled_at__isnull=True)
        .order_by()
        .values("member")
        .annotate(total=Sum("amount_of_coop_shares"))
        .values("total")
    )
    # Latest cooperative-equity payback date across ALL the member's coop
    # shares. ``CoopShare.payback_due_date`` is snapshotted per share when it's
    # cancelled (NULL on live shares, so ``Max`` ignores them) — the member's
    # effective payback date is the latest of them. Subquery (not a direct
    # ``Max`` annotate over the reverse relation) so it doesn't fan out / clash
    # with the other coop-share aggregates above.
    payback_due_date_sq = (
        CoopShare.objects.filter(member=OuterRef("pk"))
        .order_by()
        .values("member")
        .annotate(latest=Max("payback_due_date"))
        .values("latest")
    )
    # Count of the member's coop shares still awaiting office confirmation
    # (unconfirmed, not rejected, not cancelled). Reuses the badge_viewsets
    # ``pending_admin_confirmation_q()`` predicate so it can't drift from the
    # counters (the previous hand-rolled ``admin_confirmed=False`` dropped the
    # ``admin_confirmed__isnull=True`` branch). Drives the gold "needs
    # confirmation" badge on the Members table's coop-shares button + the
    # member-detail card. Subquery so it doesn't fan out / clash with the other
    # coop-share aggregates.
    coop_shares_pending_count_sq = (
        CoopShare.objects.filter(
            pending_admin_confirmation_q(),
            member=OuterRef("pk"),
            cancelled_at__isnull=True,
        )
        .order_by()
        .values("member")
        .annotate(c=Count("*"))
        .values("c")
    )
    queryset = queryset.annotate(
        active_subscriptions_count=Coalesce(
            Subquery(active_count_sq, output_field=IntegerField()),
            Value(0),
            output_field=IntegerField(),
        ),
        coop_shares_total=Coalesce(
            Subquery(
                coop_shares_sq,
                output_field=DecimalField(max_digits=10, decimal_places=2),
            ),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=10, decimal_places=2),
        ),
        payback_due_date=Subquery(payback_due_date_sq, output_field=DateField()),
        coop_shares_pending_count=Coalesce(
            Subquery(coop_shares_pending_count_sq, output_field=IntegerField()),
            Value(0),
            output_field=IntegerField(),
        ),
        priority=Case(
            When(
                admin_confirmed=False,
                admin_rejection_reason__isnull=True,
                then=0,
            ),
            default=1,
            output_field=IntegerField(),
        ),
    ).order_by(
        "priority",
        F("member_number").asc(nulls_last=True),
        # Stable tiebreak: pending members share priority=0 + member_number NULL,
        # so without this LIMIT/OFFSET pagination could overlap/skip applicants.
        "-created_at",
        "id",
    )

    # Members may only see/update their own profile; staff bypass.
    return scope_to_member(queryset, request, path="pk")


def _parse_required_effective_at(request: Request):
    """Parse + validate a required ``effective_at`` (YYYY-MM-DD) from the body,
    raising the project's ``CommissioningError`` envelope on missing/bad input.
    Shared by the office + member cancellation flows."""
    return parse_body_date(request, "effective_at", code_prefix="member.cancel")


@extend_schema_view(
    # ``get_serializer_class`` serves office/staff the full ``MemberSerializer``
    # (model ``__all__`` + the office-only ``admin_confirmed_by_name`` /
    # ``created_by_name`` / ``linked_user_info`` / annotated counts) and serves a
    # member-role caller reading their OWN row the narrower
    # ``MemberSelfReadSerializer`` (a strict SUBSET: it drops ``note`` + the admin
    # confirm/reject audit trail and never declares the office method fields).
    # We document the office SUPERSET here so the generated type isn't inferred;
    # member-role responses are that shape minus the dropped office-internal keys.
    retrieve=extend_schema(responses={200: MemberSerializer}),
)
class MemberViewSet(
    RefetchForResponseMixin,
    PIIReadLoggingMixin,
    RolePermissionsMixin,
    viewsets.ModelViewSet,
):
    # Members may READ their own row (the scoped queryset confines them to it),
    # but all WRITES are office-only. Member self-edit goes through the narrow,
    # PK-less MyMemberDataView allowlist (MyMemberDataUpdateSerializer) — NOT
    # this office serializer, which exposes is_active / is_trial / etc. Leaving
    # write open to members here would let them PATCH those fields on their own
    # row (update/partial_update are not enforce_privileged-gated).
    read_permission = IsOfficeOrMember
    write_permission = IsOffice
    serializer_class = MemberSerializer
    # Opt-in pagination: callers that don't pass `?limit=` keep getting the
    # full list (unchanged response shape). Pages that need pagination pass
    # `?limit=200` (or similar) and get `{count, next, previous, results}`.
    pagination_class = OptionalLimitOffsetPagination

    # PATCHes that touch the SEPA fields trip step-up auth. Most member
    # edits (name, address, note) don't touch these and pass through
    # unprompted; rewriting iban / account_owner could redirect
    # direct-debit money, so the modal fires only for those.
    _SEPA_SENSITIVE_FIELDS = ("iban", "account_owner")

    def get_permissions(self):
        from apps.accounts.permissions import requires_step_up_for_fields

        perms = super().get_permissions()
        if self.action in {"create", "update", "partial_update"}:
            perms.append(requires_step_up_for_fields(*self._SEPA_SENSITIVE_FIELDS)())
        return perms

    def get_serializer_class(self):
        # ``read_permission = IsOfficeOrMember`` lets a member-role caller
        # GET their OWN row (the queryset is scoped to it). The office
        # ``MemberSerializer`` exposes ``__all__`` + office-internal fields
        # (free-text ``note``, the admin confirm/reject audit trail,
        # ``linked_user_info``) — ``read_only_fields`` guards writes, not
        # reads. So serve member-role callers a narrowed self-read serializer
        # on the read actions; staff keep the office serializer. Writes are
        # office-only, and anonymous / schema-generation falls through to the
        # office serializer (the documented response shape).
        request = getattr(self, "request", None)
        if (
            self.action in {"list", "retrieve"}
            and request is not None
            and getattr(request, "user", None)
            and request.user.is_authenticated
            and not IsStaff().has_permission(request, self)
        ):
            return MemberSelfReadSerializer
        return MemberSerializer

    @extend_schema(
        parameters=[
            get_is_active_parameter(),
            get_is_trial_parameter(required=False),
            OpenApiParameter(
                name="only_with_subscriptions",
                type=OpenApiTypes.BOOL,
                required=False,
                description="Only return members that have subscriptions",
            ),
            OpenApiParameter(
                name="exclude_trial_members",
                type=OpenApiTypes.BOOL,
                required=False,
                description="Exclude trial members from results",
            ),
        ],
        # Office/staff get the full ``MemberSerializer``; a member-role caller
        # reading their own row gets the narrower ``MemberSelfReadSerializer``
        # subset (see ``get_serializer_class`` + the class-level note). The
        # documented office superset covers both. Pagination is opt-in via
        # ``?limit=`` (``OptionalLimitOffsetPagination``).
        responses={200: MemberSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Member]:
        return _build_member_queryset(self.request)

    @extend_schema(
        description=(
            "Create a Member. If the supplied email matches an existing "
            "JasminUser, the new Member is linked to that user (instead of "
            "rejecting with a uniqueness error). The behaviour depends on "
            "the user's account status:\n"
            "  * ``active``              → link, auto-confirm the member, "
            "and (if ``notify_user=true``) send a 'you are now a member' "
            "email.\n"
            "  * ``pending_invitation``  → link only; the member is "
            "auto-confirmed when the user accepts the invitation.\n"
            "  * ``pending_approval``    → 409 conflict; the user already "
            "has a pending member application.\n"
            "  * ``inactive``            → 409 conflict.\n"
        ),
        request=MemberCreateRequestSerializer,
        responses={
            201: MemberSerializer,
            # ``MemberLinkConflict`` — see the status table above.
            409: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        enforce_privileged(request, "Only office staff may create members.")

        email: str = (request.data.get("email") or "").strip().lower()
        notify_user: bool = bool(request.data.get("notify_user"))

        service = MemberService()
        existing_user = service.find_existing_user_for_email(email)
        if existing_user is not None:
            # Raises MemberLinkConflict (409) when blocked.
            service.assert_user_can_be_linked(existing_user)

        # Strip the optional flag before serializer validation.
        data = {k: v for k, v in request.data.items() if k != "notify_user"}
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        member: Member = serializer.save()

        if existing_user is not None:
            service.link_to_user(
                member,
                existing_user,
                admin_user=request.user,
                notify_user=notify_user,
                request=request,
            )

        headers = self.get_success_headers(serializer.data)
        out = self.refetch_for_response(member)
        return Response(
            self.get_serializer(out).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        enforce_privileged(request, "Only office staff may delete members.")
        instance: Member = self.get_object()
        if instance.admin_confirmed:
            raise MemberConfirmedImmutable(
                "Confirmed members cannot be deleted. Use the `cancel` action "
                "instead (it stamps cancelled_at and preserves the record)."
            )
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        description="Confirm a pending member.",
        # No body — without ``request=None`` spectacular would infer a
        # full required Member requestBody the view never reads.
        request=None,
        responses={
            200: MemberSerializer,
            # ``MemberAlreadyConfirmed``.
            409: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, pk: str | None = None) -> Response:
        enforce_privileged(request, "Only office staff may confirm members.")
        member: Member = self.get_object()

        from django.db import transaction

        with transaction.atomic():
            # Re-fetch under a row lock: two concurrent confirms would both
            # read ``admin_confirmed=False`` on the unlocked instance and run
            # the admission side-effects (member number, entry date, email)
            # twice. The second request blocks here, then the service's
            # already-confirmed check raises the 409.
            member = Member.objects.select_for_update().get(pk=member.pk)

            # Raises MemberAlreadyConfirmed (409) when not pending.
            MemberService().confirm_and_notify(
                member, admin_user=request.user, request=request
            )

        updated_member = self.refetch_for_response(member)
        return Response(
            self.get_serializer(updated_member).data, status=status.HTTP_200_OK
        )

    @extend_schema(
        description="Reject a pending member with an optional reason.",
        # Mirrors SubscriptionViewSet.reject's inline request schema.
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
            }
        },
        responses={200: MemberSerializer},
    )
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        enforce_privileged(request, "Only office staff may reject members.")
        member: Member = self.get_object()
        reason: str | None = request.data.get("reason")

        MemberService().reject_and_notify(
            member,
            admin_user=request.user,
            reason=reason,
            request=request,
        )

        updated_member = self.refetch_for_response(member)
        return Response(
            self.get_serializer(updated_member).data, status=status.HTTP_200_OK
        )

    @extend_schema(
        description=(
            "Office-cancel a membership effective on the given date "
            "(``effective_at``, YYYY-MM-DD; the legal GenG exit date). Cascades "
            "to the member's coop shares (cancelled + payback_due_date "
            "snapshotted = effective + retention). By default the cancellation "
            "is REFUSED (409) while the member still holds active subscriptions "
            "— end those first. Pass ``force=true`` to cancel anyway: the active "
            "subscriptions are then ended in the same transaction (term "
            "truncated, future deliveries dropped, charges re-planned). The "
            "response lists any subscription that could NOT be ended (it keeps a "
            "live mandate and needs manual attention)."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "effective_at": {"type": "string", "format": "date"},
                    "reason": {"type": "string"},
                    "force": {"type": "boolean", "default": False},
                },
                "required": ["effective_at"],
            }
        },
        responses={
            200: inline_serializer(
                name="MemberCancelResult",
                fields={
                    "member": MemberSerializer(),
                    "subscriptions_not_ended": drf_serializers.ListField(
                        child=drf_serializers.CharField(),
                        help_text=(
                            "Subscription IDs the force-cancel could not end — "
                            "these still hold an active mandate."
                        ),
                    ),
                },
            ),
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        from ..errors import MemberAlreadyCancelled
        from ..services.member_cancellation import cancel_member_with_coop_shares

        enforce_privileged(request, "Only office staff may cancel members.")
        member: Member = self.get_object()
        if member.cancelled_at is not None:
            raise MemberAlreadyCancelled("This membership is already cancelled.")

        effective = _parse_required_effective_at(request)
        # Default: refuse if active subscriptions remain (the service raises
        # MemberHasActiveSubscriptions → 409). ``force`` bypasses the restraint
        # and ends the subscriptions as part of the cascade.
        force = bool(request.data.get("force", False))
        result_member = cancel_member_with_coop_shares(
            member,
            cancelled_effective_at=effective,
            cancelled_by=request.user,
            reason=request.data.get("reason"),
            force=force,
        )
        cancellation_result = getattr(result_member, "cancellation_result", {})

        updated_member = self.refetch_for_response(member)
        return Response(
            {
                "member": self.get_serializer(updated_member).data,
                "subscriptions_not_ended": cancellation_result.get(
                    "subscriptions_not_ended", []
                ),
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        description=(
            "GenG §30 member register (Mitgliederliste) as CSV for a date "
            "range — every member who was a member at any point in the window, "
            "with their Eintritt/Austritt dates and the cooperative shares + "
            "paid-in capital held as of the window end."
        ),
        parameters=EXPORT_DATE_RANGE_PARAMETERS,
        responses={
            (200, "text/csv"): OpenApiTypes.BINARY,
            400: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["get"], url_path="export_csv")
    def export_csv(self, request: Request) -> StreamingHttpResponse:
        # Office-only: a custom @action falls under ``write_permission``
        # (IsOffice) via RolePermissionsMixin, so a member-role caller cannot
        # pull the whole register even though list/retrieve allow members.
        from ..services.member_register_export import (
            build_member_register_csv_response,
        )

        params = validate_query_params(request, required=["date_from", "date_to"])
        return build_member_register_csv_response(
            date_from=params["date_from"], date_to=params["date_to"]
        )

    @extend_schema(
        description=(
            "Every EmailLog row whose recipient matches this member's "
            "email address — projected to the audit-relevant columns "
            "(purpose, subject, status, sent_at, delivered_at). Used by "
            "the office UI's per-member 'Sent emails' modal to answer "
            '"did this member receive the application_approved mail?". '
            "Returns the empty list when the member has no email on "
            "file."
        ),
        responses={200: MemberEmailLogSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def emails(self, request: Request, pk: str | None = None) -> Response:
        enforce_privileged(request, "Only office staff may view sent emails.")
        member: Member = self.get_object()
        from apps.notifications.models import EmailLog

        if not member.email:
            return Response([], status=status.HTTP_200_OK)

        # ``recipient`` is a plain CharField mirroring whatever
        # ``email_service.send_email`` wrote — equality match is
        # correct, no case-folding (the service stores the raw value
        # from the Member.email column).
        rows = (
            EmailLog.objects.filter(recipient=member.email)
            .order_by("-created_at")
            .values(
                "id",
                "purpose",
                "subject",
                "template",
                "status",
                "sent_at",
                "delivered_at",
                "created_at",
            )
        )
        return Response(
            MemberEmailLogSerializer(list(rows), many=True).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        description=(
            "Send (or re-send) a JasminUser invitation email to this member. "
            "Creates a JasminUser in pending_invitation status linked to the "
            "member if one does not already exist."
        ),
        # No body — see ``confirm``.
        request=None,
        responses={200: MemberSerializer},
    )
    @action(detail=True, methods=["post"])
    def send_invitation(self, request: Request, pk: str | None = None) -> Response:
        enforce_privileged(request, "Only office staff may send invitations.")
        member: Member = self.get_object()

        # Raises MemberInvitationError (400) when not eligible.
        MemberService().send_invitation(member, admin_user=request.user)

        updated_member = self.refetch_for_response(member)
        return Response(
            self.get_serializer(updated_member).data, status=status.HTTP_200_OK
        )


def _build_subscription_queryset(request: Request) -> QuerySet[Subscription]:
    """Return the filtered Subscription queryset.

    Read-only display fields (member name, share type strings, payment-
    cycle name, etc.) are resolved by `SubscriptionSerializer` via
    `source=` / `SerializerMethodField`. The select_related chain below
    must cover every relation the serializer touches to avoid N+1.
    """
    params = validate_query_params(
        request,
        optional=[
            "member",
            "share_type_variation",
            "is_trial",
            "share_option",
            "active_at_date",
            "on_waiting_list",
        ],
    )
    member = params["member"]
    share_type_variation = params["share_type_variation"]
    is_trial = params["is_trial"]
    share_option = params["share_option"]
    active_at_date = params["active_at_date"]
    on_waiting_list = params["on_waiting_list"]

    if active_at_date is not None:
        queryset: QuerySet[Subscription] = Subscription.current.active_at_date(
            active_at_date
        )
    else:
        queryset = Subscription.objects.all()

    queryset = queryset.select_related(
        "member",
        "share_type_variation__share_type",
        "payment_cycle",
        "default_delivery_station_day__delivery_day",
        "default_delivery_station_day__delivery_station",
        "admin_confirmed_by",
        "created_by",
        # Serializer renders ``cancelled_by_name`` (source=cancelled_by.username)
        # — without this, every cancelled row lazy-loads one JasminUser (N+1).
        "cancelled_by",
    ).annotate(
        # ``deliveries_count`` counts materialised ``ShareDelivery``
        # rows for this subscription, excluding joker-taken weeks.
        # Source of truth for the "Lieferungen" column on Abos.tsx —
        # replaces the prior frontend calendar arithmetic which
        # double-counted fortnightly cycles and ignored jokers.
        #
        # Zero is a meaningful value: a not-yet-confirmed
        # subscription has no ShareDelivery rows yet (materialisation
        # happens in ``SubscriptionService._post_confirm``), so a
        # draft row legitimately shows ``0×``. The office reads that
        # as "needs admin-confirmation".
        #
        # Opt-outs for on-off variations are excluded too, so Abos.tsx agrees
        # with the demand pipeline / preparation lists and with billing — all
        # three now share the one ``ShareDelivery.delivery_counts_q`` rule.
        deliveries_count=Count(
            "sharedelivery",
            filter=ShareDelivery.delivery_counts_q(prefix="sharedelivery__"),
        ),
        # Jokers TAKEN for this subscription = materialised ShareDelivery
        # rows flagged ``joker_taken``. Counted here (over the same
        # ``sharedelivery`` reverse join as ``deliveries_count``, so it's a
        # single JOIN + two FILTERed counts — no row multiplication) and read
        # by ``SubscriptionSerializer.jokers_taken``. The allowance (the "/Y")
        # is the share type's ``amount_of_jokers`` (per-share-type joker
        # system), surfaced via ``SubscriptionSerializer.amount_of_jokers``.
        jokers_taken=Count(
            "sharedelivery",
            filter=Q(sharedelivery__joker_taken=True),
        ),
        # Donation jokers taken — same pattern (a third FILTERed count over the
        # one sharedelivery join, so no row multiplication). Allowance is the
        # share type's ``amount_of_donation_jokers``.
        donation_jokers_taken=Count(
            "sharedelivery",
            filter=Q(sharedelivery__donation_joker_taken=True),
        ),
    )

    if member is not None:
        try:
            queryset = queryset.filter(member=member)
        except ValueError:
            return Subscription.objects.none()

    if share_type_variation is not None:
        try:
            queryset = queryset.filter(share_type_variation=share_type_variation)
        except ValueError:
            return Subscription.objects.none()

    if share_option is not None:
        try:
            queryset = queryset.filter(
                share_type_variation__share_type__share_option=share_option
            )
        except ValueError:
            return Subscription.objects.none()

    if is_trial is not None:
        queryset = queryset.filter(is_trial=is_trial)
    if on_waiting_list is not None:
        queryset = queryset.filter(on_waiting_list=on_waiting_list)

    return scope_to_member(queryset, request, path="member")


@extend_schema_view(
    # ``retrieve`` is inherited (no override) and was guessed; the viewset's
    # ``serializer_class`` / ``_build_subscription_queryset`` return a single
    # ``SubscriptionSerializer`` row.
    retrieve=extend_schema(responses={200: SubscriptionSerializer}),
)
class SubscriptionViewSet(
    RefetchForResponseMixin, RolePermissionsMixin, viewsets.ModelViewSet
):
    read_permission = IsStaffOrMember
    write_permission = IsOffice
    serializer_class = SubscriptionSerializer
    pagination_class = OptionalLimitOffsetPagination

    def get_serializer_context(self):
        """Surface ``min_weeks_to_cancel_before_ending`` on the
        serializer context so ``SubscriptionSerializer.get_automatically_renewed_at``
        doesn't fetch ``TenantSettings.get_current_settings`` per row
        (~1000+ row queries on the Abos page otherwise). One fetch
        per response covers every row.
        """
        ctx = super().get_serializer_context()
        from django.db import connection

        from apps.shared.tenants.models import TenantSettings

        tenant = getattr(connection, "tenant", None)
        if tenant is not None and getattr(tenant, "schema_name", "") != "public":
            settings = TenantSettings.get_current_settings(tenant)
            if settings is not None:
                ctx["min_weeks_to_cancel_before_ending"] = getattr(
                    settings, "min_weeks_to_cancel_before_ending", None
                )
        return ctx

    @extend_schema(
        parameters=[
            get_member_parameter(required=False),
            get_share_type_variation_parameter(required=False),
            get_share_option_parameter(required=False),
            get_is_trial_parameter(required=False),
            get_active_at_date_parameter(),
            OpenApiParameter(
                name="on_waiting_list",
                type=OpenApiTypes.BOOL,
                required=False,
                description="Filter by waiting list status",
            ),
        ],
        # Stock DRF list — returns the annotated ``_build_subscription_queryset``
        # rows serialized as ``SubscriptionSerializer``. Pagination is opt-in via
        # ``?limit=`` (``OptionalLimitOffsetPagination``).
        responses={200: SubscriptionSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Subscription]:
        return _build_subscription_queryset(self.request)

    @extend_schema(
        description="Create a draft (unconfirmed) subscription.",
        # Returns the created row (re-fetched through the annotated
        # ``_build_subscription_queryset``) at 201.
        responses={201: SubscriptionSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = SubscriptionService()
        subscription = service.create_bare_subscription(serializer.validated_data)

        created_subscription = self.refetch_for_response(subscription)
        response_serializer = self.get_serializer(created_subscription)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        description=(
            "Update a subscription. Only allowed while the subscription is "
            "still a draft (admin_confirmed=False). To end a confirmed "
            "subscription early, use the `cancel` action."
        ),
        responses={
            200: SubscriptionSerializer,
            # ``SubscriptionConfirmedImmutable``.
            409: ErrorResponseSerializer,
        },
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._save_subscription(request, partial=False)

    @extend_schema(
        description=(
            "Partially update a subscription. Only allowed while the "
            "subscription is still a draft (admin_confirmed=False)."
        ),
        responses={
            200: SubscriptionSerializer,
            # ``SubscriptionConfirmedImmutable``.
            409: ErrorResponseSerializer,
        },
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._save_subscription(request, partial=True)

    @extend_schema(
        responses={
            204: None,
            # ``SubscriptionConfirmedImmutable``.
            409: ErrorResponseSerializer,
        },
    )
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: Subscription = self.get_object()
        if instance.admin_confirmed:
            raise SubscriptionConfirmedImmutable(
                "Confirmed subscriptions cannot be deleted. Use the "
                "`cancel` action instead."
            )
        return super().destroy(request, *args, **kwargs)

    def _save_subscription(self, request: Request, *, partial: bool) -> Response:
        instance: Subscription = self.get_object()
        if instance.admin_confirmed:
            raise SubscriptionConfirmedImmutable(
                "Confirmed subscriptions cannot be edited. Use the "
                "`cancel` action to end them early."
            )

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        SubscriptionService().update_draft_subscription(
            instance, serializer.validated_data
        )

        updated_subscription = self.refetch_for_response(instance)
        return Response(
            self.get_serializer(updated_subscription).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        description=(
            "Admin-confirm a subscription. Materialises Shares, ShareDeliveries "
            "and the PLANNED ChargeSchedule for the term. Idempotent: re-running "
            "only fills missing rows; ISSUED/PAID/FAILED/WAIVED charges are "
            "never touched."
        ),
        # No body — without ``request=None`` spectacular would infer a full
        # required Subscription requestBody the view never reads.
        request=None,
        responses={
            200: SubscriptionSerializer,
            # ``SubscriptionAlreadyConfirmed`` / ``DeliveryStationOverCapacity``.
            409: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, pk: str | None = None) -> Response:
        from ..errors import MemberAlreadyCancelled

        subscription: Subscription = self.get_object()

        from django.db import transaction

        # All-or-nothing: ``confirm`` flips ``admin_confirmed`` then materialises
        # shares/deliveries, which can now raise ``DeliveryStationOverCapacity``
        # (a reserved slot lapsed and was taken). Wrap so the flag rolls back
        # with it instead of leaving a confirmed-but-empty subscription.
        with transaction.atomic():
            # Re-fetch under a row lock before checking ``admin_confirmed``:
            # two concurrent confirms would both read False on the unlocked
            # instance and double-materialise shares/deliveries/charges. The
            # second request blocks on the lock and then sees the flipped flag.
            subscription = Subscription.objects.select_for_update().get(
                pk=subscription.pk
            )

            if subscription.admin_confirmed:
                raise SubscriptionAlreadyConfirmed("Subscription is already confirmed")

            # Never confirm a subscription for a member who has initiated their
            # exit — confirming materialises ShareDeliveries + PLANNED charges
            # (and would back-cascade member.confirm()) for someone who has
            # legally left.
            member = subscription.member
            if member and member.cancelled_at is not None:
                raise MemberAlreadyCancelled(
                    "Cannot confirm a subscription for a cancelled member."
                )

            subscription.confirm(admin_user=request.user, save=True)

        updated = self.refetch_for_response(subscription)
        return Response(self.get_serializer(updated).data, status=status.HTTP_200_OK)

    @extend_schema(
        description=(
            "Offer a freed spot to a queued waiting-list member: holds both "
            "capacity axes (station-day reservation + status-counted variation "
            "hold) for the response window and emails the member a magic link "
            "to accept/decline without logging in. Optional "
            "``price_per_delivery`` lets the office set the price at offer time "
            "(a waiting_list entry may be a year old). Only a PENDING waiting-list "
            "entry can be offered; a capacity 409 means the slot filled up "
            "between the office's view and the click."
        ),
        request=inline_serializer(
            name="OfferSpotRequest",
            fields={
                "price_per_delivery": drf_serializers.DecimalField(
                    max_digits=8,
                    decimal_places=2,
                    required=False,
                    allow_null=True,
                ),
            },
        ),
        responses={200: SubscriptionSerializer},
    )
    @action(detail=True, methods=["post"], url_path="offer_spot")
    def offer_spot(self, request: Request, pk: str | None = None) -> Response:
        from ..services.waiting_list_offer_service import WaitingListOfferService

        subscription: Subscription = self.get_object()
        WaitingListOfferService.offer_spot(
            subscription,
            price_per_delivery=request.data.get("price_per_delivery"),
        )
        updated = self.refetch_for_response(subscription)
        return Response(self.get_serializer(updated).data, status=status.HTTP_200_OK)

    @extend_schema(
        description=(
            "Reject a pending subscription application. Stamps "
            "``admin_rejected_at`` + ``admin_rejection_reason`` so the "
            "office UI surfaces the decision; ``admin_confirmed`` "
            "stays False, no shares / deliveries / charges are "
            "materialised. Idempotent on already-rejected rows."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
            }
        },
        responses={200: SubscriptionSerializer},
    )
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        enforce_privileged(request, "Only office staff may reject subscriptions.")
        subscription: Subscription = self.get_object()

        # ``reject`` is for PENDING applications only. Rejecting an already
        # CONFIRMED subscription would merely un-flip the flag while leaving
        # its materialised ShareDeliveries and PLANNED ChargeSchedule rows
        # intact — those are still SEPA-debited (create_run filters on
        # status=PLANNED, not admin_confirmed). Genuine revocation of a
        # confirmed subscription must route through ``cancel`` (which drops
        # future deliveries + PLANNED charges and re-plans). Already-rejected
        # rows stay idempotent (admin_confirmed is False).
        if subscription.admin_confirmed:
            raise SubscriptionAlreadyConfirmed(
                "Confirmed subscriptions cannot be rejected — cancel them instead."
            )

        reason: str | None = request.data.get("reason")

        # Mirrors ``MembersViewSet.reject``: no email side-effect today
        # — subscriptions don't ship a ``subscription.application_
        # rejected`` template yet. Add the email wiring alongside the
        # template if product asks. For now ``reject()`` just stamps
        # the audit fields and saves.
        subscription.reject(admin_user=request.user, reason=reason, save=True)

        # Free the draft's held station-day capacity. The reject stamps flags
        # but does NOT delete the row, so the CASCADE that would otherwise drop
        # the CapacityReservation never fires — without this, the rejected
        # applicant keeps blocking the slot (and any waiting_list promotion) until
        # the 14-day TTL lapses.
        from ..services.capacity_reservation_service import (
            CapacityReservationService,
        )

        CapacityReservationService.release_for_subscription(subscription)

        updated = self.refetch_for_response(subscription)
        return Response(self.get_serializer(updated).data, status=status.HTTP_200_OK)

    @extend_schema(
        description=(
            "Cancel a confirmed subscription with effect from `effective_at` "
            "(YYYY-MM-DD). Truncates the term, deletes future ShareDeliveries, "
            "drops PLANNED charges past the new end and re-plans the rest. "
            "ISSUED/PAID/FAILED/WAIVED charges are never touched."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "effective_at": {"type": "string", "format": "date"},
                    "reason": {"type": "string"},
                },
                "required": ["effective_at"],
            }
        },
        responses={
            200: SubscriptionSerializer,
            # ``CommissioningError`` — effective_at missing / malformed.
            400: ErrorResponseSerializer,
            # ``FinalizedError`` — cancelling a draft subscription.
            409: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        from ..errors import FinalizedError

        subscription: Subscription = self.get_object()
        if not subscription.admin_confirmed:
            raise FinalizedError(
                "Draft subscriptions cannot be cancelled — delete them instead.",
                code="subscription.cancel_draft",
            )

        effective_at = parse_body_date(
            request, "effective_at", code_prefix="subscription.cancel"
        )

        SubscriptionService().cancel_subscription(
            subscription,
            cancelled_by=request.user,
            effective_at=effective_at,
            reason=request.data.get("reason"),
        )

        updated = self.refetch_for_response(subscription)
        return Response(self.get_serializer(updated).data, status=status.HTTP_200_OK)

    @extend_schema(
        description=(
            "Bulk-renew the selected subscriptions — same per-subscription logic "
            "as the daily auto-renewal sweep. Creates an UNCONFIRMED renewal draft "
            "for each eligible row (the office reviews + confirms downstream). "
            "Ineligible rows (trial / cancelled / cancelled member / already "
            "renewed / open-ended) are skipped; a row with no same-size variation "
            "covering the new term is counted as failed. One bad row never aborts "
            "the batch."
        ),
        request=inline_serializer(
            name="BulkRenewRequest",
            fields={
                "subscription_ids": drf_serializers.ListField(
                    child=drf_serializers.CharField(), allow_empty=False
                ),
                # Optional common end date for every renewal in the batch (the
                # modal sends the office's chosen Sunday). Omit to keep each
                # predecessor's term length (the daily sweep's default).
                "valid_until": drf_serializers.DateField(
                    required=False, allow_null=True
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="BulkRenewResult",
                fields={
                    "created": drf_serializers.IntegerField(),
                    # Per-row reasons so the office sees which selected
                    # subscriptions did NOT renew and why. ``reason`` is a code
                    # (e.g. trial / cancelled / open_ended / already_renewed /
                    # no_variation / dsd_coverage) the frontend localizes.
                    "skipped": inline_serializer(
                        name="BulkRenewSkipped",
                        many=True,
                        fields={
                            "id": drf_serializers.CharField(),
                            "label": drf_serializers.CharField(),
                            "reason": drf_serializers.CharField(),
                        },
                    ),
                    "failed": inline_serializer(
                        name="BulkRenewFailed",
                        many=True,
                        fields={
                            "id": drf_serializers.CharField(),
                            "label": drf_serializers.CharField(),
                            "reason": drf_serializers.CharField(),
                        },
                    ),
                },
            ),
            400: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["post"], url_path="bulk_renew")
    def bulk_renew(self, request: Request) -> Response:
        from ..errors import CommissioningError
        from ..services.renewal import bulk_renew as bulk_renew_service

        ids = request.data.get("subscription_ids")
        if not isinstance(ids, list) or not ids:
            raise CommissioningError(
                "Provide a non-empty list of subscription_ids.",
                field="subscription_ids",
                code="subscription.bulk_renew.ids_required",
            )

        # Optional common end date for the whole batch (the modal's chosen date);
        # omit for the per-subscription term-length default.
        new_valid_until = parse_body_date(
            request,
            "valid_until",
            required=False,
            code_prefix="subscription.bulk_renew",
            format_code="subscription.bulk_renew.invalid_valid_until",
        )
        # Each renewal runs variation/price resolution + an INSERT with
        # full_clean (station-day coverage query included) synchronously in this
        # request — an unbounded list is a gateway-timeout / mild-DoS vector.
        if len(ids) > 500:
            raise CommissioningError(
                "At most 500 subscriptions can be renewed per request.",
                field="subscription_ids",
                code="subscription.bulk_renew.too_many_ids",
            )

        result = bulk_renew_service(
            [str(i) for i in ids], new_valid_until=new_valid_until
        )
        return Response(result, status=status.HTTP_200_OK)


@extend_schema_view(
    retrieve=extend_schema(responses={200: CoopShareSerializer}),
    create=extend_schema(responses={201: CoopShareSerializer}),
    update=extend_schema(responses={200: CoopShareSerializer}),
    partial_update=extend_schema(responses={200: CoopShareSerializer}),
    destroy=extend_schema(responses={204: None}),
)
class CoopShareViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = CoopShareSerializer

    @extend_schema(
        parameters=[
            get_member_parameter(required=True),
            # ``year`` is optional at runtime — see ``get_queryset`` below,
            # which only filters when present. Schema previously claimed
            # required=True; relaxed so the per-member CoopSharesModal can
            # ask for "all years" by omitting the param.
            get_year_parameter(required=False),
        ],
        responses={200: CoopShareSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[CoopShare]:
        # ``admin_confirmed_by`` is read by the serializer's
        # ``admin_confirmed_by_name`` (source=admin_confirmed_by.username) — keep
        # it select_related to avoid an N+1 across the rows.
        queryset = CoopShare.objects.all().select_related(
            "member", "admin_confirmed_by"
        )

        params = validate_query_params(self.request, optional=["member", "year"])
        member = params["member"]
        year = params["year"]

        if member:
            queryset = queryset.filter(member=member)
        if year:
            queryset = queryset.filter(due_date__year=year)

        return queryset.order_by("-paid_at")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: CoopShare = self.get_object()
        if instance.admin_confirmed:
            raise CoopShareConfirmedImmutable(
                "Confirmed coop shares cannot be deleted (statutory GenG "
                "retention). Cancel the share (or the member) instead."
            )
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        # Office-created shares are confirmed by definition — the office IS the
        # authority. (Member self-service shares are created via
        # MyCoopShareSubscribeView and stay admin_confirmed=False until an
        # office user confirms them through the ``confirm`` action below.)
        # Create + auto-confirm are ONE unit: confirm runs the trial-conversion
        # bounds check, so an out-of-range share must roll back the insert too.
        from django.db import transaction

        from core.db_locks import acquire_advisory_xact_lock

        with transaction.atomic():
            # Serialise concurrent creates PER MEMBER: the min/max bounds check
            # in ``CoopShare.clean()`` is check-then-act (read the member's
            # total, compare, insert), so two parallel creates could both pass
            # against the same stale total and overshoot the GenG max window.
            # The advisory lock makes the second writer wait until the first
            # commits, so its clean() sees the fresh total (mirrors
            # ``Member._generate_member_number``).
            member = serializer.validated_data.get("member")
            if member is not None:
                acquire_advisory_xact_lock(f"coop_share_bounds:{member.pk}")
            instance = serializer.save()
            instance.confirm(self.request.user)

    @extend_schema(
        # No body — without ``request=None`` spectacular would infer a full
        # required CoopShare requestBody the view never reads.
        request=None,
        responses={200: CoopShareSerializer},
    )
    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request: Request, pk: str | None = None) -> Response:
        """Office-confirm a pending (e.g. member-self-subscribed) coop share.

        Vice-versa cascade: if the share belongs to a not-yet-admitted member,
        confirming the share admits the member too (initial admission from the
        equity side) — which in turn confirms the member's other pending shares
        and sends the admission email. This is best-effort: if the member is not
        yet eligible for admission (e.g. below the min-shares window), the share
        is still confirmed and the member stays pending (admit later via
        member-confirm). Members admitted earlier skip this entirely."""
        from django.db import transaction

        from ..errors import MemberAlreadyConfirmed, MemberCoopSharesOutOfRange

        coop_share = self.get_object()

        with transaction.atomic():
            # Re-fetch under a row lock: two concurrent confirms would both
            # see the pre-confirm state on the unlocked instance and run the
            # confirm side-effects (trial conversion, member admission
            # cascade + email) twice. The second request blocks here and then
            # operates on the already-confirmed row.
            coop_share = CoopShare.objects.select_for_update().get(pk=coop_share.pk)
            coop_share.confirm(request.user)

            member = coop_share.member
            if member is not None and not member.admin_confirmed:
                # Lock the member row too — the admission cascade's
                # ``admin_confirmed`` check must not race a concurrent
                # member-confirm (or a sibling share's cascade).
                member = Member.objects.select_for_update().get(pk=member.pk)
                if not member.admin_confirmed:
                    try:
                        MemberService().confirm_and_notify(
                            member, admin_user=request.user, request=request
                        )
                    except (MemberAlreadyConfirmed, MemberCoopSharesOutOfRange):
                        pass

        return Response(self.get_serializer(coop_share).data)


# Stock DRF CRUD: ``retrieve`` / ``create`` / ``update`` / ``partial_update``
# all return a single ``MemberLoanSerializer`` (the viewset ``serializer_class``);
# ``destroy`` returns 204 No Content. Declared explicitly so spectacular doesn't
# infer them. (``list`` carries its own ``@extend_schema`` for its query params.)
@extend_schema_view(
    retrieve=extend_schema(responses={200: MemberLoanSerializer}),
    create=extend_schema(responses={201: MemberLoanSerializer}),
    update=extend_schema(responses={200: MemberLoanSerializer}),
    partial_update=extend_schema(responses={200: MemberLoanSerializer}),
    destroy=extend_schema(responses={204: None}),
)
class MemberLoanViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """Office-managed register of member loans (interest-bearing loans
    the co-op accepts from its members).

    Filters mirror the existing ``CoopShareViewSet`` so the office UI
    can use the same year-+-member filter widgets on both pages —
    ``year`` filters by ``start_date__year``, ``member`` by the FK.
    Both are optional at runtime; the schema marks them as such so
    drf-spectacular doesn't reject calls that omit either.
    """

    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = MemberLoanSerializer

    @extend_schema(
        parameters=[
            get_member_parameter(required=False),
            get_year_parameter(required=False),
        ],
        responses={200: MemberLoanSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer: MemberLoanSerializer) -> None:
        # Stamp authorship server-side (the field is read-only to clients).
        serializer.save(created_by=self.request.user)

    def get_queryset(self) -> QuerySet[MemberLoan]:
        queryset = MemberLoan.objects.all().select_related("member")

        params = validate_query_params(self.request, optional=["member", "year"])
        member = params["member"]
        year = params["year"]

        if member:
            queryset = queryset.filter(member=member)
        if year:
            queryset = queryset.filter(start_date__year=year)

        return queryset.order_by("-start_date")
