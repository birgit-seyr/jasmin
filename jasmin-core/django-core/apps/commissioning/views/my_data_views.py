from __future__ import annotations

import logging

from django.db import connection, transaction
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authz.permissions import IsCustomer, IsMember
from apps.shared.request_utils import client_ip
from apps.shared.tenants.models import TenantSettings
from core.errors import NotFoundError
from core.serializers import ErrorResponseSerializer

from ..errors import CustomerProfileNotLinked, MemberProfileNotLinked
from ..models import ContactEntity, CoopShare, Member, Reseller
from ..serializers import (
    MyCoopShareSubscribeSerializer,
    MyCustomerDataReadSerializer,
    MyCustomerDataUpdateSerializer,
    MyDataCoopShareSerializer,
    MyMemberDataReadSerializer,
    MyMemberDataUpdateSerializer,
    MySubscriptionSubscribeSerializer,
    SubscriptionSerializer,
)

logger = logging.getLogger(__name__)


def _notify_office_of_self_cancel(member: Member) -> None:
    """Best-effort office notification when a member self-cancels.

    Goes to the tenant's office mailbox (``Tenant.email``); a missing address
    or a failed send is logged and swallowed — it must never roll back the
    cancellation (the office still sees the row in the members table). Mirrors
    ``gdpr.services.send_deletion_pending_admin_office_email``.
    """
    from apps.shared.invitations import _frontend_base_url, _tenant_name
    from apps.shared.tenants.email_service import EmailService

    tenant = getattr(connection, "tenant", None)
    office_email = getattr(tenant, "email", None)
    if not office_email:
        logger.info(
            "commissioning.self_cancel_office_email_skipped member=%s "
            "reason=no_office_email",
            member.id,
        )
        return

    context = {
        "tenant_name": _tenant_name(),
        "member": {
            "first_name": member.first_name,
            "last_name": member.last_name,
            "member_number": member.member_number,
        },
        "cancelled_effective_at": (
            member.cancelled_effective_at.strftime("%d.%m.%Y")
            if member.cancelled_effective_at
            else ""
        ),
        "review_url": f"{_frontend_base_url()}/members/members/{member.id}",
    }
    try:
        ok = EmailService().send_email(
            slug="commissioning.member_self_cancelled_office",
            to_emails=[office_email],
            context=context,
            related_object_type="member",
            related_object_id=str(member.id),
            priority="normal",
        )
        if not ok:
            # send_email returns False on the dominant failure class (SMTP
            # down, template error) without raising — log it so the office
            # notification miss is visible.
            logger.error(
                "commissioning.self_cancel_office_email_not_sent member=%s",
                member.id,
            )
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        logger.error(
            "commissioning.self_cancel_office_email_failed member=%s error=%s",
            member.id,
            exc,
        )


@extend_schema_view(
    get=extend_schema(
        tags=["commissioning"],
        responses={
            200: MyMemberDataReadSerializer,
            404: ErrorResponseSerializer,
        },
    ),
    patch=extend_schema(
        tags=["commissioning"],
        request=MyMemberDataUpdateSerializer,
        responses={
            200: MyMemberDataReadSerializer,
            404: ErrorResponseSerializer,
        },
    ),
)
class MyMemberDataView(APIView):
    """Self-edit surface for the authenticated Member.

    Resolves the target row via the ``request.user.member_profile``
    reverse OneToOne — the same ownership-link convention used by
    ``apps.authz.scoping.scope_by_user_attr``. There is no addressable
    PK on this endpoint, so a member cannot reach another member's
    row regardless of role. Encrypted columns (IBAN, ``account_owner``)
    come back as ``*_stored`` booleans, never plaintext."""

    permission_classes = [IsMember]

    def get_permissions(self):
        """Step-up gate the SEPA fields on the self-service path too.

        The office ``MemberViewSet`` already requires fresh re-authentication
        to change ``iban`` / ``account_owner``; without the same gate here a
        hijacked or long-lived member session could silently redirect the
        member's own direct-debit mandate. ``requires_step_up_for_fields``
        only fires when one of those fields is actually changing, so benign
        self-edits (name, address, ...) PATCH through unprompted.
        """
        from apps.accounts.permissions import requires_step_up_for_fields

        perms = super().get_permissions()
        perms.append(requires_step_up_for_fields("iban", "account_owner")())
        return perms

    def _serialize(self, member: Member) -> Response:
        # Hand-roll a "prefetch" so the read serializer doesn't run an
        # extra query per request. (Real prefetch_related needs a
        # queryset entry-point we don't have here.)
        member._prefetched_coop_shares = list(  # type: ignore[attr-defined]
            CoopShare.objects.filter(member=member)
        )
        return Response(MyMemberDataReadSerializer(member).data)

    def _resolve(self, request: Request) -> Member:
        member: Member | None = getattr(request.user, "member_profile", None)
        if member is None:
            raise MemberProfileNotLinked("No member profile linked to this user.")
        return member

    def get(self, request: Request) -> Response:
        member = self._resolve(request)
        return self._serialize(member)

    def patch(self, request: Request) -> Response:
        member = self._resolve(request)
        # Object-level step-up check: raises StepUpRequired only when a SEPA
        # field actually changes (the conditional permission compares the
        # submitted value against the stored one). APIView resolves the row
        # itself, so this must be invoked explicitly — DRF only auto-runs it
        # via a ViewSet's get_object().
        self.check_object_permissions(request, member)
        serializer = MyMemberDataUpdateSerializer(
            member, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info(
            "commissioning.my_member_data.update user=%s fields=%s tenant=%s ip=%s",
            request.user.email,
            sorted(serializer.validated_data.keys()),
            connection.schema_name,
            client_ip(request),
        )
        member.refresh_from_db()
        return self._serialize(member)


@extend_schema_view(
    get=extend_schema(
        tags=["commissioning"],
        responses={
            200: MyCustomerDataReadSerializer,
            404: ErrorResponseSerializer,
        },
    ),
    patch=extend_schema(
        tags=["commissioning"],
        request=MyCustomerDataUpdateSerializer,
        responses={
            200: MyCustomerDataReadSerializer,
            404: ErrorResponseSerializer,
        },
    ),
)
class MyCustomerDataView(APIView):
    """Self-edit surface for the authenticated Customer (Reseller).

    Resolves the target row via the ``request.user.linked_reseller``
    reverse OneToOne — same ownership-link convention as
    ``MyMemberDataView`` / ``scope_by_user_attr``. Edits land on the
    linked ``ContactEntity``; the owning ``Reseller`` row
    (customer_number, invoice_*, channel flags) stays office-only."""

    permission_classes = [IsCustomer]

    def get_permissions(self):
        """Same SEPA step-up gate as the member self-edit path.

        The customer's bank details live on the linked ``ContactEntity``
        (``iban``); changing it must require fresh re-authentication so a
        hijacked customer session can't reroute the mandate. Only fires when
        ``iban`` is actually changing.
        """
        from apps.accounts.permissions import requires_step_up_for_fields

        perms = super().get_permissions()
        perms.append(requires_step_up_for_fields("iban")())
        return perms

    def _resolve(self, request: Request) -> Reseller:
        reseller: Reseller | None = getattr(request.user, "linked_reseller", None)
        if reseller is None:
            raise CustomerProfileNotLinked("No customer profile linked to this user.")
        if reseller.contact is None:
            # Office-onboarded resellers always have a contact, but the
            # seed-fixture / future self-service flows may not. Provision
            # a blank ContactEntity lazily so the self-edit surface is
            # always usable — the user just sees empty fields and fills
            # them in.
            reseller.contact = ContactEntity.objects.create()
            reseller.save(update_fields=["contact"])
        return reseller

    def get(self, request: Request) -> Response:
        reseller = self._resolve(request)
        return Response(
            MyCustomerDataReadSerializer(
                reseller.contact, context={"reseller": reseller}
            ).data
        )

    def patch(self, request: Request) -> Response:
        reseller = self._resolve(request)
        contact = reseller.contact
        # Object-level step-up check against the ContactEntity that owns the
        # iban — raises StepUpRequired only when iban actually changes.
        self.check_object_permissions(request, contact)
        serializer = MyCustomerDataUpdateSerializer(
            contact, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info(
            "commissioning.my_customer_data.update user=%s fields=%s tenant=%s ip=%s",
            request.user.email,
            sorted(serializer.validated_data.keys()),
            connection.schema_name,
            client_ip(request),
        )
        contact.refresh_from_db()
        return Response(
            MyCustomerDataReadSerializer(contact, context={"reseller": reseller}).data
        )


class MyCoopShareSubscribeView(APIView):
    """Member self-service cooperative-share subscription ("Zeichnung").

    The authenticated member subscribes additional cooperative shares. The
    member is resolved via ``request.user.member_profile`` (same ownership-link
    convention as :class:`MyMemberDataView`), so a member can only ever
    subscribe shares for themselves. Everything authoritative is set
    server-side — ``value_one_coop_share`` comes from the current tenant
    settings, ``is_increase`` reflects whether the member already holds shares,
    and the share is created **unconfirmed** (``admin_confirmed=False``): a
    self-subscribed share does NOT count as live equity until an office user
    confirms it (``CoopShareViewSet.confirm``).

    Bounds enforcement is confirmation-status-dependent: ``CoopShare.clean()``
    only enforces the tenant min/max window for members who are ALREADY
    admin-confirmed (``_bounds_apply_to``). For a not-yet-admitted member the
    bounds are NOT checked at creation — they are validated later, when the
    office admits the member (``assert_member_total_within_bounds`` in
    ``MemberService.confirm_and_notify``) against the cumulative total.

    When the tenant has uploaded a Zeichnungsvertrag, the member must affirm
    agreement to it (``agreed_to_contract``); the agreement timestamp is
    recorded on the share.
    """

    permission_classes = [IsMember]

    @extend_schema(
        tags=["commissioning"],
        request=MyCoopShareSubscribeSerializer,
        responses={
            201: MyDataCoopShareSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        from django.db import transaction

        from ..errors import (
            ConsentDocumentNotFound,
            CoopShareContractAgreementRequired,
            CoopShareValueNotConfigured,
            MemberAlreadyCancelled,
        )
        from ..models import ConsentKind
        from ..services import ConsentService

        member: Member | None = getattr(request.user, "member_profile", None)
        if member is None:
            raise MemberProfileNotLinked("No member profile linked to this user.")
        # A member who has initiated their exit must not self-subscribe new
        # equity — that would re-introduce live coop shares for a departing
        # member. Gate on cancelled_at (exit recorded), not the possibly-future
        # cancelled_effective_at.
        if member.cancelled_at is not None:
            raise MemberAlreadyCancelled(
                "Your membership is cancelled — you can no longer subscribe shares."
            )

        serializer = MyCoopShareSubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data["amount_of_coop_shares"]
        note = serializer.validated_data.get("note") or ""
        agreed_to_contract = serializer.validated_data.get("agreed_to_contract")

        # The Zeichnungsvertrag is a first-class consent document. When one is
        # currently published (ConsentKind.COOP_CONTRACT), the member must affirm
        # agreement before subscribing — enforced here, not only in the UI — and
        # we record a versioned, hash-verified ConsentRecord as proof (DSGVO
        # Art. 7), the same way privacy/SEPA/withdrawal consents are captured.
        try:
            contract_doc = ConsentService.get_current_document(
                kind=ConsentKind.COOP_CONTRACT, locale="de"
            )
        except ConsentDocumentNotFound:
            contract_doc = None
        if contract_doc is not None and not agreed_to_contract:
            raise CoopShareContractAgreementRequired(
                "You must agree to the cooperative-share contract before "
                "subscribing."
            )

        settings = TenantSettings.get_current_settings(tenant=connection.tenant)
        value_one = settings.value_one_coop_share if settings else None
        # MEM-2/6: never persist a 0-valued share — a missing/zero tenant
        # coop-share value is a configuration error, not a silent default.
        if not value_one:
            raise CoopShareValueNotConfigured(
                "The cooperative-share value is not configured for this tenant."
            )

        # MEM-8: lock the member row so two concurrent self-subscribes can't both
        # read has_existing_shares=False and mis-stamp ``is_increase``. The
        # share + the contract ConsentRecord are written in one atomic unit.
        with transaction.atomic():
            Member.objects.select_for_update().filter(pk=member.pk).first()
            has_existing_shares = CoopShare.objects.filter(
                member=member, cancelled_at__isnull=True
            ).exists()
            coop_share = CoopShare.objects.create(
                member=member,
                amount_of_coop_shares=amount,
                value_one_coop_share=value_one,
                is_increase=has_existing_shares,
                note=note,
                # admin_confirmed stays False (default) — pending office confirmation.
            )
            if contract_doc is not None:
                ConsentService.record(
                    member=member,
                    document=contract_doc,
                    ip_address=client_ip(request) or None,
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
        logger.info(
            "commissioning.coop_share.self_subscribe member=%s amount=%s "
            "contract_consent=%s tenant=%s ip=%s",
            member.id,
            amount,
            contract_doc is not None,
            connection.schema_name,
            client_ip(request),
        )
        return Response(
            MyDataCoopShareSerializer(coop_share).data,
            status=status.HTTP_201_CREATED,
        )


class MySubscriptionSubscribeView(APIView):
    """Member self-service subscription ("Abo") creation.

    The authenticated member subscribes to a share-type variation. The member
    is resolved from ``request.user.member_profile`` (same ownership-link
    convention as :class:`MyMemberDataView`) and forced server-side, so a member
    can NEVER subscribe for another member — any ``member`` in the request body
    is ignored. ``is_trial`` is forced False and ``price_per_delivery`` is
    derived from the chosen variation; the member sets only the variation,
    quantity, payment cycle, delivery station+day and start (+ optional end)
    date. The subscription is created as a DRAFT (``admin_confirmed=False``,
    reusing the office ``create_bare_subscription`` path, which reserves its
    station-day capacity); the office confirms it through the existing abo
    confirmation flow, which materialises the deliveries.
    """

    permission_classes = [IsMember]

    @extend_schema(
        tags=["commissioning"],
        request=MySubscriptionSubscribeSerializer,
        responses={
            201: SubscriptionSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        from ..errors import MemberAlreadyCancelled
        from ..models import ShareTypeVariationGrossPrice
        from ..services import SubscriptionService

        member: Member | None = getattr(request.user, "member_profile", None)
        if member is None:
            raise MemberProfileNotLinked("No member profile linked to this user.")
        # A departing member must not self-subscribe new subscriptions (which
        # would reserve capacity + materialise into deliveries/charges on
        # confirm). Gate on cancelled_at (exit recorded).
        if member.cancelled_at is not None:
            raise MemberAlreadyCancelled(
                "Your membership is cancelled — you can no longer add subscriptions."
            )

        in_serializer = MySubscriptionSubscribeSerializer(data=request.data)
        in_serializer.is_valid(raise_exception=True)
        choice = in_serializer.validated_data

        # The variation's gross-price window effective AT THE SUBSCRIPTION'S
        # START (``valid_from``), not today — ``ShareTypeVariationGrossPrice`` is
        # time-bound and ``valid_from`` is virtually always a future Monday. A
        # today-anchored lookup would make a future-price-only variation (one the
        # member picker deliberately surfaces via ``include_future``)
        # un-subscribable, and would resolve the reference price from the wrong
        # window. A None result means the variation is unknown or has no priced
        # window covering ``valid_from``. Newest-effective-wins: the time-bound
        # window filter alone doesn't order, so pick the row with the latest
        # ``valid_from`` deterministically instead of relying on table order.
        gross_price = (
            ShareTypeVariationGrossPrice.current.active_at_date(
                choice["valid_from"].isoformat()
            )
            .filter(share_type_variation_id=choice["share_type_variation"])
            .order_by("-valid_from")
            .first()
        )
        if gross_price is None or gross_price.price_per_delivery is None:
            raise NotFoundError(
                "No active price for this share-type variation",
                code="subscription.no_active_price",
            )

        # Solidarity pricing: the member may choose their own price ONLY when the
        # tenant enables it (validated against the variation's floor by
        # SubscriptionSerializer). Otherwise the reference price is forced — the
        # member never sets their own price.
        from apps.shared.tenants.models import TenantSettings

        current_settings = TenantSettings.get_current_settings(connection.tenant)
        allows_solidarity = bool(
            current_settings and current_settings.allows_solidarity_pricing
        )
        submitted_price = choice.get("price_per_delivery")
        price_per_delivery = (
            submitted_price
            if allows_solidarity and submitted_price is not None
            else gross_price.price_per_delivery
        )

        # Authoritative fields are forced here — the member is taken from the
        # token (NOT the body), is_trial is always False, price is derived, and
        # admin_confirmed stays False (draft). Everything else goes through the
        # same SubscriptionSerializer + SubscriptionService the office uses.
        data = {
            "member": str(member.id),
            "share_type_variation": choice["share_type_variation"],
            "quantity": choice["quantity"],
            "payment_cycle": choice["payment_cycle"],
            "valid_from": choice["valid_from"],
            "valid_until": choice.get("valid_until"),
            "default_delivery_station_day": choice["default_delivery_station_day"],
            "is_trial": False,
            "price_per_delivery": str(price_per_delivery),
            # Full station-day → waiting-list entry (holds no capacity; the
            # office promotes it via the normal confirm flow).
            "on_waiting_list": bool(choice.get("on_waiting_list", False)),
        }
        sub_serializer = SubscriptionSerializer(data=data, context={"request": request})
        sub_serializer.is_valid(raise_exception=True)
        subscription = SubscriptionService().create_bare_subscription(
            sub_serializer.validated_data
        )
        logger.info(
            "commissioning.subscription.self_subscribe member=%s variation=%s "
            "tenant=%s ip=%s",
            member.id,
            choice["share_type_variation"],
            connection.schema_name,
            client_ip(request),
        )
        return Response(
            SubscriptionSerializer(subscription).data,
            status=status.HTTP_201_CREATED,
        )


class MyMembershipCancelView(APIView):
    """Member self-service membership cancellation.

    The member cancels THEIR OWN membership — resolved from
    ``request.user.member_profile`` (same ownership-link convention as
    :class:`MyMemberDataView`), so a member can never cancel anyone else.
    Gated by a restraint: they must hold no active (admin-confirmed,
    not-cancelled, not-expired) subscriptions — those have to be wound down
    first. (The office can force-cancel via ``MemberViewSet.cancel``, which
    cascades and ends the subscriptions instead of refusing.) On success it
    cascades to the member's coop shares exactly like the office path
    (``cancel_member_with_coop_shares`` snapshots each share's ``payback_due_date``).
    """

    permission_classes = [IsMember]

    @extend_schema(
        tags=["commissioning"],
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
            200: MyMemberDataReadSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        from datetime import date as _date

        from django.db.models import Q
        from django.utils import timezone

        from core.errors import BadRequestError

        from ..errors import MemberAlreadyCancelled, MemberHasActiveSubscriptions
        from ..models import Subscription
        from ..services.member_cancellation import cancel_member_with_coop_shares

        member: Member | None = getattr(request.user, "member_profile", None)
        if member is None:
            raise MemberProfileNotLinked("No member profile linked to this user.")
        if member.cancelled_at is not None:
            raise MemberAlreadyCancelled("Your membership is already cancelled.")

        # Restraint: a member may only self-cancel once they hold no active
        # subscriptions (admin-confirmed, not cancelled, not past their term).
        today = timezone.now().date()
        has_active_subscription = (
            Subscription.objects.filter(
                member=member,
                admin_confirmed=True,
                cancelled_at__isnull=True,
            )
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
            .exists()
        )
        if has_active_subscription:
            raise MemberHasActiveSubscriptions(
                "Cancel (or let expire) your active subscriptions before "
                "cancelling your membership."
            )

        effective_raw = request.data.get("effective_at")
        if not effective_raw:
            raise BadRequestError(
                "effective_at is required",
                code="member.cancel.effective_at_required",
            )
        try:
            effective = _date.fromisoformat(str(effective_raw))
        except ValueError as exc:
            raise BadRequestError(
                "effective_at must be YYYY-MM-DD",
                code="member.cancel.effective_at_format",
            ) from exc

        # A member may NOT backdate their own exit — a past effective_at would
        # rewrite the GenG Austrittsdatum and shrink the coop-share payback
        # retention window (payback_due = effective + retention_months) without
        # office review. Backdating stays an office-only prerogative
        # (MemberViewSet.cancel). Future dates are allowed (planned exit).
        if effective < today:
            raise BadRequestError(
                "effective_at cannot be in the past.",
                code="member.cancel.effective_at_in_past",
            )

        cancel_member_with_coop_shares(
            member,
            cancelled_effective_at=effective,
            cancelled_by=request.user,
            reason=request.data.get("reason"),
        )
        logger.info(
            "commissioning.membership.self_cancel member=%s effective=%s "
            "tenant=%s ip=%s",
            member.id,
            effective,
            connection.schema_name,
            client_ip(request),
        )
        # Notify the office that a member self-cancelled (best-effort,
        # post-commit) so they can review the exit + handle the payout. Only on
        # the SELF path — an office-initiated cancel needs no self-notification.
        transaction.on_commit(lambda: _notify_office_of_self_cancel(member))
        member.refresh_from_db()
        member._prefetched_coop_shares = list(  # type: ignore[attr-defined]
            CoopShare.objects.filter(member=member)
        )
        return Response(MyMemberDataReadSerializer(member).data)
